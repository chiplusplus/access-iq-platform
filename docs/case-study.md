# Access-IQ: NHS Trust Analytics Platform - Case Study

## The Problem

NHS Trusts generate vast volumes of operational data every day - electronic health records, appointment bookings, urgent care logs, diagnostic orders, provider rosters - but struggle to connect it for cross-cutting analysis. Data sits in siloed transactional systems optimised for clinical workflows, not analytical insight.

Northshire Trust (simulated) faces this pattern acutely. Patient demographics and encounter histories live in an EHR database (RDS Postgres). Daily appointment files arrive via SFTP drops. Diagnostics orders and provider exports sit in S3. Urgent care logs share the EHR database but serve a different operational team. Each system uses its own identifiers, update cadences, and quality standards.

The result: leadership cannot answer basic questions about access equity. Are waiting times equitable across deprivation quintiles? Do diagnostic turnaround times differ by ethnicity? Where do A&E four-hour breaches concentrate by geography and age? Are gaps widening or narrowing over time?

These are not speculative questions. They map directly to NHS regulatory scrutiny, NHSE operational standards (18-week RTT, 6-week diagnostics, 4-hour A&E), and the Health Inequalities Improvement Programme. But without a unified, governed data platform, answers remain anecdotal or retrospective.

Access-IQ simulates what a data engineering consultancy would build for a real Trust engagement: a full pipeline from source extraction through governed transformation to analyst-ready dimensional models and interactive dashboards.

---

## Approach

The platform uses a **two-account AWS architecture** modelling the vendor/client trust boundary. The Trust account owns the source data (RDS, SFTP, S3) inside a private VPC. The Platform account owns the analytics infrastructure - data lake, warehouse, orchestration, dashboards - in a peered VPC with controlled cross-account access.

Data flows through a **medallion architecture**: Bronze (raw, append-only Parquet in S3), Silver (conformed, pseudonymised, quality-gated in Redshift), and Gold (dimensional mart tables optimised for dashboard queries). Every transformation is version-controlled in dbt with documented lineage.

All infrastructure is **ephemeral by design**. `make up` deploys the full stack in 20-35 minutes. `make down` tears it down completely. Monthly cost when idle: $0. Active session cost: $2-5 for a 2-4 hour working session. This is achieved through CDK-managed stacks with a Lambda-backed budget teardown as a safety net.

The project was delivered across **9 phases**, each with verifiable exit criteria: networking, lake, compute, warehouse, Silver models, Gold models, orchestration, dashboard, and operational polish.

---

## What Was Built

**Ingestion** - Three ECS Fargate tasks pull data from Trust sources in parallel. `ingest-postgres` uses `SELECT *` with PyArrow conversion to Parquet. `ingest-sftp` reads appointment files via Paramiko with SHA-256 integrity checks. `ingest-trust-s3` copies diagnostics and provider exports. All three write to Bronze with a shared manifest and idempotency contract. Why: VPC-isolated, $0 idle, horizontally scalable.

**Bronze Layer** - S3 Parquet partitioned by `source/entity/ingest_date/run_id`. Each run produces an append-only manifest recording row counts, file sizes, and status. Idempotency check reads the latest manifest before work begins - successful runs are skipped. Why: auditable, immutable, cheap storage.

**Silver Layer** - 10 dbt models in Redshift conforming raw data to analytical schemas. NHS numbers are pseudonymised via HMAC-SHA-256 using a per-environment key stored in Secrets Manager, executed through a Redshift Lambda UDF. Mod-11 checksum validation routes invalid records to a quarantine table. Patient identifiers are isolated in a restricted `silver_keys` schema. Why: Caldicott-aligned - no raw NHS numbers appear in analyst-readable schemas.

**Gold Layer** - 4 fact tables (`fct_wait_times`, `fct_inequality`, `fct_urgent_care`, `fct_utilisation`) and 6 dimension tables (`dim_patient`, `dim_date`, `dim_site`, `dim_specialty`, `dim_ethnicity`, `dim_imd`). The inequality fact computes SII (Slope Index of Inequality) and RII (Relative Index of Inequality) using weighted OLS regression per the PHE/OHID methodology. Small-cell suppression protects counts below 5. Why: directly answers the headline NHS access questions with statistically rigorous inequality measurement.

**Data Quality** - dbt-expectations tests across all Silver and Gold models. Great Expectations validation suites on person-level Silver data. A DQ gate macro blocks Gold promotion if validation fails. Why: production-shaped quality management, not decorative.

**Orchestration** - Self-hosted Prefect 3 on ECS Fargate. The daily flow runs: ingest (parallel) -> dbt Silver -> GE validation -> dbt Gold -> Gold export. Cloud Map DNS provides worker-to-server discovery. SSM port-forwarding exposes the Prefect UI locally. Why: $0 idle, reuses the existing Fargate cluster, no vendor lock-in.

**Dashboard** - Streamlit Community Cloud reading static Gold Parquet exports via DuckDB. Three pages: Wait Times (RTT breach analysis, median/P90 by cohort), Inequality (SII/RII visualisation, deprivation gradient charts), and Urgent Care (4-hour/12-hour breach rates, triage-to-clinician times). Why: $0/month hosting, no Redshift dependency, 24/7 portfolio availability.

**Observability** - CloudWatch log groups per ingestion source, metric filters for error rates, SNS alarm notifications, and an operational dashboard. Budget alarms at 80% of monthly ceiling trigger a Lambda that destroys ephemeral stacks. Why: production-shaped ops posture.

---

## Key Decisions

Architecture decisions are documented in [13 ADRs](adr/). The table below summarises the major trade-offs.

| Decision             | Chose                                  | Over                                    | Because                                                                               | Trade-off                                        | Mitigation                                                        |
| -------------------- | -------------------------------------- | --------------------------------------- | ------------------------------------------------------------------------------------- | ------------------------------------------------ | ----------------------------------------------------------------- |
| Warehouse            | Redshift Serverless                    | Snowflake, Athena                       | AWS-native, Spectrum on Bronze, $0 idle via usage limits, dbt-redshift mature         | Cold-start latency 30-90s                        | Pre-warm `SELECT 1` in `make up`                                  |
| Orchestrator         | Self-hosted Prefect 3                  | Prefect Cloud, Airflow MWAA             | $0 idle, push-pool free-tier incompatible with ECS, reuses Fargate cluster            | Flow history lost between sessions               | Bronze S3 manifests are the durable audit log                     |
| Pseudonymisation     | HMAC-SHA-256 per-env key               | Bare SHA-256, AES encryption            | Bare SHA-256 is rainbow-trivial on 10-digit NHS numbers; HMAC requires key compromise | One-way transform - cannot reverse to NHS number | By design per Caldicott principles                                |
| Dashboard hosting    | Streamlit Community Cloud              | Self-hosted on ECS                      | $0/month, no auth needed (synthetic data), no Redshift dependency for availability    | Data freshness limited to last pipeline run      | `export_date` shown in sidebar; re-run `make pipeline` to refresh |
| Data lake encryption | KMS CMK (customer-managed)             | SSE-S3, aws/s3 managed key              | Controller holds key policy; DSPT-aligned; supports key rotation                      | KMS API cost (~$0.003/10K requests)              | S3 Bucket Key enabled to amortise calls                           |
| NAT lifecycle        | Ephemeral (destroyed with `make down`) | Always-on NAT Gateway                   | $0 idle vs ~$32/month always-on                                                       | 3-5 minute recreation on `make up`               | Parallel CDK stack deployment absorbs wait                        |
| IMD derivation       | Re-derived from LSOA at Gold           | Carried from Bronze `imd_decile` column | Source column unreliable; LSOA-to-IMD lookup is canonical ONS methodology             | Requires seed data maintenance                   | `lsoa_imd_lookup` seed versioned in dbt                           |
| Gold export format   | Static Parquet to S3                   | Direct Redshift queries from dashboard  | Decouples dashboard availability from warehouse uptime; enables $0 idle               | Adds export step to pipeline                     | Automated in Prefect daily flow                                   |

See also: [ADR-007 ECS Fargate](adr/ADR-007-ecs-fargate-ingestion.md), [ADR-008 Medallion](adr/ADR-008-medallion-architecture.md), [ADR-009 Redshift](adr/ADR-009-redshift-serverless.md), [ADR-010 Prefect](adr/ADR-010-self-hosted-prefect.md), [ADR-011 Static Gold Export](adr/ADR-011-static-gold-export.md), [ADR-012 NAT Ephemeral](adr/ADR-012-nat-ephemeral.md), [ADR-015 Two-Account Boundary](adr/ADR-015-two-account-staging.md).

---

## Results

The platform delivers end-to-end pipeline execution: Trust source data flows through Bronze ingestion, Silver transformation with pseudonymisation and quality gates, Gold dimensional modelling, Parquet export, and dashboard visualisation.

- **Pipeline**: Full ingest-to-dashboard cycle completes from a deployed state. Three parallel ingestion tasks, 10 Silver models, 10 Gold models, automated quality gates.
- **Cost**: $0/month when stacks are destroyed. ~$2-5 for a 2-4 hour active working session. Budget Lambda enforces ceiling automatically.
- **Documentation**: 13 Architecture Decision Records, operational runbook, data flow map, asset register, engagement context documents.
- **Quality**: dbt-expectations tests on all models. Great Expectations person-level validation. DQ gate blocks Gold promotion on failure. Quarantine table retains failed records for audit.
- **Security**: HMAC-SHA-256 pseudonymisation with per-environment keys. KMS CMK encryption at rest. IAM prefix-scoped roles. No raw NHS numbers in Silver or Gold.
- **Dashboard**: 3 pages covering wait times, inequality (SII/RII), and urgent care. Hosted on Streamlit Community Cloud at $0/month with 24/7 availability.

---

## Governance

While this is a portfolio project with synthetic data, the governance artefacts demonstrate the data protection practices expected in NHS environments. The platform is designed as if real patient data could flow through it - controls are functional, not decorative.

DSPT-aligned artefacts:

- [Data Flow Map](governance/data-flow-map.md) - traces every data hop from Trust source to dashboard with encryption, pseudonymisation, and access control annotations at each stage.
- [Asset Register](governance/asset-register.md) - catalogues all information assets by classification (Confidential, Pseudonymised, Restricted, Aggregated) with storage, encryption, and retention details.
- [Runbook](governance/runbook.md) - operational procedures for deploy, monitor, ingest, pipeline execution, teardown, and incident response.

See also: [Pseudonymisation Method](security/pseudonymisation.md) for detailed HMAC-SHA-256 rationale and key management.

---

## Future Work

The current platform answers the core NHS access and inequality questions. Several extensions would add predictive and operational capabilities:

- **Demand forecasting**: Prophet or ARIMA models on appointment volumes and A&E attendances to predict capacity pressure 2-4 weeks ahead.
- **Referral letter triage**: NLP classification of referral free-text to flag urgent pathways and reduce clinician triage burden.
- **Breach-rate anomaly detection**: Statistical process control on RTT and A&E breach rates to surface emerging problems before they reach regulatory thresholds.
- **Streaming ingestion**: Replace batch SFTP/S3 polling with CDC (Change Data Capture) from Trust RDS for near-real-time Silver updates.
- **Multi-Trust federation**: Generalise the two-account model to support multiple Trusts with tenant-isolated Bronze/Silver layers and a shared Gold comparison layer.
- **Authentication**: Add Cognito or NHS Care Identity Service integration if the platform were to handle real patient data, replacing the current open-access dashboard model.
