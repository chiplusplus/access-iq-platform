"""Integration tests: VPC, peering, endpoints, security groups."""

from __future__ import annotations

from typing import Any

import pytest

from tests.integration.conftest import skip_if_not_found

pytestmark = pytest.mark.integration


def _get_platform_vpc_id(ec2_client: Any, prefix: str) -> str:
    response = ec2_client.describe_vpcs(
        Filters=[{"Name": "tag:Name", "Values": [f"{prefix}/*", f"{prefix}-*"]}]
    )
    vpcs = response["Vpcs"]
    if not vpcs:
        # Try broader filter - CDK names may vary
        response = ec2_client.describe_vpcs(
            Filters=[{"Name": "tag:aws:cloudformation:stack-name", "Values": [f"network-{prefix}"]}]
        )
        vpcs = response["Vpcs"]
    if not vpcs:
        pytest.skip("Platform VPC not found")
    vpc_id: str = vpcs[0]["VpcId"]
    return vpc_id


class TestPlatformVpc:
    @skip_if_not_found
    def test_platform_vpc_exists_with_correct_cidr(
        self, ec2_client: Any, env_config: dict[str, Any]
    ) -> None:
        vpc_id = _get_platform_vpc_id(ec2_client, env_config["prefix"])
        response = ec2_client.describe_vpcs(VpcIds=[vpc_id])
        cidr = response["Vpcs"][0]["CidrBlock"]
        assert cidr == "10.10.0.0/16"

    @skip_if_not_found
    def test_vpc_peering_active(self, ec2_client: Any, env_config: dict[str, Any]) -> None:
        vpc_id = _get_platform_vpc_id(ec2_client, env_config["prefix"])
        response = ec2_client.describe_vpc_peering_connections(
            Filters=[{"Name": "requester-vpc-info.vpc-id", "Values": [vpc_id]}]
        )
        connections = response["VpcPeeringConnections"]
        active = [c for c in connections if c["Status"]["Code"] == "active"]
        if not connections:
            pytest.skip("No peering connections found")
        assert active, f"Peering exists but not active: {connections[0]['Status']}"


class TestVpcEndpoints:
    @skip_if_not_found
    def test_s3_gateway_endpoint_exists(self, ec2_client: Any, env_config: dict[str, Any]) -> None:
        vpc_id = _get_platform_vpc_id(ec2_client, env_config["prefix"])
        response = ec2_client.describe_vpc_endpoints(
            Filters=[
                {"Name": "vpc-id", "Values": [vpc_id]},
                {"Name": "service-name", "Values": [f"com.amazonaws.{env_config['region']}.s3"]},
                {"Name": "vpc-endpoint-type", "Values": ["Gateway"]},
            ]
        )
        assert response["VpcEndpoints"], "S3 gateway endpoint not found"

    @skip_if_not_found
    def test_interface_endpoints_exist(self, ec2_client: Any, env_config: dict[str, Any]) -> None:
        vpc_id = _get_platform_vpc_id(ec2_client, env_config["prefix"])
        region = env_config["region"]
        expected_services = {
            f"com.amazonaws.{region}.secretsmanager",
            f"com.amazonaws.{region}.kms",
            f"com.amazonaws.{region}.ecr.api",
            f"com.amazonaws.{region}.ecr.dkr",
            f"com.amazonaws.{region}.logs",
            f"com.amazonaws.{region}.ssm",
            f"com.amazonaws.{region}.ssmmessages",
            f"com.amazonaws.{region}.ec2messages",
        }
        response = ec2_client.describe_vpc_endpoints(
            Filters=[
                {"Name": "vpc-id", "Values": [vpc_id]},
                {"Name": "vpc-endpoint-type", "Values": ["Interface"]},
            ]
        )
        found_services = {ep["ServiceName"] for ep in response["VpcEndpoints"]}
        missing = expected_services - found_services
        assert not missing, f"Missing interface endpoints: {missing}"


class TestSecurityGroups:
    @skip_if_not_found
    def test_ecs_task_sg_rules(self, ec2_client: Any, env_config: dict[str, Any]) -> None:
        response = ec2_client.describe_security_groups(
            Filters=[
                {"Name": "group-name", "Values": [f"{env_config['prefix']}-ecs-task"]},
            ]
        )
        sgs = response["SecurityGroups"]
        if not sgs:
            pytest.skip("ECS task security group not found")
        sg = sgs[0]
        egress_ports = {
            rule["FromPort"] for rule in sg["IpPermissionsEgress"] if "FromPort" in rule
        }
        assert 5432 in egress_ports, "Missing egress rule for RDS (5432)"
        assert 22 in egress_ports, "Missing egress rule for SFTP (22)"
        assert 443 in egress_ports, "Missing egress rule for HTTPS (443)"
