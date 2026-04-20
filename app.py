"""
app.py — BAMPR-II experiment log.

Entry point only. Responsible for:
  - Page config
  - Session state initialisation
  - Sidebar
  - Tab layout (delegates rendering to log_tab and visualisation)
"""

import pathlib
from datetime import datetime

import streamlit as st

from config import load_config, col_name
from sheets import get_sheet_logger
from utility import format_counter
from tab_log import render_log_tab
from tab_plot import render_plot_tab

# ── Page setup ────────────────────────────────────────────────────────────────

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
logger = get_sheet_logger()

# ── Flush pending widget values ───────────────────────────────────────────────
# Auto-increment widgets stage their next value under _pending_<key> so it can
# be written to the widget key before the widget is drawn on the next rerun.

for group in groups:
    for var in group["variables"]:
        val_key    = f"{group['name']}_{var['name']}"
        widget_key = f"input_{val_key}"
        pending    = f"_pending_{widget_key}"
        if pending in st.session_state:
            st.session_state[widget_key] = st.session_state.pop(pending)

# ── Session state init ────────────────────────────────────────────────────────

for group in groups:
    if f"active_{group['name']}" not in st.session_state:
        st.session_state[f"active_{group['name']}"] = True

for group in groups:
    for var in group["variables"]:
        key = f"{group['name']}_{var['name']}"
        if key not in st.session_state:
            if var.get("type") == "auto_increment":
                c = col_name(group["name"], var["name"])
                last = logger.get_last_counter(c, var)
                next_n = last + 1
                formatted = format_counter(next_n, var)
                st.session_state[key] = formatted
                st.session_state[f"_counter_{key}"] = next_n
                st.session_state[f"input_{key}"] = formatted
            else:
                default = var.get("default", "")
                st.session_state[key] = default
                st.session_state[f"input_{key}"] = default

if "log_message" not in st.session_state:
    st.session_state.log_message = None

if "df_cache" not in st.session_state:
    st.session_state.df_cache = None

# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.image(str(_HERE / "MXI_logo.png"), width=240)
    st.title("Blown-powder Additive Manufacturing Process Replicator, version II (BAMPR-II)")
    st.markdown("---")
    st.subheader("Usage")
    st.text("Fill in variables for the current print. Variables can be reset to the defaults,"
               " or to the last set."
               "\nOnce printed, log the run with the red button at the bottom")
    st.markdown("---")
    st.subheader("Active Equipment")
    st.caption("Toggle which variable sets are relevant for this session.")

    for group in groups:
        if group.get("always_on"):
            st.markdown(f"✅ **{group['name']}** *(always on)*")
        else:
            key = f"active_{group['name']}"
            st.session_state[key] = st.checkbox(
                group["name"],
                value=st.session_state[key],
                key=f"toggle_{group['name']}",
            )

    st.markdown("---")
    st.subheader("Log Details")

    n_rows = logger.row_count()
    if n_rows:
        st.metric("Total Runs Logged", n_rows)
        if st.button("📥 Fetch & Download CSV", width="stretch"):
            with st.spinner("Fetching data..."):
                df_log = logger.load()
            csv_bytes = df_log.to_csv(index=False).encode()
            st.download_button(
                label="⬇️ Click to save",
                data=csv_bytes,
                file_name=f"experiment_log_{datetime.now().strftime('%Y%m%d')}.csv",
                mime="text/csv",
            )
    else:
        st.info("Could not connect to sheet.")

# ── Tabs ──────────────────────────────────────────────────────────────────────

tab_log, tab_plot = st.tabs(["📋 Log Scan", "📈 Plot Results"])

with tab_log:
    render_log_tab(logger, groups)

with tab_plot:
    render_plot_tab(logger, groups, config)