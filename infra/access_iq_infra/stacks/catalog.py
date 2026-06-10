"""CatalogStack - Glue Data Catalog database placeholder for Phase 4."""

from __future__ import annotations

from typing import Any

from aws_cdk import CfnOutput, RemovalPolicy, Stack
from aws_cdk import aws_glue as glue
from constructs import Construct

from access_iq_infra.settings import EnvConfig


class CatalogStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        cfg: EnvConfig,
        **kwargs: Any,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        db_name = f"{cfg.app_name}-{cfg.env_name}-bronze"

        database = glue.CfnDatabase(
            self,
            "BronzeDatabase",
            catalog_id=cfg.account_id,
            database_input=glue.CfnDatabase.DatabaseInputProperty(
                name=db_name,
                description=(
                    f"Bronze catalog for {cfg.app_name} ({cfg.env_name}). "
                    "Phase 4 dbt-external-tables registers partitions here."
                ),
            ),
        )
        database.apply_removal_policy(
            RemovalPolicy.RETAIN if cfg.env_name == "prod" else RemovalPolicy.DESTROY
        )

        CfnOutput(
            self,
            "BronzeDatabaseName",
            value=db_name,
            export_name=f"{cfg.app_name}-{cfg.env_name}-bronze-db-name",
            description="Glue database name for Bronze external tables.",
        )

        self.database_name = db_name
