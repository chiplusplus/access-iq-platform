# Data Contract — Trust S3 Diagnostics Orders Exports (CSV)

## 1) Source Overview

**Source name:** Trust-owned S3 Exports (Diagnostics Orders)
**Ownership:** Trust Diagnostics / Informatics Team
**Access pattern:** Daily CSV exports in Trust S3 bucket (partitioned by export date)
**Cadence:** Daily (expected by 07:00 local time)
**Purpose in access-iq:** Diagnostics utilisation trends and (where available) turnaround metrics (order → result).

**Authoritative stance:**
Trust S3 exports are the **source of truth** for diagnostics extracts used by access-iq. The simulator local cache is development-only and never treated as authoritative.

---

## 2) Delivery Contract (S3 Object-Level)

**Bucket:** Provided via environment config
**Prefix/partitioning (expected):** `diagnostics_orders/export_date=YYYY-MM-DD/`
**Format:** CSV, UTF-8, header row required
**Overwrite behavior:** Partitions may be overwritten/corrected.

**Object-level audit requirements (manifest):**
- export_date
- object keys + sizes
- row counts (if computed)
- last_modified / version_id (if available)
- ingested_at

---

## 3) Schema (Contracted)

**Dataset:** diagnostics_orders_export (CSV)
**Grain:** 1 row per diagnostic order (or order line; must be consistent and documented)

### 3.1 Keys

**Primary key (preferred):**
- `order_id` (unique, non-null)

**If order_id unavailable (composite key):**
- `patient_id` + `order_timestamp` + `test_code` + `provider_site_code`

### 3.2 Columns (expected)

| Column | Type | Required | Notes |
|---|---:|:---:|---|
| order_id | STRING/INT | ⚠️ | Preferred primary key |
| patient_id | STRING/INT | ⚠️ | Join to EHR if available |
| order_timestamp | TIMESTAMP | ✅ | Required |
| result_timestamp | TIMESTAMP | ⚠️ | Optional; required for turnaround |
| test_code | STRING | ✅ | Or test_name if codes absent |
| test_name | STRING | ⚠️ | Optional |
| provider_site_code | STRING | ✅ | Conformed via provider reference |
| ordering_service | STRING | ⛔ | Optional |
| updated_at | TIMESTAMP | ⛔ | Optional |

---

## 4) Expected Volume (Indicative)

- Daily rows proportional to diagnostics activity; monitored for anomalies
- Missing partitions or sudden volume drops trigger alerts

---

## 5) Late-Arriving and Change Behaviour

- Results may appear after initial order export; result_timestamp may be populated later.
- Exports may be corrected via partition overwrite.

**Survivorship / update rule (Silver):**
- Upsert/dedupe by order_id (preferred) using updated_at if available
- Else by composite key + latest ingested_at
- Turnaround metrics computed only when both timestamps present and valid

---

## 6) Idempotency Strategy

**Bronze:**
- Partition-based landing by export_date; retain raw files exactly
- Re-run for export_date overwrites Bronze partition (or writes new run_id and Silver picks latest) — choose one and document in ADR

**Silver:**
- Deterministic upsert/dedupe by key + latest record
- Supports backfill for date range

---

## 7) Failure Handling

**Fail fast (stop + alert):**
- Missing required columns (order_timestamp, provider_site_code, test_code/test_name)
- Unparseable timestamps above threshold
- Missing daily partition (freshness SLA breach) depending on severity level (dev/test fail; prod alert)

**Warn + continue (flag DQ):**
- High missing result_timestamp rate (turnaround not interpretable)
- High unmapped test_code rate (if mapping used)
- Duplicate rate spikes

---

## 8) Authoritative Conflict Rules (Explicit)

1. For diagnostics metrics, **Trust S3 exports win** over any local cache or secondary sources.
2. If the same order appears in multiple partitions (historical window exports), **latest ingested record wins** by updated_at/ingested_at.
3. Provider/site grouping uses **Provider/Site Reference** as conformance; unknown codes are mapped to `Unknown` and counted.

---

## 9) Summary

Diagnostics exports are authoritative but may be incomplete for turnaround. The contract is designed around partition-based ingestion, explicit backfill, and conservative metric calculation with visible completeness indicators.
