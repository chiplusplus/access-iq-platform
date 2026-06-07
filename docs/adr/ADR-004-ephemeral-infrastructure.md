# ADR-004: Ephemeral Infrastructure Pattern

## Status

Accepted

## Context

Access-IQ is a portfolio project developed in roughly 8-hour weekly sessions. Leaving AWS infrastructure running continuously would cost ~$350/month or more (eu-west-2 pricing) - unjustifiable for a project with zero production traffic. The two-account architecture (Trust + Platform) compounds the problem: RDS, Transfer Family, ECS, and NAT gateways each incur hourly charges even when idle.

Key cost drivers if left running (eu-west-2, as of 2026):

| Service               | Hourly              | Monthly (always-on)            | Monthly (8h/week) |
| --------------------- | ------------------- | ------------------------------ | ----------------- |
| RDS db.t3.micro       | $0.021              | ~$15                           | ~$0.73            |
| Transfer Family SFTP  | $0.30               | ~$219                          | ~$10.38           |
| NAT Gateway           | $0.048              | ~$35                           | ~$1.66            |
| Redshift 8 RPU        | $3.74 (active only) | $0 idle (auto-pauses)          | ~$4               |
| ECS Fargate (3 tasks) | $0.085              | ~$62                           | ~$2.94            |
| **Total**             |                     | **~$331** (+ Redshift queries) | **~$20**          |

Redshift Serverless auto-pauses to zero RPU when idle (no compute charge), but the 8h/week estimate assumes ~1 hour of active query time per session. All other services charge continuously whether used or not.

## Decision

All infrastructure deploys from scratch at the start of a working session (`make up`) and is fully destroyed at the end (`make down`). A Lambda-backed budget alarm (BudgetStack) provides a safety net - if monthly spend reaches 80% of the ceiling ($10 dev / $20 prod), stacks are automatically torn down.

### What is destroyed and recreated each session

In dev, all resources use `RemovalPolicy.DESTROY`. `make down` runs `cdk destroy --all`, leaving the accounts at $0 idle cost with nothing persisted between sessions.

| Resource                     | Recreate time | Notes                                                            |
| ---------------------------- | ------------- | ---------------------------------------------------------------- |
| S3 data lake (all Parquet)   | N/A           | Destroyed with `auto_delete_objects`; re-ingestion + dbt rebuild |
| KMS CMK                      | <1 min        | New key created each session (7-day pending deletion on old key) |
| Secrets Manager entries      | <1 min        | Re-seeded by `session.sh` from Trust stack outputs               |
| ECR repository + image       | 2-3 min       | Image rebuilt and pushed each session                            |
| Glue Data Catalog            | <1 min        | Spectrum tables re-registered by dbt                             |
| RDS Postgres (Trust)         | 4-6 min       | Data is synthetic; re-seeded from the simulator                  |
| Transfer Family SFTP (Trust) | 1-2 min       | Appointment drops re-generated                                   |
| VPC + NAT + peering          | 3-5 min       | Stateless networking                                             |
| ECS cluster + tasks          | 1-2 min       | Fargate tasks are ephemeral by nature                            |
| Redshift Serverless          | 2-3 min       | Silver/Gold rebuilt by dbt from Bronze via Spectrum              |
| Observability (CloudWatch)   | <1 min        | Log groups and dashboards recreate from CDK                      |
| BudgetStack (Platform)       | <1 min        | Account-level, no persistent state                               |

In prod, stateful resources (S3 bucket, KMS key, Secrets, ECR, Glue Catalog) use `RemovalPolicy.RETAIN` to survive stack destruction.

### Session orchestration

```
make up    → Trust bootstrap → Platform CDK → Redshift pre-warm → Trust routes → Secrets → Docker → dbt → Prefect  (20-35 min)
make down  → Prefect stop → Platform destroy → Trust destroy  (6-10 min)
```

`session.sh` automates the full sequence including cross-account credential switching, VPC peering handshake, and Redshift Spectrum schema creation.

## Consequences

- Monthly cost for 8h/week usage: ~$20 (vs ~$331 always-on). **94% reduction**.
- Session startup latency: 20-35 minutes. Acceptable for weekly development sessions; would not work for a team needing instant access.
- Redshift cold-start adds 60-90 seconds on first query after `make up`. Mitigated by the pre-warm step in `session.sh`.
- Trade-off: developer must remember to `make down`. Mitigated by the BudgetStack Lambda safety net (tears down ephemeral stacks if spend threshold is breached).

## Alternatives considered

- **Always-on with scheduling**: AWS Instance Scheduler or EventBridge rules to stop/start resources on a schedule. Still requires RDS and SFTP to exist (storage charges apply even when stopped). Transfer Family has no stop/start - only create/delete. Doesn't eliminate the $219/month SFTP cost.
- **Serverless-only architecture**: Replace RDS with DynamoDB, SFTP with API Gateway + Lambda. Would eliminate idle costs but the project specifically demonstrates enterprise-shaped infrastructure (RDS, SFTP, VPC peering) for portfolio credibility. A serverless-only design tells a different story.
- **LocalStack / local Docker**: Run AWS services locally for development. Doesn't demonstrate real cross-account networking, IAM, or Spectrum. Adds a parallel environment to maintain. The portfolio value is in the real AWS deployment.

## References

- [BudgetStack implementation](../../infra/access_iq_infra/stacks/budget.py) - Lambda teardown safety net
- [session.sh](../../scripts/session.sh) - Full deploy/destroy orchestration
