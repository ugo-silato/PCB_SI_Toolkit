# -*- coding: utf-8 -*-
"""
Return current map (high frequency) of a net between two pads: KiCad side.

Collects from the board what the numeric core (return_map_core.py) needs:
- the signal path from one pad to the other through tracks and vias
  (net_path.find_path), with the layer of every segment;
- the ground copper of every layer near the path: planes, coplanar ground
  next to the tracks, pours on other layers (zones of the reference net),
  rasterized with HitTestFilledArea (the same safe call used by the Return
  Path check);
- the ground vias and through-hole ground pads, which connect the ground of
  different layers;
- the height of every copper layer in the stackup, to know how far each
  plane is from each segment;
then runs the core and returns everything the map window needs.
"""
import math

import pcbnew

from ..common import geometry
from ..common.i18n import _
from . import impedance, net_path, return_map_core

# Maximum number of raster cells per layer, and in total (keeps the time
# within some seconds)
MAX_CELLS_LAYER = 45000
MAX_CELLS_TOTAL = 150000


def _layer_heights(board, stack):
    """
    Height (mm) of every copper layer, from the top: the sum of the copper
    and dielectric thicknesses above it, read from the stackup.
    """
    stackup, _note = impedance.read_stackup(board)
    z, heights = 0.0, {}
    for layer in stack:
        heights[layer] = z
        info = stackup.get(layer) or {}
        t = (info.get("t") or 35e-6) * 1e3
        below = info.get("below")
        z += t + (below[0] * 1e3 if below else 0.2)
    return heights


def build_map(board, net_name, pad_from, pad_to, ref_filter="GND", progress=None, tracks=None,
              mode="hf", crossings=(), targets=None, exit_pad=None, auto_loads=False, detail=1,
              weights=None, load_refs=None):
    """
    weights: optional currents (any unit) of the 'targets', same order:
    each load gets its share weights[k] / sum(weights) instead of an equal
    share (see analysis/load_estimate.py). load_refs: the names of the
    targets, for the summary.

    detail: resolution factor of the raster (1 = normal, 1.5 = high,
    2 = very high): the cell size is divided by it; the cells grow with
    its square and the calculation time even faster (about 7x at 2).

    auto_loads: the loads are found automatically from pad_from (the input
    of the current): every component reached from its net, also through
    series parts, that has a ground pin (net_path.find_loads); the current
    is shared equally among them.
    exit_pad: ground pad where the return current leaves the board (e.g.
    where the ground of the power supply or instrument is connected). If
    not given, the ground pins of the input component are used, or the
    start of the line if it has none.
    targets: optional [(pad, crossings)] for several loads at once (e.g. all
    the pads of the net): the signal current from pad_from is shared
    equally among them, each path carries its share, and the return enters
    the ground at the ground pins of every load. pad_to/crossings are then
    ignored.
    mode: "hf" (high frequency: the return follows the track, minimum
    inductance) or "dc" (direct current / low frequency: the return takes
    the path of minimum resistance between the ground pins, regardless of
    where the track runs).

    Computes the return current map of 'net_name' from pad_from to pad_to,
    or, if 'tracks' is given, along those tracks (selection in Pcbnew, from
    one free end to the other; net and pads are then ignored).

    progress(fraction, message): optional callback; if it returns False the
    calculation stops (ValueError).
    Returns a dictionary for the map window (see the end of the function).
    """
    def report(frac, msg):
        if progress is not None and progress(frac, msg) is False:
            raise ValueError(_("Calcolo interrotto."))

    import numpy as np

    seg_current = None   # share of the signal current in each segment
    target_ends = None   # for several loads: (pad, index of its last segment, share)
    load_refs = list(load_refs or [])
    shares_t = []
    if net_name is None and pad_from is not None:
        net_name = pad_from.GetNetname()
    if auto_loads and not targets:
        net_name = pad_from.GetNetname()
        found = net_path.find_loads(board, pad_from, ref_filter, dc=(mode == "dc"))
        if not found:
            raise ValueError(_("Nessun carico trovato: dalla net del pad di ingresso non si raggiunge "
                               "nessun componente con un pin di massa."))
        targets = [(p, cr) for p, cr, _r in found]
        load_refs = [r for _p, _c, r in found]
    if targets:
        # One path per load, merged: a stretch shared by several paths
        # carries the sum of their shares (the current splits at the
        # branches). Paths start from pad_from, so they are all oriented
        # the same way along shared stretches.
        if weights is not None:
            total = float(sum(weights))
            if total <= 0:
                raise ValueError(_("Tutti i carichi hanno corrente nulla: inserisci almeno una corrente."))
            shares_t = [w / total for w in weights]
        else:
            shares_t = [1.0 / len(targets)] * len(targets)
        merged, index, vias_all, target_ends = [], {}, {}, []
        stack = None
        for (t_pad, t_cross), share in zip(targets, shares_t):
            if t_cross:
                p = net_path.find_path_through(board, pad_from, t_pad, t_cross, dc=(mode == "dc"))
            else:
                p = net_path.find_path(board, net_name, pad_from, t_pad)
            stack = p["stack"]
            last = None
            for sg in p["segments"]:
                key = (round(sg[0], 4), round(sg[1], 4), round(sg[2], 4), round(sg[3], 4), sg[4])
                if key not in index:
                    index[key] = len(merged)
                    merged.append([sg, 0.0])
                merged[index[key]][1] += share
                last = index[key]
            for v in p["vias"]:
                vias_all[(round(v[0], 4), round(v[1], 4))] = v
            target_ends.append((t_pad, last, share))
        path = {"segments": [m[0] for m in merged], "vias": list(vias_all.values()),
                "length": sum(math.hypot(m[0][2] - m[0][0], m[0][3] - m[0][1]) for m in merged),
                "stack": stack}
        seg_current = [m[1] for m in merged]
    elif tracks:
        path = net_path.path_from_tracks(board, tracks)
        net_name = tracks[0].GetNetname()
    elif crossings:
        # The destination is beyond series parts (R, L, ...): the path goes
        # through them up to the real load
        path = net_path.find_path_through(board, pad_from, pad_to, crossings, dc=(mode == "dc"))
    else:
        path = net_path.find_path(board, net_name, pad_from, pad_to)
    segs = path["segments"]
    stack = path["stack"]
    heights = _layer_heights(board, stack)

    # --- Ground layers: copper layers with zones of the reference net ---
    zones_by_layer = {}
    for layer in stack:
        zones = geometry.find_reference_zones(board, layer, ref_filter)
        if zones:
            zones_by_layer[layer] = zones
    if not zones_by_layer:
        raise ValueError(_("Nessuna zona della net di riferimento ({0}) sulla scheda.").format(ref_filter))
    gnd_layers = [l for l in stack if l in zones_by_layer]   # in stack order

    # --- Raster window: path extent + a wide margin (around a gap the return
    # can detour far; the window edge would act as a false edge of the plane)
    sig_layers = {s[4] for s in segs}
    z_min = min(abs(heights[g] - heights[s]) for s in sig_layers for g in gnd_layers
                if g != s) if any(g not in sig_layers for g in gnd_layers) else 0.2
    z_min = max(z_min, 0.05)
    xs = [v for s in segs for v in (s[0], s[2])]
    ys = [v for s in segs for v in (s[1], s[3])]
    # The ground pins of the input and load components and the exit pad must
    # be inside the window: the return current enters / leaves there
    comps_pads = [pad_from] + [t[0] for t in (targets or [])] + ([pad_to] if pad_to is not None else [])
    for cp in comps_pads:
        try:
            fpads = list(cp.GetParentFootprint().Pads())
        except AttributeError:
            fpads = []
        for gp in fpads:
            if ref_filter.upper() in gp.GetNetname().upper():
                xs.append(pcbnew.ToMM(gp.GetPosition().x))
                ys.append(pcbnew.ToMM(gp.GetPosition().y))
    if exit_pad is not None:
        xs.append(pcbnew.ToMM(exit_pad.GetPosition().x))
        ys.append(pcbnew.ToMM(exit_pad.GetPosition().y))
    # Ground vias near the signal vias must be inside the window: they are
    # where the return current changes plane. The two nearest of each
    # signal via (within 20 mm) extend the window if needed.
    gnd_via_pos = [(pcbnew.ToMM(t.GetPosition().x), pcbnew.ToMM(t.GetPosition().y))
                   for t in board.GetTracks()
                   if t.Type() == pcbnew.PCB_VIA_T and ref_filter.upper() in t.GetNetname().upper()]
    for vx, vy, _la, _lb in path["vias"]:
        near = sorted(gnd_via_pos, key=lambda p: (p[0] - vx) ** 2 + (p[1] - vy) ** 2)[:2]
        for px_, py_ in near:
            if math.hypot(px_ - vx, py_ - vy) <= 20.0:
                xs.append(px_)
                ys.append(py_)
    pad = max(25 * z_min, 6.0)
    x0, x1 = min(xs) - pad, max(xs) + pad
    y0, y1 = min(ys) - pad, max(ys) + pad
    area = (x1 - x0) * (y1 - y0)
    # Higher detail = more cells allowed (and a finer limit on the cell
    # compared with the dielectric height)
    detail = max(1.0, float(detail))
    cell = max(z_min / (3.0 * detail), 0.02,
               math.sqrt(area / (MAX_CELLS_LAYER * detail ** 2)),
               math.sqrt(area * len(gnd_layers) / (MAX_CELLS_TOTAL * detail ** 2)))
    nx = int(math.ceil((x1 - x0) / cell))
    ny = int(math.ceil((y1 - y0) / cell))

    # --- Raster of the ground copper of each layer ---
    nl = len(gnd_layers)
    copper = np.zeros((nl, ny, nx), dtype=bool)
    for li, layer in enumerate(gnd_layers):
        boxes = []
        for z in zones_by_layer[layer]:
            bb = z.GetBoundingBox()
            boxes.append((z, pcbnew.ToMM(bb.GetLeft()), pcbnew.ToMM(bb.GetTop()),
                          pcbnew.ToMM(bb.GetRight()), pcbnew.ToMM(bb.GetBottom())))
        for i in range(ny):
            yc = y0 + (i + 0.5) * cell
            row_zones = [b for b in boxes if b[2] <= yc <= b[4]]
            if row_zones:
                yn = pcbnew.FromMM(yc)
                for j in range(nx):
                    xc = x0 + (j + 0.5) * cell
                    p = pcbnew.VECTOR2I(pcbnew.FromMM(xc), yn)
                    for z, bx0, _by0, bx1, _by1 in row_zones:
                        if bx0 <= xc <= bx1 and z.HitTestFilledArea(layer, p, 0):
                            copper[li, i, j] = True
                            break
            if i % 10 == 0:
                report((li + i / ny) / nl * 0.8,
                       _("Lettura della massa su {0}...").format(board.GetLayerName(layer)))

    def cell_of(x, y):
        return int((y - y0) / cell), int((x - x0) / cell)

    def nearest_copper(li, x, y, rmax):
        """
        Copper cell of layer li closest to (x, y) within rmax mm, or None.
        Needed because the cell at the very centre of a via or pad may have
        no copper in the raster (drill hole, thermal relief).
        """
        i0, j0 = cell_of(x, y)
        n = max(1, int(math.ceil(rmax / cell)))
        best = None
        for i in range(max(0, i0 - n), min(ny, i0 + n + 1)):
            for j in range(max(0, j0 - n), min(nx, j0 + n + 1)):
                if copper[li, i, j]:
                    d = (i - i0) ** 2 + (j - j0) ** 2
                    if d <= n * n and (best is None or d < best[0]):
                        best = (d, i, j)
        return None if best is None else best[1:]

    # --- Ground vias and through-hole ground pads: links between layers ---
    # Each one joins, on the layers it spans, the nearest copper cell
    # (general links between cells, with high conductance)
    G_VIA = 20.0
    extra_links, gnd_vias = [], []   # gnd_vias: (x, y, [indices into extra_links])

    def add_via(x, y, item, radius):
        cells = []
        for li, l in enumerate(gnd_layers):
            if item.IsOnLayer(l):
                c = nearest_copper(li, x, y, radius + cell)
                if c is not None:
                    cells.append((li, c[0], c[1]))
        if len(cells) >= 2:
            idx = []
            for a, b in zip(cells, cells[1:]):
                idx.append(len(extra_links))
                extra_links.append((a, b, G_VIA))
            gnd_vias.append((x, y, idx))

    for t in board.GetTracks():
        if t.Type() == pcbnew.PCB_VIA_T and ref_filter.upper() in t.GetNetname().upper():
            pos = t.GetPosition()
            x, y = pcbnew.ToMM(pos.x), pcbnew.ToMM(pos.y)
            if x0 <= x <= x1 and y0 <= y <= y1:
                add_via(x, y, t, pcbnew.ToMM(net_path._via_radius(t)))
    for p in board.GetPads():
        if ref_filter.upper() in p.GetNetname().upper():
            pos = p.GetPosition()
            x, y = pcbnew.ToMM(pos.x), pcbnew.ToMM(pos.y)
            if x0 <= x <= x1 and y0 <= y <= y1:
                bb = p.GetBoundingBox()
                add_via(x, y, p, pcbnew.ToMM(max(bb.GetWidth(), bb.GetHeight())) / 2)

    def ground_pins(pad, ref_li, only=None):
        """
        Where the return current enters / leaves the ground at a component:
        its ground pins. For each one, the cells of the ground copper it
        touches: on its own layer, or else through the nearest ground via
        (within 3 mm: an SMD pin usually reaches the plane through a short
        track and a via). Returns (list of cells, list of pin positions).
        """
        if only is not None:
            pad_list = only  # a given ground pad (the exit of the return)
        else:
            try:
                fp = pad.GetParentFootprint()
            except AttributeError:
                fp = None
            if fp is None:
                return [], []
            pad_list = list(fp.Pads())
        cells, pins = [], []
        for p in pad_list:
            if ref_filter.upper() not in p.GetNetname().upper():
                continue
            pos = p.GetPosition()
            x, y = pcbnew.ToMM(pos.x), pcbnew.ToMM(pos.y)
            if not (x0 <= x <= x1 and y0 <= y <= y1):
                continue
            bb = p.GetBoundingBox()
            r = pcbnew.ToMM(max(bb.GetWidth(), bb.GetHeight())) / 2
            here = []
            for li, l in enumerate(gnd_layers):
                if p.IsOnLayer(l):
                    c = nearest_copper(li, x, y, r + cell)
                    if c is not None:
                        here.append((li, c[0], c[1]))
            if not here:
                # Through the nearest ground via: the pin current enters the
                # ground at that via, on the reference plane of the line
                # (the via itself then links the other layers)
                near = sorted(gnd_via_pos, key=lambda v: (v[0] - x) ** 2 + (v[1] - y) ** 2)[:1]
                for vx, vy in near:
                    if math.hypot(vx - x, vy - y) <= 3.0:
                        order = [ref_li] + [li for li in range(len(gnd_layers)) if li != ref_li]
                        for li in order:
                            c = nearest_copper(li, vx, vy, 0.5)
                            if c is not None:
                                here.append((li, c[0], c[1]))
                                break
            if here:
                cells += here
                pins.append((x, y, list(here)))  # position and its own cells
        return cells, pins

    # --- Which planes carry the ideal return of each segment ---
    def coverage(li, seg):
        # Share of copper of layer li under the segment (sampled)
        sx0, sy0, sx1, sy1 = seg[:4]
        n = max(2, int(math.hypot(sx1 - sx0, sy1 - sy0) / cell))
        hits = 0
        for k in range(n + 1):
            i, j = cell_of(sx0 + (sx1 - sx0) * k / n, sy0 + (sy1 - sy0) * k / n)
            hits += bool(0 <= i < ny and 0 <= j < nx and copper[li, i, j])
        return hits / (n + 1)

    core_segs, refs = [], []
    for seg in segs:
        s_layer = seg[4]
        hz = heights[s_layer]
        above = [(hz - heights[g], li) for li, g in enumerate(gnd_layers) if heights[g] < hz]
        below = [(heights[g] - hz, li) for li, g in enumerate(gnd_layers) if heights[g] > hz]
        cand = []
        # Nearest ground layer above and below with copper under the segment
        # (a pour far from the line does not count as a reference)
        for side in (sorted(above), sorted(below)):
            for z, li in side:
                if coverage(li, seg) >= 0.3:
                    cand.append((max(z, 0.02), li))
                    break
        if not cand:
            # No plane under the line: the nearest ground layer anyway
            # (also the same layer: coplanar ground only)
            allz = [(abs(heights[g] - hz) or seg[5], li) for li, g in enumerate(gnd_layers)]
            cand = [min(allz)]
        inv = sum(1 / z for z, _li in cand)
        shares = {li: ((1 / z) / inv, z) for z, li in cand}
        if seg_current is not None:
            # Several loads: the ideal return of the stretch is its share
            # of the current
            cur = seg_current[len(core_segs)]
            shares = {li: (w * cur, z) for li, (w, z) in shares.items()}
        core_segs.append((seg[0], seg[1], seg[2], seg[3], shares))
        refs.append(max(shares, key=lambda k: shares[k][0]))

    # Where the return current leaves / enters the ground: the ground pins
    # of the two components (driver = From, receiver = To). The pins of the
    # same component are joined inside the package (strong link). If a
    # component has no ground pin (e.g. a resistor) the end of the line is
    # used.
    ends = [(segs[0][0], segs[0][1], refs[0]), (segs[-1][2], segs[-1][3], refs[-1])]
    G_CHIP = 50.0
    # Components with ground pins: cells, pins, current and the indices of
    # their internal links (to compute afterwards the current of each pin)
    comps = []

    def use_pins(cells, pins, amount):
        idx = []
        for a, b in zip(cells, cells[1:]):
            idx.append(len(extra_links))
            extra_links.append((a, b, G_CHIP))
        comps.append({"cells": cells, "pins": pins, "amount": amount, "links": idx})

    single_amounts = (-1.0, +1.0)
    for k, pad in ((0, pad_from), (1, pad_to)):
        if pad is None:
            continue
        if k == 0 and exit_pad is not None:
            # The return leaves at the chosen ground pad, not at the input
            cells, pins = ground_pins(exit_pad, refs[0], only=[exit_pad])
            if not cells:
                raise ValueError(_("Il pad di uscita del ritorno non tocca rame di massa."))
            ends[0] = cells
            use_pins(cells, pins, -1.0)
            continue
        cells, pins = ground_pins(pad, refs[0] if k == 0 else refs[-1])
        if cells:
            ends[k] = cells
            use_pins(cells, pins, single_amounts[k])
    sources = None
    if target_ends is not None:
        # Several loads: the return leaves the ground at the driver's ground
        # pins (all the current) and enters it at each load's ground pins
        # (its share), or at the end of its path for loads without a ground pin
        sources = [(ends[0], -1.0)]
        for t_pad, last, share in target_ends:
            seg = segs[last]
            spec = (seg[2], seg[3], refs[last])
            cells, pins = ground_pins(t_pad, refs[last])
            if cells:
                spec = cells
                use_pins(cells, pins, share)
            sources.append((spec, share))
    if mode == "dc":
        # DC: no "ideal" current under the track, only the resistance of the
        # copper decides; no capacitance between the planes (in DC only vias
        # and pads connect them)
        core_segs = []
    # High frequency: every cell of the window is assigned to the nearest
    # segment of the line; on the planes that are NOT the reference of that
    # segment the sheet conductance is reduced (factor 0.1). This mimics the
    # higher inductance of a return running on a farther plane, so the
    # return stays on the reference plane of each stretch and changes plane
    # at the ground vias near the signal vias, as it does in reality.
    # DC: no weighting (only the resistance of the copper counts).
    weight = None
    if mode != "dc" and nl > 1:
        xs_c = x0 + (np.arange(nx) + 0.5) * cell
        ys_c = y0 + (np.arange(ny) + 0.5) * cell
        xc, yc = np.meshgrid(xs_c, ys_c)
        best_d = np.full((ny, nx), np.inf)
        best_k = np.zeros((ny, nx), dtype=int)
        for k, (sx0, sy0, sx1, sy1, _shares) in enumerate(core_segs):
            dx, dy = sx1 - sx0, sy1 - sy0
            l2 = dx * dx + dy * dy or 1e-12
            u = np.clip(((xc - sx0) * dx + (yc - sy0) * dy) / l2, 0, 1)
            d = np.hypot(xc - sx0 - u * dx, yc - sy0 - u * dy)
            closer = d < best_d
            best_d[closer] = d[closer]
            best_k[closer] = k
        weight = np.full((nl, ny, nx), 0.1)
        for k, (_a, _b, _c, _d, shares) in enumerate(core_segs):
            mine = best_k == k
            for li in shares:
                weight[li][mine] = 1.0
    report(0.85, _("Calcolo della corrente di ritorno..."))
    try:
        res = return_map_core.solve(copper, x0, y0, cell, core_segs, ends, (),
                                    end_radius=max(1.5 * z_min, 0.3),
                                    g_plane=1e-12 if mode == "dc" else 1e-6,
                                    extra_links=extra_links, sheet_weight=weight,
                                    sources=sources)
    except ValueError:
        raise ValueError(_("Nessun rame di massa nei punti di ingresso/uscita del ritorno."))

    # Current of each ground pin (share of the 1 A): the current injected in
    # its cells plus what arrives through the internal links of the chip
    flows = res["extra_current"]
    pin_marks = []
    for comp in comps:
        inj = comp["amount"] / len(comp["cells"])
        inflow = {}
        for li_ in comp["links"]:
            a, b, _g = extra_links[li_]
            inflow[b] = inflow.get(b, 0.0) + flows[li_]
            inflow[a] = inflow.get(a, 0.0) - flows[li_]
        for x, y, cells in comp["pins"]:
            cur = sum(inj + inflow.get(c, 0.0) for c in cells)
            pin_marks.append((x, y, abs(cur)))

    # Ground vias carrying return current between layers, by current
    vias_loaded = sorted(
        ((x, y, max((abs(flows[k]) for k in idx), default=0.0)) for x, y, idx in gnd_vias),
        key=lambda t: -t[2])

    return {
        "res": res, "copper": copper, "x0": x0, "y0": y0, "cell": cell,
        "layers": [board.GetLayerName(l) for l in gnd_layers],
        "segments": segs, "signal_vias": path["vias"],
        "length": path["length"], "z_min": z_min,
        "k_peak": 1.0 / (math.pi * z_min),
        "gnd_vias": vias_loaded,
        "start": (segs[0][0], segs[0][1]), "end": (segs[-1][2], segs[-1][3]),
        # End point of every load's path (several loads), for the markers
        "load_ends": ([(segs[i][2], segs[i][3]) for _p, i, _s in target_ends]
                      if target_ends else [(segs[-1][2], segs[-1][3])]),
        "net": net_name, "mode": mode, "gnd_pins": pin_marks, "loads": load_refs,
        "load_shares": list(shares_t),
    }
