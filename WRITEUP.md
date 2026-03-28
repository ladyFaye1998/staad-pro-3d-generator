# AI-Powered STAAD.Pro 3D Generator
## Deterministic Pipeline for Production-Ready PEB Models from QRF JSON

---

## 1. Introduction

This project presents a fully automated pipeline that converts SIJCON-style QRF JSON documents into complete, production-ready STAAD.Pro `.std` command files for Pre-Engineered Building (PEB) structures. The pipeline handles the full workflow: input parsing, 3D geometry generation, load application, steel design checks, section optimization, serviceability verification, and BOQ estimation — in under 2 seconds per building.

## 2. Methodology

### 2.1 Architecture Overview

```
QRF JSON → ai_parser (LLM) + qrf.py (regex) → BuildingSpec
    → section_optimizer (load-aware AISC selection) → optimized sections
    → build_frame() → FrameModel (haunches, crane beams, portal bracing, mezzanine, canopy, framed openings, jack beams)
    → validate_frame() → build_std_text() → .std file (tapered sections, RATIO 0.95)
    → fea_verify() → PyNite FEA verification (iterative UR + deflection check)
    → estimate_boq() → Steel Tonnage + Regional Costing
```

Each stage is a pure function — deterministic, testable, and auditable.

### 2.2 QRF Parsing (`qrf.py`)

SIJCON-format JSON files use deeply nested, inconsistent schemas. Key parsing innovations:

- **Bracket notation parser**: Handles `[5@8.700 m]` patterns for non-uniform bay spacings.
- **Dimension disambiguation**: Distinguishes overall dimensions (`"24380 O/O"`) from center-to-center spacings using proximity-weighted regex.
- **Fuzzy row matching**: Falls back to substring matching when exact keys don't match.
- **Seismic zone parser**: Handles `"Zone III"`, `"Zone: IV"`, `"II"`, `"Zone 3"` and strips irrelevant IS standard references.
- **Wind pressure derivation**: Converts wind speed (m/s) to pressure via `p = 0.613 × v²`.
- **Design code detection**: Maps IS 800, AISC, MBMA mentions to STAAD-compatible code strings.
- **Deflection limit parsing**: Extracts `L/240`, `H/150` patterns with context-aware assignment to vertical, lateral, and purlin categories.

### 2.3 AI/ML: LLM-Assisted Parsing (`ai_parser.py`)

QRF mezzanine descriptions vary wildly. A hybrid LLM + regex parser:
1. Sends raw mezzanine rows to **Hugging Face Inference API** (Qwen2.5-Coder-32B-Instruct) with a structured extraction prompt.
2. Extracts elevation, width, length, live/dead loads, and column spacing.
3. Falls back to regex if the API is unavailable — ensuring offline reliability.
4. Caches results as JSON sidecar files.

### 2.4 AI/ML: Load-Aware Section Optimizer (`section_optimizer.py`)

Uses simplified structural analysis for initial section selection:
1. Internal AISC W-shape catalog (~34 sections) with Zx, Ix, area, weight.
2. Estimates bending demand via the portal method: rafter M = w_u × L²/8, column M from stiffness ratio.
3. Selects the lightest section targeting UR ≈ 0.9 before STAAD further optimizes with `RATIO 0.95`.

### 2.5 Geometry Generation (`geometry.py`)

The engine produces a complete, **fully connected** 3D structural model with zero disconnected joints (verified by graph connectivity test):

**Primary structure:** Portal frames at each bay line with split columns and rafters — every secondary attachment point (purlin, girt, crane bracket, portal brace knee) is an intermediate node on the parent member, ensuring a single connected structural system.

**Haunches:** Tapered deeper members at every column–rafter eave junction (~10% of rafter span). Haunches use TAPERED properties 2.2× rafter depth at the eave end, tapering to 1.5× at the haunch tip — matching real PEB fabrication practice.

**Secondary structure:** Purlins at parametric positions along each roof face; multiple wall girt rows (count varies with eave height — up to 4 rows for tall buildings); endwall columns extending to roof slope and connected to rafter intermediate joints.

**Bracing:** Roof X-braces (first/last bays), sidewall X-braces, portal knee braces at column–rafter junctions.

**Crane beams:** Longitudinal beams at bracket height on both sidewalls when crane load > 0.

**Mezzanine floor:** Columns, transverse beams, longitudinal ties. Base joints are merged with existing portal frame bases to ensure structural continuity.

**Canopy:** Overhang beams extending beyond the Z=0 sidewall at the entrance bay, creating a covered entrance area. Connected to existing eave joints at the portal frames.

**Framed openings & jack beams:** Vertical jamb columns at each side of the opening, with a horizontal jack beam (header) spanning above the opening and connecting to adjacent portal frame eave joints. This creates a proper load path around door/window openings.

**Floor joists:** Intermediate Z-direction members within each mezzanine bay at ~1.5 m spacing, supporting the floor slab between main transverse beams.

**Cage ladder:** Vertical access ladder on the Z=W sidewall near the last bay, modeled as stringer members with ties back to the building frame at base and eave.

### 2.6 Validation (`validate.py`)

Every model undergoes pre-flight checks: duplicate member IDs, missing joints, zero-length members, dangling joints. Failures raise `FrameValidationError` before any .std output.

### 2.7 FEA Verification (`fea_verify.py`)

Independent FEA verification using PyNite:
1. Single-bay 2D portal frame with actual dimensions.
2. Factored loads (LRFD: 1.2D + 1.6L) and SLS loads.
3. Unity Ratio: UR = M/Mp + P/Py with iterative section optimization.
4. Converges in 2–8 iterations; all 7 buildings pass with UR 0.29–0.72.

### 2.8 STAAD.Pro Output (`writer.py`)

The writer emits a complete .std file following strict STAAD.Pro syntax:

**Structure:** `STAAD SPACE` as the first command, `START JOB INFORMATION`, `INPUT WIDTH 79`, `JOINT COORDINATES`, `MEMBER INCIDENCES`, `START GROUP DEFINITION` / `MEMBER` / `END GROUP DEFINITION`, `DEFINE MATERIAL START` / `ISOTROPIC STEEL`, `MEMBER PROPERTY AMERICAN` (with `TAPERED` for haunches, PEB columns, and rafters), `SUPPORTS` (FIXED), `MEMBER TRUSS` (inline member list) with `MEMBER RELEASE` for braces.

**Loading — up to 10 Primary Load Cases:**
1. **Dead Load**: Self-weight + superimposed dead.
2. **Live Load**: Roof live on rafters and purlins.
3. **Wind +Z**: Transverse pressure/suction.
4. **Wind -Z**: Reverse transverse.
5. **Wind +X**: Longitudinal on endwalls/sidewalls.
6. **Wind -X**: Reverse longitudinal.
7. **Seismic +X**: Base shear at eave joints (IS 1893 / ASCE 7).
8. **Seismic -X**: Reverse seismic direction.
9. **Crane/Hoist** (when applicable).
10. **Mezzanine Dead + Live** (when applicable).

**Load Combinations — 17+ LRFD per ASCE 7-16 / IS 875:**
- `1.4D`, `1.2D + 1.6L`
- `1.2D + 1.0L ± 1.0W` (transverse both directions)
- `1.2D + 1.6L + 0.5W` (both transverse directions)
- `0.9D ± 1.0W` (transverse and longitudinal — 4 combos for uplift)
- `1.2D + 1.0L ± 1.0WX` (longitudinal both directions)
- `1.2D ± 1.0E + 1.0L`, `0.9D ± 1.0E` (both seismic directions)
- Crane combinations, SLS combos (D+L, D+L+Wz, D+L+Wx)

**Steel Design — 4-Stage Workflow with Re-Analysis:**
1. `PERFORM ANALYSIS PRINT STATICS CHECK` — initial analysis.
2. `PARAMETER 1`: CHECK CODE with TRACK 2, RATIO 1.0.
3. `PARAMETER 2`: SELECT with RATIO 0.95 (UR 0.9–1.0 targeting).
4. `PARAMETER 3`: Serviceability under SLS with per-group DFF values.
5. `PERFORM ANALYSIS` — **re-analysis with optimized sections**.
6. `PARAMETER 4`: Final CHECK CODE on all members — verifying post-optimization results.

### 2.9 BOQ Estimation (`boq.py`)

Steel BOQ with **system-level grouping** (Primary Frames incl. haunches, Secondary Members, Bracing, Crane System, Mezzanine, Mezzanine Joists, Accessories incl. canopy/jambs/jack beams/cage ladder) and a **10% fabrication/connections allowance** for gusset plates, base plates, bolts, and splices. Regional costing auto-selects rates per design code (IS 800 → ₹70/kg, AISC → $1.20/kg). Per-kind section details: section name, member count, total length, unit weight.

## 3. Challenges Solved

**Structural connectivity:** Purlins, girts, crane beams, and portal braces all attach to intermediate joints that are inserted into the parent column/rafter members. This eliminates the common modeling error of disconnected structural subsystems, verified by a graph connectivity test ensuring zero disconnected joints across all models.

**Heterogeneous inputs:** Multi-layered parsing (exact key → fuzzy substring → regex → defaults) handles inconsistent field names, units, and notation.

**Non-uniform bays:** Bracket notation `[1@7.115 m] [5@8.700 m]` places each portal frame at the exact specified X position.

**Multi-directional wind:** Four wind cases (±Z transverse, ±X longitudinal) with appropriate pressure/suction coefficients ensure bracing is properly designed.

**Multi-directional seismic:** Both ±X seismic cases per IS 1893 / ASCE 7 requirements.

**PEB haunch detailing:** Tapered haunches at every eave connection with deeper sections matching industry practice for moment-resistant PEB connections.

## 4. Results

### 4.1 Competition File Conversion

All 6 competition files convert successfully with zero disconnected joints:

| File | Joints | Members | Steel (t) | Design Code |
|------|--------|---------|-----------|-------------|
| BulkStore | 628 | 1126 | 174.39 | AISC UNIFIED 2010 |
| Jebel_Ali_Industrial_Area | 262 | 436 | 47.47 | AISC UNIFIED 2010 |
| knitting-plant | 548 | 781 | 178.49 | AISC UNIFIED 2010 |
| RMStore | 289 | 519 | 75.30 | AISC UNIFIED 2010 |
| RSC-ARC-101-R0_AISC | 680 | 1168 | 106.51 | AISC UNIFIED 2010 |
| S-2447-BANSWARA | 209 | 361 | 32.27 | IS800 LSD |

### 4.2 Unity Ratio & Deflection

The 4-stage design workflow (CHECK → SELECT → re-ANALYSIS → final CHECK) with `RATIO 0.95` targets UR 0.9–1.0. Deflection limits parsed per QRF (L/240, L/180, L/360) applied per member group under isolated SLS combinations.

### 4.3 BOQ Accuracy

Benchmarked against MBMA/AISC Design Guide 24 (15–40 kg/m² for standard, 25–55 kg/m² for crane buildings). All 6 files fall within industry ranges. The 10% fabrication allowance brings totals to realistic project-level estimates.

### 4.4 Test Suite

36 pytest tests: smoke tests on all 7 files, golden hash determinism, FEA verification, crane beams, portal bracing, haunch members, tapered sections, longitudinal wind, multiple girt rows, BOQ system groups, structural connectivity, canopy members, framed openings with jack beams, accessories connectivity, mezzanine joists, cage ladder, parser unit tests, validation edge cases.

## 5. Interactive Web Application

A Gradio app (`app.py`) provides upload/select, interactive 3D wireframe (Plotly), building spec table, BOQ chart, and .std download. A static **[GitHub Pages demo](https://ladyfaye1998.github.io/staad-pro-3d-generator/)** is also available.

## 6. Reproducibility

```bash
git clone https://github.com/ladyFaye1998/staad-pro-3d-generator.git && cd staad-pro-3d-generator
pip install -e ".[dev]"
pip install gradio plotly
python app.py          # Web app at http://127.0.0.1:7860
python -m staad_generator --verbose  # CLI batch conversion
pytest -v              # 36 tests
```

---

*Built with Python 3.10+. AI features powered by Hugging Face Inference API. FEA verification powered by PyNite.*
