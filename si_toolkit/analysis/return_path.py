"""
Modulo "Return Path Checker".

Idea di base: il ritorno di corrente ad alta frequenza di una traccia di
segnale scorre nel piano di riferimento immediatamente adiacente (sopra
o sotto), seguendo il percorso della traccia stessa per minimizzare
l'area del loop. Se in un tratto del percorso il piano è assente (split,
foro, area isolata) il ritorno deve "saltare" lateralmente, aumentando
area di loop, EMI e impedenza vista dal segnale.

Questo modulo NON fa un vero solve a campi elettromagnetici: è un
controllo geometrico di continuità. Per ogni traccia misura il GAP
CONTINUO più lungo (in mm) in cui il piano di riferimento manca sotto
(o sopra) la traccia, e segnala solo i gap sopra una soglia.

Perché il gap e non il numero di punti scoperti:
- su una board a 2 layer il pour del lato opposto viene interrotto da
  ogni traccia che lo attraversa; un incrocio perpendicolare crea un gap
  di mezzo millimetro, praticamente innocuo, mentre un gap di 10-20 mm
  sotto una traccia veloce è un problema vero;
- i fori di clearance attorno a pad e via della stessa net non sono
  discontinuità del ritorno (la corrente passa dalla via stessa), quindi
  i punti vicini a questi elementi vengono ignorati.
"""
from dataclasses import dataclass, field

import pcbnew

from ..common import geometry
from ..common.i18n import _

# Distanza di campionamento lungo la traccia (0.5 mm) e tetto massimo di
# campioni per traccia (le tracce molto lunghe vengono campionate più
# rado ma con un limite fisso al costo di calcolo)
SAMPLE_STEP_NM = pcbnew.FromMM(0.5)
MAX_SAMPLES_PER_TRACK = 200

# Raggio di ricerca per una via di stitching vicino a un tratto scoperto:
# se c'è una via sulla net di riferimento entro questo raggio, il ritorno
# può comunque passare lì vicino, quindi il problema è "minore"
STITCHING_SEARCH_RADIUS_NM = pcbnew.FromMM(3.0)

# Raggio attorno a pad e via della STESSA net della traccia entro cui un
# punto scoperto viene ignorato (foro di clearance nel piano)
HOLE_EXCLUSION_RADIUS_NM = pcbnew.FromMM(1.0)

# Gap minimo (mm) per segnalare una traccia, se non specificato dalla GUI
DEFAULT_MIN_GAP_MM = 5.0


@dataclass
class ReturnPathIssue:
    """Un problema di continuità rilevato su una traccia."""

    track: object  # riferimento all'oggetto PCB_TRACK di pcbnew
    uncovered_points: list = field(default_factory=list)  # solo gap sopra soglia
    max_gap_mm: float = 0.0
    has_nearby_stitching_via: bool = False
    # Net reale del piano di riferimento e nome del layer su cui il piano
    # risulta interrotto (mostrati nella colonna "Riferimento" della GUI)
    ref_net: str = ""
    ref_layer_name: str = ""

    @property
    def track_layer_name(self):
        # Nome del layer su cui sta la traccia (es. "B.Cu")
        return self.track.GetLayerName()

    @property
    def net_name(self):
        return self.track.GetNetname()

    @property
    def length_mm(self):
        return pcbnew.ToMM(self.track.GetLength())


def _copper_layer_stack(board):
    """
    Lista dei layer di rame abilitati, dal più esterno (top) al più
    interno (bottom), nell'ordine fisico dello stack-up.
    """
    return list(board.GetEnabledLayers().CuStack())


def _adjacent_layers(board, layer_id):
    """Layer di rame fisicamente adiacenti a 'layer_id' (sopra e/o sotto)."""
    stack = _copper_layer_stack(board)
    try:
        idx = stack.index(layer_id)
    except ValueError:
        return []

    adjacent = []
    if idx - 1 >= 0:
        adjacent.append(stack[idx - 1])
    if idx + 1 < len(stack):
        adjacent.append(stack[idx + 1])
    return adjacent


def _build_indexes(board):
    """
    Precalcola UNA SOLA VOLTA due indici, per non scansionare la board
    per ogni punto:
    - via_index: solo le via, tuple (posizione, net), per il controllo
      di stitching;
    - hole_index: via + pad, tuple (posizione, net), per ignorare i fori
      di clearance attorno a elementi della stessa net della traccia.

    NOTA: si usa Type() == ... e non IsType([...]) perché IsType con la
    lista fallisce con un errore SWIG in questa build di KiCad 10.
    """
    via_index = []
    hole_index = []
    for track in board.GetTracks():
        if track.Type() != pcbnew.PCB_VIA_T:
            continue
        entry = (track.GetPosition(), track.GetNetname())
        via_index.append(entry)
        hole_index.append(entry)
    for pad in board.GetPads():
        hole_index.append((pad.GetPosition(), pad.GetNetname()))
    return via_index, hole_index


def _near_item_on_net(index, point, net_name, radius_nm):
    """Vero se nell'indice c'è un elemento della net data entro il raggio."""
    r2 = radius_nm * radius_nm
    for pos, net in index:
        if net != net_name:
            continue
        dx = pos.x - point.x
        dy = pos.y - point.y
        if dx * dx + dy * dy <= r2:
            return True
    return False


def _uncovered_runs(flags):
    """
    Dato un elenco di booleani (True = punto scoperto) ritorna la lista
    dei tratti consecutivi scoperti come tuple (indice_inizio, indice_fine)
    con fine inclusa.
    """
    runs = []
    start = None
    for i, flag in enumerate(flags):
        if flag and start is None:
            start = i
        elif not flag and start is not None:
            runs.append((start, i - 1))
            start = None
    if start is not None:
        runs.append((start, len(flags) - 1))
    return runs


def analyze_board(
    board,
    reference_net_filter="GND",
    min_gap_mm=DEFAULT_MIN_GAP_MM,
    progress_callback=None,
    should_cancel=None,
):
    """
    Analizza le tracce di segnale e ritorna la lista di ReturnPathIssue
    (ordinata dal gap più lungo al più corto).

    reference_net_filter: sottostringa che identifica le zone di piano di
    riferimento (default "GND").

    min_gap_mm: lunghezza minima (mm) di un tratto continuo senza piano
    perché la traccia venga segnalata.

    progress_callback(indice, totale): chiamata dopo ogni traccia; la GUI
    la usa anche per processare gli eventi (wx.Yield()).

    should_cancel(): se ritorna True l'analisi si ferma e restituisce
    quanto trovato fino a quel momento.
    """
    issues = []
    # Type() == ... invece di IsType([...]) (vedi _build_indexes)
    tracks = [t for t in board.GetTracks() if t.Type() == pcbnew.PCB_TRACE_T]
    total = len(tracks)

    via_index, hole_index = _build_indexes(board)

    # Cache delle zone di riferimento per layer
    zones_cache = {}

    def get_reference_zones(layer_id):
        if layer_id not in zones_cache:
            zones_cache[layer_id] = geometry.find_reference_zones(
                board, layer_id, reference_net_filter
            )
        return zones_cache[layer_id]

    for i, track in enumerate(tracks):
        if progress_callback:
            progress_callback(i, total)
        if should_cancel and should_cancel():
            break

        # Le tracce sulla net di riferimento non sono "segnale"
        if reference_net_filter.upper() in track.GetNetname().upper():
            continue

        layer_id = track.GetLayer()

        # Layer adiacenti che hanno almeno una zona di riferimento. Ognuno
        # viene controllato SEPARATAMENTE: su 4+ layer una traccia interna
        # ha un piano sopra e uno sotto, e l'interruzione puo' riguardare
        # solo uno dei due. Ogni coppia (traccia, layer) e' un possibile
        # problema a se' stante.
        ref_candidates = []
        for candidate_layer in _adjacent_layers(board, layer_id):
            candidate_zones = get_reference_zones(candidate_layer)
            if candidate_zones:
                ref_candidates.append((candidate_layer, candidate_zones))

        if not ref_candidates:
            continue  # nessun piano di riferimento per questa traccia

        points = geometry.sample_points_along_track(
            track, SAMPLE_STEP_NM, MAX_SAMPLES_PER_TRACK
        )
        if len(points) < 2:
            continue

        # Distanza fra due campioni consecutivi (mm): serve a convertire
        # il numero di campioni consecutivi scoperti in lunghezza del gap
        track_len_mm = pcbnew.ToMM(track.GetLength())
        step_mm = track_len_mm / (len(points) - 1)
        net_name = track.GetNetname()

        # I punti vicini a pad/via della stessa net (fori di clearance) non
        # dipendono dal layer: si calcolano una volta per traccia
        near_hole = [
            _near_item_on_net(hole_index, p, net_name, HOLE_EXCLUSION_RADIUS_NM)
            for p in points
        ]

        for ref_layer, ref_zones in ref_candidates:
            flags = []
            for p, is_hole in zip(points, near_hole):
                if is_hole:
                    flags.append(False)  # foro di clearance: non e' un gap vero
                else:
                    flags.append(
                        not geometry.point_covered_by_any_zone(ref_zones, ref_layer, p)
                    )

            # Tratti continui scoperti; teniamo solo quelli sopra soglia
            bad_points = []
            max_gap = 0.0
            for start, end in _uncovered_runs(flags):
                # Ogni campione "rappresenta" un passo di traccia, quindi un
                # tratto di k campioni consecutivi vale circa k * step. Con
                # tutti i punti scoperti darebbe lunghezza + 1 passo, quindi
                # si limita il gap alla lunghezza reale della traccia.
                gap_mm = min((end - start + 1) * step_mm, track_len_mm)
                if gap_mm >= min_gap_mm:
                    bad_points.extend(points[start : end + 1])
                    max_gap = max(max_gap, gap_mm)

            if bad_points:
                ref_net = ref_zones[0].GetNetname()
                has_via = any(
                    _near_item_on_net(via_index, p, ref_net, STITCHING_SEARCH_RADIUS_NM)
                    for p in bad_points
                )
                issues.append(
                    ReturnPathIssue(
                        track=track,
                        uncovered_points=bad_points,
                        max_gap_mm=max_gap,
                        has_nearby_stitching_via=has_via,
                        ref_net=ref_net,
                        ref_layer_name=board.GetLayerName(ref_layer),
                    )
                )

    issues.sort(key=lambda issue: issue.max_gap_mm, reverse=True)
    return issues


def diagnose_track(board, track, reference_net_filter, log_path):
    """
    Diagnostica di una singola traccia, scritta su file di testo.

    Ogni passo viene scritto su disco (flush + fsync) PRIMA di eseguire la
    chiamata successiva: se una chiamata API manda in crash KiCad, l'ultima
    riga del file dice quale era. Ogni chiamata e' anche in try/except,
    cosi' le eccezioni Python normali finiscono nel log senza fermare il resto.
    """
    import os

    f = open(log_path, "w", encoding="utf-8")

    def log(msg):
        f.write(msg + "\n")
        f.flush()
        os.fsync(f.fileno())

    def attempt(label, func):
        # Scrive l'etichetta, esegue, scrive il risultato o l'eccezione
        log(f"-> {label}")
        try:
            result = func()
            log(_("   OK: {0}").format(result))
            return result
        except Exception as exc:
            log(_("   ERRORE: {0}: {1}").format(type(exc).__name__, exc))
            return None

    try:
        layer = track.GetLayer()
        log(_("Traccia net={0} layer={1}").format(track.GetNetname(), board.GetLayerName(layer)))
        log(_("Start={0} End={1} lunghezza_mm={2:.2f}").format(track.GetStart(), track.GetEnd(), pcbnew.ToMM(track.GetLength())))

        adj = _adjacent_layers(board, layer)
        log(_("Layer adiacenti: ") + ", ".join(board.GetLayerName(a) for a in adj))

        # Punti di prova: inizio, meta', fine (uso un VECTOR2I fresco)
        pts = geometry.sample_points_along_track(track, pcbnew.FromMM(5), 4)
        log(_("Punti di prova: {0}").format(len(pts)))

        # Elenco di TUTTE le zone, solo con chiamate semplici
        log(_("--- Zone sulla board ---"))
        zones = list(board.Zones())
        for n, z in enumerate(zones):
            if reference_net_filter.upper() not in z.GetNetname().upper():
                continue
            lname = attempt(_("zona {0} GetLayer").format(n), lambda: board.GetLayerName(z.GetLayer()))
            attempt(_("zona {0} GetNetname").format(n), lambda: z.GetNetname())
            attempt(_("zona {0} IsFilled").format(n), lambda: z.IsFilled())
            attempt(_("zona {0} GetZoneName").format(n), lambda: z.GetZoneName())

        # Test di copertura, un metodo alla volta, dal meno rischioso
        log(_("--- Test copertura ---"))
        for n, z in enumerate(zones):
            if not any(z.IsOnLayer(a) for a in adj):
                continue
            # Solo zone della net di riferimento (sono 240+ sulla board)
            if reference_net_filter.upper() not in z.GetNetname().upper():
                continue
            ref_l = [a for a in adj if z.IsOnLayer(a)][0]
            for k, p in enumerate(pts):
                attempt(
                    _("zona {0} HitTestFilledArea punto {1} ({2},{3})").format(n, k, p.x, p.y),
                    lambda: z.HitTestFilledArea(ref_l, p, 0),
                )
        log(_("--- Poligoni riempiti (chiamata piu' rischiosa, per ultima) ---"))
        for n, z in enumerate(zones):
            if not any(z.IsOnLayer(a) for a in adj):
                continue
            if reference_net_filter.upper() not in z.GetNetname().upper():
                continue
            ref_l = [a for a in adj if z.IsOnLayer(a)][0]
            polys = attempt(_("zona {0} GetFilledPolysList").format(n),
                            lambda: z.GetFilledPolysList(ref_l))
            if polys is not None:
                attempt(_("zona {0} OutlineCount").format(n), lambda: polys.OutlineCount())
        log(_("FINE diagnostica senza crash."))
    finally:
        f.close()


def highlight_issues(board, issues, severe_layer=pcbnew.User_1,
                     minor_layer=pcbnew.User_2):
    """
    Disegna un piccolo cerchio (PCB_SHAPE) in ogni punto dei tratti
    scoperti, su due layer grafici diversi (non elettrici), cosi' i due
    casi hanno colori diversi in Pcbnew:
    - 'severe_layer' (User.1): nessuna via di stitching vicina,
      il ritorno di corrente non ha un percorso alternativo;
    - 'minor_layer' (User.2): c'e' una via di stitching vicina.
    Il colore e' quello del layer, impostabile nel pannello Aspetto.
    """
    marker_radius_nm = pcbnew.FromMM(0.3)

    created_markers = []
    for issue in issues:
        for point in issue.uncovered_points:
            marker = pcbnew.PCB_SHAPE(board)
            marker.SetShape(pcbnew.SHAPE_T_CIRCLE)
            marker.SetFilled(True)
            # Layer (e quindi colore) secondo la gravita'
            marker.SetLayer(minor_layer if issue.has_nearby_stitching_via else severe_layer)
            marker.SetCenter(point)
            marker.SetEnd(pcbnew.VECTOR2I(point.x + marker_radius_nm, point.y))
            marker.SetWidth(0)
            board.Add(marker)
            created_markers.append(marker)

    pcbnew.Refresh()
    # Forza anche il ridisegno dell'interfaccia: senza, in alcune build i
    # nuovi oggetti non compaiono finche' non si sposta la vista
    try:
        pcbnew.UpdateUserInterface()
    except Exception:
        pass
    return created_markers


def clear_highlight(board, markers):
    """Rimuove dalla board tutti i marker creati da highlight_issues."""
    for marker in markers:
        board.Remove(marker)
    pcbnew.Refresh()
