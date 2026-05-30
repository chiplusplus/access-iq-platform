# ADR-007: ECS Fargate for Ingestion Compute

## Status

Accepted

## Context

The Access-IQ platform ingests data from three sources (RDS Postgres via `ingest-postgres`,
SFTP appointment drops via `ingest-sftp`, and Trust S3 exports via `ingest-trust-s3`). Each
runs as a CLI command dispatched by `src/access_iq/ingestion/cli.py`. The compute layer must:

- Run inside the Platform VPC with VPC peering to the Trust VPC (RDS and SFTP are private).
- Handle runs lasting 30 seconds to 5 minutes per source.
- Share a single Docker image with CLI dispatch (`python -m access_iq.ingestion.cli <command>`).
- Be triggerable by the Prefect orchestrator and by `make ingest` for manual runs.
- Cost $0 when idle (ephemeral deploy/destroy pattern).

## Decision

**ECS Fargate with one task definition per source, sharing a single ECR image.** Specifically:

- Three ECS task definitions (`ingest-postgres`, `ingest-sftp`, `ingest-trust-s3`) each
  override the container command to invoke their respective CLI subcommand.
- Tasks run in Platform VPC private subnets with VPC peering to Trust RDS and SFTP.
- Secrets injected via `valueFrom` (Secrets Manager ARNs), so credentials never appear in
  task definition plaintext. Each source gets only its required secrets: postgres gets DSN
  values, sftp gets `SFTP_*` credentials, trust-s3 gets none (IAM role-based).
- ECS task role is independent of the SSO user role, providing a distinct audit trail
  aligned with NHS DSPT controls (D-14).
- Prefect standard `ecs` work pool reuses the same Fargate cluster, so orchestrated and
  manual runs share identical infrastructure.

## Consequences

- Single image build (`make docker-build`) serves all 3 ingestion tasks and the Prefect
  pipeline. ECR push is one artifact, not three.
- ECS task role separation from SSO role means duplicate S3 permissions, but provides the
  audit boundary NHS DSPT requires (who did what: human vs. automation).
- Cold-start is approximately 30 seconds (Fargate image pull + container init). Acceptable
  for a batch workload that runs at most a few times per day.
- ECS idle cost is $0 -- Fargate charges only for running tasks. Cluster itself is free.
- Future scaling (more sources, larger tables) can add task definitions or increase task
  CPU/memory without architectural change.

## Alternatives considered

- **Lambda**: 15-minute timeout constrains large table ingestion (the `postgres.py` path
  reads full tables into memory via `SELECT *`). VPC-attached Lambda cold-starts add 5-10
  seconds. Package size limit (250 MB) is tight with pyarrow + psycopg2. Lambda cannot run
  as a Prefect worker, so orchestration would require a separate invocation pattern.
- **EC2**: Idle cost (minimum t3.micro ~$7.50/mo even when stopped for EBS). AMI maintenance
  overhead. No benefit over Fargate for a batch workload with no persistent state.
- **AWS Batch**: Additional service to configure and monitor. Fargate launch type is available
  in Batch but adds job queue and compute environment abstractions -- unnecessary complexity
  for a 3-task workload. Prefect does not have a native Batch work pool.

## References

- CLAUDE.md architecture section (ingestion CLI dispatch)
- `infra/access_iq_infra/stacks/compute.py` (ECS Fargate implementation)
- `src/access_iq/ingestion/cli.py` (CLI entry point)
