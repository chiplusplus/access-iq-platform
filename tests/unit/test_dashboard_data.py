"""Unit tests for dashboard data layer."""

from __future__ import annotations

import subprocess
import sys
import types
from unittest.mock import MagicMock, patch

import pytest

# Stub streamlit before importing dashboard modules
_ST = types.ModuleType("streamlit")


def _passthrough_decorator(*args, **kw):  # type: ignore[no-untyped-def]
    """Stub decorator that handles both @decorator and @decorator(...) forms."""
    if args and callable(args[0]):
        return args[0]
    return lambda f: f


_ST.cache_data = _passthrough_decorator  # type: ignore[attr-defined]
_ST.cache_resource = _passthrough_decorator  # type: ignore[attr-defined]
_ST.secrets = {}  # type: ignore[attr-defined]
sys.modules.setdefault("streamlit", _ST)

# Stub structlog
_STRUCTLOG = types.ModuleType("structlog")
_STRUCTLOG.get_logger = lambda *a, **kw: MagicMock()  # type: ignore[attr-defined]
sys.modules.setdefault("structlog", _STRUCTLOG)

from dashboard.lib.s3 import (  # noqa: E402
    GOLD_TABLES,
    get_data_source,
    list_local_export_dates,
    parquet_path,
)


class TestGetDataSource:
    """Tests for get_data_source() function."""

    def test_local_when_env_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """DATA_SOURCE=local returns 'local' (D-18)."""
        monkeypatch.setenv("DATA_SOURCE", "local")
        assert get_data_source() == "local"

    def test_s3_when_secrets_present(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Returns 's3' when st.secrets has AWS_ACCESS_KEY_ID."""
        monkeypatch.delenv("DATA_SOURCE", raising=False)
        mock_secrets = MagicMock()
        mock_secrets.get.return_value = "AKIAEXAMPLE"
        with patch("dashboard.lib.s3.st") as mock_st:
            mock_st.secrets = mock_secrets
            assert get_data_source() == "s3"

    def test_local_when_no_secrets(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Returns 'local' when st.secrets has no AWS key."""
        monkeypatch.delenv("DATA_SOURCE", raising=False)
        mock_secrets = MagicMock()
        mock_secrets.get.return_value = ""
        with patch("dashboard.lib.s3.st") as mock_st:
            mock_st.secrets = mock_secrets
            assert get_data_source() == "local"


class TestParquetPath:
    """Tests for parquet_path() function."""

    def test_s3_path_format(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """S3 mode returns correct s3:// path."""
        monkeypatch.delenv("DATA_SOURCE", raising=False)
        with patch("dashboard.lib.s3.get_data_source", return_value="s3"):
            result = parquet_path("fct_wait_times", "2026-05-30", bucket="my-bucket")
        assert (
            result
            == "s3://my-bucket/gold_export/table=fct_wait_times/export_date=2026-05-30/*.parquet"
        )

    def test_local_path_format_with_date(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Local mode with export_date returns partitioned path."""
        monkeypatch.setenv("DATA_SOURCE", "local")
        result = parquet_path("fct_wait_times", "2026-05-30")
        assert result == "./data/gold/fct_wait_times/export_date=2026-05-30/*.parquet"

    def test_local_path_format_no_date(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Local mode with None export_date reads all parquet."""
        monkeypatch.setenv("DATA_SOURCE", "local")
        result = parquet_path("fct_wait_times", None)
        assert result == "./data/gold/fct_wait_times/*.parquet"

    def test_invalid_table_raises(self) -> None:
        """Unknown table name raises ValueError."""
        with pytest.raises(ValueError, match="not in GOLD_TABLES"):
            parquet_path("not_a_table", "2026-05-30")


class TestListLocalExportDates:
    """Tests for list_local_export_dates() function."""

    def test_discovers_dates_from_filesystem(self, tmp_path: object) -> None:
        """Finds export_date partitions in table subdirectories."""
        from pathlib import Path

        base = Path(str(tmp_path))
        (base / "fct_wait_times" / "export_date=2026-05-29").mkdir(parents=True)
        (base / "fct_wait_times" / "export_date=2026-05-30").mkdir(parents=True)
        result = list_local_export_dates(str(base))
        assert result == ["2026-05-30", "2026-05-29"]

    def test_empty_when_no_dir(self, tmp_path: object) -> None:
        """Returns empty list for nonexistent directory."""
        from pathlib import Path

        result = list_local_export_dates(str(Path(str(tmp_path)) / "nonexistent"))
        assert result == []

    def test_empty_when_no_partitions(self, tmp_path: object) -> None:
        """Returns empty list when table dir exists but has no export_date= children."""
        from pathlib import Path

        base = Path(str(tmp_path))
        (base / "fct_wait_times").mkdir(parents=True)
        result = list_local_export_dates(str(base))
        assert result == []


class TestGoldTables:
    """Tests for GOLD_TABLES constant."""

    def test_gold_tables_count(self) -> None:
        """GOLD_TABLES contains all 10 Gold models."""
        assert len(GOLD_TABLES) == 10

    def test_gold_tables_contains_facts(self) -> None:
        """All four fact tables are in GOLD_TABLES."""
        for table in ("fct_wait_times", "fct_inequality", "fct_urgent_care", "fct_utilisation"):
            assert table in GOLD_TABLES


class TestQueryUcEquity:
    """Tests for query_uc_equity connection usage."""

    def test_query_uc_equity_has_connection(self) -> None:
        """Verify query_uc_equity calls get_connection() (no NameError)."""
        # Stub duckdb before importing data module
        _duckdb = types.ModuleType("duckdb")
        sys.modules.setdefault("duckdb", _duckdb)

        mock_conn = MagicMock()
        mock_conn.execute.return_value.df.return_value = MagicMock()

        with patch("dashboard.lib.data.get_connection", return_value=mock_conn) as mock_get:
            from dashboard.lib.data import query_uc_equity

            query_uc_equity("2026-05-30", (), "IMD Decile")
            mock_get.assert_called_once()


class TestNoSilverBronzeRefs:
    """Enforce REQ-DASH-02: no Silver/Bronze references in dashboard code."""

    def test_no_silver_bronze_in_dashboard(self) -> None:
        """grep returns no matches for silver|bronze in dashboard/*.py."""
        result = subprocess.run(
            ["grep", "-r", r"silver\|bronze", "dashboard/", "--include=*.py"],
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0, (
            f"Found silver/bronze references in dashboard code:\n{result.stdout}"
        )
