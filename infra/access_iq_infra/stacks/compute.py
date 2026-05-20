"""ComputeStack -- ECS cluster + 3 Fargate task definitions with secrets wired (D-01, D-05, D-06)."""

from __future__ import annotations

from typing import Any

from aws_cdk import CfnOutput, Stack
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_ecr as ecr
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_iam as iam
from aws_cdk import aws_kms as kms
from aws_cdk import aws_logs as logs
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_secretsmanager as secretsmanager
from constructs import Construct

from access_iq_infra.settings import EnvConfig

INGESTION_SOURCES = ["ingest-postgres", "ingest-sftp", "ingest-trust-s3"]


class ComputeStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        cfg: EnvConfig,
        vpc: ec2.IVpc,
        ecs_task_sg: ec2.ISecurityGroup,
        repository: ecr.IRepository,
        platform_bucket: s3.IBucket,
        lake_key: kms.IKey,
        pseudonymisation_key_secret: secretsmanager.ISecret,
        ecs_task_role: iam.IRole,
        ecs_execution_role: iam.IRole,
        log_groups: dict[str, logs.ILogGroup],
        **kwargs: Any,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # platform_bucket, lake_key, pseudonymisation_key_secret, ecs_task_sg:
        # Accepted as constructor props for completeness / future use (e.g. passing
        # bucket name as env var, SG for run-task network config). IAM grants live
        # in IngestionRoleStack to avoid cross-stack cyclic dependencies.

        # -- Section 1: ECS Cluster (REQ-ECS-01) ----------
        cluster = ecs.Cluster(
            self,
            "IngestionCluster",
            cluster_name=f"{cfg.app_name}-{cfg.env_name}-ingestion",
            vpc=vpc,
            enable_fargate_capacity_providers=True,
            container_insights=True,
        )

        # -- Section 2: Secrets lookup (REQ-ECS-01 -- valueFrom wiring) ----------
        # Secrets already exist in SM under access-iq/{env}/ prefix.
        # Looked up by name -- CDK does not create them; they must exist at deploy time.
        _sm = secretsmanager.Secret

        ingestion_secrets: dict[str, ecs.Secret] = {
            "EHR_DSN": ecs.Secret.from_secrets_manager(
                _sm.from_secret_name_v2(self, "EhrDsnSecret", f"access-iq/{cfg.env_name}/ehr-dsn")
            ),
            "URGENT_CARE_DSN": ecs.Secret.from_secrets_manager(
                _sm.from_secret_name_v2(
                    self,
                    "UrgentCareDsnSecret",
                    f"access-iq/{cfg.env_name}/urgent-care-dsn",
                )
            ),
            "SFTP_HOST": ecs.Secret.from_secrets_manager(
                _sm.from_secret_name_v2(
                    self, "SftpHostSecret", f"access-iq/{cfg.env_name}/sftp-host"
                )
            ),
            "SFTP_PORT": ecs.Secret.from_secrets_manager(
                _sm.from_secret_name_v2(
                    self, "SftpPortSecret", f"access-iq/{cfg.env_name}/sftp-port"
                )
            ),
            "SFTP_USER": ecs.Secret.from_secrets_manager(
                _sm.from_secret_name_v2(
                    self, "SftpUserSecret", f"access-iq/{cfg.env_name}/sftp-user"
                )
            ),
            "SFTP_PASSWORD": ecs.Secret.from_secrets_manager(
                _sm.from_secret_name_v2(
                    self,
                    "SftpPasswordSecret",
                    f"access-iq/{cfg.env_name}/sftp-password",
                )
            ),
        }

        # Source-specific secret subsets -- each task def only gets what it needs
        postgres_secrets = {
            k: v for k, v in ingestion_secrets.items() if k in ("EHR_DSN", "URGENT_CARE_DSN")
        }
        sftp_secrets = {k: v for k, v in ingestion_secrets.items() if k.startswith("SFTP_")}
        trust_s3_secrets: dict[str, ecs.Secret] = {}

        source_secrets_map: dict[str, dict[str, ecs.Secret]] = {
            "ingest-postgres": postgres_secrets,
            "ingest-sftp": sftp_secrets,
            "ingest-trust-s3": trust_s3_secrets,
        }

        # -- Section 3: Task Definitions (D-01, D-05, D-06, REQ-ECS-01) ----------
        task_defs: dict[str, ecs.FargateTaskDefinition] = {}

        for source in INGESTION_SOURCES:
            construct_id_safe = "".join(w.capitalize() for w in source.split("-")) + "TaskDef"

            task_def = ecs.FargateTaskDefinition(
                self,
                construct_id_safe,
                family=f"{cfg.app_name}-{cfg.env_name}-{source}",
                task_role=ecs_task_role,
                execution_role=ecs_execution_role,
                cpu=cfg.ecs.get("cpu", 512),
                memory_limit_mib=cfg.ecs.get("memory_limit_mib", 1024),
            )

            task_def.add_container(
                source,
                image=ecs.ContainerImage.from_ecr_repository(repository, tag="latest"),
                command=[source],
                logging=ecs.LogDrivers.aws_logs(
                    stream_prefix=source,
                    log_group=log_groups[source],
                ),
                environment={
                    "ACCESS_IQ_ENV": cfg.env_name,
                    "ACCESS_IQ_AWS_REGION": cfg.region,
                    "ACCESS_IQ_PLATFORM_BUCKET": platform_bucket.bucket_name,
                },
                secrets=source_secrets_map[source],
            )

            task_defs[source] = task_def

        # -- Section 4: CfnOutputs ----------
        CfnOutput(
            self,
            "ClusterArn",
            value=cluster.cluster_arn,
            export_name=f"{cfg.app_name}-{cfg.env_name}-cluster-arn",
            description="ECS ingestion cluster ARN.",
        )
        CfnOutput(
            self,
            "ClusterName",
            value=cluster.cluster_name,
            export_name=f"{cfg.app_name}-{cfg.env_name}-cluster-name",
            description="ECS ingestion cluster name.",
        )

        for source, td in task_defs.items():
            safe = source.replace("-", "")
            CfnOutput(
                self,
                f"{safe}TaskDefArn",
                value=td.task_definition_arn,
                export_name=f"{cfg.app_name}-{cfg.env_name}-{source}-task-def-arn",
                description=f"Task definition ARN for {source}.",
            )

        # -- Section 5: Exposed props ----------
        self.cluster = cluster
        self.task_defs = task_defs
