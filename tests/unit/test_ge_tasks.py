"""Tests for GE validation gate task."""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock, patch

import pytest

# Stub prefect before importing flow modules
_PREFECT = sys.modules.get("prefect") or types.ModuleType("prefect")
_PREFECT.flow = lambda **kw: (lambda f: f)  # type: ignore[attr-defined]
_PREFECT.task = lambda **kw: (lambda f: f)  # type: ignore[attr-defined]
sys.modules.setdefault("prefect", _PREFECT)

# Stub boto3 so it doesn't need real AWS credentials

from access_iq_flows.ge_tasks import run_ge_gate  # noqa: E402


def _make_ge_result(table_name: str, status: str) -> MagicMock:
    r = MagicMock()
    r.table_name = table_name
    r.run_status = status
    r.run_id = "test-run-id-9999"
    return r


class TestGeTasks:
    def _mock_ge_module(self, statuses: dict[str, str]) -> MagicMock:
        """Build a mock run_ge_gate module with controlled result statuses."""
        results = [_make_ge_result(t, s) for t, s in statuses.items()]
        mod = MagicMock()
        mod.run_ge_validation.return_value = results
        mod.write_results_to_redshift = MagicMock()
        mod.write_results_to_s3 = MagicMock(return_value="_dq/x/ge_results.json")
        return mod

    def test_ge_gate_raises_on_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """run_ge_gate raises RuntimeError when any Silver table fails GE validation."""
        monkeypatch.setenv("REDSHIFT_DSN", "postgresql://user:pass@host/db")
        monkeypatch.setenv("PLATFORM_BUCKET", "test-bucket")

        mock_mod = self._mock_ge_module({"patients": "PASSED", "encounters": "FAILED"})

        with patch("access_iq_flows.ge_tasks._load_ge_gate_module", return_value=mock_mod):
            with patch("access_iq_flows.ge_tasks.boto3.client", return_value=MagicMock()):
                with pytest.raises(RuntimeError, match="encounters"):
                    run_ge_gate()

    def test_ge_gate_passes_on_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """run_ge_gate completes without raising when all tables pass."""
        monkeypatch.setenv("REDSHIFT_DSN", "postgresql://user:pass@host/db")
        monkeypatch.setenv("PLATFORM_BUCKET", "test-bucket")

        mock_mod = self._mock_ge_module(
            {"patients": "PASSED", "encounters": "PASSED", "referrals": "PASSED"}
        )

        with patch("access_iq_flows.ge_tasks._load_ge_gate_module", return_value=mock_mod):
            with patch("access_iq_flows.ge_tasks.boto3.client", return_value=MagicMock()):
                run_ge_gate()  # should not raise

    def test_ge_gate_writes_results(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """run_ge_gate calls write_results_to_redshift and write_results_to_s3."""
        monkeypatch.setenv("REDSHIFT_DSN", "postgresql://user:pass@host/db")
        monkeypatch.setenv("PLATFORM_BUCKET", "test-bucket")

        mock_mod = self._mock_ge_module({"patients": "PASSED"})

        with patch("access_iq_flows.ge_tasks._load_ge_gate_module", return_value=mock_mod):
            with patch("access_iq_flows.ge_tasks.boto3.client", return_value=MagicMock()):
                run_ge_gate()

        mock_mod.write_results_to_redshift.assert_called_once()
        mock_mod.write_results_to_s3.assert_called_once()
