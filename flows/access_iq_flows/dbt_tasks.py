"""dbt Silver and Gold build tasks using dbtRunner in-process API."""

from __future__ import annotations

import os

import structlog
from prefect import task

log = structlog.get_logger(__name__)


@task(retries=2, retry_delay_seconds=[60, 120], name="dbt-silver")
def run_dbt_silver() -> None:
    """Build Silver models via dbtRunner (in-process, not subprocess)."""
    from dbt.cli.main import dbtRunner, dbtRunnerResult  # noqa: F401

    profiles_dir = os.environ.get("DBT_PROFILES_DIR", "/app/dbt")
    project_dir = os.environ.get("DBT_PROJECT_DIR", "/app/dbt")
    target = os.environ.get("DBT_TARGET", "prod")

    runner = dbtRunner()
    result: dbtRunnerResult = runner.invoke(
        [
            "build",
            "--select",
            "silver",
            "--profiles-dir",
            profiles_dir,
            "--project-dir",
            project_dir,
            "--target",
            target,
        ]
    )
    if not result.success:
        detail = result.exception or str(result.result) or "unknown error"
        raise RuntimeError(f"dbt silver build failed: {detail}")
    log.info("dbt_silver_complete")


@task(retries=2, retry_delay_seconds=[60, 120], name="dbt-gold")
def run_dbt_gold() -> None:
    """Build Gold models via dbtRunner (in-process, not subprocess)."""
    from dbt.cli.main import dbtRunner, dbtRunnerResult  # noqa: F401

    profiles_dir = os.environ.get("DBT_PROFILES_DIR", "/app/dbt")
    project_dir = os.environ.get("DBT_PROJECT_DIR", "/app/dbt")
    target = os.environ.get("DBT_TARGET", "prod")

    runner = dbtRunner()
    result: dbtRunnerResult = runner.invoke(
        [
            "build",
            "--select",
            "gold",
            "--profiles-dir",
            profiles_dir,
            "--project-dir",
            project_dir,
            "--target",
            target,
        ]
    )
    if not result.success:
        detail = result.exception or str(result.result) or "unknown error"
        raise RuntimeError(f"dbt gold build failed: {detail}")
    log.info("dbt_gold_complete")
