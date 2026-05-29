"""Tests for daily_ingest flow chain ordering and failure propagation."""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import pytest

# Stub prefect before importing flow modules
_PREFECT = types.ModuleType("prefect")
_PREFECT.flow = lambda **kw: (lambda f: f)
_PREFECT.task = lambda **kw: (lambda f: f)
sys.modules.setdefault("prefect", _PREFECT)

_PREFECT_FUTURES = types.ModuleType("prefect.futures")
_PREFECT_FUTURES.wait = MagicMock()
sys.modules.setdefault("prefect.futures", _PREFECT_FUTURES)


class TestDailyIngestChain:
    @pytest.mark.skip(reason="awaiting implementation — Task 3")
    def test_all_steps_called_in_order(self): ...

    @pytest.mark.skip(reason="awaiting implementation — Task 3")
    def test_ingestion_failure_propagates(self): ...

    @pytest.mark.skip(reason="awaiting implementation — Task 3")
    def test_invalid_run_date_raises(self): ...
