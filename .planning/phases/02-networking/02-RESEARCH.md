# Phase 2: Networking - Research

**Researched:** 2026-05-19
**Domain:** AWS CDK VPC, cross-account VPC peering, VPC endpoints, security groups
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Use CDK `AwsCustomResource` to automate peering acceptance on the Trust side. Platform CDK assumes a cross-account role in the Trust account to accept the peering connection, update Trust route tables, and enable DNS resolution.
- **D-02:** A peering-accepter IAM role must be created in the Trust account (Northshire simulator repo). Scoped to `ec2:AcceptVpcPeeringConnection`, `ec2:CreateRoute`, `ec2:ModifyVpcPeeringConnectionOptions`. This is a prerequisite — researcher should flag it.
- **D-03:** Cross-VPC DNS resolution enabled via `AwsCustomResource` calling `ModifyVpcPeeringConnectionOptions` on both sides. ECS tasks resolve Trust RDS by hostname, not IP.
- **D-04:** Single ephemeral `NetworkStack` containing all networking resources: VPC, subnets, NAT gateway, peering connection + acceptance, route tables, security groups, and all VPC endpoints. No stateful/stateless split for networking — everything is ephemeral per D6.
- **D-05:** Trust-side peering acceptance (`AwsCustomResource`) lives in the same `NetworkStack`. One stack creates, peers, and configures everything.
- **D-06:** Trust VPC details (vpc_id, route_table_ids) passed as CDK context params (`-c trust_vpc_id=xxx`), not config file values. Trust stack is ephemeral so IDs change every session. `make up` (Phase 9) will orchestrate deploy order; during development, manual `-c` flags or a helper script suffice.
- **D-07:** Full endpoint suite deployed in the NetworkStack: S3 gateway endpoint (free) + interface endpoints for Secrets Manager, KMS, ECR API, ECR DKR, and CloudWatch Logs. Stack is ephemeral so cost is pennies per session.

### Claude's Discretion
- **Interface endpoint AZ placement:** Deploy in both AZs (both private subnets). Cost delta negligible on ephemeral stacks; avoids constraining ECS task placement to a single AZ.

### Deferred Ideas (OUT OF SCOPE)
None — discussion stayed within phase scope.
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| REQ-NET-01 | Platform VPC with public + private subnets across 2 AZs, NAT gateway (single-AZ in dev) | `ec2.Vpc` with `max_azs=2`, `nat_gateways=1`, `subnet_configuration` with PUBLIC + PRIVATE_WITH_EGRESS |
| REQ-NET-02 | VPC peering Platform ↔ Trust with route table updates both sides, security groups scoped to required ports/CIDRs | `ec2.CfnVPCPeeringConnection` + `AwsCustomResource` for Trust-side routes + `ModifyVpcPeeringConnectionOptions` |
| REQ-NET-03 (endpoints portion) | S3 gateway endpoint keeps Bronze writes off NAT; Secrets Manager + KMS interface endpoints for ECS `valueFrom` | `GatewayVpcEndpointAwsService.S3` + `InterfaceVpcEndpointAwsService.*` for full suite (D-07) |
</phase_requirements>

---

## Summary

Phase 2 builds the complete networking layer as a single ephemeral `NetworkStack`. The core challenge is cross-account VPC peering: creating the peering connection from the Platform account while automating Trust-side acceptance, route table updates, and DNS resolution — all without manual console steps and all destroy-able on `cdk destroy`.

Two distinct CDK mechanisms handle the two halves of peering: `CfnVPCPeeringConnection` with `peer_role_arn` handles peering creation + acceptance atomically within CloudFormation (no AwsCustomResource needed for acceptance itself). `AwsCustomResource` is needed for the Trust-side operations CloudFormation cannot do: adding routes to Trust route tables (`ec2:CreateRoute`) and enabling DNS resolution on the Trust side (`ec2:ModifyVpcPeeringConnectionOptions`). Both custom resources assume a cross-account role in the Northshire Trust account.

The VPC endpoint suite and security groups are straightforward CDK L2 constructs. The most significant pitfall is dependency ordering: the `AwsCustomResource` resources must depend on the peering connection reaching `ACTIVE`, and the peering connection depends on the Trust VPC ID being available at synth time (via CDK context, not config files).

**Primary recommendation:** Use `CfnVPCPeeringConnection(peer_role_arn=...)` for atomic cross-account creation+acceptance, then two `AwsCustomResource` constructs (with `add_dependency`) for Trust route table + DNS config. Pass Trust VPC details exclusively via CDK context params.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Platform VPC + subnets + NAT | Platform CDK (NetworkStack) | — | All ephemeral; single stack owns lifecycle |
| VPC peering connection request | Platform CDK (NetworkStack) | — | Requester is Platform account |
| Trust-side peering acceptance | Platform CDK via cross-account AwsCustomResource | Trust IAM role (prerequisite) | D-01: automated, no manual Trust console steps |
| Trust-side route table update | Platform CDK via cross-account AwsCustomResource | Trust IAM role | CreateRoute into Trust route tables |
| DNS resolution (both sides) | Platform CDK via AwsCustomResource (both accounts) | — | D-03: `ModifyVpcPeeringConnectionOptions` required on both sides |
| Platform route tables | Platform CDK (CfnRoute L1) | — | CDK Vpc L2 does not expose peering routes |
| Security groups | Platform CDK (NetworkStack) | — | Deny-by-default; ingress rules scoped to peer CIDR + ports |
| VPC endpoints (S3 gateway + interface) | Platform CDK (NetworkStack) | — | D-07: full suite in single ephemeral stack |

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| aws-cdk-lib | 2.236.0 | All CDK constructs (ec2, custom_resources) | Already locked in infra/pyproject.toml |
| constructs | (bundled) | Base construct tree | Required by CDK |

[VERIFIED: infra/pyproject.toml]

### CDK Modules Used

| Module | Key Classes | Notes |
|--------|------------|-------|
| `aws_cdk.aws_ec2` | `Vpc`, `SubnetConfiguration`, `SubnetType`, `SecurityGroup`, `Peer`, `Port`, `CfnVPCPeeringConnection`, `CfnRoute`, `GatewayVpcEndpoint`, `InterfaceVpcEndpoint`, `GatewayVpcEndpointAwsService`, `InterfaceVpcEndpointAwsService` | All L1/L2 networking |
| `aws_cdk.custom_resources` | `AwsCustomResource`, `AwsCustomResourcePolicy`, `AwsSdkCall`, `PhysicalResourceId` | Trust-side automation |
| `aws_cdk.aws_iam` | `PolicyStatement`, `Effect` | Custom resource Lambda policy |
| `aws_cdk` | `Stack`, `RemovalPolicy`, `CfnOutput` | Stack base + outputs |

[VERIFIED: Context7 /websites/aws_amazon_cdk_api_v2_python]

### No New Packages Required

All constructs needed are in `aws-cdk-lib` which is already installed. No additional pip packages.

---

## Architecture Patterns

### System Architecture Diagram

```
CDK App (Platform account)
│
├── [STATEFUL — existing]
│   ├── LakeStack          (S3, KMS)
│   ├── SecretsStack
│   ├── CatalogStack
│   └── EcrStack
│
└── [STATELESS — Phase 2 adds]
    └── NetworkStack
        │
        ├── ec2.Vpc  (10.10.0.0/16, 2 AZ)
        │   ├── PublicSubnet-AZ1  (10.10.0.0/24)
        │   ├── PublicSubnet-AZ2  (10.10.1.0/24)
        │   ├── PrivateSubnet-AZ1 (10.10.2.0/24)  ─── NAT → IGW
        │   └── PrivateSubnet-AZ2 (10.10.3.0/24)  ─── NAT → IGW
        │
        ├── CfnVPCPeeringConnection
        │   └── peer_role_arn → Trust IAM role (auto-accepts in Trust account)
        │
        ├── Platform CfnRoute (private subnets → 10.0.0.0/16 via peering)
        │
        ├── AwsCustomResource: TrustRouteUpdate
        │   └── assumes trust-peering-accepter-role
        │   └── ec2:CreateRoute on Trust route tables
        │
        ├── AwsCustomResource: DnsResolution
        │   └── assumes trust-peering-accepter-role
        │   └── ec2:ModifyVpcPeeringConnectionOptions (both sides)
        │
        ├── SecurityGroup: EgressSg (ECS tasks, deny all by default)
        │   ├── egress 5432 → 10.0.0.0/16  (Trust RDS)
        │   ├── egress 22   → 10.0.0.0/16  (Trust SFTP)
        │   └── egress 443  → 0.0.0.0/0    (AWS service endpoints)
        │
        ├── GatewayVpcEndpoint: S3
        └── InterfaceVpcEndpoints: SecretsManager, KMS, ECR_API, ECR_DOCKER, CloudWatch_Logs
```

### Recommended Project Structure

```
infra/access_iq_infra/
├── stacks/
│   ├── network.py          # NetworkStack (new — this phase)
│   ├── lake.py             # existing
│   ├── secrets.py          # existing
│   ├── catalog.py          # existing
│   ├── ecr.py              # existing
│   └── iam.py              # existing
├── settings.py             # EnvConfig — extend vpc section
└── app.py                  # wire NetworkStack after stateful stacks
```

### Pattern 1: VPC with Controlled Subnet Layout

**What:** Two public + two private subnets across 2 AZs, single NAT gateway. CIDR `/16` split into `/24` per subnet.

**When to use:** All environments (dev and prod identical for this portfolio; single NAT is acceptable per REQ-NET-01).

```python
# Source: https://docs.aws.amazon.com/cdk/api/v2/python/aws_cdk.aws_ec2/Vpc.html
from aws_cdk import aws_ec2 as ec2

vpc = ec2.Vpc(
    self,
    "PlatformVpc",
    vpc_name=f"{cfg.app_name}-{cfg.env_name}-platform",
    ip_addresses=ec2.IpAddresses.cidr("10.10.0.0/16"),
    max_azs=2,
    nat_gateways=1,
    subnet_configuration=[
        ec2.SubnetConfiguration(
            name="public",
            subnet_type=ec2.SubnetType.PUBLIC,
            cidr_mask=24,
        ),
        ec2.SubnetConfiguration(
            name="private",
            subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS,
            cidr_mask=24,
        ),
    ],
)
```

[VERIFIED: Context7 /websites/aws_amazon_cdk_api_v2_python + WebSearch]

### Pattern 2: Cross-Account VPC Peering via peer_role_arn

**What:** `CfnVPCPeeringConnection` with `peer_role_arn` triggers CloudFormation to assume the Trust-side role and auto-accept the peering. This is the correct mechanism — no separate `AwsCustomResource` for acceptance is needed.

**When to use:** When requester and accepter are in different AWS accounts in the same region.

**Key insight:** `CfnVPCPeeringConnection.peer_role_arn` was added specifically for cross-account automation. When provided, CloudFormation on the requester side assumes that role to accept the connection. D-01 describing "AwsCustomResource for acceptance" is technically achievable but `peer_role_arn` is simpler and more reliable for acceptance only. `AwsCustomResource` is still needed for Trust route tables and DNS.

```python
# Source: https://docs.aws.amazon.com/cdk/api/v2/python/aws_cdk.aws_ec2/CfnVPCPeeringConnection.html
from aws_cdk import aws_ec2 as ec2

trust_vpc_id = self.node.try_get_context("trust_vpc_id")
trust_account_id = cfg.iam["trust_account_id"]  # stored in infra/config/{env}.json
peering_role_arn = f"arn:aws:iam::{trust_account_id}:role/access-iq-peering-accepter"

peering = ec2.CfnVPCPeeringConnection(
    self,
    "PlatformToTrustPeering",
    vpc_id=vpc.vpc_id,
    peer_vpc_id=trust_vpc_id,
    peer_owner_id=trust_account_id,
    peer_region=cfg.region,
    peer_role_arn=peering_role_arn,
)
```

[VERIFIED: Context7 /websites/aws_amazon_cdk_api_v2_python; CITED: https://docs.aws.amazon.com/cdk/api/v2/python/aws_cdk.aws_ec2/CfnVPCPeeringConnection.html]

### Pattern 3: Platform-Side Route Tables (L1 CfnRoute)

**What:** The CDK L2 `Vpc` construct does not expose a method to add peering routes. Use `CfnRoute` against each private subnet's route table.

**When to use:** After peering connection is created; must `add_dependency(peering)`.

```python
# Source: https://docs.aws.amazon.com/cdk/api/v2/python/aws_cdk.aws_ec2/CfnRoute.html
from aws_cdk import aws_ec2 as ec2

for i, subnet in enumerate(vpc.private_subnets):
    route = ec2.CfnRoute(
        self,
        f"TrustRoute{i}",
        route_table_id=subnet.route_table.route_table_id,
        destination_cidr_block="10.0.0.0/16",
        vpc_peering_connection_id=peering.ref,
    )
    route.add_dependency(peering)
```

[VERIFIED: Context7 /websites/aws_amazon_cdk_api_v2_python]

### Pattern 4: Trust-Side Route Update via AwsCustomResource

**What:** After peering is ACTIVE, call `ec2:CreateRoute` in the Trust account via cross-account `AwsCustomResource`. One call per Trust route table ID (passed as CDK context).

**When to use:** Trust-side route tables can't be managed from Platform CDK directly without cross-account SDK calls.

```python
# Source: https://docs.aws.amazon.com/cdk/api/v2/python/aws_cdk.custom_resources/AwsCustomResource.html
from aws_cdk import aws_iam as iam
from aws_cdk.custom_resources import (
    AwsCustomResource,
    AwsCustomResourcePolicy,
    AwsSdkCall,
    PhysicalResourceId,
)

trust_rtb_ids: list[str] = self.node.try_get_context("trust_route_table_ids").split(",")
peering_accepter_role_arn = f"arn:aws:iam::{trust_account_id}:role/access-iq-peering-accepter"

for i, rtb_id in enumerate(trust_rtb_ids):
    cr = AwsCustomResource(
        self,
        f"TrustRoute{i}",
        on_create=AwsSdkCall(
            assumed_role_arn=peering_accepter_role_arn,
            service="EC2",
            action="createRoute",
            parameters={
                "RouteTableId": rtb_id,
                "DestinationCidrBlock": "10.10.0.0/16",
                "VpcPeeringConnectionId": peering.ref,
            },
            physical_resource_id=PhysicalResourceId.of(f"trust-route-{rtb_id}"),
        ),
        on_delete=AwsSdkCall(
            assumed_role_arn=peering_accepter_role_arn,
            service="EC2",
            action="deleteRoute",
            parameters={
                "RouteTableId": rtb_id,
                "DestinationCidrBlock": "10.10.0.0/16",
            },
            physical_resource_id=PhysicalResourceId.of(f"trust-route-{rtb_id}`"),
        ),
        policy=AwsCustomResourcePolicy.from_statements([
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=["sts:AssumeRole"],
                resources=[peering_accepter_role_arn],
            )
        ]),
        install_latest_aws_sdk=False,  # avoid Lambda internet dependency
    )
    cr.add_dependency(peering)
```

[VERIFIED: Context7 /websites/aws_amazon_cdk_api_v2_python; CITED: https://docs.aws.amazon.com/cdk/api/v2/python/aws_cdk.custom_resources/AwsCustomResource.html]

### Pattern 5: DNS Resolution via AwsCustomResource

**What:** `ModifyVpcPeeringConnectionOptions` must be called on the peering connection to enable `AllowDnsResolutionFromRemoteVpc` on both sides. CDK L2 does not expose this. Two AwsCustomResource calls (one per side), or one call with both options set.

```python
dns_cr = AwsCustomResource(
    self,
    "PeeringDnsResolution",
    on_create=AwsSdkCall(
        service="EC2",
        action="modifyVpcPeeringConnectionOptions",
        parameters={
            "VpcPeeringConnectionId": peering.ref,
            "RequesterPeeringConnectionOptions": {
                "AllowDnsResolutionFromRemoteVpc": True,
            },
        },
        physical_resource_id=PhysicalResourceId.of("peering-dns-requester"),
    ),
    policy=AwsCustomResourcePolicy.from_sdk_calls(resources=["*"]),
    install_latest_aws_sdk=False,
)
dns_cr.add_dependency(peering)

# Trust-side DNS: separate call assuming Trust role
dns_trust_cr = AwsCustomResource(
    self,
    "PeeringDnsTrust",
    on_create=AwsSdkCall(
        assumed_role_arn=peering_accepter_role_arn,
        service="EC2",
        action="modifyVpcPeeringConnectionOptions",
        parameters={
            "VpcPeeringConnectionId": peering.ref,
            "AccepterPeeringConnectionOptions": {
                "AllowDnsResolutionFromRemoteVpc": True,
            },
        },
        physical_resource_id=PhysicalResourceId.of("peering-dns-accepter"),
    ),
    policy=AwsCustomResourcePolicy.from_statements([
        iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=["sts:AssumeRole"],
            resources=[peering_accepter_role_arn],
        )
    ]),
    install_latest_aws_sdk=False,
)
dns_trust_cr.add_dependency(peering)
```

[VERIFIED: Context7 /websites/aws_amazon_cdk_api_v2_python; ASSUMED: `modifyVpcPeeringConnectionOptions` parameter naming — verify exact camelCase against boto3 docs before execution]

### Pattern 6: VPC Endpoint Suite

**What:** S3 gateway endpoint (free, routes to private subnets) + five interface endpoints with private DNS.

```python
# Source: https://docs.aws.amazon.com/cdk/api/v2/python/aws_cdk.aws_ec2/README.html
from aws_cdk import aws_ec2 as ec2

# S3 gateway — free, attach to private subnets
vpc.add_gateway_endpoint(
    "S3Endpoint",
    service=ec2.GatewayVpcEndpointAwsService.S3,
    subnets=[ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS)],
)

# Interface endpoints — one security group per endpoint or shared
endpoint_sg = ec2.SecurityGroup(self, "EndpointSg", vpc=vpc, allow_all_outbound=False)
endpoint_sg.add_ingress_rule(ec2.Peer.ipv4("10.10.0.0/16"), ec2.Port.tcp(443))

for endpoint_id, service in [
    ("SecretsManagerEndpoint", ec2.InterfaceVpcEndpointAwsService.SECRETS_MANAGER),
    ("KmsEndpoint", ec2.InterfaceVpcEndpointAwsService.KMS),
    ("EcrApiEndpoint", ec2.InterfaceVpcEndpointAwsService.ECR),
    ("EcrDkrEndpoint", ec2.InterfaceVpcEndpointAwsService.ECR_DOCKER),
    ("CloudWatchLogsEndpoint", ec2.InterfaceVpcEndpointAwsService.CLOUDWATCH_LOGS),
]:
    ec2.InterfaceVpcEndpoint(
        self,
        endpoint_id,
        vpc=vpc,
        service=service,
        subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
        security_groups=[endpoint_sg],
        private_dns_enabled=True,
    )
```

[VERIFIED: Context7 /websites/aws_amazon_cdk_api_v2_python]

### Pattern 7: Security Groups (Deny-by-Default Egress)

**What:** ECS tasks get a security group with `allow_all_outbound=False`. Egress rules added explicitly for Trust RDS (5432), Trust SFTP (22), and HTTPS (443) for AWS service endpoints.

```python
from aws_cdk import aws_ec2 as ec2

ecs_sg = ec2.SecurityGroup(
    self,
    "EcsTaskSg",
    vpc=vpc,
    security_group_name=f"{cfg.app_name}-{cfg.env_name}-ecs-task",
    description="ECS ingestion tasks — deny-by-default egress",
    allow_all_outbound=False,  # critical: disables CDK's default 0.0.0.0/0 egress
)

trust_cidr = ec2.Peer.ipv4("10.0.0.0/16")
ecs_sg.add_egress_rule(trust_cidr, ec2.Port.tcp(5432), "Trust RDS PostgreSQL")
ecs_sg.add_egress_rule(trust_cidr, ec2.Port.tcp(22), "Trust SFTP")
ecs_sg.add_egress_rule(ec2.Peer.ipv4("10.10.0.0/16"), ec2.Port.tcp(443), "VPC interface endpoints")
```

[VERIFIED: Context7 /websites/aws_amazon_cdk_api_v2_python]

### Pattern 8: CDK Context Param Extraction

**What:** Trust VPC details are runtime values (Trust stack is ephemeral). Pass as CDK context; fail fast if missing.

```python
# In NetworkStack.__init__ or app.py
trust_vpc_id: str | None = self.node.try_get_context("trust_vpc_id")
trust_rtb_ids_raw: str | None = self.node.try_get_context("trust_route_table_ids")

if trust_vpc_id is None or trust_rtb_ids_raw is None:
    raise ValueError(
        "Trust VPC context required. Pass: "
        "-c trust_vpc_id=vpc-xxx "
        "-c trust_route_table_ids=rtb-aaa,rtb-bbb"
    )
trust_route_table_ids = trust_rtb_ids_raw.split(",")
```

[ASSUMED: comma-separated list is the idiomatic CDK context pattern for multi-value params — no official doc for this specific convention]

### Anti-Patterns to Avoid

- **Storing Trust VPC ID in config file:** Trust stack is ephemeral — IDs change every session. Context params only.
- **Using `allow_all_outbound=True` (CDK default):** Creates 0.0.0.0/0 egress by default. Always set `allow_all_outbound=False` on ECS task SGs.
- **Setting `install_latest_aws_sdk=True` on AwsCustomResource:** Requires Lambda internet access; will fail in private subnets without NAT. Use `False`.
- **Placing AwsCustomResource Lambda in VPC:** The custom resource Lambda does NOT need to be in a VPC to make cross-account SDK calls. Placing it in a VPC with `install_latest_aws_sdk=True` and no NAT causes timeouts.
- **Using `AwsCustomResourcePolicy.from_sdk_calls` for cross-account:** This auto-generates IAM policy from the SDK call. For cross-account calls, the policy must explicitly allow `sts:AssumeRole` on the target role ARN — use `from_statements` instead.
- **Not calling `add_dependency` on CfnRoute / AwsCustomResource:** CloudFormation may try to create routes before the peering is ACTIVE, causing a `InvalidVpcPeeringConnectionID` error.
- **Using VPC L2 `select_subnets` for route table IDs:** L2 subnets expose `.route_table.route_table_id` but this is the CDK-generated L1 ref. Works for Platform side; Trust route tables must come from context.
- **Skipping `on_delete` in AwsCustomResource:** If no `on_delete` is provided for the Trust route creation, `cdk destroy` will leave orphaned routes in the Trust route tables, blocking future peering attempts until manually cleaned.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Cross-account SDK call automation | Lambda function with boto3 cross-account logic | `AwsCustomResource` from `aws_cdk.custom_resources` | Managed singleton Lambda, CloudFormation lifecycle, retry/rollback included |
| Route table management | Manual `CfnRouteTable` + `CfnSubnetRouteTableAssociation` | Let `ec2.Vpc` L2 manage route tables; use `CfnRoute` L1 only to add peering routes | L2 Vpc handles IGW/NAT route wiring; only peering routes need L1 override |
| Interface endpoint ENI placement | Custom subnet selection logic | `ec2.SubnetSelection(subnet_type=SubnetType.PRIVATE_WITH_EGRESS)` | CDK places ENIs correctly in all matching subnets |
| Security group rule deduplication | Manual tracking of rule conflicts | CDK `connections.allow_to` / `add_ingress_rule` | CDK deduplicates rules automatically |

---

## Cross-Account IAM Role (Prerequisite in Trust Repo)

**D-02 Hard Prerequisite:** Before deploying `NetworkStack`, this role must exist in the Trust (Northshire) account.

### Minimum Permissions

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ec2:AcceptVpcPeeringConnection"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "ec2:CreateRoute",
        "ec2:DeleteRoute"
      ],
      "Resource": "arn:aws:ec2:<region>:<trust_account_id>:route-table/*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "ec2:ModifyVpcPeeringConnectionOptions"
      ],
      "Resource": "*"
    }
  ]
}
```

**Trust relationship (role must be assumable by Platform account):**

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "AWS": "arn:aws:iam::<platform_account_id>:root"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
```

**Role name convention:** `access-iq-peering-accepter` (matches what `CfnVPCPeeringConnection.peer_role_arn` will reference via the stable ARN pattern in `infra/config/{env}.json`).

**Note on peer_role_arn vs AwsCustomResource for acceptance:** `CfnVPCPeeringConnection` with `peer_role_arn` handles acceptance automatically within CloudFormation. The Trust IAM role needs `ec2:AcceptVpcPeeringConnection` for this CloudFormation-native path, and also `ec2:CreateRoute` + `ec2:ModifyVpcPeeringConnectionOptions` for the subsequent `AwsCustomResource` calls. All three actions can be on the same role.

[VERIFIED: CITED: https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/peer-with-vpc-in-another-account.html; CITED: https://docs.aws.amazon.com/cdk/api/v2/python/aws_cdk.aws_ec2/CfnVPCPeeringConnection.html]

---

## Config File Changes Required

Both `infra/config/dev.json` and `infra/config/prod.json` need a `vpc` section added for static values, and `iam.trust_account_id` for the peering role ARN construction:

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

`EnvConfig` dataclass in `settings.py` needs a `vpc: dict[str, Any]` field added alongside existing `s3` and `iam` fields.

**Trust VPC details NOT in config files** — passed only as CDK context params per D-06.

---

## Common Pitfalls

### Pitfall 1: Peering ACTIVE Race Condition
**What goes wrong:** `CfnRoute` or `AwsCustomResource` for route creation is executed before the peering connection reaches `ACTIVE` state. Error: `InvalidVpcPeeringConnectionID.NotFound` or `InvalidState`.
**Why it happens:** CloudFormation creates resources in dependency order; if `add_dependency` is not called, routes may be attempted immediately after the peering resource is created (before AWS transitions it to ACTIVE).
**How to avoid:** Call `route.add_dependency(peering)` and `trust_route_cr.add_dependency(peering)` on every downstream resource.
**Warning signs:** CloudFormation stack stuck in `CREATE_IN_PROGRESS` on Route resources; Lambda logs show `InvalidVpcPeeringConnectionID`.

### Pitfall 2: AwsCustomResource Lambda in VPC with install_latest_aws_sdk=True
**What goes wrong:** Custom resource Lambda times out during deployment.
**Why it happens:** `install_latest_aws_sdk=True` (the default) downloads the AWS SDK from npmjs.com at Lambda cold start. Inside a private VPC with no NAT (or before NAT is up), this fails.
**How to avoid:** Set `install_latest_aws_sdk=False` on all `AwsCustomResource` instances. The built-in Lambda SDK is sufficient for the EC2 API calls needed.
**Warning signs:** Lambda timeout in CloudWatch during stack creation with no apparent error in the custom resource logic.

### Pitfall 3: Missing on_delete Causes Orphaned Trust Routes
**What goes wrong:** `cdk destroy` succeeds but Trust route tables retain the Platform CIDR route. Next session's peering attempt may fail due to conflicting route entries.
**Why it happens:** `AwsCustomResource` with only `on_create` does not clean up on stack destroy.
**How to avoid:** Always define `on_delete=AwsSdkCall(action="deleteRoute", ...)` for Trust route creation custom resources.
**Warning signs:** Subsequent peering attempts fail with `RouteAlreadyExists`.

### Pitfall 4: CDK Context Params Not Validated at Synth Time
**What goes wrong:** `cdk deploy` starts successfully, NetworkStack begins creating, then fails mid-deploy when a resource tries to reference `None`.
**Why it happens:** `try_get_context` returns `None` silently if the `-c` flag is missing.
**How to avoid:** Validate all required context params at the top of `NetworkStack.__init__` with explicit `ValueError` if any are missing. Fail fast at synth, not at deploy.
**Warning signs:** Unexplained `None` values in CloudFormation resource properties.

### Pitfall 5: Security Group Default Egress Overrides
**What goes wrong:** ECS tasks can reach any destination despite intention to lock down egress.
**Why it happens:** CDK's `SecurityGroup` constructor defaults `allow_all_outbound=True`, which adds a `0.0.0.0/0 ALL` egress rule. This rule cannot be removed by adding specific rules — it coexists.
**How to avoid:** Set `allow_all_outbound=False` explicitly on ECS task security groups. Then add explicit egress rules for required ports.
**Warning signs:** Security group in console shows a `0.0.0.0/0 ALL` egress rule alongside specific rules.

### Pitfall 6: Interface Endpoint Private DNS + External DNS Conflict
**What goes wrong:** ECS tasks cannot resolve AWS service hostnames after interface endpoints are deployed.
**Why it happens:** Interface endpoints with `private_dns_enabled=True` override DNS for the service hostname within the VPC. If the VPC DHCP options do not have `enableDnsSupport=true` and `enableDnsHostnames=true`, private DNS resolution fails.
**How to avoid:** The CDK `ec2.Vpc` L2 construct sets both DHCP options by default. Do not override them. Verify post-deploy with `aws ec2 describe-vpc-attribute`.
**Warning signs:** Intermittent DNS resolution failures for `secretsmanager.eu-west-2.amazonaws.com` from within ECS tasks.

### Pitfall 7: Trust Route Table IDs via Context — Comma Parsing
**What goes wrong:** Only the first route table is updated if context parsing is wrong.
**Why it happens:** `try_get_context("trust_route_table_ids")` returns a string. Splitting on `,` with accidental whitespace (e.g., `"rtb-aaa, rtb-bbb"`) produces IDs with leading spaces.
**How to avoid:** Strip whitespace: `[x.strip() for x in raw.split(",")]`.
**Warning signs:** Only one Trust subnet can reach Platform; the other silently black-holes traffic.

---

## Code Examples

### NetworkStack Constructor Signature

```python
# Follows existing stack patterns in infra/access_iq_infra/stacks/
from __future__ import annotations
from typing import Any
from aws_cdk import RemovalPolicy, Stack
from aws_cdk import aws_ec2 as ec2
from constructs import Construct
from access_iq_infra.settings import EnvConfig


class NetworkStack(Stack):
    """
    Stateless: Platform VPC, peering, routes, endpoints, security groups.
    All resources have DESTROY removal policy. Deploy/destroy with each session.

    Required CDK context params:
        -c trust_vpc_id=vpc-xxx
        -c trust_route_table_ids=rtb-aaa,rtb-bbb
    """

    # Exposed for Phase 3 ECS stack
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
        ...
```

### app.py Integration Point

```python
# After existing stateless IngestionRoleStack in app.py:
from access_iq_infra.stacks.network import NetworkStack

network = NetworkStack(
    app,
    f"network-{cfg.app_name}-{cfg.env_name}",
    cfg=cfg,
    env=cdk_env,
)
# Phase 3 will consume: network.vpc, network.ecs_task_sg
```

### CDK Assertions Test Pattern (follows existing tests/unit/test_lake_stack.py style)

```python
# tests/unit/test_network_stack.py
import pytest
aws_cdk = pytest.importorskip("aws_cdk")
from aws_cdk import App
from aws_cdk.assertions import Template, Match
from access_iq_infra.settings import EnvConfig
from access_iq_infra.stacks.network import NetworkStack


def _cfg() -> EnvConfig:
    return EnvConfig(
        app_name="access-iq",
        env_name="dev",
        user_name="test/test",
        account_id="111111111111",
        region="eu-west-2",
        s3={},
        iam={"external_bucket": "x", "trust_account_id": "999999999999"},
        vpc={"platform_cidr": "10.10.0.0/16", "trust_cidr": "10.0.0.0/16", "max_azs": 2, "nat_gateways": 1},
        tags={},
    )


def _template() -> Template:
    app = App(context={
        "trust_vpc_id": "vpc-test",
        "trust_route_table_ids": "rtb-test1,rtb-test2",
    })
    stack = NetworkStack(app, "NetworkStack", cfg=_cfg())
    return Template.from_stack(stack)


def test_vpc_cidr() -> None:
    tpl = _template()
    tpl.has_resource_properties("AWS::EC2::VPC", {"CidrBlock": "10.10.0.0/16"})


def test_two_private_two_public_subnets() -> None:
    tpl = _template()
    tpl.resource_count_is("AWS::EC2::Subnet", 4)


def test_single_nat_gateway() -> None:
    tpl = _template()
    tpl.resource_count_is("AWS::EC2::NatGateway", 1)


def test_s3_gateway_endpoint() -> None:
    tpl = _template()
    tpl.has_resource_properties(
        "AWS::EC2::VPCEndpoint",
        {"VpcEndpointType": "Gateway", "ServiceName": Match.string_like_regexp("s3")},
    )


def test_interface_endpoints_count() -> None:
    tpl = _template()
    tpl.resource_count_is("AWS::EC2::VPCEndpoint", 6)  # 1 gateway + 5 interface


def test_ecs_sg_deny_all_outbound() -> None:
    # Allow-all-outbound=False means NO 0.0.0.0/0 egress rule in the SG
    tpl = _template()
    sgs = tpl.find_resources("AWS::EC2::SecurityGroup")
    # Verify at least one SG has specific egress rules (not 0.0.0.0/0)
    ...
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Manual VPC peering acceptance via console | `CfnVPCPeeringConnection.peer_role_arn` auto-accepts | CDK v2 (stabilised ~2022) | Full automation; no human step in Trust account after role creation |
| Custom Lambda for cross-account SDK calls | `AwsCustomResource` with `assumed_role_arn` | CDK v2 custom_resources module | Singleton Lambda, managed lifecycle; significantly less boilerplate |
| `SubnetType.PRIVATE_ISOLATED` for private subnets | `SubnetType.PRIVATE_WITH_EGRESS` | CDK v2 (deprecated PRIVATE) | Semantically clearer; `PRIVATE` is deprecated alias |
| `ip_cidr` param on `ec2.Vpc` | `ip_addresses=ec2.IpAddresses.cidr(...)` | CDK v2 (recent) | Old `cidr` param still works but `ip_addresses` is current API |

**Deprecated/outdated:**
- `ec2.SubnetType.PRIVATE`: Deprecated alias for `PRIVATE_WITH_EGRESS`. Use `PRIVATE_WITH_EGRESS` explicitly.
- `ec2.Vpc(cidr=...)`: Replaced by `ip_addresses=ec2.IpAddresses.cidr(...)` in recent CDK v2. Both work in 2.236.0 but `ip_addresses` is preferred.

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | CDK context comma-separated list for `trust_route_table_ids` is the idiomatic pattern | Pattern 8 | Minor — alternative is multiple `-c` flags or JSON string; plan must specify chosen convention |
| A2 | `modifyVpcPeeringConnectionOptions` API action name (camelCase) is correct for AwsSdkCall | Pattern 5 | Deploy failure — AwsSdkCall action names are camelCase JavaScript SDK method names |
| A3 | Trust Northshire simulator has a stable role name `access-iq-peering-accepter` — this is a convention proposal, not confirmed | Cross-Account IAM section | Mismatch between Platform CDK ARN construction and actual role name in Trust account |
| A4 | `ec2.InterfaceVpcEndpointAwsService.ECR` (without `_DOCKER`) maps to `com.amazonaws.<region>.ecr.api` | Pattern 6 | Wrong endpoint; ECR pulls would fail from ECS tasks |

---

## Open Questions

1. **Trust Northshire simulator: peering-accepter role current state**
   - What we know: D-02 identifies this as a hard prerequisite; role does not yet exist.
   - What's unclear: When will the Northshire sim repo be updated? Does it need a CDK stack or raw CloudFormation?
   - Recommendation: Plan Wave 0 should include a prerequisite verification step — check Trust account for role ARN before executing Phase 2 CDK deploy.

2. **Trust route table count and structure**
   - What we know: Trust VPC (`10.0.0.0/16`) has private subnets for RDS; exact route table structure depends on current Northshire sim CDK.
   - What's unclear: Does Trust have one route table per subnet or a shared route table? How many IDs to expect?
   - Recommendation: Planner should query Trust CloudFormation outputs for route table IDs as part of the deploy-time context param documentation.

3. **`peer_role_arn` vs AwsCustomResource for acceptance**
   - What we know: `CfnVPCPeeringConnection.peer_role_arn` handles acceptance atomically; D-01 mentions AwsCustomResource for acceptance specifically.
   - What's unclear: D-01 may have been written assuming the `peer_role_arn` path was not viable; it is viable.
   - Recommendation: Plan should use `peer_role_arn` for acceptance (simpler, less error-prone) and `AwsCustomResource` only for Trust route tables + DNS. If the team wants the AwsCustomResource path for acceptance anyway, add `ec2:AcceptVpcPeeringConnection` to the custom resource policy statements.

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| aws-cdk-lib | NetworkStack synthesis | Yes | 2.236.0 | — |
| AWS Platform account credentials | `cdk deploy` | Yes (dev: 222308823356) | — | — |
| Trust account (Northshire) credentials | Peering-accepter role creation | [ASSUMED: yes] | — | Manual role creation via console |
| Trust VPC deployed | NetworkStack context params | Depends on Northshire sim | — | Cannot deploy NetworkStack without Trust VPC |
| Peering-accepter IAM role in Trust account | `CfnVPCPeeringConnection.peer_role_arn` | Not yet (D-02 prerequisite) | — | BLOCKING: no fallback — role must exist before deploy |

**Missing dependencies with no fallback:**
- `access-iq-peering-accepter` IAM role in Trust account — must be created in Northshire simulator repo before any `cdk deploy` of NetworkStack.

**Missing dependencies with fallback:**
- Trust VPC ID / route table IDs: will be available once Northshire simulator is deployed for the session.

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest (existing, via `make test`) |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` |
| Quick run command | `. .venv/bin/activate && pytest tests/unit/test_network_stack.py -v` |
| Full suite command | `make test` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| REQ-NET-01 | VPC exists with 10.10.0.0/16 CIDR | unit | `pytest tests/unit/test_network_stack.py::test_vpc_cidr -x` | Wave 0 |
| REQ-NET-01 | 4 subnets (2 public + 2 private) across 2 AZs | unit | `pytest tests/unit/test_network_stack.py::test_two_private_two_public_subnets -x` | Wave 0 |
| REQ-NET-01 | Single NAT gateway in dev | unit | `pytest tests/unit/test_network_stack.py::test_single_nat_gateway -x` | Wave 0 |
| REQ-NET-02 | CfnVPCPeeringConnection resource exists | unit | `pytest tests/unit/test_network_stack.py::test_vpc_peering_resource -x` | Wave 0 |
| REQ-NET-02 | Platform-side CfnRoute to Trust CIDR exists | unit | `pytest tests/unit/test_network_stack.py::test_platform_peering_routes -x` | Wave 0 |
| REQ-NET-02 | AwsCustomResource for Trust routes exists | unit | `pytest tests/unit/test_network_stack.py::test_trust_route_custom_resource -x` | Wave 0 |
| REQ-NET-02 | ECS SG has no 0.0.0.0/0 egress (deny-by-default) | unit | `pytest tests/unit/test_network_stack.py::test_ecs_sg_deny_all_outbound -x` | Wave 0 |
| REQ-NET-03 | S3 gateway endpoint present | unit | `pytest tests/unit/test_network_stack.py::test_s3_gateway_endpoint -x` | Wave 0 |
| REQ-NET-03 | 5 interface endpoints present | unit | `pytest tests/unit/test_network_stack.py::test_interface_endpoints_count -x` | Wave 0 |
| REQ-NET-03 | Full suite synths cleanly (dev + prod) | unit | `pytest tests/unit/test_app_synth.py -x` | Extend existing |

### Sampling Rate

- **Per task commit:** `pytest tests/unit/test_network_stack.py -x`
- **Per wave merge:** `make test`
- **Phase gate:** `make ci` (ruff format + lint + mypy + full test suite green)

### Wave 0 Gaps

- [ ] `tests/unit/test_network_stack.py` — covers all REQ-NET-* assertions above
- [ ] `tests/unit/test_app_synth.py` — extend existing to include NetworkStack synth with context params

---

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | N/A (no user auth in this phase) |
| V3 Session Management | No | N/A |
| V4 Access Control | Yes | IAM least-privilege: peering-accepter role scoped to specific EC2 actions; ECS SG deny-by-default |
| V5 Input Validation | Yes | CDK context params validated at synth time with explicit ValueError |
| V6 Cryptography | No | No data encryption in networking layer; handled by LakeStack |

### Known Threat Patterns for Cross-Account Networking

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Overly permissive peering-accepter role | Elevation of Privilege | Scope to specific EC2 actions; do not use `ec2:*` or `*` |
| Peering CIDR too broad | Spoofing | Lock Trust CIDR to exactly `10.0.0.0/16`; never use `0.0.0.0/0` in peering routes |
| ECS task SG with default egress | Tampering / Exfiltration | `allow_all_outbound=False`; explicit egress rules to Trust CIDR only + 443 for AWS endpoints |
| Secrets in CDK context | Information Disclosure | Trust VPC IDs are not secrets; Trust account ID in config file is acceptable |
| AwsCustomResource Lambda IAM over-grant | Elevation of Privilege | Use `AwsCustomResourcePolicy.from_statements` with explicit minimal actions; never `from_sdk_calls` for cross-account |

---

## Sources

### Primary (HIGH confidence)
- `/websites/aws_amazon_cdk_api_v2_python` (Context7) — `CfnVPCPeeringConnection`, `AwsCustomResource`, `Vpc`, `InterfaceVpcEndpointAwsService`, `GatewayVpcEndpointAwsService`, `SecurityGroup`, `CfnRoute`, `SubnetType`
- `infra/access_iq_infra/stacks/lake.py` — established stack patterns (`RemovalPolicy`, `cfg` prop, `from __future__ import annotations`)
- `infra/access_iq_infra/settings.py` — `EnvConfig` frozen dataclass pattern
- `infra/app.py` — stateful/stateless stack ordering pattern
- `tests/unit/test_lake_stack.py` — CDK assertions test pattern (`Template.from_stack`, `resource_count_is`, `has_resource_properties`)

### Secondary (MEDIUM confidence)
- [Cross-account VPC Peering with AWS CDK - Purple Technology](https://blog.purple-technology.com/cross-account-vpc-peering-with-aws-cdk/) — confirmed `peer_role_arn` pattern and AwsCustomResource for route/DNS
- [AWS CDK VPC Peering DEV Community Drill #006](https://dev.to/aws-builders/aws-cdk-100-drill-exercises-006-vpc-peering-cross-account-network-integration-and-dns-546) — `ModifyVpcPeeringConnectionOptions` usage pattern
- [AWS CloudFormation: Peer with VPC in another account](https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/peer-with-vpc-in-another-account.html) — Trust-side IAM role minimum permissions

### Tertiary (LOW confidence)
- WebSearch results on AwsCustomResource cross-account buggy behaviour (GitHub issue #9170) — flag for testing; not confirmed resolved.

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — `aws-cdk-lib==2.236.0` already installed; all constructs verified via Context7
- Architecture: HIGH — patterns verified against Context7 API docs + official CloudFormation docs; existing stack conventions confirmed from codebase
- Pitfalls: MEDIUM — race conditions and SG defaults verified; AwsCustomResource Lambda VPC pitfall from community sources
- Cross-account IAM permissions: MEDIUM — IAM actions from official CloudFormation docs; exact resource-level scoping is an assumption

**Research date:** 2026-05-19
**Valid until:** 2026-06-19 (CDK API stable; 30-day window)
