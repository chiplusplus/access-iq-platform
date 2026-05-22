from __future__ import annotations

import argparse
import os
from datetime import date

import boto3
import structlog

from access_iq.config import Settings
from access_iq.ingestion.postgres import ingest_postgres_source_to_bronze
from access_iq.ingestion.sftp import ingest_sftp_directory_to_bronze
from access_iq.ingestion.trust_s3 import (
    ingest_trust_diagnostics_export_date_to_bronze,
    ingest_trust_provider_ref_to_bronze,
)
from access_iq.logging_config import configure_logging

log = structlog.get_logger(__name__)


def main() -> None:
    configure_logging()

    parser = argparse.ArgumentParser()
    parser.add_argument("cmd", choices=["ingest-postgres", "ingest-sftp", "ingest-trust-s3"])
    parser.add_argument("--db", default="all", help="ehr_postgres | urgent_care_postgres | all")
    parser.add_argument("--ingest-date", default=date.today().isoformat())
    parser.add_argument("--fail-fast", action="store_true", default=False)
    parser.add_argument("--name", default="appointments")
    args = parser.parse_args()

    ingest_date = date.fromisoformat(args.ingest_date)
    settings = Settings()  # type: ignore[call-arg]  # pydantic-settings resolves required fields from env

    structlog.contextvars.bind_contextvars(env=settings.env)

    if args.cmd == "ingest-postgres":
        dbs = list(settings.postgres_sources.keys()) if args.db == "all" else [args.db]

        for db in dbs:
            if db not in settings.postgres_sources:
                raise SystemExit(
                    f"Unknown db '{db}'. Known: {list(settings.postgres_sources.keys())}"
                )

            src = settings.postgres_sources[db]
            dsn = os.getenv(src.dsn_env, "")
            if not dsn:
                raise SystemExit(f"Missing required env var for {db}: {src.dsn_env}")

            log.info("ingest_start", source=db, cmd="ingest-postgres")
            manifest = ingest_postgres_source_to_bronze(
                db=db,
                dsn=dsn,
                tables=src.tables,
                platform_bucket=settings.platform_bucket,
                ingest_date=ingest_date,
                env=settings.env,
                aws_region=settings.aws_region,
                aws_profile=settings.aws_profile,
                fail_fast=args.fail_fast,
                kms_key_arn=settings.lake_kms_key_arn,
            )
            log.info(
                "ingest_done",
                source=db,
                status=manifest["status"],
                run_id=manifest["run_id"],
            )

    elif args.cmd == "ingest-sftp":
        try:
            sftp_cfg = settings.sftp_sources[args.name]
        except KeyError:
            raise SystemExit(
                f"Unknown SFTP source '{args.name}'. Known: {list(settings.sftp_sources.keys())}"
            ) from None

        host = os.getenv(sftp_cfg.host_env)
        if not host:
            raise SystemExit(f"Missing required env var: {sftp_cfg.host_env}")
        port = int(os.getenv(sftp_cfg.port_env, "22"))
        user = os.getenv(sftp_cfg.user_env)
        if not user:
            raise SystemExit(f"Missing required env var: {sftp_cfg.user_env}")

        private_key: str | None = None
        password: str | None = None
        if sftp_cfg.private_key_env:
            private_key = os.getenv(sftp_cfg.private_key_env)
            if not private_key:
                raise SystemExit(f"Missing required env var: {sftp_cfg.private_key_env}")
        elif sftp_cfg.password_env:
            password = os.getenv(sftp_cfg.password_env)
            if not password:
                raise SystemExit(f"Missing required env var: {sftp_cfg.password_env}")
        else:
            raise SystemExit("SFTP source must define either private_key_env or password_env")

        remote_dir = sftp_cfg.remote_dir
        source_name = sftp_cfg.source_name or f"sftp_{args.name}"

        log.info("ingest_start", source=source_name, cmd="ingest-sftp")
        manifest = ingest_sftp_directory_to_bronze(
            source_name=source_name,
            host=host,
            port=port,
            username=user,
            password=password,
            private_key=private_key,
            remote_dir=remote_dir,
            platform_bucket=settings.platform_bucket,
            ingest_date=ingest_date,
            env=settings.env,
            aws_region=settings.aws_region,
            aws_profile_platform=settings.aws_profile,
            fail_fast=args.fail_fast,
            kms_key_arn=settings.lake_kms_key_arn,
        )
        log.info(
            "ingest_done",
            source=source_name,
            status=manifest["status"],
            run_id=manifest["run_id"],
        )

    elif args.cmd == "ingest-trust-s3":
        if settings.trust_s3 is None:
            raise SystemExit("Missing required env var: ACCESS_IQ_TRUST_S3")

        trust_cfg = settings.trust_s3
        base_cfg = trust_cfg.base
        diagnostics_cfg = trust_cfg.diagnostics
        provider_cfg = trust_cfg.provider_ref

        if provider_cfg.key is None:
            raise SystemExit("Missing trust_s3.provider_ref.key in ACCESS_IQ_TRUST_S3")
        if diagnostics_cfg.prefix_root is None:
            raise SystemExit("Missing trust_s3.diagnostics.prefix_root in ACCESS_IQ_TRUST_S3")

        session = boto3.Session(
            profile_name=base_cfg.profile,
            region_name=settings.aws_region,
        )
        s3 = session.client("s3")

        log.info("ingest_start", source="trust_s3_provider_ref", cmd="ingest-trust-s3")
        providers_manifest = ingest_trust_provider_ref_to_bronze(
            s3=s3,
            trust_bucket=base_cfg.bucket,
            trust_key=provider_cfg.key,
            platform_bucket=settings.platform_bucket,
            ingest_date=ingest_date,
            env=settings.env,
            source_name=provider_cfg.source_name or "trust_s3_provider_ref",
            kms_key_arn=settings.lake_kms_key_arn,
        )
        log.info(
            "ingest_done",
            source="provider_ref",
            status=providers_manifest["status"],
            run_id=providers_manifest["run_id"],
        )

        log.info("ingest_start", source="trust_s3_diagnostics", cmd="ingest-trust-s3")
        diagnostics_manifest = ingest_trust_diagnostics_export_date_to_bronze(
            s3=s3,
            trust_bucket=base_cfg.bucket,
            prefix_root=diagnostics_cfg.prefix_root,
            export_date=ingest_date,
            platform_bucket=settings.platform_bucket,
            env=settings.env,
            source_name=diagnostics_cfg.source_name or "trust_s3_diagnostics",
            fail_fast=args.fail_fast,
            kms_key_arn=settings.lake_kms_key_arn,
        )
        log.info(
            "ingest_done",
            source="diagnostics",
            status=diagnostics_manifest["status"],
            run_id=diagnostics_manifest["run_id"],
        )


if __name__ == "__main__":
    main()
