"""Tests for GE gate mechanism.

Validates:
- run_ge_gate.py exits 0 when all tables pass
- run_ge_gate.py exits 1 when any table fails
- run_ge_gate.py writes results to _dq_results table
- run_ge_gate.py handles missing REDSHIFT_DSN gracefully

Note: great_expectations and psycopg2 are not installed in the dev venv (they live in
the flows subpackage, installed only in Phase 7). All GE + psycopg2 imports are
patched at sys.modules level before the script module is loaded.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Stub out heavy third-party deps before loading the script module
# ---------------------------------------------------------------------------

_GX_STUB = types.ModuleType("great_expectations")
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

_PSYCOPG2_STUB = types.ModuleType("psycopg2")
_PSYCOPG2_STUB.connect = MagicMock()  # type: ignore[attr-defined]

sys.modules.setdefault("great_expectations", _GX_STUB)
sys.modules.setdefault("psycopg2", _PSYCOPG2_STUB)

# ---------------------------------------------------------------------------
# Load the script module
# ---------------------------------------------------------------------------

_SCRIPT = Path(__file__).resolve().parents[2] / "dbt" / "scripts" / "run_ge_gate.py"
_spec = importlib.util.spec_from_file_location("run_ge_gate", _SCRIPT)
_mod = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
sys.modules["run_ge_gate"] = _mod  # required so @dataclass can resolve __module__
_spec.loader.exec_module(_mod)  # type: ignore[union-attr]

GERunResult = _mod.GERunResult
write_results_to_redshift = _mod.write_results_to_redshift
SILVER_TABLES = _mod.SILVER_TABLES


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_result(table: str, status: str = "PASSED", failures: int = 0) -> GERunResult:
    return GERunResult(
        table_name=table,
        run_date="2026-05-28",
        run_status=status,
        failure_count=failures,
        run_id="test-run-id-1234",
        details="{}",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestGEGateExitBehavior:
    """Test run_ge_gate.py exit code logic."""

    def test_all_tables_pass_exits_zero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """GE gate exits 0 when all 4 Silver tables pass validation."""
        passing_results = [_make_result(t, "PASSED") for t in SILVER_TABLES]

        monkeypatch.setenv("REDSHIFT_DSN", "postgresql://user:pass@host/db")
        monkeypatch.setenv("PLATFORM_BUCKET", "test-bucket")

        with (
            patch.object(_mod, "run_ge_validation", return_value=passing_results),
            patch.object(_mod, "write_results_to_redshift"),
            patch.object(_mod, "write_results_to_s3", return_value="_dq/x/ge_results.json"),
            patch.object(_mod, "publish_cloudwatch_metrics"),
            patch("boto3.client"),
            pytest.raises(SystemExit) as exc_info,
        ):
            _mod.main()

        assert exc_info.value.code == 0

    def test_any_table_fails_exits_one(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """GE gate exits 1 when any Silver table fails validation."""
        mixed_results = [
            _make_result("patients", "PASSED"),
            _make_result("encounters", "FAILED", failures=2),
            _make_result("referrals", "PASSED"),
            _make_result("diagnoses", "PASSED"),
        ]

        monkeypatch.setenv("REDSHIFT_DSN", "postgresql://user:pass@host/db")
        monkeypatch.setenv("PLATFORM_BUCKET", "test-bucket")

        with (
            patch.object(_mod, "run_ge_validation", return_value=mixed_results),
            patch.object(_mod, "write_results_to_redshift"),
            patch.object(_mod, "write_results_to_s3", return_value="_dq/x/ge_results.json"),
            patch.object(_mod, "publish_cloudwatch_metrics"),
            patch("boto3.client"),
            pytest.raises(SystemExit) as exc_info,
        ):
            _mod.main()

        assert exc_info.value.code == 1

    def test_missing_dsn_uses_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """GE gate builds DSN from REDSHIFT_HOST/USER/PASSWORD when REDSHIFT_DSN absent."""
        monkeypatch.delenv("REDSHIFT_DSN", raising=False)
        monkeypatch.setenv("REDSHIFT_HOST", "localhost")
        monkeypatch.setenv("REDSHIFT_USER", "admin")
        monkeypatch.setenv("REDSHIFT_PASSWORD", "secret")
        monkeypatch.setenv("PLATFORM_BUCKET", "test-bucket")

        passing_results = [_make_result(t, "PASSED") for t in SILVER_TABLES]

        with (
            patch.object(_mod, "run_ge_validation", return_value=passing_results),
            patch.object(_mod, "write_results_to_redshift"),
            patch.object(_mod, "write_results_to_s3", return_value="_dq/x/ge_results.json"),
            patch.object(_mod, "publish_cloudwatch_metrics"),
            patch("boto3.client"),
            pytest.raises(SystemExit) as exc_info,
        ):
            _mod.main()

        assert exc_info.value.code == 0

    def test_missing_bucket_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """GE gate raises RuntimeError when no bucket can be resolved."""
        monkeypatch.setenv("REDSHIFT_DSN", "postgresql://user:pass@host/db")
        monkeypatch.delenv("PLATFORM_BUCKET", raising=False)
        monkeypatch.delenv("BRONZE_S3_PREFIX", raising=False)

        passing_results = [_make_result(t, "PASSED") for t in SILVER_TABLES]

        with (
            patch.object(_mod, "run_ge_validation", return_value=passing_results),
            patch.object(_mod, "write_results_to_redshift"),
            pytest.raises(RuntimeError, match="PLATFORM_BUCKET"),
        ):
            _mod.main()


class TestGEResultsWrite:
    """Test _dq_results table write logic."""

    def test_writes_one_row_per_table(self) -> None:
        """write_results_to_redshift inserts one row per validated table."""
        results = [_make_result(t) for t in SILVER_TABLES]

        mock_cursor = MagicMock()
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        with patch("psycopg2.connect", return_value=mock_conn):
            write_results_to_redshift("postgresql://user:pass@host/db", results)

        # One CREATE TABLE IF NOT EXISTS + one INSERT per table
        assert mock_cursor.execute.call_count == 1 + len(SILVER_TABLES)

    def test_creates_table_if_not_exists(self) -> None:
        """write_results_to_redshift issues CREATE TABLE IF NOT EXISTS."""
        results = [_make_result("patients")]

        mock_cursor = MagicMock()
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        with patch("psycopg2.connect", return_value=mock_conn):
            write_results_to_redshift("postgresql://user:pass@host/db", results)

        first_call_sql: str = mock_cursor.execute.call_args_list[0][0][0]
        assert "CREATE TABLE IF NOT EXISTS" in first_call_sql
        assert "gold._dq_results" in first_call_sql
