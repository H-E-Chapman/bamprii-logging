"""
tab_plot.py — Plot Results tab: filters, axis configuration, bubble chart.

Derived quantities (energy densities etc.) are defined in config.yaml under
`derived`: each is an arithmetic formula over short aliases that map to sheet
columns, so renaming a variable in the config does not require a code change.
"""

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from config import auto_increment_cols, get_filterable_col_names
from sheets import SheetLogger

NONE = "(none)"


def render_plot_tab(logger: SheetLogger, groups: list, config: dict) -> None:
    st.title("Experiment visualisation")

    col_refresh, col_info = st.columns([1, 4])
    with col_refresh:
        # The callback clears the cache before the script runs, so every tab
        # reads fresh data on this run and axis selections are kept.
        st.button("🔄 Refresh Data", type="primary", width="stretch", on_click=logger.refresh)

    df = logger.load()
    if df.empty:
        st.info("No data logged yet — come back once you have some runs.")
        return

    derived_specs = config.get("derived", [])
    df, derived_added = _compute_derived_columns(df, derived_specs)

    with col_info:
        st.caption(
            f"Loaded **{len(df)}** runs. Data refreshes automatically about once a minute; "
            "press refresh to pull the latest rows now."
        )

    numeric_cols = df.select_dtypes(include="number").columns.tolist()
    if len(numeric_cols) < 2:
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

    with st.expander("🧮 Derived quantity definitions", expanded=False):
        for spec in derived_specs:
            available = f"Derived: {spec['name']}" in derived_added
            status = "" if available else " *(source columns not present in the log)*"
            st.markdown(f"**{spec['name']}** = `{spec['formula']}`{status}")
            st.caption("  ·  ".join(f"`{alias}` = {col}" for alias, col in spec["inputs"].items()))
            if spec.get("note"):
                st.caption(f"⚠️ {spec['note']}")

    plottable_cols = [c for c in filterable_col_names if c in numeric_cols] + derived_added
    _apply_plot_defaults(plottable_cols, filterable_col_names, df, config)

    sel_cols = st.columns(3)
    with sel_cols[0]:
        x_col = st.selectbox("X axis", options=plottable_cols, key="plot_x")

    y_options = [c for c in plottable_cols if c != x_col]
    if st.session_state.get("plot_y") not in y_options:
        st.session_state["plot_y"] = y_options[0] if y_options else ""
    with sel_cols[1]:
        y_col = st.selectbox("Y axis", options=y_options, key="plot_y")

    colour_options = [NONE] + [
        c for c in filterable_col_names if c in df.columns and c not in (x_col, y_col)
    ]
    if st.session_state.get("plot_colour") not in colour_options:
        st.session_state["plot_colour"] = NONE
    with sel_cols[2]:
        colour_col = st.selectbox("Colour by", options=colour_options, key="plot_colour")

    # ── Binning / bubble size ─────────────────────────────────────────────────

    st.markdown("---")
    st.subheader("Point Grouping")
    bin_cols = st.columns([2, 2, 3])
    with bin_cols[0]:
        x_decimals = st.number_input(
            "Round X to N decimal places", min_value=0, max_value=6, value=1, step=1,
            key="bin_x", help="Points with the same rounded X & Y value are merged into one bubble.",
        )
    with bin_cols[1]:
        y_decimals = st.number_input(
            "Round Y to N decimal places", min_value=0, max_value=6, value=1, step=1, key="bin_y",
        )
    with bin_cols[2]:
        size_scale = st.slider(
            "Max bubble size", min_value=20, max_value=100, value=50, step=5, key="size_scale",
        )

    # ── Aggregate + chart ─────────────────────────────────────────────────────

    id_col = next((c for c in auto_increment_cols(groups) if c in df.columns), None)
    grouped = _aggregate(
        df_filtered, x_col, y_col, colour_col, numeric_cols, id_col,
        int(x_decimals), int(y_decimals), size_scale,
    )
    fig = _build_figure(grouped, x_col, y_col, colour_col, numeric_cols, size_scale)
    st.plotly_chart(fig, width="stretch")

    counts = grouped["_count"].fillna(0)
    unique_bins = len(grouped)
    st.caption(
        f"**{unique_bins}** unique position{'s' if unique_bins != 1 else ''} shown. "
        f"Bubble size = number of runs at that position (min {int(counts.min())}, max {int(counts.max())}). "
        "Hover over a bubble to see the count and contributing run IDs."
    )

    with st.expander("📐 Summary statistics", expanded=False):
        st.dataframe(df_filtered[[x_col, y_col]].describe().round(4), width="stretch")


# ── Private helpers ───────────────────────────────────────────────────────────

def _compute_derived_columns(df: pd.DataFrame, specs: list) -> tuple[pd.DataFrame, list[str]]:
    """Append each configured derived quantity whose source columns are present."""
    added: list[str] = []
    for spec in specs:
        inputs = spec["inputs"]
        if not all(c in df.columns for c in inputs.values()):
            continue
        local = {alias: pd.to_numeric(df[c], errors="coerce") for alias, c in inputs.items()}
        for alias in spec.get("exclude_zero", []):
            local[alias] = local[alias].replace(0, np.nan)  # e.g. runs with no powder feed
        try:
            series = pd.eval(spec["formula"], local_dict=local, engine="python")
            if not isinstance(series, pd.Series):
                raise TypeError("formula must produce one value per row")
            series = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan)
        except Exception as e:
            st.warning(f"Could not compute derived quantity '{spec['name']}': {e}")
            continue
        name = f"Derived: {spec['name']}"
        df[name] = series
        added.append(name)
    return df, added


def _render_filter_panel(df: pd.DataFrame, filterable: list, config: dict) -> pd.DataFrame:
    """Render the filter expander and return the filtered DataFrame."""
    with st.expander("🔍 Filter Data", expanded=False):
        st.caption("Filter runs before plotting.")
        # The callback sets the flag before the next run, so it is in place
        # when the multiselects below are created.
        st.button("Reset filters", on_click=lambda: st.session_state.update(_reset_filters=True))
        reset = st.session_state.pop("_reset_filters", False)
        df_filtered = df.copy()
        filter_cols = st.columns(3)
        default_filters = config.get("default_filters", {})

        for i, col in enumerate(filterable):
            with filter_cols[i % 3]:
                unique_vals = sorted(df[col].dropna().unique().tolist(), key=str)
                filter_default = (
                    [v for v in default_filters[col] if v in unique_vals]
                    if col in default_filters else unique_vals
                )
                key = f"filter_{col}"
                if reset or key not in st.session_state:
                    st.session_state[key] = filter_default
                else:  # drop selections that disappeared from the data since the last load
                    st.session_state[key] = [v for v in st.session_state[key] if v in unique_vals]
                selected = st.multiselect(col, options=unique_vals, key=key)
                if selected:
                    df_filtered = df_filtered[df_filtered[col].isin(selected) | df_filtered[col].isna()]

        if "Timestamp" in df.columns:
            df_filtered["Timestamp"] = pd.to_datetime(df_filtered["Timestamp"], errors="coerce")
            valid_dates = df_filtered["Timestamp"].dropna()
            if not valid_dates.empty:
                min_date, max_date = valid_dates.min().date(), valid_dates.max().date()
                if min_date < max_date:
                    with filter_cols[len(filterable) % 3]:
                        if reset or "filter_date" not in st.session_state:
                            st.session_state["filter_date"] = (min_date, max_date)
                        date_range = st.date_input(
                            "Date range", min_value=min_date, max_value=max_date, key="filter_date",
                        )
                        if len(date_range) == 2:
                            dates = df_filtered["Timestamp"].dt.date
                            df_filtered = df_filtered[(dates >= date_range[0]) & (dates <= date_range[1])]

        st.caption(f"Showing **{len(df_filtered)}** of {len(df)} runs after filtering.")

    return df_filtered


def _apply_plot_defaults(
    plottable_cols: list, filterable_col_names: list, df: pd.DataFrame, config: dict
) -> None:
    """Write plot axis defaults into session_state on first load or config change."""
    default_x = config.get("default_plot_x", "")
    default_y = config.get("default_plot_y", "")
    default_colour = config.get("default_plot_colour", "")

    fingerprint = f"{default_x}|{default_y}|{default_colour}"
    if st.session_state.get("_plot_defaults_applied") == fingerprint:
        return

    x = default_x if default_x in plottable_cols else (plottable_cols[0] if plottable_cols else "")
    st.session_state["plot_x"] = x

    y_opts = [c for c in plottable_cols if c != x]
    st.session_state["plot_y"] = default_y if default_y in y_opts else (y_opts[0] if y_opts else "")

    colour_opts = [NONE] + [c for c in filterable_col_names if c in df.columns]
    st.session_state["plot_colour"] = default_colour if default_colour in colour_opts else NONE

    st.session_state["_plot_defaults_applied"] = fingerprint


def _aggregate(
    df: pd.DataFrame, x_col: str, y_col: str, colour_col: str,
    numeric_cols: list, id_col: str | None,
    x_decimals: int, y_decimals: int, size_scale: int,
) -> pd.DataFrame:
    """Bin and group the filtered data for bubble plotting."""
    plot_df = df.copy()
    plot_df["_x_bin"] = plot_df[x_col].round(x_decimals)
    plot_df["_y_bin"] = plot_df[y_col].round(y_decimals)

    agg_dict: dict = {"_count": (x_col, "count")}

    if colour_col != NONE and colour_col in plot_df.columns:
        if colour_col in numeric_cols:
            agg_dict["_colour"] = (colour_col, "mean")
        else:
            agg_dict["_colour"] = (colour_col, lambda x: x.mode().iloc[0] if len(x) > 0 else "")

    if id_col:
        agg_dict["_runs"] = (id_col, lambda x: ", ".join(str(v) for v in x.dropna()))

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
    numeric_cols: list, size_scale: int,
) -> go.Figure:
    """Construct and return the Plotly bubble chart figure."""
    hover_parts = [
        f"<b>{x_col}</b>: %{{x}}",
        f"<b>{y_col}</b>: %{{y}}",
        "<b>Count</b>: %{customdata[0]}",
    ]
    custom_cols = ["_count"]
    if "_runs" in grouped.columns:
        hover_parts.append("<b>Runs</b>: %{customdata[1]}")
        custom_cols.append("_runs")
    hover_template = "<br>".join(hover_parts) + "<extra></extra>"

    marker_style = dict(sizemode="diameter", opacity=0.75, line=dict(width=1, color="white"))
    fig = go.Figure()

    if colour_col != NONE and "_colour" in grouped.columns:
        if colour_col in numeric_cols:
            fig = px.scatter(
                grouped, x=x_col, y=y_col, size="_size", color="_colour",
                color_continuous_scale="Viridis", size_max=size_scale,
                template="plotly_white",
                labels={"_colour": colour_col, "_size": "Count"},
                custom_data=custom_cols,
            )
            fig.update_traces(hovertemplate=hover_template)
            fig.update_coloraxes(colorbar_title=colour_col)
        else:
            for cat_val, grp in grouped.groupby("_colour"):
                fig.add_trace(go.Scatter(
                    x=grp[x_col], y=grp[y_col], mode="markers", name=str(cat_val),
                    marker=dict(size=grp["_size"], **marker_style),
                    customdata=grp[custom_cols].values, hovertemplate=hover_template,
                ))
            fig.update_layout(template="plotly_white")
    else:
        fig.add_trace(go.Scatter(
            x=grouped[x_col], y=grouped[y_col], mode="markers",
            marker=dict(size=grouped["_size"], color="#1f77b4", **marker_style),
            customdata=grouped[custom_cols].values, hovertemplate=hover_template,
        ))
        fig.update_layout(template="plotly_white")

    fig.update_layout(
        xaxis_title=x_col, yaxis_title=y_col, height=580,
        margin=dict(l=20, r=20, t=40, b=20),
        legend=dict(orientation="v", x=1.02, y=1),
    )
    return fig
