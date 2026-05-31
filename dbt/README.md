# access-iq-dbt

Workspace skeleton for the Access-IQ dbt project - Silver staging models
(patients, encounters, appointments, urgent_care, diagnostics, providers)
and Gold marts (wait_times, inequality, urgent_care, utilisation) targeting
Redshift Serverless.

**Empty until Phase 4 by design.** See `.planning/ROADMAP.md` § Phase 4 for
the modelling layer plan. This member exists now solely so the uv workspace
resolves five members per locked decision D8, isolating dbt's transitive
deps (jinja2, marshmallow) from the ingestion and CDK members.
