# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

Access-IQ is a portfolio-grade data platform simulating a consultancy engagement with a UK NHS Trust ("Northshire Trust"). It ingests operational healthcare data from a simulated Trust environment, models it through a Bronze → Silver → Gold medallion architecture, and surfaces analytics about healthcare access and inequality via a Streamlit dashboard.

Two AWS accounts model a vendor-client boundary:

- **Trust account** - RDS Postgres (EHR + Urgent Care), AWS Transfer Family (SFTP appointment drops), S3 (diagnostics/provider exports), private VPC
- **Platform account** - ECS Fargate (ingestion compute), S3 (data lake), Redshift Serverless (warehouse), Prefect (orchestration), CloudWatch (observability), Streamlit (dashboard), VPC peered to Trust

All infrastructure is CDK-managed with an ephemeral deploy/destroy pattern to avoid idle costs between working sessions.

## Commands

The project uses `uv` + a Make-driven workflow. Most commands assume `.venv` exists (created by `make setup`).

- `make setup` - check prereqs (`uv`, `node`, `cdk`, `aws`, `jq`), run `uv sync --group dev`, install `infra/` editable, install pre-commit hooks
- `make fmt` / `make lint` - `ruff format .` / `ruff check .`
- `make type` - `mypy .`
- `make test` - `pytest --cov=access_iq --cov=access_iq_infra`
- `make ci` - fmt + lint + type + test (mirrors `.github/workflows/ci.yml`)
- Run a single test: `.venv/bin/pytest tests/unit/test_postgres.py::test_name -v`

CDK (run from `infra/`, requires `PLATFORM_PROFILE` and `CDK_ENV` set to `dev` or `prod`):

- `make infra-bootstrap` / `make infra-diff` / `make infra-deploy` / `make infra-destroy`
- `infra-deploy` accepts `CDK_STACK=<name>` to deploy a single stack.

CI requires ruff format **check** to pass (`ruff format --check .`) - run `make fmt` before committing.

## Architecture

This is an NHS Trust access-and-inequality analytics platform. Two top-level Python packages live in different roots and are intentionally separated:

- `src/access_iq/` - the runtime/ingestion package (importable as `access_iq`, configured via `pyproject.toml`'s `pythonpath = ["src"]`).
- `infra/access_iq_infra/` - AWS CDK app. Synthesised by `infra/app.py`. Has its own config tree at `infra/config/{dev,prod}.json`, separate from the runtime config at `config/{dev,prod}.json`. Don't conflate them.

### Ingestion (`src/access_iq/ingestion/`)

The CLI (`cli.py`) is the single entry point and dispatches three commands: `ingest-postgres`, `ingest-sftp`, `ingest-trust-s3`. It loads `config/{ENV}.json` from the current working directory (so the CLI must be run from repo root) and resolves credentials from env vars named in that config (e.g. `EHR_DSN`, `SFTP_HOST`).

All three ingestion paths share the same Bronze contract:

- Output key: `bronze/source=<src>/entity=<ent>/ingest_date=YYYY-MM-DD/run_id=<uuid>/<file>`
- One run = one `run_id` (uuid4), one aggregate manifest at `_manifests/source=<src>/ingest_date=.../run_id=<uuid>.json`
- **Idempotency**: before doing work, `idempotency.should_skip_if_already_successful` lists the latest manifest under that source+date prefix and skips if `status == "success"`. New work always writes a fresh `run_id`; manifests are append-only and the _latest_ one wins.
- `fail_fast` flag controls whether per-table/per-file failures abort the run or continue and mark the manifest as `failed`.

Source-specific notes:

- `postgres.py` uses `SELECT *` with `cursor.fetchall()` converted to Parquet via `_parquet_buffer` - large tables will need a streaming rewrite.
- `trust_s3.py` uses S3 server-side `copy_object` (no download). The Trust bucket uses `export_date=YYYYMMDD` (no dashes) in its prefix layout - the code handles the conversion; preserve it.
- `sftp.py` reads files fully into memory and SHA-256s them before upload.

### Infra (`infra/`)

`app.py` requires `-c env=dev|prod` context, loads `infra/config/<env>.json` via `settings.load_env_config` into a frozen `EnvConfig` dataclass, and synthesises these stacks:

1. `LakeStack` - S3 data lake bucket + KMS CMK for encryption at rest.
2. `SecretsStack` - Secrets Manager entries (pseudonymisation key, Redshift password).
3. `CatalogStack` - Glue Data Catalog database for Spectrum external tables.
4. `EcrStack` - ECR container registry for ingestion image.
5. `IamStack` - IAM roles (ECS task, execution, Prefect worker, Spectrum). Grants are prefix-scoped: ingestion writes `bronze/*` + `_manifests/*` only; Spectrum reads all prefixes + writes `gold_export/*`. Also grants dashboard export bucket write + KMS encrypt if `dashboard` config is set.
6. `NetworkStack` - VPC, subnets, NAT Gateway, VPC peering to Trust.
7. `ObservabilityStack` - CloudWatch log groups, 15+ metric filters (ingestion events + pipeline lifecycle), 6 alarms (ingestion failure, budget, Redshift usage, GE gate failure, validation error, pipeline/export staleness), EventBridge OOM detection rule, SNS topics, pipeline-health dashboard.
8. `WarehouseStack` - Redshift Serverless namespace + workgroup with RPU usage limits.
9. `ComputeStack` - ECS Fargate cluster, task definitions, Prefect server + worker services.
10. `BudgetStack` - AWS Budgets ($10 dev / $20 prod monthly ceiling) with SNS alarm at 80% threshold. Breaching triggers a Lambda that auto-destroys ephemeral stacks (compute, warehouse, network, observability, ingestion-role). Connected to ObservabilityStack's delivery topic for notifications.

Tags from `cfg.tags` are applied app-wide via `tagging.apply_tags(app, ...)` before stack instantiation.

### Config (`infra/config/`)

Each env config file (`dev.json`, `prod.json`) contains account IDs, VPC CIDRs, and feature-specific blocks. Key sections beyond the basics:

- `obs.staleness_alarm_hours` / `obs.export_staleness_alarm_hours` - evaluation windows for pipeline and Gold export staleness alarms (defaults: 48h / 50h in dev).
- `obs.slack_webhook_url` - optional Slack webhook for budget teardown notifications.
- `dashboard.export_bucket` / `dashboard.kms_key_arn` - permanent S3 bucket and KMS key for Streamlit Gold exports (outside ephemeral stacks).
- `redshift` block - base_capacity, usage_limit_rpu_hours, snapshot_retention_days, db_name.

### Environments

Two AWS accounts (dev/prod). Promotion model (per `docs/architecture/environment_matrix.md`): merge to `main` → dev; tag (e.g. `v0.1.0`) → prod. Secrets follow `access-iq/{env}/<name>` in Secrets Manager. Don't hardcode env-specific values; route through the env config files.

## What's not built yet

Most of the platform is implemented. Remaining gaps:

- **dbt Silver models**: 9 of 10 Silver models pass; `stg_patients` is blocked by a Redshift 3-part name resolution error (see `.planning/` notes).
- **Great Expectations**: validation suite scaffolded but not fully wired into the pipeline gate.
- **Observability integration tests**: unit tests cover all stacks; integration tests for the new pipeline-event metric filters and staleness alarms are stubbed but need live-stack validation.

## Things to remember

1. Files under .planning/ are gitignored should not be commited
