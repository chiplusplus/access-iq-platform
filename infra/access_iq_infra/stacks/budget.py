"""BudgetStack -- monthly cost ceiling via AWS Budgets alarm + SNS -> Lambda teardown."""

from __future__ import annotations

from typing import Any

from aws_cdk import Duration, Stack
from aws_cdk import aws_budgets as budgets
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as _lambda
from aws_cdk import aws_sns as sns
from aws_cdk import aws_sns_subscriptions as subs
from constructs import Construct

from access_iq_infra.settings import EnvConfig

_TEARDOWN_HANDLER = """\
import boto3
import os
import json


def handler(event, context):
    stacks = os.environ["EPHEMERAL_STACKS"].split(",")
    region = os.environ["STACK_REGION"]
    cf = boto3.client("cloudformation", region_name=region)
    for stack in stacks:
        try:
            cf.delete_stack(StackName=stack)
            print(f"Initiated destroy: {stack}")
        except Exception as e:
            print(f"Skip {stack}: {e}")
"""


class BudgetStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        cfg: EnvConfig,
        ephemeral_stack_names: list[str],
        **kwargs: Any,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        is_prod = cfg.env_name == "prod"
        ceiling_amount = 20 if is_prod else 10

        # -- SNS topic for budget alarm notifications --
        topic = sns.Topic(
            self,
            "BudgetAlarmTopic",
            topic_name=f"{cfg.app_name}-{cfg.env_name}-budget-alarm",
        )

        # Restrict publishers to AWS Budgets service only (T-09-02)
        topic.add_to_resource_policy(
            iam.PolicyStatement(
                principals=[iam.ServicePrincipal("budgets.amazonaws.com")],
                actions=["sns:Publish"],
                resources=[topic.topic_arn],
            )
        )

        # -- AWS Budget: monthly cost ceiling --
        budgets.CfnBudget(
            self,
            "MonthlyCeiling",
            budget=budgets.CfnBudget.BudgetDataProperty(
                budget_type="COST",
                time_unit="MONTHLY",
                budget_limit=budgets.CfnBudget.SpendProperty(
                    amount=ceiling_amount,
                    unit="USD",
                ),
            ),
            notifications_with_subscribers=[
                budgets.CfnBudget.NotificationWithSubscribersProperty(
                    notification=budgets.CfnBudget.NotificationProperty(
                        notification_type="ACTUAL",
                        comparison_operator="GREATER_THAN",
                        threshold=80,
                        threshold_type="PERCENTAGE",
                    ),
                    subscribers=[
                        budgets.CfnBudget.SubscriberProperty(
                            subscription_type="SNS",
                            address=topic.topic_arn,
                        ),
                    ],
                ),
            ],
        )

        # -- Lambda teardown function --
        teardown_fn = _lambda.Function(
            self,
            "TeardownFn",
            function_name=f"{cfg.app_name}-{cfg.env_name}-budget-teardown",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="index.handler",
            code=_lambda.InlineCode(_TEARDOWN_HANDLER),
            timeout=Duration.minutes(5),
            environment={
                "EPHEMERAL_STACKS": ",".join(ephemeral_stack_names),
                "STACK_REGION": cfg.region,
            },
        )

        # Scope IAM to specific stack ARNs only (T-09-01 least-privilege)
        teardown_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["cloudformation:DeleteStack"],
                resources=[
                    f"arn:aws:cloudformation:{cfg.region}:{cfg.account_id}:stack/{name}/*"
                    for name in ephemeral_stack_names
                ],
            )
        )

        # Subscribe Lambda to budget alarm topic
        topic.add_subscription(subs.LambdaSubscription(teardown_fn))
