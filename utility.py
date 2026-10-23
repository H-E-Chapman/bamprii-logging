"""
utility.py — Pure helpers for auto-increment counter formatting (no Streamlit dependency).
"""

import re


def format_counter(n: int, var: dict) -> str:
    """
    Format an integer counter according to the variable's config.

    Formats:
      - "padded"   → zero-padded integer,  e.g. 0042
      - "prefixed" → prefix + zero-padded, e.g. RUN0042
    """
    pad = int(var.get("pad", 4))
    prefix = var.get("prefix", "") if var.get("format", "padded") == "prefixed" else ""
    return f"{prefix}{str(n).zfill(pad)}"


def extract_counter(value, var: dict) -> int | None:
    """
    Parse a counter value back to an integer, stripping any prefix.

    Accepts strings or numbers: Google Sheets returns padded counters such as
    "0042" as the integer 42. Returns None if the value cannot be parsed.
    """
    if value is None:
        return None
    if isinstance(value, float):
        if value != value or not value.is_integer():  # NaN or fractional
            return None
        value = int(value)
    s = str(value).strip()
    prefix = var.get("prefix", "")
    if var.get("format") == "prefixed" and prefix and s.startswith(prefix):
        s = s[len(prefix):]
    digits = re.sub(r"[^0-9]", "", s)
    return int(digits) if digits else None
