# access-iq — Risks and Assumptions

## Purpose of This Document

This document records the key assumptions, risks, and mitigations associated with the access-iq engagement.

It exists to:
- Make uncertainty explicit rather than implicit
- Prevent misinterpretation of metrics and outputs
- Provide context for technical and analytical trade-offs
- Support informed decision-making by stakeholders

All risks and assumptions are revisited throughout delivery and updated as new information emerges.

---

## Core Assumptions

The following assumptions underpin the design and delivery of access-iq.

### A1. Data Provided Is Sufficient for Access Analysis

The engagement assumes that:
- EHR, urgent care, appointments, and diagnostics data collectively provide adequate coverage to analyse access and utilisation patterns.
- Gaps in data completeness are measurable and manageable through quality indicators.

**Impact if false:**
Some access metrics may be partially interpretable or require scope reduction.

**Mitigation:**
Explicit data quality metrics and visible unknown categories are built into all outputs.

---

### A2. Operational Timestamps Are Directionally Reliable

The platform assumes that recorded timestamps (arrival, triage, clinician contact, discharge, booking) are directionally correct, even if delayed or incomplete.

**Impact if false:**
Wait-time metrics could be biased or misleading.

**Mitigation:**
- Implausible durations are excluded from metric calculations.
- Timestamp completeness is tracked and surfaced alongside metrics.

---

### A3. Patient Demographics Are Imperfect but Informative

The engagement assumes demographic attributes (ethnicity, postcode, sex) are:
- Incomplete and inconsistently coded
- Still useful for inequality analysis when treated cautiously

**Impact if false:**
Cohort-level comparisons may underrepresent certain groups.

**Mitigation:**
- Unknown categories are explicitly included.
- Metrics with high missingness are flagged with warnings.

---

### A4. No Risk Adjustment in Phase 1

The platform assumes:
- Raw access metrics are acceptable for descriptive benchmarking in Phase 1.
- Case-mix or clinical risk adjustment is out of scope.

**Impact if false:**
Stakeholders may misinterpret variance as performance differences.

**Mitigation:**
- Clear documentation stating metrics are descriptive, not causal.
- Volume context and warnings included in benchmarking views.

---

### A5. Read-Only, Batch-Oriented Data Access

The engagement assumes:
- All upstream sources are accessed read-only.
- Near-real-time data is not required.

**Impact if false:**
Architecture would need to change significantly.

**Mitigation:**
Platform explicitly designed for daily batch analytics.

---

## Key Risks and Mitigations

### R1. Missing or Incomplete Timestamps

**Description:**
Urgent care and appointment data may have missing or late timestamps.

**Impact:**
Underestimation or distortion of wait-time metrics.

**Mitigation:**
- Exclude invalid intervals from calculations
- Track and surface completeness rates
- Avoid imputing missing times

---

### R2. Ambiguous Appointment Status Semantics

**Description:**
Inconsistent use of statuses (DNA vs late cancellation vs reschedule).

**Impact:**
Incorrect DNA rates and utilisation metrics.

**Mitigation:**
- Explicit status mapping contract
- Versioned status logic
- Regression tests on status changes

---

### R3. Late-Arriving Updates and Corrections

**Description:**
Discharge times, appointment statuses, and diagnostic results may update after initial ingestion.

**Impact:**
Historical metrics may change over time.

**Mitigation:**
- Incremental reconciliation logic in Silver layer
- Backfill windows and controlled reprocessing
- Clear documentation of metric revision behavior

---

### R4. Inconsistent Provider/Site Coding Across Sources

**Description:**
Different systems may use slightly different provider/site codes.

**Impact:**
Broken joins and misleading benchmarking.

**Mitigation:**
- Authoritative provider/site reference contract
- Unknown mapping with explicit DQ metrics
- Fail-fast behavior for reference inconsistencies

---

### R5. Schema Drift in Source Systems

**Description:**
Upstream systems may add, remove, or rename fields without notice.

**Impact:**
Pipeline failures or silent data corruption.

**Mitigation:**
- Schema validation at ingestion
- CI checks on expected columns
- Fail ingestion on breaking schema changes

---

### R6. Overinterpretation of Inequality Metrics

**Description:**
Stakeholders may interpret descriptive differences as causal or individual-level effects.

**Impact:**
Misguided operational or policy decisions.

**Mitigation:**
- Clear framing in documentation and dashboards
- No patient-level drill-downs
- Explicit disclaimers on interpretation

---

### R7. Performance and Cost Constraints

**Description:**
Large volumes or inefficient queries could impact performance or cost.

**Impact:**
Slow dashboards or excessive cloud spend.

**Mitigation:**
- Pre-aggregated Gold marts
- Query optimisation and cost monitoring
- Explicit cost/performance trade-offs documented

---

## Known Limitations

The following limitations are accepted as part of the engagement:

- No clinical outcomes or quality-of-care measures
- No real-time or intraday monitoring
- No predictive modelling or optimisation
- No external population denominators (unless simulated)
- Limited ability to distinguish demand vs capacity causality

These limitations are documented to avoid overclaiming platform capabilities.

---

## Review and Update Process

- Risks and assumptions are reviewed at major delivery milestones.
- New risks are added as they are identified.
- Mitigations are updated based on observed data behavior.

All changes are versioned in Git.

---

## Summary

access-iq is designed to surface access patterns and inequalities using imperfect operational data.
By making assumptions and risks explicit, the platform prioritises transparency, trust, and defensible analysis over false precision.
