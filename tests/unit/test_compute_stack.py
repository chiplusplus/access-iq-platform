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
SAFE_ENV_NAMES = {
    "ACCESS_IQ_ENV",
    "ACCESS_IQ_AWS_REGION",
    "ACCESS_IQ_PLATFORM_BUCKET",
    "ACCESS_IQ_LAKE_KMS_KEY_ARN",
    "ACCESS_IQ_POSTGRES_SOURCES",
    "ACCESS_IQ_SFTP_SOURCES",
    "ACCESS_IQ_TRUST_S3",
    # Pipeline-only env vars (Phase 7)
    "DBT_TARGET",
    "DBT_PROFILES_DIR",
    "DBT_PROJECT_DIR",
    "REDSHIFT_LAMBDA_UDF_ROLE_ARN",
    "HMAC_LAMBDA_NAME",
    "ALERT_SNS_TOPIC_ARN",
    "REDSHIFT_SPECTRUM_ROLE_ARN",
    "BRONZE_S3_PREFIX",
    "PREFECT_API_URL",
    # Prefect server container env vars
    "PREFECT_SERVER_API_HOST",
    "PREFECT_HOME",
    "PREFECT_SERVER_ANALYTICS_ENABLED",
}


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
        redshift={
            "base_capacity": 8,
            "usage_limit_rpu_hours": 4,
            "snapshot_retention_days": 7,
            "db_name": "dev",
        },
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
        self.log_groups["pipeline"] = logs.LogGroup(
            self, "LgPipeline", log_group_name="/test/pipeline"
        )
        self.log_groups["prefect-server"] = logs.LogGroup(
            self, "LgPrefectServer", log_group_name="/test/prefect-server"
        )
        self.log_groups["prefect-worker"] = logs.LogGroup(
            self, "LgPrefectWorker", log_group_name="/test/prefect-worker"
        )
        self.prefect_worker_role = iam.Role(
            self,
            "PrefectWorkerRole",
            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
        )


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
        prefect_worker_role=deps.prefect_worker_role,
        env=env,
    )
    return Template.from_stack(stack)


def test_one_ecs_cluster() -> None:
    tpl = _template()
    tpl.resource_count_is("AWS::ECS::Cluster", 1)


def test_six_task_definitions() -> None:
    """3 ingestion + 1 pipeline + 1 prefect-server + 1 prefect-worker = 6 total."""
    tpl = _template()
    tpl.resource_count_is("AWS::ECS::TaskDefinition", 6)


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
    for name in ("SFTP_HOST", "SFTP_PORT", "SFTP_USER", "SFTP_PRIVATE_KEY"):
        assert name in sftp_secrets, f"ingest-sftp missing {name} secret"

    # ingest-trust-s3 should have no source-specific secrets
    s3_secrets = command_secrets.get("ingest-trust-s3", [])
    assert len(s3_secrets) == 0, f"ingest-trust-s3 should have no secrets, got {s3_secrets}"


def test_source_config_env_vars_match_task() -> None:
    """Each ingestion task def gets only its own config blob; pipeline gets all three."""
    tpl = _template()
    task_defs = tpl.find_resources("AWS::ECS::TaskDefinition")

    config_env_names = {
        "ACCESS_IQ_POSTGRES_SOURCES",
        "ACCESS_IQ_SFTP_SOURCES",
        "ACCESS_IQ_TRUST_S3",
    }
    # Ingestion task defs: each gets exactly one config blob
    ingestion_expected: dict[str, str] = {
        "ingest-postgres": "ACCESS_IQ_POSTGRES_SOURCES",
        "ingest-sftp": "ACCESS_IQ_SFTP_SOURCES",
        "ingest-trust-s3": "ACCESS_IQ_TRUST_S3",
    }

    for _lid, res in task_defs.items():
        containers = res.get("Properties", {}).get("ContainerDefinitions", [])
        for container in containers:
            cmd = container.get("Command", [])
            if not cmd:
                continue
            source = cmd[0]
            if source == "pipeline":
                # Pipeline task gets all three config blobs merged in
                env_names = {e.get("Name") for e in container.get("Environment", [])}
                for cfg_var in config_env_names:
                    assert cfg_var in env_names, f"pipeline missing {cfg_var}"
                continue
            # Skip non-ingestion containers (prefect server/worker use bash -c or prefect commands)
            if source not in ingestion_expected:
                continue
            env_names = {e.get("Name") for e in container.get("Environment", [])}
            config_vars = env_names & config_env_names
            assert ingestion_expected[source] in config_vars, (
                f"{source} missing {ingestion_expected[source]}"
            )
            unexpected = config_vars - {ingestion_expected[source]}
            assert not unexpected, f"{source} has config for wrong source: {unexpected}"


def test_cluster_name_follows_convention() -> None:
    tpl = _template()
    tpl.has_resource_properties(
        "AWS::ECS::Cluster",
        {"ClusterName": "access-iq-dev-ingestion"},
    )


def test_two_ecs_services() -> None:
    """Prefect server + worker ECS services = 2."""
    tpl = _template()
    tpl.resource_count_is("AWS::ECS::Service", 2)


def test_cloud_map_namespace() -> None:
    """One private DNS namespace for Prefect service discovery."""
    tpl = _template()
    tpl.resource_count_is("AWS::ServiceDiscovery::PrivateDnsNamespace", 1)


def test_server_health_check() -> None:
    """Prefect server container has a HealthCheck with health endpoint."""
    tpl = _template()
    task_defs = tpl.find_resources("AWS::ECS::TaskDefinition")
    found = False
    for _lid, res in task_defs.items():
        containers = res.get("Properties", {}).get("ContainerDefinitions", [])
        for container in containers:
            hc = container.get("HealthCheck", {})
            cmd = hc.get("Command", [])
            if any("health" in str(c) for c in cmd):
                found = True
    assert found, "Expected Prefect server container to have a HealthCheck referencing 'health'"


def test_worker_connects_to_server() -> None:
    """Worker container has PREFECT_API_URL pointing to Cloud Map hostname."""
    tpl = _template()
    task_defs = tpl.find_resources("AWS::ECS::TaskDefinition")
    found = False
    for _lid, res in task_defs.items():
        containers = res.get("Properties", {}).get("ContainerDefinitions", [])
        for container in containers:
            env_vars = container.get("Environment", [])
            for ev in env_vars:
                if ev.get(
                    "Name"
                ) == "PREFECT_API_URL" and "prefect-server.access-iq.local" in ev.get("Value", ""):
                    found = True
    assert found, (
        "Expected worker (or pipeline) container to have PREFECT_API_URL with prefect-server.access-iq.local"
    )


def test_pipeline_has_prefect_api_url() -> None:
    """Pipeline container has PREFECT_API_URL in environment (not in secrets)."""
    tpl = _template()
    task_defs = tpl.find_resources("AWS::ECS::TaskDefinition")
    found = False
    for _lid, res in task_defs.items():
        containers = res.get("Properties", {}).get("ContainerDefinitions", [])
        for container in containers:
            cmd = container.get("Command", [])
            if "pipeline" not in (cmd[0] if cmd else ""):
                continue
            env_vars = container.get("Environment", [])
            env_names = {e.get("Name") for e in env_vars}
            secret_names = {s.get("Name") for s in container.get("Secrets", [])}
            if "PREFECT_API_URL" in env_names and "PREFECT_API_URL" not in secret_names:
                found = True
    assert found, "Expected pipeline container to have PREFECT_API_URL in environment (not secrets)"
