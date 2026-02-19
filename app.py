import streamlit as st
import pandas as pd
import yaml
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
import pathlib
import re
import plotly.express as px
import plotly.graph_objects as go

# ── Paths ─────────────────────────────────────────────────────────────────────

_HERE = pathlib.Path(__file__).parent
CONFIG_FILE = _HERE / "config.yaml"

st.set_page_config(
    page_title="BAMPR-II log",
    page_icon=str(_HERE / "MXI.png"),
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Google Sheets connection ──────────────────────────────────────────────────

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

@st.cache_resource
def get_worksheet():
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    client = gspread.authorize(creds)
    sheet_id = st.secrets["google_sheets"]["sheet_id"]
    spreadsheet = client.open_by_key(sheet_id)
    try:
        worksheet = spreadsheet.worksheet("Log")
    except gspread.WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(title="Log", rows=2000, cols=50)
    return worksheet

def load_log() -> pd.DataFrame:
    try:
        ws = get_worksheet()
        data = ws.get_all_records()
        if not data:
            return pd.DataFrame()
        df = pd.DataFrame(data)
        for col in df.columns:
            converted = pd.to_numeric(df[col], errors="coerce")
            if converted.notna().sum() > 0:
                df[col] = converted
        return df
    except Exception as e:
        st.warning(f"Could not load log from Google Sheets: {e}")
        return pd.DataFrame()

def append_log(row: dict):
    ws = get_worksheet()
    existing = ws.get_all_values()
    if not existing:
        ws.append_row(list(row.keys()), value_input_option="USER_ENTERED")
    else:
        current_headers = existing[0]
        new_headers = [k for k in row.keys() if k not in current_headers]
        if new_headers:
            ws.update("1:1", [current_headers + new_headers])
        current_headers = ws.row_values(1)
        row = {k: row.get(k, "") for k in current_headers}
    ws.append_row(list(row.values()), value_input_option="USER_ENTERED")

# ── Auto-increment helpers ────────────────────────────────────────────────────

def format_counter(n: int, var: dict) -> str:
    fmt = var.get("format", "padded")
    pad = int(var.get("pad", 4))
    prefix = var.get("prefix", "")
    if fmt == "prefixed":
        return f"{prefix}{str(n).zfill(pad)}"
    return str(n).zfill(pad)

def extract_counter(value: str, var: dict) -> int | None:
    fmt = var.get("format", "padded")
    prefix = var.get("prefix", "")
    try:
        if fmt == "prefixed" and prefix:
            stripped = value.replace(prefix, "")
        else:
            stripped = value
        return int(re.sub(r"[^0-9]", "", stripped))
    except (ValueError, TypeError):
        return None

def get_last_counter(col_name: str, var: dict) -> int:
    start = int(var.get("start", 1))
    try:
        ws = get_worksheet()
        all_values = ws.get_all_values()
        if not all_values or len(all_values) < 2:
            return start - 1
        headers = all_values[0]
        if col_name not in headers:
            return start - 1
        col_idx = headers.index(col_name)
        nums = []
        for row in all_values[1:]:
            if col_idx < len(row) and row[col_idx]:
                n = extract_counter(row[col_idx], var)
                if n is not None:
                    nums.append(n)
        return max(nums) if nums else start - 1
    except Exception:
        return start - 1

# ── Load config ───────────────────────────────────────────────────────────────

@st.cache_data
def load_config():
    with open(CONFIG_FILE, "r") as f:
        return yaml.safe_load(f)

config = load_config()
groups = config["groups"]

# ── Session state init ────────────────────────────────────────────────────────

for group in groups:
    key = f"active_{group['name']}"
    if key not in st.session_state:
        st.session_state[key] = True

for group in groups:
    for var in group["variables"]:
        key = f"val_{group['name']}_{var['name']}"
        if key not in st.session_state:
            if var.get("type") == "auto_increment":
                counter_key = f"_counter_{key}"
                if counter_key not in st.session_state:
                    col_name = f"{group['name']} — {var['name']}"
                    last = get_last_counter(col_name, var)
                    next_n = last + 1
                    st.session_state[key] = format_counter(next_n, var)
                    st.session_state[counter_key] = next_n
                else:
                    n = st.session_state[counter_key]
                    st.session_state[key] = format_counter(n, var)
            else:
                st.session_state[key] = var.get("default", "")

if "log_message" not in st.session_state:
    st.session_state.log_message = None

# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("Blown-powder Additive Manufacturing Process Replicator, version II (BAMPR-II)")
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
    st.subheader("Log")

    try:
        ws = get_worksheet()
        all_vals = ws.get_all_values()
        n_rows = max(0, len(all_vals) - 1)
        st.metric("Total Runs Logged", n_rows)
    except Exception:
        st.info("Could not connect to sheet.")
        n_rows = 0

    if n_rows > 0:
        if st.button("📥 Fetch & Download CSV", use_container_width=True):
            with st.spinner("Fetching data..."):
                df_log = load_log()
            csv_bytes = df_log.to_csv(index=False).encode()
            st.download_button(
                label="⬇️ Click to save",
                data=csv_bytes,
                file_name=f"experiment_log_{datetime.now().strftime('%Y%m%d')}.csv",
                mime="text/csv",
            )

# ── Data cache ────────────────────────────────────────────────────────────────

if "df_cache" not in st.session_state:
    st.session_state.df_cache = None

# ── Tabs ──────────────────────────────────────────────────────────────────────

tab_log, tab_plot = st.tabs(["📋 Run Entry", "📈 Plot"])

# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — Run Entry
# ══════════════════════════════════════════════════════════════════════════════

with tab_log:
    st.title("Run Entry")

    if st.session_state.log_message:
        msg_type, msg_text = st.session_state.log_message
        if msg_type == "success":
            st.success(msg_text)
        elif msg_type == "error":
            st.error(msg_text)
        st.session_state.log_message = None

    active_groups = [
        g for g in groups
        if g.get("always_on") or st.session_state.get(f"active_{g['name']}")
    ]

    if not active_groups:
        st.warning("No equipment groups are active. Enable some in the sidebar.")
    else:
        for i in range(0, len(active_groups), 2):
            cols = st.columns(2)
            for j, group in enumerate(active_groups[i : i + 2]):
                with cols[j]:
                    with st.container(border=True):
                        st.subheader(group["name"])
                        for var in group["variables"]:
                            val_key = f"val_{group['name']}_{var['name']}"
                            vtype = var.get("type", "text")
                            label = var["name"]
                            required = var.get("required", False)
                            display_label = f"{label} *" if required else label

                            if vtype == "auto_increment":
                                current_val = st.session_state[val_key]
                                c1, c2 = st.columns([3, 1])
                                with c1:
                                    override = st.text_input(
                                        display_label,
                                        value=current_val,
                                        key=f"input_{val_key}",
                                        help="Auto-increments on log. Edit manually to override.",
                                    )
                                    st.session_state[val_key] = override
                                with c2:
                                    st.markdown("<br>", unsafe_allow_html=True)
                                    if st.button("🔁", key=f"resync_{val_key}", help="Re-sync from sheet"):
                                        col_name = f"{group['name']} — {var['name']}"
                                        last = get_last_counter(col_name, var)
                                        next_n = last + 1
                                        st.session_state[val_key] = format_counter(next_n, var)
                                        st.session_state[f"_counter_{val_key}"] = next_n
                                        st.rerun()
                            elif vtype == "float":
                                st.session_state[val_key] = st.number_input(
                                    display_label,
                                    value=float(st.session_state[val_key]),
                                    key=f"input_{val_key}",
                                    format="%.3f",
                                )
                            elif vtype == "integer":
                                st.session_state[val_key] = st.number_input(
                                    display_label,
                                    value=int(st.session_state[val_key]),
                                    key=f"input_{val_key}",
                                    step=1,
                                )
                            elif vtype == "select":
                                options = var.get("options", [])
                                current = st.session_state[val_key]
                                idx = options.index(current) if current in options else 0
                                st.session_state[val_key] = st.selectbox(
                                    display_label,
                                    options=options,
                                    index=idx,
                                    key=f"input_{val_key}",
                                )
                            else:
                                st.session_state[val_key] = st.text_input(
                                    display_label,
                                    value=str(st.session_state[val_key]),
                                    key=f"input_{val_key}",
                                )

        st.markdown("---")
        col1, col2, col3 = st.columns([1, 1, 3])

        with col1:
            log_pressed = st.button("📋 Log Run", type="primary", use_container_width=True)

        with col2:
            if st.button("🔄 Reset Fields", use_container_width=True):
                for group in groups:
                    for var in group["variables"]:
                        key = f"val_{group['name']}_{var['name']}"
                        if var.get("type") == "auto_increment":
                            col_name = f"{group['name']} — {var['name']}"
                            last = get_last_counter(col_name, var)
                            next_n = last + 1
                            st.session_state[key] = format_counter(next_n, var)
                            st.session_state[f"_counter_{key}"] = next_n
                        else:
                            st.session_state[key] = var.get("default", "")
                st.rerun()

        if log_pressed:
            missing = []
            for group in active_groups:
                for var in group["variables"]:
                    if var.get("required"):
                        val = st.session_state[f"val_{group['name']}_{var['name']}"]
                        if not str(val).strip():
                            missing.append(var["name"])

            if missing:
                st.session_state.log_message = (
                    "error",
                    f"Please fill in required fields: {', '.join(missing)}",
                )
                st.rerun()
            else:
                row = {"Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
                for group in active_groups:
                    for var in group["variables"]:
                        col_name = f"{group['name']} — {var['name']}"
                        row[col_name] = st.session_state[f"val_{group['name']}_{var['name']}"]

                try:
                    with st.spinner("Saving to Google Sheets..."):
                        append_log(row)

                    for group in active_groups:
                        for var in group["variables"]:
                            if var.get("type") == "auto_increment":
                                key = f"val_{group['name']}_{var['name']}"
                                counter_key = f"_counter_{key}"
                                current_n = st.session_state.get(counter_key, int(var.get("start", 1)))
                                next_n = current_n + 1
                                st.session_state[key] = format_counter(next_n, var)
                                st.session_state[counter_key] = next_n

                    run_id = row.get("General — Run ID", "—")
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

    st.markdown("---")
    with st.expander("📊 View Recent Runs", expanded=False):
        with st.spinner("Loading..."):
            df_log = load_log()
        if df_log.empty:
            st.info("Nothing logged yet.")
        else:
            st.dataframe(
                df_log.tail(20).iloc[::-1],
                use_container_width=True,
                hide_index=True,
            )
            st.caption(f"Showing last 20 of {len(df_log)} total runs.")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — Plot
# ══════════════════════════════════════════════════════════════════════════════

with tab_plot:
    st.title("Plot")

    col_refresh, col_info = st.columns([1, 4])
    with col_refresh:
        if st.button("🔄 Load / Refresh Data", type="primary", use_container_width=True):
            with st.spinner("Pulling from Google Sheets..."):
                st.session_state.df_cache = load_log()

    if st.session_state.df_cache is None:
        st.info("Press **Load / Refresh Data** to fetch runs from the sheet.")
        st.stop()

    df = st.session_state.df_cache

    if df.empty:
        st.info("No data logged yet — come back once you have some runs.")
        st.stop()

    with col_info:
        st.caption(f"Loaded **{len(df)}** runs. Press refresh to pull latest data from the sheet.")

        # Force numeric conversion on anything that looks numeric
        for col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="ignore")

    numeric_cols = df.select_dtypes(include="number").columns.tolist()
    categorical_cols = df.select_dtypes(exclude="number").columns.tolist()
    all_cols = df.columns.tolist()

    if len(numeric_cols) < 2:
        st.warning("Need at least 2 numeric columns to plot. Log more runs with numeric fields.")
        st.stop()

    # ── Filter panel ──────────────────────────────────────────────────────────

    # Build the set of columns from groups marked filterable: true in config
    filterable_col_names = set()
    for group in groups:
        if group.get("filterable"):
            for var in group["variables"]:
                filterable_col_names.add(f"{group['name']} — {var['name']}")

    # If no groups are marked filterable, fall back to all categoricals
    if filterable_col_names:
        filterable = [
            c for c in filterable_col_names
            if c in df.columns and 1 < df[c].nunique() <= 30
        ]
    else:
        filterable = [c for c in categorical_cols if 1 < df[c].nunique() <= 30]

    with st.expander("🔍 Filter Data", expanded=True):
        st.caption("Filter runs before plotting.")
        df_filtered = df.copy()
        filter_cols = st.columns(3)

        for i, col in enumerate(filterable):
            with filter_cols[i % 3]:
                unique_vals = sorted(df[col].dropna().unique().tolist(), key=str)
                selected = st.multiselect(
                    col,
                    options=unique_vals,
                    default=unique_vals,
                    key=f"filter_{col}",
                )
                if selected:
                    df_filtered = df_filtered[df_filtered[col].isin(selected)]

        # Date/timestamp range filter
        if "Timestamp" in df.columns:
            df_filtered["Timestamp"] = pd.to_datetime(df_filtered["Timestamp"], errors="coerce")
            valid_dates = df_filtered["Timestamp"].dropna()
            if not valid_dates.empty:
                min_date = valid_dates.min().date()
                max_date = valid_dates.max().date()
                if min_date < max_date:
                    with filter_cols[len(filterable) % 3]:
                        date_range = st.date_input(
                            "Date range",
                            value=(min_date, max_date),
                            min_value=min_date,
                            max_value=max_date,
                            key="filter_date",
                        )
                        if len(date_range) == 2:
                            df_filtered = df_filtered[
                                (df_filtered["Timestamp"].dt.date >= date_range[0]) &
                                (df_filtered["Timestamp"].dt.date <= date_range[1])
                                ]

        st.caption(f"Showing **{len(df_filtered)}** of {len(df)} runs after filtering.")
    # ── Axis selectors ────────────────────────────────────────────────────────

    st.markdown("---")
    st.subheader("Axis Configuration")
    sel_cols = st.columns(3)

    # Only allow plotting columns from filterable groups
    plottable_cols = [
        c for c in filterable_col_names
        if c in df.columns and c in numeric_cols
    ] if filterable_col_names else numeric_cols

    with sel_cols[0]:
        x_col = st.selectbox("X axis", options=plottable_cols, key="plot_x")
    with sel_cols[1]:
        y_col = st.selectbox(
            "Y axis",
            options=[c for c in plottable_cols if c != x_col],
            key="plot_y",
        )
    with sel_cols[2]:
        colour_options = ["(none)"] + [c for c in filterable_col_names if
                                       c in df.columns and c not in (x_col, y_col)]
        colour_col = st.selectbox("Colour by", options=colour_options, key="plot_colour")

    # ── Binning tolerance ─────────────────────────────────────────────────────
    # X/Y values are continuous floats so "same point" needs a binning tolerance.
    # We round each axis to N significant figures before grouping.

    st.markdown("---")
    st.subheader("Point Grouping")
    bin_cols = st.columns([2, 2, 3])

    with bin_cols[0]:
        x_decimals = st.number_input(
            f"Round X to N decimal places",
            min_value=0, max_value=6, value=1, step=1,
            key="bin_x",
            help="Points with the same rounded X & Y value are merged into one bubble.",
        )
    with bin_cols[1]:
        y_decimals = st.number_input(
            f"Round Y to N decimal places",
            min_value=0, max_value=6, value=1, step=1,
            key="bin_y",
        )
    with bin_cols[2]:
        size_scale = st.slider(
            "Max bubble size",
            min_value=20, max_value=100, value=50, step=5,
            key="size_scale",
        )

    # ── Aggregate: count runs per (x_bin, y_bin) ─────────────────────────────

    plot_df = df_filtered.copy()
    plot_df["_x_bin"] = plot_df[x_col].round(int(x_decimals))
    plot_df["_y_bin"] = plot_df[y_col].round(int(y_decimals))

    # For colour: if categorical take the mode per bin; if numeric take the mean
    agg_dict = {"_count": (x_col, "count")}

    if colour_col != "(none)" and colour_col in plot_df.columns:
        if colour_col in numeric_cols:
            agg_dict["_colour"] = (colour_col, "mean")
        else:
            agg_dict["_colour"] = (colour_col, lambda x: x.mode().iloc[0] if len(x) > 0 else "")

    # Collect run IDs for hover tooltip
    id_col = next((c for c in all_cols if "run" in c.lower() and "id" in c.lower()), None)
    if id_col:
        agg_dict["_runs"] = (id_col, lambda x: ", ".join(x.astype(str).tolist()))

    grouped = (
        plot_df
        .groupby(["_x_bin", "_y_bin"])
        .agg(**agg_dict)
        .reset_index()
        .rename(columns={"_x_bin": x_col, "_y_bin": y_col})
    )

    # Normalise count → bubble size in pixel range [8, size_scale]
    counts = grouped["_count"].fillna(0)
    if counts.max() > counts.min():
        grouped["_size"] = 8 + (size_scale - 8) * (counts - counts.min()) / (counts.max() - counts.min())
    else:
        grouped["_size"] = size_scale * 0.5

    # ── Build hover template ──────────────────────────────────────────────────

    hover_parts = [
        f"<b>{x_col}</b>: %{{x}}",
        f"<b>{y_col}</b>: %{{y}}",
        "<b>Count</b>: %{customdata[0]}",
    ]
    custom_cols = ["_count"]
    if id_col and "_runs" in grouped.columns:
        hover_parts.append("<b>Runs</b>: %{customdata[1]}")
        custom_cols.append("_runs")

    hover_template = "<br>".join(hover_parts) + "<extra></extra>"

    # ── Plot ──────────────────────────────────────────────────────────────────

    colour_arg = "_colour" if colour_col != "(none)" else None
    colour_label = colour_col if colour_col != "(none)" else None

    fig = go.Figure()

    if colour_arg and colour_arg in grouped.columns:
        # Split into traces by colour category (or use continuous scale for numeric)
        if colour_col in numeric_cols:
            fig = px.scatter(
                grouped,
                x=x_col,
                y=y_col,
                size="_size",
                color="_colour",
                color_continuous_scale="Viridis",
                size_max=size_scale,
                template="plotly_white",
                labels={"_colour": colour_col, "_size": "Count"},
                custom_data=custom_cols,
            )
            fig.update_traces(hovertemplate=hover_template)
            fig.update_coloraxes(colorbar_title=colour_col)
        else:
            for cat_val, grp in grouped.groupby("_colour"):
                fig.add_trace(go.Scatter(
                    x=grp[x_col],
                    y=grp[y_col],
                    mode="markers",
                    name=str(cat_val),
                    marker=dict(
                        size=grp["_size"],
                        sizemode="diameter",
                        opacity=0.75,
                        line=dict(width=1, color="white"),
                    ),
                    customdata=grp[custom_cols].values,
                    hovertemplate=hover_template,
                ))
            fig.update_layout(template="plotly_white")
    else:
        fig.add_trace(go.Scatter(
            x=grouped[x_col],
            y=grouped[y_col],
            mode="markers",
            marker=dict(
                size=grouped["_size"],
                sizemode="diameter",
                color="#1f77b4",
                opacity=0.75,
                line=dict(width=1, color="white"),
            ),
            customdata=grouped[custom_cols].values,
            hovertemplate=hover_template,
        ))
        fig.update_layout(template="plotly_white")

    fig.update_layout(
        xaxis_title=x_col,
        yaxis_title=y_col,
        height=580,
        margin=dict(l=20, r=20, t=40, b=20),
        legend=dict(orientation="v", x=1.02, y=1),
    )

    st.plotly_chart(fig, use_container_width=True)

    # ── Legend note ───────────────────────────────────────────────────────────

    counts = grouped["_count"].fillna(0)
    min_c, max_c = int(counts.min()), int(counts.max())
    unique_bins = len(grouped)
    st.caption(
        f"**{unique_bins}** unique position{'s' if unique_bins != 1 else ''} shown. "
        f"Bubble size = number of runs at that position (min {min_c}, max {max_c}). "
        f"Hover over a bubble to see the count and contributing run IDs."
    )

    # ── Summary stats ─────────────────────────────────────────────────────────

    with st.expander("📐 Summary statistics", expanded=False):
        with st.expander("📐 Summary statistics", expanded=False):
            stat_cols = [c for c in [x_col, y_col] if c in plottable_cols]
            st.dataframe(
                df_filtered[stat_cols].describe().round(4),
                use_container_width=True,
            )