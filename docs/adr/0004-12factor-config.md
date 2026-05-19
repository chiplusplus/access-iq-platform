# ADR 0004: 12-factor runtime config + dual-tree boundary

## Status

Accepted (Phase 1, 2026-05-12)

## Context

Pre-Phase-1, `src/access_iq/ingestion/cli.py:load_config()` read `Path.cwd() / "config" / f"{env}.json"`. This implicit cwd contract:

- Broke silently when the CLI ran outside the repo root (e.g. inside an ECS container with `/app` as cwd).
- Coupled runtime config to filesystem layout, contradicting 12-factor's "config in env".
- Conflated cleanly with the CDK deploy-time config at `infra/config/{env}.json`, encouraging key drift between the two trees.

## Decision

1. Runtime config lives in env vars consumed by a Pydantic `Settings` class (`src/access_iq/config.py`) with prefix `ACCESS_IQ_`.
2. Secrets are pulled at task start via ECS `valueFrom` referencing AWS Secrets Manager ARNs (Phase 3 wires this).
3. Local dev uses `.env` at repo root (gitignored); `.env.example` is the committed schema.
4. **CDK deploy-time config at `infra/config/{env}.json` is retained.** CDK needs account IDs, CIDRs, env names *before* synthesising resources that emit runtime env vars. The two trees are intentionally distinct:
   - `infra/config/*.json` — read by `cdk synth/deploy`, never by the runtime container.
   - `Settings()` (env vars) — read by the runtime container, never by `cdk`.
5. The legacy `config/{env}.json` runtime tree is deleted.

## Consequences

- Container images do not bake runtime config; ECS task definitions inject env vars + secrets per environment.
- Test suites can override config via `monkeypatch.setenv` rather than tempfiles.
- A future Phase 7 may add SSM Parameter Store as a third source (Deferred Idea in CONTEXT.md) — that would extend Settings, not replace this pattern.

## Alternatives considered

- **Keep `config/{env}.json` but resolve path relative to module** — rejected: still file-based, still leaks repo structure into the container, doesn't solve the dual-tree confusion.
- **Pull all config from SSM Parameter Store** — rejected for Phase 1: adds an external dependency for a use case env vars solve. Deferred.

## References

- 12-factor app §III. Config: https://12factor.net/config
- pydantic-settings docs: https://docs.pydantic.dev/latest/concepts/pydantic_settings/
- `CONTEXT.md` "Config loading" decision (Phase 1)
