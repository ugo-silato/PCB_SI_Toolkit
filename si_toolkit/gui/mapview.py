"""
Finestra "Mappa a colori": disegna la scheda (tracce, via, pad) e colora
gli elementi analizzati secondo un valore numerico (es. densita' di
corrente o tensione), con scala dei colori, zoom e lettura col mouse.

Disegnata con wxPython (nessuna dipendenza da matplotlib), dentro KiCad.
Coordinate in mm, asse y verso il basso come in Pcbnew.
"""
import math

import wx

from ..common.i18n import _


def colormap(t):
    """
    Colore per t fra 0 e 1: blu -> azzurro -> verde -> giallo -> rosso
    (scala "a semaforo" leggibile anche su fondo scuro).
    """
    t = max(0.0, min(1.0, t))
    stops = [
        (0.00, (40, 60, 200)),
        (0.25, (30, 170, 230)),
        (0.50, (60, 190, 90)),
        (0.75, (240, 210, 40)),
        (1.00, (220, 40, 40)),
    ]
    for (t0, c0), (t1, c1) in zip(stops, stops[1:]):
        if t <= t1:
            f = (t - t0) / (t1 - t0) if t1 > t0 else 0.0
            return tuple(int(a + (b - a) * f) for a, b in zip(c0, c1))
    return stops[-1][1]


class MapData:
    """
    Dati da disegnare:
    - background: segmenti di contesto [(x0, y0, x1, y1, w)] in grigio;
    - pads: [(x, y, sx, sy)] rettangoli dei pad (ingombro);
    - items: elementi colorati, dizionari con 'kind' ("track"/"via"),
      geometria ('seg' = (x0, y0, x1, y1, w) oppure 'via' = (x, y, r)),
      'values' = {nome_grandezza: valore} e 'label' (testo per il mouse);
    - quantities: elenco (nome, unita') delle grandezze disponibili.
    """

    def __init__(self, title, background, pads, items, quantities, markers=(),
                 zero_based=(), fixed_ranges=None):
        self.title = title
        self.background = background
        self.pads = pads
        self.items = items
        self.quantities = quantities
        # Marcatori [(x, y, testo, (r, g, b))], es. IN / OUT sui pad scelti
        self.markers = list(markers)
        # Grandezze la cui scala parte da zero (densita', corrente, %)
        self.zero_based = set(zero_based)
        # Scale fisse {grandezza: (min, max)}: i colori hanno un significato
        # assoluto (es. % del limite: 0-120%), non relativo alla mappa
        self.fixed_ranges = dict(fixed_ranges or {})


class MapPanel(wx.Panel):
    """Area di disegno con zoom (rotella), spostamento (trascinamento) e lettura."""

    def __init__(self, parent, data, on_hover):
        super().__init__(parent, style=wx.FULL_REPAINT_ON_RESIZE)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.data = data
        self.on_hover = on_hover
        self.quantity = data.quantities[0][0] if data.quantities else None
        self.scale = 1.0
        self.offset = (0.0, 0.0)
        self._drag = None
        self._fitted = False
        self.Bind(wx.EVT_PAINT, self.on_paint)
        self.Bind(wx.EVT_MOUSEWHEEL, self.on_wheel)
        self.Bind(wx.EVT_LEFT_DOWN, self.on_down)
        self.Bind(wx.EVT_LEFT_UP, self.on_up)
        self.Bind(wx.EVT_MOTION, self.on_motion)
        self.Bind(wx.EVT_SIZE, lambda e: (self.Refresh(), e.Skip()))

    # --- Trasformazione mm -> pixel ---
    def fit(self):
        """Inquadra tutti gli elementi colorati (con un margine)."""
        pts = []
        for it in self.data.items:
            if it["kind"] == "track":
                x0, y0, x1, y1, _w = it["seg"]
                pts += [(x0, y0), (x1, y1)]
            else:
                pts.append(it["via"][:2])
        if not pts:
            for x0, y0, x1, y1, _w in self.data.background:
                pts += [(x0, y0), (x1, y1)]
        if not pts:
            return
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        w, h = self.GetClientSize()
        span_x = max(max(xs) - min(xs), 1.0) * 1.2
        span_y = max(max(ys) - min(ys), 1.0) * 1.2
        self.scale = min(max(w - 120, 50) / span_x, max(h, 50) / span_y)
        cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
        self.offset = ((w - 120) / 2 - cx * self.scale, h / 2 - cy * self.scale)
        self._fitted = True

    def to_px(self, x, y):
        return x * self.scale + self.offset[0], y * self.scale + self.offset[1]

    def to_mm(self, px, py):
        return (px - self.offset[0]) / self.scale, (py - self.offset[1]) / self.scale

    # --- Valori e colori ---
    def value_range(self):
        """
        Estremi della scala dei colori:
        - se la grandezza ha una scala fissa (fixed_ranges) si usa quella;
        - per le grandezze "assolute" (zero_based) la scala va da zero al
          massimo;
        - altrimenti dal minimo al massimo (es. tensione).
        Se i valori sono praticamente uguali, la scala si centra sul valore
        e tutti gli elementi hanno lo stesso colore.
        """
        if self.quantity in self.data.fixed_ranges:
            return self.data.fixed_ranges[self.quantity]
        vals = [it["values"].get(self.quantity) for it in self.data.items]
        vals = [v for v in vals if v is not None]
        if not vals:
            return 0.0, 1.0
        lo, hi = min(vals), max(vals)
        if self.quantity in self.data.zero_based:
            lo = min(0.0, lo)
        span = max(abs(hi), abs(lo), 1e-12)
        if hi - lo < span * 1e-3:
            lo, hi = lo - span * 0.5, hi + span * 0.5
        return lo, hi

    def all_equal(self):
        """Vero se tutti gli elementi hanno (quasi) lo stesso valore."""
        vals = [it["values"].get(self.quantity) for it in self.data.items]
        vals = [v for v in vals if v is not None]
        if len(vals) < 2:
            return True
        span = max(abs(max(vals)), abs(min(vals)), 1e-12)
        return (max(vals) - min(vals)) < span * 1e-3

    def color_of(self, it, lo, hi):
        v = it["values"].get(self.quantity)
        if v is None:
            return wx.Colour(120, 120, 120)
        return wx.Colour(*colormap((v - lo) / (hi - lo)))

    # --- Disegno ---
    def on_paint(self, event):
        if not self._fitted:
            self.fit()
        dc = wx.AutoBufferedPaintDC(self)
        dc.SetBackground(wx.Brush(wx.Colour(25, 28, 34)))
        dc.Clear()
        gc = wx.GraphicsContext.Create(dc)
        if gc is None:
            return
        s = self.scale

        # Pad (prima delle tracce, cosi' le tracce corte restano visibili)
        gc.SetPen(wx.TRANSPARENT_PEN)
        gc.SetBrush(wx.Brush(wx.Colour(80, 84, 94)))
        for x, y, sx, sy in self.data.pads:
            px, py = self.to_px(x - sx / 2, y - sy / 2)
            gc.DrawRectangle(px, py, max(sx * s, 1), max(sy * s, 1))
        # Tracce di contesto in grigio
        for x0, y0, x1, y1, w in self.data.background:
            gc.SetPen(gc.CreatePen(wx.GraphicsPenInfo(wx.Colour(110, 114, 124)).Width(max(1.0, w * s)).Cap(wx.CAP_ROUND)))
            a, b = self.to_px(x0, y0), self.to_px(x1, y1)
            gc.StrokeLine(a[0], a[1], b[0], b[1])

        # Elementi colorati
        lo, hi = self.value_range()
        for it in self.data.items:
            col = self.color_of(it, lo, hi)
            if it["kind"] == "track":
                x0, y0, x1, y1, w = it["seg"]
                width = max(2.0, w * s)
                grad = it.get("grad", {}).get(self.quantity)
                if grad is None:
                    # Colore unico per tutto il tratto
                    gc.SetPen(gc.CreatePen(wx.GraphicsPenInfo(col).Width(width).Cap(wx.CAP_ROUND)))
                    a, b = self.to_px(x0, y0), self.to_px(x1, y1)
                    gc.StrokeLine(a[0], a[1], b[0], b[1])
                else:
                    # Sfumatura: il tratto e' diviso in N pezzi, ognuno col
                    # colore del valore interpolato fra inizio e fine
                    v0, v1 = grad
                    n = 12
                    for j in range(n):
                        f0, f1 = j / n, (j + 1) / n
                        v = v0 + (v1 - v0) * (f0 + f1) / 2  # valore al centro del pezzo
                        c = wx.Colour(*colormap((v - lo) / (hi - lo)))
                        # estremi arrotondati solo su primo/ultimo pezzo
                        cap = wx.CAP_ROUND if j in (0, n - 1) else wx.CAP_BUTT
                        gc.SetPen(gc.CreatePen(wx.GraphicsPenInfo(c).Width(width).Cap(cap)))
                        a = self.to_px(x0 + (x1 - x0) * f0, y0 + (y1 - y0) * f0)
                        b = self.to_px(x0 + (x1 - x0) * f1, y0 + (y1 - y0) * f1)
                        gc.StrokeLine(a[0], a[1], b[0], b[1])
        for it in self.data.items:
            if it["kind"] == "via":
                x, y, r = it["via"]
                gc.SetPen(wx.Pen(wx.Colour(230, 230, 230), 1))
                gc.SetBrush(wx.Brush(self.color_of(it, lo, hi)))
                px, py = self.to_px(x, y)
                rr = max(r * s, 3)
                gc.DrawEllipse(px - rr, py - rr, 2 * rr, 2 * rr)

        # Marcatori (IN / OUT): cerchio colorato con etichetta
        font = wx.Font(10, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD)
        for x, y, text, rgb in self.data.markers:
            px, py = self.to_px(x, y)
            gc.SetPen(wx.Pen(wx.Colour(*rgb), 3))
            gc.SetBrush(wx.TRANSPARENT_BRUSH)
            gc.DrawEllipse(px - 12, py - 12, 24, 24)
            gc.SetFont(font, wx.Colour(*rgb))
            gc.DrawText(text, px + 14, py - 22)

        self.draw_colorbar(gc, lo, hi)

    def draw_colorbar(self, gc, lo, hi):
        """Scala dei colori a destra, con i valori minimo, medio e massimo."""
        w, h = self.GetClientSize()
        x, top, bar_h, bar_w = w - 95, 30, max(h - 80, 60), 18
        steps = 60
        gc.SetPen(wx.TRANSPARENT_PEN)
        for i in range(steps):
            t = 1 - i / steps
            gc.SetBrush(wx.Brush(wx.Colour(*colormap(t))))
            gc.DrawRectangle(x, top + i * bar_h / steps, bar_w, bar_h / steps + 1)
        unit = dict(self.data.quantities).get(self.quantity, "")
        font = wx.Font(9, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL)
        gc.SetFont(font, wx.Colour(220, 220, 220))
        for frac, val in ((0, hi), (0.5, (lo + hi) / 2), (1, lo)):
            gc.DrawText(_fmt(val), x + bar_w + 4, top + frac * bar_h - 7)
        gc.DrawText(unit, x - 5, top - 22)
        if self.all_equal() and self.data.items:
            v = self.data.items[0]["values"].get(self.quantity)
            if v is not None:
                gc.DrawText(_("tutti uguali:"), x - 30, top + bar_h + 8)
                gc.DrawText(_fmt(v) + " " + unit, x - 30, top + bar_h + 22)

    # --- Interazione ---
    def on_wheel(self, event):
        f = 1.2 if event.GetWheelRotation() > 0 else 1 / 1.2
        mx, my = event.GetPosition()
        x, y = self.to_mm(mx, my)
        self.scale *= f
        self.offset = (mx - x * self.scale, my - y * self.scale)
        self.Refresh()

    def on_down(self, event):
        self._drag = (event.GetPosition(), self.offset)
        self.CaptureMouse()

    def on_up(self, event):
        self._drag = None
        if self.HasCapture():
            self.ReleaseMouse()

    def on_motion(self, event):
        pos = event.GetPosition()
        if self._drag and event.Dragging():
            (sx, sy), (ox, oy) = self._drag
            self.offset = (ox + pos[0] - sx, oy + pos[1] - sy)
            self.Refresh()
            return
        x, y = self.to_mm(*pos)
        self.on_hover(self.nearest(x, y))

    def nearest(self, x, y):
        """Elemento colorato sotto il mouse (entro qualche pixel), o None."""
        tol = 6 / self.scale
        best, best_d = None, None
        for it in self.data.items:
            if it["kind"] == "track":
                x0, y0, x1, y1, w = it["seg"]
                d = _dist_seg(x, y, x0, y0, x1, y1) - w / 2
            else:
                vx, vy, r = it["via"]
                d = math.hypot(x - vx, y - vy) - r
            if d <= tol and (best_d is None or d < best_d):
                best, best_d = it, d
        return best


class MapFrame(wx.Frame):
    """Finestra con menu della grandezza, mappa e riga di lettura."""

    def __init__(self, parent, data):
        super().__init__(parent, title=_(data.title), size=(1100, 700))
        panel = wx.Panel(self)
        top = wx.BoxSizer(wx.HORIZONTAL)
        top.Add(wx.StaticText(panel, label=_("Colora per:")), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.choice = wx.Choice(panel, choices=[f"{_(n)} ({u})" for n, u in data.quantities])  # nome tradotto
        self.choice.SetSelection(0)
        top.Add(self.choice, 0, wx.RIGHT, 12)
        fit_btn = wx.Button(panel, label=_("Inquadra"))
        top.Add(fit_btn, 0)
        top.Add(wx.StaticText(panel, label=_("   Rotella = zoom, trascina = sposta, mouse sopra = valori")),
                0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 12)

        self.info = wx.StaticText(panel, label="")
        self.map = MapPanel(panel, data, self.show_info)
        self.choice.Bind(wx.EVT_CHOICE, self.on_choice)
        fit_btn.Bind(wx.EVT_BUTTON, lambda e: (self.map.fit(), self.map.Refresh()))

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(top, 0, wx.ALL, 8)
        sizer.Add(self.map, 1, wx.EXPAND)
        sizer.Add(self.info, 0, wx.ALL, 8)
        panel.SetSizer(sizer)
        self.data = data

    def on_choice(self, event):
        self.map.quantity = self.data.quantities[self.choice.GetSelection()][0]
        self.map.Refresh()

    def show_info(self, item):
        self.info.SetLabel(_(item["label"]) if item else "")


def _fmt(v):
    """Numero compatto per la scala dei colori."""
    a = abs(v)
    if a == 0:
        return "0"
    if a >= 100:
        return f"{v:.0f}"
    if a >= 1:
        return f"{v:.3g}" if a < 10 else f"{v:.1f}"
    return f"{v:.3g}"


def _dist_seg(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    u = 0.0 if L2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
    return math.hypot(px - ax - u * dx, py - ay - u * dy)
