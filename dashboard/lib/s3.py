"""S3 partition discovery and local fallback for Gold Parquet reads."""

from __future__ import annotations

import os
from pathlib import Path

import streamlit as st
import structlog

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


def get_data_source() -> str:
    """Return 's3' or 'local'. Check env var first, then st.secrets."""
    if os.environ.get("DATA_SOURCE", "").lower() == "local":
        return "local"
    try:
        if not st.secrets.get("AWS_ACCESS_KEY_ID"):
            return "local"
    except Exception:
        log.warning("secrets_unavailable", exc_info=True)
        return "local"
    return "s3"


def get_bucket() -> str:
    """Return bucket name from st.secrets or env var."""
    try:
        return st.secrets.get("PLATFORM_BUCKET", "")
    except Exception:
        log.warning("bucket_secret_unavailable", exc_info=True)
        return os.environ.get("PLATFORM_BUCKET", "")


def list_export_dates(bucket: str, table: str = "fct_wait_times") -> list[str]:
    """List available export_date partition values from S3 prefix structure (D-04)."""
    import boto3

    try:
        key_id = st.secrets.get("AWS_ACCESS_KEY_ID", "")
        secret = st.secrets.get("AWS_SECRET_ACCESS_KEY", "")
        region = st.secrets.get("AWS_REGION", "eu-west-2")
    except Exception:
        key_id = os.environ.get("AWS_ACCESS_KEY_ID", "")
        secret = os.environ.get("AWS_SECRET_ACCESS_KEY", "")
        region = os.environ.get("AWS_REGION", "eu-west-2")

    s3 = boto3.client(
        "s3",
        aws_access_key_id=key_id,
        aws_secret_access_key=secret,
        region_name=region,
    )
    prefix = f"gold_export/table={table}/export_date="
    response = s3.list_objects_v2(Bucket=bucket, Prefix=prefix, Delimiter="/")
    dates: list[str] = []
    for cp in response.get("CommonPrefixes", []):
        date_part = cp["Prefix"].rstrip("/").split("export_date=")[-1]
        dates.append(date_part)
    return sorted(dates, reverse=True)


def list_local_export_dates(base_dir: str = "./data/gold") -> list[str]:
    """Discover available export dates from local filesystem (D-04 local fallback).

    Scans for subdirectories matching export_date=YYYY-MM-DD pattern under
    any table directory in base_dir. Returns sorted dates (newest first).
    If no export_date partitions exist, returns empty list -- pages handle
    empty by reading *.parquet directly without date partitioning.
    """
    base = Path(base_dir)
    dates: set[str] = set()
    if not base.exists():
        log.warning("local_gold_dir_missing", path=str(base))
        return []
    for table_dir in base.iterdir():
        if not table_dir.is_dir():
            continue
        for sub in table_dir.iterdir():
            if sub.is_dir() and sub.name.startswith("export_date="):
                date_val = sub.name.split("export_date=", 1)[1]
                dates.add(date_val)
    return sorted(dates, reverse=True)


def parquet_path(table: str, export_date: str | None, bucket: str = "") -> str:
    """Return DuckDB-readable path for a Gold table's Parquet files.

    When export_date is None (local mode without partitions), reads all
    Parquet directly from the table directory.
    """
    if table not in GOLD_TABLES:
        raise ValueError(f"Table {table!r} not in GOLD_TABLES allowlist")
    if get_data_source() == "local":
        if export_date:
            return f"./data/gold/{table}/export_date={export_date}/*.parquet"
        return f"./data/gold/{table}/*.parquet"
    return f"s3://{bucket}/gold_export/table={table}/export_date={export_date}/*.parquet"
