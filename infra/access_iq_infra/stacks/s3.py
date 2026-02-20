from __future__ import annotations

from aws_cdk import (
    Duration,
    RemovalPolicy,
    Stack,
)
from aws_cdk import aws_s3 as s3
from constructs import Construct

from access_iq_infra.settings import EnvConfig


class PlatformBucketStack(Stack):
    """
    Creates the main project bucket used by access-iq (Bronze/Silver/Gold + others).
    """

    def __init__(self, scope: Construct, construct_id: str, *, cfg: EnvConfig, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        data_bucket = s3.Bucket(
            self,
            "ProjectBucket",
            bucket_name=f"{cfg.app_name}-{cfg.env_name}-{cfg.account_id}",
            versioned=True,
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            object_ownership=s3.ObjectOwnership.BUCKET_OWNER_ENFORCED,
            # Dev can be destroyed; prod should retain
            removal_policy=RemovalPolicy.RETAIN
            if cfg.env_name == "prod"
            else RemovalPolicy.DESTROY,
            auto_delete_objects=False if cfg.env_name == "prod" else True,
            lifecycle_rules=[
                # Hygiene: don't leave broken multipart uploads around
                s3.LifecycleRule(
                    enabled=True,
                    abort_incomplete_multipart_upload_after=Duration.days(7),
                ),
                # Versioning can get expensive; trim old noncurrent versions
                s3.LifecycleRule(
                    enabled=True,
                    noncurrent_version_expiration=Duration.days(
                        30 if cfg.env_name == "prod" else 7
                    ),
                ),
            ],
        )

        self.data_bucket = data_bucket
