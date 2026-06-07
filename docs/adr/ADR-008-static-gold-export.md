# ADR-008: Static Gold Export to Streamlit Community Cloud

## Status

Accepted

## Context

The Streamlit dashboard needs to display Gold mart analytics (wait times, inequality,
urgent care, utilisation). Two approaches were considered:

1. **Live Redshift connection** -- Streamlit queries Redshift directly. Requires the
   warehouse to be running for the dashboard to function, which contradicts the ephemeral
   infrastructure pattern ($0 idle cost). The dashboard would go down every time
   `make down` destroys the Redshift workgroup.

2. **Static export** -- Gold marts exported to Parquet on S3, consumed by the dashboard
   without a live warehouse.

## Decision

**Static Gold export to S3 Parquet, consumed by Streamlit Community Cloud via DuckDB.**

- The Prefect pipeline's final task exports all 10 Gold tables to `s3://<public-export>/gold/` as Parquet files.
- Export is idempotent per `run_id` -- re-running the pipeline overwrites with the same
  data, not duplicates.
- Streamlit app reads Parquet files via an IAM user with read-only S3 access. DuckDB
  provides in-process SQL over the Parquet files without a server.
- `st.cache_data(ttl=3600)` masks S3 fetch latency -- files are cached in memory for
  one hour per session.
- Small-cell suppression applied at the Gold dbt layer is carried through to Parquet
  unchanged. No additional masking needed at the dashboard layer.
- Dashboard cost is $0 (Streamlit Community Cloud free tier) plus minimal cost for
  S3 storage for the exported Parquet files.

## Consequences

- Dashboard works 24/7 without Redshift running. Users can view analytics at any time,
  even when the platform infrastructure is torn down.
- Data freshness equals the last pipeline run (not real-time). Acceptable for the purposes of this portfolio project. Mitigated by displaying `export_date` in the dashboard sidebar so
  users know when data was last refreshed.
- Inline `conn.execute().df()` calls in dashboard pages are intentionally not cached
  across sessions. They populate sidebar filters via registered DuckDB views, and
  cross-session caching would serve stale data for different `export_date` selections.
