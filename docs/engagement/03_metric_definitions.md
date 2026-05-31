# access-iq - Metric Definitions

## Purpose of This Document

This document defines the core metrics produced by the access-iq platform.
It acts as the **single source of truth** for how access, utilisation, and inequality metrics are calculated, interpreted, and displayed.

All downstream models, dashboards, and analyses must align with these definitions.
Where trade-offs or assumptions exist, they are documented explicitly.

---

## General Principles

The following principles apply to all metrics unless stated otherwise:

- Metrics are **derived from operational data**, not self-reported aggregates
- All metrics are **time-bound** and analysable over consistent periods
- Cohort breakdowns are first-class, not optional
- Missing or unknown values are represented explicitly
- Metrics are defined at a **clear grain** (event, appointment, encounter, patient-period)

---

## Time Windows and Aggregation

### Reporting Periods
- Daily (for ingestion validation only)
- Weekly (ISO week)
- Monthly (calendar month)

Unless stated otherwise:
- **Trend charts** use monthly aggregation
- **Comparisons and benchmarking** use rolling 3-month windows to reduce noise

Partial periods (e.g. current month) are flagged and may be excluded from comparisons.

---

## Core Access Metrics

### 1. Arrival → Triage Time (Urgent Care)

**Definition**
Time elapsed between a patient’s arrival at urgent care and recorded triage timestamp.

**Formula**
```
triage_timestamp - arrival_timestamp
```

**Grain**
Urgent care encounter

**Inclusions**
- Encounters with both arrival and triage timestamps present
- First triage event only

**Exclusions**
- Encounters missing either timestamp
- Negative or implausible durations (e.g. >24 hours)

**Notes**
- Measures initial access to clinical assessment
- Missing triage data is treated as a data quality issue, not zero wait

---

### 2. Triage → First Clinician Time (Urgent Care)

**Definition**
Time elapsed between triage and first clinician contact.

**Formula**
```
first_clinician_timestamp - triage_timestamp
```

**Grain**
Urgent care encounter

**Inclusions**
- Encounters with triage and clinician timestamps present

**Exclusions**
- Missing timestamps
- Negative or implausible durations

**Notes**
- Used to identify bottlenecks post-triage
- Highly sensitive to documentation quality

---

### 3. Arrival → Discharge Time (Urgent Care LOS)

**Definition**
Total length of stay in urgent care.

**Formula**
```
discharge_timestamp - arrival_timestamp
```

**Grain**
Urgent care encounter

**Inclusions**
- Completed encounters only

**Exclusions**
- Ongoing encounters
- Missing discharge timestamp

**Notes**
- Used for throughput and flow analysis
- Not interpreted as a quality-of-care outcome

---

### 4. Appointment Wait Time

**Definition**
Time between appointment booking date and attended appointment date.

**Formula**
```
appointment_date - booking_date
```

**Grain**
Appointment

**Inclusions**
- Appointments with status = `attended`
- First booking instance only

**Exclusions**
- Cancelled appointments
- DNAs
- Rebookings unless explicitly analysed separately

**Notes**
- Reflects access to scheduled care
- Rebookings and cancellations are handled as separate utilisation signals

---

### 5. Diagnostic Turnaround Time (where available)

**Definition**
Time between diagnostic order and result availability.

**Formula**
```
result_timestamp - order_timestamp
```

**Grain**
Diagnostic order

**Inclusions**
- Orders with both timestamps present

**Exclusions**
- Missing timestamps
- Outlier durations (configurable threshold)

**Notes**
- Used cautiously due to variability in export completeness
- Always accompanied by data completeness indicators

---

## Utilisation and Demand Metrics

### 6. Appointment Volume

**Definition**
Count of scheduled appointments.

**Grain**
Appointment

**Dimensions**
- Service line
- Provider / site
- Time period
- Patient cohort

**Notes**
- Used as a denominator for DNA rates
- Not adjusted for population size unless explicitly stated

---

### 7. DNA Rate (Did Not Attend)

**Definition**
Proportion of scheduled appointments where the patient did not attend.

**Formula**
```
DNAs / (Attended + DNAs)
```

**Grain**
Appointment

**Inclusions**
- Status = `DNA`

**Exclusions**
- Cancelled appointments (any timing)
- Provider-initiated cancellations

**Notes**
- Late cancellations are treated as cancellations, not DNAs
- High DNA rates are interpreted as access friction, not patient fault

---

### 8. Encounter Volume

**Definition**
Count of completed encounters.

**Grain**
Encounter (urgent care or inpatient/outpatient as available)

**Notes**
- Used for utilisation and flow analysis
- Not interpreted as demand proxy without context

---

## Benchmarking Metrics

### 9. Median and P90 Wait Times

**Definition**
Distributional statistics calculated over defined reporting windows.

**Metrics**
- Median wait time
- 90th percentile wait time

**Grain**
- Encounter or appointment (depending on metric)

**Notes**
- P90 used to identify tail-risk and extreme delays
- Benchmarks are descriptive, not normative

---

### 10. Provider / Site Variance

**Definition**
Comparison of access metrics across providers or sites within the Trust.

**Approach**
- Raw comparisons only (no risk adjustment in Phase 1)
- Volume context always displayed alongside performance

**Notes**
- Explicitly avoids ranking language
- Outliers flagged, not labelled as underperforming

---

## Inequality Analysis

### Cohort Dimensions

All applicable metrics are analysable by:

- Age band
- Sex
- Ethnicity
- Deprivation (IMD decile/quintile or proxy)
- Geography (postcode district)
- Provider / site
- Service line

### Handling Missing or Unknown Values

- Missing values are grouped as `Unknown`
- Unknown is always visible in charts
- Metrics with >X% unknowns are flagged with a data quality warning

---

## Trend Analysis

### Definition

Metrics tracked over time to identify directional change.

**Approach**
- Rolling averages where appropriate
- Seasonal context noted explicitly

**Notes**
- Trends are descriptive, not causal
- Short-term fluctuations are interpreted cautiously

---

## Data Quality Considerations

For all metrics:
- Completeness, validity, and timeliness are tracked
- Failed quality checks do not silently suppress metrics
- Data quality indicators are exposed alongside metrics where relevant

---

## Versioning and Change Control

- Metric definitions are versioned in Git
- Changes require documentation of:
  - What changed
  - Why it changed
  - Impact on historical comparisons

Breaking changes are explicitly flagged.

---

## Summary

These definitions prioritise:
- Interpretability over complexity
- Transparency over optimisation
- Trust over precision theatre

They are designed to support consistent, defensible analysis of healthcare access and inequality across the Trust.
