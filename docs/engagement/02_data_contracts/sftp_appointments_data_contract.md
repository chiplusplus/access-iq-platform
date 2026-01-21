# Data Contract — SFTP Outbound Appointment Drops

## 1) Source Overview

**Source name:** SFTP Outbound Drops (Appointments/Bookings)  
**Ownership:** Trust Scheduling / PAS Team  
**Access pattern:** Nightly CSV drops under `/upload/outbound/appointments/`  
**Cadence:** Daily (expected by 07:00 local time)  
**Purpose in access-iq:** Scheduled care access metrics (appointment wait time), DNAs, cancellations, utilisation trends, service/site benchmarking.

**Authoritative stance:**  
Authoritative for **appointment booking/attendance status** and **scheduled appointment timing**. When conflicts occur between files or updates, **the latest status update wins** per rules below.

---

## 2) Delivery Contract (File-Level)

**SFTP Path:** `/upload/outbound/appointments/`  
**Expected file naming:** `appointments_YYYY-MM-DD.csv` (or includes timestamp/sequence)  
**Format:** CSV, UTF-8, header row required  
**Compression:** none (optional `.gz` supported if documented)

**File-level audit requirements (captured in manifest):**
- file_name, file_size_bytes
- checksum/etag (if available)
- row_count
- extracted_for_date (if provided)
- ingested_at timestamp

---

## 3) Schema (Contracted)

**Dataset:** appointments_export (CSV)  
**Grain (expected):** 1 row per appointment instance (preferred) OR 1 row per appointment status event (acceptable if documented)

### 3.1 Keys

**Primary key (preferred):**
- `appointment_id` (unique, non-null)

**If appointment_id unreliable/unavailable (composite key):**
- `patient_id` + `appointment_datetime` + `service_code` + `provider_site_code` (+ `booking_created_at` if available)

### 3.2 Columns (expected)

| Column | Type | Required | Notes |
|---|---:|:---:|---|
| appointment_id | STRING/INT | ⚠️ | Preferred primary key |
| patient_id | STRING/INT | ✅ | Join to EHR patient |
| service_code | STRING | ✅ | Clinic/service identifier |
| provider_site_code | STRING | ✅ | Conformed via provider reference |
| booking_created_at | TIMESTAMP/DATE | ✅ | Required for wait time (booking → appointment) |
| appointment_datetime | TIMESTAMP | ✅ | Scheduled start time |
| status | STRING | ✅ | Raw status code/text |
| status_updated_at | TIMESTAMP | ⚠️ | Strongly preferred for late updates |
| cancellation_reason | STRING | ⛔ | Optional |
| appointment_type | STRING | ⛔ | Optional (new/follow-up) |

---

## 4) Expected Volume (Indicative)

- Daily rows proportional to Trust appointment volume
- Volume anomalies (spikes/drops) are monitored and alerted

---

## 5) Late-Arriving and Change Behaviour

- Appointment statuses can change after appointment time (late coding).
- Reschedules can create multiple rows across days/files for the same logical appointment.

**Survivorship / update rule (Silver):**
- If `status_updated_at` present: keep latest by `status_updated_at`
- Else: keep latest by `ingested_at`
- If multiple distinct appointment instances exist (true reschedule creating new appointment_id), treat as separate facts

**Backfill window (recommended):**
- Re-ingest last 14 days (configurable) OR explicitly run backfills when status changes are detected.

---

## 6) Status Normalisation and Authoritative Conflict Rules (Explicit)

### 6.1 Normalised Status Groups

Raw statuses are mapped into:

- **ATTENDED**
- **DNA**
- **CANCELLED_PATIENT**
- **CANCELLED_PROVIDER**
- **RESCHEDULED**
- **UNKNOWN** (unmapped/missing)

### 6.2 Authoritative Rules for Conflicts

1. If the same appointment (by appointment_id or composite key) appears with multiple statuses:
   - **Latest status wins** (by status_updated_at, else ingested_at)
2. If one record indicates **ATTENDED** and another indicates **CANCELLED**:
   - Latest status wins; if timestamps tie, use deterministic precedence:
     - ATTENDED > DNA > CANCELLED_PROVIDER > CANCELLED_PATIENT > RESCHEDULED > UNKNOWN
3. DNA rate uses denominator **(ATTENDED + DNA)** only. Cancellations are excluded.
4. Wait time is computed only for **ATTENDED** appointments (booking_created_at → appointment_datetime).
5. Unknown/unmapped statuses are retained and counted; if UNKNOWN exceeds threshold, raise alert.

---

## 7) Idempotency Strategy

**Bronze:**
- Land raw files by ingest_date/run_id; do not mutate content
- Record each file in manifest to prevent duplicate processing
- Safe to re-run: either detect previously ingested checksum OR allow overwrite for same ingest_date/run_id

**Silver:**
- Deterministic dedupe/upsert by appointment key + latest status rule
- Rebuildable from Bronze at any time

---

## 8) Failure Handling

**Fail fast (stop + alert):**
- Missing required columns (patient_id, service_code, provider_site_code, booking_created_at, appointment_datetime, status)
- Unparseable appointment_datetime at scale (above threshold)
- File unreadable/encoding errors

**Warn + continue (flag DQ):**
- High UNKNOWN status rate
- High missing booking_created_at rate (impacts wait time)
- Duplicate rate above expected threshold

---

## 9) Summary

Appointments SFTP is the highest-risk source due to status semantics and late updates. This contract enforces explicit normalisation, latest-status survivorship, and strict idempotent ingestion with auditability so utilisation and DNA metrics remain defensible.
