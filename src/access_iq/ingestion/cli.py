from __future__ import annotations

import argparse
import json
import os
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel

from access_iq.ingestion.postgres import ingest_postgres_source_to_bronze


class PostgresSource(BaseModel):
    dsn_env: str
    tables: list[str]


class Config(BaseModel):
    env: str
    aws_region: str
    platform_bucket: str
    postgres_sources: dict[str, PostgresSource]
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
        aws_profile=os.getenv("AWS_PROFILE") or None,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("cmd", choices=["ingest-postgres"])
    parser.add_argument("--db", default="all", help="ehr_postgres | urgent_care_postgres | all")
    parser.add_argument("--ingest-date", default=date.today().isoformat())
    parser.add_argument("--fail-fast", action="store_true", default=True)
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


if __name__ == "__main__":
    main()
