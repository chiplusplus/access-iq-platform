"""Bronze post-processing: repartition Parquet files by business date.

ingest_date in this system represents the business date of the source data,
not the wall-clock time of ingestion. This is a deliberate design choice
for the portfolio simulation.
"""

from __future__ import annotations

import io
import uuid
from datetime import date
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import structlog

log = structlog.get_logger(__name__)

ENTITY_DATE_COLUMNS: dict[str, str | None] = {
    "patient_demographics": "registration_start_date",
    "encounters": "encounter_datetime_start",
    "referrals": "referral_datetime",
    "diagnoses": "clinical_datetime",
    "appointments": "appointment_start_datetime",
    "diagnostics_orders": "request_date",
    "urgent_care_logs": "arrival_datetime",
    "provider_site_reference": None,
}


def extract_business_dates(
    *,
    parquet_bytes: bytes,
    entity: str,
    date_column_map: dict[str, str | None] = ENTITY_DATE_COLUMNS,
) -> list[date] | None:
    """Extract unique business dates from a Parquet file.

    Returns None for static entities (no date column).
    """
    date_col = date_column_map.get(entity)
    if date_col is None:
        return None

    table = pq.read_table(io.BytesIO(parquet_bytes))
    col = table.column(date_col)
    dates = set()
    for val in col.to_pylist():
        if val is None:
            continue
        if hasattr(val, "date"):
            dates.add(val.date())
        elif isinstance(val, str):
            dates.add(date.fromisoformat(val[:10]))
        elif isinstance(val, date):
            dates.add(val)
    return sorted(dates)


def repartition_bronze_key(
    *,
    s3: Any,
    bucket: str,
    source_key: str,
    source: str,
    entity: str,
    date_column_map: dict[str, str | None] = ENTITY_DATE_COLUMNS,
    kms_key_arn: str | None = None,
) -> list[str]:
    """Read a bronze Parquet file and split it into per-business-date partitions.

    Returns list of new S3 keys written.
    """
    date_col = date_column_map.get(entity)
    if date_col is None:
        log.info("repartition_skip", entity=entity, reason="static entity")
        return [source_key]

    resp = s3.get_object(Bucket=bucket, Key=source_key)
    raw = resp["Body"].read()
    table = pq.read_table(io.BytesIO(raw))

    df = table.to_pandas()
    df["_biz_date"] = pd.to_datetime(df[date_col]).dt.date

    new_keys: list[str] = []
    run_id = str(uuid.uuid4())

    extra_args = {}
    if kms_key_arn:
        extra_args = {
            "ServerSideEncryption": "aws:kms",
            "SSEKMSKeyId": kms_key_arn,
        }

    for biz_date, group in df.groupby("_biz_date"):
        group_clean = group.drop(columns=["_biz_date"])
        out_table = pa.Table.from_pandas(group_clean, preserve_index=False)
        buf = io.BytesIO()
        pq.write_table(out_table, buf, compression="snappy")
        buf.seek(0)

        new_key = (
            f"bronze/source={source}/entity={entity}/"
            f"ingest_date={biz_date.isoformat()}/run_id={run_id}/{entity}.parquet"
        )

        s3.upload_fileobj(
            Fileobj=buf,
            Bucket=bucket,
            Key=new_key,
            ExtraArgs=extra_args if extra_args else None,
        )
        new_keys.append(new_key)
        log.info("repartition_write", entity=entity, biz_date=str(biz_date), key=new_key)

    # Delete the original file (now replaced by per-date partitions)
    if new_keys and any(k != source_key for k in new_keys):
        s3.delete_object(Bucket=bucket, Key=source_key)
        log.info("repartition_cleanup", deleted=source_key)

    return new_keys
