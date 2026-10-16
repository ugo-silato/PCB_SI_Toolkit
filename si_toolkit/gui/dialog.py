"""
Main plugin dialog: a window with a Notebook (tabs), one per analysis
module (Layout checks, Return Path, DC Current, Impedance, Diff. pairs,
Crosstalk, openEMS), plus the Options and Help tabs.

The UI texts are written in Italian and translated at runtime with _()
(see common/i18n.py and common/i18n_en.py).
"""
import math
import os

import pcbnew
import wx
import wx.html  # HTML pages (Help, Check openEMS)

# All the analysis modules are imported HERE, at load time: KiCad's
# "Refresh plugins" reloads only the modules imported when the plugin is
# loaded, so a module imported later inside a function would stay in memory
# in its old version after an update.
from ..common import project_data
from ..common.version import VERSION
from ..analysis import (crosstalk, dc_current, impedance, layout_check, net_path, openems_check,
                        openems_export, return_map, return_path)
from ..common import geometry
from ..common import i18n
from ..common.settings_path import settings_path
from ..common.i18n import _
from . import help_text, mapview
from ..analysis import load_estimate

# Thresholds on the current/IPC-2221 limit ratio: above CRITICAL the limit is
# exceeded, above WARNING it is getting close (80%)
CRITICAL_RATIO = 1.0
WARNING_RATIO = 0.8


# --- Settings saved to file (in the KiCad user folder, see
# common/settings_path.py: this way they survive plugin updates) ---
SETTINGS_PATH = settings_path()


def load_settings():
    """Reads the saved settings; empty dictionary if the file is missing or broken."""
    import json

    try:
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_setting(key, value):
    """Updates a single setting and rewrites the file."""
    import json

    data = load_settings()
    data[key] = value
    try:
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass  # settings cannot be saved: not a blocking error


def persist(ctrl, key):
    """
    Links a text box to the settings file: on opening it loads the saved
    value (if any), and saves it at every change.
    """
    saved = load_settings().get(key)
    if saved is not None:
        ctrl.ChangeValue(str(saved))  # ChangeValue does not generate EVT_TEXT
    ctrl.Bind(wx.EVT_TEXT, lambda evt: (save_setting(key, ctrl.GetValue()), evt.Skip()))


def persist_check(ctrl, key):
    """Like persist(), but for a check box."""
    saved = load_settings().get(key)
    if saved is not None:
        ctrl.SetValue(bool(saved))  # SetValue does not generate EVT_CHECKBOX
    ctrl.Bind(wx.EVT_CHECKBOX, lambda evt: (save_setting(key, ctrl.GetValue()), evt.Skip()))


def persist_all(panel, prefix, skip=()):
    """
    Makes all the text boxes (attributes ending in '_ctrl') and check boxes
    ('_check') of a tab persistent: key = prefix + attribute name. Choices
    tied to the board (net, pad) are not saved.
    """
    for name, obj in list(vars(panel).items()):
        if name in skip:
            continue
        # Controls borrowed from another tab (e.g. Options): the tab that owns
        # them already saves them
        if isinstance(obj, wx.Window) and obj.GetParent() is not panel:
            continue
        key = f"{prefix}_{name}"
        if name.endswith("_ctrl") and isinstance(obj, wx.TextCtrl):
            persist(obj, key)
        elif name.endswith("_check") and isinstance(obj, wx.CheckBox):
            persist_check(obj, key)


def add_help_button(panel, row, key):
    """
    "?" button at the end of a row of buttons: opens a small window with the
    drawing and the explanation of the tab (same part as the Help tab).
    """
    btn = wx.Button(panel, label="?", size=(28, -1))
    btn.SetToolTip(_("Cosa fa questa scheda e quali dati inserire"))
    btn.Bind(wx.EVT_BUTTON, lambda evt: show_tab_help(panel, key))
    row.Add(btn, 0, wx.LEFT, 12)


def show_tab_help(parent, key):
    """Window with only the help section of one tab."""
    dlg = wx.Dialog(parent, title=_("Aiuto"), size=(700, 560),
                    style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
    html = wx.html.HtmlWindow(dlg, style=wx.html.HW_SCROLLBAR_AUTO)
    html.SetPage(help_text.section(i18n.LANG, key))
    sizer = wx.BoxSizer(wx.VERTICAL)
    sizer.Add(html, 1, wx.EXPAND | wx.ALL, 5)
    ok = wx.Button(dlg, wx.ID_OK, "OK")
    sizer.Add(ok, 0, wx.ALIGN_RIGHT | wx.ALL, 8)
    dlg.SetSizer(sizer)
    dlg.ShowModal()
    dlg.Destroy()


def default_runs_dir():
    """
    Default folder for the openEMS simulations: outside OneDrive (which locks
    files while syncing them), in the local AppData.
    """
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "SI_Toolkit", "openems_runs")


def make_light_images():
    """
    List of traffic-light icons (0 green, 1 yellow, 2 red, 3 grey = excluded
    row) for the "Status" columns. Drawn with wx, no external files.
    """
    images = wx.ImageList(14, 14)
    for colour in ((60, 180, 75), (245, 190, 30), (220, 50, 47), (190, 190, 190)):
        bmp = wx.Bitmap(14, 14)
        dc = wx.MemoryDC(bmp)
        dc.SetBackground(wx.Brush(wx.WHITE))
        dc.Clear()
        dc.SetBrush(wx.Brush(wx.Colour(*colour)))
        dc.SetPen(wx.Pen(wx.Colour(80, 80, 80), 1))
        dc.DrawCircle(7, 7, 6)
        dc.SelectObject(wx.NullBitmap)
        # The white background becomes transparent
        bmp.SetMask(wx.Mask(bmp, wx.WHITE))
        images.Add(bmp)
    return images


class SIToolkitDialog(wx.Dialog):
    def __init__(self, parent, board):
        # Interface language (Options tab): must be set before creating any
        # text
        i18n.set_language(load_settings().get("lang", "en"))  # default: English
        super().__init__(
            parent,
            # Name and version in the title bar (version from common/version.py)
            title=f"{_('PCB Signal Integrity Toolkit')} {VERSION}",
            size=(860, 520),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self.board = board
        # Graphic markers (PCB_SHAPE) created by the last analysis, to be
        # removed when the dialog is closed or the analysis is run again
        self.markers = []

        notebook = wx.Notebook(self)
        # The Options tab is created FIRST (the other tabs use its controls)
        # but shown at the end, before Help
        self.options = OptionsPanel(notebook, self)
        # Layout checks first: the whole-board overview, then the detailed tabs
        notebook.AddPage(LayoutCheckPanel(notebook, self), _("Controlli layout"))
        notebook.AddPage(ReturnPathPanel(notebook, self), _("Return Path"))
        notebook.AddPage(DcCurrentPanel(notebook, self), _("Corrente DC"))
        notebook.AddPage(ImpedancePanel(notebook, self), _("Impedenza"))
        notebook.AddPage(DiffPairPanel(notebook, self), _("Coppie diff."))
        notebook.AddPage(CrosstalkPanel(notebook, self), _("Crosstalk"))
        notebook.AddPage(OpenEMSPanel(notebook, self), _("openEMS"))
        notebook.AddPage(self.options, _("Opzioni"))
        notebook.AddPage(HelpPanel(notebook), _("Aiuto"))

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(notebook, 1, wx.EXPAND | wx.ALL, 5)
        self.SetSizer(sizer)

        # Minimum size = the one the widest tab needs to show all its fields
        # and buttons (the Notebook computes it as the maximum over its pages),
        # without exceeding the screen
        best = self.GetBestSize()
        idx = wx.Display.GetFromWindow(self)
        area = wx.Display(idx if idx != wx.NOT_FOUND else 0).GetClientArea()
        min_w = min(best.width, area.width)
        min_h = min(max(best.height, 420), area.height)
        self.SetMinSize((min_w, min_h))
        self._restore_geometry(min_w, min_h)

        # A non-modal dialog closed with the X is only hidden by default: we
        # destroy it ourselves, so Destroy() cleans up the markers and the next
        # run of the plugin creates a new one.
        self.Bind(wx.EVT_CLOSE, self.on_close)

    def _restore_geometry(self, min_w, min_h):
        """
        Restores the window to the position and size of the last time (saved in
        the settings at closing). If that screen is gone (e.g. a disconnected
        monitor) the window is centred.
        """
        rect = load_settings().get("window_rect")
        try:
            x, y, w, h = (int(v) for v in rect)
        except Exception:
            x = y = None
            w, h = 860, 520
        self.SetSize((max(w, min_w), max(h, min_h)))
        # The title bar must fall on an existing screen
        if x is not None and wx.Display.GetFromPoint(wx.Point(x + 60, y + 15)) != wx.NOT_FOUND:
            self.SetPosition((x, y))
        else:
            self.CentreOnParent()

    def _save_geometry(self):
        """Saves the window position and size (not when minimized)."""
        try:
            if not self.IsIconized() and not self.IsMaximized():
                r = self.GetRect()
                save_setting("window_rect", [r.x, r.y, r.width, r.height])
        except Exception:
            pass  # not serious: next time it opens with the default values

    def on_close(self, event):
        self.Destroy()

    def Destroy(self):
        # Before closing: position and size for the next opening
        self._save_geometry()
        # Cleanup of the graphic markers when the dialog closes: if the user
        # closes it without pressing "Clear overlay" no leftover mark must
        # remain on the board.
        if self.markers:
            return_path.clear_highlight(self.board, self.markers)
            self.markers = []
        return super().Destroy()


class OptionsPanel(wx.Panel):
    """
    "Options" tab: settings shared by several tabs (stackup, ground, DC
    current, openEMS) and language. The other tabs use these controls directly
    (self.er_ctrl = options.er_ctrl, etc.).
    """

    DEFAULT_PYTHON = r"D:\Users\ugosi\AppData\Local\Programs\Python\Python310\python.exe"

    def __init__(self, parent, dialog):
        super().__init__(parent)

        def grid(box_title, rows):
            """Box with a title and label/control pairs on two columns."""
            box = wx.StaticBoxSizer(wx.VERTICAL, self, _(box_title))
            g = wx.FlexGridSizer(cols=2, vgap=6, hgap=8)
            g.AddGrowableCol(1)
            for label, ctrl in rows:
                g.Add(wx.StaticText(self, label=_(label)), 0, wx.ALIGN_CENTER_VERTICAL)
                g.Add(ctrl, 1, wx.EXPAND)
            box.Add(g, 0, wx.EXPAND | wx.ALL, 6)
            return box

        # --- General ---
        self.lang_choice = wx.Choice(self, choices=["Italiano", "English"])
        self.lang_choice.SetSelection(1 if i18n.LANG == "en" else 0)
        self.lang_choice.Bind(wx.EVT_CHOICE, self.on_language)
        lang_note = wx.StaticText(self, label=_("La lingua si applica alla prossima apertura del plugin."))

        # --- Stackup and ground (Impedance, Diff. pairs, openEMS) ---
        # "auto" = values read from the board stackup
        self.er_ctrl = wx.TextCtrl(self, value="auto", size=(70, -1))
        self.h_ctrl = wx.TextCtrl(self, value="auto", size=(70, -1))
        self.mask_check = wx.CheckBox(self, label=_("Considera il solder mask (layer esterni)"))
        self.mask_check.SetValue(True)
        # Net acting as ground for the automatic detection
        self.gnd_ctrl = wx.TextCtrl(self, value="GND", size=(70, -1))

        # --- DC Current ---
        self.copper_ctrl = wx.TextCtrl(self, value="auto", size=(70, -1))
        self.plating_ctrl = wx.TextCtrl(self, value="25", size=(70, -1))
        # Allowed temperature rise, for the IPC-2221 current limit
        self.dt_ctrl = wx.TextCtrl(self, value="10", size=(70, -1))
        # Copper zones as zero-resistance connections (see dc_current)
        self.zones_check = wx.CheckBox(self, label=_("Zone di rame = resistenza nulla"))
        self.zones_check.SetValue(True)

        # --- openEMS ---
        self.python_ctrl = wx.TextCtrl(self, value=self.DEFAULT_PYTHON, size=(420, -1))
        # Folder where openEMS is installed (contains the DLLs)
        self.oe_ctrl = wx.TextCtrl(self, value=r"D:\Programmi\openEMS", size=(420, -1))
        self.runs_ctrl = wx.TextCtrl(self, value=default_runs_dir(), size=(420, -1))
        browse_btn = wx.Button(self, label=_("Sfoglia..."))
        browse_btn.Bind(wx.EVT_BUTTON, self.on_browse_runs)
        runs_row = wx.BoxSizer(wx.HORIZONTAL)
        runs_row.Add(self.runs_ctrl, 1, wx.RIGHT, 5)
        runs_row.Add(browse_btn, 0)
        self.mesh_ctrl = wx.TextCtrl(self, value="0.1", size=(70, -1))
        self.margin_ctrl = wx.TextCtrl(self, value="3", size=(70, -1))

        # Values saved by previous versions (keys of the old openEMS tab) are
        # recovered once
        data = load_settings()
        for new, old in (("opt_python_ctrl", "openems_python"), ("opt_oe_ctrl", "openems_path"),
                         ("opt_runs_ctrl", "openems_runs_dir"), ("opt_mesh_ctrl", "openems_mesh"),
                         ("opt_margin_ctrl", "openems_margin")):
            if new not in data and old in data:
                save_setting(new, data[old])

        left = wx.BoxSizer(wx.VERTICAL)
        gen = wx.StaticBoxSizer(wx.VERTICAL, self, _("Generale"))
        lrow = wx.BoxSizer(wx.HORIZONTAL)
        lrow.Add(wx.StaticText(self, label=_("Lingua / Language:")), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        lrow.Add(self.lang_choice, 0)
        gen.Add(lrow, 0, wx.ALL, 6)
        gen.Add(lang_note, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
        left.Add(gen, 0, wx.EXPAND | wx.BOTTOM, 8)
        stack_box = grid("Stackup e massa (Impedenza, Coppie diff., openEMS)",
                         [("Er (auto = stackup):", self.er_ctrl),
                          ("Dielettrico (mm, auto = stackup):", self.h_ctrl),
                          ("Net di massa:", self.gnd_ctrl)])
        stack_box.Add(self.mask_check, 0, wx.ALL, 6)
        left.Add(stack_box, 0, wx.EXPAND | wx.BOTTOM, 8)
        dc_box = grid("Corrente DC",
                      [("Rame (um, auto = stackup):", self.copper_ctrl),
                       ("Placcatura via (um):", self.plating_ctrl),
                       ("DT max ammesso (C):", self.dt_ctrl)])
        dc_box.Add(self.zones_check, 0, wx.ALL, 6)
        left.Add(dc_box, 0, wx.EXPAND)

        oe_box = grid("openEMS",
                      [("Python con openEMS:", self.python_ctrl),
                       ("Cartella openEMS:", self.oe_ctrl),
                       ("Cartella risultati:", runs_row),
                       ("Mesh (mm):", self.mesh_ctrl),
                       ("Margine attorno alla linea (mm):", self.margin_ctrl)])
        # Check of the openEMS installation (Python, modules, DLLs)
        check_btn = wx.Button(self, label=_("Verifica openEMS"))
        check_btn.SetToolTip(_("Controlla Python, moduli e cartella di openEMS e dice cosa manca"))
        check_btn.Bind(wx.EVT_BUTTON, self.on_check_openems)
        check_row = wx.BoxSizer(wx.HORIZONTAL)
        check_row.Add(check_btn, 0, wx.RIGHT, 8)
        check_row.Add(wx.StaticText(self, label=_("(il controllo richiede alcuni secondi)")), 0,
                      wx.ALIGN_CENTER_VERTICAL)
        oe_box.Add(check_row, 0, wx.ALL, 6)

        main = wx.BoxSizer(wx.HORIZONTAL)
        main.Add(left, 0, wx.EXPAND | wx.ALL, 10)
        main.Add(oe_box, 1, wx.EXPAND | wx.TOP | wx.RIGHT | wx.BOTTOM, 10)
        self.SetSizer(main)
        # All values remembered between sessions
        persist_all(self, "opt")

    def on_check_openems(self, event):
        """Check openEMS button: shows any unexpected error."""
        try:
            self._check_openems()
        except Exception:
            import traceback

            wx.MessageBox(traceback.format_exc(), _("Verifica openEMS"), wx.OK | wx.ICON_ERROR, self)

    def _check_openems(self):
        """
        Checks the openEMS installation and shows the report. If installable
        packages are missing (pip or openEMS .whl files) it offers to install
        them, after confirmation, in a visible window.
        """
        python_exe = self.python_ctrl.GetValue().strip()
        oe_dir = self.oe_ctrl.GetValue().strip()
        # "Please wait" popup: the check starts the external Python and imports
        # openEMS, it takes a few seconds
        busy = wx.BusyCursor()
        info = wx.BusyInfo(_("Verifica di openEMS in corso, attendere alcuni secondi..."), self)
        wx.GetApp().Yield()  # draws the popup right away, before blocking in the check
        try:
            res = openems_check.check(python_exe, oe_dir)
        finally:
            del info
            del busy

        # HTML report: green = ok, orange = warning, red = error
        colors = {"ok": "#1e8449", "warn": "#b9770e", "err": "#c0392b"}
        marks = {"ok": "&#10004;", "warn": "!", "err": "&#10008;"}
        rows = "".join(
            f'<p><font color="{colors[st]}"><b>{marks[st]}</b></font> {txt}</p>'
            for st, txt in res["lines"]
        )
        head = _("Tutto pronto: la scheda openEMS puo' simulare.") if res["ok"] else \
            _("Ci sono problemi da risolvere (vedi sotto). Dopo le correzioni premi di nuovo Verifica.")
        can_install = bool(res["pip"] or res["wheels"])
        if can_install:
            items = [os.path.basename(w) for w in res["wheels"]] + res["pip"]
            rows += "<p>" + _("Si possono installare automaticamente: {0}").format(", ".join(items)) + "</p>"

        dlg = wx.Dialog(self, title=_("Verifica openEMS"), size=(720, 460),
                        style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        html = wx.html.HtmlWindow(dlg, style=wx.html.HW_SCROLLBAR_AUTO)
        html.SetPage(f"<h4>{head}</h4>{rows}")
        btns = wx.BoxSizer(wx.HORIZONTAL)
        if can_install:
            inst = wx.Button(dlg, label=_("Installa pacchetti mancanti"))
            inst.Bind(wx.EVT_BUTTON, lambda e: self._install_missing(dlg, python_exe, res))
            btns.Add(inst, 0, wx.RIGHT, 8)
        btns.Add(wx.Button(dlg, wx.ID_OK, "OK"), 0)
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(html, 1, wx.EXPAND | wx.ALL, 5)
        sizer.Add(btns, 0, wx.ALIGN_RIGHT | wx.ALL, 8)
        dlg.SetSizer(sizer)
        dlg.ShowModal()
        dlg.Destroy()

    def _install_missing(self, parent, python_exe, res):
        """Installs (after confirmation) the missing packages in a visible window."""
        import subprocess
        import sys

        cmd = openems_check.install_command(python_exe, res["pip"], res["wheels"])
        msg = _("Verra' eseguito questo comando (serve Internet per i pacchetti da pip):\n\n{0}\n\nProcedere?").format(
            " ".join(f'"{c}"' if " " in c else c for c in cmd))
        if wx.MessageBox(msg, _("Installa pacchetti mancanti"), wx.YES_NO | wx.ICON_QUESTION, parent) != wx.YES:
            return
        if sys.platform.startswith("win"):
            # cmd /k: the window stays open at the end, to read the outcome
            subprocess.Popen(["cmd", "/k"] + cmd, creationflags=subprocess.CREATE_NEW_CONSOLE)
        else:
            subprocess.Popen(cmd)
        wx.MessageBox(_("Installazione avviata in una finestra separata. Quando ha finito, "
                        "premi di nuovo 'Verifica openEMS'."), _("Verifica openEMS"), wx.OK, parent)

    def on_language(self, event):
        """Saves the chosen language: applies from the next opening of the plugin."""
        save_setting("lang", "en" if self.lang_choice.GetSelection() == 1 else "it")

    def on_browse_runs(self, event):
        """Chooses the openEMS results folder with the Windows dialog."""
        start = self.runs_ctrl.GetValue().strip() or default_runs_dir()
        dlg = wx.DirDialog(self, _("Cartella per i risultati di openEMS"), start)
        if dlg.ShowModal() == wx.ID_OK:
            self.runs_ctrl.SetValue(dlg.GetPath())  # SetValue also saves the setting
        dlg.Destroy()


class HelpPanel(wx.Panel):
    """"Help" tab: essential guide, in the chosen language."""

    def __init__(self, parent):
        super().__init__(parent)
        html = wx.html.HtmlWindow(self, style=wx.html.HW_SCROLLBAR_AUTO)
        html.SetPage(help_text.page(i18n.LANG))
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(html, 1, wx.EXPAND | wx.ALL, 5)
        self.SetSizer(sizer)


class PlaceholderPanel(wx.Panel):
    """Placeholder tab for modules not implemented yet."""

    def __init__(self, parent, module_name):
        super().__init__(parent)
        sizer = wx.BoxSizer(wx.VERTICAL)
        label = wx.StaticText(
            self, label=_("Modulo \"{0}\" non ancora implementato.").format(module_name)
        )
        sizer.Add(label, 0, wx.ALL | wx.ALIGN_CENTER, 20)
        self.SetSizer(sizer)


class DcCurrentPanel(wx.Panel):
    """"DC Current" tab: how the current splits among tracks and vias."""

    def __init__(self, parent, dialog):
        super().__init__(parent)
        self.board = dialog.board
        self._pads = []  # (label, pad) of the chosen net
        self._elements = []  # results of the last calculation, like the rows

        # --- Row 1: net and input pad ---
        row1 = wx.BoxSizer(wx.HORIZONTAL)
        self.net_choice = wx.Choice(self, choices=dc_current.list_nets(self.board))
        self.net_choice.Bind(wx.EVT_CHOICE, self.on_net_changed)
        self.src_choice = wx.Choice(self)
        self.snk_choice = wx.Choice(self)
        # Changing input or output recalculates and highlights the path
        self.src_choice.Bind(wx.EVT_CHOICE, self.on_pads_changed)
        self.snk_choice.Bind(wx.EVT_CHOICE, self.on_pads_changed)
        for label, ctrl in (("Net:", self.net_choice),
                            ("Ingresso:", self.src_choice)):
            row1.Add(wx.StaticText(self, label=_(label)), 0,
                     wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
            row1.Add(ctrl, 0, wx.RIGHT, 12)

        # --- "Outputs" box: all the outputs together, each with its current.
        # On the left the pad + current are chosen and added, on the right is
        # the list. With an empty list the chosen pad is used directly with its
        # current (simple case: a single output).
        out_box = wx.StaticBoxSizer(wx.HORIZONTAL, self, _("Uscite (carichi)"))
        left = wx.BoxSizer(wx.VERTICAL)
        pick = wx.BoxSizer(wx.HORIZONTAL)
        self.current_ctrl = wx.TextCtrl(self, value="1.0", size=(60, -1))
        pick.Add(wx.StaticText(self, label=_("Pad:")), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        pick.Add(self.snk_choice, 0, wx.RIGHT, 12)
        pick.Add(wx.StaticText(self, label=_("Corrente (A):")), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        pick.Add(self.current_ctrl, 0, wx.RIGHT, 12)
        btns = wx.BoxSizer(wx.HORIZONTAL)
        for label, handler in (("Aggiungi", self.on_add_load),
                               ("Rimuovi", self.on_remove_load),
                               ("Svuota", self.on_clear_loads)):
            btn = wx.Button(self, label=_(label))
            btn.Bind(wx.EVT_BUTTON, handler)
            btns.Add(btn, 0, wx.RIGHT, 5)
        left.Add(pick, 0, wx.BOTTOM, 6)
        left.Add(btns, 0, wx.BOTTOM, 6)
        left.Add(wx.StaticText(self, label=_("Elenco vuoto = una sola uscita: il pad e la corrente scelti qui.")), 0)
        # List of the outputs: pad and current
        self.loads_list = wx.ListCtrl(self, style=wx.LC_REPORT, size=(230, 95))
        self.loads_list.InsertColumn(0, _("Pad"), width=110)
        self.loads_list.InsertColumn(1, _("Corrente (A)"), width=100)
        self.loads = []  # [(label, current A)] in list order
        out_box.Add(left, 0, wx.ALL, 6)
        out_box.Add(self.loads_list, 0, wx.ALL, 6)

        # --- Row 2: model parameters ---
        # Model parameters (copper, plating, DT, zones): they are in the
        # Options tab; the same controls are used here
        opts = dialog.options
        self.copper_ctrl = opts.copper_ctrl
        self.plating_ctrl = opts.plating_ctrl
        self.dt_ctrl = opts.dt_ctrl
        self.zones_check = opts.zones_check
        # --- Row 3: buttons ---
        row3 = wx.BoxSizer(wx.HORIZONTAL)
        calc_btn = wx.Button(self, label=_("Calcola"))
        calc_btn.Bind(wx.EVT_BUTTON, self.on_calculate)
        row3.Add(calc_btn, 0, wx.RIGHT, 5)
        sel_btn = wx.Button(self, label=_("Seleziona tutti"))
        sel_btn.Bind(wx.EVT_BUTTON, self.on_select_all)
        row3.Add(sel_btn, 0, wx.RIGHT, 5)
        map_btn = wx.Button(self, label=_("Mappa a colori"))
        map_btn.Bind(wx.EVT_BUTTON, self.on_map)
        row3.Add(map_btn, 0, wx.RIGHT, 5)
        crit_btn = wx.Button(self, label=_("Seleziona critici"))
        crit_btn.Bind(wx.EVT_BUTTON, self.on_select_critical)
        row3.Add(crit_btn, 0, wx.RIGHT, 5)
        from_sel_btn = wx.Button(self, label=_("Da selezione"))
        from_sel_btn.Bind(wx.EVT_BUTTON, self.on_from_selection)
        row3.Add(from_sel_btn, 0, wx.RIGHT, 5)
        reset_btn = wx.Button(self, label=_("Reset"))
        reset_btn.Bind(wx.EVT_BUTTON, self.on_reset)
        row3.Add(reset_btn, 0)
        add_help_button(self, row3, "dc_current")

        # --- Results list (sorted by current density) ---
        self.results_list = wx.ListCtrl(self, style=wx.LC_REPORT, size=(400, 150))
        for i, (name, w) in enumerate((("Stato", 95), ("Elemento", 70), ("Layer", 80),
                                       ("V monte (mV)", 90), ("Lungh. (mm)", 80), ("Largh. (mm)", 80),
                                       ("R (mOhm)", 75), ("Corrente (A)", 90),
                                       ("Caduta (mV)", 85), ("Potenza (mW)", 90),
                                       ("Dens. (A/mm2)", 95), ("% limite", 70))):
            self.results_list.InsertColumn(i, _(name), width=w)
        self.results_list.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_row_selected)

        self._light_images = make_light_images()
        self.results_list.SetImageList(self._light_images, wx.IMAGE_LIST_SMALL)

        self.status_label = wx.StaticText(self, label=_("Scegli una net, un pad di ingresso e uno di uscita."))

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(row1, 0, wx.ALL, 10)
        sizer.Add(out_box, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        sizer.Add(row3, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        sizer.Add(self.results_list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        sizer.Add(self.status_label, 0, wx.ALL, 10)
        self.SetSizer(sizer)
        # Remember the box values between sessions
        persist_all(self, "dc")

    def on_net_changed(self, event):
        """When the net is chosen, fills the pad lists and highlights it."""
        self._load_net(self.net_choice.GetStringSelection(), highlight=True)

    def _load_net(self, net, highlight):
        """
        Fills the input/output pad lists for the given net. If 'highlight' is
        true the whole net is selected in Pcbnew (not done when the net comes
        from the user's selection, so as not to overwrite it).
        """
        self._pads = dc_current.list_pads(self.board, net)
        labels = [label for label, _pad in self._pads]
        for ctrl in (self.src_choice, self.snk_choice):
            ctrl.Set(labels)
        # The outputs list is only valid for the net it was made on
        self._set_loads([])
        if labels:
            # Default: first pad as input, last as output
            self.src_choice.SetSelection(0)
            self.snk_choice.SetSelection(len(labels) - 1)
        # Net changed: old results removed
        self._clear_results()
        if highlight:
            self._select(dc_current.net_items(self.board, net))
            self.status_label.SetLabel(_("Net {0} evidenziata ({1} pad).").format(net, len(labels)))

    def on_from_selection(self, event):
        """
        Brings into the tab what is selected in Pcbnew: the net of the selected
        track/via/pad and, if one or two pads are selected, uses them as input
        (and output) and calculates.
        """
        selected = dc_current.selected_items(self.board)
        if not selected:
            self.status_label.SetLabel(_("Niente di selezionato in Pcbnew: seleziona una traccia, una via o dei pad."))
            return
        net = selected[0].GetNetname()
        if not net or not self.net_choice.SetStringSelection(net):
            self.status_label.SetLabel(_("L'elemento selezionato non ha una net utilizzabile."))
            return
        self._load_net(net, highlight=False)

        # Selected pads (in the order Pcbnew returns them) on the net
        labels = [label for label, _p in self._pads]
        sel_pads = [dc_current.pad_label(i) for i in selected
                    if i.GetNetname() == net and dc_current.is_pad(i)]
        sel_pads = [l for l in sel_pads if l in labels]
        if sel_pads:
            self.src_choice.SetSelection(labels.index(sel_pads[0]))
        if len(sel_pads) >= 2:
            self.snk_choice.SetSelection(labels.index(sel_pads[1]))
            # With 3 or more pads: all except the first become outputs, with
            # the current written in the box (to be corrected afterwards)
            if len(sel_pads) >= 3:
                amps = self._number(self.current_ctrl, 1.0)
                self._set_loads([(l, amps) for l in sel_pads[1:]])
            self.on_calculate(event)
        else:
            self.status_label.SetLabel(
                _("Net {0} presa dalla selezione").format(net)
                + (_("; ingresso {0}. Scegli l'uscita.").format(sel_pads[0]) if sel_pads else _(". Scegli ingresso e uscita."))
            )

    def on_pads_changed(self, event):
        """Input/output chosen: calculates and highlights the part between the two pads."""
        self.on_calculate(event)

    def _clear_results(self):
        self._elements = []
        self.results_list.DeleteAllItems()

    def on_reset(self, event):
        """Clears the list, the Pcbnew selection and the message."""
        self._clear_results()
        self._select([])
        self.status_label.SetLabel(_("Scegli una net, un pad di ingresso e uno di uscita."))

    @staticmethod
    def _number(ctrl, default):
        """Reads a number from a box (accepts the decimal comma)."""
        try:
            return float(ctrl.GetValue().strip().replace(",", "."))
        except ValueError:
            return default

    def _set_loads(self, loads):
        """Replaces the outputs list and updates the table."""
        self.loads = list(loads)
        self.loads_list.DeleteAllItems()
        for label, amps in self.loads:
            idx = self.loads_list.InsertItem(self.loads_list.GetItemCount(), _(label))
            self.loads_list.SetItem(idx, 1, f"{amps:g}")

    def on_add_load(self, event):
        """Adds the chosen pad with its current to the list."""
        label = self.snk_choice.GetStringSelection()
        if not label:
            self.status_label.SetLabel(_("Scegli il pad dell'uscita."))
            return
        amps = self._number(self.current_ctrl, None)
        if amps is None or amps <= 0:
            self.status_label.SetLabel(_("Corrente non valida."))
            return
        # Same pad already present: the current is updated instead of
        # duplicating it
        loads = [(l, a) for l, a in self.loads if l != label] + [(label, amps)]
        self._set_loads(loads)
        self.on_calculate(event)

    def on_remove_load(self, event):
        """Removes the selected output from the list."""
        k = self.loads_list.GetFirstSelected()
        if k < 0:
            self.status_label.SetLabel(_("Seleziona nell'elenco l'uscita da togliere."))
            return
        self._set_loads(self.loads[:k] + self.loads[k + 1:])
        self.on_calculate(event)

    def on_clear_loads(self, event):
        """Clears the list: back to a single output."""
        self._set_loads([])
        self.on_calculate(event)

    def _loads(self):
        """
        Loads to simulate [(label, pad, current A)]: those in the list or, if the
        list is empty, the chosen pad with the current in the box.
        """
        by_label = dict(self._pads)
        if self.loads:
            return [(l, by_label[l], a) for l, a in self.loads if l in by_label]
        if self.snk_choice.GetSelection() < 0:
            raise ValueError("Scegli il pad di uscita.")
        snk_label, snk = self._pads[self.snk_choice.GetSelection()]
        return [(snk_label, snk, self._number(self.current_ctrl, 1.0))]

    def on_calculate(self, event):
        net = self.net_choice.GetStringSelection()
        if not net or self.src_choice.GetSelection() < 0:
            self.status_label.SetLabel(_("Scegli prima net, ingresso e uscita."))
            return
        src = self._pads[self.src_choice.GetSelection()][1]
        snk = self._pads[self.snk_choice.GetSelection()][1]
        try:
            loads = self._loads()
        except ValueError as exc:
            self._clear_results()
            self.status_label.SetLabel(_(str(exc)))
            return
        # Always clear the list first: if the calculation fails no rows from a
        # previous calculation must remain
        self._clear_results()
        copper_text = self.copper_ctrl.GetValue().strip().lower()
        copper_um = None if copper_text in ("", "auto") else self._number(self.copper_ctrl, None)
        try:
            result = dc_current.analyze_net(
                self.board, net, src, snk,
                current_a=self._number(self.current_ctrl, 1.0),
                loads=[(pad, amps) for _l, pad, amps in loads],
                copper_um=copper_um,
                via_plating_um=self._number(self.plating_ctrl, 25.0),
                include_zones=self.zones_check.GetValue(),
                delta_t=self._number(self.dt_ctrl, 10.0),
                report_path=os.path.join(
                    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "dc_diagnostics.txt",
                ),
            )
        except ValueError as exc:
            # Network not connected, same pads, etc.: clear message, and the
            # Pcbnew selection is removed too (no highlighted path)
            self._select([])
            self.status_label.SetLabel(_(str(exc)) + _("  [dettagli nel file dc_diagnostics.txt]"))
            self.status_label.Wrap(self.GetSize().GetWidth() - 40)
            self.Layout()
            return

        self._elements = result.elements
        self.results_list.DeleteAllItems()
        for el in result.elements:
            # Traffic light: green below 80% of the limit, yellow between 80%
            # and 100%, red from 100% up
            if el.ratio >= CRITICAL_RATIO:
                light, word = 2, "Critico"
            elif el.ratio >= WARNING_RATIO:
                light, word = 1, "Al limite"
            else:
                light, word = 0, "OK"
            idx = self.results_list.InsertItem(
                self.results_list.GetItemCount(), _(word), light
            )
            self.results_list.SetItem(idx, 1, _(el.kind))
            self.results_list.SetItem(idx, 2, _(el.layer_name))
            self.results_list.SetItem(idx, 3, f"{el.potential_v * 1000:.2f}")
            self.results_list.SetItem(idx, 4, f"{el.length_mm:.2f}" if el.kind == "Traccia" else "-")
            self.results_list.SetItem(idx, 5, f"{el.width_mm:.2f}" if el.kind == "Traccia" else "-")
            self.results_list.SetItem(idx, 6, f"{el.resistance_ohm * 1000:.2f}")
            self.results_list.SetItem(idx, 7, f"{el.current_a:.4f}")
            self.results_list.SetItem(idx, 8, f"{el.drop_v * 1000:.2f}")
            self.results_list.SetItem(idx, 9, f"{el.power_w * 1000:.2f}")
            self.results_list.SetItem(idx, 10, f"{el.density_a_mm2:.1f}")
            self.results_list.SetItem(idx, 11, f"{el.ratio * 100:.0f}%")

        n_crit = sum(1 for e in result.elements if e.ratio >= CRITICAL_RATIO)
        n_warn = sum(1 for e in result.elements if WARNING_RATIO <= e.ratio < CRITICAL_RATIO)
        # Line 1: results; line 2: notes on the model used
        line1 = (_("R totale = {0:.2f} mOhm, caduta = {1:.2f} mV, potenza = {2:.2f} mW. Oltre il limite: {3}, al limite: {4}.").format(result.total_resistance_ohm * 1000, result.total_drop_v * 1000, result.total_power_w * 1000, n_crit, n_warn))
        if len(result.load_drops) > 1:
            # Several outputs: drop from the input to each of them. The "total
            # R" is only an equivalent (worst drop / total current)
            total_i = sum(i for _l, i, _d in result.load_drops)
            line1 = (_("Ingresso {0:.3f} A. Caduta verso: ").format(total_i)
                     + ", ".join(_("{0} ({1:g} A) {2:.2f} mV").format(l, i, d * 1000) for l, i, d in result.load_drops)
                     + _(". Potenza = {0:.2f} mW. Oltre il limite: {1}, al limite: {2}.").format(result.total_power_w * 1000, n_crit, n_warn))
        line2 = result.copper_note
        if result.zones_modeled:
            line2 += ". Zone trattate come R = 0 (risultato ottimistico)."
        elif result.has_zones:
            line2 += ". ATTENZIONE: la net ha zone di rame, non considerate (risultato pessimistico)."
        self.status_label.SetLabel(_(line1) + "\n" + _(line2))
        self.Layout()
        # Highlight in Pcbnew the path taken by the current between the pads
        self._select([el.item for el in result.elements])

    def on_row_selected(self, event):
        """Click on a row: selects the track or via in Pcbnew."""
        idx = event.GetIndex()
        if 0 <= idx < len(self._elements):
            self._select([self._elements[idx].item])

    def on_select_all(self, event):
        self._select([el.item for el in self._elements])

    def on_map(self, event):
        """
        Opens the color map of the results: all the board tracks in gray as
        reference, those carrying current colored according to the chosen
        quantity (density, % of limit, voltage, current).
        """
        if not self._elements:
            self.status_label.SetLabel(_("Prima premi Calcola: la mappa mostra i risultati del calcolo."))
            return
        mm = pcbnew.ToMM
        used = {id(el.item) for el in self._elements}
        background = []
        for t in self.board.GetTracks():
            if t.Type() in (pcbnew.PCB_TRACE_T, pcbnew.PCB_ARC_T):
                a, b = t.GetStart(), t.GetEnd()
                background.append((mm(a.x), mm(a.y), mm(b.x), mm(b.y), mm(t.GetWidth())))
        pads = []
        for p in self.board.GetPads():
            box = p.GetBoundingBox()
            c = p.GetPosition()
            pads.append((mm(c.x), mm(c.y), mm(box.GetWidth()), mm(box.GetHeight())))

        items = []
        for el in self._elements:
            values = {
                "Densita' di corrente": el.density_a_mm2,
                "% del limite IPC": el.ratio * 100,
                "Tensione (IR drop)": el.potential_v * 1000,
                "Corrente": el.current_a,
            }
            label = (_("{0} su {1}:  I = {2:.3f} A,  densita' = {3:.1f} A/mm2,  {4:.0f}% del limite,  V monte = {5:.2f} mV,  caduta = {6:.2f} mV").format(_(el.kind), el.layer_name, el.current_a, el.density_a_mm2, el.ratio * 100, el.potential_v * 1000, el.drop_v * 1000))
            it = el.item
            if el.kind == "Traccia":
                a, b = it.GetStart(), it.GetEnd()
                items.append({"kind": "track",
                              "seg": (mm(a.x), mm(a.y), mm(b.x), mm(b.y), mm(it.GetWidth())),
                              "values": values, "label": label,
                              # Voltage shaded from GetStart() to GetEnd()
                              "grad": {"Tensione (IR drop)": (el.v_start * 1000, el.v_end * 1000)}})
            else:
                c = it.GetPosition()
                r = mm(it.GetBoundingBox().GetWidth()) / 2
                items.append({"kind": "via", "via": (mm(c.x), mm(c.y), r),
                              "values": values, "label": label})

        # References for the fixed scales: density at the IPC limit (the lowest
        # among the elements: the most conservative) and total current
        limits = [el.density_a_mm2 / el.ratio for el in self._elements if el.ratio > 0]
        density_at_limit = min(limits) if limits else max(el.density_a_mm2 for el in self._elements)
        try:
            loads = self._loads()
        except ValueError:
            loads = []
        total_current = sum(a for _l, _p, a in loads) or max(el.current_a for el in self._elements)

        # Markers on the current input (green) and output (red) pads
        markers = []
        k = self.src_choice.GetSelection()
        if 0 <= k < len(self._pads):
            label, pad = self._pads[k]
            c = pad.GetPosition()
            markers.append((mm(c.x), mm(c.y), _("IN {0}").format(label), (60, 210, 90)))
        # One OUT marker for every output, with its current
        for label, pad, amps in loads:
            c = pad.GetPosition()
            markers.append((mm(c.x), mm(c.y), _("OUT {0} {1:g} A").format(label, amps), (235, 70, 60)))

        data = mapview.MapData(
            _("Mappa corrente DC - net {0}").format(self.net_choice.GetStringSelection()),
            background, pads, items,
            [("Densita' di corrente", "A/mm2"), ("% del limite IPC", "%"),
             ("Tensione (IR drop)", "mV"), ("Corrente", "A")],
            markers=markers,
            zero_based=("Densita' di corrente", "% del limite IPC", "Corrente"),
            fixed_ranges={
                # % of limit: 0 = blue, 100% = orange-red, 120% = full red
                "% del limite IPC": (0.0, 120.0),
                # Density: from 0 to the density matching the IPC limit of the
                # analyzed tracks (red means "at the limit")
                "Densita' di corrente": (0.0, density_at_limit),
                # Current: from 0 to the total current set
                "Corrente": (0.0, total_current),
            },
        )
        frame = mapview.MapFrame(wx.GetTopLevelParent(self), data)
        frame.Show()

    def on_select_critical(self, event):
        """Selects in Pcbnew only the elements at or above the limit."""
        critical = [el.item for el in self._elements if el.ratio >= WARNING_RATIO]
        if not critical:
            self.status_label.SetLabel(_("Nessun elemento vicino al limite di corrente."))
            return
        self._select(critical)
        self.status_label.SetLabel(_("Selezionati {0} elementi critici o vicini al limite.").format(len(critical)))

    def _select(self, items):
        try:
            # Deselects tracks, vias and pads, then selects the given elements
            for it in list(self.board.GetTracks()) + list(self.board.GetPads()):
                if it.IsSelected():
                    it.ClearSelected()
            for it in items:
                it.SetSelected()
            pcbnew.Refresh()
        except Exception as exc:
            self.status_label.SetLabel(_("Impossibile selezionare: {0}").format(exc))


class ImpedancePanel(wx.Panel):
    """"Impedance" tab: Z0 of the tracks from the board stackup."""

    def __init__(self, parent, dialog):
        super().__init__(parent)
        self.board = dialog.board
        self._groups = []  # one group per row: list of tracks (net, layer, width)

        row = wx.BoxSizer(wx.HORIZONTAL)
        self.net_filter_ctrl = wx.TextCtrl(self, value="", size=(120, -1))
        self.target_ctrl = wx.TextCtrl(self, value="50", size=(50, -1))
        self.tol_ctrl = wx.TextCtrl(self, value="10", size=(40, -1))
        # Stackup (Er, dielectric), solder mask and ground net: Options tab
        opts = dialog.options
        self.er_ctrl, self.h_ctrl = opts.er_ctrl, opts.h_ctrl
        self.gnd_ctrl, self.mask_check = opts.gnd_ctrl, opts.mask_check
        # Distance from the ground on the same layer (coplanar microstrip)
        self.gap_ctrl = wx.TextCtrl(self, value="auto", size=(45, -1))
        # Row 1: filter and target; row 2: gap and buttons
        for label, ctrl in (("Filtro net (vuoto = tutte):", self.net_filter_ctrl),
                            ("Z0 target (ohm):", self.target_ctrl),
                            ("Tolleranza dal target (%):", self.tol_ctrl)):
            row.Add(wx.StaticText(self, label=_(label)), 0,
                    wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
            row.Add(ctrl, 0, wx.RIGHT, 12)
        row_b = wx.BoxSizer(wx.HORIZONTAL)
        for label, ctrl in (("Gap massa (mm; auto, no):", self.gap_ctrl),):
            row_b.Add(wx.StaticText(self, label=_(label)), 0,
                      wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
            row_b.Add(ctrl, 0, wx.RIGHT, 12)
        calc_btn = wx.Button(self, label=_("Calcola"))
        calc_btn.Bind(wx.EVT_BUTTON, self.on_calculate)
        row_b.Add(calc_btn, 0, wx.RIGHT, 5)
        sel_btn = wx.Button(self, label=_("Da selezione"))
        sel_btn.Bind(wx.EVT_BUTTON, self.on_from_selection)
        row_b.Add(sel_btn, 0)
        add_help_button(self, row_b, "impedance")

        self.results_list = wx.ListCtrl(self, style=wx.LC_REPORT, size=(400, 150))
        for i, (name, w) in enumerate((("Stato", 95), ("Net", 150), ("Layer", 70),
                                       ("Tipo", 85), ("Largh. (mm)", 85),
                                       ("Lungh. tot. (mm)", 110), ("Z0 (ohm)", 80),
                                       ("Gap massa (mm)", 105), ("Piano sotto", 85),
                                       ("Largh. per target (mm)", 150),
                                       ("Gap per target (mm)", 140))):
            self.results_list.InsertColumn(i, _(name), width=w)
        self._light_images = make_light_images()
        self.results_list.SetImageList(self._light_images, wx.IMAGE_LIST_SMALL)
        self.results_list.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_row_selected)

        self.status_label = wx.StaticText(
            self, label=_("Premi Calcola: l'impedenza si ricava dallo stackup della scheda.")
        )

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(row, 0, wx.ALL, 10)
        sizer.Add(row_b, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        sizer.Add(self.results_list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        sizer.Add(self.status_label, 0, wx.ALL, 10)
        self.SetSizer(sizer)
        # Remember the box values between sessions
        persist_all(self, "imp")

    @staticmethod
    def _number(ctrl, default):
        try:
            return float(ctrl.GetValue().strip().replace(",", "."))
        except ValueError:
            return default

    def on_from_selection(self, event):
        """Sets the filter to the nets of the selected tracks and calculates."""
        nets = sorted({t.GetNetname() for t in self.board.GetTracks()
                       if t.IsSelected() and t.GetNetname()})
        if not nets:
            self.status_label.SetLabel(_("Niente di selezionato in Pcbnew: seleziona una o piu' tracce."))
            return
        # The filter is a substring: several nets are listed separated by |
        self.net_filter_ctrl.SetValue("|".join(nets))
        self.on_calculate(event)

    def on_calculate(self, event):
        target = self._number(self.target_ctrl, 50.0)
        tol = self._number(self.tol_ctrl, 10.0) / 100.0
        wanted = [f.strip().upper() for f in self.net_filter_ctrl.GetValue().split("|") if f.strip()]

        # Er and dielectric thickness: "auto" uses the board values
        er_text = self.er_ctrl.GetValue().strip().lower()
        h_text = self.h_ctrl.GetValue().strip().lower()
        er_override = None if er_text in ("", "auto") else self._number(self.er_ctrl, None)
        h_mm = None if h_text in ("", "auto") else self._number(self.h_ctrl, None)
        # Gap from the coplanar ground: "no" = no ground next to the track,
        # "auto" = measured by the plugin for each group of tracks
        gap_text = self.gap_ctrl.GetValue().strip().lower()
        gap_auto = gap_text in ("", "auto")
        gap_manual = None if gap_auto or gap_text in ("no", "0") else self._number(self.gap_ctrl, None)
        ground_filter = self.gnd_ctrl.GetValue().strip() or "GND"
        stackup, stackup_note = impedance.read_stackup(
            self.board, er_override, h_mm * 1e-3 if h_mm else None
        )
        if not stackup:
            self.status_label.SetLabel(
                _("Impossibile ricavare lo stackup: servono almeno due layer di rame.")
            )
            return
        stack = list(self.board.GetEnabledLayers().CuStack())
        outer = {stack[0], stack[-1]} if stack else set()
        # Source of the solder mask data (for the message at the bottom)
        masks = [stackup.get(l, {}).get("mask") for l in outer]
        if any(masks):
            m = next(x for x in masks if x)
            mask_note = _("da stackup ({0:.0f} um, Er {1:.1f})").format(m[0] * 1e6, m[1])
        else:
            mask_note = "di default (10 um, Er 3,3: non presente nello stackup)"

        # Group the tracks by (net, layer, width)
        groups = {}
        for t in self.board.GetTracks():
            if t.Type() != pcbnew.PCB_TRACE_T:
                continue
            net = t.GetNetname()
            if wanted and not any(w in net.upper() for w in wanted):
                continue
            groups.setdefault((net, t.GetLayer(), t.GetWidth()), []).append(t)

        self.results_list.DeleteAllItems()
        self._groups = []
        n_bad = 0
        zone_cache = {}  # ground zones per layer, reused across groups
        busy = wx.BusyCursor()  # the ground detection can take a few seconds
        for (net, layer, width), tracks in sorted(
            groups.items(), key=lambda kv: (kv[0][0], kv[0][1], kv[0][2])
        ):
            width_m = pcbnew.ToMM(width) * 1e-3
            # Side ground and plane below: measured on the board (only for
            # outer tracks and not for the ground tracks themselves)
            gap_m, below = None, None
            if layer in outer and ground_filter.upper() not in net.upper():
                if gap_auto:
                    gap_m, below = impedance.detect_coplanar(
                        self.board, tracks, layer, ground_filter, zone_cache
                    )
                else:
                    gap_m = gap_manual * 1e-3 if gap_manual else None
                    _g, below = impedance.detect_coplanar(
                        self.board, tracks, layer, ground_filter, zone_cache
                    )
            kind, z0, w_target, g_target, note = impedance.analyze_layer(
                stackup, layer, width_m, outer, target, gap_m,
                solder_mask=self.mask_check.GetValue(),
            )
            length_mm = sum(pcbnew.ToMM(t.GetLength()) for t in tracks)
            if z0 is None:
                light, word = 1, "n/d"
            else:
                err = abs(z0 - target) / target
                if err <= tol:
                    light, word = 0, "OK"
                elif err <= 2 * tol:
                    light, word = 1, "Al limite"
                else:
                    light, word = 2, "Fuori"
                    n_bad += 1
            idx = self.results_list.InsertItem(self.results_list.GetItemCount(), _(word), light)
            self.results_list.SetItem(idx, 1, _(net))
            self.results_list.SetItem(idx, 2, _(self.board.GetLayerName(layer)))
            self.results_list.SetItem(idx, 3, _(kind))
            self.results_list.SetItem(idx, 4, f"{pcbnew.ToMM(width):.3f}")
            self.results_list.SetItem(idx, 5, f"{length_mm:.1f}")
            self.results_list.SetItem(idx, 6, f"{z0:.1f}" if z0 else (_(note or "n/d")))
            self.results_list.SetItem(idx, 7, f"{gap_m * 1e3:.2f}" if gap_m else "-")
            # If the plane below is partly missing, the computed impedance is
            # not reliable
            self.results_list.SetItem(
                idx, 8, f"{below * 100:.0f}%" if below is not None else "-"
            )
            self.results_list.SetItem(
                idx, 9, f"{w_target * 1e3:.3f}" if w_target else "-"
            )
            self.results_list.SetItem(
                idx, 10, f"{g_target * 1e3:.3f}" if g_target else "-"
            )
            self._groups.append(tracks)
        del busy

        self.status_label.SetLabel(
            _("{0} gruppi (net/layer/larghezza), {1} fuori tolleranza rispetto a {2:g} ohm.\nStackup: {3}. Se 'Piano sotto' e' sotto circa il 90% il valore non e' affidabile. Calcolo con risolutore di campo 2D (quasi-TEM)").format(len(self._groups), n_bad, target, stackup_note)
            + (_(", solder mask {0}.").format(mask_note) if self.mask_check.GetValue() else _(", senza solder mask."))
        )
        self.Layout()

    def on_row_selected(self, event):
        """Click on a row: selects the tracks of the group in Pcbnew."""
        idx = event.GetIndex()
        if not 0 <= idx < len(self._groups):
            return
        try:
            for t in self.board.GetTracks():
                if t.IsSelected():
                    t.ClearSelected()
            for t in self._groups[idx]:
                t.SetSelected()
            pcbnew.Refresh()
        except Exception as exc:
            self.status_label.SetLabel(_("Impossibile selezionare: {0}").format(exc))


class DiffPairPanel(wx.Panel):
    """"Diff. pairs" tab: differential impedance of track pairs."""

    def __init__(self, parent, dialog):
        super().__init__(parent)
        self.board = dialog.board
        self._rows = []  # for each row: tracks to select (the two nets on the layer)
        self._manual_pair = None  # pair chosen with "From selection" (any names)

        row = wx.BoxSizer(wx.HORIZONTAL)
        self.filter_ctrl = wx.TextCtrl(self, value="", size=(120, -1))
        self.target_ctrl = wx.TextCtrl(self, value="100", size=(50, -1))
        self.tol_ctrl = wx.TextCtrl(self, value="10", size=(40, -1))
        # Stackup, solder mask and ground net: Options tab
        opts = dialog.options
        self.er_ctrl, self.h_ctrl = opts.er_ctrl, opts.h_ctrl
        self.gnd_ctrl, self.mask_check = opts.gnd_ctrl, opts.mask_check
        for label, ctrl in (("Filtro coppia (vuoto = tutte):", self.filter_ctrl),
                            ("Zdiff target (ohm):", self.target_ctrl),
                            ("Tolleranza dal target (%):", self.tol_ctrl)):
            row.Add(wx.StaticText(self, label=_(label)), 0,
                    wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
            row.Add(ctrl, 0, wx.RIGHT, 12)

        row_b = wx.BoxSizer(wx.HORIZONTAL)
        calc_btn = wx.Button(self, label=_("Rileva e calcola"))
        # The button recalculates the pairs recognized by name (clears the pair
        # chosen by hand with "From selection")
        calc_btn.Bind(wx.EVT_BUTTON, self.on_detect)
        row_b.Add(calc_btn, 0, wx.RIGHT, 5)
        sel_btn = wx.Button(self, label=_("Da selezione"))
        sel_btn.Bind(wx.EVT_BUTTON, self.on_from_selection)
        row_b.Add(sel_btn, 0)
        add_help_button(self, row_b, "diff_pair")

        self.results_list = wx.ListCtrl(self, style=wx.LC_REPORT, size=(400, 150))
        for i, (name, w) in enumerate((("Stato", 95), ("Coppia", 150), ("Layer", 65),
                                       ("Tipo", 80), ("Largh. (mm)", 85),
                                       ("Spaz. (mm)", 80), ("Accoppiata", 85),
                                       ("Zdiff (ohm)", 85), ("Z comune (ohm)", 105),
                                       ("Z0 singolo (ohm)", 115), ("Gap massa (mm)", 105),
                                       ("Piano sotto", 85), ("Delta lungh. P/N (mm)", 140),
                                       ("Largh. per target (mm)", 150))):
            self.results_list.InsertColumn(i, _(name), width=w)
        self._light_images = make_light_images()
        self.results_list.SetImageList(self._light_images, wx.IMAGE_LIST_SMALL)
        self.results_list.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_row_selected)

        self.status_label = wx.StaticText(
            self, label=_("Le coppie si riconoscono dai nomi delle net: _P/_N, DP/DM, +/-.")
        )

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(row, 0, wx.ALL, 10)
        sizer.Add(row_b, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        sizer.Add(self.results_list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        sizer.Add(self.status_label, 0, wx.ALL, 10)
        self.SetSizer(sizer)
        # Remember the box values between sessions
        persist_all(self, "diff")

    @staticmethod
    def _number(ctrl, default):
        try:
            return float(ctrl.GetValue().strip().replace(",", "."))
        except ValueError:
            return default

    def on_from_selection(self, event):
        """
        Pairs from the selected tracks. If tracks of exactly two nets are
        selected, those two nets are treated as a pair even if the names do not
        follow the _P/_N convention (useful for tracks running parallel for a
        stretch). Otherwise the pairs recognized by name are filtered.
        """
        nets = sorted({t.GetNetname() for t in self.board.GetTracks()
                       if t.IsSelected() and t.GetNetname()})
        if len(nets) == 2:
            self._manual_pair = (f"{nets[0]} / {nets[1]}", nets[0], nets[1])
            self.filter_ctrl.SetValue("")
            self.on_calculate(event)
            return
        self._manual_pair = None
        names = [base for base, p, n in impedance.detect_pairs(
            sorted({t.GetNetname() for t in self.board.GetTracks() if t.GetNetname()}))
            if p in nets or n in nets]
        if not names:
            self.status_label.SetLabel(
                _("Nessuna coppia: seleziona tracce di DUE net diverse per trattarle come coppia.")
            )
            return
        self.filter_ctrl.SetValue("|".join(names))
        self.on_calculate(event)

    def on_detect(self, event):
        self._manual_pair = None
        self.on_calculate(event)

    def on_calculate(self, event):
        target = self._number(self.target_ctrl, 100.0)
        tol = self._number(self.tol_ctrl, 10.0) / 100.0
        wanted = [f.strip().upper() for f in self.filter_ctrl.GetValue().split("|") if f.strip()]
        ground_filter = self.gnd_ctrl.GetValue().strip() or "GND"
        er_text = self.er_ctrl.GetValue().strip().lower()
        h_text = self.h_ctrl.GetValue().strip().lower()
        er_override = None if er_text in ("", "auto") else self._number(self.er_ctrl, None)
        h_mm = None if h_text in ("", "auto") else self._number(self.h_ctrl, None)

        stackup, stackup_note = impedance.read_stackup(
            self.board, er_override, h_mm * 1e-3 if h_mm else None
        )
        if not stackup:
            self.status_label.SetLabel(_("Impossibile ricavare lo stackup: servono almeno due layer di rame."))
            return
        stack = list(self.board.GetEnabledLayers().CuStack())
        outer = {stack[0], stack[-1]} if stack else set()

        # Tracks of every net, split by layer
        by_net = {}
        for t in self.board.GetTracks():
            if t.Type() == pcbnew.PCB_TRACE_T and t.GetNetname():
                by_net.setdefault(t.GetNetname(), {}).setdefault(t.GetLayer(), []).append(t)
        if self._manual_pair:
            pairs = [self._manual_pair]  # pair chosen by hand
        else:
            pairs = impedance.detect_pairs(sorted(by_net))
            if wanted:
                pairs = [p for p in pairs if any(w in p[0].upper() for w in wanted)]

        self.results_list.DeleteAllItems()
        self._rows = []
        n_bad = 0
        zone_cache = {}
        busy = wx.BusyCursor()
        for base, net_p, net_n in pairs:
            # Total length difference between the two nets (skew)
            len_p = sum(pcbnew.ToMM(t.GetLength()) for ts in by_net[net_p].values() for t in ts)
            len_n = sum(pcbnew.ToMM(t.GetLength()) for ts in by_net[net_n].values() for t in ts)
            for layer in sorted(set(by_net[net_p]) & set(by_net[net_n])):
                tp, tn = by_net[net_p][layer], by_net[net_n][layer]
                # Width: average of the prevailing width of the two nets
                wp = sorted(t.GetWidth() for t in tp)[len(tp) // 2]
                wn = sorted(t.GetWidth() for t in tn)[len(tn) // 2]
                width_m = pcbnew.ToMM((wp + wn) / 2.0) * 1e-3
                spacing, fraction, _count = geometry.pair_spacing(
                    tp, tn, pcbnew.FromMM(0.5), 60, pcbnew.FromMM(1.5)
                )
                # Layer geometry (dielectrics, copper, solder mask)
                geom = impedance.layer_geometry(stackup, layer, outer, self.mask_check.GetValue())
                model = impedance.layer_model(stackup, layer, outer)
                below = gap_m = None
                if ground_filter.upper() not in base.upper():
                    _lat, below = impedance.detect_coplanar(
                        self.board, tp, layer, ground_filter, zone_cache
                    )
                    # Side ground on the outer side of the pair (outer layers
                    # only: neglected for striplines)
                    if geom and geom["kind"] == "micro":
                        gap_m = impedance.pair_lateral_gap(
                            self.board, tp + tn, layer, ground_filter, zone_cache
                        )
                zdiff = zcomm = z0 = w_target = None
                if geom and spacing is not None:
                    s_m = spacing * 1e-9
                    # 2D field solver: odd (differential) and even (common)
                    # mode on the real cross-section of the pair
                    zdiff, zcomm, _zo, _ze = impedance.pair_field(geom, width_m, s_m, gap_m)
                    z0 = impedance.field_z0(geom, width_m, gap_m)
                    w_target = impedance.width_for_diff_field(geom, s_m, target, gap_m)
                # Traffic light on the Zdiff value; weakly coupled = not
                # reliable
                if zdiff is None:
                    light, word = 1, "n/d"
                elif fraction < 0.5:
                    light, word = 1, "Poco acc."
                else:
                    err = abs(zdiff - target) / target
                    if err <= tol:
                        light, word = 0, "OK"
                    elif err <= 2 * tol:
                        light, word = 1, "Al limite"
                    else:
                        light, word = 2, "Fuori"
                        n_bad += 1
                idx = self.results_list.InsertItem(self.results_list.GetItemCount(), _(word), light)
                self.results_list.SetItem(idx, 1, _(base))
                self.results_list.SetItem(idx, 2, _(self.board.GetLayerName(layer)))
                self.results_list.SetItem(idx, 3, _("Microstrip") if model and model[0] == "micro" else _("Stripline"))
                self.results_list.SetItem(idx, 4, f"{width_m * 1e3:.3f}")
                self.results_list.SetItem(idx, 5, f"{spacing * 1e-6:.3f}" if spacing is not None else "-")
                self.results_list.SetItem(idx, 6, f"{fraction * 100:.0f}%")
                self.results_list.SetItem(idx, 7, f"{zdiff:.1f}" if zdiff else "n/d")
                self.results_list.SetItem(idx, 8, f"{zcomm:.1f}" if zcomm else "-")
                self.results_list.SetItem(idx, 9, f"{z0:.1f}" if z0 else "-")
                self.results_list.SetItem(idx, 10, f"{gap_m * 1e3:.3f}" if gap_m else _("nessuna"))
                self.results_list.SetItem(idx, 11, f"{below * 100:.0f}%" if below is not None else "-")
                self.results_list.SetItem(idx, 12, f"{abs(len_p - len_n):.2f}")
                self.results_list.SetItem(idx, 13, f"{w_target * 1e3:.3f}" if w_target else "-")
                self._rows.append(tp + tn)
        del busy

        self.status_label.SetLabel(
            _("{0} coppie riconosciute, {1} righe (coppia/layer), {2} fuori tolleranza rispetto a {3:g} ohm.\nStackup: {4}. Risolutore di campo 2D (modi dispari/pari), con massa laterale esterna rilevata").format(len(pairs), len(self._rows), n_bad, target, stackup_note)
            + (_(" e solder mask.") if self.mask_check.GetValue() else _(", senza solder mask."))
        )
        self.Layout()

    def on_row_selected(self, event):
        """Click on a row: selects in Pcbnew the tracks of the two nets on the layer."""
        idx = event.GetIndex()
        if not 0 <= idx < len(self._rows):
            return
        try:
            for t in self.board.GetTracks():
                if t.IsSelected():
                    t.ClearSelected()
            for t in self._rows[idx]:
                t.SetSelected()
            pcbnew.Refresh()
        except Exception as exc:
            self.status_label.SetLabel(_("Impossibile selezionare: {0}").format(exc))


class CrosstalkPanel(wx.Panel):
    """"Crosstalk" tab: parallel track runs and estimated noise."""

    # Traffic-light thresholds on the estimated NEXT (fraction of the signal)
    RED = 0.05
    YELLOW = 0.02

    def __init__(self, parent, dialog):
        super().__init__(parent)
        self.board = dialog.board
        self._rows = []

        row = wx.BoxSizer(wx.HORIZONTAL)
        self.filter_ctrl = wx.TextCtrl(self, value="", size=(120, -1))
        self.exclude_ctrl = wx.TextCtrl(self, value="GND", size=(90, -1))
        self.rise_ctrl = wx.TextCtrl(self, value="1", size=(45, -1))
        for label, ctrl in (("Filtro net (vuoto = tutte):", self.filter_ctrl),
                            ("Net escluse:", self.exclude_ctrl),
                            ("Salita generale (ns):", self.rise_ctrl)):
            row.Add(wx.StaticText(self, label=_(label)), 0,
                    wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
            row.Add(ctrl, 0, wx.RIGHT, 12)

        row_b = wx.BoxSizer(wx.HORIZONTAL)
        self.spacing_ctrl = wx.TextCtrl(self, value="1", size=(45, -1))
        self.minlen_ctrl = wx.TextCtrl(self, value="2", size=(45, -1))
        # Rise times per net: "part_of_name=ns" separated by |. Nets that do
        # not match use the general time above.
        self.per_net_ctrl = wx.TextCtrl(
            self, value="SDA=300|SCL=300|TX=20|RX=20", size=(220, -1)
        )
        for label, ctrl in (("Spazio max (mm):", self.spacing_ctrl),
                            ("Tratto minimo (mm):", self.minlen_ctrl),
                            ("Tempi per net (nome=ns):", self.per_net_ctrl)):
            row_b.Add(wx.StaticText(self, label=_(label)), 0,
                      wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
            row_b.Add(ctrl, 0, wx.RIGHT, 12)
        # Buttons on their own row: with the fields on the same row the tab
        # became too wide and the buttons went off the window
        row_c = wx.BoxSizer(wx.HORIZONTAL)
        calc_btn = wx.Button(self, label=_("Calcola"))
        calc_btn.Bind(wx.EVT_BUTTON, self.on_calculate)
        row_c.Add(calc_btn, 0, wx.RIGHT, 5)
        sel_btn = wx.Button(self, label=_("Da selezione"))
        sel_btn.Bind(wx.EVT_BUTTON, self.on_from_selection)
        row_c.Add(sel_btn, 0)
        add_help_button(self, row_c, "crosstalk")

        self.results_list = wx.ListCtrl(self, style=wx.LC_REPORT, size=(400, 150))
        for i, (name, w) in enumerate((("Stato", 95), ("Net A", 140), ("Net B", 140),
                                       ("Layer", 65), ("Tratto par. (mm)", 110),
                                       ("Spazio min (mm)", 105), ("Spazio med (mm)", 110),
                                       ("Accoppiamento", 105), ("NEXT stimato", 100),
                                       ("NEXT (dB)", 80), ("Salita usata (ns)", 115))):
            self.results_list.InsertColumn(i, _(name), width=w)
        self._light_images = make_light_images()
        self.results_list.SetImageList(self._light_images, wx.IMAGE_LIST_SMALL)
        self.results_list.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_row_selected)

        self.status_label = wx.StaticText(
            self, label=_("Trova le tracce di net diverse che corrono parallele e vicine sullo stesso layer.")
        )

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(row, 0, wx.ALL, 10)
        sizer.Add(row_b, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        sizer.Add(row_c, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        sizer.Add(self.results_list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        sizer.Add(self.status_label, 0, wx.ALL, 10)
        self.SetSizer(sizer)
        # Remember the box values between sessions
        persist_all(self, "xtalk")

    @staticmethod
    def _number(ctrl, default):
        try:
            return float(ctrl.GetValue().strip().replace(",", "."))
        except ValueError:
            return default

    def on_from_selection(self, event):
        """Filters on the nets of the selected tracks and calculates."""
        nets = sorted({t.GetNetname() for t in self.board.GetTracks()
                       if t.IsSelected() and t.GetNetname()})
        if not nets:
            self.status_label.SetLabel(_("Niente di selezionato in Pcbnew: seleziona una o piu' tracce."))
            return
        self.filter_ctrl.SetValue("|".join(nets))
        self.on_calculate(event)

    def on_calculate(self, event):
        rise_s = self._number(self.rise_ctrl, 1.0) * 1e-9
        # "name=ns" rules: the first one found in the net name wins
        rules = []
        for item in self.per_net_ctrl.GetValue().split("|"):
            if "=" in item:
                key, val = item.split("=", 1)
                try:
                    rules.append((key.strip().upper(), float(val.strip().replace(",", ".")) * 1e-9))
                except ValueError:
                    pass

        def net_rise(net):
            for key, value in rules:
                if key and key in net.upper():
                    return value
            return rise_s

        spacing_nm = pcbnew.FromMM(self._number(self.spacing_ctrl, 1.0))
        min_len_mm = self._number(self.minlen_ctrl, 2.0)
        wanted = [f.strip().upper() for f in self.filter_ctrl.GetValue().split("|") if f.strip()]
        exclude = [e.strip() for e in self.exclude_ctrl.GetValue().replace(",", "|").split("|")]

        # Height above the plane and effective dielectric constant per layer
        stackup, stackup_note = impedance.read_stackup(self.board)
        stack = list(self.board.GetEnabledLayers().CuStack())
        outer = {stack[0], stack[-1]} if stack else set()

        busy = wx.BusyCursor()
        runs = crosstalk.find_parallel_runs(
            self.board, exclude=exclude, spacing_limit_nm=spacing_nm
        )
        rows = []
        for (net_a, net_b, layer), r in runs.items():
            length_mm = r["length_nm"] * 1e-6
            if length_mm < min_len_mm:
                continue
            if wanted and not any(w in net_a.upper() or w in net_b.upper() for w in wanted):
                continue
            gaps = sorted(r["gaps"])
            gap_med = gaps[len(gaps) // 2]
            width = sorted(r["widths"])[len(r["widths"]) // 2]
            model = impedance.layer_model(stackup, layer, outer) if stackup else None
            if model is None:
                continue
            kind, h, er, _t = model
            if kind == "micro":
                w_m = width * 1e-9
                eeff = (er + 1) / 2 + (er - 1) / 2 / math.sqrt(1 + 12 * h / w_m)
                h_plane = h
            else:
                eeff = er
                h_plane = h / 2.0  # stripline: distance from the closest plane
            center_m = (gap_med + width) * 1e-9  # center-to-center distance
            # The faster edge of the two counts: it is the one that disturbs
            # the most
            pair_rise = min(net_rise(net_a), net_rise(net_b))
            coupling, nxt = crosstalk.next_estimate(
                center_m, h_plane, length_mm * 1e-3, pair_rise, eeff
            )
            rows.append((nxt, net_a, net_b, layer, length_mm, gaps[0], gap_med, coupling, r["tracks"], pair_rise))
        del busy

        # From the highest noise to the lowest
        rows.sort(key=lambda r: -r[0])
        self.results_list.DeleteAllItems()
        self._rows = []
        n_red = 0
        for nxt, net_a, net_b, layer, length_mm, gap_min, gap_med, coupling, tracks, pair_rise in rows:
            if nxt >= self.RED:
                light, word = 2, "Alto"
                n_red += 1
            elif nxt >= self.YELLOW:
                light, word = 1, "Al limite"
            else:
                light, word = 0, "OK"
            idx = self.results_list.InsertItem(self.results_list.GetItemCount(), _(word), light)
            self.results_list.SetItem(idx, 1, _(net_a))
            self.results_list.SetItem(idx, 2, _(net_b))
            self.results_list.SetItem(idx, 3, _(self.board.GetLayerName(layer)))
            self.results_list.SetItem(idx, 4, f"{length_mm:.1f}")
            self.results_list.SetItem(idx, 5, f"{gap_min * 1e-6:.3f}")
            self.results_list.SetItem(idx, 6, f"{gap_med * 1e-6:.3f}")
            self.results_list.SetItem(idx, 7, f"{coupling * 100:.0f}%")
            self.results_list.SetItem(idx, 8, f"{nxt * 100:.1f}%")
            self.results_list.SetItem(idx, 9, f"{20 * math.log10(nxt):.0f}" if nxt > 0 else "-")
            self.results_list.SetItem(idx, 10, f"{pair_rise * 1e9:g}")
            self._rows.append(tracks)

        self.status_label.SetLabel(
            _("{0} tratti paralleli, {1} con disturbo alto (oltre {2:.0f}%), giallo da {3:.0f}%.\nStima di ordine di grandezza (regola di Johnson, NEXT). Stackup: {4}.").format(len(self._rows), n_red, self.RED * 100, self.YELLOW * 100, stackup_note)
        )
        self.Layout()

    def on_row_selected(self, event):
        """Click on a row: selects in Pcbnew the tracks of the parallel run."""
        idx = event.GetIndex()
        if not 0 <= idx < len(self._rows):
            return
        try:
            for t in self.board.GetTracks():
                if t.IsSelected():
                    t.ClearSelected()
            for t in self._rows[idx]:
                t.SetSelected()
            pcbnew.Refresh()
        except Exception as exc:
            self.status_label.SetLabel(_("Impossibile selezionare: {0}").format(exc))


class OpenEMSPanel(wx.Panel):
    """"openEMS" tab: EM simulation of the selected line (external Python)."""

    DEFAULT_PYTHON = r"D:\Users\ugosi\AppData\Local\Programs\Python\Python310\python.exe"

    def __init__(self, parent, dialog):
        super().__init__(parent)
        self.board = dialog.board
        self._last_dir = None

        # Python, openEMS folder, results folder, mesh, margin and ground net:
        # Options tab (the same controls are used here)
        opts = dialog.options
        self.python_ctrl, self.oe_ctrl = opts.python_ctrl, opts.oe_ctrl
        self.runs_ctrl = opts.runs_ctrl
        self.mesh_ctrl, self.margin_ctrl = opts.mesh_ctrl, opts.margin_ctrl
        self.gnd_ctrl = opts.gnd_ctrl

        row_b = wx.BoxSizer(wx.HORIZONTAL)
        self.fmax_ctrl = wx.TextCtrl(self, value="3", size=(45, -1))
        self.fmark_ctrl = wx.TextCtrl(self, value="1.575", size=(55, -1))
        for label, ctrl in (("f max (GHz):", self.fmax_ctrl),
                            ("f di interesse (GHz):", self.fmark_ctrl)):
            row_b.Add(wx.StaticText(self, label=_(label)), 0,
                      wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
            row_b.Add(ctrl, 0, wx.RIGHT, 12)
        # Tab fields remembered between sessions
        for ctrl, key in ((self.fmax_ctrl, "openems_fmax"),
                          (self.fmark_ctrl, "openems_fmark")):
            persist(ctrl, key)

        row_c = wx.BoxSizer(wx.HORIZONTAL)
        # Field recording for the animated GIFs (large files: off by default,
        # but the choice is remembered)
        self.fields_check = wx.CheckBox(self, label=_("Salva campi (GIF animate)"))
        self.fields_check.SetValue(bool(load_settings().get("openems_fields", False)))
        self.fields_check.Bind(
            wx.EVT_CHECKBOX,
            lambda evt: save_setting("openems_fields", self.fields_check.GetValue()),
        )
        row_c.Add(self.fields_check, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 12)
        # Peak signal voltage on the line: the GIF fields are rescaled to this
        # value (real V/mm)
        self.vsig_ctrl = wx.TextCtrl(self, value="1", size=(45, -1))
        self.vsig_ctrl.SetToolTip(_("Tensione di picco sulla linea per i campi delle GIF. "
                                  "Si puo' cambiare dopo, senza risimulare, con reprocess_fields.bat"))
        persist(self.vsig_ctrl, "openems_vsig")
        row_c.Add(wx.StaticText(self, label=_("Tensione segnale (V):")), 0,
                  wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        row_c.Add(self.vsig_ctrl, 0, wx.RIGHT, 12)
        # Fixed color scale in V/mm (empty = automatic): to compare GIFs made
        # with different voltages
        self.escale_ctrl = wx.TextCtrl(self, value="", size=(45, -1))
        self.escale_ctrl.SetToolTip(_("Vuoto = scala automatica. Con un valore fisso (es. 100) "
                                    "le GIF a tensioni diverse sono confrontabili a colpo d'occhio."))
        persist(self.escale_ctrl, "openems_escale")
        row_c.Add(wx.StaticText(self, label=_("Scala fissa (V/mm):")), 0,
                  wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        row_c.Add(self.escale_ctrl, 0, wx.RIGHT, 12)
        # Rise time of the step for TDR/TDT (10-90%, in ns)
        self.trise_ctrl = wx.TextCtrl(self, value="1", size=(45, -1))
        self.trise_ctrl.SetToolTip(_("Fronte del segnale digitale per TDR/TDT. Serve f max >= 1,2 / tempo di salita "
                                   "(es. 0,5 ns -> f max >= 2,4 GHz)."))
        persist(self.trise_ctrl, "openems_trise")
        row_c.Add(wx.StaticText(self, label=_("Tempo salita (ns):")), 0,
                  wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        row_c.Add(self.trise_ctrl, 0, wx.RIGHT, 12)

        # --- Button row: separate, so the buttons do not go past the window
        # edge ---
        row_e = wx.BoxSizer(wx.HORIZONTAL)
        sim_btn = wx.Button(self, label=_("Simula linea selezionata"))
        sim_btn.Bind(wx.EVT_BUTTON, self.on_simulate)
        row_e.Add(sim_btn, 0, wx.RIGHT, 5)
        # Redoes the GIFs (and TDR) of the last simulation with the current
        # voltage/scale, without simulating again (the calculation is linear)
        regif_btn = wx.Button(self, label=_("Rielabora (senza simulare)"))
        regif_btn.SetToolTip(_("Rifa' GIF e TDR dell'ultima simulazione con tensione, scala e tempo di salita attuali"))
        regif_btn.Bind(wx.EVT_BUTTON, self.on_redo_gif)
        row_e.Add(regif_btn, 0, wx.RIGHT, 5)
        open_btn = wx.Button(self, label=_("Apri cartella risultati"))
        open_btn.Bind(wx.EVT_BUTTON, self.on_open_dir)
        row_e.Add(open_btn, 0)
        add_help_button(self, row_e, "openems")

        self.status_label = wx.StaticText(
            self,
            label=_("Seleziona in Pcbnew le tracce di UNA linea (stessa net, layer esterno, "
                  "senza diramazioni) e premi Simula.\nLa simulazione gira in una finestra "
                  "separata; alla fine compaiono i grafici di S11, S21 e impedenza."),
        )

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(row_b, 0, wx.ALL, 10)
        sizer.Add(row_c, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        sizer.Add(row_e, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        sizer.Add(self.status_label, 0, wx.ALL, 10)
        self.SetSizer(sizer)

    @staticmethod
    def _number(ctrl, default):
        try:
            return float(ctrl.GetValue().strip().replace(",", "."))
        except ValueError:
            return default

    def on_simulate(self, event):
        python_exe = self.python_ctrl.GetValue().strip()
        if not os.path.exists(python_exe):
            self.status_label.SetLabel(_("Python non trovato: {0}").format(python_exe))
            return
        tracks = [t for t in self.board.GetTracks() if t.IsSelected()]
        mesh_mm = self._number(self.mesh_ctrl, 0.1)
        busy = wx.BusyCursor()
        try:
            model = openems_export.build_model(
                self.board, tracks,
                ground_filter=self.gnd_ctrl.GetValue().strip() or "GND",
                margin_mm=self._number(self.margin_ctrl, 3.0),
                # Ground sampled finely (0.05 mm), independent of the mesh: the
                # ground edge determines the gap, which matters a lot
                raster_mm=min(mesh_mm, 0.05),
            )
        except ValueError as exc:
            del busy
            self.status_label.SetLabel(_(str(exc)))
            self.Layout()
            return
        out_root = self._runs_root()
        try:
            self._last_dir = openems_export.write_and_launch(
                model, python_exe, out_root,
                self._number(self.fmax_ctrl, 3.0),
                self._number(self.fmark_ctrl, 1.575),
                mesh_mm,
                self.oe_ctrl.GetValue().strip() or r"D:\Programmi\openEMS",
                dump_fields=self.fields_check.GetValue(),
                v_signal=self._number(self.vsig_ctrl, 1.0),
                t_rise_ns=self._number(self.trise_ctrl, 1.0),
                lang=i18n.LANG,  # language of the plots
            )
        except Exception as exc:
            del busy
            self.status_label.SetLabel(_("Impossibile avviare la simulazione: {0}").format(exc))
            self.Layout()
            return
        del busy
        self.status_label.SetLabel(
            _("Simulazione avviata: linea {0} su {1}, h = {2:.3f} mm, Er = {3:.2f}, {4} strisce di massa coplanare.\nSegui l'avanzamento nella finestra nera. Risultati in: {5}").format(model['net'], model['layer'], model['h'], model['er'], len(model['ground']), self._last_dir)
            + _(self._band_warning())
        )
        self.Layout()

    def _band_warning(self):
        """Warning if f max is too low for the chosen rise time (TDR)."""
        tr = self._number(self.trise_ctrl, 1.0)
        fmax = self._number(self.fmax_ctrl, 3.0)
        need = 1.22 / tr if tr > 0 else 0  # GHz, with tr in ns
        if fmax < need:
            return (_("\nNota: per un fronte di {0:g} ns serve f max >= {1:.1f} GHz; con {2:g} GHz il TDR usera' un fronte piu' lento.").format(tr, need, fmax))
        return ""

    def _runs_root(self):
        """Folder where the simulations are created ('Results folder' box)."""
        return self.runs_ctrl.GetValue().strip() or default_runs_dir()

    def _latest_run_dir(self):
        """Folder of the last simulation: the one launched now or the most recent on disk."""
        if self._last_dir and os.path.isdir(self._last_dir):
            return self._last_dir
        root = self._runs_root()
        if not os.path.isdir(root):
            return None
        runs = sorted(d for d in os.listdir(root) if d.startswith("sim_"))  # name = date and time
        return os.path.join(root, runs[-1]) if runs else None

    def on_redo_gif(self, event):
        """
        Relaunches the script of the last simulation in --results mode with the
        voltage, scale and rise time written in the tab: redoes only GIFs and TDR.
        """
        import subprocess
        import sys

        python_exe = self.python_ctrl.GetValue().strip()
        if not os.path.exists(python_exe):
            self.status_label.SetLabel(_("Python non trovato: {0}").format(python_exe))
            return
        run_dir = self._latest_run_dir()
        script = os.path.join(run_dir, "simulate.py") if run_dir else ""
        if not os.path.exists(script):
            self.status_label.SetLabel(_("Nessuna simulazione trovata: lanciane prima una con 'Salva campi'."))
            return
        v = self._number(self.vsig_ctrl, 1.0)
        scale = self._number(self.escale_ctrl, 0.0) if self.escale_ctrl.GetValue().strip() else 0.0
        flags = subprocess.CREATE_NEW_CONSOLE if sys.platform.startswith("win") else 0
        tr = self._number(self.trise_ctrl, 1.0)
        subprocess.Popen([python_exe, script, "--results", "--voltage", str(v), "--scale", str(scale),
                          "--rise", str(tr)],
                         cwd=run_dir, creationflags=flags)
        self.status_label.SetLabel(
            _("Rielaboro {0}: {1:g} V, fronte {2:g} ns").format(os.path.basename(run_dir), v, tr)
            + (_(", scala fissa {0:g} V/mm").format(scale) if scale else _(", scala automatica"))
            + _(" (si apre una finestra; ci vuole circa un minuto).")
        )

    def on_open_dir(self, event):
        """Opens the folder of the last simulation in Explorer."""
        path = self._last_dir or self._runs_root()
        if os.path.isdir(path):
            os.startfile(path)
        else:
            self.status_label.SetLabel(_("Nessuna simulazione ancora eseguita."))


class LayoutCheckPanel(wx.Panel):
    """
    "Layout checks" tab: a "smart DRC" on the whole board (see
    analysis/layout_check.py). The checks measure the layout (distances,
    presence of vias and planes) and compare it with good-practice
    thresholds; every row of the table is a problem, with the measure found
    and the limit.
    """

    COLS = (("Stato", 100), ("Controllo", 145), ("Oggetto", 130), ("Dettaglio", 400),
            ("Misura", 85), ("Limite", 85))

    def __init__(self, parent, dialog):
        super().__init__(parent)
        self.dialog = dialog
        self.board = dialog.board
        self._cancel_requested = False
        self._issues = []   # issues of the last run, same order as the rows
        self._rings = {}    # row index -> ring marker drawn on the board

        # --- Which checks to run (two rows of four) ---
        checks_box = wx.StaticBoxSizer(wx.VERTICAL, self, _("Controlli"))
        checks_grid = wx.GridSizer(cols=4, vgap=2, hgap=10)
        self.decap_check = wx.CheckBox(self, label=_("Disaccoppiamento"))
        self.decap_check.SetToolTip(_("Condensatore vicino a ogni pin di alimentazione degli integrati "
                                      "e via di massa vicina ai pad GND"))
        self.layer_check = wx.CheckBox(self, label=_("Cambio layer"))
        self.layer_check.SetToolTip(_("Via di segnale dove cambia il piano di riferimento: "
                                      "serve una via di massa vicina"))
        self.stitch_check = wx.CheckBox(self, label=_("Via di stitching"))
        self.stitch_check.SetToolTip(_("Zone di massa su piu' layer: aree troppo lontane da una via di massa"))
        self.gap_check = wx.CheckBox(self, label=_("Piano interrotto"))
        self.gap_check.SetToolTip(_("Tracce che passano sopra un'interruzione del piano di massa"))
        self.edge_check = wx.CheckBox(self, label=_("Bordo del piano"))
        self.edge_check.SetToolTip(_("Tracce troppo vicine al bordo del loro piano di riferimento "
                                     "(in multipli dello spessore del dielettrico h)"))
        self.width_check = wx.CheckBox(self, label=_("Larghezza tracce"))
        self.width_check.SetToolTip(_("Larghezza delle tracce rispetto alla corrente indicata nel campo "
                                      "Correnti (IPC-2221)"))
        self.iso_check = wx.CheckBox(self, label=_("Isolamento"))
        self.iso_check.SetToolTip(_("Distanza fra net con tensioni diverse oltre 30 V (IPC-2221)"))
        self.length_check = wx.CheckBox(self, label=_("Lunghezze"))
        self.length_check.SetToolTip(_("Differenza di lunghezza nelle coppie differenziali e nei gruppi di net"))
        # Checks 9-16
        def check_box(label, tip):
            cb = wx.CheckBox(self, label=label)
            cb.SetToolTip(tip)
            return cb

        self.stub_check = check_box(_("Rami morti"), _("Tracce che finiscono senza collegarsi a niente"))
        self.acute_check = check_box(_("Angoli acuti"), _("Tracce della stessa net che si incontrano a meno di "
                                                         "90 gradi (acid trap)"))
        self.wstep_check = check_box(_("Cambi di larghezza"), _("Net di segnale con tracce di larghezza diversa "
                                                               "(salto di impedenza)"))
        self.vip_check = check_box(_("Via nei pad"), _("Foro di una via dentro un pad SMD (lo stagno scende nel foro)"))
        self.tomb_check = check_box(_("Tombstoning"), _("Componenti piccoli con un pad annegato nella zona e "
                                                        "l'altro su traccia"))
        self.viacur_check = check_box(_("Corrente via"), _("Numero di via a ogni cambio di layer per le net del "
                                                          "campo Correnti (IPC-2221)"))
        self.xtal_check = check_box(_("Quarzo"), _("Tracce sotto il quarzo e lunghezza delle tracce "
                                                  "quarzo-integrato"))
        self.broad_check = check_box(_("Tracce sovrapposte"), _("Tracce di net diverse una sopra l'altra su layer "
                                                               "adiacenti"))
        # Every check box gets the "_check" suffix: persist_all saves them
        self._check_boxes = (self.decap_check, self.layer_check, self.stitch_check, self.gap_check,
                             self.edge_check, self.width_check, self.iso_check, self.length_check,
                             self.stub_check, self.acute_check, self.wstep_check, self.vip_check,
                             self.tomb_check, self.viacur_check, self.xtal_check, self.broad_check)
        for cb in self._check_boxes:
            cb.SetValue(True)
            checks_grid.Add(cb, 0)
        checks_box.Add(checks_grid, 0, wx.ALL, 5)
        # "All" / "None": select or clear every check at once
        sel_row = wx.BoxSizer(wx.HORIZONTAL)
        all_btn = wx.Button(self, label=_("Tutti"), style=wx.BU_EXACTFIT)
        all_btn.SetToolTip(_("Seleziona tutti i controlli"))
        all_btn.Bind(wx.EVT_BUTTON, lambda e: self._set_all_checks(True))
        none_btn = wx.Button(self, label=_("Nessuno"), style=wx.BU_EXACTFIT)
        none_btn.SetToolTip(_("Deseleziona tutti i controlli"))
        none_btn.Bind(wx.EVT_BUTTON, lambda e: self._set_all_checks(False))
        sel_row.Add(all_btn, 0, wx.RIGHT, 6)
        sel_row.Add(none_btn, 0)
        checks_box.Add(sel_row, 0, wx.LEFT | wx.BOTTOM, 5)

        # --- Thresholds (two label/box pairs per row) ---
        def num_box(value):
            return wx.TextCtrl(self, value=value, size=(50, -1))

        # Default values: the ones of layout_check.CheckSettings (single source)
        d = layout_check.CheckSettings()
        self._defaults = {
            "decap_warn_ctrl": d.decap_warn_mm, "decap_err_ctrl": d.decap_err_mm,
            "gnd_via_ctrl": d.gnd_via_mm, "return_via_ctrl": d.return_via_mm,
            "stitch_ctrl": d.stitch_spacing_mm, "min_gap_ctrl": d.min_gap_mm,
            "edge_h_ctrl": d.edge_h_factor, "dt_ctrl": d.delta_t,
            "skew_ctrl": d.skew_mm, "group_tol_ctrl": d.group_tol_mm,
            "stub_ctrl": d.stub_mm, "acute_ctrl": d.acute_deg, "wstep_ctrl": d.width_step_pct,
            "xtal_ctrl": d.crystal_mm, "broad_ctrl": d.broadside_mm,
        }
        self.decap_warn_ctrl = num_box(f"{d.decap_warn_mm:g}")
        self.decap_err_ctrl = num_box(f"{d.decap_err_mm:g}")
        self.gnd_via_ctrl = num_box(f"{d.gnd_via_mm:g}")
        self.return_via_ctrl = num_box(f"{d.return_via_mm:g}")
        self.stitch_ctrl = num_box(f"{d.stitch_spacing_mm:g}")
        self.min_gap_ctrl = num_box(f"{d.min_gap_mm:g}")
        self.edge_h_ctrl = num_box(f"{d.edge_h_factor:g}")
        self.dt_ctrl = num_box(f"{d.delta_t:g}")
        self.skew_ctrl = num_box(f"{d.skew_mm:g}")
        self.group_tol_ctrl = num_box(f"{d.group_tol_mm:g}")
        self.stub_ctrl = num_box(f"{d.stub_mm:g}")
        self.acute_ctrl = num_box(f"{d.acute_deg:g}")
        self.wstep_ctrl = num_box(f"{d.width_step_pct:g}")
        self.xtal_ctrl = num_box(f"{d.crystal_mm:g}")
        self.broad_ctrl = num_box(f"{d.broadside_mm:g}")
        self.skip_power_check = wx.CheckBox(self, label=_("Cambio layer e bordo: ignora le net di alimentazione"))
        self.skip_power_check.SetValue(True)
        # Copper islands: a via counts only for the piece of ground copper it
        # really touches (reads the filled polygons of the zones)
        self.islands_check = wx.CheckBox(self, label=_("Distingui le isole di rame"))
        self.islands_check.SetToolTip(_("Una via di massa conta solo per il pezzo di rame che tocca davvero "
                                        "(non per quello oltre una fessura)"))
        self.islands_check.SetValue(True)

        thr_box = wx.StaticBoxSizer(wx.VERTICAL, self, _("Soglie"))
        grid = wx.FlexGridSizer(cols=6, vgap=4, hgap=6)
        rows = (
            ("Condensatore: attenzione oltre (mm):", self.decap_warn_ctrl,
             "Condensatore: errore oltre (mm):", self.decap_err_ctrl),
            ("Via di massa dei pad GND entro (mm):", self.gnd_via_ctrl,
             "Via di ritorno al cambio layer entro (mm):", self.return_via_ctrl),
            ("Passo massimo via di stitching (mm):", self.stitch_ctrl,
             "Gap minimo del piano (mm):", self.min_gap_ctrl),
            ("Bordo del piano: almeno (multipli di h):", self.edge_h_ctrl,
             "Riscaldamento massimo tracce (C):", self.dt_ctrl),
            ("Skew massimo coppie differenziali (mm):", self.skew_ctrl,
             "Differenza massima nei gruppi (mm):", self.group_tol_ctrl),
            ("Rami morti da (mm):", self.stub_ctrl,
             "Angoli acuti sotto (gradi):", self.acute_ctrl),
            ("Cambio di larghezza oltre (%):", self.wstep_ctrl,
             "Tracce quarzo-integrato fino a (mm):", self.xtal_ctrl),
            ("Tracce sovrapposte da (mm):", self.broad_ctrl,
             None, None),
        )
        # The (label, box) pairs, laid out three per row: the tab must leave
        # room to the results table
        pairs = [(l, c) for l1, c1, l2, c2 in rows for l, c in ((l1, c1), (l2, c2)) if l is not None]
        for k, (label, ctrl) in enumerate(pairs):
            grid.Add(wx.StaticText(self, label=_(label)), 0, wx.ALIGN_CENTER_VERTICAL)
            # Space after the box, except at the end of the row
            grid.Add(ctrl, 0, wx.RIGHT, 0 if k % 3 == 2 else 14)
        thr_box.Add(grid, 0, wx.ALL, 5)
        opt_row = wx.BoxSizer(wx.HORIZONTAL)
        opt_row.Add(self.skip_power_check, 0, wx.RIGHT, 20)
        opt_row.Add(self.islands_check, 0)
        thr_box.Add(opt_row, 0, wx.LEFT | wx.BOTTOM, 5)

        # --- Net data typed by the user (checks 6-8): "net = value; ..." ---
        def data_box(hint, tip):
            ctrl = wx.TextCtrl(self, value="", size=(300, -1))
            ctrl.SetHint(hint)
            ctrl.SetToolTip(tip)
            return ctrl

        self.currents_ctrl = data_box(
            "+5V=2; VIN=3",
            _("Corrente (A) delle net da controllare, separate da ';'. Ammessi * e ? nel nome."))
        self.voltages_ctrl = data_box(
            "HV*=400; L=325",
            _("Tensione (V) delle net; senza indicazione e' quella scritta nel nome (+5V, 24V_IN, 3V3), "
              "0 V per le masse."))
        self.groups_ctrl = data_box(
            "SD_*; ETH_TX*, ETH_CLK",
            _("Gruppi di net da tenere della stessa lunghezza: un gruppo per ';', nomi separati da ','. "
              "Le coppie differenziali sono riconosciute da sole."))
        data_sizer = wx.StaticBoxSizer(wx.VERTICAL, self, _("Dati delle net"))
        data_grid = wx.FlexGridSizer(cols=2, vgap=4, hgap=6)
        for label, ctrl in ((_("Correnti (A):"), self.currents_ctrl),
                            (_("Tensioni (V):"), self.voltages_ctrl),
                            (_("Gruppi di lunghezza:"), self.groups_ctrl)):
            data_grid.Add(wx.StaticText(self, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
            data_grid.Add(ctrl, 1, wx.EXPAND)
        data_grid.AddGrowableCol(1, 1)
        data_sizer.Add(data_grid, 1, wx.EXPAND | wx.ALL, 5)

        # Thresholds and net data side by side
        top_row = wx.BoxSizer(wx.HORIZONTAL)
        top_row.Add(checks_box, 0, wx.EXPAND | wx.RIGHT, 10)
        top_row.Add(data_sizer, 1, wx.EXPAND)

        # --- Buttons ---
        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        self.run_btn = wx.Button(self, label=_("Esegui controlli"))
        self.run_btn.SetToolTip(_("Controlla tutta la scheda (le zone devono essere riempite: tasto B)"))
        self.run_btn.Bind(wx.EVT_BUTTON, self.on_run)
        btn_row.Add(self.run_btn, 0, wx.RIGHT, 5)
        self.cancel_btn = wx.Button(self, label=_("Interrompi"))
        self.cancel_btn.Bind(wx.EVT_BUTTON, self.on_cancel)
        self.cancel_btn.Disable()
        btn_row.Add(self.cancel_btn, 0, wx.RIGHT, 10)
        clear_btn = wx.Button(self, label=_("Pulisci overlay"))
        clear_btn.Bind(wx.EVT_BUTTON, self.on_clear)
        btn_row.Add(clear_btn, 0, wx.RIGHT, 10)
        # Filter of the table: all the rows or only the errors
        self.show_choice = wx.Choice(self, choices=[_("Tutti"), _("Solo errori")])
        self.show_choice.SetSelection(0)
        self.show_choice.Bind(wx.EVT_CHOICE, lambda e: self._fill_list())
        btn_row.Add(wx.StaticText(self, label=_("Mostra:")), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        btn_row.Add(self.show_choice, 0)
        # HTML report of the last run (disabled until the checks have run)
        self.report_btn = wx.Button(self, label=_("Rapporto..."))
        self.report_btn.SetToolTip(_("Pagina HTML con i risultati e i disegni dei punti segnalati, accanto "
                                     "alla scheda (dal browser: Stampa -> Salva come PDF)"))
        self.report_btn.Bind(wx.EVT_BUTTON, self.on_report)
        self.report_btn.Disable()
        btn_row.Add(self.report_btn, 0, wx.LEFT, 10)
        # Back to the default thresholds and switches
        reset_btn = wx.Button(self, label=_("Valori predefiniti"))
        reset_btn.SetToolTip(_("Rimette soglie e caselle ai valori predefiniti"))
        reset_btn.Bind(wx.EVT_BUTTON, self.on_reset_defaults)
        btn_row.Add(reset_btn, 0, wx.LEFT, 10)
        add_help_button(self, btn_row, "layout_check")

        # --- Results table ---
        self.results_list = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL, size=(400, 150))
        for k, (title, width) in enumerate(self.COLS):
            self.results_list.InsertColumn(k, _(title), width=width)
        self._light_images = make_light_images()
        self.results_list.SetImageList(self._light_images, wx.IMAGE_LIST_SMALL)
        self.results_list.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_row_selected)
        self.results_list.Bind(wx.EVT_LIST_ITEM_RIGHT_CLICK, self.on_right_click)
        self._shown = []  # indexes (in self._issues) of the rows shown
        self._keys = []   # identity of every row (layout_check.issue_key)
        self._notes = []
        self._settings_used = None
        self._excluded = set()

        self.status_label = wx.StaticText(self, label="")

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(top_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 10)
        sizer.Add(thr_box, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 10)
        sizer.Add(btn_row, 0, wx.ALL, 10)
        sizer.Add(self.results_list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        sizer.Add(self.status_label, 0, wx.ALL, 10)
        self.SetSizer(sizer)
        # One-time update of the saved thresholds: the values still equal to
        # the OLD defaults (never changed by the user) become the new ones
        self._migrate_defaults()
        # Remember switches and thresholds between sessions (general settings);
        # the net data belong to the board: they go in its project file
        persist_all(self, "lc", skip=("currents_ctrl", "voltages_ctrl", "groups_ctrl"))
        self._load_project_data()

    # Net data saved in the project file of the board: (key, text box name)
    _PROJECT_FIELDS = (("lc_currents", "currents_ctrl"), ("lc_voltages", "voltages_ctrl"),
                       ("lc_groups", "groups_ctrl"))

    def _load_project_data(self):
        """
        Net data and excluded rows of THIS board, from its project file (see
        common/project_data.py). A board without a project file yet takes the
        net data saved by the previous versions in the general settings, so
        nothing typed before is lost. Every change is saved at once.
        """
        data = project_data.load(self.board)
        general = load_settings()
        for key, name in self._PROJECT_FIELDS:
            ctrl = getattr(self, name)
            value = data.get(key)
            if value is None:
                value = general.get(f"lc_{name}", "")
            ctrl.ChangeValue(str(value))  # ChangeValue does not generate EVT_TEXT
            ctrl.Bind(wx.EVT_TEXT, lambda evt, k=key, c=ctrl: (self._save_project(k, c.GetValue()), evt.Skip()))
        self._excluded = set(data.get("lc_excluded", []))

    def _save_project(self, key, value):
        """
        Saves one value in the project file of the board. A board never saved
        has no project file: the value goes to the general settings instead.
        """
        if not project_data.save(self.board, key, value):
            names = dict(self._PROJECT_FIELDS)
            if key in names:
                save_setting(f"lc_{names[key]}", value)

    # Defaults of the first version of the tab: (settings key, old value)
    _OLD_DEFAULTS = (("lc_decap_warn_ctrl", "5"), ("lc_decap_err_ctrl", "10"),
                     ("lc_gnd_via_ctrl", "2"))

    def _migrate_defaults(self):
        """
        Saved settings are loaded over the defaults, so new defaults would
        never reach who already used the tab. Once (flag in the settings), the
        saved values still equal to the old defaults are replaced by the new
        ones; values changed by the user are kept.
        """
        data = load_settings()
        if data.get("lc_defaults_version", 1) >= 2:
            return
        for key, old in self._OLD_DEFAULTS:
            if str(data.get(key, "")).strip() == old:
                save_setting(key, f"{self._defaults[key[3:]]:g}")
        save_setting("lc_defaults_version", 2)

    def _set_all_checks(self, value):
        """
        Selects (value True) or clears all the check boxes of the checks and
        saves them: SetValue does not send the event that would save them.
        """
        for cb in self._check_boxes:
            cb.SetValue(value)
            for name, obj in vars(self).items():
                if obj is cb:
                    save_setting(f"lc_{name}", value)

    def on_reset_defaults(self, event):
        """Puts back the default thresholds and switches (and saves them)."""
        for name, value in self._defaults.items():
            getattr(self, name).SetValue(f"{value:g}")  # SetValue also saves it
        # The net data (currents, voltages, groups) are the user's data, not
        # thresholds: they are left as they are
        for cb in self._check_boxes + (self.skip_power_check, self.islands_check):
            cb.SetValue(True)
            # SetValue of a check box does not generate the event that saves it
            for name, obj in vars(self).items():
                if obj is cb:
                    save_setting(f"lc_{name}", True)
        self.status_label.SetLabel(_("Valori predefiniti ripristinati."))

    @staticmethod
    def _number(ctrl, default):
        """Number from a text box (decimal comma accepted), default if invalid."""
        try:
            return float(ctrl.GetValue().strip().replace(",", "."))
        except ValueError:
            return default

    def _settings(self):
        """Settings of the analysis from the controls of the tab and of Options."""
        d = layout_check.CheckSettings()  # defaults, used for invalid values
        n = self._number
        return layout_check.CheckSettings(
            ref_filter=self.dialog.options.gnd_ctrl.GetValue().strip() or "GND",
            do_decap=self.decap_check.GetValue(),
            do_layer_change=self.layer_check.GetValue(),
            do_stitching=self.stitch_check.GetValue(),
            do_plane_gap=self.gap_check.GetValue(),
            decap_warn_mm=n(self.decap_warn_ctrl, d.decap_warn_mm),
            decap_err_mm=n(self.decap_err_ctrl, d.decap_err_mm),
            gnd_via_mm=n(self.gnd_via_ctrl, d.gnd_via_mm),
            return_via_mm=n(self.return_via_ctrl, d.return_via_mm),
            skip_power_nets=self.skip_power_check.GetValue(),
            stitch_spacing_mm=max(n(self.stitch_ctrl, d.stitch_spacing_mm), 1.0),
            min_gap_mm=n(self.min_gap_ctrl, d.min_gap_mm),
            use_islands=self.islands_check.GetValue(),
            do_plane_edge=self.edge_check.GetValue(),
            do_width=self.width_check.GetValue(),
            do_isolation=self.iso_check.GetValue(),
            do_length=self.length_check.GetValue(),
            edge_h_factor=max(n(self.edge_h_ctrl, d.edge_h_factor), 0.1),
            delta_t=max(n(self.dt_ctrl, d.delta_t), 1.0),
            currents=self.currents_ctrl.GetValue(),
            voltages=self.voltages_ctrl.GetValue(),
            skew_mm=max(n(self.skew_ctrl, d.skew_mm), 0.0),
            group_tol_mm=max(n(self.group_tol_ctrl, d.group_tol_mm), 0.0),
            groups=self.groups_ctrl.GetValue(),
            do_stub=self.stub_check.GetValue(),
            do_acute=self.acute_check.GetValue(),
            do_width_step=self.wstep_check.GetValue(),
            do_via_in_pad=self.vip_check.GetValue(),
            do_tombstone=self.tomb_check.GetValue(),
            do_via_current=self.viacur_check.GetValue(),
            do_crystal=self.xtal_check.GetValue(),
            do_broadside=self.broad_check.GetValue(),
            stub_mm=max(n(self.stub_ctrl, d.stub_mm), 0.0),
            acute_deg=min(max(n(self.acute_ctrl, d.acute_deg), 1.0), 179.0),
            width_step_pct=max(n(self.wstep_ctrl, d.width_step_pct), 0.0),
            crystal_mm=max(n(self.xtal_ctrl, d.crystal_mm), 0.0),
            broadside_mm=max(n(self.broad_ctrl, d.broadside_mm), 0.0),
            # Via plating: the same value used by the DC Current tab (Options)
            via_plating_um=max(n(self.dialog.options.plating_ctrl, d.via_plating_um), 1.0),
        )

    def on_run(self, event):
        """Runs the enabled checks on the whole board and fills the table."""
        self.on_clear(event)  # old markers off the board first
        settings = self._settings()
        self._cancel_requested = False
        self.run_btn.Disable()
        self.cancel_btn.Enable()
        self.status_label.SetLabel(_("Controlli in corso... (0%)"))
        wx.Yield()

        def on_progress(fraction, name):
            # Called often by the checks: shows the progress and keeps the
            # window responsive (a click on "Stop" is processed here)
            self.status_label.SetLabel(_("Controlli in corso: {0} ({1}%)").format(name, int(100 * fraction)))
            wx.Yield()

        try:
            issues, notes = layout_check.run_checks(
                self.board, settings, progress=on_progress,
                cancel=lambda: self._cancel_requested)
        except Exception:
            import traceback

            self.run_btn.Enable()
            self.cancel_btn.Disable()
            self.status_label.SetLabel(_("Errore durante i controlli."))
            wx.MessageBox(traceback.format_exc(), _("Controlli layout"), wx.OK | wx.ICON_ERROR, self)
            return

        # The excluded rows (saved for this board) go to the bottom of the list
        self._excluded = set(project_data.load(self.board).get("lc_excluded", self._excluded))
        keys = [layout_check.issue_key(it) for it in issues]
        order = sorted(range(len(issues)), key=lambda k: keys[k] in self._excluded)
        self._issues = [issues[k] for k in order]
        self._keys = [keys[k] for k in order]
        self._notes = notes
        self._settings_used = settings
        self.run_btn.Enable()
        self.cancel_btn.Disable()
        self.report_btn.Enable()
        self._show_results()

    def _excluded_rows(self):
        """Indexes (in self._issues) of the rows excluded by the user."""
        return {k for k, key in enumerate(self._keys) if key in self._excluded}

    def _show_results(self):
        """
        Markers on the board (not for the excluded rows), table and status
        line, from the last results. Called after a run and after a row is
        excluded or included again.
        """
        if self.dialog.markers:
            return_path.clear_highlight(self.board, self.dialog.markers)
            self.dialog.markers = []
        skip = self._excluded_rows()
        # Markers on the board: User.1 = errors, User.2 = warnings
        markers, self._rings = layout_check.highlight(self.board, self._issues, skip=skip)
        self.dialog.markers = markers
        self._fill_list()

        active = [it for k, it in enumerate(self._issues) if k not in skip]
        n_err = sum(1 for it in active if it.severity == layout_check.SEV_ERROR)
        n_warn = len(active) - n_err
        if self._cancel_requested:
            msg = _("Interrotto dall'utente: {0} errori e {1} avvisi trovati prima dello stop.").format(n_err, n_warn)
        elif not active:
            msg = _("Nessun problema trovato con le soglie impostate.")
        else:
            msg = _("{0} errori e {1} avvisi. Sulla scheda: un cerchio per ogni problema e una forma piena "
                    "per ogni area senza via di stitching (User.1 = errori, User.2 = avvisi).").format(n_err, n_warn)
        if skip:
            msg += "  " + _("{0} righe escluse (in grigio): clic destro per includerle di nuovo.").format(len(skip))
        if self._notes:
            msg += "  " + "  ".join(self._notes)
        self.status_label.SetLabel(msg)
        self.status_label.Wrap(max(self.GetSize().width - 30, 300))
        self.Layout()

    def on_report(self, event):
        """
        Writes the HTML report of the last run next to the board (asks where
        if the board has never been saved) and opens it in the browser.
        """
        from ..analysis import layout_report
        from ..common.version import VERSION

        board_file = self.board.GetFileName()
        suffix = _("_controlli_layout") + ".html"
        if board_file:
            path = os.path.splitext(board_file)[0] + suffix
        else:
            dlg = wx.FileDialog(self, _("Salva il rapporto"), wildcard="HTML (*.html)|*.html",
                                defaultFile="layout" + suffix, style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT)
            if dlg.ShowModal() != wx.ID_OK:
                dlg.Destroy()
                return
            path = dlg.GetPath()
            dlg.Destroy()
        try:
            wx.BeginBusyCursor()
            layout_report.write_report(path, self.board, self._issues, self._excluded_rows(),
                                       self._settings_used, self._notes, VERSION)
        except Exception:
            import traceback

            wx.MessageBox(traceback.format_exc(), _("Rapporto"), wx.OK | wx.ICON_ERROR, self)
            return
        finally:
            if wx.IsBusy():
                wx.EndBusyCursor()
        self.status_label.SetLabel(_("Rapporto salvato: {0}").format(path))
        import webbrowser

        webbrowser.open("file:///" + path.replace(os.sep, "/").lstrip("/"))

    def on_right_click(self, event):
        """
        Right click on a row: menu to exclude it (accepted, it turns grey and
        leaves the board) or to include it again. The choice is saved in the
        project file of the board, so it is kept in the next runs.
        """
        row = event.GetIndex()
        if row < 0 or row >= len(self._shown):
            return
        k = self._shown[row]
        key = self._keys[k]
        menu = wx.Menu()
        if key in self._excluded:
            item = menu.Append(wx.ID_ANY, _("Includi di nuovo"))
            self.Bind(wx.EVT_MENU, lambda e: self._set_excluded(key, False), item)
        else:
            item = menu.Append(wx.ID_ANY, _("Escludi (accettato)"))
            self.Bind(wx.EVT_MENU, lambda e: self._set_excluded(key, True), item)
        if self._excluded:
            menu.AppendSeparator()
            all_item = menu.Append(wx.ID_ANY, _("Includi di nuovo tutte le righe escluse"))
            self.Bind(wx.EVT_MENU, lambda e: self._set_excluded(None, False), all_item)
        self.PopupMenu(menu)
        menu.Destroy()

    def _set_excluded(self, key, excluded):
        """Excludes / includes a row (key None = include all again) and saves the choice."""
        if key is None:
            self._excluded = set()
        elif excluded:
            self._excluded.add(key)
        else:
            self._excluded.discard(key)
        if not project_data.save(self.board, "lc_excluded", sorted(self._excluded)):
            wx.MessageBox(_("La scheda non e' ancora salvata: l'esclusione vale solo fino alla chiusura "
                            "della finestra."), _("Controlli layout"), wx.OK | wx.ICON_INFORMATION, self)
        # Excluded rows go to the bottom, included ones back among the others
        order = sorted(range(len(self._issues)), key=lambda k: self._keys[k] in self._excluded)
        self._issues = [self._issues[k] for k in order]
        self._keys = [self._keys[k] for k in order]
        self._show_results()

    @staticmethod
    def _value_text(value, unit, limit=False):
        """
        Text of a Measured / Limit cell with its unit: "0.13 mm", "45°",
        "67 %", "2 via". Lengths below 10 mm get two decimals (track widths,
        clearances); limits are written as typed (:g).
        """
        if value is None:
            return "-"
        if unit == "via":
            txt = f"{int(round(value))}"
        elif unit in ("°", "%"):
            txt = f"{value:.0f}"
        elif limit:
            txt = f"{value:g}"
        else:
            txt = f"{value:.2f}" if value < 10 else f"{value:.1f}"
        if not unit:
            return txt
        return f"{txt}{unit}" if unit == "°" else f"{txt} {unit}"

    def _fill_list(self):
        """Fills the table with the issues, filtered by the 'Show' choice."""
        names = layout_check.check_names()
        only_errors = self.show_choice.GetSelection() == 1
        self.results_list.DeleteAllItems()
        self._shown = []
        skip = self._excluded_rows()
        for k, it in enumerate(self._issues):
            excluded = k in skip
            if only_errors and (it.severity != layout_check.SEV_ERROR or excluded):
                continue
            # Traffic light: 2 = red (error), 1 = yellow (warning), 3 = grey (excluded)
            if excluded:
                word, icon = "Escluso", 3
            else:
                word = "Errore" if it.severity == layout_check.SEV_ERROR else "Attenzione"
                icon = it.severity
            row = self.results_list.InsertItem(self.results_list.GetItemCount(), _(word), icon)
            if excluded:
                # Greyed out, as KiCad does with the excluded DRC markers
                self.results_list.SetItemTextColour(row, wx.Colour(150, 150, 150))
            self.results_list.SetItem(row, 1, names.get(it.check, it.check))
            self.results_list.SetItem(row, 2, it.obj)
            self.results_list.SetItem(row, 3, it.detail)
            self.results_list.SetItem(row, 4, self._value_text(it.measured_mm, it.unit))
            self.results_list.SetItem(row, 5, self._value_text(it.limit_mm, it.unit, limit=True))
            self._shown.append(k)

    def _clear_selection(self):
        """Deselects tracks, vias, pads, footprints and drawings in Pcbnew."""
        groups = (self.board.GetTracks(), self.board.GetPads(),
                  self.board.GetFootprints(), self.board.GetDrawings())
        for group in groups:
            for it in group:
                if it.IsSelected():
                    it.ClearSelected()

    def on_row_selected(self, event):
        """
        Click on a row: selects in Pcbnew the objects involved (pad,
        capacitor, via, track) and centres the view on them. For the
        stitching areas the view centres on the area shape and highlights it.
        """
        row = event.GetIndex()
        if row < 0 or row >= len(self._shown):
            return
        k = self._shown[row]
        it = self._issues[k]
        # Stitching area: the area shape is selected (so it is highlighted) and
        # the view centres on it. Selecting a marker is safe because
        # clear_highlight deselects every marker before removing it.
        if it.polys:
            self._clear_selection()
            shape = self._rings.get(k)
            if shape is not None:
                try:
                    shape.SetSelected()
                    pcbnew.FocusOnItem(shape)
                except AttributeError:
                    pass  # FocusOnItem not available in every build
                except Exception as exc:
                    self.status_label.SetLabel(_("Impossibile selezionare: {0}").format(exc))
            pcbnew.Refresh()
            return
        # Other checks: the real board objects involved (pad, capacitor, via,
        # track) are selected
        items = list(it.items)
        if not items:
            self._clear_selection()
            pcbnew.Refresh()
            return
        try:
            self._clear_selection()
            for obj in items:
                obj.SetSelected()
            try:
                pcbnew.FocusOnItem(items[0])
            except AttributeError:
                pass  # not available in every build: the selection stays
            pcbnew.Refresh()
        except Exception as exc:
            # The object may have been deleted after the checks
            self.status_label.SetLabel(_("Impossibile selezionare: {0}").format(exc))

    def on_cancel(self, event):
        """Stops the running checks (they return what was found so far)."""
        self._cancel_requested = True
        self.status_label.SetLabel(_("Interruzione in corso..."))

    def on_clear(self, event):
        """Removes the markers of the last run from the board."""
        if self.dialog.markers:
            return_path.clear_highlight(self.board, self.dialog.markers)
            self.dialog.markers = []
        self._rings = {}
        self.status_label.SetLabel("")


class ReturnPathPanel(wx.Panel):
    """Return Path checker tab."""

    def __init__(self, parent, dialog):
        super().__init__(parent)
        self.dialog = dialog
        self.board = dialog.board
        self._cancel_requested = False

        # --- Top row: reference net filter + buttons ---
        top_sizer = wx.BoxSizer(wx.HORIZONTAL)
        top_sizer.Add(
            wx.StaticText(self, label=_("Net di riferimento:")),
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.RIGHT,
            5,
        )
        self.net_filter_ctrl = wx.TextCtrl(self, value="GND")
        top_sizer.Add(self.net_filter_ctrl, 0, wx.RIGHT, 10)

        # Threshold: minimum length (mm) of a continuous stretch without plane
        # under the track for it to be reported. Shorter gaps (e.g. a crossing
        # with a track on the opposite side) are ignored.
        top_sizer.Add(
            wx.StaticText(self, label=_("Gap minimo (mm):")),
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.RIGHT,
            5,
        )
        self.min_gap_ctrl = wx.TextCtrl(self, value="5", size=(50, -1))
        top_sizer.Add(self.min_gap_ctrl, 0, wx.RIGHT, 10)

        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)  # second row: buttons
        self.analyze_btn = wx.Button(self, label=_("Analizza"))
        self.analyze_btn.Bind(wx.EVT_BUTTON, self.on_analyze)
        btn_sizer.Add(self.analyze_btn, 0, wx.RIGHT, 5)
        # Only the tracks selected in Pcbnew (the dialog stays open: click a
        # track on the board, 'U' selects the whole connected track, then
        # press this button)
        self.analyze_sel_btn = wx.Button(self, label=_("Analizza selezione"))
        self.analyze_sel_btn.SetToolTip(_("Analizza solo le tracce selezionate in Pcbnew "
                                          "(tasto U in Pcbnew: seleziona tutta la traccia collegata)"))
        self.analyze_sel_btn.Bind(wx.EVT_BUTTON, lambda e: self.on_analyze(e, selection=True))
        btn_sizer.Add(self.analyze_sel_btn, 0, wx.RIGHT, 5)

        # Button to stop a running analysis: on large boards or with poorly
        # continuous planes the calculation can take several seconds, and the
        # first version had no way to stop it (pcbnew had to be killed). It
        # stays disabled until an analysis starts.
        self.cancel_btn = wx.Button(self, label=_("Interrompi"))
        self.cancel_btn.Bind(wx.EVT_BUTTON, self.on_cancel)
        self.cancel_btn.Disable()
        btn_sizer.Add(self.cancel_btn, 0, wx.RIGHT, 10)

        clear_btn = wx.Button(self, label=_("Pulisci overlay"))
        clear_btn.Bind(wx.EVT_BUTTON, self.on_clear)
        btn_sizer.Add(clear_btn, 0, wx.RIGHT, 10)

        # Selects all the tracks of the list in Pcbnew at once: a reliable
        # alternative to the graphic markers, which do not show up in some
        # builds
        sel_all_btn = wx.Button(self, label=_("Evidenzia tutte"))
        sel_all_btn.Bind(wx.EVT_BUTTON, self.on_select_all)
        btn_sizer.Add(sel_all_btn, 0)
        add_help_button(self, btn_sizer, "return_path")

        # --- Return current map: input of the current and exit of the return ---
        # The user gives only where the current enters (Input) and where the
        # return leaves the board (Exit, e.g. the ground of the power supply).
        # The net, the loads (components with a ground pin reached from the
        # input, also through series parts) and the paths are found by the
        # plugin; the current is shared equally among the loads.
        # Two rows (input/exit, then frequency/resolution/button) so the tab
        # does not force a very wide window
        map_box = wx.StaticBoxSizer(wx.VERTICAL, self, _("Mappa della corrente di ritorno"))
        map_row1, map_row2 = wx.BoxSizer(wx.HORIZONTAL), wx.BoxSizer(wx.HORIZONTAL)
        map_box.Add(map_row1, 0, wx.BOTTOM, 4)
        map_box.Add(map_row2, 0)
        self.map_in_choice = wx.Choice(self, size=(130, -1))
        self._map_in_pads = []   # (label, pad): pads of the net of the input
        in_sel = wx.Button(self, label=_("Ingresso da selezione"))
        in_sel.SetToolTip(_("Seleziona in Pcbnew il pad (o una traccia) da cui entra la corrente"))
        in_sel.Bind(wx.EVT_BUTTON, self.on_map_from_selection)
        self.map_exit_choice = wx.Choice(self, size=(170, -1))
        self._map_exit_pads = []  # (label, pad); index 0 = automatic
        exit_sel = wx.Button(self, label=_("Uscita da selezione"))
        exit_sel.SetToolTip(_("Seleziona in Pcbnew il pad di massa dove colleghi la massa "
                              "dell'alimentatore o dello strumento"))
        exit_sel.Bind(wx.EVT_BUTTON, self.on_map_exit_from_selection)
        for label, ctrl, btn in (("Ingresso:", self.map_in_choice, in_sel),
                                 ("Uscita ritorno:", self.map_exit_choice, exit_sel)):
            map_row1.Add(wx.StaticText(self, label=_(label)), 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT | wx.RIGHT, 5)
            map_row1.Add(ctrl, 0, wx.RIGHT, 3)
            map_row1.Add(btn, 0, wx.RIGHT, 10)
        # Frequency: high (the return follows the track) or DC / low
        # frequency (the return takes the path of minimum resistance)
        self.map_freq_choice = wx.Choice(self, choices=[_("Alta frequenza (HF)"), _("Continua (DC)")])
        self.map_freq_choice.SetSelection(0)
        map_row2.Add(wx.StaticText(self, label=_("Frequenza:")), 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT | wx.RIGHT, 5)
        map_row2.Add(self.map_freq_choice, 0, wx.RIGHT, 8)
        # Resolution of the map: finer grid = sharper drawing but slower
        # calculation (about 3x the time for High, 7x for Very high)
        self.map_res_choice = wx.Choice(self, choices=[_("Normale"), _("Alta"), _("Molto alta")])
        self.map_res_choice.SetSelection(0)
        self.map_res_choice.SetToolTip(_("Risoluzione della mappa: piu' alta = disegno piu' fine ma calcolo piu' lento"))
        map_row2.Add(wx.StaticText(self, label=_("Risoluzione:")), 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT | wx.RIGHT, 5)
        map_row2.Add(self.map_res_choice, 0, wx.RIGHT, 8)
        map_btn = wx.Button(self, label=_("Mappa ritorno"))
        map_btn.SetToolTip(_("Trova da solo net, carichi e percorsi dall'ingresso, poi mostra la mappa"))
        map_btn.Bind(wx.EVT_BUTTON, self.on_return_map)
        map_row2.Add(map_btn, 0, wx.RIGHT, 5)
        self._load_exit_pads()

        # --- Results list ---
        self.results_list = wx.ListCtrl(self, style=wx.LC_REPORT, size=(400, 150))
        # "Status" column with traffic light: red = no stitching via nearby
        # (severe), yellow = a via is nearby (minor)
        self.results_list.InsertColumn(0, _("Stato"), width=90)
        self.results_list.InsertColumn(1, _("Net"), width=100)
        self.results_list.InsertColumn(2, _("Riferimento"), width=300)
        self.results_list.InsertColumn(3, _("Gap max (mm)"), width=110)
        self.results_list.InsertColumn(4, _("Via stitching vicina"), width=140)
        self.results_list.InsertColumn(5, _("Lunghezza (mm)"), width=110)
        self._light_images = make_light_images()
        self.results_list.SetImageList(self._light_images, wx.IMAGE_LIST_SMALL)

        # Issues of the last analysis, in the same order as the list rows: used
        # to go from the clicked row back to the track
        self._issues = []
        self.results_list.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_row_selected)

        self.status_label = wx.StaticText(self, label="")

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(top_sizer, 0, wx.ALL, 10)
        sizer.Add(btn_sizer, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        sizer.Add(self.results_list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        sizer.Add(map_box, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
        sizer.Add(self.status_label, 0, wx.ALL, 10)
        self.SetSizer(sizer)
        # Remember the box values between sessions
        persist_all(self, "rp")

    def on_analyze(self, event, selection=False):
        # With selection=True only the tracks selected in Pcbnew are analyzed
        # (read BEFORE clearing the overlay, which changes the selection)
        sel_tracks = None
        if selection:
            sel_tracks = [t for t in self.board.GetTracks()
                          if t.IsSelected() and t.Type() == pcbnew.PCB_TRACE_T]
            if not sel_tracks:
                self.status_label.SetLabel(_("Niente di selezionato in Pcbnew: seleziona una o piu' tracce."))
                return
        # Removes any overlay of a previous analysis before starting again, so
        # old markers do not pile up on the board
        self.on_clear(event)

        net_filter = self.net_filter_ctrl.GetValue().strip() or "GND"

        # Gap threshold: the decimal comma is accepted too; if the value is not
        # a valid number the default is used
        try:
            min_gap_mm = float(self.min_gap_ctrl.GetValue().strip().replace(",", "."))
        except ValueError:
            min_gap_mm = return_path.DEFAULT_MIN_GAP_MM

        # While the analysis runs, "Analyze" is disabled (so two cannot run in
        # parallel) and "Stop" is enabled. self._cancel_requested is checked
        # inside analyze_board after every track.
        self._cancel_requested = False
        self.analyze_btn.Disable()
        self.cancel_btn.Enable()
        self.status_label.SetLabel(_("Analisi in corso... (0%)"))
        wx.Yield()

        def on_progress(i, total):
            # Called after every track by analyze_board: updates the status
            # label and above all calls wx.Yield(), which processes the queued
            # events (including a possible click on "Stop") so the interface
            # stays responsive during the calculation instead of freezing until
            # the end.
            if total:
                self.status_label.SetLabel(
                    _("Analisi in corso... ({0}%)").format(100 * i // total)
                )
            wx.Yield()

        issues = return_path.analyze_board(
            self.board,
            reference_net_filter=net_filter,
            min_gap_mm=min_gap_mm,
            progress_callback=on_progress,
            should_cancel=lambda: self._cancel_requested,
            tracks=sel_tracks,
        )

        self.results_list.DeleteAllItems()
        for issue in issues:
            if issue.has_nearby_stitching_via:
                light, word = 1, "Minore"
            else:
                light, word = 2, "Grave"
            idx = self.results_list.InsertItem(
                self.results_list.GetItemCount(), _(word), light
            )
            self.results_list.SetItem(idx, 1, _(issue.net_name))
            # Actual net of the plane and layer where it is interrupted
            self.results_list.SetItem(
                idx, 2, _("{0} interrotto su {1} (traccia su {2})").format(issue.ref_net, issue.ref_layer_name, issue.track_layer_name)
            )
            self.results_list.SetItem(idx, 3, f"{issue.max_gap_mm:.1f}")
            self.results_list.SetItem(
                idx, 4, "Sì" if issue.has_nearby_stitching_via else _("No")
            )
            self.results_list.SetItem(idx, 5, f"{issue.length_mm:.1f}")

        self._issues = issues
        self.dialog.markers = return_path.highlight_issues(self.board, issues)

        self.analyze_btn.Enable()
        self.cancel_btn.Disable()
        if self._cancel_requested:
            self.status_label.SetLabel(
                _("Interrotto dall'utente — {0} problemi trovati prima dello stop.").format(len(issues))
            )
        else:
            self.status_label.SetLabel(
                _("Trovate {0} tracce con ritorno di corrente non continuo. Marker: User.1 = senza via di stitching vicina (grave), User.2 = con via vicina.").format(len(issues))
            )

    def on_row_selected(self, event):
        """
        Click on a row: selects the corresponding track in Pcbnew and tries to
        centre it in the view, so you see right away where it is.
        """
        idx = event.GetIndex()
        if idx < 0 or idx >= len(self._issues):
            return
        track = self._issues[idx].track
        try:
            # Deselects everything that was selected before
            for item in self.board.GetTracks():
                if item.IsSelected():
                    item.ClearSelected()
            track.SetSelected()
            # FocusOnItem centres and zooms the view on the object; it is not
            # guaranteed to exist in every build, so if it is missing a plain
            # refresh is used (the track stays selected)
            try:
                pcbnew.FocusOnItem(track)
            except AttributeError:
                pass
            pcbnew.Refresh()
        except Exception as exc:
            # The track may have been deleted after the analysis
            self.status_label.SetLabel(_("Impossibile selezionare la traccia: {0}").format(exc))

    def on_select_all(self, event):
        """Selects in Pcbnew all the tracks with issues in the list."""
        try:
            # First deselect everything, then select the reported tracks
            for item in self.board.GetTracks():
                if item.IsSelected():
                    item.ClearSelected()
            for issue in self._issues:
                issue.track.SetSelected()
            pcbnew.Refresh()
            self.status_label.SetLabel(_("Selezionate {0} tracce.").format(len(self._issues)))
        except Exception as exc:
            self.status_label.SetLabel(_("Impossibile selezionare: {0}").format(exc))

    def _load_exit_pads(self, select=None):
        """
        Choices for the exit of the return: 'automatic' (ground pins of the
        input component) and the ground pads of connectors and test points,
        where a power supply or an instrument is usually connected; plus a
        pad added with 'Exit from selection'.
        """
        ref = (self.net_filter_ctrl.GetValue().strip() if hasattr(self, "net_filter_ctrl") else "") or "GND"
        pads = []
        for p in self.board.GetPads():
            if ref.upper() not in p.GetNetname().upper():
                continue
            try:
                fref = p.GetParentFootprint().GetReference()
            except AttributeError:
                continue
            letters = "".join(ch for ch in fref if ch.isalpha()).upper()
            if letters.startswith(("J", "P", "CN", "X", "TP", "CON")):
                pads.append((dc_current.pad_label(p), p))
        if select is not None and dc_current.pad_label(select) not in [lb for lb, _p in pads]:
            pads.append((dc_current.pad_label(select), select))
        pads.sort(key=lambda t: t[0])
        self._map_exit_pads = [(_("(automatica: GND del componente di ingresso)"), None)] + pads
        self.map_exit_choice.Set([lb for lb, _p in self._map_exit_pads])
        labels = [lb for lb, _p in self._map_exit_pads]
        k = labels.index(dc_current.pad_label(select)) if select is not None else 0
        self.map_exit_choice.SetSelection(k)

    def on_map_from_selection(self, event):
        """
        Input of the current from the Pcbnew selection: a selected pad
        becomes the input; with a track or via selected, the pads of its net
        are listed and the first one is proposed.
        """
        items = dc_current.selected_items(self.board)
        if not items:
            self.status_label.SetLabel(_("Niente di selezionato in Pcbnew: seleziona il pad di ingresso o una traccia."))
            return
        net = items[0].GetNetname()
        if not net:
            self.status_label.SetLabel(_("L'elemento selezionato non ha una net utilizzabile."))
            return
        self._map_in_pads = dc_current.list_pads(self.board, net)
        labels = [lb for lb, _p in self._map_in_pads]
        self.map_in_choice.Set(labels)
        pad_sel = [dc_current.pad_label(i) for i in items if dc_current.is_pad(i)]
        k = labels.index(pad_sel[0]) if pad_sel and pad_sel[0] in labels else 0
        if labels:
            self.map_in_choice.SetSelection(k)
        self.status_label.SetLabel(_("Net {0}: controlla l'ingresso, scegli l'uscita del ritorno e premi Mappa ritorno.").format(net))

    def on_map_exit_from_selection(self, event):
        """Exit of the return: the ground pad selected in Pcbnew."""
        ref = self.net_filter_ctrl.GetValue().strip() or "GND"
        pads = [p for p in self.board.GetPads() if p.IsSelected() and ref.upper() in p.GetNetname().upper()]
        if not pads:
            self.status_label.SetLabel(_("Seleziona in Pcbnew un pad di massa ({0}).").format(ref))
            return
        self._load_exit_pads(select=pads[0])
        self.status_label.SetLabel(_("Uscita del ritorno: {0}.").format(dc_current.pad_label(pads[0])))

    def _map_context(self, res, ref):
        """
        Components and tracks of the other nets inside the map window, drawn
        over the map only for orientation (they do not change the result).
        Returns (footprints, others) in the MapData format.
        """
        mm = pcbnew.ToMM
        ny, nx = res["copper"].shape[1:]
        wx0, wy0 = res["x0"], res["y0"]
        wx1, wy1 = wx0 + nx * res["cell"], wy0 + ny * res["cell"]

        def inside(x0, y0, x1, y1):
            # Rectangle touching the window
            return x1 >= wx0 and x0 <= wx1 and y1 >= wy0 and y0 <= wy1

        footprints = []
        try:
            fps = list(self.board.GetFootprints())
        except AttributeError:
            fps = []
        for fp in fps:
            fpads = []
            box = None
            for p in fp.Pads():
                try:
                    bb = p.GetBoundingBox()
                    x0, y0 = mm(bb.GetLeft()), mm(bb.GetTop())
                    x1, y1 = mm(bb.GetRight()), mm(bb.GetBottom())
                except AttributeError:
                    continue
                gnd = ref.upper() in p.GetNetname().upper()
                fpads.append(((x0 + x1) / 2, (y0 + y1) / 2, x1 - x0, y1 - y0, gnd))
                box = (x0, y0, x1, y1) if box is None else \
                    (min(box[0], x0), min(box[1], y0), max(box[2], x1), max(box[3], y1))
            # Outline = pads extent with a small margin (the courtyard is not
            # always present and the full bounding box includes the texts)
            if box is None or not inside(*box):
                continue
            m = 0.3
            footprints.append((box[0] - m, box[1] - m, box[2] + m, box[3] + m,
                               fp.GetReference(), fpads))

        others = []
        for t in self.board.GetTracks():
            if t.Type() != pcbnew.PCB_TRACE_T or t.GetNetname() == res["net"]:
                continue
            a, b = t.GetStart(), t.GetEnd()
            x0, y0, x1, y1 = mm(a.x), mm(a.y), mm(b.x), mm(b.y)
            if inside(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)):
                others.append((x0, y0, x1, y1, mm(t.GetWidth())))
        return footprints, others

    def on_return_map(self, event):
        """Button handler: an unexpected error is shown instead of being lost."""
        try:
            self._return_map()
        except Exception:
            import traceback

            # Closes a progress window left open by the error
            for w in wx.GetTopLevelWindows():
                if isinstance(w, wx.ProgressDialog):
                    w.Destroy()
            wx.MessageBox(traceback.format_exc(), _("Mappa ritorno"), wx.OK | wx.ICON_ERROR, self)

    def _return_map(self):
        """
        Return current map of the chosen net between the two pads: signal
        path through tracks and vias, ground copper of every layer, ground
        vias; solved with return_map and shown in the map window.
        """
        import numpy as np

        # Input pad (chosen with 'Input from selection') and exit of the return
        k_in = self.map_in_choice.GetSelection()
        if k_in < 0 or not self._map_in_pads:
            self.status_label.SetLabel(_("Scegli prima l'ingresso: seleziona il pad in Pcbnew e premi "
                                         "Ingresso da selezione."))
            return
        pad_in = self._map_in_pads[k_in][1]
        k_exit = self.map_exit_choice.GetSelection()
        exit_pad = self._map_exit_pads[k_exit][1] if k_exit > 0 else None
        ref = self.net_filter_ctrl.GetValue().strip() or "GND"
        mode = "dc" if self.map_freq_choice.GetSelection() == 1 else "hf"

        # Loads with the estimated current: the user checks and corrects
        # them in a table before the map is calculated
        try:
            loads, volts, origin = load_estimate.estimate_loads(self.board, pad_in, ref, mode)
        except ValueError as exc:
            wx.MessageBox(_(str(exc)), _("Mappa ritorno"), wx.OK | wx.ICON_INFORMATION, self)
            return
        if not loads:
            wx.MessageBox(_("Nessun carico trovato: dalla net del pad di ingresso non si raggiunge "
                            "nessun componente con un pin di massa."), _("Mappa ritorno"),
                          wx.OK | wx.ICON_INFORMATION, self)
            return
        dlg = LoadsDialog(self, self.board, pad_in, ref, mode, loads, volts, origin)
        ok = dlg.ShowModal() == wx.ID_OK
        chosen = dlg.result() if ok else None
        dlg.Destroy()
        if not chosen:
            return
        prog = wx.ProgressDialog(_("Mappa ritorno (HF)"), _("Ricerca del percorso..."), 100, self,
                                 wx.PD_APP_MODAL | wx.PD_CAN_ABORT | wx.PD_AUTO_HIDE)

        def progress(frac, msg):
            cont, _skip = prog.Update(min(99, int(frac * 100)), msg)
            return cont  # False = the user pressed Cancel

        try:
            res = return_map.build_map(self.board, None, pad_in, None, ref, progress, mode=mode,
                                       targets=[(d["pad"], d["crossings"]) for d in chosen],
                                       weights=[d["current"] for d in chosen],
                                       load_refs=[d["ref"] for d in chosen],
                                       exit_pad=exit_pad,
                                       detail=(1.0, 1.5, 2.0)[max(0, self.map_res_choice.GetSelection())])
        except ValueError as exc:
            # Expected problems (path not found, no ground...): message box,
            # so it is not missed, and in the status line
            prog.Destroy()
            self.status_label.SetLabel(_(str(exc)))
            self.Layout()
            wx.MessageBox(_(str(exc)), _("Mappa ritorno"), wx.OK | wx.ICON_INFORMATION, self)
            return
        prog.Destroy()

        core = res["res"]
        dc = res["mode"] == "dc"
        # HF: % of the ideal peak under the track. DC: there is no "ideal"
        # profile, the scale is the maximum current density of the map.
        if dc:
            # Scale on the 99th percentile, not on the maximum: right at a
            # pin or via the density has a very sharp peak that would make
            # everything else look blue
            kpos = core["k"][res["copper"] & (core["k"] > 0)]
            peak = float(np.percentile(kpos, 99)) if kpos.size else 1.0
        else:
            peak = res["k_peak"]
        fields, vec, quantities, ranges = {}, {}, [], {}
        for li, name in enumerate(res["layers"]):
            # One map per ground layer: % of the ideal peak, NaN = no copper
            q = _("Ritorno su {0}").format(name)
            cu = res["copper"][li]
            fields[q] = np.where(cu, core["k"][li] / peak * 100, np.nan)
            vec[q] = (np.where(cu, core["kx"][li], np.nan), np.where(cu, core["ky"][li], np.nan))
            quantities.append((q, "%"))
            ranges[q] = (0.0, 100.0)
        raster = {"x0": res["x0"], "y0": res["y0"], "cell": res["cell"],
                  "fields": fields, "vec": vec,
                  "unit_label": _("% del massimo") if dc else _("% del picco ideale")}

        background = [(x0, y0, x1, y1, w) for x0, y0, x1, y1, _l, w in res["segments"]]
        markers = [(res["start"][0], res["start"][1], _("inizio"), (60, 210, 90))]
        for ex, ey in res.get("load_ends", [res["end"]]):
            markers.append((ex, ey, _("fine"), (235, 70, 60)))
        for vx, vy, _la, _lb in res["signal_vias"]:
            markers.append((vx, vy, _("via segnale"), (255, 200, 60)))
        # Ground pins of the two components, where the return enters/leaves
        for gx, gy, gc in res.get("gnd_pins", []):
            # Ground pin with the share of the return current through it
            markers.append((gx, gy, f"GND {gc * 100:.0f}%", (230, 230, 230)))
        # Ground vias as small squares; the most loaded ones with their share
        pads = [(x, y, 0.5, 0.5) for x, y, _c in res["gnd_vias"]]
        for x, y, c in res["gnd_vias"][:3]:
            if c >= 0.05:
                markers.append((x, y, f"{c * 100:.0f}%", (120, 220, 255)))

        lines = []
        if res.get("loads"):
            # Share of each load, from the currents of the table
            parts = [f"{r} {sh * 100:.0f}%" for r, sh in zip(res["loads"], res.get("load_shares", []))]
            lines.append(_("Carichi: {0}.").format(", ".join(parts)))
            lines.append(_("Risultato teorico: correnti stimate dal tipo e dal valore dei componenti, "
                           "non da una simulazione del circuito."))
        lines.append(_("Percorso {0:.1f} mm, {1} cambi di layer.").format(res["length"], len(res["signal_vias"])))
        if dc:
            lines.append(_("Continua: la corrente di ritorno prende la strada a resistenza minima fra le "
                           "masse dei due componenti, anche lontano dalla traccia."))
        elif res["signal_vias"]:
            through_vias = sum(c for _x, _y, c in res["gnd_vias"])
            lines.append(_("Ritorno fra i piani: {0:.0f}% attraverso le via di massa, {1:.0f}% per capacita' "
                           "fra i piani (nessuna via vicina: rumore).").format(
                min(100, through_vias * 100), min(100, core["plane_jump"] * 100)))
        if not dc:
            lines.append(_("Stima quasi-statica ad alta frequenza."))
        summary = " ".join(lines)
        footprints, others = self._map_context(res, ref)
        data = mapview.MapData(
            _("Ritorno di corrente - net {0}").format(res["net"]) + (" (DC)" if dc else " (HF)"),
            background, pads, [], quantities, markers=markers,
            fixed_ranges=ranges, raster=raster, summary=summary,
            footprints=footprints, others=others)
        mapview.MapFrame(self, data).Show()
        self.status_label.SetLabel(summary)
        self.Layout()

    def on_cancel(self, event):
        self._cancel_requested = True
        self.status_label.SetLabel(_("Interruzione in corso..."))

    def on_clear(self, event):
        if self.dialog.markers:
            return_path.clear_highlight(self.board, self.dialog.markers)
            self.dialog.markers = []
        self.status_label.SetLabel("")


class LoadsDialog(wx.Dialog):
    """
    Loads of the return map with their estimated current, before the
    calculation: the user can exclude a load or correct its current. The
    voltage of the line and the frequency (for the capacitors in HF) can
    be changed too, then 'Recalculate estimate' updates the table.
    """

    COLS = ("Usa", "Componente", "Pin", "Corrente (mA)", "Stima")

    def __init__(self, parent, board, pad_in, ref, mode, loads, volts, origin=None):
        import wx.grid as gridlib

        super().__init__(parent, title=_("Carichi della linea"), size=(900, 460),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.board, self.pad_in, self.ref, self.mode = board, pad_in, ref, mode
        self.loads = loads
        note = wx.StaticText(self, label=_(
            "Correnti stimate dal tipo e dal valore dei componenti (risultato teorico, non una "
            "simulazione). Correggi i valori che conosci, togli la spunta ai carichi da escludere."))
        note.Wrap(860)

        # Voltage of the line and frequency for the capacitors
        row = wx.BoxSizer(wx.HORIZONTAL)
        row.Add(wx.StaticText(self, label=_("Tensione della linea (V):")), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        self.v_ctrl = wx.TextCtrl(self, value=f"{volts:g}", size=(60, -1))
        row.Add(self.v_ctrl, 0, wx.RIGHT, 6)
        # Where the voltage comes from; if it was not found, the field is
        # highlighted and the text asks for the real value
        if origin:
            v_note = wx.StaticText(self, label="(" + origin + ")")
        else:
            v_note = wx.StaticText(self, label=_("tensione non trovata: {0:g} V ipotizzati, "
                                                 "scrivi quella vera").format(volts))
            v_note.SetForegroundColour(wx.Colour(220, 60, 40))
            self.v_ctrl.SetBackgroundColour(wx.Colour(255, 220, 200))
        self.v_note = v_note
        row.Add(v_note, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 15)
        self.f_ctrl = None
        if mode != "dc":
            row.Add(wx.StaticText(self, label=_("Frequenza per i condensatori (MHz):")), 0,
                    wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
            self.f_ctrl = wx.TextCtrl(self, value="10", size=(60, -1))
            row.Add(self.f_ctrl, 0, wx.RIGHT, 15)
        again = wx.Button(self, label=_("Ricalcola stima"))
        again.Bind(wx.EVT_BUTTON, self.on_recalc)
        row.Add(again, 0)

        # Table: checkbox, reference, pin, current (editable), reason
        self.grid = gridlib.Grid(self)
        self.grid.CreateGrid(len(loads), len(self.COLS))
        for c, name in enumerate(self.COLS):
            self.grid.SetColLabelValue(c, _(name))
        self.grid.SetColFormatBool(0)
        self.grid.SetRowLabelSize(0)
        self.fill()

        btns = self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL)
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(note, 0, wx.ALL, 8)
        sizer.Add(row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        sizer.Add(self.grid, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)
        sizer.Add(btns, 0, wx.EXPAND | wx.ALL, 8)
        self.SetSizer(sizer)

    def fill(self):
        """Writes the loads in the table; only 'Use' and the current are editable."""
        for r, d in enumerate(self.loads):
            self.grid.SetCellValue(r, 0, "1" if d["include"] else "")
            self.grid.SetCellValue(r, 1, d["ref"])
            self.grid.SetCellValue(r, 2, d["pin"])
            self.grid.SetCellValue(r, 3, f"{d['current'] * 1000:.4g}")
            self.grid.SetCellValue(r, 4, d["reason"])
            for c in (1, 2, 4):
                self.grid.SetReadOnly(r, c, True)
        self.grid.AutoSizeColumns()

    @staticmethod
    def _num(text, default):
        """Number from a text field, decimal comma accepted."""
        try:
            return float(text.strip().replace(",", "."))
        except ValueError:
            return default

    def on_recalc(self, event):
        """New estimate with the voltage and frequency written above."""
        volts = self._num(self.v_ctrl.GetValue(), 3.3)
        freq = self._num(self.f_ctrl.GetValue(), 10.0) * 1e6 if self.f_ctrl else 10e6
        self.loads, _v, _o = load_estimate.estimate_loads(self.board, self.pad_in, self.ref, self.mode,
                                                          volts=volts, freq_hz=freq)
        # Voltage written by the user: no longer an assumption
        self.v_note.SetLabel(_("(scritta da te)"))
        self.v_note.SetForegroundColour(wx.NullColour)
        self.v_ctrl.SetBackgroundColour(wx.NullColour)
        self.Layout()
        self.grid.ClearGrid()
        n = self.grid.GetNumberRows()
        if n < len(self.loads):
            self.grid.AppendRows(len(self.loads) - n)
        self.fill()

    def result(self):
        """
        Loads kept by the user, with the current of the table (A). Empty
        list (and a message) if nothing is left with a current above zero.
        """
        out = []
        for r, d in enumerate(self.loads):
            if self.grid.GetCellValue(r, 0) not in ("1", "true", "True"):
                continue
            ma = self._num(self.grid.GetCellValue(r, 3), 0.0)
            if ma <= 0:
                continue
            item = dict(d)
            item["current"] = ma / 1000.0
            out.append(item)
        if not out:
            wx.MessageBox(_("Nessun carico con corrente maggiore di zero: inserisci almeno una corrente."),
                          _("Mappa ritorno"), wx.OK | wx.ICON_INFORMATION, self)
        return out
