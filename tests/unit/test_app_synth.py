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
from access_iq_infra.stacks.ecr import EcrStack  # noqa: E402
from access_iq_infra.stacks.iam import IngestionRoleStack  # noqa: E402
from access_iq_infra.stacks.lake import LakeStack  # noqa: E402
from access_iq_infra.stacks.secrets import SecretsStack  # noqa: E402

EXPECTED_STACKS = {
    "lake-access-iq-{env}",
    "secrets-access-iq-{env}",
    "catalog-access-iq-{env}",
    "ecr-access-iq-{env}",
    "ingestion-role-access-iq-{env}",
}


def _cfg(env_name: str) -> EnvConfig:
    return EnvConfig(
        app_name="access-iq",
        env_name=env_name,
        user_name="test-user",
        account_id="111111111111",
        region="eu-west-2",
        s3={"removal_policy": "RETAIN" if env_name == "prod" else "DESTROY"},
        iam={"external_bucket": "northshire-trust-external-exports"},
        tags={"Environment": env_name},
    )


def _synth_app(env_name: str) -> App:
    app = App()
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
    CatalogStack(app, f"catalog-{cfg.app_name}-{cfg.env_name}", cfg=cfg, env=cdk_env)
    EcrStack(app, f"ecr-{cfg.app_name}-{cfg.env_name}", cfg=cfg, env=cdk_env)
    IngestionRoleStack(
        app,
        f"ingestion-role-{cfg.app_name}-{cfg.env_name}",
        cfg=cfg,
        platform_bucket=lake.lake_bucket,
        lake_key=lake.lake_key,
        pseudonymisation_key_secret=secrets.pseudonymisation_key_secret,
        env=cdk_env,
    )

    app.synth()
    return app


@pytest.mark.parametrize("env_name", ["dev", "prod"])
def test_synth_produces_five_stacks(env_name: str) -> None:
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
    tpl = Template.from_stack(ingestion_stack)
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
