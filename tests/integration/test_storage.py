"""Integration tests: S3 lake bucket, KMS encryption, bronze data, manifests."""

from __future__ import annotations

import json
from typing import Any

import pytest

from tests.integration.conftest import skip_if_not_found

pytestmark = pytest.mark.integration


class TestLakeBucket:
    @skip_if_not_found
    def test_lake_bucket_exists(self, s3_client: Any, env_config: dict[str, Any]) -> None:
        bucket = f"{env_config['prefix']}-{env_config['account_id']}"
        response = s3_client.head_bucket(Bucket=bucket)
        assert response["ResponseMetadata"]["HTTPStatusCode"] == 200

    @skip_if_not_found
    def test_lake_bucket_kms_encrypted(self, s3_client: Any, env_config: dict[str, Any]) -> None:
        bucket = f"{env_config['prefix']}-{env_config['account_id']}"
        encryption = s3_client.get_bucket_encryption(Bucket=bucket)
        rules = encryption["ServerSideEncryptionConfiguration"]["Rules"]
        sse = rules[0]["ApplyServerSideEncryptionByDefault"]
        assert sse["SSEAlgorithm"] == "aws:kms"
        assert sse["KMSMasterKeyID"]  # not empty - CMK, not SSE-S3

    @skip_if_not_found
    def test_lake_bucket_versioning_enabled(
        self, s3_client: Any, env_config: dict[str, Any]
    ) -> None:
        bucket = f"{env_config['prefix']}-{env_config['account_id']}"
        versioning = s3_client.get_bucket_versioning(Bucket=bucket)
        assert versioning.get("Status") == "Enabled"


class TestBronzeData:
    @skip_if_not_found
    def test_bronze_parquet_files_exist(self, s3_client: Any, env_config: dict[str, Any]) -> None:
        bucket = f"{env_config['prefix']}-{env_config['account_id']}"
        response = s3_client.list_objects_v2(Bucket=bucket, Prefix="bronze/", MaxKeys=10)
        contents = response.get("Contents", [])
        if not contents:
            pytest.skip("No bronze data ingested yet")
        parquet_keys = [obj["Key"] for obj in contents if obj["Key"].endswith(".parquet")]
        assert parquet_keys, "Bronze files exist but none are .parquet"

    @skip_if_not_found
    def test_bronze_parquet_magic_bytes(self, s3_client: Any, env_config: dict[str, Any]) -> None:
        bucket = f"{env_config['prefix']}-{env_config['account_id']}"
        response = s3_client.list_objects_v2(Bucket=bucket, Prefix="bronze/", MaxKeys=50)
        contents = response.get("Contents", [])
        parquet_keys = [obj["Key"] for obj in contents if obj["Key"].endswith(".parquet")]
        if not parquet_keys:
            pytest.skip("No parquet files to verify")
        obj = s3_client.get_object(Bucket=bucket, Key=parquet_keys[0], Range="bytes=0-3")
        magic = obj["Body"].read(4)
        assert magic == b"PAR1", f"Expected PAR1 magic bytes, got {magic!r}"

    @skip_if_not_found
    def test_manifests_exist_with_success_status(
        self, s3_client: Any, env_config: dict[str, Any]
    ) -> None:
        bucket = f"{env_config['prefix']}-{env_config['account_id']}"
        response = s3_client.list_objects_v2(Bucket=bucket, Prefix="_manifests/", MaxKeys=50)
        contents = response.get("Contents", [])
        if not contents:
            pytest.skip("No manifests found")
        json_keys = [obj["Key"] for obj in contents if obj["Key"].endswith(".json")]
        assert json_keys, "Manifest files exist but none are .json"

        obj = s3_client.get_object(Bucket=bucket, Key=json_keys[-1])
        manifest = json.loads(obj["Body"].read())
        assert manifest["status"] == "success", f"Latest manifest status: {manifest['status']}"
