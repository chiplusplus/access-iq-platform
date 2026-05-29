"""Tests for Gold Parquet export via Redshift UNLOAD."""

from __future__ import annotations

import sys
import types

import pytest

_PREFECT = types.ModuleType("prefect")
_PREFECT.task = lambda **kw: (lambda f: f)
sys.modules.setdefault("prefect", _PREFECT)


class TestExportTasks:
    @pytest.mark.skip(reason="awaiting implementation — Task 3")
    def test_unload_prefix_format(self): ...

    @pytest.mark.skip(reason="awaiting implementation — Task 3")
    def test_validate_export_date_rejects_invalid(self): ...

    @pytest.mark.skip(reason="awaiting implementation — Task 3")
    def test_validate_export_date_accepts_valid(self): ...

    @pytest.mark.skip(reason="awaiting implementation — Task 3")
    def test_validate_export_date_defaults_to_today(self): ...
