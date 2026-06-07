# Access-IQ: NHS Trust Analytics Platform - Case Study

## The Problem

NHS Trusts generate vast volumes of operational data every day - electronic health records, appointment bookings, urgent care logs, diagnostic orders, provider rosters - but struggle to connect it for cross-cutting analysis. Data sits in siloed transactional systems optimised for clinical workflows, not analytical insight.

Northshire Trust (simulated) faces this pattern acutely. Patient demographics and encounter histories live in an EHR database. Daily appointment files arrive via SFTP drops. Diagnostics orders and provider exports sit in S3. Urgent care logs share the EHR database but serve a different operational team. Each system uses its own identifiers, update cadences, and quality standards.

The result: leadership cannot answer basic questions about access equity. Are waiting times equitable across deprivation quintiles? Do diagnostic turnaround times differ by ethnicity? Where do A&E four-hour breaches concentrate by geography and age? Are gaps widening or narrowing over time?

These are not speculative questions. They map directly to NHS regulatory scrutiny, NHSE operational standards (18-week RTT, 6-week diagnostics, 4-hour A&E), and the Health Inequalities Improvement Programme. But without a unified, governed data platform, answers remain anecdotal or retrospective.

Access-IQ simulates what a data engineering consultancy would build for a real Trust engagement: a full pipeline from source extraction through governed transformation to analyst-ready dimensional models and interactive dashboards.

---

## Approach

The platform uses a **two-account AWS architecture** modelling the vendor/client trust boundary. The Trust account owns the source data (RDS, SFTP, S3) inside a private VPC. The Platform account owns the analytics infrastructure - data lake, warehouse, orchestration, dashboards - in a peered VPC with controlled cross-account access.

Data flows through a **medallion architecture**: Bronze (raw Parquet in S3), Silver (conformed, pseudonymised, quality-gated in Redshift), and Gold (dimensional mart tables optimised for dashboard queries). Every transformation is version-controlled in dbt with documented lineage.

All infrastructure is **ephemeral by design**. `make up` deploys the full stack in 20-35 minutes. `make down` tears it down completely, returning to $0 idle cost. A Lambda-backed budget alarm provides a safety net — if monthly spend reaches 80% of the ceiling, ephemeral stacks are automatically destroyed.

---

## What Was Built

**Ingestion** — Three parallel ECS Fargate tasks extract data from Trust sources across a VPC peering connection. Each source (Postgres, SFTP, S3) has its own ingestion path writing to a shared Bronze contract with manifest-based idempotency. Successful runs are skipped on re-execution.

**Bronze Layer** — Append-only Parquet in S3, partitioned by source, entity, date, and run ID. Each run produces a manifest recording row counts, file sizes, and status. Serves as the immutable audit trail and the single source for all downstream processing.

**Silver Layer** — 10 dbt models conforming raw data to analytical schemas in Redshift. NHS numbers are pseudonymised via HMAC-SHA-256 through a Lambda UDF, with per-environment keys in Secrets Manager. Mod-11 checksum validation routes invalid records to a quarantine table. Patient identifiers are isolated in a restricted schema, invisible to analyst roles.

**Gold Layer** — 4 fact tables and 6 dimensions answering the headline NHS access questions. The inequality fact computes SII (Slope Index of Inequality) and RII (Relative Index of Inequality) using weighted OLS regression per the PHE/OHID methodology. Small-cell suppression protects counts below 5.

**Data Quality** — Two-layer approach: dbt-expectations tests across all models for structural integrity, plus Great Expectations validation on person-level Silver data. A DQ gate blocks Gold promotion if validation fails — quality management is enforced, not advisory.

**Orchestration** — Self-hosted Prefect 3 on ECS Fargate. The daily flow runs ingestion, Silver transforms, quality validation, Gold builds, and Parquet export in sequence. $0 idle — server and worker are destroyed with everything else on `make down`.

**Dashboard** — Streamlit Community Cloud reading static Gold Parquet exports via DuckDB. Three pages covering wait times (RTT breach analysis by cohort), inequality (SII/RII visualisation, deprivation gradients), and urgent care (4-hour/12-hour breach rates). $0/month hosting with 24/7 availability independent of whether the platform infrastructure is running.

**Observability** — CloudWatch log groups per ingestion source, metric filters for error rates, SNS alarm notifications, and an operational dashboard. Budget alarms trigger automated teardown if cost thresholds are breached.

---

## Key Decisions

Architecture decisions are documented in [9 ADRs](adr/). The table below summarises the major trade-offs.

| Decision             | Chose                                  | Over                                    | Because                                                                               | Trade-off                                        | Mitigation                                    |
| -------------------- | -------------------------------------- | --------------------------------------- | ------------------------------------------------------------------------------------- | ------------------------------------------------ | --------------------------------------------- |
| Warehouse            | Redshift Serverless                    | Snowflake, Athena                       | AWS-native, Spectrum on Bronze, $0 idle via usage limits                              | Cold-start latency 30-90s                        | Pre-warm step in deployment script            |
| Orchestrator         | Self-hosted Prefect 3                  | Prefect Cloud, Airflow MWAA             | $0 idle, Cloud free-tier incompatible with ECS push-pool, reuses Fargate cluster      | Flow history lost between sessions               | Bronze S3 manifests are the durable audit log |
| Pseudonymisation     | HMAC-SHA-256 per-env key               | Bare SHA-256, AES encryption            | Bare SHA-256 is rainbow-trivial on 10-digit NHS numbers; HMAC requires key compromise | One-way transform — cannot reverse to NHS number | By design per Caldicott principles            |
| Dashboard hosting    | Streamlit Community Cloud              | Self-hosted on ECS                      | $0/month, no Redshift dependency for availability                                     | Data freshness limited to last pipeline run      | Export date shown in sidebar                  |
| Data lake encryption | KMS CMK (customer-managed)             | SSE-S3, AWS-managed key                 | Controller holds key policy; DSPT-aligned; per-principal audit trail via CloudTrail   | KMS API cost (~$0.003/10K requests)              | S3 Bucket Key enabled to amortise calls       |
| NAT lifecycle        | Ephemeral (destroyed with `make down`) | Always-on NAT Gateway                   | $0 idle vs ~$35/month always-on                                                       | 3-5 minute recreation on `make up`               | Parallel CDK stack deployment absorbs wait    |
| IMD derivation       | Re-derived from LSOA at Gold           | Carried from Bronze `imd_decile` column | Source column unreliable; LSOA-to-IMD lookup is canonical ONS methodology             | Requires seed data maintenance                   | Seed versioned in dbt                         |
| Gold export format   | Static Parquet to S3                   | Direct Redshift queries from dashboard  | Decouples dashboard availability from warehouse uptime; enables $0 idle               | Adds export step to pipeline                     | Automated in Prefect daily flow               |

See also: [ADR-001 Medallion](adr/ADR-001-medallion-architecture.md), [ADR-003 KMS CMK](adr/ADR-003-kms-cmk-on-lake.md), [ADR-004 Ephemeral Infrastructure](adr/ADR-004-ephemeral-infrastructure.md), [ADR-005 ECS Fargate](adr/ADR-005-ecs-fargate-ingestion.md), [ADR-008 Static Gold Export](adr/ADR-008-static-gold-export.md), [ADR-009 Self-hosted Prefect](adr/ADR-009-self-hosted-prefect.md).

---

## Results

- **Pipeline**: Full ingest-to-dashboard cycle completes from a cold deploy. Three parallel ingestion tasks, 10 Silver models, 10 Gold models, automated quality gates.
- **Cost**: $0/month when stacks are destroyed. Budget Lambda enforces ceiling automatically.
- **Documentation**: 9 Architecture Decision Records, operational runbook, data flow map, asset register.
- **Quality**: dbt-expectations tests on all models. Great Expectations person-level validation. DQ gate blocks Gold promotion on failure. Quarantine table retains failed records for audit.
- **Security**: HMAC-SHA-256 pseudonymisation with per-environment keys. KMS CMK encryption at rest. IAM prefix-scoped roles. No raw NHS numbers in Silver or Gold.
- **Dashboard**: [3 interactive pages](https://access-iq-platform-h7uetia39pda9vbx3afhxl.streamlit.app/) covering wait times, inequality (SII/RII), and urgent care. Hosted at $0/month with 24/7 availability.

---

## Governance

While this is a portfolio project with synthetic data, the governance artefacts demonstrate the data protection practices expected in NHS environments. The platform is designed as if real patient data could flow through it — controls are functional, not decorative.

DSPT-aligned artefacts:

- [Data Flow Map](governance/data-flow-map.md) — traces every data hop from Trust source to dashboard with encryption, pseudonymisation, and access control annotations at each stage.
- [Asset Register](governance/asset-register.md) — catalogues all information assets by classification (Confidential, Pseudonymised, Restricted, Aggregated) with storage, encryption, and retention details.
- [Runbook](governance/runbook.md) — operational procedures for deploy, monitor, ingest, pipeline execution, teardown, and incident response.

---

## Future Work

The current platform answers the core NHS access and inequality questions. Several extensions would add predictive and operational capabilities:

- **Demand forecasting**: Prophet or ARIMA models on appointment volumes and A&E attendances to predict capacity pressure 2-4 weeks ahead.
- **Referral letter triage**: NLP classification of referral free-text to flag urgent pathways and reduce clinician triage burden.
- **Breach-rate anomaly detection**: Statistical process control on RTT and A&E breach rates to surface emerging problems before they reach regulatory thresholds.
- **Streaming ingestion**: Replace batch SFTP/S3 polling with CDC (Change Data Capture) from Trust RDS for near-real-time Silver updates.
- **Multi-Trust federation**: Generalise the two-account model to support multiple Trusts with tenant-isolated Bronze/Silver layers and a shared Gold comparison layer.
