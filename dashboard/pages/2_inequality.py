"""Inequality -- IMD deprivation, ethnicity, age, sex stratification."""

from __future__ import annotations

import streamlit as st

from lib.charts import (
    bar_with_suppression,
    deviation_bar,
    heatmap_chart,
)
from lib.data import (
    data_freshness_text,
    get_connection,
    query_inequality_by_stratifier,
    query_inequality_kpis,
    register_tables,
)
from lib.s3 import get_bucket

# Map display labels to fct_inequality stratifier column values (T-08-01 allowlist)
STRATIFIER_MAP: dict[str, str] = {
    "IMD Decile": "imd_decile",
    "Ethnicity": "ethnicity_ons",
    "Age Band": "age_band",
    "Sex": "sex",
}


def _run() -> None:
    # --- Title + freshness badge ---
    st.title("Inequality")
    export_date = st.session_state.get("export_date")
    bucket = st.session_state.get("bucket") or get_bucket()
    st.caption(data_freshness_text(export_date))

    # --- Register tables (D-02) ---
    conn = get_connection()
    register_tables(conn, bucket, export_date, ["fct_inequality"])

    # --- Sidebar filters (D-10) ---
    selected_stratifier: str = st.sidebar.selectbox(
        "Stratifier",
        options=["IMD Decile", "Ethnicity", "Age Band", "Sex"],
        index=0,
    )
    stratifier_val = STRATIFIER_MAP[selected_stratifier]

    # --- KPI cards (D-08) ---
    kpi_df = query_inequality_kpis(export_date)

    c1, c2, c3 = st.columns(3)
    with c1:
        sii_help = "Slope Index of Inequality — measures the absolute difference in health outcomes between the most and least deprived groups. Only available when stratified by IMD Decile."
        if selected_stratifier != "IMD Decile":
            st.metric(label="SII (Slope Index)", value="N/A", help=sii_help)
            st.markdown(
                '<span style="color:#768692; font-size:12px;">'
                "N/A — SII requires IMD decile stratifier</span>",
                unsafe_allow_html=True,
            )
        else:
            sii = kpi_df["sii"].iloc[0] if not kpi_df.empty else 0
            sii = sii if sii is not None else 0
            st.metric(
                label="SII (Slope Index)",
                value=f"{sii:.2f}",
                delta_color="inverse",
                help="Slope Index of Inequality — measures the absolute difference in health outcomes between the most and least deprived groups. A positive value means more deprived areas have worse outcomes.",
            )
    with c2:
        imd_gap = kpi_df["imd_gap"].iloc[0] if not kpi_df.empty else 0
        imd_gap = imd_gap if imd_gap is not None else 0
        st.metric(
            label="IMD Gap (Decile 1 vs 10)",
            value=f"{imd_gap:.1f} days",
            delta_color="inverse",
            help="Difference in median wait times between IMD Decile 1 (most deprived) and Decile 10 (least deprived). A large gap signals unequal access to care.",
        )
    with c3:
        suppressed_count = int(kpi_df["suppressed_count"].iloc[0]) if not kpi_df.empty else 0
        st.metric(
            label="Suppressed Cells",
            value=f"{suppressed_count}",
            help="Number of data cells suppressed due to small population counts (< 5 patients). Suppression protects patient confidentiality per NHS statistical disclosure rules.",
        )

    # --- Divider ---
    st.divider()

    # --- Charts (D-09) ---
    df = query_inequality_by_stratifier(export_date, stratifier_val)

    if df.empty:
        st.warning("No data for selected filters")
        st.markdown(
            "Try widening the date range or removing provider filters. "
            f"Export date {export_date} is loaded."
        )
        return

    # Filter for specific metrics
    df_wait = df[df["metric_name"] == "wait_time_median"].copy()

    # Chart 1 (full width): Wait time by selected stratifier with suppression
    if not df_wait.empty:
        fig_wait = bar_with_suppression(
            df_wait,
            "stratum",
            "metric_value",
            f"Wait Time by {selected_stratifier}",
            selected_stratifier,
            "Median Wait (Days)",
        )
        st.plotly_chart(fig_wait, use_container_width=True)

    # Chart 2 + 3 (side by side, 60%/40%)
    col_left, col_right = st.columns([3, 2])

    with col_left:
        # DNA rate by age band -- always show age band regardless of stratifier picker
        df_dna_age = query_inequality_by_stratifier(export_date, "age_band")
        df_dna_age = df_dna_age[df_dna_age["metric_name"] == "dna_rate"].copy()
        if not df_dna_age.empty:
            fig_dna = bar_with_suppression(
                df_dna_age,
                "stratum",
                "metric_value",
                "DNA Rate by Age Band",
                "Age Band",
                "DNA Rate",
            )
            st.plotly_chart(fig_dna, use_container_width=True)

    with col_right:
        # Demographic breakdown heatmap -- pivot metric x stratum
        if not df.empty:
            pivot_df = df[["metric_name", "stratum", "metric_value"]].copy()
            pivot_df = pivot_df.dropna(subset=["metric_value"])
            if not pivot_df.empty:
                fig_heatmap = heatmap_chart(
                    pivot_df,
                    "stratum",
                    "metric_name",
                    "metric_value",
                    f"Demographic Breakdown ({selected_stratifier})",
                    selected_stratifier,
                    "Metric",
                    colorscale=[[0, "#FFFFFF"], [1, "#AE2573"]],
                )
                st.plotly_chart(fig_heatmap, use_container_width=True)

    # Chart 4 (full width): Deviation from Trust average
    if not df_wait.empty:
        mean_val = df_wait["metric_value"].mean()
        df_dev = df_wait[["stratum", "metric_value"]].copy()
        df_dev["deviation"] = df_dev["metric_value"] - mean_val
        df_dev = df_dev.dropna(subset=["deviation"])
        if not df_dev.empty:
            fig_dev = deviation_bar(
                df_dev,
                "stratum",
                "deviation",
                f"Deviation from Trust Average ({selected_stratifier})",
                "Deviation (Days)",
            )
            st.plotly_chart(fig_dev, use_container_width=True)


_run()
