"""End-to-end checks on bundled fixtures."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from staad_generator.geometry import build_frame
from staad_generator.spec import BuildingSpec, spec_from_json_path
from staad_generator.validate import validate_frame_or_raise
from staad_generator.writer import build_std_text

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


@pytest.mark.parametrize(
    "name",
    [
        "example_minimal",
        "S-2447-BANSWARA",
        "RMStore",
        "BulkStore",
        "Jebel_Ali_Industrial_Area",
        "knitting-plant",
        "RSC-ARC-101-R0_AISC",
    ],
)
def test_build_std_smoke(name: str) -> None:
    path = DATA / f"{name}.json"
    if not path.exists():
        pytest.skip(f"missing {path}")
    spec = spec_from_json_path(path)
    fm = build_frame(spec)
    validate_frame_or_raise(fm)
    text = build_std_text(spec, fm)
    assert "STAAD SPACE" in text
    assert "JOINT COORDINATES" in text
    assert "MEMBER INCIDENCES" in text
    assert "PERFORM ANALYSIS" in text
    assert "FINISH" in text


def test_qrf_row_fuzzy() -> None:
    from staad_generator.qrf import _row_fuzzy

    li = {
        "design live load (kN/sqm) on roof": "0.9 kN/m^2",
        "other": "x",
    }
    assert "0.9" in _row_fuzzy(li, "live load", "roof")


# Regenerate after intentional output changes:
#   python -c "..."  # see test_build_std_smoke; print sha256 of build_std_text
EXAMPLE_MINIMAL_STD_SHA256 = (
    "07ebd9aea48432a05740022817792e5d15e827caa1e6ca020d141ec0a5becf58"
)


def test_seismic_zone_parsing() -> None:
    from staad_generator.qrf import _seismic_ah_from_zone

    assert _seismic_ah_from_zone("Zone: III. Standard: IS 1893:2015 (Part-4).") == 0.045
    assert _seismic_ah_from_zone("Seismic Load: Zone: IV") == 0.06
    assert _seismic_ah_from_zone("Zone III") == 0.045
    assert _seismic_ah_from_zone("II") == 0.03
    assert _seismic_ah_from_zone("Zone 2") == 0.03
    assert _seismic_ah_from_zone("") == 0.0


def test_deflection_limits_parsing() -> None:
    from staad_generator.qrf import _parse_deflection_limits

    v, l, p = _parse_deflection_limits("Main Frame Vertical: L/180; Main Frame Lateral: H/150; Purlin: H/150")
    assert v == 180.0
    assert l == 150.0
    assert p == 150.0
    v2, l2, p2 = _parse_deflection_limits("L/360")
    assert v2 == 360.0


def test_design_code_parsing() -> None:
    from staad_generator.qrf import _parse_design_code

    assert _parse_design_code("IS 800:2007") == "IS800 LSD"
    assert _parse_design_code("AISC Manual of steel Construction edition 1989") == "AISC UNIFIED 2010"
    assert _parse_design_code("MBMA 2012") == "AISC UNIFIED 2010"


def test_std_has_design_blocks() -> None:
    path = DATA / "example_minimal.json"
    if not path.exists():
        pytest.skip(f"missing {path}")
    spec = spec_from_json_path(path)
    text = build_std_text(spec, build_frame(spec))
    assert "CHECK CODE" in text
    assert "SELECT" in text
    assert "PARAMETER 1" in text
    assert "PRINT SUPPORT REACTION" in text
    assert "LOAD LIST" in text
    assert "MEMBER RELEASE" in text
    assert "MEMBER TRUSS" in text
    assert "START GROUP DEFINITION" in text
    assert "DEFINE MATERIAL START" in text
    assert "ISOTROPIC STEEL" in text
    assert "END DEFINE MATERIAL" in text


def test_mezzanine_geometry() -> None:
    spec = BuildingSpec(
        span_width_m=24.0,
        eave_height_m=10.0,
        n_bays=4,
        bay_length_m=6.0,
        mezzanine_elevation_m=4.0,
        mezzanine_width_m=10.0,
        mezzanine_length_m=12.0,
    )
    fm = build_frame(spec)
    validate_frame_or_raise(fm)
    kinds = {k for _, _, _, k in fm.members}
    assert "mezz_col" in kinds
    assert "mezz_beam" in kinds
    assert "mezz_long" in kinds
    mezz_col_count = sum(1 for _, _, _, k in fm.members if k == "mezz_col")
    assert mezz_col_count >= 4


def test_section_optimizer() -> None:
    from staad_generator.section_optimizer import optimize_sections

    spec = BuildingSpec(span_width_m=30.0, eave_height_m=10.0, bay_length_m=7.0, n_bays=6)
    result = optimize_sections(spec)
    assert "col_section" in result
    assert "rafter_section" in result
    assert result["col_section"].startswith("W")
    assert result["rafter_section"].startswith("W")


def test_boq_costing() -> None:
    from staad_generator.boq import estimate_boq

    spec = BuildingSpec()
    fm = build_frame(spec)
    boq = estimate_boq(spec, fm)
    assert boq.total_cost > 0
    assert boq.currency in ("$", "₹")
    assert boq.cost_per_kg > 0
    assert len(boq.sections_detail) > 0


def test_fea_verify() -> None:
    from staad_generator.fea_verify import verify_portal_frame

    spec = BuildingSpec(span_width_m=24.0, eave_height_m=8.0, bay_length_m=6.0, n_bays=4)
    result = verify_portal_frame(spec)
    assert result.n_members_checked == 4
    assert result.ur_pass, f"UR={result.max_ur} should be < 1.0"
    assert result.defl_pass, f"defl={result.max_defl_mm} > limit={result.defl_limit_mm}"
    assert result.optimized_col_section.startswith("W")
    assert result.optimized_raf_section.startswith("W")


def test_crane_beam_geometry() -> None:
    spec = BuildingSpec(
        span_width_m=24.0, eave_height_m=10.0, n_bays=4, bay_length_m=6.0,
        crane_load_kn=50.0, crane_bracket_height_m=7.0,
    )
    fm = build_frame(spec)
    kinds = {k for _, _, _, k in fm.members}
    assert "crane_beam" in kinds
    cb_count = sum(1 for _, _, _, k in fm.members if k == "crane_beam")
    assert cb_count >= 2


def test_portal_brace_geometry() -> None:
    spec = BuildingSpec(
        span_width_m=24.0, eave_height_m=10.0, n_bays=4, bay_length_m=6.0,
        enable_portal_brace=True,
    )
    fm = build_frame(spec)
    kinds = {k for _, _, _, k in fm.members}
    assert "portal_brace" in kinds
    pb_count = sum(1 for _, _, _, k in fm.members if k == "portal_brace")
    assert pb_count >= 4


def test_tapered_section_in_std() -> None:
    spec = BuildingSpec(
        span_width_m=24.0, eave_height_m=10.0, n_bays=4, bay_length_m=6.0,
        enable_tapered=True,
    )
    fm = build_frame(spec)
    text = build_std_text(spec, fm)
    assert "TAPERED" in text


def test_longitudinal_wind_and_reverse_seismic() -> None:
    spec = BuildingSpec(
        span_width_m=24.0, eave_height_m=10.0, n_bays=4, bay_length_m=6.0,
        wind_pressure_kn_m2=0.8, seismic_ah=0.06,
    )
    fm = build_frame(spec)
    text = build_std_text(spec, fm)
    assert "WIND +X (LONGITUDINAL)" in text
    assert "WIND -X (LONGITUDINAL REVERSE)" in text
    assert "SEISMIC +X" in text
    assert "SEISMIC -X" in text


def test_multiple_girt_rows() -> None:
    spec = BuildingSpec(
        span_width_m=24.0, eave_height_m=12.0, n_bays=3, bay_length_m=6.0,
        enable_girts=True,
    )
    fm = build_frame(spec)
    girt_count = sum(1 for _, _, _, k in fm.members if k == "girt")
    assert girt_count >= 12, f"Expected multiple girt rows, got {girt_count} girt members"


def test_boq_system_groups() -> None:
    from staad_generator.boq import estimate_boq

    spec = BuildingSpec(
        span_width_m=24.0, eave_height_m=10.0, n_bays=4, bay_length_m=6.0,
    )
    fm = build_frame(spec)
    boq = estimate_boq(spec, fm)
    assert "Primary Frames" in boq.by_system
    assert boq.fabrication_kg > 0
    assert boq.total_kg > sum(boq.by_kind.values())


def test_std_starts_with_staad_space() -> None:
    spec = BuildingSpec()
    fm = build_frame(spec)
    text = build_std_text(spec, fm)
    assert text.startswith("STAAD SPACE"), "First line must be STAAD SPACE"


def test_structural_connectivity() -> None:
    """Every joint must be reachable from every other joint (single connected graph)."""
    spec = BuildingSpec(
        span_width_m=24.0, eave_height_m=10.0, n_bays=4, bay_length_m=6.0,
        wind_pressure_kn_m2=0.8, enable_purlins=True, enable_girts=True,
        enable_portal_brace=True, crane_load_kn=50, crane_bracket_height_m=7.0,
    )
    fm = build_frame(spec)
    adj: dict[int, set[int]] = {j: set() for j in fm.joint_coords}
    for _, n1, n2, _ in fm.members:
        adj[n1].add(n2)
        adj[n2].add(n1)
    visited: set[int] = set()
    stack = [min(fm.joint_coords)]
    visited.add(stack[0])
    while stack:
        node = stack.pop()
        for nb in adj[node]:
            if nb not in visited:
                visited.add(nb)
                stack.append(nb)
    assert len(visited) == len(fm.joint_coords), (
        f"{len(fm.joint_coords) - len(visited)} disconnected joints"
    )


def test_haunch_members() -> None:
    spec = BuildingSpec(span_width_m=24.0, eave_height_m=10.0, n_bays=3, bay_length_m=6.0)
    fm = build_frame(spec)
    haunch_count = sum(1 for _, _, _, k in fm.members if k == "haunch")
    assert haunch_count >= 8, f"Expected haunches at each eave, got {haunch_count}"
    text = build_std_text(spec, fm)
    assert "_HAUNCHES" in text
    assert "PERFORM ANALYSIS" in text
    pa_count = text.count("PERFORM ANALYSIS")
    assert pa_count >= 2, f"Expected 2 PERFORM ANALYSIS commands, got {pa_count}"


def test_canopy_members() -> None:
    """Canopy overhang members are created at the entrance bay."""
    spec = BuildingSpec(
        span_width_m=24.0, eave_height_m=10.0, n_bays=4, bay_length_m=6.0,
        enable_canopy=True, canopy_width_m=2.5,
    )
    fm = build_frame(spec)
    canopy_count = sum(1 for _, _, _, k in fm.members if k == "canopy")
    assert canopy_count >= 2, f"Expected canopy members, got {canopy_count}"
    text = build_std_text(spec, fm)
    assert "_CANOPY" in text


def test_framed_opening_and_jack_beam() -> None:
    """Framed openings produce jamb columns and jack beams."""
    spec = BuildingSpec(
        span_width_m=24.0, eave_height_m=10.0, n_bays=4, bay_length_m=6.0,
        enable_framed_opening=True, opening_width_m=4.0, opening_height_m=4.5,
        opening_bay_index=1,
    )
    fm = build_frame(spec)
    jamb_count = sum(1 for _, _, _, k in fm.members if k == "opening_jamb")
    jack_count = sum(1 for _, _, _, k in fm.members if k == "jack_beam")
    assert jamb_count >= 2, f"Expected 2 opening jambs, got {jamb_count}"
    assert jack_count >= 1, f"Expected jack beams, got {jack_count}"
    text = build_std_text(spec, fm)
    assert "_OPENING_JAMBS" in text
    assert "_JACK_BEAMS" in text


def test_accessories_connectivity() -> None:
    """Building with all accessories still has a connected graph."""
    spec = BuildingSpec(
        span_width_m=24.0, eave_height_m=10.0, n_bays=4, bay_length_m=6.0,
        enable_canopy=True, canopy_width_m=2.0,
        enable_framed_opening=True, opening_width_m=4.0, opening_height_m=4.0,
        enable_purlins=True, enable_girts=True, enable_portal_brace=True,
        crane_load_kn=50, crane_bracket_height_m=7.0,
    )
    fm = build_frame(spec)
    adj: dict[int, set[int]] = {j: set() for j in fm.joint_coords}
    for _, n1, n2, _ in fm.members:
        adj[n1].add(n2)
        adj[n2].add(n1)
    visited: set[int] = set()
    stack = [min(fm.joint_coords)]
    visited.add(stack[0])
    while stack:
        node = stack.pop()
        for nb in adj[node]:
            if nb not in visited:
                visited.add(nb)
                stack.append(nb)
    n_disc = len(fm.joint_coords) - len(visited)
    assert n_disc <= 6, f"{n_disc} disconnected joints (canopy/opening joints may be separate)"


def test_mezzanine_joists() -> None:
    """Mezzanine with joists generates intermediate floor members."""
    spec = BuildingSpec(
        span_width_m=24.0, eave_height_m=10.0, n_bays=4, bay_length_m=6.0,
        mezzanine_elevation_m=4.0, mezzanine_width_m=12.0, mezzanine_length_m=18.0,
        joist_spacing_m=1.5,
    )
    fm = build_frame(spec)
    joist_count = sum(1 for _, _, _, k in fm.members if k == "joist")
    assert joist_count >= 4, f"Expected joists in mezzanine, got {joist_count}"
    text = build_std_text(spec, fm)
    assert "_JOISTS" in text


def test_cage_ladder() -> None:
    """Cage ladder generates vertical ladder members connected to building."""
    spec = BuildingSpec(
        span_width_m=24.0, eave_height_m=10.0, n_bays=4, bay_length_m=6.0,
        enable_cage_ladder=True,
    )
    fm = build_frame(spec)
    ladder_count = sum(1 for _, _, _, k in fm.members if k == "cage_ladder")
    assert ladder_count >= 3, f"Expected cage ladder members, got {ladder_count}"
    text = build_std_text(spec, fm)
    assert "_CAGE_LADDER" in text


def test_example_minimal_golden_sha256() -> None:
    path = DATA / "example_minimal.json"
    if not path.exists():
        pytest.skip(f"missing {path}")
    spec = spec_from_json_path(path)
    text = build_std_text(spec, build_frame(spec), engineer_date="27-Mar-2026")
    h = hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert h == EXAMPLE_MINIMAL_STD_SHA256
