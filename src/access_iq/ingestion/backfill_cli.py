"""CLI for historical bronze backfill. Called by session.sh during make up."""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

import boto3
import structlog
from dateutil.relativedelta import relativedelta
from dotenv import load_dotenv

from access_iq.config import Settings
from access_iq.ingestion.backfill import backfill_from_staging
from access_iq.logging_config import configure_logging

log = structlog.get_logger(__name__)


def main() -> None:
    configure_logging()
    load_dotenv(Path.cwd() / ".env")

    parser = argparse.ArgumentParser(
        description="Historical bronze backfill from Trust staging CSVs."
    )
    parser.add_argument(
        "--staging-core-dir",
        type=str,
        help="Path to Trust staging core CSVs (default: auto-detect from TRUST_REPO)",
    )
    parser.add_argument(
        "--assume-role-arn",
        type=str,
        help="IAM role ARN to assume for S3 writes (e.g. the ECS task role)",
    )
    args = parser.parse_args()

    settings = Settings()  # type: ignore[call-arg]
    pipeline_start = date.today() - relativedelta(months=12)

    # Resolve staging directories
    import os

    if args.staging_core_dir:
        staging_base = Path(args.staging_core_dir).parent
    else:
        trust_repo = os.environ.get("TRUST_REPO", "")
        if trust_repo:
            staging_base = Path(trust_repo) / "data" / "staging"
        else:
            staging_base = Path.cwd().parent / "northshire-hospital-sim" / "data" / "staging"

    staging_core = staging_base / "core"
    staging_exports = staging_base / "exports"

    if not staging_core.exists():
        log.error("staging_dir_not_found", path=str(staging_core))
        sys.exit(1)

    session = boto3.Session(
        profile_name=settings.aws_profile,
        region_name=settings.aws_region,
    )

    if args.assume_role_arn:
        sts = session.client("sts")
        creds = sts.assume_role(
            RoleArn=args.assume_role_arn,
            RoleSessionName="backfill-bronze",
        )["Credentials"]
        s3 = boto3.client(
            "s3",
            region_name=settings.aws_region,
            aws_access_key_id=creds["AccessKeyId"],
            aws_secret_access_key=creds["SecretAccessKey"],
            aws_session_token=creds["SessionToken"],
        )
    else:
        s3 = session.client("s3")

    log.info(
        "backfill_start",
        pipeline_start=pipeline_start.isoformat(),
        staging_core=str(staging_core),
        staging_exports=str(staging_exports),
        env=settings.env,
    )

    result = backfill_from_staging(
        staging_core_dir=staging_core,
        staging_exports_dir=staging_exports,
        platform_bucket=settings.platform_bucket,
        pipeline_start_date=pipeline_start,
        env=settings.env,
        s3=s3,
        kms_key_arn=settings.lake_kms_key_arn,
    )

    total_partitions = sum(len(v) for v in result.values())
    total_entities = len(result)
    log.info("backfill_complete", entities=total_entities, partitions=total_partitions)


if __name__ == "__main__":
    main()
