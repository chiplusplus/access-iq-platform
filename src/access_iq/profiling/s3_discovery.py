"""S3 partition discovery and Bronze entity registry for profiling."""

from __future__ import annotations

from typing import Any

import pandas as pd
import structlog

log = structlog.get_logger(__name__)

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


def read_bronze_entity(
    *, s3_session: Any, bucket: str, prefix: str, region: str = "eu-west-2"
) -> pd.DataFrame | None:
    """Read all Parquet files under *prefix* into a single DataFrame.

    Uses boto3 session credentials with pyarrow S3FileSystem so SSO
    profiles work correctly.

    Returns ``None`` on error instead of an empty DataFrame so callers
    can distinguish "no data" from "read failed".
    """
    import pyarrow as pa
    import pyarrow.dataset as pads
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
        dataset = pads.dataset(bare_path, filesystem=fs, format="parquet")
        fragments = list(dataset.get_fragments())
        schema = pa.unify_schemas(
            [f.physical_schema for f in fragments],
            promote_options="permissive",
        )
        dataset = pads.dataset(bare_path, filesystem=fs, format="parquet", schema=schema)
        df = dataset.to_table().to_pandas()
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

    entity_dfs: dict[str, pd.DataFrame] = {}
    for entity_name, entity_cfg in BRONZE_ENTITIES.items():
        entity_prefix = f"bronze/{entity_cfg['source_prefix']}/"
        df = read_bronze_entity(
            s3_session=session,
            bucket=platform_bucket,
            prefix=entity_prefix,
            region=aws_region,
        )
        if df is None:
            log.warning("read_failed", entity=entity_name)
            continue
        entity_dfs[entity_name] = df
        log.info("loaded_entity", entity=entity_name, rows=len(df))

    return entity_dfs
