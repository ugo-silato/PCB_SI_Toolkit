"""
Modulo "openEMS": simulazione elettromagnetica (FDTD) di una linea.

Il plugin NON esegue openEMS dentro KiCad: esporta la geometria della linea
selezionata (tracce, massa sullo stesso layer, piano sotto, dielettrico) in
uno script Python autonomo e lo lancia con un Python separato in cui e'
installato openEMS. Lo script simula, calcola S11, S21 e l'impedenza della
linea e mostra i grafici (matplotlib), salvando anche PNG e CSV.

Modello (prima versione, volutamente semplice):
- solo tracce su un layer ESTERNO (microstrip, eventualmente coplanare);
- rame a spessore nullo (lamina PEC), dielettrico omogeneo con l'Er dello
  stackup, piano di massa sotto pieno nella zona simulata;
- massa sullo stesso layer ricavata dal rame riempito delle zone di massa,
  campionato a griglia (scalinata alla risoluzione della mesh);
- due porte concentrate da 50 ohm alle estremita' libere della linea.
"""
import json
import shutil
import math
import os
import subprocess
import sys
import time

import pcbnew

from ..common import geometry
from . import impedance
from .return_path import _copper_layer_stack
from ..common.i18n import _


def _chain_ends(tracks):
    """
    Estremita' "libere" della linea: punti che compaiono una sola volta fra
    gli estremi delle tracce selezionate (tolleranza 1 um).
    """
    pts = []
    for t in tracks:
        for p in (t.GetStart(), t.GetEnd()):
            pts.append((p.x, p.y, t.GetWidth()))
    ends = []
    for i, (x, y, w) in enumerate(pts):
        shared = sum(1 for j, (x2, y2, _w) in enumerate(pts)
                     if j != i and abs(x - x2) <= 1000 and abs(y - y2) <= 1000)
        if shared == 0:
            ends.append((x, y, w))
    return ends


def build_model(board, tracks, ground_filter="GND", margin_mm=3.0, raster_mm=0.1):
    """
    Raccoglie la geometria da simulare. Solleva ValueError con un messaggio
    chiaro se la selezione non e' adatta. Coordinate in mm, relative
    all'angolo del box simulato.
    """
    tracks = [t for t in tracks if t.Type() == pcbnew.PCB_TRACE_T]
    if not tracks:
        raise ValueError(_("Seleziona in Pcbnew le tracce rettilinee della linea da simulare."))
    nets = {t.GetNetname() for t in tracks}
    layers = {t.GetLayer() for t in tracks}
    if len(nets) != 1 or len(layers) != 1:
        raise ValueError(_("Le tracce selezionate devono essere della stessa net e sullo stesso layer."))
    layer = layers.pop()
    stack = _copper_layer_stack(board)
    if layer not in (stack[0], stack[-1]):
        raise ValueError(_("Per ora si simulano solo linee su un layer esterno (microstrip)."))
    ends = _chain_ends(tracks)
    if len(ends) != 2:
        raise ValueError(
            _("La linea deve avere esattamente due estremita' libere (trovate {0}): seleziona un percorso unico, senza diramazioni.").format(len(ends))
        )

    stackup, note = impedance.read_stackup(board)
    model = impedance.layer_model(stackup, layer, {stack[0], stack[-1]})
    if model is None:
        raise ValueError(_("Stackup non sufficiente per questo layer."))
    _kind, h_m, er, _t = model

    # Box simulato: ingombro delle tracce + margine
    mm = pcbnew.ToMM
    xs = [mm(p.x) for t in tracks for p in (t.GetStart(), t.GetEnd())]
    ys = [mm(p.y) for t in tracks for p in (t.GetStart(), t.GetEnd())]
    x0, x1 = min(xs) - margin_mm, max(xs) + margin_mm
    y0, y1 = min(ys) - margin_mm, max(ys) + margin_mm

    segs = [[mm(t.GetStart().x) - x0, mm(t.GetStart().y) - y0,
             mm(t.GetEnd().x) - x0, mm(t.GetEnd().y) - y0, mm(t.GetWidth())]
            for t in tracks]

    # Massa coplanare: rame riempito delle zone di massa sullo stesso layer,
    # campionato a griglia e unito in strisce orizzontali
    zones = geometry.find_reference_zones(board, layer, ground_filter)
    ground = []
    step = raster_mm
    ny = int((y1 - y0) / step)
    nx = int((x1 - x0) / step)
    for j in range(ny):
        y = y0 + (j + 0.5) * step
        run_start = None
        for i in range(nx + 1):
            covered = False
            if i < nx:
                x = x0 + (i + 0.5) * step
                p = pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y))
                covered = geometry.point_covered_by_any_zone(zones, layer, p)
            if covered and run_start is None:
                run_start = i
            elif not covered and run_start is not None:
                ground.append([run_start * step, j * step, i * step, (j + 1) * step])
                run_start = None

    # Via di massa dentro la zona simulata: collegano la massa coplanare
    # al piano sotto (senza, la massa sopra resterebbe isolata nel modello)
    gnd_vias = []
    for v in board.GetTracks():
        if v.Type() != pcbnew.PCB_VIA_T:
            continue
        if ground_filter.upper() not in v.GetNetname().upper():
            continue
        vx, vy = mm(v.GetPosition().x), mm(v.GetPosition().y)
        if x0 <= vx <= x1 and y0 <= vy <= y1:
            gnd_vias.append([vx - x0, vy - y0, mm(v.GetDrillValue()) / 2.0 + 0.025])

    # Porte microstrip (MSL): occupano un tratto dritto della traccia a
    # ciascuna estremita'. Servono segmenti finali paralleli agli assi e
    # lunghi almeno 1 mm; altrimenti si ripiega sulle porte concentrate.
    msl_ports, msl_note = [], ""
    for ex, ey, _w in ends:
        seg = None
        for t in tracks:
            for a, b in ((t.GetStart(), t.GetEnd()), (t.GetEnd(), t.GetStart())):
                if abs(a.x - ex) <= 1000 and abs(a.y - ey) <= 1000:
                    seg = (a, b, t.GetWidth())
        if seg is None:
            msl_note = _("estremita' non trovata")
            break
        a, b, w = seg
        dx, dy = mm(b.x - a.x), mm(b.y - a.y)
        length = math.hypot(dx, dy)
        if abs(dx) > 1e-3 and abs(dy) > 1e-3:
            msl_note = _("il tratto finale della linea non e' orizzontale o verticale")
            break
        lp = min(5.0, 0.8 * length)  # porta piu' lunga: misura piu' stabile
        if lp < 1.0:
            msl_note = _("il tratto finale dritto della linea e' piu' corto di 1,25 mm")
            break
        axis = "x" if abs(dx) > abs(dy) else "y"
        sign = 1 if (dx if axis == "x" else dy) > 0 else -1
        msl_ports.append({
            "end": [mm(a.x) - x0, mm(a.y) - y0],
            "axis": axis,
            "sign": sign,
            "length": lp,
            "w": mm(w),
        })
    if len(msl_ports) != 2:
        msl_ports = []

    # Unione delle strisce: strisce di righe consecutive con gli stessi
    # bordi in x diventano un solo rettangolo (modello piu' leggero, niente
    # strisce piu' sottili di una cella di mesh)
    merged = []
    open_rects = {}  # (x0, x1) -> rettangolo in costruzione [x0, y0, x1, y1]
    for gx0, gy0, gx1, gy1 in sorted(ground, key=lambda r: (r[1], r[0])):
        key = (round(gx0, 6), round(gx1, 6))
        rect = open_rects.get(key)
        if rect is not None and abs(rect[3] - gy0) < 1e-9:
            rect[3] = gy1  # prosegue il rettangolo della riga sopra
        else:
            if rect is not None:
                merged.append(rect)
            open_rects[key] = [gx0, gy0, gx1, gy1]
    merged += list(open_rects.values())
    ground = merged

    return {
        "net": nets.pop(),
        "gnd_vias": gnd_vias,
        "msl_ports": msl_ports,
        "msl_note": msl_note,
        "layer": board.GetLayerName(layer),
        "size": [x1 - x0, y1 - y0],
        "h": h_m * 1e3,
        "er": er,
        "segments": segs,
        "ground": ground,
        "ports": [[mm(x) - x0, mm(y) - y0, mm(w)] for x, y, w in ends],
        "stackup_note": note,
    }


def write_and_launch(model, python_exe, out_root, f_max_ghz, f_mark_ghz, mesh_mm,
                     openems_path=r"D:\Programmi\openEMS", dump_fields=False, v_signal=1.0, t_rise_ns=1.0, lang="en"):
    """
    Scrive lo script di simulazione in una cartella nuova e lo lancia con il
    Python indicato, in una finestra separata. Ritorna la cartella.
    """
    stamp = time.strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(out_root, _("sim_{0}").format(stamp))
    os.makedirs(out_dir, exist_ok=True)
    params = dict(model, f_max=f_max_ghz * 1e9, f_mark=f_mark_ghz * 1e9, mesh=mesh_mm,
                  openems_path=openems_path, dump_fields=dump_fields,
                  v_signal=v_signal, t_rise_ns=t_rise_ns, lang=lang)
    template_path = os.path.join(os.path.dirname(__file__), "openems_template.py")
    with open(template_path, encoding="utf-8") as f:
        template = f.read()
    script = template.replace("__MODEL_JSON__", json.dumps(params))
    script_path = os.path.join(out_dir, "simulate.py")
    # Il calcolo del TDR sta in un file a parte (provabile fuori da KiCad):
    # lo si copia accanto allo script, che lo importa da li'
    shutil.copy(os.path.join(os.path.dirname(__file__), "tdr_core.py"), out_dir)
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(script)

    # File .bat per rifare le GIF con un'altra tensione senza risimulare:
    # chiede la tensione (e una scala fissa facoltativa) e rilancia lo
    # script in modalita' --results sugli ultimi dati salvati
    bat = (
        _("@echo off\r\ncd /d \"%~dp0\"\r\nset /p V=Tensione del segnale in V (es. 5): \r\nset /p S=Scala colori fissa in V/mm (Invio = automatica): \r\nif \"%S%\"==\"\" (set S=0)\r\n\"{0}\" simulate.py --results --voltage %V% --scale %S%\r\n").format(python_exe)
    )
    with open(os.path.join(out_dir, "reprocess_fields.bat"), "w", encoding="ascii", errors="replace", newline="") as f:
        f.write(bat)

    flags = 0
    if sys.platform.startswith("win"):
        flags = subprocess.CREATE_NEW_CONSOLE  # finestra propria con il log
    subprocess.Popen([python_exe, script_path], cwd=out_dir, creationflags=flags)
    return out_dir
