# Video Script — STAAD.Pro 3D Generator (≤ 3 minutes)

---

## INTRO — 15 seconds

**Say:**
> "Hi, I'm presenting my STAAD.Pro 3D Generator — an AI-powered pipeline that converts QRF JSON files into production-ready .std files with mezzanine support, UR targeting between 0.9 and 1.0, and full BOQ with costing. Let me show you how it works."

**Show on screen:** The GitHub repo README — scroll slowly past the title, badges, and capability table.

---

## PART 1: LIVE DEMO — 50 seconds

**Say:**
> "First, the live demo. This is hosted on GitHub Pages — no installation needed."

**Action:** Open https://ladyfaye1998.github.io/staad-pro-3d-generator/

**Say:**
> "I'll select the Jebel Ali Industrial Area building. You can see the building spec on the left — 45 meters long, 30 meters wide, 7 bays. Notice it detected a 10 by 20 meter mezzanine at 2.5 meters elevation."

**Action:** Select "Jebel_Ali_Industrial_Area" from dropdown. Point at the mezzanine row in the spec table.

**Say:**
> "The 3D wireframe shows the full model — columns in blue, rafters in red, purlins in green, and the mezzanine members in pink. You can rotate and zoom."

**Action:** Rotate the 3D model to show the mezzanine floor clearly. Zoom in on the mezzanine area.

**Say:**
> "The BOQ chart shows 39.62 tonnes of steel with a cost estimate of about $47,500 at $1.20 per kilogram. Below that, you can preview the .std file — all load cases, combinations, and design commands are there."

**Action:** Scroll down to show the BOQ chart and .std preview. Point at `MEZZANINE DEAD LOAD` and `MEZZANINE LIVE LOAD` in the preview.

---

## PART 2: CLI + CODE — 40 seconds

**Say:**
> "Now let me show the command line. One command converts all 6 competition files."

**Action:** Open terminal in the project directory. Run:

```
python -m staad_generator --verbose
```

**Say:**
> "Each file generates in under a second. You can see the parsed specs — bays, heights, loads — and the mezzanine details when present."

**Action:** Let the output scroll. Point at a line showing mezzanine info.

**Say:**
> "We can also check a single file. The .std output includes a 4-stage design workflow: initial check, SELECT optimization with RATIO 0.95 targeting UR 0.9 to 1.0, serviceability check, and final verification."

**Action:** Run:

```
python -m staad_generator --one data/S-2447-BANSWARA.json -v
```

---

## PART 3: INNOVATION — 40 seconds

**Say:**
> "What makes this pipeline special is the AI/ML innovation. First, the section optimizer uses a 34-section AISC W-shape catalog with simplified portal-frame analysis to pick sections that target a utilization ratio of 0.9 — not oversized, not undersized."

**Action:** Briefly show `section_optimizer.py` in the editor (scroll past the AISC table).

**Say:**
> "Second, the AI parser uses Hugging Face's Inference API to extract mezzanine data from free-text QRF descriptions that vary wildly between projects. It falls back to regex if the API is unavailable, so the pipeline always works offline."

**Action:** Briefly show `ai_parser.py` — the LLM prompt and the regex fallback.

**Say:**
> "And the BOQ now includes realistic costing — 70 rupees per kilo for IS 800 projects, $1.20 per kilo for AISC — with a complete section-by-section breakdown."

---

## PART 4: TESTS + CLOSE — 25 seconds

**Say:**
> "All 21 tests pass — including new tests for mezzanine geometry, the section optimizer, and BOQ costing."

**Action:** Run:

```
python -m pytest tests/ -v
```

**Say:**
> "Six competition files, all converting successfully, all within industry steel benchmarks, all with a complete 4-stage design workflow targeting UR between 0.9 and 1.0. Thank you."

**Action:** Show the test output (21 passed), then cut to the GitHub repo or the 3D demo as a closing shot.

---

## Timing Summary

| Section        | Duration |
|----------------|----------|
| Intro          | 15s      |
| Live demo      | 50s      |
| CLI + code     | 40s      |
| Innovation     | 40s      |
| Tests + close  | 25s      |
| **Total**      | **~2:50**|

---

## Key Rubric Points to Hit

- **Correctness:** Show .std preview with valid STAAD commands
- **Completeness:** Show mezzanine in 3D viewer + load cases in preview
- **Accuracy:** Mention RATIO 0.95 and UR 0.9–1.0 targeting
- **Innovation:** Show ai_parser.py (LLM) and section_optimizer.py
- **BOQ Bonus:** Show costing in BOQ chart and mention regional rates
- **Documentation:** The video itself + notebook + writeup + live demo
