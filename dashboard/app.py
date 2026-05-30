"""Access-IQ NHS Trust Analytics Dashboard."""

from __future__ import annotations

import streamlit as st
from dashboard.lib.s3 import get_bucket, get_data_source, list_export_dates, list_local_export_dates

st.set_page_config(
    page_title="Access-IQ | Northshire NHS Trust",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("Access-IQ | Northshire NHS Trust")

# Shared sidebar: export date picker (D-04)
source = get_data_source()
bucket = get_bucket()

if source == "s3" and bucket:
    dates = list_export_dates(bucket)
    if dates:
        selected_date = st.sidebar.selectbox("Export date", options=dates, index=0)
    else:
        selected_date = None
        st.warning("No export dates found in S3.")
else:
    # Local fallback: discover dates from filesystem (D-04, D-18)
    local_dates = list_local_export_dates()
    if local_dates:
        selected_date = st.sidebar.selectbox("Export date (local)", options=local_dates, index=0)
    else:
        # No partitioned data -- will read all parquet directly
        selected_date = None

st.session_state["export_date"] = selected_date
st.session_state["bucket"] = bucket
st.session_state["data_source"] = source

st.markdown("Select a page from the sidebar to view analytics.")
