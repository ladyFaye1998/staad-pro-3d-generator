"""Gradio app — STAAD.Pro 3D Generator: QRF JSON → .std with 3D wireframe."""

from __future__ import annotations

import atexit
import tempfile
from pathlib import Path

_TEMP_FILES: list[str] = []

def _cleanup_temps():
    for f in _TEMP_FILES:
        try:
            Path(f).unlink(missing_ok=True)
        except OSError:
            pass

atexit.register(_cleanup_temps)

import pandas  # noqa: F401 — must import before plotly to avoid circular import bug
import gradio as gr
import plotly.graph_objects as go

from staad_generator._version import __version__
from staad_generator.boq import estimate_boq, format_boq
from staad_generator.geometry import FrameModel, build_frame
from staad_generator.spec import BuildingSpec, format_spec_summary, spec_from_json_path
from staad_generator.validate import FrameValidationError, validate_frame_or_raise
from staad_generator.writer import build_std_text

SAMPLE_DIR = Path("data")

KIND_COLORS: dict[str, str] = {
    "column": "#2563eb",
    "haunch": "#7c3aed",
    "rafter": "#dc2626",
    "eave_long": "#f59e0b",
    "ridge_long": "#f59e0b",
    "purlin": "#10b981",
    "girt": "#8b5cf6",
    "roof_brace": "#f97316",
    "wall_brace": "#f97316",
    "portal_brace": "#ea580c",
    "endwall_col": "#06b6d4",
    "crane_beam": "#0891b2",
    "mezz_col": "#e879f9",
    "mezz_beam": "#fb7185",
    "mezz_long": "#fb7185",
    "canopy": "#14b8a6",
    "opening_jamb": "#a3e635",
    "jack_beam": "#facc15",
    "joist": "#38bdf8",
    "cage_ladder": "#f472b6",
}

KIND_LABELS = {
    "column": "Columns",
    "haunch": "Haunches",
    "rafter": "Rafters",
    "eave_long": "Eave Beams",
    "ridge_long": "Ridge Beams",
    "purlin": "Purlins",
    "girt": "Wall Girts",
    "roof_brace": "Roof Braces",
    "wall_brace": "Wall Braces",
    "portal_brace": "Portal Braces",
    "endwall_col": "Endwall Columns",
    "crane_beam": "Crane Beams",
    "mezz_col": "Mezz Columns",
    "mezz_beam": "Mezz Beams",
    "mezz_long": "Mezz Longitudinal",
    "canopy": "Canopy",
    "opening_jamb": "Opening Jambs",
    "jack_beam": "Jack Beams",
    "joist": "Floor Joists",
    "cage_ladder": "Cage Ladder",
}


def _build_3d_figure(fm: FrameModel, spec: BuildingSpec) -> go.Figure:
    """Build a Plotly 3D wireframe of the frame model."""
    traces_by_kind: dict[str, dict] = {}

    for mid, n1, n2, kind in fm.members:
        if n1 not in fm.joint_coords or n2 not in fm.joint_coords:
            continue
        x1, y1, z1 = fm.joint_coords[n1]
        x2, y2, z2 = fm.joint_coords[n2]

        if kind not in traces_by_kind:
            traces_by_kind[kind] = {"x": [], "y": [], "z": []}
        t = traces_by_kind[kind]
        t["x"].extend([x1, x2, None])
        t["y"].extend([z1, z2, None])
        t["z"].extend([y1, y2, None])

    fig = go.Figure()

    for kind, coords in traces_by_kind.items():
        color = KIND_COLORS.get(kind, "#888888")
        label = KIND_LABELS.get(kind, kind)
        width = 4 if kind in ("column", "rafter") else 2
        fig.add_trace(go.Scatter3d(
            x=coords["x"], y=coords["y"], z=coords["z"],
            mode="lines",
            name=label,
            line=dict(color=color, width=width),
        ))

    L = max(spec.n_bays * spec.bay_length_m, spec.span_width_m, spec.eave_height_m * 2)
    fig.update_layout(
        scene=dict(
            xaxis_title="Length (m)",
            yaxis_title="Width (m)",
            zaxis_title="Height (m)",
            aspectmode="data",
            camera=dict(eye=dict(x=1.5, y=1.5, z=0.8)),
        ),
        legend=dict(
            orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5,
            font=dict(size=11),
        ),
        margin=dict(l=0, r=0, t=30, b=0),
        height=550,
        template="plotly_dark",
    )
    return fig


def _build_boq_chart(spec: BuildingSpec, fm: FrameModel) -> go.Figure:
    """Horizontal bar chart of steel tonnage by member kind."""
    boq = estimate_boq(spec, fm)
    kinds = list(boq.by_kind.keys())
    values = [boq.by_kind[k] / 1000.0 for k in kinds]
    colors = [KIND_COLORS.get(k, "#888888") for k in kinds]
    labels = [KIND_LABELS.get(k, k) for k in kinds]

    fig = go.Figure(go.Bar(
        x=values, y=labels, orientation="h",
        marker_color=colors,
        text=[f"{v:.1f} t" for v in values],
        textposition="auto",
    ))
    fig.update_layout(
        title=f"Steel BOQ: {boq.total_tonnes:.2f} tonnes — {boq.currency}{boq.total_cost:,.0f}  ({boq.member_count} members, {boq.total_length_m:.0f} m)",
        xaxis_title="Tonnes",
        yaxis=dict(autorange="reversed"),
        height=350,
        margin=dict(l=120, r=20, t=50, b=40),
        template="plotly_dark",
    )
    return fig


def process_file(file_obj):
    """Main pipeline: JSON file → (spec_md, 3d_fig, boq_fig, std_text, download_path)."""
    if file_obj is None:
        return "Upload a QRF JSON file to begin.", None, None, "", None

    fp = Path(file_obj) if isinstance(file_obj, str) else Path(file_obj.name)

    try:
        spec = spec_from_json_path(fp)
        fm = build_frame(spec)
        validate_frame_or_raise(fm)
    except (FrameValidationError, Exception) as e:
        return f"**Error:** {e}", None, None, "", None

    summary = format_spec_summary(spec, n_joints=len(fm.joint_coords), n_members=len(fm.members))
    boq = estimate_boq(spec, fm)

    mezz_row = ""
    if spec.mezzanine_elevation_m > 0:
        mezz_row = f"\n| **Mezzanine** | {spec.mezzanine_width_m:.1f} x {spec.mezzanine_length_m:.1f} m @ {spec.mezzanine_elevation_m:.1f} m |"

    spec_md = f"""### {spec.name}

| Parameter | Value |
|-----------|-------|
| **Plan dimensions** | {spec.n_bays * spec.bay_length_m:.1f} x {spec.span_width_m:.1f} m |
| **Bays** | {spec.n_bays} @ {spec.bay_length_m:.2f} m |
| **Eave height** | {spec.eave_height_m:.1f} m |
| **Roof slope** | 1:{1/max(spec.roof_slope_ratio, 0.001):.1f} |
| **Design code** | {spec.design_code} |
| **Fy** | {spec.fyld_mpa:.0f} MPa |
| **Wind pressure** | {spec.wind_pressure_kn_m2:.3f} kN/m² |
| **Seismic Ah** | {spec.seismic_ah} |
| **Crane load** | {spec.crane_load_kn:.1f} kN |{mezz_row}
| **Deflection limits** | V: L/{spec.defl_frame_vertical:.0f}, H: L/{spec.defl_frame_lateral:.0f}, Purlin: L/{spec.defl_purlin:.0f} |
| **3D model** | **{len(fm.joint_coords)} joints, {len(fm.members)} members** |
| **Steel estimate** | **{boq.total_tonnes:.2f} tonnes ({boq.currency}{boq.total_cost:,.0f})** |
"""

    fig3d = _build_3d_figure(fm, spec)
    boq_fig = _build_boq_chart(spec, fm)

    std_text = build_std_text(spec, fm)

    tmp = tempfile.NamedTemporaryFile(
        suffix=".std", prefix=f"{spec.name}_", delete=False, mode="w",
        encoding="utf-8", newline="\n",
    )
    tmp.write(std_text)
    tmp.close()
    _TEMP_FILES.append(tmp.name)

    return spec_md, fig3d, boq_fig, std_text, tmp.name


def load_sample(name):
    """Load one of the bundled competition JSON files."""
    p = SAMPLE_DIR / name
    if not p.exists():
        return None
    return str(p)


samples = sorted(p.name for p in SAMPLE_DIR.glob("*.json")) if SAMPLE_DIR.exists() else []

css = """
.main-title { text-align: center; margin-bottom: 0; }
.subtitle { text-align: center; color: #888; margin-top: 0; font-size: 0.95em; }
footer { display: none !important; }
"""

with gr.Blocks(
    title="STAAD.Pro 3D Generator",
    theme=gr.themes.Soft(primary_hue="blue"),
    css=css,
) as demo:
    gr.Markdown("# STAAD.Pro 3D Generator", elem_classes="main-title")
    gr.Markdown(
        f"QRF JSON → Production-Ready .std with 3D Wireframe, Unity Ratio & Serviceability Checks &nbsp;|&nbsp; v{__version__}",
        elem_classes="subtitle",
    )

    with gr.Row():
        with gr.Column(scale=1):
            gr.Markdown("### Input")
            file_input = gr.File(
                label="Upload QRF JSON",
                file_types=[".json"],
                type="filepath",
            )
            if samples:
                sample_dd = gr.Dropdown(
                    choices=samples,
                    label="Or pick a competition file",
                    interactive=True,
                )
                sample_dd.change(fn=load_sample, inputs=sample_dd, outputs=file_input)

            run_btn = gr.Button("Generate .std", variant="primary", size="lg")

            spec_out = gr.Markdown(label="Building Specification")

        with gr.Column(scale=2):
            gr.Markdown("### 3D Wireframe")
            plot3d = gr.Plot(label="3D Model")

    with gr.Row():
        with gr.Column(scale=1):
            gr.Markdown("### Steel BOQ")
            boq_plot = gr.Plot(label="BOQ Breakdown")
        with gr.Column(scale=1):
            gr.Markdown("### Download")
            std_preview = gr.Code(label="STAAD .std preview (first 60 lines)", language=None, lines=15)
            download_btn = gr.File(label="Download .std file")

    def _run(fp):
        spec_md, fig3d, boq_fig, std_text, dl_path = process_file(fp)
        preview = "\n".join(std_text.splitlines()[:60]) + "\n..." if std_text else ""
        return spec_md, fig3d, boq_fig, preview, dl_path

    run_btn.click(
        fn=_run,
        inputs=file_input,
        outputs=[spec_out, plot3d, boq_plot, std_preview, download_btn],
    )

    file_input.change(
        fn=_run,
        inputs=file_input,
        outputs=[spec_out, plot3d, boq_plot, std_preview, download_btn],
    )

if __name__ == "__main__":
    demo.launch(
        server_name="0.0.0.0",
        server_port=7860,
    )
