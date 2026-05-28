"""S3 partition discovery and Bronze entity registry for profiling."""

from __future__ import annotations

import json
import re
from typing import Any

import pandas as pd
import structlog

log = structlog.get_logger(__name__)

_INGEST_DATE_RE = re.compile(r"ingest_date=(\d{4}-\d{2}-\d{2})")

BRONZE_ENTITIES: dict[str, dict[str, Any]] = {
    "patient_demographics": {
        "source_prefix": "source=ehr_postgres/entity=patient_demographics",
        "pk": "patient_id",
        "pk_type": "bigint",
        "join_keys": ["patient_id"],
    },
    "encounters": {
        "source_prefix": "source=ehr_postgres/entity=encounters",
        "pk": "encounter_id",
        "pk_type": "bigint",
        "join_keys": ["patient_id", "provider_id", "clinician_id"],
    },
    "referrals": {
        "source_prefix": "source=ehr_postgres/entity=referrals",
        "pk": "referral_id",
        "pk_type": "bigint",
        "join_keys": ["patient_id", "source_provider_id", "target_provider_id"],
    },
    "diagnoses": {
        "source_prefix": "source=ehr_postgres/entity=diagnoses",
        "pk": "diagnosis_id",
        "pk_type": "bigint",
        "join_keys": ["patient_id", "encounter_id"],
    },
    "appointments": {
        "source_prefix": "source=sftp_appointments/entity=appointments",
        "pk": "appointment_id",
        "pk_type": "varchar",
        "join_keys": ["patient_id", "nhs_pseudo_id"],
    },
    "urgent_care_logs": {
        "source_prefix": "source=urgent_care_postgres/entity=urgent_care_logs",
        "pk": "uc_log_id",
        "pk_type": "bigint",
        "join_keys": ["patient_id", "provider_id", "encounter_id"],
    },
    "diagnostics_orders": {
        "source_prefix": "source=trust_s3_diagnostics/entity=diagnostics_orders",
        "pk": "diagnostic_id",
        "pk_type": "varchar",
        "join_keys": ["patient_id", "referral_id", "encounter_id", "provider_id"],
    },
    "provider_site_reference": {
        "source_prefix": "source=trust_s3_provider_ref/entity=provider_site_reference",
        "pk": "provider_id",
        "pk_type": "bigint",
        "join_keys": ["provider_id", "provider_code"],
    },
}


def find_latest_partition(*, s3: Any, bucket: str, entity_prefix: str) -> str:
    """Find the latest ingest_date partition under bronze/{entity_prefix}/.

    Returns the full prefix ``bronze/{entity_prefix}/ingest_date={latest}/``
    or an empty string if no partitions exist.
    """
    prefix = f"bronze/{entity_prefix}/"
    paginator = s3.get_paginator("list_objects_v2")
    dates: list[str] = []
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix, Delimiter="/"):
        for cp in page.get("CommonPrefixes", []):
            m = _INGEST_DATE_RE.search(cp["Prefix"])
            if m:
                dates.append(m.group(1))
    if not dates:
        log.info("no_partitions_found", bucket=bucket, prefix=prefix)
        return ""
    latest = sorted(dates)[-1]
    result = f"bronze/{entity_prefix}/ingest_date={latest}/"
    log.info("latest_partition", partition=result)
    return result


def resolve_latest_run_id(*, s3: Any, bucket: str, manifest_prefix: str) -> str:
    """Find the latest successful run_id from manifests under *manifest_prefix*.

    Reads JSON manifests at ``_manifests/{source_prefix}/ingest_date={date}/``
    and returns the ``run_id`` of the latest one with ``"status": "success"``.
    Returns empty string if no successful manifest found.
    """
    paginator = s3.get_paginator("list_objects_v2")
    successful_runs: list[tuple[str, str]] = []  # (timestamp, run_id)
    manifest_count = 0
    error_count = 0

    for page in paginator.paginate(Bucket=bucket, Prefix=manifest_prefix):
        for obj in page.get("Contents", []):
            key = obj.get("Key", "")
            if not key.endswith(".json"):
                continue
            manifest_count = manifest_count + 1
            try:
                resp = s3.get_object(Bucket=bucket, Key=key)
                body = json.loads(resp["Body"].read())
                if body.get("status") == "success":
                    ts = body.get("finished_at", body.get("started_at", ""))
                    run_id = body.get("run_id", "")
                    if run_id:
                        successful_runs.append((ts, run_id))
            except Exception:
                error_count = error_count + 1
                log.warning("manifest_read_error", key=key, exc_info=True)

    if error_count > 0 and error_count == manifest_count:
        log.error(
            "all_manifests_failed",
            prefix=manifest_prefix,
            total=manifest_count,
            errors=error_count,
        )

    if not successful_runs:
        log.info("no_successful_manifests", prefix=manifest_prefix)
        return ""

    # Sort by timestamp descending, pick latest
    successful_runs.sort(key=lambda x: x[0], reverse=True)
    run_id = successful_runs[0][1]
    log.info("resolved_run_id", run_id=run_id)
    return run_id


def read_bronze_entity(
    *, s3_session: Any, bucket: str, prefix: str, region: str = "eu-west-2"
) -> pd.DataFrame | None:
    """Read all Parquet files under *prefix* into a single DataFrame.

    Uses boto3 session credentials with pyarrow S3FileSystem so SSO
    profiles work correctly.

    Returns ``None`` on error instead of an empty DataFrame so callers
    can distinguish "no data" from "read failed".
    """
    import pyarrow.fs as pafs

    bare_path = f"{bucket}/{prefix}"
    try:
        creds = s3_session.get_credentials().get_frozen_credentials()
        fs = pafs.S3FileSystem(
            region=region,
            access_key=creds.access_key,
            secret_key=creds.secret_key,
            session_token=creds.token,
        )
        df = pd.read_parquet(bare_path, engine="pyarrow", filesystem=fs)
        log.info("read_bronze_entity", path=bare_path, rows=len(df))
        return df
    except Exception:
        log.error("read_bronze_entity_failed", path=bare_path, exc_info=True)
        return None


def load_all_bronze_entities(
    *, aws_profile: str | None, aws_region: str, platform_bucket: str
) -> dict[str, pd.DataFrame]:
    """Load all registered Bronze entities from S3 into DataFrames.

    Shared helper used by both ``profile_bronze`` and ``readiness_gate``
    to avoid duplicating the partition-discovery / manifest-resolution /
    read loop.
    """
    import boto3

    session = boto3.Session(profile_name=aws_profile, region_name=aws_region)
    s3 = session.client("s3")

    entity_dfs: dict[str, pd.DataFrame] = {}
    for entity_name, entity_cfg in BRONZE_ENTITIES.items():
        partition = find_latest_partition(
            s3=s3,
            bucket=platform_bucket,
            entity_prefix=entity_cfg["source_prefix"],
        )
        if not partition:
            log.warning("no_partition", entity=entity_name)
            continue

        source_part = entity_cfg["source_prefix"].split("/")[0]
        date_part = partition.rstrip("/").split("/")[-1]
        manifest_prefix = f"_manifests/{source_part}/{date_part}/"
        run_id = resolve_latest_run_id(
            s3=s3, bucket=platform_bucket, manifest_prefix=manifest_prefix
        )

        read_prefix = f"{partition}run_id={run_id}/" if run_id else partition
        df = read_bronze_entity(
            s3_session=session,
            bucket=platform_bucket,
            prefix=read_prefix,
            region=aws_region,
        )
        if df is None:
            log.warning("read_failed", entity=entity_name)
            continue
        entity_dfs[entity_name] = df
        log.info("loaded_entity", entity=entity_name, rows=len(df))

    return entity_dfs
