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

    for page in paginator.paginate(Bucket=bucket, Prefix=manifest_prefix):
        for obj in page.get("Contents", []):
            key = obj.get("Key", "")
            if not key.endswith(".json"):
                continue
            try:
                resp = s3.get_object(Bucket=bucket, Key=key)
                body = json.loads(resp["Body"].read())
                if body.get("status") == "success":
                    ts = body.get("finished_at", body.get("started_at", ""))
                    run_id = body.get("run_id", "")
                    if run_id:
                        successful_runs.append((ts, run_id))
            except Exception:
                log.warning("manifest_read_error", key=key, exc_info=True)

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
) -> pd.DataFrame:
    """Read all Parquet files under *prefix* into a single DataFrame.

    Uses ``pandas.read_parquet`` with pyarrow engine. Falls back to
    ``pyarrow.fs.S3FileSystem`` if storage_options fails.
    """
    s3_path = f"s3://{bucket}/{prefix}"

    # Try with profile from session first
    profile_name = s3_session._session.profile if hasattr(s3_session, "_session") else None
    try:
        storage_opts: dict[str, Any] = {}
        if profile_name:
            storage_opts["profile"] = profile_name
        df = pd.read_parquet(s3_path, engine="pyarrow", storage_options=storage_opts)
        log.info("read_bronze_entity", path=s3_path, rows=len(df))
        return df
    except Exception:
        log.info("storage_options_fallback", path=s3_path)

    try:
        import pyarrow.fs as pafs

        fs = pafs.S3FileSystem(region=region)
        df = pd.read_parquet(s3_path, engine="pyarrow", filesystem=fs)
        log.info("read_bronze_entity", path=s3_path, rows=len(df))
        return df
    except Exception:
        log.error("read_bronze_entity_failed", path=s3_path, exc_info=True)
        return pd.DataFrame()
