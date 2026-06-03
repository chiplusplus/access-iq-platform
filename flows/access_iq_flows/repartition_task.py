"""Prefect task: repartition bronze Parquet files by business date."""

from __future__ import annotations

from datetime import date

import boto3
import structlog
from dateutil.relativedelta import relativedelta
from prefect import task

from access_iq.config import Settings
from access_iq.ingestion.repartition import repartition_bronze_key

log = structlog.get_logger(__name__)

SOURCE_ENTITIES = {
    "ehr_postgres": ["patient_demographics", "encounters", "referrals", "diagnoses"],
    "urgent_care_postgres": ["urgent_care_logs"],
    "sftp_appointments": ["appointments"],
    "trust_s3_diagnostics": ["diagnostics_orders"],
    "trust_s3_provider_ref": ["provider_site_reference"],
}


@task(retries=1, retry_delay_seconds=30, name="repartition-bronze")
def repartition_bronze(run_date: str, settings: Settings) -> dict:
    """Repartition all bronze entities from the current ingestion run by business date.

    Only repartitions data at ingest_date=run_date. If no data exists at that
    partition (already repartitioned or skipped by idempotency), this is a no-op.
    """
    ingest_date = date.fromisoformat(run_date)
    pipeline_start = date.today() - relativedelta(months=12)
    session = boto3.Session(region_name=settings.aws_region)
    s3 = session.client("s3")
    bucket = settings.platform_bucket

    results = {}
    repartitioned_sources = []

    for source, entities in SOURCE_ENTITIES.items():
        for entity in entities:
            prefix = (
                f"bronze/source={source}/entity={entity}/ingest_date={ingest_date.isoformat()}/"
            )

            resp = s3.list_objects_v2(Bucket=bucket, Prefix=prefix)
            if resp.get("KeyCount", 0) == 0:
                log.info("repartition_no_data", source=source, entity=entity)
                continue

            for obj in resp.get("Contents", []):
                if obj["Key"].endswith(".parquet"):
                    new_keys = repartition_bronze_key(
                        s3=s3,
                        bucket=bucket,
                        source_key=obj["Key"],
                        source=source,
                        entity=entity,
                        pipeline_start_date=pipeline_start,
                        kms_key_arn=settings.lake_kms_key_arn,
                    )
                    results[f"{source}/{entity}"] = new_keys
                    repartitioned_sources.append(source)

    # Only clean up manifests for sources that were actually repartitioned.
    # If ingestion was skipped (idempotency) there's nothing to clean up.
    for source in set(repartitioned_sources):
        manifest_prefix = f"_manifests/source={source}/ingest_date={ingest_date.isoformat()}/"
        manifest_resp = s3.list_objects_v2(Bucket=bucket, Prefix=manifest_prefix)
        for obj in manifest_resp.get("Contents", []):
            s3.delete_object(Bucket=bucket, Key=obj["Key"])
            log.info("repartition_manifest_cleanup", deleted=obj["Key"])

    log.info("repartition_complete", partitions_created=sum(len(v) for v in results.values()))
    return results
