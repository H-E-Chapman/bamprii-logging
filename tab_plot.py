"""
tab_plot.py — Renders the Plot Results tab (tab 2).
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from config import get_filterable_col_names
from sheets import SheetLogger

# ── Derived quantity definitions ──────────────────────────────────────────────

_COL_POWER   = "Laser Processing Parameters: Laser Power (W)"
_COL_SPEED   = "Laser Processing Parameters: Scan Speed (mm/s)"
_COL_SPOT    = "Laser Processing Parameters: Laser Spot Size (mm)"
_COL_FEED    = "Powder delivery: Feed rate (rpm)"

DERIVED_COLS = {
    "Derived: Linear Energy Density (J/mm)": {
        "formula": "Power / Speed",
        "requires": [_COL_POWER, _COL_SPEED],
        "compute": lambda df: df[_COL_POWER] / df[_COL_SPEED],
    },
    "Derived: Specific Energy Density (J/mm²)": {
        "formula": "Power / (Speed × Spot Size)",
        "requires": [_COL_POWER, _COL_SPEED, _COL_SPOT],
        "compute": lambda df: df[_COL_POWER] / (df[_COL_SPEED] * df[_COL_SPOT]),
    },
    "Derived: Powder Delivery Ratio (rpm·s/mm)": {
        "formula": "Feed Rate / Speed  ⚠️ uncalibrated — proportional to g/mm only",
        "requires": [_COL_FEED, _COL_SPEED],
        "compute": lambda df: (
            pd.to_numeric(df[_COL_FEED],  errors="coerce").replace(0, pd.NA) /
            pd.to_numeric(df[_COL_SPEED], errors="coerce").replace(0, pd.NA)
        ),
    },
}

_COL_POWDER_MAT = "Sample: Powder material"


def _compute_derived_columns(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """
    Append standard derived quantity columns to *df* where required source
    columns are present.  Returns the augmented DataFrame and names added.
    """
    added: list[str] = []
    for col_name, spec in DERIVED_COLS.items():
        if not all(r in df.columns for r in spec["requires"]):
            continue
        try:
            series = spec["compute"](df.copy())
            series = series.replace([float("inf"), float("-inf")], pd.NA)
            df[col_name] = pd.to_numeric(series, errors="coerce")
            added.append(col_name)
        except Exception:
            pass
    return df, added



def render_plot_tab(logger: SheetLogger, groups: list, config: dict) -> None:
    st.title("Experiment visualisation")

    col_refresh, col_info = st.columns([1, 4])
    with col_refresh:
        if st.button("🔄 Load / Refresh Data", type="primary", width="stretch"):
            with st.spinner("Pulling from Google Sheets..."):
                st.session_state.df_cache = logger.load()
            st.session_state.pop("_plot_defaults_applied", None)

    if st.session_state.df_cache is None:
        st.info("Press **Load / Refresh Data** to fetch runs from the sheet.")
        return

    df = st.session_state.df_cache.copy()

    if df.empty:
        st.info("No data logged yet — come back once you have some runs.")
        return

    # ── Standard derived quantities ───────────────────────────────────────────
    df, derived_added = _compute_derived_columns(df)

    with col_info:
        st.caption(f"Loaded **{len(df)}** runs. Press refresh to pull latest data from the sheet.")

    all_cols = df.columns.tolist()

    if len(df.select_dtypes(include="number").columns) < 2:
        st.warning("Need at least 2 numeric columns to plot. Log more runs with numeric fields.")
        return

    # ── Filter panel ──────────────────────────────────────────────────────────

    filterable_col_names = get_filterable_col_names(groups)

    if filterable_col_names:
        filterable = [c for c in filterable_col_names if c in df.columns and 1 < df[c].nunique() <= 30]
    else:
        filterable = [c for c in df.select_dtypes(exclude="number").columns if 1 < df[c].nunique() <= 30]

    df_filtered = _render_filter_panel(df, filterable, config)

    # ── Axis selectors ────────────────────────────────────────────────────────

    st.markdown("---")
    st.subheader("Axis Configuration")

    # ── Derived quantities expander ───────────────────────────────────────────
    with st.expander("🧮 Derived quantity definitions", expanded=False):

        # ── Standard formula list ─────────────────────────────────────────────
        for dc in derived_added:
            spec = DERIVED_COLS[dc]
            short = dc.split(": ", 1)[-1]
            st.markdown(f"**{short}** = `{spec['formula']}`")

        st.markdown("---")
        st.caption(
            "⚠️ **Powder Delivery Ratio** is uncalibrated (rpm·s/mm). "
            "It is proportional to g/mm but requires a density and feeder "
            "calibration factor to convert to absolute units."
        )

    # ── Build plottable columns list ──────────────────────────────────────────
    numeric_cols = df.select_dtypes(include="number").columns.tolist()

    plottable_cols = [c for c in filterable_col_names if c in df.columns and c in numeric_cols]
    for dc in derived_added:
        if dc not in plottable_cols:
            plottable_cols.append(dc)

    _apply_plot_defaults(plottable_cols, filterable_col_names, df, config)

    sel_cols = st.columns(3)

    with sel_cols[0]:
        x_col = st.selectbox("X axis", options=plottable_cols, key="plot_x")

    _y_options = [c for c in plottable_cols if c != x_col]
    if st.session_state.get("plot_y") not in _y_options:
        st.session_state["plot_y"] = _y_options[0] if _y_options else ""

    with sel_cols[1]:
        y_col = st.selectbox("Y axis", options=_y_options, key="plot_y")

    _colour_options = (
        ["(none)"] + [c for c in filterable_col_names if c in df.columns and c not in (x_col, y_col)]
    )
    if st.session_state.get("plot_colour") not in _colour_options:
        st.session_state["plot_colour"] = "(none)"

    with sel_cols[2]:
        colour_col = st.selectbox("Colour by", options=_colour_options, key="plot_colour")

    # ── Binning / bubble size ─────────────────────────────────────────────────

    st.markdown("---")
    st.subheader("Point Grouping")
    bin_cols = st.columns([2, 2, 3])

    with bin_cols[0]:
        x_decimals = st.number_input(
            "Round X to N decimal places", min_value=0, max_value=6, value=1, step=1,
            key="bin_x",
            help="Points with the same rounded X & Y value are merged into one bubble.",
        )
    with bin_cols[1]:
        y_decimals = st.number_input(
            "Round Y to N decimal places", min_value=0, max_value=6, value=1, step=1,
            key="bin_y",
        )
    with bin_cols[2]:
        size_scale = st.slider(
            "Max bubble size", min_value=20, max_value=100, value=50, step=5,
            key="size_scale",
        )

    # ── Aggregate ─────────────────────────────────────────────────────────────

    grouped = _aggregate(df_filtered, x_col, y_col, colour_col, numeric_cols, all_cols,
                         int(x_decimals), int(y_decimals), size_scale)

    # ── Render chart ──────────────────────────────────────────────────────────

    fig = _build_figure(grouped, x_col, y_col, colour_col, numeric_cols, all_cols, size_scale)
    st.plotly_chart(fig, width="stretch")

    # ── Caption ───────────────────────────────────────────────────────────────

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
        stat_cols = [c for c in [x_col, y_col] if c in plottable_cols]
        st.dataframe(df_filtered[stat_cols].describe().round(4), width="stretch")


# ── Private helpers ───────────────────────────────────────────────────────────

def _render_filter_panel(df: pd.DataFrame, filterable: list, config: dict) -> pd.DataFrame:
    """Render the filter expander and return the filtered DataFrame."""
    with st.expander("🔍 Filter Data", expanded=False):
        st.caption("Filter runs before plotting.")
        if st.button("Reset filters"):
            st.session_state["_reset_filters"] = True
            st.rerun()
        df_filtered = df.copy()
        filter_cols = st.columns(3)
        default_filters = config.get("default_filters", {})

        for i, col in enumerate(filterable):
            with filter_cols[i % 3]:
                unique_vals = sorted(df[col].dropna().unique().tolist(), key=str)
                filter_default = (
                    [v for v in default_filters.get(col, unique_vals) if v in unique_vals]
                    if col in default_filters else unique_vals
                )
                key = f"filter_{col}"

                if st.session_state.get("_reset_filters"):
                    st.session_state[key] = filter_default

                selected = st.multiselect(
                    col,
                    options=unique_vals,
                    default=filter_default,
                    key=key
                )
                if selected:
                    df_filtered = df_filtered[
                        df_filtered[col].isin(selected) | df_filtered[col].isna()
                        ]
        if "Timestamp" in df.columns:
            df_filtered["Timestamp"] = pd.to_datetime(df_filtered["Timestamp"], errors="coerce")
            valid_dates = df_filtered["Timestamp"].dropna()
            if not valid_dates.empty:
                min_date, max_date = valid_dates.min().date(), valid_dates.max().date()
                if min_date < max_date:
                    with filter_cols[len(filterable) % 3]:
                        if st.session_state.get("_reset_filters"):
                            st.session_state["filter_date"] = (min_date, max_date)
                        date_range = st.date_input(
                            "Date range", value=(min_date, max_date),
                            min_value=min_date, max_value=max_date,
                            key="filter_date",
                        )
                        if len(date_range) == 2:
                            df_filtered = df_filtered[
                                (df_filtered["Timestamp"].dt.date >= date_range[0]) &
                                (df_filtered["Timestamp"].dt.date <= date_range[1])
                            ]

        st.caption(f"Showing **{len(df_filtered)}** of {len(df)} runs after filtering.")

    st.session_state.pop("_reset_filters", None)

    return df_filtered


def _apply_plot_defaults(
    plottable_cols: list, filterable_col_names: list, df: pd.DataFrame, config: dict
) -> None:
    """Write plot axis defaults into session_state on first load or config change."""
    fingerprint = (
        f"{config.get('default_plot_x', '')}|"
        f"{config.get('default_plot_y', '')}|"
        f"{config.get('default_plot_colour', '')}"
    )
    if st.session_state.get("_plot_defaults_applied") == fingerprint:
        return

    default_x = config.get("default_plot_x", "")
    default_y = config.get("default_plot_y", "")
    default_colour = config.get("default_plot_colour", "")

    x = default_x if default_x in plottable_cols else (plottable_cols[0] if plottable_cols else "")
    st.session_state["plot_x"] = x

    y_opts = [c for c in plottable_cols if c != x]
    st.session_state["plot_y"] = default_y if default_y in y_opts else (y_opts[0] if y_opts else "")

    colour_opts = ["(none)"] + [c for c in filterable_col_names if c in df.columns]
    st.session_state["plot_colour"] = default_colour if default_colour in colour_opts else "(none)"

    st.session_state["_plot_defaults_applied"] = fingerprint


def _aggregate(
    df: pd.DataFrame, x_col: str, y_col: str, colour_col: str,
    numeric_cols: list, all_cols: list,
    x_decimals: int, y_decimals: int, size_scale: int,
) -> pd.DataFrame:
    """Bin and group the filtered data for bubble plotting."""
    plot_df = df.copy()
    plot_df["_x_bin"] = plot_df[x_col].round(x_decimals)
    plot_df["_y_bin"] = plot_df[y_col].round(y_decimals)

    agg_dict: dict = {"_count": (x_col, "count")}

    if colour_col != "(none)" and colour_col in plot_df.columns:
        if colour_col in numeric_cols:
            agg_dict["_colour"] = (colour_col, "mean")
        else:
            agg_dict["_colour"] = (colour_col, lambda x: x.mode().iloc[0] if len(x) > 0 else "")

    id_col = next((c for c in all_cols if "run" in c.lower() and "id" in c.lower()), None)
    if id_col:
        agg_dict["_runs"] = (
            id_col,
            lambda x: ", ".join(str(v) for v in x.dropna())
        )

    grouped = (
        plot_df
        .groupby(["_x_bin", "_y_bin"])
        .agg(**agg_dict)
        .reset_index()
        .rename(columns={"_x_bin": x_col, "_y_bin": y_col})
    )

    counts = grouped["_count"].fillna(0)
    if counts.max() > counts.min():
        grouped["_size"] = 8 + (size_scale - 8) * (counts - counts.min()) / (counts.max() - counts.min())
    else:
        grouped["_size"] = size_scale * 0.5

    return grouped


def _build_figure(
    grouped: pd.DataFrame, x_col: str, y_col: str, colour_col: str,
    numeric_cols: list, all_cols: list, size_scale: int,
) -> go.Figure:
    """Construct and return the Plotly bubble chart figure."""
    id_col = next((c for c in all_cols if "run" in c.lower() and "id" in c.lower()), None)

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
    colour_arg = "_colour" if colour_col != "(none)" and "_colour" in grouped.columns else None
    fig = go.Figure()

    if colour_arg:
        if colour_col in numeric_cols:
            fig = px.scatter(
                grouped, x=x_col, y=y_col,
                size="_size", color="_colour",
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
                    x=grp[x_col], y=grp[y_col],
                    mode="markers",
                    name=str(cat_val),
                    marker=dict(size=grp["_size"], sizemode="diameter",
                                opacity=0.75, line=dict(width=1, color="white")),
                    customdata=grp[custom_cols].values,
                    hovertemplate=hover_template,
                ))
            fig.update_layout(template="plotly_white")
    else:
        fig.add_trace(go.Scatter(
            x=grouped[x_col], y=grouped[y_col],
            mode="markers",
            marker=dict(size=grouped["_size"], sizemode="diameter",
                        color="#1f77b4", opacity=0.75,
                        line=dict(width=1, color="white")),
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
    return fig