"""CDK assertion tests for IngestionRoleStack -- SSO + ECS task + execution roles."""

from __future__ import annotations

import pytest

aws_cdk = pytest.importorskip("aws_cdk")
from aws_cdk import App, Environment, Stack  # noqa: E402
from aws_cdk import aws_kms as kms  # noqa: E402
from aws_cdk import aws_s3 as s3  # noqa: E402
from aws_cdk import aws_secretsmanager as secretsmanager  # noqa: E402
from aws_cdk.assertions import Match, Template  # noqa: E402

from access_iq_infra.settings import EnvConfig  # noqa: E402
from access_iq_infra.stacks.iam import IngestionRoleStack  # noqa: E402


def _cfg() -> EnvConfig:
    return EnvConfig(
        app_name="access-iq",
        env_name="dev",
        user_name="AWSReservedSSO_test/test",
        account_id="111111111111",
        region="eu-west-2",
        s3={},
        iam={"external_bucket": "trust-exports-bucket", "trust_account_id": "999999999999"},
        vpc={},
        tags={},
        ecs={},
        obs={},
    )


def _template() -> Template:
    app = App()
    env = Environment(account="111111111111", region="eu-west-2")
    cfg = _cfg()

    # Mock dependency stack
    deps = Stack(app, "deps", env=env)
    bucket = s3.Bucket(deps, "MockBucket")
    key = kms.Key(deps, "MockKey")
    secret = secretsmanager.Secret(deps, "MockSecret", encryption_key=key)

    stack = IngestionRoleStack(
        app,
        "iam-test",
        cfg=cfg,
        platform_bucket=bucket,
        lake_key=key,
        pseudonymisation_key_secret=secret,
        env=env,
    )
    return Template.from_stack(stack)


def test_four_iam_roles_exist() -> None:
    """IngestionRoleStack should create exactly 4 IAM roles."""
    tpl = _template()
    tpl.resource_count_is("AWS::IAM::Role", 4)


def test_ecs_task_role_trust_policy() -> None:
    """ECS task role is trusted by ecs-tasks.amazonaws.com."""
    tpl = _template()
    tpl.has_resource_properties(
        "AWS::IAM::Role",
        Match.object_like(
            {
                "RoleName": Match.string_like_regexp(".*ecs-task-role$"),
                "AssumeRolePolicyDocument": Match.object_like(
                    {
                        "Statement": Match.array_with(
                            [
                                Match.object_like(
                                    {
                                        "Principal": Match.object_like(
                                            {"Service": "ecs-tasks.amazonaws.com"}
                                        ),
                                    }
                                )
                            ]
                        )
                    }
                ),
            }
        ),
    )


def test_ecs_execution_role_trust_policy() -> None:
    """ECS execution role is trusted by ecs-tasks.amazonaws.com."""
    tpl = _template()
    tpl.has_resource_properties(
        "AWS::IAM::Role",
        Match.object_like(
            {
                "RoleName": Match.string_like_regexp(".*ecs-execution-role$"),
                "AssumeRolePolicyDocument": Match.object_like(
                    {
                        "Statement": Match.array_with(
                            [
                                Match.object_like(
                                    {
                                        "Principal": Match.object_like(
                                            {"Service": "ecs-tasks.amazonaws.com"}
                                        ),
                                    }
                                )
                            ]
                        )
                    }
                ),
            }
        ),
    )


def test_execution_role_has_managed_policy() -> None:
    """Execution role has the AmazonECSTaskExecutionRolePolicy managed policy."""
    tpl = _template()
    tpl.has_resource_properties(
        "AWS::IAM::Role",
        Match.object_like(
            {
                "RoleName": Match.string_like_regexp(".*ecs-execution-role$"),
                "ManagedPolicyArns": Match.array_with(
                    [
                        Match.object_like(
                            {
                                "Fn::Join": Match.array_with(
                                    [
                                        Match.string_like_regexp(""),
                                        Match.array_with(
                                            [
                                                Match.string_like_regexp(
                                                    ".*AmazonECSTaskExecutionRolePolicy"
                                                )
                                            ]
                                        ),
                                    ]
                                )
                            }
                        )
                    ]
                ),
            }
        ),
    )


def test_ecs_task_role_has_s3_permissions() -> None:
    """ECS task role has an inline policy with S3 GetObject and PutObject actions."""
    tpl = _template()
    tpl.has_resource_properties(
        "AWS::IAM::Policy",
        Match.object_like(
            {
                "PolicyName": Match.string_like_regexp(".*ecs-task-policy$"),
                "PolicyDocument": Match.object_like(
                    {
                        "Statement": Match.array_with(
                            [
                                Match.object_like(
                                    {
                                        "Action": Match.array_with(["s3:GetObject"]),
                                    }
                                ),
                                Match.object_like(
                                    {
                                        "Action": Match.array_with(["s3:PutObject"]),
                                    }
                                ),
                            ]
                        )
                    }
                ),
            }
        ),
    )


def test_ecs_operator_role_trust_policy() -> None:
    """ECS operator role is trusted by the SSO user (same as ingestion role)."""
    tpl = _template()
    tpl.has_resource_properties(
        "AWS::IAM::Role",
        Match.object_like(
            {
                "RoleName": Match.string_like_regexp(".*ecs-operator-role$"),
                "AssumeRolePolicyDocument": Match.object_like(
                    {
                        "Statement": Match.array_with(
                            [
                                Match.object_like(
                                    {
                                        "Principal": Match.object_like(
                                            {"AWS": Match.string_like_regexp(".*assumed-role.*")}
                                        ),
                                    }
                                )
                            ]
                        )
                    }
                ),
            }
        ),
    )


def test_operator_role_has_run_task_permission() -> None:
    """Operator role grants ecs:RunTask scoped to project task definitions."""
    tpl = _template()
    tpl.has_resource_properties(
        "AWS::IAM::Policy",
        Match.object_like(
            {
                "PolicyDocument": Match.object_like(
                    {
                        "Statement": Match.array_with(
                            [
                                Match.object_like(
                                    {
                                        "Action": "ecs:RunTask",
                                        "Effect": "Allow",
                                    }
                                )
                            ]
                        )
                    }
                ),
            }
        ),
    )


def test_operator_role_has_pass_role_permission() -> None:
    """Operator role grants iam:PassRole scoped to ECS task/execution roles."""
    tpl = _template()
    tpl.has_resource_properties(
        "AWS::IAM::Policy",
        Match.object_like(
            {
                "PolicyDocument": Match.object_like(
                    {
                        "Statement": Match.array_with(
                            [
                                Match.object_like(
                                    {
                                        "Action": "iam:PassRole",
                                        "Condition": {
                                            "StringEquals": {
                                                "iam:PassedToService": "ecs-tasks.amazonaws.com"
                                            }
                                        },
                                    }
                                )
                            ]
                        )
                    }
                ),
            }
        ),
    )


def test_sso_role_unchanged() -> None:
    """SSO ingestion role still uses ArnPrincipal trust, not ServicePrincipal."""
    tpl = _template()
    tpl.has_resource_properties(
        "AWS::IAM::Role",
        Match.object_like(
            {
                "RoleName": Match.string_like_regexp(".*ingestion-role$"),
                "AssumeRolePolicyDocument": Match.object_like(
                    {
                        "Statement": Match.array_with(
                            [
                                Match.object_like(
                                    {
                                        "Principal": Match.object_like(
                                            {"AWS": Match.string_like_regexp(".*assumed-role.*")}
                                        ),
                                    }
                                )
                            ]
                        )
                    }
                ),
            }
        ),
    )
