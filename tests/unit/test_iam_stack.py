"""CDK assertion tests for IngestionRoleStack -- SSO + ECS task + execution + dashboard roles."""

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
        redshift={},
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


def test_five_iam_roles_exist() -> None:
    """IngestionRoleStack should create exactly 5 IAM roles."""
    tpl = _template()
    tpl.resource_count_is("AWS::IAM::Role", 5)


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


def test_ecs_task_role_has_sns_publish() -> None:
    """ECS task role has sns:Publish for pipeline on_failure alerting (Phase 7)."""
    tpl = _template()
    policies = tpl.find_resources("AWS::IAM::Policy")
    found = False
    for _lid, policy in policies.items():
        statements = policy.get("Properties", {}).get("PolicyDocument", {}).get("Statement", [])
        for stmt in statements:
            actions = stmt.get("Action", [])
            if isinstance(actions, str):
                actions = [actions]
            if "sns:Publish" in actions:
                resource_str = str(stmt.get("Resource", ""))
                assert "ingestion-alerts" in resource_str, (
                    "sns:Publish should be scoped to ingestion-alerts topic"
                )
                found = True
                break
    assert found, "ECS task role missing sns:Publish permission"


class TestDashboardReaderUser:
    """Tests for dashboard reader IAM user (D-17, Phase 8)."""

    def test_dashboard_reader_user_exists(self) -> None:
        """Dashboard reader IAM user exists with correct name."""
        tpl = _template()
        tpl.has_resource_properties(
            "AWS::IAM::User",
            Match.object_like({"UserName": Match.string_like_regexp(".*dashboard-reader$")}),
        )

    def test_dashboard_reader_get_object_policy(self) -> None:
        """Dashboard reader has s3:GetObject scoped to gold_export/* prefix."""
        tpl = _template()
        policies = tpl.find_resources("AWS::IAM::Policy")
        found = False
        for _lid, policy in policies.items():
            stmts = policy.get("Properties", {}).get("PolicyDocument", {}).get("Statement", [])
            for stmt in stmts:
                action = stmt.get("Action", "")
                if action == "s3:GetObject":
                    resources = stmt.get("Resource", [])
                    resource_str = str(resources)
                    if "gold_export/*" in resource_str:
                        found = True
                        break
        assert found, "Dashboard reader policy missing s3:GetObject on gold_export/*"

    def test_dashboard_reader_list_bucket_policy(self) -> None:
        """Dashboard reader has s3:ListBucket with gold_export/* prefix condition."""
        tpl = _template()
        policies = tpl.find_resources("AWS::IAM::Policy")
        found = False
        for _lid, policy in policies.items():
            stmts = policy.get("Properties", {}).get("PolicyDocument", {}).get("Statement", [])
            for stmt in stmts:
                action = stmt.get("Action", "")
                cond = stmt.get("Condition", {})
                if action == "s3:ListBucket" and "StringLike" in cond:
                    prefix_cond = cond["StringLike"].get("s3:prefix", [])
                    if prefix_cond == ["gold_export/*"]:
                        found = True
                        break
        assert found, "Dashboard reader policy missing s3:ListBucket with gold_export/* condition"

    def test_dashboard_reader_kms_decrypt(self) -> None:
        """Dashboard reader has kms:Decrypt on the lake key for encrypted Gold Parquet."""
        tpl = _template()
        policies = tpl.find_resources("AWS::IAM::Policy")
        found = False
        for _lid, policy in policies.items():
            stmts = policy.get("Properties", {}).get("PolicyDocument", {}).get("Statement", [])
            for stmt in stmts:
                actions = stmt.get("Action", [])
                if isinstance(actions, str):
                    actions = [actions]
                if "kms:Decrypt" in actions:
                    found = True
                    break
        assert found, "Dashboard reader missing kms:Decrypt grant on lake key"

    def test_dashboard_reader_access_key_exists(self) -> None:
        """Dashboard reader IAM access key resource exists."""
        tpl = _template()
        tpl.resource_count_is("AWS::IAM::AccessKey", 1)


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
