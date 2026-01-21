# access-iq — Context

## Background

NHS Trusts operate under sustained pressure to improve access to care while managing constrained capacity, workforce shortages, and rising demand. Waiting times, appointment non-attendance (DNA), emergency department flow, and diagnostic delays are closely scrutinised by regulators, executives, and the public.

At the same time, evidence consistently shows that access to care is not experienced equally across patient groups. Differences by ethnicity, deprivation, geography, age, and sex can materially affect outcomes, yet these inequalities are often difficult to quantify reliably using existing reporting tools.

Most Trusts already possess the underlying data required to understand these issues. However, that data is fragmented across operational systems, inconsistently defined, and poorly suited to longitudinal or cross-cutting analysis. As a result, leadership teams rely on static reports, manual extracts, or anecdotal evidence when making decisions about access and capacity.

access-iq is positioned as a modern analytics platform designed to close this gap.

---

## The Problem

The Trust’s current data landscape makes it difficult to answer basic but critical questions, such as:

- Where in care pathways do delays most frequently occur?
- Which patient cohorts experience systematically longer waits or higher DNA rates?
- How does access differ by provider site, service line, or geography?
- Are observed differences driven by demand, capacity, operational performance, or data artefacts?

Operational systems (EHRs, urgent care systems, booking platforms, diagnostics systems) are optimised for transactional workflows, not analytical insight. Data definitions vary between teams, historical changes are poorly tracked, and quality issues (missing demographics, duplicate events, late-arriving updates) undermine confidence in reported metrics.

As a result:
- Access issues are often identified late.
- Inequality analysis is ad hoc or retrospective.
- Benchmarking across providers or cohorts is fragile.
- Decision-makers lack a shared, trusted view of access performance.

---

## What access-iq Is

access-iq is a decision-support analytics platform designed to consolidate, standardise, and analyse healthcare access data at Trust level.

It ingests data from existing operational sources and transforms it into a governed, analytics-ready warehouse with clearly defined metrics, quality controls, and lineage. The platform enables consistent reporting on access and utilisation while applying an explicit inequality lens across patient cohorts.

access-iq is not a generic BI dashboard. It is a structured analytics foundation that supports repeatable analysis, transparent metric definitions, and robust comparison across time, cohorts, and providers.

---

## Who It’s For

The primary users of access-iq are:

- **Operational and performance leads**
  Monitoring waiting times, DNAs, utilisation, and flow; identifying pressure points and underperforming pathways.

- **Service and clinical managers**
  Understanding how access varies across patient groups and sites; prioritising interventions.

- **Executive leadership**
  Receiving a consolidated, defensible view of access performance and inequality trends.

Secondary users include analytics and informatics teams who require a stable data model and clear definitions to support deeper analysis.

---

## What Questions It Answers

access-iq is designed to answer questions such as:

- How do waiting times differ by ethnicity, deprivation, age, and geography?
- Where in urgent care pathways do delays most commonly occur, and for whom?
- Which providers or sites are outliers on DNA rates or throughput?
- Are access gaps widening or narrowing over time?
- Which services contribute most to overall access pressure?

All metrics are derived from documented definitions and can be traced back to source data.

---

## What It Is Not

access-iq is deliberately scoped and does not attempt to be:

- A real-time operational system
- A replacement for EHR or booking platforms
- A clinical decision-support or risk prediction tool
- A population health or outcomes modelling platform

Its focus is access, utilisation, and inequality analysis using routinely collected operational data.

---

## Engagement Framing

This project is framed as a simulated external consultancy engagement with a single NHS Trust. The Trust provides read-only access to operational data sources and expects a robust analytics platform capable of supporting ongoing performance monitoring.

While designed for a single Trust context, the platform architecture and data modelling approach are intentionally generalisable to other Trusts with similar source systems.

Assumptions, risks, and limitations are explicitly documented as part of the engagement.

---

## What Success Looks Like

From a Trust perspective, the engagement is successful if:

- Access and inequality metrics are clearly defined, reproducible, and trusted.
- Leadership can confidently compare access performance across cohorts, sites, and time.
- Data quality issues are visible and managed rather than hidden.
- The platform can be extended to additional pathways or metrics without rework.
- Insights generated by the platform can directly inform operational decisions.

From a delivery perspective, success means the platform is well-documented, testable, and maintainable, with transparent trade-offs and clear ownership boundaries.
