# Codebase Structure

**Analysis Date:** 2026-05-08

## Directory Layout

```
access-iq-platform/
├── src/
│   └── access_iq/                  # Runtime package (importable as `access_iq`)
│       ├── __init__.py
│       └── ingestion/              # All three ingestion paths + shared idempotency
│           ├── cli.py              # Single CLI entry point (subcommands)
│           ├── postgres.py         # COPY -> S3 Bronze
│           ├── sftp.py             # paramiko -> S3 Bronze
│           ├── trust_s3.py         # S3 server-side copy -> Bronze
│           └── idempotency.py      # Manifest-based skip check
├── infra/                          # CDK app (separate root, separate config)
│   ├── app.py                      # CDK entry — synth-time stack wiring
│   ├── cdk.json                    # CDK app definition + context defaults
│   ├── access_iq_infra/
│   │   ├── __init__.py
│   │   ├── settings.py             # `EnvConfig` frozen dataclass + loader
│   │   ├── tagging.py              # `apply_tags` + REQUIRED_TAGS list
│   │   └── stacks/
│   │       ├── __init__.py
│   │       ├── s3.py               # `PlatformBucketStack`
│   │       └── iam.py              # `IngestionRoleStack`
│   └── config/                     # Infra-only env config
│       ├── dev.json                # gitignored real values
│       ├── dev.json.example
│       ├── prod.json
│       └── prod.json.example
├── config/                         # Runtime ingestion config (NOT infra)
│   └── dev.json                    # Source catalogue + env-var pointers
├── tests/
│   └── unit/                       # Mirrors `src/access_iq/ingestion/` 1:1
│       ├── __init__.py
│       ├── test_cli.py
│       ├── test_idempotency.py
│       ├── test_ingestion.py
│       ├── test_postgres.py
│       ├── test_sftp.py
│       └── test_trust_s3.py
├── docs/
│   ├── architecture/
│   │   └── environment_matrix.md   # dev/prod promotion model
│   └── engagement/                 # Consultancy-style spec docs
│       ├── 00_context.md
│       ├── 01_scope_success.md
│       ├── 02_data_contracts/      # One contract per source
│       ├── 03_metric_definitions.md
│       ├── 04_risks_assumptions.md
│       ├── 05_delivery_plan.md
│       └── 06_traceability.md
├── access-iq-platform/             # Stray nested dir (contains tests/unit/test_cli.py only)
├── .github/workflows/ci.yml        # CI: fmt-check + lint + type + test
├── .planning/codebase/             # Generated GSD codebase maps (this file)
├── Makefile                        # `make setup|fmt|lint|type|test|ci|infra-*`
├── pyproject.toml                  # Package metadata, ruff/mypy/pytest/coverage config
├── .pre-commit-config.yaml
├── .editorconfig
├── .gitignore
├── CLAUDE.md                       # Repo-level Claude Code instructions
└── README.md
```

## Directory Purposes

**`src/access_iq/`:**
- Purpose: Runtime/ingestion package shipped as `access_iq` (per `pyproject.toml` `pythonpath = ["src"]`).
- Contains: Python modules, no resources.
- Key files: `ingestion/cli.py`, `ingestion/postgres.py`, `ingestion/sftp.py`, `ingestion/trust_s3.py`, `ingestion/idempotency.py`.

**`src/access_iq/ingestion/`:**
- Purpose: All ingestion paths and the shared idempotency check.
- Contains: One module per source kind plus the CLI dispatcher.
- Key files: see above.

**`infra/`:**
- Purpose: AWS CDK application root. Run `cdk` from here.
- Contains: `app.py` (entry), `cdk.json`, the `access_iq_infra` package, and infra-only `config/`.
- Key files: `infra/app.py`, `infra/cdk.json`.

**`infra/access_iq_infra/`:**
- Purpose: CDK constructs and helpers for the platform account.
- Contains: `settings.py` (typed env config), `tagging.py` (required-tag enforcement), `stacks/` (one stack per resource group).
- Key files: `settings.py`, `tagging.py`, `stacks/s3.py`, `stacks/iam.py`.

**`infra/config/`:**
- Purpose: Per-env CDK inputs (`account_id`, `region`, `tags`, `iam.external_bucket`, `user_name`).
- Contains: `dev.json`, `prod.json`, plus `.example` skeletons.
- Note: Distinct from runtime `config/` — never merge these.

**`config/` (repo root):**
- Purpose: Runtime ingestion config — source catalogue and env-var indirection.
- Contains: `dev.json` only (prod will follow the same shape).
- Loaded by: `src/access_iq/ingestion/cli.py:load_config` via `Path.cwd() / "config" / f"{ENV}.json"`.

**`tests/unit/`:**
- Purpose: Pytest unit tests mirroring `src/access_iq/ingestion/`.
- Contains: One `test_<module>.py` per ingestion module + `test_cli.py` + `test_ingestion.py` + `test_idempotency.py`.
- `pyproject.toml` `[tool.pytest.ini_options]`: `testpaths = ["tests"]`, `pythonpath = ["src"]`.

**`docs/architecture/`:**
- Purpose: Architecture decision documents (currently `environment_matrix.md`).

**`docs/engagement/`:**
- Purpose: Consultancy-style engagement docs — context, scope, data contracts, metrics, risks, delivery plan, traceability.
- Contains: Numbered markdown files; data contracts split per source under `02_data_contracts/`.

**`access-iq-platform/` (nested):**
- Purpose: Stray nested directory containing only `tests/unit/test_cli.py`. Likely accidental — not referenced by `pyproject.toml`'s `testpaths`.
- Contains: One file. Treat as cruft pending cleanup.

**`.github/workflows/`:**
- Purpose: CI pipeline (`ci.yml`) — runs `make ci` minus formatter-write (uses `ruff format --check`).

**`.planning/codebase/`:**
- Purpose: GSD-generated codebase maps consumed by `/gsd-plan-phase` and `/gsd-execute-phase`.
- Generated: Yes (by GSD agents).

## Key File Locations

**Entry Points:**
- `src/access_iq/ingestion/cli.py`: CLI dispatcher (`main`).
- `infra/app.py`: CDK app (`python3 app.py` per `cdk.json`).

**Configuration:**
- `pyproject.toml`: package metadata, ruff (line-length 100, py312, rules `E,F,I,B,UP`), mypy (strict-ish: `warn_return_any`, `check_untyped_defs`, `no_implicit_optional`), pytest, coverage (`fail_under = 70`).
- `Makefile`: developer commands.
- `infra/cdk.json`: CDK app + default context (`app_name`, `default_region`).
- `config/dev.json`: runtime source catalogue.
- `infra/config/{dev,prod}.json`: CDK env config.
- `.pre-commit-config.yaml`: pre-commit hook list.
- `.editorconfig`: editor defaults.

**Core Logic:**
- `src/access_iq/ingestion/postgres.py`: `ingest_postgres_source_to_bronze`, `ingest_table_to_bronze`, `_copy_stream`.
- `src/access_iq/ingestion/sftp.py`: `ingest_sftp_directory_to_bronze`, `FileResult`.
- `src/access_iq/ingestion/trust_s3.py`: `ingest_trust_provider_ref_to_bronze`, `ingest_trust_diagnostics_export_date_to_bronze`.
- `src/access_iq/ingestion/idempotency.py`: `should_skip_if_already_successful`.
- `infra/access_iq_infra/stacks/s3.py`: `PlatformBucketStack`.
- `infra/access_iq_infra/stacks/iam.py`: `IngestionRoleStack`.
- `infra/access_iq_infra/settings.py`: `EnvConfig`, `load_env_config`.
- `infra/access_iq_infra/tagging.py`: `apply_tags`, `REQUIRED_TAGS`.

**Testing:**
- `tests/unit/test_postgres.py`, `test_sftp.py`, `test_trust_s3.py`, `test_idempotency.py`, `test_cli.py`, `test_ingestion.py`.

## Naming Conventions

**Files:**
- Python modules: `snake_case.py`. One source kind per module (`postgres.py`, `sftp.py`, `trust_s3.py`).
- Tests: `test_<module>.py` mirroring runtime module name 1:1.
- Stacks: lowercase singular noun describing the resource group (`s3.py`, `iam.py`).
- Config: `{env}.json`, with `{env}.json.example` for committed skeletons.

**Directories:**
- All lowercase, snake_case (`access_iq`, `access_iq_infra`).
- Package roots match the importable name (`src/access_iq/` -> `import access_iq`).

**Functions:**
- Ingestion entry points: `ingest_<source>_to_bronze` (`ingest_postgres_source_to_bronze`, `ingest_sftp_directory_to_bronze`, `ingest_trust_diagnostics_export_date_to_bronze`).
- Private helpers: leading underscore (`_copy_stream`, `_latest_manifest_key`, `_put_manifest`).
- Predicates: `should_*` (`should_skip_if_already_successful`).

**Classes:**
- CDK stacks: `<Purpose>Stack` (`PlatformBucketStack`, `IngestionRoleStack`).
- Pydantic/dataclass models: PascalCase (`Config`, `PostgresSource`, `EnvConfig`, `FileResult`).

**S3 keys:**
- Bronze: `bronze/source=<src>/entity=<ent>/ingest_date=YYYY-MM-DD/run_id=<uuid>/<file>`.
- Manifests: `_manifests/source=<src>/ingest_date=YYYY-MM-DD/run_id=<uuid>.json`.
- Hive-style `key=value` partitioning throughout.

## Where to Add New Code

**New ingestion source:**
- Implementation: new module in `src/access_iq/ingestion/<source>.py` exposing `ingest_<source>_to_bronze(...) -> dict[str, Any]`. Reuse `idempotency.should_skip_if_already_successful` and the Bronze key contract.
- CLI wiring: add subcommand branch in `src/access_iq/ingestion/cli.py:main` and a config schema (pydantic model alongside `PostgresSource`).
- Config: extend `config/{env}.json` under `sources.<kind>`.
- Tests: `tests/unit/test_<source>.py`.

**New CDK stack:**
- Implementation: `infra/access_iq_infra/stacks/<resource>.py` defining `<Purpose>Stack(Stack)`.
- Wiring: instantiate in `infra/app.py` after `apply_tags`, passing `cfg=cfg, env=cdk_env` and any cross-stack handles (`bucket.data_bucket` etc.).
- Config: extend `infra/config/{dev,prod}.json` and (if needed) `EnvConfig` in `infra/access_iq_infra/settings.py`.

**New env config field (runtime):**
- Add to `config/dev.json`.
- Extend `Config`/`PostgresSource` (or add new pydantic model) in `src/access_iq/ingestion/cli.py`.
- Read from `os.getenv` for secrets; use `*_env` indirection pattern.

**New env config field (infra):**
- Add to `infra/config/{dev,prod}.json` and the `.example` skeletons.
- Extend `EnvConfig` dataclass + `load_env_config` parsing in `infra/access_iq_infra/settings.py`.

**Shared utility used across ingestors:**
- Place in `src/access_iq/ingestion/` next to siblings (e.g. `idempotency.py`). No `utils/` package exists yet — only create one if cross-cutting helpers grow beyond ingestion.

**New tests:**
- `tests/unit/test_<module>.py`. Tests live at the repo-root `tests/` tree only (mind the stray `access-iq-platform/tests/unit/test_cli.py` — do not add files there).

**New IAM permissions for ingestion:**
- Edit `infra/access_iq_infra/stacks/iam.py`. Keep prefix-scoped to `bronze/*` and `_manifests/*`. Silver/Gold permissions belong in a separate role/stack.

**Documentation:**
- Architecture decisions: `docs/architecture/<topic>.md`.
- Engagement / spec docs: `docs/engagement/` (numbered).
- Per-source data contract: `docs/engagement/02_data_contracts/<source>_data_contract.md`.

## Special Directories

**`.venv/`:**
- Purpose: uv-managed virtualenv created by `make setup`.
- Generated: Yes.
- Committed: No.

**`infra/cdk.out/`:**
- Purpose: CDK synthesised CloudFormation. Excluded from mypy via `pyproject.toml` `exclude = "infra/cdk.out/.*"`.
- Generated: Yes.
- Committed: No.

**`src/access_iq.egg-info/`:**
- Purpose: editable-install metadata.
- Generated: Yes.
- Committed: No.

**`.planning/`:**
- Purpose: GSD workflow artefacts (codebase maps, phase plans).
- Generated: Yes.
- Committed: Yes (per GSD convention).

**`access-iq-platform/` (nested):**
- Purpose: Apparent leftover; only `tests/unit/test_cli.py` inside.
- Generated: No.
- Committed: Yes (currently). Candidate for removal.

---

*Structure analysis: 2026-05-08*
