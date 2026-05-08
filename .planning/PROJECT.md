# Access-IQ

## What This Is

Access-IQ is a portfolio-grade data platform that simulates a consultancy engagement with a UK NHS Trust ("Northshire Trust"). It ingests operational healthcare data from a simulated Trust environment, models it through a Bronze → Silver → Gold medallion architecture on AWS, and surfaces analytics about healthcare access and inequality through a Streamlit dashboard. The audience is hiring managers and staff engineers reviewing the work as evidence of senior data/platform engineering capability.

## Core Value

A reviewer can read a written case study **and** spin up the live system end-to-end on demand, watch synthetic NHS data flow Trust → Bronze → Silver → Gold → dashboard, and see production-shaped data quality, observability, and orchestration along the way.

## Requirements

### Validated

<!-- Inferred from existing code (brownfield). -->

- ✓ Trust account CDK stack (RDS Postgres, AWS Transfer Family SFTP, Trust S3, private VPC) — existing in separate repo
- ✓ Platform S3 bucket stack (versioned, SSL-enforced, env-aware removal policy) — existing
- ✓ IAM ingestion role scoped to `bronze/*` and `_manifests/*` — existing
- ✓ Postgres → Bronze ingestion with manifest + idempotency contract (`access_iq.ingestion.postgres`) — existing
- ✓ SFTP → Bronze ingestion with SHA-256 + manifest contract (`access_iq.ingestion.sftp`) — existing
- ✓ Trust S3 → Bronze server-side copy ingestion (`access_iq.ingestion.trust_s3`) — existing
- ✓ Shared Bronze contract: `bronze/source=.../entity=.../ingest_date=.../run_id=.../...` + aggregate manifests + idempotency on latest manifest — existing
- ✓ CLI entrypoint dispatching `ingest-postgres` / `ingest-sftp` / `ingest-trust-s3` (`access_iq.ingestion.cli`) — existing
- ✓ Make-driven dev workflow (`make setup/fmt/lint/type/test/ci`) and CI gating on ruff format check — existing
- ✓ Two AWS accounts (Trust + Platform) with vendor/client boundary modelling — existing
- ✓ Promotion model: merge to `main` → dev; tag `vX.Y.Z` → prod — existing

### Active

<!-- v1 milestone scope: 8 phases. All hypotheses until shipped + verified. -->

- [ ] **REQ-ECS-01** Run ingestion on ECS Fargate (not local) against the Trust environment
- [ ] **REQ-OBS-01** CloudWatch log groups, metric filters, and alarms with SNS notifications for ingestion + pipeline failures
- [ ] **REQ-OBS-02** Operational CloudWatch dashboard covering ingestion runs, manifest status, and pipeline lag
- [ ] **REQ-WH-01** Redshift Serverless workgroup + namespace with VPC peering Platform↔Trust and least-privilege IAM
- [ ] **REQ-DBT-01** dbt project initialised against Redshift with environment-aware profiles and CI hook
- [ ] **REQ-SILVER-01** Silver staging models for `patients`, `encounters`, `appointments`, `urgent_care`, `diagnostics`, `providers`
- [ ] **REQ-GOLD-WT-01** Gold mart: `wait_times` (referral-to-treatment, A&E breaches, diagnostics waits)
- [ ] **REQ-GOLD-INEQ-01** Gold mart: `inequality` sliced by IMD decile, age band, ethnicity, and gender
- [ ] **REQ-GOLD-UC-01** Gold mart: `urgent_care` (attendances, breaches, conversion to admission)
- [ ] **REQ-GOLD-UTIL-01** Gold mart: `utilisation` (provider/clinic capacity, DNA rates)
- [ ] **REQ-DQ-01** Great Expectations validation suites on every Silver table, blocking promotion on failure
- [ ] **REQ-DQ-02** GE results published to S3 + summarised in observability dashboard
- [ ] **REQ-ORCH-01** Prefect flows orchestrating ingestion → dbt run → GE validation → dbt gold, with retries + alerting
- [ ] **REQ-DASH-01** Streamlit dashboard with three pages: Wait Times, Inequality, Urgent Care
- [ ] **REQ-DASH-02** Dashboard reads exclusively from Gold layer (no direct Silver/Bronze access)
- [ ] **REQ-SEED-01** Synthetic UK-shaped seed data (Faker + UK postcodes + realistic IMD/ethnicity/age distributions, plausible appointment volumes) seeded into Trust RDS, SFTP, and Trust S3
- [ ] **REQ-OPS-01** Session workflow: `make up` (deploy + seed), `make down` (destroy), `make ingest` (trigger ECS task) — strict ephemeral
- [ ] **REQ-DOC-01** ADRs covering major architecture/tooling decisions
- [ ] **REQ-DOC-02** README + written case study (problem, approach, trade-offs, screenshots, diagrams) suitable for a hiring-manager audience

### Out of Scope

- **Real PII / live NHS data** — synthetic only; this is a simulated Trust, not an integration with NHS systems
- **Multi-Trust / multi-tenant architecture** — single Trust by design; tenant isolation is a different problem class
- **ML / predictive analytics** — descriptive analytics only; no forecasting or models
- **Authentication on the dashboard** — Streamlit is open or behind a simple gate in dev; no IAM Identity Center login flow
- **Always-on production-grade infrastructure** — strict ephemeral deploy/destroy; no warm prod baseline
- **Streaming / real-time pipelines** — batch-oriented daily ingestion is sufficient for the use case

## Context

**Codebase state (from `.planning/codebase/`):**
- Ingestion runtime in `src/access_iq/ingestion/` is the most-developed area: three entrypoints share a Bronze contract with manifests + idempotency.
- Two parallel config trees exist: runtime (`config/{env}.json`) and infra (`infra/config/{env}.json`). They are intentionally separated and must not be conflated.
- CDK app at `infra/app.py` synthesises Trust + Platform stacks; Trust stack already deployed; Platform stack so far is just bucket + ingestion IAM role.
- Known issues recorded in `.planning/codebase/CONCERNS.md`: in-memory buffering in postgres `COPY` and SFTP read paths (OOM risk at scale), manifest `error` accumulation bug in `postgres.py`, empty-result idempotency poisoning in `trust_s3.py`, `infra/config/prod.json` missing required keys, hardcoded SSO role ARN in IAM trust, SSE-S3 instead of KMS CMK on the data lake.

**Domain:**
- UK NHS Trust operational data: EHR (RDS), urgent care (RDS), appointments (SFTP daily drops), diagnostics + provider exports (Trust S3).
- Headline analytics framing is **access** (waits, breaches, DNA) and **inequality** (outcomes sliced by IMD, age, ethnicity, gender).
- IMD = Index of Multiple Deprivation, the canonical UK deprivation index. Ethnicity follows ONS categories.

**Audience:**
- Hiring managers + staff engineers evaluating senior data/platform engineering candidates.
- They will both read the case study/ADRs and (likely) clone-and-run the system, so DX matters as much as architecture.

## Constraints

- **Tech stack**: AWS-native (CDK, ECS Fargate, S3, Redshift Serverless, CloudWatch), Python (`uv`-managed), dbt-core on Redshift, Great Expectations, Prefect, Streamlit. Don't introduce a fourth config tree, a non-CDK IaC tool, or non-AWS managed services.
- **Cost**: Strict ephemeral. `make up` deploys, `make down` destroys. Nothing should accrue cost overnight — Redshift Serverless paused, ECS scaled to 0, RDS stopped or destroyed, no NAT idle if avoidable.
- **Promotion**: merge to `main` → dev account; tag `vX.Y.Z` → prod account. Never hardcode env-specific values; route through env config files.
- **Security**: synthetic data only, but treat the codebase *as if* PII were real — least-privilege IAM, prefix-scoped role boundaries, no secrets in code, KMS encryption where it costs nothing extra.
- **Quality bar**: production-shaped DQ + observability — GE blocks bad data, CloudWatch alarms have SNS subscribers, runbooks exist for the top failure modes.
- **CI**: `make ci` (ruff format check + ruff lint + mypy + pytest with coverage) must pass on every commit. CI failures block merge.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Whole platform end-to-end as a single v1 milestone with 8 phases | User wants sequential, fully-working stages; one milestone keeps the narrative coherent for the case study | — Pending |
| Strict ephemeral infrastructure | Portfolio project — no budget for idle dev/prod baseline; demonstrates good cost hygiene | — Pending |
| Synthetic UK-shaped seed data (Faker + UK postcodes + realistic IMD/ethnicity/age distributions) | Realism makes inequality analytics meaningful without touching real PII | — Pending |
| Inequality dimensions = IMD decile + age band + ethnicity + gender | Aligned with NHS inequality reporting practice | — Pending |
| Production-shaped DQ + observability | Reviewer audience is senior; demonstrative-only would undersell the work | — Pending |
| Dashboard reads only from Gold layer | Enforces the medallion contract and demonstrates discipline | — Pending |
| Two-account vendor/client boundary preserved | Already shipped; modelling the consultancy engagement is part of the value proposition | ✓ Good |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-05-08 after initialization*
