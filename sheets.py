"""
sheets.py — Google Sheets access layer.

Every read goes through load() or load_calc_values(), which are cached for
CACHE_TTL seconds so that widget interactions do not each cost a round-trip to
Google (all users share one service account and therefore one API quota).
append(), append_calc_value() and refresh() clear that cache.

The 'Log' worksheet holds experiment runs; the 'Calc Values' worksheet holds
the Energy & Powder calculator values that were logged with an outcome rating.
"""

import gspread
import pandas as pd
import streamlit as st
from google.oauth2.service_account import Credentials

from utility import extract_counter

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
WORKSHEET = "Log"
CALC_WORKSHEET = "Calc Values"
CACHE_TTL = 60  # seconds


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def _fetch_records(_ws: gspread.Worksheet, title: str) -> list[dict]:
    """
    Worksheet rows as dicts keyed by header.

    The leading underscore keeps _ws out of the cache key, so one cache serves
    every session on the server; `title` is part of the key and keeps the
    worksheets' cached reads apart.

    Parameters
    ----------
    _ws : gspread.Worksheet
        Worksheet to read.
    title : str
        Worksheet title, used only as the cache key.

    Returns
    -------
    list of dict
        One dict per non-blank data row, keyed by header.

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


def _append_row(ws: gspread.Worksheet, row: dict) -> None:
    """
    Append a row dict to a worksheet, extending the header row if the dict
    contains keys the header does not have yet.

    Parameters
    ----------
    ws : gspread.Worksheet
        Worksheet to append to.
    row : dict
        Column name to cell value; None is written as an empty cell.
    """
    headers = ws.row_values(1)
    if not headers:
        headers = list(row.keys())
        ws.append_row(headers, value_input_option="USER_ENTERED")
    else:
        new = [k for k in row if k not in headers]
        if new:
            headers = headers + new
            ws.update(values=[headers], range_name="1:1")

    values = ["" if row.get(h) is None else row.get(h, "") for h in headers]
    ws.append_row(values, value_input_option="USER_ENTERED")


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
        self.calc_error: str | None = None  # set when the most recent load_calc_values() failed
        spreadsheet = gspread.authorize(creds).open_by_key(self.sheet_id)
        try:
            self.ws = spreadsheet.worksheet(WORKSHEET)
        except gspread.WorksheetNotFound:
            self.ws = spreadsheet.add_worksheet(title=WORKSHEET, rows=2000, cols=50)
        try:
            self.calc_ws = spreadsheet.worksheet(CALC_WORKSHEET)
        except gspread.WorksheetNotFound:
            self.calc_ws = spreadsheet.add_worksheet(title=CALC_WORKSHEET, rows=1000, cols=40)

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
            records = _fetch_records(self.ws, WORKSHEET)
        except Exception as e:
            self.last_error = str(e)
            return pd.DataFrame()
        self.last_error = None
        return _to_frame(records) if records else pd.DataFrame()

    def load_calc_values(self) -> pd.DataFrame:
        """
        All logged calculator values as a DataFrame (cached). On failure returns
        an empty frame and records the reason in self.calc_error.
        """
        try:
            records = _fetch_records(self.calc_ws, CALC_WORKSHEET)
        except Exception as e:
            self.calc_error = str(e)
            return pd.DataFrame()
        self.calc_error = None
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
        Append a row dict to the 'Log' worksheet, extending the header row if the
        dict contains new keys (e.g. an equipment group activated for the first time).
        """
        _append_row(self.ws, row)
        self.refresh()

    def append_calc_value(self, row: dict) -> None:
        """Append a row dict to the 'Calc Values' worksheet, extending its header as needed."""
        _append_row(self.calc_ws, row)
        self.refresh()


@st.cache_resource
def get_sheet_logger() -> SheetLogger:
    """Cached SheetLogger singleton: the gspread auth handshake happens once per server."""
    return SheetLogger()
