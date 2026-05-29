"""Gold Parquet export via Redshift UNLOAD (server-side, D-05)."""

from __future__ import annotations

import os
from datetime import date

import psycopg2
import structlog
from prefect import task

log = structlog.get_logger(__name__)

GOLD_TABLES = [
    "fct_wait_times",
    "fct_inequality",
    "fct_urgent_care",
    "fct_utilisation",
    "dim_patient",
    "dim_site",
    "dim_imd",
    "dim_date",
]


def _validate_export_date(run_date: str | None) -> str:
    """Validate and return ISO date string. Guards against SQL injection (T-07-02)."""
    if run_date is None:
        return date.today().isoformat()
    # Raises ValueError if not a valid ISO date
    date.fromisoformat(run_date)
    return run_date


@task(retries=1, retry_delay_seconds=30, name="export-gold-to-s3")
def export_gold_to_s3(run_date: str | None = None) -> None:
    """UNLOAD each Gold table to S3 as Parquet. Data never touches the container.

    Prefix pattern (D-06): gold_export/table=<name>/export_date=YYYY-MM-DD/
    """
    export_date = _validate_export_date(run_date)
    bucket = os.environ["PLATFORM_BUCKET"]
    role_arn = os.environ["SPECTRUM_ROLE_ARN"]

    # Build a psycopg2-compatible DSN from REDSHIFT_DSN
    raw_dsn = os.environ["REDSHIFT_DSN"]
    dsn = raw_dsn.replace("postgresql+psycopg2://", "postgresql://").replace(
        "redshift+psycopg2://", "postgresql://"
    )

    conn = psycopg2.connect(dsn, sslmode="prefer")
    try:
        with conn.cursor() as cur:
            for table_name in GOLD_TABLES:
                s3_prefix = (
                    f"s3://{bucket}/gold_export/table={table_name}/export_date={export_date}/"
                )
                sql = (
                    f"UNLOAD ('SELECT * FROM gold.{table_name}') "
                    f"TO '{s3_prefix}' "
                    f"IAM_ROLE '{role_arn}' "
                    f"FORMAT AS PARQUET "
                    f"ALLOWOVERWRITE "
                    f"PARALLEL OFF"
                )
                cur.execute(sql)
                log.info("gold_exported", table=table_name, prefix=s3_prefix)
        conn.commit()
    finally:
        conn.close()
    log.info("gold_export_complete", table_count=len(GOLD_TABLES), export_date=export_date)
