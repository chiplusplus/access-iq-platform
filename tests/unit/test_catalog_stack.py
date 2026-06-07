from __future__ import annotations

import pytest

aws_cdk = pytest.importorskip("aws_cdk")
from aws_cdk import App  # noqa: E402
from aws_cdk.assertions import Template  # noqa: E402

from access_iq_infra.settings import EnvConfig  # noqa: E402
from access_iq_infra.stacks.catalog import CatalogStack  # noqa: E402


def _cfg(env_name: str = "dev") -> EnvConfig:
    return EnvConfig(
        app_name="access-iq",
        env_name=env_name,
        user_name="x",
        account_id="111111111111",
        region="eu-west-2",
        s3={},
        iam={},
        vpc={},
        tags={},
        ecs={},
        obs={},
        redshift={},
        dashboard={},
    )


@pytest.mark.parametrize(
    ("env_name", "expected_policy"),
    [("dev", "Delete"), ("prod", "Retain")],
)
def test_catalog_creates_glue_database(env_name: str, expected_policy: str) -> None:
    app = App()
    stack = CatalogStack(app, f"CatalogStack-{env_name}", cfg=_cfg(env_name))
    tpl = Template.from_stack(stack)

    tpl.resource_count_is("AWS::Glue::Database", 1)
    tpl.has_resource("AWS::Glue::Database", {"DeletionPolicy": expected_policy})
    tpl.has_resource_properties(
        "AWS::Glue::Database",
        {
            "DatabaseInput": {
                "Name": f"access-iq-{env_name}-bronze",
            },
        },
    )


def test_catalog_exports_database_name() -> None:
    app = App()
    stack = CatalogStack(app, "CatalogStack", cfg=_cfg())
    tpl = Template.from_stack(stack)

    tpl.has_output(
        "BronzeDatabaseName",
        {"Export": {"Name": "access-iq-dev-bronze-db-name"}},
    )
