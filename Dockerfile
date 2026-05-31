FROM python:3.12-slim

# Install uv for deterministic dependency management
RUN pip install --no-cache-dir uv==0.7.0

WORKDIR /app

# Copy the ingestion package
COPY src/access_iq/ ./src/access_iq/

# Create venv and install the package directly (avoids workspace sync
# needing all members present)
RUN uv venv .venv && uv pip install --python .venv/bin/python ./src/access_iq/

# Default entrypoint - ECS task definition overrides CMD per source
ENTRYPOINT ["/app/.venv/bin/python", "-m", "access_iq.ingestion.cli"]
CMD ["ingest-postgres"]
