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
from access_iq.ingestion.postgres import ENTITY_DATE_COLUMNS

log = structlog.get_logger(__name__)

ENTITY_COLUMN_TYPES: dict[str, dict[str, str]] = {
    "patient_demographics": {
        "patient_id": "int64",
        "nhs_pseudo_id": "str",  # Glue expects varchar; CSV reads as int64
        "date_of_birth": "date",
        "age": "int64",
        "imd_decile": "int64",
        "chronic_conditions_count": "int64",
        "is_active": "bool",
        "registration_start_date": "date",
        "registration_end_date": "date",
        "updated_at": "timestamp",
    },
    "encounters": {
        "encounter_id": "int64",
        "patient_id": "int64",
        "provider_id": "int64",
        "clinician_id": "int64",
        "encounter_datetime_start": "timestamp",
        "encounter_datetime_end": "timestamp",
        "was_attended": "bool",
        "first_attendance_flag": "bool",
        "wait_time_days": "int64",
        "created_at": "timestamp",
        "updated_at": "timestamp",
    },
    "referrals": {
        "referral_id": "int64",
        "patient_id": "int64",
        "source_provider_id": "int64",
        "target_provider_id": "int64",
        "referral_datetime": "timestamp",
        "created_at": "timestamp",
        "updated_at": "timestamp",
    },
    "diagnoses": {
        "diagnosis_id": "int64",
        "patient_id": "int64",
        "encounter_id": "int64",
        "coded_datetime": "timestamp",
        "clinical_datetime": "timestamp",
        "created_at": "timestamp",
        "updated_at": "timestamp",
    },
    "urgent_care_logs": {
        "uc_log_id": "int64",
        "patient_id": "int64",
        "provider_id": "int64",
        "encounter_id": "int64",
        "arrival_datetime": "timestamp",
        "triage_datetime": "timestamp",
        "seen_by_clinician_datetime": "timestamp",
        "departure_datetime": "timestamp",
        "created_at": "timestamp",
        "updated_at": "timestamp",
    },
}


def _coerce_types(df: pd.DataFrame, entity: str) -> pd.DataFrame:
    """Cast DataFrame columns to match the Glue external table schema."""
    type_map = ENTITY_COLUMN_TYPES.get(entity, {})
    for col, dtype in type_map.items():
        if col not in df.columns:
            if dtype == "timestamp":
                df[col] = pd.Timestamp.now(tz="UTC")
            else:
                continue
        if dtype == "timestamp":
            df[col] = pd.to_datetime(df[col], errors="coerce")
        elif dtype == "date":
            df[col] = pd.to_datetime(df[col], errors="coerce").dt.date
        elif dtype == "int64":
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")
        elif dtype == "bool":
            df[col] = (
                df[col]
                .map(
                    {
                        "True": True,
                        "true": True,
                        "1": True,
                        "False": False,
                        "false": False,
                        "0": False,
                    }
                )
                .astype("boolean")
            )
        elif dtype == "str":
            df[col] = df[col].astype(str)
    return df


BACKFILL_SOURCES: list[dict[str, str]] = [
    {"csv": "patients.csv", "source": "ehr_postgres", "entity": "patient_demographics"},
    {"csv": "encounters.csv", "source": "ehr_postgres", "entity": "encounters"},
    {"csv": "referrals.csv", "source": "ehr_postgres", "entity": "referrals"},
    {"csv": "diagnoses.csv", "source": "ehr_postgres", "entity": "diagnoses"},
    {"csv": "urgent_care_logs.csv", "source": "urgent_care_postgres", "entity": "urgent_care_logs"},
]


def _write_partition(
    *,
    df: pd.DataFrame,
    source: str,
    entity: str,
    biz_date: date,
    platform_bucket: str,
    env: str,
    s3: Any,
    kms_key_arn: str | None = None,
) -> str:
    """Write a single bronze partition (Parquet + manifest) and return the S3 key."""
    run_id = str(uuid.uuid4())
    started_at = utc_now_iso()

    out_table = pa.Table.from_pandas(df, preserve_index=False)
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
                    "rows": len(df),
                }
            ],
            "tables_succeeded": 1,
            "tables_failed": 0,
        },
    )
    write_manifest(s3=s3, bucket=platform_bucket, manifest=manifest, kms_key_arn=kms_key_arn)
    return bronze_key


def _backfill_core_csvs(
    *,
    staging_core_dir: Path,
    pipeline_start_date: date,
    platform_bucket: str,
    env: str,
    s3: Any,
    kms_key_arn: str | None = None,
) -> dict[str, Any]:
    """Backfill Postgres-sourced entities from core staging CSVs."""
    results: dict[str, Any] = {}

    for entry in BACKFILL_SOURCES:
        csv_path = staging_core_dir / entry["csv"]
        source = entry["source"]
        entity = entry["entity"]
        date_col = ENTITY_DATE_COLUMNS.get(entity)

        if not csv_path.exists():
            log.warning("backfill_csv_missing", path=str(csv_path), entity=entity)
            continue

        df = pd.read_csv(csv_path, dtype=str)
        if df.empty:
            log.info("backfill_empty_csv", entity=entity)
            continue

        df = _coerce_types(df, entity)

        if date_col is None:
            partitions: dict[date, pd.DataFrame] = {date.today(): df}
        else:
            raw_dates = pd.to_datetime(df[date_col]).dt.date
            df["_biz_date"] = raw_dates.apply(
                lambda d: pipeline_start_date if d < pipeline_start_date else d
            )
            partitions = {
                date.fromisoformat(str(biz_date)): group.drop(columns=["_biz_date"])
                for biz_date, group in df.groupby("_biz_date")
            }

        log.info(
            "backfill_entity_start",
            source=source,
            entity=entity,
            partitions=len(partitions),
            rows=len(df),
        )
        table_keys = [
            _write_partition(
                df=group_df,
                source=source,
                entity=entity,
                biz_date=biz_date,
                platform_bucket=platform_bucket,
                env=env,
                s3=s3,
                kms_key_arn=kms_key_arn,
            )
            for biz_date, group_df in partitions.items()
        ]
        log.info("backfill_entity_done", source=source, entity=entity, partitions=len(partitions))
        results[entity] = table_keys

    return results


def _backfill_dated_exports(
    *,
    exports_dir: Path,
    subfolder: str,
    filename_glob: str,
    source: str,
    entity: str,
    pipeline_start_date: date,
    platform_bucket: str,
    env: str,
    s3: Any,
    kms_key_arn: str | None = None,
) -> list[str]:
    """Backfill export CSVs where the date is embedded in the filename (YYYYMMDD_*.csv)."""
    export_path = exports_dir / subfolder
    if not export_path.exists():
        log.warning("backfill_export_dir_missing", path=str(export_path), entity=entity)
        return []

    files = sorted(export_path.glob(filename_glob))
    if not files:
        log.info("backfill_no_export_files", entity=entity)
        return []

    keys: list[str] = []
    for csv_file in files:
        date_str = csv_file.name[:8]
        try:
            file_date = date(int(date_str[:4]), int(date_str[4:6]), int(date_str[6:8]))
        except ValueError:
            log.warning("backfill_bad_filename", file=csv_file.name, entity=entity)
            continue

        if file_date < pipeline_start_date:
            file_date = pipeline_start_date

        df = pd.read_csv(csv_file, dtype=str)
        if df.empty:
            continue

        key = _write_partition(
            df=df,
            source=source,
            entity=entity,
            biz_date=file_date,
            platform_bucket=platform_bucket,
            env=env,
            s3=s3,
            kms_key_arn=kms_key_arn,
        )
        keys.append(key)

    log.info("backfill_entity_done", source=source, entity=entity, partitions=len(keys))
    return keys


def backfill_from_staging(
    *,
    staging_core_dir: Path,
    staging_exports_dir: Path,
    platform_bucket: str,
    pipeline_start_date: date,
    env: str,
    s3: Any,
    kms_key_arn: str | None = None,
) -> dict[str, Any]:
    """Backfill all bronze entities from Trust staging (core CSVs + export CSVs)."""
    results = _backfill_core_csvs(
        staging_core_dir=staging_core_dir,
        pipeline_start_date=pipeline_start_date,
        platform_bucket=platform_bucket,
        env=env,
        s3=s3,
        kms_key_arn=kms_key_arn,
    )

    results["appointments"] = _backfill_dated_exports(
        exports_dir=staging_exports_dir,
        subfolder="appointments",
        filename_glob="*_appointments.csv",
        source="sftp_appointments",
        entity="appointments",
        pipeline_start_date=pipeline_start_date,
        platform_bucket=platform_bucket,
        env=env,
        s3=s3,
        kms_key_arn=kms_key_arn,
    )

    results["diagnostics_orders"] = _backfill_dated_exports(
        exports_dir=staging_exports_dir,
        subfolder="diagnostics",
        filename_glob="*_diagnostic_orders.csv",
        source="trust_s3_diagnostics",
        entity="diagnostics_orders",
        pipeline_start_date=pipeline_start_date,
        platform_bucket=platform_bucket,
        env=env,
        s3=s3,
        kms_key_arn=kms_key_arn,
    )

    # Provider reference — static entity, single partition at pipeline start
    provider_xlsx = staging_exports_dir / "providers" / "sites_and_services_master.xlsx"
    if provider_xlsx.exists():
        df = pd.read_excel(provider_xlsx, engine="openpyxl", dtype=str)
        if not df.empty:
            key = _write_partition(
                df=df,
                source="trust_s3_provider_ref",
                entity="provider_site_reference",
                biz_date=pipeline_start_date,
                platform_bucket=platform_bucket,
                env=env,
                s3=s3,
                kms_key_arn=kms_key_arn,
            )
            results["provider_site_reference"] = [key]
            log.info(
                "backfill_entity_done",
                source="trust_s3_provider_ref",
                entity="provider_site_reference",
                partitions=1,
            )
    else:
        log.warning("backfill_provider_ref_missing", path=str(provider_xlsx))

    return results
