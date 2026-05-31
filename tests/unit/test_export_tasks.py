"""Tests for Gold Parquet export via Redshift UNLOAD."""

from __future__ import annotations

import sys
import types
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

# Stub prefect before importing flow modules
_PREFECT = types.ModuleType("prefect")
_PREFECT.flow = lambda **kw: (lambda f: f)  # type: ignore[attr-defined]
_PREFECT.task = lambda **kw: (lambda f: f)  # type: ignore[attr-defined]
sys.modules.setdefault("prefect", _PREFECT)

# Stub redshift_connector so import succeeds without the package installed in main venv
_REDSHIFT_CONNECTOR = types.ModuleType("redshift_connector")
_REDSHIFT_CONNECTOR.connect = MagicMock()  # type: ignore[attr-defined]
sys.modules.setdefault("redshift_connector", _REDSHIFT_CONNECTOR)

from access_iq_flows.export_tasks import (  # noqa: E402
    GOLD_TABLES,
    _validate_export_date,
    export_gold_to_s3,
)


class TestExportTasks:
    def test_unload_prefix_format(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """export_gold_to_s3 issues one UNLOAD per Gold table with correct S3 prefix."""
        monkeypatch.setenv("PLATFORM_BUCKET", "test-bucket")
        monkeypatch.setenv("REDSHIFT_SPECTRUM_ROLE_ARN", "arn:aws:iam::123456789012:role/spectrum")
        monkeypatch.setenv("REDSHIFT_HOST", "host")
        monkeypatch.setenv("REDSHIFT_USER", "user")
        monkeypatch.setenv("REDSHIFT_PASSWORD", "pass")

        mock_cursor = MagicMock()
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        with patch(
            "access_iq_flows.export_tasks.redshift_connector.connect", return_value=mock_conn
        ):
            export_gold_to_s3(run_date="2026-05-29")

        assert mock_cursor.execute.call_count == len(GOLD_TABLES)

        # First table alphabetically is dim_date (GOLD_TABLES is a sorted frozenset)
        first_sql = mock_cursor.execute.call_args_list[0][0][0]
        assert "gold_export/table=dim_date/export_date=2026-05-29/" in first_sql
        assert "FORMAT AS PARQUET" in first_sql
        assert "PARALLEL OFF" in first_sql

    def test_validate_export_date_rejects_invalid(self) -> None:
        """_validate_export_date raises ValueError for non-ISO strings."""
        with pytest.raises(ValueError):
            _validate_export_date("not-a-date")

    def test_validate_export_date_accepts_valid(self) -> None:
        """_validate_export_date returns the string unchanged for valid ISO dates."""
        result = _validate_export_date("2026-05-29")
        assert result == "2026-05-29"

    def test_validate_export_date_defaults_to_today(self) -> None:
        """_validate_export_date returns today's ISO date when run_date is None."""
        result = _validate_export_date(None)
        assert result == date.today().isoformat()
