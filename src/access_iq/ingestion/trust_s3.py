from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime
from typing import Any

from access_iq.ingestion.idempotency import should_skip_if_already_successful


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _put_manifest(*, s3: Any, bucket: str, key: str, manifest: dict[str, Any]) -> None:
    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=json.dumps(manifest, indent=2, default=str).encode("utf-8"),
        ContentType="application/json",
    )


def ingest_trust_provider_ref_to_bronze(
    *,
    s3: Any,
    trust_bucket: str,
    trust_key: str,
    platform_bucket: str,
    ingest_date: date,
    env: str,
    source_name: str = "trust_s3_provider_ref",
) -> dict[str, Any]:
    """
    Copy a single provider/site reference file from Trust S3 into platform Bronze using S3 server-side copy.
    """
    run_id = str(uuid.uuid4())
    started_at = utc_now()

    manifest_prefix = f"_manifests/source={source_name}/ingest_date={ingest_date.isoformat()}"

    if should_skip_if_already_successful(
        s3=s3, bucket=platform_bucket, manifest_prefix=manifest_prefix
    ):
        print("Ingest already successful for this date and source. Skipping.")
        return {
            "source": source_name,
            "run_id": run_id,
            "env": env,
            "ingest_date": ingest_date.isoformat(),
            "status": "skipped",
            "reason": "latest_manifest_success",
        }

    bronze_key = (
        f"bronze/source={source_name}/entity=provider_site_reference/"
        f"ingest_date={ingest_date.isoformat()}/run_id={run_id}/provider_site_reference.xlsx"
    )

    # Server-side copy (no download)
    s3.copy_object(
        Bucket=platform_bucket,
        Key=bronze_key,
        CopySource={"Bucket": trust_bucket, "Key": trust_key},
        MetadataDirective="COPY",
        TaggingDirective="COPY",
        ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    finished_at = utc_now()

    manifest = {
        "source": source_name,
        "env": env,
        "run_id": run_id,
        "ingest_date": ingest_date.isoformat(),
        "started_at": started_at,
        "finished_at": finished_at,
        "status": "success",
        "inputs": {
            "trust_bucket": trust_bucket,
            "trust_key": trust_key,
        },
        "outputs": {
            "objects_written": 1,
            "objects": [{"trust_key": trust_key, "s3_key": bronze_key}],
        },
    }

    manifest_key = f"_manifests/source={source_name}/ingest_date={ingest_date.isoformat()}/run_id={run_id}.json"
    _put_manifest(s3=s3, bucket=platform_bucket, key=manifest_key, manifest=manifest)
    return manifest


def ingest_trust_diagnostics_export_date_to_bronze(
    *,
    s3: Any,
    trust_bucket: str,
    prefix_root: str,
    export_date: date,
    platform_bucket: str,
    env: str,
    source_name: str = "trust_s3_diagnostics",
    fail_fast: bool = True,
) -> dict[str, Any]:
    """
    Copy all objects under:
      <prefix_root>/export_date=YYYYMMDD/

    into platform bronze:
      bronze/source=trust_s3_diagnostics/entity=diagnostics_orders/export_date=.../run_id=.../<filename>

    Uses server-side copy for simplicity + efficiency.
    """
    run_id = str(uuid.uuid4())
    started_at = utc_now()

    manifest_prefix = f"_manifests/source={source_name}/ingest_date={export_date.isoformat()}"

    if should_skip_if_already_successful(
        s3=s3, bucket=platform_bucket, manifest_prefix=manifest_prefix
    ):
        print("Ingest already successful for this date and source. Skipping.")
        return {
            "source": source_name,
            "env": env,
            "ingest_date": export_date.isoformat(),
            "run_id": run_id,
            "status": "skipped",
            "reason": "latest_manifest_success",
        }

    prefix_root = prefix_root.rstrip("/")
    trust_prefix = f"{prefix_root}/export_date={export_date.isoformat().replace('-', '')}/"

    results: list[dict[str, Any]] = []
    status = "success"
    error: str | None = None

    paginator = s3.get_paginator("list_objects_v2")

    for page in paginator.paginate(Bucket=trust_bucket, Prefix=trust_prefix):
        for obj in page.get("Contents", []):
            trust_key = obj.get("Key")
            if not trust_key:
                continue
            try:
                filename = trust_key.split("/")[-1] or "part.csv"
                bronze_key = (
                    f"bronze/source={source_name}/entity=diagnostics_orders/"
                    f"ingest_date={export_date.isoformat()}/run_id={run_id}/{filename}"
                )

                s3.copy_object(
                    Bucket=platform_bucket,
                    Key=bronze_key,
                    CopySource={"Bucket": trust_bucket, "Key": trust_key},
                    MetadataDirective="COPY",
                    TaggingDirective="COPY",
                    ContentType="text/csv",
                )

                results.append(
                    {
                        "trust_key": trust_key,
                        "s3_key": bronze_key,
                        "bytes": int(obj.get("Size", 0)),
                        "etag": obj.get("ETag"),
                        "status": "success",
                    }
                )
            except Exception as e:
                status = "failed"
                err = f"{type(e).__name__}: {e}"
                results.append({"trust_key": trust_key, "status": "failed", "error": err})
                if fail_fast:
                    error = err
                    break
        if status == "failed" and fail_fast:
            break

    if not results:
        print(f"Warning: No objects found in {trust_bucket}/{trust_prefix}")

    finished_at = utc_now()

    manifest = {
        "source": source_name,
        "env": env,
        "run_id": run_id,
        "ingest_date": export_date.isoformat(),
        "started_at": started_at,
        "finished_at": finished_at,
        "status": status,
        "error": error,
        "inputs": {
            "trust_bucket": trust_bucket,
            "trust_prefix": trust_prefix,
        },
        "outputs": {
            "objects_written": sum(1 for r in results if r.get("status") == "success"),
            "objects_failed": sum(1 for r in results if r.get("status") == "failed"),
            "objects": results,
        },
    }

    manifest_key = f"_manifests/source={source_name}/ingest_date={export_date.isoformat()}/run_id={run_id}.json"
    _put_manifest(s3=s3, bucket=platform_bucket, key=manifest_key, manifest=manifest)
    return manifest
