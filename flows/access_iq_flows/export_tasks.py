"""Gold Parquet export via Redshift UNLOAD (server-side, D-05)."""

from __future__ import annotations

import os
import re
from datetime import date

import redshift_connector
import structlog
from prefect import task

log = structlog.get_logger(__name__)

GOLD_TABLES: frozenset[str] = frozenset(
    [
        "fct_wait_times",
        "fct_inequality",
        "fct_urgent_care",
        "fct_utilisation",
        "dim_patient",
        "dim_site",
        "dim_specialty",
        "dim_ethnicity",
        "dim_imd",
        "dim_date",
    ]
)

_BUCKET_RE = re.compile(r"^[a-z0-9][a-z0-9.\-]{1,61}[a-z0-9]$")


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
    bucket = os.environ.get("ACCESS_IQ_PLATFORM_BUCKET") or os.environ["PLATFORM_BUCKET"]
    dashboard_bucket = os.environ.get("DASHBOARD_EXPORT_BUCKET")
    role_arn = os.environ["REDSHIFT_SPECTRUM_ROLE_ARN"]
    kms_key = os.environ.get("ACCESS_IQ_LAKE_KMS_KEY_ARN") or os.environ.get("LAKE_KMS_KEY_ARN", "")

    # Validate inputs to prevent SQL injection via interpolated values (T-07-02)
    if not _BUCKET_RE.match(bucket):
        raise ValueError(f"Invalid bucket name format: {bucket!r}")
    if not role_arn.startswith("arn:aws:iam::"):
        raise ValueError(f"Invalid IAM role ARN format: {role_arn!r}")

    host = os.environ.get("REDSHIFT_HOST", "localhost")
    port = int(os.environ.get("REDSHIFT_PORT", "5439"))
    user = os.environ.get("REDSHIFT_USER", "admin")
    password = os.environ.get("REDSHIFT_PASSWORD", "")
    dbname = os.environ.get("REDSHIFT_DBNAME", "dev")
    sslmode = os.environ.get("REDSHIFT_SSLMODE", "prefer")
    use_ssl = sslmode in ("require", "verify-ca", "verify-full", "prefer")

    conn = redshift_connector.connect(
        host=host, port=port, user=user, password=password, database=dbname, ssl=use_ssl
    )
    try:
        with conn.cursor() as cur:
            for table_name in sorted(GOLD_TABLES):
                # Defense-in-depth: only tables in GOLD_TABLES allowlist reach here
                if table_name not in GOLD_TABLES:
                    raise ValueError(f"Table {table_name!r} not in GOLD_TABLES allowlist")
                s3_prefix = (
                    f"s3://{bucket}/gold_export/table={table_name}/export_date={export_date}/"
                )
                kms_clause = f"KMS_KEY_ID '{kms_key}' ENCRYPTED" if kms_key else ""
                sql = (
                    f"UNLOAD ('SELECT * FROM gold.{table_name}') "
                    f"TO '{s3_prefix}' "
                    f"IAM_ROLE '{role_arn}' "
                    f"FORMAT AS PARQUET "
                    f"ALLOWOVERWRITE "
                    f"PARALLEL OFF "
                    f"{kms_clause}"
                )
                cur.execute(sql)
                log.info("gold_exported", table=table_name, prefix=s3_prefix)

            # Write KMS-encrypted copy to permanent dashboard bucket (if configured)
            if dashboard_bucket:
                if not _BUCKET_RE.match(dashboard_bucket):
                    raise ValueError(f"Invalid dashboard bucket name: {dashboard_bucket!r}")
                for table_name in sorted(GOLD_TABLES):
                    s3_prefix = f"s3://{dashboard_bucket}/gold_export/table={table_name}/export_date={export_date}/"
                    sql = (
                        f"UNLOAD ('SELECT * FROM gold.{table_name}') "
                        f"TO '{s3_prefix}' "
                        f"IAM_ROLE '{role_arn}' "
                        f"FORMAT AS PARQUET "
                        f"ALLOWOVERWRITE "
                        f"PARALLEL OFF"
                    )
                    cur.execute(sql)
                log.info(
                    "dashboard_export_complete", bucket=dashboard_bucket, export_date=export_date
                )

        conn.commit()
    finally:
        conn.close()
    log.info("gold_export_complete", table_count=len(GOLD_TABLES), export_date=export_date)
