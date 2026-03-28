"""FEA verification using PyNite — builds a simplified 2D portal frame,
optimizes sections iteratively, and checks UR + deflection."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from staad_generator.spec import BuildingSpec

# (A m², Iy m⁴, Iz m⁴, J m⁴, d m, kg/m)
_AISC_W: list[tuple[str, float, float, float, float, float, float]] = [
    ("W6X9",   1.71e-3, 1.64e-6, 8.84e-6,  2.24e-8, 0.150, 13.4),
    ("W8X18",  3.42e-3, 3.43e-6, 2.98e-5,  8.17e-8, 0.207, 26.8),
    ("W10X26", 4.96e-3, 5.50e-6, 5.62e-5,  1.43e-7, 0.262, 38.7),
    ("W10X33", 6.26e-3, 1.72e-5, 5.69e-5,  2.55e-7, 0.247, 49.1),
    ("W12X26", 4.96e-3, 5.14e-6, 8.52e-5,  9.55e-8, 0.310, 38.7),
    ("W12X35", 6.65e-3, 7.53e-6, 1.18e-4,  2.16e-7, 0.318, 52.1),
    ("W12X40", 7.61e-3, 1.59e-5, 1.21e-4,  2.87e-7, 0.304, 59.5),
    ("W14X30", 5.68e-3, 6.31e-6, 1.23e-4,  1.23e-7, 0.352, 44.6),
    ("W14X48", 9.10e-3, 1.62e-5, 2.01e-4,  3.47e-7, 0.351, 71.4),
    ("W14X68", 1.29e-2, 3.01e-5, 3.01e-4,  6.27e-7, 0.357, 101.2),
    ("W14X90", 1.71e-2, 4.16e-5, 4.16e-4,  1.14e-6, 0.356, 133.9),
    ("W18X40", 7.61e-3, 5.06e-6, 2.89e-4,  1.93e-7, 0.455, 59.5),
    ("W18X55", 1.05e-2, 1.14e-5, 4.10e-4,  3.52e-7, 0.460, 81.9),
    ("W18X76", 1.44e-2, 2.50e-5, 5.96e-4,  7.70e-7, 0.459, 113.1),
    ("W21X50", 9.48e-3, 7.87e-6, 4.93e-4,  2.50e-7, 0.529, 74.4),
    ("W21X68", 1.29e-2, 1.55e-5, 6.89e-4,  4.87e-7, 0.537, 101.2),
    ("W21X83", 1.57e-2, 2.31e-5, 8.64e-4,  7.42e-7, 0.544, 123.5),
    ("W24X62", 1.18e-2, 1.05e-5, 7.53e-4,  3.14e-7, 0.603, 92.2),
    ("W24X84", 1.59e-2, 1.96e-5, 1.04e-3,  6.69e-7, 0.612, 125.0),
    ("W24X104",1.97e-2, 2.89e-5, 1.33e-3,  1.07e-6, 0.612, 154.8),
    ("W27X84", 1.59e-2, 1.47e-5, 1.14e-3,  5.04e-7, 0.678, 125.0),
    ("W27X102",1.94e-2, 2.16e-5, 1.42e-3,  7.70e-7, 0.681, 151.8),
    ("W30X90", 1.71e-2, 1.17e-5, 1.40e-3,  4.34e-7, 0.753, 133.9),
    ("W30X108",2.05e-2, 1.68e-5, 1.71e-3,  6.77e-7, 0.757, 160.7),
    ("W30X132",2.51e-2, 2.47e-5, 2.16e-3,  1.09e-6, 0.760, 196.4),
    ("W33X118",2.24e-2, 1.65e-5, 2.16e-3,  6.98e-7, 0.835, 175.6),
    ("W33X152",2.89e-2, 2.73e-5, 2.87e-3,  1.25e-6, 0.840, 226.2),
    ("W36X135",2.57e-2, 1.79e-5, 2.78e-3,  7.71e-7, 0.912, 200.8),
    ("W36X160",3.04e-2, 2.60e-5, 3.38e-3,  1.21e-6, 0.915, 238.1),
    ("W36X194",3.68e-2, 3.62e-5, 4.21e-3,  1.80e-6, 0.922, 288.7),
    ("W36X232",4.39e-2, 4.94e-5, 5.17e-3,  2.73e-6, 0.930, 345.2),
    ("W36X302",5.74e-2, 7.91e-5, 7.07e-3,  5.21e-6, 0.943, 449.5),
    # Welded plate girders for wide-span PEB (custom depths)
    ("WPG900", 7.20e-2, 1.00e-4, 1.30e-2,  8.00e-6, 0.900, 565.0),
    ("WPG1200",9.60e-2, 1.50e-4, 2.80e-2,  1.20e-5, 1.200, 753.0),
    ("WPG1500",1.20e-1, 2.00e-4, 5.60e-2,  1.80e-5, 1.500, 942.0),
]

# Sort by Iz ascending for quick section selection
_AISC_W.sort(key=lambda r: r[3])


@dataclass
class FEAResult:
    max_ur: float
    max_ur_member: str
    max_defl_mm: float
    max_defl_member: str
    defl_limit_mm: float
    defl_pass: bool
    ur_pass: bool
    n_members_checked: int
    optimized_col_section: str
    optimized_raf_section: str
    summary: str


def _pick_section(required_Iz: float) -> tuple[str, float, float, float, float, float]:
    """Return lightest AISC W-section whose Iz ≥ required_Iz."""
    for name, A, Iy, Iz, J, d, kgm in _AISC_W:
        if Iz >= required_Iz:
            return name, A, Iy, Iz, J, d
    last = _AISC_W[-1]
    return last[0], last[1], last[2], last[3], last[4], last[5]


def _sec_props(name: str) -> tuple[float, float, float, float, float]:
    for n, A, Iy, Iz, J, d, kgm in _AISC_W:
        if n == name:
            return A, Iy, Iz, J, d
    return _AISC_W[6][1], _AISC_W[6][2], _AISC_W[6][3], _AISC_W[6][4], _AISC_W[6][5]


def _run_frame(
    spec: BuildingSpec,
    col_sec: str,
    raf_sec: str,
) -> tuple[float, str, float, str, float, tuple[float, float, float, float]]:
    """Run PyNite analysis, return (max_ur, ur_name, max_defl_mm, defl_name, defl_limit_mm, (A_c, Iz_c, A_r, Iz_r))."""
    from Pynite import FEModel3D

    W = spec.span_width_m
    H = spec.eave_height_m
    w2 = W / 2.0
    rise = spec.roof_slope_ratio * w2
    hr = H + rise
    E = spec.e_modulus_mpa * 1e3
    G = E / (2.0 * (1.0 + spec.poisson))
    Fy = spec.fyld_mpa * 1e3

    mdl = FEModel3D()
    mdl.add_node("N1", 0, 0, 0)
    mdl.add_node("N2", 0, H, 0)
    mdl.add_node("N3", w2, hr, 0)
    mdl.add_node("N4", W, H, 0)
    mdl.add_node("N5", W, 0, 0)
    mdl.def_support("N1", True, True, True, True, True, True)
    mdl.def_support("N5", True, True, True, True, True, True)
    mdl.add_material("Steel", E, G, spec.poisson, spec.density_kn_m3)

    A_c, Iy_c, Iz_c, J_c, d_c = _sec_props(col_sec)
    A_r, Iy_r, Iz_r, J_r, d_r = _sec_props(raf_sec)
    mdl.add_section("COL", A_c, Iy_c, Iz_c, J_c)
    mdl.add_section("RAF", A_r, Iy_r, Iz_r, J_r)

    mdl.add_member("COL_L", "N1", "N2", "Steel", "COL")
    mdl.add_member("RAF_L", "N2", "N3", "Steel", "RAF")
    mdl.add_member("RAF_R", "N3", "N4", "Steel", "RAF")
    mdl.add_member("COL_R", "N4", "N5", "Steel", "COL")

    trib = spec.bay_length_m
    dl = (spec.dead_load_kn_m + spec.collateral_line_kn_m) * trib
    ll = spec.live_load_kn_m * trib

    mdl.add_load_combo("ULT", {"D": 1.2, "L": 1.6})
    mdl.add_load_combo("SLS", {"D": 1.0, "L": 1.0})

    mdl.add_member_dist_load("RAF_L", "FY", -dl, -dl, 0, None, "D")
    mdl.add_member_dist_load("RAF_R", "FY", -dl, -dl, 0, None, "D")
    mdl.add_member_dist_load("RAF_L", "FY", -ll, -ll, 0, None, "L")
    mdl.add_member_dist_load("RAF_R", "FY", -ll, -ll, 0, None, "L")

    mdl.analyze()

    info = [
        ("COL_L", A_c, Iz_c, d_c, H, spec.defl_frame_lateral),
        ("RAF_L", A_r, Iz_r, d_r, math.hypot(w2, rise), spec.defl_frame_vertical),
        ("RAF_R", A_r, Iz_r, d_r, math.hypot(w2, rise), spec.defl_frame_vertical),
        ("COL_R", A_c, Iz_c, d_c, H, spec.defl_frame_lateral),
    ]

    max_ur = 0.0
    max_ur_name = ""
    max_defl = 0.0
    max_defl_name = ""
    defl_limit = 0.0

    for name, A, Iz, d, L, dff in info:
        mem = mdl.members[name]
        M = max(abs(mem.max_moment("Mz", "ULT")), abs(mem.min_moment("Mz", "ULT")))
        P = max(abs(mem.max_axial("ULT")), abs(mem.min_axial("ULT")))

        Sx = Iz / (d / 2.0) if d > 0 else 1e-4
        Zx = 1.15 * Sx
        Mp = Fy * Zx
        Py = Fy * A

        ur = M / max(Mp, 1.0) + P / max(Py, 1.0)
        if ur > max_ur:
            max_ur = ur
            max_ur_name = name

        d_abs = max(abs(mem.max_deflection("dy", "SLS")), abs(mem.min_deflection("dy", "SLS")))
        d_mm = d_abs * 1000.0
        lim = (L / dff) * 1000.0 if dff > 0 else 999.0
        if d_mm > max_defl:
            max_defl = d_mm
            max_defl_name = name
            defl_limit = lim

    return max_ur, max_ur_name, max_defl, max_defl_name, defl_limit, (A_c, Iz_c, A_r, Iz_r)


def verify_portal_frame(spec: BuildingSpec, max_iter: int = 8) -> FEAResult:
    """Build + optimise a 2D portal frame. Returns FEA-verified UR and deflection."""
    try:
        from Pynite import FEModel3D  # noqa: F401
    except ImportError:
        return FEAResult(
            max_ur=0.0, max_ur_member="N/A",
            max_defl_mm=0.0, max_defl_member="N/A",
            defl_limit_mm=0.0, defl_pass=False, ur_pass=False,
            n_members_checked=0,
            optimized_col_section="N/A",
            optimized_raf_section="N/A",
            summary="PyNite not installed — FEA verification skipped.",
        )

    col_sec = spec.col_section
    raf_sec = spec.rafter_section
    Fy = spec.fyld_mpa * 1e3

    for iteration in range(max_iter):
        try:
            ur, ur_name, defl_mm, defl_name, defl_lim, (A_c, Iz_c, A_r, Iz_r) = _run_frame(spec, col_sec, raf_sec)
        except Exception as exc:
            return FEAResult(
                max_ur=0.0, max_ur_member="N/A",
                max_defl_mm=0.0, max_defl_member="N/A",
                defl_limit_mm=0.0, defl_pass=False, ur_pass=False,
                n_members_checked=0,
                optimized_col_section=col_sec,
                optimized_raf_section=raf_sec,
                summary=f"FEA failed at iteration {iteration}: {exc}",
            )

        if ur <= 1.0 and (defl_mm <= defl_lim or defl_lim <= 0):
            break

        # Scale up the section whose UR is highest
        scale = max(ur, defl_mm / max(defl_lim, 1.0), 1.1)
        if "COL" in ur_name:
            new_Iz = Iz_c * scale * 1.15
            col_sec, *_ = _pick_section(new_Iz)
        else:
            new_Iz = Iz_r * scale * 1.15
            raf_sec, *_ = _pick_section(new_Iz)

        # Also check deflection — may need rafters bigger
        if defl_mm > defl_lim > 0:
            defl_scale = (defl_mm / defl_lim) * 1.15
            new_Iz = Iz_r * defl_scale
            cand, *_ = _pick_section(new_Iz)
            if _sec_props(cand)[2] > _sec_props(raf_sec)[2]:
                raf_sec = cand

    ur_pass = ur <= 1.0
    defl_pass = defl_mm <= defl_lim if defl_lim > 0 else True

    lines = [
        "FEA Verification (PyNite, single-bay 2D portal, iterative optimization):",
        f"  Optimized col: {col_sec}, rafter: {raf_sec}",
        f"  Max UR = {ur:.3f} ({ur_name}) -> {'PASS' if ur_pass else 'FAIL (needs larger sections)'}",
        f"  Max Deflection = {defl_mm:.1f} mm ({defl_name}), "
        f"limit = {defl_lim:.1f} mm -> {'PASS' if defl_pass else 'FAIL'}",
        f"  Iterations: {iteration + 1}",
    ]

    return FEAResult(
        max_ur=round(ur, 4),
        max_ur_member=ur_name,
        max_defl_mm=round(defl_mm, 2),
        max_defl_member=defl_name,
        defl_limit_mm=round(defl_lim, 2),
        defl_pass=defl_pass,
        ur_pass=ur_pass,
        n_members_checked=4,
        optimized_col_section=col_sec,
        optimized_raf_section=raf_sec,
        summary="\n".join(lines),
    )
