from __future__ import annotations

import pytest

aws_cdk = pytest.importorskip("aws_cdk")
from aws_cdk import App  # noqa: E402
from aws_cdk.assertions import Match, Template  # noqa: E402

from access_iq_infra.settings import EnvConfig  # noqa: E402
from access_iq_infra.stacks.network import NetworkStack  # noqa: E402


def _cfg() -> EnvConfig:
    return EnvConfig(
        app_name="access-iq",
        env_name="dev",
        user_name="AWSReservedSSO_test/test",
        account_id="111111111111",
        region="eu-west-2",
        s3={},
        iam={"external_bucket": "x", "trust_account_id": "999999999999"},
        vpc={
            "platform_cidr": "10.10.0.0/16",
            "trust_cidr": "10.0.0.0/16",
            "max_azs": 2,
            "nat_gateways": 1,
        },
        tags={},
        ecs={},
        obs={},
        redshift={},
    )


def _template() -> Template:
    app = App(
        context={
            "trust_vpc_id": "vpc-test123",
        }
    )
    stack = NetworkStack(app, "NetworkStack", cfg=_cfg())
    return Template.from_stack(stack)


def test_vpc_cidr() -> None:
    tpl = _template()
    tpl.has_resource_properties("AWS::EC2::VPC", {"CidrBlock": "10.10.0.0/16"})


def test_two_private_two_public_subnets() -> None:
    tpl = _template()
    tpl.resource_count_is("AWS::EC2::Subnet", 4)


def test_single_nat_gateway() -> None:
    tpl = _template()
    tpl.resource_count_is("AWS::EC2::NatGateway", 1)


def test_vpc_peering_resource() -> None:
    tpl = _template()
    tpl.has_resource_properties(
        "AWS::EC2::VPCPeeringConnection",
        {
            "PeerOwnerId": "999999999999",
            "PeerRoleArn": Match.string_like_regexp("access-iq-peering-accepter"),
        },
    )


def test_platform_peering_routes() -> None:
    tpl = _template()
    routes = tpl.find_resources(
        "AWS::EC2::Route",
        {"Properties": {"DestinationCidrBlock": "10.0.0.0/16"}},
    )
    assert len(routes) >= 1, "Expected at least one platform peering route to Trust CIDR"


def test_dns_requester_custom_resource() -> None:
    tpl = _template()
    custom_resources = tpl.find_resources("Custom::AWS")
    assert len(custom_resources) == 1, (
        "Expected exactly 1 AwsCustomResource (DNS requester only — "
        "Trust routes and DNS accepter are managed by Trust stack)"
    )


def test_peering_connection_id_output() -> None:
    tpl = _template()
    outputs = tpl.to_json().get("Outputs", {})
    assert "PeeringConnectionId" in outputs, "Expected PeeringConnectionId CfnOutput"


def test_ecs_sg_deny_all_outbound() -> None:
    tpl = _template()
    sgs = tpl.find_resources("AWS::EC2::SecurityGroup")
    # Find the ECS task SG (description contains "deny-by-default" or "ECS ingestion")
    # Verify no SG with specific egress rules has a 0.0.0.0/0 ALL-protocol egress
    ecs_sg_found = False
    for _logical_id, resource in sgs.items():
        props = resource.get("Properties", {})
        desc = props.get("GroupDescription", "")
        if "ECS" not in desc and "ecs" not in desc and "deny" not in desc.lower():
            continue
        ecs_sg_found = True
        egress_rules = props.get("SecurityGroupEgress", [])
        for rule in egress_rules:
            assert not (rule.get("CidrIp") == "0.0.0.0/0" and rule.get("IpProtocol") == "-1"), (
                f"ECS task SG must not have allow-all-outbound (0.0.0.0/0 /-1) egress rule, found: {rule}"
            )
    assert ecs_sg_found, "Expected to find an ECS task security group"


def test_ecs_sg_trust_rds_egress() -> None:
    tpl = _template()
    sgs = tpl.find_resources("AWS::EC2::SecurityGroup")
    found_rds_rule = False
    for _logical_id, resource in sgs.items():
        props = resource.get("Properties", {})
        desc = props.get("GroupDescription", "")
        if "ECS" not in desc and "ecs" not in desc and "deny" not in desc.lower():
            continue
        egress_rules = props.get("SecurityGroupEgress", [])
        for rule in egress_rules:
            if (
                rule.get("CidrIp") == "10.0.0.0/16"
                and rule.get("FromPort") == 5432
                and rule.get("ToPort") == 5432
            ):
                found_rds_rule = True
    assert found_rds_rule, "Expected ECS SG egress rule for port 5432 to Trust CIDR 10.0.0.0/16"


def test_ecs_sg_trust_sftp_egress() -> None:
    tpl = _template()
    sgs = tpl.find_resources("AWS::EC2::SecurityGroup")
    found_sftp_rule = False
    for _logical_id, resource in sgs.items():
        props = resource.get("Properties", {})
        desc = props.get("GroupDescription", "")
        if "ECS" not in desc and "ecs" not in desc and "deny" not in desc.lower():
            continue
        egress_rules = props.get("SecurityGroupEgress", [])
        for rule in egress_rules:
            if (
                rule.get("CidrIp") == "10.0.0.0/16"
                and rule.get("FromPort") == 22
                and rule.get("ToPort") == 22
            ):
                found_sftp_rule = True
    assert found_sftp_rule, "Expected ECS SG egress rule for port 22 to Trust CIDR 10.0.0.0/16"


def test_s3_gateway_endpoint() -> None:
    tpl = _template()
    endpoints = tpl.find_resources(
        "AWS::EC2::VPCEndpoint",
        {"Properties": {"VpcEndpointType": "Gateway"}},
    )
    assert len(endpoints) >= 1, "Expected at least one Gateway VPC endpoint (S3)"


def test_interface_endpoints_count() -> None:
    tpl = _template()
    tpl.resource_count_is("AWS::EC2::VPCEndpoint", 9)  # 1 gateway + 8 interface (5 core + 3 SSM)


def test_endpoint_sg_ingress_443() -> None:
    tpl = _template()
    sgs = tpl.find_resources("AWS::EC2::SecurityGroup")
    found_ingress_443 = False
    for _logical_id, resource in sgs.items():
        props = resource.get("Properties", {})
        ingress_rules = props.get("SecurityGroupIngress", [])
        for rule in ingress_rules:
            if (
                rule.get("CidrIp") == "10.10.0.0/16"
                and rule.get("FromPort") == 443
                and rule.get("ToPort") == 443
            ):
                found_ingress_443 = True
    assert found_ingress_443, (
        "Expected endpoint security group ingress rule on port 443 from 10.10.0.0/16"
    )


def test_prefect_port_4200_ingress_rule() -> None:
    """ECS SG has ingress on port 4200 from Platform CIDR for Prefect server API."""
    tpl = _template()
    sgs = tpl.find_resources("AWS::EC2::SecurityGroup")
    found = False
    for _logical_id, resource in sgs.items():
        props = resource.get("Properties", {})
        ingress_rules = props.get("SecurityGroupIngress", [])
        for rule in ingress_rules:
            if (
                rule.get("CidrIp") == "10.10.0.0/16"
                and rule.get("FromPort") == 4200
                and rule.get("ToPort") == 4200
            ):
                found = True
    assert found, "Expected ECS SG ingress rule for port 4200 from platform CIDR 10.10.0.0/16"


def test_prefect_port_4200_egress_rule() -> None:
    """ECS SG has egress on port 4200 to Platform CIDR for Prefect worker -> server."""
    tpl = _template()
    sgs = tpl.find_resources("AWS::EC2::SecurityGroup")
    found = False
    for _logical_id, resource in sgs.items():
        props = resource.get("Properties", {})
        egress_rules = props.get("SecurityGroupEgress", [])
        for rule in egress_rules:
            if (
                rule.get("CidrIp") == "10.10.0.0/16"
                and rule.get("FromPort") == 4200
                and rule.get("ToPort") == 4200
            ):
                found = True
    assert found, "Expected ECS SG egress rule for port 4200 to platform CIDR 10.10.0.0/16"


def test_synth_succeeds_without_trust_vpc_id() -> None:
    app = App(context={})
    stack = NetworkStack(app, "Test", cfg=_cfg())
    tpl = Template.from_stack(stack)
    tpl.resource_count_is("AWS::EC2::VPC", 1)
