"""Smoke tests: all three dashboard pages import without error (REQ-DASH-01)."""

from __future__ import annotations

import importlib
import pathlib
import subprocess
import sys
import types
from unittest.mock import MagicMock

import pandas as pd

# ---------------------------------------------------------------------------
# Stub streamlit + structlog + duckdb before importing page modules
# ---------------------------------------------------------------------------


def _passthrough_decorator(*args, **kw):  # type: ignore[no-untyped-def]
    """Stub decorator that handles both @decorator and @decorator(...) forms."""
    if args and callable(args[0]):
        return args[0]
    return lambda f: f


_ST = types.ModuleType("streamlit")
_ST.cache_data = _passthrough_decorator  # type: ignore[attr-defined]
_ST.cache_resource = _passthrough_decorator  # type: ignore[attr-defined]
_ST.secrets = {}  # type: ignore[attr-defined]
_ST.session_state = {"export_date": "local", "bucket": "", "data_source": "local"}  # type: ignore[attr-defined]
_ST.title = lambda *a, **k: None  # type: ignore[attr-defined]
_ST.caption = lambda *a, **k: None  # type: ignore[attr-defined]
_ST.columns = lambda n: [  # type: ignore[attr-defined]
    type(
        "C",
        (),
        {
            "metric": lambda *a, **k: None,
            "__enter__": lambda s: s,
            "__exit__": lambda *a: None,
        },
    )()
    for _ in range(n)
]
_SB = type(
    "SB",
    (),
    {
        "multiselect": lambda *a, **k: [],
        "toggle": lambda *a, **k: False,
        "selectbox": lambda *a, **k: "IMD Decile",
        "slider": lambda *a, **k: (None, None),
    },
)()
_ST.sidebar = _SB  # type: ignore[attr-defined]
_ST.plotly_chart = lambda *a, **k: None  # type: ignore[attr-defined]
_ST.divider = lambda: None  # type: ignore[attr-defined]
_ST.warning = lambda *a, **k: None  # type: ignore[attr-defined]
_ST.info = lambda *a, **k: None  # type: ignore[attr-defined]
_ST.subheader = lambda *a, **k: None  # type: ignore[attr-defined]
_ST.markdown = lambda *a, **k: None  # type: ignore[attr-defined]
_ST.error = lambda *a, **k: None  # type: ignore[attr-defined]
_ST.set_page_config = lambda **k: None  # type: ignore[attr-defined]
_ST.metric = lambda *a, **k: None  # type: ignore[attr-defined]
_ST.spinner = lambda *a, **k: type(  # type: ignore[attr-defined]
    "Ctx", (), {"__enter__": lambda s: s, "__exit__": lambda *a: None}
)()
# Use setdefault for fresh environments, but also patch existing stub
# when another test file (e.g. test_dashboard_data.py) already loaded a
# minimal streamlit stub without page-level attributes.
_existing_st = sys.modules.get("streamlit")
if _existing_st is not None:
    for attr in (
        "title",
        "caption",
        "columns",
        "sidebar",
        "plotly_chart",
        "divider",
        "warning",
        "info",
        "subheader",
        "markdown",
        "error",
        "set_page_config",
        "metric",
        "spinner",
        "session_state",
    ):
        if not hasattr(_existing_st, attr):
            setattr(_existing_st, attr, getattr(_ST, attr))
    # Ensure session_state has expected keys
    if not getattr(_existing_st, "session_state", None):
        _existing_st.session_state = _ST.session_state  # type: ignore[attr-defined]
    _ST = _existing_st  # type: ignore[assignment]
else:
    sys.modules["streamlit"] = _ST

# Stub structlog
_STRUCTLOG = types.ModuleType("structlog")
_STRUCTLOG.get_logger = lambda *a, **kw: MagicMock()  # type: ignore[attr-defined]
sys.modules.setdefault("structlog", _STRUCTLOG)

# Stub duckdb -- pages run _run() at import time, which queries for sidebar filter
# options (provider_name, specialty_name columns). Return DataFrames with columns
# present but no rows so all downstream code hits "empty" early-return paths.
_mock_conn = MagicMock()


def _mock_execute(sql: str, params: list | None = None) -> MagicMock:
    """Return a result mock whose .df() yields an empty DataFrame with plausible columns."""
    result = MagicMock()
    sql_lower = sql.lower()
    if "provider_name" in sql_lower:
        result.df.return_value = pd.DataFrame(columns=["provider_name"])
    elif "specialty_name" in sql_lower:
        result.df.return_value = pd.DataFrame(columns=["specialty_name"])
    else:
        result.df.return_value = pd.DataFrame()
    return result


_mock_conn.execute = _mock_execute

_DUCKDB = types.ModuleType("duckdb")
_DUCKDB.connect = lambda **kw: _mock_conn  # type: ignore[attr-defined]
_DUCKDB.DuckDBPyConnection = type(_mock_conn)  # type: ignore[attr-defined]
sys.modules.setdefault("duckdb", _DUCKDB)

# Pre-import data layer to patch get_connection before pages call _run()
from dashboard.lib import data as _data_mod  # noqa: E402

# Patch get_connection to return mock conn (avoids httpfs load)
_data_mod.get_connection = lambda: _mock_conn
# Patch register_tables to no-op (avoids parquet file reads)
_data_mod.register_tables = lambda *a, **k: None


class TestPageImports:
    """REQ-DASH-01: Three pages must exist and import without error."""

    def test_wait_times_imports(self) -> None:
        mod = importlib.import_module("dashboard.pages.1_wait_times")
        assert mod is not None

    def test_inequality_imports(self) -> None:
        mod = importlib.import_module("dashboard.pages.2_inequality")
        assert mod is not None

    def test_urgent_care_imports(self) -> None:
        mod = importlib.import_module("dashboard.pages.3_urgent_care")
        assert mod is not None

    def test_three_pages_exist(self) -> None:
        """Exactly 3 page files in dashboard/pages/."""
        pages = list(pathlib.Path("dashboard/pages").glob("*.py"))
        page_names = sorted(p.name for p in pages if not p.name.startswith("__"))
        assert len(page_names) == 3
        assert page_names == ["1_wait_times.py", "2_inequality.py", "3_urgent_care.py"]


class TestNoSilverBronzeInPages:
    """REQ-DASH-02: Dashboard code must not reference Silver or Bronze."""

    def test_no_silver_bronze_refs(self) -> None:
        result = subprocess.run(
            ["grep", "-rl", "-E", "silver|bronze", "dashboard/", "--include=*.py"],
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0, f"Found silver/bronze references in: {result.stdout.strip()}"
