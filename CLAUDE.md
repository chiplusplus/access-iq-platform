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

- `make setup` - create venv, install `-e ".[dev]"`, install pre-commit hooks
- `make fmt` / `make lint` - `ruff format .` / `ruff check .`
- `make type` - `mypy .`
- `make test` - `pytest --cov=access_iq`
- `make ci` - fmt + lint + type + test (mirrors `.github/workflows/ci.yml`)
- Run a single test: `. .venv/bin/activate && pytest tests/unit/test_postgres.py::test_name -v`

CDK (run from `infra/`, requires `AWS_PROFILE` and `CDK_ENV` set to `dev` or `prod`):
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
- **Idempotency**: before doing work, `idempotency.should_skip_if_already_successful` lists the latest manifest under that source+date prefix and skips if `status == "success"`. New work always writes a fresh `run_id`; manifests are append-only and the *latest* one wins.
- `fail_fast` flag controls whether per-table/per-file failures abort the run or continue and mark the manifest as `failed`.

Source-specific notes:
- `postgres.py` uses `COPY ... TO STDOUT WITH CSV HEADER` buffered into memory via `_copy_stream` - large tables will need a true streaming rewrite (noted in code).
- `trust_s3.py` uses S3 server-side `copy_object` (no download). The Trust bucket uses `export_date=YYYYMMDD` (no dashes) in its prefix layout - the code handles the conversion; preserve it.
- `sftp.py` reads files fully into memory and SHA-256s them before upload.

### Infra (`infra/`)

`app.py` requires `-c env=dev|prod` context, loads `infra/config/<env>.json` via `settings.load_env_config` into a frozen `EnvConfig` dataclass, and synthesises two stacks:
1. `PlatformBucketStack` - the project bucket (`{app_name}-{env_name}-{account_id}`), versioned, SSL-enforced, with `RemovalPolicy.RETAIN` + no auto-delete in prod, `DESTROY` + auto-delete in dev.
2. `IngestionRoleStack` - IAM role assumed by the SSO user in `cfg.user_name`. Grants read on the external Trust bucket (`cfg.iam.external_bucket`) and write on `bronze/*` + `_manifests/*` of the platform bucket only. Keep this prefix-scoped - silver/gold writes belong to different roles.

Tags from `cfg.tags` are applied app-wide via `tagging.apply_tags(app, ...)` before stack instantiation.

### Environments

Two AWS accounts (dev/prod). Promotion model (per `docs/architecture/environment_matrix.md`): merge to `main` → dev; tag (e.g. `v0.1.0`) → prod. Secrets follow `access-iq/{env}/<name>` in Secrets Manager. Don't hardcode env-specific values; route through the env config files.

## What's not built yet

The following components are planned but not yet implemented:

- **Platform infra expansion**: ECS Fargate cluster, Redshift Serverless, VPC peering, NAT gateway - all as CDK additions to Platform stack
- **Observability**: CloudWatch log groups, metric filters, alarms, operational dashboard
- **dbt modelling layer**: Silver staging models (patients, encounters, appointments, urgent_care, diagnostics, providers) and Gold marts (wait_times, inequality, urgent_care, utilisation) targeting Redshift
- **Data quality**: Great Expectations validation suites on Silver tables
- **Orchestration**: Prefect flows for ingestion → dbt → GE validation pipeline
- **Dashboard**: Streamlit app with 3 pages (Wait Times, Inequality, Urgent Care) reading from Gold layer
- **Session workflow**: `make up` (deploy + seed), `make down` (destroy), `make ingest` (trigger ECS tasks)

## Things to remember
1. Files under .planning/ are gitignored should not be commited
