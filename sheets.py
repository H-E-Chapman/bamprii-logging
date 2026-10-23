"""
sheets.py — Google Sheets access layer.

Every read goes through load(), which is cached for CACHE_TTL seconds so that
widget interactions do not each cost a round-trip to Google (all users share
one service account and therefore one API quota). append() and refresh()
clear that cache.
"""

import gspread
import pandas as pd
import streamlit as st
from google.oauth2.service_account import Credentials

from utility import extract_counter

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
WORKSHEET = "Log"
CACHE_TTL = 60  # seconds


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def _fetch_records(_ws: gspread.Worksheet) -> list[dict]:
    """
    Worksheet rows as dicts keyed by header. The leading underscore keeps _ws
    out of the cache key, so one cache serves every session on the server.

    Trailing blank header cells are dropped and each row is padded or trimmed
    to the header width, so stray cells beyond the header cannot break the read.
    """
    rows = _ws.get_all_values()
    if not rows:
        return []
    headers = rows[0]
    while headers and not headers[-1].strip():
        headers.pop()
    width = len(headers)
    return [
        dict(zip(headers, (row + [""] * width)[:width]))
        for row in rows[1:]
        if any(cell.strip() for cell in row[:width])
    ]


def _to_frame(records: list[dict]) -> pd.DataFrame:
    """
    Build a DataFrame, converting a column to numeric only when every non-empty
    cell parses as a number. Mixed columns such as a Substrate ID holding "A1"
    and "7" stay as text.
    """
    df = pd.DataFrame(records)
    for col in df.columns:
        s = df[col]
        filled = s.map(lambda v: v is not None and str(v).strip() != "")
        if not filled.any():
            continue
        converted = pd.to_numeric(s.where(filled), errors="coerce")
        if converted[filled].notna().all():
            df[col] = converted
    return df


class SheetLogger:
    """Encapsulates all read/write operations against the 'Log' worksheet."""

    def __init__(self) -> None:
        for section in ("gcp_service_account", "google_sheets"):
            if section not in st.secrets:
                raise RuntimeError(f"Missing [{section}] in Streamlit secrets")

        creds = Credentials.from_service_account_info(
            dict(st.secrets["gcp_service_account"]), scopes=SCOPES
        )
        self.sheet_id = st.secrets["google_sheets"]["sheet_id"]
        self.last_error: str | None = None  # set when the most recent load() failed
        spreadsheet = gspread.authorize(creds).open_by_key(self.sheet_id)
        try:
            self.ws = spreadsheet.worksheet(WORKSHEET)
        except gspread.WorksheetNotFound:
            self.ws = spreadsheet.add_worksheet(title=WORKSHEET, rows=2000, cols=50)

    @property
    def url(self) -> str:
        """Browser link to the Log worksheet."""
        return f"https://docs.google.com/spreadsheets/d/{self.sheet_id}/edit#gid={self.ws.id}"

    def refresh(self) -> None:
        """Drop the cached read so the next load() hits Google."""
        _fetch_records.clear()

    def load(self) -> pd.DataFrame:
        """
        All logged rows as a DataFrame (cached). On failure returns an empty
        frame and records the reason in self.last_error for the UI to show once.
        """
        try:
            records = _fetch_records(self.ws)
        except Exception as e:
            self.last_error = str(e)
            return pd.DataFrame()
        self.last_error = None
        return _to_frame(records) if records else pd.DataFrame()

    def row_count(self) -> int:
        """Number of data rows (excluding the header)."""
        return len(self.load())

    def get_last_counter(self, column: str, var: dict) -> int:
        """Highest counter value found in *column*, or (start - 1) if none."""
        start = int(var.get("start", 1))
        df = self.load()
        if column not in df.columns:
            return start - 1
        nums = [n for v in df[column].dropna() if (n := extract_counter(v, var)) is not None]
        return max(nums) if nums else start - 1

    def append(self, row: dict) -> None:
        """
        Append a row dict to the sheet, extending the header row if the dict
        contains new keys (e.g. an equipment group activated for the first time).
        """
        headers = self.ws.row_values(1)
        if not headers:
            headers = list(row.keys())
            self.ws.append_row(headers, value_input_option="USER_ENTERED")
        else:
            new = [k for k in row if k not in headers]
            if new:
                headers = headers + new
                self.ws.update(values=[headers], range_name="1:1")

        values = ["" if row.get(h) is None else row.get(h, "") for h in headers]
        self.ws.append_row(values, value_input_option="USER_ENTERED")
        self.refresh()


@st.cache_resource
def get_sheet_logger() -> SheetLogger:
    """Cached SheetLogger singleton: the gspread auth handshake happens once per server."""
    return SheetLogger()
