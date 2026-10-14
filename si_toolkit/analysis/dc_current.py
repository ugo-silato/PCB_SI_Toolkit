"""
Modulo "Distribuzione corrente DC".

Costruisce una rete di resistenze dal rame di UNA net (tracce, via, pad),
inietta una corrente fra due pad scelti dall'utente e calcola come si
ripartisce nei rami in parallelo: corrente, caduta di tensione, potenza
dissipata e densita' di corrente per ogni traccia e via.

Modello (volutamente semplice):
- traccia: R = rho * L / (larghezza * spessore rame);
- via: canna cilindrica placcata, R = rho * L / area_anello, dove la
  lunghezza e' lo spessore della board attraversato;
- pad: nodo a resistenza nulla che raccoglie tutte le tracce/via che lo
  toccano (entro il suo raggio);
- le ZONE di rame (pour) NON sono modellate: se la net ha un pour il
  risultato e' pessimistico, perche' ignora il percorso in parallelo
  attraverso il rame versato.

La parte di calcolo (Kirchhoff) e' in dc_solver.py, indipendente da KiCad.
"""
from dataclasses import dataclass

import pcbnew

from . import dc_solver
from .return_path import _copper_layer_stack
from ..common.i18n import _

# Resistivita' del rame a 20 °C (ohm * metro)
RHO_COPPER = 1.72e-8


@dataclass
class DcElement:
    """Risultato per una traccia o una via."""

    kind: str  # "Traccia" oppure "Via"
    item: object  # oggetto pcbnew (per selezionarlo)
    layer_name: str
    current_a: float
    resistance_ohm: float
    drop_v: float
    power_w: float
    density_a_mm2: float
    length_mm: float = 0.0  # solo tracce
    width_mm: float = 0.0  # solo tracce
    potential_v: float = 0.0  # tensione sul lato dell'elemento verso l'ingresso
    limit_a: float = 0.0  # corrente massima ammessa (IPC-2221) per il DT scelto
    ratio: float = 0.0  # corrente / limite (1.0 = al limite)
    v_start: float = 0.0  # tensione all'estremo GetStart() della traccia
    v_end: float = 0.0  # tensione all'estremo GetEnd() della traccia


@dataclass
class DcResult:
    elements: list
    total_resistance_ohm: float
    total_drop_v: float
    total_power_w: float
    has_zones: bool  # la net ha pour di rame
    copper_note: str = ""  # da dove arriva lo spessore del rame usato
    zones_modeled: bool = False  # zone usate come collegamenti a R = 0
    # Per ogni uscita: (etichetta pad, corrente A, caduta V dall'ingresso)
    load_drops: list = None


def list_nets(board):
    """Nomi delle net che hanno almeno un pad o una traccia (ordinati)."""
    names = set()
    for pad in board.GetPads():
        if pad.GetNetname():
            names.add(pad.GetNetname())
    for track in board.GetTracks():
        if track.GetNetname():
            names.add(track.GetNetname())
    return sorted(names)


def pad_label(pad):
    """Etichetta leggibile del pad, es. 'U1.3'."""
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
    """Pad della net, come lista di (etichetta, oggetto pad)."""
    pads = [(pad_label(p), p) for p in board.GetPads() if p.GetNetname() == net_name]
    pads.sort(key=lambda t: t[0])
    return pads


def _radius_nm(item):
    """Raggio approssimato (nm) di un pad o via dal suo bounding box."""
    box = item.GetBoundingBox()
    return max(box.GetWidth(), box.GetHeight()) / 2.0


def copper_thickness_by_layer(board, fallback_um=35.0):
    """
    Spessore del rame (metri) di ogni layer di rame, letto dallo stackup
    della board (Setup board > Stackup fisico). Per i layer senza valore
    nello stackup si usa 'fallback_um'.

    Ritorna (dizionario layer -> metri, testo che spiega la provenienza).
    """
    result = {}
    try:
        from .impedance import _read_real_stackup

        # Stessa lettura (robusta) usata dal calcolatore di impedenza
        stackup, _errors = _read_real_stackup(board)
        result = {layer: info["t"] for layer, info in stackup.items()}
    except Exception:
        result = {}  # stackup non leggibile: si usa il valore di ripiego

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
    Corrente massima (A) di un conduttore secondo IPC-2221:
        I = k * DT^0.44 * A^0.725
    con A = sezione in mil^2, DT = aumento di temperatura ammesso (°C),
    k = 0.048 per layer esterni, 0.024 per layer interni.
    E' una formula empirica per tracce isolate: va presa come stima.
    """
    area_mil2 = (width_mm / 0.0254) * (copper_um / 25.4)
    k = 0.048 if external else 0.024
    return k * (delta_t ** 0.44) * (area_mil2 ** 0.725)


def is_pad(item):
    """Vero se l'oggetto e' un pad (e non una traccia o una via)."""
    return item.Type() == pcbnew.PCB_PAD_T


def selected_items(board):
    """
    Tracce, via e pad selezionati in Pcbnew in questo momento, nell'ordine
    pad prima (se ce ne sono), poi tracce e via.
    """
    pads = [p for p in board.GetPads() if p.IsSelected()]
    tracks = [t for t in board.GetTracks() if t.IsSelected()]
    return pads + tracks


def net_items(board, net_name):
    """Tutti gli oggetti (tracce, via, pad) della net: per evidenziarla."""
    items = [t for t in board.GetTracks() if t.GetNetname() == net_name]
    items += [p for p in board.GetPads() if p.GetNetname() == net_name]
    return items


class _UnionFind:
    """Unisce i nodi che sono lo stesso punto elettrico (resistenza nulla)."""

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
    Calcola la distribuzione di corrente sulla net.

    source_pad / sink_pad: oggetti pad (da list_pads) dove la corrente
    entra ed esce. copper_um: spessore del rame in micron; se None (default)
    viene letto layer per layer dallo stackup della board.
    via_plating_um: spessore di placcatura della canna delle via.
    include_zones: se True le zone di rame della net sono trattate come
    collegamenti a resistenza nulla (ottimistico: ignora la resistenza
    del piano); se False sono ignorate (pessimistico).
    delta_t: aumento di temperatura (°C) ammesso, per il limite di corrente
    IPC-2221 di ogni traccia e via.
    loads: lista di (pad, corrente_A) per piu' uscite; se indicata,
    sink_pad e current_a sono ignorati e la corrente in ingresso e' la
    somma delle correnti dei carichi.
    report_path: se indicato, quando il collegamento non viene trovato scrive
    in quel file di testo il dettaglio dei gruppi di rame (diagnostica).
    Solleva ValueError se la rete non collega i due pad.
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
        # Estremita' di traccia: coordinate arrotondate a 1 µm + layer
        return ("e", round(point.x / 1000), round(point.y / 1000), layer)

    # ---- Raccolta elementi della net ----
    tracks, vias = [], []
    for t in board.GetTracks():
        if t.GetNetname() != net_name:
            continue
        if t.Type() == pcbnew.PCB_VIA_T:
            vias.append(t)
        elif t.Type() in (pcbnew.PCB_TRACE_T, pcbnew.PCB_ARC_T):
            tracks.append(t)
    pads = [p for p in board.GetPads() if p.GetNetname() == net_name]

    # ---- Nodi dei pad e delle via, uniti alle estremita' che li toccano ----
    # Raccolta di tutte le estremita' di traccia (nodo, posizione, layer)
    endpoints = []
    endpoint_widths = []  # larghezza della traccia di ogni estremita' (nm)
    for t in tracks:
        layer = t.GetLayer()
        for pt in (t.GetStart(), t.GetEnd()):
            endpoints.append((end_key(pt, layer), pt, layer))
            endpoint_widths.append(t.GetWidth())

    # Due estremita' sullo stesso layer sono collegate se il rame delle due
    # tracce si sovrappone, cioe' se distano meno della meta' della
    # larghezza maggiore (le estremita' sono tonde). Succede spesso che due
    # tracce si sovrappongano di pochi centesimi di mm senza coincidere:
    # per KiCad sono collegate. Soglia minima 1 um per l'arrotondamento.
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
        # Chiave = etichetta (es. "U1.3"): gli oggetti SWIG vengono ricreati
        # a ogni chiamata, quindi id(pad) non e' stabile fra due chiamate
        pad_nodes[pad_label(pad)] = node
        uf.find(node)
        pos, rad = pad.GetPosition(), _radius_nm(pad)
        for key, pt, layer in endpoints:
            if pad.IsOnLayer(layer) and _dist2(pos, pt) <= rad * rad:
                uf.union(node, key)

    via_chains = []  # per ogni via: lista di (layer, nodo)
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
            # Estremita' di traccia sul layer, dentro il raggio della via
            for key, pt, ep_layer in endpoints:
                if ep_layer == layer and _dist2(pos, pt) <= rad * rad:
                    uf.union(node, key)
            # Pad che toccano la via (via sotto un pad, "via in pad")
            for pad in pads:
                if pad.IsOnLayer(layer) and _dist2(pos, pad.GetPosition()) <= _radius_nm(pad) ** 2:
                    uf.union(node, pad_nodes[pad_label(pad)])
        via_chains.append(chain)


    # ---- Zone di rame (pour) come nodi a resistenza nulla ----
    # Ogni zona della net e' un nodo unico: tutto cio' che cade nel suo
    # rame versato (pad, via, estremita' di traccia) viene unito a quel
    # nodo. E' un'approssimazione ottimistica: la resistenza del piano e'
    # ignorata, e due isole separate della stessa zona risultano collegate.
    zones = []
    if include_zones:
        # Le teardrop sono zone anche loro: se fossero a R = 0
        # cortocircuiterebbero pad e tracce vicine, quindi si escludono
        zones = [z for z in board.Zones()
                 if z.GetNetname() == net_name and z.IsFilled() and not _is_teardrop(z)]
    for zi, zone in enumerate(zones):
        znode = ("z", zi)
        uf.find(znode)
        # Candidati: (nodo, posizione, raggio nm, lista layer)
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

    # ---- Rami della rete ----
    edges = []  # (nodo_a, nodo_b, ohm, (tipo, indice))
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

        # Punti di contatto lungo la traccia (collegamenti "a T"): estremita'
        # di altre tracce, pad e via che toccano il corpo della traccia senza
        # coincidere con le sue estremita'. Per KiCad sono collegati; la
        # traccia va spezzata in quei punti. Solo per tracce rettilinee
        # (gli archi restano un unico ramo).
        splits = []  # (parametro u da 0 a 1 lungo la traccia, nodo)
        if t.Type() == pcbnew.PCB_TRACE_T:
            S, E = t.GetStart(), t.GetEnd()
            dx, dy = E.x - S.x, E.y - S.y
            len2 = dx * dx + dy * dy
            half_w = t.GetWidth() / 2.0 + 1000  # + 1 um di tolleranza

            def try_split(pos, extra_nm, node):
                # Proiezione del punto sul segmento: se cade dentro il
                # segmento e a distanza utile, e' un contatto
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

        # Catena di sotto-rami: la resistenza si divide in proporzione alla
        # lunghezza di ogni pezzo
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
        # Anello di rame della canna: pi * t * (d + t)
        area_m2 = 3.141592653589793 * plating_m * (drill_m + plating_m)
        # Lunghezza: porzione di spessore board attraversata dalla via
        frac = (len(chain) - 1) / max(1, len(stack) - 1)
        r_total = RHO_COPPER * board_thickness_m * frac / area_m2
        r_seg = r_total / (len(chain) - 1)
        for (_l1, n1), (_l2, n2) in zip(chain, chain[1:]):
            edges.append((uf.find(n1), uf.find(n2), r_seg, ("v", k)))

    # ---- Soluzione ----
    if loads is None:
        loads = [(sink_pad, current_a)]
    # Il primo carico fa da "uscita" per i messaggi diagnostici
    sink_pad = loads[0][0]
    current_a = sum(i for _p, i in loads)  # corrente totale in ingresso
    try:
        src = uf.find(pad_nodes[pad_label(source_pad)])
        load_nodes = [(uf.find(pad_nodes[pad_label(p)]), i) for p, i in loads]
    except KeyError:
        raise ValueError(_("Pad sorgente/ritorno non trovati sulla net scelta."))
    snk = load_nodes[0][0]
    try:
        potentials, currents = dc_solver.solve_dc(edges, src, None, 0.0, loads=load_nodes)
    except ValueError as exc:
        # Collegamento non trovato: scrive il rapporto dettagliato dei
        # gruppi di rame (se richiesto) e aggiunge informazioni al messaggio
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

    # ---- Risultati per elemento (le via a catena sommano i segmenti) ----
    # (tipo, k) -> [corrente max, caduta, potenza, resistenza, tensione a monte]
    acc = {}
    for (a, b, r, tag), i in zip(edges, currents):
        e = acc.setdefault(tag, [0.0, 0.0, 0.0, 0.0, 0.0])
        e[0] = max(e[0], abs(i))
        e[1] += abs(i) * r
        e[2] += i * i * r
        e[3] += r
        # Tensione del capo piu' vicino all'ingresso (la sorgente e' la
        # piu' alta, il ritorno e' a 0 V): serve a ordinare il percorso
        e[4] = max(e[4], potentials.get(a, 0.0), potentials.get(b, 0.0))

    elements = []
    for (kind, k), (i, drop, power, r, v_hi) in acc.items():
        if i < 1e-12:
            continue  # ramo senza corrente (fuori dal percorso)
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
                          # Tensioni ai due capi: servono alla mappa per
                          # sfumare il colore lungo la traccia
                          potentials.get(uf.find(end_key(t.GetStart(), t.GetLayer())), v_hi),
                          potentials.get(uf.find(end_key(t.GetEnd(), t.GetLayer())), v_hi))
            )
        else:
            via = vias[k]
            d_mm = pcbnew.ToMM(via.GetDrillValue())
            area_mm2 = 3.141592653589793 * via_plating_um * 1e-3 * (d_mm + via_plating_um * 1e-3)
            # Via: la canna e' un tubo di rame; si usa la stessa formula con
            # la sezione dell'anello (equivalente a una "larghezza" fittizia
            # sezione / spessore di placcatura), come layer esterno
            equiv_width_mm = area_mm2 / (via_plating_um * 1e-3)
            limit = ipc2221_limit_a(equiv_width_mm, via_plating_um, delta_t, True)
            elements.append(
                DcElement("Via", via, f"{board.GetLayerName(via.TopLayer())}-{board.GetLayerName(via.BottomLayer())}",
                          i, r, drop, power, i / area_mm2, 0.0, 0.0, v_hi,
                          limit, i / limit)
            )
    # Ordine del percorso: dall'ingresso (tensione piu' alta) all'uscita
    elements.sort(key=lambda e: e.potential_v, reverse=True)

    # Caduta totale = verso il carico piu' sfavorito (quello a 0 V)
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
    Scrive su file i gruppi di rame collegati fra loro (componenti), con
    pad, numero di tracce, ingombro e le estremita' di traccia "libere"
    (che non toccano altro), indicando i gruppi di sorgente e ritorno.
    Il buco nel collegamento si trova fra le estremita' libere dei due gruppi.
    """
    mm = pcbnew.ToMM
    adj = {}
    for a, b, _r, _tag in edges:
        adj.setdefault(a, set()).add(b)
        adj.setdefault(b, set()).add(a)

    # Nodi radice di pad e via, per riconoscere le estremita' "attaccate"
    pad_root = {uf.find(n): label for label, n in pad_nodes.items()}
    via_roots = set()
    for chain in via_chains:
        for _l, n in chain:
            via_roots.add(uf.find(n))

    # Coordinate delle estremita' per nodo radice
    coords = {}
    for key, pt, layer in endpoints:
        coords.setdefault(uf.find(key), []).append((pt, layer))

    # Componenti connesse (visita del grafo)
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
            # Estremita' libere: nodo con un solo vicino, non pad ne' via
            # (solo per i gruppi di ingresso/uscita e per i piccoli)
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
    Testo diagnostico per il caso "pad non collegati": per sorgente e
    ritorno, quanti rami toccano il loro nodo e quanto dista l'estremita'
    di traccia piu' vicina; poi quali pad si raggiungono dalla sorgente.
    """
    # Insiemi di nodi raggiungibili dalla sorgente (visita del grafo)
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
    """True se la zona e' una teardrop generata da KiCad."""
    fn = getattr(zone, "IsTeardropArea", None)  # API KiCad 8+
    if fn is not None:
        try:
            return bool(fn())
        except Exception:
            pass
    # Ripiego: KiCad chiama le teardrop "$teardrop_..."
    try:
        return "teardrop" in zone.GetZoneName().lower()
    except Exception:
        return False


def _covered_by_zone(zone, layer, pos, rad_nm):
    """
    Vero se il punto (o l'area di un pad/via) tocca il rame versato della
    zona. Si prova il centro e un anello di 8 punti appena fuori dal
    raggio: un pad con thermal relief ha il centro scoperto ma gli spoke
    toccano l'anello.
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
    """Distanza al quadrato fra due punti (nm^2)."""
    dx, dy = p.x - q.x, p.y - q.y
    return dx * dx + dy * dy
