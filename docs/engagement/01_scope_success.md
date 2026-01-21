# access-iq — Scope and Success Criteria

## Purpose of This Document

This document defines the analytical scope, success criteria, and boundaries for the access-iq engagement. It translates the high-level context into concrete questions, metrics, and deliverables that the platform must support.

Its purpose is to:
- Establish a shared definition of success
- Prevent scope drift during delivery
- Provide a reference point for technical and modelling decisions

---

## In-Scope Objectives

access-iq focuses on **access to care and utilisation**, analysed through an explicit inequality lens.

The platform will support:
- Measurement of waiting times, delays, DNAs, and utilisation
- Comparison across patient cohorts, providers, and time
- Identification of access bottlenecks within care pathways
- Trend analysis to assess improvement or deterioration

The platform is designed for **analytical decision support**, not operational or clinical intervention.

---

## Out-of-Scope (Explicitly)

The following are intentionally excluded from this engagement:

- Real-time operational dashboards
- Clinical risk scoring or patient-level decision support
- Outcomes modelling (e.g. mortality, complication rates)
- Financial or tariff modelling
- Predictive or prescriptive optimisation models

These exclusions are necessary to maintain analytical clarity and delivery focus.

---

## Primary Stakeholder Questions

The engagement is structured around the following core questions.

### Q1. Where are the longest access delays occurring, and for whom?
- Focus: waiting times and pathway delays
- Perspective: cohort comparison and distributional analysis

### Q2. Are there systematic differences in access by ethnicity, deprivation, age, or geography?
- Focus: inequality analysis across standard access metrics
- Perspective: fairness and consistency of service delivery

### Q3. Which providers or sites are outliers in terms of access performance?
- Focus: benchmarking and variance analysis
- Perspective: performance improvement and capacity planning

### Q4. Where are appointment non-attendance (DNA) rates highest, and among which cohorts?
- Focus: DNAs as both access and utilisation signal
- Perspective: demand management and service design

### Q5. How does urgent care flow vary across patient groups and over time?
- Focus: emergency department flow and bottlenecks
- Perspective: operational pressure points

### Q6. Are access gaps improving or worsening over time?
- Focus: trend analysis
- Perspective: impact of interventions and seasonal effects

---

## Key Metrics (High-Level)

The platform will produce the following core metric groups. Precise definitions are maintained in `03_metric_definitions.md`.

### Access and Waiting Time Metrics
- Arrival → triage time (urgent care)
- Triage → first clinician time (urgent care)
- Arrival → discharge time (urgent care)
- Appointment wait time (booking → attended)
- Diagnostic order → result turnaround (where available)

### Utilisation and Demand Metrics
- Appointment volume by service and cohort
- Attendance vs DNA rates
- Encounter counts by pathway

### Benchmarking Metrics
- Median and P90 wait times by provider/site
- DNA rate variance across providers
- Volume-adjusted comparisons (where feasible)

### Trend Metrics
- Rolling weekly and monthly trends
- Seasonal comparison where data permits

---

## Inequality Dimensions (Slices)

All key metrics will be analysable across the following dimensions, subject to data availability:

- Age band
- Sex
- Ethnicity
- Deprivation (e.g. IMD decile/quintile or proxy)
- Geography (e.g. postcode district)
- Provider / site
- Service line / pathway
- Time (week, month)

Missing or unknown values will be explicitly represented rather than silently excluded.

---

## Minimum Lovable Product (MLP)

The MLP for this engagement consists of:

### Dashboard Pages
1. **Access & Waiting Times**
   - Key wait time distributions by cohort and provider
2. **Inequality Lens**
   - Side-by-side comparison of access metrics across demographics
3. **Utilisation & Flow**
   - DNA rates, appointment volume, and urgent care flow metrics

### Platform Capabilities
- End-to-end ingestion from all agreed sources
- Governed Silver and Gold data models
- Documented metric definitions and lineage
- Automated data quality checks with visible failures
- Reproducible builds across environments

---

## Deferred / Phase 2 Capabilities

The following are explicitly deferred beyond the initial engagement:

- Risk adjustment or case-mix modelling
- Advanced geospatial analysis
- Predictive modelling of DNAs or delays
- Near-real-time ingestion
- Patient-level drill-downs for operational use

These may be considered future extensions.

---

## Success Criteria

The engagement is considered successful when:

- All in-scope stakeholder questions can be answered using the platform
- Metrics are consistent, documented, and reproducible
- Data quality issues are surfaced and quantified
- Trends and cohort differences are interpretable and defensible
- The platform can be extended without reworking core models

Success is measured by clarity, trust, and analytical usefulness rather than dashboard volume.

---

## Acceptance Criteria (Delivery-Level)

At completion:
- A new analyst can understand and run the platform using documentation alone
- Metrics displayed in the dashboard map directly to Gold-layer models
- Lineage from source → metric is visible and auditable
- Known data limitations are explicitly documented
- The platform demonstrates senior-level engineering and analytical judgement
