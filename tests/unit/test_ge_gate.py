"""Tests for GE gate mechanism.

Validates:
- run_ge_gate.py exits 0 when all tables pass
- run_ge_gate.py exits 1 when any table fails
- run_ge_gate.py writes results to _dq_results table
- run_ge_gate.py handles missing REDSHIFT_DSN gracefully
"""

from __future__ import annotations

import pytest


class TestGEGateExitBehavior:
    """Test run_ge_gate.py exit code logic."""

    def test_all_tables_pass_exits_zero(self) -> None:
        """GE gate exits 0 when all 4 Silver tables pass validation."""
        pytest.skip("Stub — implemented in Plan 06-04")

    def test_any_table_fails_exits_one(self) -> None:
        """GE gate exits 1 when any Silver table fails validation."""
        pytest.skip("Stub — implemented in Plan 06-04")

    def test_missing_dsn_raises(self) -> None:
        """GE gate raises KeyError when REDSHIFT_DSN not set."""
        pytest.skip("Stub — implemented in Plan 06-04")


class TestGEResultsWrite:
    """Test _dq_results table write logic."""

    def test_writes_one_row_per_table(self) -> None:
        """write_results_to_redshift inserts one row per validated table."""
        pytest.skip("Stub — implemented in Plan 06-04")

    def test_creates_table_if_not_exists(self) -> None:
        """write_results_to_redshift issues CREATE TABLE IF NOT EXISTS."""
        pytest.skip("Stub — implemented in Plan 06-04")
