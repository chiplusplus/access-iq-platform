FROM python:3.12-slim

# Install uv for deterministic dependency management
RUN pip install --no-cache-dir uv

WORKDIR /app

# Copy workspace root files needed for uv sync
COPY pyproject.toml uv.lock ./

# Copy the ingestion package (workspace member)
COPY src/access_iq/ ./src/access_iq/

# Copy runtime config (CLI loads from cwd)
COPY config/ ./config/

# Install dependencies deterministically from lockfile (no dev deps)
RUN uv sync --frozen --no-dev

# Default entrypoint — ECS task definition overrides CMD per source
ENTRYPOINT ["uv", "run", "python", "-m", "access_iq.ingestion.cli"]
CMD ["ingest-postgres"]
