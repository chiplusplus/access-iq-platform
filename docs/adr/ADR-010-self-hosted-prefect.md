# ADR-010: Self-hosted Prefect 3 on ECS Fargate

## Status

Accepted (supersedes original D-2 decision for Prefect Cloud free tier)

## Context

The platform needs an orchestrator for the ingestion, dbt, data quality, and export
pipeline. The original plan (D-2 in PROJECT.md) was to use Prefect Cloud free tier with
an `ecs:push` work pool -- push pools submit ECS tasks directly without a persistent
worker process, fitting the ephemeral deploy/destroy pattern.

During Phase 7 implementation, we discovered that **Prefect Cloud free tier does not
support `ecs:push` work pools**. Only standard `ecs` work pools are available, which
require a persistent worker process polling the Cloud API. Running a persistent worker
defeats the ephemeral pattern and makes Cloud an unnecessary dependency -- the worker
already needs to run somewhere, so it can poll a local server just as easily.

## Decision

**Self-hosted Prefect 3 server on ECS Fargate with ephemeral SQLite.** Specifically:

- Prefect server runs as a session-scoped ECS service, started by `make up` and
  destroyed by `make down`. Uses the official `prefecthq/prefect:3-python3.12` image.
- Standard `ecs` work pool with a session-scoped worker service polls the server for
  scheduled flow runs and submits ECS tasks.
- **Cloud Map DNS** (`access-iq.local`) provides worker-to-server service discovery
  within the Platform VPC. The worker resolves `http://prefect-server.access-iq.local:4200`
  without hardcoded IP addresses.
- SSM port-forward tunnel exposes the Prefect UI locally for development
  (`localhost:4200` via `make prefect-ui`). Retry logic handles the ~30-second server
  startup delay.
- No persistent state -- SQLite database lives in-container and is discarded on
  teardown. Flow history is lost between sessions, which is acceptable for a portfolio
  project. Bronze S3 is the durable record of what ran and when (via manifests).
- Worker task ARN persisted to `.prefect-worker.arn` for reliable cleanup during
  `make down`.
- `PrefectWorkerRole` scoped to cluster ARN via IAM condition -- the worker can only
  submit tasks to the Access-IQ ECS cluster, not arbitrary clusters in the account.

## Consequences

- $0 idle cost. Server and worker are destroyed with `make down`. No Prefect Cloud
  subscription required.
- Flow history lost between sessions. For a portfolio project this is acceptable --
  the pipeline is demonstrably functional during a live session. Bronze manifests on S3
  provide durable run records.
- SSM tunnel adds approximately 30 seconds to `make up` with retry logic for server
  readiness.
- Separate SM lookup construct ID (`WorkerPrefectApiKeySecret`) avoids CDK synthesis
  collision with the pipeline secret.

## Alternatives considered

- **Prefect Cloud free tier**: `ecs:push` work pool is incompatible with the free tier.
  Standard `ecs` work pool requires a persistent worker, making Cloud an unnecessary
  intermediary -- the worker polls a server either way.
- **Prefect Cloud paid tier**: Minimum approximately $500/month. Absurd for a portfolio
  project with a zero-idle-cost constraint.
- **Airflow on MWAA**: Minimum $0.49/hour (~$350/month). Heavy operational overhead for
  a 4-flow pipeline. DAG authoring in Airflow is less Pythonic than Prefect's native
  task/flow decorators.
- **Step Functions**: JSON/ASL state machines. Cannot run dbt or Great Expectations
  natively -- would require Lambda wrappers for every pipeline step, adding complexity
  without benefit.
- **Dagster Cloud**: Similar push-pool limitations to Prefect Cloud. Less mature ECS
  integration. Smaller community for troubleshooting.

## References

- STATE.md (Prefect Cloud to self-hosted migration decisions)
- `flows/access_iq_flows/daily_ingest.py` (pipeline flow definition)
- `infra/access_iq_infra/stacks/compute.py` (ECS services for server and worker)
