# access-iq-platform

NHS Trust access-and-inequality analytics platform. Ingests operational healthcare
data through a Bronze/Silver/Gold medallion architecture and surfaces analytics
via a Streamlit dashboard. Two AWS accounts model a vendor-client boundary
(Trust account + Platform account); all infrastructure is CDK-managed.

## Infrastructure stacks

All stacks follow the naming convention `{kind}-{app_name}-{env_name}`.

### Stateful (RemovalPolicy.RETAIN)

| Stack                                    | Resource                                     | Notes                                                                                                          |
| ---------------------------------------- | -------------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| `lake-access-iq-{env}` (LakeStack)       | KMS CMK + S3 lake bucket                     | KMS key RETAIN in both envs; S3 bucket RETAIN in prod, DESTROY in dev. See `docs/adr/0003-kms-cmk-on-lake.md`. |
| `secrets-access-iq-{env}` (SecretsStack) | Secrets Manager pseudonymisation key         | Encrypted by the lake CMK. RETAIN avoids 7-30 day pending-deletion window.                                     |
| `catalog-access-iq-{env}` (CatalogStack) | Glue database (`access-iq-{env}-bronze`)     | Placeholder for Phase 4 `dbt-external-tables` partition registration.                                          |
| `ecr-access-iq-{env}` (EcrStack)         | ECR repository (`access-iq-{env}-ingestion`) | Immutable tags, scan-on-push, lifecycle retains last 20 untagged images.                                       |

### Stateless

| Stack                                                 | Resource                             | Notes                                                                                                 |
| ----------------------------------------------------- | ------------------------------------ | ----------------------------------------------------------------------------------------------------- |
| `ingestion-role-access-iq-{env}` (IngestionRoleStack) | IAM role for the ingestion principal | Assumed by SSO user; Phase 3 migrates to ECS task role. Scoped to `bronze/*` + `_manifests/*` writes. |

| `network-access-iq-{env}` (NetworkStack) | VPC, subnets, NAT, VPC peering, endpoints | Platform VPC peered to Trust VPC. Exports `PeeringConnectionId` for Trust-side route setup. |

ADRs: `docs/adr/0003-kms-cmk-on-lake.md` · `docs/adr/0004-12factor-config.md`

## Session workflow

The platform uses an ephemeral deploy/destroy pattern to avoid idle AWS costs.
`scripts/session.sh` orchestrates the full lifecycle across both AWS accounts.

```bash
# Prerequisites: AWS SSO sessions active for both profiles
aws sso login --profile CHI-Engineer-222308823356   # Platform account
aws sso login --profile northshire-trust             # Trust account

# Deploy everything (~20 min first run, ~15 min subsequent)
make up

# Check stack health
make status

# Tear down all resources (~8 min)
make down
```

### What `make up` does

1. **Bootstrap Trust** — deploys Trust CDK stack, creates RDS databases, generates
   100k patients + 586k encounters + supporting data, publishes to RDS/S3/SFTP
2. **Read Trust outputs** — captures Trust VPC ID from CloudFormation
3. **Deploy Platform** — deploys all 6 Platform stacks (lake, secrets, catalog, ecr,
   ingestion-role, network) with VPC peering to Trust
4. **Redeploy Trust** — adds route table entries and security group rules for the
   peering connection using Platform VPC ID and peering connection ID

### What `make down` does

1. **Destroy Platform** — tears down all 6 Platform stacks (no cross-account deps)
2. **Destroy Trust** — kills any SSM tunnel, then destroys the Trust stack

### Configuration

Environment variables (with defaults):

| Variable        | Default                      | Description                       |
| --------------- | ---------------------------- | --------------------------------- |
| `AWS_PROFILE`   | `CHI-Engineer-222308823356`  | Platform account SSO profile      |
| `TRUST_PROFILE` | `northshire-trust`           | Trust account SSO profile         |
| `CDK_ENV`       | `dev`                        | Target environment (`dev`/`prod`) |
| `REGION`        | `eu-west-2`                  | AWS region                        |
| `TRUST_REPO`    | `../northshire-hospital-sim` | Path to Trust repo                |

**First-time deploy ordering:** LakeStack → SecretsStack → CatalogStack/EcrStack → IngestionRoleStack → NetworkStack.
CDK handles this automatically via `--all`. If the dev bucket already exists from a prior SSE-S3 stack, delete it first: `aws s3 rb s3://access-iq-dev-{account_id} --force`.

## Lake layout

The platform S3 bucket (`access-iq-{env}-{account_id}`) uses a fixed prefix
contract — see `infra/access_iq_infra/lake_layout.py` for the constants.

| Prefix        | Owner                | Description                                                                                       |
| ------------- | -------------------- | ------------------------------------------------------------------------------------------------- |
| `bronze/`     | Ingestion (Phase 1+) | Raw source data. Partitioned by `source=…/entity=…/ingest_date=YYYY-MM-DD/run_id=<uuid>/`.        |
| `silver/`     | dbt (Phase 5)        | Conformed Silver tables: patients, encounters, appointments, urgent_care, diagnostics, providers. |
| `gold/`       | dbt (Phase 6)        | Marts: `fct_wait_times`, `fct_inequality`, `fct_urgent_care`, `fct_utilisation`.                  |
| `_manifests/` | Ingestion            | One JSON manifest per Bronze ingest run (idempotency + audit).                                    |
| `_dq/`        | GE (Phase 6)         | Great Expectations validation results JSON.                                                       |

All writes are SSE-KMS using the LakeStack CMK. Cross-prefix writes are blocked
by IAM (Bronze writers cannot write `silver/`; etc) — see `IngestionRoleStack`.
