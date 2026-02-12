from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime
from typing import Any

import boto3
import psycopg2


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def ingest_table_to_bronze(
    dsn: str,
    table: str,
    platform_bucket: str,
    ingest_date: date,
    env: str,
) -> dict[str, Any]:
    run_id = str(uuid.uuid4())
    started_at = utc_now()

    s3 = boto3.client("s3")

    bronze_key = (
        f"bronze/source=ehr_postgres/entity={table}/"
        f"ingest_date={ingest_date.isoformat()}/run_id={run_id}/{table}.csv"
    )

    conn = psycopg2.connect(dsn)
    cursor = conn.cursor()

    copy_sql = f"COPY (SELECT * FROM {table}) TO STDOUT WITH CSV HEADER"

    with cursor, conn:
        s3.upload_fileobj(
            Fileobj=_copy_stream(cursor, copy_sql),
            Bucket=platform_bucket,
            Key=bronze_key,
        )

    finished_at = utc_now()

    manifest = {
        "source": "ehr_postgres",
        "env": env,
        "run_id": run_id,
        "table": table,
        "started_at": started_at,
        "finished_at": finished_at,
        "status": "success",
        "s3_key": bronze_key,
    }

    manifest_key = (
        f"_manifests/source=ehr_postgres/ingest_date={ingest_date.isoformat()}/run_id={run_id}.json"
    )

    s3.put_object(
        Bucket=platform_bucket,
        Key=manifest_key,
        Body=json.dumps(manifest, indent=2).encode("utf-8"),
        ContentType="application/json",
    )

    return manifest


def _copy_stream(cursor, copy_sql: str):
    """
    Returns a file-like object that streams COPY output.
    """
    import io

    buffer = io.BytesIO()
    cursor.copy_expert(copy_sql, buffer)
    buffer.seek(0)
    return buffer
