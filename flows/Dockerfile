FROM python:3.12-slim

RUN pip install --no-cache-dir uv==0.7.0

WORKDIR /app

# Copy ingestion package
COPY src/access_iq/ ./src/access_iq/

# Copy flows package
COPY flows/ ./flows/

# Single venv: ingestion + flows (prefect, prefect-aws)
RUN uv venv .venv && \
    uv pip install --python .venv/bin/python \
        ./src/access_iq/ \
        ./flows/

# Add venv to PATH so `prefect` and `python` resolve without full path
ENV PATH="/app/.venv/bin:$PATH"

CMD ["python", "-c", "from access_iq_flows.daily_ingest import daily_ingest; daily_ingest()"]
