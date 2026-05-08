# Testing Patterns

**Analysis Date:** 2026-05-08

## Test Framework

**Runner:**
- `pytest==9.0.2` (`pyproject.toml`)
- Config: `pyproject.toml` under `[tool.pytest.ini_options]`
  - `testpaths = ["tests"]`
  - `pythonpath = ["src"]`
  - `addopts = "--maxfail=1"` — first failure aborts the run

**Coverage:**
- `pytest-cov==7.0.0`
- Configured under `[tool.coverage.run]`: `source = ["access_iq"]`, `branch = true`
- `[tool.coverage.report]`: `fail_under = 70`, `show_missing = true`

**Assertion Library:**
- Built-in `assert` statements only — no extra assertion library
- `pytest.raises(...)` for expected exceptions, with `match=` for message regex (`tests/unit/test_cli.py:91`, `:117`)

**Run Commands:**
```bash
make test                                                # pytest --cov=access_iq
make ci                                                  # fmt + lint + type + test
. .venv/bin/activate && pytest tests/unit/test_postgres.py -v      # single file
. .venv/bin/activate && pytest tests/unit/test_postgres.py::test_name -v   # single test
```

CI runs the full suite on every PR and push to `main` (`.github/workflows/ci.yml`).

## Test File Organization

**Location:**
- All tests under `tests/` at repo root, separate from `src/`
- Unit tests in `tests/unit/`
- Empty `__init__.py` markers in `tests/` and `tests/unit/`

**Naming:**
- One test module per source module: `tests/unit/test_<module>.py` mirrors `src/access_iq/ingestion/<module>.py`
- Test functions: `test_<unit>_<scenario>` — e.g. `test_ingest_postgres_source_fail_fast_true_stops_on_first_error`, `test_should_skip_returns_false_when_no_manifest`. Long, sentence-style names describing scenario explicitly.

**Structure:**
```
tests/
├── __init__.py
└── unit/
    ├── __init__.py
    ├── test_cli.py
    ├── test_idempotency.py
    ├── test_ingestion.py
    ├── test_postgres.py
    ├── test_sftp.py
    └── test_trust_s3.py
```

No `tests/integration/` or `tests/e2e/` exist yet.

## Test Structure

**Suite Organization:**
- Flat function-style tests; no `class TestX:` grouping
- Module-level `Fake*` classes defined at top of file, then test functions below
- `from __future__ import annotations` at top of every test module (matches src convention)

**Standard test shape (from `tests/unit/test_postgres.py`):**
```python
def test_ingest_postgres_source_success_writes_manifest(monkeypatch):
    s3 = FakeS3()

    monkeypatch.setattr(pg.uuid, "uuid4", lambda: "run-ok")
    monkeypatch.setattr(pg, "utc_now", lambda: "now")
    monkeypatch.setattr(
        pg.boto3,
        "Session",
        lambda profile_name, region_name: FakeSession(s3),
    )
    monkeypatch.setattr(pg, "should_skip_if_already_successful", lambda **kwargs: False)
    monkeypatch.setattr(pg, "ingest_table_to_bronze", lambda **kwargs: {...})

    out = pg.ingest_postgres_source_to_bronze(
        db="ehr",
        dsn="postgres://dsn",
        tables=["patients", "visits"],
        platform_bucket="platform",
        ingest_date=date(2026, 2, 20),
        env="dev",
        aws_region="us-east-1",
    )

    assert out["status"] == "success"
    assert out["outputs"]["tables_succeeded"] == 2
```

**Patterns:**
- Arrange: build `Fake*` doubles, patch boto3/uuid/utc_now via `monkeypatch`
- Act: call public ingestion entrypoint with explicit kwargs
- Assert: verify return manifest fields AND side effects on the fake S3 (`s3.uploads`, `s3.puts`)

## Mocking

**Framework:** `pytest`'s built-in `monkeypatch` fixture only — no `unittest.mock`, no `pytest-mock`.

**Strategy: hand-rolled Fakes, not Mocks.**
- Each test module defines `Fake*` classes implementing the minimal subset of the real client surface
- Fakes record calls in lists/dicts on `self` for assertion (`self.uploads`, `self.puts`, `self.copy_calls`)

**Canonical Fakes (reuse this shape for new tests):**

`FakeS3` — the most-duplicated fake; appears in `test_postgres.py`, `test_sftp.py`, `test_trust_s3.py`, `test_idempotency.py`:
```python
class FakeS3:
    def __init__(self):
        self.uploads = []
        self.puts = []

    def upload_fileobj(self, *, Fileobj, Bucket, Key):
        self.uploads.append({"Bucket": Bucket, "Key": Key, "Body": Fileobj.read()})

    def put_object(self, **kwargs):
        self.puts.append(kwargs)
```

`FakeSession` — wraps a `FakeS3` and asserts `client("s3")` is what's requested:
```python
class FakeSession:
    def __init__(self, s3):
        self._s3 = s3
    def client(self, name):
        assert name == "s3"
        return self._s3
```

`FakePaginator` — for boto3 paginator interface (`tests/unit/test_idempotency.py:13`).

`FakeTransport` / `FakeSFTP` / `FakeRemoteFile` — paramiko stand-ins (`tests/unit/test_sftp.py:32-87`).

`FakeCursor` / `FakeConn` — psycopg2 stand-ins (`tests/unit/test_postgres.py:24-56`).

**Patching patterns:**
- Patch on the imported module symbol, not the source module:
  ```python
  monkeypatch.setattr(pg.boto3, "Session", lambda profile_name, region_name: FakeSession(s3))
  monkeypatch.setattr(pg, "should_skip_if_already_successful", lambda **kwargs: False)
  ```
- Patch `uuid.uuid4` to deterministic value: `monkeypatch.setattr(pg.uuid, "uuid4", lambda: "run-1")`
- Patch `utc_now` per module to fixed string: `monkeypatch.setattr(pg, "utc_now", lambda: "now")`
- Patch `sys.argv` to drive CLI tests: `monkeypatch.setattr(sys, "argv", ["prog", "ingest-postgres", ...])` (`tests/unit/test_cli.py:57`)
- Use `monkeypatch.setenv` / `monkeypatch.delenv` for env-var-driven code paths
- Use `monkeypatch.chdir(tmp_path)` for `load_config` tests that read from CWD (`tests/unit/test_cli.py:30`)

**Optional-dep stubbing:**
When test must run without a heavy dep installed locally, stub the top-level module before import:
```python
if "boto3" not in sys.modules:
    boto3_module = types.ModuleType("boto3")
    cast(Any, boto3_module).Session = None
    sys.modules["boto3"] = boto3_module
```
(`tests/unit/test_postgres.py:12-19`). Then `importlib.import_module("access_iq.ingestion.postgres")`.

**What to Mock:**
- All external I/O: S3, Postgres, SFTP, paramiko transport
- `uuid.uuid4` and `utc_now` for deterministic manifests
- Idempotency check (`should_skip_if_already_successful`) when testing the wrapping flow

**What NOT to Mock:**
- Pure helpers: `sha256_bytes`, `_copy_stream` — test directly with real byte inputs
- Pydantic config models — instantiate `Config` / `PostgresSource` directly
- Date/path parsing — pass real `date` and `Path` objects

## Fixtures and Factories

**Built-in fixtures used:**
- `monkeypatch` — patching, env vars, cwd, argv (universal)
- `tmp_path` — for filesystem-backed config tests (`tests/unit/test_cli.py:13`)
- `capsys` — capture stdout for CLI assertions (`tests/unit/test_cli.py:43`)

**Custom fixtures:** None defined. No `conftest.py` exists.

**Helper functions:**
- `_wire_clients(monkeypatch, s3, transport, sftp_client)` — module-private helper to set up the standard SFTP test patching (`tests/unit/test_sftp.py:90-93`). Use this pattern for repeated patching setups within a single test module.

## Coverage

**Threshold:** `fail_under = 70` enforced via `[tool.coverage.report]`.

**View Coverage:**
```bash
make test                       # prints coverage summary
. .venv/bin/activate && pytest --cov=access_iq --cov-report=html   # HTML report
```

Coverage scope: `access_iq` package only. Infra (`access_iq_infra/`) is not in coverage scope and currently has no tests.

## Test Types

**Unit Tests:**
- Scope: single function or function + its direct dependencies, with all I/O faked
- Approach: Arrange-Act-Assert with hand-rolled fakes; no real network or filesystem (except `tmp_path`)
- All current tests are this type.

**Integration Tests:** None implemented.

**E2E Tests:** None implemented.

**Infra Tests:** None — CDK stacks (`infra/access_iq_infra/stacks/`) are not unit-tested. When adding, use `aws_cdk.assertions.Template` against a synthesised stack.

## Common Patterns

**Async Testing:** Not applicable — codebase is fully synchronous.

**Error Testing:**
```python
with pytest.raises(SystemExit, match="Unknown db"):
    cli.main()
```
(`tests/unit/test_cli.py:91`)

**Side-effect verification:**
```python
assert len(s3.uploads) == 2
assert s3.uploads[0]["Bucket"] == "platform"
manifest = json.loads(s3.puts[0]["Body"].decode("utf-8"))
assert manifest["run_id"] == "run-1"
```
Always assert both the return value AND the recorded calls on the fake.

**Determinism:**
- Always patch `uuid.uuid4` and `utc_now` when the function under test embeds them in output
- Pass `date(2026, 2, 20)` as fixed `ingest_date` rather than `date.today()`

**Fail-fast paired tests:**
For any batch-ingest function, write paired tests:
- `test_..._fail_fast_true_stops_on_first_error` — counter asserts only 1 call
- `test_..._fail_fast_false_continues` — counter asserts both calls executed
Examples: `tests/unit/test_postgres.py:198-270`, `tests/unit/test_sftp.py:167-234`.

**Idempotency-skip test:**
For any new ingest entrypoint, include a `test_..._skips_when_idempotent` that patches `should_skip_if_already_successful` to `True` and asserts `out["status"] == "skipped"` and no S3 writes occurred (`tests/unit/test_sftp.py:103-124`, `tests/unit/test_postgres.py:129-153`).

---

*Testing analysis: 2026-05-08*
