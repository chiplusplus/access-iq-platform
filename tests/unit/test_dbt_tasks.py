"""Tests for dbt Silver/Gold build tasks via dbtRunner."""

from __future__ import annotations

import sys
import types

import pytest

_PREFECT = types.ModuleType("prefect")
_PREFECT.task = lambda **kw: (lambda f: f)
sys.modules.setdefault("prefect", _PREFECT)


class TestDbtTasks:
    @pytest.mark.skip(reason="awaiting implementation — Task 3")
    def test_silver_success(self): ...

    @pytest.mark.skip(reason="awaiting implementation — Task 3")
    def test_silver_failure_raises(self): ...

    @pytest.mark.skip(reason="awaiting implementation — Task 3")
    def test_gold_success(self): ...

    @pytest.mark.skip(reason="awaiting implementation — Task 3")
    def test_env_vars_respected(self): ...
