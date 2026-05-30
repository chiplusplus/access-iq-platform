"""Tests for daily_ingest flow chain ordering and failure propagation."""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Stub prefect before importing any flow module
# ---------------------------------------------------------------------------

_PREFECT = types.ModuleType("prefect")
_PREFECT.flow = lambda **kw: (lambda f: f)  # type: ignore[attr-defined]
_PREFECT.task = lambda **kw: (lambda f: f)  # type: ignore[attr-defined]
sys.modules.setdefault("prefect", _PREFECT)


# wait() is called with a list of futures; stub it to call .result() on each
# so that any future raising an exception propagates the error.
def _wait_stub(futures):
    for f in futures:
        f.result()


_PREFECT_FUTURES = types.ModuleType("prefect.futures")
_PREFECT_FUTURES.wait = _wait_stub  # type: ignore[attr-defined]
sys.modules["prefect.futures"] = _PREFECT_FUTURES

# Stub dbt.cli.main to avoid dbt installation requirement
_DBT = types.ModuleType("dbt")
_DBT_CLI = types.ModuleType("dbt.cli")
_DBT_CLI_MAIN = types.ModuleType("dbt.cli.main")
_DBT_CLI_MAIN.dbtRunner = MagicMock()  # type: ignore[attr-defined]
_DBT_CLI_MAIN.dbtRunnerResult = MagicMock()  # type: ignore[attr-defined]
sys.modules.setdefault("dbt", _DBT)
sys.modules.setdefault("dbt.cli", _DBT_CLI)
sys.modules.setdefault("dbt.cli.main", _DBT_CLI_MAIN)

# Stub redshift_connector
_REDSHIFT_CONNECTOR = types.ModuleType("redshift_connector")
_REDSHIFT_CONNECTOR.connect = MagicMock()  # type: ignore[attr-defined]
sys.modules.setdefault("redshift_connector", _REDSHIFT_CONNECTOR)

# ---------------------------------------------------------------------------
# Now import flow module (prefect stubs are in place)
# ---------------------------------------------------------------------------

from access_iq_flows.daily_ingest import (  # noqa: E402
    daily_ingest,
)


def _make_successful_future(value=None) -> MagicMock:
    """Return a mock future whose .result() returns value."""
    f = MagicMock()
    f.result.return_value = value
    return f


def _make_failing_future(exc: Exception) -> MagicMock:
    """Return a mock future whose .result() raises exc."""
    f = MagicMock()
    f.result.side_effect = exc
    return f


class TestDailyIngestChain:
    def test_all_steps_called_in_order(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """daily_ingest submits 3 concurrent ingestion tasks then runs dbt/GE/export sequentially."""
        monkeypatch.setenv("ACCESS_IQ_PLATFORM_BUCKET", "test-bucket")

        call_order: list[str] = []

        pg_future = _make_successful_future({"ehr": {}})
        sftp_future = _make_successful_future({"sftp_appointments": {}})
        s3_future = _make_successful_future({"diagnostics": {}, "provider_ref": {}})

        def mock_pg_submit(**kw):
            call_order.append("submit_postgres")
            return pg_future

        def mock_sftp_submit(**kw):
            call_order.append("submit_sftp")
            return sftp_future

        def mock_s3_submit(**kw):
            call_order.append("submit_trust_s3")
            return s3_future

        def mock_dbt_spectrum():
            call_order.append("dbt_spectrum")

        def mock_dbt_silver():
            call_order.append("dbt_silver")

        def mock_ge_gate():
            call_order.append("ge_gate")

        def mock_dbt_gold():
            call_order.append("dbt_gold")

        def mock_export(**kw):
            call_order.append("export_gold")

        with (
            patch("access_iq_flows.daily_ingest.task_ingest_postgres") as mock_pg,
            patch("access_iq_flows.daily_ingest.task_ingest_sftp") as mock_sftp,
            patch("access_iq_flows.daily_ingest.task_ingest_trust_s3") as mock_s3,
            patch("access_iq_flows.daily_ingest.run_dbt_spectrum", side_effect=mock_dbt_spectrum),
            patch("access_iq_flows.daily_ingest.run_dbt_silver", side_effect=mock_dbt_silver),
            patch("access_iq_flows.daily_ingest.run_ge_gate", side_effect=mock_ge_gate),
            patch("access_iq_flows.daily_ingest.run_dbt_gold", side_effect=mock_dbt_gold),
            patch(
                "access_iq_flows.daily_ingest.export_gold_to_s3",
                side_effect=mock_export,
            ),
        ):
            mock_pg.submit = mock_pg_submit
            mock_sftp.submit = mock_sftp_submit
            mock_s3.submit = mock_s3_submit

            daily_ingest(run_date="2026-01-15", env="dev")

        # All 3 ingestion submits happen before sequential steps
        assert "submit_postgres" in call_order
        assert "submit_sftp" in call_order
        assert "submit_trust_s3" in call_order

        # Sequential steps follow ingestion
        assert call_order.index("dbt_spectrum") > call_order.index("submit_postgres")
        assert call_order.index("dbt_silver") > call_order.index("dbt_spectrum")
        assert call_order.index("ge_gate") > call_order.index("dbt_silver")
        assert call_order.index("dbt_gold") > call_order.index("ge_gate")
        assert call_order.index("export_gold") > call_order.index("dbt_gold")

    def test_ingestion_failure_propagates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """daily_ingest propagates RuntimeError when an ingestion future fails."""
        monkeypatch.setenv("ACCESS_IQ_PLATFORM_BUCKET", "test-bucket")

        failing_future = _make_failing_future(RuntimeError("postgres connection failed"))
        ok_future = _make_successful_future({})

        with (
            patch("access_iq_flows.daily_ingest.task_ingest_postgres") as mock_pg,
            patch("access_iq_flows.daily_ingest.task_ingest_sftp") as mock_sftp,
            patch("access_iq_flows.daily_ingest.task_ingest_trust_s3") as mock_s3,
            patch("access_iq_flows.daily_ingest.run_dbt_spectrum"),
            patch("access_iq_flows.daily_ingest.run_dbt_silver"),
            patch("access_iq_flows.daily_ingest.run_ge_gate"),
            patch("access_iq_flows.daily_ingest.run_dbt_gold"),
            patch("access_iq_flows.daily_ingest.export_gold_to_s3"),
        ):
            mock_pg.submit = MagicMock(return_value=failing_future)
            mock_sftp.submit = MagicMock(return_value=ok_future)
            mock_s3.submit = MagicMock(return_value=ok_future)

            with pytest.raises(RuntimeError, match="postgres connection failed"):
                daily_ingest(run_date="2026-01-15", env="dev")

    def test_invalid_run_date_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """daily_ingest raises ValueError for non-ISO run_date strings."""
        monkeypatch.setenv("ACCESS_IQ_PLATFORM_BUCKET", "test-bucket")

        with pytest.raises(ValueError):
            daily_ingest(run_date="not-a-date", env="dev")
