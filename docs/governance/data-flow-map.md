# Data Flow Map

This document traces the flow of data through the Access-IQ platform, marking encryption, pseudonymisation, and access control at each hop. Structured to align with NHS DSPT (Data Security and Protection Toolkit) data flow mapping requirements.

---

## Data Flow Table

| Hop | Source                                                                    | Destination                                        | Transport                   | At-Rest Encryption                                             | Pseudonymisation                                                                                                           | Access Control                                                                                                                               |
| --- | ------------------------------------------------------------------------- | -------------------------------------------------- | --------------------------- | -------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| 1a  | Trust RDS (EHR - patients, encounters, referrals, diagnoses, urgent_care) | ECS Fargate (`ingest-postgres`)                    | TLS via VPC Peering         | N/A (in-transit)                                               | None (raw)                                                                                                                 | ECS task role with Security Group ingress to Trust RDS                                                                                       |
| 1b  | Trust SFTP (daily appointment files)                                      | ECS Fargate (`ingest-sftp`)                        | SFTP over VPC Peering       | N/A (in-transit)                                               | None (raw)                                                                                                                 | Paramiko + credentials from Secrets Manager                                                                                                  |
| 1c  | Trust S3 (diagnostics_orders, providers)                                  | ECS Fargate (`ingest-trust-s3`)                    | HTTPS (S3 API)              | SSE-S3 (Trust-side)                                            | None (raw)                                                                                                                 | IAM role-based cross-account access (IngestionRole/EcsTaskRole with `s3:GetObject` on Trust bucket)                                          |
| 2   | ECS Fargate (all three tasks)                                             | S3 Bronze (Platform data lake)                     | HTTPS (S3 API)              | KMS CMK (customer-managed, per-env key, S3 Bucket Key enabled) | None (source CSV/XLSX converted to Parquet during Bronze write)                                                            | ECS task role: write `bronze/*` + `_manifests/*` + `_dq/*` prefixes; `sns:Publish` for alerting                                              |
| 3   | S3 Bronze                                                                 | Redshift Serverless (via Spectrum external tables) | Internal AWS (Spectrum)     | KMS CMK (same lake key)                                        | None (raw, external table)                                                                                                 | Spectrum IAM role: `kms:Decrypt` + `s3:GetObject` on `bronze/*`                                                                              |
| 4   | Spectrum Bronze external tables                                           | Redshift Silver schema (internal tables)           | Internal Redshift           | Redshift namespace KMS CMK                                     | **HMAC-SHA-256** via Lambda UDF (per-env Secrets Manager key). NHS Mod-11 validation; failed records routed to quarantine. | dbt execution role: write `silver` schema. Lambda UDF role (separate from Spectrum role): `secretsmanager:GetSecretValue` for HMAC key only. |
| 5   | Redshift Silver tables                                                    | Redshift Gold schema (internal tables)             | Internal Redshift           | Redshift namespace KMS CMK                                     | Inherited from Silver (`patient_sk` surrogate key only)                                                                    | dbt execution role: write `gold` schema. DQ gate (`check_ge_gate()` macro) must pass before Gold promotion.                                  |
| 6   | Redshift Gold tables                                                      | S3 Gold export (Platform data lake)                | HTTPS (S3 API, `UNLOAD`)    | KMS CMK (same lake key)                                        | Inherited (`patient_sk`)                                                                                                   | Pipeline task role: write `gold_export/*` prefix                                                                                             |
| 7   | S3 Gold export                                                            | Streamlit Community Cloud (dashboard)              | HTTPS (S3 API, `GetObject`) | KMS CMK at rest; TLS in transit                                | Inherited (`patient_sk`). Small-cell suppression applied at Gold layer (counts < 5 suppressed).                            | IAM user: read-only on `gold_export/*` prefix                                                                                                |

---

## Key Security Controls

1. **Encryption at rest**: All platform-side data encrypted with customer-managed KMS CMK. Key policy restricts usage to platform account principals. S3 Bucket Key reduces KMS API call volume.

2. **Pseudonymisation boundary**: NHS numbers are pseudonymised at the Silver transformation step (Hop 4) using HMAC-SHA-256 with a per-environment secret key stored in AWS Secrets Manager. The key is accessible only to the Lambda UDF execution role. Raw NHS numbers never appear in Silver or Gold schemas.

3. **Quarantine isolation**: Records failing Mod-11 NHS number validation are routed to a `silver_quarantine` schema. The quarantine table retains the raw `nhs_pseudo_id` for regulator audit purposes. Access to this schema requires an explicit restricted IAM grant.

4. **Patient identifier isolation**: The `silver_keys` schema contains the `patient_identifiers` mapping table (HMAC surrogate key to original patient_id). This schema has restricted access grants separate from the main `silver` schema.

5. **Small-cell suppression**: Gold-layer inequality aggregations suppress cell counts below 5 to prevent statistical disclosure of individuals in small demographic groups.

6. **No real PII**: All data is synthetic throughout. Controls are implemented to demonstrate production intent and DSPT alignment, not because real patient data is processed.

7. **Encryption in transit**: All cross-service communication uses TLS. VPC peering eliminates public internet traversal for Trust-to-Platform data flows. S3 bucket policies enforce `aws:SecureTransport`.

8. **Prefix-scoped IAM**: Each role (ingestion, Spectrum, dbt, export, dashboard reader) is scoped to specific S3 prefixes and Redshift schemas. No role has blanket access to the data lake.
