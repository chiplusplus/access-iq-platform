"""Throwaway stack: Lambda in Platform VPC to test cross-VPC connectivity."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from aws_cdk import Duration, RemovalPolicy, Stack
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from constructs import Construct

from access_iq_infra.settings import EnvConfig

SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "scripts"


class ConnectivityTestStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        cfg: EnvConfig,
        vpc: ec2.IVpc,
        security_group: ec2.ISecurityGroup,
        **kwargs: Any,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        fn = lambda_.Function(
            self,
            "ConnectivityTestFn",
            function_name=f"{cfg.app_name}-connectivity-test",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="connectivity_test.handler",
            code=lambda_.Code.from_asset(str(SCRIPTS_DIR)),
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
            security_groups=[security_group],
            timeout=Duration.seconds(30),
            memory_size=128,
        )

        logs.LogGroup(
            self,
            "ConnectivityTestLogs",
            log_group_name=f"/aws/lambda/{fn.function_name}",
            retention=logs.RetentionDays.ONE_DAY,
            removal_policy=RemovalPolicy.DESTROY,
        )
