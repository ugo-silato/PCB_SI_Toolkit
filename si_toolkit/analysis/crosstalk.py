"""
Modulo "Crosstalk": stima del disturbo fra tracce parallele vicine.

Per ogni coppia di net che corrono parallele sullo stesso layer misura:
- la lunghezza del tratto parallelo (dove lo spazio fra i bordi e' entro
  una soglia),
- lo spazio fra i bordi (minimo e mediano).

Stima poi il crosstalk all'estremo vicino (NEXT) con la regola pratica
di H. Johnson per tracce sopra un piano:
    coefficiente di accoppiamento  C = 1 / (1 + (D/H)^2)
dove D = distanza fra i CENTRI delle tracce e H = altezza sopra il piano.
Il NEXT saturo vale circa C/4 e si raggiunge quando il tratto parallelo
e' lungo almeno meta' del fronte di salita (Lsat = tr * v / 2); per tratti
piu' corti scala in proporzione.

E' una stima di ordine di grandezza (non un field solver): serve a
trovare i punti da guardare, non a dare un valore preciso.
"""
import math

import pcbnew

from ..common import geometry

C0 = 299792458.0  # velocita' della luce (m/s)


def next_estimate(center_dist_m, h_m, parallel_m, rise_s, eeff):
    """
    Ritorna (coefficiente C, NEXT stimato come frazione 0..1).
    """
    coupling = 1.0 / (1.0 + (center_dist_m / h_m) ** 2)
    v = C0 / math.sqrt(eeff)
    l_sat = rise_s * v / 2.0
    scale = min(1.0, parallel_m / l_sat) if l_sat > 0 else 1.0
    return coupling, coupling / 4.0 * scale


def find_parallel_runs(board, layer_filter=None, exclude=("GND",),
                       spacing_limit_nm=None, step_nm=None):
    """
    Trova i tratti paralleli fra net diverse sullo stesso layer.

    Campiona ogni traccia rettilinea a passi di 'step_nm'; per ogni punto
    cerca la traccia di un'altra net piu' vicina sullo stesso layer (con
    una griglia per non confrontare tutto con tutto). Se lo spazio fra i
    bordi e' entro 'spacing_limit_nm' il punto conta come parallelo.

    Ritorna un dizionario (netA, netB, layer) -> {
        "length_nm": lunghezza del tratto parallelo (misurata su netA e
                     netB e mediata),
        "gaps": lista degli spazi misurati (nm),
        "widths": lista delle larghezze (larghezza A + B)/2,
        "tracks": insieme delle tracce coinvolte }
    """
    if spacing_limit_nm is None:
        spacing_limit_nm = pcbnew.FromMM(1.0)
    if step_nm is None:
        step_nm = pcbnew.FromMM(0.5)
    excl = [e.upper() for e in exclude if e]

    # Segmenti per layer, escluse le net di massa
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

    # Griglia: cella -> indici dei segmenti che la attraversano (bounding box)
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
                # Conta solo se il punto "si affaccia" sulla traccia vicina
                # (proiezione dentro il segmento): cosi' le estremita' di
                # una traccia che finisce non allungano il tratto parallelo
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
            # Ogni net misura il tratto dal proprio lato: si somma a meta'
            r["length_nm"] += step_len / 2.0
            r["gaps"].append(max(gap, 0.0))
            r["widths"].append((w + ow) / 2.0)
            r["tracks"].add(i)
            r["tracks"].add(j)
    for r in runs.values():
        r["tracks"] = [segs[k] for k in r["tracks"]]
    return runs
