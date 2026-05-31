# access-iq-dashboard

Workspace skeleton for the Access-IQ Streamlit dashboard - three pages
(Wait Times, Inequality, Urgent Care) reading from the Gold layer in
Redshift Serverless.

**Empty until Phase 8 by design.** See `.planning/ROADMAP.md` § Phase 8 for
the dashboard plan. This member exists now solely so the uv workspace
resolves five members per locked decision D8, isolating Streamlit's
transitive deps from the ingestion and CDK members.
