# ADR-007: Data Quality Scope -- dbt-expectations Default + Selective Great Expectations

## Status

Accepted

## Context

The data quality layer requires a framework that (a) validates all Silver and Gold models
for structural integrity and (b) gates Gold promotion on person-level Silver data quality.

The original approach called for Great Expectations validation suites across all Silver tables.
This was narrowed: GE is scoped to high-sensitivity person-level tables only, with
dbt-expectations as the broad default layer.

## Decision

Two-layer DQ architecture:

1. **dbt-expectations (metaplane fork 0.10.x)** runs on ALL Silver + Gold models as schema tests
   in `_silver_models.yml` and `_gold_models.yml`. Covers row counts, type checks, value ranges,
   uniqueness constraints. Executes as part of `dbt test`.

2. **Great Expectations 1.x** runs on 4 person-level Silver tables ONLY: `patients`, `encounters`,
   `referrals`, `diagnoses`. These are the highest-sensitivity tables containing pseudonymised
   patient data. GE results are written to `gold._dq_results` and `s3://<lake>/_dq/<run_id>/`.
   A dbt pre-hook (`check_ge_gate`) queries `_dq_results` and aborts Gold model compilation
   if any failures exist.

### Risk-based scoping rationale

- Person-level tables (patients, encounters, referrals, diagnoses) carry highest data sensitivity and are the primary join keys for all downstream analytics
- Operational tables (appointments, urgent_care, providers, diagnostics_orders) have lower
  sensitivity and are adequately covered by dbt-expectations schema tests
- GE adds Python runtime overhead (psycopg2, boto3, GE 1.x) -- scoping to 4 tables keeps
  the DQ step fast and the dependency surface small

## Consequences

- `dbt test` catches structural issues across all models without external tooling
- GE gate adds ~30-60s to the pipeline before Gold build
- Expanding GE to more tables requires adding entries to `SILVER_TABLES` in `run_ge_gate.py`
- Gold promotion is blocked until GE passes -- no silent data quality degradation
- diagnoses validation is effectively a no-op until the simulator bug is resolved
