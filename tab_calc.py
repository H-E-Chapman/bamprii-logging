"""
tab_calc.py — Calculators tab: energy and powder, imaging, beamtime planning.

Defaults for the powder delivery inputs come from `powder_calibration` in
config.yaml. Everything else is entered in the tab.
"""

import math

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots
from scipy.ndimage import uniform_filter1d


def render_calc_tab(config: dict) -> None:
    st.title("Calculators")

    with st.expander("⚡ Energy & Powder", expanded=False):
        _render_energy_powder(config.get("powder_calibration", {}), config.get("materials", []))
    with st.expander("📷 Imaging: motion blur & frame budget", expanded=False):
        _render_imaging()
    with st.expander("⏱️ Beamtime Planner", expanded=False):
        _render_time_planner()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ratio(num: float, den: float) -> float | None:
    """num / den, or None when the denominator is zero."""
    return num / den if den else None


def _fmt(value: float | None, unit: str, decimals: int = 3) -> str:
    return "—" if value is None else f"{value:,.{decimals}f} {unit}"


def _fmt_duration(seconds: float) -> str:
    """Seconds as h:mm:ss."""
    seconds = max(0, int(round(seconds)))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}"


# ── Energy & Powder ───────────────────────────────────────────────────────────

_MATERIAL_INPUTS = {   # material-table key -> (widget key, label, step, format)
    "density_kg_m3":       ("ep_density", "Density (kg/m³)", 10.0, "%.0f"),
    "specific_heat_J_kgK": ("ep_cp", "Specific heat capacity (J/kg·K)", 10.0, "%.0f"),
    "latent_heat_J_kg":    ("ep_latent", "Latent heat of fusion (J/kg)", 5000.0, "%.0f"),
    "melting_point_C":     ("ep_melt", "Melting point (°C)", 10.0, "%.0f"),
    "absorptivity":        ("ep_absorb", "Laser absorptivity (0–1)", 0.05, "%.2f"),
}
CUSTOM = "Custom…"


def _apply_material(materials: list) -> None:
    """Selectbox callback: copy the chosen material's properties into the property inputs."""
    chosen = next((m for m in materials if m["name"] == st.session_state.get("ep_material")), None)
    if chosen:
        for key, (widget, *_rest) in _MATERIAL_INPUTS.items():
            st.session_state[widget] = float(chosen[key])


def _render_energy_powder(cal: dict, materials: list) -> None:
    """
    Laser energy densities, powder delivery and a melt-energy check for one set
    of process parameters.

        volume rate (mm³/s)      = rpm × calibration factor
        mass rate (g/min)        = volume rate × density × 1e-6 × 60
        linear energy density    = P / v                      (J/mm)
        areal energy density     = P / (v × d)                (J/mm²)
        power density            = P / (π d² / 4)             (W/mm²)
        interaction time         = d / v                      (s)
        powder deposited / length = mass rate × catchment / v          (g/mm)
        energy per caught mass    = P / (mass rate × catchment)         (J/g)
        energy to melt powder     = cp × (T_melt − T_0) + L_f           (J/g)
        melt energy ratio         = absorptivity × energy per caught mass / energy to melt
    """
    col_laser, col_powder, col_mat = st.columns(3)

    with col_laser:
        st.markdown("**Laser**")
        power = st.number_input("Laser power (W)", min_value=0.0, value=200.0, step=10.0, key="ep_power")
        speed = st.number_input("Scan speed (mm/s)", min_value=0.0, value=5.0, step=0.5, key="ep_speed")
        spot = st.number_input("Spot diameter (mm)", min_value=0.0, value=0.4, step=0.05, format="%.3f", key="ep_spot")
        t0 = st.number_input("Initial temperature (°C)", value=20.0, step=5.0, key="ep_t0",
                             help="Powder and substrate temperature before the laser arrives.")

    with col_powder:
        st.markdown("**Powder**")
        rpm = st.number_input("Feeder speed (rpm)", min_value=0.0, value=2.0, step=0.1, format="%.2f", key="ep_rpm")
        factor = st.number_input(
            "Calibration factor (mm³/s per rpm)", min_value=0.0, step=0.0001, format="%.4f", key="ep_factor",
            value=float(cal.get("feeder_factor_mm3_per_s_per_rpm", 1.3306)),
            help="Feeder-specific constant from calibration. Default set in config.yaml.",
        )
        catchment = st.number_input(
            "Catchment efficiency (%)", min_value=0.0, max_value=100.0, value=50.0, step=5.0, key="ep_catch",
            help="Share of the fed powder that lands in the melt pool and is deposited; the rest is lost. "
                 "BAMPR-II has been measured at about 50%: 40–60% depending on melt pool geometry, "
                 "25–75% in the worst case.",
        ) / 100

    with col_mat:
        st.markdown("**Material**")
        names = [m["name"] for m in materials] + [CUSTOM]
        if "ep_material" not in st.session_state:   # seed the property inputs from the first material
            st.session_state["ep_material"] = names[0]
            _apply_material(materials)
        st.selectbox("Material", options=names, key="ep_material", on_change=_apply_material, args=(materials,),
                     help="Choosing a material fills the properties below from config.yaml; edit any value "
                          "or pick Custom… to enter your own.")
        props = {}
        for key, (widget, label, step, fmt) in _MATERIAL_INPUTS.items():
            props[key] = st.number_input(label, min_value=0.0, step=step, format=fmt, key=widget)

    density = props["density_kg_m3"]
    volume_rate = rpm * factor                       # mm³/s
    mass_rate_g_s = volume_rate * density * 1e-6     # g/s
    mass_rate_g_min = mass_rate_g_s * 60
    caught_g_s = mass_rate_g_s * catchment           # g/s actually deposited
    energy_per_g = _ratio(power, caught_g_s)         # J per gram of powder caught by the melt pool
    sensible = props["specific_heat_J_kgK"] * (props["melting_point_C"] - t0) / 1000   # J/g
    latent = props["latent_heat_J_kg"] / 1000                                            # J/g
    to_melt = sensible + latent
    absorbed = None if energy_per_g is None else energy_per_g * props["absorptivity"]
    melt_ratio = _ratio(absorbed, to_melt) if absorbed is not None else None
    ratio_all_powder = _ratio(_ratio(power, mass_rate_g_s) * props["absorptivity"], to_melt) if mass_rate_g_s else None

    st.markdown("---")
    res_powder, res_laser, res_melt = st.columns(3)

    with res_powder:
        st.markdown("**Powder delivery**")
        st.metric("Volumetric rate", _fmt(volume_rate, "mm³/s", 4))
        st.metric("Mass rate (fed)", _fmt(mass_rate_g_min, "g/min", 3))
        st.metric("Powder deposited per unit length", _fmt(_ratio(caught_g_s * 1000, speed), "mg/mm", 3),
                  help="Fed powder per mm of track × catchment efficiency.")

    with res_laser:
        st.markdown("**Laser energy**")
        st.metric("Linear energy density", _fmt(_ratio(power, speed), "J/mm", 2))
        st.metric("Areal energy density", _fmt(_ratio(power, speed * spot), "J/mm²", 2))
        st.metric("Power density", _fmt(_ratio(power, math.pi * spot**2 / 4), "W/mm²", 1))
        t_int = _ratio(spot, speed)
        st.metric("Interaction time", _fmt(None if t_int is None else t_int * 1000, "ms", 1))
        st.metric("Energy per unit powder mass", _fmt(energy_per_g, "J/g", 0),
                  help="Laser energy per gram of powder caught by the melt pool (fed mass × catchment efficiency).")

    with res_melt:
        st.markdown("**Melt energy check**")
        st.metric("Energy to heat and melt the powder", _fmt(to_melt, "J/g", 0),
                  help=f"Sensible heat {sensible:,.0f} J/g to the melting point plus latent heat {latent:,.0f} J/g.")
        st.metric("Absorbed energy per unit powder mass", _fmt(absorbed, "J/g", 0),
                  help="Energy per unit powder mass × absorptivity.")
        st.metric("Melt energy ratio", "—" if melt_ratio is None else f"{melt_ratio:,.1f} ×",
                  help="Absorbed energy per gram ÷ energy to heat and melt one gram.")

    if melt_ratio is not None and ratio_all_powder:
        st.plotly_chart(_melt_ratio_figure(melt_ratio, ratio_all_powder, catchment), width="stretch")
        st.caption(
            "Zones follow published directed-energy-deposition and powder-bed studies: lack of fusion below about 2× "
            "(the Ti-6Al-4V DED threshold sits at 2–3×), workable builds at roughly 3–8×, excess energy above that. "
            "Published figures count all fed powder, so compare them with the circle; the diamond is the ratio for the "
            "powder actually caught."
        )
    if melt_ratio is not None:
        if melt_ratio < 1:
            st.warning(
                f"Melt energy ratio {melt_ratio:.1f}: the absorbed laser energy cannot even melt the powder "
                "caught by the melt pool. Expect unmelted particles and lack of fusion."
            )
        else:
            st.caption(
                f"Melt energy ratio {melt_ratio:.1f}: the absorbed energy is {melt_ratio:.1f}× what the caught powder "
                "needs to melt. The excess goes into the substrate melt pool, conduction and losses."
            )
    st.caption("Material properties are approximate handbook values from config.yaml; absorptivity in particular varies with surface state and should be treated as a guide.")


# (low, high, colour, label) on the melt-energy-ratio axis; colours are the status palette with transparency
_MELT_ZONES = [
    (0.0, 2.0, "rgba(208,59,59,0.28)", "Lack of fusion"),
    (2.0, 3.0, "rgba(250,178,25,0.30)", "Marginal"),
    (3.0, 8.0, "rgba(12,163,12,0.28)", "Workable"),
    (8.0, 12.0, "rgba(250,178,25,0.30)", "Excess energy"),
    (12.0, 1e9, "rgba(208,59,59,0.28)", "Over-melting"),
]


def _melt_ratio_figure(ratio: float, ratio_all_powder: float, catchment: float) -> go.Figure:
    """
    Horizontal band chart: melt energy ratio on a log axis with the literature
    zones. Markers show the ratio with all fed powder counted (as published
    studies define it) and at the entered catchment efficiency; bars behind the
    diamond span the measured catchment range of BAMPR-II, 40–60% typical and
    25–75% worst case.
    """
    x_min, x_max = 0.3, 40.0
    at = lambda eta: ratio_all_powder / eta            # ratio at a given catchment efficiency
    fig = go.Figure()
    for lo, hi, colour, label in _MELT_ZONES:
        a, b = max(lo, x_min), min(hi, x_max)
        if b <= a:
            continue
        fig.add_shape(type="rect", x0=a, x1=b, y0=0, y1=1, fillcolor=colour, line_width=0, layer="below")
        fig.add_annotation(x=math.log10(math.sqrt(a * b)), y=1.0, text=label, showarrow=False, yanchor="bottom",
                           font=dict(size=11), xref="x", yref="y")
    clamp = lambda v: min(max(v, x_min), x_max)
    fig.add_trace(go.Scatter(x=[clamp(at(0.75)), clamp(at(0.25))], y=[0.5, 0.5], mode="lines", name="25–75% catchment (worst case)",
                             line=dict(width=4, color="rgba(82,81,78,0.35)"), hovertemplate="25–75% catchment: %{x:.1f}×<extra></extra>"))
    fig.add_trace(go.Scatter(x=[clamp(at(0.60)), clamp(at(0.40))], y=[0.5, 0.5], mode="lines", name="40–60% catchment (typical)",
                             line=dict(width=10, color="rgba(82,81,78,0.8)"), hovertemplate="40–60% catchment: %{x:.1f}×<extra></extra>"))
    fig.add_trace(go.Scatter(
        x=[clamp(ratio_all_powder), clamp(ratio)], y=[0.5, 0.5], mode="markers+text",
        marker=dict(size=[12, 16], color=["#52514e", "#0b0b0b"], symbol=["circle", "diamond"], line=dict(width=2, color="white")),
        text=[f"all powder: {ratio_all_powder:.1f}×", f"{catchment:.0%} catchment: {ratio:.1f}×"],
        textposition=["bottom center", "top center"], textfont=dict(size=11),
        hovertemplate="%{text}<extra></extra>", showlegend=False,
    ))
    fig.update_layout(legend=dict(orientation="h", y=-0.55, x=0, font=dict(size=11)))
    fig.update_xaxes(type="log", range=[math.log10(x_min), math.log10(x_max)], title_text="melt energy ratio (absorbed energy ÷ energy to heat and melt the powder)",
                     tickvals=[0.3, 0.5, 1, 2, 3, 5, 8, 12, 20, 40], ticktext=["0.3", "0.5", "1", "2", "3", "5", "8", "12", "20", "40"], showgrid=False)
    fig.update_yaxes(visible=False, range=[-0.35, 1.45])
    fig.update_layout(height=260, margin=dict(l=20, r=20, t=30, b=70), template="plotly_white",
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    return fig


# ── Imaging ───────────────────────────────────────────────────────────────────

def _render_imaging() -> None:
    """
    Motion blur and frame budget for a high-speed camera watching the melt pool,
    with a simulated image of a feature of the given size as the camera would
    record it.

    Blur is set by the fastest feature of interest (spatter, melt flow, pore
    motion), not by the scan speed; the track timing is set by the scan speed.

        blur                = feature speed × exposure time
        advance per frame   = feature speed / framerate
        frames per mm       = framerate / scan speed
        track duration      = track length / scan speed
        buffer duration     = buffer frames / framerate
    """
    col_in, col_out = st.columns(2)

    with col_in:
        feature_speed = st.number_input(
            "Feature speed (mm/s)", min_value=0.0, value=1000.0, step=100.0, key="im_feature_speed",
            help="Speed of the fastest thing you need sharp: spatter and melt-pool flow are "
                 "typically 0.1 to a few m/s (100 to several thousand mm/s).",
        )
        speed = st.number_input("Scan speed (mm/s)", min_value=0.0, value=5.0, step=0.5, key="im_speed",
                                help="Sets the track duration and frames per mm of track.")
        exposure = st.number_input("Exposure time (µs)", min_value=0.0, value=20.0, step=1.0, key="im_exposure")
        framerate = st.number_input("Framerate (kfps)", min_value=0.0, value=10.0, step=0.5, key="im_fps")
        pixel = st.number_input("Effective pixel size (µm)", min_value=0.0, value=10.0, step=0.5, key="im_pixel")
        feature = st.number_input(
            "Feature size (µm)", min_value=0.0, value=50.0, step=5.0, key="im_feature",
            help="Diameter of the feature you need to resolve, e.g. a pore or spatter particle.",
        )
        track = st.number_input("Track length (mm)", min_value=0.0, value=20.0, step=1.0, key="im_track")
        buffer_frames = st.number_input(
            "Camera buffer (frames, 0 = ignore)", min_value=0, value=0, step=1000, key="im_buffer",
            help="Frames the camera can store at this resolution; leave 0 to skip the check.",
        )

    fps = framerate * 1000
    blur_um = feature_speed * exposure * 1e-3         # mm/s × µs → µm
    advance_um = _ratio(feature_speed * 1000, fps)    # µm the feature moves between frames
    frames_per_mm = _ratio(fps, speed)
    duration = _ratio(track, speed)
    frames_per_track = None if duration is None else duration * fps
    buffer_s = _ratio(buffer_frames, fps) if buffer_frames else None

    with col_out:
        st.markdown("**Per frame**")
        st.metric("Motion blur", _fmt(blur_um, "µm", 2))
        st.metric("Motion blur in pixels", _fmt(_ratio(blur_um, pixel), "px", 2))
        st.metric("Feature movement between frames", _fmt(advance_um, "µm", 2))
        st.markdown("**Per track**")
        st.metric("Frames per mm", _fmt(frames_per_mm, "", 0))
        st.metric("Track duration", "—" if duration is None else f"{duration:.2f} s")
        st.metric("Frames per track", _fmt(frames_per_track, "", 0))
        if buffer_s is not None:
            fits = frames_per_track is not None and frames_per_track <= buffer_frames
            st.metric("Buffer duration at this framerate", f"{buffer_s:.2f} s")
            (st.success if fits else st.error)(
                "Track fits in the buffer." if fits else "Track is longer than the buffer: lower the framerate or shorten the track."
            )

    blur_px = _ratio(blur_um, pixel)
    if blur_px is not None:
        if blur_px > 1:
            st.warning("Blur exceeds one pixel: shorten the exposure or accept smeared edges.")
        else:
            st.caption("Blur is under one pixel, so feature edges are limited by the optics rather than motion.")

    if feature > 0 and pixel > 0:
        st.plotly_chart(_blur_figure(feature, blur_um, pixel), width="stretch")
        st.caption(
            f"Left: a {feature:g} µm feature. Right: the same feature smeared by {blur_um:.1f} µm of motion "
            f"during the exposure and sampled on {pixel:g} µm pixels. Grid lines are pixel boundaries."
        )


_SUB = 8  # sub-samples per pixel in the blur simulation


def _blur_figure(feature_um: float, blur_um: float, pixel_um: float) -> go.Figure:
    """
    Side-by-side images: the sharp feature, and the feature smeared along the
    motion direction by the blur length and binned onto the camera's pixels.
    """
    n_pix = max(8, math.ceil((feature_um + blur_um) / pixel_um) + 4)
    n_pix += n_pix % 2  # even, so the feature sits on a pixel corner-free centre
    width = n_pix * pixel_um
    n = n_pix * _SUB
    step = pixel_um / _SUB
    coords = (np.arange(n) + 0.5) * step - width / 2
    xx, yy = np.meshgrid(coords, coords)
    scene = (xx**2 + yy**2 <= (feature_um / 2) ** 2).astype(float)

    kernel = max(1, int(round(blur_um / step)))
    smeared = uniform_filter1d(scene, size=kernel, axis=1, mode="constant")
    camera = smeared.reshape(n_pix, _SUB, n_pix, _SUB).mean(axis=(1, 3))

    fig = make_subplots(
        rows=1, cols=2, horizontal_spacing=0.06,
        subplot_titles=("Feature (no motion)", "Camera image (blur + pixels)"),
    )
    edges = np.arange(n_pix + 1) * pixel_um - width / 2
    fig.add_trace(go.Heatmap(z=scene, x=coords, y=coords, colorscale="Greys", zmin=0, zmax=1,
                             showscale=False, hoverinfo="skip"), row=1, col=1)
    fig.add_trace(go.Heatmap(z=camera, x=edges[:-1] + pixel_um / 2, y=edges[:-1] + pixel_um / 2,
                             colorscale="Greys", zmin=0, zmax=1, showscale=False,
                             hovertemplate="x %{x:.0f} µm<br>y %{y:.0f} µm<br>fill %{z:.2f}<extra></extra>"),
                  row=1, col=2)
    for col in (1, 2):
        for e in edges:
            fig.add_shape(type="line", x0=e, x1=e, y0=edges[0], y1=edges[-1],
                          line=dict(color="rgba(255,255,255,0.35)", width=1), row=1, col=col)
            fig.add_shape(type="line", y0=e, y1=e, x0=edges[0], x1=edges[-1],
                          line=dict(color="rgba(255,255,255,0.35)", width=1), row=1, col=col)
    if blur_um > 0:
        y0 = -width / 2 + pixel_um * 0.6
        fig.add_shape(type="line", x0=-blur_um / 2, x1=blur_um / 2, y0=y0, y1=y0,
                      line=dict(color="#d62728", width=3), row=1, col=2)
        fig.add_annotation(x=0, y=y0, text=f"blur {blur_um:.1f} µm", showarrow=False, yshift=12,
                           font=dict(color="#d62728", size=11), row=1, col=2)

    fig.update_xaxes(title_text="µm", range=[edges[0], edges[-1]], constrain="domain")
    fig.update_yaxes(range=[edges[0], edges[-1]], scaleanchor="x", scaleratio=1, showticklabels=False)
    fig.update_yaxes(scaleanchor="x2", row=1, col=2)
    fig.update_layout(height=380, margin=dict(l=20, r=20, t=40, b=40), template="plotly_white")
    return fig


# ── Beamtime planner ──────────────────────────────────────────────────────────

_PLAN_COLUMNS = ["Group", "Substrates", "Tracks per substrate", "Layers per track"]
_PLAN_DEFAULT = pd.DataFrame(
    [["Single tracks", 6, 10, 1], ["Thin walls", 4, 4, 10]], columns=_PLAN_COLUMNS
)


def _plan(groups: pd.DataFrame, scan_s: float, switch_s: float, margin: float) -> pd.DataFrame:
    """
    Time budget per substrate group. One scan is one layer of one track, so
    scans per substrate = tracks × layers; the time per scan already includes
    its overhead. Rows with a blank or zero count are ignored.

        substrate time = scans × time per scan + switch-over
        planned time   = substrate time × (1 + margin) × substrates
    """
    df = groups.dropna(subset=_PLAN_COLUMNS[1:]).copy()
    for col in _PLAN_COLUMNS[1:]:
        df[col] = df[col].astype(int)
    df = df[(df[_PLAN_COLUMNS[1:]] > 0).all(axis=1)].reset_index(drop=True)
    df["Group"] = df["Group"].fillna("").astype(str)
    df["Scans per substrate"] = df["Tracks per substrate"] * df["Layers per track"]
    df["Scans"] = df["Scans per substrate"] * df["Substrates"]
    df["Per substrate (s)"] = (df["Scans per substrate"] * scan_s + switch_s) * (1 + margin)
    df["Total (s)"] = df["Per substrate (s)"] * df["Substrates"]
    df["Cumulative (s)"] = df["Total (s)"].cumsum()
    return df


def _render_time_planner() -> None:
    """
    Whether a campaign of substrate groups fits the available beamtime.
    Each group has its own substrate count, tracks per substrate and layers per
    track; every scan is costed at one flat time that includes its overhead.
    Campaign-level overheads (initial setup, powder changes, major equipment
    changes) are added once, outside the per-substrate safety margin.
    """
    st.markdown("**Substrate groups** — one row per kind of experiment; add rows with ➕ at the bottom.")
    groups = st.data_editor(
        _PLAN_DEFAULT, num_rows="dynamic", hide_index=True, width="stretch", key="tp_groups",
        column_config={
            "Group": st.column_config.TextColumn("Group", help="Free label, e.g. material or geometry"),
            "Substrates": st.column_config.NumberColumn(min_value=0, step=1, format="%d"),
            "Tracks per substrate": st.column_config.NumberColumn(min_value=0, step=1, format="%d"),
            "Layers per track": st.column_config.NumberColumn(min_value=0, step=1, format="%d"),
        },
    )

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown("**Per scan / substrate**")
        scan_s = st.number_input(
            "Time per scan (s)", min_value=0.0, value=300.0, step=15.0, key="tp_scan",
            help="One layer of one track including repositioning, camera save and logging.  \n"
                 "For beamtime MA-7161, median time-per-scan was 4:15, with a lower quartile "
                 "of 2:32, and an upper quartile of 7:19. A sensible time-per-scan default "
                 "would be 5 minutes.",
        )
        switch_min = st.number_input(
            "Substrate switch-over (min)", min_value=0.0, value=15.0, step=1.0, key="tp_switch",
            help="Open hutch, swap substrate, realign, close and search.  \n"
                 "For beamtime MA-7161, median switch-over was 13:28, with a lower quartile "
                 "of 8:50, and an upper quartile of 22:06. A sensible default is 15 minutes.",
        )
    with c2:
        st.markdown("**Allowances**")
        margin_pct = st.number_input(
            "Safety margin (%)", min_value=0, max_value=200, value=25, step=5, key="tp_margin",
            help="Added to every substrate for retries, faults and the unexpected.",
        )
        breaks_per_day_h = st.number_input(
            "Breaks per 24 h (h)", min_value=0.0, max_value=24.0, value=4.0, step=0.5, key="tp_breaks",
            help="4 hours is 1 hour for breakfast and 1½ hours each for lunch and dinner, including handovers. Scaled to the available beamtime.",
        )
    with c3:
        st.markdown("**Campaign overheads**")
        setup_h = st.number_input(
            "Initial setup (h)", min_value=0.0, value=8.0, step=0.5, key="tp_setup",
            help="Time from the start of beamtime to the first substrate: alignment, "
                 "imaging set-up and parameter adjustment.",
        )
        n_powder = st.number_input("Powder changes", min_value=0, value=0, step=1, key="tp_n_powder")
        powder_h = st.number_input("Time per powder change (h)", min_value=0.0, value=1.0, step=0.25, key="tp_powder_h",
                                   help="Empty, clean and refill the hopper, then re-establish the feed.")
        n_equip = st.number_input("Major equipment changes", min_value=0, value=0, step=1, key="tp_n_equip")
        equip_h = st.number_input(
            "Time per equipment change (h)", min_value=0.0, value=4.0, step=0.5, key="tp_equip_h",
            help="Changing equipment like switching between motion controllers, or nozzle tips.",
        )
    with c4:
        st.markdown("**Beamtime**")
        available_h = st.number_input("Available beamtime (h)", min_value=0.0, value=72.0, step=1.0, key="tp_available")

    plan = _plan(groups, scan_s, switch_min * 60, margin_pct / 100)
    if plan.empty:
        st.info("Add at least one group with substrates, tracks and layers above zero.")
        return

    breaks_s = available_h / 24 * breaks_per_day_h * 3600
    usable_s = max(0.0, available_h * 3600 - breaks_s)
    overheads = [
        ("Initial setup", setup_h * 3600),
        (f"{n_powder} powder change{'s' if n_powder != 1 else ''}", n_powder * powder_h * 3600),
        (f"{n_equip} major equipment change{'s' if n_equip != 1 else ''}", n_equip * equip_h * 3600),
    ]
    overhead_s = sum(v for _, v in overheads)
    substrates_s = float(plan["Total (s)"].sum())
    planned_s = substrates_s + overhead_s
    surplus_s = usable_s - planned_s
    fits = plan["Cumulative (s)"] + overhead_s <= usable_s
    n_fit = int(fits.sum())

    st.markdown("---")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Substrates planned", int(plan["Substrates"].sum()), help=f"{int(plan['Scans'].sum())} scans in total.")
    m2.metric("Time needed", _fmt_duration(planned_s),
              help=f"Substrates {_fmt_duration(substrates_s)} (with the {margin_pct}% margin) "
                   f"+ overheads {_fmt_duration(overhead_s)}.")
    m3.metric("Usable beamtime", _fmt_duration(usable_s), help=f"{_fmt_duration(breaks_s)} of breaks removed.")
    m4.metric("Surplus" if surplus_s >= 0 else "Shortfall", _fmt_duration(abs(surplus_s)))

    if surplus_s >= 0:
        last = plan.iloc[-1]
        extra = int(surplus_s // last["Per substrate (s)"]) if last["Per substrate (s)"] else 0
        st.success(f"The plan fits. The surplus covers about {extra} more substrate(s) of '{last['Group']}'.")
    else:
        st.error(
            f"The plan does not fit: {n_fit} of {len(plan)} groups complete in table order. "
            "Reduce counts, trim the time per scan, or reorder the groups by priority."
        )

    table = plan.assign(
        **{
            "Per substrate": plan["Per substrate (s)"].map(_fmt_duration),
            "Group total": plan["Total (s)"].map(_fmt_duration),
            "Cumulative": plan["Cumulative (s)"].map(_fmt_duration),
            "Fits": fits.map({True: "✅", False: "❌"}),
        }
    )[["Group", "Substrates", "Tracks per substrate", "Layers per track", "Scans per substrate",
       "Scans", "Per substrate", "Group total", "Cumulative", "Fits"]]
    st.dataframe(table, hide_index=True, width="stretch")
    st.dataframe(
        pd.DataFrame(
            [(k, _fmt_duration(v)) for k, v in overheads]
            + [("Overheads total", _fmt_duration(overhead_s)), ("Substrates (with margin)", _fmt_duration(substrates_s)),
               ("Time needed", _fmt_duration(planned_s))],
            columns=["Campaign item", "Time"],
        ),
        hide_index=True, width="stretch",
    )
    st.caption(
        "Durations are h:mm:ss. 'Fits' is cumulative in table order after the overheads, so put the "
        "highest-priority groups first. Per-substrate time = scans × time per scan + switch-over, plus "
        "the margin; the overheads are added once without a margin."
    )
