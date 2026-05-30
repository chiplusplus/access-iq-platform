# ADR-009: Redshift Serverless as SQL Warehouse

## Status

Accepted

## Context

The platform needs a SQL warehouse for Silver and Gold dbt models. Requirements:

- Spectrum support (query S3 Bronze Parquet without COPY).
- Incremental materialisation via dbt-redshift adapter.
- IAM authentication (no static database passwords).
- Compatible with the ephemeral deploy/destroy pattern (`make up` / `make down`).
- Near-zero monthly cost when not in use.

## Decision

**Redshift Serverless with base capacity 8 RPU.** Specifically:

- Namespace encrypted with the same KMS CMK used for the lake bucket (ADR-0003).
- Usage limit of 4 RPU-hours per day caps runaway spend during development.
- Final snapshot on destroy uses a unix-timestamp suffix
  (`{prefix}-final-{unix_epoch}`) to avoid `SnapshotAlreadyExistsFault` -- a known
  Redshift pitfall where re-deploying after a destroy fails if the snapshot name
  collides with an existing one.
- Conditional restore: `restore_snapshot_name` passed as CDK context key (set by
  `session.sh`) enables resuming from a prior session's snapshot.
- Bronze data remains on S3, accessed via Spectrum external tables through the Glue
  Catalog. Silver and Gold are native Redshift tables rebuilt from Bronze on each session.
- Snapshot cleanup (`make cleanup-snapshots`) retains the 2 most recent snapshots and
  deletes older ones to avoid unbounded snapshot accumulation.

## Consequences

- $0 idle cost. Redshift Serverless auto-pauses when no queries are running.
- Cold-start latency of 30-90 seconds on the first query after a pause. Mitigated by a
  `SELECT 1` pre-warm query in `make up`.
- 8 RPU base capacity handles the portfolio workload (10 dbt models, ~100K rows per
  source). Production workloads would increase RPU or switch to provisioned.
- dbt-redshift adapter works with IAM auth via `GetClusterCredentials` -- no static
  passwords stored anywhere.
- `CfnUsageLimit` is absent from the CDK `aws_redshiftserverless` L2 constructs.
  Implemented via `AwsCustomResource` with `createUsageLimit` SDK call instead.

## Alternatives considered

- **Redshift Provisioned**: Minimum dc2.large costs approximately $180/month even when
  idle. Cannot pause to $0. Overkill for a portfolio workload with sporadic usage.
- **Snowflake**: Not AWS-native. Adds credential management for a separate service outside
  the AWS IAM boundary. The portfolio goal is a cohesive AWS-native stack.
- **DuckDB (local)**: No Spectrum equivalent for querying S3 Bronze. Cannot demonstrate
  IAM authentication, VPC networking, or production-shaped warehouse operations.
  Insufficient for portfolio credibility with hiring managers evaluating cloud data
  engineering skills.
- **Athena**: No native tables -- Silver and Gold require materialised tables, not
  query-time views. dbt-athena adapter is less mature than dbt-redshift. Incremental
  materialisation without Iceberg adds significant complexity.

## References

- `infra/access_iq_infra/stacks/warehouse.py` (Redshift Serverless CDK implementation)
- ADR-0003 (KMS CMK shared with lake bucket)
- PROJECT.md D-4 (Spectrum decision)
