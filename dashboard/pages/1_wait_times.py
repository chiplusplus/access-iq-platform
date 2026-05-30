"""Wait Times -- RTT 18-week, 52-week+ waiters, DM01 diagnostics."""

from __future__ import annotations

import streamlit as st

from lib.charts import grouped_bar, line_trend
from lib.data import (
    data_freshness_text,
    get_connection,
    query_wait_by_provider,
    query_wait_month_bounds,
    query_wait_times_kpis,
    query_wait_trend,
    register_tables,
)


def _run() -> None:
    # --- Title + freshness badge ---
    st.title("Wait Times")
    export_date = st.session_state.get("export_date")
    bucket = st.session_state.get("bucket", "")
    st.caption(data_freshness_text(export_date))

    # --- Register tables (D-02 lazy-load) ---
    conn = get_connection()
    register_tables(conn, bucket, export_date, ["fct_wait_times", "dim_site", "dim_specialty"])

    # --- Sidebar filters (D-07) ---
    # Provider multiselect
    providers_df = conn.execute(
        "SELECT DISTINCT provider_name FROM dim_site ORDER BY provider_name"
    ).df()
    all_providers = providers_df["provider_name"].tolist()
    providers: list[str] = st.sidebar.multiselect("Provider", options=all_providers)

    # Specialty multiselect
    specialties_df = conn.execute(
        "SELECT DISTINCT specialty_name FROM dim_specialty ORDER BY specialty_name"
    ).df()
    all_specialties = specialties_df["specialty_name"].tolist()
    specialties: list[str] = st.sidebar.multiselect("Specialty", options=all_specialties)

    # Date range slider -- unfiltered bounds (separate query to avoid circular dependency)
    bounds_df = query_wait_month_bounds(export_date)
    if bounds_df.empty or bounds_df["min_month"].iloc[0] is None:
        st.warning("No data available")
        return

    min_month = str(bounds_df["min_month"].iloc[0])
    max_month = str(bounds_df["max_month"].iloc[0])

    date_range = None
    if min_month != max_month:
        all_months = sorted(
            conn.execute(
                "SELECT DISTINCT referral_month FROM fct_wait_times ORDER BY referral_month"
            )
            .df()["referral_month"]
            .tolist()
        )
        date_range = st.sidebar.select_slider(
            "Referral month range",
            options=all_months,
            value=(all_months[0], all_months[-1]),
        )

    # Convert to tuples for cached query functions
    providers_t = tuple(providers)
    specialties_t = tuple(specialties)

    # --- KPI cards (D-05) ---
    kpi_df = query_wait_times_kpis(export_date, providers_t, specialties_t)

    if kpi_df.empty:
        st.warning("No data for selected filters")
        st.markdown(
            "Try widening the date range or removing provider filters. "
            f"Export date {export_date} is loaded."
        )
        return

    breach_rate = (kpi_df["breach_rate_18wk"].iloc[0] or 0) * 100
    median_wait = kpi_df["median_wait_days"].iloc[0] or 0
    waiters_52wk = int(kpi_df["waiters_52wk"].iloc[0] or 0)

    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric(
            label="18-Week Breach Rate",
            value=f"{breach_rate:.1f}%",
            delta_color="inverse",
            help="Percentage of patients waiting longer than 18 weeks from referral to treatment (RTT). The NHS target is no more than 8% breaching (i.e. 92% treated within 18 weeks).",
        )
    with c2:
        st.metric(
            label="Median Wait (Days)",
            value=f"{median_wait:.0f}",
            delta_color="inverse",
            help="The middle value (P50) of all waiting times in days. Half of patients wait less than this, half wait more.",
        )
    with c3:
        st.metric(
            label="52-Week+ Waiters",
            value=f"{waiters_52wk:,}",
            delta_color="inverse",
            help="Number of patients who have been waiting over 52 weeks (1 year) for treatment. NHS England tracks this as a critical long-wait metric.",
        )

    # --- Divider ---
    st.divider()

    # --- Charts (D-06) ---
    # Chart 1: P50/P90 wait by provider (grouped bar)
    provider_df = query_wait_by_provider(export_date, providers_t, specialties_t)
    if not provider_df.empty:
        fig_bar = grouped_bar(
            provider_df,
            "provider_name",
            ["p50_wait", "p90_wait"],
            ["P50 Wait", "P90 Wait"],
            "Wait Days by Provider",
            "Provider",
            "Days",
        )
        st.plotly_chart(fig_bar, use_container_width=True)

    # Chart 2: Wait time trend by referral_month (line)
    trend_df = query_wait_trend(export_date, providers_t, specialties_t)
    if not trend_df.empty:
        # Filter to selected date range if slider is active
        if date_range is not None:
            range_start, range_end = date_range
            trend_df = trend_df[
                (trend_df["referral_month"] >= range_start)
                & (trend_df["referral_month"] <= range_end)
            ]
        if not trend_df.empty:
            fig_line = line_trend(
                trend_df,
                "referral_month",
                ["p50_wait", "p90_wait"],
                ["P50", "P90"],
                "Wait Time Trend by Month",
                "Referral Month",
                "Days",
            )
            st.plotly_chart(fig_line, use_container_width=True)


_run()
