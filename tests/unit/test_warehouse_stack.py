"""CDK assertion tests for WarehouseStack."""

from __future__ import annotations

from typing import Any

import pytest

aws_cdk = pytest.importorskip("aws_cdk")
from aws_cdk import App, Environment, Stack  # noqa: E402
from aws_cdk import aws_ec2 as ec2  # noqa: E402
from aws_cdk import aws_kms as kms  # noqa: E402
from aws_cdk import aws_s3 as s3  # noqa: E402
from aws_cdk.assertions import Match, Template  # noqa: E402
from constructs import Construct  # noqa: E402

from access_iq_infra.settings import EnvConfig  # noqa: E402
from access_iq_infra.stacks.warehouse import WarehouseStack  # noqa: E402


def _cfg() -> EnvConfig:
    return EnvConfig(
        app_name="access-iq",
        env_name="dev",
        user_name="AWSReservedSSO_test/test",
        account_id="111111111111",
        region="eu-west-2",
        s3={},
        iam={"external_bucket": "x", "trust_account_id": "999999999999"},
        vpc={},
        tags={},
        ecs={},
        obs={},
        redshift={
            "base_capacity": 8,
            "usage_limit_rpu_hours": 4,
            "snapshot_retention_days": 7,
            "db_name": "dev",
        },
    )


class _DepsStack(Stack):
    """Helper stack providing mock dependencies for WarehouseStack."""

    def __init__(self, scope: Construct, construct_id: str, **kwargs: Any) -> None:
        super().__init__(scope, construct_id, **kwargs)
        self.vpc = ec2.Vpc(
            self,
            "Vpc",
            max_azs=2,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="private",
                    subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS,
                    cidr_mask=24,
                ),
                ec2.SubnetConfiguration(
                    name="public",
                    subnet_type=ec2.SubnetType.PUBLIC,
                    cidr_mask=24,
                ),
            ],
            nat_gateways=1,
        )
        self.ecs_task_sg = ec2.SecurityGroup(self, "EcsTaskSg", vpc=self.vpc)
        self.bucket = s3.Bucket(self, "Bucket")
        self.key = kms.Key(self, "Key")


def _template(context: dict[str, str] | None = None) -> Template:
    app = App(context=context or {})
    env = Environment(account="111111111111", region="eu-west-2")
    cfg = _cfg()

    deps = _DepsStack(app, "deps", env=env)
    stack = WarehouseStack(
        app,
        "warehouse-test",
        cfg=cfg,
        vpc=deps.vpc,
        ecs_task_sg=deps.ecs_task_sg,
        lake_bucket=deps.bucket,
        lake_key=deps.key,
        catalog_database_name="access-iq-dev-bronze",
        env=env,
    )
    return Template.from_stack(stack)


def test_cfn_namespace_created() -> None:
    tpl = _template()
    tpl.resource_count_is("AWS::RedshiftServerless::Namespace", 1)


def test_cfn_workgroup_created() -> None:
    tpl = _template()
    tpl.resource_count_is("AWS::RedshiftServerless::Workgroup", 1)


def test_workgroup_not_publicly_accessible() -> None:
    tpl = _template()
    tpl.has_resource_properties(
        "AWS::RedshiftServerless::Workgroup",
        {"PubliclyAccessible": False},
    )


def test_workgroup_enhanced_vpc_routing() -> None:
    tpl = _template()
    tpl.has_resource_properties(
        "AWS::RedshiftServerless::Workgroup",
        {"EnhancedVpcRouting": True},
    )


def test_namespace_has_log_exports() -> None:
    tpl = _template()
    tpl.has_resource_properties(
        "AWS::RedshiftServerless::Namespace",
        {"LogExports": ["userlog", "connectionlog", "useractivitylog"]},
    )


def test_namespace_has_kms_key() -> None:
    tpl = _template()
    tpl.has_resource_properties(
        "AWS::RedshiftServerless::Namespace",
        {"KmsKeyId": Match.any_value()},
    )


def test_spectrum_role_trusted_by_redshift() -> None:
    tpl = _template()
    tpl.has_resource_properties(
        "AWS::IAM::Role",
        {
            "AssumeRolePolicyDocument": {
                "Statement": Match.array_with(
                    [
                        Match.object_like(
                            {
                                "Principal": {"Service": "redshift.amazonaws.com"},
                                "Effect": "Allow",
                            }
                        )
                    ]
                )
            }
        },
    )


def test_redshift_sg_ingress_port_5439() -> None:
    # CDK emits SG-to-SG ingress as a separate AWS::EC2::SecurityGroupIngress resource
    tpl = _template()
    tpl.has_resource_properties(
        "AWS::EC2::SecurityGroupIngress",
        {"FromPort": 5439, "ToPort": 5439, "IpProtocol": "tcp"},
    )


def test_usage_limit_custom_resource_exists() -> None:
    tpl = _template()
    # CfnUsageLimit not in this CDK version — usage limit is an AwsCustomResource
    # which synthesises as Custom::AWS
    resources = tpl.find_resources("Custom::AWS")
    # Verify at least one custom resource exists (usage limit CR)
    assert len(resources) >= 1, "Expected at least one Custom::AWS resource (usage limit CR)"


def test_namespace_has_final_snapshot() -> None:
    tpl = _template()
    tpl.has_resource_properties(
        "AWS::RedshiftServerless::Namespace",
        {"FinalSnapshotName": Match.string_like_regexp(r"access-iq-dev-final-\d+")},
    )


def test_namespace_final_snapshot_has_retention() -> None:
    tpl = _template()
    tpl.has_resource_properties(
        "AWS::RedshiftServerless::Namespace",
        {"FinalSnapshotRetentionPeriod": 7},
    )


def test_restore_cr_configured_when_context_set() -> None:
    tpl = _template(context={"restore_snapshot_name": "access-iq-dev-final-1234567890"})
    # Restore CR creates an additional Custom::AWS resource alongside the usage limit CR
    resources = tpl.find_resources("Custom::AWS")
    assert len(resources) >= 2, (
        f"Expected at least 2 Custom::AWS resources (usage limit + restore CR), "
        f"found {len(resources)}"
    )


def test_no_restore_cr_when_context_absent() -> None:
    tpl = _template()
    # Without context, only the usage limit CR should exist — no restore CR
    resources = tpl.find_resources("Custom::AWS")
    assert len(resources) == 1, (
        f"Expected exactly 1 Custom::AWS resource (usage limit only), found {len(resources)}"
    )
