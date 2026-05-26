from __future__ import annotations

import io
import uuid
from datetime import date
from typing import Any

import boto3
import psycopg2
import pyarrow as pa
import pyarrow.parquet as pq
import structlog

from access_iq.ingestion.idempotency import should_skip_if_already_successful
from access_iq.ingestion.manifests import (
    Manifest,
    ManifestStatus,
    build_manifest_prefix,
    s3_kms_args,
    utc_now_iso,
    write_manifest,
)

log = structlog.get_logger(__name__)


def ingest_table_to_bronze(
    *,
    dsn: str,
    db: str,
    table: str,
    platform_bucket: str,
    ingest_date: date,
    s3_client: Any,
    run_id: str,
    kms_key_arn: str | None = None,
) -> dict[str, Any]:
    started_at = utc_now_iso()

    bronze_key = (
        f"bronze/source={db}/entity={table}/"
        f"ingest_date={ingest_date.isoformat()}/run_id={run_id}/{table}.parquet"
    )

    conn = psycopg2.connect(dsn)
    cursor = conn.cursor()

    try:
        extra = s3_kms_args(kms_key_arn)
        s3_client.upload_fileobj(
            Fileobj=_parquet_buffer(cursor, table),
            Bucket=platform_bucket,
            Key=bronze_key,
            ExtraArgs=extra if extra else None,
        )
    finally:
        cursor.close()
        conn.close()

    finished_at = utc_now_iso()

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
    kms_key_arn: str | None = None,
) -> dict[str, Any]:
    run_id = str(uuid.uuid4())
    started_at = utc_now_iso()

    bound_log = log.bind(run_id=run_id, source=db, env=env)

    session = boto3.Session(profile_name=aws_profile, region_name=aws_region)
    s3 = session.client("s3")
    manifest_prefix = build_manifest_prefix(source=db, ingest_date=ingest_date.isoformat())

    if should_skip_if_already_successful(
        s3=s3, bucket=platform_bucket, manifest_prefix=manifest_prefix
    ):
        bound_log.info("ingest_skipped", reason="latest_manifest_success")
        return {
            "source": db,
            "run_id": run_id,
            "env": env,
            "ingest_date": ingest_date.isoformat(),
            "status": "skipped",
            "reason": "latest_manifest_success",
        }

    results: list[dict[str, Any]] = []
    status: ManifestStatus = "success"
    run_errors: list[str] = []

    for table in tables:
        try:
            bound_log.info("table_ingest_start", table=table)
            results.append(
                ingest_table_to_bronze(
                    dsn=dsn,
                    db=db,
                    table=table,
                    platform_bucket=platform_bucket,
                    ingest_date=ingest_date,
                    s3_client=s3,
                    run_id=run_id,
                    kms_key_arn=kms_key_arn,
                )
            )
            bound_log.info("table_ingest_done", table=table, status="success")
        except Exception as e:
            status = "failed"
            per_table_error = f"{type(e).__name__}: {e}"
            run_errors.append(per_table_error)
            results.append(
                {
                    "db": db,
                    "table": table,
                    "status": "failed",
                    "error": per_table_error,
                    "run_id": run_id,
                    "started_at": utc_now_iso(),
                    "finished_at": utc_now_iso(),
                }
            )
            bound_log.error("table_ingest_failed", table=table, error=per_table_error)
            if fail_fast:
                break

    finished_at = utc_now_iso()

    manifest = Manifest(
        source=db,
        env=env,
        run_id=run_id,
        ingest_date=ingest_date.isoformat(),
        started_at=started_at,
        finished_at=finished_at,
        status=status,
        error=run_errors,
        inputs={"tables": tables, "dsn_redacted": True},
        outputs={
            "tables": results,
            "tables_succeeded": sum(1 for r in results if r.get("status") == "success"),
            "tables_failed": sum(1 for r in results if r.get("status") == "failed"),
        },
    )

    write_manifest(s3=s3, bucket=platform_bucket, manifest=manifest, kms_key_arn=kms_key_arn)
    return manifest.model_dump()


def _parquet_buffer(cursor: Any, table: str) -> io.BytesIO:
    """Fetch all rows via SELECT and write to in-memory Parquet buffer."""
    cursor.execute(f'SELECT * FROM "{table}"')
    columns = [desc[0] for desc in cursor.description]
    rows = cursor.fetchall()
    data = {col: [row[i] for row in rows] for i, col in enumerate(columns)}
    tbl = pa.Table.from_pydict(data)
    buf = io.BytesIO()
    pq.write_table(tbl, buf, compression="snappy")
    buf.seek(0)
    return buf
