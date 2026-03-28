"""Load-aware AISC W-shape section optimizer targeting UR ≈ 0.9."""

from __future__ import annotations

from dataclasses import dataclass

from staad_generator.spec import BuildingSpec

# AISC W-shape properties: (name, weight_lb_ft, Zx_in3, Ix_in4, A_in2)
_W_SHAPES: list[tuple[str, float, float, float, float]] = [
    ("W6X9", 9, 6.23, 16.4, 2.68),
    ("W6X12", 12, 8.30, 22.1, 3.55),
    ("W8X10", 10, 8.87, 30.8, 2.96),
    ("W8X13", 13, 11.4, 39.6, 3.84),
    ("W8X18", 18, 17.0, 61.9, 5.26),
    ("W8X24", 24, 23.1, 82.7, 7.08),
    ("W8X31", 31, 30.4, 110, 9.13),
    ("W10X22", 22, 26.0, 118, 6.49),
    ("W10X26", 26, 31.3, 144, 7.61),
    ("W10X33", 33, 38.8, 171, 9.71),
    ("W10X45", 45, 54.9, 248, 13.3),
    ("W10X54", 54, 66.6, 303, 15.8),
    ("W12X26", 26, 33.4, 204, 7.65),
    ("W12X35", 35, 51.2, 285, 10.3),
    ("W12X40", 40, 57.5, 310, 11.7),
    ("W12X50", 50, 71.9, 391, 14.6),
    ("W12X65", 65, 96.8, 533, 19.1),
    ("W12X79", 79, 119, 662, 23.2),
    ("W14X48", 48, 78.4, 484, 14.1),
    ("W14X61", 61, 102, 640, 17.9),
    ("W14X82", 82, 139, 881, 24.0),
    ("W14X90", 90, 157, 999, 26.5),
    ("W14X109", 109, 192, 1240, 32.0),
    ("W16X50", 50, 92.0, 659, 14.7),
    ("W16X67", 67, 130, 954, 19.7),
    ("W18X40", 40, 78.4, 612, 11.8),
    ("W18X55", 55, 112, 890, 16.2),
    ("W18X71", 71, 146, 1170, 20.8),
    ("W21X50", 50, 110, 984, 14.7),
    ("W21X62", 62, 144, 1330, 18.3),
    ("W21X83", 83, 196, 1830, 24.3),
    ("W24X62", 62, 153, 1550, 18.2),
    ("W24X76", 76, 200, 2100, 22.4),
    ("W24X94", 94, 254, 2700, 27.7),
]


@dataclass
class _SectionProps:
    name: str
    weight_kgm: float
    Zx_mm3: float   # plastic section modulus in mm³
    Ix_mm4: float    # moment of inertia in mm⁴
    A_mm2: float     # cross-section area in mm²


_CATALOG: list[_SectionProps] = []
for _n, _w, _zx, _ix, _a in _W_SHAPES:
    _CATALOG.append(_SectionProps(
        name=_n,
        weight_kgm=_w * 1.488,
        Zx_mm3=_zx * 16387.064,
        Ix_mm4=_ix * 416231.426,
        A_mm2=_a * 645.16,
    ))
_CATALOG.sort(key=lambda s: s.weight_kgm)


def _select_section(
    required_Zx_mm3: float,
    min_depth_mm: float = 0.0,
) -> _SectionProps:
    """Find lightest W-shape with Zx >= required and depth >= min_depth."""
    for s in _CATALOG:
        depth_mm = float(s.name.split("X")[0].replace("W", "")) * 25.4
        if s.Zx_mm3 >= required_Zx_mm3 and depth_mm >= min_depth_mm:
            return s
    return _CATALOG[-1]


def optimize_sections(spec: BuildingSpec) -> dict[str, str]:
    """Compute load-aware initial sections targeting UR ≈ 0.9.

    Uses simplified portal-method demand estimates and LRFD factored loads
    to select the lightest W-shape where capacity/demand ≈ 1/0.9.
    """
    Fy = spec.fyld_mpa  # MPa
    target_ur = 0.90
    phi_b = 0.90  # LRFD flexure resistance factor

    W = spec.span_width_m * 1000   # mm
    H = spec.eave_height_m * 1000  # mm
    L_bay = spec.bay_length_m * 1000  # mm

    w_dead = spec.dead_load_kn_m   # kN/m on rafters
    w_live = spec.live_load_kn_m
    w_u = 1.2 * w_dead + 1.6 * w_live  # LRFD factored UDL (kN/m)

    # Rafter: simply-supported span approximation for max moment
    rafter_span = W / 2.0  # half-span rafter in mm
    M_rafter = w_u * (rafter_span / 1000) ** 2 / 8.0  # kN·m
    M_rafter_Nmm = M_rafter * 1e6  # N·mm

    Zx_req_rafter = M_rafter_Nmm / (phi_b * Fy * target_ur)
    rafter = _select_section(Zx_req_rafter, min_depth_mm=300)

    # Column: portal frame moment ≈ w_u * L² / (2 * (1 + 2*K))
    # K = (I_beam/L_beam) / (I_col/H_col); assume K ≈ 1.5 for initial
    K = 1.5
    M_col = w_u * (W / 2000) ** 2 / (2 * (1 + 2 * K))  # kN·m
    # Add wind lateral: M_wind = 0.5 * wind_p * H² / 8 * bay_spacing
    M_wind = 0.5 * spec.wind_pressure_kn_m2 * (H / 1000) ** 2 / 8 * (L_bay / 1000)
    M_col_total = M_col + 0.5 * M_wind  # approximate combined
    M_col_Nmm = M_col_total * 1e6

    Zx_req_col = M_col_Nmm / (phi_b * Fy * target_ur)
    column = _select_section(Zx_req_col, min_depth_mm=250)

    # Brace: typically light, use minimum practical size
    brace = _select_section(50000, min_depth_mm=150)

    # Secondary (purlins/girts): span = bay spacing, light tributary load
    purlin_w = max(w_dead, w_live) * max(1.0, spec.purlin_spacing_m)
    M_purlin = purlin_w * (L_bay / 1000) ** 2 / 8.0
    Zx_purlin = M_purlin * 1e6 / (phi_b * Fy * target_ur)
    purlin = _select_section(max(Zx_purlin, 30000))

    return {
        "col_section": column.name,
        "rafter_section": rafter.name,
        "brace_section": brace.name,
        "purlin_section": purlin.name,
        "girt_section": purlin.name,
    }
