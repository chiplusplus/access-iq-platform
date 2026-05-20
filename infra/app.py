from aws_cdk import App, Environment

from access_iq_infra.settings import load_env_config
from access_iq_infra.stacks.catalog import CatalogStack
from access_iq_infra.stacks.ecr import EcrStack
from access_iq_infra.stacks.iam import IngestionRoleStack
from access_iq_infra.stacks.lake import LakeStack
from access_iq_infra.stacks.network import NetworkStack
from access_iq_infra.stacks.secrets import SecretsStack
from access_iq_infra.tagging import apply_tags

app = App()

env_name = app.node.try_get_context("env")
if env_name not in {"dev", "prod"}:
    raise ValueError("Pass the environment: -c env=dev or -c env=prod")

cfg = load_env_config(env_name)

apply_tags(app, cfg.tags)

cdk_env = Environment(account=cfg.account_id, region=cfg.region)

# --- Stateful stacks (RETAIN) ---

lake = LakeStack(
    app,
    f"lake-{cfg.app_name}-{cfg.env_name}",
    cfg=cfg,
    env=cdk_env,
)

secrets = SecretsStack(
    app,
    f"secrets-{cfg.app_name}-{cfg.env_name}",
    cfg=cfg,
    encryption_key=lake.lake_key,
    env=cdk_env,
)

CatalogStack(
    app,
    f"catalog-{cfg.app_name}-{cfg.env_name}",
    cfg=cfg,
    env=cdk_env,
)

EcrStack(
    app,
    f"ecr-{cfg.app_name}-{cfg.env_name}",
    cfg=cfg,
    env=cdk_env,
)

# --- Stateless stacks ---

IngestionRoleStack(
    app,
    f"ingestion-role-{cfg.app_name}-{cfg.env_name}",
    cfg=cfg,
    platform_bucket=lake.lake_bucket,
    lake_key=lake.lake_key,
    pseudonymisation_key_secret=secrets.pseudonymisation_key_secret,
    env=cdk_env,
)

network = NetworkStack(
    app,
    f"network-{cfg.app_name}-{cfg.env_name}",
    cfg=cfg,
    env=cdk_env,
)
# Phase 3 consumers: network.vpc, network.ecs_task_sg

app.synth()
