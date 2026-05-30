# ADR-015: Two-Account Vendor/Client Staging Boundary

## Status

Accepted

## Context

The project simulates a consultancy engagement with a UK NHS Trust ("Northshire Trust").
In real NHS engagements, the Trust and the data platform vendor operate in separate AWS
accounts with distinct IAM boundaries, network controls, and data sovereignty
requirements. NHS Digital's Data Security and Protection Toolkit (DSPT) mandates that
patient data remains under the data controller's jurisdiction -- the Trust account.

The question is whether to simulate this boundary with two AWS accounts or simplify to
a single account with IAM-based isolation (resource policies, permission boundaries).

## Decision

**Two AWS accounts model the vendor/client boundary.**

**Trust account hosts:**

- RDS Postgres (EHR + Urgent Care source systems)
- AWS Transfer Family (SFTP appointment exports, see ADR-013)
- Trust S3 bucket (diagnostics/provider reference exports)
- Private VPC with no internet gateway

**Platform account hosts:**

- ECS Fargate (ingestion compute)
- S3 data lake (Bronze/Silver/Gold medallion layers)
- Redshift Serverless (analytical warehouse)
- Prefect server + worker (orchestration)
- CloudWatch (observability)
- Streamlit dashboard (analytics UI)
- VPC peered to Trust VPC

**Cross-account mechanisms:**

- VPC peering connects Platform private subnets to Trust VPC for RDS and SFTP access.
- Cross-account S3 access uses bucket policy grants (Trust bucket grants Platform
  ingestion role read access).
- Secrets are account-local: Trust credentials stored in Platform Secrets Manager,
  never cross-account Secrets Manager access.
- A two-pass CDK deploy sequence handles the dependency: Trust deploys first (exports
  VPC ID), Platform peers to it, Trust redeploys with return routes.

## Consequences

- Demonstrates production-shaped security posture: no Trust credentials in Platform
  account IAM, no Platform admin access to Trust data at rest.
- VPC peering requires a two-pass CDK deploy. `session.sh` automates the full
  sequence; `make status` shows both accounts.
- Trade-off: `make up` takes 2-3 minutes longer for the two-pass deploy.
- Cross-account debugging is harder (must switch AWS profiles). Mitigated by
  `make status` and CloudWatch cross-account dashboard widgets.
- Portfolio impact: a hiring manager evaluating a "consultancy engagement simulation"
  sees account-level separation matching real NHS vendor engagements, not just IAM
  policies in a single account.

## Alternatives considered

- **Single account with IAM isolation**: Simpler to manage but does not model the NHS
  Trust boundary. Resource policies and permission boundaries cannot enforce data
  sovereignty at the account level. A single `AdministratorAccess` policy in one
  account bypasses all IAM-based isolation.

- **AWS Organizations with SCPs**: Overkill for a two-account portfolio project. Adds
  billing complexity (consolidated billing, delegated admin). SCPs are a compliance
  enforcement tool, not a data boundary tool -- they restrict actions, not data flows.

- **Separate VPCs in same account**: Network isolation without IAM boundary. Trust RDS
  is accessible to any Platform IAM principal with `rds:Connect` permission. Does not
  model the Trust's independent AWS account lifecycle (the Trust exists independently
  of the consultant's platform).

## References

- CLAUDE.md architecture overview (two-account boundary)
- `scripts/session.sh` two-pass deploy automation
- ADR-013 (Trust-side SFTP ownership)
- PROJECT.md two-account context
