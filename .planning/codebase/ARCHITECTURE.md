<!-- refreshed: 2026-05-08 -->
# Architecture

**Analysis Date:** 2026-05-08

## System Overview

```text
┌─────────────────────────────────────────────────────────────┐
│                    CLI Entry / Orchestrator                  │
│              `src/access_iq/ingestion/cli.py`                │
│   subcommands: ingest-postgres | ingest-sftp | ingest-trust-s3│
└────────┬─────────────────┬──────────────────┬───────────────┘
         │                 │                   │
         ▼                 ▼                   ▼
┌────────────────┐ ┌────────────────┐ ┌──────────────────────┐
│ postgres.py    │ │ sftp.py        │ │ trust_s3.py          │
│ COPY -> S3     │ │ paramiko -> S3 │ │ S3 server-side copy  │
└────────┬───────┘ └────────┬───────┘ └──────────┬───────────┘
         │                  │                     │
         │      ┌───────────▼────────────┐        │
         └─────▶│   idempotency.py       │◀───────┘
                │ should_skip_if_already │
                │ _successful (manifest) │
                └───────────┬────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│            Platform S3 Bucket (Bronze + manifests)           │
│   bronze/source=<src>/entity=<ent>/ingest_date=.../run_id/  │
│   _manifests/source=<src>/ingest_date=.../run_id=<uuid>.json│
└─────────────────────────────────────────────────────────────┘

╔═════════════════════════════════════════════════════════════╗
║  Infra (CDK app, separate package, separate config tree)    ║
║  `infra/app.py`                                              ║
║   ├─ PlatformBucketStack  `infra/access_iq_infra/stacks/s3.py`║
║   └─ IngestionRoleStack   `infra/access_iq_infra/stacks/iam.py`║
╚═════════════════════════════════════════════════════════════╝
```

## Component Responsibilities

| Component | Responsibility | File |
|-----------|----------------|------|
| CLI dispatcher | Parse args, load config, route to ingestor | `src/access_iq/ingestion/cli.py` |
| Config loader | Load `config/{ENV}.json` into pydantic `Config` | `src/access_iq/ingestion/cli.py` (`load_config`) |
| Postgres ingestor | `COPY ... TO STDOUT` per table -> S3 Bronze + manifest | `src/access_iq/ingestion/postgres.py` |
| SFTP ingestor | Read remote files via paramiko, sha256, upload to Bronze | `src/access_iq/ingestion/sftp.py` |
| Trust S3 ingestor | S3 server-side copy from Trust bucket to Bronze | `src/access_iq/ingestion/trust_s3.py` |
| Idempotency check | List latest manifest, skip if `status == success` | `src/access_iq/ingestion/idempotency.py` |
| CDK app entry | Synthesise stacks per env context | `infra/app.py` |
| EnvConfig loader | Frozen dataclass from `infra/config/{env}.json` | `infra/access_iq_infra/settings.py` |
| Platform bucket stack | Versioned, SSL-only S3 bucket + lifecycle rules | `infra/access_iq_infra/stacks/s3.py` |
| Ingestion role stack | IAM role + scoped policy (bronze/* + _manifests/*) | `infra/access_iq_infra/stacks/iam.py` |
| Tag enforcement | Apply required tags app-wide, fail if missing | `infra/access_iq_infra/tagging.py` |

## Pattern Overview

**Overall:** Modular medallion-ingestion CLI with manifest-based idempotency, paired with a separate AWS CDK infrastructure app.

**Key Characteristics:**
- Single CLI entry, one subcommand per source kind (Postgres / SFTP / Trust S3).
- Each ingestion module is independently importable and follows the same Bronze contract: one `run_id` per run, one aggregate manifest per run.
- Idempotency is data-driven via S3 manifests, not local state.
- Infrastructure is split from runtime: `src/access_iq/` (runtime, importable as `access_iq`) and `infra/access_iq_infra/` (CDK constructs). Two distinct config trees: `config/` vs `infra/config/`.
- Boto3 sessions accept optional `aws_profile` so the same code runs locally (SSO profile) and in ECS (instance role).

## Layers

**CLI Layer (`src/access_iq/ingestion/cli.py`):**
- Purpose: Argument parsing, env/config resolution, dispatch.
- Location: `src/access_iq/ingestion/cli.py`
- Contains: `argparse` setup, `Config`/`PostgresSource` pydantic models, `load_config`, `main`.
- Depends on: ingestor modules, `dotenv`, `pydantic`, `boto3`.
- Used by: shell user / future ECS task entrypoint.

**Ingestion Layer (`src/access_iq/ingestion/{postgres,sftp,trust_s3}.py`):**
- Purpose: Source-specific extraction; write raw bytes to Bronze and a manifest.
- Location: `src/access_iq/ingestion/`
- Contains: `ingest_*_to_bronze` functions, source-specific helpers (`_copy_stream`, `sha256_bytes`, `FileResult`).
- Depends on: `idempotency`, `boto3`, `psycopg2`, `paramiko`.
- Used by: CLI.

**Idempotency Layer (`src/access_iq/ingestion/idempotency.py`):**
- Purpose: Decide whether the current run can be skipped.
- Location: `src/access_iq/ingestion/idempotency.py`
- Contains: `_latest_manifest_key`, `should_skip_if_already_successful`.
- Depends on: `boto3` S3 client (passed in).
- Used by: every ingestion module.

**Infra App Layer (`infra/app.py`):**
- Purpose: Wire CDK stacks for the chosen env (`dev`/`prod`).
- Location: `infra/app.py`
- Depends on: `aws_cdk`, `access_iq_infra.*`.
- Used by: `cdk` CLI.

**Infra Stacks Layer (`infra/access_iq_infra/stacks/`):**
- Purpose: Define AWS resources (S3 bucket, IAM role + policy).
- Location: `infra/access_iq_infra/stacks/{s3,iam}.py`
- Depends on: `aws_cdk`, `EnvConfig`.
- Used by: `infra/app.py`.

**Infra Support Layer (`infra/access_iq_infra/{settings,tagging}.py`):**
- Purpose: Typed env config; required tag enforcement.
- Location: `infra/access_iq_infra/settings.py`, `infra/access_iq_infra/tagging.py`.

## Data Flow

### Primary Request Path — Postgres ingest

1. User runs `python -m access_iq.ingestion.cli ingest-postgres --db ehr_postgres` from repo root (`src/access_iq/ingestion/cli.py:58`).
2. `load_config()` reads `config/{ENV}.json` and resolves DSN from `os.getenv(src.dsn_env)` (`src/access_iq/ingestion/cli.py:36`).
3. `ingest_postgres_source_to_bronze` mints `run_id = uuid.uuid4()` and builds manifest prefix (`src/access_iq/ingestion/postgres.py:86`).
4. `should_skip_if_already_successful` lists manifests under `_manifests/source=<db>/ingest_date=...` and short-circuits on prior success (`src/access_iq/ingestion/idempotency.py:19`).
5. Per table: `psycopg2` connects, runs `COPY (SELECT * FROM <t>) TO STDOUT WITH CSV HEADER`, buffered in memory by `_copy_stream` (`src/access_iq/ingestion/postgres.py:179`).
6. `s3.upload_fileobj` writes `bronze/source=<db>/entity=<table>/ingest_date=.../run_id=.../<table>.csv` (`src/access_iq/ingestion/postgres.py:47`).
7. After all tables (or first failure when `fail_fast`), aggregate manifest is `put_object`-ed to `_manifests/.../run_id=<uuid>.json` (`src/access_iq/ingestion/postgres.py:169`).

### SFTP flow

1. CLI resolves host/user/password from env vars named in config (`src/access_iq/ingestion/cli.py:106`).
2. `paramiko.Transport` opens connection; `sftp.listdir(remote_dir)` enumerated and sorted (`src/access_iq/ingestion/sftp.py:83`).
3. Each file fully read into memory, sha256-digested, uploaded as `bronze/source=<src>/entity=appointments/ingest_date=.../run_id=.../files/<fname>` (`src/access_iq/ingestion/sftp.py:105`).
4. Manifest with per-file `FileResult` rows written to `_manifests/...` (`src/access_iq/ingestion/sftp.py:172`).

### Trust S3 flow

1. CLI builds a boto3 session under the Trust profile (`src/access_iq/ingestion/cli.py:143`).
2. `ingest_trust_provider_ref_to_bronze` issues a single `s3.copy_object` (server-side) for the providers xlsx (`src/access_iq/ingestion/trust_s3.py:61`).
3. `ingest_trust_diagnostics_export_date_to_bronze` translates `YYYY-MM-DD` -> `YYYYMMDD`, paginates `list_objects_v2` under `<prefix_root>/export_date=YYYYMMDD/`, and copies each (`src/access_iq/ingestion/trust_s3.py:134`).
4. Manifests written via `_put_manifest` helper (`src/access_iq/ingestion/trust_s3.py:15`).

**State Management:**
- No in-process mutable state. All durable state lives in S3 (Bronze objects + JSON manifests). Run identity is a per-call `uuid4`. Manifests are append-only; the latest one wins.

## Key Abstractions

**Bronze key contract:**
- Purpose: Uniform partitioning across all sources for downstream Silver/Gold.
- Examples: `src/access_iq/ingestion/postgres.py:32`, `src/access_iq/ingestion/sftp.py:109`, `src/access_iq/ingestion/trust_s3.py:55`.
- Pattern: `bronze/source=<src>/entity=<ent>/ingest_date=YYYY-MM-DD/run_id=<uuid>/<file>`.

**Manifest:**
- Purpose: Run record + idempotency token.
- Examples: `src/access_iq/ingestion/postgres.py:145`, `src/access_iq/ingestion/sftp.py:151`, `src/access_iq/ingestion/trust_s3.py:72`.
- Pattern: JSON `{source, env, run_id, ingest_date, started_at, finished_at, status, error, inputs, outputs}` at `_manifests/source=<src>/ingest_date=.../run_id=<uuid>.json`.

**Config (runtime):**
- Purpose: Source catalogue and platform pointer; pydantic validation at load.
- Examples: `src/access_iq/ingestion/cli.py:21` (`PostgresSource`, `Config`).
- Pattern: JSON file + env-var indirection (`*_env` keys point at env var names).

**EnvConfig (infra):**
- Purpose: Frozen dataclass capturing per-env account, region, tags, IAM, S3 settings.
- Examples: `infra/access_iq_infra/settings.py:7`.
- Pattern: Loaded once in `app.py`, passed to every stack.

## Entry Points

**Ingestion CLI:**
- Location: `src/access_iq/ingestion/cli.py` (`main`).
- Triggers: Manual invocation; future ECS Fargate task.
- Responsibilities: Parse subcommand + flags, load config, dispatch to ingestor, print final status line.

**CDK app:**
- Location: `infra/app.py`.
- Triggers: `cdk synth|diff|deploy|destroy -c env=<env>` (via `make infra-*`).
- Responsibilities: Validate env context, load `EnvConfig`, apply tags, instantiate stacks.

## Architectural Constraints

- **Runtime:** Single-process, single-threaded ingestion. No concurrency primitives in any module. Each ingestion module fully serialises its work loop.
- **Memory:** Postgres `_copy_stream` and SFTP `f.read()` buffer entire payloads in memory (`src/access_iq/ingestion/postgres.py:179`, `src/access_iq/ingestion/sftp.py:106`). Bounded by current dataset size.
- **CWD-coupled config:** `load_config` resolves `Path.cwd() / "config" / f"{env}.json"` — CLI must run from repo root (`src/access_iq/ingestion/cli.py:41`).
- **Two config trees:** Runtime config (`config/`) and infra config (`infra/config/`) are separate and must not be conflated.
- **IAM scope:** Ingestion role policy is prefix-scoped to `bronze/*` and `_manifests/*` only (`infra/access_iq_infra/stacks/iam.py:67`). Silver/Gold writes belong to a different role yet to be created.
- **Tag enforcement:** `apply_tags` raises if any of `Environment`, `Project`, `ManagedBy`, `CostCenter` are missing (`infra/access_iq_infra/tagging.py:4`).
- **Env validation:** `app.py` rejects any `env` value other than `dev`/`prod`; `load_env_config` cross-checks the JSON's `env_name` matches the requested env (`infra/access_iq_infra/settings.py:32`).
- **No global state:** No module-level singletons. Boto3 sessions/clients are constructed per call.

## Anti-Patterns

### Buffering large COPY output in memory

**What happens:** `_copy_stream` reads the full `COPY` output into a `BytesIO` before upload (`src/access_iq/ingestion/postgres.py:179`).
**Why it's wrong:** Memory grows linearly with table size; large EHR tables will OOM in ECS.
**Do this instead:** Pipe `cursor.copy_expert` into a `multipart upload` writer or use a duplex pipe (`os.pipe`) to stream directly to S3.

### Reading entire SFTP files into memory

**What happens:** `with sftp.open(...) as f: data = f.read()` (`src/access_iq/ingestion/sftp.py:106`).
**Why it's wrong:** Same memory risk as above; sha256 also computed on the in-memory blob.
**Do this instead:** Stream-read into `hashlib.sha256().update(...)` while feeding S3 multipart parts.

### Stringly-typed env-var indirection

**What happens:** SFTP config dict uses raw string keys (`host_env`, `port_env`, ...) and CLI does `dict[str, str]` lookups with manual `KeyError` handling (`src/access_iq/ingestion/cli.py:106`).
**Why it's wrong:** No schema, easy to typo, no IDE help.
**Do this instead:** Promote to a pydantic `SftpSource` model alongside `PostgresSource` (`src/access_iq/ingestion/cli.py:21`).

### CWD-relative config path

**What happens:** `Path.cwd() / "config" / f"{env}.json"` (`src/access_iq/ingestion/cli.py:41`).
**Why it's wrong:** Silently breaks if the CLI is invoked from any other directory (cron, ECS task working dir, etc.).
**Do this instead:** Resolve relative to a known anchor (e.g. an env var `ACCESS_IQ_CONFIG_DIR`, or a path passed by `argparse`).

## Error Handling

**Strategy:** Per-item `try/except Exception`, recording `{type, message}` into the manifest. The run-level `status` flips to `failed` on any failure. `fail_fast` (default `True` in modules, `False` from CLI) controls whether the loop breaks on first error.

**Patterns:**
- Catch broad `Exception`; format as `f"{type(e).__name__}: {e}"` (`src/access_iq/ingestion/postgres.py:123`, `sftp.py:128`, `trust_s3.py:172`).
- Always emit a manifest, even on failure — the manifest is the source of truth.
- Manifest decode errors in `idempotency` log a warning and return `False` (do not skip) (`src/access_iq/ingestion/idempotency.py:30`).
- CLI uses `raise SystemExit("...")` for missing config / env vars (`src/access_iq/ingestion/cli.py:75`).

## Cross-Cutting Concerns

**Logging:** `print()` only. No structured logger configured anywhere in the runtime. CloudWatch will receive stdout when running on ECS.
**Validation:** Pydantic models in CLI (`Config`, `PostgresSource`); dataclass `FileResult` for SFTP results; `EnvConfig` frozen dataclass for infra. No Great Expectations / row-level validation yet (planned).
**Authentication:** Boto3 SSO profile name read from `AWS_PROFILE` (runtime) or `cfg.user_name` ARN principal (infra IAM role trust). Postgres DSN, SFTP creds, Trust profile are env-var-based via the `*_env` config indirection.
**Idempotency:** Manifest-listing in S3 (`should_skip_if_already_successful`); shared by all three ingestors.
**Tagging:** Enforced once in `apply_tags(app, cfg.tags)`; cascades to every stack/resource via CDK aspects.

---

*Architecture analysis: 2026-05-08*
