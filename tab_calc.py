"""
tab_calc.py — Renders the Calculators tab.

Defaults for the powder delivery calculator come from `powder_calibration`
in config.yaml.
"""

import streamlit as st


def render_calc_tab(config: dict) -> None:
    st.title("Calculators")

    with st.expander("🌀 Powder Delivery Rate", expanded=False):
        _render_powder_delivery_calculator(config.get("powder_calibration", {}))


def _render_powder_delivery_calculator(cal: dict) -> None:
    """
    Volumetric and mass powder delivery rates from feeder RPM.

    Formulae (from calibration spreadsheet):
        volume_delivery (mm³/s) = rpm × calibration factor
        mass_delivery   (g/min) = volume_delivery × density × 1e-6 × 60
    """
    factor_default = float(cal.get("feeder_factor_mm3_per_s_per_rpm", 1.3306))
    density_default = float(cal.get("default_powder_density_kg_m3", 2700.0))

    with st.container(border=True):
        col_in, col_out = st.columns(2)

        with col_in:
            st.markdown("**Inputs**")
            rpm = st.number_input(
                "Feeder speed (rpm)", min_value=0.0, value=2.0, step=0.1, format="%.2f",
                help="Rotational speed of the powder feeder.",
            )
            density = st.number_input(
                "Powder density (kg/m³)", min_value=0.0, value=density_default, step=10.0, format="%.0f",
                help="Bulk density of the powder material, e.g. Al alloys ≈ 2700, 316L stainless ≈ 7900.",
            )
            calibration_factor = st.number_input(
                "Calibration factor (mm³/s per rpm)", min_value=0.0, value=factor_default,
                step=0.0001, format="%.4f",
                help="Feeder-specific constant from calibration. Default set in config.yaml.",
            )

        with col_out:
            st.markdown("**Results**")
            volume_mm3_s = rpm * calibration_factor
            mass_g_min = volume_mm3_s * density * 1e-6 * 60

            st.metric("Volumetric delivery rate", f"{volume_mm3_s:.4f} mm³/s", help="rpm × calibration factor")
            st.metric("Mass delivery rate", f"{mass_g_min:.4f} g/min", help="Volume rate × density, converted to g/min")

            st.markdown("---")
            st.caption(
                "**Formulae**  \n"
                "`volume (mm³/s) = rpm × calibration factor`  \n"
                "`mass (g/min)   = volume × density × 1×10⁻⁶ × 60`"
            )
