from __future__ import annotations

import pytest

aws_cdk = pytest.importorskip("aws_cdk")
from aws_cdk import App  # noqa: E402
from aws_cdk.assertions import Template  # noqa: E402

from access_iq_infra.settings import EnvConfig  # noqa: E402
from access_iq_infra.stacks.ecr import EcrStack  # noqa: E402


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
    )


@pytest.mark.parametrize(
    ("env_name", "expected_policy"),
    [("dev", "Delete"), ("prod", "Retain")],
)
def test_ecr_creates_one_repo(env_name: str, expected_policy: str) -> None:
    app = App()
    stack = EcrStack(app, f"EcrStack-{env_name}", cfg=_cfg(env_name))
    tpl = Template.from_stack(stack)

    tpl.resource_count_is("AWS::ECR::Repository", 1)
    tpl.has_resource("AWS::ECR::Repository", {"DeletionPolicy": expected_policy})
    tpl.has_resource_properties(
        "AWS::ECR::Repository",
        {
            "RepositoryName": f"access-iq-{env_name}-ingestion",
            "ImageScanningConfiguration": {"ScanOnPush": True},
            "ImageTagMutability": "IMMUTABLE",
        },
    )


def test_ecr_exports_repo_uri() -> None:
    app = App()
    stack = EcrStack(app, "EcrStack", cfg=_cfg())
    tpl = Template.from_stack(stack)

    tpl.has_output(
        "IngestionRepoUri",
        {"Export": {"Name": "access-iq-dev-ingestion-repo-uri"}},
    )
