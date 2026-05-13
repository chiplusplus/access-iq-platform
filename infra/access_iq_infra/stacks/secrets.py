"""SecretsStack — pseudonymisation HMAC key bootstrap (D9).

Stateful: RETAIN in both dev and prod. Secrets Manager 7-30 day
pending-deletion window breaks redeploy cycles — same posture as KMS.
"""

from __future__ import annotations

from typing import Any

from aws_cdk import CfnOutput, RemovalPolicy, Stack
from aws_cdk import aws_kms as kms
from aws_cdk import aws_secretsmanager as secretsmanager
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
            removal_policy=RemovalPolicy.RETAIN,
        )

        CfnOutput(
            self,
            "PseudonymisationKeySecretArn",
            value=pseudonymisation_key_secret.secret_arn,
            export_name=f"{cfg.app_name}-{cfg.env_name}-pseudonymisation-key-arn",
            description="ARN of the pseudonymisation key secret.",
        )

        self.pseudonymisation_key_secret = pseudonymisation_key_secret
