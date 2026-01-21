## Summary

**What does this change do?**
(1–3 sentences. Be concrete. Assume the reviewer hasn’t read the ticket/commit history.)

---

## Context

**Why is this change needed?**
- What problem does it solve?
- Which phase / deliverable does this relate to? (e.g. Phase 2 – Bronze ingestion)

Link to any relevant docs:
- Scope / metrics / contracts:
- ADR (if applicable):

---

## Type of Change

_Select all that apply:_

- [ ] Infrastructure (CDK / AWS)
- [ ] Ingestion (Bronze)
- [ ] Modelling (Silver)
- [ ] Metrics / marts (Gold)
- [ ] Data quality / validation
- [ ] Orchestration (Prefect)
- [ ] Dashboard / app
- [ ] Documentation
- [ ] Refactor / cleanup
- [ ] Other (explain below)

---

## Data Impact

**Does this change affect data outputs?**

- [ ] No data impact
- [ ] Schema change (new/changed columns or tables)
- [ ] Logic change (metrics, filters, dedupe rules, etc.)
- [ ] Backfill required
- [ ] Rebuild required (Silver / Gold)

If yes, explain briefly:
- What changed?
- Which layer(s)?
- Expected impact on existing metrics?

---

## Assumptions & Trade-offs

**What assumptions are baked into this change?**
(Especially important for healthcare data.)

-
-

**Known limitations or follow-ups:**
-

---

## Testing Performed

_Select all that apply:_

- [ ] Unit tests
- [ ] dbt tests
- [ ] Great Expectations checks
- [ ] Manual validation (describe below)
- [ ] Dry run / backfill test
- [ ] CI checks passing

**Notes on testing / validation:**
- What you checked, and why you’re confident it’s correct

---

## Risks & Rollback

**Potential risks:**
- (e.g. performance, cost, data correctness, edge cases)

**Rollback plan (if needed):**
- (e.g. revert PR, rerun previous dbt version, restore snapshot)

---

## Checklist

- [ ] Code follows repo conventions
- [ ] No secrets committed
- [ ] Data contracts respected
- [ ] Metric definitions unchanged or updated in docs
- [ ] Documentation updated (if applicable)

---

## Reviewer Notes (for future-you)

Anything you want to remember when you look at this PR in 3 months:
- Why this was done this way
- What you intentionally did *not* do
