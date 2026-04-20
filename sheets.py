"""
sheets.py — Google Sheets access layer.
"""

import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials

from utility import extract_counter

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


class SheetLogger:
    """Encapsulates all read/write operations against the 'Log' worksheet."""

    def __init__(self) -> None:
        if "gcp_service_account" not in st.secrets:
            raise RuntimeError("Missing gcp_service_account in Streamlit secrets")

        if "google_sheets" not in st.secrets:
            raise RuntimeError("Missing google_sheets in Streamlit secrets")
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
        client = gspread.authorize(creds)
        sheet_id = st.secrets["google_sheets"]["sheet_id"]
        spreadsheet = client.open_by_key(sheet_id)
        try:
            self.ws = spreadsheet.worksheet("Log")
        except gspread.WorksheetNotFound:
            self.ws = spreadsheet.add_worksheet(title="Log", rows=2000, cols=50)

    def load(self) -> pd.DataFrame:
        """Fetch all logged rows as a DataFrame. Returns empty DF on failure."""
        try:
            data = self.ws.get_all_records()
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

    def row_count(self) -> int:
        """Return the number of data rows (excluding the header)."""
        try:
            all_vals = self.ws.get_all_values()
            return max(0, len(all_vals) - 1)
        except Exception:
            return 0

    def get_last_counter(self, col_name: str, var: dict) -> int:
        """
        Scan the sheet column and return the highest counter value found.
        Falls back to (start - 1) if the column is empty or missing.
        """
        start = int(var.get("start", 1))
        try:
            all_values = self.ws.get_all_values()
            if not all_values or len(all_values) < 2:
                return start - 1
            headers = all_values[0]
            if col_name not in headers:
                return start - 1
            col_idx = headers.index(col_name)
            nums = [
                n for row in all_values[1:]
                if col_idx < len(row) and row[col_idx]
                for n in [extract_counter(row[col_idx], var)]
                if n is not None
            ]
            return max(nums) if nums else start - 1
        except Exception:
            return start - 1

    def append(self, row: dict) -> None:
        """
        Append a row dict to the sheet.

        Automatically extends the header row if the dict contains new keys
        (e.g. when a new equipment group is activated for the first time).
        """
        existing = self.ws.get_all_values()
        if not existing:
            # Sheet is brand new — write header first
            self.ws.append_row(list(row.keys()), value_input_option="USER_ENTERED")
        else:
            current_headers = existing[0]
            new_headers = [k for k in row.keys() if k not in current_headers]
            if new_headers:
                self.ws.update("1:1", [current_headers + new_headers])
            current_headers = self.ws.row_values(1)
            row = {k: row.get(k, "") for k in current_headers}
        self.ws.append_row(list(row.values()), value_input_option="USER_ENTERED")


@st.cache_resource
def get_sheet_logger() -> SheetLogger:
    """
    Return a cached SheetLogger singleton.

    @st.cache_resource keeps this alive across reruns for the lifetime of
    the server process, so the gspread auth handshake only happens once.
    """
    return SheetLogger()