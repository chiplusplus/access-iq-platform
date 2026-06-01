<!-- Replace with actual dashboard screenshot -->

![Access-IQ Dashboard](docs/images/dashboard-screenshot.png)

### **[View the Live Dashboard →](https://access-iq-platform-h7uetia39pda9vbx3afhxl.streamlit.app/)**

[Case Study](docs/case-study.md) | [Architecture Decisions](docs/adr/)

# Access-IQ Platform

End-to-end NHS Trust analytics platform simulating a consultancy engagement that ingests operational healthcare data, models it through a medallion architecture, and surfaces access and inequality analytics.

## The Problem

NHS Trusts generate vast amounts of operational data across EHR systems, A&E departments, diagnostic services, appointment bookings etc, but they rarely have the engineering infrastructure to turn it into actionable inequality analytics.

Waiting times, A&E breaches, and diagnostic delays affect deprived communities disproportionately. National targets (18-week RTT, 6-week DM01, 4-hour A&E) are tracked in aggregate, but breakdowns by IMD decile, ethnicity, age band, and gender are largely invisible.

**Access-IQ** demonstrates how a data engineering consultancy would build the analytics infrastructure for a fictional NHS Trust ("Northshire Trust") to surface these patterns. The platform ingests synthetic but structurally realistic healthcare data from three source systems, models it through a Bronze/Silver/Gold medallion architecture, and delivers inequality-aware dashboards to Trust analysts.

Two AWS accounts model a real vendor-client boundary - the Trust controls its own data, the platform account processes it under contract. All infrastructure is CDK-managed with an ephemeral deploy/destroy pattern to avoid idle costs.

## How It Works

![Infrastructure Architecture](docs/images/architecture-infra.png)

The platform spans two AWS accounts connected via VPC peering. The **Trust account** hosts the simulated hospital environment (RDS Postgres, SFTP via Transfer Family, S3 exports). The **Platform account** runs the analytics infrastructure: ECS Fargate for ingestion, S3 data lake with KMS encryption, Redshift Serverless for warehousing and dbt modelling, Prefect for orchestration, and CloudWatch for observability.

Gold-layer Parquet files are exported to S3 and read by a Streamlit dashboard on Community Cloud via DuckDB - keeping the dashboard stateless and free-tier. See [Data Flow Diagram](docs/images/architecture-dataflow.png) for the Bronze to Silver to Gold pipeline.

<details><summary>View as Mermaid (interactive)</summary>

```mermaid
graph LR
    subgraph Trust["Trust Account (Northshire Hospital Sim)"]
        RDS[(RDS Postgres<br/>EHR + Urgent Care)]
        SFTP[Transfer Family<br/>SFTP Appointments]
        TS3[Trust S3<br/>Diagnostics + Providers]
    end

    subgraph Platform["Platform Account (access-iq)"]
        subgraph Compute["ECS Fargate"]
            ING[3x Ingestion Tasks]
            PFS[Prefect Server]
            PFW[Prefect Worker]
        end
        S3L[(S3 Data Lake<br/>Bronze / Silver / Gold)]
        KMS[KMS CMK<br/>Encryption]
        RS[(Redshift Serverless<br/>Spectrum + dbt)]
        CW[CloudWatch<br/>Logs + Alarms + Dashboard]
        SNS[SNS<br/>Alert Topics]
    end

    ST[Streamlit<br/>Community Cloud]

    RDS -->|VPC Peering| ING
    SFTP -->|VPC Peering| ING
    TS3 -->|Cross-account S3| ING
    ING -->|Bronze Parquet| S3L
    S3L -->|Spectrum| RS
    RS -->|dbt Silver+Gold| RS
    PFS -->|orchestrates| PFW
    PFW -->|triggers| ING
    PFW -->|dbt run| RS
    RS -->|Gold export| S3L
    S3L -->|Parquet read| ST
    CW -->|alarm| SNS
    KMS -.->|encrypts| S3L
```

</details>

## Tech Stack

| Component            | Tool                      | Version         | Why                                                                                                                                                                  |
| -------------------- | ------------------------- | --------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Ingestion**        | ECS Fargate + Python      | 3.12 + PyArrow  | Serverless containers avoid idle EC2 costs; Fargate scales each source independently without cluster management                                                      |
| **Storage**          | S3 + KMS CMK              | -               | Decouples storage from compute; KMS CMK enables per-env key rotation and cross-account grants that SSE-S3 cannot                                                     |
| **Warehouse**        | Redshift Serverless       | 8 RPU           | Spectrum queries Bronze in-place (no ETL duplication), RPU auto-scales to zero when idle, and native dbt adapter avoids Athena per-query costs                       |
| **Modelling**        | dbt-core + dbt-redshift   | 1.10            | Declarative SQL transformations with built-in lineage, test contracts, and incremental materialisation that Redshift stored procedures lack                          |
| **Data Quality**     | dbt-expectations + GE 1.x | -               | dbt-expectations validates inline during transforms; Great Expectations covers row-level profiling that dbt tests alone cannot express                               |
| **Orchestration**    | Prefect 3 (self-hosted)   | ECS Fargate     | Free self-hosted server on Fargate avoids Prefect Cloud costs; ECS work pool launches tasks as ephemeral containers with $0 idle                                     |
| **Dashboard**        | Streamlit                 | Community Cloud | Reads static Gold Parquet via DuckDB with no warehouse connection; Community Cloud hosts free-tier with zero infrastructure                                          |
| **Infrastructure**   | AWS CDK                   | Python          | Imperative Python over declarative YAML keeps config DRY with shared `EnvConfig`; L2 constructs handle IAM/encryption defaults that CloudFormation requires manually |
| **Pseudonymisation** | HMAC-SHA-256              | Lambda UDF      | Deterministic hash preserves join integrity across tables while NHS Mod-11 validation catches malformed identifiers before pseudonymisation                          |

## Quick Start

**Prerequisites:** AWS CLI v2 with two named profiles configured (one for the Platform account, one for the Trust account), [uv](https://docs.astral.sh/uv/), Node.js (for CDK), Docker.

```bash
# Clone both repos as siblings
git clone https://github.com/chiplusplus/access-iq-platform.git
git clone https://github.com/chiplusplus/northshire-hospital-sim.git

# Set up the Trust simulator (create virtual environment and install dependencies)
cd northshire-hospital-sim
python -m venv .northshire-hospital-sim
.northshire-hospital-sim/bin/pip install -r requirements.txt

# Set up the platform
cd ../access-iq-platform
cp .env.example .env       # Fill in AWS profile, bucket name, secret ARNs
# Review infra/config/dev.json for account IDs, VPC CIDRs, Redshift capacity
make setup                 # Create venv, install deps, pre-commit hooks

# Deploy everything
export PLATFORM_PROFILE=<your-platform-profile>
export TRUST_PROFILE=<your-trust-profile>
make up                    # Deploy infra, seed data, start pipeline (~25 min)
```

`make up` invokes `scripts/session.sh` which orchestrates an 8-step deployment:

1. **Trust bootstrap** - deploys Trust CDK stack, seeds RDS with ~100K synthetic patients + ~586K encounters via `northshire-hospital-sim`, publishes to RDS/S3/SFTP
2. **Platform deploy** - deploys all Platform stacks (lake, secrets, catalog, ECR, network, warehouse, compute, observability, budget) with VPC peering
3. **Redshift pre-warm** - creates Spectrum external schema, waits for workgroup availability
4. **Secrets + Docker + dbt + Prefect** - seeds Secrets Manager, builds and pushes ingestion image, registers Spectrum tables, starts Prefect server and worker

After completion: Streamlit URL printed, CloudWatch dashboard URL printed, Prefect UI at `localhost:4200` (via SSM tunnel).

## Environments

Only dev is actively deployed. The CDK stacks and config files support a separate prod environment (`infra/config/prod.json` with RETAIN policies, Redshift snapshots, 90-day log retention), but running a second account with stateful resources is not justified for a portfolio project. See [Environment Matrix](docs/architecture/environment_matrix.md) for the full prod design.

Each environment is driven by a config file at `infra/config/{dev,prod}.json` where you set your own account IDs, region, VPC CIDRs, and Redshift capacity. CDK reads the config matching the `CDK_ENV` variable:

```bash
CDK_ENV=dev make infra-bootstrap   # one-time CDK bootstrap per account
CDK_ENV=dev make up                # deploy dev (default)
```

In dev, all resources use `DESTROY` removal policy — `make down` leaves the accounts at $0 idle cost with nothing persisted between sessions.

## Session Workflow

```bash
make up           # Deploy all stacks, seed Trust data, start Prefect
make status       # Show stack status, Redshift state, latest manifest
make pipeline     # Optional (pipeline is scheduled to trigger on the hour every hour): Run full pipeline: ingest -> dbt -> DQ -> Gold export
make dashboard    # Run Streamlit dashboard locally (reads Gold Parquet from S3 via DuckDB)
make down         # Destroy all stacks across both accounts
```

`make down` returns to **$0 idle cost**. In dev, every resource is destroyed (DESTROY removal policy) except the KMS CMK, which uses RETAIN in both environments because its pending-deletion window would break redeploy cycles.

**Budget safety net**: The BudgetStack deploys an AWS Budget with a monthly ceiling ($10 dev / $20 prod). If actual spend reaches 80% of the ceiling, an SNS alarm triggers a Lambda that **automatically destroys** the ephemeral stacks (compute, warehouse, network, observability, ingestion-role). Stateful stacks (lake, secrets, catalog, ECR) are not touched. This is a last-resort guard against forgotten `make down` sessions — if it fires, redeploy with `make up` when ready.

Additional targets: `make dbt CMD="run --select silver"`, `make rs-tunnel`, `make dq-gate`, `make reconnect`, `make profile`, `make ready`.

## Lake Layout

| Prefix        | Written by | Description                                                                                                                                        |
| ------------- | ---------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| `bronze/`     | Ingestion  | Raw Parquet, partitioned `source/entity/ingest_date/run_id`. Registered as Spectrum external tables via `dbt-external-tables` for Redshift queries |
| `silver/`     | dbt        | Conformed tables: patients, encounters, appointments, urgent_care, diagnostics, providers                                                          |
| `gold/`       | dbt        | Marts: fct_wait_times, fct_inequality, fct_urgent_care, fct_utilisation + 6 dimensions                                                             |
| `_manifests/` | Ingestion  | JSON manifest per run (idempotency + audit)                                                                                                        |
| `_dq/`        | GE         | Great Expectations validation results                                                                                                              |

## Architecture Decisions

The project documents key technical decisions as Architecture Decision Records. Highlights:

- [ADR-001: Medallion Architecture](docs/adr/ADR-001-medallion-architecture.md) - Bronze/Silver/Gold with Spectrum on Bronze
- [ADR-004: Ephemeral Infrastructure](docs/adr/ADR-004-ephemeral-infrastructure.md) - deploy/destroy pattern, ~94% cost reduction
- [ADR-008: Static Gold Export](docs/adr/ADR-008-static-gold-export.md) - DuckDB reads Parquet on Streamlit Community Cloud
- [ADR-009: Self-hosted Prefect](docs/adr/ADR-009-self-hosted-prefect.md) - Cloud push-pool incompatible with free tier
- [All 9 ADRs](docs/adr/)

## Future Work

The Gold layer and pipeline infrastructure create natural extension points. These next areas to be explored for this project are:

- **Demand forecasting** - the fct_wait_times time series lends itself to Prophet/ARIMA modelling to predict breach risk by specialty, giving Trust managers lead time to reallocate capacity
- **Referral-letter triage** - referral free-text fields could be classified to prioritise urgent pathways, reducing manual clinical triage overhead
- **Breach-rate anomaly detection** - statistical process control on fct_urgent_care 4h/12h breach rates could surface emerging pressure points before they hit aggregate targets
- **Real-time ingestion** - replacing batch ECS tasks with Kinesis Data Streams would enable sub-minute latency for time-sensitive sources like A&E arrivals

---

**License:** MIT | **Author:** [Chia A](https://github.com/chiplusplus) | [Case Study](docs/case-study.md)
