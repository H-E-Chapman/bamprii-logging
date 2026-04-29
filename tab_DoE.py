"""
tab_DoE.py — Renders the Experimental Design tab.

Three fully-functional sections:
  1. Comparative  — compare two conditions and calculate their significance
  2. Screening    — Plackett-Burman (N=8/12) and 2^(k-p) fractional factorials
  3. Response Surface — Full Factorial (configurable levels + centroid),
                        CCD (CCC/CCF/CCI with correct NIST alpha), Box-Behnken

NIST reference:
  https://www.itl.nist.gov/div898/handbook/pri/section3/pri336.htm
"""

from __future__ import annotations

import io
import itertools
import math
import random

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from scipy import stats as scipy_stats

# ─────────────────────────────────────────────────────────────────────────────
#  Shared constants
# ─────────────────────────────────────────────────────────────────────────────

STANDARD_FACTORS: dict[str, dict] = {
    "Laser Power (W)":              {"min": 50.0,  "max": 500.0,  "center": 250.0,  "unit": "W"},
    "Scan Speed (mm/s)":            {"min": 1.0,   "max": 20.0,   "center": 5.0,    "unit": "mm/s"},
    "Powder Delivery (g/min)":      {"min": 0.1,   "max": 10.0,   "center": 2.0,    "unit": "g/min"},
    "Laser Spot Size (mm)":         {"min": 0.1,   "max": 0.8,    "center": 0.4,    "unit": "mm"},
    "Shield Gas Flow (lpm)":        {"min": 5.0,   "max": 20.0,   "center": 12.5,   "unit": "lpm"},
    "Carrier Gas Flow (lpm)":       {"min": 2.0,   "max": 8.0,    "center": 5.0,    "unit": "lpm"},
    "Linear Energy Density (J/mm)": {"min": 0.1,   "max": 2.0,    "center": 1.0,    "unit": "J/mm"},
    "Powder Density (g/mm)":        {"min": 0.002, "max": 0.05,   "center": 0.02,   "unit": "g/mm"},
    "Energy/Powder Ratio (J/g)":    {"min": 10.0,  "max": 200.0,  "center": 100.0,  "unit": "J/g"},
    "Custom…":                      {"min": 0.0,   "max": 1.0,    "center": 0.5,    "unit": ""},
}

OBJECTIVE_INFO = {
    "Comparative": (
        "**Comparative** objectives test whether changing a discrete factor "
        "(e.g. material, nozzle type, operator) produces a statistically "
        "significant change in a response. The output is a comparison of result "
        "values for two sets of conditions, and their significance."
    ),
    "Screening": (
        "**Screening** objectives identify *which* factors from a large "
        "candidate set most influence the response. Fractional-factorial and "
        "Plackett–Burman designs test many factors in few runs by assuming "
        "higher-order interactions are negligible. Use this before committing "
        "to a full RSM study."
    ),
    "Response Surface": (
        "**Response Surface** objectives map the continuous relationship "
        "between factors and response to find optima or build a predictive "
        "model. CCD and Box–Behnken designs support estimation of linear, "
        "interaction, *and* quadratic effects."
    ),
}

# ─────────────────────────────────────────────────────────────────────────────
#  Plackett-Burman base rows (cyclic-shift construction)
# ─────────────────────────────────────────────────────────────────────────────

# Each tuple is one base row; cyclic-shift N-1 times then append all-(-1) row
# Source: Plackett & Burman (1946), Biometrika 33(4):305-325
_PB_BASE: dict[int, list[int]] = {
    8:  [ 1, 1, 1,-1, 1,-1,-1],
    12: [ 1, 1,-1, 1, 1, 1,-1,-1,-1, 1,-1],
    16: [ 1, 1, 1, 1,-1, 1,-1, 1, 1,-1,-1, 1,-1,-1,-1],
    20: [ 1, 1,-1,-1, 1, 1, 1, 1,-1, 1,-1, 1,-1,-1,-1,-1, 1, 1,-1],
}

# Standard 2^(k-p) generators [NIST Table 3a-c]
# Format: list of tuples (resolution, runs, base_k, generators)
# generators: list of column-index combinations whose product gives the extra factor
_FF_DESIGNS: dict[tuple, dict] = {
    # (k, p): {"res": resolution, "runs": N, "base": base_k, "gens": [[col_indices...],...]}
    (3, 1): {"res": "III", "runs":  4, "base": 2, "gens": [[0, 1]]},
    (4, 1): {"res": "IV",  "runs":  8, "base": 3, "gens": [[0, 1, 2]]},
    (5, 1): {"res": "V",   "runs": 16, "base": 4, "gens": [[0, 1, 2, 3]]},
    (5, 2): {"res": "III", "runs":  8, "base": 3, "gens": [[0, 1], [0, 2]]},
    (6, 2): {"res": "IV",  "runs": 16, "base": 4, "gens": [[0, 1, 2], [0, 1, 3]]},
    (6, 3): {"res": "III", "runs":  8, "base": 3, "gens": [[0, 1], [0, 2], [1, 2]]},
    (7, 3): {"res": "IV",  "runs": 16, "base": 4, "gens": [[0,1,2],[0,1,3],[0,2,3]]},
    (7, 4): {"res": "III", "runs":  8, "base": 3, "gens": [[0,1],[0,2],[1,2],[0,1,2]]},
    (8, 4): {"res": "IV",  "runs": 16, "base": 4, "gens": [[0,1,2],[0,1,3],[0,2,3],[1,2,3]]},
}

_FF_RESOLUTION_NOTES = {
    "III": "Main effects are **not** confounded with each other but ARE confounded "
           "with 2-factor interactions. Use only for an initial screen where 2FI "
           "are assumed negligible.",
    "IV":  "Main effects are clear of 2-factor interactions (2FI), but 2FIs are "
           "confounded with each other. Good balance of information vs run count.",
    "V":   "Both main effects **and** 2-factor interactions are estimable. "
           "Near-RSM capability in a fractional design.",
}

# CCD recommended centre replicates (NIST Table 3.24)
_CCD_NC_REC = {2: 5, 3: 6, 4: 7}
_BBD_NC_REC = {3: 3, 4: 3}


# ─────────────────────────────────────────────────────────────────────────────
#  Power-analysis helpers (no scipy dependency)
# ─────────────────────────────────────────────────────────────────────────────

def _norm_ppf(p: float) -> float:
    """Rational approximation for standard normal quantile (Abramowitz & Stegun)."""
    if p <= 0 or p >= 1:
        return float("nan")
    sign = 1 if p >= 0.5 else -1
    q = min(p, 1 - p)
    t = math.sqrt(-2 * math.log(q))
    c = (2.515517, 0.802853, 0.010328)
    d = (1.432788, 0.189269, 0.001308)
    approx = t - (c[0] + c[1]*t + c[2]*t**2) / (1 + d[0]*t + d[1]*t**2 + d[2]*t**3)
    return sign * approx


def _ttest_n_per_group(effect_size: float, alpha: float, power: float) -> int:
    """
    Two-sample two-tailed t-test: minimum n per group.
    Effect size = Cohen's d = |mu1-mu2| / sigma_pooled.
    Uses normal approximation (conservative; accurate for n > ~20).
    """
    if effect_size <= 0:
        return 9999
    z_a = _norm_ppf(1 - alpha / 2)
    z_b = _norm_ppf(power)
    n = 2 * ((z_a + z_b) / effect_size) ** 2
    return max(2, math.ceil(n))


def _anova_n_per_group(f_effect: float, k_groups: int, alpha: float, power: float) -> int:
    """
    One-way ANOVA: minimum n per group (normal approximation via Cohen's f).
    Cohen's f = sigma_m / sigma_e  (between-group SD / within-group SD).
    """
    if f_effect <= 0 or k_groups < 2:
        return 9999
    # Non-centrality parameter: lambda = n * k * f^2
    # Power ≈ P(chi^2(df1, lambda) > chi^2_crit(df1))
    # Approximation: n ≈ (z_alpha + z_power)^2 / f^2 / k_groups * (k_groups - 1 + k_groups)
    # Simpler approximation treating ANOVA as equivalent independent t-tests:
    df1 = k_groups - 1
    z_a = _norm_ppf(1 - alpha)          # one-sided F
    z_b = _norm_ppf(power)
    # lambda = (z_a + z_b)^2 at minimum power threshold
    # lambda = n * k_groups * f^2  → n = lambda / (k_groups * f^2)
    lam = (z_a + z_b) ** 2
    n = lam / (k_groups * f_effect ** 2) + df1 / k_groups
    return max(2, math.ceil(n))


# ─────────────────────────────────────────────────────────────────────────────
#  Public entry point
# ─────────────────────────────────────────────────────────────────────────────

def render_doe_tab() -> None:
    st.title("Experimental Design Planner")
    st.caption(
        "Guided workflow covering comparative tests, factor screening, and "
        "Response Surface Methodology. Reference: "
        "[NIST/SEMATECH Engineering Statistics Handbook §5.3]"
        "(https://www.itl.nist.gov/div898/handbook/pri/section3/pri3.htm)."
    )

    objective = _render_objective_selector()

    st.markdown("---")
    if objective == "Comparative":
        _render_comparative_section()
    elif objective == "Screening":
        _render_screening_section()
    else:
        _render_rsm_section()


# ─────────────────────────────────────────────────────────────────────────────
#  Section ① — Objective selector (shared)
# ─────────────────────────────────────────────────────────────────────────────

def _render_objective_selector() -> str:
    st.subheader("① Experimental Objective")
    col_sel, col_desc = st.columns([1, 2])
    with col_sel:
        obj = st.radio(
            "Objective",
            options=list(OBJECTIVE_INFO.keys()),
            index=2,
            key="doe_objective",
            label_visibility="collapsed",
        )
    with col_desc:
        st.info(OBJECTIVE_INFO[obj])
    return obj


# ─────────────────────────────────────────────────────────────────────────────
#  COMPARATIVE section
# ─────────────────────────────────────────────────────────────────────────────

def _render_comparative_section() -> None:
    st.subheader("② Comparative Experiment")
    st.caption("Enter measured values for each condition to compare their means and variability.")

    # ── Labels ────────────────────────────────────────────────────────────────
    with st.container(border=True):
        st.markdown("**Labels**")
        c1, c2, c3 = st.columns(3)
        with c1:
            response_label = st.text_input("Response variable", value="Melt pool depth (mm)", key="comp_response")
        with c2:
            label_a = st.text_input("Condition A label", value="Condition A", key="comp_label_a")
        with c3:
            label_b = st.text_input("Condition B label", value="Condition B", key="comp_label_b")

    # ── Data entry ────────────────────────────────────────────────────────────
    with st.container(border=True):
        st.markdown("**Data entry**")
        st.caption("Enter one value per row. Rows with no values are ignored.")

        n_rows = int(st.number_input(
            "Number of rows", min_value=2, max_value=50,
            value=8, step=1, key="comp_nrows"
        ))

        default_df = pd.DataFrame({
            label_a: [None] * n_rows,
            label_b: [None] * n_rows,
        })

        edited = st.data_editor(
            default_df,
            use_container_width=True,
            num_rows="fixed",
            key="comp_table",
            column_config={
                label_a: st.column_config.NumberColumn(label_a, format="%.4f"),
                label_b: st.column_config.NumberColumn(label_b, format="%.4f"),
            },
        )

    # ── Extract valid values ──────────────────────────────────────────────────
    vals_a = edited[label_a].dropna().astype(float).tolist()
    vals_b = edited[label_b].dropna().astype(float).tolist()

    if len(vals_a) < 2 and len(vals_b) < 2:
        st.info("Enter at least 2 values in one condition to see results.")
        return

    # ── Summary stats ─────────────────────────────────────────────────────────
    def _stats(vals):
        arr = np.array(vals)
        return {
            "n":    len(arr),
            "mean": float(np.mean(arr))                          if len(arr) >= 1 else None,
            "std":  float(np.std(arr, ddof=1))                   if len(arr) >= 2 else 0.0,
            "se":   float(np.std(arr, ddof=1) / np.sqrt(len(arr))) if len(arr) >= 2 else 0.0,
        }

    sa, sb = _stats(vals_a), _stats(vals_b)

    def _fmt(v, decimals=4):
        return f"{v:.{decimals}f}" if v is not None else "—"

    with st.container(border=True):
        st.markdown("**Summary statistics**")
        col1, col2, col3 = st.columns(3)

        for col, label, s in [(col1, label_a, sa), (col2, label_b, sb)]:
            with col:
                st.markdown(f"**{label}**")
                st.metric("n",    s["n"])
                st.metric("Mean", _fmt(s["mean"]))
                st.metric("SD",   _fmt(s["std"]))
                st.metric("SE",   _fmt(s["se"]))

        with col3:
            if sa["mean"] is not None and sb["mean"] is not None:
                delta = sb["mean"] - sa["mean"]
                pct   = (delta / sa["mean"] * 100) if sa["mean"] != 0 else None
                st.markdown("**Difference (B − A)**")
                st.metric("Δ mean", _fmt(delta))
                if pct is not None:
                    st.metric("Δ %", f"{pct:+.2f}%")

    # ── Plot ──────────────────────────────────────────────────────────────────
    with st.container(border=True):
        st.markdown("**Condition comparison**")

        error_type = st.radio(
            "Error bars show",
            ["Standard deviation (SD)", "Standard error (SE)"],
            horizontal=True,
            key="comp_error_type",
        )

        colors = ["#4C72B0", "#DD8452"]
        rng = np.random.default_rng(42)

        # Build subplot: bar chart (left) + strip plot (right)
        fig = make_subplots(
            rows=1, cols=2,
            column_widths=[0.55, 0.45],
            subplot_titles=[
                f"Mean ± {error_type.split()[0]}",
                "Data distribution",
            ],
        )

        all_data = [
            (label_a, sa, vals_a),
            (label_b, sb, vals_b),
        ]

        for i, (label, s, vals) in enumerate(all_data):
            if s["mean"] is None:
                continue

            err = s["std"] if "SD" in error_type else s["se"]

            # ── Left: bar + error bar ──────────────────────────────────────
            fig.add_trace(go.Bar(
                x=[label],
                y=[s["mean"]],
                error_y=dict(
                    type="data", array=[err],
                    visible=True,
                    color="black",
                    thickness=1.5,
                    width=8,
                ),
                marker_color=colors[i],
                opacity=0.8,
                name=label,
                showlegend=False,
                hovertemplate=(
                    f"<b>{label}</b><br>"
                    f"Mean: {s['mean']:.4f}<br>"
                    f"±{error_type.split()[0]}: {err:.4f}<br>"
                    f"n = {s['n']}"
                    "<extra></extra>"
                ),
            ), row=1, col=1)

            # ── Right: strip plot with jitter ─────────────────────────────
            if vals:
                jitter = rng.uniform(-0.15, 0.15, len(vals))
                fig.add_trace(go.Box(
                    x=[label] * len(vals),
                    y=vals,
                    name=label,
                    marker_color=colors[i],
                    boxpoints="all",
                    jitter=0.4,
                    pointpos=0,
                    line=dict(color=colors[i]),
                    fillcolor=f"rgba({int(colors[i][1:3], 16)}, "
                               f"{int(colors[i][3:5], 16)}, "
                               f"{int(colors[i][5:7], 16)}, 0.2)",
                    showlegend=False,
                    hovertemplate="%{y:.4f}<extra></extra>",
                ), row=1, col=2)

        fig.update_layout(
            height=440,
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            bargap=0.45,
            margin=dict(t=50, b=40, l=40, r=20),
        )
        fig.update_yaxes(
            title_text=response_label, row=1, col=1,
            showgrid=True, gridcolor="rgba(128,128,128,0.15)",
        )
        fig.update_yaxes(
            title_text=response_label, row=1, col=2,
            showgrid=True, gridcolor="rgba(128,128,128,0.15)",
        )
        fig.update_xaxes(showgrid=False)

        st.plotly_chart(fig, use_container_width=True)

    # ── Welch's t-test ────────────────────────────────────────────────────────
    if len(vals_a) >= 2 and len(vals_b) >= 2:
        with st.container(border=True):
            st.markdown("**Welch's t-test**")

            t_stat, p_val = scipy_stats.ttest_ind(vals_a, vals_b, equal_var=False)

            alpha_thresh = st.selectbox(
                "Significance level (α)",
                [0.01, 0.05, 0.10],
                index=1,
                format_func=lambda x: f"{x:.2f}",
                key="comp_ttest_alpha",
            )

            c1, c2, c3 = st.columns(3)
            c1.metric("t-statistic",  f"{t_stat:.4f}")
            c2.metric("p-value",      f"{p_val:.4f}")
            c3.metric("Significant?", "Yes ✓" if p_val < alpha_thresh else "No ✗")

            if p_val < alpha_thresh:
                st.success(
                    f"p = {p_val:.4f} < α = {alpha_thresh:.2f}: "
                    "the means are statistically distinguishable."
                )
            else:
                st.warning(
                    f"p = {p_val:.4f} ≥ α = {alpha_thresh:.2f}: "
                    "insufficient evidence to distinguish the means."
                )


# ─────────────────────────────────────────────────────────────────────────────
#  SCREENING section
# ─────────────────────────────────────────────────────────────────────────────

def _render_screening_section() -> None:
    st.subheader("② Screening Design")
    st.caption(
        "Identify the most influential factors before committing to a full RSM "
        "study. All designs here are **two-level** (low/high only). "
        "Once the important factors are identified (typically 2–4), move to "
        "**Response Surface** mode."
    )

    # ── Factor count & design picker ──────────────────────────────────────────
    with st.container(border=True):
        top = st.columns([1, 2])
        with top[0]:
            k = int(st.number_input(
                "Number of factors to screen",
                min_value=2, max_value=15,
                value=st.session_state.get("scr_k", 5),
                step=1, key="scr_k",
            ))
        with top[1]:
            design_options = _screening_options(k)
            if not design_options:
                st.error("No standard screening design available for this factor count.")
                return
            design_choice = st.selectbox(
                "Design",
                options=list(design_options.keys()),
                key="scr_design",
            )

    info = design_options[design_choice]
    n_runs = info["runs"]
    max_factors = info["max_k"]

    dcols = st.columns([2, 1, 1])
    with dcols[0]:
        st.info(_screening_design_description(design_choice, info, k))
    with dcols[1]:
        st.metric("Runs", n_runs)
    with dcols[2]:
        st.metric("Max factors for this design", max_factors)

    if "res" in info:
        st.caption(
            f"**Resolution {info['res']}** — {_FF_RESOLUTION_NOTES[info['res']]}"
        )

    # ── Factor names (low / high only) ────────────────────────────────────────
    st.markdown("---")
    st.subheader("③ Factor Definitions (Low / High)")
    factor_names, factor_lo, factor_hi, factor_rnd = _render_screening_factor_editor(k)
    if factor_names is None:
        return

    # ── Generate coded matrix ─────────────────────────────────────────────────
    coded = _generate_screening_design(design_choice, info, k)
    if coded is None:
        st.error("Could not generate design matrix.")
        return

    # Decode to real values
    df_coded = pd.DataFrame(coded, columns=[f"x{i+1}" for i in range(k)])
    df_real  = pd.DataFrame()
    for i, name in enumerate(factor_names):
        lo, hi, rnd = factor_lo[i], factor_hi[i], factor_rnd[i]
        mid = (lo + hi) / 2.0
        df_real[name] = df_coded[f"x{i+1}"].apply(
            lambda c, lo=lo, hi=hi, mid=mid: round(lo if c < 0 else (mid if c == 0 else hi), rnd)
        )

    # ── Run table ──────────────────────────────────────────────────────────────
    st.markdown("---")
    st.subheader("④ Screening Run Table")

    seed = int(st.number_input("Random seed", min_value=0, max_value=9999,
                                value=42, step=1, key="scr_seed"))
    randomise = st.checkbox("Randomise run order", value=True, key="scr_rand")

    df_out = df_real.copy()
    n = len(df_out)
    df_out.insert(0, "Std Order", range(1, n + 1))

    run_order = list(range(1, n + 1))
    if randomise:
        rng = random.Random(seed)
        rng.shuffle(run_order)
    df_out.insert(1, "Run Order", run_order)
    df_display = df_out.sort_values("Run Order").reset_index(drop=True)

    st.dataframe(df_display, hide_index=True, use_container_width=True)
    st.caption(f"**{n} runs**, {k} factors.")

    csv_buf = io.StringIO()
    df_display.to_csv(csv_buf, index=False)
    st.download_button(
        "⬇️ Download screening design as CSV",
        data=csv_buf.getvalue().encode(),
        file_name="screening_design.csv",
        mime="text/csv",
        type="primary",
    )

    with st.expander("🔢 Coded design matrix (−1 / +1)", expanded=False):
        df_coded_disp = df_coded.copy()
        df_coded_disp.columns = factor_names
        df_coded_disp.insert(0, "Std Order", range(1, n + 1))
        st.dataframe(df_coded_disp, hide_index=True, use_container_width=True)
        st.caption(
            "−1 = low level, +1 = high level, 0 = centre (Plackett-Burman only at "
            "the dummy/foldover column level)."
        )

    # ── Follow-up guidance ─────────────────────────────────────────────────────
    with st.expander("📋 After the screening run — next steps", expanded=False):
        st.markdown(
            "1. **Fit a main-effects model**: regress the response on all k factors.  \n"
            "2. **Rank factors by |effect|** (or t-statistic/p-value).  \n"
            "3. **Select the 2–4 most important factors** for follow-up.  \n"
            "4. **Switch to Response Surface mode** in this planner and design a "
            "CCD or Box–Behnken study on those factors.  \n"
            "5. If several factors have similar effect sizes, check the "
            "half-normal plot before discarding any."
        )


def _screening_options(k: int) -> dict[str, dict]:
    """Return the available screening designs for k factors."""
    opts: dict[str, dict] = {}

    # Full 2-level factorial (always available for small k)
    if k <= 5:
        n = 2 ** k
        opts[f"Full 2^{k} factorial ({n} runs)"] = {
            "type": "ff_full", "runs": n, "max_k": k
        }

    # 2^(k-p) fractional factorials
    for (kk, p), info in _FF_DESIGNS.items():
        if kk == k:
            label = (
                f"2^({k}−{p}) fractional factorial — "
                f"Res {info['res']}, {info['runs']} runs"
            )
            opts[label] = {**info, "type": "ff_frac", "k": k, "p": p,"max_k": k}

    # Plackett-Burman
    for pb_n, base in _PB_BASE.items():
        max_k = pb_n - 1
        if max_k >= k:
            label = f"Plackett–Burman N={pb_n} (up to {max_k} factors)"
            opts[label] = {"type": "pb", "runs": pb_n, "max_k": max_k, "pb_n": pb_n}
            break  # only suggest smallest PB that fits

    return opts


def _screening_design_description(choice: str, info: dict, k: int) -> str:
    t = info.get("type", "")
    if t == "ff_full":
        return (
            f"Tests **all {2**k} combinations** of low/high levels for {k} factors. "
            "Estimates all main effects and all interactions. "
            "Use when run cost is low and k ≤ 4."
        )
    elif t == "ff_frac":
        p = info.get("p", 1)
        return (
            f"A **2^({k}−{p}) = {info['runs']}-run** fraction of the full 2^{k} = {2**k}-run "
            f"factorial. Resolution {info['res']}: "
            + _FF_RESOLUTION_NOTES[info["res"]]
        )
    elif t == "pb":
        return (
            f"**Plackett–Burman N={info['pb_n']}** design, accommodating up to "
            f"{info['pb_n']-1} factors in {info['pb_n']} runs. Highly efficient for "
            "pure main-effect estimation. 2FIs are partially confounded across all "
            "columns — use only when 2FIs are expected to be small."
        )
    return ""


def _render_screening_factor_editor(k: int):
    standard_names = list(STANDARD_FACTORS.keys())
    names, lo_vals, hi_vals, rnd_vals = [], [], [], []

    for i in range(k):
        default_key = standard_names[min(i, len(standard_names) - 2)]
        with st.container(border=True):
            cols = st.columns([2.5, 1, 1, 0.8])
            with cols[0]:
                sel = st.selectbox(
                    f"Factor {chr(65+i)} — Name",
                    options=standard_names,
                    index=standard_names.index(default_key),
                    key=f"scr_sel_{i}",
                )
                if sel == "Custom…":
                    name = st.text_input(
                        "Custom name",
                        value=st.session_state.get(f"scr_custom_{i}", f"Factor {chr(65+i)}"),
                        key=f"scr_custom_{i}",
                        label_visibility="collapsed",
                    )
                else:
                    name = sel
            d = STANDARD_FACTORS.get(sel, {"min": 0.0, "max": 1.0})
            with cols[1]:
                lo = st.number_input("Low (−1)", value=float(d["min"]),
                                     format="%.4g", key=f"scr_lo_{i}")
            with cols[2]:
                hi = st.number_input("High (+1)", value=float(d["max"]),
                                     format="%.4g", key=f"scr_hi_{i}")
            with cols[3]:
                rnd = int(st.number_input("Round", min_value=0, max_value=6,
                                          value=2, step=1, key=f"scr_rnd_{i}"))
            if lo >= hi:
                st.error(f"Factor {chr(65+i)}: Low must be < High.")
                return None, None, None, None
            names.append(name); lo_vals.append(lo); hi_vals.append(hi); rnd_vals.append(rnd)

    if len(set(names)) < len(names):
        st.error("Duplicate factor names — please rename.")
        return None, None, None, None

    return names, lo_vals, hi_vals, rnd_vals


def _generate_screening_design(choice: str, info: dict, k: int) -> np.ndarray | None:
    t = info.get("type", "")
    try:
        if t == "ff_full":
            pts = list(itertools.product([-1.0, 1.0], repeat=k))
            return np.array(pts, dtype=float)

        elif t == "ff_frac":
            base_k = info["base"]
            gens   = info["gens"]
            # Generate full 2^base_k factorial
            base_pts = np.array(
                list(itertools.product([-1.0, 1.0], repeat=base_k)), dtype=float
            )
            # Append generated columns
            extra_cols = []
            for gen in gens:
                col = np.prod(base_pts[:, gen], axis=1, keepdims=True)
                extra_cols.append(col)
            if extra_cols:
                full = np.hstack([base_pts] + extra_cols)
            else:
                full = base_pts
            return full[:, :k]

        elif t == "pb":
            return _build_pb(info["pb_n"], k)

    except Exception as e:
        st.error(f"Design generation error: {e}")
    return None


def _build_pb(n: int, k: int) -> np.ndarray:
    """Build Plackett-Burman design with N rows and k columns."""
    base = _PB_BASE[n]
    rows = []
    for shift in range(n - 1):
        row = [base[(j - shift) % (n - 1)] for j in range(n - 1)]
        rows.append(row)
    rows.append([-1] * (n - 1))  # all-low row
    mat = np.array(rows, dtype=float)
    return mat[:, :k]


# ─────────────────────────────────────────────────────────────────────────────
#  RSM section
# ─────────────────────────────────────────────────────────────────────────────

_RSM_DESIGN_INFO = {
    "Axis Sweep (Centred OAT)": (
        "Sensitivity analysis design using one-at-a-time variation of each factor "
        "while holding all other factors fixed at their centroid values.\n\n"
        "Purpose: identify primary factor effects and relative sensitivities.\n"
        "Suitable for early-stage exploration of continuous variables.\n\n"
        "Limitation: does not estimate interaction effects or response curvature."
    ),

    "Full Factorial": (
        "Complete combinatorial design evaluating all possible level combinations "
        "across factors.\n\n"
        "• Two-level design (2^k): evaluates corner points of the design space.\n"
        "• Multi-level design (≥3 levels): includes interior structure and midpoints.\n\n"
        "Purpose: estimation of main effects and all interaction effects.\n"
        "Suitable for small numbers of factors due to exponential scaling with k.\n\n"
        "Capability: captures interactions; curvature requires ≥3 levels."
    ),

    "Central Composite Design (CCD)": (
        "Second-order response surface design combining factorial points, axial points, "
        "and centre replicates to estimate quadratic models.\n\n"
        "Model includes linear, interaction, and quadratic terms.\n\n"
        "Variants:\n"
        "• CCC (Circumscribed): rotatable design with axial distance α = (2^k)^(1/4)\n"
        "• CCF (Face-centred): axial points at ±1 within factor bounds\n"
        "• CCI (Inscribed): scaled factorial region within original bounds\n\n"
        "Purpose: efficient estimation of curvature and interactions in continuous factor space.\n"
        "Note: CCC may require extrapolation beyond nominal factor bounds."
    ),

    "Box–Behnken Design (BBD)": (
        "Second-order design constructed from midpoints of factor edges, excluding "
        "corner points of the design space.\n\n"
        "Purpose: estimation of quadratic response surfaces without extreme factor combinations.\n\n"
        "Requires k ≥ 3 factors.\n"
        "Run size approximately 4·C(k,2) plus centre replicates.\n\n"
        "Advantages: avoids extreme operating conditions while supporting quadratic modelling.\n"
        "Limitation: does not explore full boundary of the factor space."
    ),
}


def _render_rsm_section() -> None:
    result = _render_rsm_design_selector()
    if result is None:
        return
    k, design_type, params = result

    factors = _render_factor_editor(k)
    if factors is None:
        return

    st.markdown("---")
    coded, point_labels = _generate_rsm_design(design_type, k, params)
    if coded is None:
        return

    df_design = _decode_design(coded, factors)
    _render_visualisation(df_design, factors, k, point_labels)
    _render_rsm_run_table(df_design, factors, point_labels)


def _render_rsm_design_selector():
    st.subheader("② Factor Count & Design Type")

    top = st.columns([1, 2])
    with top[0]:
        k = int(st.number_input(
            "Number of factors",
            min_value=1, max_value=8,
            value=st.session_state.get("doe_k", 2),
            step=1, key="doe_k",
            help="How many continuous process variables will you vary?",
        ))
    with top[1]:
        if k == 1:
            st.info(
                "With **1 factor** a simple linear (or polynomial) sweep is sufficient — "
                "no formal DOE needed. Increase the factor count to design a "
                "multi-factor experiment."
            )
            return None
        if k > 4:
            _render_factor_collapsing_guidance(k)
            return None

        available = [
            "Axis Sweep (Centred OAT)",
            "Full Factorial",
            "Central Composite Design (CCD)"
        ]
        if k >= 3:
            available.append("Box–Behnken Design (BBD)")
        design_type = st.selectbox(
            "Design type", options=available, key="doe_design",
        )

    st.markdown(
        f"<small>{_RSM_DESIGN_INFO[design_type]}</small>",
        unsafe_allow_html=True,
    )
    st.markdown("")

    params: dict = {}
    # ── Axis Sweep (Centred OAT) ─────────────────────────────────────────────
    if design_type == "Axis Sweep (Centred OAT)":
        st.markdown("**Axis sweep settings**")

        n_levels = st.slider(
            "Levels per axis (including centre)",
            min_value=3,
            max_value=11,
            value=5,
            step=2,
            help=(
                "Number of points per factor axis. Must be odd so there is a true "
                "centre (0). Example: 5 → [-1, -0.5, 0, 0.5, 1]"
            ),
            key="doe_axis_levels"
        )

        include_centre = st.checkbox(
            "Ensure centre point is included once",
            value=True,
            help="Adds the (0,0,...,0) point only once at the start of the design.",
            key="doe_axis_centre"
        )

        params = {
            "n_levels": n_levels,
            "include_centre": include_centre
        }

        n_runs = _rsm_count_runs(design_type, k, params)
        st.metric("Total runs", n_runs)

        st.caption(
            "Design structure: 1 centre + k × (n_levels − 1) axis points"
        )
    # ── Full Factorial controls ────────────────────────────────────────────────
    if design_type == "Full Factorial":
        st.markdown("**Levels per factor**")

        levels = []
        cols = st.columns(min(k, 4))

        for i in range(k):
            with cols[i % 4]:
                lvl = int(st.number_input(
                    f"{chr(65 + i)} levels",
                    min_value=2, max_value=7, value=3,
                    step=1, key=f"doe_levels_{i}",
                    help="Number of grid points along this factor axis."
                ))
                levels.append(lvl)

        add_centroid = st.checkbox(
            "Add centroid (if not already included)",
            value=False,
            key="doe_ff_centroid",
            help="Adds a centre point if not already part of the grid."
        )

        params = {
            "levels_per_factor": levels,
            "add_centroid": add_centroid
        }

        n_runs = _rsm_count_runs(design_type, k, params)
        st.metric("Total runs", n_runs)

        if n_runs > 100:
            st.warning("⚠️ Large design — consider CCD or Box–Behnken for efficiency.")

    # ── CCD controls ───────────────────────────────────────────────────────────
    elif design_type == "Central Composite Design (CCD)":
        ctrl = st.columns([1, 1, 1, 1])
        with ctrl[0]:
            variant = st.selectbox(
                "CCD variant",
                ["CCC — Circumscribed", "CCF — Face-Centred", "CCI — Inscribed"],
                key="doe_ccd_variant",
            )
        variant_short = variant.split(" — ")[0]

        alpha_ccc = round((2 ** k) ** 0.25, 4)
        alpha_display = (
            alpha_ccc if variant_short == "CCC"
            else 1.0 if variant_short == "CCF"
            else round(1.0 / alpha_ccc, 4)
        )
        with ctrl[1]:
            st.metric(
                "α (star distance)",
                f"{alpha_display:.4f}",
                help=(
                    "Distance from centre to star/axial points in coded units.  \n"
                    f"CCC: (2ᵏ)^¼ = {alpha_ccc:.4f} — rotatable.  \n"
                    "CCF: 1.0 — face of cube.  \n"
                    f"CCI: 1/α_CCC = {1/alpha_ccc:.4f} — factorial shrunk inside."
                ),
            )

        default_nc = _CCD_NC_REC.get(k, 3)
        with ctrl[2]:
            n_center = int(st.number_input(
                "Centre replicates (nₒ)",
                min_value=0, max_value=10, value=default_nc,
                step=1, key="doe_ccd_nc",
                help=f"NIST recommends {default_nc} for k={k}.",
            ))

        params = {"variant": variant_short, "n_center": n_center}
        n_runs = _rsm_count_runs(design_type, k, params)
        with ctrl[3]:
            st.metric("Total runs", n_runs,
                      help=f"2^{k} factorial + 2×{k} axial + {n_center} centre")

        if variant_short == "CCC":
            st.caption(
                f"⚠️ CCC star points lie at ±{alpha_ccc:.3f} in coded units — "
                f"~{(alpha_ccc-1)*100:.0f}% beyond your stated Min/Max. "
                "The Min/Max you enter below define the **factorial ±1 range**; "
                "axial points will extrapolate beyond those bounds."
            )

    # ── BBD controls ───────────────────────────────────────────────────────────
    elif design_type == "Box–Behnken Design (BBD)":
        ctrl = st.columns([1, 2])
        default_nc = _BBD_NC_REC.get(k, 3)
        with ctrl[0]:
            n_center = int(st.number_input(
                "Centre replicates (nₒ)",
                min_value=0, max_value=10, value=default_nc,
                step=1, key="doe_bbd_nc",
                help=f"NIST recommends {default_nc} for k={k}.",
            ))
        params = {"n_center": n_center}
        n_runs = _rsm_count_runs(design_type, k, params)
        with ctrl[1]:
            st.metric("Total runs", n_runs)

    return k, design_type, params


def _render_factor_collapsing_guidance(k: int) -> None:
    tips = [
        "**Linear Energy Density (LED)** = Laser Power ÷ Scan Speed (J/mm).  \n"
        "Combines the two most influential parameters into one energy-per-length metric.",
        "**Powder Density** = Feed Rate ÷ Scan Speed → mass/length.  \n"
        "Captures deposited material per unit track length independently of speed.",
        "**Energy/Powder Ratio** = LED ÷ Powder Density (J/g).  \n"
        "Single proxy for energy per unit mass of powder — linked to melt pool temperature.",
        "**Shield/Carrier Gas Ratio**: fix total flow, vary ratio → reduces 2 factors to 1.",
    ]
    st.warning(
        f"**{k} factors** is a large continuous space. Consider collapsing "
        "correlated variables into derived quantities to reduce run count."
    )
    with st.expander("💡 Factor collapsing suggestions", expanded=True):
        for tip in tips:
            st.markdown(f"- {tip}")
        st.markdown("Once reduced to **2–4 key factors**, change the count above.")


def _render_factor_editor(k: int) -> dict | None:
    st.markdown("---")
    st.subheader("③ Factor Definitions")
    st.caption(
        "Select a standard factor or choose **Custom…** and enter your own name. "
        "Set Low (coded −1) and High (coded +1); Centre defaults to the midpoint "
        "but can be adjusted for asymmetric ranges."
    )
    standard_names = list(STANDARD_FACTORS.keys())
    factors: dict[str, dict] = {}

    for i in range(k):
        label = f"Factor {chr(65+i)}"
        default_key = standard_names[min(i, len(standard_names) - 2)]

        with st.container(border=True):
            c_name, c_lo, c_ctr, c_hi, c_rnd = st.columns([2.5, 1, 1, 1, 0.8])
            with c_name:
                sel = st.selectbox(
                    f"**{label}** — Name", options=standard_names,
                    index=standard_names.index(default_key),
                    key=f"doe_factor_sel_{i}",
                )
                name = (
                    st.text_input(
                        "Custom name",
                        value=st.session_state.get(f"doe_factor_custom_{i}", label),
                        key=f"doe_factor_custom_{i}",
                        label_visibility="collapsed",
                        placeholder="e.g. Hatch Spacing (mm)",
                    )
                    if sel == "Custom…"
                    else sel
                )

            d = STANDARD_FACTORS.get(sel, {"min": 0.0, "max": 1.0, "center": 0.5})
            with c_lo:
                lo = st.number_input("Min (−1)", value=float(d["min"]),
                                     format="%.4g", key=f"doe_min_{i}")
            with c_hi:
                hi = st.number_input("Max (+1)", value=float(d["max"]),
                                     format="%.4g", key=f"doe_max_{i}")
            with c_ctr:
                ctr = st.number_input(
                    "Centre (0)",
                    value=float(d.get("center", (d["min"]+d["max"])/2)),
                    format="%.4g", key=f"doe_center_{i}",
                    help="Adjust if the design space is asymmetric about the midpoint.",
                )
            with c_rnd:
                rnd = int(st.number_input("Round", min_value=0, max_value=6,
                                          value=2, step=1, key=f"doe_round_{i}"))
            if lo >= hi:
                st.error(f"**{label}**: Min must be strictly less than Max.")
                return None
            factors[name] = {"min": lo, "max": hi, "center": ctr,
                             "round": rnd, "unit": d.get("unit", "")}

    if len(set(factors)) < len(factors):
        st.error("Duplicate factor names — please rename.")
        return None
    return factors


# ─────────────────────────────────────────────────────────────────────────────
#  RSM design generators  (NIST-correct)
# ─────────────────────────────────────────────────────────────────────────────

def _generate_rsm_design(
    design_type: str, k: int, params: dict
) -> tuple[np.ndarray, list[str]] | tuple[None, None]:
    try:
        if design_type == "Axis Sweep (Centred OAT)":
            return _gen_axis_sweep(k, params)
        elif design_type == "Full Factorial":
            return _gen_full_factorial(k, params)
        elif design_type == "Central Composite Design (CCD)":
            return _gen_ccd(k, params)
        elif design_type == "Box–Behnken Design (BBD)":
            return _gen_bbd(k, params)
    except Exception as e:
        st.error(f"Design generation failed: {e}")
    return None, None

def _gen_axis_sweep(k: int, params: dict):
    levels = params.get("n_levels", 5)  # includes centre
    span = np.linspace(-1, 1, levels)

    pts = []

    # centre point first
    centre = np.zeros(k)
    pts.append(centre)

    for i in range(k):
        for v in span:
            if np.isclose(v, 0):
                continue  # avoid duplicate centre
            row = np.zeros(k)
            row[i] = v
            pts.append(row)

    labels = ["Centre"] + ["Axis sweep"] * (len(pts) - 1)
    return np.array(pts), labels

def _gen_full_factorial(k: int, params: dict):
    levels = params.get("levels_per_factor", [2]*k)
    add_c  = params.get("add_centroid", False)

    # Build axis for each factor
    axes = []
    for n_lev in levels:
        if n_lev == 1:
            axis = [0.0]
        else:
            axis = np.linspace(-1.0, 1.0, n_lev)
        axes.append(axis)

    # Generate full grid
    pts = np.array(list(itertools.product(*axes)), dtype=float)

    # ---- classify points
    labels = []
    for row in pts:
        if np.allclose(row, 0):
            labels.append("Centre")

        elif np.all(np.isin(row, [-1, 1])):
            labels.append("Corner")

        elif np.any(np.isclose(np.abs(row), 1)) and np.any(np.isclose(row, 0)):
            labels.append("Edge / Face")

        else:
            labels.append("Interior")

    # ---- optional centroid
    if add_c:
        origin = np.zeros(k)
        if not any(np.allclose(r, origin) for r in pts):
            pts = np.vstack([pts, origin])
            labels.append("Centre")

    return pts, labels

def _gen_ccd(k: int, params: dict):
    """
    CCD point counts (NIST §5.3.3.6.1):
      Factorial block : 2^k corners at ±fact_level
      Star/axial block: 2k points at ±star_alpha along each axis (all others = 0)
      Centre block    : n_center replicates at origin

    CCC: fact_level=1, star_alpha=(2^k)^0.25  (rotatable, alpha > 1)
    CCF: fact_level=1, star_alpha=1            (alpha=1, 3 levels)
    CCI: fact_level=1/alpha_ccc, star_alpha=1  (factorial shrunk, star at limits)
    """
    variant  = params.get("variant", "CCC")
    n_center = params.get("n_center", 1)

    alpha_ccc = (2 ** k) ** 0.25

    if variant == "CCC":
        fact_level, star_alpha = 1.0, alpha_ccc
    elif variant == "CCF":
        fact_level, star_alpha = 1.0, 1.0
    elif variant == "CCI":
        fact_level, star_alpha = 1.0 / alpha_ccc, 1.0
    else:
        raise ValueError(f"Unknown CCD variant: {variant}")

    # Factorial block: 2^k corners
    fact_pts = np.array(
        list(itertools.product([-fact_level, +fact_level], repeat=k)), dtype=float
    )
    fact_labels = ["Factorial"] * len(fact_pts)

    # Axial/star block: 2k points, strictly one non-zero per row
    star_rows = []
    for i in range(k):
        for sign in (+star_alpha, -star_alpha):
            row = np.zeros(k)
            row[i] = sign
            star_rows.append(row)
    star_pts    = np.array(star_rows, dtype=float)
    star_labels = ["Axial"] * len(star_pts)

    # Centre block
    if n_center > 0:
        centre_pts    = np.zeros((n_center, k))
        centre_labels = ["Centre"] * n_center
    else:
        centre_pts    = np.empty((0, k))
        centre_labels = []

    coded  = np.vstack([p for p in [fact_pts, star_pts, centre_pts] if len(p)])
    labels = fact_labels + star_labels + centre_labels
    return coded, labels


def _gen_bbd(k: int, params: dict):
    if k < 3:
        raise ValueError("Box–Behnken requires k ≥ 3 factors.")
    n_center = params.get("n_center", 1)

    pts = []
    for pair in itertools.combinations(range(k), 2):
        for combo in itertools.product([-1.0, 1.0], repeat=2):
            row = np.zeros(k)
            for idx, val in zip(pair, combo):
                row[idx] = val
            pts.append(row)

    edge_pts    = np.array(pts, dtype=float)
    edge_labels = ["Edge midpoint"] * len(edge_pts)

    if n_center > 0:
        centre_pts    = np.zeros((n_center, k))
        centre_labels = ["Centre"] * n_center
    else:
        centre_pts    = np.empty((0, k))
        centre_labels = []

    coded  = np.vstack([p for p in [edge_pts, centre_pts] if len(p)])
    labels = edge_labels + centre_labels
    return coded, labels


def _rsm_count_runs(design_type: str, k: int, params: dict) -> int:
    if design_type == "Axis Sweep (Centred OAT)":
        n_levels = params.get("n_levels", 5)
        return 1 + k * (n_levels - 1)

    elif design_type == "Full Factorial":
        levels = params.get("levels_per_factor", [2]*k)
        total = int(np.prod(levels))

        if params.get("add_centroid", False):
            has_center = all(l % 2 == 1 for l in levels)
            if not has_center:
                total += 1

        return total

    elif design_type == "Central Composite Design (CCD)":
        return 2**k + 2*k + params.get("n_center", 1)

    elif design_type == "Box–Behnken Design (BBD)":
        return k*(k-1)//2 * 4 + params.get("n_center", 1)

    return 0


# ─────────────────────────────────────────────────────────────────────────────
#  Shared decode + plotting
# ─────────────────────────────────────────────────────────────────────────────

def _decode_design(coded: np.ndarray, factors: dict) -> pd.DataFrame:
    """
    Piecewise-linear mapping from coded units to real values.

    coded = -1  →  lo (min)
    coded =  0  →  center
    coded = +1  →  hi  (max)
    Values outside [-1, +1] (CCC axial points) are extrapolated linearly.
    """
    rows = []
    for pt in coded:
        row = {}
        for i, (name, f) in enumerate(factors.items()):
            c = float(pt[i])
            lo, ctr, hi = f["min"], f["center"], f["max"]
            hl = ctr - lo   # half-range, low side
            hh = hi  - ctr  # half-range, high side
            if c <= -1.0:
                val = lo   + (c + 1.0) * hl   # extrapolate below lo
            elif c <= 0.0:
                val = ctr  + c * hl
            elif c <= 1.0:
                val = ctr  + c * hh
            else:
                val = hi   + (c - 1.0) * hh   # extrapolate above hi
            row[name] = round(val, f.get("round", 2))
        rows.append(row)
    return pd.DataFrame(rows)


_C_MAP = {
    "Factorial":     "#1f77b4",
    "Axial":         "#ff7f0e",
    "Centre":        "#2ca02c",
    "Edge midpoint": "#9467bd",
}
_S_MAP = {
    "Factorial": 12, "Axial": 11, "Centre": 16, "Edge midpoint": 11,
}


def _render_visualisation(
    df: pd.DataFrame, factors: dict, k: int, point_labels: list[str]
) -> None:
    st.markdown("---")
    st.subheader("④ Design Space Visualisation")
    fnames = list(factors.keys())

    if k == 2:
        _plot_2d(df, fnames, point_labels)
    elif k == 3:
        _plot_3d(df, fnames, point_labels)
    elif k == 4:
        st.caption("4-D space — use the selector to slice by the 4th factor level.")
        f4 = fnames[3]
        vals = sorted(df[f4].unique())
        sel  = st.select_slider(
            f"Filter by **{f4}**",
            options=vals, value=vals[len(vals)//2],
            format_func=lambda v: f"{f4} = {v}",
            key="doe_f4_filter",
        )
        mask = df[f4] == sel
        df_sl = df[mask].reset_index(drop=True)
        lbl_sl = [l for l, m in zip(point_labels, mask) if m]
        if df_sl.empty:
            st.warning("No design points at this level.")
        else:
            _plot_3d(df_sl, fnames[:3], lbl_sl, title=f"Slice: {f4} = {sel}")


def _plot_2d(df, fnames, labels, title=""):
    x, y = fnames[0], fnames[1]
    fig = go.Figure()
    nums = list(range(1, len(df) + 1))
    for pt in dict.fromkeys(labels):
        idx = [i for i, l in enumerate(labels) if l == pt]
        sub = df.iloc[idx]
        fig.add_trace(go.Scatter(
            x=sub[x], y=sub[y],
            mode="markers+text", name=pt,
            text=[str(nums[i]) for i in idx],
            textposition="top center", textfont=dict(size=9),
            marker=dict(size=_S_MAP.get(pt,10), color=_C_MAP.get(pt,"#888"),
                        line=dict(width=1.5, color="white"), opacity=0.9),
            hovertemplate=f"<b>{x}</b>: %{{x}}<br><b>{y}</b>: %{{y}}<br>"
                          f"<b>Type</b>: {pt}<extra></extra>",
        ))
    fig.update_layout(xaxis_title=x, yaxis_title=y, height=480,
                      template="plotly_white",
                      legend=dict(orientation="h", y=-0.18),
                      margin=dict(l=20,r=20,t=40,b=60), title="")
    st.plotly_chart(fig, use_container_width=True)


def _plot_3d(df, fnames, labels, title=""):
    x, y, z = fnames[0], fnames[1], fnames[2]
    fig = go.Figure()
    nums = list(range(1, len(df) + 1))
    for pt in dict.fromkeys(labels):
        idx = [i for i, l in enumerate(labels) if l == pt]
        sub = df.iloc[idx]
        fig.add_trace(go.Scatter3d(
            x=sub[x], y=sub[y], z=sub[z],
            mode="markers+text", name=pt,
            text=[str(nums[i]) for i in idx],
            textposition="top center", textfont=dict(size=8),
            marker=dict(size=_S_MAP.get(pt,8), color=_C_MAP.get(pt,"#888"),
                        line=dict(width=1, color="white"), opacity=0.85),
            hovertemplate=f"<b>{x}</b>: %{{x}}<br><b>{y}</b>: %{{y}}<br>"
                          f"<b>{z}</b>: %{{z}}<br><b>Type</b>: {pt}<extra></extra>",
        ))
    fig.update_layout(
        scene=dict(xaxis_title=x, yaxis_title=y, zaxis_title=z),
        height=540, template="plotly_white",
        legend=dict(orientation="h", y=-0.05),
        margin=dict(l=0,r=0,t=40,b=0), title="",
    )
    st.plotly_chart(fig, use_container_width=True)


def _render_rsm_run_table(
    df_design: pd.DataFrame, factors: dict, point_labels: list[str]
) -> None:
    st.markdown("---")
    st.subheader("⑤ Experiment Run Table")

    ctl = st.columns([1, 1, 2])
    with ctl[0]:
        rand = st.checkbox("Randomise run order", value=True, key="doe_randomise")
    with ctl[1]:
        seed = int(st.number_input("Random seed", min_value=0, max_value=9999,
                                    value=42, step=1, key="doe_seed"))

    df = df_design.copy()
    n  = len(df)
    df.insert(0, "Point Type", point_labels)
    df.insert(0, "Std Order",  range(1, n + 1))

    run_order = list(range(1, n + 1))
    if rand:
        rng = random.Random(seed)
        rng.shuffle(run_order)
    df.insert(1, "Run Order", run_order)
    df_disp = df.sort_values("Run Order").reset_index(drop=True)

    st.dataframe(df_disp, hide_index=True, use_container_width=True)

    pt_counts = {}
    for l in point_labels:
        pt_counts[l] = pt_counts.get(l, 0) + 1
    breakdown = "  |  ".join(f"{v}× {k}" for k, v in sorted(pt_counts.items()))
    st.caption(f"**{n} total runs** — {breakdown}.")

    csv = io.StringIO()
    df_disp.to_csv(csv, index=False)
    st.download_button(
        "⬇️ Download run table as CSV",
        data=csv.getvalue().encode(),
        file_name="rsm_run_table.csv",
        mime="text/csv", type="primary",
    )

    with st.expander("📐 Design summary & estimable model terms", expanded=False):
        fnames = list(factors.keys())
        k = len(fnames)
        design = st.session_state.get("doe_design", "")
        st.markdown(
            f"**Design:** {design}  \n**k:** {k}  \n**Total runs:** {n}  \n"
            f"**Point breakdown:** {breakdown}"
        )
        terms = ["β₀ (intercept)"] + [f"β ({n}) — linear" for n in fnames]
        if "CCD" in design or "Box" in design or "BBD" in design:
            terms += [f"β ({n})² — quadratic" for n in fnames]
        terms += [f"β ({a}×{b}) — interaction"
                  for a, b in itertools.combinations(fnames, 2)]
        for t in terms:
            st.markdown(f"- {t}")