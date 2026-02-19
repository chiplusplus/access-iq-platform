from __future__ import annotations

from typing import cast

from aws_cdk import (
    Stack,
)
from aws_cdk import aws_iam as iam
from aws_cdk.aws_s3 import IBucket
from constructs import Construct

from access_iq_infra.settings import EnvConfig


class IngestionRoleStack(Stack):
    """
    Creates the IAM role used by the access-iq ingestion service.
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        cfg: EnvConfig,
        platform_bucket: IBucket,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        ingestion_role = iam.Role(
            self,
            "IngestionRole",
            role_name=f"{cfg.app_name}-{cfg.env_name}-ingestion-role",
            assumed_by=cast(
                iam.IPrincipal,
                iam.ArnPrincipal(f"arn:aws:iam::{cfg.account_id}:assumed-role/{cfg.user_name}"),
            ),
        )

        ingestion_policy = iam.Policy(
            self,
            "IngestionPolicy",
            policy_name=f"{cfg.app_name}-{cfg.env_name}-ingestion-policy",
            statements=[
                iam.PolicyStatement(
                    actions=[
                        "s3:GetObject",
                        "s3:ListBucket",
                    ],
                    resources=[
                        f"arn:aws:s3:::{cfg.iam['external_bucket']}",
                        f"arn:aws:s3:::{cfg.iam['external_bucket']}/*",
                    ],
                ),
                iam.PolicyStatement(
                    actions=[
                        "s3:PutObject",
                        "s3:AbortMultipartUpload",
                        "s3:ListBucketMultipartUploads",
                        "s3:ListMultipartUploadParts",
                    ],
                    resources=[
                        f"arn:aws:s3:::{platform_bucket.bucket_name}/_manifests/*",
                        f"arn:aws:s3:::{platform_bucket.bucket_name}/bronze/*",
                    ],
                ),
                iam.PolicyStatement(
                    actions=[
                        "s3:ListBucket",
                    ],
                    resources=[
                        f"arn:aws:s3:::{platform_bucket.bucket_name}",
                    ],
                    conditions={"StringLike": {"s3:prefix": ["bronze/*", "_manifests/*"]}},
                ),
            ],
        )

        ingestion_role.attach_inline_policy(ingestion_policy)

        self.ingestion_role = ingestion_role
