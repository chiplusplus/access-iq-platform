"""Tests for GE results S3 publishing.

Validates:
- Results JSON published to s3://<bucket>/_dq/<run_id>/ge_results.json
- JSON contains all table results with correct schema
- S3 key follows _dq/<run_id>/ prefix convention

Note: great_expectations and psycopg2 are not installed in the dev venv (they live in
the flows subpackage, installed only in Phase 7). All GE + psycopg2 imports are
patched at sys.modules level before the script module is loaded.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# Stub out heavy third-party deps before loading the script module.
# test_ge_gate.py may have already registered these; use setdefault to avoid
# double-registration if both test files run in the same pytest session.
# ---------------------------------------------------------------------------

_GX_STUB = sys.modules.get("great_expectations") or types.ModuleType("great_expectations")
if not hasattr(_GX_STUB, "get_context"):
    _GX_STUB.get_context = MagicMock()  # type: ignore[attr-defined]
    _GX_STUB.core = types.SimpleNamespace(  # type: ignore[attr-defined]
        ExpectationSuite=MagicMock(),
        ValidationDefinition=MagicMock(),
    )
    _GX_STUB.expectations = types.SimpleNamespace(  # type: ignore[attr-defined]
        ExpectTableRowCountToBeBetween=MagicMock(),
        ExpectColumnValuesToNotBeNull=MagicMock(),
        ExpectColumnDistinctValuesToBeInSet=MagicMock(),
    )
    _GX_STUB.Checkpoint = MagicMock()  # type: ignore[attr-defined]

_PSYCOPG2_STUB = sys.modules.get("psycopg2") or types.ModuleType("psycopg2")
if not hasattr(_PSYCOPG2_STUB, "connect"):
    _PSYCOPG2_STUB.connect = MagicMock()  # type: ignore[attr-defined]

sys.modules.setdefault("great_expectations", _GX_STUB)
sys.modules.setdefault("psycopg2", _PSYCOPG2_STUB)

# ---------------------------------------------------------------------------
# Load the script module
# ---------------------------------------------------------------------------

_SCRIPT = Path(__file__).resolve().parents[2] / "dbt" / "scripts" / "run_ge_gate.py"
# Reuse already-loaded module if test_ge_gate.py ran first in the same session
if "run_ge_gate" in sys.modules:
    _mod = sys.modules["run_ge_gate"]
else:
    _spec = importlib.util.spec_from_file_location("run_ge_gate", _SCRIPT)
    _mod = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
    sys.modules["run_ge_gate"] = _mod  # required so @dataclass can resolve __module__
    _spec.loader.exec_module(_mod)  # type: ignore[union-attr]

GERunResult = _mod.GERunResult
write_results_to_s3 = _mod.write_results_to_s3
SILVER_TABLES = _mod.SILVER_TABLES

RUN_ID = "abc12345-def6-7890-ghij-klmnopqrstuv"


def _make_result(table: str, status: str = "PASSED") -> GERunResult:
    return GERunResult(
        table_name=table,
        run_date="2026-05-28",
        run_status=status,
        failure_count=0,
        run_id=RUN_ID,
        details="{}",
    )


class TestS3ResultsPublish:
    """Test write_results_to_s3 function."""

    def test_publishes_json_to_correct_key(self) -> None:
        """write_results_to_s3 puts object at _dq/<run_id>/ge_results.json."""
        results = [_make_result("patients")]
        mock_s3 = MagicMock()

        returned_key = write_results_to_s3(mock_s3, "test-bucket", RUN_ID, results)

        mock_s3.put_object.assert_called_once()
        call_kwargs = mock_s3.put_object.call_args[1]
        assert call_kwargs["Bucket"] == "test-bucket"
        assert call_kwargs["Key"] == f"_dq/{RUN_ID}/ge_results.json"
        assert returned_key == f"_dq/{RUN_ID}/ge_results.json"

    def test_json_contains_all_table_results(self) -> None:
        """Published JSON has one entry per validated Silver table."""
        results = [_make_result(t) for t in SILVER_TABLES]
        mock_s3 = MagicMock()

        write_results_to_s3(mock_s3, "test-bucket", RUN_ID, results)

        call_kwargs = mock_s3.put_object.call_args[1]
        body = json.loads(call_kwargs["Body"].decode("utf-8"))
        assert len(body) == len(SILVER_TABLES)
        assert {entry["table_name"] for entry in body} == set(SILVER_TABLES)

    def test_json_schema_has_required_fields(self) -> None:
        """Each result entry has table_name, run_date, run_status, failure_count, run_id."""
        results = [_make_result(t) for t in SILVER_TABLES]
        mock_s3 = MagicMock()

        write_results_to_s3(mock_s3, "test-bucket", RUN_ID, results)

        call_kwargs = mock_s3.put_object.call_args[1]
        body = json.loads(call_kwargs["Body"].decode("utf-8"))
        required_fields = {"table_name", "run_date", "run_status", "failure_count", "run_id"}
        for entry in body:
            assert required_fields.issubset(entry.keys()), (
                f"Entry missing required fields: {required_fields - entry.keys()}"
            )
