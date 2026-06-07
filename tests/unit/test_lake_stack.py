from __future__ import annotations

import pytest

aws_cdk = pytest.importorskip("aws_cdk")
from aws_cdk import App  # noqa: E402
from aws_cdk.assertions import Match, Template  # noqa: E402

from access_iq_infra.settings import EnvConfig  # noqa: E402
from access_iq_infra.stacks.lake import LakeStack  # noqa: E402


def _cfg(env_name: str = "dev") -> EnvConfig:
    return EnvConfig(
        app_name="access-iq",
        env_name=env_name,
        user_name="AWSReservedSSO_test/test",
        account_id="111111111111",
        region="eu-west-2",
        s3={},
        iam={"external_bucket": "northshire-trust-external-exports"},
        vpc={},
        tags={"Environment": env_name, "Project": "access-iq"},
        ecs={},
        obs={},
        redshift={},
        dashboard={},
    )


def _template(env_name: str = "dev") -> Template:
    app = App()
    stack = LakeStack(app, f"LakeStack-{env_name}", cfg=_cfg(env_name))
    return Template.from_stack(stack)


@pytest.mark.parametrize(
    ("env_name", "expected_policy"),
    [("dev", "Delete"), ("prod", "Retain")],
)
def test_kms_key_rotation_and_removal_policy(env_name: str, expected_policy: str) -> None:
    tpl = _template(env_name)
    tpl.resource_count_is("AWS::KMS::Key", 1)
    tpl.has_resource_properties("AWS::KMS::Key", {"EnableKeyRotation": True})
    tpl.has_resource("AWS::KMS::Key", {"DeletionPolicy": expected_policy})


@pytest.mark.parametrize("env_name", ["dev", "prod"])
def test_bucket_uses_kms_encryption(env_name: str) -> None:
    tpl = _template(env_name)
    tpl.resource_count_is("AWS::S3::Bucket", 1)
    tpl.has_resource_properties(
        "AWS::S3::Bucket",
        {
            "BucketEncryption": {
                "ServerSideEncryptionConfiguration": Match.array_with(
                    [
                        Match.object_like(
                            {
                                "ServerSideEncryptionByDefault": Match.object_like(
                                    {"SSEAlgorithm": "aws:kms"}
                                )
                            }
                        )
                    ]
                )
            }
        },
    )


def test_bucket_denies_non_kms_puts() -> None:
    tpl = _template("dev")
    bucket_policies = tpl.find_resources("AWS::S3::BucketPolicy")
    assert bucket_policies, "Expected at least one bucket policy"
    found_deny = False
    for _, res in bucket_policies.items():
        for stmt in res["Properties"]["PolicyDocument"]["Statement"]:
            if stmt.get("Effect") != "Deny":
                continue
            actions = stmt.get("Action", [])
            if isinstance(actions, str):
                actions = [actions]
            if "s3:PutObject" not in actions:
                continue
            cond = stmt.get("Condition", {})
            if (
                "StringNotEquals" in cond
                and "s3:x-amz-server-side-encryption" in cond["StringNotEquals"]
            ):
                found_deny = True
    assert found_deny, "Expected Deny PutObject when SSE != aws:kms"


def test_bucket_dev_destroy_prod_retain() -> None:
    _template("dev").has_resource("AWS::S3::Bucket", {"DeletionPolicy": "Delete"})
    _template("prod").has_resource("AWS::S3::Bucket", {"DeletionPolicy": "Retain"})


def test_stack_exports_stable_output_keys() -> None:
    tpl = _template("dev")
    outputs = tpl.to_json()["Outputs"]
    assert "BucketName" in outputs
    assert "BucketArn" in outputs
    assert "KmsKeyArn" in outputs
