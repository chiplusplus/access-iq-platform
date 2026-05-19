# Access-IQ Roadmap

**Milestone:** v1 — end-to-end NHS-Trust analytics platform
**Granularity:** standard
**Phases:** 9
**Coverage:** 22/22 Active REQ-* mapped (no orphans)

Brownfield. Bronze ingestion (postgres / sftp / trust_s3) already shipped against the Northshire Trust simulator (`https://github.com/chiplusplus/northshire-hospital-sim`). Everything Silver-onward is greenfield. Roadmap reflects locked decisions D1–D9 in `PROJECT.md`. Each phase exits on a 5-minute reviewer click-through demo gate.

## Phases

- [x] **Phase 1: Stateful Foundations & Brownfield Hardening** — Split stateful from ephemeral; fix Bronze correctness debt; uv workspace; pseudonymisation primitive
- [ ] **Phase 2: Networking** — Platform VPC, peering to Trust, gateway/interface endpoints, NAT toggle
- [ ] **Phase 3: ECS Fargate Ingestion + Observability** — Run shipped Bronze ingestion on Fargate with CloudWatch alarms + ops dashboard
- [ ] **Phase 4: Redshift Serverless + dbt Scaffold** — Warehouse online, Bronze surfaced via Spectrum, dbt project deployable
- [ ] **Phase 5: Silver Staging** — Conformed Silver models for the six core entities, NHS-number Mod-11 + HMAC pseudonymisation
- [ ] **Phase 6: Gold Marts + Data Quality** — Four Gold marts (wait_times, inequality, urgent_care, utilisation) with selective GE + dbt-expectations
- [ ] **Phase 7: Prefect Orchestration** — Prefect Cloud `ecs:push` flow chains ingestion → dbt → DQ → Gold export
- [ ] **Phase 8: Streamlit Dashboard (Static Gold Export)** — Three-page Streamlit Community Cloud app reading exported Parquet on S3
- [ ] **Phase 9: Ops Polish, ADRs, Case Study** — `make up/down/ingest`, ADRs, README + case study, cost ceiling

## Phase Details

### Phase 1: Stateful Foundations & Brownfield Hardening
**Goal**: Stateful AWS resources are isolated under retain policies and the existing Bronze ingestion is correct, observable, and packaged for ECS — so every later phase builds on a clean foundation rather than compounding silent debt.
**Depends on**: Nothing (first phase)
**Requirements**: REQ-NET-03 (lake-layout portion)
**Success Criteria** (what must be TRUE):
  1. Reviewer can `cdk synth` both `dev` and `prod` cleanly — `infra/config/prod.json` no longer crashes on missing `user_name`/`s3`/`iam`.
  2. Stateful resources (S3 lake, KMS CMK, Secrets, Glue Catalog placeholder, ECR) live in retain-policy stacks; running `cdk destroy` on stateless stacks leaves them intact.
  3. Lake bucket is encrypted with a KMS CMK (per env) — SSE-S3 is gone; bucket layout (`bronze/`, `silver/`, `gold/`, `_manifests/`) is documented.
  4. Bronze ingestion correctness bugs from `CONCERNS.md` are fixed and covered by tests: postgres `error` accumulation, `trust_s3` empty-result idempotency poisoning, manifest prefix trailing-`/`, manifest schema (`error: list` vs `str`) unified across all three sources.
  5. `access_iq.security.pseudonymise` exposes HMAC-SHA-256 with per-env key in Secrets Manager (D9); unit-tested; CLI `cwd` contract wrapped so the package runs from any working directory; `print()` calls converted to `structlog` JSON.
  6. uv workspace split (D8) lands: `ingestion`, `dbt-runner`, `prefect-flows`, `streamlit-app`, `infra` resolve independently with no transitive-dep conflicts.
**Plans**: 6 plans
- [ ] 01-01-PLAN.md — uv workspace restructure (D8): root pyproject becomes workspace; ingestion/infra/dbt/flows/dashboard members
- [ ] 01-02-PLAN.md — 12-factor config (Pydantic Settings), delete runtime config tree, fix prod CDK config, ADR 0004
- [ ] 01-03-PLAN.md — Bronze brownfield bug fixes + unified Manifest schema + structlog conversion
- [ ] 01-04-PLAN.md — LakeStack (KMS CMK + S3 + bucket policy) + lake_layout (REQ-NET-03) + ADR 0003; retire PlatformBucketStack
- [ ] 01-05-PLAN.md — SecretsStack (RETAIN) + HMAC-SHA-256 pseudonymisation primitive (D9) + method doc
- [ ] 01-06-PLAN.md — CatalogStack + EcrStack + app.py wiring + README lake-layout docs + cdk synth gate (dev+prod)

### Phase 2: Networking
**Goal**: A reviewer can deploy the Platform VPC and peer it to the Trust VPC such that ingestion compute (next phase) reaches RDS, Trust S3, and Transfer Family over private routes with deny-by-default security groups — and tear it back down to zero idle cost.
**Depends on**: Phase 1
**Requirements**: REQ-NET-01, REQ-NET-02, REQ-NET-03 (endpoints portion)
**Success Criteria** (what must be TRUE):
  1. Platform VPC exists with public + private subnets across two AZs and a single NAT gateway in dev; CIDRs match D1 (Trust `10.0.0.0/16`, Platform `10.10.0.0/16`) and are committed to `infra/config/{dev,prod}.json`.
  2. VPC peering connection between Platform and Trust is `ACTIVE`; route tables on both sides forward the peer CIDR; cross-VPC DNS resolution is enabled both sides via `AwsCustomResource` (CDK does not expose `AllowDnsResolutionFromRemoteVpc`).
  3. From a Platform private subnet, a debug task can `psql` to the Trust RDS endpoint by hostname (proves DNS + routing + SG rules); from the Trust side, no inbound to Platform is permitted.
  4. S3 gateway VPC endpoint is attached so Bronze writes do not traverse NAT; Secrets Manager and KMS interface endpoints exist for ECS `valueFrom` lookups.
  5. NAT gateway is part of the ephemeral stack (D6) — `cdk destroy` of stateless stacks removes it, leaving zero NAT idle cost.
**Plans**: 2 plans
- [ ] 02-01-PLAN.md — Extend EnvConfig with vpc field + update config files (D1 CIDRs, trust_account_id) + fix all test _cfg() helpers
- [ ] 02-02-PLAN.md — NetworkStack (VPC, peering, routes, DNS, security groups, VPC endpoints) + tests + app.py wiring

### Phase 3: ECS Fargate Ingestion + Observability
**Goal**: A reviewer can trigger any of the three Bronze ingestion flows on ECS Fargate against the Trust simulator, watch the run in a CloudWatch dashboard, and receive an SNS alert if a manifest writes `status: failed`.
**Depends on**: Phase 1, Phase 2
**Requirements**: REQ-ECS-01, REQ-OBS-01, REQ-OBS-02
**Success Criteria** (what must be TRUE):
  1. One ECR image builds from the `ingestion` workspace and is reused by three ECS task definitions (`ingest-postgres`, `ingest-sftp`, `ingest-trust-s3`); secrets are injected via `valueFrom` only — no plaintext env.
  2. Task role is the existing `IngestionRoleStack` pattern (read external Trust bucket, write `bronze/*` + `_manifests/*`); execution role is separate and minimal.
  3. Running `aws ecs run-task` for any of the three tasks completes successfully end-to-end against the live Trust simulator and produces a Bronze manifest with `status: "success"`.
  4. CloudWatch log groups exist per task with structlog-JSON parsed; metric filter on `"status":"failed"` triggers an SNS-subscribed alarm; alarm has been verified by force-failing a run.
  5. CloudWatch operational dashboard shows per-source ingestion runs (last 24h), latest manifest status, and pipeline lag (now − latest successful ingest_date) — visible from one URL.
  6. Trust-side Transfer Family is owned by the Northshire simulator (D7); access-iq is consumer only — no AWS Transfer Family resource appears in any Platform stack.
**Plans**: TBD

### Phase 4: Redshift Serverless + dbt Scaffold
**Goal**: A reviewer can `make up`, see Redshift Serverless online inside the Platform VPC, query Bronze through Spectrum without copying data, and run `dbt build` against an empty-but-deployable project — then `make down` and snapshot-restore on the next session.
**Depends on**: Phase 2, Phase 3
**Requirements**: REQ-WH-01, REQ-DBT-01
**Success Criteria** (what must be TRUE):
  1. Redshift Serverless workgroup + namespace deploy into Platform VPC private subnets with KMS CMK, IAM auth via `GetClusterCredentials`, audit logging on, and a daily RPU-hour usage limit (e.g. 4) capping runaway spend.
  2. Pre-destroy snapshot custom resource fires on `cdk destroy`; restore-on-up script (idempotent) brings the namespace back from latest snapshot — verified by a destroy/recreate round-trip preserving a marker table.
  3. Glue Catalog database registers Bronze partitions; `dbt-external-tables` macro creates Spectrum external tables for the six entities; `select count(*) from bronze_external.patients` returns the expected row count without any COPY (D4).
  4. `dbt-runner` workspace contains a deployable dbt project with environment-aware profiles (dev/prod), seeds for `dim_imd`, ICD-10, and 16+1 ethnicity, and a CI hook that runs `dbt parse` + `dbt compile` on every PR.
  5. Pre-warm helper (`SELECT 1`) is part of `make up` so cold-start latency does not bite the demo loop.
**Plans**: TBD

### Phase 5: Silver Staging
**Goal**: A reviewer can run `dbt build --select silver` and see six conformed Silver tables — patients (with HMAC pseudonymised `patient_sk`), encounters, appointments, urgent_care, diagnostics, providers — that align with the Northshire simulator schema and quarantine bad NHS numbers rather than dropping them.
**Depends on**: Phase 4
**Requirements**: REQ-SILVER-01
**Success Criteria** (what must be TRUE):
  1. Silver models for `patients`, `encounters`, `appointments`, `urgent_care`, `diagnostics`, `providers` exist as native incremental Redshift tables (D4) with explicit column lists matching `sql/ehr/init.sql` and `sql/urgent_care/init.sql` in the Northshire simulator.
  2. `patient_sk` is HMAC-SHA-256 of NHS number using the per-env Secrets-Manager key (D9, Phase 1 utility); raw NHS number never appears in Silver.
  3. NHS-number Mod-11 checksum is enforced; rows failing checksum are routed to `silver_quarantine.*` (not dropped); `varchar(10)` end-to-end.
  4. All timestamps are `timestamptz` UTC, converted from Europe/London on the Trust side; de-dup is idempotent across re-runs.
  5. Caldicott-aligned column allow-lists keep direct identifiers out of analyst-readable schemas; a `_keys` schema isolates linkable identifiers behind tighter grants.
  6. dbt source freshness + `not_null`/`unique` tests pass on every Silver model in CI.
**Plans**: TBD

### Phase 6: Gold Marts + Data Quality
**Goal**: A reviewer can run `dbt build --select gold` and produce four Gold marts that answer the headline access + inequality questions, with DQ that blocks promotion on person-level Silver failures and publishes results to the observability dashboard.
**Depends on**: Phase 5
**Requirements**: REQ-GOLD-WT-01, REQ-GOLD-INEQ-01, REQ-GOLD-UC-01, REQ-GOLD-UTIL-01, REQ-DQ-01, REQ-DQ-02
**Success Criteria** (what must be TRUE):
  1. `gold.fct_wait_times` exposes RTT (referral-to-treatment), A&E breaches, and DM01 diagnostics waits at pathway × snapshot-month grain with documented grain comment + `unique_combination_of_columns` test.
  2. `gold.fct_inequality` is long-form (metric × period × stratifier × stratum) sliced by IMD decile, age band, ethnicity (16+1 / ONS), and gender; small-cell suppression (<5–10) is applied; SII/RII helper macro available.
  3. `gold.fct_urgent_care` covers attendances, 4-hour and 12-hour breaches, and conversion-to-admission at per-attendance grain.
  4. `gold.fct_utilisation` covers provider/clinic capacity and DNA rates at per-appointment grain.
  5. Conformed dims (`dim_patient` SCD2, `dim_date`, `dim_specialty`, `dim_site`, `dim_commissioner`, `dim_imd`, `dim_ethnicity`) are in place; large facts have distkey `patient_sk` / sortkey `event_ts`.
  6. dbt-expectations runs across all Silver + Gold models; Great Expectations 1.x runs only on person-level Silver tables (D3 softening of REQ-DQ-01) and blocks Gold promotion on failure; ADR `dq-scope` documents the scope decision.
  7. GE results JSON is published to `s3://<lake>/_dq/<run_id>/` and surfaced as a panel on the Phase 3 CloudWatch dashboard (REQ-DQ-02).
**Plans**: TBD

### Phase 7: Prefect Orchestration
**Goal**: A reviewer can hit `make ingest` (or wait for the cron) and watch a single Prefect flow drive Bronze ingest → dbt build → DQ → Gold export end-to-end on `ecs:push`, with retries, alerting, and a single log destination — no Prefect worker running between sessions.
**Depends on**: Phase 3, Phase 6
**Requirements**: REQ-ORCH-01
**Success Criteria** (what must be TRUE):
  1. Prefect Cloud free-tier workspace is configured (D2); `ecs:push` work pool is bound to the Phase 3 ECS cluster and IAM role; no self-hosted Prefect metadata DB exists.
  2. `daily_ingest` flow runs the three ingestion tasks in parallel, then `dbt build --select silver`, then GE validation, then `dbt build --select gold`, then the static Gold export task (used by Phase 8) — failures at any node alert via the Phase 3 SNS topic.
  3. Flow is schedulable on cron (02:00 Europe/London) and triggerable on demand via `make ingest`; AwsCredentials/AwsSecret blocks resolve from Secrets Manager.
  4. Tenacity-style retries cover IAM eventual-consistency on first task launch and transient Redshift cold-starts.
  5. All flow + task logs land in a single CloudWatch log group already wired to the ops dashboard.
**Plans**: TBD
**Research flag**: deeper research needed on Prefect 3 `ecs:push` work-pool semantics and free-tier concurrency limits before plan-phase.

### Phase 8: Streamlit Dashboard (Static Gold Export)
**Goal**: A reviewer can open a Streamlit Community Cloud URL — without auth, no Redshift required — and complete a 5-minute click-through across Wait Times, Inequality, and Urgent Care, with all data sourced from a Parquet export of the Gold layer on S3 (D5).
**Depends on**: Phase 6, Phase 7
**Requirements**: REQ-DASH-01, REQ-DASH-02, REQ-DASH-03
**Success Criteria** (what must be TRUE):
  1. Prefect Phase 7 flow ends with a Gold-export task that writes Parquet for each of the four Gold marts to a public-read prefix `s3://<public-export>/gold/` (or DuckDB-readable layout); export is idempotent per `run_id`.
  2. Streamlit app in the `streamlit-app` workspace deploys to Streamlit Community Cloud and reads exclusively from that S3 prefix (DuckDB-on-S3 or `pyarrow.fs`) — no live Redshift connection, no Cognito, no ALB.
  3. Three pages render: **Wait Times** (RTT 18-week %, 52-week+ waiters, DM01 6-week %), **Inequality** (Core20PLUS5-style stratification by IMD decile + ethnicity + age band + gender, with SII/RII overlay), **Urgent Care** (4h/12h breaches, conversion-to-admission), and the equity overlay toggle works on the Urgent Care page.
  4. Dashboard reads only from Gold (REQ-DASH-02 amended per D5: from S3-exported Gold, not live Redshift) — no Silver/Bronze paths exist in the app code.
  5. `st.cache_data(ttl=3600)` masks S3 fetch latency; small-cell suppression carried through from Phase 6.
  6. Streamlit Community Cloud cost ≈ free tier; static export object storage is the only ongoing cost (~$1/mo).
**Plans**: TBD
**UI hint**: yes

### Phase 9: Ops Polish, ADRs, Case Study
**Goal**: A reviewer can clone the repo, read a coherent case study + ADRs, run `make up` to deploy and seed, watch the demo loop, run `make down` to return to zero idle, and trust that the cost ceiling holds — i.e. the project is portfolio-ready.
**Depends on**: Phase 1–8
**Requirements**: REQ-SEED-01, REQ-OPS-01, REQ-DOC-01, REQ-DOC-02
**Success Criteria** (what must be TRUE):
  1. `make up` deploys ephemeral stacks, restores Redshift from snapshot, pre-warms the warehouse, seeds the Trust simulator (REQ-SEED-01 lives in `northshire-hospital-sim` — access-iq invokes its seed CLI), and emits the Streamlit URL — all in one command.
  2. `make down` snapshots Redshift, destroys all ephemeral stacks (including NAT), and verifies stateful retain-stacks remain — confirmed by a post-destroy `aws s3 ls` + secrets check (REQ-OPS-01).
  3. `make ingest` triggers the Phase 7 Prefect flow on demand and tails its logs.
  4. ADRs (REQ-DOC-01) cover the nine locked decisions: warehouse choice, orchestrator choice, DQ-scope softening (D3), Spectrum-on-Bronze (D4), dashboard static-export (D5), NAT survival (D6), Trust-side SFTP (D7), uv workspace (D8), pseudonymisation method (D9), plus two-account staging.
  5. README walks a reviewer from clone → demo URL in under 15 minutes; written case study (REQ-DOC-02) covers problem framing, approach, trade-offs, screenshots, architecture diagrams, and DSPT-shaped artefacts (asset register, data-flow map, runbook, RPO doc) suitable for a hiring-manager audience.
  6. Monthly cost ceiling is enforced by a Budgets alarm + auto-tear-down Lambda; ~2% bad-row injection in seed data is documented; demo loop completes inside 5 minutes from a fresh `make up`.
**Plans**: TBD
**Research flag**: deeper research needed on Redshift Serverless snapshot/restore automation edges (custom-resource lifecycle on stack destroy, restore idempotency).

## Coverage Validation

Every Active REQ in `PROJECT.md` maps to exactly one phase. No orphans, no duplicates.

| Requirement | Phase | Notes |
|-------------|-------|-------|
| REQ-NET-01 | Phase 2 | VPC + 2 AZ subnets + NAT |
| REQ-NET-02 | Phase 2 | Peering + cross-VPC DNS custom resource |
| REQ-NET-03 | Phase 1 (lake layout) + Phase 2 (S3 endpoint) | Split across foundations and networking |
| REQ-ECS-01 | Phase 3 | Fargate task defs reusing IngestionRoleStack |
| REQ-OBS-01 | Phase 3 | Log groups, metric filters, SNS alarms |
| REQ-OBS-02 | Phase 3 | Operational CloudWatch dashboard |
| REQ-WH-01 | Phase 4 | Redshift Serverless + KMS + usage limit |
| REQ-DBT-01 | Phase 4 | dbt project + profiles + CI hook |
| REQ-SILVER-01 | Phase 5 | Six conformed Silver staging models |
| REQ-GOLD-WT-01 | Phase 6 | `gold.fct_wait_times` |
| REQ-GOLD-INEQ-01 | Phase 6 | `gold.fct_inequality` |
| REQ-GOLD-UC-01 | Phase 6 | `gold.fct_urgent_care` |
| REQ-GOLD-UTIL-01 | Phase 6 | `gold.fct_utilisation` |
| REQ-DQ-01 | Phase 6 | Softened per D3 (selective GE + dbt-expectations); ADR required |
| REQ-DQ-02 | Phase 6 | GE results to S3 + obs dashboard panel |
| REQ-ORCH-01 | Phase 7 | Prefect Cloud `ecs:push` flow |
| REQ-DASH-01 | Phase 8 | Three pages |
| REQ-DASH-02 | Phase 8 | Amended per D5: reads from S3-exported Gold |
| REQ-DASH-03 | Phase 8 | Static Gold export to public-read S3 prefix |
| REQ-SEED-01 | Phase 9 | Invoked from Northshire simulator via `make up` |
| REQ-OPS-01 | Phase 9 | `make up/down/ingest` |
| REQ-DOC-01 | Phase 9 | ADRs |
| REQ-DOC-02 | Phase 9 | README + case study |

**Coverage:** 22/22 Active REQ-* mapped. No phase delivers anything that is not requested by an Active REQ or by a locked decision (D1–D9).

## Decision Reflections

| Decision | Where it lands |
|----------|----------------|
| D1 VPC CIDRs | Phase 2 (committed to `infra/config/{dev,prod}.json` before peering work) |
| D2 Prefect Cloud free tier + `ecs:push` | Phase 7 |
| D3 DQ softening | Phase 6 (REQ-DQ-01 amended; ADR in Phase 9) |
| D4 Spectrum on Bronze, native incremental Silver/Gold | Phase 4 (Spectrum), Phase 5 (Silver), Phase 6 (Gold) |
| D5 Static Gold export → Streamlit Community Cloud | Phase 7 (export task) + Phase 8 (consumer); REQ-DASH-02 amended |
| D6 NAT destroyed with ephemeral stack | Phase 2 |
| D7 SFTP is Trust-side only | Phase 3 (no Transfer Family in Platform) |
| D8 uv workspace split | Phase 1 |
| D9 HMAC-SHA-256 pseudonymisation | Phase 1 (utility) → Phase 5 (applied) |

## Progress

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Stateful Foundations & Brownfield Hardening | 0/0 | Not started | - |
| 2. Networking | 0/2 | Planned | - |
| 3. ECS Fargate Ingestion + Observability | 0/0 | Not started | - |
| 4. Redshift Serverless + dbt Scaffold | 0/0 | Not started | - |
| 5. Silver Staging | 0/0 | Not started | - |
| 6. Gold Marts + Data Quality | 0/0 | Not started | - |
| 7. Prefect Orchestration | 0/0 | Not started | - |
| 8. Streamlit Dashboard (Static Gold Export) | 0/0 | Not started | - |
| 9. Ops Polish, ADRs, Case Study | 0/0 | Not started | - |

---
*Last updated: 2026-05-19 — Phase 2 plans created*
