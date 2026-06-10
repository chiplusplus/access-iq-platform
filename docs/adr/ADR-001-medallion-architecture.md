# ADR-001: Medallion Architecture (Bronze, Silver, Gold)

## Status

Accepted

## Context

The platform ingests operational healthcare data from three sources (RDS Postgres, SFTP
appointment drops, Trust S3 exports) with different schemas and quality levels. A layered
data architecture is needed to separate raw ingestion from conformed models from
business-ready analytics. Each layer must have distinct access controls and clear lineage
from source to dashboard.

## Decision

**Three-layer medallion architecture** with distinct storage, access controls, and
transformation responsibilities:

- **Bronze** -- Raw Parquet files on S3, landed by ECS ingestion tasks. Append-only (no
  updates or deletes). Partitioned by `source`, `entity`, and `ingest_date`. Read via
  Redshift Spectrum external tables through Glue Catalog (no COPY into Redshift). Access:
  ingestion role writes, Spectrum role reads.

- **Silver** -- Conformed, deduplicated, pseudonymised models in Redshift. Managed by dbt
  with incremental materialisation. Handles deduplication (via `run_id` ranking), SCD
  tracking, and pseudonymisation (NHS number replaced by `patient_sk` via `patient_identifiers`
  bridge table). Access: dbt role writes, analyst role reads.

- **Gold** -- Dimensional marts (4 fact tables + 6 dimension tables) in Redshift, exported
  to Parquet on S3 for dashboard consumption. Business logic (RTT breach calculations,
  inequality indices, utilisation rates) lives here. Small-cell suppression applied for
  statistical disclosure control. Access: dbt role writes, public read via S3 export.

Each layer boundary is enforced by dbt `ref()` -- Gold models reference Silver, Silver
models reference Bronze sources. No layer skipping.

## Consequences

- Clear lineage from source to dashboard. Every Gold metric traces back through Silver
  conformance to Bronze raw data.
- Three copies of data exist: S3 Bronze, Redshift Silver, Redshift Gold + S3 export.
  Mitigated by Spectrum (Bronze not copied into Redshift) and ephemeral Redshift (Silver
  and Gold rebuilt from Bronze on each working session).
- Bronze is the durable record. If Redshift is destroyed and redeployed, Silver and Gold
  are rebuilt from Bronze via `dbt build` -- no data loss.
- dbt `ref()` prevents accidental cross-layer dependencies, making the architecture
  self-documenting.
