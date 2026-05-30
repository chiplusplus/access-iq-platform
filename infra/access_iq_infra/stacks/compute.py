"""ComputeStack -- ECS cluster + 3 Fargate task definitions with secrets wired (D-01, D-05, D-06)."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

import aws_cdk as cdk
from aws_cdk import CfnOutput, Stack
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_ecr as ecr
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_iam as iam
from aws_cdk import aws_kms as kms
from aws_cdk import aws_logs as logs
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_secretsmanager as secretsmanager
from aws_cdk import aws_servicediscovery as cloudmap
from constructs import Construct

from access_iq_infra.settings import EnvConfig

if TYPE_CHECKING:
    from access_iq_infra.stacks.observability import ObservabilityStack
    from access_iq_infra.stacks.warehouse import WarehouseStack

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
        log_groups: Mapping[str, logs.ILogGroup],
        warehouse_stack: WarehouseStack | None = None,
        observability_stack: ObservabilityStack | None = None,
        prefect_worker_role: iam.IRole | None = None,
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
            "SFTP_PRIVATE_KEY": ecs.Secret.from_secrets_manager(
                _sm.from_secret_name_v2(
                    self,
                    "SftpPrivateKeySecret",
                    f"access-iq/{cfg.env_name}/sftp-private-key",
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

        # -- Section 3: Runtime config blobs (ACCESS_IQ_* JSON env vars) ----------
        # These JSON blobs tell the app which sources to ingest and where to
        # find the secret values injected by ECS (env var indirection pattern).
        source_env_map: dict[str, dict[str, str]] = {
            "ingest-postgres": {
                "ACCESS_IQ_POSTGRES_SOURCES": json.dumps(
                    {
                        "ehr_postgres": {
                            "dsn_env": "EHR_DSN",
                            "tables": [
                                "patient_demographics",
                                "encounters",
                                "referrals",
                                "diagnoses",
                            ],
                        },
                        "urgent_care_postgres": {
                            "dsn_env": "URGENT_CARE_DSN",
                            "tables": ["urgent_care_logs"],
                        },
                    }
                ),
            },
            "ingest-sftp": {
                "ACCESS_IQ_SFTP_SOURCES": json.dumps(
                    {
                        "appointments": {
                            "host_env": "SFTP_HOST",
                            "port_env": "SFTP_PORT",
                            "user_env": "SFTP_USER",
                            "private_key_env": "SFTP_PRIVATE_KEY",
                            "remote_dir": "/outbound/appointments/",
                            "source_name": "sftp_appointments",
                        },
                    }
                ),
            },
            "ingest-trust-s3": {
                "ACCESS_IQ_TRUST_S3": json.dumps(
                    {
                        "base": {"bucket": cfg.iam["external_bucket"]},
                        "diagnostics": {
                            "prefix_root": "diagnostics",
                            "source_name": "trust_s3_diagnostics",
                        },
                        "provider_ref": {
                            "key": "providers/sites_and_services_master.xlsx",
                            "source_name": "trust_s3_provider_ref",
                        },
                    }
                ),
            },
        }

        # -- Section 4: Task Definitions (D-01, D-05, D-06, REQ-ECS-01) ----------
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
                    "ACCESS_IQ_LAKE_KMS_KEY_ARN": lake_key.key_arn,
                    **source_env_map[source],
                },
                secrets=source_secrets_map[source],
            )

            task_defs[source] = task_def

        # -- Section 4b: Pipeline Task Definition (Phase 7 — full orchestration flow) --
        # Merges all ingestion secrets + Prefect API key. Environment includes
        # Redshift, dbt, GE, and SNS config for the single-container pipeline.
        pipeline_secrets: dict[str, ecs.Secret] = {
            **ingestion_secrets,  # all 6 ingestion secrets (EHR_DSN, URGENT_CARE_DSN, SFTP_*)
            "REDSHIFT_DSN": ecs.Secret.from_secrets_manager(
                _sm.from_secret_name_v2(
                    self,
                    "RedshiftDsnSecret",
                    f"access-iq/{cfg.env_name}/redshift-dsn",
                )
            ),
            "REDSHIFT_PASSWORD": ecs.Secret.from_secrets_manager(
                _sm.from_secret_name_v2(
                    self,
                    "RedshiftPasswordSecret",
                    f"access-iq/{cfg.env_name}/redshift-password",
                )
            ),
        }

        # Merge ALL source env maps (postgres + sftp + trust-s3 runtime config JSON blobs)
        pipeline_env: dict[str, str] = {
            "ACCESS_IQ_ENV": cfg.env_name,
            "ACCESS_IQ_AWS_REGION": cfg.region,
            "ACCESS_IQ_PLATFORM_BUCKET": platform_bucket.bucket_name,
            "ACCESS_IQ_LAKE_KMS_KEY_ARN": lake_key.key_arn,
        }
        for source_env in source_env_map.values():
            pipeline_env.update(source_env)

        # Additional env vars for dbt, GE, UNLOAD, SNS alerting, and self-hosted Prefect.
        pipeline_env.update(
            {
                "DBT_TARGET": "prod",
                "DBT_PROFILES_DIR": "/app/dbt",
                "DBT_PROJECT_DIR": "/app/dbt",
                "BRONZE_S3_PREFIX": f"s3://{platform_bucket.bucket_name}/bronze",
                "PREFECT_API_URL": "http://prefect-server.access-iq.local:4200/api",
            }
        )
        if warehouse_stack is not None:
            pipeline_env["REDSHIFT_LAMBDA_UDF_ROLE_ARN"] = warehouse_stack.lambda_udf_role.role_arn
            pipeline_env["HMAC_LAMBDA_NAME"] = warehouse_stack.hmac_lambda.function_name
            pipeline_env["SPECTRUM_ROLE_ARN"] = warehouse_stack.spectrum_role.role_arn
            pipeline_env["REDSHIFT_HOST"] = (
                warehouse_stack.workgroup.attr_workgroup_endpoint_address
            )
            pipeline_env["REDSHIFT_USER"] = "admin"
        if observability_stack is not None:
            pipeline_env["ALERT_SNS_TOPIC_ARN"] = observability_stack.sns_topic.topic_arn

        pipeline_task_def = ecs.FargateTaskDefinition(
            self,
            "PipelineTaskDef",
            family=f"{cfg.app_name}-{cfg.env_name}-pipeline",
            task_role=ecs_task_role,
            execution_role=ecs_execution_role,
            cpu=1024,
            memory_limit_mib=2048,
        )

        pipeline_task_def.add_container(
            "pipeline",
            image=ecs.ContainerImage.from_ecr_repository(repository, tag="latest"),
            command=["pipeline"],
            logging=ecs.LogDrivers.aws_logs(
                stream_prefix="pipeline",
                log_group=log_groups["pipeline"],
                mode=ecs.AwsLogDriverMode.NON_BLOCKING,
                max_buffer_size=cdk.Size.mebibytes(4),
            ),
            environment=pipeline_env,
            secrets=pipeline_secrets,
        )

        task_defs["pipeline"] = pipeline_task_def

        # -- Section 4c: Prefect server + worker services (Phase 7 -- self-hosted) --
        _prefect_api_url = "http://prefect-server.access-iq.local:4200/api"

        # Cloud Map private DNS namespace for service discovery within VPC
        namespace = cloudmap.PrivateDnsNamespace(
            self,
            "PrefectNamespace",
            name="access-iq.local",
            vpc=vpc,
        )

        # Prefect server task def (512 CPU / 1024 MiB)
        server_task_def = ecs.FargateTaskDefinition(
            self,
            "PrefectServerTaskDef",
            family=f"{cfg.app_name}-{cfg.env_name}-prefect-server",
            cpu=512,
            memory_limit_mib=1024,
            execution_role=ecs_execution_role,
        )
        server_task_def.add_container(
            "prefect-server",
            image=ecs.ContainerImage.from_registry("prefecthq/prefect:3-python3.12"),
            command=["prefect", "server", "start", "--host", "0.0.0.0"],
            port_mappings=[ecs.PortMapping(container_port=4200)],
            environment={
                "PREFECT_SERVER_API_HOST": "0.0.0.0",
                "PREFECT_HOME": "/data",
                "PREFECT_SERVER_ANALYTICS_ENABLED": "false",
            },
            logging=ecs.LogDrivers.aws_logs(
                stream_prefix="prefect-server",
                log_group=log_groups["prefect-server"],
            ),
            health_check=ecs.HealthCheck(
                command=[
                    "CMD-SHELL",
                    "python -c \"import urllib.request as u; u.urlopen('http://localhost:4200/api/health', timeout=3)\"",
                ],
                interval=cdk.Duration.seconds(30),
                timeout=cdk.Duration.seconds(10),
                retries=3,
                start_period=cdk.Duration.seconds(60),
            ),
        )

        # Prefect server ECS service with Cloud Map registration
        server_service = ecs.FargateService(
            self,
            "PrefectServerService",
            service_name=f"{cfg.app_name}-{cfg.env_name}-prefect-server",
            cluster=cluster,
            task_definition=server_task_def,
            desired_count=1,
            security_groups=[ecs_task_sg],
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
            cloud_map_options=ecs.CloudMapOptions(
                name="prefect-server",
                cloud_map_namespace=namespace,
                dns_record_type=cloudmap.DnsRecordType.A,
                dns_ttl=cdk.Duration.seconds(10),
            ),
        )

        # Prefect worker task def (256 CPU / 512 MiB)
        worker_role = prefect_worker_role if prefect_worker_role is not None else ecs_task_role
        worker_task_def = ecs.FargateTaskDefinition(
            self,
            "PrefectWorkerTaskDef",
            family=f"{cfg.app_name}-{cfg.env_name}-prefect-worker",
            cpu=256,
            memory_limit_mib=512,
            task_role=worker_role,
            execution_role=ecs_execution_role,
        )
        worker_task_def.add_container(
            "prefect-worker",
            image=ecs.ContainerImage.from_registry("prefecthq/prefect:3-python3.12"),
            command=[
                "bash",
                "-c",
                f"pip install prefect-aws==0.7.9 && prefect worker start --pool {cfg.app_name}-{cfg.env_name}-pipeline --type ecs",
            ],
            environment={
                "PREFECT_API_URL": _prefect_api_url,
            },
            logging=ecs.LogDrivers.aws_logs(
                stream_prefix="prefect-worker",
                log_group=log_groups["prefect-worker"],
            ),
        )

        # Prefect worker ECS service (depends on server for ordering)
        worker_service = ecs.FargateService(
            self,
            "PrefectWorkerService",
            service_name=f"{cfg.app_name}-{cfg.env_name}-prefect-worker",
            cluster=cluster,
            task_definition=worker_task_def,
            desired_count=1,
            security_groups=[ecs_task_sg],
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
        )
        worker_service.node.add_dependency(server_service)

        # -- Section 5: CfnOutputs ----------
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

        CfnOutput(
            self,
            "PrefectNamespaceArn",
            value=namespace.namespace_arn,
            export_name=f"{cfg.app_name}-{cfg.env_name}-prefect-namespace-arn",
            description="Cloud Map namespace ARN for Prefect service discovery.",
        )
        CfnOutput(
            self,
            "PrefectServerServiceArn",
            value=server_service.service_arn,
            export_name=f"{cfg.app_name}-{cfg.env_name}-prefect-server-service-arn",
            description="Prefect server ECS service ARN.",
        )

        # -- Section 6: Exposed props ----------
        self.cluster = cluster
        self.task_defs = task_defs
        self.pipeline_task_def = pipeline_task_def
        self.namespace = namespace
        self.server_service = server_service
        self.worker_service = worker_service
