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
        expected = f"{env_config['prefix']}-spectrum-role"
        paginator = iam_client.get_paginator("list_roles")
        found = False
        for page in paginator.paginate():
            if any(r["RoleName"] == expected for r in page["Roles"]):
                found = True
                break
        assert found, f"IAM role {expected} not found"

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
            Sql="SELECT schemaname FROM svv_external_schemas WHERE schemaname = 'bronze_external';",
        )
        stmt_id = stmt["Id"]
        for _ in range(15):
            time.sleep(2)
            desc = redshift_data_client.describe_statement(Id=stmt_id)
            if desc["Status"] in ("FINISHED", "FAILED"):
                break
        assert desc["Status"] == "FINISHED", f"Query failed: {desc.get('Error')}"
        result = redshift_data_client.get_statement_result(Id=stmt_id)
        schemas = [row[0]["stringValue"] for row in result.get("Records", [])]
        assert "bronze_external" in schemas, "bronze_external schema not found in Redshift"

    @skip_if_not_found
    def test_six_glue_tables_registered(self, glue_client: Any, env_config: dict[str, Any]) -> None:
        response = glue_client.get_tables(DatabaseName=f"{env_config['prefix']}-bronze")
        table_names = {t["Name"] for t in response["TableList"]}
        expected = {
            "patient_demographics",
            "encounters",
            "appointments",
            "urgent_care_logs",
            "provider_site_reference",
            "diagnostics_orders",
        }
        missing = expected - table_names
        assert not missing, f"Missing Glue tables: {missing}"

    @skip_if_not_found
    def test_spectrum_tables_have_partitions(
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
            Sql=(
                "SELECT tablename, COUNT(*) AS partitions "
                "FROM svv_external_partitions "
                "WHERE schemaname = 'bronze_external' "
                "GROUP BY tablename ORDER BY tablename;"
            ),
        )
        stmt_id = stmt["Id"]
        for _ in range(15):
            time.sleep(2)
            desc = redshift_data_client.describe_statement(Id=stmt_id)
            if desc["Status"] in ("FINISHED", "FAILED"):
                break
        assert desc["Status"] == "FINISHED", f"Query failed: {desc.get('Error')}"
        result = redshift_data_client.get_statement_result(Id=stmt_id)
        tables_with_partitions = {
            row[0]["stringValue"]: int(row[1]["longValue"]) for row in result["Records"]
        }
        expected_tables = {
            "patient_demographics",
            "encounters",
            "appointments",
            "urgent_care_logs",
            "provider_site_reference",
            "diagnostics_orders",
        }
        missing = expected_tables - set(tables_with_partitions.keys())
        assert not missing, f"Tables without partitions: {missing}"
        for table, count in tables_with_partitions.items():
            assert count >= 1, f"{table} has 0 partitions"


class TestTunnelInstance:
    @skip_if_not_found
    def test_tunnel_instance_running(self, ec2_client: Any, env_config: dict[str, Any]) -> None:
        response = ec2_client.describe_instances(
            Filters=[
                {"Name": "tag:Name", "Values": [f"warehouse-{env_config['prefix']}/*"]},
                {"Name": "instance-state-name", "Values": ["running"]},
            ]
        )
        instances = [i for r in response["Reservations"] for i in r["Instances"]]
        assert instances, "Tunnel EC2 instance not found or not running"

    @skip_if_not_found
    def test_tunnel_instance_has_ssm_agent(
        self, ec2_client: Any, env_config: dict[str, Any]
    ) -> None:
        response = ec2_client.describe_instances(
            Filters=[
                {"Name": "tag:Name", "Values": [f"warehouse-{env_config['prefix']}/*"]},
                {"Name": "instance-state-name", "Values": ["running"]},
            ]
        )
        instances = [i for r in response["Reservations"] for i in r["Instances"]]
        if not instances:
            pytest.skip("Tunnel instance not found")
        instance = instances[0]
        iam_profile = instance.get("IamInstanceProfile", {}).get("Arn", "")
        assert iam_profile, "Tunnel instance has no IAM instance profile (needed for SSM)"
