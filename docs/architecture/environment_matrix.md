# access-iq - Environment Matrix (Dev + Prod)

## Purpose

This document describes the **intended** environment separation for a production-grade deployment of Access-IQ. It defines how dev and prod environments would differ across infrastructure, data, security, and operations, and how changes would promote from dev to prod.

In practice, only dev is deployed. Running a separate prod account with stateful resources (RETAIN policies on S3, Secrets, ECR) would add ongoing cost and operational overhead that is not justified for a portfolio project. The environment matrix is included to demonstrate awareness of production environment design — the CDK configs (`infra/config/dev.json`, `infra/config/prod.json`) and removal policy logic in each stack are wired to support both environments if needed.

---

## Environments

### dev

**Purpose:** rapid iteration, feature development, pipeline experimentation, backfills/testing.
**Risk tolerance:** higher (fail fast, verbose logs).
**Data expectations:** can be smaller / subset / synthetic.

### prod

**Purpose:** stable production environment showing best practices.
**Risk tolerance:** low (controlled changes, alerts, conservative defaults).
**Data expectations:** consistent, full refresh cadence, clean run history.

---

## Deployment / Promotion Model

### Promotion principles

- **All deployments originate from Git** (no manual console drift).
- **Dev is deployed on merge to `main`**.
- **Prod is deployed only from tagged releases** (e.g., `v0.1.0`) to simulate change control.

### Promotion flow (recommended)

1. Feature branch → PR → merge to `main`
2. CI passes → deploy to **dev**
3. When stable: create a release tag (e.g. `v0.2.0`)
4. Tag triggers deploy to **prod**

---

## Environment Matrix

| Category           | dev                                                                       | prod                                                         |
| ------------------ | ------------------------------------------------------------------------- | ------------------------------------------------------------ |
| AWS account        | Separate account                                                          | Separate account                                             |
| AWS region         | Same region as prod                                                       | Same region as dev                                           |
| Naming             | `access-iq-dev-*`                                                         | `access-iq-prod-*`                                           |
| Tags               | `Environment=dev\|prod`, `Project=access-iq`,`CostCenter=project`         | `Environment=prod`, `Project=access-iq`,`CostCenter=project` |
| S3 buckets         | `access-iq-<purpose>-dev-<acct>`                                          | `access-iq-<purpose>-prod-<acct>`                            |
| S3 prefixes        | `bronze/`, `silver/`, `gold/` under dev bucket                            | Same prefixes under prod bucket                              |
| Redshift           | smaller / cheaper (or Redshift Serverless minimal)                        | stable sizing (or serverless with guardrails)                |
| Redshift DB/schema | `dev` DB or schema namespace                                              | `prod` DB or schema namespace                                |
| Schema strategy    | `bronze_dev`, `silver_dev`, `gold_dev` (or schema-per-layer + env prefix) | `bronze`, `silver`, `gold` (or env prefix `*_prod`)          |
| Secrets            | Secrets Manager entries suffixed `-dev`                                   | Secrets Manager entries suffixed `-prod`                     |
| Logging level      | DEBUG/INFO (more verbose)                                                 | INFO/WARN (less noise)                                       |
| Alerts             | optional / low-severity                                                   | enabled (pipeline failure + freshness breaches)              |
| Retention          | shorter retention acceptable                                              | longer retention for auditability                            |
| Backfills          | frequent, expected                                                        | controlled, documented                                       |
| DQ enforcement     | fail fast on more checks                                                  | fail/alert based on severity thresholds                      |
| Cost controls      | relaxed but monitored                                                     | strict tagging + budgets/alarms where possible               |

---

## Data Layer Rules by Environment

### Bronze (raw landing)

- **dev:** may ingest subset windows or smaller extracts; still must be idempotent and auditable.
- **prod:** ingests full agreed cadence; raw files retained for reproducibility.

### Silver (standardised)

- **dev:** rapid iteration on rules; more frequent rebuilds expected.
- **prod:** only promoted rule changes; versioned transformations.

### Gold (marts)

- **dev:** may include experimental marts.
- **prod:** only marts referenced by dashboard and traceability matrix.

---

## Secrets and Configuration

### Naming convention (Secrets Manager)

- `access-iq/dev/<secret-name>`
- `access-iq/prod/<secret-name>`

Examples:

- `access-iq/dev/ehr_readonly_dsn`
- `access-iq/prod/ehr_readonly_dsn`
- `access-iq/dev/sftp_credentials`
- `access-iq/prod/sftp_credentials`

### Configuration loading

- Environment selected via `ENV=dev|prod`
- No environment-specific values hardcoded in code
- All credentials resolved from Secrets Manager

---

## Logging, Monitoring, and Alerting

### dev

- Verbose logs to accelerate debugging
- Alerts optional; failures can be noisy without consequence
- Data quality checks fail fast to surface issues early

### prod

- Alerts enabled for:
  - pipeline failures
  - missing daily extracts / freshness breaches
  - severe volume anomalies
- Logs retained longer
- Data quality checks classified by severity:
  - **Critical:** fail pipeline
  - **Non-critical:** alert + flag in downstream tables

---

## Access Control (IAM)

### Principles

- Least privilege by environment
- Separate IAM roles for:
  - ingestion
  - warehouse loading
  - orchestration
  - dashboard read-only

### Environment boundaries

- dev roles cannot read/write prod buckets or prod Redshift
- prod roles cannot access dev resources (optional but ideal)
