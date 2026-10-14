# -*- coding: utf-8 -*-
"""
Script generato dal plugin "PCB Signal Integrity Toolkit" di KiCad.
Simula con openEMS una linea su PCB e mostra S11, S21 e impedenza.
Si puo' rilanciare a mano:  python simulate.py
"""
import json
import os
import sys

import numpy as np

M = json.loads(r'''__MODEL_JSON__''')


def _hook(exc_type, exc, tb):
    """In caso di errore stampa il dettaglio e NON chiude la finestra."""
    import traceback

    traceback.print_exception(exc_type, exc, tb)
    print(T("\nSi e' verificato un errore: copia il testo qui sopra.",
            "\nAn error occurred: copy the text above."))
    print(T("Per rielaborare i dati senza rifare la simulazione:  python simulate.py --results",
            "To reprocess the data without simulating again:  python simulate.py --results"))
    input(T("Premi Invio per chiudere...", "Press Enter to close..."))


sys.excepthook = _hook

# Lingua dei grafici (scelta nella scheda Opzioni del plugin)
EN = M.get("lang", "en") == "en"


def T(it, en):
    """Testo dei grafici nella lingua scelta."""
    return en if EN else it

# Dove stanno le DLL di openEMS: la variabile OPENEMS_INSTALL_PATH puo'
# mancare se KiCad era gia' aperto quando e' stata creata, quindi la si
# imposta qui dal valore passato dal plugin e si aggiunge la cartella
# alla ricerca delle DLL di Windows.
_oe = M.get("openems_path") or os.environ.get("OPENEMS_INSTALL_PATH", r"D:\Programmi\openEMS")
os.environ["OPENEMS_INSTALL_PATH"] = _oe
os.environ["PATH"] = _oe + os.pathsep + os.environ.get("PATH", "")
if hasattr(os, "add_dll_directory") and os.path.isdir(_oe):
    os.add_dll_directory(_oe)

try:
    from CSXCAD import ContinuousStructure
    from openEMS import openEMS
except ImportError as exc:
    print(T("openEMS non trovato in questo Python:", "openEMS not found in this Python:"), exc)
    print(T("Cartella openEMS usata:", "openEMS folder used:"), _oe)
    input(T("Premi Invio per chiudere...", "Press Enter to close..."))
    sys.exit(1)

HERE = os.path.dirname(os.path.abspath(__file__))
# Una cartella dati NUOVA per ogni simulazione (data e ora nel nome): cosi'
# non serve cancellare quella vecchia, che Windows/OneDrive possono tenere
# bloccata. Con --results si usa l'ultima cartella esistente.
import glob
import time

if "--results" in sys.argv:
    _old = sorted(glob.glob(os.path.join(HERE, "sim_data*")))
    SIM_PATH = _old[-1] if _old else os.path.join(HERE, "sim_data")
else:
    SIM_PATH = os.path.join(HERE, "sim_data_" + time.strftime("%Y%m%d_%H%M%S"))

sx, sy = M["size"]
h, er = M["h"], M["er"]
res = M["mesh"]
air = 4.0 * h + 2.0  # aria sopra la scheda (mm)
print(T("Linea {0} su {1}", "Line {0} on {1}").format(M['net'], M['layer'])
      + f": box {sx:.1f} x {sy:.1f} mm, h = {h:.3f} mm, Er = {er:.2f}")

# --- Simulatore: eccitazione gaussiana da 0 a f_max ---
f_max = M["f_max"]
# Limite alto di timestep: la simulazione si ferma comunque prima, quando
# l'energia scende a -40 dB (EndCriteria)
FDTD = openEMS(NrTS=1000000, EndCriteria=1e-4)
FDTD.SetGaussExcite(f_max / 2, f_max / 2)
# Bordi assorbenti PML (8 celle): piu' stabili dei MUR quando il rame
# arriva fino al bordo del volume simulato
FDTD.SetBoundaryCond(["PML_8"] * 6)

CSX = ContinuousStructure()
FDTD.SetCSX(CSX)
mesh = CSX.GetGrid()
mesh.SetDeltaUnit(1e-3)  # unita' di disegno: mm

# --- Dielettrico e piano di massa sotto (pieno nella zona simulata) ---
sub = CSX.AddMaterial("substrato", epsilon=er)
sub.AddBox([0, 0, 0], [sx, sy, h], priority=0)
pec = CSX.AddMetal("rame")
pec.AddBox([0, 0, 0], [sx, sy, 0], priority=10)

# --- Tracce: rettangolo + estremita' tonde (poligoni) a quota h ---
xlines, ylines = [0, sx], [0, sy]
for x0, y0, x1, y1, w in M["segments"]:
    dx, dy = x1 - x0, y1 - y0
    L = (dx * dx + dy * dy) ** 0.5 or 1e-9
    nx, ny = -dy / L * w / 2, dx / L * w / 2
    px = [x0 + nx, x1 + nx, x1 - nx, x0 - nx]
    py = [y0 + ny, y1 + ny, y1 - ny, y0 - ny]
    pec.AddPolygon([px, py], "z", h, priority=10)
    for cx, cy in ((x0, y0), (x1, y1)):
        ang = np.linspace(0, 2 * np.pi, 13)[:-1]
        pec.AddPolygon([list(cx + w / 2 * np.cos(ang)), list(cy + w / 2 * np.sin(ang))], "z", h, priority=10)
    # Linee di mesh sui bordi dei tratti allineati agli assi
    # Linee di mesh sui bordi dei tratti allineati agli assi
    if abs(dx) < 1e-6:
        xlines += [x0 - w / 2, x0 + w / 2]
    if abs(dy) < 1e-6:
        ylines += [y0 - w / 2, y0 + w / 2]

# --- Massa coplanare sullo stesso layer (strisce) ---
for gx0, gy0, gx1, gy1 in M["ground"]:
    pec.AddBox([gx0, gy0, h], [gx1, gy1, h], priority=5)


def _near_track(x, y, dist=1.0):
    """Vero se il punto e' entro 'dist' mm dal bordo di una traccia."""
    for sx0, sy0, sx1, sy1, sw in M["segments"]:
        dx, dy = sx1 - sx0, sy1 - sy0
        L2 = dx * dx + dy * dy
        u = 0.0 if L2 == 0 else max(0.0, min(1.0, ((x - sx0) * dx + (y - sy0) * dy) / L2))
        d = ((x - sx0 - u * dx) ** 2 + (y - sy0 - u * dy) ** 2) ** 0.5
        if d <= sw / 2 + dist:
            return True
    return False


# Linee di mesh sui bordi della massa coplanare VICINO alle tracce: senza,
# openEMS sposta il bordo della massa sulla linea di mesh piu' vicina e il
# gap simulato puo' risultare molto diverso da quello reale.
for gx0, gy0, gx1, gy1 in M["ground"]:
    cy, cx = (gy0 + gy1) / 2, (gx0 + gx1) / 2
    for gx in (gx0, gx1):
        if _near_track(gx, cy):
            xlines.append(gx)
    for gy in (gy0, gy1):
        if _near_track(cx, gy):
            ylines.append(gy)

# --- Via di massa: cilindri di rame dal piano sotto alla massa sopra ---
for vx, vy, vr in M.get("gnd_vias", []):
    # Nessuna linea di mesh al centro delle via: con tante via si creerebbero
    # celle minuscole e un passo temporale piccolissimo
    pec.AddCylinder([vx, vy, 0], [vx, vy, h], vr, priority=10)
print(T("Via di massa nel modello:", "Ground vias in the model:"), len(M.get("gnd_vias", [])))

# --- Porte ---
# Se possibile porte MICROSTRIP (MSL): misurano tensione e corrente lungo un
# tratto di traccia e danno l'impedenza della linea senza l'effetto della
# porta. Altrimenti porte concentrate da 50 ohm alle estremita'.
ports = []
use_msl = bool(M.get("msl_ports"))
msl_specs = []  # porte MSL da creare dopo la mesh
if use_msl:
    print(T("Porte microstrip (MSL) alle due estremita'.", "Microstrip (MSL) ports at both ends."))
    for k, mp in enumerate(M["msl_ports"]):
        ex, ey = mp["end"]
        lp, w, sign = mp["length"], mp["w"], mp["sign"]
        if mp["axis"] == "x":
            start = [ex, ey - w / 2, h]
            stop = [ex + sign * lp, ey + w / 2, 0]
            xlines += [ex, ex + sign * lp]
            ylines += [ey - w / 2, ey + w / 2]
        else:
            start = [ex - w / 2, ey, h]
            stop = [ex + w / 2, ey + sign * lp, 0]
            xlines += [ex - w / 2, ex + w / 2]
            ylines += [ey, ey + sign * lp]
        # La porta MSL si crea DOPO la mesh (servono almeno 5 linee lungo il
        # suo tratto): qui si salvano i dati e si aggiungono linee di mesh
        # fitte lungo la porta
        msl_specs.append((k, start, stop, mp["axis"], lp))
        lines_along = list(np.linspace(0, sign * lp, 9))
        if mp["axis"] == "x":
            xlines += [ex + d for d in lines_along]
        else:
            ylines += [ey + d for d in lines_along]
else:
    print(T("Porte concentrate (MSL non possibili:", "Lumped ports (MSL not possible:"), M.get("msl_note") or "?", ")")
    for k, (px_, py_, w) in enumerate(M["ports"]):
        a = w / 2
        start, stop = [px_ - a, py_ - a, 0], [px_ + a, py_ + a, h]
        ports.append(FDTD.AddLumpedPort(k + 1, 50, start, stop, "z", 1.0 if k == 0 else 0.0, priority=20))
        xlines += [px_ - a, px_ + a]
        ylines += [py_ - a, py_ + a]

def merge_close(lines, min_gap):
    """
    Ordina le linee di mesh e unisce quelle piu' vicine di 'min_gap'
    (le sostituisce con la loro media). Celle troppo piccole obbligano
    openEMS a un passo temporale minuscolo e la simulazione diventa
    lentissima.
    """
    out = []
    for v in sorted(lines):
        if out and v - out[-1][-1] < min_gap:
            out[-1].append(v)
        else:
            out.append([v])
    return [sum(g) / len(g) for g in out]


# --- Mesh fine nel gap fra traccia e massa coplanare ---
# Per ogni tratto dritto si cerca, su ciascun lato, il bordo di massa piu'
# vicino (entro 1 mm) e si mettono almeno 8 celle fra traccia e massa:
# con poche celle nel gap openEMS sottostima l'impedenza.
fine_min = res
gx_edges = sorted({v for r in M["ground"] for v in (r[0], r[2])})
gy_edges = sorted({v for r in M["ground"] for v in (r[1], r[3])})
for x0, y0, x1, y1, w in M["segments"]:
    if abs(y1 - y0) < 1e-6:  # tratto orizzontale: gap lungo y
        edges, center, add = gy_edges, y0, ylines
    elif abs(x1 - x0) < 1e-6:  # tratto verticale: gap lungo x
        edges, center, add = gx_edges, x0, xlines
    else:
        continue
    for side in (1, -1):
        t_edge = center + side * w / 2
        cand = [e for e in edges if 0 < side * (e - t_edge) <= 1.0]
        if not cand:
            continue
        # Solo gap "veri": bordi di massa a meno di 0,08 mm dalla traccia
        # sono quasi sempre artefatti (pad, gocce, curve) e farebbero celle
        # minuscole, con un passo temporale piccolissimo
        cand = [e for e in cand if abs(e - t_edge) >= 0.08]
        if not cand:
            continue
        g_edge = min(cand, key=lambda e: abs(e - t_edge))
        gap = abs(g_edge - t_edge)
        n = 8
        add += list(np.linspace(t_edge, g_edge, n + 1))
        # Cella nel gap mai sotto 0,02 mm
        fine_min = min(fine_min, max(gap / n, 0.02))
print(T("Cella minima nel gap:", "Smallest cell in the gap:") + f" {fine_min:.3f} mm")

xlines = merge_close(xlines, max(min(res / 3, fine_min * 0.6), 0.012))
ylines = merge_close(ylines, max(min(res / 3, fine_min * 0.6), 0.012))

# Spazio in piu' oltre la scheda, occupato dai bordi PML
pml_pad = 8 * res
mesh.AddLine("x", xlines + [-pml_pad, sx + pml_pad])
mesh.AddLine("y", ylines + [-pml_pad, sy + pml_pad])
# 8 celle nel dielettrico: la porta microstrip integra il campo in
# verticale, e con poche celle l'impedenza letta risulta troppo alta
# Linee fitte in verticale attorno al piano del rame (z = h): il campo nel
# gap della coplanare e' bidimensionale (larghezza x altezza) e serve la
# stessa finezza in z che in y. Passi crescenti da fine_min fino a res.
z_fine = []
step, dz = fine_min, 0.0
while dz + step < min(h * 0.6, 1.0) and step < res:
    dz += step
    z_fine += [h - dz, h + dz]
    step *= 1.3
# Anche in verticale si uniscono le linee troppo vicine (celle minuscole
# rallenterebbero tutta la simulazione)
mesh.AddLine("z", merge_close(list(np.linspace(0, h, 9)) + [-air / 2, h + air] + z_fine,
                              max(fine_min * 0.6, 0.012)))
c0 = 299792458.0
max_cell = c0 / f_max / np.sqrt(er) / 20 * 1e3  # lambda/20 nel dielettrico (mm)
mesh.SmoothMeshLines("x", min(res, max_cell), 1.4)
mesh.SmoothMeshLines("y", min(res, max_cell), 1.4)
mesh.SmoothMeshLines("z", min(h / 8, max_cell), 1.4)
print(T("Celle di mesh:", "Mesh cells:"), len(mesh.GetLines("x")), "x", len(mesh.GetLines("y")), "x", len(mesh.GetLines("z")))
for axis in "xyz":
    ln = np.array(mesh.GetLines(axis))
    print(T("  cella minima in", "  smallest cell in") + f" {axis}: {np.min(np.diff(ln)):.4f} mm")

# --- Porte microstrip: create ora che la mesh esiste ---
for k, start, stop, axis, lp in msl_specs:
    ports.append(FDTD.AddMSLPort(
        k + 1, pec, start, stop, axis, "z",
        excite=-1 if k == 0 else 0,
        FeedShift=min(10 * res, lp / 3),
        MeasPlaneShift=lp / 2,
        # Resistenza da 50 ohm sulla porta: senza, l'estremita' della linea
        # e' aperta, il segnale rimbalza avanti e indietro e l'energia non
        # scende mai (la simulazione non finisce)
        Feed_R=50,
        priority=10,
    ))

# --- Registrazione dei campi (facoltativa) per le GIF animate ---
# Due piani: vista dall'alto a meta' del dielettrico (dove il campo sotto la
# traccia e' piu' intenso) e sezione trasversale al centro del tratto piu'
# lungo. openEMS li salva nel tempo in file HDF5 dentro la cartella dati.
section_axis = None
if M.get("dump_fields"):
    top = CSX.AddDump("field_top", dump_type=0, file_type=1, sub_sampling=[2, 2, 1])
    top.AddBox([0, 0, h / 2], [sx, sy, h / 2])
    longest = max(M["segments"], key=lambda sg: (sg[2] - sg[0]) ** 2 + (sg[3] - sg[1]) ** 2)
    mx, my = (longest[0] + longest[2]) / 2, (longest[1] + longest[3]) / 2
    sez = CSX.AddDump("field_section", dump_type=0, file_type=1)
    if abs(longest[3] - longest[1]) < abs(longest[2] - longest[0]):
        # tratto orizzontale: sezione a x costante
        section_axis = "x"
        section_pos = mx
        sez.AddBox([mx, 0, 0], [mx, sy, 3 * h])
    else:
        section_axis = "y"
        section_pos = my
        sez.AddBox([0, my, 0], [sx, my, 3 * h])
    print(T("Registrazione dei campi attiva (le GIF si creano alla fine).",
            "Field recording on (the GIFs are created at the end)."))

# --- Simulazione ---
# Con l'opzione --results si salta la simulazione e si rielaborano i
# dati gia' calcolati nella cartella sim_data
if "--results" in sys.argv and os.path.isdir(SIM_PATH):
    print(T("Uso i dati gia' calcolati (simulazione saltata).", "Using the data already computed (simulation skipped)."))
else:
    print(T("Simulazione in corso (puo' richiedere diversi minuti)...", "Simulation running (it may take several minutes)..."))
    FDTD.Run(SIM_PATH, cleanup=True)

# --- Risultati ---
f = np.linspace(f_max / 100, f_max, 401)
for p in ports:
    p.CalcPort(SIM_PATH, f, ref_impedance=50)
s11 = ports[0].uf_ref / ports[0].uf_inc
s21 = ports[1].uf_ref / ports[0].uf_inc

# Impedenza della linea, in DUE modi indipendenti (per confronto):
# - z_port: letta dalla porta microstrip (tensione/corrente lungo la porta);
# - z_s: ricavata dai parametri S (linea supposta simmetrica).
z_port = None
if use_msl:
    # Senza impedenza di riferimento openEMS usa quella misurata della linea
    # e la mette in Z_ref; poi si torna a 50 ohm per i parametri S.
    try:
        ports[0].CalcPort(SIM_PATH, f)
        z_meas = getattr(ports[0], "Z_ref", None)
        if z_meas is not None and np.size(z_meas) == np.size(f):
            z_port = np.real(z_meas)
    except Exception as exc:
        print(T("Impedenza dalla porta non disponibile:", "Port impedance not available:"), exc)
    ports[0].CalcPort(SIM_PATH, f, ref_impedance=50)

s22, s12, z0r = s11, s21, 50.0
den = 2 * s21
B = z0r * ((1 + s11) * (1 + s22) - s12 * s21) / den
C = ((1 - s11) * (1 - s22) - s12 * s21) / den / z0r
z_s = np.abs(np.sqrt(B / C))

# Valore principale: dai parametri S (validato su una microstrip ideale da
# 50 ohm: 50,2 ohm). La lettura dalla porta risulta circa +20% e resta
# solo come curva di confronto.
zline = z_s

i_mark = int(np.argmin(abs(f - M["f_mark"])))
db = lambda x: 20 * np.log10(np.abs(x) + 1e-15)
print("\n" + T("A", "At") + f" {f[i_mark]/1e9:.3f} GHz: S11 = {db(s11)[i_mark]:.1f} dB, "
      f"S21 = {db(s21)[i_mark]:.2f} dB")
print(T("  Z linea (dai parametri S):      {0:.1f} ohm   <- valore da usare",
        "  Line Z (from S-parameters):     {0:.1f} ohm   <- value to use").format(z_s[i_mark]))
if z_port is not None:
    print(T("  Z dalla porta (solo confronto): {0:.1f} ohm, tende a +20%",
            "  Z from port (comparison only):  {0:.1f} ohm, reads ~+20% high").format(abs(z_port[i_mark])))

np.savetxt(os.path.join(HERE, "results.csv"),
           np.column_stack([f / 1e9, db(s11), db(s21), np.abs(zline)]),
           delimiter=";", header="f_GHz;S11_dB;S21_dB;Zlinea_ohm", comments="")

import matplotlib

matplotlib.use("Agg")  # solo salvataggio su file, nessuna finestra
import matplotlib.pyplot as plt

fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(8, 7), sharex=True)
ax1.plot(f / 1e9, db(s11), label=T("S11 (riflessione)", "S11 (reflection)"))
ax1.plot(f / 1e9, db(s21), label=T("S21 (trasmissione)", "S21 (transmission)"))
ax1.axvline(f[i_mark] / 1e9, color="gray", ls="--")
ax1.set_ylabel("dB")
ax1.grid(True)
ax1.legend()
ax1.set_title(T("Linea", "Line") + f" {M['net']} ({M['layer']}) - openEMS")
if z_port is not None:
    ax2.plot(f / 1e9, np.abs(z_port), color="tab:gray", ls=":", label=T("dalla porta (solo confronto, ~+20%)", "from port (comparison only, ~+20%)"))
ax2.plot(f / 1e9, z_s, color="tab:red", label=T("dai parametri S (valore da usare)", "from S-parameters (value to use)"))
ax2.legend()
ax2.axvline(f[i_mark] / 1e9, color="gray", ls="--")
ax2.set_ylabel(T("Impedenza linea (ohm)", "Line impedance (ohm)"))
ax2.set_xlabel(T("Frequenza (GHz)", "Frequency (GHz)"))
ax2.set_ylim(0, 200)
ax2.grid(True)
fig.tight_layout()
png_path = os.path.join(HERE, "results.png")
fig.savefig(png_path, dpi=120)
# Invece di plt.show() (che con alcune installazioni non apre nessuna
# finestra) si apre l'immagine salvata con il visualizzatore di Windows
if hasattr(os, "startfile"):
    os.startfile(png_path)



def _read_td_dump(path):
    """
    Legge un file di campo openEMS (HDF5, dominio del tempo). Ritorna
    (lista di matrici 2D del campo per ogni istante, assi del piano, tempi).
    Le matrici hanno 3 componenti (Ex, Ey, Ez) nell'ultima dimensione.
    """
    import h5py

    with h5py.File(path, "r") as f:
        mesh = [np.array(f["Mesh"][k]) for k in ("x", "y", "z")]
        td = f["FieldData"]["TD"]
        keys = sorted(td.keys(), key=lambda k: int("".join(c for c in k if c.isdigit()) or 0))
        frames, times = [], []
        for k in keys:
            a = np.array(td[k])
            # La dimensione da 3 sono le componenti: la si porta in fondo
            ax3 = [i for i, n in enumerate(a.shape) if n == 3]
            a = np.moveaxis(a, ax3[0], -1) if ax3 else a
            frames.append(np.squeeze(a))
            times.append(float(td[k].attrs.get("time", len(times))))
    return frames, mesh, times


def _draw_geometry(ax, plane, scale_unused=None):
    """
    Disegna sopra l'animazione il rame reale (coordinate in mm):
    - vista dall'alto: contorno nero della traccia (larghezza reale) e
      massa coplanare in grigio chiaro;
    - sezione: piano di massa, bordo del dielettrico, traccia e massa
      laterale tagliati dal piano di sezione.
    """
    from matplotlib.patches import Polygon, Rectangle

    if plane == "alto":
        for gx0, gy0, gx1, gy1 in M["ground"]:
            ax.add_patch(Rectangle((gx0, gy0), gx1 - gx0, gy1 - gy0,
                                   facecolor="0.6", edgecolor="none", alpha=0.35))
        for x0, y0, x1, y1, w in M["segments"]:
            dx, dy = x1 - x0, y1 - y0
            L = (dx * dx + dy * dy) ** 0.5 or 1e-9
            nx, ny = -dy / L * w / 2, dx / L * w / 2
            ax.add_patch(Polygon([(x0 + nx, y0 + ny), (x1 + nx, y1 + ny),
                                  (x1 - nx, y1 - ny), (x0 - nx, y0 - ny)],
                                 closed=True, fill=False, edgecolor="black", linewidth=1.2))
        return

    # Sezione: asse orizzontale = traverso alla linea, verticale = z
    across_len = sy if section_axis == "x" else sx
    # Piano di massa: barra grigia sotto z = 0, stesso colore delle masse
    # laterali (prima era una riga sul bordo dell'asse e non si vedeva)
    t_plane = max(h * 0.04, 0.02)
    ax.add_patch(Rectangle((0, -t_plane), across_len, t_plane, facecolor="0.55", edgecolor="none"))
    ax.text(0.05, -t_plane / 2, T("piano di massa", "ground plane"), color="white", fontsize=8, va="center")
    ax.plot([0, across_len], [h, h], color="0.4", linewidth=0.8, ls="--")  # superficie del dielettrico
    for x0, y0, x1, y1, w in M["segments"]:
        # tratti attraversati dal piano di sezione
        if section_axis == "x" and min(x0, x1) <= section_pos <= max(x0, x1) and abs(y1 - y0) < 1e-6:
            c = y0
        elif section_axis == "y" and min(y0, y1) <= section_pos <= max(y0, y1) and abs(x1 - x0) < 1e-6:
            c = x0
        else:
            continue
        ax.add_patch(Rectangle((c - w / 2, h), w, max(h * 0.04, 0.02),
                               facecolor="goldenrod", edgecolor="black", linewidth=1))
    for gx0, gy0, gx1, gy1 in M["ground"]:
        if section_axis == "x" and gx0 <= section_pos <= gx1:
            a0, a1 = gy0, gy1
        elif section_axis == "y" and gy0 <= section_pos <= gy1:
            a0, a1 = gx0, gx1
        else:
            continue
        ax.add_patch(Rectangle((a0, h), a1 - a0, max(h * 0.04, 0.02),
                               facecolor="0.55", edgecolor="none"))


# --- Tensione del segnale ---
# La simulazione e' lineare: il campo e' proporzionale alla tensione. Si
# simula con l'eccitazione di openEMS e poi si riscala tutto in modo che la
# tensione di picco sulla linea sia quella voluta. Si puo' cambiare senza
# rifare la simulazione:  python simulate.py --results --voltage 5
def _arg_value(name, default):
    """Valore numerico dopo un'opzione della riga di comando (es. --voltage 5)."""
    if name in sys.argv:
        try:
            return float(sys.argv[sys.argv.index(name) + 1].replace(",", "."))
        except (IndexError, ValueError):
            pass
    return default


V_SIG = _arg_value("--voltage", float(M.get("v_signal", 1.0)))
# Scala fissa dei colori in V/mm (0 = automatica): serve per confrontare a
# colpo d'occhio GIF fatte con tensioni diverse
E_SCALE = _arg_value("--scale", 0.0)
EPS0 = 8.854e-12


def _section_axes(mesh):
    """Assi della sezione in mm: (posizione trasversale, z)."""
    xa = mesh[1] if section_axis == "x" else mesh[0]
    ya = mesh[2]
    scale = 1e3 if max(abs(xa).max(), abs(ya).max()) < 1 else 1.0
    return xa * scale, ya * scale


def _trace_center_across():
    """Posizione trasversale (mm) del centro della traccia tagliata dalla sezione."""
    for x0, y0, x1, y1, _w in M["segments"]:
        if section_axis == "x" and min(x0, x1) <= section_pos <= max(x0, x1):
            return (y0 + y1) / 2
        if section_axis == "y" and min(y0, y1) <= section_pos <= max(y0, y1):
            return (x0 + x1) / 2
    return None


# Integrale col metodo dei trapezi (np.trapz e' stato rinominato in numpy 2)
_trapz = getattr(np, "trapezoid", None) or np.trapz


def _calibration(path):
    """
    Fattore che porta i campi della simulazione a quelli reali con la
    tensione V_SIG. La tensione sulla linea si ricava dal campo stesso:
    integrale di Ez lungo z, sotto il centro della traccia, dal piano (z=0)
    alla traccia (z=h). Il picco nel tempo e' la tensione dell'impulso.
    Cosi' il risultato e' in V/m qualunque sia l'unita' interna del file.
    Ritorna (fattore, tensione simulata in unita' del file).
    """
    frames, mesh, _times = _read_td_dump(path)
    xa, ya = _section_axes(mesh)
    c = _trace_center_across()
    if not frames or c is None:
        return None, None
    j = int(np.argmin(np.abs(xa - c)))  # colonna sotto il centro traccia
    rows = (ya >= 0) & (ya <= h)
    v_t = []
    for fr in frames:
        ez = fr[..., 2]
        if ez.shape == (len(xa), len(ya)):
            ez = ez.T
        v_t.append(abs(_trapz(ez[rows, j], ya[rows] * 1e-3)))
    v_sim = max(v_t)
    if v_sim <= 0:
        return None, None
    return V_SIG / v_sim, v_sim


def _make_gif(path, out_path, title, mode, k):
    """
    GIF animata del campo con il rame reale disegnato sopra.
    mode: "alto" = Ez vista dall'alto (V/mm, rosso/blu = verso),
          "campo" = |E| nella sezione (V/mm),
          "energia" = densita' di energia nella sezione (J/m^3).
    k: fattore di calibrazione (vedi _calibration); None = unita' relative.
    Si tengono solo i fotogrammi in cui c'e' campo apprezzabile.
    """
    import matplotlib.animation as anim
    from matplotlib.colors import PowerNorm, Normalize

    frames, mesh, times = _read_td_dump(path)
    if not frames:
        print(T("Nessun dato di campo in", "No field data in"), path)
        return
    kk = k if k else 1.0
    if mode == "alto":
        xa, ya = mesh[0], mesh[1]
        scale = 1e3 if max(abs(xa).max(), abs(ya).max()) < 1 else 1.0
        xa, ya = xa * scale, ya * scale
        lab = (T("x lungo la scheda (mm)", "x along the board (mm)"), "y (mm)")
    else:
        xa, ya = _section_axes(mesh)
        lab = (T("posizione trasversale (mm)", "transverse position (mm)"), T("z altezza (mm)", "z height (mm)"))
    # Costante dielettrica per riga (FR4 fra 0 e h, aria altrove)
    eps_rows = np.where((ya >= 0) & (ya <= h), er, 1.0)

    def value(fr):
        if mode == "alto":
            v = fr[..., 2] * kk / 1e3  # Ez con segno, V/m -> V/mm
        else:
            v = np.sqrt((fr ** 2).sum(axis=-1)) * kk  # |E| in V/m
        if v.shape == (len(xa), len(ya)):
            v = v.T  # -> righe = secondo asse, colonne = primo asse
        if mode == "campo":
            v = v / 1e3  # V/mm
        elif mode == "energia":
            # Densita' di energia elettrica 1/2*eps0*eps_r*|E|^2 (J/m^3):
            # mostra dove sta davvero il segnale (nel dielettrico |E| e'
            # ridotto di eps_r, l'energia no)
            v = 0.5 * EPS0 * eps_rows[:, None] * v ** 2
        return v

    vals = [value(fr) for fr in frames]
    peak = [float(np.abs(v).max()) for v in vals]
    gmax = max(peak) or 1.0
    # Solo i fotogrammi "vivi": dal primo all'ultimo sopra il 3% del massimo
    alive = [i for i, p in enumerate(peak) if p > 0.03 * gmax]
    if alive:
        i0, i1 = max(alive[0] - 1, 0), min(alive[-1] + 2, len(vals))
        vals, times = vals[i0:i1], times[i0:i1]

    # Fotogramma di picco: quello con piu' campo (l'impulso attraversa il piano)
    i_peak = int(np.argmax([float((v ** 2).sum()) for v in vals]))
    # Zona inquadrata (sezione): dal piano a 1 mm sopra la traccia
    if mode != "alto":
        xc = (xa.min() + xa.max()) / 2
        half = min((xa.max() - xa.min()) / 2, max(2.0, 2.5 * h))
        view = np.ix_(ya <= h + 1.0, (xa >= xc - half) & (xa <= xc + half))
    else:
        view = (slice(None), slice(None))
    sel = np.abs(vals[i_peak][view])
    # Scala dei colori: 99% del fotogramma di picco nella zona inquadrata
    # (i punti caldissimi sugli spigoli del rame non la decidono), oppure
    # quella fissa chiesta con --scale (in V/mm; per l'energia si converte)
    vmax = float(np.percentile(sel, 99.0)) or float(sel.max()) or 1.0
    if E_SCALE > 0 and k:
        if mode == "energia":
            vmax = 0.5 * EPS0 * er * (E_SCALE * 1e3) ** 2
        else:
            vmax = E_SCALE
    # Campo massimo nel fotogramma di picco (99%: esclude gli spigoli)
    e_info = ""
    if k and mode != "energia":
        e_info = f"  |  E max ~ {np.percentile(sel, 99.0):.0f} V/mm " + T("(aria cede a ~3000)", "(air breaks down at ~3000)")

    fig, ax = plt.subplots(figsize=(12, 5) if mode == "alto" else (10, 5))
    if mode == "alto":
        cmap, norm = "RdBu_r", Normalize(-vmax, vmax)
    else:
        # Scala "radice": il campo forte sui bordi dei gap non schiaccia a
        # nero quello piu' debole sotto la traccia
        cmap, norm = "inferno", PowerNorm(gamma=0.5, vmin=0, vmax=vmax)

    # La mesh di openEMS NON e' uniforme: pcolormesh usa le coordinate vere
    # di ogni cella (imshow le metterebbe a passo costante, deformando)
    def edges(c):
        mid = (c[1:] + c[:-1]) / 2  # bordi delle celle = punti medi fra i nodi
        return np.concatenate(([c[0]], mid, [c[-1]]))
    im = ax.pcolormesh(edges(xa), edges(ya), vals[0], cmap=cmap, norm=norm, shading="flat")
    _draw_geometry(ax, "alto" if mode == "alto" else "sezione")
    if mode == "alto":
        ax.set_xlim(xa.min(), xa.max())
        ax.set_ylim(ya.min(), ya.max())
    else:
        ax.set_xlim(xc - half, xc + half)
        ax.set_ylim(-max(h * 0.08, 0.05), min(ya.max(), h + 1.0))  # spazio per il piano
    ax.set_aspect("equal")  # proporzioni reali 1:1
    ax.set_xlabel(lab[0])
    ax.set_ylabel(lab[1])
    unit = {"alto": T("Ez (V/mm, rosso/blu = verso)", "Ez (V/mm, red/blue = direction)"),
            "campo": T("|E| (V/mm, scala radice)", "|E| (V/mm, sqrt scale)"),
            "energia": T("energia (J/m^3, scala radice)", "energy (J/m^3, sqrt scale)")}[mode]
    if not k:
        unit = unit.split(" (")[0] + T(" (unita' relative)", " (relative units)")
    fig.colorbar(im, ax=ax, label=unit)
    head = f"{title}  -  " + T("segnale", "signal") + f" {V_SIG:g} V" if k else title
    ttl = ax.set_title(head)
    fig.tight_layout()

    def update(i):
        im.set_array(vals[i].ravel())  # pcolormesh: dati appiattiti
        ttl.set_text(f"{head}  -  t = {times[i] * 1e9:.2f} ns" + (e_info if i == i_peak else ""))
        return im, ttl

    # Immagine fissa del fotogramma di picco, accanto alla GIF
    update(i_peak)
    png_peak = os.path.splitext(out_path)[0] + "_peak.png"
    fig.savefig(png_peak, dpi=110)
    print(T("Creata", "Created") + f" {png_peak} (t = {times[i_peak] * 1e9:.2f} ns){e_info}")

    ani = anim.FuncAnimation(fig, update, frames=len(vals), interval=120, blit=False)
    ani.save(out_path, writer=anim.PillowWriter(fps=8))
    plt.close(fig)
    print(T("Creata {0} ({1} fotogrammi)", "Created {0} ({1} frames)").format(out_path, len(vals)))


# --- TDR / TDT: gradino con il tempo di salita scelto ---
# Calcolati dai parametri S della simulazione (vedi tdr_core.py, copiato
# accanto a questo script). Il tempo di salita si puo' cambiare senza
# risimulare:  python simulate.py --results --rise 0.5   (in ns)
T_RISE = _arg_value("--rise", float(M.get("t_rise_ns", 1.0))) * 1e-9


def _tdr_plot():
    sys.path.insert(0, HERE)
    import tdr_core

    def s_of_f(fr):
        # Parametri S dalla simulazione sulle frequenze richieste
        for p in ports:
            p.CalcPort(SIM_PATH, fr, ref_impedance=50)
        return (ports[0].uf_ref / ports[0].uf_inc, ports[1].uf_ref / ports[0].uf_inc)

    r = tdr_core.step_responses(s_of_f, f_max, T_RISE)
    t_ns = (r["t"] - r["t0"]) * 1e9  # tempo dal centro del fronte in ingresso
    m_out = tdr_core.edge_metrics(r["t"], r["v_out"])
    m_in = tdr_core.edge_metrics(r["t"], r["v_in"])
    tr_used = r["t_rise_used"] * 1e9
    if r["clamped"]:
        print(T("\nATTENZIONE: con f max = {0:g} GHz il fronte piu' ripido rappresentabile e' {1:.2f} ns "
                "(chiesto {2:g} ns). Per {2:g} ns serve f max >= {3:.1f} GHz.",
                "\nWARNING: with f max = {0:g} GHz the fastest edge that can be represented is {1:.2f} ns "
                "(requested {2:g} ns). For {2:g} ns you need f max >= {3:.1f} GHz.").format(
                    f_max / 1e9, tr_used, T_RISE * 1e9, 1.22 / T_RISE / 1e9))
    delay = (m_out[0] - m_in[0]) * 1e9 if (m_out and m_in) else None
    # Finestra da mostrare: fino a qualche volta il doppio del ritardo
    t_end = max(2 * (delay or 1.0) + 6 * tr_used, 3.0)
    keep = (t_ns >= -2 * tr_used) & (t_ns <= t_end)

    fig, (a1, a2) = plt.subplots(2, 1, figsize=(8, 7), sharex=True)
    # TDR: impedenza vista dall'ingresso nel tempo (andata e ritorno)
    a1.plot(t_ns[keep], r["z"][keep], color="tab:red")
    a1.axhspan(45, 55, color="green", alpha=0.12, label="50 ohm +/-10%")
    if delay:
        a1.axvline(2 * delay, color="gray", ls="--", label=T("fine linea (andata e ritorno)", "line end (round trip)"))
    a1.set_ylabel(T("Impedenza vista (ohm)", "Seen impedance (ohm)"))
    zk = r["z"][keep]
    a1.set_ylim(min(30, zk.min() - 5), max(70, zk.max() + 5))
    a1.grid(True)
    a1.legend(loc="upper right")
    a1.set_title(f"TDR / TDT - " + T("fronte", "edge") + f" {tr_used:.2f} ns (10-90%), "
                 + T("segnale", "signal") + f" {V_SIG:g} V")
    # TDT: gradino in ingresso e in uscita, in volt
    a2.plot(t_ns[keep], V_SIG * r["v_in"][keep], color="tab:blue", label=T("ingresso", "input"))
    a2.plot(t_ns[keep], V_SIG * r["v_out"][keep], color="tab:orange", label=T("uscita", "output"))
    if m_out:
        a2.text(0.02, 0.95,
                T("ritardo", "delay") + f" {delay:.3f} ns   "
                + T("salita in uscita", "output rise") + f" {m_out[1]*1e9:.3f} ns   "
                f"overshoot {m_out[2]:.1f}%",
                transform=a2.transAxes, va="top", fontsize=9,
                bbox=dict(facecolor="white", alpha=0.8, edgecolor="none"))
    a2.set_ylabel(T("Tensione (V)", "Voltage (V)"))
    a2.set_xlabel(T("Tempo (ns)", "Time (ns)"))
    a2.grid(True)
    a2.legend(loc="lower right")
    fig.tight_layout()
    out = os.path.join(HERE, "tdr_" + f"{tr_used:.2f}".replace(".", "p") + "ns.png")
    fig.savefig(out, dpi=120)
    plt.close(fig)
    np.savetxt(os.path.join(HERE, "tdr.csv"),
               np.column_stack([t_ns[keep], r["z"][keep], V_SIG * r["v_in"][keep], V_SIG * r["v_out"][keep]]),
               delimiter=";", header="t_ns;Z_ohm;Vin_V;Vout_V", comments="")
    print(T("\nTDR/TDT (fronte {0:.2f} ns): Z vista min {1:.1f} / max {2:.1f} ohm",
            "\nTDR/TDT ({0:.2f} ns edge): seen Z min {1:.1f} / max {2:.1f} ohm").format(tr_used, zk.min(), zk.max())
          + (T(", ritardo {0:.3f} ns, overshoot {1:.1f}%", ", delay {0:.3f} ns, overshoot {1:.1f}%").format(delay, m_out[2])
             if m_out and delay else ""))
    print(T("Creata", "Created"), out)
    if hasattr(os, "startfile"):
        os.startfile(out)
    # Ripristina i parametri S sulla griglia dei grafici (non si sa mai)
    for p in ports:
        p.CalcPort(SIM_PATH, f, ref_impedance=50)


try:
    _tdr_plot()
except Exception as exc:
    import traceback

    traceback.print_exc()
    print(T("TDR non calcolato:", "TDR not computed:"), exc)


if M.get("dump_fields"):
    try:
        print(T("\nCreo le GIF dei campi (puo' richiedere un minuto)...", "\nCreating the field GIFs (it may take a minute)..."))
        sez_path = os.path.join(SIM_PATH, "field_section.h5")
        k_cal, v_sim = _calibration(sez_path)
        if k_cal:
            print(T("Tensione del segnale: {0:g} V di picco sulla linea (campi riscalati x{1:.3g} rispetto alla simulazione)",
                    "Signal voltage: {0:g} V peak on the line (fields scaled x{1:.3g} from the simulation)").format(V_SIG, k_cal))
        else:
            print(T("Calibrazione non riuscita: campi in unita' relative.", "Calibration failed: fields in relative units."))
        sfx = f"_{V_SIG:g}V".replace(".", "p")  # nome file con la tensione
        _make_gif(os.path.join(SIM_PATH, "field_top.h5"),
                  os.path.join(HERE, f"field_top_view{sfx}.gif"),
                  T("Campo Ez sotto la traccia", "Ez field under the track"), "alto", k_cal)
        _make_gif(sez_path, os.path.join(HERE, f"field_section{sfx}.gif"),
                  T("Campo |E| nella sezione", "|E| field in the cross-section"), "campo", k_cal)
        _make_gif(sez_path, os.path.join(HERE, f"energy_section{sfx}.gif"),
                  T("Energia nella sezione", "Energy in the cross-section"), "energia", k_cal)
        if hasattr(os, "startfile"):
            os.startfile(os.path.join(HERE, f"field_top_view{sfx}.gif"))
            os.startfile(os.path.join(HERE, f"field_section{sfx}_peak.png"))
    except Exception as exc:
        import traceback

        traceback.print_exc()
        print(T("GIF dei campi non create:", "Field GIFs not created:"), exc)

print(T("\nRisultati salvati in results.png e results.csv in:", "\nResults saved in results.png and results.csv in:"), HERE)
print(T("Per rifare GIF e TDR con altri valori senza simulare: pulsante 'Rielabora' nella scheda openEMS",
        "To redo GIFs and TDR with other values without simulating: 'Reprocess' button in the openEMS tab"))
input(T("Premi Invio per chiudere...", "Press Enter to close..."))
