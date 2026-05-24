"""Shared fixtures for integration tests against live AWS infrastructure."""

from __future__ import annotations

import os
from typing import Any

import boto3
import pytest


def _require_env(name: str, default: str | None = None) -> str:
    val = os.environ.get(name, default)
    if not val:
        pytest.skip(f"{name} not set")
    return val


@pytest.fixture(scope="session")
def env_config() -> dict[str, Any]:
    profile = _require_env("AWS_PROFILE", "CHI-Engineer-222308823356")
    env_name = _require_env("CDK_ENV", "dev")
    region = _require_env("AWS_REGION", "eu-west-2")

    session = boto3.Session(profile_name=profile, region_name=region)
    account_id = session.client("sts").get_caller_identity()["Account"]

    return {
        "profile": profile,
        "env_name": env_name,
        "region": region,
        "account_id": account_id,
        "prefix": f"access-iq-{env_name}",
        "session": session,
    }


@pytest.fixture(scope="session")
def aws_session(env_config: dict[str, Any]) -> boto3.Session:
    session: boto3.Session = env_config["session"]
    return session


@pytest.fixture(scope="session")
def s3_client(aws_session: boto3.Session) -> Any:
    return aws_session.client("s3")


@pytest.fixture(scope="session")
def ec2_client(aws_session: boto3.Session) -> Any:
    return aws_session.client("ec2")


@pytest.fixture(scope="session")
def ecs_client(aws_session: boto3.Session) -> Any:
    return aws_session.client("ecs")


@pytest.fixture(scope="session")
def ecr_client(aws_session: boto3.Session) -> Any:
    return aws_session.client("ecr")


@pytest.fixture(scope="session")
def cfn_client(aws_session: boto3.Session) -> Any:
    return aws_session.client("cloudformation")


@pytest.fixture(scope="session")
def glue_client(aws_session: boto3.Session) -> Any:
    return aws_session.client("glue")


@pytest.fixture(scope="session")
def redshift_serverless_client(aws_session: boto3.Session) -> Any:
    return aws_session.client("redshift-serverless")


@pytest.fixture(scope="session")
def redshift_data_client(aws_session: boto3.Session) -> Any:
    return aws_session.client("redshift-data")


@pytest.fixture(scope="session")
def cloudwatch_client(aws_session: boto3.Session) -> Any:
    return aws_session.client("cloudwatch")


@pytest.fixture(scope="session")
def logs_client(aws_session: boto3.Session) -> Any:
    return aws_session.client("logs")


@pytest.fixture(scope="session")
def sns_client(aws_session: boto3.Session) -> Any:
    return aws_session.client("sns")


@pytest.fixture(scope="session")
def secretsmanager_client(aws_session: boto3.Session) -> Any:
    return aws_session.client("secretsmanager")


@pytest.fixture(scope="session")
def iam_client(aws_session: boto3.Session) -> Any:
    return aws_session.client("iam")


@pytest.fixture(scope="session")
def lambda_client(aws_session: boto3.Session) -> Any:
    return aws_session.client("lambda")


def skip_if_not_found(func):
    """Decorator: skip test if AWS resource doesn't exist."""
    import functools

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as exc:
            error_code = getattr(exc, "response", {}).get("Error", {}).get("Code", "")
            skip_codes = {
                "NoSuchBucket",
                "ResourceNotFoundException",
                "NotFoundException",
                "EntityNotFoundException",
                "ClusterNotFoundException",
                "StackNotFoundException",
                "RepositoryNotFoundException",
                "SecretNotFoundException",
                "NoSuchEntity",
                "DashboardNotFoundError",
            }
            if error_code in skip_codes:
                pytest.skip(f"Resource not found: {error_code}")
            raise

    return wrapper
