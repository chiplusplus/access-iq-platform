# Codebase Concerns

**Analysis Date:** 2026-05-08

## Tech Debt

**Postgres COPY buffered fully in memory:**
- Issue: `_copy_stream` collects entire `COPY ... TO STDOUT` output into a `BytesIO` before upload. Large tables (encounters, urgent_care_logs at scale) will OOM the ECS task.
- Files: `src/access_iq/ingestion/postgres.py` (lines 179–187, see explicit `NOTE:` comment)
- Impact: Hard memory ceiling on table size; ECS Fargate task crashes on big tables; no progress/resume on failure.
- Fix approach: Use `s3.upload_part` multipart with a streaming wrapper around `cursor.copy_expert`, or pipe through a `tempfile.SpooledTemporaryFile`. Switch from `psycopg2` to `psycopg` (v3) for native server-side cursor + async streaming.

**SFTP files read fully into memory:**
- Issue: `sftp.open(remote_path, "rb").read()` loads the whole file before SHA-256 + S3 upload.
- Files: `src/access_iq/ingestion/sftp.py:106`
- Impact: Memory ceiling for large appointment drops; no resume on failure.
- Fix approach: Stream-read in chunks, update SHA-256 incrementally, use `s3.upload_fileobj` with a streaming wrapper or multipart upload.

**`error` accumulation bug in postgres ingest:**
- Issue: When a table fails, the entire growing `error` list is written into each per-table failure record (`results.append({..., "error": error, ...})`). All failed rows reference the same list, and after subsequent failures the manifest shows every prior error duplicated against later tables.
- Files: `src/access_iq/ingestion/postgres.py:123-139`
- Impact: Manifest corruption; misleading per-table error attribution.
- Fix approach: Append a single error string to the per-table record (`"error": f"{type(e).__name__}: {e}"`), keep the run-level `error` list separate.

**Mismatched error types across ingestion modules:**
- Issue: `postgres.py` stores `error` as `list[str]`; `sftp.py` and `trust_s3.py` store run-level `error` as `str`. Manifest schema is inconsistent across sources.
- Files: `src/access_iq/ingestion/postgres.py:108`, `src/access_iq/ingestion/sftp.py:81`, `src/access_iq/ingestion/trust_s3.py:138`
- Impact: Downstream Silver/dbt parsing of manifests must branch by source. Schema drift.
- Fix approach: Standardise on `list[str]` for run-level errors plus a single `error: str | None` per item.

**Connection not closed on exception in postgres ingest:**
- Issue: `conn = psycopg2.connect(...)` happens before `try`. If `cursor.close` or upload fails, conn closes via `finally`, but if `psycopg2.connect` itself succeeds and `cursor()` raises, connection leaks. Also no `with` context manager / no transaction rollback.
- Files: `src/access_iq/ingestion/postgres.py:37-54`
- Impact: Potential connection leak on Trust RDS under partial failure; exhausts max_connections.
- Fix approach: Use `with psycopg2.connect(dsn) as conn, conn.cursor() as cursor:` pattern.

**Per-table connection churn:**
- Issue: A new psycopg2 connection is opened per table inside `ingest_postgres_source_to_bronze` loop.
- Files: `src/access_iq/ingestion/postgres.py:37`, called from `postgres.py:113`
- Impact: Connection storm on RDS for sources with many tables; slower throughput.
- Fix approach: Open one connection per source, pass cursor/conn down to `ingest_table_to_bronze`.

**CLI requires repo-root CWD (implicit contract):**
- Issue: `load_config` uses `Path.cwd() / "config" / f"{env}.json"`. Running CLI from any other directory silently fails with `FileNotFoundError`. Will break inside ECS container if working directory differs.
- Files: `src/access_iq/ingestion/cli.py:36-43`
- Impact: Hard-to-diagnose runtime errors; container packaging fragility.
- Fix approach: Resolve config path relative to module (`Path(__file__).resolve().parents[3]`) or accept `--config` flag; fail fast with explicit message.

**Two parallel config trees with no validation linking them:**
- Issue: Runtime config (`config/{env}.json`) and CDK config (`infra/config/{env}.json`) duplicate concepts (env name, bucket name, account id) with no cross-validation. `platform_bucket` in `config/dev.json` is a hardcoded string not derived from `app_name-env-account_id` in `infra/config/dev.json`.
- Files: `config/dev.json:3`, `infra/config/dev.json`, `infra/access_iq_infra/stacks/s3.py:25`
- Impact: Bucket rename in CDK silently desyncs runtime CLI; ingest writes to wrong bucket or 404s.
- Fix approach: Generate runtime `platform_bucket` from CDK outputs, or share a single source-of-truth JSON.

**`infra/config/prod.json` missing required keys:**
- Issue: Loading prod env via `load_env_config` will raise `KeyError` because `user_name`, `s3`, `iam` are absent in the prod config file but `EnvConfig` constructor reads them.
- Files: `infra/config/prod.json` (only has app_name, env_name, account_id, region, tags), `infra/access_iq_infra/settings.py:38-45`
- Impact: `make infra-deploy CDK_ENV=prod` will crash before synth.
- Fix approach: Populate prod config with `user_name`, `s3`, and `iam.external_bucket`; add a unit test that loads both env configs.

**Trust S3 ingest hardcodes `entity` and ContentType:**
- Issue: `ingest_trust_diagnostics_export_date_to_bronze` always writes under `entity=diagnostics_orders` and copies with `ContentType="text/csv"` regardless of source file extension.
- Files: `src/access_iq/ingestion/trust_s3.py:150,160`
- Impact: Non-CSV files in the diagnostics prefix will be tagged with wrong MIME type; entity name not configurable for new Trust sources.
- Fix approach: Plumb entity name through config; default ContentType from filename extension.

**No retry/backoff on transient AWS or DB errors:**
- Issue: All boto3 and psycopg2 calls are bare. `s3.copy_object`, `s3.upload_fileobj`, `cursor.copy_expert`, SFTP transport—any transient throttle/timeout aborts the run.
- Files: all of `src/access_iq/ingestion/`
- Impact: Flaky runs in production; operator must re-run manually.
- Fix approach: Wrap with `tenacity` or `botocore` retry config (`Config(retries={"max_attempts": 5, "mode": "adaptive"})`).

**Ephemeral run logs only in print():**
- Issue: All status output uses `print()`. No structured logging, no log level, no JSON formatter for CloudWatch.
- Files: `src/access_iq/ingestion/cli.py`, `src/access_iq/ingestion/postgres.py:96`, `src/access_iq/ingestion/sftp.py:69`, `src/access_iq/ingestion/trust_s3.py:45,123,183`
- Impact: Hard to trace runs in CloudWatch; can't filter by run_id, source, severity.
- Fix approach: Adopt `logging` with JSON handler; bind `run_id` and `source` via `LoggerAdapter`/contextvars.

**Stray duplicated test directory at repo root:**
- Issue: `access-iq-platform/tests/unit/test_cli.py` exists as a shadow copy under a misleading subdirectory. Likely a copy/paste artefact.
- Files: `access-iq-platform/tests/unit/test_cli.py`
- Impact: Confusion; risk of edits going to the wrong file; pytest may pick it up depending on cwd.
- Fix approach: Delete the `access-iq-platform/` subdirectory at repo root.

**Deleted `infra/access_iq_infra/stacks/core.py` not yet removed from working tree:**
- Issue: `git status` shows it as deleted but uncommitted. Indicates incomplete refactor.
- Files: `infra/access_iq_infra/stacks/core.py` (deleted)
- Impact: Working tree dirty; CI may rely on commit ordering.
- Fix approach: Commit the deletion or restore.

## Known Bugs

**Idempotency "latest manifest" relies on `LastModified`, not `run_id` ordering:**
- Symptoms: If two runs land in the same second (concurrent CI runs), S3 `LastModified` granularity is 1 second and ordering between them is undefined; a failed later run can mask a successful earlier one or vice versa.
- Files: `src/access_iq/ingestion/idempotency.py:11-16`
- Trigger: Two CLI invocations within the same second for the same source+date.
- Workaround: Run ingestion serially per source+date (already implicit single-runner assumption).

**`should_skip_if_already_successful` checks the manifest *prefix* without trailing `/`:**
- Symptoms: `manifest_prefix = "_manifests/source=ehr_postgres/ingest_date=2026-05-08"` will also match `ingest_date=2026-05-08-something/...` if such a key existed.
- Files: `src/access_iq/ingestion/postgres.py:91`, `src/access_iq/ingestion/sftp.py:64`, `src/access_iq/ingestion/trust_s3.py:40,118`
- Trigger: Any future key naming that prefix-collides with an ingest_date partition.
- Workaround: Append `/` to manifest_prefix.

**Trust S3 diagnostics: empty result writes a "success" manifest:**
- Symptoms: When the Trust prefix has zero objects for `export_date`, `results` is empty and `status` stays `"success"`. The next-day idempotency check then **skips** retries even though nothing was ingested.
- Files: `src/access_iq/ingestion/trust_s3.py:136-183`
- Trigger: Trust runs late and uploads files after platform polled.
- Workaround: Run with a fresh `ingest_date`; manually delete the empty manifest. Better fix: treat `objects_written == 0` as `status="empty"` (not success) so idempotency does not short-circuit.

**`fail_fast=False` in trust_s3 still aborts the *page* after first failure:**
- Symptoms: Inner `if status == "failed" and fail_fast: break` logic sets `status="failed"` on first error but does not preserve continuation correctly when `fail_fast=False`. It should keep iterating but the run-level `error` only captures the first failure (last-write-wins issue if `fail_fast=False`).
- Files: `src/access_iq/ingestion/trust_s3.py:172-180`
- Trigger: A bad object mid-page when `fail_fast=False`.
- Workaround: Use `fail_fast=True`.

**Provider ref ingest never marks failure status:**
- Symptoms: `ingest_trust_provider_ref_to_bronze` has no `try/except` around `s3.copy_object`; on failure the manifest is never written and the function raises. No "failed" manifest is emitted, so idempotency state is "no manifest" and next run will retry — which is correct, but operator has no audit trail of the failed attempt.
- Files: `src/access_iq/ingestion/trust_s3.py:24-92`
- Trigger: Trust S3 access denied / object missing.
- Workaround: Inspect CloudWatch logs.
- Fix approach: Wrap copy in try/except, write a `status=failed` manifest on error.

**Manifest body encoding loses non-ASCII safely but with `default=str` in trust_s3 only:**
- Symptoms: `trust_s3.py` uses `json.dumps(..., default=str)`; `postgres.py` and `sftp.py` do not. If a future field is non-serialisable, only trust_s3 survives.
- Files: `src/access_iq/ingestion/trust_s3.py:19`, `postgres.py:172`, `sftp.py:177`
- Workaround: Standardise on `default=str`.

## Security Considerations

**SFTP password auth, not key auth:**
- Risk: Password-based SFTP is materially weaker than key-based; password handled in env var and passed plaintext to `paramiko.Transport.connect`.
- Files: `src/access_iq/ingestion/sftp.py:85`, `src/access_iq/ingestion/cli.py:113-115`
- Current mitigation: Password sourced from env var (presumably AWS Secrets Manager → ECS task env injection).
- Recommendations: Switch to SSH key pair auth via Secrets Manager; pin host key (currently no `set_missing_host_key_policy` — paramiko default rejects unknown hosts, but this should be explicit and pre-loaded with the Trust SFTP server's known_hosts).

**No SSH host key verification configured:**
- Risk: `paramiko.Transport(...)` does not verify the remote host key. MITM possible.
- Files: `src/access_iq/ingestion/sftp.py:83`
- Current mitigation: VPC peering between Trust and Platform restricts network path.
- Recommendations: Load known_hosts and call `transport.get_remote_server_key()` validation, or use `SSHClient` with `load_host_keys`.

**IAM role allows broad PutObject on `bronze/*`:**
- Risk: Ingestion role can overwrite arbitrary keys under `bronze/`, including manifests written by other sources. No object-key prefix scoping per source.
- Files: `infra/access_iq_infra/stacks/iam.py:58-69`
- Current mitigation: Single ingestion role used by trusted ECS tasks; bucket versioning enabled.
- Recommendations: Per-source roles or `aws:RequestTag`/`s3:RequestObjectKeyName` conditions; deny PutObject overwriting an existing key (use `s3:If-None-Match: *` once supported in the SDK call).

**`assumed_by` ARN includes a single SSO session role name:**
- Risk: `arn:aws:iam::{account}:assumed-role/{user_name}` with `user_name = "AWSReservedSSO_CHI-Engineer_56b619fe880e8582/chia"` hardcodes a specific SSO role hash that AWS rotates when the permission set is updated. Role trust will silently break after permission set change.
- Files: `infra/access_iq_infra/stacks/iam.py:35-38`, `infra/config/dev.json:5`
- Current mitigation: None.
- Recommendations: Trust the SSO permission-set boundary or parameterise via wildcard: `arn:aws:iam::{account}:assumed-role/AWSReservedSSO_CHI-Engineer_*/chia`. Or better, trust the ECS task role principal, not the human's SSO role.

**psycopg2 DSN passed via env var as a single string:**
- Risk: DSN includes password in plaintext form (`postgres://user:pw@host/db`); appears in process env and may leak via core dumps, error traces, or `ps`.
- Files: `src/access_iq/ingestion/cli.py:80`, `src/access_iq/ingestion/postgres.py:37`
- Current mitigation: `dsn_redacted: True` flag in the manifest (the manifest does not contain the DSN, just a flag).
- Recommendations: Pull connection params from Secrets Manager with `boto3.client("secretsmanager").get_secret_value(...)` at runtime; never store full DSN in env.

**Bucket lacks key-level KMS:**
- Risk: `BucketEncryption.S3_MANAGED` (SSE-S3) is fine for hygiene but not for PHI/PII. NHS data should be encrypted with a customer-managed KMS key with audit trail.
- Files: `infra/access_iq_infra/stacks/s3.py:27`
- Current mitigation: Block public access, SSL enforced, bucket-owner-enforced ownership.
- Recommendations: Use `BucketEncryption.KMS` with a CMK; grant ingestion role `kms:Encrypt`/`kms:GenerateDataKey` only.

**No bucket policy denying non-TLS or non-KMS uploads beyond defaults:**
- Risk: `enforce_ssl=True` is set, but no explicit deny statement for unencrypted PutObject (belt-and-braces for compliance).
- Files: `infra/access_iq_infra/stacks/s3.py`
- Recommendation: Add explicit deny statements; required for HIPAA/UK NHS DSP toolkit.

## Performance Bottlenecks

**Sequential per-table ingest:**
- Problem: `for table in tables:` is serial. Even small tables block on each other.
- Files: `src/access_iq/ingestion/postgres.py:110`
- Cause: No concurrency layer.
- Improvement path: Use `concurrent.futures.ThreadPoolExecutor` (boto3/psycopg2 are I/O-bound) or async with `psycopg` v3.

**Trust S3 paginator pulls Contents but does not parallelise copy_object:**
- Problem: Each `copy_object` is sequential; 100s of files = 100s of round trips.
- Files: `src/access_iq/ingestion/trust_s3.py:142-160`
- Improvement path: Threadpool the copy calls; for objects >5GB use multipart copy.

**No caching of latest-manifest probe:**
- Problem: Every CLI invocation runs a full `list_objects_v2` paginate of `_manifests/source=.../ingest_date=...` even for date partitions with few keys, but per-source it's still an extra round trip per run.
- Files: `src/access_iq/ingestion/idempotency.py:11`
- Improvement path: Use `head_object` on a deterministic "_LATEST" marker key per source+date, written atomically after each run.

**Bucket versioning + dev `auto_delete_objects=True`:**
- Problem: In dev, `RemovalPolicy.DESTROY` + `auto_delete_objects=True` triggers a custom-resource Lambda that lists+deletes all versions on stack deletion. With heavy ingestion volume, deletion can timeout (15 min).
- Files: `infra/access_iq_infra/stacks/s3.py:31-35`
- Improvement path: Add lifecycle rule expiring all current versions in dev after N days; tune `noncurrent_version_expiration` lower for dev.

## Fragile Areas

**Implicit cwd contract for CLI:**
- Files: `src/access_iq/ingestion/cli.py:41`
- Why fragile: Container/Prefect runner must `cd` to repo root before invoking. Easy to miss.
- Safe modification: See Tech Debt fix above.
- Test coverage: `tests/unit/test_cli.py` mocks the load — does not exercise cwd contract.

**Manifest schema across three sources:**
- Files: `src/access_iq/ingestion/postgres.py:145-163`, `src/access_iq/ingestion/sftp.py:151-170`, `src/access_iq/ingestion/trust_s3.py:187-205`
- Why fragile: No shared schema/dataclass; downstream consumers (dbt, GE, Streamlit) will hand-roll parsers.
- Safe modification: Extract `Manifest` pydantic model in `src/access_iq/ingestion/manifest.py`, validate before `put_object`.
- Test coverage: Each test asserts shape independently; no schema-conformance test.

**`tests/__init__.py` and `tests/unit/__init__.py` exist:**
- Files: `tests/__init__.py`, `tests/unit/__init__.py`
- Why fragile: With `pythonpath = ["src"]` and packaged tests, pytest collection can pick up the stray `access-iq-platform/tests/unit/test_cli.py` as a duplicate import (`tests.unit.test_cli` collision).
- Safe modification: Remove `__init__.py` from `tests/` dirs (pytest auto-discovers without packages) OR delete the stray copy.

**Trust S3 export_date format conversion:**
- Files: `src/access_iq/ingestion/trust_s3.py:134`
- Why fragile: Trust uses `YYYYMMDD` (no hyphens), platform manifests use `YYYY-MM-DD`. Conversion is a single inline `.replace('-', '')`. If Trust changes to ISO, code silently builds wrong prefix and finds zero objects (which is then mis-flagged success — see bug above).
- Safe modification: Centralise date formatting in a helper; assert non-empty result of paginator.

## Scaling Limits

**ECS Fargate task memory ceiling:**
- Current capacity: Memory bound by chosen task size (not yet defined in CDK).
- Limit: Postgres COPY buffered in memory will OOM on tables larger than task memory. SFTP file size similarly bounded.
- Scaling path: Streaming refactor (see Tech Debt) is the only sustainable path; raising task memory is a temporary patch.

**Single CLI process per source:**
- Current capacity: One CLI invocation = one source ingested. Three sources × N tables runs serially across CLI invocations.
- Limit: Total Bronze ingest time = sum of all source times.
- Scaling path: Parallelise at the orchestrator (Prefect) layer with one task per source; consolidate manifest write per orchestrator run.

## Dependencies at Risk

**`psycopg2-binary` 2.9.11:**
- Risk: `psycopg2` is in maintenance mode; `psycopg` (v3) is the recommended successor with native async + better streaming.
- Impact: Streaming refactor will be easier on psycopg v3.
- Migration plan: Switch to `psycopg[binary]>=3.2` when implementing streaming COPY.

**`paramiko` 4.0.0:**
- Risk: 4.x is recent and removed several long-deprecated APIs. Pinned exact version means no patch-level security updates.
- Impact: Missed CVEs.
- Migration plan: Loosen pin to `paramiko>=4,<5`.

**Exact pins everywhere:**
- Risk: Every direct dep is `==` pinned. No security updates without manual bump.
- Impact: Slow CVE response.
- Migration plan: Use `~=` for libraries with stable SemVer; keep `==` only for `aws-cdk-lib` and `constructs` (where minor versions can break synth).

## Missing Critical Features

**No streaming/large-table support:** see postgres.py and sftp.py tech debt.

**No structured logging or metrics emission:** required before ECS/Prefect operationalisation.

**No retry/dead-letter handling:** transient errors abort runs.

**No Trust CDK stack:** `CLAUDE.md` flags this; nothing in `infra/` provisions RDS, Transfer Family, Trust S3, Trust VPC.

**No VPC / networking stack:** ECS Fargate tasks have no compute/networking infrastructure yet.

**No Secrets Manager integration:** all credentials assumed in env vars; no CDK code creates secrets or grants `secretsmanager:GetSecretValue`.

**No data-quality layer:** Great Expectations and dbt are referenced in the docs but unbuilt.

**No CI integration test against LocalStack/moto:** all tests are pure unit mocks.

## Test Coverage Gaps

**Idempotency edge cases:**
- What's not tested: behaviour when two manifests have identical `LastModified`; behaviour when manifest body is truncated mid-write; behaviour when `Contents` paginates across multiple pages.
- Files: `tests/unit/test_idempotency.py`
- Risk: Subtle skipping/non-skipping bugs in production.
- Priority: High.

**Streaming and large-payload path:**
- What's not tested: `_copy_stream` is invoked with toy data; no test asserts memory-bounded behaviour.
- Files: `tests/unit/test_postgres.py`
- Risk: Silent regression on the stream/buffer boundary when refactoring.
- Priority: High when streaming refactor lands.

**SSH host key / SFTP failure paths:**
- What's not tested: connection failure, host key mismatch, permission denied during `sftp.open`.
- Files: `tests/unit/test_sftp.py`
- Risk: Operator-facing errors are unclear.
- Priority: Medium.

**CDK synth tests:**
- What's not tested: no `cdk.assertions.Template` snapshot/asserts on `PlatformBucketStack` or `IngestionRoleStack`.
- Files: none.
- Risk: IAM regressions, removal-policy regressions, encryption regressions land silently.
- Priority: High before prod deploy.

**Prod config load:**
- What's not tested: `load_env_config("prod")` is never exercised; would currently fail (see KeyError bug above).
- Files: none.
- Risk: First prod deploy crashes at synth.
- Priority: High.

**CLI argument validation:**
- What's not tested: invalid `--ingest-date`, missing env vars surfaced as `SystemExit` strings.
- Files: `tests/unit/test_cli.py` (covers happy paths).
- Risk: Operator UX.
- Priority: Low.

**Coverage threshold:** `pyproject.toml` sets `fail_under = 70` — modest. Critical paths (manifest write, idempotency) deserve 100%.

---

*Concerns audit: 2026-05-08*
