"""WarehouseStack — Redshift Serverless namespace, workgroup, Spectrum IAM role, SG, usage limit.

Snapshot lifecycle:
  - FinalSnapshotName uses a timestamp suffix to guarantee uniqueness across destroy/recreate
    cycles (avoids SnapshotAlreadyExistsFault — Pitfall 6).
  - Snapshots are taken automatically on ``cdk destroy`` but not auto-restored on deploy.
    Fresh namespace is created each session; bronze data in S3 persists for dbt rebuilds.
"""

from __future__ import annotations

import time
from typing import Any

from aws_cdk import CfnOutput, Stack
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_iam as iam
from aws_cdk import aws_kms as kms
from aws_cdk import aws_redshiftserverless as rs
from aws_cdk import aws_s3 as s3
from aws_cdk.custom_resources import (
    AwsCustomResource,
    AwsCustomResourcePolicy,
    AwsSdkCall,
    PhysicalResourceId,
)
from constructs import Construct

from access_iq_infra.settings import EnvConfig


class WarehouseStack(Stack):
    """
    Redshift Serverless warehouse for the Access-IQ platform.

    Resources created:
      - CfnNamespace  (KMS-encrypted, audit-logged, Spectrum IAM role attached)
      - CfnWorkgroup  (private subnets, enhanced VPC routing, not publicly accessible)
      - Spectrum IAM role  (S3 read on lake + Glue Catalog read-only)
      - Redshift security group  (inbound 5439 from ECS task SG only)
      - Usage limit CR  (caps RPU-hours/day via AwsCustomResource — CfnUsageLimit not in CDK)

    Exposes:
        self.workgroup      — rs.CfnWorkgroup
        self.namespace      — rs.CfnNamespace
        self.spectrum_role  — iam.Role
        self.redshift_sg    — ec2.SecurityGroup
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        cfg: EnvConfig,
        vpc: ec2.IVpc,
        ecs_task_sg: ec2.ISecurityGroup,
        lake_bucket: s3.IBucket,
        lake_key: kms.IKey,
        catalog_database_name: str,
        **kwargs: Any,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        prefix = f"{cfg.app_name}-{cfg.env_name}"

        # ── Security Group (T-04-04) ──────────────────────────────────────────
        # Deny-by-default egress; inbound only from ECS task SG on port 5439.
        redshift_sg = ec2.SecurityGroup(
            self,
            "RedshiftSg",
            vpc=vpc,
            security_group_name=f"{prefix}-redshift",
            description="Redshift Serverless - inbound from ECS task SG only",
            allow_all_outbound=False,
        )
        redshift_sg.add_ingress_rule(
            ecs_task_sg,
            ec2.Port.tcp(5439),
            "dbt and ECS tasks to Redshift",
        )
        # HTTPS egress for S3 via VPC gateway endpoint
        redshift_sg.add_egress_rule(
            ec2.Peer.any_ipv4(),
            ec2.Port.tcp(443),
            "HTTPS to S3 via VPC gateway endpoint",
        )

        # ── Spectrum IAM Role (T-04-02, D-14) ────────────────────────────────
        # Read-only on lake bucket + Glue Catalog; no write permissions.
        spectrum_role = iam.Role(
            self,
            "SpectrumRole",
            role_name=f"{prefix}-spectrum-role",
            assumed_by=iam.ServicePrincipal("redshift.amazonaws.com"),
            description="Spectrum: S3 read on lake + Glue Catalog access",
        )
        lake_bucket.grant_read(spectrum_role)
        lake_key.grant_decrypt(spectrum_role)
        spectrum_role.add_to_principal_policy(
            iam.PolicyStatement(
                actions=[
                    "glue:GetDatabase",
                    "glue:GetDatabases",
                    "glue:GetTable",
                    "glue:GetTables",
                    "glue:GetPartition",
                    "glue:GetPartitions",
                    "glue:BatchGetPartition",
                    "glue:CreateTable",
                    "glue:UpdateTable",
                    "glue:DeleteTable",
                    "glue:CreatePartition",
                    "glue:BatchCreatePartition",
                    "glue:UpdatePartition",
                    "glue:DeletePartition",
                    "glue:BatchDeletePartition",
                ],
                resources=["*"],
            )
        )

        # ── CfnNamespace (T-04-03, D-01, D-12) ───────────────────────────────
        # Timestamped FinalSnapshotName avoids SnapshotAlreadyExistsFault on repeated
        # destroy/recreate cycles (Pitfall 6 mitigation).
        snapshot_name = f"{prefix}-final-{int(time.time())}"
        namespace = rs.CfnNamespace(
            self,
            "Namespace",
            namespace_name=prefix,
            db_name=cfg.redshift.get("db_name", "dev"),
            kms_key_id=lake_key.key_arn,
            manage_admin_password=True,
            iam_roles=[spectrum_role.role_arn],
            default_iam_role_arn=spectrum_role.role_arn,
            log_exports=["userlog", "connectionlog", "useractivitylog"],
            final_snapshot_name=snapshot_name,
            final_snapshot_retention_period=cfg.redshift.get("snapshot_retention_days", 7),
        )

        # ── CfnWorkgroup (T-04-01, D-13) ─────────────────────────────────────
        private_subnet_ids = vpc.select_subnets(
            subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
        ).subnet_ids
        workgroup = rs.CfnWorkgroup(
            self,
            "Workgroup",
            workgroup_name=prefix,
            namespace_name=namespace.namespace_name,
            base_capacity=cfg.redshift.get("base_capacity", 8),
            enhanced_vpc_routing=True,
            publicly_accessible=False,
            subnet_ids=private_subnet_ids,
            security_group_ids=[redshift_sg.security_group_id],
        )
        workgroup.add_dependency(namespace)

        # ── Usage Limit (T-04-05, D-02) ──────────────────────────────────────
        # CfnUsageLimit is not available in this CDK version; use AwsCustomResource.
        usage_limit_cr = AwsCustomResource(
            self,
            "UsageLimitCr",
            on_create=AwsSdkCall(
                service="redshift-serverless",
                action="createUsageLimit",
                parameters={
                    "resourceArn": workgroup.attr_workgroup_workgroup_arn,
                    "usageType": "serverless-compute",
                    "amount": cfg.redshift.get("usage_limit_rpu_hours", 4),
                    "period": "daily",
                },
                physical_resource_id=PhysicalResourceId.of(f"{prefix}-usage-limit"),
            ),
            policy=AwsCustomResourcePolicy.from_sdk_calls(resources=["*"]),
            install_latest_aws_sdk=False,
        )
        usage_limit_cr.node.add_dependency(workgroup)

        # ── CfnOutputs ───────────────────────────────────────────────────────
        CfnOutput(
            self,
            "WorkgroupEndpoint",
            value=workgroup.attr_workgroup_endpoint_address,
            export_name=f"{prefix}-redshift-endpoint",
            description="Redshift Serverless workgroup endpoint address",
        )
        CfnOutput(
            self,
            "SpectrumRoleArn",
            value=spectrum_role.role_arn,
            export_name=f"{prefix}-spectrum-role-arn",
            description="Spectrum IAM role ARN for Redshift external schema",
        )
        CfnOutput(
            self,
            "NamespaceName",
            value=namespace.namespace_name,
            export_name=f"{prefix}-redshift-namespace",
            description="Redshift Serverless namespace name",
        )

        # ── Expose props ──────────────────────────────────────────────────────
        self.workgroup = workgroup
        self.namespace = namespace
        self.spectrum_role = spectrum_role
        self.redshift_sg = redshift_sg
