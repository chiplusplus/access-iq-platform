"""Integration tests: ECS cluster, task definitions, ECR repository."""

from __future__ import annotations

from typing import Any

import pytest

from tests.integration.conftest import skip_if_not_found

pytestmark = pytest.mark.integration


class TestEcsCluster:
    @skip_if_not_found
    def test_ecs_cluster_exists(self, ecs_client: Any, env_config: dict[str, Any]) -> None:
        response = ecs_client.describe_clusters(clusters=[f"{env_config['prefix']}-cluster"])
        clusters = [c for c in response["clusters"] if c["status"] == "ACTIVE"]
        assert clusters, "ECS cluster not found or not ACTIVE"

    @skip_if_not_found
    def test_three_task_definitions_registered(
        self, ecs_client: Any, env_config: dict[str, Any]
    ) -> None:
        prefix = env_config["prefix"]
        expected_families = {
            f"{prefix}-ingest-postgres",
            f"{prefix}-ingest-sftp",
            f"{prefix}-ingest-trust-s3",
        }
        found = set()
        for family in expected_families:
            response = ecs_client.list_task_definitions(familyPrefix=family, status="ACTIVE")
            if response["taskDefinitionArns"]:
                found.add(family)
        missing = expected_families - found
        assert not missing, f"Missing task definitions: {missing}"


class TestEcrRepository:
    @skip_if_not_found
    def test_ecr_repo_exists_with_scan_on_push(
        self, ecr_client: Any, env_config: dict[str, Any]
    ) -> None:
        response = ecr_client.describe_repositories(
            repositoryNames=[f"{env_config['prefix']}-ingestion"]
        )
        repo = response["repositories"][0]
        assert repo["imageScanningConfiguration"]["scanOnPush"] is True

    @skip_if_not_found
    def test_ecr_image_pushed(self, ecr_client: Any, env_config: dict[str, Any]) -> None:
        response = ecr_client.list_images(
            repositoryName=f"{env_config['prefix']}-ingestion",
            filter={"tagStatus": "TAGGED"},
        )
        image_ids = response.get("imageIds", [])
        tags = [img.get("imageTag") for img in image_ids]
        if not tags:
            pytest.skip("No tagged images pushed yet")
        assert "latest" in tags, f"'latest' tag not found, tags: {tags}"
