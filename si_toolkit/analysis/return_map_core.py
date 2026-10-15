# -*- coding: utf-8 -*-
"""
High-frequency return current map in the ground copper (pure numpy, no
KiCad dependency, so it can be tested outside KiCad).

Model (quasi-static estimate):
- Every copper layer that carries ground (planes, coplanar ground next to
  the track, ground pours on other layers) is a conducting sheet, rasterized
  on the same grid. Sheets of different layers are connected only where
  there is a ground via or a through-hole ground pad.
- Ideal return: at high frequency the return current of a track segment
  flows in the ground planes right under / over it. For a plane at distance
  z from the track, the sheet current at lateral distance d is
  (A/mm per 1 A of signal):
      K0(d) = 1 / (pi * z) / (1 + (d / z)^2)
  opposite to the signal. With a plane on both sides (stripline) the current
  splits between them in inverse proportion to the distance.
- Actual return: the ideal current is projected on the currents that are
  physically possible (L2 projection):
      K = K0 - grad(phi),  div(K) = sources  inside the copper,
      K . n = 0 at the copper edges,
  with the 1 A of return current entering the ground at the far end of the
  line and leaving it at the near end. Where a plane is interrupted, or where
  the signal changes reference plane through a via, the current is forced
  to detour: along the remaining copper of the same layer, or to another
  layer through the nearest ground vias.
It is an estimate, not a full-wave result (that is what openEMS is for), but
it shows clearly where and how much the return current has to deviate.

Units: millimetres; currents per 1 A of signal current.
"""
import math

import numpy as np


def lorentz(xc, yc, seg, z):
    """
    Ideal return sheet current of one straight segment for a plane at
    distance z, on the grid points (xc, yc). seg = (x0, y0, x1, y1) in the
    direction of the SIGNAL current. Points whose projection falls outside
    the segment get no contribution (the next/previous segment covers them).
    Returns (kx, ky) arrays (A/mm per 1 A), opposite to the signal.
    """
    x0, y0, x1, y1 = seg
    dx, dy = x1 - x0, y1 - y0
    length = math.hypot(dx, dy)
    if length <= 0:
        return np.zeros_like(xc), np.zeros_like(xc)
    ux, uy = dx / length, dy / length
    s = (xc - x0) * ux + (yc - y0) * uy           # coordinate along the segment
    d = (xc - x0) * (-uy) + (yc - y0) * ux        # perpendicular distance
    k = (1.0 / (math.pi * z)) / (1.0 + (d / z) ** 2)
    k = np.where((s >= 0) & (s <= length), k, 0.0)
    return -k * ux, -k * uy


def _cg(apply, b, diag, iters=6000, tol=1e-7):
    """Jacobi-preconditioned conjugate gradient (numpy arrays of any shape)."""
    x = np.zeros_like(b)
    r = b.copy()
    dinv = 1.0 / np.where(diag > 0, diag, 1.0)
    z = r * dinv
    p = z.copy()
    rz = float((r * z).sum())
    bnorm = math.sqrt(float((r * r).sum())) or 1.0
    for _i in range(iters):
        ap = apply(p)
        pap = float((p * ap).sum())
        if pap <= 0:
            break
        alpha = rz / pap
        x += alpha * p
        r -= alpha * ap
        if math.sqrt(float((r * r).sum())) / bnorm < tol:
            break
        z = r * dinv
        rz_new = float((r * z).sum())
        p = z + (rz_new / rz) * p
        rz = rz_new
    return x


def solve(copper, x0, y0, cell, segments, ends, links=(), g_link=20.0, end_radius=0.5,
          g_plane=1e-6, extra_links=(), sheet_weight=None, sources=None):
    """
    Return current map on several ground layers.

    copper:   3D bool array (layer, row = y, column = x), True where that layer
              has ground copper. Cell (l, i, j) has its centre at
              (x0 + (j + 0.5) * cell, y0 + (i + 0.5) * cell).
    segments: [(x0, y0, x1, y1, {layer_index: (weight, z)})] in signal order
              and direction: for each segment, the planes that carry its ideal
              return, with their share (weights summing to 1) and distance z.
    ends:     [start, end]: where the return current leaves / enters the
              ground. Each one is either (x, y, layer_index) (a small disc
              around that point, e.g. the end of the line) or a list of
              cells [(layer_index, i, j), ...] (e.g. the ground pins of the
              chip), sharing the current equally.
    sheet_weight: optional array (layer, row, column) multiplying the sheet
              conductance of each cell (default 1). Used to make it "costly"
              for the high-frequency return to run on a plane that is NOT
              the reference of the track above it (a farther plane means a
              larger loop, i.e. more inductance): the plain L2 projection
              would otherwise share the current between near and far
              planes too easily.
    sources:  optional [(end, amount)] in place of 'ends', for several loads:
              each end (same formats as above) with the current entering
              the ground there (+) or leaving it (-); the amounts sum to 0.
    extra_links: [((la, ia, ja), (lb, ib, jb), g)] extra conductances
              between any two cells, e.g. the ground pins of the same chip,
              joined inside the package.
    links:    [(i, j, layer_a, layer_b)] ground vias / pads: cells (i, j)
              connected between two layers, with conductance g_link (a
              face of the sheet has conductance 1).
    g_plane:  weak coupling between consecutive ground layers in every cell
              where both have copper: the capacitance between the planes.
              At high frequency, where there is no ground via, the return
              current can still jump between planes this way (it is what
              happens in reality: displacement current, which spreads and
              makes noise). It also keeps the system solvable when no via
              connects the planes.
    Returns a dictionary with, per layer, the arrays kx, ky (actual return),
    k0x, k0y (ideal, cut by the copper), the magnitude k, the current through
    each link and a few figures.
    """
    nl, ny, nx = copper.shape
    xs = x0 + (np.arange(nx) + 0.5) * cell
    ys = y0 + (np.arange(ny) + 0.5) * cell
    xc, yc = np.meshgrid(xs, ys)

    # --- Ideal return on each layer (as if the planes were solid) ---
    k0x = np.zeros((nl, ny, nx))
    k0y = np.zeros((nl, ny, nx))
    for sx0, sy0, sx1, sy1, shares in segments:
        for li, (w, z) in shares.items():
            ax, ay = lorentz(xc, yc, (sx0, sy0, sx1, sy1), z)
            k0x[li] += w * ax
            k0y[li] += w * ay

    # --- Face fluxes of the ideal current, only between two copper cells ---
    gh = copper[:, :, :-1] & copper[:, :, 1:]      # x-faces (0/1)
    gv = copper[:, :-1, :] & copper[:, 1:, :]      # y-faces (0/1)
    fx0 = np.where(gh, 0.5 * (k0x[:, :, :-1] + k0x[:, :, 1:]) * cell, 0.0)
    fy0 = np.where(gv, 0.5 * (k0y[:, :-1, :] + k0y[:, 1:, :]) * cell, 0.0)
    div = np.zeros((nl, ny, nx))
    div[:, :, :-1] += fx0
    div[:, :, 1:] -= fx0
    div[:, :-1, :] += fy0
    div[:, 1:, :] -= fy0

    # --- Sources: 1 A enters at the END of the line, leaves at the START ---
    src = np.zeros((nl, ny, nx))
    if sources is None:
        sources = list(zip(ends, (-1.0, +1.0)))
    for end, amount in sources:
        if isinstance(end, list):
            # Ground pins: the current is shared by their cells
            cells = [(l, i, j) for l, i, j in end if copper[l, i, j]]
            if cells:
                for l, i, j in cells:
                    src[l, i, j] += amount / len(cells)
                continue
            raise ValueError("no ground copper at the ground pins")
        ex, ey, li = end
        disc = ((xc - ex) ** 2 + (yc - ey) ** 2 <= max(end_radius, 2.5 * cell) ** 2) & copper[li]
        if not disc.any():
            # No copper right there: nearest copper cell of that layer
            dist = np.where(copper[li], (xc - ex) ** 2 + (yc - ey) ** 2, np.inf)
            if not np.isfinite(dist).any():
                raise ValueError("no ground copper on the end layer")
            disc = np.zeros((ny, nx), dtype=bool)
            disc[np.unravel_index(np.argmin(dist), dist.shape)] = True
        src[li][disc] += amount / disc.sum()

    # --- Conductances: in-layer faces + inter-layer links (vias) ---
    ghf, gvf = gh.astype(float), gv.astype(float)
    if sheet_weight is not None:
        # Face conductance = the smaller weight of the two cells
        ghf = ghf * np.minimum(sheet_weight[:, :, :-1], sheet_weight[:, :, 1:])
        gvf = gvf * np.minimum(sheet_weight[:, :-1, :], sheet_weight[:, 1:, :])
    diag = np.zeros((nl, ny, nx))
    diag[:, :, :-1] += ghf
    diag[:, :, 1:] += ghf
    diag[:, :-1, :] += gvf
    diag[:, 1:, :] += gvf
    # Links only between cells that have copper on both layers
    link_idx = [(i, j, a, b) for i, j, a, b in links
                if 0 <= i < ny and 0 <= j < nx and copper[a, i, j] and copper[b, i, j]]
    if link_idx:
        li_i = np.array([t[0] for t in link_idx])
        li_j = np.array([t[1] for t in link_idx])
        li_a = np.array([t[2] for t in link_idx])
        li_b = np.array([t[3] for t in link_idx])
        np.add.at(diag, (li_a, li_i, li_j), g_link)
        np.add.at(diag, (li_b, li_i, li_j), g_link)
    # Extra links between arbitrary cells (chip ground pins)
    ex_keep = [k for k, (a, b, _g) in enumerate(extra_links) if copper[a] and copper[b]]
    ex_ok = [extra_links[k] for k in ex_keep]
    if ex_ok:
        ea = tuple(np.array([t[0][k] for t in ex_ok]) for k in range(3))
        eb = tuple(np.array([t[1][k] for t in ex_ok]) for k in range(3))
        eg = np.array([t[2] for t in ex_ok], dtype=float)
        np.add.at(diag, ea, eg)
        np.add.at(diag, eb, eg)
    # Plane-to-plane capacitive coupling between consecutive layers
    both = copper[:-1] & copper[1:] if nl > 1 else np.zeros((0, ny, nx), dtype=bool)
    gp = g_plane * both.astype(float)
    if nl > 1:
        diag[:-1] += gp
        diag[1:] += gp
    diag_reg = diag + 1e-9 * copper  # islands not connected to the ends

    def apply(p):
        out = diag_reg * p
        out[:, :, :-1] -= ghf * p[:, :, 1:]
        out[:, :, 1:] -= ghf * p[:, :, :-1]
        out[:, :-1, :] -= gvf * p[:, 1:, :]
        out[:, 1:, :] -= gvf * p[:, :-1, :]
        if link_idx:
            np.add.at(out, (li_a, li_i, li_j), -g_link * p[li_b, li_i, li_j])
            np.add.at(out, (li_b, li_i, li_j), -g_link * p[li_a, li_i, li_j])
        if ex_ok:
            np.add.at(out, ea, -eg * p[eb])
            np.add.at(out, eb, -eg * p[ea])
        if nl > 1:
            out[:-1] -= gp * p[1:]
            out[1:] -= gp * p[:-1]
        return np.where(copper, out, 0.0)

    # Conservation in each cell: sum of outgoing fluxes = source
    #   F = F0 + g (phi_i - phi_j)  ->  L phi = source - div
    rhs = np.where(copper, src - div, 0.0)
    phi = _cg(apply, rhs, np.where(copper, diag_reg, 1.0))

    # Corrected flux F = F0 + g (phi_i - phi_j), g = face conductance
    fx = np.where(gh, fx0 + ghf * (phi[:, :, :-1] - phi[:, :, 1:]), 0.0)
    fy = np.where(gv, fy0 + gvf * (phi[:, :-1, :] - phi[:, 1:, :]), 0.0)

    # --- Back to cell centres (A/mm) ---
    def centre(f, g, axis):
        acc = np.zeros((nl, ny, nx))
        cnt = np.zeros((nl, ny, nx))
        if axis == 2:
            acc[:, :, :-1] += f
            acc[:, :, 1:] += f
            cnt[:, :, :-1] += g
            cnt[:, :, 1:] += g
        else:
            acc[:, :-1, :] += f
            acc[:, 1:, :] += f
            cnt[:, :-1, :] += g
            cnt[:, 1:, :] += g
        return np.where(cnt > 0, acc / np.maximum(cnt, 1) / cell, 0.0)

    kx = np.where(copper, centre(fx, gh, 2), 0.0)
    ky = np.where(copper, centre(fy, gv, 1), 0.0)
    k = np.hypot(kx, ky)

    # Current through each link (from layer a to layer b), A per 1 A
    link_current = []
    if link_idx:
        flow = g_link * (phi[li_a, li_i, li_j] - phi[li_b, li_i, li_j])
        link_current = list(zip(link_idx, flow.tolist()))

    # Current through each extra link (same order as extra_links; 0 if the
    # link was dropped because one of its cells has no copper)
    extra_current = [0.0] * len(extra_links)
    if ex_ok:
        flows = eg * (phi[ea] - phi[eb])
        for idx, f in zip(ex_keep, flows.tolist()):
            extra_current[idx] = f

    # Current jumping between planes capacitively (no via): total, per layer pair
    plane_jump = float(np.abs(gp * (phi[:-1] - phi[1:])).sum()) if nl > 1 else 0.0

    # Share of the return that is not where it ideally would be
    k0_mag = np.hypot(k0x, k0y)
    total_ideal = float(k0_mag.sum()) or 1.0
    diverted = float(np.hypot(kx - np.where(copper, k0x, 0), ky - np.where(copper, k0y, 0)).sum()) / total_ideal
    missing = 1.0 - float(np.where(copper, k0_mag, 0).sum()) / total_ideal
    return {
        "kx": kx, "ky": ky, "k": k,
        "k0x": k0x, "k0y": k0y, "k0": k0_mag,
        "links": link_current, "plane_jump": plane_jump, "extra_current": extra_current,
        "diverted": diverted, "missing": missing,
    }
