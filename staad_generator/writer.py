"""Emit STAAD command file (.std) from BuildingSpec — primary + secondary + combos."""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from pathlib import Path

from staad_generator.geometry import FrameModel, build_frame
from staad_generator.spec import BuildingSpec, format_spec_summary, spec_from_dict, spec_from_json_path
from staad_generator.validate import validate_frame_or_raise

logger = logging.getLogger(__name__)

LARGE_MODEL_JOINT_WARN = 2000
_MEMBER_LOAD_MAX_IDS_PER_LINE = 18

_W_SECTION_DIMS: dict[str, tuple[float, float, float, float]] = {
    "W6X9":   (0.150, 0.007, 0.100, 0.006),
    "W8X10":  (0.200, 0.008, 0.100, 0.006),
    "W8X18":  (0.207, 0.010, 0.133, 0.006),
    "W10X22": (0.260, 0.010, 0.147, 0.006),
    "W10X26": (0.262, 0.011, 0.147, 0.007),
    "W10X33": (0.247, 0.013, 0.202, 0.007),
    "W12X26": (0.310, 0.010, 0.165, 0.006),
    "W12X35": (0.318, 0.013, 0.167, 0.008),
    "W12X40": (0.304, 0.013, 0.203, 0.008),
    "W14X30": (0.352, 0.010, 0.171, 0.007),
    "W14X48": (0.351, 0.013, 0.204, 0.008),
    "W18X40": (0.455, 0.013, 0.153, 0.008),
}


def _tapered_dims(section: str, *, bottom_factor: float = 1.8, top_factor: float = 1.0) -> str:
    """Generate STAAD TAPERED property string: depth_i tf bf tw depth_j tf bf tw."""
    d, tf, bf, tw = _W_SECTION_DIMS.get(section, (0.300, 0.012, 0.200, 0.008))
    d_bot = round(d * bottom_factor, 4)
    d_top = round(d * top_factor, 4)
    return (
        f"{d_bot} {tf} {bf} {tw} "
        f"{d_top} {tf} {bf} {tw}"
    )


def _member_uni_lines(
    member_ids: list[int],
    axis: str,
    load_value: float,
    *,
    max_ids_per_line: int = _MEMBER_LOAD_MAX_IDS_PER_LINE,
) -> list[str]:
    """Chunk ``UNI GX|GY|GZ`` lines so each stays short for STAAD / editors."""
    ids = sorted(set(member_ids))
    if not ids:
        return []
    out: list[str] = []
    fs = _fmt_load(load_value)
    for i in range(0, len(ids), max_ids_per_line):
        chunk = ids[i : i + max_ids_per_line]
        out.append(f"{_runs_str(chunk)} UNI {axis} {fs}")
    return out


def _sanitize_job_title(name: str, max_len: int = 48) -> str:
    s = re.sub(r"[^\w\-. ]+", "", str(name).strip()) or "model"
    s = re.sub(r"\s+", " ", s)
    return s[:max_len].strip()


def _fmt_dim(x: float) -> str:
    return f"{round(float(x), 4):.4f}".rstrip("0").rstrip(".")


def _fmt_load(x: float) -> str:
    x = float(x)
    if abs(x) < 1e-12:
        return "0"
    if abs(x) >= 1000:
        return f"{x:.6g}"
    s = f"{x:.6f}".rstrip("0").rstrip(".")
    return s if s else "0"


def _joint_load_fx_lines(joint_ids: list[int], fx: float, max_ids_per_line: int = 28) -> list[str]:
    """Avoid very long JOINT LOAD lines (STAAD / editor limits)."""
    ids = sorted(set(joint_ids))
    if not ids:
        return []
    out: list[str] = []
    fs = _fmt_load(fx)
    for i in range(0, len(ids), max_ids_per_line):
        chunk = ids[i : i + max_ids_per_line]
        out.append(f"{_runs_str(chunk)} FX {fs}")
    return out


def _fmt_coord_line(joints: dict[int, tuple[float, float, float]], chunk: int = 4) -> list[str]:
    items = sorted(joints.items(), key=lambda kv: kv[0])
    lines_out: list[str] = []
    buf: list[str] = []
    for jid, (x, y, z) in items:
        buf.append(f"{jid} {_fmt_dim(x)} {_fmt_dim(y)} {_fmt_dim(z)}")
        if len(buf) >= chunk:
            lines_out.append(" ".join(buf) + " ")
            buf = []
    if buf:
        lines_out.append(" ".join(buf) + " ")
    return lines_out


def _member_lines(members: list[tuple[int, int, int, str]], chunk: int = 6) -> list[str]:
    lines_out: list[str] = []
    buf: list[str] = []
    for mid, n1, n2, _ in members:
        buf.append(f"{mid} {n1} {n2}")
        if len(buf) >= chunk:
            lines_out.append("; ".join(buf) + " ;")
            buf = []
    if buf:
        lines_out.append("; ".join(buf) + " ;")
    return lines_out


def _ids_by_kind(members: list[tuple[int, int, int, str]]) -> dict[str, list[int]]:
    d: dict[str, list[int]] = defaultdict(list)
    for mid, _, _, k in members:
        d[k].append(mid)
    return d


def _runs_str(ids: list[int]) -> str:
    ids = sorted(set(ids))
    if not ids:
        return ""
    parts: list[str] = []
    i = 0
    n = len(ids)
    while i < n:
        start = end = ids[i]
        j = i + 1
        while j < n and ids[j] == end + 1:
            end = ids[j]
            j += 1
        parts.append(str(start) if start == end else f"{start} TO {end}")
        i = j
    return " ".join(parts)


def _eave_joint_ids(fm: FrameModel, spec: BuildingSpec) -> list[int]:
    H = spec.eave_height_m
    W = spec.span_width_m
    out: list[int] = []
    for jid, (x, y, z) in fm.joint_coords.items():
        if abs(y - H) > 0.05:
            continue
        if z < 0.05 or abs(z - W) < 0.05:
            out.append(jid)
    return sorted(out)


def build_std_text(spec: BuildingSpec, model: FrameModel | None = None, *, engineer_date: str | None = None) -> str:
    fm = model if model is not None else build_frame(spec)
    validate_frame_or_raise(fm)
    nj = len(fm.joint_coords)
    if nj > LARGE_MODEL_JOINT_WARN:
        logger.warning(
            "Large model (%d joints); .std may be heavy for editors and STAAD.",
            nj,
        )

    by_kind = _ids_by_kind(fm.members)

    col_ids = by_kind.get("column", [])
    raf_ids = by_kind.get("rafter", [])
    haunch_ids = by_kind.get("haunch", [])
    eave_ids = by_kind.get("eave_long", [])
    ridge_ids = by_kind.get("ridge_long", [])
    purlin_ids = by_kind.get("purlin", [])
    girt_ids = by_kind.get("girt", [])
    roof_brace_ids = by_kind.get("roof_brace", [])
    wall_brace_ids = by_kind.get("wall_brace", [])
    endwall_col_ids = by_kind.get("endwall_col", [])
    mezz_col_ids = by_kind.get("mezz_col", [])
    mezz_beam_ids = by_kind.get("mezz_beam", [])
    mezz_long_ids = by_kind.get("mezz_long", [])
    crane_beam_ids = by_kind.get("crane_beam", [])
    portal_brace_ids = by_kind.get("portal_brace", [])
    canopy_ids = by_kind.get("canopy", [])
    opening_jamb_ids = by_kind.get("opening_jamb", [])
    jack_beam_ids = by_kind.get("jack_beam", [])
    joist_ids = by_kind.get("joist", [])
    cage_ladder_ids = by_kind.get("cage_ladder", [])
    has_mezz = bool(mezz_col_ids or mezz_beam_ids)
    has_crane_beams = bool(crane_beam_ids)

    job = _sanitize_job_title(spec.name)
    nm = len(fm.members)
    e_knm2 = spec.e_modulus_mpa * 1e3
    fyld_kn_m2 = spec.fyld_mpa * 1e3

    # Collect member groups for later reference
    all_mezz = sorted(set(mezz_col_ids + mezz_beam_ids + mezz_long_ids))
    all_primary = sorted(set(col_ids + raf_ids + haunch_ids + eave_ids + ridge_ids + endwall_col_ids + mezz_col_ids + crane_beam_ids + opening_jamb_ids + jack_beam_ids + canopy_ids + cage_ladder_ids))
    all_secondary = sorted(set(purlin_ids + girt_ids + mezz_beam_ids + mezz_long_ids + joist_ids))
    all_brace = sorted(set(roof_brace_ids + wall_brace_ids + portal_brace_ids))
    roof_m = sorted(set(raf_ids + haunch_ids + ridge_ids))
    all_ids = sorted(set(m[0] for m in fm.members))

    # ===================================================================
    # HEADER
    # ===================================================================
    from datetime import date as _date

    _today = engineer_date or _date.today().strftime("%d-%b-%Y")
    lines: list[str] = [
        "STAAD SPACE",
        "START JOB INFORMATION",
        f"ENGINEER DATE {_today}",
        f"JOB NAME {job}",
        "END JOB INFORMATION",
        "INPUT WIDTH 79",
        "",
        f"* ===================================================================",
        f"* Project      : {job}",
        f"* Design Code  : {spec.design_code}",
        f"* Joints={nj}  Members={nm}",
        f"* Generated by : staad_generator (QRF -> STAAD.Pro pipeline)",
        f"* ===================================================================",
        "",
        "UNIT METER KN",
    ]

    # ===================================================================
    # GEOMETRY
    # ===================================================================
    lines.extend(["", "* --- Joint Coordinates ---", "JOINT COORDINATES"])
    lines.extend(_fmt_coord_line(fm.joint_coords))
    lines.extend(["", "* --- Member Incidences ---", "MEMBER INCIDENCES"])
    lines.extend(_member_lines(fm.members))

    # ===================================================================
    # MEMBER GROUPS (DEFINE GROUP)
    # ===================================================================
    lines.extend(["", "* --- Member Groups ---"])
    _groups: list[tuple[str, list[int]]] = [
        ("_COLUMNS", col_ids),
        ("_HAUNCHES", haunch_ids),
        ("_RAFTERS", raf_ids),
        ("_EAVE_BEAMS", eave_ids),
        ("_RIDGE_BEAMS", ridge_ids),
        ("_PURLINS", purlin_ids),
        ("_GIRTS", girt_ids),
        ("_ROOF_BRACE", roof_brace_ids),
        ("_WALL_BRACE", wall_brace_ids),
        ("_ENDWALL_COLS", endwall_col_ids),
        ("_MEZZ_COLS", mezz_col_ids),
        ("_MEZZ_BEAMS", mezz_beam_ids),
        ("_MEZZ_LONG", mezz_long_ids),
        ("_CRANE_BEAMS", crane_beam_ids),
        ("_PORTAL_BRACE", portal_brace_ids),
        ("_CANOPY", canopy_ids),
        ("_OPENING_JAMBS", opening_jamb_ids),
        ("_JACK_BEAMS", jack_beam_ids),
        ("_JOISTS", joist_ids),
        ("_CAGE_LADDER", cage_ladder_ids),
    ]
    active_groups = [(gn, gi) for gn, gi in _groups if gi]
    if active_groups:
        lines.append("START GROUP DEFINITION")
        lines.append("MEMBER")
        for gname, gids in active_groups:
            lines.append(f"{gname} {_runs_str(gids)}")
        lines.append("END GROUP DEFINITION")

    # ===================================================================
    # MATERIAL DEFINITION + CONSTANTS
    # ===================================================================
    lines.extend(
        [
            "",
            "DEFINE MATERIAL START",
            "ISOTROPIC STEEL",
            f"E {e_knm2:.6E}",
            f"POISSON {spec.poisson}",
            f"DENSITY {spec.density_kn_m3}",
            "ALPHA 1.2E-005",
            "DAMP 0.03",
            "END DEFINE MATERIAL",
            "",
            "UNIT METER KN",
            "CONSTANTS",
            "MATERIAL STEEL ALL",
        ]
    )

    # ===================================================================
    # MEMBER PROPERTIES
    # ===================================================================
    lines.extend(["", "MEMBER PROPERTY AMERICAN"])
    if spec.enable_tapered and col_ids:
        _td = _tapered_dims(spec.col_section, bottom_factor=1.8, top_factor=1.0)
        lines.append(f"{_runs_str(col_ids)} TAPERED {_td}")
    elif col_ids:
        lines.append(f"{_runs_str(col_ids)} TABLE ST {spec.col_section}")
    if haunch_ids:
        _hd = _tapered_dims(spec.rafter_section, bottom_factor=2.2, top_factor=1.5)
        lines.append(f"{_runs_str(haunch_ids)} TAPERED {_hd}")
    if spec.enable_tapered and raf_ids:
        _td = _tapered_dims(spec.rafter_section, bottom_factor=1.5, top_factor=1.0)
        lines.append(f"{_runs_str(raf_ids)} TAPERED {_td}")
    elif raf_ids:
        lines.append(f"{_runs_str(raf_ids)} TABLE ST {spec.rafter_section}")
    horiz_ids = sorted(eave_ids + ridge_ids)
    if horiz_ids:
        lines.append(f"{_runs_str(horiz_ids)} TABLE ST {spec.brace_section}")
    if purlin_ids:
        lines.append(f"{_runs_str(purlin_ids)} TABLE ST {spec.purlin_section}")
    if girt_ids:
        lines.append(f"{_runs_str(girt_ids)} TABLE ST {spec.girt_section}")
    if roof_brace_ids:
        lines.append(f"{_runs_str(roof_brace_ids)} TABLE ST {spec.brace_section}")
    if wall_brace_ids:
        lines.append(f"{_runs_str(wall_brace_ids)} TABLE ST {spec.brace_section}")
    if endwall_col_ids:
        lines.append(f"{_runs_str(endwall_col_ids)} TABLE ST {spec.col_section}")
    if mezz_col_ids:
        lines.append(f"{_runs_str(mezz_col_ids)} TABLE ST {spec.mezz_col_section}")
    mezz_beam_all = sorted(set(mezz_beam_ids + mezz_long_ids))
    if mezz_beam_all:
        lines.append(f"{_runs_str(mezz_beam_all)} TABLE ST {spec.mezz_beam_section}")
    if crane_beam_ids:
        lines.append(f"{_runs_str(crane_beam_ids)} TABLE ST {spec.crane_beam_section}")
    if portal_brace_ids:
        lines.append(f"{_runs_str(portal_brace_ids)} TABLE ST {spec.brace_section}")
    if canopy_ids:
        lines.append(f"{_runs_str(canopy_ids)} TABLE ST {spec.canopy_section}")
    if opening_jamb_ids:
        lines.append(f"{_runs_str(opening_jamb_ids)} TABLE ST {spec.col_section}")
    if jack_beam_ids:
        lines.append(f"{_runs_str(jack_beam_ids)} TABLE ST {spec.jack_beam_section}")
    if joist_ids:
        lines.append(f"{_runs_str(joist_ids)} TABLE ST {spec.joist_section}")
    if cage_ladder_ids:
        lines.append(f"{_runs_str(cage_ladder_ids)} TABLE ST {spec.girt_section}")

    # ===================================================================
    # SUPPORTS
    # ===================================================================
    base_ids = sorted(jid for jid, (_, y, _) in fm.joint_coords.items() if y == 0.0)
    if base_ids:
        lines.append("SUPPORTS")
        lines.append(f"{_runs_str(base_ids)} FIXED")
        lines.append("")

    # ===================================================================
    # MEMBER TRUSS + MEMBER RELEASE
    # ===================================================================
    if all_brace:
        lines.append(f"MEMBER TRUSS {_runs_str(all_brace)}")
        lines.append("")
        lines.append("MEMBER RELEASE")
        lines.append(f"{_runs_str(all_brace)} START MX MY MZ")
        lines.append(f"{_runs_str(all_brace)} END MX MY MZ")
        lines.append("")

    # ===================================================================
    # LOADING
    # ===================================================================
    w_roof = spec.wind_pressure_kn_m2
    w_wall = w_roof * 0.85
    purlin_dl = spec.dead_load_kn_m + spec.collateral_line_kn_m
    purlin_ll = spec.live_load_kn_m
    purlin_w = max(0.0, w_roof * 1.15 * min(2.0, spec.span_width_m / 16.0))
    load_num = 1

    # --- Load 1: Dead ---
    lines.extend(["* --- Primary Load Cases ---", "UNIT METER KN"])
    lines.append(f"LOAD {load_num} DEAD LOAD")
    lines.append("SELFWEIGHT Y -1")
    dead_ml: list[str] = []
    if spec.dead_load_kn_m > 0 and roof_m:
        dead_ml.extend(_member_uni_lines(roof_m, "GY", -spec.dead_load_kn_m))
    if purlin_dl > 0 and purlin_ids:
        dead_ml.extend(_member_uni_lines(purlin_ids, "GY", -purlin_dl))
    if dead_ml:
        lines.append("MEMBER LOAD")
        lines.extend(dead_ml)
    lc_dead = load_num
    load_num += 1

    # --- Load 2: Live ---
    lines.append("")
    lines.append(f"LOAD {load_num} LIVE LOAD")
    live_ml: list[str] = []
    if spec.live_load_kn_m > 0 and roof_m:
        live_ml.extend(_member_uni_lines(roof_m, "GY", -spec.live_load_kn_m))
    if purlin_ll > 0 and purlin_ids:
        live_ml.extend(_member_uni_lines(purlin_ids, "GY", -purlin_ll))
    if live_ml:
        lines.append("MEMBER LOAD")
        lines.extend(live_ml)
    elif roof_m:
        lines.append("MEMBER LOAD")
        lines.extend(_member_uni_lines(roof_m, "GY", -0.01))
    lc_live = load_num
    load_num += 1

    # --- Load 3: Wind +Z (pressure on sidewall, suction on roof) ---
    has_wind = w_roof > 0 and bool(roof_m)
    lc_wind_pz = 0
    lc_wind_nz = 0
    if has_wind:
        lines.append("")
        lines.append(f"LOAD {load_num} WIND +Z (TRANSVERSE)")
        lines.append("MEMBER LOAD")
        if raf_ids:
            lines.extend(_member_uni_lines(raf_ids, "GZ", -w_roof * 1.25))
        if ridge_ids:
            lines.extend(_member_uni_lines(ridge_ids, "GY", -w_roof * 0.35))
        if purlin_ids and purlin_w > 0:
            lines.extend(_member_uni_lines(purlin_ids, "GZ", -purlin_w))
        if girt_ids:
            lines.extend(_member_uni_lines(girt_ids, "GX", -w_wall * 0.9))
        lc_wind_pz = load_num
        load_num += 1

        # --- Load 4: Wind -Z (reverse direction) ---
        lines.append("")
        lines.append(f"LOAD {load_num} WIND -Z (TRANSVERSE REVERSE)")
        lines.append("MEMBER LOAD")
        if raf_ids:
            lines.extend(_member_uni_lines(raf_ids, "GZ", w_roof * 1.25))
        if ridge_ids:
            lines.extend(_member_uni_lines(ridge_ids, "GY", -w_roof * 0.35))
        if purlin_ids and purlin_w > 0:
            lines.extend(_member_uni_lines(purlin_ids, "GZ", w_roof * 0.8))
        if girt_ids:
            lines.extend(_member_uni_lines(girt_ids, "GX", w_wall * 0.9))
        lc_wind_nz = load_num
        load_num += 1

    # --- Load 5/6: Wind +X/-X (longitudinal on endwalls) ---
    lc_wind_px = 0
    lc_wind_nx = 0
    if has_wind:
        endwall_col_ids_load = by_kind.get("endwall_col", [])
        wall_press_x = w_wall * 0.7
        lines.append("")
        lines.append(f"LOAD {load_num} WIND +X (LONGITUDINAL)")
        lines.append("MEMBER LOAD")
        if col_ids:
            lines.extend(_member_uni_lines(col_ids, "GX", -wall_press_x * 0.5))
        if endwall_col_ids_load:
            lines.extend(_member_uni_lines(endwall_col_ids_load, "GX", -wall_press_x))
        if raf_ids:
            lines.extend(_member_uni_lines(raf_ids, "GY", -w_roof * 0.5))
        lc_wind_px = load_num
        load_num += 1

        lines.append("")
        lines.append(f"LOAD {load_num} WIND -X (LONGITUDINAL REVERSE)")
        lines.append("MEMBER LOAD")
        if col_ids:
            lines.extend(_member_uni_lines(col_ids, "GX", wall_press_x * 0.5))
        if endwall_col_ids_load:
            lines.extend(_member_uni_lines(endwall_col_ids_load, "GX", wall_press_x))
        if raf_ids:
            lines.extend(_member_uni_lines(raf_ids, "GY", -w_roof * 0.5))
        lc_wind_nx = load_num
        load_num += 1

    # --- Load N: Seismic +X ---
    has_seis = spec.seismic_ah > 0.0
    lc_seis_px = 0
    lc_seis_nx = 0
    if has_seis:
        dl_area = max(spec.dead_load_kn_m / max(0.9, spec.span_width_m / 12.0), 0.05)
        roof_wt = dl_area * spec.span_width_m * spec.bay_length_m * max(1, spec.n_bays)
        v_base = spec.seismic_ah * roof_wt * 1.1
        ej = _eave_joint_ids(fm, spec)
        if ej:
            fx = v_base / len(ej)
            fx = max(0.5, min(200.0, fx))
            lines.append("")
            lines.append(f"LOAD {load_num} SEISMIC +X")
            lines.append("JOINT LOAD")
            lines.extend(_joint_load_fx_lines(ej, fx))
            lc_seis_px = load_num
            load_num += 1

            lines.append("")
            lines.append(f"LOAD {load_num} SEISMIC -X")
            lines.append("JOINT LOAD")
            lines.extend(_joint_load_fx_lines(ej, -fx))
            lc_seis_nx = load_num
            load_num += 1
        else:
            has_seis = False

    # --- Load N: Crane (if applicable) ---
    has_crane = spec.crane_load_kn > 0
    lc_crane = 0
    if has_crane:
        lines.append("")
        lines.append(f"LOAD {load_num} CRANE/HOIST")
        if crane_beam_ids:
            crane_w = spec.crane_load_kn / max(1.0, spec.span_width_m * 0.3)
            lines.append("MEMBER LOAD")
            lines.extend(_member_uni_lines(crane_beam_ids, "GY", -crane_w))
            lc_crane = load_num
            load_num += 1
        else:
            crane_jids = _eave_joint_ids(fm, spec)[:4]
            if crane_jids:
                lines.append("JOINT LOAD")
                fz_crane = -spec.crane_load_kn / max(1, len(crane_jids))
                for cj in crane_jids:
                    lines.append(f"{cj} FY {_fmt_load(fz_crane)}")
                lc_crane = load_num
                load_num += 1
            else:
                has_crane = False

    # --- Mezzanine Dead + Live loads ---
    lc_mezz_dead = 0
    lc_mezz_live = 0
    if has_mezz and mezz_beam_all:
        trib_mezz = max(1.0, spec.mezzanine_width_m / max(1, len(mezz_beam_ids) + 1))
        mezz_dl_line = spec.mezzanine_slab_kn_m2 * trib_mezz
        mezz_ll_line = spec.mezzanine_live_load_kn_m2 * trib_mezz

        lines.append("")
        lines.append(f"LOAD {load_num} MEZZANINE DEAD LOAD")
        lines.append("MEMBER LOAD")
        lines.extend(_member_uni_lines(mezz_beam_all, "GY", -mezz_dl_line))
        lc_mezz_dead = load_num
        load_num += 1

        lines.append("")
        lines.append(f"LOAD {load_num} MEZZANINE LIVE LOAD")
        lines.append("MEMBER LOAD")
        lines.extend(_member_uni_lines(mezz_beam_all, "GY", -mezz_ll_line))
        lc_mezz_live = load_num
        load_num += 1

    # ===================================================================
    # LOAD COMBINATIONS (ASCE 7 / LRFD)
    # ===================================================================
    _combo_ref = "IS 875 / IS 800" if "IS800" in spec.design_code else "ASCE 7-16"
    lines.extend(["", f"* --- Load Combinations (LRFD per {_combo_ref}) ---"])
    combo_num = 101

    def _add_combo(name: str, factors: str) -> int:
        nonlocal combo_num
        lines.append(f"LOAD COMB {combo_num} {name}")
        lines.append(factors)
        n = combo_num
        combo_num += 1
        return n

    # ASCE 7-16 Section 2.3
    _mezz_d = f" {lc_mezz_dead} 1.4" if lc_mezz_dead else ""
    _add_combo("ULT_1.4D", f"{lc_dead} 1.4{_mezz_d}")

    _mezz_d12 = f" {lc_mezz_dead} 1.2" if lc_mezz_dead else ""
    _mezz_l16 = f" {lc_mezz_live} 1.6" if lc_mezz_live else ""
    _mezz_l10 = f" {lc_mezz_live} 1.0" if lc_mezz_live else ""
    _mezz_d09 = f" {lc_mezz_dead} 0.9" if lc_mezz_dead else ""
    _mezz_d10 = f" {lc_mezz_dead} 1.0" if lc_mezz_dead else ""
    _mezz_l10s = f" {lc_mezz_live} 1.0" if lc_mezz_live else ""

    _add_combo("ULT_1.2D+1.6L", f"{lc_dead} 1.2 {lc_live} 1.6{_mezz_d12}{_mezz_l16}")

    if has_wind:
        _add_combo("ULT_1.2D+1.0L+1.0Wp", f"{lc_dead} 1.2 {lc_live} 1.0 {lc_wind_pz} 1.0{_mezz_d12}{_mezz_l10}")
        _add_combo("ULT_1.2D+1.0L+1.0Wn", f"{lc_dead} 1.2 {lc_live} 1.0 {lc_wind_nz} 1.0{_mezz_d12}{_mezz_l10}")
        _add_combo("ULT_1.2D+1.6L+0.5Wp", f"{lc_dead} 1.2 {lc_live} 1.6 {lc_wind_pz} 0.5{_mezz_d12}{_mezz_l16}")
        _add_combo("ULT_1.2D+1.6L+0.5Wn", f"{lc_dead} 1.2 {lc_live} 1.6 {lc_wind_nz} 0.5{_mezz_d12}{_mezz_l16}")
        _add_combo("ULT_0.9D+1.0Wp", f"{lc_dead} 0.9 {lc_wind_pz} 1.0{_mezz_d09}")
        _add_combo("ULT_0.9D+1.0Wn", f"{lc_dead} 0.9 {lc_wind_nz} 1.0{_mezz_d09}")
        # Longitudinal wind combinations
        _add_combo("ULT_1.2D+1.0L+1.0WXp", f"{lc_dead} 1.2 {lc_live} 1.0 {lc_wind_px} 1.0{_mezz_d12}{_mezz_l10}")
        _add_combo("ULT_1.2D+1.0L+1.0WXn", f"{lc_dead} 1.2 {lc_live} 1.0 {lc_wind_nx} 1.0{_mezz_d12}{_mezz_l10}")
        _add_combo("ULT_0.9D+1.0WXp", f"{lc_dead} 0.9 {lc_wind_px} 1.0{_mezz_d09}")
        _add_combo("ULT_0.9D+1.0WXn", f"{lc_dead} 0.9 {lc_wind_nx} 1.0{_mezz_d09}")

    if has_seis:
        _add_combo("ULT_1.2D+1.0Ep+1.0L", f"{lc_dead} 1.2 {lc_seis_px} 1.0 {lc_live} 1.0{_mezz_d12}{_mezz_l10}")
        _add_combo("ULT_0.9D+1.0Ep", f"{lc_dead} 0.9 {lc_seis_px} 1.0{_mezz_d09}")
        _add_combo("ULT_1.2D+1.0En+1.0L", f"{lc_dead} 1.2 {lc_seis_nx} 1.0 {lc_live} 1.0{_mezz_d12}{_mezz_l10}")
        _add_combo("ULT_0.9D+1.0En", f"{lc_dead} 0.9 {lc_seis_nx} 1.0{_mezz_d09}")

    if has_crane:
        _add_combo("ULT_1.2D+1.6L+1.0CR", f"{lc_dead} 1.2 {lc_live} 1.6 {lc_crane} 1.0{_mezz_d12}{_mezz_l16}")
        if has_wind:
            _add_combo("ULT_1.2D+CR+0.5Wp", f"{lc_dead} 1.2 {lc_crane} 1.0 {lc_wind_pz} 0.5{_mezz_d12}")

    sls_combo = _add_combo("SLS_D+L", f"{lc_dead} 1.0 {lc_live} 1.0{_mezz_d10}{_mezz_l10s}")
    if has_wind:
        _add_combo("SLS_D+L+Wz", f"{lc_dead} 1.0 {lc_live} 1.0 {lc_wind_pz} 0.6{_mezz_d10}{_mezz_l10s}")
        _add_combo("SLS_D+L+Wx", f"{lc_dead} 1.0 {lc_live} 1.0 {lc_wind_px} 0.6{_mezz_d10}{_mezz_l10s}")

    # ===================================================================
    # ANALYSIS
    # ===================================================================
    lines.extend(
        [
            "",
            "PERFORM ANALYSIS PRINT STATICS CHECK",
            "",
            "* --- Output Requests ---",
            "PRINT SUPPORT REACTION",
            "",
        ]
    )

    # ===================================================================
    # STEEL DESIGN — Unity Ratio (UR) check
    # ===================================================================
    lines.append("* --- Steel Design: Unity Ratio Check ---")
    lines.append("PARAMETER 1")
    lines.append(f"CODE {spec.design_code}")
    lines.append("METHOD LRFD")
    lines.append(f"FYLD {fyld_kn_m2:.0f} ALL")
    lines.append("TRACK 2 ALL")
    lines.append(f"DFF {spec.defl_frame_vertical:.0f} ALL")
    lines.append("RATIO 1.0 ALL")
    if all_primary:
        lines.append(f"CHECK CODE {_runs_str(all_primary)}")
    if all_secondary:
        lines.append(f"CHECK CODE {_runs_str(all_secondary)}")
    lines.append("")

    # --- SELECT MEMBER for optimized sections ---
    lines.append("* --- Section Optimization (target UR 0.9-1.0) ---")
    lines.append("PARAMETER 2")
    lines.append(f"CODE {spec.design_code}")
    lines.append("METHOD LRFD")
    lines.append(f"FYLD {fyld_kn_m2:.0f} ALL")
    lines.append(f"DFF {spec.defl_frame_vertical:.0f} ALL")
    lines.append("RATIO 0.95 ALL")
    if all_primary:
        lines.append(f"SELECT {_runs_str(all_primary)}")
    if all_secondary:
        lines.append(f"SELECT {_runs_str(all_secondary)}")
    lines.append("")

    # ===================================================================
    # SERVICEABILITY — Deflection check under SLS
    # ===================================================================
    lines.append("* --- Serviceability / Deflection Check (SLS) ---")
    lines.append(f"LOAD LIST {sls_combo}")
    lines.append("PARAMETER 3")
    lines.append(f"CODE {spec.design_code}")
    lines.append("METHOD LRFD")
    lines.append(f"FYLD {fyld_kn_m2:.0f} ALL")
    _col_endwall = sorted(set(col_ids + endwall_col_ids + mezz_col_ids))
    _beams = sorted(set(raf_ids + haunch_ids + eave_ids + ridge_ids + mezz_beam_all + crane_beam_ids))
    if _col_endwall:
        lines.append(f"DFF {spec.defl_frame_lateral:.0f} MEMB {_runs_str(_col_endwall)}")
    if _beams:
        lines.append(f"DFF {spec.defl_frame_vertical:.0f} MEMB {_runs_str(_beams)}")
    if all_secondary:
        lines.append(f"DFF {spec.defl_purlin:.0f} MEMB {_runs_str(all_secondary)}")
    lines.append("TRACK 2 ALL")
    lines.append("RATIO 1.0 ALL")
    if all_primary:
        lines.append(f"CHECK CODE {_runs_str(all_primary)}")
    if all_secondary:
        lines.append(f"CHECK CODE {_runs_str(all_secondary)}")
    lines.append("")

    # Re-analysis required after SELECT changes sections
    lines.append("LOAD LIST ALL")
    lines.append("PERFORM ANALYSIS")
    lines.append("")

    # Final CHECK CODE after re-analysis with optimized sections
    lines.append("* --- Final Code Check (post-optimization) ---")
    lines.append("PARAMETER 4")
    lines.append(f"CODE {spec.design_code}")
    lines.append("METHOD LRFD")
    lines.append(f"FYLD {fyld_kn_m2:.0f} ALL")
    lines.append(f"DFF {spec.defl_frame_vertical:.0f} ALL")
    lines.append("TRACK 2 ALL")
    lines.append("RATIO 1.0 ALL")
    lines.append(f"CHECK CODE {_runs_str(all_ids)}")
    lines.append("")

    # ===================================================================
    # FEA VERIFICATION COMMENT (PyNite, if available)
    # ===================================================================
    try:
        from staad_generator.fea_verify import verify_portal_frame

        fea = verify_portal_frame(spec)
        if fea.n_members_checked > 0:
            lines.append("* ===================================================================")
            lines.append("* FEA VERIFICATION (PyNite, simplified single-bay 2D portal frame)")
            lines.append(f"*   Optimized col: {fea.optimized_col_section}  rafter: {fea.optimized_raf_section}")
            lines.append(f"*   Max UR = {fea.max_ur:.3f} ({fea.max_ur_member}) -> {'PASS' if fea.ur_pass else 'FAIL'}")
            lines.append(
                f"*   Max Defl = {fea.max_defl_mm:.1f} mm ({fea.max_defl_member}), "
                f"limit = {fea.defl_limit_mm:.1f} mm -> {'PASS' if fea.defl_pass else 'FAIL'}"
            )
            lines.append("* ===================================================================")
            lines.append("")
    except Exception:
        pass

    lines.append("FINISH")

    return "\n".join(lines) + "\n"


def json_file_to_std(
    json_path: Path,
    std_path: Path | None = None,
    *,
    spec: BuildingSpec | None = None,
    model: FrameModel | None = None,
    text: str | None = None,
    force: bool = False,
    skip_if_fresher: bool = False,
) -> Path:
    """Write ``json_path`` → ``.std``.

    - If ``std_path`` is omitted, the file is written next to ``json_path`` as
      ``<stem>.std`` (same folder). The CLI ``--one`` mode passes an explicit
      ``std_path`` under ``--output`` instead.
    - If ``text`` is provided, it is written as-is (no second call to
      :func:`build_std_text`); use after building once with ``spec``/``model``.
    - If ``skip_if_fresher`` is true and ``force`` is false and ``std_path``
      (or the default next to JSON) exists with mtime ≥ ``json_path``, the
      file is not rewritten and that path is returned.
    """
    out = std_path if std_path is not None else json_path.with_suffix(".std")
    if skip_if_fresher and not force and out.exists():
        try:
            if out.stat().st_mtime >= json_path.stat().st_mtime:
                logger.info("Skipping up-to-date: %s", out)
                return out
        except OSError:
            pass
    if text is None:
        if spec is None:
            spec = spec_from_json_path(json_path)
        text = build_std_text(spec, model)
    out.write_text(text, encoding="utf-8", newline="\n")
    return out


def dict_to_std(data: dict, std_path: Path, name: str = "model") -> Path:
    spec = spec_from_dict(data, name=name)
    std_path.write_text(build_std_text(spec, None), encoding="utf-8", newline="\n")
    return std_path


def batch_convert(
    input_dir: Path,
    output_dir: Path,
    *,
    dry_run: bool = False,
    verbose: bool = False,
    quiet: bool = False,
    force: bool = False,
    skip_if_fresher: bool = False,
) -> list[Path]:
    """Convert each ``*.json`` in *input_dir*. If *dry_run*, validate only (no files written)."""
    output_dir.mkdir(parents=True, exist_ok=True)
    out_paths: list[Path] = []
    for jp in sorted(input_dir.glob("*.json")):
        op = output_dir / f"{jp.stem}.std"
        if skip_if_fresher and not force and not dry_run and op.exists():
            try:
                if op.stat().st_mtime >= jp.stat().st_mtime:
                    logger.info("Skipping up-to-date: %s", op.name)
                    out_paths.append(op)
                    continue
            except OSError:
                pass

        spec = spec_from_json_path(jp)
        fm = build_frame(spec)
        if verbose and not quiet:
            logger.info(
                "%s",
                format_spec_summary(
                    spec,
                    n_joints=len(fm.joint_coords),
                    n_members=len(fm.members),
                ),
            )
        text = build_std_text(spec, fm)
        if dry_run:
            out_paths.append(op)
            continue
        op.write_text(text, encoding="utf-8", newline="\n")
        out_paths.append(op)
    return out_paths
