"""Tests for dbt Silver/Gold build tasks via dbtRunner."""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock, patch

import pytest

# Stub prefect before importing flow modules
_PREFECT = types.ModuleType("prefect")
_PREFECT.task = lambda **kw: (lambda f: f)
sys.modules.setdefault("prefect", _PREFECT)

# Stub dbt.cli.main so dbt package is not required in main venv
_DBT_CLI_MAIN = types.ModuleType("dbt.cli.main")


class _MockDbtRunnerResult:
    def __init__(self, success: bool = True, exception: Exception | None = None):
        self.success = success
        self.exception = exception


_DBT_CLI_MAIN.dbtRunner = MagicMock  # replaced per-test via patch
_DBT_CLI_MAIN.dbtRunnerResult = _MockDbtRunnerResult

# Register dbt namespace modules so the import inside the function works
_DBT = types.ModuleType("dbt")
_DBT_CLI = types.ModuleType("dbt.cli")
sys.modules.setdefault("dbt", _DBT)
sys.modules.setdefault("dbt.cli", _DBT_CLI)
sys.modules.setdefault("dbt.cli.main", _DBT_CLI_MAIN)

from access_iq_flows.dbt_tasks import run_dbt_gold, run_dbt_silver  # noqa: E402


class TestDbtTasks:
    def test_silver_success(self) -> None:
        """run_dbt_silver calls dbtRunner.invoke with 'silver' selector and succeeds."""
        mock_result = _MockDbtRunnerResult(success=True)
        mock_runner_instance = MagicMock()
        mock_runner_instance.invoke.return_value = mock_result
        mock_runner_cls = MagicMock(return_value=mock_runner_instance)

        with patch("dbt.cli.main.dbtRunner", mock_runner_cls):
            run_dbt_silver()

        mock_runner_instance.invoke.assert_called_once()
        args = mock_runner_instance.invoke.call_args[0][0]
        assert "silver" in args
        assert "build" in args

    def test_silver_failure_raises(self) -> None:
        """run_dbt_silver raises RuntimeError when dbtRunner result is not successful."""
        mock_result = _MockDbtRunnerResult(success=False, exception=Exception("dbt error"))
        mock_runner_instance = MagicMock()
        mock_runner_instance.invoke.return_value = mock_result
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
