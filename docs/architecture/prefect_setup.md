# Prefect Cloud Setup

The pipeline orchestration layer uses Prefect Cloud (free tier) with standard `ecs` work pools and a session-scoped Prefect worker running as a lightweight Fargate task (256 CPU / 512 MB, ~$0.01/hour).

## How It Works

1. `make up` (Step 9/9) creates the `access-iq-{env}-pipeline` work pool with `--type ecs`
2. After pool creation and flow deployment, `make up` launches a Prefect worker as a Fargate task
3. The worker polls Prefect Cloud for scheduled/triggered runs
4. When a run is triggered, the worker launches the pipeline task (1024 CPU / 2048 MB) via the ECS API
5. `make down` (Step 1/3) stops the worker Fargate task before destroying stacks

The worker only runs during active sessions. No compute runs between `make down` and the next `make up`. The worker task ARN is saved to `.prefect-worker.arn` for reliable cleanup.

## Prerequisites

- AWS CLI configured with the platform account profile
- Deployed platform stacks (`make infra-deploy`)

## 1. Create a Prefect Cloud Account

1. Sign up at [app.prefect.cloud](https://app.prefect.cloud)
2. A default workspace is created automatically
3. Note the **account ID** and **workspace ID** from the URL:
   ```
   app.prefect.cloud/account/<ACCOUNT_ID>/workspace/<WORKSPACE_ID>
   ```

## 2. Generate an API Key

1. Go to **Account Settings > API Keys**
2. Create a new key (name it `access-iq-dev` or similar)
3. Copy the key -- it won't be shown again

## 3. Store the API Key in Secrets Manager

```bash
aws secretsmanager create-secret \
  --name "access-iq/dev/prefect-api-key" \
  --secret-string "<YOUR_API_KEY>" \
  --profile access-iq-dev \
  --region eu-west-2
```

For prod, replace `dev` with `prod` in both the secret name and profile.

## 4. Set Environment Variables

Add to your `.env` (see `.env.example`):

```bash
PREFECT_ACCOUNT_ID=<account-id-from-url>
PREFECT_WORKSPACE_ID=<workspace-id-from-url>
```

## 5. Deploy

Run `make up`. Step 9/9 will:

1. Read the API key from Secrets Manager
2. Create the `access-iq-dev-pipeline` work pool (type `ecs`, idempotent)
3. Resolve CDK stack outputs (cluster ARN, task/execution role ARNs, image URI)
4. Update the work pool job template with those values
5. Deploy the `daily-ingest/dev` flow definition from `flows/prefect.yaml`
6. Resume the cron schedule
7. Start a Prefect worker Fargate task (256/512) that polls for runs
8. Save the worker task ARN to `.prefect-worker.arn`

If the API key is not found, step 9/9 is skipped gracefully with a warning.

## Verify

```bash
prefect cloud login --key $PREFECT_API_KEY \
  --workspace $PREFECT_ACCOUNT_ID/$PREFECT_WORKSPACE_ID

prefect work-pool ls                          # should show access-iq-dev-pipeline (type: ecs)
prefect deployment inspect 'daily-ingest/dev' # should show cron + ecs config
```

## Trigger a Pipeline Run

```bash
make pipeline
```

This reads the API key from Secrets Manager and runs `prefect deployment run 'daily-ingest/dev'`.
