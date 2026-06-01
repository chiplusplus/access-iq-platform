# Operational Runbook

Procedures for deploying, operating, and tearing down the Access-IQ platform. All commands assume the repository root as working directory with `AWS_PROFILE` and `CDK_ENV` environment variables set.

---

## Deploy (`make up`)

Total time: 20-35 minutes. The session script (`scripts/session.sh up`) orchestrates the full sequence.

### Step 1: Trust Bootstrap (8-12 min)

Deploy the Northshire Trust CDK stack, create the EHR database, and generate synthetic data.

```bash
make up
# Or with flags:
# make up ARGS="--skip-generate"  # reuse existing data/staging/
```

The Trust stack creates: RDS Postgres (EHR + urgent care), S3 bucket (diagnostics/provider exports), SFTP via AWS Transfer Family.

### Step 2: Read Trust Outputs

The session script automatically reads CloudFormation outputs from `NorthshireTrustStack` - VPC ID, RDS endpoint, SFTP endpoint, S3 bucket name - and passes them to Platform stack deployment.

### Step 3: Deploy Platform CDK Stacks (5-10 min)

Stacks deployed in dependency order:

1. `lake` - S3 data lake bucket + KMS CMK
2. `secrets` - Secrets Manager (pseudonymisation key, Redshift password)
3. `catalog` - Glue Data Catalog database for Spectrum
4. `ecr` - Container registry for ingestion image
5. `ingestion-role` - IAM roles (ECS task, execution, Prefect worker)
6. `network` - VPC, subnets, NAT Gateway, VPC peering to Trust
7. `observability` - CloudWatch log groups, metric filters, SNS alarms, ops dashboard
8. `warehouse` - Redshift Serverless namespace + workgroup with usage limits
9. `compute` - ECS Fargate cluster, task definitions, Prefect server + worker services
10. `budget` - AWS Budgets ($10 dev / $20 prod monthly ceiling) with SNS alarm at 80% threshold; breaching the threshold triggers a Lambda that automatically destroys ephemeral stacks (compute, warehouse, network, observability, ingestion-role)

### Step 4: Redshift Pre-warm + Spectrum (30-60s)

```bash
# Automated by session script:
# 1. Poll get-workgroup until status = AVAILABLE (up to 5 min on cold start)
# 2. Run SELECT 1 to warm the serverless endpoint
# 3. Create Spectrum external schema pointing to Glue catalog
```

**Known slow path**: Redshift workgroup transitions from CREATING to AVAILABLE can take up to 5 minutes. The script polls `aws redshift-serverless get-workgroup` with backoff.

### Step 5: Trust Redeploy with VPC Routes (2 min)

Two-pass peering: Trust stack is redeployed with VPC route table entries and Security Group rules referencing the Platform VPC. This is required because peering is bidirectional and both VPCs must exist before routes can be added.

### Step 6: Seed Secrets Manager (<30s)

Platform Secrets Manager entries are seeded from Trust CloudFormation outputs: EHR DSN, SFTP credentials, Trust S3 bucket name.

### Step 7: Docker Build + Push (1-3 min)

Build the ingestion container image and push to ECR:

```bash
# Automated by session script - builds from repo root Dockerfile
# Tags: latest
```

### Step 8: Prefect Configuration (30-60s)

1. Start SSM port-forward tunnel to Prefect server (port 4200)
2. Create/update ECS work pool
3. Deploy flow definitions

**Known slow path**: Prefect tunnel retries up to 3 times with 15-second backoff. PID written to `.prefect-tunnel.pid`.

---

## Monitor

### CloudWatch Dashboard

```
https://{region}.console.aws.amazon.com/cloudwatch/home#dashboards:name=access-iq-{env}-ingestion
```

Displays: ingestion task status, error rates, Redshift query latency, ECS CPU/memory utilisation.

### Alarms

| Alarm                | Trigger                                      | Action                                                 |
| -------------------- | -------------------------------------------- | ------------------------------------------------------ |
| Ingestion failure    | Manifest `status: failed` in CloudWatch logs | SNS notification to ops topic                          |
| Budget threshold     | 80% of monthly ceiling ($10 dev / $20 prod)  | SNS notification + Lambda teardown of ephemeral stacks |
| Redshift usage limit | RPU-hours exceeded                           | Workgroup auto-pauses; `make status` reports state     |

### Prefect UI

```bash
# Accessible via SSM tunnel started by make up:
open http://localhost:4200
```

Shows: flow runs, task states, work pool health, deployment schedules.

### Quick Status Check

```bash
make status
# Reports: stack deployment state, Redshift workgroup status, ECS service counts, tunnel PIDs
```

---

## Ingest (`make ingest`)

Triggers the three ECS Fargate ingestion tasks in parallel:

```bash
make ingest
```

Behaviour:

1. Launches `ingest-postgres`, `ingest-sftp`, `ingest-trust-s3` as ECS RunTask calls
2. Polls until all tasks reach STOPPED state
3. Reports per-task exit codes (0 = success, 1 = failure)
4. Each task writes a manifest to `_manifests/source={src}/ingest_date={date}/run_id={uuid}.json`

Idempotency: if a successful manifest already exists for today's date and source, the task skips work and exits 0.

---

## Pipeline (`make pipeline`)

Runs the full daily flow via Prefect:

```bash
make pipeline
```

Sequence:

1. Opens SSM tunnel to Prefect server (if not already open)
2. Triggers: `prefect deployment run 'daily-ingest/dev'`
3. Flow execution order:
   - Ingest (3 parallel ECS tasks)
   - dbt Silver (10 models)
   - Great Expectations validation
   - dbt Gold (10 models, gated by DQ)
   - Gold Parquet export to S3
4. Logs tailed from CloudWatch log groups

---

## Additional Session Commands

| Command                | Description                                                                 |
| ---------------------- | --------------------------------------------------------------------------- |
| `make up --skip-seed`  | Infra-only deploy (no data seeding)                                         |
| `make up --skip-infra` | Reuse existing stacks (skip CDK deploy)                                     |
| `make reconnect`       | Re-establish SSM tunnels without redeploying                                |
| `make dbt CMD="..."`   | Run dbt commands through the Redshift SSM tunnel                            |
| `make dashboard`       | Run Streamlit dashboard locally                                             |
| `make profile`         | Profile Bronze data and generate data dictionary (requires live S3 session) |
| `make ready`           | Run Bronze-to-Silver readiness gate (PK uniqueness, join keys, types)       |
| `cleanup-snapshots`    | Remove stale Redshift snapshots                                             |

Session workflow notes:

- `make up` generates a `.env` file from Trust and Platform CloudFormation outputs. This file is gitignored and must be regenerated each session.
- The budget stack monitors Platform account spend only. Trust account cost controls are managed in the Trust repository.

---

## Teardown (`make down`)

Total time: 6-10 minutes.

```bash
make down
```

Sequence:

1. Kill Prefect SSM tunnel (PID from `.prefect-tunnel.pid`) and Redshift SSM tunnel (PID from `.tunnel.pid`)
2. `cdk destroy --all` Platform stacks
   - Dev: Redshift snapshot skipped, S3 auto-delete enabled
   - Prod: Timestamped final Redshift snapshot created, S3 retained
3. `cdk destroy` Trust stack

**Post-teardown verification:**

```bash
make status
# Should report: all stacks destroyed, no running ECS tasks, no active tunnels
```

---

## Incident Response

### Ingestion Failure

**Symptoms**: `make ingest` reports exit code 1 for one or more tasks. Manifest shows `status: failed`.

**Investigate**:

```bash
# Check CloudWatch logs for the failing source:
aws logs tail /access-iq/{env}/ingest-{source} --since 1h --profile $AWS_PROFILE
```

**Common causes**:

- Trust RDS not available - VPC peering not yet active or Trust stack not deployed. Fix: verify Trust stack is deployed, check Security Group rules, re-run `make ingest`.
- SFTP credentials expired or rotated - Secrets Manager entry stale. Fix: re-run Step 6 (seed secrets) from `make up`.
- S3 access denied - cross-account bucket policy not applied. Fix: verify Trust stack outputs include bucket policy grant.

### Redshift Unavailable

**Symptoms**: dbt commands fail with connection refused or timeout. `make status` shows workgroup not AVAILABLE.

**Investigate**:

```bash
aws redshift-serverless get-workgroup \
  --workgroup-name access-iq-{env} \
  --profile $AWS_PROFILE --region $REGION
```

**Common causes**:

- Cold start - workgroup transitioning from CREATING/RESUMING. Fix: wait 30-90 seconds, re-check status.
- Usage limit exceeded - RPU-hours exhausted for the day. Fix: wait until next UTC day or temporarily increase limit in CDK config.
- Workgroup deleted - `make down` was run. Fix: `make up` to redeploy.

### Dashboard Blank or Stale

**Symptoms**: Streamlit pages show no data or outdated `export_date`.

**Investigate**: Check S3 Gold export prefix for Parquet files:

```bash
aws s3 ls s3://{bucket}/gold_export/ --profile $AWS_PROFILE
```

**Common causes**:

- Pipeline hasn't run since last session - Gold export is stale or missing. Fix: `make pipeline` to run full flow and re-export.
- Export task failed - check CloudWatch logs for the export ECS task.
- IAM credentials expired - dashboard reader IAM user keys rotated. Fix: update Streamlit secrets.

### Budget Alarm Fired

**Symptoms**: SNS notification received. Ephemeral stacks may have been automatically destroyed by the teardown Lambda.

**Investigate**:

```bash
make status
# Check which stacks remain deployed
```

**Response**: The Lambda automatically destroys ephemeral stacks (compute, warehouse, network, observability, ingestion-role). Stateful stacks (lake, secrets, catalog, ecr) are retained. Redeploy with `make up` when ready to resume work.

### Prefect Tunnel Failure

**Symptoms**: `prefect` CLI commands fail with connection refused. Prefect UI at `localhost:4200` unreachable.

**Fix**:

```bash
# Kill stale tunnel process:
kill $(cat .prefect-tunnel.pid) 2>/dev/null

# Restart tunnel only (without full make up):
# The session script's Step 8 handles this, or manually:
aws ssm start-session \
  --target {ecs-task-id} \
  --document-name AWS-StartPortForwardingSession \
  --parameters '{"portNumber":["4200"],"localPortNumber":["4200"]}' \
  --profile $AWS_PROFILE --region $REGION &
echo $! > .prefect-tunnel.pid
```

### Redshift Snapshot Restore Failure

**Symptoms**: `make up` with `--restore` flag fails during warehouse stack deployment.

**Investigate**:

```bash
# List available snapshots:
aws redshift-serverless list-snapshots \
  --namespace-name access-iq-{env} \
  --profile $AWS_PROFILE --region $REGION
```

**Common causes**:

- Snapshot name mismatch - the `restore_snapshot_name` CDK context key doesn't match an existing snapshot. Fix: list snapshots and pass the correct name.
- Snapshot from different namespace - cross-namespace restore not supported. Fix: use a snapshot from the same `access-iq-{env}` namespace.

---

## Permanent Dashboard Infrastructure (One-Time Setup)

The Streamlit Community Cloud dashboard needs to read Gold Parquet files from S3 using long-lived credentials. These resources live outside the ephemeral stacks so the dashboard stays live between sessions and survives budget teardowns. Other users cloning this project do not need this — the dashboard falls back to local Parquet files.

### 1. Create the dashboard S3 bucket

```bash
aws s3api create-bucket \
  --bucket access-iq-dashboard-gold \
  --region eu-west-2 \
  --create-bucket-configuration LocationConstraint=eu-west-2 \
  --profile $AWS_PROFILE

aws s3api put-public-access-block \
  --bucket access-iq-dashboard-gold \
  --public-access-block-configuration \
    BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true \
  --profile $AWS_PROFILE
```

### 2. Create the dashboard reader IAM user

```bash
aws iam create-user --user-name access-iq-dashboard-reader --profile $AWS_PROFILE

aws iam put-user-policy \
  --user-name access-iq-dashboard-reader \
  --policy-name DashboardGoldReadOnly \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:ListBucket"],
      "Resource": [
        "arn:aws:s3:::access-iq-dashboard-gold",
        "arn:aws:s3:::access-iq-dashboard-gold/*"
      ]
    }]
  }' \
  --profile $AWS_PROFILE

aws iam create-access-key --user-name access-iq-dashboard-reader --profile $AWS_PROFILE
```

Save the `AccessKeyId` and `SecretAccessKey` from the output.

### 3. Grant Redshift UNLOAD write access

The Spectrum IAM role needs write access to the dashboard bucket so the Gold export task can UNLOAD to it:

```bash
aws iam put-role-policy \
  --role-name access-iq-dev-spectrum-role \
  --policy-name DashboardBucketWrite \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Action": ["s3:PutObject", "s3:GetBucketLocation"],
      "Resource": [
        "arn:aws:s3:::access-iq-dashboard-gold",
        "arn:aws:s3:::access-iq-dashboard-gold/*"
      ]
    }]
  }' \
  --profile $AWS_PROFILE
```

### 4. Configure the pipeline

Add to your `.env` (or set in the ECS task environment):

```bash
DASHBOARD_EXPORT_BUCKET=access-iq-dashboard-gold
```

The Gold export task writes to both the ephemeral lake bucket (KMS-encrypted, for Spectrum) and the dashboard bucket (unencrypted, for Streamlit).

### 5. Configure Streamlit Community Cloud secrets

In the Streamlit app settings, set these secrets:

```toml
PLATFORM_BUCKET = "access-iq-dashboard-gold"
AWS_ACCESS_KEY_ID = "<from step 2>"
AWS_SECRET_ACCESS_KEY = "<from step 2>"
AWS_REGION = "eu-west-2"
```
