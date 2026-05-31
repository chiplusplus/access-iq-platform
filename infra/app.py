from aws_cdk import App, Environment

from access_iq_infra.settings import load_env_config
from access_iq_infra.stacks.budget import BudgetStack
from access_iq_infra.stacks.catalog import CatalogStack
from access_iq_infra.stacks.compute import ComputeStack
from access_iq_infra.stacks.ecr import EcrStack
from access_iq_infra.stacks.iam import IngestionRoleStack
from access_iq_infra.stacks.lake import LakeStack
from access_iq_infra.stacks.network import NetworkStack
from access_iq_infra.stacks.observability import ObservabilityStack
from access_iq_infra.stacks.secrets import SecretsStack
from access_iq_infra.stacks.warehouse import WarehouseStack
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

catalog = CatalogStack(
    app,
    f"catalog-{cfg.app_name}-{cfg.env_name}",
    cfg=cfg,
    env=cdk_env,
)

ecr = EcrStack(
    app,
    f"ecr-{cfg.app_name}-{cfg.env_name}",
    cfg=cfg,
    env=cdk_env,
)

# --- Stateless stacks ---

iam_stack = IngestionRoleStack(
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

# --- Phase 3: Compute + Observability ---

obs = ObservabilityStack(
    app,
    f"observability-{cfg.app_name}-{cfg.env_name}",
    cfg=cfg,
    env=cdk_env,
)

# --- Phase 4: Warehouse ---

warehouse = WarehouseStack(
    app,
    f"warehouse-{cfg.app_name}-{cfg.env_name}",
    cfg=cfg,
    vpc=network.vpc,
    ecs_task_sg=network.ecs_task_sg,
    lake_bucket=lake.lake_bucket,
    lake_key=lake.lake_key,
    catalog_database_name=catalog.database_name,
    env=cdk_env,
)

ComputeStack(
    app,
    f"compute-{cfg.app_name}-{cfg.env_name}",
    cfg=cfg,
    vpc=network.vpc,
    ecs_task_sg=network.ecs_task_sg,
    repository=ecr.repository,
    platform_bucket=lake.lake_bucket,
    lake_key=lake.lake_key,
    pseudonymisation_key_secret=secrets.pseudonymisation_key_secret,
    ecs_task_role=iam_stack.ecs_task_role,
    ecs_execution_role=iam_stack.ecs_execution_role,
    log_groups=obs.log_groups,
    warehouse_stack=warehouse,
    observability_stack=obs,
    prefect_worker_role=iam_stack.prefect_worker_role,
    env=cdk_env,
)

# --- Phase 9: Cost ceiling (account-level, us-east-1) ---

BudgetStack(
    app,
    f"budget-{cfg.app_name}-{cfg.env_name}",
    cfg=cfg,
    ephemeral_stack_names=[
        f"compute-{cfg.app_name}-{cfg.env_name}",
        f"warehouse-{cfg.app_name}-{cfg.env_name}",
        f"network-{cfg.app_name}-{cfg.env_name}",
        f"observability-{cfg.app_name}-{cfg.env_name}",
        f"ingestion-role-{cfg.app_name}-{cfg.env_name}",
    ],
    env=Environment(account=cfg.account_id, region="us-east-1"),
)

# Trust account budget - only synthesised when explicitly requested via CDK context
# to avoid `cdk deploy --all` attempting cross-account deploy with Platform credentials.
# Deployed separately: cdk deploy budget-trust-... -c include_trust_budget=true --profile $TRUST_PROFILE
trust_account_id = cfg.iam.get("trust_account_id", "") if isinstance(cfg.iam, dict) else ""
include_trust_budget = app.node.try_get_context("include_trust_budget") == "true"
if trust_account_id and include_trust_budget:
    BudgetStack(
        app,
        f"budget-trust-{cfg.app_name}-{cfg.env_name}",
        cfg=cfg,
        ephemeral_stack_names=["NorthshireTrustStack"],
        target_account_id=trust_account_id,
        target_region=cfg.region,
        topic_name_suffix="trust-budget-alarm",
        env=Environment(account=trust_account_id, region="us-east-1"),
    )

app.synth()
