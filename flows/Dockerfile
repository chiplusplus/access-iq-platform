FROM python:3.12-slim

# System deps for psycopg2-binary and dbt package git deps
RUN apt-get update && apt-get install -y --no-install-recommends git && \
    rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv==0.7.0

WORKDIR /app

# Copy ingestion package
COPY src/access_iq/ ./src/access_iq/

# Copy flows package
COPY flows/ ./flows/

# Copy dbt project (profiles, models, macros, seeds, scripts)
COPY dbt/ ./dbt/

# Copy runtime config (Settings reads config/{env}.json from cwd)
COPY config/ ./config/

# Single venv with all dependencies:
# - access-iq-ingestion (ingestion modules)
# - access-iq-flows (prefect, prefect-aws, GE, dbt deps)
# - dbt-core + dbt-redshift (dbt build)
RUN uv venv .venv && \
    uv pip install --python .venv/bin/python \
        ./src/access_iq/ \
        ./flows/ \
        dbt-core==1.10.0 \
        dbt-redshift==1.10.0 && \
    # Install dbt packages (dbt_expectations, dbt_date, dbt_external_tables)
    /app/.venv/bin/dbt deps --project-dir /app/dbt --profiles-dir /app/dbt

# Add venv to PATH so `prefect` and `python` resolve without full path
ENV PATH="/app/.venv/bin:$PATH"

# Default fallback: run the daily ingest flow directly.
# For ecs:push work pool, Prefect Cloud overrides the command at runtime.
CMD ["python", "-c", "from access_iq_flows.daily_ingest import daily_ingest; daily_ingest()"]
