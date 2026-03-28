# Video Demo Script (≤ 3 minutes)

Record your screen while running these commands. Use a large terminal font.

---

## Scene 1: Intro (15 sec)
Open the terminal. Say/show:

> "This is the STAAD.Pro 3D Generator — it converts QRF JSON to production-ready .std files."

## Scene 2: Show input (30 sec)
```
type data\S-2447-BANSWARA.json | python -m json.tool | more
```
Scroll through briefly to show the nested QRF structure.
Point out: "This is a SIJCON QRF form — building parameters, design loads, all in messy JSON."

## Scene 3: Single file conversion (30 sec)
```
python -m staad_generator --one data/S-2447-BANSWARA.json -v
```
Show it completes in 0.01s. Highlight: "146 joints, 149 members, instant."

## Scene 4: Show the output (30 sec)
```
more output\S-2447-BANSWARA.std
```
Scroll through showing:
- Header + joint coordinates
- Member incidences
- Load cases (Dead, Live, Wind, Seismic)
- Load combinations
- CHECK CODE / SELECT / DFF / FINISH

Say: "Full design workflow — analysis, unity ratio, optimization, serviceability."

## Scene 5: Batch conversion (20 sec)
```
python -m staad_generator --verbose
```
Show all 7 files converting. Point at the summary table.

## Scene 6: BOQ (20 sec)
```
python -c "from pathlib import Path; from staad_generator.spec import spec_from_json_path; from staad_generator.geometry import build_frame; from staad_generator.boq import estimate_boq, format_boq; s=spec_from_json_path(Path('data/S-2447-BANSWARA.json')); print(format_boq(estimate_boq(s, build_frame(s))))"
```
Show the tonnage breakdown.

## Scene 7: Tests (15 sec)
```
python -m pytest tests/ -v
```
Show 18/18 passing.

## Scene 8: Closing (10 sec)
> "Zero dependencies. Handles any QRF format. Production-ready .std output."

---

**Total: ~2.5 minutes**

Upload to YouTube as unlisted. Paste the link in the submission.
