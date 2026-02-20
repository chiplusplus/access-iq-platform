from __future__ import annotations

import argparse
import json
import os
from datetime import date
from pathlib import Path

import boto3
from dotenv import load_dotenv
from pydantic import BaseModel

from access_iq.ingestion.postgres import ingest_postgres_source_to_bronze
from access_iq.ingestion.sftp import ingest_sftp_directory_to_bronze
from access_iq.ingestion.trust_s3 import (
    ingest_trust_diagnostics_export_date_to_bronze,
    ingest_trust_provider_ref_to_bronze,
)


class PostgresSource(BaseModel):
    dsn_env: str
    tables: list[str]


class Config(BaseModel):
    env: str
    aws_region: str
    platform_bucket: str
    postgres_sources: dict[str, PostgresSource]
    sftp_sources: dict[str, dict[str, str]]
    trust_s3: dict[str, dict[str, str]]
    aws_profile: str | None = None


def load_config() -> Config:
    load_dotenv(".env")
    env = os.getenv("ENV", "dev")

    # IMPORTANT: config should live at repo root: ./config/dev.json
    config_path = Path.cwd() / "config" / f"{env}.json"
    with open(config_path) as f:
        config_data = json.load(f)

    pg_sources = config_data["sources"]["postgres"]

    return Config(
        env=env,
        aws_region=config_data["aws_region"],
        platform_bucket=config_data["platform_bucket"],
        postgres_sources={k: PostgresSource(**v) for k, v in pg_sources.items()},
        sftp_sources=config_data["sources"]["sftp"],
        trust_s3=config_data["sources"]["trust_s3"],
        aws_profile=os.getenv("AWS_PROFILE") or None,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("cmd", choices=["ingest-postgres", "ingest-sftp", "ingest-trust-s3"])
    parser.add_argument("--db", default="all", help="ehr_postgres | urgent_care_postgres | all")
    parser.add_argument("--ingest-date", default=date.today().isoformat())
    parser.add_argument("--fail-fast", action="store_true", default=False)
    parser.add_argument("--name", default="appointments")
    args = parser.parse_args()

    ingest_date = date.fromisoformat(args.ingest_date)
    config = load_config()

    if args.cmd == "ingest-postgres":
        dbs = list(config.postgres_sources.keys()) if args.db == "all" else [args.db]

        for db in dbs:
            if db not in config.postgres_sources:
                raise SystemExit(
                    f"Unknown db '{db}'. Known: {list(config.postgres_sources.keys())}"
                )

            src = config.postgres_sources[db]
            dsn = os.getenv(src.dsn_env, "")
            if not dsn:
                raise SystemExit(f"Missing required env var for {db}: {src.dsn_env}")

            print(f"\n=== Ingesting Postgres source: {db} ===")
            manifest = ingest_postgres_source_to_bronze(
                db=db,
                dsn=dsn,
                tables=src.tables,
                platform_bucket=config.platform_bucket,
                ingest_date=ingest_date,
                env=config.env,
                aws_region=config.aws_region,
                aws_profile=config.aws_profile,
                fail_fast=args.fail_fast,
            )
            print(f"{db}: {manifest['status']} (run_id={manifest['run_id']})")

    elif args.cmd == "ingest-sftp":
        try:
            sftp_cfg = config.sftp_sources[args.name]
        except KeyError:
            raise SystemExit(
                f"Unknown SFTP source '{args.name}'. Known: {list(config.sftp_sources.keys())}"
            ) from None

        host = os.getenv(sftp_cfg["host_env"])
        if not host:
            raise SystemExit(f"Missing required env var: {sftp_cfg['host_env']}")
        port = int(os.getenv(sftp_cfg["port_env"], "22"))
        user = os.getenv(sftp_cfg["user_env"])
        if not user:
            raise SystemExit(f"Missing required env var: {sftp_cfg['user_env']}")
        password = os.getenv(sftp_cfg["password_env"])
        if not password:
            raise SystemExit(f"Missing required env var: {sftp_cfg['password_env']}")
        remote_dir = sftp_cfg["remote_dir"]
        source_name = sftp_cfg.get("source_name", f"sftp_{args.name}")

        manifest = ingest_sftp_directory_to_bronze(
            source_name=source_name,
            host=host,
            port=port,
            username=user,
            password=password,
            remote_dir=remote_dir,
            platform_bucket=config.platform_bucket,
            ingest_date=ingest_date,
            env=config.env,
            aws_region=config.aws_region,
            aws_profile_platform=config.aws_profile,
            fail_fast=args.fail_fast,
        )

        print(f"{source_name}: {manifest['status']} (run_id={manifest['run_id']})")

    elif args.cmd == "ingest-trust-s3":
        trust_cfg = config.trust_s3

        base_cfg = trust_cfg["base"]
        diagnostics_cfg = trust_cfg["diagnostics"]
        provider_cfg = trust_cfg["provider_ref"]

        session = boto3.Session(
            profile_name=base_cfg["profile"],
            region_name=config.aws_region,
        )
        s3 = session.client("s3")

        providers_manifest = ingest_trust_provider_ref_to_bronze(
            s3=s3,
            trust_bucket=base_cfg["bucket"],
            trust_key=provider_cfg["key"],
            platform_bucket=config.platform_bucket,
            ingest_date=ingest_date,
            env=config.env,
            source_name=provider_cfg.get("source_name", "trust_s3_provider_ref"),
        )
        print("provider_ref:", providers_manifest["status"], providers_manifest["run_id"])

        diagnostics_manifest = ingest_trust_diagnostics_export_date_to_bronze(
            s3=s3,
            trust_bucket=base_cfg["bucket"],
            prefix_root=diagnostics_cfg["prefix_root"],
            export_date=ingest_date,
            platform_bucket=config.platform_bucket,
            env=config.env,
            source_name=diagnostics_cfg.get("source_name", "trust_s3_diagnostics"),
            fail_fast=args.fail_fast,
        )
        print("diagnostics:", diagnostics_manifest["status"], diagnostics_manifest["run_id"])


if __name__ == "__main__":
    main()
