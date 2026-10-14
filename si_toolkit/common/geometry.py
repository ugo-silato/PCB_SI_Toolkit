"""
Funzioni geometriche condivise fra i moduli di analisi.

Lo stile ricalca quello già usato in PnPImporter per la ricostruzione
della netlist dal rame fisico (collision detection con GetEffectiveShape
+ Collide), qui riadattato per capire se un punto o una traccia sono
coperti da un piano di riferimento.
"""
import pcbnew


def sample_points_along_track(track, step_nm, max_samples=30):
    """
    Restituisce una lista di punti (VECTOR2I) campionati lungo la
    traccia ogni 'step_nm' nanometri (unità interna di KiCad).

    Serve a controllare la presenza del piano di riferimento non solo
    agli estremi della traccia ma anche nei punti intermedi: uno split
    di piano può tagliare il percorso a metà, non solo in corrispondenza
    dei pad di partenza/arrivo.

    'max_samples' limita il numero di punti anche su tracce molto lunghe
    (es. una traccia verso un'antenna di 60-80 mm): senza questo limite,
    con uno step di 1 mm si arriva a decine di punti per traccia, e ogni
    punto costa una chiamata a HitTestFilledArea (vedi point_covered_by_zone)
    più, in return_path.py, un controllo via di stitching. Su una board
    con molte tracce lunghe il costo totale cresce rapidamente e può
    bloccare l'interfaccia per decine di secondi: meglio un campionamento
    più rado ma con un tetto fisso, che un'analisi esatta ma potenzialmente
    bloccante.
    """
    start = track.GetStart()
    end = track.GetEnd()
    length = track.GetLength()  # lunghezza in nm (unità interna KiCad)

    if length == 0:
        return [start]

    n_steps = min(max_samples, max(1, int(length // step_nm)))
    points = []
    for i in range(n_steps + 1):
        t = i / n_steps
        x = int(start.x + (end.x - start.x) * t)
        y = int(start.y + (end.y - start.y) * t)
        points.append(pcbnew.VECTOR2I(x, y))
    return points


def find_reference_zone(board, layer_id, net_name_filter=None):
    """
    Cerca la prima ZONE riempita sul layer 'layer_id' che corrisponde a
    un piano di riferimento (tipicamente GND o un'alimentazione),
    filtrando per sottostringa nel nome net se specificato.

    Ritorna l'oggetto ZONE oppure None se non trovata.

    NOTA: questa è una scelta semplificata pensata per il caso comune
    (un solo piano di riferimento per layer). Se la board ha più piani
    separati sullo stesso layer (es. GND digitale e GND analogico
    affiancati) va estesa per restituire una lista e farsi dire
    dall'utente quale usare come riferimento per quel gruppo di tracce.
    """
    for zone in board.Zones():
        # IsOnLayer (e non GetLayer) perche' le zone multilayer hanno
        # GetLayer() == undefined ma appartengono a piu' layer
        if not zone.IsOnLayer(layer_id):
            continue
        if not zone.IsFilled():
            continue
        net_name = zone.GetNetname()
        if net_name_filter is None:
            return zone
        if net_name_filter.upper() in net_name.upper():
            return zone
    return None


def find_reference_zones(board, layer_id, net_name_filter=None):
    """
    Come find_reference_zone, ma ritorna TUTTE le zone riempite del layer
    che corrispondono al filtro (lista, anche vuota).

    Serve perché sul layer di riferimento possono esistere più pour
    separati con la stessa net (es. un'isola di massa vicino a un
    connettore): prendere solo il primo faceva risultare "scoperti" i
    punti coperti dagli altri pour.
    """
    zones = []
    for zone in board.Zones():
        # IsOnLayer: vedi nota in find_reference_zone (zone multilayer)
        if not zone.IsOnLayer(layer_id):
            continue
        if not zone.IsFilled():
            continue
        if net_name_filter is None or net_name_filter.upper() in zone.GetNetname().upper():
            zones.append(zone)
    return zones


def point_covered_by_any_zone(zones, layer_id, point, accuracy_nm=0):
    """Vero se il punto è coperto dal riempimento di almeno una delle zone."""
    for zone in zones:
        if zone.HitTestFilledArea(layer_id, point, accuracy_nm):
            return True
    return False


def point_covered_by_zone(zone, layer_id, point, accuracy_nm=0):
    """
    Vero se 'point' è coperto dal riempimento della zona sul layer
    indicato. Usa HitTestFilledArea, che lavora sul poligono di rame
    effettivamente versato (già scontato di clearance e thermal relief),
    non sull'outline disegnato a mano dall'utente in fase di progetto.
    """
    if zone is None:
        return False
    return zone.HitTestFilledArea(layer_id, point, accuracy_nm)


def lateral_gaps(zones, layer_id, track, step_nm, max_nm, n_samples, margin_nm, pads=()):
    """
    Misura, da alcuni punti lungo una traccia rettilinea, la distanza fra il
    bordo della traccia e il rame riempito delle 'zones' sullo stesso layer,
    separatamente sui due lati. Si avanza a passi di 'step_nm' fino a
    'max_nm' dal bordo; se non si trova rame il lato vale None.

    Ritorna una lista di (gap_lato_1, gap_lato_2) in nm, uno per punto di
    prova. I punti vicini alle estremita' (entro 'margin_nm') si saltano:
    li' ci sono pad e curve, e la distanza non e' rappresentativa.

    'pads': pad di massa sullo stesso layer; anche il loro rame conta come
    massa laterale (es. il pad GND di un condensatore accanto alla linea).
    """
    start, end = track.GetStart(), track.GetEnd()
    dx, dy = end.x - start.x, end.y - start.y
    length = (dx * dx + dy * dy) ** 0.5
    if length <= 0:
        return []
    ux, uy = dx / length, dy / length
    nx, ny = -uy, ux  # normale alla traccia
    half_w = track.GetWidth() / 2.0

    # Posizioni di prova lungo la traccia (distanza dall'inizio)
    if length > 2 * margin_nm and n_samples > 1:
        span = length - 2 * margin_nm
        positions = [margin_nm + span * (i + 0.5) / n_samples for i in range(n_samples)]
    else:
        positions = [length / 2.0]

    result = []
    for pos in positions:
        cx, cy = start.x + ux * pos, start.y + uy * pos
        sides = []
        for sign in (1, -1):
            gap = None
            d = half_w + step_nm
            while d <= half_w + max_nm:
                p = pcbnew.VECTOR2I(int(cx + sign * nx * d), int(cy + sign * ny * d))
                if point_covered_by_any_zone(zones, layer_id, p) or any(
                    pad.HitTest(p) for pad in pads
                ):
                    # Trovato rame fra (d - step) e d: si restringe l'intervallo
                    # con una bisezione, cosi' il gap non e' arrotondato al
                    # passo di ricerca (precisione di circa 1 um)
                    lo, hi = d - step_nm, d
                    for _ in range(6):
                        mid = (lo + hi) / 2.0
                        pm = pcbnew.VECTOR2I(
                            int(cx + sign * nx * mid), int(cy + sign * ny * mid)
                        )
                        if point_covered_by_any_zone(zones, layer_id, pm):
                            hi = mid
                        else:
                            lo = mid
                    gap = hi - half_w
                    break
                d += step_nm
            sides.append(gap)
        result.append(tuple(sides))
    return result


def point_segment_distance(px, py, ax, ay, bx, by):
    """Distanza (stesse unita' degli argomenti) fra il punto P e il segmento AB."""
    dx, dy = bx - ax, by - ay
    len2 = dx * dx + dy * dy
    if len2 == 0:
        return ((px - ax) ** 2 + (py - ay) ** 2) ** 0.5
    u = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / len2))
    cx, cy = ax + u * dx, ay + u * dy
    return ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5


def pair_spacing(tracks_p, tracks_n, step_nm, max_samples, coupling_limit_nm):
    """
    Distanza fra i bordi di due gruppi di tracce (le due net di una coppia
    differenziale) misurata da punti lungo le tracce del primo gruppo.

    Per ogni punto prende la distanza dal segmento piu' vicino del secondo
    gruppo meno meta' delle due larghezze (spazio di rame libero fra i bordi).
    I punti con spazio oltre 'coupling_limit_nm' sono considerati non
    accoppiati (le tracce li' si separano).

    Ritorna (spaziatura mediana in nm o None, frazione accoppiata, n. punti).
    """
    segs = [(t.GetStart(), t.GetEnd(), t.GetWidth()) for t in tracks_n
            if t.Type() == pcbnew.PCB_TRACE_T]
    if not segs:
        return None, 0.0, 0
    gaps = []
    for t in tracks_p:
        if t.Type() != pcbnew.PCB_TRACE_T:
            continue
        for p in sample_points_along_track(t, step_nm, 10):
            best = min(
                point_segment_distance(p.x, p.y, a.x, a.y, b.x, b.y) - w / 2.0
                for a, b, w in segs
            ) - t.GetWidth() / 2.0
            gaps.append(max(best, 0.0))
    if not gaps:
        return None, 0.0, 0
    if len(gaps) > max_samples:  # sottocampiona in modo uniforme
        stride = len(gaps) / max_samples
        gaps = [gaps[int(i * stride)] for i in range(max_samples)]
    coupled = sorted(g for g in gaps if g <= coupling_limit_nm)
    fraction = len(coupled) / len(gaps)
    median = coupled[len(coupled) // 2] if coupled else None
    return median, fraction, len(gaps)
