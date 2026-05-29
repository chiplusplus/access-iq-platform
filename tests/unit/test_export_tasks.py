"""Tests for Gold Parquet export via Redshift UNLOAD."""

from __future__ import annotations

import sys
import types
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

# Stub prefect before importing flow modules
_PREFECT = types.ModuleType("prefect")
_PREFECT.task = lambda **kw: (lambda f: f)
sys.modules.setdefault("prefect", _PREFECT)

# Stub psycopg2 so import succeeds without the binary installed in main venv
_PSYCOPG2 = types.ModuleType("psycopg2")
_PSYCOPG2.connect = MagicMock()
sys.modules.setdefault("psycopg2", _PSYCOPG2)

from access_iq_flows.export_tasks import (  # noqa: E402
    GOLD_TABLES,
    _validate_export_date,
    export_gold_to_s3,
)


class TestExportTasks:
    def test_unload_prefix_format(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """export_gold_to_s3 issues one UNLOAD per Gold table with correct S3 prefix."""
        monkeypatch.setenv("PLATFORM_BUCKET", "test-bucket")
        monkeypatch.setenv("SPECTRUM_ROLE_ARN", "arn:aws:iam::123456789012:role/spectrum")
        monkeypatch.setenv("REDSHIFT_DSN", "postgresql://user:pass@host/db")

        mock_cursor = MagicMock()
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        with patch("access_iq_flows.export_tasks.psycopg2.connect", return_value=mock_conn):
            export_gold_to_s3(run_date="2026-05-29")

        assert mock_cursor.execute.call_count == len(GOLD_TABLES)

        # First table is fct_wait_times
        first_sql = mock_cursor.execute.call_args_list[0][0][0]
        assert "gold_export/table=fct_wait_times/export_date=2026-05-29/" in first_sql
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
