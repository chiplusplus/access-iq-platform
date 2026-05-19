# Phase 2: Networking - Pattern Map

**Mapped:** 2026-05-19
**Files analyzed:** 7
**Analogs found:** 7 / 7

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `infra/access_iq_infra/stacks/network.py` | stack | request-response (deploy-time CDK) | `infra/access_iq_infra/stacks/lake.py` | exact (same stack role, same cfg prop pattern) |
| `infra/app.py` | config/wiring | request-response | `infra/app.py` (itself — add lines) | exact |
| `infra/access_iq_infra/settings.py` | config | transform | `infra/access_iq_infra/settings.py` (itself — add field) | exact |
| `infra/access_iq_infra/stacks/__init__.py` | config | — | `infra/access_iq_infra/stacks/__init__.py` (itself — add export) | exact |
| `tests/unit/test_network_stack.py` | test | — | `tests/unit/test_lake_stack.py` | exact (same CDK assertions pattern) |
| `infra/config/dev.json` | config | — | `infra/config/dev.json` (itself — add vpc + iam.trust_account_id) | exact |
| `infra/config/prod.json` | config | — | `infra/config/dev.json` (structure identical) | exact |

---

## Pattern Assignments

### `infra/access_iq_infra/stacks/network.py` (stack, CDK deploy-time)

**Analog:** `infra/access_iq_infra/stacks/lake.py`

**Imports pattern** (lake.py lines 1-22):
```python
from __future__ import annotations

from typing import Any

from aws_cdk import RemovalPolicy, Stack
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_iam as iam
from aws_cdk.custom_resources import (
    AwsCustomResource,
    AwsCustomResourcePolicy,
    AwsSdkCall,
    PhysicalResourceId,
)
from constructs import Construct

from access_iq_infra.settings import EnvConfig
```

**Constructor signature pattern** (lake.py lines 37-46 — keyword-only `cfg`, `**kwargs` forwarded to `super()`):
```python
class NetworkStack(Stack):
    """
    Stateless: Platform VPC, peering, routes, endpoints, security groups.
    All resources use DESTROY removal policy — deploy/destroy each session.

    Required CDK context params:
        -c trust_vpc_id=vpc-xxx
        -c trust_route_table_ids=rtb-aaa,rtb-bbb
    """

    vpc: ec2.Vpc
    ecs_task_sg: ec2.SecurityGroup

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        cfg: EnvConfig,
        **kwargs: Any,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)
```

**Context param validation pattern** (fail fast at synth — from RESEARCH.md Pattern 8; matches lake.py's defensive style):
```python
        # Fail fast — Trust stack is ephemeral; IDs must be provided at synth time
        trust_vpc_id: str | None = self.node.try_get_context("trust_vpc_id")
        trust_rtb_ids_raw: str | None = self.node.try_get_context("trust_route_table_ids")
        if trust_vpc_id is None or trust_rtb_ids_raw is None:
            raise ValueError(
                "Trust VPC context required. Pass: "
                "-c trust_vpc_id=vpc-xxx "
                "-c trust_route_table_ids=rtb-aaa,rtb-bbb"
            )
        trust_route_table_ids = [x.strip() for x in trust_rtb_ids_raw.split(",")]
        trust_account_id: str = cfg.iam["trust_account_id"]
        peering_accepter_role_arn = (
            f"arn:aws:iam::{trust_account_id}:role/access-iq-peering-accepter"
        )
```

**cfg field access pattern** (lake.py lines 62-66 — dict fields accessed via `cfg.iam[...]`, `cfg.s3[...]`):
```python
        # vpc section added to EnvConfig in this phase
        platform_cidr: str = cfg.vpc["platform_cidr"]   # "10.10.0.0/16"
        trust_cidr: str = cfg.vpc["trust_cidr"]          # "10.0.0.0/16"
        max_azs: int = cfg.vpc["max_azs"]                # 2
        nat_gateways: int = cfg.vpc["nat_gateways"]      # 1
```

**Naming convention pattern** (lake.py lines 63-65 — `f"{cfg.app_name}-{cfg.env_name}-<resource>"`):
```python
        vpc = ec2.Vpc(
            self,
            "PlatformVpc",
            vpc_name=f"{cfg.app_name}-{cfg.env_name}-platform",
            ...
        )
        ecs_sg = ec2.SecurityGroup(
            self,
            "EcsTaskSg",
            security_group_name=f"{cfg.app_name}-{cfg.env_name}-ecs-task",
            ...
        )
```

**Exposed properties pattern** (lake.py lines 121-123 — assign to `self.*` at end of `__init__`):
```python
        self.vpc = vpc
        self.ecs_task_sg = ecs_sg
```

**RemovalPolicy pattern** (lake.py lines 57, 74 — RETAIN for stateful, DESTROY for stateless):
```python
        # NetworkStack is fully stateless — all resources DESTROY
        # No is_prod check needed; VPC is ephemeral in all envs per D-06
        removal_policy = RemovalPolicy.DESTROY
```

---

### `infra/app.py` (wiring — add NetworkStack)

**Analog:** `infra/app.py` itself (lines 1-66)

**Existing import block pattern** (lines 1-9):
```python
from aws_cdk import App, Environment

from access_iq_infra.settings import load_env_config
from access_iq_infra.stacks.catalog import CatalogStack
from access_iq_infra.stacks.ecr import EcrStack
from access_iq_infra.stacks.iam import IngestionRoleStack
from access_iq_infra.stacks.lake import LakeStack
from access_iq_infra.stacks.secrets import SecretsStack
from access_iq_infra.tagging import apply_tags
```
Add `from access_iq_infra.stacks.network import NetworkStack` to this block.

**Stateless stack instantiation pattern** (lines 54-64 — after `# --- Stateless stacks ---` comment, keyword-only props, `env=cdk_env`):
```python
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
```
NetworkStack goes after IngestionRoleStack, same section:
```python
network = NetworkStack(
    app,
    f"network-{cfg.app_name}-{cfg.env_name}",
    cfg=cfg,
    env=cdk_env,
)
# Phase 3 consumers: network.vpc, network.ecs_task_sg
```

**Context validation pattern** (lines 13-15 — fail fast on missing context):
```python
env_name = app.node.try_get_context("env")
if env_name not in {"dev", "prod"}:
    raise ValueError("Pass the environment: -c env=dev or -c env=prod")
```
Trust VPC context validation lives inside `NetworkStack.__init__`, not `app.py` — keeps app.py clean.

---

### `infra/access_iq_infra/settings.py` (extend EnvConfig)

**Analog:** `infra/access_iq_infra/settings.py` itself (lines 1-48)

**Frozen dataclass pattern** (lines 7-16):
```python
@dataclass(frozen=True)
class EnvConfig:
    app_name: str
    env_name: str
    user_name: str
    account_id: str
    region: str
    s3: dict[str, Any]
    iam: dict[str, Any]
    tags: dict[str, str]
```
Add `vpc: dict[str, Any]` field after `iam`, before `tags` (maintains alphabetical grouping of dict fields).

**load_env_config construction pattern** (lines 37-46 — `dict(raw.get("key", {}))` for optional dict fields):
```python
        return EnvConfig(
            app_name=str(raw["app_name"]),
            env_name=str(raw["env_name"]),
            user_name=str(raw["user_name"]),
            account_id=str(raw["account_id"]),
            region=str(raw["region"]),
            s3=dict(raw.get("s3", {})),
            iam=dict(raw.get("iam", {})),
            tags=dict(raw.get("tags", {})),
        )
```
Add `vpc=dict(raw.get("vpc", {})),` after `iam=` line. The `get(..., {})` default means existing tests that construct `EnvConfig` without `vpc=` will break — all call sites must add `vpc={}` or `vpc={...}`.

---

### `infra/access_iq_infra/stacks/__init__.py` (add NetworkStack export)

**Analog:** `infra/access_iq_infra/stacks/__init__.py` itself (lines 1-7)

**Export pattern** (lines 1-7 — bare import + `__all__` list, alphabetical):
```python
from access_iq_infra.stacks.catalog import CatalogStack
from access_iq_infra.stacks.ecr import EcrStack
from access_iq_infra.stacks.iam import IngestionRoleStack
from access_iq_infra.stacks.lake import LakeStack
from access_iq_infra.stacks.secrets import SecretsStack

__all__ = ["CatalogStack", "EcrStack", "IngestionRoleStack", "LakeStack", "SecretsStack"]
```
Add `from access_iq_infra.stacks.network import NetworkStack` (alphabetical: after `lake`, before `secrets`). Add `"NetworkStack"` to `__all__` in same position.

---

### `tests/unit/test_network_stack.py` (new test file)

**Analog:** `tests/unit/test_lake_stack.py` (lines 1-90)

**File header + importorskip pattern** (lines 1-10):
```python
from __future__ import annotations

import pytest

aws_cdk = pytest.importorskip("aws_cdk")
from aws_cdk import App  # noqa: E402
from aws_cdk.assertions import Match, Template  # noqa: E402

from access_iq_infra.settings import EnvConfig  # noqa: E402
from access_iq_infra.stacks.network import NetworkStack  # noqa: E402
```

**`_cfg()` fixture pattern** (lake.py lines 13-23 — inline `EnvConfig` construction, no file I/O):
```python
def _cfg() -> EnvConfig:
    return EnvConfig(
        app_name="access-iq",
        env_name="dev",
        user_name="AWSReservedSSO_test/test",
        account_id="111111111111",
        region="eu-west-2",
        s3={},
        iam={"external_bucket": "x", "trust_account_id": "999999999999"},
        vpc={
            "platform_cidr": "10.10.0.0/16",
            "trust_cidr": "10.0.0.0/16",
            "max_azs": 2,
            "nat_gateways": 1,
        },
        tags={},
    )
```

**`_template()` factory pattern** (lake.py lines 26-29 — App → Stack → Template.from_stack):
```python
def _template() -> Template:
    app = App(context={
        "trust_vpc_id": "vpc-test123",
        "trust_route_table_ids": "rtb-test1,rtb-test2",
    })
    stack = NetworkStack(app, "NetworkStack", cfg=_cfg())
    return Template.from_stack(stack)
```
Note: `App(context={...})` not `App()` — Trust context params required at synth.

**Assertion patterns** (lake.py lines 33-89):
```python
# resource_count_is
tpl.resource_count_is("AWS::EC2::Subnet", 4)
tpl.resource_count_is("AWS::EC2::NatGateway", 1)
tpl.resource_count_is("AWS::EC2::VPCEndpoint", 6)  # 1 gateway + 5 interface

# has_resource_properties
tpl.has_resource_properties("AWS::EC2::VPC", {"CidrBlock": "10.10.0.0/16"})
tpl.has_resource_properties(
    "AWS::EC2::VPCEndpoint",
    {"VpcEndpointType": "Gateway", "ServiceName": Match.string_like_regexp("s3")},
)

# find_resources for custom assertion logic (see lake.py lines 66-84)
sgs = tpl.find_resources("AWS::EC2::SecurityGroup")
```

**Parametrize pattern** (lake.py lines 32, 40 — `@pytest.mark.parametrize` for dev/prod where removal policy differs):
```python
# NetworkStack is DESTROY in all envs — no parametrize needed for removal policy.
# Single _template() factory is sufficient.
```

---

### `infra/config/dev.json` and `infra/config/prod.json` (add vpc section)

**Analog:** `infra/config/dev.json` itself (lines 1-19)

**Existing structure** (dev.json lines 1-19):
```json
{
  "app_name": "access-iq",
  "env_name": "dev",
  "account_id": "222308823356",
  "user_name": "AWSReservedSSO_CHI-Engineer_56b619fe880e8582/chia",
  "region": "eu-west-2",
  "tags": { ... },
  "s3": { "removal_policy": "DESTROY" },
  "iam": { "external_bucket": "northshire-trust-external-exports" }
}
```

**Addition pattern** — add `vpc` object and `trust_account_id` into `iam`:
```json
{
  "vpc": {
    "platform_cidr": "10.10.0.0/16",
    "trust_cidr": "10.0.0.0/16",
    "max_azs": 2,
    "nat_gateways": 1
  },
  "iam": {
    "external_bucket": "northshire-trust-external-exports",
    "trust_account_id": "<northshire_trust_account_id>"
  }
}
```
`trust_account_id` value is a placeholder — must be filled with the real Northshire Trust AWS account ID before `cdk deploy`. Trust VPC ID and route table IDs are NOT stored here (CDK context params per D-06).

---

## Shared Patterns

### Stack Constructor Keyword-Only `cfg` Prop
**Source:** `infra/access_iq_infra/stacks/lake.py` lines 38-46
**Apply to:** `network.py`
```python
def __init__(
    self,
    scope: Construct,
    construct_id: str,
    *,
    cfg: EnvConfig,
    **kwargs: Any,
) -> None:
    super().__init__(scope, construct_id, **kwargs)
```

### `from __future__ import annotations`
**Source:** `infra/access_iq_infra/stacks/lake.py` line 11, `tests/unit/test_lake_stack.py` line 1
**Apply to:** `network.py`, `test_network_stack.py`
Every new infra file opens with this line — enables PEP 563 postponed evaluation for type hints.

### `f"{cfg.app_name}-{cfg.env_name}-<suffix>"` Resource Naming
**Source:** `infra/access_iq_infra/stacks/lake.py` lines 63, 66
**Apply to:** `network.py` (all named AWS resources: VPC, security groups)
```python
vpc_name=f"{cfg.app_name}-{cfg.env_name}-platform"
security_group_name=f"{cfg.app_name}-{cfg.env_name}-ecs-task"
```

### Stack ID Naming in app.py
**Source:** `infra/app.py` lines 25, 32, 41, 45, 56
**Apply to:** `app.py` (NetworkStack instantiation)
Pattern: `f"<role>-{cfg.app_name}-{cfg.env_name}"` e.g. `"network-access-iq-dev"`.

### `pytest.importorskip("aws_cdk")` Guard
**Source:** `tests/unit/test_lake_stack.py` line 5
**Apply to:** `tests/unit/test_network_stack.py`
```python
aws_cdk = pytest.importorskip("aws_cdk")
```
Skips test module if `aws_cdk` not installed — keeps CI from hard-failing in environments without CDK.

### `# noqa: E402` on post-importorskip imports
**Source:** `tests/unit/test_lake_stack.py` lines 6-10
**Apply to:** `tests/unit/test_network_stack.py`
All imports after `pytest.importorskip` are module-level but post-skip-guard — ruff/flake8 E402 suppressed inline.

### `dict(raw.get("key", {}))` for Optional Config Sections
**Source:** `infra/access_iq_infra/settings.py` lines 43-45
**Apply to:** `settings.py` (new `vpc` field in `load_env_config`)
```python
vpc=dict(raw.get("vpc", {})),
```

---

## Call-Site Updates Required (Not New Files)

When `EnvConfig` gains the `vpc` field, all existing `EnvConfig(...)` call sites must add `vpc={}` (or a populated dict). Known call sites:

| File | Line | Action |
|------|------|--------|
| `tests/unit/test_lake_stack.py` | 14-23 | Add `vpc={}` to `_cfg()` |
| `tests/unit/test_ecr_stack.py` | (check) | Add `vpc={}` to `_cfg()` |
| `tests/unit/test_secrets_stack.py` | (check) | Add `vpc={}` to `_cfg()` |
| `tests/unit/test_iam_stack.py` | (check) | Add `vpc={}` to `_cfg()` |
| `tests/unit/test_app_synth.py` | (check) | Add `vpc` context + field |

---

## No Analog Found

None — all 7 files have direct analogs in the codebase.

---

## Metadata

**Analog search scope:** `infra/access_iq_infra/stacks/`, `infra/app.py`, `infra/access_iq_infra/settings.py`, `infra/config/`, `tests/unit/`
**Files read:** 7
**Pattern extraction date:** 2026-05-19
