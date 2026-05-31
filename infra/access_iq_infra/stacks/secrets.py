"""SecretsStack - pseudonymisation HMAC key bootstrap (D9)."""

from __future__ import annotations

from typing import Any

from aws_cdk import CfnOutput, RemovalPolicy, Stack
from aws_cdk import aws_iam as iam
from aws_cdk import aws_kms as kms
from aws_cdk import aws_secretsmanager as secretsmanager
from aws_cdk.custom_resources import (
    AwsCustomResource,
    AwsCustomResourcePolicy,
    AwsSdkCall,
    PhysicalResourceId,
)
from constructs import Construct

from access_iq_infra.settings import EnvConfig


class SecretsStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        cfg: EnvConfig,
        encryption_key: kms.IKey,
        **kwargs: Any,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        pseudonymisation_key_secret = secretsmanager.Secret(
            self,
            "PseudonymisationKey",
            secret_name=f"access-iq/{cfg.env_name}/pseudonymisation-key",
            description="HMAC-SHA-256 key for NHS-number pseudonymisation (D9).",
            encryption_key=encryption_key,
            generate_secret_string=secretsmanager.SecretStringGenerator(
                secret_string_template='{"created_by": "cdk"}',
                generate_string_key="key",
                password_length=64,
                exclude_characters="\"@/\\'\\` ",
                exclude_punctuation=False,
                include_space=False,
                require_each_included_type=False,
            ),
            removal_policy=RemovalPolicy.RETAIN
            if cfg.env_name == "prod"
            else RemovalPolicy.DESTROY,
        )

        if cfg.env_name != "prod":
            # Force immediate deletion in dev to avoid the 7-30 day recovery
            # window that blocks redeploys with the same secret name.
            AwsCustomResource(
                self,
                "ForceDeleteSecret",
                on_delete=AwsSdkCall(
                    service="SecretsManager",
                    action="deleteSecret",
                    parameters={
                        "SecretId": pseudonymisation_key_secret.secret_arn,
                        "ForceDeleteWithoutRecovery": True,
                    },
                    physical_resource_id=PhysicalResourceId.of("force-delete-secret"),
                ),
                policy=AwsCustomResourcePolicy.from_statements(
                    [
                        iam.PolicyStatement(
                            actions=["secretsmanager:DeleteSecret"],
                            resources=[pseudonymisation_key_secret.secret_arn],
                        )
                    ]
                ),
            )

        CfnOutput(
            self,
            "PseudonymisationKeySecretArn",
            value=pseudonymisation_key_secret.secret_arn,
            export_name=f"{cfg.app_name}-{cfg.env_name}-pseudonymisation-key-arn",
            description="ARN of the pseudonymisation key secret.",
        )

        self.pseudonymisation_key_secret = pseudonymisation_key_secret
