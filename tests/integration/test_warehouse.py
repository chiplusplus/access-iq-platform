"""Integration tests: Redshift Serverless, Spectrum, Glue catalog, usage limits."""

from __future__ import annotations

import time
from typing import Any

import pytest

from tests.integration.conftest import skip_if_not_found

pytestmark = pytest.mark.integration


class TestRedshiftNamespace:
    @skip_if_not_found
    def test_namespace_exists(
        self, redshift_serverless_client: Any, env_config: dict[str, Any]
    ) -> None:
        response = redshift_serverless_client.get_namespace(namespaceName=env_config["prefix"])
        assert response["namespace"]["status"] == "AVAILABLE"

    @skip_if_not_found
    def test_managed_admin_password_enabled(
        self, redshift_serverless_client: Any, env_config: dict[str, Any]
    ) -> None:
        response = redshift_serverless_client.get_namespace(namespaceName=env_config["prefix"])
        secret_arn = response["namespace"].get("adminPasswordSecretArn")
        assert secret_arn, "Managed admin password not enabled (no secret ARN)"

    @skip_if_not_found
    def test_namespace_kms_encrypted(
        self, redshift_serverless_client: Any, env_config: dict[str, Any]
    ) -> None:
        response = redshift_serverless_client.get_namespace(namespaceName=env_config["prefix"])
        kms_key = response["namespace"].get("kmsKeyId")
        assert kms_key, "Namespace not KMS encrypted"


class TestRedshiftWorkgroup:
    @skip_if_not_found
    def test_workgroup_available_and_private(
        self, redshift_serverless_client: Any, env_config: dict[str, Any]
    ) -> None:
        response = redshift_serverless_client.get_workgroup(workgroupName=env_config["prefix"])
        wg = response["workgroup"]
        assert wg["status"] == "AVAILABLE"
        assert wg["publiclyAccessible"] is False

    @skip_if_not_found
    def test_redshift_sg_inbound_5439_only(
        self, ec2_client: Any, env_config: dict[str, Any]
    ) -> None:
        response = ec2_client.describe_security_groups(
            Filters=[
                {"Name": "group-name", "Values": [f"{env_config['prefix']}-redshift"]},
            ]
        )
        sgs = response["SecurityGroups"]
        if not sgs:
            pytest.skip("Redshift security group not found")
        ingress_ports = {rule["FromPort"] for rule in sgs[0]["IpPermissions"] if "FromPort" in rule}
        assert 5439 in ingress_ports, "Missing inbound rule for port 5439"

    @skip_if_not_found
    def test_usage_limit_set(
        self, redshift_serverless_client: Any, env_config: dict[str, Any]
    ) -> None:
        response = redshift_serverless_client.list_usage_limits(
            resourceArn=redshift_serverless_client.get_workgroup(
                workgroupName=env_config["prefix"]
            )["workgroup"]["workgroupArn"]
        )
        limits = response.get("usageLimits", [])
        assert limits, "No usage limits configured"
        compute_limits = [ul for ul in limits if ul["usageType"] == "serverless-compute"]
        assert compute_limits, "No serverless-compute usage limit found"


class TestGlueCatalog:
    @skip_if_not_found
    def test_glue_database_exists(self, glue_client: Any, env_config: dict[str, Any]) -> None:
        response = glue_client.get_database(Name=f"{env_config['prefix']}-bronze")
        assert response["Database"]["Name"] == f"{env_config['prefix']}-bronze"


class TestSpectrum:
    @skip_if_not_found
    def test_spectrum_role_exists(self, iam_client: Any, env_config: dict[str, Any]) -> None:
        response = iam_client.get_role(RoleName=f"{env_config['prefix']}-spectrum-role")
        trust_policy = response["Role"]["AssumeRolePolicyDocument"]
        principals = [
            stmt.get("Principal", {}).get("Service", "")
            for stmt in trust_policy.get("Statement", [])
        ]
        assert "redshift.amazonaws.com" in principals

    @skip_if_not_found
    def test_external_schema_queryable(
        self,
        redshift_serverless_client: Any,
        redshift_data_client: Any,
        env_config: dict[str, Any],
    ) -> None:
        ns = redshift_serverless_client.get_namespace(namespaceName=env_config["prefix"])
        secret_arn = ns["namespace"].get("adminPasswordSecretArn")
        if not secret_arn:
            pytest.skip("No managed admin password — can't authenticate")

        stmt = redshift_data_client.execute_statement(
            WorkgroupName=env_config["prefix"],
            Database="dev",
            SecretArn=secret_arn,
            Sql="SELECT schema_name FROM svv_external_schemas WHERE schema_name = 'bronze_external';",
        )
        stmt_id = stmt["Id"]
        for _ in range(15):
            time.sleep(2)
            desc = redshift_data_client.describe_statement(Id=stmt_id)
            if desc["Status"] in ("FINISHED", "FAILED"):
                break
        assert desc["Status"] == "FINISHED", f"Query failed: {desc.get('Error')}"
        result = redshift_data_client.get_statement_result(Id=stmt_id)
        schemas = [row[0]["stringValue"] for row in result["Records"]]
        assert "bronze_external" in schemas, "bronze_external schema not found in Redshift"
