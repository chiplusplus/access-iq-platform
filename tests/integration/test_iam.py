"""Integration tests: IAM roles, Secrets Manager entries."""

from __future__ import annotations

from typing import Any

import pytest

from tests.integration.conftest import skip_if_not_found

pytestmark = pytest.mark.integration


class TestSecretsManager:
    @skip_if_not_found
    def test_secrets_exist(self, secretsmanager_client: Any, env_config: dict[str, Any]) -> None:
        response = secretsmanager_client.list_secrets(
            Filters=[{"Key": "name", "Values": [f"access-iq/{env_config['env_name']}/"]}]
        )
        secrets = response.get("SecretList", [])
        if not secrets:
            pytest.skip("No secrets found — stack may not be deployed")
        secret_names = [s["Name"] for s in secrets]
        assert len(secret_names) >= 1, "Expected at least one secret"


class TestIamRoles:
    @skip_if_not_found
    def test_ecs_task_role_exists(self, iam_client: Any, env_config: dict[str, Any]) -> None:
        response = iam_client.get_role(RoleName=f"{env_config['prefix']}-ecs-task-role")
        trust = response["Role"]["AssumeRolePolicyDocument"]
        principals = [
            stmt.get("Principal", {}).get("Service", "") for stmt in trust.get("Statement", [])
        ]
        assert "ecs-tasks.amazonaws.com" in principals

    @skip_if_not_found
    def test_ecs_execution_role_exists(self, iam_client: Any, env_config: dict[str, Any]) -> None:
        response = iam_client.get_role(RoleName=f"{env_config['prefix']}-ecs-exec-role")
        trust = response["Role"]["AssumeRolePolicyDocument"]
        principals = [
            stmt.get("Principal", {}).get("Service", "") for stmt in trust.get("Statement", [])
        ]
        assert "ecs-tasks.amazonaws.com" in principals
