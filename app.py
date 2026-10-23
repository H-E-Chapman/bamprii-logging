"""
app.py — BAMPR-II experiment log.

Entry point only: page config, config and sheet connection, session state,
sidebar, and the tab layout. All rendering is delegated to the tab_* modules.
"""

import pathlib
from datetime import datetime

import streamlit as st

from config import load_config
from sheets import get_sheet_logger
from tab_log import (
    init_session_state, render_action_buttons, render_log_tab, render_pin_controls,
)
from tab_plot import render_plot_tab
from tab_DoE import render_doe_tab
from tab_calc import render_calc_tab

_HERE = pathlib.Path(__file__).parent

st.set_page_config(
    page_title="BAMPR-II Log",
    page_icon=str(_HERE / "MXI.png"),
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Config + shared objects ───────────────────────────────────────────────────

config = load_config()
groups = config["groups"]
timezone = config.get("timezone")
logger = get_sheet_logger()

init_session_state(groups, logger)

active_groups = [
    g for g in groups
    if g.get("always_on") or st.session_state.get(f"toggle_{g['name']}", True)
]

# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.image(str(_HERE / "MXI_logo.png"), width=240)
    st.title("Blown-powder Additive Manufacturing Process Replicator, version II (BAMPR-II)")
    st.markdown("---")
    st.subheader("Usage")
    st.text(
        "Fill in variables for the current print. Variables can be reset to the defaults,"
        " or to the last set."
        "\nOnce printed, log the run with the red button at the bottom"
    )
    st.markdown("---")

    render_action_buttons(
        logger, active_groups, groups, timezone, location="sidebar", stacked=True
    )
    st.link_button("Directly Access Logging Sheet", logger.url, width="stretch")

    st.markdown("---")
    st.subheader("Active Equipment")
    st.caption("Toggle which variable sets are relevant for this session.")
    for group in groups:
        if group.get("always_on"):
            st.markdown(f"✅ **{group['name']}** *(always on)*")
        else:
            st.checkbox(group["name"], value=True, key=f"toggle_{group['name']}")

    st.markdown("---")
    st.subheader("⭐ Frequent Fields")
    st.caption("Pick fields that change every run to show them together at the top of the Log tab.")
    render_pin_controls(groups, active_groups, logger)

    st.markdown("---")
    st.subheader("Log Details")
    df_log = logger.load()
    if logger.last_error:
        st.warning(f"Could not connect to the sheet: {logger.last_error}")
    else:
        st.metric("Total Runs Logged", len(df_log))
    if not df_log.empty:
        st.download_button(
            "⬇️ Download log as CSV",
            data=df_log.to_csv(index=False).encode(),
            file_name=f"experiment_log_{datetime.now().strftime('%Y%m%d')}.csv",
            mime="text/csv",
            width="stretch",
        )

# ── Tabs ──────────────────────────────────────────────────────────────────────

tab_log, tab_plot, tab_doe, tab_calc = st.tabs(
    ["📋 Log Scan", "📈 Plot Results", "🔬 Experiment Design", "🧮 Calculators"]
)
with tab_log:
    render_log_tab(logger, active_groups, groups, timezone)
with tab_plot:
    render_plot_tab(logger, groups, config)
with tab_doe:
    render_doe_tab()
with tab_calc:
    render_calc_tab(config)
