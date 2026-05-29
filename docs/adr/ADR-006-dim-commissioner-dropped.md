# ADR-006: dim_commissioner Dropped from Gold Layer

## Status

Accepted

## Context

The original Gold dimensional model included a `dim_commissioner` dimension to represent
NHS Clinical Commissioning Groups (CCGs) / Integrated Care Boards (ICBs) that commission
services from the Northshire Trust. Commissioner-level analysis would enable understanding
of referral patterns and wait time variation by commissioning body.

## Decision

**dim_commissioner is dropped from Phase 6.** The Northshire Hospital Simulator does not
generate commissioner data in any of its source systems:

- EHR (patient_demographics, encounters, diagnoses): no commissioner/CCG/ICB fields
- Urgent Care (urgent_care_logs): no commissioner reference
- Appointments (SFTP export): no commissioner field
- Referrals (EHR): no commissioning body or CCG code
- Provider reference (S3 export): providers only, no commissioner relationship

Without source data, a dim_commissioner would be either:

1. A static seed with no fact table joins (decorative, no analytical value)
2. A placeholder with synthetic data (misleading in a portfolio piece)

Neither option serves the Trust's analytical needs or demonstrates genuine data engineering skill.

## Consequences

- Gold layer has 6 dimensions (not 7): dim_patient, dim_date, dim_specialty, dim_site, dim_imd, dim_ethnicity
- If the simulator is extended with commissioner data in future, add dim_commissioner as a new
  Gold dimension with FK from referrals (referral_commissioner_code)
- The case study write-up should note this as a deliberate scope decision, not an oversight
