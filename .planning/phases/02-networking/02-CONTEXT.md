# Phase 2: Networking - Context

**Gathered:** 2026-05-19
**Status:** Ready for planning

<domain>
## Phase Boundary

Private connectivity between the Platform and Trust AWS accounts. Deploy a Platform VPC with public + private subnets, establish VPC peering to the Trust VPC (separate account, fully ephemeral), configure VPC endpoints for AWS service access, and set up security groups scoped to required ports/CIDRs — so that Phase 3's ECS Fargate tasks can reach Trust RDS, SFTP, and S3 over private routes with deny-by-default security groups.

Both the Trust and Platform stacks are ephemeral (destroyed between sessions). The entire networking layer tears down to zero idle cost.

</domain>

<decisions>
## Implementation Decisions

### Cross-Account Peering
- **D-01:** Use CDK `AwsCustomResource` to automate peering acceptance on the Trust side. Platform CDK assumes a cross-account role in the Trust account to accept the peering connection, update Trust route tables, and enable DNS resolution.
- **D-02:** A peering-accepter IAM role must be created in the Trust account (Northshire simulator repo). Scoped to `ec2:AcceptVpcPeeringConnection`, `ec2:CreateRoute`, `ec2:ModifyVpcPeeringConnectionOptions`. This is a prerequisite — researcher should flag it.
- **D-03:** Cross-VPC DNS resolution enabled via `AwsCustomResource` calling `ModifyVpcPeeringConnectionOptions` on both sides. ECS tasks resolve Trust RDS by hostname, not IP.

### Stack Architecture
- **D-04:** Single ephemeral `NetworkStack` containing all networking resources: VPC, subnets, NAT gateway, peering connection + acceptance, route tables, security groups, and all VPC endpoints. No stateful/stateless split for networking — everything is ephemeral per D6.
- **D-05:** Trust-side peering acceptance (AwsCustomResource) lives in the same `NetworkStack`. One stack creates, peers, and configures everything.
- **D-06:** Trust VPC details (vpc_id, route_table_ids) passed as CDK context params (`-c trust_vpc_id=xxx`), not config file values. Trust stack is ephemeral so IDs change every session. `make up` (Phase 9) will orchestrate deploy order; during development, manual `-c` flags or a helper script suffice.

### VPC Endpoints
- **D-07:** Full endpoint suite deployed in the NetworkStack: S3 gateway endpoint (free) + interface endpoints for Secrets Manager, KMS, ECR API, ECR DKR, and CloudWatch Logs. Stack is ephemeral so cost is pennies per session.

### Claude's Discretion
- **Interface endpoint AZ placement:** Deploy in both AZs (both private subnets). Cost delta negligible on ephemeral stacks; avoids constraining ECS task placement to a single AZ.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project-Level
- `.planning/PROJECT.md` — locked decisions D1 (CIDRs), D6 (ephemeral NAT), D7 (SFTP Trust-side only)
- `.planning/ROADMAP.md` § Phase 2 — goal + 5 success criteria

### Infrastructure
- `infra/app.py` — current CDK app wiring; NetworkStack must integrate here
- `infra/access_iq_infra/settings.py` — frozen `EnvConfig` dataclass pattern; extend for Trust context params
- `infra/config/dev.json` — existing env config; Trust account ID and peering role ARN need referencing
- `infra/config/prod.json` — same for prod
- `infra/access_iq_infra/stacks/` — existing stacks (lake, secrets, catalog, ecr, iam) to integrate with

### Prior Phase
- `.planning/phases/01-stateful-foundations-brownfield-hardening/01-CONTEXT.md` — Phase 1 decisions on stateful/stateless split, EnvConfig pattern, stack naming

### External
- `https://github.com/chiplusplus/northshire-hospital-sim` — Trust simulator repo; needs peering-accepter IAM role added as prerequisite

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `infra/access_iq_infra/settings.py` — `EnvConfig` dataclass + `load_env_config` loader; extend to accept Trust VPC context params
- `infra/app.py` — stack wiring pattern (stateful vs stateless ordering, cross-stack references via props)

### Established Patterns
- Frozen `EnvConfig` dataclass for all CDK config; CDK context (`-c env=dev|prod`) selects config file
- Tags applied app-wide via `tagging.apply_tags(app, cfg.tags)`
- Stacks receive `cfg` as a constructor prop for environment-aware configuration
- `RemovalPolicy.RETAIN` for stateful, `DESTROY` for stateless — NetworkStack is all `DESTROY`

### Integration Points
- `app.py` — new `NetworkStack` must be instantiated and its VPC/subnets/SGs exposed as props for Phase 3's ECS stack
- `IngestionRoleStack` — may need VPC context in Phase 3 (not this phase)
- `LakeStack` — S3 gateway endpoint routes to the existing lake bucket

</code_context>

<specifics>
## Specific Ideas

- Trust stack is fully ephemeral — no stable IDs. CDK context injection is the only viable approach for Trust VPC references.
- The peering-accepter role in the Trust account is a hard prerequisite. Researcher should investigate minimum IAM permissions and CDK patterns for cross-account `AwsCustomResource`.
- D1 CIDRs are locked: Trust `10.0.0.0/16`, Platform `10.10.0.0/16`.
- REQ-NET-01 allows single-AZ NAT in dev for cost. Prod config should use multi-AZ if needed, but as a portfolio project single-AZ may suffice for both.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 2-Networking*
*Context gathered: 2026-05-19*
