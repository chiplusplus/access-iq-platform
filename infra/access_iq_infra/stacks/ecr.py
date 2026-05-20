"""EcrStack — container registry for the ingestion image (Phase 3)."""

from __future__ import annotations

from typing import Any

from aws_cdk import CfnOutput, RemovalPolicy, Stack
from aws_cdk import aws_ecr as ecr
from constructs import Construct

from access_iq_infra.settings import EnvConfig


class EcrStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        cfg: EnvConfig,
        **kwargs: Any,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        repo_name = f"{cfg.app_name}-{cfg.env_name}-ingestion"

        repository = ecr.Repository(
            self,
            "IngestionRepo",
            repository_name=repo_name,
            image_scan_on_push=True,
            image_tag_mutability=ecr.TagMutability.MUTABLE,
            removal_policy=RemovalPolicy.RETAIN
            if cfg.env_name == "prod"
            else RemovalPolicy.DESTROY,
            empty_on_delete=cfg.env_name != "prod",
            lifecycle_rules=[
                ecr.LifecycleRule(
                    description="Retain last 20 untagged images",
                    max_image_count=20,
                    rule_priority=1,
                    tag_status=ecr.TagStatus.UNTAGGED,
                ),
            ],
        )

        CfnOutput(
            self,
            "IngestionRepoUri",
            value=repository.repository_uri,
            export_name=f"{cfg.app_name}-{cfg.env_name}-ingestion-repo-uri",
            description="ECR repository URI for the ingestion container image.",
        )

        self.repository = repository
