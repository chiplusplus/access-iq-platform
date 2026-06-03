"""Historical backfill: ingest bronze data directly to correct ingest_date partitions.

Called once during `make up` to populate 12 months of historical bronze data.
Each entity's data is grouped by business date, clamped to [pipeline_start, today],
and written as Parquet with a manifest per partition. This makes the platform
look like it's been running daily for a year.

Not part of the Prefect pipeline — this is a one-time setup operation.
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
    "appointments": "appointment_start_datetime",
    "diagnostics_orders": "request_date",
    "urgent_care_logs": "arrival_datetime",
    "provider_site_reference": None,
}

SOURCE_ENTITIES: dict[str, list[str]] = {
    "ehr_postgres": ["patient_demographics", "encounters", "referrals", "diagnoses"],
    "urgent_care_postgres": ["urgent_care_logs"],
}


def backfill_postgres_source(
    *,
    dsn: str,
    source: str,
    tables: list[str],
    platform_bucket: str,
    pipeline_start_date: date,
    env: str,
    s3: Any,
    kms_key_arn: str | None = None,
) -> dict[str, Any]:
    """Ingest all data from a Postgres source, partitioned by business date.

    For each table: SELECT * → group by business date → write one parquet
    per date to the correct ingest_date partition → write manifest per date.
    """
    import psycopg2

    results: dict[str, Any] = {}
    today = date.today()

    conn = psycopg2.connect(dsn)
    try:
        for table in tables:
            date_col = ENTITY_DATE_COLUMNS.get(table)
            cursor = conn.cursor()
            cursor.execute(f'SELECT * FROM "{table}"')
            columns = [desc[0] for desc in cursor.description]
            rows = cursor.fetchall()
            cursor.close()

            if not rows:
                log.info("backfill_empty_table", source=source, table=table)
                continue

            df = pd.DataFrame(rows, columns=columns)

            if date_col is None:
                partitions = {today: df}
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
                    f"bronze/source={source}/entity={table}/"
                    f"ingest_date={biz_date.isoformat()}/{table}.parquet"
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
                    inputs={"tables": [table], "backfill": True},
                    outputs={
                        "tables": [
                            {
                                "table": table,
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
                "backfill_table_done",
                source=source,
                table=table,
                partitions=len(partitions),
                rows=len(df),
            )
            results[table] = table_keys
    finally:
        conn.close()

    return results
