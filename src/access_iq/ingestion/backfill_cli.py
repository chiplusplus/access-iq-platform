"""CLI for historical bronze backfill. Called by session.sh during make up."""

from __future__ import annotations

import os
import sys
from datetime import date

import boto3
import structlog
from dateutil.relativedelta import relativedelta

from access_iq.config import Settings
from access_iq.ingestion.backfill import backfill_postgres_source
from access_iq.logging_config import configure_logging

log = structlog.get_logger(__name__)


def main() -> None:
    configure_logging()

    # Load ALL vars from .env into os.environ — pydantic Settings only reads
    # ACCESS_IQ_* prefixed fields, but the DSN vars (EHR_DSN, etc.) are raw
    # env vars referenced indirectly via postgres_sources.dsn_env.
    from dotenv import load_dotenv

    load_dotenv()

    settings = Settings()  # type: ignore[call-arg]
    pipeline_start = date.today() - relativedelta(months=12)

    session = boto3.Session(region_name=settings.aws_region)
    s3 = session.client("s3")

    log.info("backfill_start", pipeline_start=pipeline_start.isoformat(), env=settings.env)

    # Postgres sources (EHR + Urgent Care)
    for db, src in settings.postgres_sources.items():
        dsn = os.environ.get(src.dsn_env, "")
        if not dsn:
            log.error("backfill_missing_dsn", source=db, env_var=src.dsn_env)
            sys.exit(1)

        log.info("backfill_source_start", source=db, tables=src.tables)
        result = backfill_postgres_source(
            dsn=dsn,
            source=db,
            tables=src.tables,
            platform_bucket=settings.platform_bucket,
            pipeline_start_date=pipeline_start,
            env=settings.env,
            s3=s3,
            kms_key_arn=settings.lake_kms_key_arn,
        )
        total_partitions = sum(len(v) for v in result.values())
        log.info("backfill_source_done", source=db, partitions=total_partitions)

    # SFTP and Trust S3 sources are already partitioned correctly:
    # - SFTP appointments: one file per day, ingested to ingest_date matching the file
    # - Trust S3 diagnostics: export_date folders, ingested per export_date
    # - Provider reference: static, single ingest_date
    # These are handled by the normal ingestion tasks (called separately).
    log.info("backfill_postgres_complete", pipeline_start=pipeline_start.isoformat())
    log.info(
        "backfill_note",
        message="SFTP and Trust S3 sources use normal ingestion (already date-partitioned)",
    )


if __name__ == "__main__":
    main()
