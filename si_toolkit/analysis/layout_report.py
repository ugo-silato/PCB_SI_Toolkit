"""
Report of the Layout checks: one self-contained HTML page (no external
files, no libraries) with:
- board, date, plugin and KiCad version;
- the checks run, their thresholds and the net data;
- a summary per check (errors, warnings, excluded);
- a drawing of the whole board with the numbered problems;
- one card per problem: text, measure, limit, position and a zoomed drawing
  of the board around it (tracks, pads, vias, ground fill, the objects
  involved highlighted, the measured segment);
- the rows excluded by the user, greyed, and the notes.

The drawings are SVG written directly from the pcbnew objects (the KiCad
Python has no plotting library). The page prints well: from the browser,
"Print -> Save as PDF" gives the PDF.
"""
import datetime
import html
import math
import os

import pcbnew

from ..common.i18n import _
from . import layout_check as lc

# Colours of the drawings (copper of the outer layers, inner layers, pads...)
_LAYER_COLOURS = {pcbnew.F_Cu: "#c83434", pcbnew.B_Cu: "#3d7fc4"}
_INNER_COLOUR = "#3c9a5f"
_PAD_COLOUR = "#c9a227"
_VIA_COLOUR = "#9a9a9a"
_EDGE_COLOUR = "#e8e8e8"
_SEV_COLOUR = {lc.SEV_ERROR: "#e74c3c", lc.SEV_WARNING: "#f1c40f"}
_EXCL_COLOUR = "#9a9a9a"


def _mm(nm):
    """Nanometers -> millimeters."""
    return nm / 1e6


def _esc(text):
    """Text safe inside HTML."""
    return html.escape(str(text))


class _BoardDrawing:
    """
    The copper of the board read once (tracks, vias, pads, ground fill,
    outline) in millimeters, to draw it in SVG at any zoom.
    """

    def __init__(self, board, ref_filter):
        self.cu = list(board.GetEnabledLayers().CuStack())
        self.tracks = []   # (x0, y0, x1, y1, width, colour)
        self.vias = []     # (x, y, radius)
        self.pads = []     # (x0, y0, x1, y1) bounding boxes
        self.fills = []    # (list of points, colour) ground fill outlines
        self.edges = []    # (x0, y0, x1, y1) board outline
        for t in board.GetTracks():
            if t.Type() == pcbnew.PCB_VIA_T:
                p = t.GetPosition()
                self.vias.append((_mm(p.x), _mm(p.y), _mm(t.GetWidth()) / 2.0))
                continue
            pts = lc._track_points(t, pcbnew.FromMM(0.2), 200) if lc._is_arc(t) else \
                [(t.GetStart().x, t.GetStart().y), (t.GetEnd().x, t.GetEnd().y)]
            col = _LAYER_COLOURS.get(t.GetLayer(), _INNER_COLOUR)
            for a, b in zip(pts, pts[1:]):
                self.tracks.append((_mm(a[0]), _mm(a[1]), _mm(b[0]), _mm(b[1]), _mm(t.GetWidth()), col))
        for pad in board.GetPads():
            bb = pad.GetBoundingBox()
            self.pads.append((_mm(bb.GetLeft()), _mm(bb.GetTop()), _mm(bb.GetRight()), _mm(bb.GetBottom())))
        # Ground fill of the outer layers, as outlines (light)
        for z in board.Zones():
            if not z.IsFilled() or not lc._is_ref_net(z.GetNetname(), ref_filter):
                continue
            if lc.geometry.is_teardrop(z):
                continue  # teardrops are drawn as part of the tracks, not as ground fill
            for layer in self.cu:
                if not z.IsOnLayer(layer):
                    continue
                try:
                    polys = z.GetFilledPolysList(layer)
                    for i in range(polys.OutlineCount()):
                        ch = polys.Outline(i)
                        pts = [(_mm(ch.CPoint(k).x), _mm(ch.CPoint(k).y)) for k in range(ch.PointCount())]
                        if len(pts) > 2:
                            self.fills.append((pts, _LAYER_COLOURS.get(layer, _INNER_COLOUR)))
                except Exception:
                    pass
        for d in board.GetDrawings():
            if d.GetLayer() != pcbnew.Edge_Cuts:
                continue
            try:
                shape = d.GetShape()
                if shape == pcbnew.SHAPE_T_SEGMENT:
                    a, b = d.GetStart(), d.GetEnd()
                    self.edges.append((_mm(a.x), _mm(a.y), _mm(b.x), _mm(b.y)))
                elif shape == pcbnew.SHAPE_T_RECT:
                    a, b = d.GetStart(), d.GetEnd()
                    x0, y0, x1, y1 = _mm(a.x), _mm(a.y), _mm(b.x), _mm(b.y)
                    self.edges += [(x0, y0, x1, y0), (x1, y0, x1, y1), (x1, y1, x0, y1), (x0, y1, x0, y0)]
                else:
                    # Arcs, circles, polygons: their outline as a polyline
                    if shape == pcbnew.SHAPE_T_ARC:
                        pts = self._arc_points(d)
                    elif shape == pcbnew.SHAPE_T_CIRCLE:
                        c, r = d.GetCenter(), d.GetRadius()
                        pts = [(_mm(c.x + r * math.cos(2 * math.pi * k / 32)),
                                _mm(c.y + r * math.sin(2 * math.pi * k / 32))) for k in range(33)]
                    elif shape == pcbnew.SHAPE_T_POLY:
                        pts = [(_mm(p.x), _mm(p.y)) for p in d.GetCorners()]
                        pts.append(pts[0])
                    else:
                        continue  # curves and other shapes: not drawn
                    for a, b in zip(pts, pts[1:]):
                        self.edges.append((a[0], a[1], b[0], b[1]))
            except Exception:
                continue
        bb = board.GetBoardEdgesBoundingBox()
        if bb.GetWidth() <= 0:
            bb = board.ComputeBoundingBox(True)
        self.box = (_mm(bb.GetLeft()), _mm(bb.GetTop()), _mm(bb.GetRight()), _mm(bb.GetBottom()))

    @staticmethod
    def _arc_points(d):
        """Points of an Edge.Cuts arc (start, middle, end -> 16 segments)."""
        s, m, e = d.GetStart(), d.GetArcMid(), d.GetEnd()
        c = d.GetCenter()
        r = math.hypot(s.x - c.x, s.y - c.y)
        a0 = math.atan2(s.y - c.y, s.x - c.x)
        a1 = math.atan2(e.y - c.y, e.x - c.x)
        am = math.atan2(m.y - c.y, m.x - c.x)
        sweep = (a1 - a0) % (2 * math.pi)
        if (am - a0) % (2 * math.pi) > sweep:
            sweep -= 2 * math.pi
        return [(_mm(c.x + r * math.cos(a0 + sweep * k / 16)), _mm(c.y + r * math.sin(a0 + sweep * k / 16)))
                for k in range(17)]

    def svg(self, view, width_px, overlay="", detail=True):
        """
        SVG of the board inside view = (x0, y0, x1, y1) in mm, width_px
        wide, with 'overlay' (more SVG) drawn on top. detail=False skips the
        pads (whole-board drawing, lighter).
        """
        x0, y0, x1, y1 = view
        w, h = max(x1 - x0, 0.1), max(y1 - y0, 0.1)
        height_px = int(width_px * h / w)

        def inside(*xs_ys):
            xs, ys = xs_ys[0::2], xs_ys[1::2]
            return not (max(xs) < x0 or min(xs) > x1 or max(ys) < y0 or min(ys) > y1)

        out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{x0:.3f} {y0:.3f} {w:.3f} {h:.3f}" '
               f'width="{width_px}" height="{height_px}" style="background:#10161f">']
        for pts, col in self.fills:
            xs, ys = [p[0] for p in pts], [p[1] for p in pts]
            if max(xs) < x0 or min(xs) > x1 or max(ys) < y0 or min(ys) > y1:
                continue
            path = " ".join(f"{px:.3f},{py:.3f}" for px, py in pts)
            out.append(f'<polygon points="{path}" fill="{col}" fill-opacity="0.18" stroke="none"/>')
        for a, b, c, d, wd, col in self.tracks:
            if inside(a, b, c, d):
                out.append(f'<line x1="{a:.3f}" y1="{b:.3f}" x2="{c:.3f}" y2="{d:.3f}" stroke="{col}" '
                           f'stroke-width="{wd:.3f}" stroke-linecap="round" stroke-opacity="0.85"/>')
        if detail:
            for a, b, c, d in self.pads:
                if inside(a, b, c, d):
                    out.append(f'<rect x="{a:.3f}" y="{b:.3f}" width="{c - a:.3f}" height="{d - b:.3f}" '
                               f'fill="{_PAD_COLOUR}" fill-opacity="0.8"/>')
        for x, y, r in self.vias:
            if inside(x - r, y - r, x + r, y + r):
                out.append(f'<circle cx="{x:.3f}" cy="{y:.3f}" r="{r:.3f}" fill="{_VIA_COLOUR}"/>')
        sw = w / width_px * 1.2  # one-pixel-ish line whatever the zoom
        for a, b, c, d in self.edges:
            if inside(a, b, c, d):
                out.append(f'<line x1="{a:.3f}" y1="{b:.3f}" x2="{c:.3f}" y2="{d:.3f}" stroke="{_EDGE_COLOUR}" '
                           f'stroke-width="{sw:.4f}"/>')
        out.append(overlay)
        out.append("</svg>")
        return "".join(out)


def _issue_overlay(it, colour, scale, number=None, outline_items=True):
    """
    SVG drawn over the board for one issue: its objects highlighted, the
    stitching area, the measured segment, a ring and (optionally) its number.
    'scale' = mm per pixel of the drawing, to keep strokes and text readable.
    """
    out = []
    # Objects involved, outlined (not in the whole-board drawing: too crowded)
    for o in (it.items if outline_items else ()):
        try:
            if o.Type() in (pcbnew.PCB_TRACE_T, getattr(pcbnew, "PCB_ARC_T", -1)):
                a, b = o.GetStart(), o.GetEnd()
                out.append(f'<line x1="{_mm(a.x):.3f}" y1="{_mm(a.y):.3f}" x2="{_mm(b.x):.3f}" y2="{_mm(b.y):.3f}" '
                           f'stroke="#ffffff" stroke-width="{max(_mm(o.GetWidth()), 2 * scale):.3f}" '
                           f'stroke-linecap="round" stroke-opacity="0.55"/>')
            else:
                # A footprint is outlined by its pads (its outline can be large)
                if o.Type() == pcbnew.PCB_FOOTPRINT_T:
                    pads = list(o.Pads())
                    bb = pads[0].GetBoundingBox()
                    for pd in pads[1:]:
                        bb.Merge(pd.GetBoundingBox())
                else:
                    bb = o.GetBoundingBox()
                out.append(f'<rect x="{_mm(bb.GetLeft()):.3f}" y="{_mm(bb.GetTop()):.3f}" '
                           f'width="{_mm(bb.GetWidth()):.3f}" height="{_mm(bb.GetHeight()):.3f}" fill="none" '
                           f'stroke="#ffffff" stroke-width="{2 * scale:.3f}" stroke-dasharray="{4 * scale:.3f}"/>')
        except Exception:
            continue
    # Stitching areas
    for outer, holes in it.polys:
        d = "M " + " L ".join(f"{_mm(x):.3f},{_mm(y):.3f}" for x, y in outer) + " Z"
        for hole in holes:
            d += " M " + " L ".join(f"{_mm(x):.3f},{_mm(y):.3f}" for x, y in hole) + " Z"
        out.append(f'<path d="{d}" fill="{colour}" fill-opacity="0.35" fill-rule="evenodd" stroke="{colour}" '
                   f'stroke-width="{scale:.3f}"/>')
    x, y = _mm(it.x_nm), _mm(it.y_nm)
    # Measured segment
    if it.ref_xy is not None:
        rx, ry = _mm(it.ref_xy[0]), _mm(it.ref_xy[1])
        out.append(f'<line x1="{x:.3f}" y1="{y:.3f}" x2="{rx:.3f}" y2="{ry:.3f}" stroke="{colour}" '
                   f'stroke-width="{2 * scale:.3f}"/>')
    r = 14 * scale
    out.append(f'<circle cx="{x:.3f}" cy="{y:.3f}" r="{r:.3f}" fill="none" stroke="{colour}" '
               f'stroke-width="{2.5 * scale:.3f}"/>')
    if number is not None:
        fs = 13 * scale
        out.append(f'<text x="{x + r:.3f}" y="{y - r:.3f}" font-size="{fs:.3f}" font-family="sans-serif" '
                   f'fill="{colour}" font-weight="bold">{number}</text>')
    return "".join(out)


def _zoom_view(it):
    """Square view (mm) around an issue: its point, objects and measure, at least 8 mm."""
    xs, ys = [_mm(it.x_nm)], [_mm(it.y_nm)]
    if it.ref_xy is not None:
        xs.append(_mm(it.ref_xy[0]))
        ys.append(_mm(it.ref_xy[1]))
    for o in it.items[:20]:
        try:
            # A footprint counts by its pads (its outline can be much larger)
            parts = list(o.Pads()) if o.Type() == pcbnew.PCB_FOOTPRINT_T else [o]
            for part in parts:
                bb = part.GetBoundingBox()
                xs += [_mm(bb.GetLeft()), _mm(bb.GetRight())]
                ys += [_mm(bb.GetTop()), _mm(bb.GetBottom())]
        except Exception:
            pass
    for outer, _holes in it.polys:
        xs += [_mm(p[0]) for p in outer]
        ys += [_mm(p[1]) for p in outer]
    cx, cy = (min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0
    half = min(max(max(xs) - min(xs), max(ys) - min(ys)) / 2.0 + 2.0, 25.0)
    half = max(half, 4.0)
    return cx - half, cy - half, cx + half, cy + half


def _value(v, unit, limit=False):
    """Measure / limit text with its unit (same rules as the table of the tab)."""
    if v is None:
        return "-"
    if unit == "via":
        txt = f"{int(round(v))}"
    elif unit in ("°", "%"):
        txt = f"{v:.0f}"
    elif limit:
        txt = f"{v:g}"
    else:
        txt = f"{v:.2f}" if v < 10 else f"{v:.1f}"
    if not unit:
        return txt
    return f"{txt}{unit}" if unit == "°" else f"{txt} {unit}"


def write_report(path, board, issues, excluded, settings, notes, plugin_version=""):
    """
    Writes the HTML report.
    issues: the rows of the last run; excluded: set of their indexes excluded
    by the user; settings: the CheckSettings used; notes: status notes.
    Returns the path written.
    """
    names = lc.check_names()
    draw = _BoardDrawing(board, settings.ref_filter)
    active = [(k, it) for k, it in enumerate(issues) if k not in excluded]
    excl = [(k, it) for k, it in enumerate(issues) if k in excluded]
    n_err = sum(1 for _k, it in active if it.severity == lc.SEV_ERROR)
    n_warn = len(active) - n_err
    board_name = os.path.basename(board.GetFileName() or "") or _("(scheda non salvata)")
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    try:
        kicad = pcbnew.Version()
    except Exception:
        kicad = "?"

    h = []
    h.append("<!DOCTYPE html><html><head><meta charset='utf-8'>")
    h.append(f"<title>{_esc(_('Controlli layout'))} - {_esc(board_name)}</title>")
    h.append("""<style>
body{font-family:Segoe UI,Arial,sans-serif;margin:24px;color:#222;max-width:1100px}
h1{font-size:22px;margin-bottom:4px} h2{font-size:17px;margin-top:28px;border-bottom:1px solid #ccc}
.meta{color:#555;font-size:13px}
table{border-collapse:collapse;font-size:13px;margin:8px 0}
td,th{border:1px solid #ccc;padding:4px 8px;text-align:left;vertical-align:top}
th{background:#f2f2f2}
.err{color:#c0392b;font-weight:bold} .warn{color:#b7950b;font-weight:bold} .excl{color:#999}
.card{border:1px solid #ccc;border-radius:6px;padding:10px;margin:12px 0;display:flex;gap:14px;page-break-inside:avoid}
.card .txt{flex:1;font-size:13px} .card .num{font-size:20px;font-weight:bold;min-width:34px}
.card.excluded{opacity:0.55}
.legend{font-size:12px;color:#555}
@media print{body{margin:10mm} .card{break-inside:avoid}}
</style></head><body>""")
    h.append(f"<h1>{_esc(_('Controlli layout'))}: {_esc(board_name)}</h1>")
    h.append(f"<div class='meta'>{_esc(now)} &middot; PCB Signal Integrity Toolkit {_esc(plugin_version)} "
             f"&middot; KiCad {_esc(kicad)}</div>")
    h.append("<p><b>{0}</b> {1}, <b>{2}</b> {3}, <b>{4}</b> {5}</p>".format(
        n_err, _esc(_("errori")), n_warn, _esc(_("avvisi")), len(excl), _esc(_("righe escluse"))))

    # --- Summary per check ---
    h.append(f"<h2>{_esc(_('Riepilogo'))}</h2><table><tr><th>{_esc(_('Controllo'))}</th>"
             f"<th>{_esc(_('Errori'))}</th><th>{_esc(_('Avvisi'))}</th><th>{_esc(_('Escluse'))}</th></tr>")
    enabled = {lc.CHECK_DECAP: settings.do_decap, lc.CHECK_LAYER_CHANGE: settings.do_layer_change,
               lc.CHECK_STITCHING: settings.do_stitching, lc.CHECK_PLANE_GAP: settings.do_plane_gap,
               lc.CHECK_PLANE_EDGE: settings.do_plane_edge, lc.CHECK_WIDTH: settings.do_width,
               lc.CHECK_ISOLATION: settings.do_isolation, lc.CHECK_LENGTH: settings.do_length,
               lc.CHECK_STUB: settings.do_stub, lc.CHECK_ACUTE: settings.do_acute,
               lc.CHECK_WIDTH_STEP: settings.do_width_step, lc.CHECK_VIA_IN_PAD: settings.do_via_in_pad,
               lc.CHECK_TOMBSTONE: settings.do_tombstone, lc.CHECK_VIA_CURRENT: settings.do_via_current,
               lc.CHECK_CRYSTAL: settings.do_crystal, lc.CHECK_BROADSIDE: settings.do_broadside}
    for key in lc.CHECK_ORDER:
        if not enabled.get(key):
            h.append(f"<tr class='excl'><td>{_esc(names[key])}</td><td colspan='3'>{_esc(_('non eseguito'))}</td></tr>")
            continue
        e = sum(1 for _k, it in active if it.check == key and it.severity == lc.SEV_ERROR)
        w = sum(1 for _k, it in active if it.check == key and it.severity != lc.SEV_ERROR)
        x = sum(1 for _k, it in excl if it.check == key)
        h.append(f"<tr><td>{_esc(names[key])}</td><td class='{'err' if e else ''}'>{e}</td>"
                 f"<td class='{'warn' if w else ''}'>{w}</td><td>{x}</td></tr>")
    h.append("</table>")

    # --- Settings used ---
    h.append(f"<h2>{_esc(_('Soglie e dati usati'))}</h2><table>")
    rows = [
        (_("Net di massa"), settings.ref_filter),
        (_("Condensatore: attenzione / errore oltre"), f"{settings.decap_warn_mm:g} / {settings.decap_err_mm:g} mm"),
        (_("Via di massa dei pad GND entro"), f"{settings.gnd_via_mm:g} mm"),
        (_("Via di ritorno al cambio layer entro"), f"{settings.return_via_mm:g} mm"),
        (_("Passo massimo via di stitching"), f"{settings.stitch_spacing_mm:g} mm"),
        (_("Gap minimo del piano"), f"{settings.min_gap_mm:g} mm"),
        (_("Bordo del piano: almeno"), f"{settings.edge_h_factor:g} h"),
        (_("Riscaldamento massimo tracce"), f"{settings.delta_t:g} C"),
        (_("Skew massimo coppie / differenza nei gruppi"), f"{settings.skew_mm:g} / {settings.group_tol_mm:g} mm"),
        (_("Rami morti da"), f"{settings.stub_mm:g} mm"),
        (_("Angoli acuti sotto"), f"{settings.acute_deg:g}°"),
        (_("Cambio di larghezza oltre"), f"{settings.width_step_pct:g} %"),
        (_("Tracce quarzo-integrato fino a"), f"{settings.crystal_mm:g} mm"),
        (_("Tracce sovrapposte da"), f"{settings.broadside_mm:g} mm"),
        (_("Correnti"), settings.currents or "-"),
        (_("Tensioni"), settings.voltages or "-"),
        (_("Gruppi di lunghezza"), settings.groups or "-"),
    ]
    for label, value in rows:
        h.append(f"<tr><th>{_esc(label)}</th><td>{_esc(value)}</td></tr>")
    h.append("</table>")

    # --- Whole board with numbered problems ---
    h.append(f"<h2>{_esc(_('Scheda'))}</h2>")
    bx0, by0, bx1, by1 = draw.box
    pad = 2.0
    view = (bx0 - pad, by0 - pad, bx1 + pad, by1 + pad)
    scale = (view[2] - view[0]) / 1000.0
    overlay = "".join(_issue_overlay(it, _SEV_COLOUR[it.severity], scale, n + 1, outline_items=False)
                      for n, (_k, it) in enumerate(active))
    h.append(draw.svg(view, 1000, overlay, detail=False))
    h.append(f"<div class='legend'>{_esc(_('Rosso = errore, giallo = avviso; il numero rimanda alla scheda del problema qui sotto. Tracce: rosso F.Cu, blu B.Cu.'))}</div>")

    # --- One card per problem ---
    def card(n, it, excluded_row):
        colour = _EXCL_COLOUR if excluded_row else _SEV_COLOUR[it.severity]
        view = _zoom_view(it)
        scale = (view[2] - view[0]) / 300.0
        svg = draw.svg(view, 300, _issue_overlay(it, colour, scale))
        sev = _("Escluso") if excluded_row else (_("Errore") if it.severity == lc.SEV_ERROR else _("Attenzione"))
        cls = "excl" if excluded_row else ("err" if it.severity == lc.SEV_ERROR else "warn")
        return (f"<div class='card{' excluded' if excluded_row else ''}'><div class='num'>{n}</div>"
                f"<div class='txt'><span class='{cls}'>{_esc(sev)}</span> &middot; <b>{_esc(names[it.check])}</b>"
                f" &middot; {_esc(it.obj)}<p>{_esc(it.detail)}</p>"
                f"<p>{_esc(_('Misura'))}: <b>{_esc(_value(it.measured_mm, it.unit))}</b> &nbsp; "
                f"{_esc(_('Limite'))}: <b>{_esc(_value(it.limit_mm, it.unit, True))}</b> &nbsp; "
                f"{_esc(_('Posizione'))}: x {_mm(it.x_nm):.2f}, y {_mm(it.y_nm):.2f} mm</p></div>"
                f"<div>{svg}</div></div>")

    h.append(f"<h2>{_esc(_('Problemi'))}</h2>")
    if not active:
        h.append(f"<p>{_esc(_('Nessun problema trovato con le soglie impostate.'))}</p>")
    for n, (_k, it) in enumerate(active):
        h.append(card(n + 1, it, False))
    if excl:
        h.append(f"<h2>{_esc(_('Righe escluse (accettate)'))}</h2>")
        for n, (_k, it) in enumerate(excl):
            h.append(card(f"E{n + 1}", it, True))
    if notes:
        h.append(f"<h2>{_esc(_('Note'))}</h2><ul>" + "".join(f"<li>{_esc(t)}</li>" for t in notes) + "</ul>")
    h.append("</body></html>")
    with open(path, "w", encoding="utf-8") as f:
        f.write("".join(h))
    return path
