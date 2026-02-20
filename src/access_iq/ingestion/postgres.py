from __future__ import annotations

import io
import json
import uuid
from datetime import UTC, date, datetime
from typing import Any

import boto3
import psycopg2

from access_iq.ingestion.idempotency import should_skip_if_already_successful


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def ingest_table_to_bronze(
    *,
    dsn: str,
    db: str,
    table: str,
    platform_bucket: str,
    ingest_date: date,
    s3_client: Any,
    run_id: str,
) -> dict[str, Any]:
    started_at = utc_now()

    bronze_key = (
        f"bronze/source={db}/entity={table}/"
        f"ingest_date={ingest_date.isoformat()}/run_id={run_id}/{table}.csv"
    )

    conn = psycopg2.connect(dsn)
    cursor = conn.cursor()

    copy_sql = f"COPY (SELECT * FROM {table}) TO STDOUT WITH CSV HEADER"

    with cursor, conn:
        s3_client.upload_fileobj(
            Fileobj=_copy_stream(cursor, copy_sql),
            Bucket=platform_bucket,
            Key=bronze_key,
        )

    finished_at = utc_now()

    return {
        "db": db,
        "table": table,
        "started_at": started_at,
        "finished_at": finished_at,
        "status": "success",
        "s3_key": bronze_key,
    }


def ingest_postgres_source_to_bronze(
    db: str,
    dsn: str,
    tables: list[str],
    platform_bucket: str,
    ingest_date: date,
    env: str,
    aws_region: str,
    aws_profile: str | None = None,
    fail_fast: bool = True,
) -> dict[str, Any]:
    """
    Ingest ALL tables for a given Postgres source (e.g. ehr_postgres) in one run.
    Writes:
      - one run_id shared across tables
      - one aggregate manifest (recommended)
      - optionally per-table results in the manifest
    """
    run_id = str(uuid.uuid4())
    started_at = utc_now()

    session = boto3.Session(profile_name=aws_profile, region_name=aws_region)
    s3 = session.client("s3")
    manifest_prefix = f"_manifests/source={db}/ingest_date={ingest_date.isoformat()}"

    if should_skip_if_already_successful(
        s3=s3, bucket=platform_bucket, manifest_prefix=manifest_prefix
    ):
        print("Ingest already successful for this date and source. Skipping.")
        return {
            "source": db,
            "run_id": run_id,
            "env": env,
            "ingest_date": ingest_date.isoformat(),
            "status": "skipped",
            "reason": "latest_manifest_success",
        }

    results: list[dict[str, Any]] = []
    status = "success"
    error: str | None = None

    for table in tables:
        try:
            results.append(
                ingest_table_to_bronze(
                    dsn=dsn,
                    db=db,
                    table=table,
                    platform_bucket=platform_bucket,
                    ingest_date=ingest_date,
                    s3_client=s3,
                    run_id=run_id,
                )
            )
        except Exception as e:
            status = "failed"
            error = f"{type(e).__name__}: {e}"
            results.append(
                {
                    "db": db,
                    "table": table,
                    "status": "failed",
                    "error": error,
                    "run_id": run_id,
                    "started_at": utc_now(),
                    "finished_at": utc_now(),
                }
            )
            if fail_fast:
                break

    finished_at = utc_now()

    manifest = {
        "source": db,
        "env": env,
        "run_id": run_id,
        "ingest_date": ingest_date.isoformat(),
        "started_at": started_at,
        "finished_at": finished_at,
        "status": status,
        "error": error,
        "inputs": {
            "tables": tables,
            "dsn_redacted": True,
        },
        "outputs": {
            "tables": results,
            "tables_succeeded": sum(1 for r in results if r.get("status") == "success"),
            "tables_failed": sum(1 for r in results if r.get("status") == "failed"),
        },
    }

    manifest_key = (
        f"_manifests/source={db}/ingest_date={ingest_date.isoformat()}/run_id={run_id}.json"
    )

    s3.put_object(
        Bucket=platform_bucket,
        Key=manifest_key,
        Body=json.dumps(manifest, indent=2).encode("utf-8"),
        ContentType="application/json",
    )

    return manifest


def _copy_stream(cursor, copy_sql: str) -> io.BytesIO:
    """
    NOTE: This buffers the COPY output in memory.
    If we hit huge tables, we can switch to a true streaming implementation.
    """
    buffer = io.BytesIO()
    cursor.copy_expert(copy_sql, buffer)
    buffer.seek(0)
    return buffer
