"""
config.py — Load and query the YAML configuration.
"""

import pathlib
import yaml
import streamlit as st

_HERE = pathlib.Path(__file__).parent
CONFIG_FILE = _HERE / "config.yaml"


@st.cache_data
def load_config() -> dict:
    """Load config.yaml once and cache it for the session."""
    with open(CONFIG_FILE, "r") as f:
        return yaml.safe_load(f)


def get_filterable_col_names(groups: list) -> list[str]:
    """
    Return the ordered list of 'Group — Variable' column names
    that are marked filterable: true in config.
    Preserves declaration order and deduplicates.
    """
    seen: set[str] = set()
    names: list[str] = []
    for group in groups:
        if group.get("filterable"):
            for var in group["variables"]:
                col = col_name(group["name"], var["name"])
                if col not in seen:
                    names.append(col)
                    seen.add(col)
    return names


def col_name(group: str, variable: str) -> str:
    """Canonical column name used in Google Sheets: 'Group — Variable'."""
    return f"{group}: {variable}"