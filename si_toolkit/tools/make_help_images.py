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


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    for lang in ("it", "en"):
        for fn in (return_path, dc_current, impedance, diff_pair, crosstalk, openems):
            fn(lang)
    print("Immagini create in", OUT)
