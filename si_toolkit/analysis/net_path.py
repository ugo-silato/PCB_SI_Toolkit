# -*- coding: utf-8 -*-
"""
Signal path of a net between two pads, through tracks and vias.

Builds a graph of the net copper:
- nodes: track ends (per layer), vias, pads;
- edges: tracks (weight = length), via barrels (connect the layers they
  span), pad copper (connects the track ends lying on the pad),
  T-junctions (a track end lying on the middle of another track);
and finds the shortest path between the two pads (Dijkstra). The result is
the list of straight segments, each with its layer, in the order followed
by the signal, plus the vias where it changes layer.

Coordinates in mm.
"""
import heapq
import math

import pcbnew

from ..common.i18n import _

# Two track ends closer than this are the same point (KiCad snaps them, but
# imported boards may have tiny offsets)
_TOL_NM = 1000  # 1 um


def _key(p, layer):
    """Graph node of a track end (rounded position + layer)."""
    return ("e", int(round(p.x / _TOL_NM)), int(round(p.y / _TOL_NM)), layer)


def _via_radius(v):
    """
    Radius (nm) of a via's copper. In KiCad 9/10 GetWidth() of a via wants
    the layer (pad stacks can differ per layer); older versions take no
    argument. The bounding box is the last fallback.
    """
    for args in ((pcbnew.F_Cu,), ()):
        try:
            return v.GetWidth(*args) / 2.0
        except Exception:
            pass
    return v.GetBoundingBox().GetWidth() / 2.0


def _pad_touches(pad, x, y, radius, layer):
    """
    True if a track end (disc of 'radius' nm at x, y) touches the pad copper.
    PAD.HitTest takes an accuracy (extra distance) in nm; the signature
    changed between KiCad versions, so several forms are tried.
    """
    p = pcbnew.VECTOR2I(int(x), int(y))
    for args in ((p, int(radius), layer), (p, int(radius)), (p,)):
        try:
            return bool(pad.HitTest(*args))
        except Exception:
            continue
    return False


def _point_seg_dist(px, py, ax, ay, bx, by):
    """Distance of P from segment AB and position along it (0..1)."""
    dx, dy = bx - ax, by - ay
    l2 = dx * dx + dy * dy
    u = 0.0 if l2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / l2))
    return math.hypot(px - ax - u * dx, py - ay - u * dy), u


def _net_items(board, net_name):
    """Tracks and vias of a net."""
    tracks, vias = [], []
    for t in board.GetTracks():
        if t.GetNetname() != net_name:
            continue
        if t.Type() == pcbnew.PCB_TRACE_T:
            tracks.append(t)
        elif t.Type() == pcbnew.PCB_VIA_T:
            vias.append(t)
    return tracks, vias


def find_path(board, net_name, pad_from, pad_to):
    """
    Shortest copper path of 'net_name' from pad_from to pad_to.

    Returns a dictionary:
      segments: [(x0, y0, x1, y1, layer_id, width_mm)] in signal order;
      vias:     [(x, y, from_layer, to_layer)] layer changes along the path;
      length:   total length (mm).
    Raises ValueError if the two pads are not connected by tracks/vias.
    """
    tracks, vias = _net_items(board, net_name)
    return _path(board, tracks, vias, (pad_from, pad_to))


def path_from_tracks(board, tracks):
    """
    Path along the tracks selected in Pcbnew (one net, possibly on several
    layers joined by vias), from one free end of the selection to the
    other (the two free ends farthest apart). No pads needed: any track
    can be analyzed. Same result format as find_path.
    """
    tracks = [t for t in tracks if t.Type() == pcbnew.PCB_TRACE_T]
    if not tracks:
        raise ValueError(_("Seleziona in Pcbnew le tracce della linea da analizzare."))
    nets = {t.GetNetname() for t in tracks}
    if len(nets) != 1:
        raise ValueError(_("Le tracce selezionate devono essere della stessa net."))
    _all, vias = _net_items(board, nets.pop())
    return _path(board, tracks, vias, None)


def _path(board, tracks, vias, pads):
    """
    Common part: graph of 'tracks' and 'vias', shortest path between the
    two pads (pads = (from, to)) or, with pads = None, between the two free
    ends of the tracks farthest apart.
    """
    stack = list(board.GetEnabledLayers().CuStack())

    graph = {}  # node -> list of (neighbour, length_mm, info)

    def link(a, b, length, info):
        graph.setdefault(a, []).append((b, length, info))
        graph.setdefault(b, []).append((a, length, info))

    # layer -> [(node, x_nm, y_nm, half_width_nm)] for via/pad/T lookups.
    # Copper that overlaps is connected (as KiCad considers it): a track end
    # is a disc of radius = half the track width, not a point.
    ends_by_layer = {}
    for k, t in enumerate(tracks):
        layer = t.GetLayer()
        a, b = t.GetStart(), t.GetEnd()
        hw = t.GetWidth() / 2.0
        na, nb = _key(a, layer), _key(b, layer)
        link(na, nb, pcbnew.ToMM(t.GetLength()), ("track", k))
        ends_by_layer.setdefault(layer, []).extend([(na, a.x, a.y, hw), (nb, b.x, b.y, hw)])

    # Track ends of the same layer whose copper overlaps (not exactly the
    # same point, e.g. two tracks ending a few um apart): connected
    for layer, ends in ends_by_layer.items():
        for i in range(len(ends)):
            n1, x1, y1, h1 = ends[i]
            for n2, x2, y2, h2 in ends[i + 1:]:
                if n1 != n2 and math.hypot(x1 - x2, y1 - y2) <= max(h1, h2):
                    link(n1, n2, 0.0, ("overlap",))

    # T-junctions: a track end lying on the inside of another track of the
    # same layer splits that track in two
    for k, t in enumerate(tracks):
        layer = t.GetLayer()
        a, b = t.GetStart(), t.GetEnd()
        half_w = t.GetWidth() / 2.0
        for node, x, y, hw_end in ends_by_layer.get(layer, []):
            d, u = _point_seg_dist(x, y, a.x, a.y, b.x, b.y)
            if d <= half_w + hw_end and 0.0 < u < 1.0 and node not in (_key(a, layer), _key(b, layer)):
                L = pcbnew.ToMM(t.GetLength())
                link(node, _key(a, layer), L * u, ("tsplit", k))
                link(node, _key(b, layer), L * (1 - u), ("tsplit", k))

    # Vias: one node per via, linked to the track ends on any layer it spans
    for v in vias:
        pos = v.GetPosition()
        r = _via_radius(v)
        vnode = ("v", pos.x, pos.y)
        for layer, ends in ends_by_layer.items():
            if not v.IsOnLayer(layer):
                continue
            for node, x, y, hw_end in ends:
                if math.hypot(x - pos.x, y - pos.y) <= r + hw_end:
                    link(vnode, node, 0.0, ("via", pos.x, pos.y, layer))

    # Pads: linked to the track ends lying on their copper
    def pad_node(pad):
        # Key by position: the same pad can come as different Python objects
        # (e.g. from the pad list of the dialog and from board.GetPads())
        pos = pad.GetPosition()
        node = ("p", pos.x, pos.y)
        for layer, ends in ends_by_layer.items():
            if not pad.IsOnLayer(layer):
                continue
            for n, x, y, hw_end in ends:
                if _pad_touches(pad, x, y, hw_end, layer):
                    link(node, n, 0.0, ("pad",))
        return node

    # Every pad of the net joins the track ends lying on its copper: two
    # tracks that end in different points of the same pad ARE connected
    # (the pad copper links them), as KiCad itself considers them
    net = tracks[0].GetNetname() if tracks else ""
    for p in board.GetPads():
        if p.GetNetname() == net:
            pad_node(p)

    if pads is not None:
        src, dst = pad_node(pads[0]), pad_node(pads[1])
        if src not in graph or dst not in graph:
            raise ValueError(_("Nessuna traccia collegata a uno dei due pad scelti."))
    else:
        # Free ends: track-end nodes with a single connection (vias and
        # T-junctions give more than one); the farthest-apart pair
        def is_free(n, lst):
            # One track connection, and no via or pad that joins it to
            # another selected track (a via/pad touched only by this end,
            # e.g. the pad where the line starts, does not count)
            tracks_here = [m for m, _w, info in lst if info[0] in ("track", "tsplit")]
            joined = [m for m, _w, info in lst
                      if info[0] in ("via", "pad") and len(graph.get(m, ())) >= 2]
            return len(tracks_here) == 1 and not joined
        free = [n for n, lst in graph.items() if n[0] == "e" and is_free(n, lst)]
        if len(free) < 2:
            raise ValueError(_("Le tracce selezionate formano un anello: non ci sono due estremita' libere."))
        src, dst = max(((a, b) for a in free for b in free),
                       key=lambda ab: (ab[0][1] - ab[1][1]) ** 2 + (ab[0][2] - ab[1][2]) ** 2)

    # --- Dijkstra ---
    dist = {src: 0.0}
    prev = {}
    heap = [(0.0, 0, src)]
    counter = 1
    while heap:
        d, _c, n = heapq.heappop(heap)
        if n == dst:
            break
        if d > dist.get(n, math.inf):
            continue
        for m, w, info in graph.get(n, ()):
            nd = d + w
            if nd < dist.get(m, math.inf):
                dist[m] = nd
                prev[m] = (n, info)
                heapq.heappush(heap, (nd, counter, m))
                counter += 1
    if dst not in dist:
        if pads is None:
            raise ValueError(_("Le tracce selezionate non formano una linea continua."))
        # Diagnostics: the pads that CAN be reached from the start pad, to
        # see where the copper is interrupted
        reach = []
        for p in board.GetPads():
            pos = p.GetPosition()
            if ("p", pos.x, pos.y) in dist and p.GetNetname() == net:
                try:
                    ref = p.GetParentFootprint().GetReference()
                except AttributeError:
                    ref = "?"
                reach.append(f"{ref}.{p.GetNumber()}" if hasattr(p, "GetNumber") else ref)
        raise ValueError(_("I due pad non sono collegati da tracce e via.") + " "
                         + _("Dal pad Da si raggiungono: {0}").format(", ".join(sorted(reach)) or "-"))

    # --- Path reconstruction: nodes from dst back to src ---
    chain = [dst]
    while chain[-1] != src:
        chain.append(prev[chain[-1]][0])
    chain.reverse()

    def xy(node):
        """Position (mm) of a track-end node."""
        return node[1] * _TOL_NM / 1e6, node[2] * _TOL_NM / 1e6

    segments, via_list = [], []
    last_layer = None
    for a, b in zip(chain, chain[1:]):
        if a[0] == "e" and b[0] == "e" and a[3] == b[3]:
            # Track (or part of it) on one layer
            (x0, y0), (x1, y1) = xy(a), xy(b)
            if math.hypot(x1 - x0, y1 - y0) < 1e-6:
                continue
            info = prev[b][1]
            width = pcbnew.ToMM(tracks[info[1]].GetWidth()) if info[0] in ("track", "tsplit") else 0.2
            layer = a[3]
            if last_layer is not None and layer != last_layer and segments:
                # Layer change: through the via at the start of this segment
                via_list.append((x0, y0, last_layer, layer))
            segments.append((x0, y0, x1, y1, layer, width))
            last_layer = layer
    if not segments:
        raise ValueError(_("Percorso troppo corto fra i due pad."))
    return {
        "segments": segments,
        "vias": via_list,
        "length": sum(math.hypot(s[2] - s[0], s[3] - s[1]) for s in segments),
        "stack": stack,
    }


# --------------------------------------------------------------------------
# Paths through series components (resistors, inductors, ferrites, ...)
# --------------------------------------------------------------------------
# Reference prefixes of two-pin parts that the signal current goes THROUGH:
# the current does not end at their pad but continues on the other net, up
# to the real load. C is included: at high frequency a series capacitor
# passes the signal (in DC it blocks it, see series_targets).
SERIES_PREFIXES = ("R", "L", "FB", "FL", "F", "C", "JP", "NT")


def _pad_label(pad):
    """Readable pad label, e.g. 'R2.1' (same format as the DC tab)."""
    try:
        ref = pad.GetParentFootprint().GetReference()
    except AttributeError:
        ref = "?"
    num = pad.GetNumber() if hasattr(pad, "GetNumber") else pad.GetName()
    return f"{ref}.{num}"


def _ref_prefix(ref):
    """Letters at the start of a reference: 'R12' -> 'R', 'FB3' -> 'FB'."""
    out = ""
    for ch in ref:
        if not ch.isalpha():
            break
        out += ch
    return out.upper()


def series_targets(board, net_name, ref_filter="GND", max_hops=4):
    """
    Pads reachable from 'net_name' passing through series two-pin parts.

    For every two-pin part (see SERIES_PREFIXES) with one pad on a net of
    the chain and the other on a different net that is not ground, the
    other net joins the chain. Returns a list of
      (label, pad, crossings)
    where 'crossings' is the list of (pad_in, pad_out, reference) parts
    crossed to get from 'net_name' to the pad's net (empty for the pads of
    'net_name' itself). Ground nets end the chain (the current enters the
    ground there: the part's ground pin is the return point).
    """
    by_net = {}
    for p in board.GetPads():
        by_net.setdefault(p.GetNetname(), []).append(p)

    result = [(_pad_label(p), p, []) for p in by_net.get(net_name, [])]
    seen = {net_name}
    frontier = [(net_name, [])]
    for _hop in range(max_hops):
        nxt = []
        for net, crossings in frontier:
            for pad in by_net.get(net, []):
                try:
                    fp = pad.GetParentFootprint()
                except AttributeError:
                    continue
                if fp is None:
                    continue
                pads = list(fp.Pads())
                if len(pads) != 2 or _ref_prefix(fp.GetReference()) not in SERIES_PREFIXES:
                    continue
                other = pads[1] if pads[0].GetPosition().x == pad.GetPosition().x and \
                    pads[0].GetPosition().y == pad.GetPosition().y else pads[0]
                onet = other.GetNetname()
                if not onet or onet in seen or ref_filter.upper() in onet.upper():
                    continue
                seen.add(onet)
                chain = crossings + [(pad, other, fp.GetReference())]
                for q in by_net.get(onet, []):
                    label = f"{_pad_label(q)} ({_('via')} {', '.join(c[2] for c in chain)})"
                    result.append((label, q, chain))
                nxt.append((onet, chain))
        frontier = nxt
        if not frontier:
            break
    return result


def find_path_through(board, pad_from, pad_to, crossings, dc=False):
    """
    Path from pad_from to pad_to crossing the given series parts: on each
    net the track path to the part, then the part itself (a straight piece
    between its two pads, on the pad layer: the signal current flows
    through the part, and its return under it), and so on up to pad_to.
    Same result format as find_path. In DC a series capacitor blocks the
    current: ValueError.
    """
    if dc:
        caps = [ref for _a, _b, ref in crossings if _ref_prefix(ref) == "C"]
        if caps:
            raise ValueError(_("In continua il condensatore in serie {0} blocca la corrente: "
                               "scegli una destinazione prima del condensatore.").format(", ".join(caps)))
    segments, vias, length = [], [], 0.0
    start = pad_from
    stack = None
    for pad_in, pad_out, _ref in list(crossings) + [(pad_to, None, None)]:
        part = find_path(board, start.GetNetname(), start, pad_in)
        stack = part["stack"]
        if segments and part["segments"] and part["segments"][0][4] != segments[-1][4]:
            # Layer change between two nets (e.g. a through-hole part)
            s = part["segments"][0]
            vias.append((s[0], s[1], segments[-1][4], s[4]))
        segments += part["segments"]
        vias += part["vias"]
        length += part["length"]
        if pad_out is None:
            break
        # The part itself: from the end of the path on this net to the
        # other pad of the part (same layer as the last segment)
        a, b = pad_in.GetPosition(), pad_out.GetPosition()
        last = segments[-1]
        segments.append((last[2], last[3], pcbnew.ToMM(b.x), pcbnew.ToMM(b.y), last[4], last[5]))
        length += pcbnew.ToMM(math.hypot(b.x - a.x, b.y - a.y))
        start = pad_out
    return {"segments": segments, "vias": vias, "length": length, "stack": stack}


def find_loads(board, pad_in, ref_filter="GND", dc=False):
    """
    Loads of the current entering at 'pad_in': every component reached from
    its net (also through series parts, see series_targets) that has a
    ground pin, i.e. where the current enters the ground. Components without
    a ground pin (connectors, test points, series parts) are not loads: no
    current ends there. In DC capacitors are not loads (they block DC).

    Returns [(load_pad, crossings, reference)], one per component (its first
    pad on the signal chain).
    """
    try:
        own = pad_in.GetParentFootprint().GetReference()
    except AttributeError:
        own = None
    loads, seen = [], set()
    for _label, pad, crossings in series_targets(board, pad_in.GetNetname(), ref_filter):
        try:
            fp = pad.GetParentFootprint()
        except AttributeError:
            continue
        if fp is None:
            continue
        ref = fp.GetReference()
        if ref == own or ref in seen:
            continue
        if dc and _ref_prefix(ref) == "C":
            continue
        if dc and any(_ref_prefix(c[2]) == "C" for c in crossings):
            continue  # beyond a series capacitor: no DC current
        if not any(ref_filter.upper() in p.GetNetname().upper() for p in fp.Pads()):
            continue  # no ground pin: not a load
        seen.add(ref)
        loads.append((pad, crossings, ref))
    return loads
