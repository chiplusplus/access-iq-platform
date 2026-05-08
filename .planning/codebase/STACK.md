# Technology Stack

**Analysis Date:** 2026-05-08

## Languages

**Primary:**
- Python `>=3.12` — runtime ingestion package (`src/access_iq/`) and CDK infra app (`infra/`)

**Secondary:**
- JSON — environment configuration (`config/{env}.json`, `infra/config/{env}.json`)
- Make — task runner (`Makefile`)
- YAML — GitHub Actions CI (`.github/workflows/ci.yml`)

## Runtime

**Environment:**
- CPython 3.12 (pinned via `pyproject.toml` `requires-python = ">=3.12"` and CI `python-version: "3.12"`)

**Package Manager:**
- `uv` (Astral) — venv creation and editable installs (`make setup`, CI installs via `astral.sh/uv/install.sh`)
- Lockfile: Not detected (no `uv.lock` / `requirements.txt` checked in; pinning is in `pyproject.toml`)

## Frameworks

**Core:**
- `aws-cdk-lib` 2.236.0 — IaC framework for AWS resources (`infra/app.py`, `infra/access_iq_infra/stacks/`)
- `constructs` 10.4.5 — CDK construct base library
- `pydantic` 2.12.5 — config and data models (`src/access_iq/ingestion/cli.py:21-32`)
- `boto3` 1.42.53 — AWS SDK for ingestion (`src/access_iq/ingestion/{cli,trust_s3,sftp,postgres}.py`)

**Testing:**
- `pytest` 9.0.2 — test runner (`tests/`, configured in `pyproject.toml` `[tool.pytest.ini_options]`)
- `pytest-cov` 7.0.0 — coverage with `fail_under = 70` (`pyproject.toml` `[tool.coverage.report]`)

**Build/Dev:**
- `ruff` 0.14.13 — formatter + linter (`select = ["E","F","I","B","UP"]`, line-length 100)
- `mypy` 1.19.1 — strict-leaning type checker (`warn_return_any`, `check_untyped_defs`, `no_implicit_optional`)
- `pre-commit` 4.5.1 — git hook runner (installed via `make setup`)
- `uv` — dependency installer

## Key Dependencies

**Critical:**
- `psycopg2-binary` 2.9.11 — Postgres driver, uses `COPY ... TO STDOUT WITH CSV HEADER` (`src/access_iq/ingestion/postgres.py`)
- `paramiko` 4.0.0 — SFTP client (`src/access_iq/ingestion/sftp.py`)
- `boto3` 1.42.53 — S3 client for Bronze writes and Trust S3 server-side copies (`src/access_iq/ingestion/trust_s3.py`)
- `python-dotenv` 1.2.1 — loads `.env` into env vars at CLI startup (`src/access_iq/ingestion/cli.py:37`)

**Infrastructure:**
- `aws-cdk-lib` 2.236.0 + `constructs` 10.4.5 — synthesises `PlatformBucketStack` and `IngestionRoleStack`
- AWS CDK CLI (`cdk`) — invoked via `make infra-{bootstrap,diff,deploy,destroy}` (not a Python dep; assumed on PATH)

**Type stubs (dev):**
- `types-psycopg2`, `types-boto3`, `types-boto3-s3`, `boto3-stubs`, `types-paramiko`

## Configuration

**Environment:**
- Runtime ingestion config: `config/{ENV}.json` loaded from CWD (`src/access_iq/ingestion/cli.py:41`); `ENV` env var defaults to `dev`
- CDK infra config: `infra/config/{env}.json` loaded via `infra/access_iq_infra/settings.py::load_env_config` selected by `-c env=dev|prod` context flag (`infra/app.py:9-13`)
- Two config trees are intentionally separate — runtime != infra
- `.env` at repo root loaded via `python-dotenv` for credentials

**Key configs required (env vars):**
- `ENV` — selects runtime config file
- `AWS_PROFILE` — AWS SSO profile (also referenced by Make targets and `boto3.Session(profile_name=...)`)
- `CDK_ENV` — `dev` | `prod` for `make infra-*`
- `EHR_DSN`, `URGENT_CARE_DSN` — Postgres DSNs (names declared in `config/dev.json`)
- `SFTP_HOST`, `SFTP_PORT`, `SFTP_USER`, `SFTP_PASSWORD` — SFTP credentials

**Build:**
- `pyproject.toml` — single source of dep + tool config
- `infra/cdk.json` — CDK app entry point config
- `Makefile` — task wrappers
- `.github/workflows/ci.yml` — CI pipeline

## Platform Requirements

**Development:**
- Python 3.12
- `uv` installed
- `cdk` (AWS CDK CLI) on PATH for infra targets
- AWS SSO configured profile (`AWS_PROFILE`)
- Active AWS account access for `eu-west-2`

**Production:**
- AWS account `222308823356` (dev) — separate prod account via `infra/config/prod.json`
- Region `eu-west-2`
- Two-account model (Trust + Platform) per `CLAUDE.md`; only Platform stacks currently coded

---

*Stack analysis: 2026-05-08*
