from __future__ import annotations

import pytest

aws_cdk = pytest.importorskip("aws_cdk")
from access_iq_infra.stacks.network import NetworkStack  # noqa: E402
from aws_cdk import App  # noqa: E402
from aws_cdk.assertions import Match, Template  # noqa: E402

from access_iq_infra.settings import EnvConfig  # noqa: E402


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
    )


def _template() -> Template:
    app = App(
        context={
            "trust_vpc_id": "vpc-test123",
            "trust_route_table_ids": "rtb-test1,rtb-test2",
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


def test_trust_route_custom_resource() -> None:
    tpl = _template()
    # AwsCustomResource creates AWS::CloudFormation::CustomResource resources
    custom_resources = tpl.find_resources("AWS::CloudFormation::CustomResource")
    assert len(custom_resources) >= 1, "Expected at least one AwsCustomResource for Trust routes"


def test_dns_resolution_custom_resources() -> None:
    tpl = _template()
    # Both requester and accepter DNS custom resources expected
    custom_resources = tpl.find_resources("AWS::CloudFormation::CustomResource")
    assert len(custom_resources) >= 2, (
        "Expected at least 2 AwsCustomResource entries (Trust routes + DNS resolution)"
    )


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
    tpl.has_resource_properties(
        "AWS::EC2::VPCEndpoint",
        {
            "VpcEndpointType": "Gateway",
            "ServiceName": Match.string_like_regexp("s3"),
        },
    )


def test_interface_endpoints_count() -> None:
    tpl = _template()
    tpl.resource_count_is("AWS::EC2::VPCEndpoint", 6)  # 1 gateway + 5 interface


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


def test_context_validation_missing_vpc_id() -> None:
    with pytest.raises(ValueError, match="trust_vpc_id"):
        app = App(
            context={
                "trust_route_table_ids": "rtb-test1,rtb-test2",
                # trust_vpc_id intentionally omitted
            }
        )
        NetworkStack(app, "Test", cfg=_cfg())


def test_context_validation_missing_rtb_ids() -> None:
    with pytest.raises(ValueError, match="trust_route_table_ids"):
        app = App(
            context={
                "trust_vpc_id": "vpc-test123",
                # trust_route_table_ids intentionally omitted
            }
        )
        NetworkStack(app, "Test", cfg=_cfg())
