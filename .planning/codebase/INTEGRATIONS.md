# External Integrations

**Analysis Date:** 2026-05-08

## APIs & External Services

**AWS (Platform account `222308823356`, region `eu-west-2`):**
- AWS S3 — Bronze data lake writes + manifest writes (`src/access_iq/ingestion/postgres.py`, `sftp.py`, `trust_s3.py`)
  - SDK: `boto3` 1.42.53
  - Auth: AWS SSO profile via `AWS_PROFILE` env var; passed to `boto3.Session(profile_name=...)` (`src/access_iq/ingestion/cli.py:54, 143-146`)
- AWS IAM — `IngestionRoleStack` provisions the role assumed by the SSO user `cfg.user_name` (`infra/access_iq_infra/stacks/iam.py`)
- AWS CloudFormation (via CDK) — synthesised by `infra/app.py`; deployed with `cdk deploy`
- AWS Secrets Manager — convention `access-iq/{env}/<name>` per `CLAUDE.md`; not yet wired into ingestion code

**Trust account (vendor boundary):**
- Trust S3 bucket `northshire-trust-external-exports` — external read source (`config/dev.json`, `infra/config/dev.json` `iam.external_bucket`)
  - Access: server-side `s3.copy_object` (no download) using profile `access-iq-dev-ingestion` (`config/dev.json` `trust_s3.base.profile`)
  - Prefix quirk: Trust uses `export_date=YYYYMMDD` (no dashes); converted in `src/access_iq/ingestion/trust_s3.py`

**Healthcare data sources (simulated NHS Trust):**
- Postgres: EHR (`ehr_postgres`) — tables `patient_demographics`, `encounters`
- Postgres: Urgent Care (`urgent_care_postgres`) — table `urgent_care_logs`
- SFTP: Appointments drop at `/upload/outbound/appointments/`

## Data Storage

**Databases (read-only sources):**
- PostgreSQL (RDS, Trust account) — two logical DBs
  - Connection: DSN env vars `EHR_DSN`, `URGENT_CARE_DSN` (declared in `config/dev.json` `sources.postgres.*.dsn_env`)
  - Client: `psycopg2-binary` 2.9.11 with `COPY ... TO STDOUT WITH CSV HEADER` (`src/access_iq/ingestion/postgres.py::_copy_stream`)
- Redshift Serverless — planned warehouse (per `CLAUDE.md`); not yet implemented

**File Storage:**
- AWS S3 platform bucket: `access-iq-{env}-{account_id}` (e.g. `access-iq-dev-222308823356`) — provisioned by `PlatformBucketStack` (`infra/access_iq_infra/stacks/s3.py`)
  - Versioned, SSL-enforced
  - Removal policy: `RETAIN` (prod), `DESTROY` + auto-delete (dev) — driven by `infra/config/{env}.json` `s3.removal_policy`
  - Bronze prefix layout: `bronze/source=<src>/entity=<ent>/ingest_date=YYYY-MM-DD/run_id=<uuid>/<file>`
  - Manifests: `_manifests/source=<src>/ingest_date=.../run_id=<uuid>.json`
- AWS S3 Trust bucket: `northshire-trust-external-exports` — external read source

**Caching:**
- None

## Authentication & Identity

**Auth Provider:**
- AWS IAM Identity Center (SSO)
  - Implementation: `cfg.user_name` (e.g. `AWSReservedSSO_CHI-Engineer_56b619fe880e8582/chia`) is granted `sts:AssumeRole` on the ingestion role by `IngestionRoleStack` (`infra/access_iq_infra/stacks/iam.py`)
  - Local resolution: `boto3.Session(profile_name=os.getenv("AWS_PROFILE"))`

**Postgres auth:**
- DSN strings (user/password embedded) provided via env vars; loaded with `python-dotenv`

**SFTP auth:**
- Username + password via env vars (`SFTP_USER`, `SFTP_PASSWORD`); no key-based auth wired in (`src/access_iq/ingestion/cli.py:106-115`, `src/access_iq/ingestion/sftp.py`)

## Monitoring & Observability

**Error Tracking:**
- None (planned: CloudWatch alarms per `CLAUDE.md`)

**Logs:**
- `print(...)` to stdout in CLI (`src/access_iq/ingestion/cli.py`)
- Manifest JSON in S3 acts as durable run record (`status`, `run_id`, per-entity outcomes)

**Metrics:**
- None (planned: CloudWatch metric filters + operational dashboard)

## CI/CD & Deployment

**Hosting:**
- AWS (planned ECS Fargate for ingestion compute, Redshift Serverless for warehouse, Streamlit for dashboard) — not yet built
- Current code runs locally via CLI from repo root

**CI Pipeline:**
- GitHub Actions: `.github/workflows/ci.yml`
  - Triggers: PRs and pushes to `main`
  - Steps: checkout → setup-python 3.12 → install `uv` → `uv pip install -e ".[dev]"` → `ruff format --check .` → `ruff check .` → `mypy .` → `pytest --cov=access_iq`
- No CD: deploys are manual via `make infra-deploy` with explicit `AWS_PROFILE` and `CDK_ENV`

**Promotion model (per `docs/architecture/environment_matrix.md`, referenced in `CLAUDE.md`):**
- Merge to `main` → dev
- Tag (e.g. `v0.1.0`) → prod

## Environment Configuration

**Required env vars:**
- `ENV` — `dev` | `prod`
- `AWS_PROFILE` — SSO profile for platform account
- `CDK_ENV` — `dev` | `prod` (Make targets)
- `EHR_DSN`, `URGENT_CARE_DSN` — Postgres connection strings
- `SFTP_HOST`, `SFTP_PORT`, `SFTP_USER`, `SFTP_PASSWORD` — SFTP credentials

**Secrets location:**
- Local dev: `.env` at repo root (loaded by `python-dotenv`); existence noted, contents not read
- Production convention: AWS Secrets Manager under `access-iq/{env}/<name>` (per `CLAUDE.md`); not yet integrated into ingestion code

## Webhooks & Callbacks

**Incoming:**
- None

**Outgoing:**
- None

---

*Integration audit: 2026-05-08*
