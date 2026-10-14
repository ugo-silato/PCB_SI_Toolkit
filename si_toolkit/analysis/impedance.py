"""
Modulo "Calcolatore di impedenza".

Calcola l'impedenza caratteristica Z0 delle tracce con formule chiuse:
- microstrip (traccia su layer esterno, piano di riferimento solo da un
  lato): formule di Hammerstad-Jensen con correzione per lo spessore;
- stripline (traccia su layer interno fra due piani): formula IPC-2141.

Sono formule di progetto, accurate al 5-10% circa: vanno bene per capire
se una traccia e' lontana dai 50 ohm voluti, NON sostituiscono un field
solver (per quello servira' il modulo openEMS). Non considerano il solder
mask, ne' la rugosita' del rame, ne' la perdita nel dielettrico.

Le funzioni di calcolo non dipendono da pcbnew (si provano fuori da KiCad);
solo read_stackup() legge la board.
"""
import math

import pcbnew

from ..common import geometry
from . import field2d
from .return_path import (
    HOLE_EXCLUSION_RADIUS_NM,
    _build_indexes,
    _copper_layer_stack,
    _near_item_on_net,
)
from ..common.i18n import _


def microstrip_z0(w, h, er, t):
    """
    Z0 (ohm) di una microstrip. w = larghezza, h = distanza dal piano,
    er = costante dielettrica, t = spessore rame. Unita' qualsiasi, purche'
    uguali fra loro (es. metri).
    """
    # Larghezza efficace: lo spessore del rame "allarga" elettricamente la traccia
    if t > 0:
        u0 = w / h
        if u0 <= 1.0 / (2 * math.pi):
            dw = (t / math.pi) * (1 + math.log(4 * math.pi * w / t))
        else:
            dw = (t / math.pi) * (1 + math.log(2 * h / t))
        w = w + dw
    u = w / h
    # Costante dielettrica efficace (parte nell'aria e parte nel dielettrico)
    eeff = (er + 1) / 2 + (er - 1) / 2 / math.sqrt(1 + 12 / u)
    if u < 1:
        eeff += (er - 1) / 2 * 0.04 * (1 - u) ** 2
    if u <= 1:
        return 60 / math.sqrt(eeff) * math.log(8 / u + u / 4)
    return 120 * math.pi / (math.sqrt(eeff) * (u + 1.393 + 0.667 * math.log(u + 1.444)))


def stripline_z0(w, b, er, t):
    """
    Z0 (ohm) di una stripline centrata fra due piani (IPC-2141):
    b = distanza totale fra i due piani, comprensiva dello spessore del rame.
    """
    return 60 / math.sqrt(er) * math.log(1.9 * b / (0.8 * w + t))


def _ellip_k(k):
    """Integrale ellittico completo K(k) con la media aritmetico-geometrica."""
    a, b = 1.0, math.sqrt(1.0 - k * k)
    for _step in range(40):
        a, b = (a + b) / 2, math.sqrt(a * b)
    return math.pi / (2 * a)


def cpwg_z0(w, gap, h, er, t=0.0):
    """
    Z0 (ohm) di una microstrip COPLANARE con piano di massa sotto (CPWG):
    traccia di larghezza w con massa sullo stesso layer a distanza 'gap'
    per lato e piano di riferimento a distanza h. Formula con integrali
    ellittici (conformal mapping).

    Spessore del rame 't' (metodo dei calcolatori Qucs/KiCad): la traccia
    "spessa" si allarga di d e il gap si stringe di d SOLO nel termine in
    aria (fra traccia e massa laterale), mentre la costante dielettrica
    efficace cala leggermente. Verificato con la Calcolatrice PCB di KiCad
    (w 0,7 / gap 0,2 / h 1,51 / Er 4,5 / t 0,035: KiCad 58,2 ohm, qui 56,7).
    La versione precedente applicava d a tutto il calcolo e dava 49,8 ohm.
    """
    def parts(w_, g_):
        # q1: termine fra traccia e massa laterale; q3: termine verso il piano
        a = w_ / 2.0
        b = a + g_
        k = a / b
        k3 = math.tanh(math.pi * a / (2 * h)) / math.tanh(math.pi * b / (2 * h))
        q1 = _ellip_k(k) / _ellip_k(math.sqrt(1 - k * k))
        q3 = _ellip_k(k3) / _ellip_k(math.sqrt(1 - k3 * k3))
        return q1, q3

    q1, q3 = parts(w, gap)
    eeff = (1 + er * q3 / q1) / (1 + q3 / q1)
    if t > 0:
        d = (1.25 * t / math.pi) * (1 + math.log(4 * math.pi * w / t))
        q1_t, _ = parts(w + d, max(gap - d, gap * 0.1))
        eeff = eeff - (0.7 * (eeff - 1) * t / gap) / (q1 + 0.7 * t / gap)
        q1 = q1_t
    return 60 * math.pi / math.sqrt(eeff) / (q1 + q3)


def width_for_z0(z_func, target, w_min, w_max):
    """
    Larghezza che da' l'impedenza 'target', per bisezione: z_func(w) cala
    all'aumentare di w. Ritorna None se il target e' fuori da [w_min, w_max].
    """
    z_hi, z_lo = z_func(w_min), z_func(w_max)  # z_hi: traccia stretta
    if not (z_lo <= target <= z_hi):
        return None
    lo, hi = w_min, w_max
    for _step in range(60):
        mid = (lo + hi) / 2
        if z_func(mid) > target:
            lo = mid  # troppo impedente: serve piu' larga
        else:
            hi = mid
    return (lo + hi) / 2


def _item_kind(it):
    """
    'cu' per un layer di rame, 'diel' per un dielettrico, None per il resto
    (solder mask, serigrafia...). Usa le costanti di pcbnew se esistono e,
    in mancanza, il nome del tipo (GetTypeName), perche' i nomi delle
    costanti cambiano fra versioni di KiCad.
    """
    cu = getattr(pcbnew, "BS_ITEM_TYPE_COPPER", None)
    di = getattr(pcbnew, "BS_ITEM_TYPE_DIELECTRIC", None)
    sm = getattr(pcbnew, "BS_ITEM_TYPE_SOLDERMASK", None)
    if cu is not None and di is not None:
        kind = it.GetType()
        if kind == cu:
            return "cu"
        if kind == di:
            return "diel"
        if sm is not None and kind == sm:
            return "mask"
        return None
    name = str(it.GetTypeName()).lower()
    if "copper" in name:
        return "cu"
    if "dielectric" in name:
        return "diel"
    if "mask" in name and "solder" in name:
        return "mask"
    return None


def _items_from_api(board):
    """Elementi dello stackup letti con l'API di pcbnew. Ritorna (items, errori)."""
    errors = []
    try:
        raw = list(board.GetDesignSettings().GetStackupDescriptor().GetList())
    except Exception as exc:
        return [], [_("API stackup: {0}").format(exc)]

    items = []  # ("cu", layer, spessore m) / ("diel", None, spessore m, er)
    for it in raw:
        try:
            kind = _item_kind(it)
            if kind == "cu":
                items.append(("cu", it.GetBrdLayerId(), it.GetThickness() * 1e-9))
            elif kind == "diel":
                # Un dielettrico puo' avere piu' sotto-strati: spessori
                # sommati, er pesata sullo spessore
                th_tot, er_w = 0.0, 0.0
                for sub in range(max(1, it.GetSublayersCount())):
                    th = it.GetThickness(sub) * 1e-9
                    th_tot += th
                    er_w += th * it.GetEpsilonR(sub)
                if th_tot > 0:
                    items.append(("diel", None, th_tot, er_w / th_tot))
            elif kind == "mask":
                items.append(("mask", None, it.GetThickness() * 1e-9, it.GetEpsilonR()))
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
    return items, errors


def _parse_sexpr(text):
    """Parser minimo di s-expression KiCad: liste annidate di stringhe."""
    import re

    tokens = re.findall(r'\(|\)|"(?:[^"\\]|\\.)*"|[^\s()]+', text)
    stack, current = [], []
    for tok in tokens:
        if tok == "(":
            stack.append(current)
            current = []
        elif tok == ")":
            done = current
            current = stack.pop() if stack else []
            current.append(done)
        else:
            current.append(tok.strip('"'))
    return current


def _items_from_file(board):
    """
    Elementi dello stackup letti dal file .kicad_pcb salvato (sezione
    "stackup"). Serve quando l'API Python non espone gli strati. Legge il
    file su disco: le modifiche non ancora salvate non si vedono.
    Ritorna (items, errori).
    """
    import os
    import re

    path = board.GetFileName()
    if not path or not os.path.exists(path):
        return [], [_("file della scheda non trovato (salvala prima)")]
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except Exception as exc:
        return [], [_("lettura file: {0}").format(exc)]
    start = text.find("(stackup")
    if start < 0:
        return [], [_("nel file .kicad_pcb non c'e' la sezione stackup (aprila in Setup scheda > Stackup fisico, premi OK e salva)")]
    # Blocco "(stackup ...)" completo, contando le parentesi fuori dalle stringhe
    depth, i, in_str = 0, start, False
    while i < len(text):
        ch = text[i]
        if in_str:
            if ch == "\\":
                i += 1
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                break
        i += 1
    tree = _parse_sexpr(text[start : i + 1])
    node = tree[0] if tree and isinstance(tree[0], list) else []

    items, errors = [], []
    for entry in node:
        if not (isinstance(entry, list) and entry and entry[0] == "layer"):
            continue
        name = entry[1] if len(entry) > 1 else ""
        fields = [c for c in entry if isinstance(c, list) and c]
        ltype = next((c[1] for c in fields if c[0] == "type" and len(c) > 1), "").lower()
        try:
            if ltype == "copper":
                th = next(float(c[1]) for c in fields if c[0] == "thickness") * 1e-3
                items.append(("cu", board.GetLayerID(name), th))
            elif "solder mask" in ltype:
                th = next((float(c[1]) for c in fields if c[0] == "thickness"), 0.0) * 1e-3
                er = next((float(c[1]) for c in fields if c[0] == "epsilon_r"), 3.3)
                if th > 0:
                    items.append(("mask", None, th, er))
            elif ltype in ("core", "prepreg", "dielectric"):
                # Coppie (spessore, er); le sotto-strati ripetono i campi
                pairs, th, er = [], None, None
                for c in fields:
                    if c[0] == "thickness":
                        if th is not None:
                            pairs.append((th, er if er else 4.5))
                            er = None
                        th = float(c[1]) * 1e-3
                    elif c[0] == "epsilon_r":
                        er = float(c[1])
                if th is not None:
                    pairs.append((th, er if er else 4.5))
                th_tot = sum(p[0] for p in pairs)
                if th_tot > 0:
                    items.append(("diel", None, th_tot,
                                  sum(p[0] * p[1] for p in pairs) / th_tot))
        except Exception as exc:
            errors.append(_("strato {0}: {1}: {2}").format(name, type(exc).__name__, exc))
    return items, errors


def _read_real_stackup(board):
    """
    Legge lo stackup fisico della board (Setup board > Stackup): prima con
    l'API di pcbnew, e se questa non espone gli strati dal file .kicad_pcb.

    Ritorna (dizionario, errori) dove il dizionario e': layer_di_rame -> {
        "t": spessore rame (m),
        "above": (spessore dielettrico (m), er) verso il layer sopra, o None,
        "below": (spessore (m), er) verso il layer sotto, o None }
    ed e' vuoto se lo stackup non e' leggibile.
    """
    items, errors = _items_from_api(board)
    source = "API"
    if not items:
        file_items, file_errors = _items_from_file(board)
        errors = errors + file_errors
        if file_items:
            items, source = file_items, "file"
    if not items:
        errors.append(_("{0} elementi riconosciuti").format(len(items)))
        return {}, errors

    def gather(start, step):
        """Somma i dielettrici dal rame in 'start' fino al rame successivo."""
        th_tot, er_w, i = 0.0, 0.0, start + step
        while 0 <= i < len(items) and items[i][0] != "cu":
            if items[i][0] == "diel":
                th_tot += items[i][2]
                er_w += items[i][2] * items[i][3]
            i += step
        reached_copper = 0 <= i < len(items)
        if th_tot <= 0 or not reached_copper:
            return None
        return (th_tot, er_w / th_tot)

    result = {}
    for idx, it in enumerate(items):
        if it[0] == "cu" and it[2] > 0:
            # Solder mask direttamente sopra/sotto questo rame (layer esterni)
            mask = None
            for j in (idx - 1, idx + 1):
                if 0 <= j < len(items) and items[j][0] == "mask":
                    mask = (items[j][2], items[j][3])
            result[it[1]] = {
                "t": it[2],
                "above": gather(idx, -1),
                "below": gather(idx, +1),
                "mask": mask,
            }
    # Se la lettura e' riuscita via file, l'errore dell'API non interessa piu'
    return result, ([] if result else errors)


def _synthetic_stackup(board, er):
    """
    Stackup stimato quando la scheda non ne ha uno definito: rame da 35 um
    su ogni layer e dielettrico di spessore uguale fra layer adiacenti,
    ricavato dallo spessore totale della scheda. E' solo una stima: su
    schede a 4+ layer prepreg e core hanno spessori diversi.
    """
    stack = list(board.GetEnabledLayers().CuStack())
    n = len(stack)
    if n < 2:
        return {}
    total_m = board.GetDesignSettings().GetBoardThickness() * 1e-9
    t = 35e-6
    gap = (total_m - n * t) / (n - 1)
    if gap <= 0:
        gap = total_m / (n - 1)
    result = {}
    for i, layer in enumerate(stack):
        result[layer] = {
            "t": t,
            "above": (gap, er) if i > 0 else None,
            "below": (gap, er) if i < n - 1 else None,
            "mask": None,  # stackup stimato: si usa il solder mask di default
        }
    return result


def gap_for_z0(w, h, er, t, target, g_min=0.03e-3, g_max=3e-3):
    """
    Gap (m) dalla massa coplanare che da' Z0 = target a larghezza w fissa,
    per bisezione: l'impedenza cresce allargando il gap. None se il target
    non e' raggiungibile nell'intervallo [g_min, g_max].
    """
    z_lo, z_hi = cpwg_z0(w, g_min, h, er, t), cpwg_z0(w, g_max, h, er, t)
    if not (z_lo <= target <= z_hi):
        return None
    lo, hi = g_min, g_max
    for _step in range(60):
        mid = (lo + hi) / 2
        if cpwg_z0(w, mid, h, er, t) < target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def read_stackup(board, er_override=None, h_override_m=None):
    """
    Stackup da usare per il calcolo, con una nota che dice da dove viene.

    Prima prova a leggere quello definito nella scheda; se non c'e' (file
    convertiti da altri programmi spesso non lo hanno) usa una stima dallo
    spessore totale con er = 4.5. er_override e h_override_m (metri), se
    dati, sostituiscono costante dielettrica e spessore del dielettrico in
    ogni caso.

    Ritorna (stackup, nota).
    """
    try:
        stackup, errors = _read_real_stackup(board)
    except Exception as exc:
        stackup, errors = {}, [str(exc)]
    # Motivi dei problemi di lettura (primi due), mostrati nella nota
    err = f" ({'; '.join(errors[:2])})" if errors and not stackup else ""

    # Uno stackup e' utilizzabile se almeno un layer ha un dielettrico
    usable = any(v["above"] or v["below"] for v in stackup.values())
    if usable:
        note = _("stackup letto dalla scheda")
    else:
        stackup = _synthetic_stackup(board, er_override or 4.5)
        note = (_("stackup NON definito nella scheda") + err
                + _(": uso una stima dallo spessore totale"))

    if er_override or h_override_m:
        for v in stackup.values():
            for side in ("above", "below"):
                if v[side]:
                    h, er = v[side]
                    v[side] = (h_override_m or h, er_override or er)
        note += _(" (valori impostati a mano)")
    return stackup, note


# Solder mask di default (valori predefiniti di KiCad) se lo stackup non lo descrive
DEFAULT_MASK = (10e-6, 3.3)


def layer_geometry(stackup, layer, outer_layers, solder_mask=True):
    """
    Geometria del layer per il calcolo: dizionario con
      kind: "micro" (layer esterno) o "strip" (interno),
      h: dielettrico fra traccia e piano sotto (m),
      h_top: dielettrico verso il piano sopra (solo stripline, m),
      er: costante dielettrica (media pesata per la stripline), t: rame (m).
    None se lo stackup non basta.
    """
    info = stackup.get(layer)
    if info is None:
        return None
    t = info["t"]
    if layer in outer_layers:
        diel = info["below"] if info["below"] else info["above"]
        if diel is None:
            return None
        mask = (info.get("mask") or DEFAULT_MASK) if solder_mask else (0.0, 1.0)
        return {"kind": "micro", "h": diel[0], "h_top": None, "er": diel[1], "t": t,
                "sm_t": mask[0], "sm_er": mask[1]}
    if info["above"] is None or info["below"] is None:
        return None
    (h1, er1), (h2, er2) = info["above"], info["below"]
    return {"kind": "strip", "h": h2, "h_top": h1,
            "er": (er1 * h1 + er2 * h2) / (h1 + h2), "t": t, "sm_t": 0.0, "sm_er": 1.0}


def _formula_z0(g, w, gap):
    """Z0 con le formule chiuse (veloci): usate come punto di partenza."""
    if g["kind"] == "micro":
        if gap:
            return cpwg_z0(w, gap, g["h"], g["er"], g["t"])
        return microstrip_z0(w, g["h"], g["er"], g["t"])
    return stripline_z0(w, g["h"] + g["h_top"] + g["t"], g["er"], g["t"])


def field_z0(g, w, gap=None):
    """Z0 col risolutore di campo 2D (preciso)."""
    return field2d.line_z0(w, g["h"], g["er"], g["t"],
                           gap=gap if g["kind"] == "micro" else None,
                           h_top=g["h_top"], sm_t=g["sm_t"], sm_er=g["sm_er"])[0]


def _target_with_field(g, target, var, fixed_w, fixed_gap, x0):
    """
    Trova la larghezza (var="w") o il gap (var="gap") che danno Z0 = target
    col risolutore di campo. Per non fare decine di calcoli di campo si usa
    la formula chiusa "corretta": a ogni passo si misura il rapporto
    campo/formula nel punto attuale e si risolve la formula con il target
    diviso per quel rapporto (bastano 2 passi, errore sotto l'1%).
    """
    x = x0
    for _step in range(2):  # 2 passi: il rapporto campo/formula varia poco
        w = x if var == "w" else fixed_w
        gap = x if var == "gap" else fixed_gap
        ratio = field_z0(g, w, gap) / _formula_z0(g, w, gap)
        if var == "w":
            x_new = width_for_z0(lambda ww: _formula_z0(g, ww, fixed_gap),
                                 target / ratio, g["h"] * 0.02, g["h"] * 8)
        else:
            x_new = gap_for_z0(fixed_w, g["h"], g["er"], g["t"], target / ratio)
        if x_new is None:
            return None
        if abs(x_new - x) < x * 0.002:
            return x_new
        x = x_new
    return x


def analyze_layer(stackup, layer, width_m, outer_layers, target_ohm, gap_m=None,
                  solder_mask=True):
    """
    Impedenza di una traccia di larghezza 'width_m' sul layer dato, col
    RISOLUTORE DI CAMPO 2D (field2d); le formule chiuse servono solo come
    punto di partenza nella ricerca della larghezza/gap per il target.
    gap_m: distanza dalla massa sullo stesso layer (solo layer esterni).
    Ritorna (tipo, z0, larghezza_per_target_m, gap_per_target_m, nota).
    """
    g = layer_geometry(stackup, layer, outer_layers, solder_mask)
    if g is None:
        return ("n/d", None, None, None, _("stackup insufficiente"))
    if g["kind"] == "micro":
        kind = _("Microstrip coplanare") if gap_m else "Microstrip"
    else:
        kind = "Stripline"
        gap_m = None
    try:
        z0 = field_z0(g, width_m, gap_m)
        w_target = _target_with_field(g, target_ohm, "w", width_m, gap_m, width_m)
        g_target = (_target_with_field(g, target_ohm, "gap", width_m, gap_m, gap_m)
                    if gap_m else None)
        note = _("campo 2D")
    except Exception as exc:
        # Ripiego sulle formule se il calcolo di campo fallisce
        z0 = _formula_z0(g, width_m, gap_m)
        w_target = width_for_z0(lambda ww: _formula_z0(g, ww, gap_m),
                                target_ohm, g["h"] * 0.02, g["h"] * 8)
        g_target = (gap_for_z0(width_m, g["h"], g["er"], g["t"], target_ohm)
                    if gap_m else None)
        note = _("formula (campo 2D fallito: {0})").format(exc)
    return (kind, z0, w_target, g_target, note)

def diagnose_stackup(board, log_path):
    """
    Scrive su file cosa vede il plugin nello stackup: nomi disponibili,
    ogni elemento con tipo, spessore e layer. Ogni passo e' scritto su
    disco prima di eseguire il successivo, e ogni chiamata e' protetta,
    cosi' gli errori finiscono nel file.
    """
    import os

    f = open(log_path, "w", encoding="utf-8")

    def log(msg):
        f.write(msg + "\n")
        f.flush()
        os.fsync(f.fileno())

    def attempt(label, func):
        log(f"-> {label}")
        try:
            result = func()
            log(_("   OK: {0}").format(result))
            return result
        except Exception as exc:
            log(_("   ERRORE: {0}: {1}").format(type(exc).__name__, exc))
            return None

    try:
        log(_("Costanti BS_ITEM in pcbnew: ")
            + ", ".join(n for n in dir(pcbnew) if n.startswith("BS_ITEM")))
        stackup = attempt("GetStackupDescriptor",
                          lambda: board.GetDesignSettings().GetStackupDescriptor())
        if stackup is None:
            return
        items = attempt("GetList", lambda: list(stackup.GetList()))
        for n, it in enumerate(items or []):
            attempt(_("elemento {0} GetTypeName").format(n), lambda: it.GetTypeName())
            attempt(_("elemento {0} GetType").format(n), lambda: it.GetType())
            attempt(_("elemento {0} GetThickness").format(n), lambda: it.GetThickness())
            attempt(_("elemento {0} GetBrdLayerId").format(n), lambda: it.GetBrdLayerId())
            attempt(_("elemento {0} GetEpsilonR").format(n), lambda: it.GetEpsilonR())
            attempt(_("elemento {0} GetSublayersCount").format(n), lambda: it.GetSublayersCount())
        attempt("read_stackup", lambda: read_stackup(board))
        log(_("FINE diagnostica."))
    finally:
        f.close()


def detect_coplanar(board, tracks, layer, ground_filter="GND", zone_cache=None):
    """
    Cerca la massa vicino a un gruppo di tracce (stessa net/layer/larghezza).

    - Massa laterale (coplanare): da alcuni punti lungo le tracce misura la
      distanza dal rame di massa sullo stesso layer, sui due lati. Se la
      massa c'e' dai due lati in almeno meta' delle misure, ritorna la
      mediana come gap; altrimenti None (nessuna massa laterale).
    - Piano sotto: frazione dei punti lungo le tracce coperti dal rame di
      massa sul layer di riferimento (quello adiacente, verso l'interno).

    Ritorna (gap_m o None, frazione_piano_sotto o None).
    'zone_cache' (dizionario) evita di rifare la ricerca delle zone.
    """
    if zone_cache is None:
        zone_cache = {}

    def zones_on(layer_id):
        if layer_id not in zone_cache:
            zone_cache[layer_id] = geometry.find_reference_zones(
                board, layer_id, ground_filter
            )
        return zone_cache[layer_id]

    def pads_on(layer_id):
        # Pad della net di massa sul layer (anche il loro rame e' massa
        # laterale), salvati nella stessa cache delle zone
        key = ("pads", layer_id)
        if key not in zone_cache:
            zone_cache[key] = [
                p for p in board.GetPads()
                if ground_filter.upper() in p.GetNetname().upper() and p.IsOnLayer(layer_id)
            ]
        return zone_cache[key]

    step = pcbnew.FromMM(0.05)
    max_dist = pcbnew.FromMM(1.0)
    margin = pcbnew.FromMM(1.0)

    # Campioni: al massimo 8 punti per gruppo, ripartiti fra le tracce
    straight = [t for t in tracks if t.Type() == pcbnew.PCB_TRACE_T]
    pick = sorted(straight, key=lambda t: -t.GetLength())[:4]
    gaps = []
    for t in pick:
        gaps += geometry.lateral_gaps(
            zones_on(layer), layer, t, step, max_dist, 2, margin, pads_on(layer)
        )

    found = [g for pair in gaps for g in pair if g is not None]
    total = sum(len(pair) for pair in gaps)
    lateral = None
    if total and len(found) >= total / 2:
        found.sort()
        lateral = found[len(found) // 2] * 1e-9  # mediana, in metri

    # Piano di riferimento sotto: layer adiacente verso l'interno
    stack = _copper_layer_stack(board)
    below = None
    if layer in stack and len(stack) > 1:
        i = stack.index(layer)
        ref = stack[i + 1] if i == 0 else stack[i - 1]
        ref_zones = zones_on(ref)
        # Indice di pad e via, calcolato una volta sola (chiave "holes")
        if "holes" not in zone_cache:
            zone_cache["holes"] = _build_indexes(board)[1]
        holes = zone_cache["holes"]
        pts, all_pts = [], []
        for t in pick:
            net = t.GetNetname()
            for p in geometry.sample_points_along_track(t, pcbnew.FromMM(0.5), 20):
                all_pts.append(p)
                # I punti vicini a pad/via della stessa net (estremita' della
                # traccia, keep-out voluti sotto un pin) non contano come
                # interruzione del piano: come nel Return Path
                if not _near_item_on_net(holes, p, net, HOLE_EXCLUSION_RADIUS_NM):
                    pts.append(p)
        # Traccia corta (es. 1-2 mm fra due pad): tutti i punti cadono vicino
        # ai pad e verrebbero scartati, lasciando "-". In quel caso si usano
        # comunque tutti i punti.
        if not pts:
            pts = all_pts
        if pts:
            covered = sum(
                1 for p in pts if geometry.point_covered_by_any_zone(ref_zones, ref, p)
            )
            below = covered / len(pts)
    return lateral, below


def detect_pairs(net_names):
    """
    Riconosce le coppie differenziali dai nomi delle net: suffissi
    P/N, DP/DM, + / - (con eventuale separatore _ - .). Per esempio
    "USB_DP"/"USB_DM", "/ETH/TX_P"/"/ETH/TX_N", "D+"/"D-".

    Ritorna una lista di (nome_coppia, net_positiva, net_negativa).
    """
    import re

    pattern = re.compile(r"^(.*?)[_\-.]?(P|N|DP|DM|\+|-)$", re.IGNORECASE)
    complement = {"P": "N", "DP": "DM", "+": "-"}
    by_key = {}
    for name in net_names:
        m = pattern.match(name)
        if not m or not m.group(1):
            continue
        base, suffix = m.group(1), m.group(2).upper()
        by_key[(base, suffix)] = name
    pairs = []
    for (base, suffix), name in by_key.items():
        if suffix in complement and (base, complement[suffix]) in by_key:
            pairs.append((base, name, by_key[(base, complement[suffix])]))
    pairs.sort()
    return pairs


def layer_model(stackup, layer, outer_layers):
    """
    Modello fisico del layer: ("micro", h, er, t) per un layer esterno,
    ("strip", b, er, t) per uno interno, oppure None se lo stackup non basta.
    """
    info = stackup.get(layer)
    if info is None:
        return None
    t = info["t"]
    if layer in outer_layers:
        diel = info["below"] if info["below"] else info["above"]
        return ("micro", diel[0], diel[1], t) if diel else None
    if info["above"] is None or info["below"] is None:
        return None
    (h1, er1), (h2, er2) = info["above"], info["below"]
    return ("strip", h1 + h2 + t, (er1 * h1 + er2 * h2) / (h1 + h2), t)


def single_z0(model, w):
    """Z0 singolo (ohm) di una traccia di larghezza w secondo il modello del layer."""
    kind, h, er, t = model
    return microstrip_z0(w, h, er, t) if kind == "micro" else stripline_z0(w, h, er, t)


def diff_z0(model, w, s):
    """
    Impedenza differenziale (ohm) di una coppia accoppiata sul bordo, con
    larghezza w e spazio fra i bordi s (formule IPC-2141):
      microstrip: Zdiff = 2*Z0*(1 - 0.48*exp(-0.96*s/h))
      stripline:  Zdiff = 2*Z0*(1 - 0.347*exp(-2.9*s/b))
    Non considera massa coplanare accanto alla coppia.
    """
    kind, h, er, t = model
    z0 = single_z0(model, w)
    if kind == "micro":
        return 2 * z0 * (1 - 0.48 * math.exp(-0.96 * s / h))
    return 2 * z0 * (1 - 0.347 * math.exp(-2.9 * s / h))


def width_for_diff(model, s, target, h_ref):
    """Larghezza (m) che da' Zdiff = target a spazio s fissato, o None."""
    return width_for_z0(lambda w: diff_z0(model, w, s), target, h_ref * 0.02, h_ref * 8)


# --------------------------------------------------------------------------
# Coppie differenziali col risolutore di campo 2D
# --------------------------------------------------------------------------
def pair_field(g, w, s, gap=None):
    """
    Coppia differenziale col risolutore di campo (field2d.pair_z0) sulla
    geometria 'g' di layer_geometry. gap: massa laterale sul lato esterno
    (solo layer esterni). Ritorna (zdiff, zcomune, z_odd, z_even).
    """
    return field2d.pair_z0(w, s, g["h"], g["er"], g["t"],
                           gap=gap if g["kind"] == "micro" else None,
                           h_top=g["h_top"], sm_t=g["sm_t"], sm_er=g["sm_er"])


def _model_from_geometry(g):
    """Modello (tipo, h, er, t) per le formule chiuse, dalla geometria del layer."""
    if g["kind"] == "micro":
        return ("micro", g["h"], g["er"], g["t"])
    return ("strip", g["h"] + g["h_top"] + g["t"], g["er"], g["t"])


def width_for_diff_field(g, s, target, gap=None):
    """
    Larghezza (m) che da' Zdiff = target col risolutore di campo, a spazio s
    fissato. Come per le tracce singole: la formula IPC-2141 si "corregge"
    col rapporto campo/formula misurato nel punto attuale (2 passi).
    """
    model = _model_from_geometry(g)
    w = width_for_diff(model, s, target, g["h"])
    for _step in range(2):
        if w is None:
            return None
        ratio = pair_field(g, w, s, gap)[0] / diff_z0(model, w, s)
        w_new = width_for_z0(lambda ww: diff_z0(model, ww, s), target / ratio,
                             g["h"] * 0.02, g["h"] * 8)
        if w_new is None or abs(w_new - w) < w * 0.002:
            return w_new
        w = w_new
    return w


def pair_lateral_gap(board, tracks, layer, ground_filter="GND", zone_cache=None):
    """
    Massa laterale accanto a una coppia: da punti lungo le tracce delle due
    net si misura la distanza dalla massa sui due lati e si tiene la MINORE
    (il lato esterno: dall'altro lato c'e' la traccia compagna). Se la massa
    si trova in almeno meta' dei punti ritorna la mediana (m), altrimenti None.
    """
    if zone_cache is None:
        zone_cache = {}
    if layer not in zone_cache:
        zone_cache[layer] = geometry.find_reference_zones(board, layer, ground_filter)
    pkey = ("pads", layer)
    if pkey not in zone_cache:
        zone_cache[pkey] = [p for p in board.GetPads()
                            if ground_filter.upper() in p.GetNetname().upper() and p.IsOnLayer(layer)]
    straight = [t for t in tracks if t.Type() == pcbnew.PCB_TRACE_T]
    pick = sorted(straight, key=lambda t: -t.GetLength())[:6]
    found, total = [], 0
    for t in pick:
        for g1, g2 in geometry.lateral_gaps(zone_cache[layer], layer, t, pcbnew.FromMM(0.05),
                                            pcbnew.FromMM(1.0), 2, pcbnew.FromMM(1.0),
                                            zone_cache[pkey]):
            total += 1
            sides = [g for g in (g1, g2) if g is not None]
            if sides:
                found.append(min(sides))
    if not total or len(found) < total / 2:
        return None
    found.sort()
    return found[len(found) // 2] * 1e-9
