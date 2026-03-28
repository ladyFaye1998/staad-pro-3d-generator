"""Extract building parameters from heterogeneous competition JSON."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


@dataclass
class BuildingSpec:
    """PEB 3D model: primary portal + secondary + braces + design loads."""

    name: str = "model"
    n_bays: int = 4
    bay_length_m: float = 6.0
    bay_spacings: list[float] | None = None
    span_width_m: float = 24.0
    eave_height_m: float = 8.0
    roof_slope_ratio: float = 0.1
    col_section: str = "W12X40"
    rafter_section: str = "W14X48"
    brace_section: str = "W8X18"
    purlin_section: str = "W6X9"
    girt_section: str = "W6X9"
    e_modulus_mpa: float = 205000.0
    poisson: float = 0.3
    density_kn_m3: float = 77.0
    dead_load_kn_m: float = 2.0
    live_load_kn_m: float = 1.5
    wind_pressure_kn_m2: float = 0.5
    collateral_line_kn_m: float = 0.0
    seismic_ah: float = 0.0
    purlin_spacing_m: float = 1.65
    enable_roof_x_brace: bool = True
    enable_wall_x_brace: bool = True
    enable_purlins: bool = True
    enable_girts: bool = True
    enable_endwall_cols: bool = True
    design_code: str = "AISC UNIFIED 2010"
    fyld_mpa: float = 345.0
    defl_frame_vertical: float = 240.0
    defl_frame_lateral: float = 180.0
    defl_purlin: float = 180.0
    crane_load_kn: float = 0.0
    crane_bracket_height_m: float = 0.0
    crane_beam_section: str = "W14X30"
    enable_portal_brace: bool = True
    enable_tapered: bool = True
    # Accessories
    enable_canopy: bool = True
    canopy_width_m: float = 2.0
    canopy_section: str = "W8X18"
    opening_width_m: float = 4.0
    opening_height_m: float = 4.5
    opening_bay_index: int = 1
    enable_framed_opening: bool = True
    jack_beam_section: str = "W8X18"
    enable_cage_ladder: bool = True
    cage_ladder_bay_index: int = -1
    # Mezzanine floor
    mezzanine_elevation_m: float = 0.0
    mezzanine_width_m: float = 0.0
    mezzanine_length_m: float = 0.0
    mezzanine_live_load_kn_m2: float = 5.0
    mezzanine_slab_kn_m2: float = 2.0
    mezz_beam_section: str = "W18X40"
    mezz_col_section: str = "W10X33"
    joist_section: str = "W6X9"
    joist_spacing_m: float = 1.5


def _to_float(x: Any, default: float) -> float:
    if x is None:
        return default
    if isinstance(x, (int, float)) and not isinstance(x, bool):
        if math.isnan(float(x)):
            return default
        return float(x)
    if isinstance(x, str):
        s = re.sub(r"[^\d.\-eE+]", "", x.replace(",", ""))
        if not s:
            return default
        try:
            return float(s)
        except ValueError:
            return default
    return default


def _to_int(x: Any, default: int) -> int:
    f = _to_float(x, float(default))
    return int(round(f)) if not math.isnan(f) else default


def _flatten(obj: Any, out: dict[str, Any], prefix: str = "") -> None:
    if isinstance(obj, Mapping):
        for k, v in obj.items():
            key = f"{prefix}.{k}" if prefix else str(k)
            if isinstance(v, Mapping):
                _flatten(v, out, key)
            elif isinstance(v, list) and v and isinstance(v[0], Mapping):
                for i, item in enumerate(v):
                    _flatten(item, out, f"{key}[{i}]")
            else:
                out[key.lower()] = v
                out[str(k).lower()] = v
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            _flatten(item, out, f"{prefix}[{i}]" if prefix else f"[{i}]")


def _first(flat: dict[str, Any], *names: str) -> Any:
    for n in names:
        v = flat.get(n.lower())
        if v is not None:
            return v
    for k, v in flat.items():
        kl = k.lower()
        for n in names:
            if n.lower() in kl:
                return v
    return None


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def format_spec_summary(
    spec: BuildingSpec,
    *,
    n_joints: int | None = None,
    n_members: int | None = None,
) -> str:
    """One block of text for CLI --verbose / logs."""
    L = spec.n_bays * spec.bay_length_m
    parts = [
        f"{spec.name}: plan ~ {L:.2f} x {spec.span_width_m:.2f} m  "
        f"({spec.n_bays} bays @ {spec.bay_length_m:.3f} m), "
        f"H_eave={spec.eave_height_m:.2f} m, slope={spec.roof_slope_ratio:.4f}",
        f"  steel: col {spec.col_section}  raf {spec.rafter_section}  "
        f"brace {spec.brace_section}  purlin {spec.purlin_section}",
        f"  loads: w_dead_line={spec.dead_load_kn_m:.4g} w_live_line={spec.live_load_kn_m:.4g} "
        f"kN/m  wind_p={spec.wind_pressure_kn_m2:.4g} kN/m2  "
        f"coll_line={spec.collateral_line_kn_m:.4g}  a_h={spec.seismic_ah:.4g}",
        f"  flags: purlins={spec.enable_purlins} girts={spec.enable_girts} "
        f"roof_x_brace={spec.enable_roof_x_brace} wall_x_brace={spec.enable_wall_x_brace} "
        f"endwall_cols={spec.enable_endwall_cols}",
        f"  design: {spec.design_code}  Fy={spec.fyld_mpa:.0f} MPa  "
        f"defl V/L={spec.defl_frame_vertical:.0f} H/L={spec.defl_frame_lateral:.0f} pur={spec.defl_purlin:.0f}",
    ]
    if spec.mezzanine_elevation_m > 0:
        parts.append(
            f"  mezzanine: {spec.mezzanine_width_m:.1f} x {spec.mezzanine_length_m:.1f} m "
            f"@ {spec.mezzanine_elevation_m:.1f} m  "
            f"LL={spec.mezzanine_live_load_kn_m2:.1f} DL={spec.mezzanine_slab_kn_m2:.1f} kN/m²"
        )
    if n_joints is not None and n_members is not None:
        parts.append(f"  mesh: {n_joints} joints, {n_members} members")
    return "\n".join(parts)


def spec_from_dict(data: dict[str, Any], name: str = "model") -> BuildingSpec:
    flat: dict[str, Any] = {}
    _flatten(data, flat)

    length = _to_float(
        _first(flat, "building_length", "length", "length_m", "overall_length", "l", "clear_length"),
        24.0,
    )
    width = _to_float(
        _first(flat, "building_width", "width", "span", "clear_span", "clear_width", "w"),
        24.0,
    )
    eave = _to_float(
        _first(flat, "eave_height", "height", "height_to_eave", "sidewall_height", "h", "eave"),
        8.0,
    )
    slope_deg = _to_float(_first(flat, "roof_slope", "roof_angle", "slope", "pitch"), float("nan"))
    slope_ratio = _to_float(_first(flat, "roof_slope_ratio", "rise_run"), float("nan"))
    if not math.isnan(slope_deg):
        slope_ratio = math.tan(math.radians(slope_deg))
    elif math.isnan(slope_ratio):
        slope_ratio = 0.1

    bays = _to_int(_first(flat, "n_bays", "num_bays", "bays", "number_of_bays"), 0)
    bay_len = _to_float(_first(flat, "bay_length", "bay_spacing", "bay_width"), float("nan"))
    if bays <= 0 and not math.isnan(bay_len) and bay_len > 0.1:
        bays = max(1, int(round(length / bay_len)))
    if bays <= 0:
        bays = max(1, int(round(length / 6.0)))
    bay_len = length / bays if bays else 6.0

    col = _first(flat, "column_section", "col_section", "interior_column", "section_column")
    raf = _first(flat, "rafter_section", "beam_section", "section_rafter")
    brc = _first(flat, "brace_section", "girt_section")
    pur = _first(flat, "purlin_section")
    girt = _first(flat, "girt_section")

    e_mpa = _to_float(_first(flat, "modulus_of_elasticity", "youngs_modulus", "elastic_modulus"), 205000.0)
    nu = _to_float(_first(flat, "poisson", "poissons_ratio"), 0.3)
    dens = _to_float(_first(flat, "density", "steel_density"), 77.0)

    dl = _to_float(_first(flat, "dead_load", "dl", "roof_dead_load"), 2.0)
    ll = _to_float(_first(flat, "live_load", "ll", "roof_live_load"), 1.5)
    wind = _to_float(_first(flat, "wind_pressure", "wind_load", "wind"), 0.5)
    coll = _to_float(_first(flat, "collateral_line", "collateral_kn_m"), 0.0)
    ah = _to_float(_first(flat, "seismic_ah", "ah"), 0.0)
    ps = _to_float(_first(flat, "purlin_spacing_m"), 1.65)

    crane = _to_float(_first(flat, "crane_load", "crane_capacity", "crane_load_kn", "hoist_load"), 0.0)
    crane_h = _to_float(_first(flat, "crane_bracket_height", "crane_height", "bracket_height"), 0.0)
    if crane > 0 and crane_h <= 0:
        crane_h = round(max(2.0, eave) * 0.75, 2)
    crane_sec = _clean_section(_first(flat, "crane_beam_section")) or "W14X30"

    return BuildingSpec(
        name=name,
        n_bays=max(1, bays),
        bay_length_m=max(0.5, bay_len),
        span_width_m=max(3.0, width),
        eave_height_m=max(2.0, eave),
        roof_slope_ratio=max(0.02, min(0.5, slope_ratio)),
        col_section=_clean_section(col) or "W12X40",
        rafter_section=_clean_section(raf) or "W14X48",
        brace_section=_clean_section(brc) or "W8X18",
        purlin_section=_clean_section(pur) or "W6X9",
        girt_section=_clean_section(girt) or "W6X9",
        e_modulus_mpa=e_mpa,
        poisson=nu,
        density_kn_m3=dens,
        dead_load_kn_m=max(0.0, dl),
        live_load_kn_m=max(0.0, ll),
        wind_pressure_kn_m2=max(0.0, wind),
        collateral_line_kn_m=max(0.0, coll),
        seismic_ah=max(0.0, ah),
        purlin_spacing_m=max(0.8, min(3.5, ps)),
        crane_load_kn=max(0.0, crane),
        crane_bracket_height_m=max(0.0, crane_h),
        crane_beam_section=crane_sec,
        enable_roof_x_brace=_to_boolish(_first(flat, "enable_roof_x_brace"), True),
        enable_wall_x_brace=_to_boolish(_first(flat, "enable_wall_x_brace"), True),
        enable_purlins=_to_boolish(_first(flat, "enable_purlins"), True),
        enable_girts=_to_boolish(_first(flat, "enable_girts"), True),
        enable_endwall_cols=_to_boolish(_first(flat, "enable_endwall_cols"), True),
        enable_portal_brace=_to_boolish(_first(flat, "enable_portal_brace"), True),
        enable_tapered=_to_boolish(_first(flat, "enable_tapered"), True),
    )


def _to_boolish(x: Any, default: bool) -> bool:
    if x is None:
        return default
    if isinstance(x, bool):
        return x
    s = str(x).strip().lower()
    if s in ("0", "false", "no", "off"):
        return False
    if s in ("1", "true", "yes", "on"):
        return True
    return default


def _clean_section(x: Any) -> str | None:
    if x is None:
        return None
    s = str(x).strip().upper().replace(" ", "")
    if not s or s in ("NONE", "NULL", "TBD"):
        return None
    s = re.sub(r"[^A-Z0-9X]", "", s)
    return s or None


def spec_from_json_path(path: Path) -> BuildingSpec:
    data = load_json(path)
    from staad_generator.qrf import is_qrf_payload, spec_from_qrf

    if is_qrf_payload(data):
        return spec_from_qrf(data, name=path.stem)
    return spec_from_dict(data, name=path.stem)
