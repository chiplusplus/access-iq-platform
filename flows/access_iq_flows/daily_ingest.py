"""Daily ingestion pipeline flow - Bronze -> Spectrum -> Silver -> GE -> Gold -> Export.

Single ECS task runs the entire flow (D-01). Each step is a @task for
Prefect UI visibility (D-02). Ingestion called as Python imports (D-03).
"""

from __future__ import annotations

import os
from datetime import date

import structlog
from prefect import flow, task
from prefect.futures import wait

from access_iq.config import Settings
from access_iq.ingestion.postgres import ingest_postgres_source_to_bronze
from access_iq.ingestion.sftp import ingest_sftp_directory_to_bronze
from access_iq.ingestion.trust_s3 import (
    ingest_trust_diagnostics_export_date_to_bronze,
    ingest_trust_provider_ref_to_bronze,
)
from access_iq.logging_config import configure_logging
from access_iq_flows.alerts import sns_on_failure
from access_iq_flows.dbt_tasks import run_dbt_gold, run_dbt_silver, run_dbt_spectrum
from access_iq_flows.export_tasks import export_gold_to_s3
from access_iq_flows.ge_tasks import run_ge_gate

log = structlog.get_logger(__name__)


@task(retries=3, retry_delay_seconds=[30, 60, 120], name="ingest-postgres")
def task_ingest_postgres(run_date: str, settings: Settings) -> dict:
    """Ingest EHR + Urgent Care postgres sources to Bronze."""
    ingest_date = date.fromisoformat(run_date)
    manifests = {}
    for db, src in settings.postgres_sources.items():
        dsn = os.environ.get(src.dsn_env, "")
        if not dsn:
            raise RuntimeError(f"Missing required env var: {src.dsn_env}")
        manifest = ingest_postgres_source_to_bronze(
            db=db,
            dsn=dsn,
            tables=src.tables,
            platform_bucket=settings.platform_bucket,
            ingest_date=ingest_date,
            env=settings.env,
            aws_region=settings.aws_region,
            kms_key_arn=settings.lake_kms_key_arn,
        )
        manifests[db] = manifest
    return manifests


@task(retries=3, retry_delay_seconds=[30, 60, 120], name="ingest-sftp")
def task_ingest_sftp(run_date: str, settings: Settings) -> dict:
    """Ingest SFTP appointment files to Bronze."""
    ingest_date = date.fromisoformat(run_date)
    manifests = {}
    for name, src in settings.sftp_sources.items():
        manifest = ingest_sftp_directory_to_bronze(
            host=os.environ.get(src.host_env, ""),
            port=int(os.environ.get(src.port_env, "22")),
            username=os.environ.get(src.user_env, ""),
            private_key=os.environ.get(src.private_key_env or "", None) or None,
            remote_dir=src.remote_dir,
            source_name=src.source_name or name,
            platform_bucket=settings.platform_bucket,
            ingest_date=ingest_date,
            env=settings.env,
            aws_region=settings.aws_region,
            kms_key_arn=settings.lake_kms_key_arn,
        )
        manifests[name] = manifest
    return manifests


@task(retries=3, retry_delay_seconds=[30, 60, 120], name="ingest-trust-s3")
def task_ingest_trust_s3(run_date: str, settings: Settings) -> dict:
    """Ingest Trust S3 diagnostics and provider ref to Bronze."""
    ingest_date = date.fromisoformat(run_date)
    trust_s3_cfg = settings.trust_s3
    if trust_s3_cfg is None:
        log.warning("trust_s3_config_missing", reason="trust_s3 not configured - skipping")
        return {}

    import boto3

    session = boto3.Session(region_name=settings.aws_region)
    s3 = session.client("s3")

    base_bucket = trust_s3_cfg.base.bucket

    # Diagnostics — pass export_date=None to auto-discover all available
    # export_date folders in Trust S3. The function's idempotency check
    # skips dates that already have a successful manifest.
    diag_cfg = trust_s3_cfg.diagnostics
    diag_manifest = ingest_trust_diagnostics_export_date_to_bronze(
        s3=s3,
        trust_bucket=base_bucket,
        prefix_root=diag_cfg.prefix_root or "",
        source_name=diag_cfg.source_name or "trust_diagnostics",
        export_date=None,
        platform_bucket=settings.platform_bucket,
        env=settings.env,
        kms_key_arn=settings.lake_kms_key_arn,
    )

    # Provider reference
    prov_cfg = trust_s3_cfg.provider_ref
    prov_manifest = ingest_trust_provider_ref_to_bronze(
        s3=s3,
        trust_bucket=base_bucket,
        trust_key=prov_cfg.key or "",
        source_name=prov_cfg.source_name or "trust_provider_ref",
        platform_bucket=settings.platform_bucket,
        ingest_date=ingest_date,
        env=settings.env,
        kms_key_arn=settings.lake_kms_key_arn,
    )

    return {"diagnostics": diag_manifest, "provider_ref": prov_manifest}


@flow(
    name="daily-ingest",
    on_failure=[sns_on_failure],
    retries=0,
)
def daily_ingest(run_date: str | None = None, env: str = "dev") -> None:
    """End-to-end pipeline: Bronze ingest -> Spectrum -> dbt Silver -> GE gate -> dbt Gold -> Gold export.

    All steps run in a single ECS task (D-01). Each step is a @task for
    Prefect UI visibility (D-02).

    Args:
        run_date: ISO date string (YYYY-MM-DD). Defaults to today.
        env: Environment name. Defaults to 'dev'.
    """
    configure_logging()
    structlog.contextvars.bind_contextvars(env=env)

    effective_date = run_date or date.today().isoformat()
    # Validate date format at flow entry (T-07-07); also guards export_gold_to_s3 SQL
    date.fromisoformat(effective_date)

    log.info("pipeline_start", run_date=effective_date, env=env)

    # Settings reads ACCESS_IQ_* env vars (injected by ECS task definition)
    settings = Settings()  # type: ignore[call-arg]

    # Step 1: Concurrent Bronze ingestion (D-03)
    pg_future = task_ingest_postgres.submit(run_date=effective_date, settings=settings)
    sftp_future = task_ingest_sftp.submit(run_date=effective_date, settings=settings)
    s3_future = task_ingest_trust_s3.submit(run_date=effective_date, settings=settings)
    futures = [pg_future, sftp_future, s3_future]
    wait(futures)
    # Prefect 3.x wait() does not raise on task failure; .result() does
    for future in futures:
        future.result()

    log.info("bronze_ingestion_complete")

    # Step 2: Refresh Spectrum external tables + partitions
    run_dbt_spectrum()

    # Step 3: dbt Silver build
    run_dbt_silver()

    # Step 4: GE validation gate (blocks Gold on failure)
    run_ge_gate()

    # Step 5: dbt Gold build
    run_dbt_gold()

    # Step 6: Gold Parquet export to S3 (D-05, D-06)
    export_gold_to_s3(run_date=effective_date)

    log.info("pipeline_complete", run_date=effective_date)
