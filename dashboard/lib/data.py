"""DuckDB connection and cached Gold layer queries."""

from __future__ import annotations

from datetime import UTC, datetime

import duckdb
import pandas as pd
import streamlit as st
import structlog

from lib.s3 import get_data_source, parquet_path

log = structlog.get_logger(__name__)


@st.cache_resource
def get_connection() -> duckdb.DuckDBPyConnection:
    """Single shared DuckDB connection. S3 creds from st.secrets (D-01)."""
    conn = duckdb.connect(database=":memory:")

    if get_data_source() == "s3":
        conn.execute("INSTALL httpfs; LOAD httpfs;")
        import os

        def _secret(key: str, default: str = "") -> str:
            try:
                return str(st.secrets[key])
            except (KeyError, Exception):
                return os.environ.get(key, default)

        key_id = _secret("AWS_ACCESS_KEY_ID")
        secret = _secret("AWS_SECRET_ACCESS_KEY")
        region = _secret("AWS_REGION", "eu-west-2")
        if key_id:
            conn.execute(f"""
                CREATE OR REPLACE SECRET s3_cred (
                    TYPE S3,
                    KEY_ID '{key_id}',
                    SECRET '{secret}',
                    REGION '{region}'
                )
            """)
    return conn


def register_tables(
    conn: duckdb.DuckDBPyConnection,
    bucket: str,
    export_date: str | None,
    tables: list[str],
) -> None:
    """Register only the tables this page needs as DuckDB views (D-02)."""
    for table in tables:
        path = parquet_path(table, export_date, bucket)
        conn.execute(f"CREATE OR REPLACE VIEW {table} AS SELECT * FROM read_parquet('{path}')")


def data_freshness_text(export_date: str | None) -> str:
    """Return freshness badge text per UI-SPEC."""
    now_utc = datetime.now(UTC).strftime("%H:%M")
    if get_data_source() == "local":
        label = f"export_date {export_date}" if export_date else "all files"
        return f"Data: sample Gold export ({label})  |  Source: local Parquet"
    return f"Data: export_date {export_date}  |  Loaded: {now_utc} UTC  |  Source: S3 gold_export/"


# ---------- Wait Times queries (D-05, D-06) ----------


@st.cache_data(ttl=3600)
def query_wait_times_kpis(
    export_date: str, providers: tuple[str, ...], specialties: tuple[str, ...]
) -> pd.DataFrame:
    """KPI row: 18-week breach rate, median wait days, 52-week+ count."""
    conn = get_connection()
    where_clauses = ["1=1"]
    params: list = []
    if providers:
        where_clauses.append("ds.provider_name = ANY(?)")
        params.append(list(providers))
    if specialties:
        where_clauses.append("dsp.specialty_name = ANY(?)")
        params.append(list(specialties))
    where = " AND ".join(where_clauses)
    return conn.execute(
        f"""
        SELECT
            AVG(CASE WHEN fw.rtt_breach_flag THEN 1.0 ELSE 0.0 END) AS breach_rate_18wk,
            MEDIAN(fw.wait_days) AS median_wait_days,
            COUNT(*) FILTER (WHERE fw.wait_days > 364) AS waiters_52wk
        FROM fct_wait_times fw
        LEFT JOIN dim_site ds ON ds.site_sk = fw.site_sk
        LEFT JOIN dim_specialty dsp ON dsp.specialty_sk = fw.specialty_sk
        WHERE {where}
    """,
        params,
    ).df()


@st.cache_data(ttl=3600)
def query_wait_by_provider(
    export_date: str, providers: tuple[str, ...], specialties: tuple[str, ...]
) -> pd.DataFrame:
    """P50/P90 wait days by provider for grouped bar chart (D-06)."""
    conn = get_connection()
    where_clauses = ["1=1"]
    params: list = []
    if providers:
        where_clauses.append("ds.provider_name = ANY(?)")
        params.append(list(providers))
    if specialties:
        where_clauses.append("dsp.specialty_name = ANY(?)")
        params.append(list(specialties))
    where = " AND ".join(where_clauses)
    return conn.execute(
        f"""
        SELECT
            ds.provider_name,
            MEDIAN(fw.wait_days) AS p50_wait,
            QUANTILE_CONT(fw.wait_days, 0.9) AS p90_wait
        FROM fct_wait_times fw
        JOIN dim_site ds ON ds.site_sk = fw.site_sk
        LEFT JOIN dim_specialty dsp ON dsp.specialty_sk = fw.specialty_sk
        WHERE {where}
        GROUP BY ds.provider_name
        ORDER BY ds.provider_name
    """,
        params,
    ).df()


@st.cache_data(ttl=3600)
def query_wait_trend(
    export_date: str, providers: tuple[str, ...], specialties: tuple[str, ...]
) -> pd.DataFrame:
    """Wait time trend by referral_month (D-06)."""
    conn = get_connection()
    where_clauses = ["1=1"]
    params: list = []
    if providers:
        where_clauses.append("ds.provider_name = ANY(?)")
        params.append(list(providers))
    if specialties:
        where_clauses.append("dsp.specialty_name = ANY(?)")
        params.append(list(specialties))
    where = " AND ".join(where_clauses)
    return conn.execute(
        f"""
        SELECT
            fw.referral_month,
            MEDIAN(fw.wait_days) AS p50_wait,
            QUANTILE_CONT(fw.wait_days, 0.9) AS p90_wait
        FROM fct_wait_times fw
        LEFT JOIN dim_site ds ON ds.site_sk = fw.site_sk
        LEFT JOIN dim_specialty dsp ON dsp.specialty_sk = fw.specialty_sk
        WHERE {where}
        GROUP BY fw.referral_month
        ORDER BY fw.referral_month
    """,
        params,
    ).df()


@st.cache_data(ttl=3600)
def query_wait_month_bounds(export_date: str) -> pd.DataFrame:
    """Unfiltered min/max referral_month for date range slider bounds (D-07).

    Separate from filtered query to avoid circular dependency --
    slider bounds must be known before filters are applied.
    """
    conn = get_connection()
    return conn.execute("""
        SELECT
            MIN(referral_month) AS min_month,
            MAX(referral_month) AS max_month
        FROM fct_wait_times
    """).df()


# ---------- Inequality queries (D-08, D-09) ----------


@st.cache_data(ttl=3600)
def query_inequality_kpis(export_date: str) -> pd.DataFrame:
    """KPI row: SII, IMD gap, suppressed count (D-08)."""
    conn = get_connection()
    return conn.execute("""
        SELECT
            (SELECT sii_value FROM fct_inequality
             WHERE metric_name='wait_time_median' AND stratifier='imd_decile'
             ORDER BY period DESC LIMIT 1) AS sii,
            (SELECT MAX(metric_value) - MIN(metric_value) FROM fct_inequality
             WHERE metric_name='wait_time_median' AND stratifier='imd_decile'
             AND stratum IN ('1','10')) AS imd_gap,
            (SELECT COUNT(*) FROM fct_inequality
             WHERE metric_name='wait_time_median' AND population_count IS NULL) AS suppressed_count
    """).df()


@st.cache_data(ttl=3600)
def query_inequality_by_stratifier(export_date: str, stratifier: str) -> pd.DataFrame:
    """Metric values by stratum for selected stratifier (D-09)."""
    conn = get_connection()
    return conn.execute(
        """
        SELECT metric_name, period, stratum, population_count, metric_value,
               sii_value, rii_value
        FROM fct_inequality
        WHERE stratifier = ?
        ORDER BY metric_name, stratum
    """,
        [stratifier],
    ).df()


# ---------- Urgent Care queries (D-11, D-12, D-15) ----------


@st.cache_data(ttl=3600)
def query_urgent_care_kpis(export_date: str, providers: tuple[str, ...]) -> pd.DataFrame:
    """KPI row: 4h breach rate, 12h breach count, admission rate (D-11)."""
    conn = get_connection()
    where_clauses = ["1=1"]
    params: list = []
    if providers:
        where_clauses.append("ds.provider_name = ANY(?)")
        params.append(list(providers))
    where = " AND ".join(where_clauses)
    return conn.execute(
        f"""
        SELECT
            AVG(CASE WHEN uc.four_hour_breach_flag THEN 1.0 ELSE 0.0 END) AS breach_rate_4h,
            COUNT(*) FILTER (WHERE uc.twelve_hour_breach_flag) AS breach_count_12h,
            AVG(CASE WHEN uc.admitted_flag THEN 1.0 ELSE 0.0 END) AS admission_rate
        FROM fct_urgent_care uc
        LEFT JOIN dim_site ds ON ds.site_sk = uc.site_sk
        WHERE {where}
    """,
        params,
    ).df()


@st.cache_data(ttl=3600)
def query_uc_stage_times(export_date: str, providers: tuple[str, ...]) -> pd.DataFrame:
    """Average time by stage for stacked bar (D-12)."""
    conn = get_connection()
    where_clauses = ["1=1"]
    params: list = []
    if providers:
        where_clauses.append("ds.provider_name = ANY(?)")
        params.append(list(providers))
    where = " AND ".join(where_clauses)
    return conn.execute(
        f"""
        SELECT
            ds.provider_name,
            AVG(uc.arrival_to_triage_mins) AS avg_triage,
            AVG(uc.arrival_to_seen_mins) - AVG(uc.arrival_to_triage_mins) AS avg_seen,
            AVG(uc.arrival_to_discharge_mins) - AVG(uc.arrival_to_seen_mins) AS avg_discharge
        FROM fct_urgent_care uc
        JOIN dim_site ds ON ds.site_sk = uc.site_sk
        WHERE {where}
        GROUP BY ds.provider_name
        ORDER BY ds.provider_name
    """,
        params,
    ).df()


@st.cache_data(ttl=3600)
def query_uc_breach_trend(export_date: str, providers: tuple[str, ...]) -> pd.DataFrame:
    """4h breach rate by arrival_month (D-12)."""
    conn = get_connection()
    where_clauses = ["1=1"]
    params: list = []
    if providers:
        where_clauses.append("ds.provider_name = ANY(?)")
        params.append(list(providers))
    where = " AND ".join(where_clauses)
    return conn.execute(
        f"""
        SELECT
            uc.arrival_month,
            AVG(CASE WHEN uc.four_hour_breach_flag THEN 1.0 ELSE 0.0 END) AS breach_rate_4h
        FROM fct_urgent_care uc
        LEFT JOIN dim_site ds ON ds.site_sk = uc.site_sk
        WHERE {where}
        GROUP BY uc.arrival_month
        ORDER BY uc.arrival_month
    """,
        params,
    ).df()


@st.cache_data(ttl=3600)
def query_uc_busiest_hours(export_date: str, providers: tuple[str, ...]) -> pd.DataFrame:
    """Attendance count by day-of-week x hour-of-day for heatmap (D-12)."""
    conn = get_connection()
    where_clauses = ["1=1"]
    params: list = []
    if providers:
        where_clauses.append("ds.provider_name = ANY(?)")
        params.append(list(providers))
    where = " AND ".join(where_clauses)
    return conn.execute(
        f"""
        SELECT
            DAYNAME(CAST(uc.arrival_datetime AS TIMESTAMP)) AS day_of_week,
            EXTRACT(HOUR FROM CAST(uc.arrival_datetime AS TIMESTAMP)) AS hour_of_day,
            COUNT(*) AS attendance_count
        FROM fct_urgent_care uc
        LEFT JOIN dim_site ds ON ds.site_sk = uc.site_sk
        WHERE {where}
        GROUP BY DAYNAME(CAST(uc.arrival_datetime AS TIMESTAMP)), EXTRACT(HOUR FROM CAST(uc.arrival_datetime AS TIMESTAMP))
        ORDER BY day_of_week, hour_of_day
    """,
        params,
    ).df()


@st.cache_data(ttl=3600)
def query_uc_equity(
    export_date: str,
    providers: tuple[str, ...],
    stratifier: str,
) -> pd.DataFrame:
    """Urgent Care with demographic split for equity overlay (D-15, D-16).

    Joins fct_urgent_care to dim_patient, groups by stratifier column.
    stratifier is one of: IMD Decile, Ethnicity, Age Band, Sex.
    """
    conn = get_connection()
    col_map = {
        "IMD Decile": "dp.imd_decile",
        "Ethnicity": "dp.ethnicity_ons",
        "Age Band": "dp.age_band",
        "Sex": "dp.sex",
    }
    col = col_map.get(stratifier)
    if not col:
        raise ValueError(f"Unknown stratifier: {stratifier!r}")

    where_clauses = ["dp.is_current"]
    params: list = []
    if providers:
        where_clauses.append("ds.provider_name = ANY(?)")
        params.append(list(providers))
    where = " AND ".join(where_clauses)
    return conn.execute(
        f"""
        SELECT
            {col} AS stratum,
            AVG(CASE WHEN uc.four_hour_breach_flag THEN 1.0 ELSE 0.0 END) AS breach_rate_4h,
            COUNT(*) FILTER (WHERE uc.twelve_hour_breach_flag) AS breach_count_12h,
            AVG(CASE WHEN uc.admitted_flag THEN 1.0 ELSE 0.0 END) AS admission_rate,
            AVG(uc.arrival_to_triage_mins) AS avg_triage,
            AVG(uc.arrival_to_seen_mins) - AVG(uc.arrival_to_triage_mins) AS avg_seen,
            AVG(uc.arrival_to_discharge_mins) - AVG(uc.arrival_to_seen_mins) AS avg_discharge,
            COUNT(*) AS attendance_count
        FROM fct_urgent_care uc
        JOIN dim_patient dp ON dp.patient_sk = uc.patient_sk
        LEFT JOIN dim_site ds ON ds.site_sk = uc.site_sk
        WHERE {where}
        GROUP BY {col}
        ORDER BY {col}
    """,
        params,
    ).df()
