"""Bill of Quantities (BOQ) — approximate steel tonnage + costing from frame model."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from staad_generator.geometry import FrameModel
from staad_generator.spec import BuildingSpec

# Approximate kg/m for common AISC W-shapes used in PEB heuristic selection.
_SECTION_KGM: dict[str, float] = {
    "W6X9": 13.4,
    "W6X12": 17.9,
    "W8X10": 14.9,
    "W8X13": 19.3,
    "W8X18": 26.8,
    "W8X24": 35.7,
    "W8X31": 46.1,
    "W10X22": 32.7,
    "W10X26": 38.7,
    "W10X33": 49.1,
    "W10X45": 67.0,
    "W10X54": 80.4,
    "W12X26": 38.7,
    "W12X35": 52.1,
    "W12X40": 59.5,
    "W12X50": 74.4,
    "W12X65": 96.7,
    "W12X79": 117.5,
    "W14X48": 71.4,
    "W14X61": 90.8,
    "W14X82": 122.0,
    "W14X90": 133.9,
    "W14X109": 162.2,
    "W16X50": 74.4,
    "W16X67": 99.7,
    "W18X40": 59.5,
    "W18X55": 81.8,
    "W18X71": 105.7,
    "W21X50": 74.4,
    "W21X62": 92.3,
    "W21X83": 123.5,
    "W24X62": 92.3,
    "W24X76": 113.1,
    "W24X94": 139.9,
}

# Regional steel rates: (currency_symbol, rate_per_kg)
_STEEL_RATES: dict[str, tuple[str, float]] = {
    "IS800 LSD": ("₹", 70.0),
    "AISC UNIFIED 2010": ("$", 1.20),
    "AISC UNIFIED 2016": ("$", 1.25),
}
_DEFAULT_RATE = ("$", 1.20)


def _section_kgm(name: str) -> float:
    n = name.upper().replace(" ", "")
    if n in _SECTION_KGM:
        return _SECTION_KGM[n]
    m = re.search(r"X(\d+)", n)
    if m:
        return float(m.group(1)) * 1.488
    return 50.0


def _member_length(fm: FrameModel, mid: int, n1: int, n2: int) -> float:
    j = fm.joint_coords
    if n1 not in j or n2 not in j:
        return 0.0
    x1, y1, z1 = j[n1]
    x2, y2, z2 = j[n2]
    return math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2 + (z2 - z1) ** 2)


@dataclass
class SectionDetail:
    """Per-kind breakdown with section name, total length, and total weight."""
    section: str
    total_length_m: float
    total_weight_kg: float
    unit_weight_kgm: float
    count: int


_SYSTEM_GROUPS: dict[str, list[str]] = {
    "Primary Frames": ["column", "haunch", "rafter", "eave_long", "ridge_long", "endwall_col"],
    "Secondary Members": ["purlin", "girt"],
    "Bracing": ["roof_brace", "wall_brace", "portal_brace"],
    "Crane System": ["crane_beam"],
    "Mezzanine": ["mezz_col", "mezz_beam", "mezz_long"],
    "Accessories": ["canopy", "opening_jamb", "jack_beam", "cage_ladder"],
    "Mezzanine Joists": ["joist"],
}

FABRICATION_ALLOWANCE = 0.10


@dataclass
class BOQSummary:
    total_kg: float
    total_tonnes: float
    by_kind: dict[str, float]
    member_count: int
    total_length_m: float
    cost_per_kg: float = 0.0
    total_cost: float = 0.0
    cost_by_kind: dict[str, float] = field(default_factory=dict)
    currency: str = "$"
    sections_detail: dict[str, SectionDetail] = field(default_factory=dict)
    by_system: dict[str, float] = field(default_factory=dict)
    fabrication_kg: float = 0.0


def estimate_boq(spec: BuildingSpec, fm: FrameModel) -> BOQSummary:
    kind_section = {
        "column": spec.col_section,
        "haunch": spec.rafter_section,
        "rafter": spec.rafter_section,
        "eave_long": spec.brace_section,
        "ridge_long": spec.brace_section,
        "purlin": spec.purlin_section,
        "girt": spec.girt_section,
        "roof_brace": spec.brace_section,
        "wall_brace": spec.brace_section,
        "endwall_col": spec.col_section,
        "mezz_col": spec.mezz_col_section,
        "mezz_beam": spec.mezz_beam_section,
        "mezz_long": spec.mezz_beam_section,
        "crane_beam": spec.crane_beam_section,
        "portal_brace": spec.brace_section,
        "canopy": spec.canopy_section,
        "opening_jamb": spec.col_section,
        "jack_beam": spec.jack_beam_section,
        "joist": spec.joist_section,
        "cage_ladder": spec.girt_section,
    }
    by_kind: dict[str, float] = {}
    kind_len: dict[str, float] = {}
    kind_count: dict[str, int] = {}
    total_len = 0.0

    for mid, n1, n2, kind in fm.members:
        length = _member_length(fm, mid, n1, n2)
        total_len += length
        sec = kind_section.get(kind, spec.brace_section)
        kg = _section_kgm(sec) * length
        by_kind[kind] = by_kind.get(kind, 0.0) + kg
        kind_len[kind] = kind_len.get(kind, 0.0) + length
        kind_count[kind] = kind_count.get(kind, 0) + 1

    member_kg = sum(by_kind.values())
    fab_kg = round(member_kg * FABRICATION_ALLOWANCE, 1)
    total_kg = round(member_kg + fab_kg, 1)

    # Group by structural system
    by_system: dict[str, float] = {}
    for sys_name, kinds_in_sys in _SYSTEM_GROUPS.items():
        sys_kg = sum(by_kind.get(k, 0.0) for k in kinds_in_sys)
        if sys_kg > 0:
            by_system[sys_name] = round(sys_kg, 1)
    if fab_kg > 0:
        by_system["Fabrication/Connections"] = fab_kg

    currency, rate = _STEEL_RATES.get(spec.design_code, _DEFAULT_RATE)
    total_cost = total_kg * rate
    cost_by_kind = {k: round(v * rate, 2) for k, v in by_kind.items()}

    sections_detail: dict[str, SectionDetail] = {}
    for kind in by_kind:
        sec = kind_section.get(kind, spec.brace_section)
        sections_detail[kind] = SectionDetail(
            section=sec,
            total_length_m=round(kind_len.get(kind, 0.0), 1),
            total_weight_kg=round(by_kind[kind], 1),
            unit_weight_kgm=round(_section_kgm(sec), 2),
            count=kind_count.get(kind, 0),
        )

    return BOQSummary(
        total_kg=total_kg,
        total_tonnes=round(total_kg / 1000.0, 2),
        by_kind={k: round(v, 1) for k, v in sorted(by_kind.items())},
        member_count=len(fm.members),
        total_length_m=round(total_len, 1),
        cost_per_kg=rate,
        total_cost=round(total_cost, 2),
        cost_by_kind=cost_by_kind,
        currency=currency,
        sections_detail=sections_detail,
        by_system=by_system,
        fabrication_kg=fab_kg,
    )


def format_boq(boq: BOQSummary) -> str:
    lines = [
        f"Steel BOQ Estimate: {boq.total_tonnes:.2f} tonnes ({boq.total_kg:.0f} kg)",
        f"  Members: {boq.member_count}  Total length: {boq.total_length_m:.1f} m",
        f"  Fabrication/Connections allowance ({FABRICATION_ALLOWANCE:.0%}): {boq.fabrication_kg:.0f} kg",
        f"  Estimated Cost: {boq.currency}{boq.total_cost:,.2f} @ {boq.currency}{boq.cost_per_kg}/kg",
        "",
        "  System Summary:",
    ]
    for sys_name, sys_kg in boq.by_system.items():
        pct = sys_kg / boq.total_kg * 100 if boq.total_kg > 0 else 0
        lines.append(f"    {sys_name:30s} {sys_kg:8.1f} kg  ({pct:5.1f}%)")

    lines.extend(["", "  Weight Breakdown by Member Kind:"])
    for kind, kg in boq.by_kind.items():
        pct = kg / boq.total_kg * 100 if boq.total_kg > 0 else 0
        cost = boq.cost_by_kind.get(kind, 0.0)
        sd = boq.sections_detail.get(kind)
        sec_str = f"  [{sd.section}]" if sd else ""
        lines.append(f"    {kind:20s} {kg:8.1f} kg  ({pct:5.1f}%)  {boq.currency}{cost:>10,.2f}{sec_str}")

    if boq.sections_detail:
        lines.extend(["", "  Section Details:"])
        for kind, sd in sorted(boq.sections_detail.items()):
            lines.append(
                f"    {kind:20s}  {sd.section:12s}  {sd.count:3d} memb  "
                f"{sd.total_length_m:8.1f} m  {sd.unit_weight_kgm:.1f} kg/m"
            )

    return "\n".join(lines)
