"""
"Crosstalk" module: estimate of the noise between close parallel tracks.

For every pair of nets running parallel on the same layer it measures:
- the length of the parallel run (where the edge-to-edge spacing is within
  a threshold),
- the edge-to-edge spacing (minimum and median).

It then estimates the near-end crosstalk (NEXT) with H. Johnson's rule of
thumb for tracks over a plane:
    coupling coefficient  C = 1 / (1 + (D/H)^2)
where D = distance between the track CENTERS and H = height above the plane.
The saturated NEXT is about C/4 and is reached when the parallel run is at
least half the rise time long (Lsat = tr * v / 2); for shorter runs it
scales proportionally.

It is an order-of-magnitude estimate (not a field solver): it is meant to
find the spots worth a look, not to give a precise value.
"""
import math

import pcbnew

from ..common import geometry

C0 = 299792458.0  # speed of light (m/s)


def next_estimate(center_dist_m, h_m, parallel_m, rise_s, eeff):
    """
    Returns (coefficient C, estimated NEXT as a 0..1 fraction).
    """
    coupling = 1.0 / (1.0 + (center_dist_m / h_m) ** 2)
    v = C0 / math.sqrt(eeff)
    l_sat = rise_s * v / 2.0
    scale = min(1.0, parallel_m / l_sat) if l_sat > 0 else 1.0
    return coupling, coupling / 4.0 * scale


def find_parallel_runs(board, layer_filter=None, exclude=("GND",),
                       spacing_limit_nm=None, step_nm=None):
    """
    Finds the parallel runs between different nets on the same layer.

    Samples every straight track every 'step_nm'; for each point it looks for
    the closest track of another net on the same layer (using a grid to avoid
    comparing everything with everything). If the edge-to-edge spacing is
    within 'spacing_limit_nm' the point counts as parallel.

    Returns a dictionary (netA, netB, layer) -> {
        "length_nm": length of the parallel run (measured on netA and netB
                     and averaged),
        "gaps": list of the measured spacings (nm),
        "widths": list of the widths (width A + B)/2,
        "tracks": set of the tracks involved }
    """
    if spacing_limit_nm is None:
        spacing_limit_nm = pcbnew.FromMM(1.0)
    if step_nm is None:
        step_nm = pcbnew.FromMM(0.5)
    excl = [e.upper() for e in exclude if e]

    # Segments per layer, ground nets excluded
    segs = []
    for t in board.GetTracks():
        if t.Type() != pcbnew.PCB_TRACE_T:
            continue
        net = t.GetNetname()
        if not net or any(e in net.upper() for e in excl):
            continue
        if layer_filter is not None and t.GetLayer() not in layer_filter:
            continue
        segs.append(t)

    # Grid: cell -> indexes of the segments crossing it (bounding box)
    cell = pcbnew.FromMM(2.0)
    grid = {}
    info = []
    for i, t in enumerate(segs):
        a, b = t.GetStart(), t.GetEnd()
        info.append((a.x, a.y, b.x, b.y, t.GetWidth(), t.GetNetname(), t.GetLayer()))
        pad = spacing_limit_nm + t.GetWidth()
        x0, x1 = (min(a.x, b.x) - pad) // cell, (max(a.x, b.x) + pad) // cell
        y0, y1 = (min(a.y, b.y) - pad) // cell, (max(a.y, b.y) + pad) // cell
        for cx in range(int(x0), int(x1) + 1):
            for cy in range(int(y0), int(y1) + 1):
                grid.setdefault((cx, cy, t.GetLayer()), []).append(i)

    runs = {}
    for i, t in enumerate(segs):
        ax, ay, bx, by, w, net, layer = info[i]
        pts = geometry.sample_points_along_track(t, step_nm, 400)
        if len(pts) < 2:
            continue
        step_len = t.GetLength() / (len(pts) - 1)
        for p in pts:
            best = None
            for j in grid.get((p.x // cell, p.y // cell, layer), ()):
                ox0, oy0, ox1, oy1, ow, onet, _ol = info[j]
                if onet == net:
                    continue
                # Counts only if the point "faces" the nearby track (projection
                # inside the segment): this way the ends of a track that stops
                # do not lengthen the parallel run
                dx, dy = ox1 - ox0, oy1 - oy0
                len2 = dx * dx + dy * dy
                if len2 == 0:
                    continue
                u = ((p.x - ox0) * dx + (p.y - oy0) * dy) / len2
                if not 0.0 <= u <= 1.0:
                    continue
                gap = geometry.point_segment_distance(p.x, p.y, ox0, oy0, ox1, oy1) - ow / 2.0 - w / 2.0
                if gap <= spacing_limit_nm and (best is None or gap < best[0]):
                    best = (gap, onet, ow, j)
            if best is None:
                continue
            gap, onet, ow, j = best
            a_net, b_net = sorted((net, onet))
            r = runs.setdefault((a_net, b_net, layer),
                                {"length_nm": 0.0, "gaps": [], "widths": [], "tracks": set()})
            # Each net measures the run from its own side: half is added
            r["length_nm"] += step_len / 2.0
            r["gaps"].append(max(gap, 0.0))
            r["widths"].append((w + ow) / 2.0)
            r["tracks"].add(i)
            r["tracks"].add(j)
    for r in runs.values():
        r["tracks"] = [segs[k] for k in r["tracks"]]
    return runs
