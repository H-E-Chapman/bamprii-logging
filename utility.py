"""
utility.py — Pure helper functions for auto-increment counter formatting.
"""

import re


def format_counter(n: int, var: dict) -> str:
    """
    Format an integer counter according to the variable's config.

    Formats:
      - "padded"   → zero-padded integer,  e.g. 0042
      - "prefixed" → prefix + zero-padded, e.g. RUN0042
    """
    fmt = var.get("format", "padded")
    pad = int(var.get("pad", 4))
    prefix = var.get("prefix", "")
    if fmt == "prefixed":
        return f"{prefix}{str(n).zfill(pad)}"
    return str(n).zfill(pad)


def extract_counter(value: str, var: dict) -> int | None:
    """
    Parse a counter value back to an integer, stripping any prefix.
    Returns None if the value cannot be parsed.
    """
    fmt = var.get("format", "padded")
    prefix = var.get("prefix", "")
    try:
        stripped = value.replace(prefix, "") if (fmt == "prefixed" and prefix) else value
        return int(re.sub(r"[^0-9]", "", stripped))
    except (ValueError, TypeError):
        return None