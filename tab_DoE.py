"""
tab_doe.py — Renders the Experimental Design tab (tab 4).

Guides the user through designing a Response Surface Methodology (RSM)
experiment: objective selection → factor count & design type →
factor definition → visualisation → run table & CSV export.
"""

from __future__ import annotations

import io
import itertools
import random

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st


# ── Constants ─────────────────────────────────────────────────────────────────

STANDARD_FACTORS: dict[str, dict] = {
    "Laser Power (W)": {"min": 100.0, "max": 500.0, "center": 300.0, "unit": "W"},
    "Scan Speed (mm/s)": {"min": 200.0, "max": 1000.0, "center": 600.0, "unit": "mm/s"},
    "Feed Rate (rpm)": {"min": 1.0, "max": 5.0, "center": 3.0, "unit": "rpm"},
    "Laser Spot Size (mm)": {"min": 1.0, "max": 5.0, "center": 2.5, "unit": "mm"},
    "Shield Gas Flow (lpm)": {"min": 5.0, "max": 20.0, "center": 12.5, "unit": "lpm"},
    "Carrier Gas Flow (lpm)": {"min": 2.0, "max": 8.0, "center": 5.0, "unit": "lpm"},
    "Linear Energy Density (J/mm)": {"min": 0.1, "max": 2.0, "center": 1.0, "unit": "J/mm"},
    "Powder Density (g/mm)": {"min": 0.002, "max": 0.05, "center": 0.02, "unit": "g/mm"},
    "Energy/Powder Ratio (J/g)": {"min": 10.0, "max": 200.0, "center": 100.0, "unit": "J/g"},
    "Custom…": {"min": 0.0, "max": 1.0, "center": 0.5, "unit": ""},
}

OBJECTIVE_INFO: dict[str, str] = {
    "Comparative": (
        "**Comparative** objectives test whether changing a factor produces a "
        "statistically significant difference in a response (e.g. t-tests, ANOVA). "
        "Useful for confirming that a parameter *matters* before investing in "
        "full optimisation."
    ),
    "Screening": (
        "**Screening** objectives identify which factors from a large candidate "
        "set have the most influence on the response. Fractional-factorial and "
        "Plackett–Burman designs are common choices — they test many factors in "
        "few runs by assuming higher-order interactions are negligible."
    ),
    "Response Surface": (
        "**Response Surface** objectives map the relationship between factors and "
        "response(s) to find optima or build predictive models. Designs such as "
        "Central Composite (CCD) and Box–Behnken support estimation of linear, "
        "interaction, and quadratic effects. This is the most informative — and "
        "most resource-intensive — class of experiment."
    ),
}

DESIGN_INFO: dict[str, str] = {
    "Full Factorial (2-level)": (
        "Tests every combination of low (−1) and high (+1) levels for all factors. "
        "For *k* factors this produces **2ᵏ runs** plus any added centre points. "
        "Estimates all main effects and interactions, but run count grows quickly."
    ),
    "Central Composite Design (CCD)": (
        "Augments a 2-level factorial with *axial* (star) points at ±α along each "
        "factor axis and one or more centre replicates. Supports full quadratic "
        "models. The face-centred variant (α = 1) keeps all points within the "
        "experimental region. Produces **2ᵏ + 2k + 1** runs per block."
    ),
    "Box–Behnken Design (BBD)": (
        "Places design points at the mid-edges of a hypercube — no corner runs. "
        "Avoids extreme combinations of all factors simultaneously, which can be "
        "safer for process equipment. Requires k ≥ 3 factors. Produces a similar "
        "number of runs to CCD but with different coverage."
    ),
}

COLLAPSING_TIPS = [
    (
        "**Linear Energy Density (LED)**  \n"
        "LED = Laser Power ÷ Scan Speed (J/mm).  \n"
        "Combines two of the most influential process parameters into a single "
        "measure of energy input per unit length of track."
    ),
    (
        "**Powder Density**  \n"
        "Powder Density = Feed Rate (mass/time) ÷ Scan Speed (mm/s) → mass per mm.  \n"
        "Captures how much material is deposited per unit length, independent of "
        "absolute speed."
    ),
    (
        "**Energy-to-Powder Ratio**  \n"
        "Ratio = LED ÷ Powder Density (J/g).  \n"
        "A single dimensionless proxy for the energy available per unit mass of "
        "deposited powder — strongly linked to melt-pool temperature and catchment "
        "efficiency."
    ),
    (
        "**Shield Gas / Carrier Gas Ratio**  \n"
        "Fixing the total gas flow while varying the ratio can reduce your gas "
        "variables from two factors to one."
    ),
]


# ── Public entry point ────────────────────────────────────────────────────────

def render_doe_tab() -> None:
    st.title("Experimental Design Planner")
    st.caption(
        "Guided workflow for Response Surface Methodology (RSM) experiment design. "
        "Inspired by the [NIST/SEMATECH Engineering Statistics Handbook]"
        "(https://www.itl.nist.gov/div898/handbook/pri/section3/pri3.htm)."
    )

    # ── 1. Objective ─────────────────────────────────────────────────────────
    objective = _render_objective_selector()

    if objective != "Response Surface":
        _render_non_rsm_guidance(objective)
        return

    st.success(
        "✅ **Response Surface** selected — continue below to build your design.",
        icon=None,
    )

    # ── 2. Factor count & design type ─────────────────────────────────────────
    k, design_type = _render_design_selector()

    if k is None:
        return  # guidance shown inside, nothing to continue

    # ── 3. Factor definition ──────────────────────────────────────────────────
    factors = _render_factor_editor(k)

    if factors is None:
        return

    # ── 4. Generate design ────────────────────────────────────────────────────
    st.markdown("---")
    coded = _generate_design(design_type, k)
    if coded is None:
        return

    df_design = _decode_design(coded, factors)

    # ── 5. Visualisation ──────────────────────────────────────────────────────
    _render_visualisation(df_design, factors, k)

    # ── 6. Run table & download ────────────────────────────────────────────────
    _render_run_table(df_design, factors)


# ── Section renderers ─────────────────────────────────────────────────────────

def _render_objective_selector() -> str:
    st.markdown("---")
    st.subheader("① Experimental Objective")

    col_sel, col_desc = st.columns([1, 2])
    with col_sel:
        objective = st.radio(
            "Select objective",
            options=list(OBJECTIVE_INFO.keys()),
            index=2,  # default to Response Surface
            key="doe_objective",
            label_visibility="collapsed",
        )

    with col_desc:
        st.info(OBJECTIVE_INFO[objective])

    return objective


def _render_non_rsm_guidance(objective: str) -> None:
    st.markdown("---")
    if objective == "Comparative":
        st.subheader("Comparative Experiment Guidance")
        st.markdown(
            "For a comparative study:  \n"
            "- Decide on the response variable and acceptable effect size.  \n"
            "- Use a power analysis to determine the required number of replicates "
            "per condition.  \n"
            "- Randomise run order to guard against systematic drift.  \n"
            "- An independent two-sample t-test or one-way ANOVA is usually "
            "sufficient for single-factor comparisons.  \n\n"
            "This planner focuses on **Response Surface** designs. "
            "Select *Response Surface* above to continue."
        )
    else:
        st.subheader("Screening Experiment Guidance")
        st.markdown(
            "For a screening study with many factors (k ≥ 5):  \n"
            "- Consider a **2ᵏ⁻ᵖ fractional factorial** to test k factors in "
            "2ᵏ⁻ᵖ runs.  \n"
            "- **Plackett–Burman** designs allow up to k = N − 1 factors in N runs "
            "(N a multiple of 4).  \n"
            "- Use Resolution III or IV designs to screen; confounding of main "
            "effects with 2-factor interactions is acceptable at this stage.  \n"
            "- After screening, promote the 2–4 most important factors to an "
            "RSM experiment.  \n\n"
            "This planner focuses on **Response Surface** designs. "
            "Select *Response Surface* above to continue."
        )


def _render_design_selector() -> tuple[int | None, str | None]:
    st.markdown("---")
    st.subheader("② Number of Factors & Design Type")

    col_k, col_design = st.columns([1, 2])

    with col_k:
        k = st.number_input(
            "Number of factors",
            min_value=1,
            max_value=8,
            value=st.session_state.get("doe_k", 2),
            step=1,
            key="doe_k",
            help="How many independent process variables will you vary?",
        )

    with col_design:
        if k == 1:
            st.info(
                "With a single factor only a **linear (one-dimensional) study** "
                "is needed — vary the factor across its range and fit a polynomial. "
                "No formal DOE structure is required. Increase the factor count to "
                "design a multi-factor experiment."
            )
            return None, None

        if k > 4:
            _render_factor_collapsing_guidance(k)
            return None, None

        # k in {2, 3, 4}
        available_designs = ["Full Factorial (2-level)", "Central Composite Design (CCD)"]
        if k >= 3:
            available_designs.append("Box–Behnken Design (BBD)")

        selected_design = st.selectbox(
            "Design type",
            options=available_designs,
            key="doe_design",
            help="Choose the experimental design structure.",
        )

    if k >= 2:
        n_runs = _count_runs(selected_design, k)
        col_info_a, col_info_b = st.columns(2)
        with col_info_a:
            st.info(DESIGN_INFO[selected_design])
        with col_info_b:
            st.metric("Estimated run count", n_runs, help="Includes 1 centre point.")

    return int(k), selected_design


def _render_factor_collapsing_guidance(k: int) -> None:
    st.warning(
        f"**{k} factors** is a large space. Consider collapsing correlated "
        "variables into derived quantities before designing the experiment. "
        "This reduces run count dramatically and often improves physical "
        "interpretability."
    )
    with st.expander("💡 Factor collapsing suggestions", expanded=True):
        for tip in COLLAPSING_TIPS:
            st.markdown(f"- {tip}")
        st.markdown(
            "\nOnce you have reduced to **2–4 key factors** (or derived quantities), "
            "change the factor count above to continue."
        )


def _render_factor_editor(k: int) -> dict | None:
    st.markdown("---")
    st.subheader("③ Factor Definitions")
    st.caption(
        "Select a standard factor name or choose **Custom…** and type your own. "
        "Set the low (−1) and high (+1) levels; the centre point defaults to the "
        "arithmetic midpoint but can be adjusted for any asymmetry in your range."
    )

    standard_names = list(STANDARD_FACTORS.keys())
    factors: dict[str, dict] = {}
    factor_labels = [f"Factor {chr(65 + i)}" for i in range(k)]  # A, B, C, D

    for i in range(k):
        label = factor_labels[i]
        default_key = standard_names[min(i, len(standard_names) - 2)]  # avoid "Custom…"

        with st.container(border=True):
            col_name_sel, col_min, col_center, col_max, col_round = st.columns(
                [2.5, 1, 1, 1, 0.8]
            )

            with col_name_sel:
                sel = st.selectbox(
                    f"**{label}** — Name",
                    options=standard_names,
                    index=standard_names.index(default_key),
                    key=f"doe_factor_sel_{i}",
                )
                if sel == "Custom…":
                    name = st.text_input(
                        "Custom name",
                        value=st.session_state.get(f"doe_factor_custom_{i}", f"Factor {label}"),
                        key=f"doe_factor_custom_{i}",
                        label_visibility="collapsed",
                        placeholder="e.g. Hatch Spacing (mm)",
                    )
                else:
                    name = sel

            defaults = STANDARD_FACTORS.get(sel, {"min": 0.0, "max": 1.0, "center": 0.5})
            auto_center = (defaults["min"] + defaults["max"]) / 2

            with col_min:
                lo = st.number_input(
                    "Min (−1)",
                    value=float(defaults["min"]),
                    format="%.4g",
                    key=f"doe_min_{i}",
                )
            with col_max:
                hi = st.number_input(
                    "Max (+1)",
                    value=float(defaults["max"]),
                    format="%.4g",
                    key=f"doe_max_{i}",
                )
            with col_center:
                center = st.number_input(
                    "Centre (0)",
                    value=float(defaults.get("center", auto_center)),
                    format="%.4g",
                    key=f"doe_center_{i}",
                    help="Leave at midpoint, or adjust if your response space is asymmetric.",
                )
            with col_round:
                rnd = st.number_input(
                    "Round",
                    min_value=0,
                    max_value=6,
                    value=2,
                    step=1,
                    key=f"doe_round_{i}",
                    help="Decimal places to round factor values to in the output table.",
                )

            if lo >= hi:
                st.error(f"**{label}**: Min must be strictly less than Max.")
                return None

            factors[name] = {
                "min": lo,
                "max": hi,
                "center": center,
                "round": int(rnd),
                "unit": STANDARD_FACTORS.get(sel, {}).get("unit", ""),
            }

    # Check for duplicate names
    names_list = list(factors.keys())
    if len(set(names_list)) < len(names_list):
        st.error("Each factor must have a unique name. Please rename any duplicates.")
        return None

    return factors


# ── Design generators ─────────────────────────────────────────────────────────

def _generate_design(design_type: str, k: int) -> np.ndarray | None:
    try:
        if design_type == "Full Factorial (2-level)":
            return _full_factorial(k)
        elif design_type == "Central Composite Design (CCD)":
            return _ccd(k)
        elif design_type == "Box–Behnken Design (BBD)":
            return _bbd(k)
    except Exception as e:
        st.error(f"Design generation failed: {e}")
    return None


def _full_factorial(k: int) -> np.ndarray:
    combos = list(itertools.product([-1.0, 1.0], repeat=k))
    pts = np.array(combos, dtype=float)
    centre = np.zeros((1, k))
    return np.vstack([pts, centre])


def _ccd(k: int, alpha: float = 1.0, n_centre: int = 1) -> np.ndarray:
    factorial = _full_factorial(k)[:-1]  # drop centre from factorial block
    axial = []
    for i in range(k):
        for sign in (+alpha, -alpha):
            row = [0.0] * k
            row[i] = sign
            axial.append(row)
    axial_pts = np.array(axial, dtype=float)
    centre = np.zeros((n_centre, k))
    return np.vstack([factorial, axial_pts, centre])


def _bbd(k: int, n_centre: int = 1) -> np.ndarray:
    if k < 3:
        raise ValueError("Box–Behnken requires k ≥ 3 factors.")
    points = []
    for pair in itertools.combinations(range(k), 2):
        for combo in itertools.product([-1.0, 1.0], repeat=2):
            row = [0.0] * k
            for idx, val in zip(pair, combo):
                row[idx] = val
            points.append(row)
    pts = np.array(points, dtype=float)
    centre = np.zeros((n_centre, k))
    return np.vstack([pts, centre])


def _count_runs(design_type: str, k: int) -> int:
    if design_type == "Full Factorial (2-level)":
        return 2**k + 1
    elif design_type == "Central Composite Design (CCD)":
        return 2**k + 2 * k + 1
    elif design_type == "Box–Behnken Design (BBD)":
        n_pairs = k * (k - 1) // 2
        return n_pairs * 4 + 1
    return 0


def _decode_design(coded: np.ndarray, factors: dict) -> pd.DataFrame:
    """Convert coded (−1 / 0 / +1) array to a DataFrame of real values."""
    rows = []
    for pt in coded:
        row = {}
        for i, (name, finfo) in enumerate(factors.items()):
            c = float(pt[i])
            lo, center, hi = finfo["min"], finfo["center"], finfo["max"]
            if c <= 0:
                real_val = center + c * (center - lo)
            else:
                real_val = center + c * (hi - center)
            rnd = finfo.get("round", 2)
            row[name] = round(real_val, rnd)
        rows.append(row)

    df = pd.DataFrame(rows)
    return df


# ── Visualisation ─────────────────────────────────────────────────────────────

def _render_visualisation(df: pd.DataFrame, factors: dict, k: int) -> None:
    st.markdown("---")
    st.subheader("④ Design Space Visualisation")

    factor_names = list(factors.keys())

    # Identify point types for colouring
    point_labels = _classify_points(df, factors)

    color_map = {
        "Factorial": "#1f77b4",
        "Axial": "#ff7f0e",
        "Centre": "#2ca02c",
        "Edge midpoint": "#9467bd",
    }
    marker_sizes = {
        "Factorial": 12,
        "Axial": 10,
        "Centre": 14,
        "Edge midpoint": 10,
    }

    if k == 2:
        _plot_2d(df, factor_names, point_labels, color_map, marker_sizes)

    elif k == 3:
        _plot_3d(df, factor_names, point_labels, color_map, marker_sizes)

    elif k == 4:
        st.caption(
            "With 4 factors the design space is 4-dimensional. "
            "Use the slider below to filter by the 4th factor level and inspect "
            "3-D slices."
        )
        f4_name = factor_names[3]
        f4_vals = sorted(df[f4_name].unique())
        f4_labels = {v: f"{f4_name} = {v}" for v in f4_vals}

        selected_f4 = st.select_slider(
            f"Filter by **{f4_name}**",
            options=f4_vals,
            value=f4_vals[len(f4_vals) // 2],
            format_func=lambda v: f4_labels[v],
            key="doe_f4_filter",
        )
        df_slice = df[df[f4_name] == selected_f4].reset_index(drop=True)
        labels_slice = [point_labels[i] for i, row in df.iterrows() if row[f4_name] == selected_f4]

        if df_slice.empty:
            st.warning("No points at this level.")
        else:
            _plot_3d(df_slice, factor_names[:3], labels_slice, color_map, marker_sizes,
                     title=f"Slice: {f4_name} = {selected_f4}")


def _classify_points(df: pd.DataFrame, factors: dict) -> list[str]:
    """Label each design point as Factorial, Axial, Centre, or Edge midpoint."""
    labels = []
    factor_names = list(factors.keys())
    for _, row in df.iterrows():
        coded = []
        for name, finfo in factors.items():
            lo, center, hi = finfo["min"], finfo["center"], finfo["max"]
            val = row[name]
            if abs(val - center) < 1e-9:
                coded.append(0)
            elif abs(val - lo) < 1e-9 or abs(val - hi) < 1e-9:
                coded.append(1)
            else:
                coded.append(0.5)  # axial / intermediate

        n_nonzero = sum(abs(c) > 0.01 for c in coded)
        n_extreme = sum(abs(c - 1) < 0.01 for c in coded)
        n_zero = sum(abs(c) < 0.01 for c in coded)

        if n_nonzero == 0:
            labels.append("Centre")
        elif n_extreme == len(coded):
            labels.append("Factorial")
        elif n_nonzero == 1:
            labels.append("Axial")
        elif n_nonzero == 2 and n_zero == len(coded) - 2:
            labels.append("Edge midpoint")
        else:
            labels.append("Factorial")
    return labels


def _plot_2d(df, factor_names, point_labels, color_map, marker_sizes):
    x_name, y_name = factor_names[0], factor_names[1]

    fig = go.Figure()
    for ptype in dict.fromkeys(point_labels):
        mask = [l == ptype for l in point_labels]
        subset = df[mask]
        fig.add_trace(go.Scatter(
            x=subset[x_name],
            y=subset[y_name],
            mode="markers+text",
            name=ptype,
            text=[str(i + 1) for i, m in enumerate(mask) if m],
            textposition="top center",
            textfont=dict(size=9),
            marker=dict(
                size=marker_sizes.get(ptype, 10),
                color=color_map.get(ptype, "#888"),
                line=dict(width=1.5, color="white"),
                opacity=0.9,
            ),
            hovertemplate=(
                f"<b>{x_name}</b>: %{{x}}<br>"
                f"<b>{y_name}</b>: %{{y}}<br>"
                f"<b>Type</b>: {ptype}<extra></extra>"
            ),
        ))

    fig.update_layout(
        xaxis_title=x_name,
        yaxis_title=y_name,
        height=480,
        template="plotly_white",
        legend=dict(orientation="h", y=-0.15),
        margin=dict(l=20, r=20, t=40, b=60),
    )
    st.plotly_chart(fig, use_container_width=True)


def _plot_3d(df, factor_names, point_labels, color_map, marker_sizes,
             title: str = ""):
    x_name, y_name, z_name = factor_names[0], factor_names[1], factor_names[2]

    fig = go.Figure()
    run_indices = list(range(len(df)))

    for ptype in dict.fromkeys(point_labels):
        mask = [l == ptype for l in point_labels]
        subset = df[[x_name, y_name, z_name]][[m for m in mask]]
        idx_subset = [i + 1 for i, m in enumerate(mask) if m]

        # rebuild subset via boolean indexing
        bool_mask = pd.Series(mask)
        df_sub = df[bool_mask.values]

        fig.add_trace(go.Scatter3d(
            x=df_sub[x_name],
            y=df_sub[y_name],
            z=df_sub[z_name],
            mode="markers+text",
            name=ptype,
            text=[str(i + 1) for i, m in enumerate(mask) if m],
            textposition="top center",
            textfont=dict(size=8),
            marker=dict(
                size=marker_sizes.get(ptype, 8),
                color=color_map.get(ptype, "#888"),
                line=dict(width=1, color="white"),
                opacity=0.85,
            ),
            hovertemplate=(
                f"<b>{x_name}</b>: %{{x}}<br>"
                f"<b>{y_name}</b>: %{{y}}<br>"
                f"<b>{z_name}</b>: %{{z}}<br>"
                f"<b>Type</b>: {ptype}<extra></extra>"
            ),
        ))

    fig.update_layout(
        scene=dict(
            xaxis_title=x_name,
            yaxis_title=y_name,
            zaxis_title=z_name,
        ),
        height=540,
        template="plotly_white",
        legend=dict(orientation="h", y=-0.05),
        margin=dict(l=0, r=0, t=40, b=0),
        title=title or None,
    )
    st.plotly_chart(fig, use_container_width=True)


# ── Run table & download ──────────────────────────────────────────────────────

def _render_run_table(df_design: pd.DataFrame, factors: dict) -> None:
    st.markdown("---")
    st.subheader("⑤ Experiment Run Table")

    col_opts = st.columns([1, 1, 2])
    with col_opts[0]:
        randomise = st.checkbox(
            "Randomise run order",
            value=True,
            key="doe_randomise",
            help="Randomising the order of runs guards against systematic drift and "
                 "time-related confounding.",
        )
    with col_opts[1]:
        seed = st.number_input(
            "Random seed",
            min_value=0,
            max_value=9999,
            value=42,
            step=1,
            key="doe_seed",
            help="Set a seed for reproducible randomisation.",
        )

    df_out = df_design.copy()

    point_labels = _classify_points(df_out, factors)
    df_out.insert(0, "Point Type", point_labels)
    df_out.insert(0, "Std Order", range(1, len(df_out) + 1))

    if randomise:
        rng = random.Random(int(seed))
        run_order = list(range(1, len(df_out) + 1))
        rng.shuffle(run_order)
        df_out.insert(1, "Run Order", run_order)
        df_display = df_out.sort_values("Run Order").reset_index(drop=True)
    else:
        df_out.insert(1, "Run Order", range(1, len(df_out) + 1))
        df_display = df_out.copy()

    st.dataframe(df_display, hide_index=True, use_container_width=True)

    st.caption(
        f"**{len(df_display)} runs** total. "
        "Standard Order = order in which the design was constructed. "
        "Run Order = recommended execution sequence."
    )

    # CSV download
    csv_buf = io.StringIO()
    df_display.to_csv(csv_buf, index=False)
    st.download_button(
        label="⬇️ Download run table as CSV",
        data=csv_buf.getvalue().encode(),
        file_name="doe_run_table.csv",
        mime="text/csv",
        type="primary",
    )

    # Design summary card
    with st.expander("📐 Design summary & model terms", expanded=False):
        factor_names = list(factors.keys())
        k = len(factor_names)
        design_type = st.session_state.get("doe_design", "")

        st.markdown(f"**Design:** {design_type}  \n**Factors (k):** {k}  \n**Total runs:** {len(df_display)}")

        st.markdown("**Estimable model terms:**")
        terms = [f"β₀ (intercept)"]
        for name in factor_names:
            terms.append(f"β ({name}) — linear")
        if "CCD" in design_type or "Box" in design_type:
            for name in factor_names:
                terms.append(f"β ({name})² — quadratic")
        for a, b in itertools.combinations(factor_names, 2):
            terms.append(f"β ({a} × {b}) — interaction")

        for t in terms:
            st.markdown(f"- {t}")