from __future__ import annotations

from typing import Any, cast

from aws_cdk import Stack
from aws_cdk import aws_iam as iam
from aws_cdk import aws_kms as kms
from aws_cdk import aws_secretsmanager as secretsmanager
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
        lake_key: kms.IKey,
        pseudonymisation_key_secret: secretsmanager.ISecret | None = None,
        **kwargs: Any,
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
                        f"arn:aws:s3:::{platform_bucket.bucket_name}/_manifests",
                        f"arn:aws:s3:::{platform_bucket.bucket_name}/_manifests/*",
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

        lake_key.grant_encrypt_decrypt(ingestion_role)

        # Grant secretsmanager:GetSecretValue manually instead of using
        # grant_read(), which also adds a KMS key policy on the lake key —
        # that creates a cross-stack cyclic dependency (lake ↔ ingestion-role).
        # KMS decrypt is already covered by lake_key.grant_encrypt_decrypt above.
        if pseudonymisation_key_secret is not None:
            ingestion_role.add_to_principal_policy(
                iam.PolicyStatement(
                    actions=["secretsmanager:GetSecretValue"],
                    resources=[pseudonymisation_key_secret.secret_arn],
                )
            )

        self.ingestion_role = ingestion_role

        # ── ECS Task Role (D-13, D-14) ──────────────────────────────────
        ecs_task_role = iam.Role(
            self,
            "EcsTaskRole",
            role_name=f"{cfg.app_name}-{cfg.env_name}-ecs-task-role",
            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
        )

        ecs_task_policy = iam.Policy(
            self,
            "EcsTaskPolicy",
            policy_name=f"{cfg.app_name}-{cfg.env_name}-ecs-task-policy",
            statements=[
                iam.PolicyStatement(
                    actions=["s3:GetObject", "s3:ListBucket"],
                    resources=[
                        f"arn:aws:s3:::{cfg.iam['external_bucket']}",
                        f"arn:aws:s3:::{cfg.iam['external_bucket']}/*",
                        f"arn:aws:s3:::{platform_bucket.bucket_name}/_manifests",
                        f"arn:aws:s3:::{platform_bucket.bucket_name}/_manifests/*",
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
                    actions=["s3:ListBucket"],
                    resources=[f"arn:aws:s3:::{platform_bucket.bucket_name}"],
                    conditions={"StringLike": {"s3:prefix": ["bronze/*", "_manifests/*"]}},
                ),
            ],
        )
        ecs_task_role.attach_inline_policy(ecs_task_policy)

        # KMS: use grant_encrypt_decrypt (updates both role policy AND key resource policy)
        lake_key.grant_encrypt_decrypt(ecs_task_role)

        # Secrets Manager: manual grant to avoid cross-stack cyclic dependency
        if pseudonymisation_key_secret is not None:
            ecs_task_role.add_to_principal_policy(
                iam.PolicyStatement(
                    actions=["secretsmanager:GetSecretValue"],
                    resources=[pseudonymisation_key_secret.secret_arn],
                )
            )

        self.ecs_task_role = ecs_task_role

        # ── ECS Execution Role (D-13) ───────────────────────────────────
        ecs_execution_role = iam.Role(
            self,
            "EcsExecutionRole",
            role_name=f"{cfg.app_name}-{cfg.env_name}-ecs-execution-role",
            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AmazonECSTaskExecutionRolePolicy"
                ),
            ],
        )

        # Scope SM access to access-iq/{env}/* for ECS valueFrom injection
        ecs_execution_role.add_to_principal_policy(
            iam.PolicyStatement(
                actions=["secretsmanager:GetSecretValue"],
                resources=[
                    f"arn:aws:secretsmanager:{cfg.region}:{cfg.account_id}:secret:access-iq/{cfg.env_name}/*",
                ],
            )
        )

        self.ecs_execution_role = ecs_execution_role
