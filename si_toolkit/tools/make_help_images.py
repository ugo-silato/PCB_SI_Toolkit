# -*- coding: utf-8 -*-
"""
Generates the images of the "Help" tab (one per plugin tab, in Italian and
English) in the gui/img folder.

Not needed by KiCad: the images are already included in the plugin. Run it
again only to change the drawings:  python make_help_images.py
(requires matplotlib).
"""
import os

import matplotlib

matplotlib.use("Agg")  # files only, no window
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, FancyArrowPatch, Polygon, Rectangle

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui", "img")

# Common colors: copper, board, ground, dielectric, solder mask, dimensions
COPPER = "#d9902f"
BOARD = "#2f7d4f"
GND = "#9aa3ad"
DIEL = "#cfe3c8"
MASK = "#3c9a5f"
DIM = "#c0392b"
TXT = "#222222"

# Texts of the drawings: (Italian, English)
L = {
    "plane": ("piano di massa (layer sotto)", "ground plane (layer below)"),
    "slot": ("interruzione del piano", "plane gap"),
    "track": ("traccia di segnale", "signal track"),
    "mingap": ("Gap minimo", "Minimum gap"),
    "via": ("via di stitching", "stitching via"),
    "marker": ("cerchio disegnato sulla board:\nlayer User.1 = grave (nessuna via vicina)\nlayer User.2 = c'e' una via vicina",
               "circle drawn on the board:\nlayer User.1 = severe (no via nearby)\nlayer User.2 = a via is nearby"),
    "rp_title": ("Return Path: il ritorno di corrente scorre sul piano sotto la traccia",
                 "Return Path: the return current flows in the plane under the track"),
    "in": ("Ingresso (pad)", "Input (pad)"),
    "out": ("Uscita", "Output"),
    "dc_title": ("Corrente DC: ingresso, uscite con la loro corrente, tracce e via",
                 "DC current: input, outputs with their current, tracks and vias"),
    "width": ("larghezza traccia", "track width"),
    "copper": ("rame (spessore da stackup)", "copper (thickness from stackup)"),
    "plating": ("placcatura via", "via plating"),
    "imp_title": ("Impedenza: sezione della traccia (microstrip coplanare)",
                  "Impedance: track cross-section (coplanar microstrip)"),
    "diel": ("dielettrico (Er)", "dielectric (Er)"),
    "mask": ("solder mask", "solder mask"),
    "gap": ("Gap massa", "Ground gap"),
    "side_gnd": ("massa laterale", "side ground"),
    "h": ("Dielettrico H", "Dielectric H"),
    "w": ("W", "W"),
    "diff_title": ("Coppie diff.: sezione della coppia P/N", "Diff. pairs: P/N pair cross-section"),
    "spacing": ("Spaz. S", "Spacing S"),
    "xt_title": ("Crosstalk: tratto parallelo fra due net (aggressore -> vittima)",
                 "Crosstalk: parallel run between two nets (aggressor -> victim)"),
    "aggr": ("net A (aggressore)", "net A (aggressor)"),
    "vict": ("net B (vittima)", "net B (victim)"),
    "plen": ("Tratto parallelo (>= Tratto minimo)", "Parallel run (>= Minimum run)"),
    "sp": ("Spazio (<= Spazio max)", "Spacing (<= Max spacing)"),
    "rise": ("fronte: tempo di salita", "edge: rise time"),
    "oe_title": ("openEMS: linea selezionata, porte alle estremita', volume simulato",
                 "openEMS: selected line, ports at the ends, simulated volume"),
    "port1": ("porta 1 (eccitazione)", "port 1 (excitation)"),
    "port2": ("porta 2 (carico 50 ohm)", "port 2 (50 ohm load)"),
    "margin": ("Margine", "Margin"),
    "box": ("volume simulato (mesh)", "simulated volume (mesh)"),
    "sel": ("tracce selezionate (una sola linea, layer esterno)", "selected tracks (one line, outer layer)"),
    "lc_title": ("Controlli layout: misure sulla scheda confrontate con le soglie",
                 "Layout checks: board measures compared with the thresholds"),
    "ic": ("integrato", "IC"),
    "vcc_pin": ("pin di\nalimentazione", "supply\npin"),
    "cap": ("condensatore", "capacitor"),
    "d_cap": ("distanza\npin - condensatore", "distance\npin - capacitor"),
    "gnd_via": ("via di massa\ndel pad GND", "ground via\nof the GND pad"),
    "sig_via": ("via di segnale\n(cambio layer)", "signal via\n(layer change)"),
    "ret_via": ("via di ritorno", "return via"),
    "bottom": ("traccia sul layer sotto", "track on the layer below"),
    "stitch": ("passo via di stitching", "stitching via spacing"),
    # --- Layout checks 5-8 ---
    "pe_title": ("Bordo del piano: sezione della scheda vicino al bordo",
                 "Plane edge: cross-section of the board near the edge"),
    "pe_track": ("traccia (F.Cu)", "track (F.Cu)"),
    "pe_plane": ("rame GND sul layer sotto (B.Cu)", "GND copper on the layer below (B.Cu)"),
    "pe_edge": ("bordo\nscheda", "board\nedge"),
    "pe_clear": ("distanza\nrame-bordo", "copper-to-edge\nclearance"),
    "pe_field": ("campo della traccia: si allarga\ndi qualche h ai lati",
                 "field of the track: it spreads\na few h to the sides"),
    "pe_meas": ("Misura", "Measured"),
    "pe_limit": ("Limite = 3 x h", "Limit = 3 x h"),
    "pe_err": ("errore\n(< 1 h)", "error\n(< 1 h)"),
    "pe_warn": ("attenzione\n(1 - 3 h)", "warning\n(1 - 3 h)"),
    "pe_ok": ("OK (> 3 h)", "OK (> 3 h)"),
    "pe_note": ("Misura = dal bordo della traccia al punto dove finisce il rame GND (visto dall'alto)",
                "Measured = from the edge of the track to where the GND copper ends (seen from above)"),
    "tw_title": ("Larghezza tracce: larghezza rispetto alla corrente (IPC-2221)",
                 "Track width: width against the current (IPC-2221)"),
    "tw_cur": ("corrente della net\n(campo Correnti, es. +5V=2)", "current of the net\n(Currents field, e.g. +5V=2)"),
    "tw_have": ("Misura = larghezza attuale", "Measured = actual width"),
    "tw_need": ("Limite = larghezza necessaria\nper il riscaldamento massimo", "Limit = width needed\nfor the maximum rise"),
    "tw_note": ("piu' stretta = si scalda di piu': la riga dice il riscaldamento stimato (C)",
                "narrower = hotter: the row gives the estimated temperature rise (C)"),
    "iso_title": ("Isolamento: distanza fra net a tensioni diverse (oltre 30 V)",
                  "Isolation: distance between nets at different voltages (above 30 V)"),
    "iso_hv": ("net HV_400V (400 V)", "net HV_400V (400 V)"),
    "iso_gnd": ("net GND (0 V)", "net GND (0 V)"),
    "iso_meas": ("Misura = distanza\nbordo-bordo, stesso layer", "Measured = edge-to-edge\ndistance, same layer"),
    "iso_tab": ("Limite (IPC-2221)       esterno B2   interno B1\n"
                "fino a 100 V              0,6 mm        0,1 mm\n"
                "fino a 300 V              1,25 mm       0,2 mm\n"
                "fino a 500 V              2,5 mm        0,25 mm\n"
                "oltre 500 V               0,005 mm/V    0,0025 mm/V",
                "Limit (IPC-2221)       outer B2    inner B1\n"
                "up to 100 V              0.6 mm       0.1 mm\n"
                "up to 300 V              1.25 mm      0.2 mm\n"
                "up to 500 V              2.5 mm       0.25 mm\n"
                "above 500 V              0.005 mm/V   0.0025 mm/V"),
    "iso_volt": ("tensione: dal campo Tensioni o dal nome\ndella net (+5V, 24V_IN); masse = 0 V",
                 "voltage: from the Voltages field or the\nnet name (+5V, 24V_IN); grounds = 0 V"),
    "len_title": ("Lunghezze: coppie differenziali e gruppi di net",
                  "Lengths: differential pairs and groups of nets"),
    "len_pair": ("coppia USB_DP / USB_DM\n(riconosciuta dai nomi)", "pair USB_DP / USB_DM\n(recognized from the names)"),
    "len_pmeas": ("Misura = L(DM) - L(DP)\nLimite = skew massimo", "Measured = L(DM) - L(DP)\nLimit = maximum skew"),
    "len_group": ("gruppo \"SD_*\" (campo Gruppi di lunghezza)", "group \"SD_*\" (Length groups field)"),
    "len_gmeas": ("Misura = la piu' lunga - questa\nLimite = differenza massima", "Measured = the longest - this one\nLimit = maximum difference"),
    "len_longest": ("la piu' lunga", "the longest"),
    # --- Layout checks 9-16 ---
    "stub_title": ("Rami morti: tracce che finiscono senza collegarsi", "Dead branches: tracks ending without a connection"),
    "stub_free": ("estremita' libera", "free end"),
    "stub_meas": ("Misura = lunghezza del ramo morto\nLimite = Rami morti da (mm)",
                  "Measured = length of the dead branch\nLimit = Dead branches from (mm)"),
    "stub_why": ("fa da antenna e, su una linea veloce, riflette il segnale",
                 "it acts as an antenna and, on a fast line, reflects the signal"),
    "ac_title": ("Angoli acuti: due tratti che si incontrano a meno di 90 gradi",
                 "Acute angles: two segments meeting at less than 90 degrees"),
    "ac_bad": ("angolo acuto: nella punta\nl'acido di incisione ristagna", "acute angle: the etching\nliquid stays in the tip"),
    "ac_good": ("OK: due tratti a 45 gradi\n(angoli di 135 gradi)", "OK: two 45 degree segments\n(135 degree angles)"),
    "ac_meas": ("Misura = angolo, Limite = Angoli acuti sotto (gradi)", "Measured = angle, Limit = Acute angles below (degrees)"),
    "ws_title": ("Cambi di larghezza: la stessa net con tracce di larghezza diversa",
                 "Width steps: the same net with tracks of different widths"),
    "ws_wide": ("larga", "wide"),
    "ws_narrow": ("stretta", "narrow"),
    "ws_step": ("salto di impedenza", "impedance step"),
    "ws_neck": ("strozzatura vicino al pad\n(fino a 1 mm): ignorata", "neck-down at the pad\n(up to 1 mm): ignored"),
    "ws_meas": ("Misura = (larga - stretta) / stretta in %\nLimite = Cambio di larghezza oltre (%)",
                "Measured = (wide - narrow) / narrow in %\nLimit = Width step above (%)"),
    "vip_title": ("Via nei pad: il foro di una via dentro un pad SMD", "Vias in pads: the drill of a via inside an SMD pad"),
    "vip_bad": ("segnalato: in saldatura\nlo stagno scende nel foro", "reported: in reflow the\nsolder flows into the hole"),
    "vip_good": ("OK: via fuori dal pad", "OK: via outside the pad"),
    "vip_ep": ("pad termico grande\n(> 1,5 mm): ignorato", "large thermal pad\n(> 1.5 mm): ignored"),
    "tb_title": ("Tombstoning: componente piccolo con i pad collegati in modo diverso",
                 "Tombstoning: small part with its pads connected differently"),
    "tb_zone": ("zona GND", "GND zone"),
    "tb_bad": ("segnalato: un pad annegato nella zona,\nl'altro su traccia: si scaldano diversi\ne il componente si alza",
               "reported: one pad flooded in the zone,\nthe other on a track: they heat up\ndifferently and the part stands up"),
    "tb_good": ("OK: scarico termico\nsul pad nella zona", "OK: thermal relief\non the pad in the zone"),
    "vc_title": ("Corrente via: quante via servono a un cambio di layer", "Via current: how many vias a layer change needs"),
    "vc_cur": ("net del campo Correnti\n(es. +5V=5)", "net of the Currents field\n(e.g. +5V=5)"),
    "vc_meas": ("Misura = via presenti (2)\nLimite = via necessarie (3)\nper il riscaldamento massimo",
                "Measured = vias present (2)\nLimit = vias needed (3)\nfor the maximum rise"),
    "vc_missing": ("manca", "missing"),
    "xt_title2": ("Quarzo: niente tracce sotto, e vicino all'integrato", "Crystal: no tracks under it, and close to the IC"),
    "xt_xtal": ("quarzo Y1", "crystal Y1"),
    "xt_ic": ("integrato", "IC"),
    "xt_under": ("traccia di un'altra net\nsotto il quarzo: errore", "track of another net\nunder the crystal: error"),
    "xt_meas": ("Misura = lunghezza delle tracce quarzo-integrato\nLimite = Tracce quarzo-integrato fino a (mm)",
                "Measured = length of the crystal-IC tracks\nLimit = Crystal-IC tracks up to (mm)"),
    "bs_title": ("Tracce sovrapposte: net diverse una sopra l'altra su layer adiacenti",
                 "Overlapping tracks: different nets one over the other on adjacent layers"),
    "bs_top": ("net A sul layer sopra (F.Cu)", "net A on the layer above (F.Cu)"),
    "bs_bot": ("net B sul layer sotto (B.Cu)", "net B on the layer below (B.Cu)"),
    "bs_meas": ("Misura = tratto in cui il rame si sovrappone\nLimite = Tracce sovrapposte da (mm)",
                "Measured = stretch where the copper overlaps\nLimit = Overlapping tracks from (mm)"),
    "bs_why": ("senza un piano in mezzo si accoppiano (crosstalk)", "with no plane between them they couple (crosstalk)"),
}


def t(key, lang):
    return L[key][0 if lang == "it" else 1]


def dim_arrow(ax, x0, y0, x1, y1, text, lang_text_pos=None, color=DIM, fs=9, offset=(0, 0)):
    """Dimension with a double arrow and text in the middle."""
    ax.add_patch(FancyArrowPatch((x0, y0), (x1, y1), arrowstyle="<->", mutation_scale=10,
                                 color=color, lw=1.3))
    xm, ym = (x0 + x1) / 2 + offset[0], (y0 + y1) / 2 + offset[1]
    ax.text(xm, ym, text, color=color, fontsize=fs, ha="center", va="center",
            bbox=dict(facecolor="white", edgecolor="none", pad=1, alpha=0.9))


def new_fig(title, w=7.2, h=3.2):
    fig, ax = plt.subplots(figsize=(w, h), dpi=100)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.set_title(title, fontsize=10, color=TXT)
    return fig, ax


def save(fig, name, lang):
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, f"{name}_{lang}.png"), facecolor="white")
    plt.close(fig)


def return_path(lang):
    fig, ax = new_fig(t("rp_title", lang))
    # Ground plane with a vertical slot
    ax.add_patch(Rectangle((0, 0), 4.2, 3, color=GND, alpha=0.55))
    ax.add_patch(Rectangle((5.0, 0), 5, 3, color=GND, alpha=0.55))
    ax.text(0.2, 0.2, t("plane", lang), fontsize=8, color=TXT)
    ax.text(4.6, 2.7, t("slot", lang), fontsize=8, color=TXT, ha="center")
    # Track crossing the slot
    ax.add_patch(Rectangle((0.3, 1.35), 9.4, 0.3, color=COPPER))
    ax.text(1.0, 1.85, t("track", lang), fontsize=8, color=TXT)
    dim_arrow(ax, 4.2, 0.7, 5.0, 0.7, t("mingap", lang), offset=(0, -0.35))
    # Marker on the gap and nearby stitching via
    ax.add_patch(Circle((4.6, 1.5), 0.45, fill=False, color="#e74c3c", lw=2))
    ax.text(5.2, 2.05, t("marker", lang), fontsize=7.5, color="#e74c3c", va="bottom")
    ax.add_patch(Circle((5.6, 0.85), 0.15, color="#555555"))
    ax.text(5.85, 0.75, t("via", lang), fontsize=8, color=TXT)
    ax.set_xlim(-0.2, 10.2)
    ax.set_ylim(-0.3, 3.2)
    save(fig, "return_path", lang)


def dc_current(lang):
    fig, ax = new_fig(t("dc_title", lang))
    ax.add_patch(Rectangle((0, 0), 10, 4, color=BOARD, alpha=0.18))
    # Path: input on the left, branch splitting into two outputs
    ax.add_patch(Rectangle((0.8, 1.85), 4.2, 0.3, color=COPPER))
    ax.add_patch(Polygon([(5.0, 1.85), (5.0, 2.15), (8.0, 3.15), (8.0, 2.85)], color=COPPER))
    ax.add_patch(Rectangle((5.0, 1.85), 3.0, 0.3, color=COPPER))
    ax.add_patch(Polygon([(5.0, 1.85), (5.0, 2.15), (8.0, 1.15), (8.0, 0.85)], color=COPPER, alpha=0.0))
    # Via halfway
    ax.add_patch(Circle((3.0, 2.0), 0.25, color="#555555"))
    ax.add_patch(Circle((3.0, 2.0), 0.12, color="white"))
    ax.annotate(t("plating", lang), (3.0, 2.25), (2.2, 3.3), fontsize=8,
                arrowprops=dict(arrowstyle="->", color=TXT))
    # Input and output pads
    ax.add_patch(Rectangle((0.3, 1.6), 0.6, 0.8, color=COPPER, ec="black"))
    ax.add_patch(Rectangle((8.0, 2.6), 0.6, 0.8, color=COPPER, ec="black"))
    ax.add_patch(Rectangle((8.0, 1.6), 0.6, 0.8, color=COPPER, ec="black"))
    ax.text(0.6, 1.2, t("in", lang) + "\n1.0 A", fontsize=8, ha="center", color="#1e8449")
    ax.text(9.3, 3.0, t("out", lang) + " 1\n0.6 A", fontsize=8, ha="center", color="#c0392b")
    ax.text(9.3, 2.0, t("out", lang) + " 2\n0.4 A", fontsize=8, ha="center", color="#c0392b")
    # Current arrows
    for x0, y0, x1, y1 in ((1.3, 2.45, 2.4, 2.45), (5.6, 2.6, 7.0, 3.05), (5.6, 2.45, 7.0, 2.45)):
        ax.annotate("", (x1, y1), (x0, y0), arrowprops=dict(arrowstyle="->", color="#1f618d", lw=1.5))
    dim_arrow(ax, 6.5, 1.85, 6.5, 2.15, "", fs=7)
    ax.text(6.65, 1.45, t("width", lang), fontsize=8, color=DIM)
    ax.text(0.3, 0.3, t("copper", lang), fontsize=8, color=TXT)
    ax.set_xlim(-0.2, 10.2)
    ax.set_ylim(0, 4)
    save(fig, "dc_current", lang)


def cross_section(ax, lang, traces, gap, show_mask=True):
    """Cross-section: plane, dielectric, tracks and side grounds. traces = [(x, w)]."""
    H, T = 1.6, 0.18
    ax.add_patch(Rectangle((0, -0.25), 10, 0.25, color=GND))                 # ground plane
    ax.add_patch(Rectangle((0, 0), 10, H, color=DIEL))                        # dielectric
    ax.text(0.15, 0.5, t("diel", lang), fontsize=8, color=TXT)
    ax.text(0.15, -0.6, t("plane", lang), fontsize=8, color=TXT)
    x_first, x_last = traces[0][0], traces[-1][0] + traces[-1][1]
    # Side grounds
    ax.add_patch(Rectangle((0, H), x_first - gap, T, color=GND))
    ax.add_patch(Rectangle((x_last + gap, H), 10 - x_last - gap, T, color=GND))
    ax.text(0.15, H + 0.35, t("side_gnd", lang), fontsize=8, color=TXT)
    for x, w in traces:
        ax.add_patch(Rectangle((x, H), w, T, color=COPPER))
    if show_mask:
        # Solder mask as a line over all the copper/dielectric
        ax.plot([0, 10], [H + T + 0.08, H + T + 0.08], color=MASK, lw=3, alpha=0.7)
        ax.text(10, H + T + 0.3, t("mask", lang), fontsize=8, color=MASK, ha="right")
    dim_arrow(ax, x_first - 0.15, 0, x_first - 0.15, H, t("h", lang), offset=(-0.9, 0))
    dim_arrow(ax, x_first - gap, H + 0.75, x_first, H + 0.75, t("gap", lang), offset=(0, 0.3))
    return H, T


def impedance(lang):
    fig, ax = new_fig(t("imp_title", lang))
    H, T = cross_section(ax, lang, [(4.0, 2.0)], 1.0)
    dim_arrow(ax, 4.0, H + 1.3, 6.0, H + 1.3, t("w", lang))
    ax.set_xlim(-0.2, 10.2)
    ax.set_ylim(-0.9, 3.6)
    save(fig, "impedance", lang)


def diff_pair(lang):
    fig, ax = new_fig(t("diff_title", lang))
    H, T = cross_section(ax, lang, [(2.9, 1.6), (5.5, 1.6)], 0.9)
    ax.text(3.7, H - 0.35, "P", fontsize=10, ha="center", color=TXT)
    ax.text(6.3, H - 0.35, "N", fontsize=10, ha="center", color=TXT)
    dim_arrow(ax, 2.9, H + 1.3, 4.5, H + 1.3, t("w", lang))
    dim_arrow(ax, 4.5, H + 0.75, 5.5, H + 0.75, t("spacing", lang), offset=(0, 0.3))
    ax.set_xlim(-0.2, 10.2)
    ax.set_ylim(-0.9, 3.6)
    save(fig, "diff_pair", lang)


def crosstalk(lang):
    fig, ax = new_fig(t("xt_title", lang))
    ax.add_patch(Rectangle((0, 0), 10, 4, color=BOARD, alpha=0.15))
    # Aggressor: goes straight; victim: approaches, runs parallel, moves away
    ax.add_patch(Rectangle((0.5, 2.4), 9, 0.25, color=COPPER))
    ax.plot([0.5, 2.2, 2.8, 7.2, 7.8, 9.5], [0.6, 0.6, 1.75, 1.75, 0.6, 0.6], color=COPPER, lw=7,
            solid_capstyle="butt")
    ax.text(0.5, 2.85, t("aggr", lang), fontsize=8, color=TXT)
    ax.text(0.5, 0.15, t("vict", lang), fontsize=8, color=TXT)
    dim_arrow(ax, 2.8, 3.3, 7.2, 3.3, t("plen", lang))
    dim_arrow(ax, 5.0, 1.85, 5.0, 2.4, "", fs=7)
    ax.text(5.2, 2.05, t("sp", lang), fontsize=8, color=DIM)
    # Small rising edge on the aggressor
    ax.plot([8.2, 8.5, 8.8, 9.3], [3.2, 3.2, 3.7, 3.7], color="#1f618d", lw=1.5)
    ax.text(8.75, 2.9, t("rise", lang), fontsize=7, color="#1f618d", ha="center")
    ax.set_xlim(-0.2, 10.2)
    ax.set_ylim(0, 4)
    save(fig, "crosstalk", lang)


def openems(lang):
    fig, ax = new_fig(t("oe_title", lang))
    # Simulated volume, dashed, with the mesh
    ax.add_patch(Rectangle((1.0, 0.5), 8.0, 3.0, fill=False, ls="--", color="#555555"))
    for x in [1.0 + i * 0.5 for i in range(17)]:
        ax.plot([x, x], [0.5, 3.5], color="#dddddd", lw=0.5, zorder=0)
    for y in [0.5 + i * 0.5 for i in range(7)]:
        ax.plot([1.0, 9.0], [y, y], color="#dddddd", lw=0.5, zorder=0)
    ax.text(1.05, 3.6, t("box", lang), fontsize=8, color="#555555")
    # Selected line with side grounds
    ax.add_patch(Rectangle((1.0, 1.85), 8.0, 0.3, color=COPPER))
    ax.add_patch(Rectangle((1.0, 1.0), 8.0, 0.55, color=GND, alpha=0.7))
    ax.add_patch(Rectangle((1.0, 2.45), 8.0, 0.55, color=GND, alpha=0.7))
    ax.text(5.0, 2.25, t("sel", lang), fontsize=8, ha="center", color=TXT)
    # Ports at the ends
    for x, key in ((1.6, "port1"), (8.4, "port2")):
        ax.add_patch(Rectangle((x - 0.15, 1.7), 0.3, 0.6, fill=False, color="#1f618d", lw=2))
        ax.text(x, 0.65, t(key, lang), fontsize=8, ha="center", color="#1f618d")
    dim_arrow(ax, 9.0, 3.0, 9.0, 3.5, "", fs=7)
    ax.text(9.15, 3.2, t("margin", lang), fontsize=8, color=DIM)
    ax.set_xlim(0.5, 10.5)
    ax.set_ylim(0.3, 3.9)
    save(fig, "openems", lang)


def layout_check(lang):
    fig, ax = new_fig(t("lc_title", lang), h=3.6)
    ax.add_patch(Rectangle((0, 0), 10, 4.4, color=BOARD, alpha=0.15))
    # Integrated circuit with its supply pin (left) and the capacitor
    ax.add_patch(Rectangle((0.6, 2.4), 1.6, 1.4, color="#333333"))
    ax.text(1.4, 3.1, t("ic", lang), fontsize=8, color="white", ha="center", va="center")
    ax.add_patch(Rectangle((2.2, 3.35), 0.35, 0.25, color=COPPER))
    ax.text(2.9, 3.0, t("vcc_pin", lang), fontsize=7, ha="center", va="center", color=TXT)
    ax.add_patch(Rectangle((3.6, 3.25), 0.35, 0.45, color=COPPER, ec="black", lw=0.5))
    ax.add_patch(Rectangle((3.6, 2.55), 0.35, 0.45, color=COPPER, ec="black", lw=0.5))
    ax.text(4.1, 3.0, t("cap", lang), fontsize=7, color=TXT, va="center")
    ax.plot([2.55, 3.6], [3.48, 3.48], color=COPPER, lw=3)
    dim_arrow(ax, 2.38, 3.9, 3.78, 3.9, "", fs=7)
    ax.text(3.1, 4.35, t("d_cap", lang), fontsize=7, color=DIM, ha="center", va="top")
    # Ground via of the capacitor GND pad
    ax.add_patch(Circle((3.78, 2.15), 0.13, color="#555555"))
    ax.annotate(t("gnd_via", lang), (3.78, 2.05), (2.3, 1.3), fontsize=7, ha="center",
                arrowprops=dict(arrowstyle="->", color=TXT))
    # Signal changing layer: top track, via, bottom track (dashed) and return via
    ax.plot([5.2, 6.8], [2.6, 2.6], color=COPPER, lw=3)
    ax.plot([6.8, 8.6], [2.6, 2.6], color="#b06f25", lw=3, ls="--")
    ax.add_patch(Circle((6.8, 2.6), 0.16, color=COPPER, ec="black", lw=0.6))
    ax.add_patch(Circle((6.8, 2.05), 0.13, color="#555555"))
    ax.text(6.8, 3.0, t("sig_via", lang), fontsize=7, ha="center", color=TXT)
    ax.annotate(t("ret_via", lang), (6.9, 2.0), (8.4, 1.75), fontsize=7, ha="left", va="center",
                arrowprops=dict(arrowstyle="->", color=TXT))
    ax.text(7.7, 2.3, t("bottom", lang), fontsize=6.5, ha="center", color="#7a4a12")
    # Grid of stitching vias along the bottom, with the spacing
    for x in (4.6, 6.0, 7.4, 8.8):
        ax.add_patch(Circle((x, 0.6), 0.12, color="#555555"))
    dim_arrow(ax, 6.0, 0.95, 7.4, 0.95, "", fs=7)
    ax.text(6.7, 1.15, t("stitch", lang), fontsize=7, color=DIM, ha="center")
    ax.set_xlim(-0.2, 10.2)
    ax.set_ylim(0, 4.5)
    save(fig, "layout_check", lang)


def lc_plane_edge(lang):
    """Plane edge check: cross-section near the board edge, measure and limit."""
    fig, ax = new_fig(t("pe_title", lang), h=3.6)
    edge, clear, h = 0.8, 0.5, 1.2          # board edge, copper-to-edge clearance, dielectric
    plane_end = edge + clear
    y_pl, y_top = 0.6, 0.6 + h              # plane top, track bottom
    # Dielectric and the copper of the plane (stops before the board edge)
    ax.add_patch(Rectangle((edge, y_pl), 9.6 - edge, h, color=DIEL))
    ax.add_patch(Rectangle((plane_end, y_pl - 0.15), 9.6 - plane_end, 0.15, color=COPPER))
    ax.text(6.0, y_pl - 0.42, t("pe_plane", lang), fontsize=10.8, color=TXT, ha="center")
    # Board edge and clearance
    ax.plot([edge, edge], [0.2, 3.3], color="#555555", lw=1.5, ls="--")
    ax.text(edge - 0.1, 3.45, t("pe_edge", lang), fontsize=10.1, color="#555555", ha="center", va="bottom")
    dim_arrow(ax, edge, 0.15, plane_end, 0.15, "", fs=9.5)
    ax.text(edge - 0.05, -0.2, t("pe_clear", lang), fontsize=9.5, color=DIM, ha="left", va="top")
    # Track on top
    tx0, tx1 = 2.7, 3.3
    ax.add_patch(Rectangle((tx0, y_top), tx1 - tx0, 0.15, color=COPPER))
    ax.text((tx0 + tx1) / 2 + 0.6, y_top + 0.25, t("pe_track", lang), fontsize=10.8, color=TXT)
    # Field lines from the track down to the plane (half-ellipses); the ones
    # that would land beyond the end of the copper are dashed red
    import numpy as np
    xc = (tx0 + tx1) / 2
    for k in (0.45, 1.0, 1.8, 2.8):
        for side in (-1, 1):
            xs = xc + side * k * h * np.sin(np.linspace(0, np.pi / 2, 30))
            ys = y_top - h * (1 - np.cos(np.linspace(0, np.pi / 2, 30))) * 0.98
            lost = side < 0 and xs[-1] < plane_end
            ax.plot(xs, ys, color="#c0392b" if lost else "#7f8c8d", lw=0.9, ls="--" if lost else "-")
    ax.text(5.0, 1.25, t("pe_field", lang), fontsize=10.1, color="#7f8c8d", va="center")
    # h
    dim_arrow(ax, 9.3, y_pl, 9.3, y_top, "h", fs=12.2)
    # Measure: track edge -> end of the copper; limit: 3 h from the end of the copper
    dim_arrow(ax, plane_end, 2.3, tx0, 2.3, t("pe_meas", lang), fs=10.8, offset=(0, 0.22))
    dim_arrow(ax, plane_end, 2.85, plane_end + 3 * h, 2.85, t("pe_limit", lang), fs=10.8, offset=(0, 0.22))
    # Where the track edge falls: error / warning / OK
    zones = ((plane_end, plane_end + h, "#f5b7b1", "pe_err"),
             (plane_end + h, plane_end + 3 * h, "#fde9a9", "pe_warn"),
             (plane_end + 3 * h, 9.6, "#c8ecd2", "pe_ok"))
    for x0, x1, col, key in zones:
        ax.add_patch(Rectangle((x0, 3.3), x1 - x0, 0.45, color=col))
        ax.text((x0 + x1) / 2, 3.52, t(key, lang), fontsize=9.5, ha="center", va="center", color=TXT)
    ax.text(4.9, -1.15, t("pe_note", lang), fontsize=10.1, color=TXT, ha="center")
    ax.set_xlim(-0.3, 10.0)
    ax.set_ylim(-1.35, 3.95)
    save(fig, "lc_plane_edge", lang)


def lc_width(lang):
    """Track width check: actual width against the width needed for the current."""
    fig, ax = new_fig(t("tw_title", lang), h=2.9)
    # Needed width (dashed outline) and actual track
    ax.add_patch(Rectangle((0.6, 1.0), 7.0, 1.0, fill=False, ls="--", color=DIM, lw=1.2))
    ax.add_patch(Rectangle((0.6, 1.35), 7.0, 0.3, color=COPPER))
    # Current along the track
    ax.add_patch(FancyArrowPatch((1.0, 2.35), (3.6, 2.35), arrowstyle="-|>", mutation_scale=14, color="#1f618d", lw=2))
    ax.text(3.8, 2.35, t("tw_cur", lang), fontsize=10.1, color="#1f618d", va="center")
    # Dimensions on the right
    dim_arrow(ax, 7.95, 1.35, 7.95, 1.65, "", fs=9.5)
    ax.text(8.15, 1.5, t("tw_have", lang), fontsize=10.1, color=DIM, va="center")
    dim_arrow(ax, 7.75, 1.0, 7.75, 2.0, "", fs=9.5)
    ax.text(8.15, 0.85, t("tw_need", lang), fontsize=10.1, color=DIM, va="center")
    ax.text(4.8, 0.35, t("tw_note", lang), fontsize=10.1, color=TXT, ha="center")
    ax.set_xlim(0.2, 11.3)
    ax.set_ylim(0.1, 2.9)
    save(fig, "lc_width", lang)


def lc_isolation(lang):
    """Isolation check: edge-to-edge distance between two nets and the IPC table."""
    fig, ax = new_fig(t("iso_title", lang), h=3.0)
    ax.add_patch(Rectangle((0.4, 2.2), 5.2, 0.35, color="#e67e22"))
    ax.text(0.5, 2.7, t("iso_hv", lang), fontsize=10.8, color=TXT)
    ax.add_patch(Rectangle((0.4, 0.9), 5.2, 0.6, color=GND))
    ax.text(0.5, 0.6, t("iso_gnd", lang), fontsize=10.8, color=TXT)
    dim_arrow(ax, 2.0, 1.5, 2.0, 2.2, "", fs=9.5)
    ax.text(2.2, 1.85, t("iso_meas", lang), fontsize=10.1, color=DIM, va="center")
    ax.text(5.9, 2.9, t("iso_tab", lang), fontsize=9.5, family="monospace", color=TXT, va="top",
            bbox=dict(facecolor="#f4f6f7", edgecolor="#bbbbbb", pad=4))
    ax.text(5.9, 0.75, t("iso_volt", lang), fontsize=10.1, color="#555555", va="center")
    ax.set_xlim(0.2, 11.6)
    ax.set_ylim(0.3, 3.1)
    save(fig, "lc_isolation", lang)


def lc_length(lang):
    """Length check: skew of a differential pair, difference inside a group."""
    fig, ax = new_fig(t("len_title", lang), h=3.4)
    # Differential pair: DP straight, DM with a detour (longer)
    ax.plot([0.5, 5.0], [3.1, 3.1], color=COPPER, lw=3)
    ax.plot([0.5, 2.2, 2.4, 2.9, 3.1, 5.0], [2.8, 2.8, 2.45, 2.45, 2.8, 2.8], color="#b06f25", lw=3)
    ax.text(5.1, 3.1, "DP", fontsize=10.8, va="center")
    ax.text(5.1, 2.8, "DM", fontsize=10.8, va="center")
    ax.text(0.5, 3.35, t("len_pair", lang), fontsize=10.1, color=TXT, va="bottom")
    ax.text(6.1, 2.95, t("len_pmeas", lang), fontsize=10.1, color=DIM, va="center")
    # Group: three nets, one shorter than the longest
    ends = (("SD_CLK", 5.0), ("SD_D0", 4.8), ("SD_D1", 3.9))
    for k, (name, x_end) in enumerate(ends):
        y = 1.55 - k * 0.38
        ax.plot([0.5, x_end], [y, y], color=COPPER, lw=3)
        # The longest one is named as such next to its name
        label = f"{name}  ({t('len_longest', lang)})" if k == 0 else name
        ax.text(x_end + 0.1, y, label, fontsize=10.1, va="center")
    ax.text(0.5, 1.8, t("len_group", lang), fontsize=10.1, color=TXT, va="bottom")
    ax.plot([5.0, 5.0], [1.65, 0.6], color="#888888", lw=0.8, ls=":")
    dim_arrow(ax, 3.9, 0.55, 5.0, 0.55, "", fs=9.5)
    ax.text(6.1, 0.95, t("len_gmeas", lang), fontsize=10.1, color=DIM, va="center")
    ax.set_xlim(0.2, 10.6)
    ax.set_ylim(0.05, 3.9)
    save(fig, "lc_length", lang)


# Font sizes of the drawings of the checks 9-16 (shown 600 px wide in the
# Help tab: smaller text is not readable)
FS, FS_S = 10.5, 9.5
RED = "#c0392b"
GREEN = "#1e8449"


def _pad(ax, x, y, w, h, label=None):
    """Copper pad (rectangle centred in x, y) with an optional label inside."""
    ax.add_patch(Rectangle((x - w / 2, y - h / 2), w, h, color=COPPER, ec="#8a5a1a", lw=0.8))
    if label:
        ax.text(x, y, label, fontsize=FS_S - 1, ha="center", va="center", color="white")


def _trk(ax, pts, w=0.18, color=COPPER, ls="-"):
    """Track through the points (thick line, round ends)."""
    xs, ys = zip(*pts)
    ax.plot(xs, ys, color=color, lw=w * 40, solid_capstyle="round", ls=ls)


def lc_stub(lang):
    """Dead branch: a track leaving the line and ending in nothing."""
    fig, ax = new_fig(t("stub_title", lang), h=3.0)
    _pad(ax, 1.0, 1.0, 0.6, 0.6)
    _pad(ax, 7.0, 1.0, 0.6, 0.6)
    _trk(ax, [(1.0, 1.0), (7.0, 1.0)])
    _trk(ax, [(4.0, 1.0), (4.0, 2.6)])
    ax.add_patch(Circle((4.0, 2.6), 0.22, fill=False, color=RED, lw=1.8))
    ax.text(4.35, 2.75, t("stub_free", lang), fontsize=FS_S, color=RED, va="center")
    dim_arrow(ax, 3.55, 1.12, 3.55, 2.6, "", fs=FS_S)
    ax.text(7.6, 2.2, t("stub_meas", lang), fontsize=FS, color=DIM, va="center")
    ax.text(4.0, 0.35, t("stub_why", lang), fontsize=FS_S, color=TXT, ha="center")
    ax.set_xlim(0.4, 12.6)
    ax.set_ylim(0.1, 3.2)
    save(fig, "lc_stub", lang)


def lc_acute(lang):
    """Acute angle (bad) next to two 45 degree segments (good)."""
    import numpy as np

    fig, ax = new_fig(t("ac_title", lang), h=3.3)
    # Bad: the line comes back at 30 degrees
    _trk(ax, [(0.6, 1.0), (4.0, 1.0)])
    ang = np.radians(30)
    _trk(ax, [(4.0, 1.0), (4.0 - 3.0 * np.cos(ang), 1.0 + 3.0 * np.sin(ang))])
    a = np.linspace(np.pi - ang, np.pi, 20)
    ax.plot(4.0 + 1.0 * np.cos(a), 1.0 + 1.0 * np.sin(a), color=RED, lw=1.5)
    ax.text(2.6, 1.22, "30°", fontsize=FS, color=RED)
    ax.text(0.6, 2.75, t("ac_bad", lang), fontsize=FS_S, color=RED, va="center")
    # Good: two 45 degree segments
    _trk(ax, [(6.2, 1.0), (8.2, 1.0), (9.4, 2.2), (9.4, 3.0)])
    ax.text(9.7, 1.1, t("ac_good", lang), fontsize=FS_S, color=GREEN, va="center")
    ax.text(5.6, 0.25, t("ac_meas", lang), fontsize=FS, color=DIM, ha="center")
    ax.set_xlim(0.3, 12.6)
    ax.set_ylim(0.0, 3.4)
    save(fig, "lc_acute", lang)


def lc_width_step(lang):
    """Width step along a net, and the neck-down at a pad that is ignored."""
    fig, ax = new_fig(t("ws_title", lang), h=3.0)
    _pad(ax, 0.8, 1.6, 0.7, 0.9)
    _trk(ax, [(0.8, 1.6), (1.3, 1.6)], w=0.07)              # neck-down at the pad
    _trk(ax, [(1.3, 1.6), (5.0, 1.6)], w=0.3)
    _trk(ax, [(5.0, 1.6), (9.0, 1.6)], w=0.12)
    ax.text(3.0, 2.15, t("ws_wide", lang), fontsize=FS_S, ha="center")
    ax.text(7.0, 1.95, t("ws_narrow", lang), fontsize=FS_S, ha="center")
    ax.annotate(t("ws_step", lang), (5.0, 1.6), (5.3, 2.6), fontsize=FS_S, color=RED,
                arrowprops=dict(arrowstyle="->", color=RED))
    ax.annotate(t("ws_neck", lang), (1.1, 1.55), (0.3, 0.45), fontsize=FS_S - 0.5, color="#555555",
                arrowprops=dict(arrowstyle="->", color="#555555"))
    ax.text(6.0, 0.75, t("ws_meas", lang), fontsize=FS, color=DIM, va="center")
    ax.set_xlim(0.2, 12.6)
    ax.set_ylim(0.1, 3.0)
    save(fig, "lc_width_step", lang)


def lc_via_in_pad(lang):
    """Via drill inside an SMD pad (bad), via outside (good), thermal pad (ignored)."""
    fig, ax = new_fig(t("vip_title", lang), h=3.1)
    # Bad
    _pad(ax, 1.6, 2.0, 1.2, 0.8)
    ax.add_patch(Circle((1.6, 2.0), 0.28, color="#bbbbbb", ec="#555555"))
    ax.add_patch(Circle((1.6, 2.0), 0.14, color="white", ec="#555555"))
    ax.text(1.6, 0.9, t("vip_bad", lang), fontsize=FS_S, color=RED, ha="center", va="center")
    # Good
    _pad(ax, 5.0, 2.0, 1.2, 0.8)
    _trk(ax, [(5.0, 2.0), (5.0, 3.0)])
    ax.add_patch(Circle((5.0, 3.0), 0.28, color="#bbbbbb", ec="#555555"))
    ax.add_patch(Circle((5.0, 3.0), 0.14, color="white", ec="#555555"))
    ax.text(5.0, 0.9, t("vip_good", lang), fontsize=FS_S, color=GREEN, ha="center", va="center")
    # Thermal pad with vias
    _pad(ax, 9.0, 2.0, 2.4, 2.0)
    for dx in (-0.6, 0.0, 0.6):
        for dy in (-0.5, 0.5):
            ax.add_patch(Circle((9.0 + dx, 2.0 + dy), 0.14, color="white", ec="#555555"))
    ax.text(9.0, 0.45, t("vip_ep", lang), fontsize=FS_S, color="#555555", ha="center", va="center")
    ax.set_xlim(0.2, 11.0)
    ax.set_ylim(0.0, 3.5)
    save(fig, "lc_via_in_pad", lang)


def lc_tombstone(lang):
    """Two-pad part: one pad flooded in the zone (bad) and with a thermal relief (good)."""
    fig, ax = new_fig(t("tb_title", lang), h=3.3)
    for x0 in (0.4, 6.4):
        # Zone ending between the two pads (0.25 clearance from the right one)
        ax.add_patch(Rectangle((x0, 0.9), 2.45, 2.0, color=GND, alpha=0.6))
        ax.text(x0 + 0.1, 3.0, t("tb_zone", lang), fontsize=FS_S, color="#555555")
        # Body of the part (dashed) behind its two pads
        ax.add_patch(Rectangle((x0 + 1.5, 1.45), 1.9, 0.9, fill=False, ec="#444444", lw=1, ls="--"))
    # Bad: left pad flooded (no gap around it), right pad on a track
    _pad(ax, 2.3, 1.9, 0.6, 0.7)
    _pad(ax, 3.4, 1.9, 0.6, 0.7)
    _trk(ax, [(3.4, 1.9), (4.6, 1.9)])
    ax.text(0.4, 0.35, t("tb_bad", lang), fontsize=FS_S - 0.5, color=RED, va="center")
    # Good: thermal relief (gap around the pad, three spokes)
    ax.add_patch(Rectangle((7.8, 1.35), 1.05, 1.1, color="white"))
    for (x0, y0, w, h) in ((8.25, 1.35, 0.1, 0.2), (8.25, 2.25, 0.1, 0.2), (7.8, 1.85, 0.2, 0.1)):
        ax.add_patch(Rectangle((x0, y0), w, h, color=GND))
    _pad(ax, 8.3, 1.9, 0.6, 0.7)
    _pad(ax, 9.4, 1.9, 0.6, 0.7)
    _trk(ax, [(9.4, 1.9), (10.6, 1.9)])
    ax.text(7.0, 0.45, t("tb_good", lang), fontsize=FS_S, color=GREEN, va="center")
    ax.set_xlim(0.2, 11.4)
    ax.set_ylim(-0.4, 3.4)
    save(fig, "lc_tombstone", lang)


def lc_via_current(lang):
    """Layer change with two vias where three are needed."""
    fig, ax = new_fig(t("vc_title", lang), h=3.0)
    _trk(ax, [(3.2, 1.6), (7.0, 1.6)], w=0.45, color="#9c6a2e")   # layer below (darker)
    _trk(ax, [(0.5, 1.6), (3.9, 1.6)], w=0.45)                    # layer above
    for x in (3.2, 3.9):
        ax.add_patch(Circle((x, 1.6), 0.28, color="#bbbbbb", ec="#555555", zorder=3))
        ax.add_patch(Circle((x, 1.6), 0.14, color="white", ec="#555555", zorder=4))
    ax.add_patch(Circle((4.6, 1.6), 0.28, fill=False, ec=RED, ls="--", lw=1.5, zorder=3))
    ax.text(4.6, 2.15, t("vc_missing", lang), fontsize=FS_S, color=RED, ha="center")
    ax.text(0.5, 2.55, t("vc_cur", lang), fontsize=FS_S, color="#1f618d", va="center")
    ax.text(7.5, 1.6, t("vc_meas", lang), fontsize=FS, color=DIM, va="center")
    ax.set_xlim(0.2, 12.4)
    ax.set_ylim(0.6, 3.0)
    save(fig, "lc_via_current", lang)


def lc_crystal(lang):
    """Crystal: a foreign track under it (error) and the crystal-IC tracks length."""
    fig, ax = new_fig(t("xt_title2", lang), h=3.4)
    # Crystal outline and pads
    ax.add_patch(Rectangle((1.0, 1.4), 2.0, 1.2, fill=False, ec="#555555", lw=1.2))
    _pad(ax, 1.4, 2.0, 0.5, 0.8)
    _pad(ax, 2.6, 2.0, 0.5, 0.8)
    ax.text(3.15, 2.45, t("xt_xtal", lang), fontsize=FS_S, ha="left")
    # IC
    ax.add_patch(Rectangle((7.4, 1.2), 1.6, 1.6, color="#333333"))
    ax.text(8.2, 2.0, t("xt_ic", lang), fontsize=FS_S, color="white", ha="center", va="center")
    _trk(ax, [(1.4, 2.0), (1.4, 3.1), (7.0, 3.1), (7.0, 2.4), (7.4, 2.4)])
    _trk(ax, [(2.6, 2.0), (4.0, 2.0), (4.0, 1.6), (7.4, 1.6)])
    # Foreign track under the crystal (other layer)
    _trk(ax, [(2.0, 1.0), (2.0, 3.5)], color="#2b6cb0", ls="--")
    ax.add_patch(Circle((2.0, 1.55), 0.22, fill=False, color=RED, lw=2))
    ax.text(0.2, 0.5, t("xt_under", lang), fontsize=FS_S, color=RED, va="center")
    ax.text(4.1, 0.6, t("xt_meas", lang), fontsize=FS, color=DIM, va="center")
    ax.set_xlim(0.1, 11.6)
    ax.set_ylim(0.0, 3.7)
    save(fig, "lc_crystal", lang)


def lc_broadside(lang):
    """Two tracks of different nets one over the other on adjacent layers."""
    fig, ax = new_fig(t("bs_title", lang), h=2.9)
    _trk(ax, [(0.6, 1.6), (6.6, 1.6)], w=0.22)
    _trk(ax, [(2.6, 1.62), (8.6, 1.62), (8.6, 0.7)], w=0.22, color="#2b6cb0", ls=(0, (1.2, 0.8)))
    # The two labels on separate lines (the English ones are long)
    ax.text(0.6, 1.15, t("bs_top", lang), fontsize=FS_S, color="#8a5a1a")
    ax.text(0.6, 0.78, t("bs_bot", lang), fontsize=FS_S, color="#2b6cb0")
    dim_arrow(ax, 2.6, 2.6, 6.6, 2.6, "", fs=FS_S)
    ax.plot([2.6, 2.6], [1.8, 2.6], color="#888888", lw=0.8, ls=":")
    ax.plot([6.6, 6.6], [1.8, 2.6], color="#888888", lw=0.8, ls=":")
    ax.text(9.0, 2.35, t("bs_meas", lang), fontsize=FS, color=DIM, va="center")
    ax.text(0.6, 0.38, t("bs_why", lang), fontsize=FS_S, color=TXT)
    ax.set_xlim(0.3, 14.4)
    ax.set_ylim(0.1, 3.0)
    save(fig, "lc_broadside", lang)


ALL = (layout_check, lc_plane_edge, lc_width, lc_isolation, lc_length,
       lc_stub, lc_acute, lc_width_step, lc_via_in_pad, lc_tombstone, lc_via_current, lc_crystal, lc_broadside,
       return_path, dc_current, impedance, diff_pair, crosstalk, openems)

if __name__ == "__main__":
    import sys

    # Optional argument: names of the drawings to make (default: all), e.g.
    #   python make_help_images.py layout_check
    wanted = set(sys.argv[1:])
    os.makedirs(OUT, exist_ok=True)
    for lang in ("it", "en"):
        for fn in ALL:
            if not wanted or fn.__name__ in wanted:
                fn(lang)
    print("Immagini create in", OUT)
