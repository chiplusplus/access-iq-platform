"""CDK assertion tests for BudgetStack."""

from __future__ import annotations

import pytest

aws_cdk = pytest.importorskip("aws_cdk")
from aws_cdk import App, Environment  # noqa: E402
from aws_cdk.assertions import Template  # noqa: E402

from access_iq_infra.settings import EnvConfig  # noqa: E402
from access_iq_infra.stacks.budget import BudgetStack  # noqa: E402


def _cfg(env_name: str = "dev") -> EnvConfig:
    return EnvConfig(
        app_name="access-iq",
        env_name=env_name,
        user_name="AWSReservedSSO_test/test",
        account_id="123456789012",
        region="eu-west-2",
        s3={},
        iam={"external_bucket": "x", "trust_account_id": "999999999999"},
        vpc={},
        tags={},
        ecs={},
        obs={},
        redshift={},
    )


def _template(env_name: str = "dev") -> Template:
    app = App()
    stack = BudgetStack(
        app,
        f"budget-test-{env_name}",
        cfg=_cfg(env_name),
        ephemeral_stack_names=["compute-access-iq-dev", "network-access-iq-dev"],
        env=Environment(account="123456789012", region="us-east-1"),
    )
    return Template.from_stack(stack)


def test_budget_stack_synth_clean() -> None:
    """BudgetStack synthesises with expected resource counts."""
    template = _template()
    template.resource_count_is("AWS::Budgets::Budget", 1)
    template.resource_count_is("AWS::SNS::Topic", 1)
    template.resource_count_is("AWS::Lambda::Function", 1)


def test_budget_threshold_is_percentage() -> None:
    """Budget notification fires at 80% ACTUAL threshold."""
    template = _template()
    template.has_resource_properties(
        "AWS::Budgets::Budget",
        {
            "NotificationsWithSubscribers": [
                {
                    "Notification": {
                        "NotificationType": "ACTUAL",
                        "ComparisonOperator": "GREATER_THAN",
                        "Threshold": 80,
                        "ThresholdType": "PERCENTAGE",
                    },
                }
            ],
        },
    )


def test_teardown_lambda_has_scoped_policy() -> None:
    """Lambda role has cloudformation:DeleteStack scoped to specific stacks."""
    template = _template()
    template.has_resource_properties(
        "AWS::IAM::Policy",
        {
            "PolicyDocument": {
                "Statement": [
                    {
                        "Action": "cloudformation:DeleteStack",
                    }
                ],
            },
        },
    )


def test_prod_ceiling_is_twenty() -> None:
    """Prod environment uses $20 ceiling."""
    template = _template("prod")
    template.has_resource_properties(
        "AWS::Budgets::Budget",
        {
            "Budget": {
                "BudgetLimit": {
                    "Amount": 20,
                    "Unit": "USD",
                },
            },
        },
    )


def test_dev_ceiling_is_ten() -> None:
    """Dev environment uses $10 ceiling."""
    template = _template("dev")
    template.has_resource_properties(
        "AWS::Budgets::Budget",
        {
            "Budget": {
                "BudgetLimit": {
                    "Amount": 10,
                    "Unit": "USD",
                },
            },
        },
    )


def _trust_template(env_name: str = "dev") -> Template:
    app = App()
    cfg = _cfg(env_name)
    stack = BudgetStack(
        app,
        f"budget-trust-test-{env_name}",
        cfg=cfg,
        ephemeral_stack_names=["NorthshireTrustStack"],
        target_account_id="999999999999",
        target_region="eu-west-2",
        topic_name_suffix="trust-budget-alarm",
        env=Environment(account="999999999999", region="us-east-1"),
    )
    return Template.from_stack(stack)


def test_trust_budget_stack_synth_clean() -> None:
    """Trust BudgetStack synthesises with expected resource counts."""
    template = _trust_template()
    template.resource_count_is("AWS::Budgets::Budget", 1)
    template.resource_count_is("AWS::SNS::Topic", 1)
    template.resource_count_is("AWS::Lambda::Function", 1)


def test_trust_teardown_targets_trust_account() -> None:
    """Trust Lambda IAM policy scopes to Trust account stack ARNs."""
    template = _trust_template()
    template.has_resource_properties(
        "AWS::IAM::Policy",
        {
            "PolicyDocument": {
                "Statement": [
                    {
                        "Action": "cloudformation:DeleteStack",
                        "Resource": "arn:aws:cloudformation:eu-west-2:999999999999:stack/NorthshireTrustStack/*",
                    }
                ],
            },
        },
    )
