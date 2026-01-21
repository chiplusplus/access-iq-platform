# access-iq — Delivery Plan

## Purpose of This Document

This document defines the delivery plan for the access-iq engagement.  
It translates scope, metrics, data contracts, and risks into a **structured execution plan** with clear phases, checkpoints, and acceptance criteria.

The plan is designed to:
- Deliver a portfolio-grade analytics platform within ~6 weeks
- Prioritise senior-consultant quality over breadth
- Reduce rework through explicit sequencing and milestones

---

## Delivery Principles

- Build foundations before features
- Optimise for clarity, traceability, and trust
- Prefer fewer end-to-end pipelines over many partial ones
- Make progress visible at least every two weeks
- Treat documentation as a first-class deliverable

---

## High-Level Timeline (Indicative)

| Week | Focus |
|-----:|------|
| 0 | Engagement framing & contracts |
| 1 | Platform foundations & environments |
| 2 | Bronze ingestion (core sources) |
| 3 | Silver modelling & data quality |
| 4 | Gold marts & metric validation |
| 5 | Dashboard, observability, and CI/CD |
| 6 | Hardening, documentation, and case study |

Dates are indicative and may flex to maintain quality.

---

## Phase 0 — Engagement Setup

**Deliverables**
- Context, scope, metric definitions
- Data contracts for all sources
- Risks and assumptions

**Exit Criteria**
- All Phase 0 documents approved and versioned
- No ambiguity on metrics or scope

---

## Phase 1 — Platform Foundations

### Objectives
- Establish a professional, production-grade baseline
- Enable safe iteration via environments and CI

### Key Tasks
- Repository scaffolding (Python, dbt, CI, linting)
- AWS CDK baseline (S3, IAM, Redshift, logging)
- Environment separation (dev/test/prod)
- Secrets management and security baseline

### Deliverables
- Reproducible local dev environment
- Parameterised CDK stacks
- CI pipeline with basic checks

### Acceptance Criteria
- New developer can run `make setup` and deploy dev environment
- No secrets committed to repo
- CI fails on lint/test errors

---

## Phase 2 — Bronze Ingestion

### Objectives
- Reliably land raw data from all sources
- Preserve source truth with auditability

### In-Scope Sources
- EHR Postgres mirror
- Urgent care Postgres mirror
- SFTP appointments drops
- Trust S3 diagnostics exports
- Trust S3 provider/site reference

### Key Tasks
- S3 Bronze layout definition
- Incremental ingestion logic per contract
- Prefect flows and schedules
- File- and batch-level auditing

### Deliverables
- Bronze datasets partitioned by source and ingest date
- Prefect flows with retries and logging
- Freshness and volume checks

### Acceptance Criteria
- Pipelines are idempotent
- Missing/late data triggers alerts
- Raw data can be reprocessed deterministically

---

## Phase 3 — Silver Layer & Data Quality

### Objectives
- Standardise, dedupe, and reconcile messy operational data
- Surface data quality issues explicitly

### Key Tasks
- dbt Silver models per source
- Surrogate keys and survivorship rules
- Conformed dimensions (patient, provider/site)
- Great Expectations checks at Bronze→Silver boundary

### Deliverables
- Cleaned, typed Silver tables
- Data quality reports stored and inspectable
- dbt tests enforcing integrity rules

### Acceptance Criteria
- Late-arriving updates reconcile correctly
- Orphaned or invalid records are flagged, not dropped
- Known data issues are measurable

---

## Phase 4 — Gold Layer & Metrics

### Objectives
- Implement metric-ready marts aligned to definitions
- Enable fast, consistent analytical queries

### Key Tasks
- Dimensional modelling (facts + dimensions)
- Metric aggregation marts (access, utilisation, inequality)
- Distributional statistics (median, P90)
- dbt docs and lineage generation

### Deliverables
- Gold tables matching metric definitions
- Versioned metric logic
- Clear lineage from source to metric

### Acceptance Criteria
- Every dashboard metric maps to a Gold model
- Metric outputs match definitions exactly
- Lineage graph is complete and interpretable

---

## Phase 5 — Product Layer & Observability

### Objectives
- Deliver stakeholder-facing insights
- Ensure reliability and visibility of platform health

### Key Tasks
- Streamlit dashboard (MLP scope)
- Parameterised filters and cohort views
- CloudWatch logging and alerts
- CI/CD for infra, dbt, and app

### Deliverables
- Deployed dashboard backed by Gold marts
- Alerting on pipeline failures and freshness breaches
- Automated deployments to dev/prod

### Acceptance Criteria
- Dashboard answers core stakeholder questions
- Failures are visible and actionable
- Deployments are repeatable and low-friction

---

## Phase 6 — Hardening & Portfolio Packaging

### Objectives
- Make the project explainable, maintainable, and credible
- Package the work as a senior-level case study

### Key Tasks
- Performance and cost review
- Architecture and data flow diagrams
- ADRs documenting key decisions
- Case study write-up with screenshots

### Deliverables
- Complete README and onboarding guide
- Architecture diagrams embedded in repo
- Written case study suitable for portfolio

### Acceptance Criteria
- Third party can run and understand the platform
- Trade-offs and limitations are explicit
- Project reads as a real consultancy engagement

---

## Minimum Lovable Product (MLP)

The MLP includes:
- End-to-end ingestion → Silver → Gold for all core sources
- Access, inequality, and utilisation metrics
- Three dashboard pages:
  1. Access & Waiting Times
  2. Inequality Lens
  3. Utilisation & Flow
- Data quality checks that can fail visibly
- Full documentation of decisions and limitations

---

## Deferred / Phase 2 Scope

Explicitly deferred items:
- Risk adjustment or case-mix modelling
- Predictive analytics
- Real-time ingestion
- Advanced geospatial analysis
- Patient-level operational drill-downs

---

## Delivery Governance

- Weekly self-review against acceptance criteria
- Phase exit reviews before progressing
- Scope changes require explicit documentation

---

## Summary

This delivery plan prioritises quality, traceability, and trust.  
By sequencing work deliberately and defining clear acceptance criteria, access-iq is positioned to deliver a portfolio-grade analytics platform that reflects senior data engineering practice.
