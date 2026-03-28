"""3D PEB: portal frame + purlins + wall girts + roof X-braces (Y vertical).

All secondary members (purlins, girts, crane beams, portal braces) attach
to intermediate joints that are inserted INTO the parent column / rafter
members.  This ensures a single connected structural system in STAAD.Pro.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from staad_generator.spec import BuildingSpec


@dataclass
class FrameModel:
    joint_coords: dict[int, tuple[float, float, float]]
    members: list[tuple[int, int, int, str]]


def _rnd(x: float, nd: int = 4) -> float:
    return round(float(x), nd)


def _bay_x_offsets(spec: BuildingSpec) -> list[float]:
    n = spec.n_bays
    if spec.bay_spacings and len(spec.bay_spacings) == n:
        xs = [0.0]
        for sp in spec.bay_spacings:
            xs.append(xs[-1] + sp)
        return xs
    return [i * spec.bay_length_m for i in range(n + 1)]


def _lerp(a: float, b: float, t: float) -> float:
    return a + t * (b - a)


def build_frame(spec: BuildingSpec) -> FrameModel:
    n = spec.n_bays
    lines = n + 1
    W = spec.span_width_m
    H = spec.eave_height_m
    w2 = W / 2.0
    rise = spec.roof_slope_ratio * w2
    hr = H + rise

    x_offsets = _bay_x_offsets(spec)

    joints: dict[int, tuple[float, float, float]] = {}
    members: list[tuple[int, int, int, str]] = []
    jid = 1
    mid = 1

    # ------------------------------------------------------------------
    # Collect all intermediate heights / parametric positions needed
    # BEFORE creating members, so we can split columns and rafters.
    # ------------------------------------------------------------------

    # Girt Y-positions
    girt_ys: list[float] = []
    if spec.enable_girts and H >= 4.5:
        n_girt_rows = max(1, min(4, int(H / 3.0)))
        girt_ys = [_rnd((k + 1) * H / (n_girt_rows + 1)) for k in range(n_girt_rows)]

    # Crane bracket Y
    crane_y: float = 0.0
    has_crane_beams = spec.crane_bracket_height_m > 0 and spec.crane_load_kn > 0
    if has_crane_beams:
        crane_y = _rnd(min(spec.crane_bracket_height_m, H - 0.5))

    # Portal brace parameters
    has_portal_brace = spec.enable_portal_brace and n >= 1
    kb_drop = min(1.5, H * 0.15)
    kb_run = min(1.5, w2 * 0.15)
    knee_y = _rnd(H - kb_drop)
    raf_brace_t = _rnd(kb_run / math.hypot(w2, rise)) if math.hypot(w2, rise) > 0.01 else 0.0

    # Purlin parametric positions on rafter (pre-rounded to avoid near-duplicates)
    purlin_ts: list[float] = []
    if spec.enable_purlins and lines >= 2:
        slope_len = math.hypot(w2, hr - H)
        n_strip = max(1, min(8, int(slope_len / max(0.8, spec.purlin_spacing_m))))
        purlin_ts = [_rnd((k + 1) / (n_strip + 1)) for k in range(n_strip)]

    # Haunch parametric T — ~10% of rafter span at eave end
    haunch_t = _rnd(min(0.12, 1.5 / max(1.0, math.hypot(w2, rise))))

    portal_brace_frame_indices = set()
    if has_portal_brace:
        portal_brace_frame_indices = {0, n}

    # Endwall column Z positions and their rafter T-values
    endwall_frame_indices = set()
    endwall_z_positions: list[float] = []
    endwall_raf_ts_left: list[float] = []
    endwall_raf_ts_right: list[float] = []
    if spec.enable_endwall_cols and W > 8.0:
        endwall_frame_indices = {0, n}
        n_inner = max(1, min(5, int(W / 8.0) - 1))
        for k in range(1, n_inner + 1):
            z = _rnd(k * W / (n_inner + 1))
            endwall_z_positions.append(z)
            if z < w2 - 0.01:
                endwall_raf_ts_left.append(_rnd(z / w2))
            elif z > w2 + 0.01:
                endwall_raf_ts_right.append(_rnd((W - z) / (W - w2)))

    # ------------------------------------------------------------------
    # For each frame line, build split columns and rafters.
    # ------------------------------------------------------------------
    # Per-frame-line data: dict from y or t -> jid for each column/rafter
    # line_data[i] = {
    #   'b0': base_jid_z0, 'b1': base_jid_zW,
    #   'col0_joints': {y: jid}, 'col1_joints': {y: jid},
    #   'raf_left_joints': {t: jid}, 'raf_right_joints': {t: jid},
    #   'e0': eave_z0, 'e1': eave_zW, 'r': ridge
    # }
    line_data: list[dict] = []

    for i in range(lines):
        x = _rnd(x_offsets[i])
        ld: dict = {}

        # --- Column Z=0: collect all intermediate Y values ---
        col0_ys = sorted(set(girt_ys))
        if has_crane_beams and crane_y not in col0_ys:
            col0_ys.append(crane_y)
        if i in portal_brace_frame_indices and knee_y not in col0_ys:
            col0_ys.append(knee_y)
        col0_ys = sorted(set(y for y in col0_ys if 0.01 < y < H - 0.01))

        # Create joints bottom to top for column Z=0
        b0 = jid; joints[b0] = (x, 0.0, 0.0); jid += 1
        col0_joints: dict[float, int] = {0.0: b0}
        for y in col0_ys:
            j = jid; joints[j] = (x, _rnd(y), 0.0); jid += 1
            col0_joints[_rnd(y)] = j
        e0 = jid; joints[e0] = (x, _rnd(H), 0.0); jid += 1
        col0_joints[_rnd(H)] = e0

        # Create column Z=0 sub-members
        all_col0_ys = sorted(col0_joints.keys())
        for idx in range(len(all_col0_ys) - 1):
            members.append((mid, col0_joints[all_col0_ys[idx]], col0_joints[all_col0_ys[idx + 1]], "column"))
            mid += 1

        # --- Column Z=W: same intermediate Y values ---
        b1 = jid; joints[b1] = (x, 0.0, _rnd(W)); jid += 1
        col1_joints: dict[float, int] = {0.0: b1}
        for y in col0_ys:
            j = jid; joints[j] = (x, _rnd(y), _rnd(W)); jid += 1
            col1_joints[_rnd(y)] = j
        e1 = jid; joints[e1] = (x, _rnd(H), _rnd(W)); jid += 1
        col1_joints[_rnd(H)] = e1

        all_col1_ys = sorted(col1_joints.keys())
        for idx in range(len(all_col1_ys) - 1):
            members.append((mid, col1_joints[all_col1_ys[idx]], col1_joints[all_col1_ys[idx + 1]], "column"))
            mid += 1

        # --- Left rafter (eave Z=0 → ridge): collect parametric T values ---
        raf_left_ts = sorted(set(purlin_ts))
        if haunch_t > 0.01:
            raf_left_ts.append(haunch_t)
        if i in portal_brace_frame_indices and raf_brace_t > 0.01:
            raf_left_ts.append(raf_brace_t)
        if i in endwall_frame_indices:
            raf_left_ts.extend(endwall_raf_ts_left)
        raf_left_ts = sorted(set(t for t in raf_left_ts if 0.01 < t < 0.99))

        raf_left_joints: dict[float, int] = {0.0: e0}
        for t in raf_left_ts:
            py = _rnd(H + t * (hr - H))
            pz = _rnd(t * w2)
            j = jid; joints[j] = (x, py, pz); jid += 1
            raf_left_joints[_rnd(t)] = j

        r = jid; joints[r] = (x, _rnd(hr), _rnd(w2)); jid += 1
        raf_left_joints[1.0] = r

        all_raf_left_ts = sorted(raf_left_joints.keys())
        for idx in range(len(all_raf_left_ts) - 1):
            kind = "haunch" if idx == 0 and haunch_t > 0.01 else "rafter"
            members.append((mid, raf_left_joints[all_raf_left_ts[idx]], raf_left_joints[all_raf_left_ts[idx + 1]], kind))
            mid += 1

        # --- Right rafter (eave Z=W → ridge): mirror ---
        raf_right_ts = sorted(set(purlin_ts))
        if haunch_t > 0.01:
            raf_right_ts.append(haunch_t)
        if i in portal_brace_frame_indices and raf_brace_t > 0.01:
            raf_right_ts.append(raf_brace_t)
        if i in endwall_frame_indices:
            raf_right_ts.extend(endwall_raf_ts_right)
        raf_right_ts = sorted(set(t for t in raf_right_ts if 0.01 < t < 0.99))

        raf_right_joints: dict[float, int] = {0.0: e1}
        for t in raf_right_ts:
            py = _rnd(H + t * (hr - H))
            pz = _rnd(W - t * (W - w2))
            j = jid; joints[j] = (x, py, pz); jid += 1
            raf_right_joints[_rnd(t)] = j
        raf_right_joints[1.0] = r

        all_raf_right_ts = sorted(raf_right_joints.keys())
        for idx in range(len(all_raf_right_ts) - 1):
            kind = "haunch" if idx == 0 and haunch_t > 0.01 else "rafter"
            members.append((mid, raf_right_joints[all_raf_right_ts[idx]], raf_right_joints[all_raf_right_ts[idx + 1]], kind))
            mid += 1

        ld.update({
            'b0': b0, 'b1': b1, 'e0': e0, 'e1': e1, 'r': r,
            'col0': col0_joints, 'col1': col1_joints,
            'raf_left': raf_left_joints, 'raf_right': raf_right_joints,
        })
        line_data.append(ld)

    # ------------------------------------------------------------------
    # Longitudinal members: eave beams + ridge beams
    # ------------------------------------------------------------------
    for i in range(lines - 1):
        members.append((mid, line_data[i]['e0'], line_data[i + 1]['e0'], "eave_long")); mid += 1
        members.append((mid, line_data[i]['e1'], line_data[i + 1]['e1'], "eave_long")); mid += 1
    for i in range(lines - 1):
        members.append((mid, line_data[i]['r'], line_data[i + 1]['r'], "ridge_long")); mid += 1

    # ------------------------------------------------------------------
    # Purlins — connected to rafter intermediate joints
    # ------------------------------------------------------------------
    if purlin_ts and lines >= 2:
        for t in purlin_ts:
            t_rnd = _rnd(t)
            prev_l: int | None = None
            prev_r: int | None = None
            for i in range(lines):
                jl = line_data[i]['raf_left'].get(t_rnd)
                jr = line_data[i]['raf_right'].get(t_rnd)
                if jl is not None and prev_l is not None:
                    members.append((mid, prev_l, jl, "purlin")); mid += 1
                if jr is not None and prev_r is not None:
                    members.append((mid, prev_r, jr, "purlin")); mid += 1
                if jl is not None:
                    prev_l = jl
                if jr is not None:
                    prev_r = jr

    # ------------------------------------------------------------------
    # Wall girts — connected to column intermediate joints
    # ------------------------------------------------------------------
    if girt_ys and lines >= 2:
        for yg in girt_ys:
            yg_rnd = _rnd(yg)
            prev0: int | None = None
            prev1: int | None = None
            for i in range(lines):
                j0 = line_data[i]['col0'].get(yg_rnd)
                j1 = line_data[i]['col1'].get(yg_rnd)
                if j0 is not None and prev0 is not None:
                    members.append((mid, prev0, j0, "girt")); mid += 1
                if j1 is not None and prev1 is not None:
                    members.append((mid, prev1, j1, "girt")); mid += 1
                if j0 is not None:
                    prev0 = j0
                if j1 is not None:
                    prev1 = j1

    # ------------------------------------------------------------------
    # Roof X-braces (first and last bay — connect existing frame joints)
    # ------------------------------------------------------------------
    if spec.enable_roof_x_brace and n >= 1:
        e0a, e0b = line_data[0]['e0'], line_data[1]['e0']
        e1a, e1b = line_data[0]['e1'], line_data[1]['e1']
        ra, rb = line_data[0]['r'], line_data[1]['r']
        members.append((mid, e0a, rb, "roof_brace")); mid += 1
        members.append((mid, e0b, ra, "roof_brace")); mid += 1
        members.append((mid, e1a, rb, "roof_brace")); mid += 1
        members.append((mid, e1b, ra, "roof_brace")); mid += 1
        if n >= 2:
            e0p, e0q = line_data[-2]['e0'], line_data[-1]['e0']
            e1p, e1q = line_data[-2]['e1'], line_data[-1]['e1']
            rp, rq = line_data[-2]['r'], line_data[-1]['r']
            members.append((mid, e0p, rq, "roof_brace")); mid += 1
            members.append((mid, e0q, rp, "roof_brace")); mid += 1
            members.append((mid, e1p, rq, "roof_brace")); mid += 1
            members.append((mid, e1q, rp, "roof_brace")); mid += 1

    # ------------------------------------------------------------------
    # Sidewall X-braces (first and last bay, both walls)
    # ------------------------------------------------------------------
    if spec.enable_wall_x_brace and n >= 1:
        for ia, ib in [(0, 1)] + ([(n - 1, n)] if n >= 2 else []):
            b0a = line_data[ia]['b0']; e0a_sw = line_data[ia]['e0']
            b0b = line_data[ib]['b0']; e0b_sw = line_data[ib]['e0']
            b1a = line_data[ia]['b1']; e1a_sw = line_data[ia]['e1']
            b1b = line_data[ib]['b1']; e1b_sw = line_data[ib]['e1']
            members.append((mid, b0a, e0b_sw, "wall_brace")); mid += 1
            members.append((mid, b0b, e0a_sw, "wall_brace")); mid += 1
            members.append((mid, b1a, e1b_sw, "wall_brace")); mid += 1
            members.append((mid, b1b, e1a_sw, "wall_brace")); mid += 1

    # ------------------------------------------------------------------
    # Endwall columns — connect base to rafter intermediate joints
    # ------------------------------------------------------------------
    if endwall_z_positions:
        for frame_i in sorted(endwall_frame_indices):
            for z in endwall_z_positions:
                z_rnd = _rnd(z)
                if z_rnd < w2 - 0.01:
                    t_rnd = _rnd(z_rnd / w2)
                    je = line_data[frame_i]['raf_left'].get(t_rnd)
                elif z_rnd > w2 + 0.01:
                    t_rnd = _rnd((W - z_rnd) / (W - w2))
                    je = line_data[frame_i]['raf_right'].get(t_rnd)
                else:
                    je = line_data[frame_i]['r']
                if je is None:
                    continue
                jb = jid; joints[jb] = (_rnd(x_offsets[frame_i]), 0.0, z_rnd); jid += 1
                members.append((mid, jb, je, "endwall_col")); mid += 1

    # ------------------------------------------------------------------
    # Crane beams — connected to column intermediate joints
    # ------------------------------------------------------------------
    if has_crane_beams and lines >= 2:
        crane_y_rnd = _rnd(crane_y)
        prev_cb0: int | None = None
        prev_cb1: int | None = None
        for i in range(lines):
            cb0 = line_data[i]['col0'].get(crane_y_rnd)
            cb1 = line_data[i]['col1'].get(crane_y_rnd)
            if cb0 is not None and prev_cb0 is not None:
                members.append((mid, prev_cb0, cb0, "crane_beam")); mid += 1
            if cb1 is not None and prev_cb1 is not None:
                members.append((mid, prev_cb1, cb1, "crane_beam")); mid += 1
            if cb0 is not None:
                prev_cb0 = cb0
            if cb1 is not None:
                prev_cb1 = cb1

    # ------------------------------------------------------------------
    # Portal braces — connected to column + rafter intermediate joints
    # ------------------------------------------------------------------
    if has_portal_brace:
        knee_y_rnd = _rnd(knee_y)
        brace_t_rnd = _rnd(raf_brace_t)
        for fi in portal_brace_frame_indices:
            kc0 = line_data[fi]['col0'].get(knee_y_rnd)
            kr0 = line_data[fi]['raf_left'].get(brace_t_rnd)
            if kc0 is not None and kr0 is not None:
                members.append((mid, kc0, kr0, "portal_brace")); mid += 1

            kc1 = line_data[fi]['col1'].get(knee_y_rnd)
            kr1 = line_data[fi]['raf_right'].get(brace_t_rnd)
            if kc1 is not None and kr1 is not None:
                members.append((mid, kc1, kr1, "portal_brace")); mid += 1

    # ------------------------------------------------------------------
    # Mezzanine floor (columns, beams, longitudinal ties)
    # ------------------------------------------------------------------
    if spec.mezzanine_elevation_m > 0 and spec.mezzanine_width_m > 0:
        y_mezz = _rnd(spec.mezzanine_elevation_m)
        mw = min(spec.mezzanine_width_m, W)
        ml = min(spec.mezzanine_length_m, x_offsets[-1]) if spec.mezzanine_length_m > 0 else x_offsets[-1]

        n_mezz_z = max(2, int(mw / 6.0) + 1)
        z_positions = [_rnd(k * mw / (n_mezz_z - 1)) for k in range(n_mezz_z)]

        x_positions = [x for x in x_offsets if x <= ml + 0.01]
        if not x_positions:
            x_positions = x_offsets[:2]

        _base_lookup: dict[tuple[float, float], int] = {}
        for existing_jid, (ex, ey, ez) in joints.items():
            if ey == 0.0:
                _base_lookup[(_rnd(ex), _rnd(ez))] = existing_jid

        mezz_grid: dict[tuple[float, float], int] = {}
        for xq in x_positions:
            xr = _rnd(xq)
            for zq in z_positions:
                zr = _rnd(zq)
                j = jid; joints[j] = (xr, y_mezz, zr); jid += 1
                mezz_grid[(xr, zr)] = j

        for (xr, zr), mj in mezz_grid.items():
            existing_base = _base_lookup.get((xr, zr))
            if existing_base is not None:
                jb = existing_base
            else:
                jb = jid; joints[jb] = (xr, 0.0, zr); jid += 1
            members.append((mid, jb, mj, "mezz_col")); mid += 1

        for xq in x_positions:
            xr = _rnd(xq)
            prev_j: int | None = None
            for zq in z_positions:
                zr = _rnd(zq)
                cj = mezz_grid.get((xr, zr))
                if cj is not None:
                    if prev_j is not None:
                        members.append((mid, prev_j, cj, "mezz_beam")); mid += 1
                    prev_j = cj

        for zq in z_positions:
            zr = _rnd(zq)
            prev_j = None
            for xq in x_positions:
                xr = _rnd(xq)
                cj = mezz_grid.get((xr, zr))
                if cj is not None:
                    if prev_j is not None:
                        members.append((mid, prev_j, cj, "mezz_long")); mid += 1
                    prev_j = cj

        # Joists: intermediate floor members between main beams within each bay
        js = max(1.0, spec.joist_spacing_m)
        for bay_i in range(len(x_positions) - 1):
            x_a = x_positions[bay_i]
            x_b = x_positions[bay_i + 1]
            bay_span = x_b - x_a
            n_joists = max(1, int(bay_span / js))
            for ji in range(1, n_joists):
                xj = _rnd(x_a + ji * bay_span / n_joists)
                joist_joints_in_row: list[int] = []
                for zq in z_positions:
                    zr = _rnd(zq)
                    jj = jid; joints[jj] = (xj, y_mezz, zr); jid += 1
                    joist_joints_in_row.append(jj)
                for k in range(len(joist_joints_in_row) - 1):
                    members.append((mid, joist_joints_in_row[k], joist_joints_in_row[k + 1], "joist")); mid += 1

    # ------------------------------------------------------------------
    # Canopy — overhang on Z=0 sidewall at the entrance bay
    # ------------------------------------------------------------------
    if spec.enable_canopy and spec.canopy_width_m > 0.3 and n >= 1:
        cw = _rnd(spec.canopy_width_m)
        canopy_bay = min(spec.opening_bay_index, n - 1)
        for fi in [canopy_bay, canopy_bay + 1]:
            if fi >= lines:
                continue
            e0 = line_data[fi]['e0']
            x_can = _rnd(x_offsets[fi])
            jc = jid; joints[jc] = (x_can, _rnd(H), _rnd(-cw)); jid += 1
            members.append((mid, e0, jc, "canopy")); mid += 1
        if canopy_bay + 1 < lines:
            can_joints = [
                jid_c for jid_c, (cx, cy, cz) in joints.items()
                if cy == _rnd(H) and cz == _rnd(-cw)
            ]
            if len(can_joints) >= 2:
                can_joints.sort(key=lambda j: joints[j][0])
                for ci in range(len(can_joints) - 1):
                    members.append((mid, can_joints[ci], can_joints[ci + 1], "canopy")); mid += 1

    # ------------------------------------------------------------------
    # Framed opening + jack beam on Z=0 sidewall
    # ------------------------------------------------------------------
    if spec.enable_framed_opening and spec.opening_width_m > 0.5 and n >= 2:
        oi = min(spec.opening_bay_index, n - 1)
        x_left = _rnd(x_offsets[oi])
        x_right = _rnd(x_offsets[oi + 1])
        x_mid = _rnd((x_left + x_right) / 2.0)
        ow = min(spec.opening_width_m, (x_right - x_left) * 0.85)
        oh = min(spec.opening_height_m, H - 0.5)
        x_ol = _rnd(x_mid - ow / 2.0)
        x_or = _rnd(x_mid + ow / 2.0)

        jbl = jid; joints[jbl] = (x_ol, 0.0, 0.0); jid += 1
        jtl = jid; joints[jtl] = (x_ol, _rnd(oh), 0.0); jid += 1
        members.append((mid, jbl, jtl, "opening_jamb")); mid += 1

        jbr = jid; joints[jbr] = (x_or, 0.0, 0.0); jid += 1
        jtr = jid; joints[jtr] = (x_or, _rnd(oh), 0.0); jid += 1
        members.append((mid, jbr, jtr, "opening_jamb")); mid += 1

        members.append((mid, jtl, jtr, "jack_beam")); mid += 1

        e0_left = line_data[oi]['e0']
        e0_right = line_data[oi + 1]['e0']
        members.append((mid, e0_left, jtl, "jack_beam")); mid += 1
        members.append((mid, jtr, e0_right, "jack_beam")); mid += 1

    # ------------------------------------------------------------------
    # Cage ladder — vertical access ladder on Z=W sidewall near last bay
    # ------------------------------------------------------------------
    if spec.enable_cage_ladder and n >= 1:
        cl_bay = spec.cage_ladder_bay_index
        if cl_bay < 0:
            cl_bay = n - 1
        cl_bay = min(cl_bay, n - 1)
        cl_fi = cl_bay + 1
        if cl_fi >= lines:
            cl_fi = cl_bay
        x_cl = _rnd(x_offsets[cl_fi])
        z_cl = _rnd(W + 0.4)
        rung_spacing = 2.5
        n_rungs = max(2, int(H / rung_spacing) + 1)
        ladder_joints: list[int] = []
        for ri in range(n_rungs):
            y_r = _rnd(ri * H / (n_rungs - 1))
            jl = jid; joints[jl] = (x_cl, y_r, z_cl); jid += 1
            ladder_joints.append(jl)
        for ri in range(len(ladder_joints) - 1):
            members.append((mid, ladder_joints[ri], ladder_joints[ri + 1], "cage_ladder")); mid += 1
        b1 = line_data[cl_fi]['b1']
        e1 = line_data[cl_fi]['e1']
        members.append((mid, b1, ladder_joints[0], "cage_ladder")); mid += 1
        members.append((mid, e1, ladder_joints[-1], "cage_ladder")); mid += 1

    return FrameModel(joint_coords=joints, members=members)
