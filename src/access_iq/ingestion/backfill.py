"""Historical backfill: ingest bronze data directly to correct ingest_date partitions.

Called once during `make up` to populate 12 months of historical bronze data.
Reads from local Trust staging CSVs (already generated in step 0), groups by
business date clamped to [pipeline_start, today], and writes Parquet + manifest
per partition to Platform S3.

Not part of the Prefect pipeline — this is a one-time setup operation.
"""

from __future__ import annotations

import io
import uuid
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import structlog

from access_iq.ingestion.manifests import (
    Manifest,
    s3_kms_args,
    utc_now_iso,
    write_manifest,
)

log = structlog.get_logger(__name__)

ENTITY_DATE_COLUMNS: dict[str, str | None] = {
    "patient_demographics": "registration_start_date",
    "encounters": "encounter_datetime_start",
    "referrals": "referral_datetime",
    "diagnoses": "clinical_datetime",
    "urgent_care_logs": "arrival_datetime",
}

BACKFILL_SOURCES: list[dict[str, str]] = [
    {"csv": "patients.csv", "source": "ehr_postgres", "entity": "patient_demographics"},
    {"csv": "encounters.csv", "source": "ehr_postgres", "entity": "encounters"},
    {"csv": "referrals.csv", "source": "ehr_postgres", "entity": "referrals"},
    {"csv": "diagnoses.csv", "source": "ehr_postgres", "entity": "diagnoses"},
    {"csv": "urgent_care_logs.csv", "source": "urgent_care_postgres", "entity": "urgent_care_logs"},
]


def backfill_from_staging(
    *,
    staging_core_dir: Path,
    platform_bucket: str,
    pipeline_start_date: date,
    env: str,
    s3: Any,
    kms_key_arn: str | None = None,
) -> dict[str, Any]:
    """Read Trust staging CSVs and write bronze partitions grouped by business date.

    Each CSV is read into a DataFrame, grouped by its business date column
    (clamped to pipeline_start_date for pre-window data), then each group
    is written as a Parquet file to the correct ingest_date partition with
    a matching manifest.
    """
    results: dict[str, Any] = {}

    for entry in BACKFILL_SOURCES:
        csv_path = staging_core_dir / entry["csv"]
        source = entry["source"]
        entity = entry["entity"]
        date_col = ENTITY_DATE_COLUMNS.get(entity)

        if not csv_path.exists():
            log.warning("backfill_csv_missing", path=str(csv_path), entity=entity)
            continue

        df = pd.read_csv(csv_path)
        if df.empty:
            log.info("backfill_empty_csv", entity=entity)
            continue

        if date_col is None:
            partitions = {date.today(): df}
        else:
            raw_dates = pd.to_datetime(df[date_col]).dt.date
            df["_biz_date"] = raw_dates.apply(
                lambda d: pipeline_start_date if d < pipeline_start_date else d
            )
            partitions = {
                biz_date: group.drop(columns=["_biz_date"])
                for biz_date, group in df.groupby("_biz_date")
            }

        table_keys = []
        for biz_date, group_df in partitions.items():
            run_id = str(uuid.uuid4())
            started_at = utc_now_iso()

            out_table = pa.Table.from_pandas(group_df, preserve_index=False)
            buf = io.BytesIO()
            pq.write_table(out_table, buf, compression="snappy")
            buf.seek(0)

            bronze_key = (
                f"bronze/source={source}/entity={entity}/"
                f"ingest_date={biz_date.isoformat()}/{entity}.parquet"
            )

            extra = s3_kms_args(kms_key_arn)
            s3.upload_fileobj(
                Fileobj=buf,
                Bucket=platform_bucket,
                Key=bronze_key,
                ExtraArgs=extra if extra else None,
            )

            finished_at = utc_now_iso()

            manifest = Manifest(
                source=source,
                env=env,
                run_id=run_id,
                ingest_date=biz_date.isoformat(),
                started_at=started_at,
                finished_at=finished_at,
                status="success",
                inputs={"tables": [entity], "backfill": True},
                outputs={
                    "tables": [
                        {
                            "table": entity,
                            "status": "success",
                            "s3_key": bronze_key,
                            "rows": len(group_df),
                        }
                    ],
                    "tables_succeeded": 1,
                    "tables_failed": 0,
                },
            )
            write_manifest(
                s3=s3, bucket=platform_bucket, manifest=manifest, kms_key_arn=kms_key_arn
            )
            table_keys.append(bronze_key)

        log.info(
            "backfill_entity_done",
            source=source,
            entity=entity,
            partitions=len(partitions),
            rows=len(df),
        )
        results[entity] = table_keys

    return results
