"""Parse SIJCON-style QRF JSON (version_list → process_json → sections)."""

from __future__ import annotations

import math
import re
from typing import Any, Mapping

from staad_generator.spec import BuildingSpec

# Dimension appears first, then c/c (preferred for SIJCON QRF wording).
_CC_AFTER_M = re.compile(
    r"(\d+(?:\.\d+)?)\s*m[^.\d]{0,50}?(?:center-to-center|centre-to-centre|c\.c\.|\(c/c\)|\bc/c\b)",
    re.I,
)
# c/c keyword then a number — only when followed by "m" within a short tail (avoids "… is 49.671 m" after c/c).
_CC_NEAR_M = re.compile(
    r"(?:\bc/c\b|\(c/c\)|center-to-center|centre-to-centre)[^.\d]{0,12}?(\d+(?:\.\d+)?)\s*m",
    re.I,
)
_NUM_M = re.compile(r"(\d+(?:\.\d+)?)\s*m\b", re.I)
_BAY_PRODUCT = re.compile(
    r"(\d+)\s*bays?\s*[×x*]\s*(\d+(?:\.\d+)?)\s*m",
    re.I,
)
_BRACKET_BAY = re.compile(
    r"\[\s*(\d+)\s*@\s*(\d+(?:\.\d+)?)\s*m\s*\]",
    re.I,
)
_BRACKET_BAY_MM = re.compile(
    r"\[\s*(\d+)\s*@\s*(\d+(?:\.\d+)?)\s*mm\s*\]",
    re.I,
)
_MM_BAY_TOKEN = re.compile(r"\b(\d{4,5})\s*mm\b", re.I)
_SLOPE_DEG = re.compile(r"(\d+(?:\.\d+)?)\s*°")
_SLOPE_RATIO = re.compile(r"1\s*:\s*(\d+(?:\.\d+)?)")
_KNM2 = re.compile(r"(\d+(?:\.\d+)?)\s*kN\s*/\s*m\s*\^?\s*2", re.I)
_KNM2_ALT = re.compile(r"(\d+(?:\.\d+)?)\s*kN/m\s*\^?\s*2", re.I)
_KNM2_SIMPLE = re.compile(r"(\d+(?:\.\d+)?)\s*kN/m²", re.I)
_KN_SQM = re.compile(r"(\d+(?:\.\d+)?)\s*kN\s*/\s*sqm\b", re.I)
_WIND_MS = re.compile(r"(\d+(?:\.\d+)?)\s*m\s*/\s*sec", re.I)


def _unwrap_root(data: Mapping[str, Any]) -> Mapping[str, Any]:
    if "version_list" in data:
        return data
    inner = data.get("data")
    if isinstance(inner, list) and inner and isinstance(inner[0], Mapping):
        first = inner[0]
        if "version_list" in first:
            return first
    return data


def _get_sections(data: Mapping[str, Any]) -> dict[str, Any] | None:
    """Sections may live under process_json or previous_json (Kaggle export quirk)."""
    root = _unwrap_root(data)
    vl = root.get("version_list")
    if not isinstance(vl, list) or not vl or not isinstance(vl[0], Mapping):
        return None
    v0 = vl[0]
    for blob_key in ("process_json", "previous_json"):
        blob = v0.get(blob_key)
        if not isinstance(blob, dict):
            continue
        sec = blob.get("sections")
        if isinstance(sec, dict) and sec:
            return sec
    return None


def is_qrf_payload(data: Mapping[str, Any]) -> bool:
    return _get_sections(data) is not None


def _find_section_rows(sections: Mapping[str, Any], needle: str) -> list[dict[str, Any]]:
    nl = needle.lower()
    for key, rows in sections.items():
        if nl in str(key).lower() and isinstance(rows, list):
            return [r for r in rows if isinstance(r, Mapping)]
    return []


def _row_index(rows: list[Mapping[str, Any]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for r in rows:
        d = str(r.get("desc", "")).strip().lower()
        if d:
            out[d] = str(r.get("details", ""))
    return out


def _row_fuzzy(li: dict[str, str], *must_contain: str) -> str:
    """Pick *details* from the row whose *desc* (lowercased) contains every substring."""
    if not li or not must_contain:
        return ""
    subs = [s.lower() for s in must_contain]
    best: tuple[int, str] | None = None
    for k, v in li.items():
        kl = k.lower()
        if all(s in kl for s in subs):
            cand = (len(k), str(v))
            if best is None or cand[0] > best[0]:
                best = cand
    return best[1] if best else ""


def _mm_structure_dim_m(text: str) -> float | None:
    """Overall dims given as mm integers, e.g. '24380 O/O' or '10500 CLEAR'."""
    if not text:
        return None
    t = text.strip()
    for m in re.finditer(r"\b(\d{4,6})\s*mm\b", t, re.I):
        v = int(m.group(1))
        if 1000 <= v <= 200000:
            return v / 1000.0
    m = re.match(r"^\s*(\d{4,6})\b", t)
    if m:
        v = int(m.group(1))
        if 3000 <= v <= 200000:
            return v / 1000.0
    for seg in re.split(r"[;]", t, maxsplit=2):
        seg = seg.strip()
        m2 = re.match(r"(\d{4,6})\b", seg)
        if m2:
            v = int(m2.group(1))
            if 3000 <= v <= 200000:
                return v / 1000.0
    return None


def _first_cc_or_plausible_m(text: str) -> float | None:
    if not text:
        return None
    m = _CC_AFTER_M.search(text)
    if m:
        v = float(m.group(1))
        if 3 <= v <= 500:
            return v
    m = _CC_NEAR_M.search(text)
    if m:
        v = float(m.group(1))
        if 3 <= v <= 500:
            return v
    mm = _mm_structure_dim_m(text)
    if mm is not None and 3.0 <= mm <= 200.0:
        return mm
    for m in _NUM_M.finditer(text):
        v = float(m.group(1))
        if 4 <= v <= 500:
            return v
    return None


def _eave_height_m(text: str) -> float | None:
    if not text:
        return None
    tl = text.lower()
    vals: list[float] = []
    for m in _NUM_M.finditer(text):
        v = float(m.group(1))
        if 4.0 <= v <= 70.0:
            vals.append(v)
    for m in re.finditer(r"\b(\d{4,6})\s*mm\b", text, re.I):
        v = int(m.group(1)) / 1000.0
        if 4.0 <= v <= 70.0:
            vals.append(v)
    if not vals:
        mm = _mm_structure_dim_m(text)
        if mm is not None and 4.0 <= mm <= 70.0:
            return mm
        return None
    vals.sort()
    # Low-bay + high-bay QRFs: use low eave when spread is large.
    if max(vals) - min(vals) > 10.0 and ("low bay" in tl or "high bay" in tl):
        return min(vals)
    return vals[len(vals) // 2]


def _roof_slope_ratio(text: str) -> float | None:
    if not text:
        return None
    m = _SLOPE_DEG.search(text)
    if m:
        return math.tan(math.radians(float(m.group(1))))
    m = _SLOPE_RATIO.search(text.replace("：", ":"))
    if m:
        run = float(m.group(1))
        if run > 1e-6:
            return 1.0 / run
    return None


def _parse_bays_and_spacing(text: str) -> tuple[int | None, float | None]:
    if not text:
        return None, None
    m = _BAY_PRODUCT.search(text)
    if m:
        return int(m.group(1)), float(m.group(2))
    spans = _BRACKET_BAY.findall(text)
    spans_mm = _BRACKET_BAY_MM.findall(text)
    if spans_mm:
        total_n = sum(int(a) for a, _ in spans_mm)
        total_len = sum(int(a) * float(b) for a, b in spans_mm)
        if total_n > 0:
            return total_n, (total_len / total_n) / 1000.0
    if spans:
        total_n = sum(int(a) for a, _ in spans)
        total_len = sum(int(a) * float(b) for a, b in spans)
        if total_n > 0:
            return total_n, total_len / total_n
    mm_toks = [int(x) for x in _MM_BAY_TOKEN.findall(text)]
    if len(mm_toks) >= 2:
        meters = [t / 1000.0 for t in mm_toks if 2000 <= t <= 50000]
        if len(meters) >= 2:
            return len(meters), sum(meters) / len(meters)
    return None, None


def _parse_knm2(text: str) -> float | None:
    if not text:
        return None
    t = text.replace("^2", "2")
    for pat in (_KNM2, _KNM2_ALT, _KNM2_SIMPLE, _KN_SQM):
        m = pat.search(t)
        if m:
            return float(m.group(1))
    return None


def _wind_pressure_knm2(text: str) -> float | None:
    if not text:
        return None
    m = _WIND_MS.search(text.lower())
    if m:
        v = float(m.group(1))
        return max(0.0, 0.613e-3 * v * v)
    return None


def _collateral_line_knm(tributary_m: float, text: str) -> float:
    if not text:
        return 0.0
    t = text.replace("^2", "2").replace("m²", "m2")
    s = 0.0
    for pat in (
        r"(\d+(?:\.\d+)?)\s*kN\s*/\s*sqm\b",
        r"(\d+(?:\.\d+)?)\s*kN\s*/\s*m\s*\^?\s*2",
        r"(\d+(?:\.\d+)?)\s*kN/m2\b",
        r"(\d+(?:\.\d+)?)\s*kN/m²",
        r"(\d+(?:\.\d+)?)\s*kN\s*/\s*m2\b",
    ):
        for m in re.finditer(pat, t, re.I):
            v = float(m.group(1))
            if v < 50:
                s += v
    return max(0.0, min(s * tributary_m, 4.0))


def _seismic_ah_from_zone(text: str) -> float:
    if not text:
        return 0.0
    t = text.lower()
    t_clean = re.sub(r"(?:is\s*\d{3,4}|part[\s\-]*\d+|standard|edition|\d{4}\s*)", " ", t)
    t_clean = t_clean.replace(":", " ").replace("-", " ")
    if re.search(r"zone\s*v\b", t_clean) or re.fullmatch(r"\s*v\s*", t_clean):
        return 0.087
    if re.search(r"zone\s*iv\b", t_clean) or re.fullmatch(r"\s*iv\s*", t_clean):
        return 0.06
    if re.search(r"zone\s*iii\b", t_clean) or re.fullmatch(r"\s*iii\s*", t_clean):
        return 0.045
    if re.search(r"zone\s*ii\b", t_clean) or re.fullmatch(r"\s*ii\s*", t_clean):
        return 0.03
    if re.search(r"zone\s*5\b", t_clean):
        return 0.087
    if re.search(r"zone\s*4\b", t_clean):
        return 0.06
    if re.search(r"zone\s*3\b", t_clean):
        return 0.045
    if re.search(r"zone\s*2\b", t_clean):
        return 0.03
    return 0.0


def _parse_bay_list(text: str) -> list[float] | None:
    """Extract explicit per-bay spacings from bracket notation like ``[1@7.115 m] [5@8.700 m]``."""
    spans = _BRACKET_BAY.findall(text)
    spans_mm = _BRACKET_BAY_MM.findall(text)
    out: list[float] = []
    if spans:
        for count_s, val_s in spans:
            out.extend([float(val_s)] * int(count_s))
    elif spans_mm:
        for count_s, val_s in spans_mm:
            out.extend([float(val_s) / 1000.0] * int(count_s))
    if out and len(out) >= 2:
        return out
    return None


def _parse_deflection_limits(text: str) -> tuple[float, float, float]:
    """Return (frame_vertical, frame_lateral, purlin) deflection ratio denominators."""
    vert, lat, pur = 240.0, 180.0, 180.0
    if not text:
        return vert, lat, pur
    tl = text.lower()
    m_v = re.search(r"(?:vertical|main\s*frame\s*vertical)\s*[:\-]?\s*[lh]\s*/\s*(\d+)", tl)
    if m_v:
        vert = float(m_v.group(1))
    m_l = re.search(r"(?:lateral|main\s*frame\s*lateral)\s*[:\-]?\s*[lh]\s*/\s*(\d+)", tl)
    if m_l:
        lat = float(m_l.group(1))
    m_p = re.search(r"purlin\s*[:\-]?\s*[lh]\s*/\s*(\d+)", tl)
    if m_p:
        pur = float(m_p.group(1))
    # Fallback: simple "L/NNN" or "Span/NNN" with no context → apply to vertical
    if not m_v and not m_l and not m_p:
        m_simple = re.search(r"[lh]\s*/\s*(\d+)", tl) or re.search(r"span\s*/\s*(\d+)", tl)
        if m_simple:
            v = float(m_simple.group(1))
            vert = v
            lat = v
            pur = v
    return vert, lat, pur


def _parse_design_code(text: str) -> str:
    """Pick a STAAD-compatible code string from the design code description."""
    if not text:
        return "AISC UNIFIED 2010"
    tl = text.lower()
    if re.search(r"is\s*800|is:800", tl):
        return "IS800 LSD"
    if "aisc" in tl and "2016" in tl:
        return "AISC UNIFIED 2016"
    if "aisc" in tl:
        return "AISC UNIFIED 2010"
    if "mbma" in tl:
        return "AISC UNIFIED 2010"
    return "AISC UNIFIED 2010"


def _parse_crane_load_kn(sections: Mapping[str, Any]) -> float:
    """Extract crane/hoist capacity in kN from Crane Details or Utility Load."""
    crane_rows = _find_section_rows(sections, "crane")
    ci = _row_index(crane_rows)
    for k, v in ci.items():
        m = re.search(r"(\d+(?:\.\d+)?)\s*(?:ton|t)\b", v, re.I)
        if m:
            return float(m.group(1)) * 9.81
    return 0.0


def _brace_flags(bi: dict[str, str]) -> bool:
    keys = (
        "type of brace in side walls :, roof",
        "type of brace in side walls : roof",
        "type of brace in side walls, roof",
        "type of brace in side walls & roof",
    )
    text = ""
    for k in keys:
        text = bi.get(k, "")
        if text:
            break
    if not text:
        for k, v in bi.items():
            if "brace" in k and "roof" in k:
                text = v
                break
    if not text:
        return True
    tl = text.lower()
    if re.search(r"\bna\b|none|not applicable", tl) and "brace" not in tl:
        return False
    return bool(re.search(r"brace|bracing|diagonal|portal|rod|angle|pipe|cross", tl))


def _steel_sections(span_m: float) -> tuple[str, str, str, str]:
    """Main column, rafter, bracing/purlin-ish heavy, light secondary."""
    if span_m >= 48.0:
        return "W14X90", "W24X62", "W12X35", "W8X10"
    if span_m >= 36.0:
        return "W12X65", "W21X50", "W10X26", "W6X9"
    if span_m >= 28.0:
        return "W12X50", "W18X40", "W10X22", "W6X9"
    return "W12X40", "W14X48", "W8X18", "W6X9"


def _line_load_from_area_knm2(p_area: float, tributary_m: float = 1.5) -> float:
    return max(0.0, p_area * tributary_m)


def _single_bay_spacing_m(text: str) -> float | None:
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*m\s*", text.strip(), re.I)
    if m:
        return float(m.group(1))
    return None


def _parse_mezzanine(sections: Mapping[str, Any], eave_m: float) -> dict[str, Any]:
    """Extract mezzanine parameters from QRF Mezzanine Floor Details section."""
    mezz_rows = _find_section_rows(sections, "mezzanine")
    if not mezz_rows:
        return {}

    from staad_generator.ai_parser import parse_mezzanine_rows

    ms = parse_mezzanine_rows(mezz_rows)

    if ms.width_m <= 0 and ms.length_m <= 0:
        return {}

    elevation = ms.elevation_m
    if elevation <= 0:
        elevation = min(eave_m * 0.45, 5.0)

    return {
        "mezzanine_elevation_m": elevation,
        "mezzanine_width_m": ms.width_m,
        "mezzanine_length_m": ms.length_m,
        "mezzanine_live_load_kn_m2": ms.live_load_kn_m2 if ms.live_load_kn_m2 > 0 else 5.0,
        "mezzanine_slab_kn_m2": ms.slab_dead_load_kn_m2 if ms.slab_dead_load_kn_m2 > 0 else 2.0,
    }


def spec_from_qrf(data: Mapping[str, Any], name: str = "model") -> BuildingSpec:
    sections = _get_sections(data)
    if not sections:
        raise ValueError("Not a QRF payload")
    build_rows = _find_section_rows(sections, "building parameters")
    load_rows = _find_section_rows(sections, "design loads")
    bi = _row_index(build_rows)
    li = _row_index(load_rows)

    width_t = bi.get("width (m)", "")
    length_t = bi.get("length (m)", "")
    eave_t = bi.get("eave height (m)", "")
    slope_t = bi.get("roof slope", "")
    bay_sw = bi.get("bay spacing (m) - side wall", "")
    bay_im = bi.get("bay spacing (m) - intermediate", "")

    span_m = _first_cc_or_plausible_m(width_t) or 24.0
    length_m = _first_cc_or_plausible_m(length_t) or 48.0
    sm_l = re.search(r"individual bay dimensions is (\d+(?:\.\d+)?)\s*m", length_t, re.I)
    if sm_l:
        length_m = float(sm_l.group(1))
    eave_m = _eave_height_m(eave_t) or 10.0
    slope_ratio = _roof_slope_ratio(slope_t) or 0.1
    slope_ratio = max(0.02, min(0.45, slope_ratio))

    bay_list = _parse_bay_list(bay_sw)
    n_bay, bay_len = _parse_bays_and_spacing(bay_sw)
    if n_bay is None or bay_len is None:
        n2, bl2 = _parse_bays_and_spacing(bay_im)
        if n_bay is None:
            n_bay = n2
        if bay_len is None:
            bay_len = bl2
    single_sp = _single_bay_spacing_m(bay_sw) or _single_bay_spacing_m(bay_im)
    if single_sp and single_sp > 0.5 and n_bay is None:
        bay_len = single_sp
        n_bay = max(1, int(length_m / single_sp))
    if n_bay is None and bay_len is not None and bay_len > 0.5:
        n_bay = max(1, int(round(length_m / bay_len)))
    if n_bay is None:
        n_bay = max(1, int(round(length_m / 6.0)))
    if bay_len is None or bay_len < 0.3:
        bay_len = length_m / n_bay

    n_bay = max(1, n_bay)
    if length_m > 0:
        bay_len = length_m / n_bay
    bay_len = max(0.5, min(bay_len, length_m))

    if bay_list and len(bay_list) == n_bay:
        pass
    elif bay_list and abs(sum(bay_list) - length_m) < 1.0:
        n_bay = len(bay_list)
        bay_len = sum(bay_list) / n_bay
    else:
        bay_list = None

    dl_a = (
        _parse_knm2(li.get("dead load (kN/sqm)", "") or _row_fuzzy(li, "dead load"))
        or 0.15
    )
    ll_a = (
        _parse_knm2(
            li.get("design live load (kN/sqm) on roof", "")
            or _row_fuzzy(li, "live load", "roof")
        )
        or 0.57
    )
    trib = min(2.0, max(1.0, span_m / 18.0))
    dl_line = _line_load_from_area_knm2(dl_a, trib)
    ll_line = _line_load_from_area_knm2(ll_a, trib)
    wind_t = li.get("wind speed (km/hr)", "") or _row_fuzzy(li, "wind speed")
    wind_p = _wind_pressure_knm2(wind_t) or 0.8

    coll_t = li.get("collateral load (kN/sqm)", "") or _row_fuzzy(li, "collateral")
    collateral_line = _collateral_line_knm(trib, coll_t)
    seis_t = (
        li.get("earthquake/seismic zone", "")
        or _row_fuzzy(li, "earthquake")
        or _row_fuzzy(li, "seismic", "zone")
    )
    ah = _seismic_ah_from_zone(seis_t)
    br_on = _brace_flags(bi)
    pur_sp = max(1.15, min(2.35, span_m / 22.0))
    col_s, raf_s, br_s, pur_s = _steel_sections(span_m)

    defl_t = li.get("deflection limit", "") or _row_fuzzy(li, "deflection")
    defl_v, defl_l, defl_p = _parse_deflection_limits(defl_t)

    code_t = li.get("design code", "") or _row_fuzzy(li, "design code")
    design_code = _parse_design_code(code_t)

    crane_kn = _parse_crane_load_kn(sections)

    # Load-aware section optimization (AI/ML innovation)
    try:
        from staad_generator.section_optimizer import optimize_sections

        tmp_spec = BuildingSpec(
            span_width_m=span_m,
            eave_height_m=eave_m,
            bay_length_m=bay_len,
            n_bays=n_bay,
            dead_load_kn_m=dl_line,
            live_load_kn_m=ll_line,
            wind_pressure_kn_m2=wind_p,
            purlin_spacing_m=pur_sp,
            fyld_mpa=345.0,
        )
        opt = optimize_sections(tmp_spec)
        col_s = opt["col_section"]
        raf_s = opt["rafter_section"]
        br_s = opt["brace_section"]
        pur_s = opt["purlin_section"]
    except Exception:
        pass

    # Mezzanine parsing
    mezz_kw = _parse_mezzanine(sections, eave_m)

    spec = BuildingSpec(
        name=name,
        n_bays=n_bay,
        bay_length_m=bay_len,
        bay_spacings=bay_list,
        span_width_m=span_m,
        eave_height_m=eave_m,
        roof_slope_ratio=slope_ratio,
        col_section=col_s,
        rafter_section=raf_s,
        brace_section=br_s,
        purlin_section=pur_s,
        girt_section=pur_s,
        e_modulus_mpa=205000.0,
        poisson=0.3,
        density_kn_m3=77.0,
        dead_load_kn_m=dl_line,
        live_load_kn_m=ll_line,
        wind_pressure_kn_m2=wind_p,
        collateral_line_kn_m=collateral_line,
        seismic_ah=ah,
        purlin_spacing_m=pur_sp,
        enable_roof_x_brace=br_on,
        enable_wall_x_brace=br_on,
        enable_purlins=True,
        enable_girts=eave_m >= 4.5,
        enable_endwall_cols=True,
        design_code=design_code,
        defl_frame_vertical=defl_v,
        defl_frame_lateral=defl_l,
        defl_purlin=defl_p,
        crane_load_kn=crane_kn,
        crane_bracket_height_m=round(eave_m * 0.75, 2) if crane_kn > 0 else 0.0,
        **mezz_kw,
    )
    return spec
