"""CDK assertion tests for ComputeStack."""

from __future__ import annotations

from typing import Any

import pytest

aws_cdk = pytest.importorskip("aws_cdk")
from aws_cdk import App, Environment, Stack  # noqa: E402
from aws_cdk import aws_ec2 as ec2  # noqa: E402
from aws_cdk import aws_ecr as ecr  # noqa: E402
from aws_cdk import aws_iam as iam  # noqa: E402
from aws_cdk import aws_kms as kms  # noqa: E402
from aws_cdk import aws_logs as logs  # noqa: E402
from aws_cdk import aws_s3 as s3  # noqa: E402
from aws_cdk import aws_secretsmanager as secretsmanager  # noqa: E402
from aws_cdk.assertions import Template  # noqa: E402
from constructs import Construct  # noqa: E402

from access_iq_infra.settings import EnvConfig  # noqa: E402
from access_iq_infra.stacks.compute import ComputeStack  # noqa: E402

SOURCES = ["ingest-postgres", "ingest-sftp", "ingest-trust-s3"]
SECRET_ENV_NAMES = {
    "EHR_DSN",
    "URGENT_CARE_DSN",
    "SFTP_HOST",
    "SFTP_PORT",
    "SFTP_USER",
    "SFTP_PASSWORD",
}
SAFE_ENV_NAMES = {"ACCESS_IQ_ENV", "ACCESS_IQ_AWS_REGION", "ACCESS_IQ_PLATFORM_BUCKET"}


def _cfg() -> EnvConfig:
    return EnvConfig(
        app_name="access-iq",
        env_name="dev",
        user_name="AWSReservedSSO_test/test",
        account_id="111111111111",
        region="eu-west-2",
        s3={},
        iam={"external_bucket": "x", "trust_account_id": "999999999999"},
        vpc={},
        tags={},
        ecs={"cpu": 512, "memory_limit_mib": 1024},
        obs={},
    )


class _DepsStack(Stack):
    """Helper stack providing mock dependencies for ComputeStack."""

    def __init__(self, scope: Construct, construct_id: str, **kwargs: Any) -> None:
        super().__init__(scope, construct_id, **kwargs)
        self.vpc = ec2.Vpc(self, "Vpc")
        self.sg = ec2.SecurityGroup(self, "Sg", vpc=self.vpc)
        self.repo = ecr.Repository(self, "Repo")
        self.bucket = s3.Bucket(self, "Bucket")
        self.key = kms.Key(self, "Key")
        self.pseudo_secret = secretsmanager.Secret(self, "PseudoSecret")
        self.task_role = iam.Role(
            self, "TaskRole", assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com")
        )
        self.exec_role = iam.Role(
            self, "ExecRole", assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com")
        )
        self.log_groups = {
            src: logs.LogGroup(self, f"Lg{src}", log_group_name=f"/test/{src}") for src in SOURCES
        }


def _template() -> Template:
    app = App()
    env = Environment(account="111111111111", region="eu-west-2")
    cfg = _cfg()

    deps = _DepsStack(app, "deps", env=env)
    stack = ComputeStack(
        app,
        "compute-test",
        cfg=cfg,
        vpc=deps.vpc,
        ecs_task_sg=deps.sg,
        repository=deps.repo,
        platform_bucket=deps.bucket,
        lake_key=deps.key,
        pseudonymisation_key_secret=deps.pseudo_secret,
        ecs_task_role=deps.task_role,
        ecs_execution_role=deps.exec_role,
        log_groups=deps.log_groups,
        env=env,
    )
    return Template.from_stack(stack)


def test_one_ecs_cluster() -> None:
    tpl = _template()
    tpl.resource_count_is("AWS::ECS::Cluster", 1)


def test_three_task_definitions() -> None:
    tpl = _template()
    tpl.resource_count_is("AWS::ECS::TaskDefinition", 3)


def test_task_def_cpu_memory() -> None:
    tpl = _template()
    tpl.has_resource_properties(
        "AWS::ECS::TaskDefinition",
        {"Cpu": "512", "Memory": "1024"},
    )


def test_task_def_has_container_with_command() -> None:
    tpl = _template()
    task_defs = tpl.find_resources("AWS::ECS::TaskDefinition")
    commands_found: set[str] = set()
    for _lid, res in task_defs.items():
        containers = res.get("Properties", {}).get("ContainerDefinitions", [])
        for container in containers:
            cmd = container.get("Command", [])
            if cmd:
                commands_found.update(cmd)
    for source in SOURCES:
        assert source in commands_found, f"Expected Command [{source}] in a task definition"


def test_no_plaintext_secrets_in_environment() -> None:
    tpl = _template()
    task_defs = tpl.find_resources("AWS::ECS::TaskDefinition")
    for _lid, res in task_defs.items():
        containers = res.get("Properties", {}).get("ContainerDefinitions", [])
        for container in containers:
            env_vars = container.get("Environment", [])
            env_names = {e.get("Name") for e in env_vars}
            leaked = env_names & SECRET_ENV_NAMES
            assert not leaked, (
                f"Plaintext secrets in environment: {leaked}. Use secrets (valueFrom) instead."
            )
            # Verify only safe env vars are present
            for name in env_names:
                assert name in SAFE_ENV_NAMES, f"Unexpected env var '{name}' in environment block"


def test_secrets_wired_via_value_from() -> None:
    tpl = _template()
    task_defs = tpl.find_resources("AWS::ECS::TaskDefinition")

    # Collect secrets per command
    command_secrets: dict[str, list[str]] = {}
    for _lid, res in task_defs.items():
        containers = res.get("Properties", {}).get("ContainerDefinitions", [])
        for container in containers:
            cmd = container.get("Command", [])
            secrets_list = container.get("Secrets", [])
            secret_names = [s.get("Name") for s in secrets_list]
            if cmd:
                command_secrets[cmd[0]] = secret_names

    # ingest-postgres must have EHR_DSN and URGENT_CARE_DSN
    pg_secrets = set(command_secrets.get("ingest-postgres", []))
    assert "EHR_DSN" in pg_secrets, "ingest-postgres missing EHR_DSN secret"
    assert "URGENT_CARE_DSN" in pg_secrets, "ingest-postgres missing URGENT_CARE_DSN secret"

    # ingest-sftp must have all SFTP secrets
    sftp_secrets = set(command_secrets.get("ingest-sftp", []))
    for name in ("SFTP_HOST", "SFTP_PORT", "SFTP_USER", "SFTP_PASSWORD"):
        assert name in sftp_secrets, f"ingest-sftp missing {name} secret"

    # ingest-trust-s3 should have no source-specific secrets
    s3_secrets = command_secrets.get("ingest-trust-s3", [])
    assert len(s3_secrets) == 0, f"ingest-trust-s3 should have no secrets, got {s3_secrets}"


def test_cluster_name_follows_convention() -> None:
    tpl = _template()
    tpl.has_resource_properties(
        "AWS::ECS::Cluster",
        {"ClusterName": "access-iq-dev-ingestion"},
    )
