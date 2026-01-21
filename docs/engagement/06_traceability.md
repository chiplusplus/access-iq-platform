# access-iq — Traceability Matrix

## Purpose of This Document

This document maps **stakeholder questions → defined metrics → Gold marts → upstream sources**.
It ensures:
- Every dashboard view is defensible and traceable
- Metric logic aligns with `03_metric_definitions.md`
- Engineering tasks in Phase 1–4 map directly to stakeholder value

---

## Notation

- **Sources**
  - **EHR** = EHR Postgres mirror (patient_demographics, encounters, optional diagnoses/procedures)
  - **UC** = Urgent Care Postgres mirror (urgent_care_logs)
  - **SFTP_APPT** = SFTP appointments drops (appointments_export)
  - **S3_DIAG** = Trust S3 diagnostics exports (diagnostics_orders_export)
  - **REF_SITE** = Trust S3 provider/site reference (provider_site_reference)

- **Layers**
  - **Bronze**: raw landed datasets
  - **Silver**: standardised, deduped, conformed
  - **Gold**: dimensional facts/dims + metric marts

---

## Gold Data Model (Planned)

### Conformed Dimensions
- `dim_patient` (from EHR patient_demographics; enriched with age bands, geography, deprivation proxy where available)
- `dim_provider_site` (from REF_SITE)
- `dim_service` (from service_code/clinic/service_line across sources; conformed in Silver)
- `dim_date` (calendar + ISO week attributes)

### Core Facts (Gold)
- `fact_urgent_care_attendance` (from UC)
- `fact_appointments` (from SFTP_APPT)
- `fact_diagnostics_orders` (from S3_DIAG)
- `fact_encounters` (from EHR encounters; used primarily for broader utilisation context)

### Metric Marts (Gold)
- `mart_access_wait_times_uc` (UC wait times: median, P90, counts, completeness)
- `mart_access_wait_times_appt` (appointment wait times: median, P90, distribution buckets)
- `mart_utilisation_appointments` (volumes, DNA rates, cancellations)
- `mart_flow_urgent_care` (LOS, stage delays, bottleneck rates)
- `mart_diagnostics_utilisation` (orders volume, turnaround where available, completeness)
- `mart_provider_benchmarking` (provider/site-level comparisons across key KPIs)
- `mart_inequality_summary` (cohort comparisons across selected KPIs with DQ indicators)

---

## Question → Metric → Mart → Sources Matrix

### Q1. Where are the longest access delays occurring, and for whom?

| KPI / Metric | Definition Reference | Gold Mart(s) | Primary Fact(s) | Source(s) | Key Cohort Slices |
|---|---|---|---|---|---|
| Arrival→Triage time (median, P90) | 03 (1) | mart_access_wait_times_uc | fact_urgent_care_attendance | UC + REF_SITE + EHR | ethnicity, IMD proxy, age band, sex, site, month |
| Triage→Clinician time (median, P90) | 03 (2) | mart_access_wait_times_uc | fact_urgent_care_attendance | UC + REF_SITE + EHR | same |
| Arrival→Discharge LOS (median, P90) | 03 (3) | mart_flow_urgent_care | fact_urgent_care_attendance | UC + REF_SITE + EHR | same |
| Appointment wait time (median, P90) | 03 (4) | mart_access_wait_times_appt | fact_appointments | SFTP_APPT + REF_SITE + EHR | ethnicity, IMD proxy, age band, sex, service, site, month |
| Diagnostics turnaround time (median, P90 where valid) | 03 (5) | mart_diagnostics_utilisation | fact_diagnostics_orders | S3_DIAG + REF_SITE + EHR (optional) | cohort slices where patient linkage exists |

**Notes**
- UC timestamps are authoritative for UC flow.
- Appointment wait time computed only for ATTENDED appointments.
- Diagnostics turnaround displayed with completeness warnings.

---

### Q2. Are there systematic differences in access by ethnicity, deprivation, age, or geography?

| KPI / Metric | Definition Reference | Gold Mart(s) | Source(s) | Display Guardrails |
|---|---|---|---|---|
| UC wait times by cohort | 03 (1–3) | mart_inequality_summary + mart_access_wait_times_uc | UC + EHR + REF_SITE | show Unknown explicitly; warn if missingness > threshold |
| Appointment wait times by cohort | 03 (4) | mart_inequality_summary + mart_access_wait_times_appt | SFTP_APPT + EHR + REF_SITE | exclude cancellations/DNAs from wait time; show volume context |
| DNA rate by cohort | 03 (7) | mart_inequality_summary + mart_utilisation_appointments | SFTP_APPT + EHR + REF_SITE | denominator (ATTENDED + DNA) only |
| Diagnostics utilisation/turnaround by cohort | 03 (5) | mart_inequality_summary + mart_diagnostics_utilisation | S3_DIAG (+EHR if link) + REF_SITE | turnaround only when timestamps valid |

---

### Q3. Which providers or sites are outliers in terms of access performance?

| KPI / Metric | Definition Reference | Gold Mart(s) | Source(s) | Benchmarking Guardrails |
|---|---|---|---|---|
| Provider/site UC wait time variance | 03 (9–10) | mart_provider_benchmarking + mart_access_wait_times_uc | UC + REF_SITE | show volumes + confidence; avoid ranking language |
| Provider/site appointment wait time variance | 03 (9–10) | mart_provider_benchmarking + mart_access_wait_times_appt | SFTP_APPT + REF_SITE | show volumes + service mix |
| Provider/site DNA rate variance | 03 (7, 10) | mart_provider_benchmarking + mart_utilisation_appointments | SFTP_APPT + REF_SITE | show denominator and cancellations separately |
| Provider/site diagnostics volume/turnaround | 03 (5, 10) | mart_provider_benchmarking + mart_diagnostics_utilisation | S3_DIAG + REF_SITE | turnaround with completeness context |

---

### Q4. Where are DNA rates highest, and among which cohorts?

| KPI / Metric | Definition Reference | Gold Mart(s) | Source(s) | Notes |
|---|---|---|---|---|
| DNA rate (overall, by cohort, by service) | 03 (7) | mart_utilisation_appointments + mart_inequality_summary | SFTP_APPT + EHR + REF_SITE | cancellations excluded; Unknown statuses tracked |
| Appointment volumes (denominators) | 03 (6) | mart_utilisation_appointments | SFTP_APPT + REF_SITE | always displayed alongside DNA rate |
| Cancellation rate (patient vs provider) | (from contracts) | mart_utilisation_appointments | SFTP_APPT + REF_SITE | supports interpretation of DNA drivers |

---

### Q5. How does urgent care flow vary across patient groups and over time?

| KPI / Metric | Definition Reference | Gold Mart(s) | Source(s) | Notes |
|---|---|---|---|---|
| Stage delays (arrival→triage, triage→clinician) | 03 (1–2) | mart_flow_urgent_care + mart_access_wait_times_uc | UC + EHR + REF_SITE | completeness displayed |
| LOS (arrival→discharge) | 03 (3) | mart_flow_urgent_care | UC + EHR + REF_SITE | outlier handling documented |
| Bottleneck indicators (e.g., % > threshold) | derived | mart_flow_urgent_care | UC + REF_SITE | thresholds documented in mart schema |

---

### Q6. Are access gaps improving or worsening over time?

| KPI / Metric | Definition Reference | Gold Mart(s) | Source(s) | Trend Approach |
|---|---|---|---|---|
| UC wait times trends | 03 (Trend) | mart_access_wait_times_uc | UC + REF_SITE | monthly + rolling windows |
| Appointment wait times trends | 03 (Trend) | mart_access_wait_times_appt | SFTP_APPT + REF_SITE | exclude partial periods |
| DNA rate trends | 03 (Trend) | mart_utilisation_appointments | SFTP_APPT + REF_SITE | show denominator |
| Diagnostics trends | 03 (Trend) | mart_diagnostics_utilisation | S3_DIAG + REF_SITE | completeness flagged |

---

## Dashboard Page Traceability (MLP)

### Page 1 — Access & Waiting Times
**Primary marts**
- mart_access_wait_times_uc
- mart_access_wait_times_appt
- mart_provider_benchmarking

**Questions covered**
- Q1, Q3, Q6

---

### Page 2 — Inequality Lens
**Primary marts**
- mart_inequality_summary
- mart_access_wait_times_uc
- mart_access_wait_times_appt
- mart_utilisation_appointments

**Questions covered**
- Q1, Q2, Q4, Q6

---

### Page 3 — Utilisation & Flow
**Primary marts**
- mart_flow_urgent_care
- mart_utilisation_appointments
- mart_diagnostics_utilisation

**Questions covered**
- Q1, Q4, Q5, Q6

---

## Engineering Implications (What This Forces)

- Silver must produce conformed keys for patient, provider/site, service, and dates.
- Gold must include both:
  - distributional stats (median, P90)
  - quality indicators (completeness, Unknown rates, linkage rates)
- Every dashboard query must come from marts only (no raw querying).

---

## Change Control

If any of the following change, this document must be updated:
- Metric definitions (`03_metric_definitions.md`)
- Source contracts (`02_data_contracts/*`)
- MLP dashboard scope (`01_scope_success.md`)

All changes are versioned in Git to preserve auditability and narrative consistency.
