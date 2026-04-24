"""
tab_calc.py — Renders the Calculators tab (tab 3).

Call render_calc_tab() from app.py inside the tab_calc context manager.
"""

import streamlit as st


# ── Public entry point ────────────────────────────────────────────────────────

def render_calc_tab() -> None:
    st.title("Calculators")

    with st.expander("🌀 Powder Delivery Rate", expanded=False):
        _render_powder_delivery_calculator()


# ── Private helpers ───────────────────────────────────────────────────────────

def _render_powder_delivery_calculator() -> None:
    """
    Calculates volumetric and mass powder delivery rates from feeder RPM.

    Formulae (from calibration spreadsheet):
        volume_delivery (mm³/s) = rpm × 1.3306
        mass_delivery   (g/min) = volume_delivery × density × 1e-6 × 60
    """

    with st.container(border=True):
        col_in, col_out = st.columns(2)

        with col_in:
            st.markdown("**Inputs**")
            rpm = st.number_input(
                "Feeder speed (rpm)",
                min_value=0.0,
                value=2.0,
                step=0.1,
                format="%.2f",
                help="Rotational speed of the powder feeder.",
            )
            density = st.number_input(
                "Powder density (kg/m³)",
                min_value=0.0,
                value=2700.0,
                step=10.0,
                format="%.0f",
                help="Bulk/skeletal density of the powder material. Default: 316L stainless steel (~7900 kg/m³).",
            )
            calibration_factor = st.number_input(
                "Calibration factor (mm³/s per rpm)",
                min_value=0.0,
                value=1.3306,
                step=0.0001,
                format="%.4f",
                help="Feeder-specific constant derived from calibration. Default from GTV PF 2/2 LC.",
            )

        with col_out:
            st.markdown("**Results**")

            volume_mm3_s = rpm * calibration_factor
            mass_g_min   = volume_mm3_s * density * 1e-6 * 60

            st.metric(
                label="Volumetric delivery rate",
                value=f"{volume_mm3_s:.4f} mm³/s",
                help="rpm × calibration factor",
            )
            st.metric(
                label="Mass delivery rate",
                value=f"{mass_g_min:.4f} g/min",
                help="Volume rate × density, converted to g/min",
            )

            st.markdown("---")
            st.caption(
                "**Formulae**  \n"
                "`volume (mm³/s) = rpm × calibration factor`  \n"
                "`mass (g/min)   = volume × density × 1×10⁻⁶ × 60`"
            )