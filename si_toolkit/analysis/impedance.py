"""
"Impedance calculator" module.

Computes the characteristic impedance Z0 of the tracks. The values shown in
the plugin come from the 2D field solver (field2d.py), which handles
coplanar ground, solder mask and copper thickness. The closed-form formulas
in this file are used as a fast starting point when searching for the
width/gap that gives the target:
- microstrip (track on an outer layer, reference plane on one side only):
  Hammerstad-Jensen formulas with thickness correction;
- coplanar microstrip with ground below (CPWG): elliptic integrals;
- stripline (track on an inner layer between two planes): IPC-2141.

Neither the formulas nor the field solver account for copper roughness or
dielectric losses.

The calculation functions do not depend on pcbnew (they can be tested
outside KiCad); only the stackup and copper reading functions access the
board.
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
    Z0 (ohm) of a microstrip. w = width, h = distance from the plane,
    er = dielectric constant, t = copper thickness. Any units, as long as they
    are the same (e.g. meters).
    """
    # Effective width: the copper thickness electrically "widens" the track
    if t > 0:
        u0 = w / h
        if u0 <= 1.0 / (2 * math.pi):
            dw = (t / math.pi) * (1 + math.log(4 * math.pi * w / t))
        else:
            dw = (t / math.pi) * (1 + math.log(2 * h / t))
        w = w + dw
    u = w / h
    # Effective dielectric constant (part in air and part in the dielectric)
    eeff = (er + 1) / 2 + (er - 1) / 2 / math.sqrt(1 + 12 / u)
    if u < 1:
        eeff += (er - 1) / 2 * 0.04 * (1 - u) ** 2
    if u <= 1:
        return 60 / math.sqrt(eeff) * math.log(8 / u + u / 4)
    return 120 * math.pi / (math.sqrt(eeff) * (u + 1.393 + 0.667 * math.log(u + 1.444)))


def stripline_z0(w, b, er, t):
    """
    Z0 (ohm) of a stripline centred between two planes (IPC-2141):
    b = total distance between the two planes, copper thickness included.
    """
    return 60 / math.sqrt(er) * math.log(1.9 * b / (0.8 * w + t))


def _ellip_k(k):
    """Complete elliptic integral K(k) with the arithmetic-geometric mean."""
    a, b = 1.0, math.sqrt(1.0 - k * k)
    for _step in range(40):
        a, b = (a + b) / 2, math.sqrt(a * b)
    return math.pi / (2 * a)


def cpwg_z0(w, gap, h, er, t=0.0):
    """
    Z0 (ohm) of a COPLANAR microstrip with ground plane below (CPWG): track of
    width w with ground on the same layer at distance 'gap' per side and the
    reference plane at distance h. Formula with elliptic integrals (conformal
    mapping).

    Copper thickness 't' (method of the Qucs/KiCad calculators): the "thick"
    track widens by d and the gap narrows by d ONLY in the air term (between
    track and side ground), while the effective dielectric constant drops
    slightly. Checked against KiCad's PCB Calculator
    (w 0.7 / gap 0.2 / h 1.51 / Er 4.5 / t 0.035: KiCad 58.2 ohm, here 56.7).
    The previous version applied d to the whole calculation and gave 49.8 ohm.
    """
    def parts(w_, g_):
        # q1: term between track and side ground; q3: term towards the plane
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
    Width giving the 'target' impedance, by bisection: z_func(w) decreases as
    w grows. Returns None if the target is outside [w_min, w_max].
    """
    z_hi, z_lo = z_func(w_min), z_func(w_max)  # z_hi: narrow track
    if not (z_lo <= target <= z_hi):
        return None
    lo, hi = w_min, w_max
    for _step in range(60):
        mid = (lo + hi) / 2
        if z_func(mid) > target:
            lo = mid  # impedance too high: a wider track is needed
        else:
            hi = mid
    return (lo + hi) / 2


def _item_kind(it):
    """
    'cu' for a copper layer, 'diel' for a dielectric, None for the rest
    (solder mask, silkscreen...). Uses the pcbnew constants if they exist and,
    failing that, the type name (GetTypeName), because the constant names
    change between KiCad versions.
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
    """Stackup items read with the pcbnew API. Returns (items, errors)."""
    errors = []
    try:
        raw = list(board.GetDesignSettings().GetStackupDescriptor().GetList())
    except Exception as exc:
        return [], [_("API stackup: {0}").format(exc)]

    items = []  # ("cu", layer, thickness m) / ("diel", None, thickness m, er)
    for it in raw:
        try:
            kind = _item_kind(it)
            if kind == "cu":
                items.append(("cu", it.GetBrdLayerId(), it.GetThickness() * 1e-9))
            elif kind == "diel":
                # A dielectric can have several sub-layers: thicknesses summed,
                # er weighted by thickness
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
    """Minimal parser of KiCad s-expressions: nested lists of strings."""
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
    Stackup items read from the saved .kicad_pcb file ("stackup" section).
    Needed when the Python API does not expose the layers. It reads the file
    on disk: unsaved changes are not seen.
    Returns (items, errors).
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
    # Whole "(stackup ...)" block, counting the parentheses outside strings
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
                # (thickness, er) pairs; sub-layers repeat the fields
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
    Reads the physical stackup of the board (Board Setup > Stackup): first
    with the pcbnew API, and if that does not expose the layers, from the
    .kicad_pcb file.

    Returns (dictionary, errors) where the dictionary is: copper_layer -> {
        "t": copper thickness (m),
        "above": (dielectric thickness (m), er) towards the layer above, or None,
        "below": (thickness (m), er) towards the layer below, or None }
    and is empty if the stackup cannot be read.
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
        """Sums the dielectrics from the copper at 'start' up to the next copper."""
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
            # Solder mask directly above/below this copper (outer layers)
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
    # If reading from the file succeeded, the API error no longer matters
    return result, ([] if result else errors)


def _synthetic_stackup(board, er):
    """
    Estimated stackup when the board has none defined: 35 um copper on every
    layer and equal dielectric thickness between adjacent layers, derived from
    the total board thickness. Only an estimate: on 4+ layer boards prepreg
    and core have different thicknesses.
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
            "mask": None,  # estimated stackup: the default solder mask is used
        }
    return result


def gap_for_z0(w, h, er, t, target, g_min=0.03e-3, g_max=3e-3):
    """
    Gap (m) from the coplanar ground giving Z0 = target at a fixed width w,
    by bisection: the impedance grows as the gap widens. None if the target
    cannot be reached within [g_min, g_max].
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
    Stackup to use for the calculation, with a note telling where it comes
    from.

    It first tries to read the one defined in the board; if there is none
    (files converted from other programs often lack it) it uses an estimate
    from the total thickness with er = 4.5. er_override and h_override_m
    (meters), if given, replace the dielectric constant and the dielectric
    thickness in any case.

    Returns (stackup, note).
    """
    try:
        stackup, errors = _read_real_stackup(board)
    except Exception as exc:
        stackup, errors = {}, [str(exc)]
    # Reasons for the reading problems (first two), shown in the note
    err = f" ({'; '.join(errors[:2])})" if errors and not stackup else ""

    # A stackup is usable if at least one layer has a dielectric
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


# Default solder mask (KiCad default values) if the stackup does not describe
# it
DEFAULT_MASK = (10e-6, 3.3)


def layer_geometry(stackup, layer, outer_layers, solder_mask=True):
    """
    Layer geometry for the calculation: dictionary with
      kind: "micro" (outer layer) or "strip" (inner),
      h: dielectric between track and plane below (m),
      h_top: dielectric towards the plane above (stripline only, m),
      er: dielectric constant (weighted average for the stripline),
      t: copper (m), sm_t / sm_er: solder mask (outer layers only).
    None if the stackup is not sufficient.
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
    """Z0 with the closed-form formulas (fast): used as a starting point."""
    if g["kind"] == "micro":
        if gap:
            return cpwg_z0(w, gap, g["h"], g["er"], g["t"])
        return microstrip_z0(w, g["h"], g["er"], g["t"])
    return stripline_z0(w, g["h"] + g["h_top"] + g["t"], g["er"], g["t"])


def field_z0(g, w, gap=None):
    """Z0 with the 2D field solver (accurate)."""
    return field2d.line_z0(w, g["h"], g["er"], g["t"],
                           gap=gap if g["kind"] == "micro" else None,
                           h_top=g["h_top"], sm_t=g["sm_t"], sm_er=g["sm_er"])[0]


def _target_with_field(g, target, var, fixed_w, fixed_gap, x0):
    """
    Finds the width (var="w") or the gap (var="gap") giving Z0 = target with
    the field solver. To avoid dozens of field calculations a "corrected"
    closed-form formula is used: at each step the field/formula ratio is
    measured at the current point and the formula is solved for the target
    divided by that ratio (2 steps are enough, error below 1%).
    """
    x = x0
    for _step in range(2):  # 2 steps: the field/formula ratio changes little
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
    Impedance of a track of width 'width_m' on the given layer, with the 2D
    FIELD SOLVER (field2d); the closed-form formulas are only a starting point
    in the search for the width/gap for the target.
    gap_m: distance from the ground on the same layer (outer layers only).
    Returns (type, z0, width_for_target_m, gap_for_target_m, note).
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
        # Fall back on the formulas if the field calculation fails
        z0 = _formula_z0(g, width_m, gap_m)
        w_target = width_for_z0(lambda ww: _formula_z0(g, ww, gap_m),
                                target_ohm, g["h"] * 0.02, g["h"] * 8)
        g_target = (gap_for_z0(width_m, g["h"], g["er"], g["t"], target_ohm)
                    if gap_m else None)
        note = _("formula (campo 2D fallito: {0})").format(exc)
    return (kind, z0, w_target, g_target, note)

def diagnose_stackup(board, log_path):
    """
    Writes to a file what the plugin sees in the stackup: available names,
    every item with type, thickness and layer. Each step is written to disk
    before running the next one, and every call is protected, so the errors
    end up in the file.
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
    Looks for ground near a group of tracks (same net/layer/width).

    - Side ground (coplanar): from a few points along the tracks it measures
      the distance from the ground copper on the same layer, on both sides. If
      there is ground on both sides in at least half of the measurements, the
      median is returned as gap; otherwise None (no side ground).
    - Plane below: fraction of the points along the tracks covered by ground
      copper on the reference layer (the adjacent one, towards the inside).

    Returns (gap_m or None, plane_below_fraction or None).
    'zone_cache' (dictionary) avoids searching the zones again.
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
        # Pads of the ground net on the layer (their copper is side ground
        # too), saved in the same cache as the zones
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

    # Samples: at most 8 points per group, spread over the tracks
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
        lateral = found[len(found) // 2] * 1e-9  # median, in meters

    # Reference plane below: adjacent layer towards the inside
    stack = _copper_layer_stack(board)
    below = None
    if layer in stack and len(stack) > 1:
        i = stack.index(layer)
        ref = stack[i + 1] if i == 0 else stack[i - 1]
        ref_zones = zones_on(ref)
        # Index of pads and vias, computed only once (key "holes")
        if "holes" not in zone_cache:
            zone_cache["holes"] = _build_indexes(board)[1]
        holes = zone_cache["holes"]
        pts, all_pts = [], []
        for t in pick:
            net = t.GetNetname()
            for p in geometry.sample_points_along_track(t, pcbnew.FromMM(0.5), 20):
                all_pts.append(p)
                # The points near pads/vias of the same net (track ends,
                # intended keep-outs under a pin) do not count as plane
                # interruptions: as in Return Path
                if not _near_item_on_net(holes, p, net, HOLE_EXCLUSION_RADIUS_NM):
                    pts.append(p)
        # Short track (e.g. 1-2 mm between two pads): all the points fall near
        # the pads and would be discarded, leaving "-". In that case all the
        # points are used anyway.
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
    Recognizes differential pairs from net names: suffixes P/N, DP/DM, + / -
    (with an optional _ - . separator). For example
    "USB_DP"/"USB_DM", "/ETH/TX_P"/"/ETH/TX_N", "D+"/"D-".

    Returns a list of (pair_name, positive_net, negative_net).
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
    Physical model of the layer: ("micro", h, er, t) for an outer layer,
    ("strip", b, er, t) for an inner one, or None if the stackup is not
    sufficient.
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
    """Single-ended Z0 (ohm) of a track of width w according to the layer model."""
    kind, h, er, t = model
    return microstrip_z0(w, h, er, t) if kind == "micro" else stripline_z0(w, h, er, t)


def diff_z0(model, w, s):
    """
    Differential impedance (ohm) of an edge-coupled pair, with width w and
    edge-to-edge spacing s (IPC-2141 formulas):
      microstrip: Zdiff = 2*Z0*(1 - 0.48*exp(-0.96*s/h))
      stripline:  Zdiff = 2*Z0*(1 - 0.347*exp(-2.9*s/b))
    Does not account for coplanar ground next to the pair (used only as a
    starting point for the field solver).
    """
    kind, h, er, t = model
    z0 = single_z0(model, w)
    if kind == "micro":
        return 2 * z0 * (1 - 0.48 * math.exp(-0.96 * s / h))
    return 2 * z0 * (1 - 0.347 * math.exp(-2.9 * s / h))


def width_for_diff(model, s, target, h_ref):
    """Width (m) giving Zdiff = target at a fixed spacing s, or None."""
    return width_for_z0(lambda w: diff_z0(model, w, s), target, h_ref * 0.02, h_ref * 8)


# ---------------------------------------------------------------------
# Differential pairs with the 2D field solver
# ---------------------------------------------------------------------
def pair_field(g, w, s, gap=None):
    """
    Differential pair with the field solver (field2d.pair_z0) on the
    geometry 'g' from layer_geometry. gap: side ground on the outer side
    (outer layers only). Returns (zdiff, zcommon, z_odd, z_even).
    """
    return field2d.pair_z0(w, s, g["h"], g["er"], g["t"],
                           gap=gap if g["kind"] == "micro" else None,
                           h_top=g["h_top"], sm_t=g["sm_t"], sm_er=g["sm_er"])


def _model_from_geometry(g):
    """Model (type, h, er, t) for the closed-form formulas, from the layer geometry."""
    if g["kind"] == "micro":
        return ("micro", g["h"], g["er"], g["t"])
    return ("strip", g["h"] + g["h_top"] + g["t"], g["er"], g["t"])


def width_for_diff_field(g, s, target, gap=None):
    """
    Width (m) giving Zdiff = target with the field solver, at a fixed spacing
    s. As for single tracks: the IPC-2141 formula is "corrected" with the
    field/formula ratio measured at the current point (2 steps).
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
    Side ground next to a pair: from points along the tracks of the two nets
    the distance from ground is measured on both sides and the SMALLER is kept
    (the outer side: on the other side there is the partner track). If ground
    is found in at least half of the points the median (m) is returned,
    otherwise None.
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
