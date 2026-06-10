# access-iq-flows

Workspace skeleton for the Access-IQ Prefect orchestration layer - flows
that compose ingestion → dbt → Great Expectations validation into one
operational pipeline.

**Empty until Phase 7 by design.** See `.planning/ROADMAP.md` § Phase 7 for
the orchestration plan. This member exists now solely so the uv workspace
resolves five members per locked decision D8, isolating Prefect's
transitive deps (pydantic v1/v2 hybrids historically) from the ingestion
and CDK members.
