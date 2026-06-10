import importlib
import inspect
import pathlib
import sys
import types

import pytest

INGESTION_MODULES = [
    "access_iq.ingestion.cli",
    "access_iq.ingestion.idempotency",
    "access_iq.ingestion.postgres",
    "access_iq.ingestion.sftp",
    "access_iq.ingestion.trust_s3",
]


def _ensure_stub(name: str) -> None:
    if name in sys.modules:
        return
    module = types.ModuleType(name)
    module.__dict__.setdefault("__all__", [])
    sys.modules[name] = module


@pytest.fixture(autouse=True)
def stub_optional_third_party_modules():
    # Common optional deps used in ingestion code paths.
    for mod_name in [
        "boto3",
        "botocore",
        "botocore.client",
        "botocore.exceptions",
        "paramiko",
        "psycopg2",
        "psycopg2.extras",
        "sqlalchemy",
        "sqlalchemy.engine",
        "pandas",
        "s3fs",
        "typer",
        "click",
    ]:
        _ensure_stub(mod_name)
    yield


@pytest.mark.parametrize("module_name", INGESTION_MODULES)
def test_ingestion_modules_import(module_name):
    try:
        mod = importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        # Skip only for missing optional third-party deps.
        if exc.name is None or not exc.name.startswith("access_iq"):
            pytest.skip(f"Optional dependency missing for {module_name}: {exc.name}")
        raise
    assert mod is not None
    assert mod.__name__ == module_name


def test_ingestion_source_files_exist_and_parse():
    base = pathlib.Path(__file__).resolve().parents[2] / "src" / "access_iq" / "ingestion"
    expected_files = ["cli.py", "idempotency.py", "postgres.py", "sftp.py", "trust_s3.py"]

    for filename in expected_files:
        p = base / filename
        assert p.exists(), f"Missing source file: {p}"
        source = p.read_text(encoding="utf-8")
        assert source.strip(), f"Empty source file: {p}"
        compile(source, str(p), "exec")


def test_cli_has_some_entrypoint_shape():
    mod = importlib.import_module("access_iq.ingestion.cli")
    candidates = ("main", "cli", "app", "run")
    found = [name for name in candidates if hasattr(mod, name)]
    assert found, "Expected at least one CLI entrypoint candidate (main/cli/app/run)"


def test_idempotency_candidate_function_is_deterministic_if_present():
    mod = importlib.import_module("access_iq.ingestion.idempotency")
    candidate_names = [
        "generate_idempotency_key",
        "make_idempotency_key",
        "build_idempotency_key",
        "compute_hash",
        "sha256",
    ]
    fn = next(
        (getattr(mod, name) for name in candidate_names if callable(getattr(mod, name, None))), None
    )
    if fn is None:
        pytest.skip("No known idempotency helper function name found.")

    sig = inspect.signature(fn)
    required = [
        p
        for p in sig.parameters.values()
        if p.default is inspect._empty and p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
    ]
    if len(required) != 1:
        pytest.skip("Candidate function does not have a single required positional argument.")

    arg = "sample-input"
    first = fn(arg)
    second = fn(arg)
    assert first == second
