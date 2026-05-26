from __future__ import annotations

import pytest

aws_cdk = pytest.importorskip("aws_cdk")
from aws_cdk import App, Stack  # noqa: E402
from aws_cdk import aws_kms as kms  # noqa: E402
from aws_cdk.assertions import Match, Template  # noqa: E402

from access_iq_infra.settings import EnvConfig  # noqa: E402
from access_iq_infra.stacks.secrets import SecretsStack  # noqa: E402


def _cfg(env_name: str = "dev") -> EnvConfig:
    return EnvConfig(
        app_name="access-iq",
        env_name=env_name,
        user_name="AWSReservedSSO_test/test",
        account_id="111111111111",
        region="eu-west-2",
        s3={},
        iam={},
        vpc={},
        tags={},
        ecs={},
        obs={},
        redshift={},
    )


def _template(env_name: str = "dev") -> Template:
    app = App()
    key_stack = Stack(app, f"KeyHost-{env_name}")
    key = kms.Key(key_stack, "TestKey")
    stack = SecretsStack(app, f"SecretsStack-{env_name}", cfg=_cfg(env_name), encryption_key=key)
    return Template.from_stack(stack)


@pytest.mark.parametrize(
    ("env_name", "expected_policy"),
    [("dev", "Delete"), ("prod", "Retain")],
)
def test_secrets_stack_removal_policy(env_name: str, expected_policy: str) -> None:
    tpl = _template(env_name)
    tpl.resource_count_is("AWS::SecretsManager::Secret", 1)
    tpl.has_resource("AWS::SecretsManager::Secret", {"DeletionPolicy": expected_policy})


def test_secrets_stack_secret_name_convention() -> None:
    tpl = _template("dev")
    tpl.has_resource_properties(
        "AWS::SecretsManager::Secret",
        {"Name": "access-iq/dev/pseudonymisation-key"},
    )


def test_secrets_stack_uses_kms_encryption() -> None:
    tpl = _template("dev")
    tpl.has_resource_properties(
        "AWS::SecretsManager::Secret",
        {"KmsKeyId": Match.any_value()},
    )


def test_secrets_stack_emits_arn_output() -> None:
    tpl = _template("dev")
    outputs = tpl.find_outputs("PseudonymisationKeySecretArn")
    assert outputs, "Expected PseudonymisationKeySecretArn output"
