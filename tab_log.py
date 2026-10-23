"""
tab_log.py — Log Scan tab: form session state, input widgets and logging actions.

Session-state keys per variable:
  input_<group>_<var>     the widget's key: the live value
  <group>_<var>           mirror of the value, kept while its group is toggled
                          off (Streamlit drops the key of an unrendered widget)
  _counter_<group>_<var>  integer behind an auto_increment field

Actions run as button on_click callbacks, before any widget of the run is
created. That is the only point at which a widget key may be written, and the
widget key already holds an edit committed just before the click, so _get()
reads it in preference to the mirror.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from config import auto_increment_cols, col_name, default_value
from sheets import SheetLogger
from utility import format_counter

NCOL = 3  # input cards per row


# ── Session-state helpers ─────────────────────────────────────────────────────

def _key(group: dict, var: dict) -> str:
    return f"{group['name']}_{var['name']}"


def _widget_key(group: dict, var: dict) -> str:
    return f"input_{_key(group, var)}"


def _counter_key(group: dict, var: dict) -> str:
    return f"_counter_{_key(group, var)}"


def _get(group: dict, var: dict):
    """Current value: the widget key when present, else the mirror."""
    wkey = _widget_key(group, var)
    if wkey in st.session_state:
        return st.session_state[wkey]
    return st.session_state.get(_key(group, var))


def _set(group: dict, var: dict, value) -> None:
    """Set a variable's value. Only valid before the widget renders (init or callbacks)."""
    st.session_state[_key(group, var)] = value
    st.session_state[_widget_key(group, var)] = value


def _set_counter(group: dict, var: dict, n: int) -> None:
    st.session_state[_counter_key(group, var)] = n
    _set(group, var, format_counter(n, var))


def _sync_counter_from_sheet(group: dict, var: dict, logger: SheetLogger) -> None:
    last = logger.get_last_counter(col_name(group["name"], var["name"]), var)
    _set_counter(group, var, last + 1)


def _resync_counter(group: dict, var: dict, logger: SheetLogger) -> None:
    """Button callback: drop the cached sheet read and re-derive the counter."""
    logger.refresh()
    _sync_counter_from_sheet(group, var, logger)


def _flash(kind: str, text: str) -> None:
    st.session_state.log_message = (kind, text)


def _is_blank(value) -> bool:
    return value is None or str(value).strip() == ""


def _coerce(var: dict, value):
    """Coerce a cell read back from the sheet into the type the variable's widget expects."""
    if pd.isna(value) or value == "":
        return default_value(var)
    vtype = var.get("type", "text")
    # Numeric columns with blanks are float; show a whole number as "7", not "7.0".
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    try:
        if vtype == "float":
            return float(value)
        if vtype == "integer":
            return int(float(value))
        if vtype == "select":
            return next((o for o in var.get("options", []) if str(o) == str(value)), None)
        return str(value)
    except (TypeError, ValueError):
        return default_value(var)


def init_session_state(groups: list, logger: SheetLogger) -> None:
    """Call once per rerun, before any widget renders: seed missing values."""
    st.session_state.setdefault("log_message", None)
    for group in groups:
        for var in group["variables"]:
            if _key(group, var) not in st.session_state:
                if var.get("type") == "auto_increment":
                    _sync_counter_from_sheet(group, var, logger)
                else:
                    _set(group, var, default_value(var))


# ── Frequent fields (per session) ─────────────────────────────────────────────

PINNED_KEY = "pinned_fields"  # multiselect widget key: list of "Group: Variable" names
THRESHOLD_KEY = "pins_threshold"  # slider widget key: percentage of runs a field must change in
DEFAULT_THRESHOLD_PCT = 10        # slider default
RECENT_RUNS = 100                 # how many of the latest runs the auto-pick looks at


def render_pin_controls(groups: list, active_groups: list, logger: SheetLogger) -> None:
    """
    Sidebar picker for the fields shown together in the ⭐ Frequent card at the
    top of the Log tab, plus a button that picks them from the log automatically.
    Pinned fields keep their widget key, so values persist, and still log to
    their own group's column.
    """
    options = [col_name(g["name"], v["name"]) for g in groups for v in g["variables"]]
    if PINNED_KEY in st.session_state:  # drop fields removed from the config
        st.session_state[PINNED_KEY] = [c for c in st.session_state[PINNED_KEY] if c in options]
    st.multiselect(
        "Frequent fields", options=options, key=PINNED_KEY,
        placeholder="Type to search fields…",
        help="Fields that change often. They appear in a ⭐ Frequent card at the top "
             "of the Log tab (in the order picked) and are removed from their own card.",
    )
    st.slider(
        "Changed in more than … % of recent runs", min_value=5, max_value=50, step=5,
        value=DEFAULT_THRESHOLD_PCT, key=THRESHOLD_KEY,
        help=f"A field qualifies when its value differed from the previous run in more than "
             f"this share of the last {RECENT_RUNS} runs.",
    )
    st.button(
        "✨ Pick frequently changed fields", key="pins_suggest", width="stretch",
        help="Reads the sheet and pins every qualifying field, most frequently changed first. "
             "Run IDs and scan numbers are skipped because they change every run.",
        on_click=_suggest_pins, args=(active_groups, logger),
    )
    if message := st.session_state.pop("pins_message", None):
        st.caption(message)
    _render_pin_order()


def _render_pin_order() -> None:
    """One row per pinned field with ▲ ▼ buttons; the order is the Frequent card's order."""
    pinned = st.session_state.get(PINNED_KEY) or []
    if len(pinned) < 2:
        return
    st.caption("Order on the Frequent card:")
    names = [c.split(": ", 1)[-1] for c in pinned]
    last = len(pinned) - 1
    for i, col in enumerate(pinned):
        label = names[i] if names.count(names[i]) == 1 else col  # disambiguate duplicates
        c_up, c_down, c_label = st.columns([1, 1, 5], vertical_alignment="center")
        c_up.button("▲", key=f"pin_up_{col}", disabled=i == 0, help="Move up",
                    on_click=_move_pin, args=(col, -1))
        c_down.button("▼", key=f"pin_down_{col}", disabled=i == last, help="Move down",
                      on_click=_move_pin, args=(col, +1))
        c_label.markdown(label)


def _move_pin(col: str, step: int) -> None:
    """Button callback: swap a pinned field with its neighbour."""
    pinned = list(st.session_state.get(PINNED_KEY) or [])
    if col not in pinned:
        return
    i = pinned.index(col)
    j = i + step
    if 0 <= j < len(pinned):
        pinned[i], pinned[j] = pinned[j], pinned[i]
        st.session_state[PINNED_KEY] = pinned


def _change_counts(df: pd.DataFrame, active_groups: list) -> dict[str, int]:
    """Per field: number of consecutive-run pairs where the logged value differs."""
    counts: dict[str, int] = {}
    for g in active_groups:
        for v in g["variables"]:
            col = col_name(g["name"], v["name"])
            if v.get("type") == "auto_increment" or col not in df.columns:
                continue
            values = df[col].astype(str)
            counts[col] = int((values != values.shift()).iloc[1:].sum())
    return counts


def _suggest_pins(active_groups: list, logger: SheetLogger) -> None:
    """Button callback: pin every field that changed in more than the chosen share of recent runs."""
    threshold = st.session_state.get(THRESHOLD_KEY, DEFAULT_THRESHOLD_PCT) / 100
    logger.refresh()
    df = logger.load().tail(RECENT_RUNS)
    if len(df) < 2:
        st.session_state["pins_message"] = "Need at least two logged runs to analyse."
        return
    pairs = len(df) - 1  # consecutive-run comparisons
    ranked = sorted(_change_counts(df, active_groups).items(), key=lambda kv: -kv[1])
    st.session_state[PINNED_KEY] = [col for col, n in ranked if n / pairs > threshold]
    st.session_state["pins_message"] = (
        f"Pinned {len(st.session_state[PINNED_KEY])} fields that changed in more than "
        f"{threshold:.0%} of the last {len(df)} runs."
    )


def _pinned_fields(active_groups: list) -> list[tuple[dict, dict]]:
    """(group, var) pairs pinned to the Frequent card, in pinned order."""
    pinned = st.session_state.get(PINNED_KEY) or []
    pairs = [
        (g, v) for g in active_groups for v in g["variables"]
        if col_name(g["name"], v["name"]) in pinned
    ]
    return sorted(pairs, key=lambda gv: pinned.index(col_name(gv[0]["name"], gv[1]["name"])))


# ── Actions ───────────────────────────────────────────────────────────────────

def load_last_values(groups: list, logger: SheetLogger) -> None:
    """Fill every non-counter field from the most recent row in the sheet."""
    df = logger.load()
    if df.empty:
        _flash("error", "No previous runs to load.")
        return
    last = df.iloc[-1]
    for group in groups:
        for var in group["variables"]:
            if var.get("type") == "auto_increment":
                continue
            column = col_name(group["name"], var["name"])
            if column in last.index:
                _set(group, var, _coerce(var, last[column]))


def reset_fields(groups: list, logger: SheetLogger) -> None:
    """Reset all fields to their defaults and re-sync counters from the sheet."""
    logger.refresh()
    for group in groups:
        for var in group["variables"]:
            if var.get("type") == "auto_increment":
                _sync_counter_from_sheet(group, var, logger)
            else:
                _set(group, var, default_value(var))


def handle_log_run(
    groups: list, active_groups: list, logger: SheetLogger, timezone: str | None
) -> None:
    """Validate required fields, write the row, then advance auto-increment counters."""
    if not active_groups:
        _flash("error", "No equipment groups are active. Enable some in the sidebar.")
        return

    missing = [
        var["name"]
        for group in active_groups
        for var in group["variables"]
        if var.get("required") and _is_blank(_get(group, var))
    ]
    if missing:
        _flash("error", f"Please fill in required fields: {', '.join(missing)}")
        return

    # Another user may have logged since this page loaded. Skip past any counter
    # value that is already in the sheet, unless the operator typed their own.
    notes: list[str] = []
    logger.refresh()
    if logger.load().empty and logger.last_error:
        _flash("error", f"❌ Not logged: could not read the sheet to check counters ({logger.last_error}).")
        return
    for group in active_groups:
        for var in group["variables"]:
            if var.get("type") != "auto_increment":
                continue
            n = st.session_state.get(_counter_key(group, var))
            if n is None or _get(group, var) != format_counter(n, var):
                continue
            last = logger.get_last_counter(col_name(group["name"], var["name"]), var)
            if last >= n:
                _set_counter(group, var, last + 1)
                notes.append(
                    f"{var['name']} moved on to {format_counter(last + 1, var)} "
                    f"because {format_counter(n, var)} was already logged"
                )

    now = datetime.now(ZoneInfo(timezone)) if timezone else datetime.now()
    row = {"Timestamp": now.strftime("%Y-%m-%d %H:%M:%S")}
    for group in active_groups:
        for var in group["variables"]:
            row[col_name(group["name"], var["name"])] = _get(group, var)

    try:
        logger.append(row)
    except Exception as e:
        _flash("error", f"❌ Failed to write to Google Sheets: {e}")
        return

    # Report the first auto_increment column in *config* order (the Run ID),
    # whatever order the cards are shown in this session.
    id_col = next((c for c in auto_increment_cols(groups) if c in row), None)
    run_id = row[id_col] if id_col else "—"

    for group in active_groups:
        for var in group["variables"]:
            if var.get("type") == "auto_increment":
                current = st.session_state.get(_counter_key(group, var), int(var.get("start", 1)))
                _set_counter(group, var, current + 1)

    message = f"✅ Run '{run_id}' logged at {row['Timestamp']}"
    if notes:
        message += "  \n⚠️ " + "; ".join(notes)
    _flash("success", message)


# ── Rendering ─────────────────────────────────────────────────────────────────

def render_action_buttons(
    logger: SheetLogger, active_groups: list, groups: list,
    timezone: str | None, location: str, stacked: bool = False,
) -> None:
    """
    Use Last Values / Log Run / Reset Fields as on_click callbacks.
    *location* keeps widget keys unique between the sidebar and the tab.
    """
    slots = [st.container() for _ in range(3)] if stacked else st.columns(3)

    slots[0].button("⏮️ Use Last Values", key=f"last_{location}", width="stretch",
                    on_click=load_last_values, args=(groups, logger))
    slots[1].button("📋 Log Run", key=f"log_{location}", type="primary", width="stretch",
                    on_click=handle_log_run, args=(groups, active_groups, logger, timezone))
    slots[2].button("🔄 Reset Fields", key=f"reset_{location}", width="stretch",
                    on_click=reset_fields, args=(groups, logger))


def render_log_tab(
    logger: SheetLogger, active_groups: list, groups: list, timezone: str | None
) -> None:
    st.title("Experiment Logger")
    _flash_message()

    if not active_groups:
        st.warning("No equipment groups are active. Enable some in the sidebar.")
    else:
        _render_input_cards(active_groups, logger)
        st.markdown("---")
        render_action_buttons(logger, active_groups, groups, timezone, location="tab")

    st.markdown("---")
    _render_recent_runs(logger)


def _flash_message() -> None:
    """Display and clear any message left by an action on the previous rerun."""
    message = st.session_state.get("log_message")
    if message:
        kind, text = message
        (st.success if kind == "success" else st.error)(text)
        st.session_state.log_message = None


def _render_input_cards(active_groups: list, logger: SheetLogger) -> None:
    """
    Render the ⭐ Frequent card (pinned fields, full width) followed by one
    bordered card per active group in an NCOL-column grid, minus pinned fields.
    """
    pinned = _pinned_fields(active_groups)
    if pinned:
        with st.container(border=True):
            st.subheader("⭐ Frequent")
            cols = st.columns(NCOL)
            for i, (group, var) in enumerate(pinned):
                with cols[i % NCOL]:
                    _render_variable_input(group, var, logger, label=f"{var['name']}  ·  {group['name']}")

    pinned_set = {col_name(g["name"], v["name"]) for g, v in pinned}
    cards = [
        (group, [v for v in group["variables"] if col_name(group["name"], v["name"]) not in pinned_set])
        for group in active_groups
    ]
    cards = [(group, variables) for group, variables in cards if variables]

    for i in range(0, len(cards), NCOL):
        cols = st.columns(NCOL)
        for col, (group, variables) in zip(cols, cards[i : i + NCOL]):
            with col, st.container(border=True):
                st.subheader(group["name"])
                for var in variables:
                    _render_variable_input(group, var, logger)


def _render_variable_input(
    group: dict, var: dict, logger: SheetLogger, label: str | None = None
) -> None:
    """Render the right widget for one variable and mirror its value into session state."""
    key, wkey = _key(group, var), _widget_key(group, var)
    vtype = var.get("type", "text")
    label = label or var["name"]
    if var.get("required"):
        label += " *"
    help_text = var.get("help") or None

    # Restore the widget key from the mirror after the group was toggled off.
    if wkey not in st.session_state:
        st.session_state[wkey] = st.session_state[key]

    if vtype == "auto_increment":
        c1, c2 = st.columns([3, 1])
        with c1:
            value = st.text_input(
                label, key=wkey,
                help=help_text or "Auto-increments on log. Edit manually to override.",
            )
        with c2:
            st.markdown("<br>", unsafe_allow_html=True)
            st.button("🔁", key=f"resync_{key}", help="Re-sync from sheet",
                      on_click=_resync_counter, args=(group, var, logger))
    elif vtype == "float":
        value = st.number_input(label, key=wkey, format="%.3f", help=help_text)
    elif vtype == "integer":
        value = st.number_input(label, key=wkey, step=1, help=help_text)
    elif vtype == "select":
        value = st.selectbox(
            label, options=var.get("options", []), key=wkey,
            help=help_text, placeholder="Select…",
        )
    else:
        value = st.text_input(label, key=wkey, help=help_text)

    st.session_state[key] = value


def _render_recent_runs(logger: SheetLogger) -> None:
    with st.expander("📊 View Recent Runs", expanded=False):
        df_log = logger.load()
        if df_log.empty:
            st.info("Nothing logged yet.")
        else:
            st.dataframe(df_log.tail(20).iloc[::-1], width="stretch", hide_index=True)
            st.caption(f"Showing last 20 of {len(df_log)} total runs.")
