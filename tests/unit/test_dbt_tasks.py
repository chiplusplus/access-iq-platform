"""Tests for dbt Silver/Gold build tasks via dbtRunner."""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock, patch

import pytest

# Stub prefect before importing flow modules
_PREFECT = types.ModuleType("prefect")
_PREFECT.flow = lambda **kw: (lambda f: f)  # type: ignore[attr-defined]
_PREFECT.task = lambda **kw: (lambda f: f)  # type: ignore[attr-defined]
sys.modules.setdefault("prefect", _PREFECT)

# Stub dbt.cli.main so dbt package is not required in main venv
_DBT_CLI_MAIN = types.ModuleType("dbt.cli.main")


class _MockDbtRunnerResult:
    def __init__(self, success: bool = True, exception: Exception | None = None):
        self.success = success
        self.exception = exception


_DBT_CLI_MAIN.dbtRunner = MagicMock  # type: ignore[attr-defined]
_DBT_CLI_MAIN.dbtRunnerResult = _MockDbtRunnerResult  # type: ignore[attr-defined]

# Register dbt namespace modules so the import inside the function works
_DBT = types.ModuleType("dbt")
_DBT_CLI = types.ModuleType("dbt.cli")
sys.modules.setdefault("dbt", _DBT)
sys.modules.setdefault("dbt.cli", _DBT_CLI)
sys.modules.setdefault("dbt.cli.main", _DBT_CLI_MAIN)

from access_iq_flows.dbt_tasks import run_dbt_gold, run_dbt_silver, run_dbt_spectrum  # noqa: E402


class TestDbtTasks:
    def test_silver_success(self) -> None:
        """run_dbt_silver calls dbtRunner.invoke for seed then silver build."""
        mock_result = _MockDbtRunnerResult(success=True)
        mock_runner_instance = MagicMock()
        mock_runner_instance.invoke.return_value = mock_result
        mock_runner_cls = MagicMock(return_value=mock_runner_instance)

        with patch("dbt.cli.main.dbtRunner", mock_runner_cls):
            run_dbt_silver()

        assert mock_runner_instance.invoke.call_count == 2
        seed_args = mock_runner_instance.invoke.call_args_list[0][0][0]
        build_args = mock_runner_instance.invoke.call_args_list[1][0][0]
        assert "seed" in seed_args
        assert "silver" in build_args
        assert "build" in build_args

    def test_silver_failure_raises(self) -> None:
        """run_dbt_silver raises RuntimeError when dbt build result is not successful."""
        seed_ok = _MockDbtRunnerResult(success=True)
        build_fail = _MockDbtRunnerResult(success=False, exception=Exception("dbt error"))
        mock_runner_instance = MagicMock()
        mock_runner_instance.invoke.side_effect = [seed_ok, build_fail]
        mock_runner_cls = MagicMock(return_value=mock_runner_instance)

        with patch("dbt.cli.main.dbtRunner", mock_runner_cls):
            with pytest.raises(RuntimeError, match="dbt silver build failed"):
                run_dbt_silver()

    def test_gold_success(self) -> None:
        """run_dbt_gold calls dbtRunner.invoke with 'gold' selector and succeeds."""
        mock_result = _MockDbtRunnerResult(success=True)
        mock_runner_instance = MagicMock()
        mock_runner_instance.invoke.return_value = mock_result
        mock_runner_cls = MagicMock(return_value=mock_runner_instance)

        with patch("dbt.cli.main.dbtRunner", mock_runner_cls):
            run_dbt_gold()

        args = mock_runner_instance.invoke.call_args[0][0]
        assert "gold" in args
        assert "build" in args

    def test_spectrum_success(self) -> None:
        """run_dbt_spectrum calls stage_external_sources and add_spectrum_partitions."""
        mock_result = _MockDbtRunnerResult(success=True)
        mock_runner_instance = MagicMock()
        mock_runner_instance.invoke.return_value = mock_result
        mock_runner_cls = MagicMock(return_value=mock_runner_instance)

        with patch("dbt.cli.main.dbtRunner", mock_runner_cls):
            run_dbt_spectrum()

        assert mock_runner_instance.invoke.call_count == 2
        first_args = mock_runner_instance.invoke.call_args_list[0][0][0]
        second_args = mock_runner_instance.invoke.call_args_list[1][0][0]
        assert "run-operation" in first_args
        assert "stage_external_sources" in first_args
        assert "run-operation" in second_args
        assert "add_spectrum_partitions" in second_args

    def test_spectrum_stage_failure_raises(self) -> None:
        """run_dbt_spectrum raises RuntimeError when stage_external_sources fails."""
        mock_result = _MockDbtRunnerResult(success=False, exception=Exception("stage error"))
        mock_runner_instance = MagicMock()
        mock_runner_instance.invoke.return_value = mock_result
        mock_runner_cls = MagicMock(return_value=mock_runner_instance)

        with patch("dbt.cli.main.dbtRunner", mock_runner_cls):
            with pytest.raises(RuntimeError, match="stage_external_sources failed"):
                run_dbt_spectrum()

    def test_spectrum_partition_failure_raises(self) -> None:
        """run_dbt_spectrum raises RuntimeError when add_spectrum_partitions fails."""
        stage_ok = _MockDbtRunnerResult(success=True)
        partition_fail = _MockDbtRunnerResult(success=False, exception=Exception("partition error"))
        mock_runner_instance = MagicMock()
        mock_runner_instance.invoke.side_effect = [stage_ok, partition_fail]
        mock_runner_cls = MagicMock(return_value=mock_runner_instance)

        with patch("dbt.cli.main.dbtRunner", mock_runner_cls):
            with pytest.raises(RuntimeError, match="add_spectrum_partitions failed"):
                run_dbt_spectrum()

    def test_env_vars_respected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """run_dbt_silver passes DBT_PROFILES_DIR and DBT_TARGET from env to invoke."""
        monkeypatch.setenv("DBT_PROFILES_DIR", "/custom/profiles")
        monkeypatch.setenv("DBT_TARGET", "ci")

        mock_result = _MockDbtRunnerResult(success=True)
        mock_runner_instance = MagicMock()
        mock_runner_instance.invoke.return_value = mock_result
        mock_runner_cls = MagicMock(return_value=mock_runner_instance)

        with patch("dbt.cli.main.dbtRunner", mock_runner_cls):
            run_dbt_silver()

        args = mock_runner_instance.invoke.call_args[0][0]
        assert "/custom/profiles" in args
        assert "ci" in args
