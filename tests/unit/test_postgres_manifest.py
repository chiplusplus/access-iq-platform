from __future__ import annotations

from datetime import date
from unittest.mock import patch

import boto3
from moto import mock_aws

from access_iq.ingestion.manifests import Manifest
from access_iq.ingestion.postgres import ingest_postgres_source_to_bronze


@mock_aws
def test_per_table_error_is_scoped_string_not_shared_list() -> None:
    """Bug 1 regression: each failed table record must have its OWN error string,
    not a reference to the growing run-level error list."""
    s3 = boto3.client("s3", region_name="eu-west-2")
    bucket = "test-platform"
    s3.create_bucket(
        Bucket=bucket,
        CreateBucketConfiguration={"LocationConstraint": "eu-west-2"},
    )

    call_count = 0

    def fake_ingest_table(
        *,
        dsn,
        db,
        table,
        platform_bucket,
        ingest_date,
        s3_client,
        run_id,
        kms_key_arn=None,
        date_column=None,
    ):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("table1 failed")
        if call_count == 2:
            raise ValueError("table2 failed")
        return {
            "db": db,
            "table": table,
            "started_at": "t",
            "finished_at": "t",
            "status": "success",
            "s3_key": f"bronze/{table}.csv",
        }

    with patch(
        "access_iq.ingestion.postgres.ingest_table_to_bronze",
        side_effect=fake_ingest_table,
    ):
        result = ingest_postgres_source_to_bronze(
            db="ehr",
            dsn="host=x dbname=y",
            tables=["table1", "table2", "table3"],
            platform_bucket=bucket,
            ingest_date=date(2026, 5, 12),
            env="dev",
            aws_region="eu-west-2",
            fail_fast=False,
        )

    assert result["status"] == "failed"

    tables_output = result["outputs"]["tables"]
    failed_tables = [t for t in tables_output if t["status"] == "failed"]
    assert len(failed_tables) == 2

    assert isinstance(failed_tables[0]["error"], str)
    assert isinstance(failed_tables[1]["error"], str)
    assert "table1" in failed_tables[0]["error"]
    assert "table2" in failed_tables[1]["error"]
    assert "table2" not in failed_tables[0]["error"]
    assert "table1" not in failed_tables[1]["error"]

    assert isinstance(result["error"], list)
    assert len(result["error"]) == 2

    Manifest.model_validate(result)


@mock_aws
def test_successful_ingest_manifest_validates() -> None:
    s3 = boto3.client("s3", region_name="eu-west-2")
    bucket = "test-platform"
    s3.create_bucket(
        Bucket=bucket,
        CreateBucketConfiguration={"LocationConstraint": "eu-west-2"},
    )

    def fake_ingest_table(
        *,
        dsn,
        db,
        table,
        platform_bucket,
        ingest_date,
        s3_client,
        run_id,
        kms_key_arn=None,
        date_column=None,
    ):
        s3_client.put_object(
            Bucket=platform_bucket,
            Key=f"bronze/source={db}/entity={table}/{table}.csv",
            Body=b"col\nval\n",
        )
        return {
            "db": db,
            "table": table,
            "started_at": "t",
            "finished_at": "t",
            "status": "success",
            "s3_key": f"bronze/{table}.csv",
        }

    with patch(
        "access_iq.ingestion.postgres.ingest_table_to_bronze",
        side_effect=fake_ingest_table,
    ):
        result = ingest_postgres_source_to_bronze(
            db="ehr",
            dsn="host=x dbname=y",
            tables=["patients"],
            platform_bucket=bucket,
            ingest_date=date(2026, 5, 12),
            env="dev",
            aws_region="eu-west-2",
        )

    assert result["status"] == "success"
    assert result["error"] == []
    Manifest.model_validate(result)
