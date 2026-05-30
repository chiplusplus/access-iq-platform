# ADR-014: uv Workspace Split for Dependency Isolation

## Status

Accepted

## Context

The platform has five distinct Python components: ingestion runtime (`src/access_iq/`),
dbt runner (`dbt/`), Prefect flows (`flows/`), Streamlit dashboard (`dashboard/`), and
CDK infrastructure (`infra/`). These have conflicting transitive dependencies:

- **dbt-core** pins jinja2 to a narrow range; Prefect also depends on jinja2 but at
  different versions.
- **Prefect** pins pydantic v2 with specific minor constraints; CDK's jsii layer and
  dbt-core pull pydantic differently.
- **Streamlit** pins protobuf to its own range, conflicting with other Google-sourced
  transitive dependencies.
- **dbt-common 1.38.0** has a `mashumaro` name conflict with Python 3.14's stdlib,
  requiring the dbt workspace to pin Python to 3.12 via `.python-version`.

A single `pyproject.toml` with all five dependency trees cannot resolve without version
conflicts. Additionally, the Docker image for ECS ingestion should contain only ingestion
dependencies, not dbt/Streamlit/Prefect libraries.

## Decision

**uv workspace with 5 members.** The root `pyproject.toml` declares the workspace:

```toml
[tool.uv.workspace]
members = ["src/access_iq", "infra", "dbt", "flows", "dashboard"]
```

Each member has its own `pyproject.toml` with isolated dependencies. `uv sync` resolves
each workspace member independently. Key details:

- The ingestion workspace (`src/access_iq/`) builds the ECS Docker image -- only its
  dependencies appear in the container.
- The dbt workspace (`dbt/`) has its own `.python-version` pinned to 3.12 to avoid the
  dbt-common 1.38.0 mashumaro name conflict with Python 3.14.
- CI runs `uv sync` per workspace member to validate dependency resolution does not
  regress.
- Root `pyproject.toml` carries dev-only dependencies (pytest, ruff, mypy, pre-commit)
  shared across all workspaces.

## Consequences

- No transitive dependency conflicts between components.
- Docker image is lean: ingestion deps only (~200 MB vs ~800 MB with all components).
- Each workspace can pin its own Python version independently.
- Trade-off: developers run `uv sync` per workspace (not one global install). Mitigated
  by `make setup` which syncs all workspaces in sequence.
- New dependency additions must go to the correct workspace `pyproject.toml`, not the
  root. Wrong placement causes resolution failures in CI.

## Alternatives considered

- **pip + requirements.txt per component**: No lockfile, no workspace-level resolution.
  Dependency conflicts surface at runtime, not install time. No cross-member conflict
  detection.

- **Poetry**: No workspace support (Poetry workspaces are experimental and undocumented).
  Slower resolution than uv. Lock format is Poetry-specific and not interoperable.

- **Single package with optional extras** (`pip install .[dbt,prefect,dashboard]`):
  Resolves all extras in one environment -- conflicts resurface immediately. Cannot
  isolate Python versions per component. Docker image carries all extras.

- **Separate repos per component**: Breaks the monorepo portfolio narrative. Complicates
  CI (5 repos, 5 pipelines), versioning (cross-repo tags), and cross-component testing
  (no shared test fixtures).

## References

- PROJECT.md decision D8
- Root `pyproject.toml` workspace declaration
- `dbt/.python-version` (Python 3.12 pin)
