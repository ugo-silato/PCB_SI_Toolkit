"""
"DC current distribution" module.

Builds a resistor network from the copper of ONE net (tracks, vias, pads),
injects current at an input pad, draws it at one or more output pads and
computes how it splits among the parallel branches: current, voltage drop,
dissipated power, current density and IPC-2221 limit for every track and
via.

Model (deliberately simple):
- track: R = rho * L / (width * copper thickness), thickness from the
  board stackup;
- via: plated cylindrical barrel, R = rho * L / ring_area, where the
  length is the board thickness crossed;
- pad: zero-resistance node collecting all the tracks/vias touching it
  (within its radius);
- copper ZONES (pours): optionally treated as zero-resistance nodes
  (optimistic result); otherwise ignored (pessimistic result). Teardrops
  are always excluded.

The calculation part (Kirchhoff) is in dc_solver.py, independent of KiCad.
"""
from dataclasses import dataclass

import pcbnew

from . import dc_solver
from .return_path import _copper_layer_stack
from ..common.i18n import _

# Copper resistivity at 20 °C (ohm * meter)
RHO_COPPER = 1.72e-8


@dataclass
class DcElement:
    """Result for one track or via."""

    kind: str  # "Traccia" (track) or "Via"
    item: object  # pcbnew object (to select it)
    layer_name: str
    current_a: float
    resistance_ohm: float
    drop_v: float
    power_w: float
    density_a_mm2: float
    length_mm: float = 0.0  # tracks only
    width_mm: float = 0.0  # tracks only
    potential_v: float = 0.0  # voltage on the side of the element facing the input
    limit_a: float = 0.0  # maximum allowed current (IPC-2221) for the chosen DT
    ratio: float = 0.0  # current / limit (1.0 = at the limit)
    v_start: float = 0.0  # voltage at the GetStart() end of the track
    v_end: float = 0.0  # voltage at the GetEnd() end of the track


@dataclass
class DcResult:
    elements: list
    total_resistance_ohm: float
    total_drop_v: float
    total_power_w: float
    has_zones: bool  # the net has copper pours
    copper_note: str = ""  # where the copper thickness used comes from
    zones_modeled: bool = False  # zones used as R = 0 connections
    # For each output: (pad label, current A, drop V from the input)
    load_drops: list = None


def list_nets(board):
    """Names of the nets having at least one pad or track (sorted)."""
    names = set()
    for pad in board.GetPads():
        if pad.GetNetname():
            names.add(pad.GetNetname())
    for track in board.GetTracks():
        if track.GetNetname():
            names.add(track.GetNetname())
    return sorted(names)


def pad_label(pad):
    """Readable pad label, e.g. 'U1.3'."""
    try:
        ref = pad.GetParentFootprint().GetReference()
    except AttributeError:
        ref = pad.GetParent().GetReference()
    try:
        number = pad.GetNumber()
    except AttributeError:
        number = pad.GetName()
    return f"{ref}.{number}"


def list_pads(board, net_name):
    """Pads of the net, as a list of (label, pad object)."""
    pads = [(pad_label(p), p) for p in board.GetPads() if p.GetNetname() == net_name]
    pads.sort(key=lambda t: t[0])
    return pads


def _radius_nm(item):
    """Approximate radius (nm) of a pad or via from its bounding box."""
    box = item.GetBoundingBox()
    return max(box.GetWidth(), box.GetHeight()) / 2.0


def copper_thickness_by_layer(board, fallback_um=35.0):
    """
    Copper thickness (meters) of every copper layer, read from the board
    stackup (Board Setup > Physical Stackup). For layers without a value in
    the stackup 'fallback_um' is used.

    Returns (dictionary layer -> meters, text explaining the source).
    """
    result = {}
    try:
        from .impedance import _read_real_stackup

        # Same (robust) reading used by the impedance calculator
        stackup, _errors = _read_real_stackup(board)
        result = {layer: info["t"] for layer, info in stackup.items()}
    except Exception:
        result = {}  # stackup not readable: the fallback value is used

    missing = [l for l in _copper_layer_stack(board) if l not in result]
    for layer in missing:
        result[layer] = fallback_um * 1e-6
    if not missing:
        return result, _("rame da stackup")
    if len(missing) == len(_copper_layer_stack(board)):
        return result, _("rame {0:g} um (stackup non disponibile)").format(fallback_um)
    return result, _("rame da stackup (+{0:g} um su alcuni layer)").format(fallback_um)


def ipc2221_limit_a(width_mm, copper_um, delta_t, external):
    """
    Maximum current (A) of a conductor according to IPC-2221:
        I = k * DT^0.44 * A^0.725
    with A = cross-section in mil^2, DT = allowed temperature rise (°C),
    k = 0.048 for outer layers, 0.024 for inner layers.
    It is an empirical formula for isolated tracks: take it as an estimate.
    """
    area_mil2 = (width_mm / 0.0254) * (copper_um / 25.4)
    k = 0.048 if external else 0.024
    return k * (delta_t ** 0.44) * (area_mil2 ** 0.725)


def is_pad(item):
    """True if the object is a pad (and not a track or a via)."""
    return item.Type() == pcbnew.PCB_PAD_T


def selected_items(board):
    """
    Tracks, vias and pads currently selected in Pcbnew, with pads first (if
    any), then tracks and vias.
    """
    pads = [p for p in board.GetPads() if p.IsSelected()]
    tracks = [t for t in board.GetTracks() if t.IsSelected()]
    return pads + tracks


def net_items(board, net_name):
    """All the objects (tracks, vias, pads) of the net: to highlight it."""
    items = [t for t in board.GetTracks() if t.GetNetname() == net_name]
    items += [p for p in board.GetPads() if p.GetNetname() == net_name]
    return items


class _UnionFind:
    """Merges the nodes that are the same electrical point (zero resistance)."""

    def __init__(self):
        self.parent = {}

    def find(self, x):
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb


def analyze_net(
    board,
    net_name,
    source_pad,
    sink_pad,
    current_a,
    copper_um=None,
    via_plating_um=25.0,
    include_zones=True,
    report_path=None,
    delta_t=10.0,
    loads=None,
):
    """
    Computes the current distribution on the net.

    source_pad / sink_pad: pad objects (from list_pads) where the current
    enters and leaves. copper_um: copper thickness in microns; if None
    (default) it is read layer by layer from the board stackup.
    via_plating_um: plating thickness of the via barrel.
    include_zones: if True the copper zones of the net are treated as
    zero-resistance connections (optimistic: ignores the plane resistance);
    if False they are ignored (pessimistic).
    delta_t: allowed temperature rise (°C), for the IPC-2221 current limit of
    every track and via.
    loads: list of (pad, current_A) for several outputs; if given, sink_pad
    and current_a are ignored and the input current is the sum of the load
    currents.
    report_path: if given, when the connection is not found the details of
    the copper groups are written to that text file (diagnostics).
    Raises ValueError if the network does not connect the pads.
    """
    if copper_um is None:
        copper_by_layer, copper_note = copper_thickness_by_layer(board)
    else:
        copper_by_layer = {l: copper_um * 1e-6 for l in _copper_layer_stack(board)}
        copper_note = _("rame {0:g} um (impostato a mano)").format(copper_um)
    plating_m = via_plating_um * 1e-6
    stack = _copper_layer_stack(board)
    board_thickness_m = pcbnew.ToMM(board.GetDesignSettings().GetBoardThickness()) * 1e-3

    uf = _UnionFind()

    def end_key(point, layer):
        # Track ends: coordinates rounded to 1 µm + layer
        return ("e", round(point.x / 1000), round(point.y / 1000), layer)

    # ---- Collect the elements of the net ----
    tracks, vias = [], []
    for t in board.GetTracks():
        if t.GetNetname() != net_name:
            continue
        if t.Type() == pcbnew.PCB_VIA_T:
            vias.append(t)
        elif t.Type() in (pcbnew.PCB_TRACE_T, pcbnew.PCB_ARC_T):
            tracks.append(t)
    pads = [p for p in board.GetPads() if p.GetNetname() == net_name]

    # ---- Pad and via nodes, merged with the track ends touching them ----
    # Collect all the track ends (node, position, layer)
    endpoints = []
    endpoint_widths = []  # track width at each end (nm)
    for t in tracks:
        layer = t.GetLayer()
        for pt in (t.GetStart(), t.GetEnd()):
            endpoints.append((end_key(pt, layer), pt, layer))
            endpoint_widths.append(t.GetWidth())

    # Two ends on the same layer are connected if the copper of the two tracks
    # overlaps, i.e. if they are closer than half the larger width (the ends
    # are round). Two tracks often overlap by a few hundredths of a mm without
    # coinciding: for KiCad they are connected. Minimum threshold 1 um for
    # rounding.
    for i, (k1, p1, l1) in enumerate(endpoints):
        for j in range(i + 1, len(endpoints)):
            k2, p2, l2 = endpoints[j]
            if l1 != l2:
                continue
            reach = max(endpoint_widths[i], endpoint_widths[j]) / 2.0
            reach = max(reach, 1000.0)
            if _dist2(p1, p2) <= reach * reach:
                uf.union(k1, k2)

    pad_nodes = {}
    for k, pad in enumerate(pads):
        node = ("p", k)
        # Key = label (e.g. "U1.3"): SWIG objects are recreated at every call,
        # so id(pad) is not stable between two calls
        pad_nodes[pad_label(pad)] = node
        uf.find(node)
        pos, rad = pad.GetPosition(), _radius_nm(pad)
        for key, pt, layer in endpoints:
            if pad.IsOnLayer(layer) and _dist2(pos, pt) <= rad * rad:
                uf.union(node, key)

    via_chains = []  # for each via: list of (layer, node)
    for k, via in enumerate(vias):
        pos, rad = via.GetPosition(), _radius_nm(via)
        top, bottom = via.TopLayer(), via.BottomLayer()
        try:
            i0, i1 = sorted((stack.index(top), stack.index(bottom)))
        except ValueError:
            via_chains.append([])
            continue
        chain = []
        for layer in stack[i0 : i1 + 1]:
            node = ("v", k, layer)
            uf.find(node)
            chain.append((layer, node))
            # Track ends on the layer, within the via radius
            for key, pt, ep_layer in endpoints:
                if ep_layer == layer and _dist2(pos, pt) <= rad * rad:
                    uf.union(node, key)
            # Pads touching the via (via under a pad, "via in pad")
            for pad in pads:
                if pad.IsOnLayer(layer) and _dist2(pos, pad.GetPosition()) <= _radius_nm(pad) ** 2:
                    uf.union(node, pad_nodes[pad_label(pad)])
        via_chains.append(chain)


    # ---- Copper zones (pours) as zero-resistance nodes ----
    # Each zone of the net is a single node: everything falling in its poured
    # copper (pads, vias, track ends) is merged into that node. It is an
    # optimistic approximation: the plane resistance is ignored, and two
    # separate islands of the same zone end up connected.
    zones = []
    if include_zones:
        # Teardrops are zones too: at R = 0 they would short nearby pads and
        # tracks, so they are excluded
        zones = [z for z in board.Zones()
                 if z.GetNetname() == net_name and z.IsFilled() and not _is_teardrop(z)]
    for zi, zone in enumerate(zones):
        znode = ("z", zi)
        uf.find(znode)
        # Candidates: (node, position, radius nm, list of layers)
        candidates = []
        for key, pt, layer in endpoints:
            candidates.append((key, pt, 0, [layer]))
        for pad in pads:
            layers = [l for l in stack if pad.IsOnLayer(l)]
            candidates.append((pad_nodes[pad_label(pad)], pad.GetPosition(), _radius_nm(pad), layers))
        for k, via in enumerate(vias):
            for layer, node in via_chains[k]:
                candidates.append((node, via.GetPosition(), _radius_nm(via), [layer]))
        for node, pos, rad, layers in candidates:
            for layer in layers:
                if zone.IsOnLayer(layer) and _covered_by_zone(zone, layer, pos, rad):
                    uf.union(znode, node)
                    break

    # ---- Network branches ----
    edges = []  # (node_a, node_b, ohm, (type, index))
    for k, t in enumerate(tracks):
        layer = t.GetLayer()
        length_m = pcbnew.ToMM(t.GetLength()) * 1e-3
        width_m = pcbnew.ToMM(t.GetWidth()) * 1e-3
        if length_m <= 0 or width_m <= 0:
            continue
        copper_m = copper_by_layer.get(layer, 35e-6)
        r = RHO_COPPER * length_m / (width_m * copper_m)
        start_node = uf.find(end_key(t.GetStart(), layer))
        end_node = uf.find(end_key(t.GetEnd(), layer))

        # Contact points along the track ("T" connections): ends of other
        # tracks, pads and vias touching the body of the track without
        # coinciding with its ends. For KiCad they are connected; the track
        # must be split at those points. Straight tracks only (arcs stay a
        # single branch).
        splits = []  # (parameter u from 0 to 1 along the track, node)
        if t.Type() == pcbnew.PCB_TRACE_T:
            S, E = t.GetStart(), t.GetEnd()
            dx, dy = E.x - S.x, E.y - S.y
            len2 = dx * dx + dy * dy
            half_w = t.GetWidth() / 2.0 + 1000  # + 1 um tolerance

            def try_split(pos, extra_nm, node):
                # Projection of the point on the segment: if it falls inside
                # the segment and close enough, it is a contact
                if len2 == 0:
                    return
                u = ((pos.x - S.x) * dx + (pos.y - S.y) * dy) / len2
                if not 0.0 < u < 1.0:
                    return
                perp = abs((pos.x - S.x) * dy - (pos.y - S.y) * dx) / (len2 ** 0.5)
                if perp <= half_w + extra_nm:
                    splits.append((u, node))

            for key, pt, ep_layer in endpoints:
                if ep_layer == layer:
                    try_split(pt, 0, key)
            for pad in pads:
                if pad.IsOnLayer(layer):
                    try_split(pad.GetPosition(), _radius_nm(pad), pad_nodes[pad_label(pad)])
            for vk, via in enumerate(vias):
                for v_layer, v_node in via_chains[vk]:
                    if v_layer == layer:
                        try_split(via.GetPosition(), _radius_nm(via), v_node)

        # Chain of sub-branches: the resistance is split in proportion to the
        # length of each piece
        points = [(0.0, start_node)]
        points += sorted((u, uf.find(n)) for u, n in splits)
        points.append((1.0, end_node))
        for (u1, n1), (u2, n2) in zip(points, points[1:]):
            if n1 != n2:
                edges.append((n1, n2, r * (u2 - u1), ("t", k)))

    for k, via in enumerate(vias):
        chain = via_chains[k]
        if len(chain) < 2:
            continue
        drill_m = pcbnew.ToMM(via.GetDrillValue()) * 1e-3
        # Copper ring of the barrel: pi * t * (d + t)
        area_m2 = 3.141592653589793 * plating_m * (drill_m + plating_m)
        # Length: portion of the board thickness crossed by the via
        frac = (len(chain) - 1) / max(1, len(stack) - 1)
        r_total = RHO_COPPER * board_thickness_m * frac / area_m2
        r_seg = r_total / (len(chain) - 1)
        for (_l1, n1), (_l2, n2) in zip(chain, chain[1:]):
            edges.append((uf.find(n1), uf.find(n2), r_seg, ("v", k)))

    # ---- Solution ----
    if loads is None:
        loads = [(sink_pad, current_a)]
    # The first load acts as "output" for the diagnostic messages
    sink_pad = loads[0][0]
    current_a = sum(i for _p, i in loads)  # total input current
    try:
        src = uf.find(pad_nodes[pad_label(source_pad)])
        load_nodes = [(uf.find(pad_nodes[pad_label(p)]), i) for p, i in loads]
    except KeyError:
        raise ValueError(_("Pad sorgente/ritorno non trovati sulla net scelta."))
    snk = load_nodes[0][0]
    try:
        potentials, currents = dc_solver.solve_dc(edges, src, None, 0.0, loads=load_nodes)
    except ValueError as exc:
        # Connection not found: writes the detailed report of the copper groups
        # (if requested) and adds information to the message
        if report_path:
            try:
                _write_cluster_report(
                    report_path, board, edges, uf, tracks, vias, pads,
                    pad_nodes, via_chains, endpoints, src, snk,
                )
            except Exception as rep_exc:
                exc = ValueError(_("{0} (rapporto non scritto: {1})").format(exc, rep_exc))
        raise ValueError(
            f"{exc} | " + _explain_disconnection(
                edges, uf, pads, pad_nodes, endpoints, source_pad, sink_pad, src
            )
        )

    # ---- Results per element (chained vias add up their segments) ----
    # (type, k) -> [max current, drop, power, resistance, upstream voltage]
    acc = {}
    for (a, b, r, tag), i in zip(edges, currents):
        e = acc.setdefault(tag, [0.0, 0.0, 0.0, 0.0, 0.0])
        e[0] = max(e[0], abs(i))
        e[1] += abs(i) * r
        e[2] += i * i * r
        e[3] += r
        # Voltage of the end closest to the input (the source is the highest,
        # the return is at 0 V): used to order the path
        e[4] = max(e[4], potentials.get(a, 0.0), potentials.get(b, 0.0))

    elements = []
    for (kind, k), (i, drop, power, r, v_hi) in acc.items():
        if i < 1e-12:
            continue  # branch without current (outside the path)
        if kind == "t":
            t = tracks[k]
            copper_mm = copper_by_layer.get(t.GetLayer(), 35e-6) * 1e3
            area_mm2 = pcbnew.ToMM(t.GetWidth()) * copper_mm
            external = t.GetLayer() in (pcbnew.F_Cu, pcbnew.B_Cu)
            limit = ipc2221_limit_a(
                pcbnew.ToMM(t.GetWidth()), copper_mm * 1e3, delta_t, external
            )
            elements.append(
                DcElement("Traccia", t, t.GetLayerName(), i, r, drop, power,
                          i / area_mm2, pcbnew.ToMM(t.GetLength()),
                          pcbnew.ToMM(t.GetWidth()), v_hi, limit, i / limit,
                          # Voltages at the two ends: used by the map to shade
                          # the color along the track
                          potentials.get(uf.find(end_key(t.GetStart(), t.GetLayer())), v_hi),
                          potentials.get(uf.find(end_key(t.GetEnd(), t.GetLayer())), v_hi))
            )
        else:
            via = vias[k]
            d_mm = pcbnew.ToMM(via.GetDrillValue())
            area_mm2 = 3.141592653589793 * via_plating_um * 1e-3 * (d_mm + via_plating_um * 1e-3)
            # Via: the barrel is a copper tube; the same formula is used with
            # the ring cross-section (equivalent to a fictitious "width" =
            # cross-section / plating thickness), as an outer layer
            equiv_width_mm = area_mm2 / (via_plating_um * 1e-3)
            limit = ipc2221_limit_a(equiv_width_mm, via_plating_um, delta_t, True)
            elements.append(
                DcElement("Via", via, f"{board.GetLayerName(via.TopLayer())}-{board.GetLayerName(via.BottomLayer())}",
                          i, r, drop, power, i / area_mm2, 0.0, 0.0, v_hi,
                          limit, i / limit)
            )
    # Path order: from the input (highest voltage) to the output
    elements.sort(key=lambda e: e.potential_v, reverse=True)

    # Total drop = towards the worst-case load (the one at 0 V)
    total_drop = potentials[src]
    load_drops = [(pad_label(p), i, potentials[src] - potentials.get(n, 0.0))
                  for (p, i), (n, _i) in zip(loads, load_nodes)]
    has_zones = any(z.GetNetname() == net_name and not _is_teardrop(z) for z in board.Zones())
    return DcResult(
        elements=elements,
        total_resistance_ohm=total_drop / current_a if current_a else 0.0,
        total_drop_v=total_drop,
        total_power_w=sum(e.power_w for e in elements),
        has_zones=has_zones,
        copper_note=copper_note,
        zones_modeled=bool(zones),
        load_drops=load_drops,
    )


def _write_cluster_report(path, board, edges, uf, tracks, vias, pads,
                          pad_nodes, via_chains, endpoints, src, snk):
    """
    Writes to a file the groups of copper connected together (components),
    with pads, number of tracks, extent and the "free" track ends (touching
    nothing else), marking the source and return groups.
    The hole in the connection is between the free ends of the two groups.
    """
    mm = pcbnew.ToMM
    adj = {}
    for a, b, _r, _tag in edges:
        adj.setdefault(a, set()).add(b)
        adj.setdefault(b, set()).add(a)

    # Root nodes of pads and vias, to recognize the "attached" ends
    pad_root = {uf.find(n): label for label, n in pad_nodes.items()}
    via_roots = set()
    for chain in via_chains:
        for _l, n in chain:
            via_roots.add(uf.find(n))

    # Coordinates of the ends per root node
    coords = {}
    for key, pt, layer in endpoints:
        coords.setdefault(uf.find(key), []).append((pt, layer))

    # Connected components (graph traversal)
    seen, comps = set(), []
    for start in list(adj) + list(pad_root):
        if start in seen:
            continue
        comp, stack = {start}, [start]
        seen.add(start)
        while stack:
            n = stack.pop()
            for m in adj.get(n, ()):
                if m not in seen:
                    seen.add(m)
                    comp.add(m)
                    stack.append(m)
        comps.append(comp)
    comps.sort(key=len, reverse=True)

    with open(path, "w", encoding="utf-8") as f:
        f.write(_("Rapporto collegamenti - {0} tracce, {1} via, {2} pad\n").format(len(tracks), len(vias), len(pads)))
        f.write(_("Coordinate in mm (x, y). INGRESSO e USCITA indicano i gruppi dei due pad.\n\n"))
        for ci, comp in enumerate(comps, 1):
            tag = ""
            if src in comp:
                tag += _(" [INGRESSO]")
            if snk in comp:
                tag += _(" [USCITA]")
            comp_pads = sorted(label for r, label in pad_root.items() if r in comp)
            comp_tracks = {t for a, _b, _r, t in edges if a in comp and t[0] == "t"}
            comp_vias = {t for a, _b, _r, t in edges if a in comp and t[0] == "v"}
            xs, ys = [], []
            for n in comp:
                for pt, _l in coords.get(n, ()):
                    xs.append(mm(pt.x))
                    ys.append(mm(pt.y))
            bbox = (f"x {min(xs):.2f}..{max(xs):.2f}, y {min(ys):.2f}..{max(ys):.2f}"
                    if xs else "n/d")
            f.write(_("Gruppo {0}{1}: {2} tracce, {3} via, pad: {4}; ingombro {5}\n").format(ci, tag, len(comp_tracks), len(comp_vias), ', '.join(comp_pads) or '-', bbox))
            # Free ends: node with a single neighbour, neither pad nor via
            # (only for the input/output groups and the small ones)
            if tag or len(comp_tracks) <= 6:
                for n in comp:
                    if len(adj.get(n, ())) <= 1 and n not in pad_root and n not in via_roots:
                        for pt, layer in coords.get(n, ()):
                            f.write(_("    estremita' libera a ({0:.3f}, {1:.3f}) su {2}\n").format(mm(pt.x), mm(pt.y), board.GetLayerName(layer)))
        f.write(_("\nPad della net (posizione):\n"))
        for pad in sorted(pads, key=pad_label):
            pos = pad.GetPosition()
            f.write(f"    {pad_label(pad)} a ({mm(pos.x):.3f}, {mm(pos.y):.3f})\n")


def _explain_disconnection(edges, uf, pads, pad_nodes, endpoints, source_pad, sink_pad, src):
    """
    Diagnostic text for the "pads not connected" case: for source and return,
    how many branches touch their node and how far the nearest track end is;
    then which pads can be reached from the source.
    """
    # Sets of nodes reachable from the source (graph traversal)
    adj = {}
    for a, b, _r, _tag in edges:
        adj.setdefault(a, set()).add(b)
        adj.setdefault(b, set()).add(a)
    seen, stack = {src}, [src]
    while stack:
        n = stack.pop()
        for m in adj.get(n, ()):
            if m not in seen:
                seen.add(m)
                stack.append(m)

    parts = []
    for name, pad in ((_("ingresso"), source_pad), (_("uscita"), sink_pad)):
        node = uf.find(pad_nodes[pad_label(pad)])
        degree = len(adj.get(node, ()))
        pos = pad.GetPosition()
        best = min((_dist2(pos, pt) for _k, pt, _l in endpoints), default=None)
        near = _("nessuna traccia sulla net") if best is None else _("{0:.2f} mm").format(pcbnew.ToMM(best ** 0.5))
        parts.append(_("{0} {1}: {2} rami collegati, estremita' di traccia piu' vicina a {3}").format(name, pad_label(pad), degree, near))

    reachable = sorted(
        pad_label(p) for p in pads if uf.find(pad_nodes[pad_label(p)]) in seen
    )
    parts.append(_("dall'ingresso si raggiungono: ") + (", ".join(reachable) or _("nessun pad")))
    return "; ".join(parts)


def _is_teardrop(zone):
    """True if the zone is a teardrop generated by KiCad."""
    fn = getattr(zone, "IsTeardropArea", None)  # KiCad 8+ API
    if fn is not None:
        try:
            return bool(fn())
        except Exception:
            pass
    # Fallback: KiCad names teardrops "$teardrop_..."
    try:
        return "teardrop" in zone.GetZoneName().lower()
    except Exception:
        return False


def _covered_by_zone(zone, layer, pos, rad_nm):
    """
    True if the point (or the area of a pad/via) touches the poured copper of
    the zone. The centre and a ring of 8 points just outside the radius are
    tested: a pad with thermal relief has an uncovered centre but the spokes
    touch the ring.
    """
    import math

    ring = rad_nm + pcbnew.FromMM(0.25)
    points = [(pos.x, pos.y)]
    for a in range(8):
        ang = a * math.pi / 4
        points.append((pos.x + ring * math.cos(ang), pos.y + ring * math.sin(ang)))
    for x, y in points:
        if zone.HitTestFilledArea(layer, pcbnew.VECTOR2I(int(x), int(y)), 0):
            return True
    return False


def _dist2(p, q):
    """Squared distance between two points (nm^2)."""
    dx, dy = p.x - q.x, p.y - q.y
    return dx * dx + dy * dy
