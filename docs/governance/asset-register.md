# Information Asset Register

Structured to align with NHS DSPT asset management requirements (Objective A). Covers data assets processed by the Access-IQ platform. Hardware and software assets excluded (portfolio scope).

---

## Data Assets

| Asset                             | Classification           | Storage Location                                                         | Encryption       | Access Control                                                                               | Retention                               | Owner         |
| --------------------------------- | ------------------------ | ------------------------------------------------------------------------ | ---------------- | -------------------------------------------------------------------------------------------- | --------------------------------------- | ------------- |
| patient_demographics (Bronze)     | Confidential (simulated) | S3 `bronze/source=ehr_postgres/entity=patient_demographics/`             | KMS CMK          | IngestionRole, EcsTaskRole, EcsOperatorRole, PrefectWorkerRole (write), Spectrum role (read) | Append-only, no TTL                     | Platform team |
| encounters (Bronze)               | Confidential (simulated) | S3 `bronze/source=ehr_postgres/entity=encounters/`                       | KMS CMK          | IngestionRole, EcsTaskRole, EcsOperatorRole, PrefectWorkerRole (write), Spectrum role (read) | Append-only                             | Platform team |
| referrals (Bronze)                | Confidential (simulated) | S3 `bronze/source=ehr_postgres/entity=referrals/`                        | KMS CMK          | IngestionRole, EcsTaskRole, EcsOperatorRole, PrefectWorkerRole (write), Spectrum role (read) | Append-only                             | Platform team |
| diagnoses (Bronze)                | Confidential (simulated) | S3 `bronze/source=ehr_postgres/entity=diagnoses/`                        | KMS CMK          | IngestionRole, EcsTaskRole, EcsOperatorRole, PrefectWorkerRole (write), Spectrum role (read) | Append-only                             | Platform team |
| appointments (Bronze)             | Confidential (simulated) | S3 `bronze/source=sftp_appointments/entity=appointments/`                | KMS CMK          | IngestionRole, EcsTaskRole, EcsOperatorRole, PrefectWorkerRole (write), Spectrum role (read) | Append-only                             | Platform team |
| urgent_care_logs (Bronze)         | Confidential (simulated) | S3 `bronze/source=urgent_care_postgres/entity=urgent_care_logs/`         | KMS CMK          | IngestionRole, EcsTaskRole, EcsOperatorRole, PrefectWorkerRole (write), Spectrum role (read) | Append-only                             | Platform team |
| diagnostics_orders (Bronze)       | Confidential (simulated) | S3 `bronze/source=trust_s3_diagnostics/entity=diagnostics_orders/`       | KMS CMK          | IngestionRole, EcsTaskRole, EcsOperatorRole, PrefectWorkerRole (write), Spectrum role (read) | Append-only                             | Platform team |
| provider_site_reference (Bronze)  | Internal                 | S3 `bronze/source=trust_s3_provider_ref/entity=provider_site_reference/` | KMS CMK          | IngestionRole, EcsTaskRole, EcsOperatorRole, PrefectWorkerRole (write), Spectrum role (read) | Append-only                             | Platform team |
| Silver models (10 tables)         | Pseudonymised            | Redshift `silver` schema                                                 | Redshift KMS CMK | dbt role (write), analyst role (read)                                                        | Rebuilt each session                    | Platform team |
| patient_identifiers (Silver keys) | Restricted               | Redshift `silver_keys` schema                                            | Redshift KMS CMK | dbt role (write), restricted grant only                                                      | Rebuilt each session                    | Platform team |
| quarantine (Silver)               | Restricted               | Redshift `silver_quarantine` schema                                      | Redshift KMS CMK | dbt role (write), restricted grant only                                                      | Rebuilt each session                    | Platform team |
| Gold marts (10 tables)            | Aggregated / Public      | Redshift `gold` schema + S3 `gold_export/` export                        | KMS CMK          | dbt role (write), public read (S3 Gold export)                                               | Rebuilt each session                    | Platform team |
| Gold Parquet export               | Aggregated / Public      | S3 `gold_export/` prefix                                                 | KMS CMK          | Export task role (write), DashboardReaderUser (read)                                         | Overwritten each pipeline run           | Platform team |
| Ingestion manifests               | Operational              | S3 `_manifests/` prefix                                                  | KMS CMK          | ECS task role (write), ops team (read)                                                       | Append-only                             | Platform team |
| Data quality results              | Operational              | S3 `_dq/` prefix                                                         | KMS CMK          | Great Expectations task (write), ops team (read)                                             | Overwritten each pipeline run           | Platform team |
| DashboardReaderUser               | Operational              | IAM user with access key                                                 | N/A              | S3 `gold_export/` read, Secrets Manager dashboard-reader secret                              | Managed by CDK                          | Platform team |
| PrefectWorkerRole                 | Operational              | IAM role                                                                 | N/A              | Orchestration role for Prefect agent, S3 and ECS access                                      | Managed by CDK                          | Platform team |
| EcsOperatorRole                   | Operational              | IAM role                                                                 | N/A              | Control-plane role for ECS RunTask                                                           | Managed by CDK                          | Platform team |
| HMAC pseudonymisation key         | Secret                   | AWS Secrets Manager (`access-iq/{env}/pseudonymisation-key`)             | KMS CMK          | Lambda UDF role (read only)                                                                  | RETAIN in prod, DESTROY in dev, per-env | Platform team |
| Redshift admin password           | Secret                   | Auto-managed by Redshift (`manage_admin_password=True`)                  | KMS CMK          | Redshift service (managed), session script (read for DSN)                                    | Managed by Redshift, per-env            | Platform team |
| Dashboard reader credentials      | Secret                   | AWS Secrets Manager (`access-iq/{env}/dashboard-reader`)                 | KMS CMK          | DashboardReaderUser (read only)                                                              | RETAIN in prod, DESTROY in dev, per-env | Platform team |

---

## Classification Definitions

| Classification           | Description                                                                                                                                    | Example                                 |
| ------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------- |
| Confidential (simulated) | Synthetic data modelled on NHS patient-level records. Treated as confidential to demonstrate production controls.                              | Bronze patient demographics, encounters |
| Pseudonymised            | Data where direct identifiers (NHS number) have been replaced with HMAC-SHA-256 surrogate keys. Remains personal data under UK GDPR Art. 4(5). | Silver models                           |
| Restricted               | Data requiring elevated access controls - either raw identifiers retained for audit or mapping tables that could re-identify individuals.      | Quarantine table, patient_identifiers   |
| Aggregated / Public      | Data aggregated to a level where individual identification is not possible. Small-cell suppression applied where counts fall below 5.          | Gold fact and dimension tables          |
| Secret                   | Cryptographic material or credentials. Must not appear in code, logs, or version control.                                                      | HMAC key, Redshift password             |
| Operational              | Platform metadata supporting auditability and idempotency. No patient-level content.                                                           | Ingestion manifests                     |
| Internal                 | Non-patient reference data (provider sites, staff excluded per Caldicott).                                                                     | Providers Bronze table                  |

---

## Notes

- All classifications assume synthetic data. If real patient data were introduced, Confidential assets would require formal DPIA (Data Protection Impact Assessment) and Caldicott Guardian sign-off.
- Retention of "Append-only" Bronze assets means no deletion or overwriting. Each ingestion run creates a new `run_id` partition.
- "Rebuilt each session" means Silver and Gold tables are recreated from Bronze on each `make up` + `make pipeline` cycle. No state persists between sessions except Bronze and manifests.
- Provider `site_manager_name` and `site_manager_email` fields are excluded at Silver transformation per Caldicott minimisation principles (see ADR-008).
