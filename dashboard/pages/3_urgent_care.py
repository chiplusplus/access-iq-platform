"""Urgent Care -- A&E 4h/12h breaches, admission, equity overlay."""

from __future__ import annotations

import streamlit as st

from lib.charts import (
    grouped_bar,
    heatmap_chart,
    line_trend,
    stacked_bar,
)
from lib.data import (
    data_freshness_text,
    get_connection,
    query_uc_breach_trend,
    query_uc_busiest_hours,
    query_uc_equity,
    query_uc_stage_times,
    query_urgent_care_kpis,
    register_tables,
)
from lib.s3 import get_bucket

# Day ordering for heatmap (Mon-Sun)
_DAY_ORDER = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _render_heatmap(export_date: str | None, providers_t: tuple[str, ...]) -> None:
    """Busiest hours heatmap -- shared between equity ON and OFF modes."""
    df_hours = query_uc_busiest_hours(export_date, providers_t)
    if df_hours.empty:
        st.warning("No data for selected filters")
        return
    # Pivot to day_of_week rows x hour_of_day columns, ordered Mon-Sun
    pivot = df_hours.pivot_table(
        index="day_of_week", columns="hour_of_day", values="attendance_count", aggfunc="sum"
    )
    # Reindex to Mon-Sun order (only include days present in data)
    ordered_days = [d for d in _DAY_ORDER if d in pivot.index]
    if ordered_days:
        pivot = pivot.reindex(ordered_days)
    fig = heatmap_chart(
        df_hours,
        "hour_of_day",
        "day_of_week",
        "attendance_count",
        "Busiest Hours",
        "Hour of Day",
        "Day of Week",
        colorscale=[[0, "#F0F4F5"], [1, "#005EB8"]],
    )
    st.plotly_chart(fig, use_container_width=True)


def _run() -> None:
    # --- Title + freshness badge ---
    st.title("Urgent Care")
    export_date = st.session_state.get("export_date")
    bucket = st.session_state.get("bucket") or get_bucket()
    st.caption(data_freshness_text(export_date))

    # --- Register tables (D-02 lazy-load) ---
    conn = get_connection()
    register_tables(conn, bucket, export_date, ["fct_urgent_care", "dim_site", "dim_patient"])

    # --- Sidebar filters (D-13) ---
    # Provider multiselect
    providers_df = conn.execute(
        "SELECT DISTINCT provider_name FROM dim_site ORDER BY provider_name"
    ).df()
    all_providers = providers_df["provider_name"].tolist()
    providers: list[str] = st.sidebar.multiselect("Provider", options=all_providers)

    # Equity overlay toggle (D-14, D-15)
    equity_on: bool = st.sidebar.toggle("Show demographic breakdown", value=False)

    equity_stratifier = "IMD Decile"
    if equity_on:
        equity_stratifier = st.sidebar.selectbox(
            "Stratifier",
            options=["IMD Decile", "Ethnicity", "Age Band", "Sex"],
            index=0,
        )
        st.info(
            f"Charts now show demographic breakdown by {equity_stratifier}. "
            "Toggle off to return to aggregate view."
        )

    # Convert filter lists to tuples
    providers_t = tuple(providers)

    # --- KPI cards (D-11) ---
    kpi_df = query_urgent_care_kpis(export_date, providers_t)

    if kpi_df.empty:
        st.warning("No data for selected filters")
        st.markdown(
            "Try widening the date range or removing provider filters. "
            f"Export date {export_date} is loaded."
        )
        return

    breach_rate_4h = (kpi_df["breach_rate_4h"].iloc[0] or 0) * 100
    breach_count_12h = int(kpi_df["breach_count_12h"].iloc[0] or 0)
    admission_rate = (kpi_df["admission_rate"].iloc[0] or 0) * 100

    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric(
            label="4-Hour Breach Rate",
            value=f"{breach_rate_4h:.1f}%",
            delta_color="inverse",
            help="Percentage of A&E attendances where the patient waited more than 4 hours from arrival to admission, transfer, or discharge. NHS operational standard is 95% within 4 hours.",
        )
    with c2:
        st.metric(
            label="12-Hour Breaches",
            value=f"{breach_count_12h:,}",
            delta_color="inverse",
            help="Total number of patients spending more than 12 hours in A&E from arrival to departure. These are reportable critical incidents under NHS England guidance.",
        )
    with c3:
        st.metric(
            label="Admission Conversion Rate",
            value=f"{admission_rate:.1f}%",
            delta_color="normal",
            help="Percentage of A&E attendances that resulted in hospital admission. Higher rates may indicate more acute presentations or limited community alternatives.",
        )

    # --- Divider ---
    st.divider()

    # --- Charts ---
    if not equity_on:
        # Mode A: Equity OFF (default, D-12)

        # Chart 1: Stage times stacked bar
        df_stage = query_uc_stage_times(export_date, providers_t)
        if not df_stage.empty:
            fig_stage = stacked_bar(
                df_stage,
                "provider_name",
                ["avg_triage", "avg_seen", "avg_discharge"],
                ["Triage", "Seen by Clinician", "Discharge"],
                "Average Time by Stage",
                "Provider",
                "Minutes",
            )
            st.plotly_chart(fig_stage, use_container_width=True)

        # Chart 2: 4h breach trend
        df_trend = query_uc_breach_trend(export_date, providers_t)
        if not df_trend.empty:
            df_trend = df_trend.copy()
            df_trend["breach_rate_4h"] = df_trend["breach_rate_4h"] * 100
            fig_trend = line_trend(
                df_trend,
                "arrival_month",
                ["breach_rate_4h"],
                ["4h Breach Rate"],
                "4-Hour Breach Rate Trend",
                "Arrival Month",
                "Breach Rate (%)",
            )
            st.plotly_chart(fig_trend, use_container_width=True)

        # Chart 3: Busiest hours heatmap
        _render_heatmap(export_date, providers_t)

    else:
        # Mode B: Equity ON (D-15, D-16)
        df_equity = query_uc_equity(export_date, providers_t, equity_stratifier)

        if df_equity.empty:
            st.warning("No data for selected filters")
            return

        # Chart 1: Stage times BY STRATUM (grouped bar)
        fig_equity_stage = grouped_bar(
            df_equity,
            "stratum",
            ["avg_triage", "avg_seen", "avg_discharge"],
            ["Triage", "Seen by Clinician", "Discharge"],
            f"Average Time by Stage - by {equity_stratifier}",
            equity_stratifier,
            "Minutes",
        )
        st.plotly_chart(fig_equity_stage, use_container_width=True)

        # Chart 2: 4h breach rate BY STRATUM (grouped bar)
        df_equity_breach = df_equity.copy()
        df_equity_breach["breach_rate_4h"] = df_equity_breach["breach_rate_4h"] * 100
        fig_equity_breach = grouped_bar(
            df_equity_breach,
            "stratum",
            ["breach_rate_4h"],
            ["4h Breach Rate"],
            f"4-Hour Breach Rate by {equity_stratifier}",
            equity_stratifier,
            "Breach Rate (%)",
        )
        st.plotly_chart(fig_equity_breach, use_container_width=True)

        # Chart 3: Busiest hours heatmap -- UNCHANGED from Mode A
        _render_heatmap(export_date, providers_t)


_run()
