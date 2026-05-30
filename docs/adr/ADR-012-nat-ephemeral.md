# ADR-012: NAT Gateway Ephemeral with Stateless NetworkStack

## Status

Accepted

## Context

The Platform VPC needs a NAT gateway for ECS Fargate tasks in private subnets to
reach the internet (ECR image pull, CloudWatch, Secrets Manager -- though the latter
two have VPC interface endpoints). A NAT gateway costs ~$0.045/hr (~$32/mo) when idle.
The strict ephemeral pattern requires zero idle cost between working sessions.

VPC interface endpoints already exist for Secrets Manager, KMS, CloudWatch Logs, ECR
(API + DKR), and S3 (gateway endpoint). These reduce NAT dependency to ECR image layer
pulls that miss the DKR endpoint cache and any internet-bound traffic (e.g. PyPI in
container builds).

## Decision

**NAT gateway is part of the stateless NetworkStack, destroyed by `make down`.**

- Single NAT in dev (one AZ) for cost; prod would use one NAT per AZ for HA.
- `cdk destroy NetworkStack` removes the NAT, Elastic IP, and route table entries.
- NAT recreation takes ~3-5 minutes on `make up`.
- Interface endpoints for Secrets Manager, KMS, and CloudWatch Logs remain functional
  even without the NAT -- only ECR pulls and internet-bound traffic require it.

## Consequences

- $0 NAT idle cost between sessions. Active session cost ~$0.045/hr (typically 2-4
  hours = $0.09-$0.18 per session).
- `make up` takes 3-5 minutes longer for NAT creation. Mitigated by parallel stack
  deployment (NAT creates while other stacks deploy).
- If interface endpoints are added for ECR DKR layer pulls in future, NAT becomes
  optional even during active sessions -- but the gateway S3 endpoint already handles
  S3-backed layer storage.
- NetworkStack destroy order matters: ECS tasks must be stopped before destroying the
  NAT, or in-flight requests will fail. `make down` handles this sequencing.
