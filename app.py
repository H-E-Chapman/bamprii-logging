import streamlit as st
import pandas as pd
import yaml
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
import pathlib

# ── Paths ─────────────────────────────────────────────────────────────────────

_HERE = pathlib.Path(__file__).parent
CONFIG_FILE = _HERE / "config.yaml"

st.set_page_config(
    page_title="Experiment Logger",
    page_icon="🧪",
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
    """Connect to Google Sheets using credentials stored in Streamlit secrets."""
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
    """Read all rows from the Google Sheet."""
    try:
        ws = get_worksheet()
        data = ws.get_all_records()
        if not data:
            return pd.DataFrame()
        return pd.DataFrame(data)
    except Exception as e:
        st.warning(f"Could not load log from Google Sheets: {e}")
        return pd.DataFrame()

def append_log(row: dict):
    """Append a single row to the Google Sheet, writing headers if needed."""
    ws = get_worksheet()
    existing = ws.get_all_values()

    if not existing:
        # Sheet is empty — write header row first
        ws.append_row(list(row.keys()), value_input_option="USER_ENTERED")
    else:
        # Check if any new columns need adding
        current_headers = existing[0]
        new_headers = [k for k in row.keys() if k not in current_headers]
        if new_headers:
            updated_headers = current_headers + new_headers
            ws.update("1:1", [updated_headers])
        # Align row values to current headers
        current_headers = ws.row_values(1)
        row = {k: row.get(k, "") for k in current_headers}

    ws.append_row(list(row.values()), value_input_option="USER_ENTERED")

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
            st.session_state[key] = var.get("default", "")

if "log_message" not in st.session_state:
    st.session_state.log_message = None

# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("🧪 Experiment Logger")
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

# ── Main form ─────────────────────────────────────────────────────────────────

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
    st.stop()

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

                    if vtype == "float":
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

# ── Log / Reset buttons ───────────────────────────────────────────────────────

st.markdown("---")
col1, col2, col3 = st.columns([1, 1, 3])

with col1:
    log_pressed = st.button("📋 Log Run", type="primary", use_container_width=True)

with col2:
    if st.button("🔄 Reset Fields", use_container_width=True):
        for group in groups:
            for var in group["variables"]:
                key = f"val_{group['name']}_{var['name']}"
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

# ── Recent runs viewer ────────────────────────────────────────────────────────

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
