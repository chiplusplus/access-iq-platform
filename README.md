# access-iq-platform

NHS Trust access-and-inequality analytics platform. Ingests operational healthcare
data through a Bronze/Silver/Gold medallion architecture and surfaces analytics
via a Streamlit dashboard. Two AWS accounts model a vendor-client boundary
(Trust account + Platform account); all infrastructure is CDK-managed.

## Infrastructure stacks

All stacks follow the naming convention `{kind}-{app_name}-{env_name}`.

### Stateful (RemovalPolicy.RETAIN)

| Stack | Resource | Notes |
|---|---|---|
| `lake-access-iq-{env}` (LakeStack) | KMS CMK + S3 lake bucket | KMS key RETAIN in both envs; S3 bucket RETAIN in prod, DESTROY in dev. See `docs/adr/0003-kms-cmk-on-lake.md`. |
| `secrets-access-iq-{env}` (SecretsStack) | Secrets Manager pseudonymisation key | Encrypted by the lake CMK. RETAIN avoids 7-30 day pending-deletion window. |
| `catalog-access-iq-{env}` (CatalogStack) | Glue database (`access-iq-{env}-bronze`) | Placeholder for Phase 4 `dbt-external-tables` partition registration. |
| `ecr-access-iq-{env}` (EcrStack) | ECR repository (`access-iq-{env}-ingestion`) | Immutable tags, scan-on-push, lifecycle retains last 20 untagged images. |

### Stateless

| Stack | Resource | Notes |
|---|---|---|
| `ingestion-role-access-iq-{env}` (IngestionRoleStack) | IAM role for the ingestion principal | Assumed by SSO user; Phase 3 migrates to ECS task role. Scoped to `bronze/*` + `_manifests/*` writes. |

ADRs: `docs/adr/0003-kms-cmk-on-lake.md` · `docs/adr/0004-12factor-config.md`

**First-time deploy ordering:** LakeStack → SecretsStack → CatalogStack/EcrStack → IngestionRoleStack.
If the dev bucket already exists from a prior SSE-S3 stack, delete it first: `aws s3 rb s3://access-iq-dev-{account_id} --force`.

## Lake layout

The platform S3 bucket (`access-iq-{env}-{account_id}`) uses a fixed prefix
contract — see `infra/access_iq_infra/lake_layout.py` for the constants.

| Prefix | Owner | Description |
|---|---|---|
| `bronze/` | Ingestion (Phase 1+) | Raw source data. Partitioned by `source=…/entity=…/ingest_date=YYYY-MM-DD/run_id=<uuid>/`. |
| `silver/` | dbt (Phase 5) | Conformed Silver tables: patients, encounters, appointments, urgent_care, diagnostics, providers. |
| `gold/` | dbt (Phase 6) | Marts: `fct_wait_times`, `fct_inequality`, `fct_urgent_care`, `fct_utilisation`. |
| `_manifests/` | Ingestion | One JSON manifest per Bronze ingest run (idempotency + audit). |
| `_dq/` | GE (Phase 6) | Great Expectations validation results JSON. |

All writes are SSE-KMS using the LakeStack CMK. Cross-prefix writes are blocked
by IAM (Bronze writers cannot write `silver/`; etc) — see `IngestionRoleStack`.
