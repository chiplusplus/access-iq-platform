# Data Contract — Urgent Care Postgres Mirror

## 1) Source Overview

**Source name:** Urgent Care Postgres Mirror
**Ownership:** Trust IT / ED System Team
**Access pattern:** Read-only Postgres replica
**Cadence:** Daily incremental updates (nightly)
**Purpose in access-iq:** Urgent care flow analytics (arrival, triage, first clinician, discharge), waiting times, throughput, and cohort comparisons.

**Authoritative stance:**
Authoritative for **urgent care flow timestamps** and urgent care attendance-level facts. If similar timestamps exist elsewhere (e.g., EHR), this source wins for urgent care metrics.

---

## 2) In-Scope Tables and Schemas (Contracted)

### 2.1 urgent_care_logs

**Grain:** 1 row per urgent care attendance (encounter)
**Primary key:** `uc_encounter_id` (unique, non-null)
**Linkage key (preferred):** `patient_id` (FK to EHR) or a documented person-key if patient_id unavailable.

**Schema (expected)**
| Column | Type | Required | Notes |
|---|---:|:---:|---|
| uc_encounter_id | STRING/INT | ✅ | Canonical UC attendance key |
| patient_id | STRING/INT | ⚠️ | Preferred join to EHR; if absent, use documented linkage key |
| arrival_timestamp | TIMESTAMP | ✅ | Required for UC metrics |
| triage_timestamp | TIMESTAMP | ⚠️ | May be missing |
| first_clinician_timestamp | TIMESTAMP | ⚠️ | May be missing |
| discharge_timestamp | TIMESTAMP | ⚠️ | Often late-updated |
| provider_site_code | STRING | ⚠️ | Conformed via provider reference |
| disposition | STRING | ⛔ | Optional |
| acuity | STRING/INT | ⛔ | Optional |
| updated_at | TIMESTAMP | ⚠️ | Preferred watermark for incrementals |

**Key integrity rules**
- uc_encounter_id unique
- arrival_timestamp parseable and plausible

---

## 3) Expected Volume (Indicative)

- Append-heavy; daily inserts proportional to ED attendance
- Updates common for discharge/clinician timestamps

---

## 4) Late-Arriving and Change Behaviour

- Late documentation is expected for triage/clinician/discharge events.
- Updates can arrive days after the attendance.

**Survivorship / update rule (Silver):**
- Latest record wins by `updated_at` (preferred)
- If `updated_at` absent: rolling re-pull window (e.g., last 7–14 days) + latest by `ingested_at`

**Outliers policy:**
- Negative durations: invalid for metrics, retained for audit + DQ flags
- Implausible durations (configurable thresholds): excluded from metrics, retained + flagged

---

## 5) Idempotency Strategy

**Bronze:**
- Incremental extract by watermark (updated_at) OR rolling window strategy
- Write raw extracts to partitioned S3 with run_id + ingest_date
- Maintain manifest: run_id, watermark/window, row counts

**Silver:**
- Upsert/dedupe by `uc_encounter_id`
- Latest-wins reconciliation ensures re-runs/backfills are safe

---

## 6) Failure Handling

**Fail fast (stop + alert):**
- Missing required columns (uc_encounter_id, arrival_timestamp)
- Schema drift removing/renaming required columns
- Duplicate uc_encounter_id above threshold indicating upstream corruption

**Warn + continue (flag DQ):**
- High missingness of triage/clinician/discharge timestamps
- Low linkage rate to EHR patient_id (if applicable)
- Outlier duration spikes

---

## 7) Authoritative Conflict Rules (Explicit)

1. For urgent care waiting time metrics, **urgent_care_logs timestamps win** over any EHR-derived equivalents.
2. For patient cohort slicing, **EHR patient_demographics wins**; urgent care demographics fields (if present) are not used as the cohort truth.
3. For provider/site naming, **Provider/Site Reference wins**.

---

## 8) Summary

Urgent Care mirror is the authoritative system-of-record for ED flow timestamps used in access metrics. The contract expects late-arriving updates and treats completeness as a measured quality dimension rather than a silent assumption.
