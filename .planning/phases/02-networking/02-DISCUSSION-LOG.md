# Phase 2: Networking - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-19
**Phase:** 02-networking
**Areas discussed:** Cross-account peering, Stack split strategy, VPC endpoints scope

---

## Cross-Account Peering

### Q1: How should Platform CDK handle Trust-side peering acceptance?

| Option | Description | Selected |
|--------|-------------|----------|
| CDK AwsCustomResource | Platform CDK assumes cross-account role to accept peering + update Trust route tables. Fully automated. | ✓ |
| Manual accept + script | Platform creates request, manual accept in Trust console. Simpler trust boundary. | |
| Pre-provisioned in simulator | Simulator pre-creates accepter + routes. Platform references peering ID from config. | |

**User's choice:** CDK AwsCustomResource
**Notes:** Full automation preferred.

### Q2: Does a cross-account role exist in Trust?

| Option | Description | Selected |
|--------|-------------|----------|
| Needs creating | Add peering-accepter role to Northshire simulator CDK. | ✓ |
| Already exists | Existing role in Trust account. | |

**User's choice:** Needs creating
**Notes:** Scoped to ec2:AcceptVpcPeeringConnection, ec2:CreateRoute, ec2:ModifyVpcPeeringConnectionOptions.

### Q3: Cross-VPC DNS resolution approach?

| Option | Description | Selected |
|--------|-------------|----------|
| AwsCustomResource for DNS | Enable DNS resolution on both sides via ModifyVpcPeeringConnectionOptions. | ✓ |
| IP-based config | Put Trust RDS private IP in env config. Fragile if IP changes. | |

**User's choice:** AwsCustomResource for DNS
**Notes:** Matches ROADMAP success criterion #3.

---

## Stack Split Strategy

### Q1: How should networking resources be split across CDK stacks?

| Option | Description | Selected |
|--------|-------------|----------|
| VpcStack (stateful) + NetworkingStack (ephemeral) | VPC + subnets + peering in RETAIN stack. NAT + endpoints ephemeral. | |
| Single NetworkStack (all ephemeral) | Entire VPC + peering + NAT + endpoints in one stack. Destroys to zero. | ✓ |
| You decide | Let Claude pick. | |

**User's choice:** Single NetworkStack (all ephemeral)
**Notes:** Clean and simple. Everything tears down to zero cost.

### Q2: Should Trust-side peering AwsCustomResource be separate?

| Option | Description | Selected |
|--------|-------------|----------|
| Same NetworkStack | One stack creates VPC, peering, accepts, routes, endpoints. All ephemeral. | ✓ |
| Separate PeeringStack | Isolate cross-account custom resource. Easier to debug independently. | |

**User's choice:** Same NetworkStack
**Notes:** Simplicity over isolation.

### Q3: Where should Trust VPC details come from?

| Option | Description | Selected |
|--------|-------------|----------|
| CDK context params | Pass trust_vpc_id etc. as -c flags. `make up` orchestrates deploy order. | ✓ |
| Config file + manual update | Add to infra/config/{env}.json. Manual update each session. | |

**User's choice:** CDK context params
**Notes:** User clarified Trust stack is entirely ephemeral — IDs change every session. Config file approach rejected as it would need manual updates every session. CDK context injection is the only viable approach.

---

## VPC Endpoints Scope

### Q1: Which VPC endpoints should Phase 2 deploy?

| Option | Description | Selected |
|--------|-------------|----------|
| S3 gateway + all interface | S3 gateway (free) + Secrets Manager, KMS, ECR api+dkr, CloudWatch Logs. | ✓ |
| S3 gateway only | Just free S3 gateway. Rest via NAT. | |
| S3 gateway + Secrets/KMS only | Middle ground — ECR + CloudWatch via NAT. | |

**User's choice:** S3 gateway + all interface endpoints
**Notes:** Stack is ephemeral so cost is pennies per session.

### Q2: Interface endpoints in both AZs or single?

| Option | Description | Selected |
|--------|-------------|----------|
| Both AZs | Consistent availability. Small cost delta on ephemeral. | |
| Single AZ | Match NAT. Cheaper but constrains ECS tasks. | |
| You decide | Let Claude pick. | ✓ |

**User's choice:** You decide
**Notes:** Claude chose both AZs — negligible cost delta, avoids ECS placement constraints.

---

## Claude's Discretion

- Interface endpoint AZ placement: both AZs selected (cost negligible on ephemeral, avoids ECS constraints)

## Deferred Ideas

None — discussion stayed within phase scope.
