# -*- coding: utf-8 -*-
"""
Rough estimate of the current taken by each load of a net, from the type
and value of the components read on the board.

The plugin cannot know the real operating point (that needs a circuit
simulation with the models of all the parts). These rules only avoid the
plain equal split: a TVS that does not conduct gets 0, a resistor to ground
gets V/R, a MOSFET gate gets almost nothing, and so on. Every estimate
carries the reason, so the user can check it and correct it.

estimate_loads(...) returns one dictionary per load:
    ref, pin, kind, current (A), reason, include (bool)
"""
import math
import re

from ..common.i18n import _
from . import net_path

# Diodes that do not conduct in normal operation (protection, reference):
# words found in the value or in the footprint name
_TVS_WORDS = ("TVS", "ESD", "SMAJ", "SMBJ", "SMCJ", "SMF", "PESD", "P6KE", "1.5KE", "P4SMA",
              "ZENER", "BZX", "BZT", "MMSZ", "MMBZ", "ZD", "TPD", "USBLC", "PRTR")

# Unit prefixes of component values (4k7, 100n, 2.2u, 1R5, 10M ...)
_PREFIX = {"p": 1e-12, "n": 1e-9, "u": 1e-6, "µ": 1e-6, "m": 1e-3, "r": 1.0,
           "k": 1e3, "K": 1e3, "M": 1e6, "G": 1e9}


def parse_value(text):
    """
    Number from a component value: '4k7' -> 4700, '100n' -> 1e-7,
    '10uF' -> 1e-5, '1R5' -> 1.5, '220' -> 220. None if not readable.
    """
    if not text:
        return None
    s = text.strip().replace(",", ".").replace("Ω", "").replace("ohm", "").replace("Ohm", "")
    # Notation with the prefix in place of the decimal point: 4k7, 1R5, 2u2
    m = re.match(r"^(\d+)([pnuµmrRkKMG])(\d+)", s)
    if m:
        p = m.group(2) if m.group(2) != "R" else "r"
        return float(m.group(1) + "." + m.group(3)) * _PREFIX[p]
    # Normal notation: number, optional prefix, optional unit letters
    m = re.match(r"^(\d+(?:\.\d+)?)\s*([pnuµmrRkKMG]?)", s)
    if not m:
        return None
    p = m.group(2)
    if p == "R":
        p = "r"
    # 'm' before 'F' or alone is milli; 'M' is mega (resistors)
    return float(m.group(1)) * _PREFIX.get(p, 1.0) if p else float(m.group(1))


def voltage_from_net(name):
    """
    Voltage written in a net name: VCC_3.3 -> 3.3, +5V -> 5, 3V3 -> 3.3,
    12V_IN -> 12. None if the name has no voltage.
    """
    if not name:
        return None
    n = name.upper()
    m = re.search(r"(\d+)V(\d+)", n)          # 3V3, 1V8
    if m:
        return float(m.group(1) + "." + m.group(2))
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*V(?![A-Z0-9])", n)  # 5V, 3.3V, 12 V, 12V_IN
    if m:
        return float(m.group(1).replace(",", "."))
    m = re.search(r"(?:VCC|VDD|VIN|VBAT|V)[_\-]?(\d+(?:[.,]\d+)?)", n)  # VCC_3.3, VDD5
    if m:
        return float(m.group(1).replace(",", "."))
    return None


def _func_letters(text):
    """
    Leading letters of a pin name: 'C-3' -> 'C', 'B_2' -> 'B',
    'Gate' -> 'GATE', '3' -> ''. Names like 'C-3' (function-number) are
    common in transistor symbols.
    """
    m = re.match(r"\s*([A-Za-z]+)", text or "")
    return m.group(1).upper() if m else ""


def _pin_function(pad, ref=""):
    """
    Function of the pad (B, C, E, G, D, S ...) and where it was read:
      1) the pin name copied from the schematic symbol (GetPinFunction);
      2) the pad number, if it has letters (e.g. 'C', 'B2');
      3) the name KiCad gives to an unnamed net: 'Net-(Q1-C)' or 'Q1-C'
         = component Q1, pin C.
    Returns (letters, source text); ('', '') if nothing is found.
    """
    try:
        f = _func_letters(str(pad.GetPinFunction()))
        if f:
            return f, _("nome del pin")
    except AttributeError:
        pass
    try:
        f = _func_letters(str(pad.GetNumber()))
        if f:
            return f, _("numero del pad")
    except AttributeError:
        pass
    net = pad.GetNetname() or ""
    if ref:
        m = re.search(re.escape(ref) + r"-(?:Pad)?([A-Za-z]+)", net)
        if m and m.group(1).upper() != "PAD":
            return m.group(1).upper(), _("nome della net {0}").format(net)
    return "", ""


def _fp_text(fp):
    """Value and footprint name of a component, upper case, for the keyword checks."""
    parts = []
    try:
        parts.append(fp.GetValue())
    except AttributeError:
        pass
    try:
        parts.append(str(fp.GetFPID().GetLibItemName()))
    except AttributeError:
        pass
    return " ".join(parts).upper()


def _series_resistance(crossings):
    """Sum of the series resistors crossed to reach a load (ohm)."""
    total = 0.0
    for _a, _b, ref in crossings:
        if net_path._ref_prefix(ref) != "R":
            continue
        try:
            total += parse_value(_b.GetParentFootprint().GetValue()) or 0.0
        except AttributeError:
            continue
    return total


def estimate_one(pad, crossings, ref, volts, mode, freq_hz, r_pullup=None):
    """
    Current (A) and reason for one load, from its type, value and the pin
    reached. 'volts' is the voltage of the input net, 'freq_hz' the
    frequency used for the capacitors in HF.
    """
    fp = pad.GetParentFootprint()
    prefix = net_path._ref_prefix(ref)
    text = _fp_text(fp)
    value = ""
    try:
        value = fp.GetValue()
    except AttributeError:
        pass
    r_series = _series_resistance(crossings)
    func, func_src = _pin_function(pad, ref)
    dc = mode == "dc"

    # Protection and zener diodes: off in normal operation
    if prefix in ("D", "TVS", "ZD") and any(w in text for w in _TVS_WORDS) or prefix in ("TVS", "ZD"):
        return 0.0, "tvs", _("TVS / zener: in funzionamento normale non conduce")
    if prefix in ("LED",) or (prefix == "D" and "LED" in text):
        if r_series > 0:
            i = max(0.0, volts - 2.0) / r_series
            return i, "led", _("LED: ({0:g} V - 2 V) / {1:g} ohm in serie").format(volts, r_series)
        return 2e-3, "led", _("LED: valore tipico 2 mA (nessuna resistenza in serie trovata)")
    if prefix == "D":
        return 0.0, "diode", _("Diodo verso massa: conduce solo se la linea scende sotto massa")

    # Resistor to ground: Ohm's law, with the series resistors crossed
    if prefix == "R":
        r = parse_value(value)
        if r:
            i = volts / (r + r_series)
            extra = _(" + {0:g} ohm in serie").format(r_series) if r_series else ""
            return i, "res", _("Resistenza: {0:g} V / ({1:g} ohm{2})").format(volts, r, extra)
        return 1e-3, "res", _("Resistenza con valore non leggibile ({0}): 1 mA di prova").format(value)

    # Capacitor to ground: no DC current; in HF I = V * 2 pi f C
    if prefix == "C":
        if dc:
            return 0.0, "cap", _("Condensatore: in continua non passa corrente")
        c = parse_value(value)
        if c:
            z = 1.0 / (2 * math.pi * freq_hz * c) + r_series
            # Upper bound: in reality the driver limits the current, but the
            # ratio with the other loads is what matters for the map
            return volts / z, "cap", _("Condensatore {0}: V / |Z| a {1:g} MHz (in realta' limitata "
                                       "dal driver)").format(value, freq_hz / 1e6)
        return 1e-3, "cap", _("Condensatore con valore non leggibile ({0}): 1 mA di prova").format(value)

    # Inductor / ferrite to ground: like a short in DC, limited by the series R
    if prefix in ("L", "FB"):
        if r_series > 0:
            return volts / r_series, "ind", _("Induttanza verso massa: limitata da {0:g} ohm in serie").format(r_series)
        return 1e-3, "ind", _("Induttanza verso massa: corrente non stimabile, 1 mA di prova")

    # Transistors: the pin reached decides
    if prefix in ("Q", "T", "M"):
        if func.startswith("G"):
            return (0.0 if dc else 1e-5), "gate", _("Gate di un MOSFET: corrente quasi nulla "
                                                    "(solo carica della capacita' di gate)")
        if func.startswith("B"):
            if r_series > 0:
                i = max(0.0, volts - 0.7) / r_series
                return i, "base", _("Base ({0}): ({1:g} V - 0,7 V) / {2:g} ohm in serie").format(
                    func_src, volts, r_series)
            return 1e-4, "base", _("Base di un BJT: 0,1 mA di prova (nessuna resistenza in serie)")
        if func.startswith(("C", "D")):
            # Collector / drain on the line: when the transistor is on it
            # pulls the line to ground; the current is limited by the
            # resistors in series and by the pull-up of the line
            r_lim = r_series + (r_pullup or 0.0)
            if r_lim > 0:
                return volts / r_lim, "coll", _(
                    "Collettore/drain ({0}): con il transistor acceso, {1:g} V / {2:g} ohm "
                    "(serie + pull-up); spento = 0").format(func_src, volts, r_lim)
            return 1e-3, "coll", _("Collettore/drain ({0}): nessuna resistenza che limita la corrente "
                                   "trovata, 1 mA di prova").format(func_src)
        try:
            num = str(pad.GetNumber())
        except AttributeError:
            num = "?"
        return 1e-3, "trans", _("Transistor (pad {0}, funzione del pin non trovata): corrente non nota, "
                                "1 mA di prova").format(num)

    # Integrated circuits: input pins take almost nothing
    if prefix in ("U", "IC"):
        return 1e-6, "ic", _("Ingresso di un chip: corrente trascurabile (1 uA di prova)")

    return 1e-3, "other", _("Componente {0}: corrente non nota, 1 mA di prova").format(prefix or "?")


# Parts that carry the supply voltage to a nearby net (DC path): resistors
# (pull-ups), inductors, ferrites, fuses, jumpers, net ties. Not capacitors.
_DC_SERIES = ("R", "L", "FB", "FL", "F", "JP", "NT")


def pullup_resistance(board, net, ref_filter="GND"):
    """
    Resistance of the pull-up of a net: the lowest two-pin resistor that
    joins it to a net with a voltage in the name (VCC_5V, +3V3 ...).
    None if there is none.
    """
    best = None
    for p in board.GetPads():
        if p.GetNetname() != net:
            continue
        try:
            fp = p.GetParentFootprint()
            pads = list(fp.Pads())
            ref = fp.GetReference()
        except AttributeError:
            continue
        if len(pads) != 2 or net_path._ref_prefix(ref) != "R":
            continue
        other = pads[1] if pads[0] is p else pads[0]
        onet = other.GetNetname() or ""
        if ref_filter.upper() in onet.upper() or not voltage_from_net(onet):
            continue
        r = parse_value(fp.GetValue())
        if r and (best is None or r < best):
            best = r
    return best


def find_voltage(board, pad_in, ref_filter="GND", max_hops=3):
    """
    Voltage of the input line when its net name has none.

    1) The net name itself (VCC_3.3, 5V, 3V3 ...).
    2) Nets reached through two-pin DC series parts (a pull-up to VCC_5V,
       a ferrite from +3V3 ...), nearest first: the supply voltage, i.e.
       an upper limit for the line.
    3) The other pads of the input component (a regulator, a power
       connector) whose net has a voltage in the name: the lowest one.

    Returns (volts, text) with the text explaining where the value comes
    from, or (None, None) if nothing is found.
    """
    net0 = pad_in.GetNetname()
    v = voltage_from_net(net0)
    if v:
        return v, _("dal nome della net {0}").format(net0)

    by_net = {}
    for p in board.GetPads():
        by_net.setdefault(p.GetNetname(), []).append(p)

    # Breadth-first search through the DC series parts
    seen = {net0}
    frontier = [(net0, [])]
    for _hop in range(max_hops):
        nxt = []
        for net, refs in frontier:
            for pad in by_net.get(net, []):
                try:
                    fp = pad.GetParentFootprint()
                except AttributeError:
                    continue
                if fp is None:
                    continue
                pads = list(fp.Pads())
                ref = fp.GetReference()
                if len(pads) != 2 or net_path._ref_prefix(ref) not in _DC_SERIES:
                    continue
                other = pads[1] if pads[0] is pad or (
                    pads[0].GetPosition().x == pad.GetPosition().x and
                    pads[0].GetPosition().y == pad.GetPosition().y) else pads[0]
                onet = other.GetNetname()
                if not onet or onet in seen or ref_filter.upper() in onet.upper():
                    continue
                seen.add(onet)
                v = voltage_from_net(onet)
                if v:
                    return v, _("da {0} tramite {1}").format(onet, ", ".join(refs + [ref]))
                nxt.append((onet, refs + [ref]))
        frontier = nxt

    # Other pads of the input component (regulator, power connector)
    try:
        fp = pad_in.GetParentFootprint()
        cands = []
        for p in fp.Pads():
            v = voltage_from_net(p.GetNetname())
            if v:
                cands.append((v, p.GetNetname()))
        if cands:
            v, n = min(cands)
            return v, _("da {0}, net del componente di ingresso {1}").format(n, fp.GetReference())
    except AttributeError:
        pass
    return None, None


def estimate_loads(board, pad_in, ref_filter="GND", mode="hf", volts=None, freq_hz=10e6):
    """
    Loads reached from pad_in (net_path.find_loads) with the estimated
    current. In DC the capacitors are left out already by find_loads.

    Returns (loads, volts, origin): loads = list of dictionaries (see the
    module), volts = voltage used, origin = text saying where it comes
    from; origin is None when the voltage was not found and 3.3 V is only
    an assumption (or when the user wrote it: volts given).
    """
    origin = None
    if volts is None:
        volts, origin = find_voltage(board, pad_in, ref_filter)
        if volts is None:
            volts = 3.3
    out = []
    for pad, crossings, ref in net_path.find_loads(board, pad_in, ref_filter, dc=(mode == "dc")):
        # Pull-up on the load's own net, or else on the input line
        r_up = pullup_resistance(board, pad.GetNetname(), ref_filter) or \
            pullup_resistance(board, pad_in.GetNetname(), ref_filter)
        i, kind, reason = estimate_one(pad, crossings, ref, volts, mode, freq_hz, r_up)
        out.append({"ref": ref, "pin": net_path._pad_label(pad), "pad": pad, "crossings": crossings,
                    "kind": kind, "current": i, "reason": reason, "include": i > 0})
    return out, volts, origin
