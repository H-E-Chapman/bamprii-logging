"""
config.py — Load, validate and query the YAML configuration.
"""

import pathlib
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import streamlit as st
import yaml

_HERE = pathlib.Path(__file__).parent
CONFIG_FILE = _HERE / "config.yaml"

VAR_TYPES = {"float", "integer", "text", "select", "auto_increment"}
MATERIAL_FIELDS = ("density_kg_m3", "specific_heat_J_kgK", "latent_heat_J_kg", "melting_point_C", "absorptivity")


def load_config() -> dict:
    """Load and validate config.yaml; cached until the file's modification time changes."""
    return _load_config(CONFIG_FILE.stat().st_mtime)


@st.cache_data
def _load_config(mtime: float) -> dict:
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    _validate(config)
    return config


def _validate(config: dict) -> None:
    """Raise ValueError listing every config mistake, naming the field."""
    problems: list[str] = []
    seen: set[tuple[str, str]] = set()

    for group in config.get("groups", []):
        gname = group.get("name")
        if not gname:
            problems.append("A group is missing 'name'.")
            continue
        for var in group.get("variables", []):
            vname = var.get("name")
            if not vname:
                problems.append(f"{gname}: a variable is missing 'name'.")
                continue
            where = f"{gname} / {vname}"
            if (gname, vname) in seen:
                problems.append(f"{where}: duplicate variable name.")
            seen.add((gname, vname))

            vtype = var.get("type", "text")
            if vtype not in VAR_TYPES:
                problems.append(f"{where}: unknown type '{vtype}'.")
            elif vtype == "select":
                options = var.get("options")
                if not options:
                    problems.append(f"{where}: select needs a non-empty 'options' list.")
                elif var.get("default") not in (None, "", *options):
                    problems.append(f"{where}: default {var['default']!r} is not in options.")
            elif vtype in ("float", "integer"):
                try:
                    default_value(var)
                except (TypeError, ValueError):
                    problems.append(f"{where}: default {var.get('default')!r} is not a number.")

    for spec in config.get("derived", []):
        if not (spec.get("name") and spec.get("formula") and spec.get("inputs")):
            problems.append(f"derived entry {spec!r} needs 'name', 'formula' and 'inputs'.")
        elif any(a not in spec["inputs"] for a in spec.get("exclude_zero", [])):
            problems.append(f"derived '{spec['name']}': exclude_zero names an alias not in inputs.")

    for mat in config.get("materials", []):
        name = mat.get("name") or "<unnamed>"
        for key in MATERIAL_FIELDS:
            try:
                float(mat[key])
            except (KeyError, TypeError, ValueError):
                problems.append(f"materials / {name}: '{key}' must be a number.")

    tz = config.get("timezone")
    if tz:
        try:
            ZoneInfo(tz)
        except (ZoneInfoNotFoundError, ValueError, TypeError):
            problems.append(f"timezone {tz!r} is not a valid IANA zone name (e.g. Europe/London).")

    if problems:
        raise ValueError("config.yaml has errors:\n- " + "\n- ".join(problems))


def default_value(var: dict):
    """Initial widget value for a variable, coerced to the type its widget expects."""
    vtype = var.get("type", "text")
    default = var.get("default")
    blank = default is None or default == ""
    if vtype == "float":
        return 0.0 if blank else float(default)
    if vtype == "integer":
        return 0 if blank else int(default)
    if vtype == "select":
        return None if blank else default
    return "" if blank else str(default)


def col_name(group: str, variable: str) -> str:
    """Canonical column name used in Google Sheets: 'Group: Variable'."""
    return f"{group}: {variable}"


def get_filterable_col_names(groups: list) -> list[str]:
    """
    Ordered, de-duplicated 'Group: Variable' column names for groups marked
    filterable: true. These drive the filter panel and axis choices in the Plot tab.
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


def auto_increment_cols(groups: list) -> list[str]:
    """Sheet column names of all auto_increment variables, in declaration order."""
    return [
        col_name(g["name"], v["name"])
        for g in groups
        for v in g["variables"]
        if v.get("type") == "auto_increment"
    ]
