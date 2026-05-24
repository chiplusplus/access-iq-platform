"""LakeStack — stateful KMS CMK + S3 lake bucket + hardened bucket policy.

Bundled because the bucket's default encryption AND deny-non-KMS bucket policy
both reference the KMS key ARN; splitting these into two stacks would create
a circular reference. Stateful resources have RETAIN policies so destroying
stateless stacks (Phase 2+) leaves data intact.

See docs/adr/0003-kms-cmk-on-lake.md for the encryption decision.
"""

from __future__ import annotations

from typing import Any

from aws_cdk import CfnOutput, Duration, RemovalPolicy, Stack
from aws_cdk import aws_iam as iam
from aws_cdk import aws_kms as kms
from aws_cdk import aws_s3 as s3
from constructs import Construct

from access_iq_infra.lake_layout import LAKE_PREFIXES
from access_iq_infra.settings import EnvConfig


class LakeStack(Stack):
    """
    Stateful: KMS CMK + S3 lake bucket + hardened bucket policy.

    Lake layout (REQ-NET-03 lake portion):
        bronze/   silver/   gold/   _manifests/   _dq/

    Removal policy:
      - KMS key: RETAIN in dev AND prod (pending-deletion window breaks
        redeploy cycles — see pitfalls.md #8).
      - S3 bucket: RETAIN in prod; DESTROY + auto_delete_objects in dev.
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        cfg: EnvConfig,
        **kwargs: Any,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        is_prod = cfg.env_name == "prod"

        lake_key = kms.Key(
            self,
            "LakeKey",
            alias=f"alias/{cfg.app_name}-{cfg.env_name}-lake",
            description=(
                f"CMK for access-iq lake ({cfg.env_name}). Encrypts S3 + future Secrets/Logs."
            ),
            enable_key_rotation=True,
            removal_policy=RemovalPolicy.RETAIN if is_prod else RemovalPolicy.DESTROY,
            pending_window=Duration.days(30 if is_prod else 7),
        )

        lake_bucket = s3.Bucket(
            self,
            "LakeBucket",
            bucket_name=f"{cfg.app_name}-{cfg.env_name}-{cfg.account_id}",
            versioned=True,
            encryption=s3.BucketEncryption.KMS,
            encryption_key=lake_key,
            bucket_key_enabled=True,  # amortises KMS API cost for S3 reads/writes
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            object_ownership=s3.ObjectOwnership.BUCKET_OWNER_ENFORCED,
            removal_policy=RemovalPolicy.RETAIN if is_prod else RemovalPolicy.DESTROY,
            auto_delete_objects=False if is_prod else True,
            lifecycle_rules=[
                s3.LifecycleRule(
                    enabled=True,
                    abort_incomplete_multipart_upload_after=Duration.days(7),
                ),
                s3.LifecycleRule(
                    enabled=True,
                    noncurrent_version_expiration=Duration.days(30 if is_prod else 7),
                ),
            ],
        )

        # 3) Defence-in-depth bucket policy: deny non-KMS uploads even though
        # default encryption is KMS (clients can still explicitly request
        # SSE-S3 or SSE-C on a put — this blocks them).
        lake_bucket.add_to_resource_policy(
            iam.PolicyStatement(
                sid="DenyUnEncryptedObjectUploads",
                effect=iam.Effect.DENY,
                principals=[iam.AnyPrincipal()],
                actions=["s3:PutObject"],
                resources=[lake_bucket.arn_for_objects("*")],
                conditions={
                    "StringNotEquals": {
                        "s3:x-amz-server-side-encryption": "aws:kms",
                    },
                },
            )
        )
        # Also deny puts that specify a different KMS key ARN.
        lake_bucket.add_to_resource_policy(
            iam.PolicyStatement(
                sid="DenyIncorrectKmsKey",
                effect=iam.Effect.DENY,
                principals=[iam.AnyPrincipal()],
                actions=["s3:PutObject"],
                resources=[lake_bucket.arn_for_objects("*")],
                conditions={
                    "StringNotEqualsIfExists": {
                        "s3:x-amz-server-side-encryption-aws-kms-key-id": lake_key.key_arn,
                    },
                },
            )
        )

        self.lake_key = lake_key
        self.lake_bucket = lake_bucket
        self.lake_prefixes = LAKE_PREFIXES

        CfnOutput(self, "BucketName", value=lake_bucket.bucket_name)
        CfnOutput(self, "BucketArn", value=lake_bucket.bucket_arn)
        CfnOutput(self, "KmsKeyArn", value=lake_key.key_arn)
