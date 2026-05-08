# Coding Conventions

**Analysis Date:** 2026-05-08

## Naming Patterns

**Files:**
- snake_case Python modules: `postgres.py`, `trust_s3.py`, `idempotency.py`, `settings.py`, `tagging.py`
- Test files mirror module names with `test_` prefix: `tests/unit/test_postgres.py`, `tests/unit/test_trust_s3.py`
- Config files keyed by env name: `config/dev.json`, `config/prod.json`, `infra/config/dev.json`

**Functions:**
- snake_case throughout
- Verb-led action names for top-level public ingestion entrypoints: `ingest_table_to_bronze`, `ingest_postgres_source_to_bronze`, `ingest_sftp_directory_to_bronze`, `ingest_trust_provider_ref_to_bronze`, `ingest_trust_diagnostics_export_date_to_bronze` (`src/access_iq/ingestion/postgres.py`, `sftp.py`, `trust_s3.py`)
- Predicate helpers prefixed with `should_`: `should_skip_if_already_successful` (`src/access_iq/ingestion/idempotency.py`)
- Module-private helpers underscore-prefixed: `_copy_stream`, `_latest_manifest_key`, `_put_manifest`
- Small utility helpers: `utc_now()`, `sha256_bytes()`

**Variables:**
- snake_case locals
- `run_id`, `ingest_date`, `manifest_prefix`, `bronze_key`, `manifest_key` are recurring vocabulary — reuse these names verbatim in new ingestion code
- `cfg` is the canonical name for a loaded `EnvConfig` (`infra/access_iq_infra/stacks/s3.py`, `infra/access_iq_infra/stacks/iam.py`)

**Types / Classes:**
- PascalCase: `PostgresSource`, `Config` (Pydantic), `EnvConfig` (dataclass), `FileResult` (dataclass), `PlatformBucketStack`, `IngestionRoleStack`
- CDK stacks suffixed `Stack`: `PlatformBucketStack`, `IngestionRoleStack` (`infra/access_iq_infra/stacks/`)
- Pydantic models extend `BaseModel`; immutable infra config uses `@dataclass(frozen=True)` (`infra/access_iq_infra/settings.py`)

## Code Style

**Formatting:**
- `ruff format` — enforced; CI runs `ruff format --check .` (`.github/workflows/ci.yml`)
- `line-length = 100` (`pyproject.toml`)
- `target-version = "py312"` — Python 3.12 syntax
- Always run `make fmt` before commit; pre-commit hook runs `ruff` and `ruff-format` (`.pre-commit-config.yaml`)

**Linting:**
- `ruff check` with rule sets `["E", "F", "I", "B", "UP"]` (pycodestyle, pyflakes, isort, bugbear, pyupgrade)
- `E501` ignored (handled by formatter)
- `fix = true` — ruff auto-fixes on run

**Type Checking:**
- `mypy .` enforced in CI
- Settings: `warn_return_any`, `warn_unused_ignores`, `no_implicit_optional`, `check_untyped_defs` (`pyproject.toml`)
- Explicit type annotations on public function signatures (parameters and return)
- Use `from __future__ import annotations` at top of every module — universal in this codebase
- Modern PEP 604 unions: `str | None` not `Optional[str]`
- Built-in generics: `list[str]`, `dict[str, Any]` (no `List`, `Dict`)
- `Any` from `typing` used for boto3 clients (no concrete stub binding)

## Import Organization

**Order (ruff isort):**
1. `from __future__ import annotations` (always first)
2. Standard library (`json`, `uuid`, `datetime`, `pathlib`, `typing`)
3. Third-party (`boto3`, `psycopg2`, `paramiko`, `pydantic`, `aws_cdk`, `constructs`)
4. First-party (`access_iq.*`, `access_iq_infra.*`)

**Path Aliases:**
- Runtime package import root: `src/` configured via `pyproject.toml` (`pythonpath = ["src"]`, `mypy_path = "src"`)
- Always import from full package path: `from access_iq.ingestion.idempotency import should_skip_if_already_successful`
- Infra package: `from access_iq_infra.settings import EnvConfig`

## Error Handling

**Patterns:**
- **Per-item try/except in batch loops**: each table/file/object wrapped individually; per-item failure recorded as a result entry with `status="failed"` and `error="{type(e).__name__}: {e}"` (see `ingest_postgres_source_to_bronze` in `src/access_iq/ingestion/postgres.py:110-141`, `ingest_sftp_directory_to_bronze` in `src/access_iq/ingestion/sftp.py:95-142`, diagnostics loop in `src/access_iq/ingestion/trust_s3.py:142-180`)
- **`fail_fast` flag** controls whether the loop breaks on first failure or continues; default `True`. Always plumb this through new batch ingestion functions.
- **Manifest-level status aggregation**: any per-item failure flips run status to `"failed"`; manifest is still written with full result detail.
- **CLI argument errors → `SystemExit`** with `from None` to suppress chained traceback: `raise SystemExit(...) from None` (`src/access_iq/ingestion/cli.py:102-104`)
- **Config loader re-raises with context** via `raise ... from e` chaining (`infra/access_iq_infra/settings.py:25-48`)
- **Defensive JSON decode**: `idempotency.should_skip_if_already_successful` catches `(TypeError, json.JSONDecodeError)`, prints warning, returns `False` rather than raising (`src/access_iq/ingestion/idempotency.py:28-38`)
- **Resource cleanup via try/finally**: SFTP transport closed in `finally`; cursor/conn closed in `finally` (`src/access_iq/ingestion/postgres.py:46-54`, `src/access_iq/ingestion/sftp.py:83-147`)

## Logging

**Framework:** `print()` only — no logging library configured.

**Patterns:**
- Status messages printed at run boundaries: `print(f"\n=== Ingesting Postgres source: {db} ===")` (`cli.py:84`)
- Skip notifications: `print("Ingest already successful for this date and source. Skipping.")`
- Warnings prefixed with `"Warning: "`: `print(f"Warning: could not decode manifest JSON ...")` (`idempotency.py:31`)
- Final outcomes printed by CLI: `print(f"{db}: {manifest['status']} (run_id={manifest['run_id']})")`

When adding logging, follow this `print()` convention until a structured logger is introduced — do not mix `logging.getLogger` ad hoc.

## Comments

**When to Comment:**
- Module-level docstrings on public ingest functions describe contract: bronze key shape, manifest behaviour, idempotency guarantees (`src/access_iq/ingestion/sftp.py:52-58`, `trust_s3.py:34-36`)
- Inline comments mark known-debt or rationale: `# IMPORTANT: config should live at repo root: ./config/dev.json` (`cli.py:40`), `# NOTE: This buffers the COPY output in memory.` (`postgres.py:181`)
- CDK stack docstrings short and capability-focused (`infra/access_iq_infra/stacks/s3.py:14-16`)

**Docstring Style:**
- Plain triple-quoted prose; no Sphinx/Google/Numpy formal sections
- Document side effects (writes, S3 keys, manifests) explicitly

## Function Design

**Size:** Functions stay focused — typical ingest entrypoints 50-100 lines; helpers under 20.

**Parameters:**
- **Keyword-only enforced via `*`** for almost every public ingestion function: `def ingest_table_to_bronze(*, dsn, db, table, ...)` (`postgres.py:20`), `ingest_sftp_directory_to_bronze(*, source_name, host, ...)` (`sftp.py:38`), `_latest_manifest_key(*, s3, bucket, prefix)` (`idempotency.py:7`)
- All new public functions in `src/access_iq/` MUST use `*` to force keyword args
- Optional parameters with sensible defaults at end: `aws_profile: str | None = None`, `fail_fast: bool = True`

**Return Values:**
- Ingest functions return a manifest `dict[str, Any]` with a stable shape: `source`, `env`, `run_id`, `ingest_date`, `started_at`, `finished_at`, `status`, `error`, `inputs`, `outputs`
- `status` is one of: `"success"`, `"failed"`, `"skipped"`
- Skipped runs return early with `reason: "latest_manifest_success"`
- Predicates return `bool`; helpers return concrete types (`io.BytesIO`, `str | None`)

## Module Design

**Exports:**
- No `__all__` declarations; rely on import paths
- `__init__.py` files are empty markers (`src/access_iq/__init__.py`, `tests/unit/__init__.py`, `infra/access_iq_infra/__init__.py`)

**Barrel Files:** Not used.

**Module shape:**
- Each ingestion source has its own module under `src/access_iq/ingestion/` exposing one or two `ingest_*` entrypoints
- Cross-cutting helpers (idempotency) live in their own module and are imported, not duplicated
- CDK stacks: one stack per file under `infra/access_iq_infra/stacks/`

## Domain Conventions (project-specific)

- **Bronze key shape (mandatory):** `bronze/source=<src>/entity=<ent>/ingest_date=YYYY-MM-DD/run_id=<uuid>/<file>`
- **Manifest key shape:** `_manifests/source=<src>/ingest_date=YYYY-MM-DD/run_id=<uuid>.json`
- **`run_id`** = `str(uuid.uuid4())`, generated once per run, shared across all items
- **`utc_now()`** returns ISO 8601 with `+00:00` offset; defined per-module (`postgres.py:16`, `sftp.py:18`, `trust_s3.py:11`) — duplicate this helper rather than importing across ingestion modules (current convention)
- **Trust S3 partition oddity:** Trust bucket uses `export_date=YYYYMMDD` (no dashes); convert via `export_date.isoformat().replace('-', '')` (`trust_s3.py:134`). Preserve this conversion for any new Trust-side reads.
- **Config separation:** runtime config at `config/{env}.json` (loaded from CWD); infra config at `infra/config/{env}.json` (loaded from package path). Do not conflate.

---

*Convention analysis: 2026-05-08*
