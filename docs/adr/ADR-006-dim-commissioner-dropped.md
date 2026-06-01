# ADR-006: dim_commissioner Dropped from Gold Layer

## Status

Accepted

## Context

The original Gold dimensional model included a `dim_commissioner` dimension to represent
NHS Clinical Commissioning Groups (CCGs) / Integrated Care Boards (ICBs) that commission
services from the Northshire Trust. Commissioner-level analysis would enable understanding
of referral patterns and wait time variation by commissioning body.

## Decision

**dim_commissioner is dropped from the Gold layer.** The platform's analytical focus is
on patient-facing access and inequality metrics -- wait times by deprivation, breach rates
by ethnicity, diagnostic delays by geography. Commissioner-level breakdowns serve a
different audience (contract managers, ICB performance teams) and answer different
questions that fall outside the platform's core value proposition.

Adding a commissioner dimension would require:

- A new source system integration or significant extension to existing sources
- A commissioner-to-provider mapping that introduces organisational hierarchy complexity
- Fact table grain changes to support commissioner-level aggregation

The analytical value does not justify the effort. The existing six dimensions
(patient, date, specialty, site, IMD decile, ethnicity) directly serve the inequality
and access questions the platform is built to answer.

## Consequences

- Gold layer has 6 dimensions (not 7): dim_patient, dim_date, dim_specialty, dim_site, dim_imd, dim_ethnicity
- If commissioner-level analysis becomes a priority, dim_commissioner can be added as a
  new Gold dimension with FK from referrals (referral_commissioner_code)
- The scope stays focused on patient-facing inequality metrics rather than expanding into
  organisational performance reporting
