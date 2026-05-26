"""End-to-end synth test — both envs synthesise the expected stack shape.

Programmatic synth is the canonical gate: fast, no `cdk` binary, no Node
toolchain in the test runner.
"""

from __future__ import annotations

import pytest

aws_cdk = pytest.importorskip("aws_cdk")
from aws_cdk import App, Environment  # noqa: E402

from access_iq_infra.settings import EnvConfig  # noqa: E402
from access_iq_infra.stacks.catalog import CatalogStack  # noqa: E402
from access_iq_infra.stacks.compute import ComputeStack  # noqa: E402
from access_iq_infra.stacks.ecr import EcrStack  # noqa: E402
from access_iq_infra.stacks.iam import IngestionRoleStack  # noqa: E402
from access_iq_infra.stacks.lake import LakeStack  # noqa: E402
from access_iq_infra.stacks.network import NetworkStack  # noqa: E402
from access_iq_infra.stacks.observability import ObservabilityStack  # noqa: E402
from access_iq_infra.stacks.secrets import SecretsStack  # noqa: E402
from access_iq_infra.stacks.warehouse import WarehouseStack  # noqa: E402

EXPECTED_STACKS = {
    "lake-access-iq-{env}",
    "secrets-access-iq-{env}",
    "catalog-access-iq-{env}",
    "ecr-access-iq-{env}",
    "ingestion-role-access-iq-{env}",
    "network-access-iq-{env}",
    "observability-access-iq-{env}",
    "compute-access-iq-{env}",
    "warehouse-access-iq-{env}",
}


def _cfg(env_name: str) -> EnvConfig:
    return EnvConfig(
        app_name="access-iq",
        env_name=env_name,
        user_name="test-user",
        account_id="111111111111",
        region="eu-west-2",
        s3={"removal_policy": "RETAIN" if env_name == "prod" else "DESTROY"},
        iam={
            "external_bucket": "northshire-trust-external-exports",
            "trust_account_id": "999999999999",
        },
        vpc={
            "platform_cidr": "10.10.0.0/16",
            "trust_cidr": "10.0.0.0/16",
            "max_azs": 2,
            "nat_gateways": 1,
        },
        tags={"Environment": env_name},
        ecs={"cpu": 512, "memory_limit_mib": 1024},
        obs={"log_retention_days": 7, "alert_email": "test@example.com"},
        redshift={
            "base_capacity": 8,
            "usage_limit_rpu_hours": 4,
            "snapshot_retention_days": 7,
            "db_name": "dev",
        },
    )


def _synth_app(env_name: str) -> App:
    app = App(
        context={
            "trust_vpc_id": "vpc-test",
            "trust_route_table_ids": "rtb-test1,rtb-test2",
        }
    )
    cfg = _cfg(env_name)
    cdk_env = Environment(account=cfg.account_id, region=cfg.region)

    lake = LakeStack(app, f"lake-{cfg.app_name}-{cfg.env_name}", cfg=cfg, env=cdk_env)
    secrets = SecretsStack(
        app,
        f"secrets-{cfg.app_name}-{cfg.env_name}",
        cfg=cfg,
        encryption_key=lake.lake_key,
        env=cdk_env,
    )
    catalog = CatalogStack(app, f"catalog-{cfg.app_name}-{cfg.env_name}", cfg=cfg, env=cdk_env)
    ecr = EcrStack(app, f"ecr-{cfg.app_name}-{cfg.env_name}", cfg=cfg, env=cdk_env)
    iam_stack = IngestionRoleStack(
        app,
        f"ingestion-role-{cfg.app_name}-{cfg.env_name}",
        cfg=cfg,
        platform_bucket=lake.lake_bucket,
        lake_key=lake.lake_key,
        pseudonymisation_key_secret=secrets.pseudonymisation_key_secret,
        env=cdk_env,
    )
    network = NetworkStack(
        app,
        f"network-{cfg.app_name}-{cfg.env_name}",
        cfg=cfg,
        env=cdk_env,
    )
    obs = ObservabilityStack(
        app,
        f"observability-{cfg.app_name}-{cfg.env_name}",
        cfg=cfg,
        env=cdk_env,
    )
    ComputeStack(
        app,
        f"compute-{cfg.app_name}-{cfg.env_name}",
        cfg=cfg,
        vpc=network.vpc,
        ecs_task_sg=network.ecs_task_sg,
        repository=ecr.repository,
        platform_bucket=lake.lake_bucket,
        lake_key=lake.lake_key,
        pseudonymisation_key_secret=secrets.pseudonymisation_key_secret,
        ecs_task_role=iam_stack.ecs_task_role,
        ecs_execution_role=iam_stack.ecs_execution_role,
        log_groups=obs.log_groups,
        env=cdk_env,
    )
    WarehouseStack(
        app,
        f"warehouse-{cfg.app_name}-{cfg.env_name}",
        cfg=cfg,
        vpc=network.vpc,
        ecs_task_sg=network.ecs_task_sg,
        lake_bucket=lake.lake_bucket,
        lake_key=lake.lake_key,
        catalog_database_name=catalog.database_name,
        env=cdk_env,
    )

    app.synth()
    return app


@pytest.mark.parametrize("env_name", ["dev", "prod"])
def test_synth_produces_nine_stacks(env_name: str) -> None:
    from aws_cdk import Stack

    app = _synth_app(env_name)
    stack_names = {child.node.id for child in app.node.children if isinstance(child, Stack)}
    expected = {s.format(env=env_name) for s in EXPECTED_STACKS}
    assert stack_names == expected


@pytest.mark.parametrize("env_name", ["dev", "prod"])
def test_ingestion_role_has_secret_grant(env_name: str) -> None:
    app = _synth_app(env_name)
    from aws_cdk.assertions import Match, Template

    ingestion_stack = app.node.find_child(f"ingestion-role-access-iq-{env_name}")
    tpl = Template.from_stack(ingestion_stack)  # type: ignore
    tpl.has_resource_properties(
        "AWS::IAM::Policy",
        {
            "PolicyDocument": {
                "Statement": Match.array_with(
                    [
                        Match.object_like(
                            {
                                "Action": "secretsmanager:GetSecretValue",
                                "Effect": "Allow",
                            }
                        ),
                    ]
                ),
            },
        },
    )
