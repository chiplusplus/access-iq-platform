from aws_cdk import App, Environment

from access_iq_infra.settings import load_env_config
from access_iq_infra.stacks.iam import IngestionRoleStack
from access_iq_infra.stacks.s3 import PlatformBucketStack
from access_iq_infra.tagging import apply_tags

app = App()

env_name = app.node.try_get_context("env")
if env_name not in {"dev", "prod"}:
    raise ValueError("Pass the environment: -c env=dev or -c env=prod")

cfg = load_env_config(env_name)

# Apply tags globally to everything in this CDK app
apply_tags(app, cfg.tags)

cdk_env = Environment(account=cfg.account_id, region=cfg.region)

bucket = PlatformBucketStack(
    app,
    f"platform-bucket-{cfg.app_name}",
    cfg=cfg,
    env=cdk_env,
)

IngestionRoleStack(
    app,
    f"ingestion-role-{cfg.app_name}",
    cfg=cfg,
    platform_bucket=bucket.data_bucket,
    env=cdk_env,
)
app.synth()
