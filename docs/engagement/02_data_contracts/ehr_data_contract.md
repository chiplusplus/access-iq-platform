# Data Contract - EHR Postgres Mirror

## 1) Source Overview

**Source name:** EHR Postgres Mirror
**Ownership:** Trust IT / Clinical Systems
**Access pattern:** Read-only Postgres replica
**Cadence:** Daily incremental updates (nightly)
**Purpose in access-iq:** Patient cohort attributes + encounter-level activity for access, utilisation, and inequality analysis.

**Authoritative stance:**
- Authoritative for **patient demographics** (as current-state attributes) and **encounter records** originating in the EHR domain.
- Not authoritative for urgent care flow timestamps (see Urgent Care mirror).

---

## 2) In-Scope Tables and Schemas (Contracted)

> Types below are *contract expectations* for analytics ingestion. If upstream differs, the ingestion layer must cast/standardise or fail fast for breaking changes.

### 2.1 patient_demographics

**Grain:** 1 row per patient (current-state snapshot)
**Primary key:** `patient_id` (unique, non-null)

**Schema (expected)**
| Column | Type | Required | Notes |
|---|---:|:---:|---|
| patient_id | STRING/INT | ✅ | Canonical patient key |
| date_of_birth | DATE | ✅ | Used for age bands |
| sex | STRING | ⚠️ | May be missing/inconsistent |
| ethnicity | STRING | ⚠️ | High missingness possible |
| postcode | STRING | ⚠️ | Partial/outdated possible |
| registration_date | DATE | ⛔ | Optional |
| updated_at | TIMESTAMP | ⚠️ | Preferred for incremental loads |

**Key integrity rules**
- `patient_id` must be unique
- `date_of_birth` must be parseable and plausible (e.g., not in future)

---

### 2.2 encounters

**Grain:** 1 row per encounter
**Primary key:** `encounter_id` (unique, non-null)
**Foreign key:** `patient_id` → patient_demographics.patient_id

**Schema (expected)**
| Column | Type | Required | Notes |
|---|---:|:---:|---|
| encounter_id | STRING/INT | ✅ | Canonical encounter key |
| patient_id | STRING/INT | ✅ | Join to patient |
| encounter_type | STRING | ✅ | e.g. outpatient/inpatient (urgent care may also appear but is not authoritative for flow timestamps) |
| arrival_timestamp | TIMESTAMP | ⚠️ | May be missing |
| discharge_timestamp | TIMESTAMP | ⚠️ | May be late-updated |
| provider_site_code | STRING | ⚠️ | Conformed via provider reference |
| service_line | STRING | ⛔ | Optional |
| updated_at | TIMESTAMP | ⚠️ | Preferred for incremental loads |

**Key integrity rules**
- encounter_id unique
- patient_id non-null; orphaned encounters are retained but flagged

---

### 2.3 diagnoses (Optional)

**Grain:** 1 row per (encounter_id, diagnosis_code)
**Key:** (encounter_id, diagnosis_code)

**Schema (expected)**
| Column | Type | Required |
|---|---:|:---:|
| encounter_id | STRING/INT | ✅ |
| diagnosis_code | STRING | ✅ |
| diagnosis_system | STRING | ⛔ |
| recorded_at | TIMESTAMP | ⛔ |

---

### 2.4 procedures (Optional)

**Grain:** 1 row per (encounter_id, procedure_code)
**Key:** (encounter_id, procedure_code)

**Schema (expected)**
| Column | Type | Required |
|---|---:|:---:|
| encounter_id | STRING/INT | ✅ |
| procedure_code | STRING | ✅ |
| procedure_system | STRING | ⛔ |
| recorded_at | TIMESTAMP | ⛔ |

---

## 3) Expected Volume (Indicative)

- **patient_demographics:** low change rate; size proportional to registered population; daily delta typically small
- **encounters:** append-heavy; daily inserts proportional to Trust activity; late updates expected

> Portfolio note: treat “volume” as monitored rather than fixed; implement daily row-count anomaly checks.

---

## 4) Late-Arriving and Change Behaviour

- Demographics may be corrected after initial capture (ethnicity/postcode updates).
- Encounter records may be updated after the fact (e.g., discharge timestamp).
- Hard deletes are not expected; if encountered, treat as a data incident.

**Survivorship / update rule (Silver):**
- Latest record wins by `updated_at` (preferred)
- If `updated_at` absent, use ingestion timestamp (`ingested_at`) and deterministic tie-breakers

---

## 5) Idempotency Strategy

**Bronze (raw landing):**
- Extract in batches by watermark; write to partitioned S3 path (by source + ingest_date/run_id)
- Maintain an ingestion manifest: run_id, watermark range, row count, extract timestamp

**Silver (reconciliation):**
- Dedupe/upsert by primary key (patient_id, encounter_id)
- Latest-wins strategy as above ensures safe re-runs and backfills

---

## 6) Failure Handling

**Fail fast (pipeline stop + alert):**
- Missing required columns for contracted tables
- Primary key nulls above threshold
- Breaking schema drift (rename/remove required columns)

**Warn + continue (flagged in DQ):**
- Ethnicity/postcode missingness above threshold
- Orphaned encounters (patient_id not found)
- Timestamp plausibility outliers

---

## 7) Authoritative Conflict Rules (Explicit)

When conflicts occur between sources for similar concepts:

1. **Urgent care flow timestamps** (arrival/triage/clinician/discharge for ED flow): **Urgent Care Postgres Mirror wins.**
2. **Patient demographics** used for cohort slicing: **EHR patient_demographics wins** (current-state snapshot), with missingness surfaced as `Unknown`.
3. **Provider/site naming and grouping:** **Provider/Site Reference wins**; codes not found are labelled `Unknown` and counted.
4. If an encounter appears in multiple extracts with differing fields, **latest update wins** per survivorship rules.

---

## 8) Summary

The EHR mirror is the foundational source for patient cohorts and encounter activity. It is authoritative for demographics and encounter presence, while urgent care timing is sourced from the dedicated urgent care system for higher fidelity.
