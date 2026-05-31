"""dbt Silver and Gold build tasks using dbtRunner in-process API."""

from __future__ import annotations

import os

import structlog
from prefect import task

log = structlog.get_logger(__name__)


@task(retries=2, retry_delay_seconds=[60, 120], name="dbt-spectrum")
def run_dbt_spectrum() -> None:
    """Create/refresh Spectrum external tables and register partitions."""
    from dbt.cli.main import dbtRunner, dbtRunnerResult  # noqa: F401

    profiles_dir = os.environ.get("DBT_PROFILES_DIR", "/app/dbt")
    project_dir = os.environ.get("DBT_PROJECT_DIR", "/app/dbt")
    target = os.environ.get("DBT_TARGET", "prod")

    runner = dbtRunner()
    common_args = ["--profiles-dir", profiles_dir, "--project-dir", project_dir, "--target", target]

    schema_result: dbtRunnerResult = runner.invoke(
        ["run-operation", "create_external_schema", *common_args]
    )
    if not schema_result.success:
        detail = schema_result.exception or str(schema_result.result) or "unknown error"
        raise RuntimeError(f"create_external_schema failed: {detail}")
    log.info("spectrum_schema_created")

    stage_result: dbtRunnerResult = runner.invoke(
        ["run-operation", "stage_external_sources", *common_args]
    )
    if not stage_result.success:
        detail = stage_result.exception or str(stage_result.result) or "unknown error"
        raise RuntimeError(f"stage_external_sources failed: {detail}")
    log.info("spectrum_tables_created")

    partition_result: dbtRunnerResult = runner.invoke(
        ["run-operation", "add_spectrum_partitions", *common_args]
    )
    if not partition_result.success:
        detail = partition_result.exception or str(partition_result.result) or "unknown error"
        raise RuntimeError(f"add_spectrum_partitions failed: {detail}")
    log.info("spectrum_partitions_registered")


@task(retries=2, retry_delay_seconds=[60, 120], name="dbt-silver")
def run_dbt_silver() -> None:
    """Build Silver models via dbtRunner (in-process, not subprocess)."""
    from dbt.cli.main import dbtRunner, dbtRunnerResult  # noqa: F401

    profiles_dir = os.environ.get("DBT_PROFILES_DIR", "/app/dbt")
    project_dir = os.environ.get("DBT_PROJECT_DIR", "/app/dbt")
    target = os.environ.get("DBT_TARGET", "prod")

    runner = dbtRunner()
    common_args = ["--profiles-dir", profiles_dir, "--project-dir", project_dir, "--target", target]

    seed_result: dbtRunnerResult = runner.invoke(["seed", *common_args])
    if not seed_result.success:
        detail = seed_result.exception or str(seed_result.result) or "unknown error"
        raise RuntimeError(f"dbt seed failed: {detail}")
    log.info("dbt_seed_complete")

    result: dbtRunnerResult = runner.invoke(["build", "--select", "silver", *common_args])
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
