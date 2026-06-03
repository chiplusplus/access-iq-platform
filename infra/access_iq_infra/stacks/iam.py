from __future__ import annotations

from typing import Any, cast

from aws_cdk import CfnOutput, SecretValue, Stack
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
        # grant_read(), which also adds a KMS key policy on the lake key -
        # that creates a cross-stack cyclic dependency (lake ↔ iam).
        # KMS decrypt is already covered by lake_key.grant_encrypt_decrypt above.
        if pseudonymisation_key_secret is not None:
            ingestion_role.add_to_principal_policy(
                iam.PolicyStatement(
                    actions=["secretsmanager:GetSecretValue"],
                    resources=[pseudonymisation_key_secret.secret_arn],
                )
            )

        self.ingestion_role = ingestion_role

        CfnOutput(
            self,
            "IngestionRoleArn",
            value=ingestion_role.role_arn,
            export_name=f"{cfg.app_name}-{cfg.env_name}-ingestion-role-arn",
            description="ARN of the ingestion role (assumable by SSO user for bronze writes).",
        )

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
                        "s3:GetObject",
                        "s3:PutObject",
                        "s3:DeleteObject",
                        "s3:AbortMultipartUpload",
                        "s3:ListBucketMultipartUploads",
                        "s3:ListMultipartUploadParts",
                    ],
                    resources=[
                        f"arn:aws:s3:::{platform_bucket.bucket_name}/_manifests/*",
                        f"arn:aws:s3:::{platform_bucket.bucket_name}/bronze/*",
                        f"arn:aws:s3:::{platform_bucket.bucket_name}/_dq/*",
                    ],
                ),
                iam.PolicyStatement(
                    actions=["s3:ListBucket"],
                    resources=[f"arn:aws:s3:::{platform_bucket.bucket_name}"],
                    conditions={"StringLike": {"s3:prefix": ["bronze/*", "_manifests/*", "_dq/*"]}},
                ),
            ],
        )
        ecs_task_role.attach_inline_policy(ecs_task_policy)

        # SNS: allow pipeline on_failure hook to publish alerts (Phase 7)
        ecs_task_role.add_to_principal_policy(
            iam.PolicyStatement(
                actions=["sns:Publish"],
                resources=[
                    f"arn:aws:sns:{cfg.region}:{cfg.account_id}:{cfg.app_name}-{cfg.env_name}-ingestion-alerts",
                ],
            )
        )

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

        CfnOutput(
            self,
            "EcsTaskRoleArn",
            value=ecs_task_role.role_arn,
            export_name=f"{cfg.app_name}-{cfg.env_name}-ecs-task-role-arn",
        )

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

        CfnOutput(
            self,
            "EcsExecutionRoleArn",
            value=ecs_execution_role.role_arn,
            export_name=f"{cfg.app_name}-{cfg.env_name}-ecs-execution-role-arn",
        )

        # ── ECS Operator Role (control-plane) ──────────────────────────────
        # Separated from ingestion_role (data-plane) so a leaked data
        # credential cannot launch compute.  Grants RunTask + PassRole only.
        cluster_arn_pattern = (
            f"arn:aws:ecs:{cfg.region}:{cfg.account_id}:cluster/{cfg.app_name}-{cfg.env_name}-*"
        )
        task_def_arn_pattern = (
            f"arn:aws:ecs:{cfg.region}:{cfg.account_id}"
            f":task-definition/{cfg.app_name}-{cfg.env_name}-*"
        )

        ecs_operator_role = iam.Role(
            self,
            "EcsOperatorRole",
            role_name=f"{cfg.app_name}-{cfg.env_name}-ecs-operator-role",
            assumed_by=cast(
                iam.IPrincipal,
                iam.ArnPrincipal(f"arn:aws:iam::{cfg.account_id}:assumed-role/{cfg.user_name}"),
            ),
        )

        ecs_operator_role.add_to_principal_policy(
            iam.PolicyStatement(
                actions=["ecs:RunTask"],
                resources=[task_def_arn_pattern],
                conditions={"ArnLike": {"ecs:cluster": cluster_arn_pattern}},
            )
        )

        ecs_operator_role.add_to_principal_policy(
            iam.PolicyStatement(
                actions=["iam:PassRole"],
                resources=[ecs_task_role.role_arn, ecs_execution_role.role_arn],
                conditions={"StringEquals": {"iam:PassedToService": "ecs-tasks.amazonaws.com"}},
            )
        )

        ecs_operator_role.add_to_principal_policy(
            iam.PolicyStatement(
                actions=[
                    "ecs:DescribeTasks",
                    "ecs:ListTasks",
                    "ecs:DescribeClusters",
                ],
                resources=["*"],
                conditions={"ArnLike": {"ecs:cluster": cluster_arn_pattern}},
            )
        )

        ecs_operator_role.add_to_principal_policy(
            iam.PolicyStatement(
                actions=[
                    "ec2:DescribeVpcs",
                    "ec2:DescribeSubnets",
                    "ec2:DescribeSecurityGroups",
                ],
                resources=["*"],
            )
        )

        stack_arn_pattern = (
            f"arn:aws:cloudformation:{cfg.region}:{cfg.account_id}"
            f":stack/*-{cfg.app_name}-{cfg.env_name}/*"
        )
        ecs_operator_role.add_to_principal_policy(
            iam.PolicyStatement(
                actions=["cloudformation:DescribeStacks"],
                resources=[stack_arn_pattern],
            )
        )

        self.ecs_operator_role = ecs_operator_role

        CfnOutput(
            self,
            "EcsOperatorRoleArn",
            value=ecs_operator_role.role_arn,
            export_name=f"{cfg.app_name}-{cfg.env_name}-ecs-operator-role-arn",
            description="ARN of the ECS operator role for RunTask operations.",
        )

        # ── Prefect Worker Task Role (Phase 7 -- self-hosted) ───────────────────
        prefect_worker_role = iam.Role(
            self,
            "PrefectWorkerRole",
            role_name=f"{cfg.app_name}-{cfg.env_name}-prefect-worker-role",
            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
        )
        prefect_worker_role.add_to_principal_policy(
            iam.PolicyStatement(
                sid="EcsRunTask",
                actions=[
                    "ecs:RunTask",
                    "ecs:StopTask",
                    "ecs:DescribeTasks",
                    "ecs:TagResource",
                ],
                resources=["*"],
                conditions={
                    "ArnEquals": {
                        "ecs:cluster": f"arn:aws:ecs:{cfg.region}:{cfg.account_id}:cluster/{cfg.app_name}-{cfg.env_name}-ingestion"
                    }
                },
            )
        )
        prefect_worker_role.add_to_principal_policy(
            iam.PolicyStatement(
                sid="EcsTaskDefinition",
                actions=[
                    "ecs:RegisterTaskDefinition",
                    "ecs:DeregisterTaskDefinition",
                    "ecs:DescribeTaskDefinition",
                ],
                resources=["*"],
            )
        )
        prefect_worker_role.add_to_principal_policy(
            iam.PolicyStatement(
                sid="Ec2Describe",
                actions=[
                    "ec2:DescribeVpcs",
                    "ec2:DescribeSubnets",
                    "ec2:DescribeSecurityGroups",
                ],
                resources=["*"],
            )
        )
        prefect_worker_role.add_to_principal_policy(
            iam.PolicyStatement(
                sid="PassRole",
                actions=["iam:PassRole"],
                resources=[ecs_task_role.role_arn, ecs_execution_role.role_arn],
            )
        )
        prefect_worker_role.add_to_principal_policy(
            iam.PolicyStatement(
                sid="LogsWrite",
                actions=["logs:CreateLogStream", "logs:PutLogEvents"],
                resources=[
                    f"arn:aws:logs:{cfg.region}:{cfg.account_id}:log-group:/access-iq/{cfg.env_name}/*",
                    f"arn:aws:logs:{cfg.region}:{cfg.account_id}:log-group:/access-iq/{cfg.env_name}/*:log-stream:*",
                ],
            )
        )
        self.prefect_worker_role = prefect_worker_role

        CfnOutput(
            self,
            "PrefectWorkerRoleArn",
            value=prefect_worker_role.role_arn,
            export_name=f"{cfg.app_name}-{cfg.env_name}-prefect-worker-role-arn",
        )

        # ---------- Dashboard reader (D-17, Phase 8) ----------
        dashboard_user = iam.User(
            self,
            "DashboardReaderUser",
            user_name=f"{cfg.app_name}-{cfg.env_name}-dashboard-reader",
        )

        dashboard_policy = iam.Policy(
            self,
            "DashboardReaderPolicy",
            statements=[
                iam.PolicyStatement(
                    actions=["s3:GetObject"],
                    resources=[
                        f"arn:aws:s3:::{platform_bucket.bucket_name}/gold_export/*",
                    ],
                ),
                iam.PolicyStatement(
                    actions=["s3:ListBucket"],
                    resources=[
                        f"arn:aws:s3:::{platform_bucket.bucket_name}",
                    ],
                    conditions={
                        "StringLike": {"s3:prefix": ["gold_export/*"]},
                    },
                ),
            ],
        )
        dashboard_policy.attach_to_user(dashboard_user)

        lake_key.grant_decrypt(dashboard_user)

        # Access key for Streamlit Community Cloud secrets
        access_key = iam.AccessKey(self, "DashboardReaderKey", user=dashboard_user)

        # Store access key ID in Secrets Manager
        secretsmanager.Secret(
            self,
            "DashboardReaderSecret",
            secret_name=f"{cfg.app_name}/{cfg.env_name}/dashboard-reader",
            secret_string_value=SecretValue.unsafe_plain_text(
                '{"access_key_id":"' + access_key.access_key_id + '"}'
            ),
            description="Dashboard reader IAM user access key ID"
            " (secret key in CloudFormation output)",
        )

        CfnOutput(
            self,
            "DashboardReaderAccessKeyId",
            value=access_key.access_key_id,
            description="Dashboard reader IAM user access key ID",
        )
        CfnOutput(
            self,
            "DashboardReaderSecretKey",
            value=access_key.secret_access_key.unsafe_unwrap(),
            description="Dashboard reader IAM user secret access key (rotate after first use)",
        )

        self.dashboard_user = dashboard_user
