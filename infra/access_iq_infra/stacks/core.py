from __future__ import annotations

from access_iq_infra.settings import EnvConfig
from aws_cdk import (
    Duration,
    RemovalPolicy,
    Stack,
    Tags,
)
from aws_cdk import aws_logs as logs
from aws_cdk import aws_s3 as s3
from constructs import Construct


class CoreStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, *, cfg: EnvConfig, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Tags: cost allocation + maturity signal
        Tags.of(self).add("Project", cfg.app_name)
        Tags.of(self).add("Environment", cfg.env_name)
        Tags.of(self).add("ManagedBy", "cdk")

        # Central log group (you'll use this later for pipeline/app logs)
        logs.LogGroup(
            self,
            "AccessIqLogGroup",
            log_group_name=f"/aws/access-iq/{cfg.app_name}",
            retention=logs.RetentionDays.ONE_MONTH
            if cfg.env_name == "prod"
            else logs.RetentionDays.ONE_WEEK,
            removal_policy=RemovalPolicy.RETAIN
            if cfg.env_name == "prod"
            else RemovalPolicy.DESTROY,
        )

        # One “platform” bucket per environment
        # You will later create prefixes conventionally: bronze/, silver/, gold/
        s3.Bucket(
            self,
            "DataBucket",
            bucket_name=f"{cfg.app_name}-data-{cfg.env_name}-{cfg.account_id}",
            versioned=True,
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            removal_policy=RemovalPolicy.RETAIN
            if cfg.env_name == "prod"
            else RemovalPolicy.DESTROY,
            auto_delete_objects=False if cfg.env_name == "prod" else True,
            lifecycle_rules=[
                s3.LifecycleRule(
                    enabled=True,
                    abort_incomplete_multipart_upload_after=Duration.days(7),
                )
            ],
        )
