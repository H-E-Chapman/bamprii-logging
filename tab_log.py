"""
tab_log.py — Renders the Log Scan tab (tab 1).

Call render_log_tab(logger, groups) from app.py inside the tab_log
context manager.
"""

from datetime import datetime

import streamlit as st

from config import col_name
from sheets import SheetLogger
from utility import format_counter


def render_log_tab(logger: SheetLogger, groups: list) -> None:
    st.title("Experiment Logger")

    _flash_message()

    active_groups = [
        g for g in groups
        if g.get("always_on") or st.session_state.get(f"active_{g['name']}")
    ]

    if not active_groups:
        st.warning("No equipment groups are active. Enable some in the sidebar.")
    else:
        _render_input_cards(active_groups, logger)
        _render_action_buttons(active_groups, groups, logger)

    st.markdown("---")
    _render_recent_runs(logger)


# ── Private helpers ───────────────────────────────────────────────────────────

def _flash_message() -> None:
    """Display and clear any success/error message left by the previous rerun."""
    if st.session_state.log_message:
        msg_type, msg_text = st.session_state.log_message
        (st.success if msg_type == "success" else st.error)(msg_text)
        st.session_state.log_message = None


def _render_input_cards(active_groups: list, logger: SheetLogger) -> None:
    """Render variable input cards in a two-column grid."""
    for i in range(0, len(active_groups), 2):
        cols = st.columns(2)
        for j, group in enumerate(active_groups[i : i + 2]):
            with cols[j]:
                with st.container(border=True):
                    st.subheader(group["name"])
                    for var in group["variables"]:
                        _render_variable_input(group, var, logger)

def _load_last_values(groups: list, logger: SheetLogger) -> None:
    df = logger.load()

    if df.empty:
        st.session_state["log_message"] = ("error", "No previous runs to load.")
        return

    last_row = df.iloc[-1]

    updates = {}

    for group in groups:
        for var in group["variables"]:
            if var.get("type") == "auto_increment":
                continue
            base_key = f"{group['name']}_{var['name']}"
            column = col_name(group["name"], var["name"])

            if column in last_row.index:
                updates[base_key] = last_row[column]

    for k, v in updates.items():
        st.session_state[k] = v
        st.session_state[f"_pending_input_{k}"] = v

def _render_action_buttons(active_groups: list, groups: list, logger: SheetLogger) -> None:
    """Render the Log Run and Reset Fields buttons and handle their actions."""
    st.markdown("---")
    col1, col2, col3 = st.columns([1,2,1])

    with col1:
        if st.button("⏮️ Use Last Values", width="stretch"):
            _load_last_values(groups, logger)
            st.rerun()

    with col2:
        if st.button("📋 Log Run", type="primary", width="stretch"):
            _handle_log_run(active_groups, logger)
            st.rerun()

    with col3:
        if st.button("🔄 Reset Fields", width="stretch"):
            _reset_fields(groups, logger)
            st.rerun()



def _render_recent_runs(logger: SheetLogger) -> None:
    """Render the recent runs expander at the bottom of the tab."""
    with st.expander("📊 View Recent Runs", expanded=False):
        with st.spinner("Loading..."):
            df_log = logger.load()
        if df_log.empty:
            st.info("Nothing logged yet.")
        else:
            st.dataframe(df_log.tail(20).iloc[::-1], width="stretch", hide_index=True)
            st.caption(f"Showing last 20 of {len(df_log)} total runs.")


def _render_variable_input(group: dict, var: dict, logger: SheetLogger) -> None:
    """Render the correct Streamlit widget for a single variable."""
    val_key = f"{group['name']}_{var['name']}"
    vtype = var.get("type", "text")
    display_label = f"{var['name']} *" if var.get("required") else var["name"]
    help_text=var.get("help","")

    if vtype == "auto_increment":
        c1, c2 = st.columns([3, 1])
        with c1:
            override = st.text_input(
                display_label,
                key=f"input_{val_key}",
                help=help_text or "Auto-increments on log. Edit manually to override.",
            )
            st.session_state[val_key] = override
        with c2:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("🔁", key=f"resync_{val_key}", help="Re-sync from sheet"):
                _resync_counter(group, var, val_key, logger)
                st.rerun()

    elif vtype == "float":
        st.session_state[val_key] = st.number_input(
            display_label,
            key=f"input_{val_key}",
            format="%.3f",
            help=help_text,
        )
    elif vtype == "integer":
        st.session_state[val_key] = st.number_input(
            display_label,
            key=f"input_{val_key}",
            step=1,
            help=help_text,
        )
    elif vtype == "select":
        options = var.get("options", [])
        st.session_state[val_key] = st.selectbox(
            display_label,
            options=options,
            key=f"input_{val_key}",
            help=help_text,
        )
    else:
        st.session_state[val_key] = st.text_input(
            display_label,
            key=f"input_{val_key}",
            help=help_text,
        )


def _resync_counter(group: dict, var: dict, val_key: str, logger: SheetLogger) -> None:
    """Pull the latest counter value from the sheet and stage it for the next rerun."""
    c = col_name(group["name"], var["name"])
    last = logger.get_last_counter(c, var)
    next_n = last + 1
    formatted = format_counter(next_n, var)
    st.session_state[val_key] = formatted
    st.session_state[f"_counter_{val_key}"] = next_n
    st.session_state[f"_pending_input_{val_key}"] = formatted


def _reset_fields(groups: list, logger: SheetLogger) -> None:
    """Reset all fields to defaults, re-syncing auto-increment counters from the sheet."""
    for group in groups:
        for var in group["variables"]:
            key = f"{group['name']}_{var['name']}"
            if var.get("type") == "auto_increment":
                _resync_counter(group, var, key, logger)
            else:
                st.session_state[key] = var.get("default", "")


def _handle_log_run(active_groups: list, logger: SheetLogger) -> None:
    """Validate required fields, write the row, then advance auto-increment counters."""
    missing = [
        var["name"]
        for group in active_groups
        for var in group["variables"]
        if var.get("required")
        and not str(st.session_state[f"{group['name']}_{var['name']}"]).strip()
    ]

    if missing:
        st.session_state.log_message = (
            "error",
            f"Please fill in required fields: {', '.join(missing)}",
        )
        st.rerun()
        return

    row = {"Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    for group in active_groups:
        for var in group["variables"]:
            row[col_name(group["name"], var["name"])] = (
                st.session_state[f"{group['name']}_{var['name']}"]
            )

    try:
        with st.spinner("Saving to Google Sheets..."):
            logger.append(row)

        for group in active_groups:
            for var in group["variables"]:
                if var.get("type") == "auto_increment":
                    key = f"{group['name']}_{var['name']}"
                    counter_key = f"_counter_{key}"
                    current_n = st.session_state.get(counter_key, int(var.get("start", 1)))
                    next_n = current_n + 1
                    formatted = format_counter(next_n, var)
                    st.session_state[key] = formatted
                    st.session_state[counter_key] = next_n
                    st.session_state[f"_pending_input_{key}"] = formatted

        run_id = row.get(col_name("General", "Run ID"), "—")
        st.session_state.log_message = (
            "success",
            f"✅ Run '{run_id}' logged at {row['Timestamp']}",
        )
    except Exception as e:
        st.session_state.log_message = (
            "error",
            f"❌ Failed to write to Google Sheets: {e}",
        )

    st.rerun()