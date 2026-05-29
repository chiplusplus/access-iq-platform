"""Tests for GE validation gate task."""

from __future__ import annotations

import sys
import types

import pytest

_PREFECT = types.ModuleType("prefect")
_PREFECT.task = lambda **kw: (lambda f: f)
sys.modules.setdefault("prefect", _PREFECT)


class TestGeTasks:
    @pytest.mark.skip(reason="awaiting implementation — Task 3")
    def test_ge_gate_raises_on_failure(self): ...

    @pytest.mark.skip(reason="awaiting implementation — Task 3")
    def test_ge_gate_passes_on_success(self): ...

    @pytest.mark.skip(reason="awaiting implementation — Task 3")
    def test_ge_gate_writes_results(self): ...
