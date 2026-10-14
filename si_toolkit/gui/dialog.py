"""
Dialog principale del plugin: una finestra con un Notebook (schede), una
per ogni modulo di analisi.

Per ora solo la scheda "Return Path" è funzionante; le altre tre sono
segnaposto per i moduli successivi della roadmap (distribuzione
corrente DC, calcolatore impedenza, integrazione openEMS) — vedi
README.md del progetto.
"""
import math
import os

import pcbnew
import wx
import wx.html  # pagine HTML (Aiuto, Verifica openEMS)

from ..analysis import crosstalk, dc_current, impedance, openems_check, openems_export, return_path
from ..common import geometry
from ..common import i18n
from ..common.settings_path import settings_path
from ..common.i18n import _
from . import help_text, mapview

# Soglie sul rapporto corrente/limite IPC-2221: oltre CRITICAL il limite e' superato,
# oltre WARNING ci si avvicina (80%)
CRITICAL_RATIO = 1.0
WARNING_RATIO = 0.8


# --- Impostazioni salvate su file (nella cartella utente di KiCad, vedi
# common/settings_path.py: cosi' sopravvivono agli aggiornamenti del plugin) ---
SETTINGS_PATH = settings_path()


def load_settings():
    """Legge le impostazioni salvate; dizionario vuoto se il file manca o e' rotto."""
    import json

    try:
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_setting(key, value):
    """Aggiorna una singola impostazione e riscrive il file."""
    import json

    data = load_settings()
    data[key] = value
    try:
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass  # impostazioni non salvabili: non e' un errore bloccante


def persist(ctrl, key):
    """
    Collega una casella di testo al file impostazioni: all'apertura
    carica il valore salvato (se c'e'), e lo salva a ogni modifica.
    """
    saved = load_settings().get(key)
    if saved is not None:
        ctrl.ChangeValue(str(saved))  # ChangeValue non genera EVT_TEXT
    ctrl.Bind(wx.EVT_TEXT, lambda evt: (save_setting(key, ctrl.GetValue()), evt.Skip()))


def persist_check(ctrl, key):
    """Come persist(), ma per una casella di spunta."""
    saved = load_settings().get(key)
    if saved is not None:
        ctrl.SetValue(bool(saved))  # SetValue non genera EVT_CHECKBOX
    ctrl.Bind(wx.EVT_CHECKBOX, lambda evt: (save_setting(key, ctrl.GetValue()), evt.Skip()))


def persist_all(panel, prefix, skip=()):
    """
    Rende persistenti tutte le caselle di testo (attributi che finiscono in
    '_ctrl') e le spunte ('_check') di una scheda: chiave = prefisso + nome
    dell'attributo. Le scelte legate alla board (net, pad) non si salvano.
    """
    for name, obj in list(vars(panel).items()):
        if name in skip:
            continue
        # Controlli presi in prestito da un'altra scheda (es. Opzioni):
        # li salva gia' la scheda che li contiene
        if isinstance(obj, wx.Window) and obj.GetParent() is not panel:
            continue
        key = f"{prefix}_{name}"
        if name.endswith("_ctrl") and isinstance(obj, wx.TextCtrl):
            persist(obj, key)
        elif name.endswith("_check") and isinstance(obj, wx.CheckBox):
            persist_check(obj, key)


def add_help_button(panel, row, key):
    """
    Pulsante "?" in fondo a una riga di pulsanti: apre una finestrella con
    il disegno e la spiegazione della scheda (stessa parte della scheda Aiuto).
    """
    btn = wx.Button(panel, label="?", size=(28, -1))
    btn.SetToolTip(_("Cosa fa questa scheda e quali dati inserire"))
    btn.Bind(wx.EVT_BUTTON, lambda evt: show_tab_help(panel, key))
    row.Add(btn, 0, wx.LEFT, 12)


def show_tab_help(parent, key):
    """Finestra con la sola sezione dell'aiuto relativa a una scheda."""
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
    Cartella predefinita per le simulazioni openEMS: fuori da OneDrive
    (che blocca i file mentre li sincronizza), in AppData locale.
    """
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "SI_Toolkit", "openems_runs")


def make_light_images():
    """
    Lista di icone del semaforo (0 verde, 1 giallo, 2 rosso) per le colonne
    "Stato". Disegnate con wx, senza file esterni.
    """
    images = wx.ImageList(14, 14)
    for colour in ((60, 180, 75), (245, 190, 30), (220, 50, 47)):
        bmp = wx.Bitmap(14, 14)
        dc = wx.MemoryDC(bmp)
        dc.SetBackground(wx.Brush(wx.WHITE))
        dc.Clear()
        dc.SetBrush(wx.Brush(wx.Colour(*colour)))
        dc.SetPen(wx.Pen(wx.Colour(80, 80, 80), 1))
        dc.DrawCircle(7, 7, 6)
        dc.SelectObject(wx.NullBitmap)
        # Il bianco di sfondo diventa trasparente
        bmp.SetMask(wx.Mask(bmp, wx.WHITE))
        images.Add(bmp)
    return images


class SIToolkitDialog(wx.Dialog):
    def __init__(self, parent, board):
        # Lingua dell'interfaccia (scheda Opzioni): va impostata prima di
        # creare qualunque testo
        i18n.set_language(load_settings().get("lang", "en"))  # default: inglese
        super().__init__(
            parent,
            title=_("PCB Signal Integrity Toolkit"),
            size=(860, 520),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self.board = board
        # Marker grafici (PCB_SHAPE) creati dall'ultima analisi, da
        # rimuovere quando si chiude il dialog o si rilancia l'analisi
        self.markers = []

        notebook = wx.Notebook(self)
        # La scheda Opzioni si crea per PRIMA (le altre usano i suoi
        # controlli) ma si mostra in fondo, prima dell'Aiuto
        self.options = OptionsPanel(notebook, self)
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

        # Dimensione minima = quella che serve alla scheda piu' larga per
        # mostrare tutti i campi e i pulsanti (il Notebook la calcola sul
        # massimo delle sue pagine), senza superare lo schermo
        best = self.GetBestSize()
        idx = wx.Display.GetFromWindow(self)
        area = wx.Display(idx if idx != wx.NOT_FOUND else 0).GetClientArea()
        min_w = min(best.width, area.width)
        min_h = min(max(best.height, 420), area.height)
        self.SetMinSize((min_w, min_h))
        self._restore_geometry(min_w, min_h)

        # Un dialog non modale, alla chiusura con la X, per default viene
        # solo nascosto: lo distruggiamo noi, così Destroy() ripulisce i
        # marker e la prossima esecuzione del plugin ne crea uno nuovo.
        self.Bind(wx.EVT_CLOSE, self.on_close)

    def _restore_geometry(self, min_w, min_h):
        """
        Riporta la finestra alla posizione e dimensione dell'ultima volta
        (salvate in settings.json alla chiusura). Se lo schermo non c'e' piu'
        (es. monitor scollegato) la finestra si centra.
        """
        rect = load_settings().get("window_rect")
        try:
            x, y, w, h = (int(v) for v in rect)
        except Exception:
            x = y = None
            w, h = 860, 520
        self.SetSize((max(w, min_w), max(h, min_h)))
        # La barra del titolo deve cadere su uno schermo esistente
        if x is not None and wx.Display.GetFromPoint(wx.Point(x + 60, y + 15)) != wx.NOT_FOUND:
            self.SetPosition((x, y))
        else:
            self.CentreOnParent()

    def _save_geometry(self):
        """Salva posizione e dimensione della finestra (non se ridotta a icona)."""
        try:
            if not self.IsIconized() and not self.IsMaximized():
                r = self.GetRect()
                save_setting("window_rect", [r.x, r.y, r.width, r.height])
        except Exception:
            pass  # non e' grave: la prossima volta si apre con i valori di default

    def on_close(self, event):
        self.Destroy()

    def Destroy(self):
        # Prima di chiudere: posizione e dimensione per la prossima apertura
        self._save_geometry()
        # Pulizia dei marker grafici alla chiusura del dialog: se
        # l'utente chiude senza premere "Pulisci overlay" non deve
        # restare nessun segnaccio residuo sulla board.
        if self.markers:
            return_path.clear_highlight(self.board, self.markers)
            self.markers = []
        return super().Destroy()


class OptionsPanel(wx.Panel):
    """
    Scheda "Opzioni": impostazioni comuni a piu' schede (stackup, massa,
    corrente DC, openEMS) e lingua. Le altre schede usano direttamente
    questi controlli (self.er_ctrl = options.er_ctrl, ecc.).
    """

    DEFAULT_PYTHON = r"D:\Users\ugosi\AppData\Local\Programs\Python\Python310\python.exe"

    def __init__(self, parent, dialog):
        super().__init__(parent)

        def grid(box_title, rows):
            """Riquadro con titolo e coppie etichetta/controllo su due colonne."""
            box = wx.StaticBoxSizer(wx.VERTICAL, self, _(box_title))
            g = wx.FlexGridSizer(cols=2, vgap=6, hgap=8)
            g.AddGrowableCol(1)
            for label, ctrl in rows:
                g.Add(wx.StaticText(self, label=_(label)), 0, wx.ALIGN_CENTER_VERTICAL)
                g.Add(ctrl, 1, wx.EXPAND)
            box.Add(g, 0, wx.EXPAND | wx.ALL, 6)
            return box

        # --- Generale ---
        self.lang_choice = wx.Choice(self, choices=["Italiano", "English"])
        self.lang_choice.SetSelection(1 if i18n.LANG == "en" else 0)
        self.lang_choice.Bind(wx.EVT_CHOICE, self.on_language)
        lang_note = wx.StaticText(self, label=_("La lingua si applica alla prossima apertura del plugin."))

        # --- Stackup e massa (Impedenza, Coppie diff., openEMS) ---
        # "auto" = valori letti dallo stackup della scheda
        self.er_ctrl = wx.TextCtrl(self, value="auto", size=(70, -1))
        self.h_ctrl = wx.TextCtrl(self, value="auto", size=(70, -1))
        self.mask_check = wx.CheckBox(self, label=_("Considera il solder mask (layer esterni)"))
        self.mask_check.SetValue(True)
        # Net che fa da massa per il rilevamento automatico
        self.gnd_ctrl = wx.TextCtrl(self, value="GND", size=(70, -1))

        # --- Corrente DC ---
        self.copper_ctrl = wx.TextCtrl(self, value="auto", size=(70, -1))
        self.plating_ctrl = wx.TextCtrl(self, value="25", size=(70, -1))
        # Aumento di temperatura ammesso, per il limite di corrente IPC-2221
        self.dt_ctrl = wx.TextCtrl(self, value="10", size=(70, -1))
        # Zone di rame come collegamenti a resistenza nulla (vedi dc_current)
        self.zones_check = wx.CheckBox(self, label=_("Zone di rame = resistenza nulla"))
        self.zones_check.SetValue(True)

        # --- openEMS ---
        self.python_ctrl = wx.TextCtrl(self, value=self.DEFAULT_PYTHON, size=(420, -1))
        # Cartella dove e' installato openEMS (contiene le DLL)
        self.oe_ctrl = wx.TextCtrl(self, value=r"D:\Programmi\openEMS", size=(420, -1))
        self.runs_ctrl = wx.TextCtrl(self, value=default_runs_dir(), size=(420, -1))
        browse_btn = wx.Button(self, label=_("Sfoglia..."))
        browse_btn.Bind(wx.EVT_BUTTON, self.on_browse_runs)
        runs_row = wx.BoxSizer(wx.HORIZONTAL)
        runs_row.Add(self.runs_ctrl, 1, wx.RIGHT, 5)
        runs_row.Add(browse_btn, 0)
        self.mesh_ctrl = wx.TextCtrl(self, value="0.1", size=(70, -1))
        self.margin_ctrl = wx.TextCtrl(self, value="3", size=(70, -1))

        # I valori salvati con le versioni precedenti (chiavi della vecchia
        # scheda openEMS) si recuperano una volta sola
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
        # Controllo dell'installazione di openEMS (Python, moduli, DLL)
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
        # Tutti i valori ricordati fra un'apertura e l'altra
        persist_all(self, "opt")

    def on_check_openems(self, event):
        """Pulsante Verifica openEMS: in caso di errore imprevisto lo mostra."""
        try:
            self._check_openems()
        except Exception:
            import traceback

            wx.MessageBox(traceback.format_exc(), _("Verifica openEMS"), wx.OK | wx.ICON_ERROR, self)

    def _check_openems(self):
        """
        Verifica l'installazione di openEMS e mostra il rapporto. Se mancano
        pacchetti installabili (pip o file .whl di openEMS) propone di
        installarli, dopo conferma, in una finestra visibile.
        """
        python_exe = self.python_ctrl.GetValue().strip()
        oe_dir = self.oe_ctrl.GetValue().strip()
        # Finestrella "attendere": il controllo avvia il Python esterno e
        # importa openEMS, ci vogliono alcuni secondi
        busy = wx.BusyCursor()
        info = wx.BusyInfo(_("Verifica di openEMS in corso, attendere alcuni secondi..."), self)
        wx.GetApp().Yield()  # disegna subito la finestrella prima di bloccarsi nel controllo
        try:
            res = openems_check.check(python_exe, oe_dir)
        finally:
            del info
            del busy

        # Rapporto in HTML: verde = ok, arancio = avviso, rosso = errore
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
        """Installa (dopo conferma) i pacchetti mancanti in una finestra visibile."""
        import subprocess
        import sys

        cmd = openems_check.install_command(python_exe, res["pip"], res["wheels"])
        msg = _("Verra' eseguito questo comando (serve Internet per i pacchetti da pip):\n\n{0}\n\nProcedere?").format(
            " ".join(f'"{c}"' if " " in c else c for c in cmd))
        if wx.MessageBox(msg, _("Installa pacchetti mancanti"), wx.YES_NO | wx.ICON_QUESTION, parent) != wx.YES:
            return
        if sys.platform.startswith("win"):
            # cmd /k: la finestra resta aperta alla fine, per leggere l'esito
            subprocess.Popen(["cmd", "/k"] + cmd, creationflags=subprocess.CREATE_NEW_CONSOLE)
        else:
            subprocess.Popen(cmd)
        wx.MessageBox(_("Installazione avviata in una finestra separata. Quando ha finito, "
                        "premi di nuovo 'Verifica openEMS'."), _("Verifica openEMS"), wx.OK, parent)

    def on_language(self, event):
        """Salva la lingua scelta: vale dalla prossima apertura del plugin."""
        save_setting("lang", "en" if self.lang_choice.GetSelection() == 1 else "it")

    def on_browse_runs(self, event):
        """Sceglie la cartella dei risultati di openEMS con la finestra di Windows."""
        start = self.runs_ctrl.GetValue().strip() or default_runs_dir()
        dlg = wx.DirDialog(self, _("Cartella per i risultati di openEMS"), start)
        if dlg.ShowModal() == wx.ID_OK:
            self.runs_ctrl.SetValue(dlg.GetPath())  # SetValue salva anche l'impostazione
        dlg.Destroy()


class HelpPanel(wx.Panel):
    """Scheda "Aiuto": guida essenziale, nella lingua scelta."""

    def __init__(self, parent):
        super().__init__(parent)
        html = wx.html.HtmlWindow(self, style=wx.html.HW_SCROLLBAR_AUTO)
        html.SetPage(help_text.page(i18n.LANG))
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(html, 1, wx.EXPAND | wx.ALL, 5)
        self.SetSizer(sizer)


class PlaceholderPanel(wx.Panel):
    """Scheda segnaposto per i moduli non ancora implementati."""

    def __init__(self, parent, module_name):
        super().__init__(parent)
        sizer = wx.BoxSizer(wx.VERTICAL)
        label = wx.StaticText(
            self, label=_("Modulo \"{0}\" non ancora implementato.").format(module_name)
        )
        sizer.Add(label, 0, wx.ALL | wx.ALIGN_CENTER, 20)
        self.SetSizer(sizer)


class DcCurrentPanel(wx.Panel):
    """Scheda "Corrente DC": come si ripartisce la corrente fra tracce e via."""

    def __init__(self, parent, dialog):
        super().__init__(parent)
        self.board = dialog.board
        self._pads = []  # (etichetta, pad) della net scelta
        self._elements = []  # risultati dell'ultimo calcolo, come le righe

        # --- Riga 1: scelta net e pad di ingresso ---
        row1 = wx.BoxSizer(wx.HORIZONTAL)
        self.net_choice = wx.Choice(self, choices=dc_current.list_nets(self.board))
        self.net_choice.Bind(wx.EVT_CHOICE, self.on_net_changed)
        self.src_choice = wx.Choice(self)
        self.snk_choice = wx.Choice(self)
        # Cambiando ingresso o uscita si ricalcola e si evidenzia il tratto
        self.src_choice.Bind(wx.EVT_CHOICE, self.on_pads_changed)
        self.snk_choice.Bind(wx.EVT_CHOICE, self.on_pads_changed)
        for label, ctrl in (("Net:", self.net_choice),
                            ("Ingresso:", self.src_choice)):
            row1.Add(wx.StaticText(self, label=_(label)), 0,
                     wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
            row1.Add(ctrl, 0, wx.RIGHT, 12)

        # --- Riquadro "Uscite": tutte le uscite insieme, ognuna con la sua
        # corrente. A sinistra si sceglie pad + corrente e si aggiunge, a
        # destra c'e' l'elenco. Con l'elenco vuoto si usa direttamente il
        # pad scelto con la sua corrente (caso semplice: una sola uscita).
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
        # Elenco delle uscite: pad e corrente
        self.loads_list = wx.ListCtrl(self, style=wx.LC_REPORT, size=(230, 95))
        self.loads_list.InsertColumn(0, _("Pad"), width=110)
        self.loads_list.InsertColumn(1, _("Corrente (A)"), width=100)
        self.loads = []  # [(etichetta, corrente A)] nell'ordine dell'elenco
        out_box.Add(left, 0, wx.ALL, 6)
        out_box.Add(self.loads_list, 0, wx.ALL, 6)

        # --- Riga 2: parametri del modello ---
        # Parametri del modello (rame, placcatura, DT, zone): stanno nella
        # scheda Opzioni; qui si usano gli stessi controlli
        opts = dialog.options
        self.copper_ctrl = opts.copper_ctrl
        self.plating_ctrl = opts.plating_ctrl
        self.dt_ctrl = opts.dt_ctrl
        self.zones_check = opts.zones_check
        # --- Riga 3: pulsanti ---
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

        # --- Lista risultati (ordinata per densita' di corrente) ---
        self.results_list = wx.ListCtrl(self, style=wx.LC_REPORT)
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
        # Ricorda i valori delle caselle fra un'apertura e l'altra
        persist_all(self, "dc")

    def on_net_changed(self, event):
        """Alla scelta della net riempie le liste dei pad e la evidenzia."""
        self._load_net(self.net_choice.GetStringSelection(), highlight=True)

    def _load_net(self, net, highlight):
        """
        Riempie le liste dei pad ingresso/uscita per la net data. Se
        'highlight' e' vero seleziona in Pcbnew tutta la net (non lo si fa
        quando la net viene dalla selezione dell'utente, per non
        sovrascriverla).
        """
        self._pads = dc_current.list_pads(self.board, net)
        labels = [label for label, _pad in self._pads]
        for ctrl in (self.src_choice, self.snk_choice):
            ctrl.Set(labels)
        # L'elenco delle uscite vale solo per la net su cui e' stato fatto
        self._set_loads([])
        if labels:
            # Default: primo pad come ingresso, ultimo come uscita
            self.src_choice.SetSelection(0)
            self.snk_choice.SetSelection(len(labels) - 1)
        # Cambiata la net: via i risultati vecchi
        self._clear_results()
        if highlight:
            self._select(dc_current.net_items(self.board, net))
            self.status_label.SetLabel(_("Net {0} evidenziata ({1} pad).").format(net, len(labels)))

    def on_from_selection(self, event):
        """
        Porta nella scheda cio' che e' selezionato in Pcbnew: la net della
        traccia/via/pad selezionato e, se sono selezionati uno o due pad,
        li usa come ingresso (e uscita) e calcola.
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

        # Pad selezionati (nell'ordine in cui li restituisce Pcbnew) sulla net
        labels = [label for label, _p in self._pads]
        sel_pads = [dc_current.pad_label(i) for i in selected
                    if i.GetNetname() == net and dc_current.is_pad(i)]
        sel_pads = [l for l in sel_pads if l in labels]
        if sel_pads:
            self.src_choice.SetSelection(labels.index(sel_pads[0]))
        if len(sel_pads) >= 2:
            self.snk_choice.SetSelection(labels.index(sel_pads[1]))
            # Con 3 o piu' pad: tutti tranne il primo diventano uscite, con
            # la corrente scritta nella casella (poi si correggono)
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
        """Scelti ingresso/uscita: calcola e evidenzia la parte fra i due pad."""
        self.on_calculate(event)

    def _clear_results(self):
        self._elements = []
        self.results_list.DeleteAllItems()

    def on_reset(self, event):
        """Azzera lista, selezione in Pcbnew e messaggio."""
        self._clear_results()
        self._select([])
        self.status_label.SetLabel(_("Scegli una net, un pad di ingresso e uno di uscita."))

    @staticmethod
    def _number(ctrl, default):
        """Legge un numero da una casella (accetta la virgola decimale)."""
        try:
            return float(ctrl.GetValue().strip().replace(",", "."))
        except ValueError:
            return default

    def _set_loads(self, loads):
        """Sostituisce l'elenco delle uscite e aggiorna la tabella."""
        self.loads = list(loads)
        self.loads_list.DeleteAllItems()
        for label, amps in self.loads:
            idx = self.loads_list.InsertItem(self.loads_list.GetItemCount(), _(label))
            self.loads_list.SetItem(idx, 1, f"{amps:g}")

    def on_add_load(self, event):
        """Aggiunge all'elenco il pad scelto con la sua corrente."""
        label = self.snk_choice.GetStringSelection()
        if not label:
            self.status_label.SetLabel(_("Scegli il pad dell'uscita."))
            return
        amps = self._number(self.current_ctrl, None)
        if amps is None or amps <= 0:
            self.status_label.SetLabel(_("Corrente non valida."))
            return
        # Stesso pad gia' presente: si aggiorna la corrente invece di duplicarlo
        loads = [(l, a) for l, a in self.loads if l != label] + [(label, amps)]
        self._set_loads(loads)
        self.on_calculate(event)

    def on_remove_load(self, event):
        """Toglie dall'elenco l'uscita selezionata."""
        k = self.loads_list.GetFirstSelected()
        if k < 0:
            self.status_label.SetLabel(_("Seleziona nell'elenco l'uscita da togliere."))
            return
        self._set_loads(self.loads[:k] + self.loads[k + 1:])
        self.on_calculate(event)

    def on_clear_loads(self, event):
        """Svuota l'elenco: si torna a una sola uscita."""
        self._set_loads([])
        self.on_calculate(event)

    def _loads(self):
        """
        Carichi da simulare [(etichetta, pad, corrente A)]: quelli
        dell'elenco, oppure, se l'elenco e' vuoto, il pad scelto con la
        corrente della casella.
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
        # Svuota sempre la lista prima: se il calcolo fallisce non devono
        # restare righe di un calcolo precedente
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
            # Rete non collegata, pad uguali, ecc.: messaggio chiaro, e si
            # toglie anche la selezione in Pcbnew (niente tratto evidenziato)
            self._select([])
            self.status_label.SetLabel(_(str(exc)) + _("  [dettagli nel file dc_diagnostics.txt]"))
            self.status_label.Wrap(self.GetSize().GetWidth() - 40)
            self.Layout()
            return

        self._elements = result.elements
        self.results_list.DeleteAllItems()
        for el in result.elements:
            # Semaforo: verde sotto l'80% del limite, giallo fra 80% e 100%,
            # rosso dal 100% in su
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
        # Riga 1: risultati; riga 2: note sul modello usato
        line1 = (_("R totale = {0:.2f} mOhm, caduta = {1:.2f} mV, potenza = {2:.2f} mW. Oltre il limite: {3}, al limite: {4}.").format(result.total_resistance_ohm * 1000, result.total_drop_v * 1000, result.total_power_w * 1000, n_crit, n_warn))
        if len(result.load_drops) > 1:
            # Piu' uscite: caduta dall'ingresso a ciascuna. La "R totale" e'
            # solo un equivalente (caduta peggiore / corrente totale)
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
        # Evidenzia in Pcbnew il tratto percorso dalla corrente fra i due pad
        self._select([el.item for el in result.elements])

    def on_row_selected(self, event):
        """Click su una riga: seleziona in Pcbnew la traccia o la via."""
        idx = event.GetIndex()
        if 0 <= idx < len(self._elements):
            self._select([self._elements[idx].item])

    def on_select_all(self, event):
        self._select([el.item for el in self._elements])

    def on_map(self, event):
        """
        Apre la mappa a colori dei risultati: tutte le tracce della scheda
        in grigio come riferimento, quelle percorse dalla corrente colorate
        secondo la grandezza scelta (densita', % limite, tensione, corrente).
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
                              # Tensione sfumata da GetStart() a GetEnd()
                              "grad": {"Tensione (IR drop)": (el.v_start * 1000, el.v_end * 1000)}})
            else:
                c = it.GetPosition()
                r = mm(it.GetBoundingBox().GetWidth()) / 2
                items.append({"kind": "via", "via": (mm(c.x), mm(c.y), r),
                              "values": values, "label": label})

        # Riferimenti per le scale fisse: densita' al limite IPC (la piu'
        # bassa fra gli elementi: e' la piu' prudente) e corrente totale
        limits = [el.density_a_mm2 / el.ratio for el in self._elements if el.ratio > 0]
        density_at_limit = min(limits) if limits else max(el.density_a_mm2 for el in self._elements)
        try:
            loads = self._loads()
        except ValueError:
            loads = []
        total_current = sum(a for _l, _p, a in loads) or max(el.current_a for el in self._elements)

        # Marcatori sui pad di ingresso (verde) e uscita (rossa) della corrente
        markers = []
        k = self.src_choice.GetSelection()
        if 0 <= k < len(self._pads):
            label, pad = self._pads[k]
            c = pad.GetPosition()
            markers.append((mm(c.x), mm(c.y), _("IN {0}").format(label), (60, 210, 90)))
        # Un marcatore OUT per ogni uscita, con la sua corrente
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
                # % del limite: 0 = blu, 100% = rosso-arancio, 120% = rosso pieno
                "% del limite IPC": (0.0, 120.0),
                # Densita': da 0 alla densita' corrispondente al limite IPC
                # delle tracce analizzate (il rosso vuol dire "al limite")
                "Densita' di corrente": (0.0, density_at_limit),
                # Corrente: da 0 alla corrente totale impostata
                "Corrente": (0.0, total_current),
            },
        )
        frame = mapview.MapFrame(wx.GetTopLevelParent(self), data)
        frame.Show()

    def on_select_critical(self, event):
        """Seleziona in Pcbnew solo gli elementi al limite o oltre."""
        critical = [el.item for el in self._elements if el.ratio >= WARNING_RATIO]
        if not critical:
            self.status_label.SetLabel(_("Nessun elemento vicino al limite di corrente."))
            return
        self._select(critical)
        self.status_label.SetLabel(_("Selezionati {0} elementi critici o vicini al limite.").format(len(critical)))

    def _select(self, items):
        try:
            # Deseleziona tracce, via e pad, poi seleziona gli elementi dati
            for it in list(self.board.GetTracks()) + list(self.board.GetPads()):
                if it.IsSelected():
                    it.ClearSelected()
            for it in items:
                it.SetSelected()
            pcbnew.Refresh()
        except Exception as exc:
            self.status_label.SetLabel(_("Impossibile selezionare: {0}").format(exc))


class ImpedancePanel(wx.Panel):
    """Scheda "Impedenza": Z0 delle tracce dallo stackup della scheda."""

    def __init__(self, parent, dialog):
        super().__init__(parent)
        self.board = dialog.board
        self._groups = []  # un gruppo per riga: lista di tracce (net, layer, larghezza)

        row = wx.BoxSizer(wx.HORIZONTAL)
        self.net_filter_ctrl = wx.TextCtrl(self, value="", size=(120, -1))
        self.target_ctrl = wx.TextCtrl(self, value="50", size=(50, -1))
        self.tol_ctrl = wx.TextCtrl(self, value="10", size=(40, -1))
        # Stackup (Er, dielettrico), solder mask e net di massa: scheda Opzioni
        opts = dialog.options
        self.er_ctrl, self.h_ctrl = opts.er_ctrl, opts.h_ctrl
        self.gnd_ctrl, self.mask_check = opts.gnd_ctrl, opts.mask_check
        # Distanza dalla massa sullo stesso layer (microstrip coplanare)
        self.gap_ctrl = wx.TextCtrl(self, value="auto", size=(45, -1))
        # Riga 1: filtro e target; riga 2: gap e pulsanti
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

        self.results_list = wx.ListCtrl(self, style=wx.LC_REPORT)
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
        # Ricorda i valori delle caselle fra un'apertura e l'altra
        persist_all(self, "imp")

    @staticmethod
    def _number(ctrl, default):
        try:
            return float(ctrl.GetValue().strip().replace(",", "."))
        except ValueError:
            return default

    def on_from_selection(self, event):
        """Imposta il filtro sulle net delle tracce selezionate e calcola."""
        nets = sorted({t.GetNetname() for t in self.board.GetTracks()
                       if t.IsSelected() and t.GetNetname()})
        if not nets:
            self.status_label.SetLabel(_("Niente di selezionato in Pcbnew: seleziona una o piu' tracce."))
            return
        # Il filtro e' una sottostringa: con piu' net si elencano separate da |
        self.net_filter_ctrl.SetValue("|".join(nets))
        self.on_calculate(event)

    def on_calculate(self, event):
        target = self._number(self.target_ctrl, 50.0)
        tol = self._number(self.tol_ctrl, 10.0) / 100.0
        wanted = [f.strip().upper() for f in self.net_filter_ctrl.GetValue().split("|") if f.strip()]

        # Er e spessore del dielettrico: "auto" usa quelli della scheda
        er_text = self.er_ctrl.GetValue().strip().lower()
        h_text = self.h_ctrl.GetValue().strip().lower()
        er_override = None if er_text in ("", "auto") else self._number(self.er_ctrl, None)
        h_mm = None if h_text in ("", "auto") else self._number(self.h_ctrl, None)
        # Gap dalla massa coplanare: "no" = nessuna massa accanto alla traccia
        # "auto" = lo misura il plugin per ogni gruppo di tracce
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
        # Origine dei dati del solder mask (per il messaggio in basso)
        masks = [stackup.get(l, {}).get("mask") for l in outer]
        if any(masks):
            m = next(x for x in masks if x)
            mask_note = _("da stackup ({0:.0f} um, Er {1:.1f})").format(m[0] * 1e6, m[1])
        else:
            mask_note = "di default (10 um, Er 3,3: non presente nello stackup)"

        # Raggruppa le tracce per (net, layer, larghezza)
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
        zone_cache = {}  # zone di massa per layer, riusate fra i gruppi
        busy = wx.BusyCursor()  # il rilevamento della massa puo' richiedere qualche secondo
        for (net, layer, width), tracks in sorted(
            groups.items(), key=lambda kv: (kv[0][0], kv[0][1], kv[0][2])
        ):
            width_m = pcbnew.ToMM(width) * 1e-3
            # Massa laterale e piano sotto: misurati sulla scheda (solo per
            # le tracce esterne e non per le tracce di massa stesse)
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
            # Se il piano sotto manca in parte, l'impedenza calcolata non e' affidabile
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
        """Click su una riga: seleziona in Pcbnew le tracce del gruppo."""
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
    """Scheda "Coppie diff.": impedenza differenziale delle coppie di tracce."""

    def __init__(self, parent, dialog):
        super().__init__(parent)
        self.board = dialog.board
        self._rows = []  # per ogni riga: tracce da selezionare (le due net sul layer)
        self._manual_pair = None  # coppia scelta con "Da selezione" (nomi qualsiasi)

        row = wx.BoxSizer(wx.HORIZONTAL)
        self.filter_ctrl = wx.TextCtrl(self, value="", size=(120, -1))
        self.target_ctrl = wx.TextCtrl(self, value="100", size=(50, -1))
        self.tol_ctrl = wx.TextCtrl(self, value="10", size=(40, -1))
        # Stackup, solder mask e net di massa: scheda Opzioni
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
        # Il pulsante ricalcola le coppie riconosciute dal nome (azzera la
        # coppia scelta a mano con "Da selezione")
        calc_btn.Bind(wx.EVT_BUTTON, self.on_detect)
        row_b.Add(calc_btn, 0, wx.RIGHT, 5)
        sel_btn = wx.Button(self, label=_("Da selezione"))
        sel_btn.Bind(wx.EVT_BUTTON, self.on_from_selection)
        row_b.Add(sel_btn, 0)
        add_help_button(self, row_b, "diff_pair")

        self.results_list = wx.ListCtrl(self, style=wx.LC_REPORT)
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
        # Ricorda i valori delle caselle fra un'apertura e l'altra
        persist_all(self, "diff")

    @staticmethod
    def _number(ctrl, default):
        try:
            return float(ctrl.GetValue().strip().replace(",", "."))
        except ValueError:
            return default

    def on_from_selection(self, event):
        """
        Coppie dalle tracce selezionate. Se sono selezionate tracce di
        esattamente due net, quelle due net vengono trattate come coppia
        anche se i nomi non seguono la convenzione _P/_N (utile per tracce
        che corrono parallele per un tratto). Altrimenti si filtra sulle
        coppie riconosciute dal nome.
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

        # Tracce di ogni net, divise per layer
        by_net = {}
        for t in self.board.GetTracks():
            if t.Type() == pcbnew.PCB_TRACE_T and t.GetNetname():
                by_net.setdefault(t.GetNetname(), {}).setdefault(t.GetLayer(), []).append(t)
        if self._manual_pair:
            pairs = [self._manual_pair]  # coppia scelta a mano
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
            # Differenza di lunghezza totale fra le due net (skew)
            len_p = sum(pcbnew.ToMM(t.GetLength()) for ts in by_net[net_p].values() for t in ts)
            len_n = sum(pcbnew.ToMM(t.GetLength()) for ts in by_net[net_n].values() for t in ts)
            for layer in sorted(set(by_net[net_p]) & set(by_net[net_n])):
                tp, tn = by_net[net_p][layer], by_net[net_n][layer]
                # Larghezza: media fra la larghezza prevalente delle due net
                wp = sorted(t.GetWidth() for t in tp)[len(tp) // 2]
                wn = sorted(t.GetWidth() for t in tn)[len(tn) // 2]
                width_m = pcbnew.ToMM((wp + wn) / 2.0) * 1e-3
                spacing, fraction, _count = geometry.pair_spacing(
                    tp, tn, pcbnew.FromMM(0.5), 60, pcbnew.FromMM(1.5)
                )
                # Geometria del layer (dielettrici, rame, solder mask)
                geom = impedance.layer_geometry(stackup, layer, outer, self.mask_check.GetValue())
                model = impedance.layer_model(stackup, layer, outer)
                below = gap_m = None
                if ground_filter.upper() not in base.upper():
                    _lat, below = impedance.detect_coplanar(
                        self.board, tp, layer, ground_filter, zone_cache
                    )
                    # Massa laterale sul lato esterno della coppia (solo
                    # layer esterni: nelle stripline la si trascura)
                    if geom and geom["kind"] == "micro":
                        gap_m = impedance.pair_lateral_gap(
                            self.board, tp + tn, layer, ground_filter, zone_cache
                        )
                zdiff = zcomm = z0 = w_target = None
                if geom and spacing is not None:
                    s_m = spacing * 1e-9
                    # Risolutore di campo 2D: modo dispari (differenziale) e
                    # pari (comune) sulla sezione reale della coppia
                    zdiff, zcomm, _zo, _ze = impedance.pair_field(geom, width_m, s_m, gap_m)
                    z0 = impedance.field_z0(geom, width_m, gap_m)
                    w_target = impedance.width_for_diff_field(geom, s_m, target, gap_m)
                # Semaforo sul valore di Zdiff; poco accoppiata = non affidabile
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
        """Click su una riga: seleziona in Pcbnew le tracce delle due net sul layer."""
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
    """Scheda "Crosstalk": tratti di tracce parallele e disturbo stimato."""

    # Soglie del semaforo sul NEXT stimato (frazione del segnale)
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
        # Tempi di salita per net: "parte_del_nome=ns" separati da |. Le net
        # che non corrispondono usano il tempo generale qui sopra.
        self.per_net_ctrl = wx.TextCtrl(
            self, value="SDA=300|SCL=300|TX=20|RX=20", size=(220, -1)
        )
        for label, ctrl in (("Spazio max (mm):", self.spacing_ctrl),
                            ("Tratto minimo (mm):", self.minlen_ctrl),
                            ("Tempi per net (nome=ns):", self.per_net_ctrl)):
            row_b.Add(wx.StaticText(self, label=_(label)), 0,
                      wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
            row_b.Add(ctrl, 0, wx.RIGHT, 12)
        # Pulsanti su una riga propria: con i campi sulla stessa riga la
        # scheda diventava troppo larga e i pulsanti uscivano dalla finestra
        row_c = wx.BoxSizer(wx.HORIZONTAL)
        calc_btn = wx.Button(self, label=_("Calcola"))
        calc_btn.Bind(wx.EVT_BUTTON, self.on_calculate)
        row_c.Add(calc_btn, 0, wx.RIGHT, 5)
        sel_btn = wx.Button(self, label=_("Da selezione"))
        sel_btn.Bind(wx.EVT_BUTTON, self.on_from_selection)
        row_c.Add(sel_btn, 0)
        add_help_button(self, row_c, "crosstalk")

        self.results_list = wx.ListCtrl(self, style=wx.LC_REPORT)
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
        # Ricorda i valori delle caselle fra un'apertura e l'altra
        persist_all(self, "xtalk")

    @staticmethod
    def _number(ctrl, default):
        try:
            return float(ctrl.GetValue().strip().replace(",", "."))
        except ValueError:
            return default

    def on_from_selection(self, event):
        """Filtra sulle net delle tracce selezionate e calcola."""
        nets = sorted({t.GetNetname() for t in self.board.GetTracks()
                       if t.IsSelected() and t.GetNetname()})
        if not nets:
            self.status_label.SetLabel(_("Niente di selezionato in Pcbnew: seleziona una o piu' tracce."))
            return
        self.filter_ctrl.SetValue("|".join(nets))
        self.on_calculate(event)

    def on_calculate(self, event):
        rise_s = self._number(self.rise_ctrl, 1.0) * 1e-9
        # Regole "nome=ns": la prima che compare nel nome della net vince
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

        # Altezza sopra il piano e costante dielettrica efficace per layer
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
                h_plane = h / 2.0  # stripline: distanza dal piano piu' vicino
            center_m = (gap_med + width) * 1e-9  # distanza fra i centri
            # Conta il fronte piu' veloce dei due: e' quello che disturba di piu'
            pair_rise = min(net_rise(net_a), net_rise(net_b))
            coupling, nxt = crosstalk.next_estimate(
                center_m, h_plane, length_mm * 1e-3, pair_rise, eeff
            )
            rows.append((nxt, net_a, net_b, layer, length_mm, gaps[0], gap_med, coupling, r["tracks"], pair_rise))
        del busy

        # Dal disturbo piu' alto al piu' basso
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
        """Click su una riga: seleziona in Pcbnew le tracce del tratto parallelo."""
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
    """Scheda "openEMS": simulazione EM della linea selezionata (Python esterno)."""

    DEFAULT_PYTHON = r"D:\Users\ugosi\AppData\Local\Programs\Python\Python310\python.exe"

    def __init__(self, parent, dialog):
        super().__init__(parent)
        self.board = dialog.board
        self._last_dir = None

        # Python, cartella openEMS, cartella risultati, mesh, margine e net
        # di massa: scheda Opzioni (qui si usano gli stessi controlli)
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
        # Campi della scheda ricordati fra un'apertura e l'altra
        for ctrl, key in ((self.fmax_ctrl, "openems_fmax"),
                          (self.fmark_ctrl, "openems_fmark")):
            persist(ctrl, key)

        row_c = wx.BoxSizer(wx.HORIZONTAL)
        # Registrazione dei campi per le GIF animate (file grandi: spenta di
        # default, ma la scelta viene ricordata)
        self.fields_check = wx.CheckBox(self, label=_("Salva campi (GIF animate)"))
        self.fields_check.SetValue(bool(load_settings().get("openems_fields", False)))
        self.fields_check.Bind(
            wx.EVT_CHECKBOX,
            lambda evt: save_setting("openems_fields", self.fields_check.GetValue()),
        )
        row_c.Add(self.fields_check, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 12)
        # Tensione di picco del segnale sulla linea: i campi delle GIF
        # vengono riscalati a questo valore (V/mm reali)
        self.vsig_ctrl = wx.TextCtrl(self, value="1", size=(45, -1))
        self.vsig_ctrl.SetToolTip(_("Tensione di picco sulla linea per i campi delle GIF. "
                                  "Si puo' cambiare dopo, senza risimulare, con reprocess_fields.bat"))
        persist(self.vsig_ctrl, "openems_vsig")
        row_c.Add(wx.StaticText(self, label=_("Tensione segnale (V):")), 0,
                  wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        row_c.Add(self.vsig_ctrl, 0, wx.RIGHT, 12)
        # Scala colori fissa in V/mm (vuota = automatica): per confrontare
        # GIF fatte con tensioni diverse
        self.escale_ctrl = wx.TextCtrl(self, value="", size=(45, -1))
        self.escale_ctrl.SetToolTip(_("Vuoto = scala automatica. Con un valore fisso (es. 100) "
                                    "le GIF a tensioni diverse sono confrontabili a colpo d'occhio."))
        persist(self.escale_ctrl, "openems_escale")
        row_c.Add(wx.StaticText(self, label=_("Scala fissa (V/mm):")), 0,
                  wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        row_c.Add(self.escale_ctrl, 0, wx.RIGHT, 12)
        # Tempo di salita del gradino per il TDR/TDT (10-90%, in ns)
        self.trise_ctrl = wx.TextCtrl(self, value="1", size=(45, -1))
        self.trise_ctrl.SetToolTip(_("Fronte del segnale digitale per TDR/TDT. Serve f max >= 1,2 / tempo di salita "
                                   "(es. 0,5 ns -> f max >= 2,4 GHz)."))
        persist(self.trise_ctrl, "openems_trise")
        row_c.Add(wx.StaticText(self, label=_("Tempo salita (ns):")), 0,
                  wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        row_c.Add(self.trise_ctrl, 0, wx.RIGHT, 12)

        # --- Riga pulsanti: separata, cosi' non escono dal bordo della finestra ---
        row_e = wx.BoxSizer(wx.HORIZONTAL)
        sim_btn = wx.Button(self, label=_("Simula linea selezionata"))
        sim_btn.Bind(wx.EVT_BUTTON, self.on_simulate)
        row_e.Add(sim_btn, 0, wx.RIGHT, 5)
        # Rifa' le GIF dell'ultima simulazione con tensione/scala attuali,
        # senza simulare di nuovo (il calcolo e' lineare)
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
                # Massa campionata fine (0,05 mm), indipendente dalla mesh:
                # il bordo della massa determina il gap, che conta molto
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
                lang=i18n.LANG,  # lingua dei grafici
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
        """Avviso se f max e' troppo bassa per il tempo di salita scelto (TDR)."""
        tr = self._number(self.trise_ctrl, 1.0)
        fmax = self._number(self.fmax_ctrl, 3.0)
        need = 1.22 / tr if tr > 0 else 0  # GHz, con tr in ns
        if fmax < need:
            return (_("\nNota: per un fronte di {0:g} ns serve f max >= {1:.1f} GHz; con {2:g} GHz il TDR usera' un fronte piu' lento.").format(tr, need, fmax))
        return ""

    def _runs_root(self):
        """Cartella dove si creano le simulazioni (casella 'Cartella risultati')."""
        return self.runs_ctrl.GetValue().strip() or default_runs_dir()

    def _latest_run_dir(self):
        """Cartella dell'ultima simulazione: quella lanciata ora o la piu' recente su disco."""
        if self._last_dir and os.path.isdir(self._last_dir):
            return self._last_dir
        root = self._runs_root()
        if not os.path.isdir(root):
            return None
        runs = sorted(d for d in os.listdir(root) if d.startswith("sim_"))  # nome = data e ora
        return os.path.join(root, runs[-1]) if runs else None

    def on_redo_gif(self, event):
        """
        Rilancia lo script dell'ultima simulazione in modalita' --results
        con la tensione e la scala scritte nella scheda: rifa' solo le GIF.
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
        """Apre in Esplora risorse la cartella dell'ultima simulazione."""
        path = self._last_dir or self._runs_root()
        if os.path.isdir(path):
            os.startfile(path)
        else:
            self.status_label.SetLabel(_("Nessuna simulazione ancora eseguita."))


class ReturnPathPanel(wx.Panel):
    """Scheda funzionante per il return path checker."""

    def __init__(self, parent, dialog):
        super().__init__(parent)
        self.dialog = dialog
        self.board = dialog.board
        self._cancel_requested = False

        # --- Riga superiore: filtro net di riferimento + bottoni ---
        top_sizer = wx.BoxSizer(wx.HORIZONTAL)
        top_sizer.Add(
            wx.StaticText(self, label=_("Net di riferimento:")),
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.RIGHT,
            5,
        )
        self.net_filter_ctrl = wx.TextCtrl(self, value="GND")
        top_sizer.Add(self.net_filter_ctrl, 0, wx.RIGHT, 10)

        # Soglia: lunghezza minima (mm) di un tratto continuo senza piano
        # sotto la traccia perché venga segnalata. Gap più corti (es. un
        # incrocio con una traccia del lato opposto) vengono ignorati.
        top_sizer.Add(
            wx.StaticText(self, label=_("Gap minimo (mm):")),
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.RIGHT,
            5,
        )
        self.min_gap_ctrl = wx.TextCtrl(self, value="5", size=(50, -1))
        top_sizer.Add(self.min_gap_ctrl, 0, wx.RIGHT, 10)

        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)  # seconda riga: pulsanti
        self.analyze_btn = wx.Button(self, label=_("Analizza"))
        self.analyze_btn.Bind(wx.EVT_BUTTON, self.on_analyze)
        btn_sizer.Add(self.analyze_btn, 0, wx.RIGHT, 5)

        # Bottone per interrompere un'analisi in corso: su board grandi o
        # con piani poco continui il calcolo può richiedere parecchi
        # secondi, e la prima versione non aveva modo di fermarlo (serviva
        # chiudere pcbnew a forza). Resta disabilitato finché non parte
        # un'analisi.
        self.cancel_btn = wx.Button(self, label=_("Interrompi"))
        self.cancel_btn.Bind(wx.EVT_BUTTON, self.on_cancel)
        self.cancel_btn.Disable()
        btn_sizer.Add(self.cancel_btn, 0, wx.RIGHT, 10)

        clear_btn = wx.Button(self, label=_("Pulisci overlay"))
        clear_btn.Bind(wx.EVT_BUTTON, self.on_clear)
        btn_sizer.Add(clear_btn, 0, wx.RIGHT, 10)

        # Seleziona in Pcbnew tutte le tracce della lista in un colpo solo:
        # alternativa affidabile ai marker grafici, che in alcune build
        # non compaiono
        sel_all_btn = wx.Button(self, label=_("Seleziona tutte"))
        sel_all_btn.Bind(wx.EVT_BUTTON, self.on_select_all)
        btn_sizer.Add(sel_all_btn, 0)
        add_help_button(self, btn_sizer, "return_path")


        # --- Lista risultati ---
        self.results_list = wx.ListCtrl(self, style=wx.LC_REPORT)
        # Colonna "Stato" con semaforo: rosso = nessuna via di stitching
        # vicina (grave), giallo = c'e' una via vicina (minore)
        self.results_list.InsertColumn(0, _("Stato"), width=90)
        self.results_list.InsertColumn(1, _("Net"), width=100)
        self.results_list.InsertColumn(2, _("Riferimento"), width=300)
        self.results_list.InsertColumn(3, _("Gap max (mm)"), width=110)
        self.results_list.InsertColumn(4, _("Via stitching vicina"), width=140)
        self.results_list.InsertColumn(5, _("Lunghezza (mm)"), width=110)
        self._light_images = make_light_images()
        self.results_list.SetImageList(self._light_images, wx.IMAGE_LIST_SMALL)

        # Problemi dell'ultima analisi, nello stesso ordine delle righe
        # della lista: serve per risalire alla traccia dalla riga cliccata
        self._issues = []
        self.results_list.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_row_selected)

        self.status_label = wx.StaticText(self, label="")

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(top_sizer, 0, wx.ALL, 10)
        sizer.Add(btn_sizer, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        sizer.Add(self.results_list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        sizer.Add(self.status_label, 0, wx.ALL, 10)
        self.SetSizer(sizer)
        # Ricorda i valori delle caselle fra un'apertura e l'altra
        persist_all(self, "rp")

    def on_analyze(self, event):
        # Rimuove eventuali overlay di un'analisi precedente prima di
        # ripartire, per non accumulare marker vecchi sulla board
        self.on_clear(event)

        net_filter = self.net_filter_ctrl.GetValue().strip() or "GND"

        # Soglia del gap: accetta anche la virgola decimale; se il valore
        # non è un numero valido si torna al default
        try:
            min_gap_mm = float(self.min_gap_ctrl.GetValue().strip().replace(",", "."))
        except ValueError:
            min_gap_mm = return_path.DEFAULT_MIN_GAP_MM

        # Mentre l'analisi gira, disabilita "Analizza" (per non lanciarne
        # due in parallelo) e abilita "Interrompi". self._cancel_requested
        # viene controllato dentro analyze_board dopo ogni traccia.
        self._cancel_requested = False
        self.analyze_btn.Disable()
        self.cancel_btn.Enable()
        self.status_label.SetLabel(_("Analisi in corso... (0%)"))
        wx.Yield()

        def on_progress(i, total):
            # Chiamata dopo ogni traccia da analyze_board: aggiorna la
            # label di stato e soprattutto chiama wx.Yield(), che processa
            # gli eventi in coda (compreso un eventuale click su
            # "Interrompi") così l'interfaccia resta reattiva durante il
            # calcolo invece di congelarsi fino alla fine.
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
            # Net reale del piano e layer su cui e' interrotto
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
        Click su una riga: seleziona la traccia corrispondente in Pcbnew e
        prova a centrarla nella vista, così si vede subito dove si trova.
        """
        idx = event.GetIndex()
        if idx < 0 or idx >= len(self._issues):
            return
        track = self._issues[idx].track
        try:
            # Deseleziona tutto ciò che era selezionato prima
            for item in self.board.GetTracks():
                if item.IsSelected():
                    item.ClearSelected()
            track.SetSelected()
            # FocusOnItem centra e zooma la vista sull'oggetto; non è
            # garantito che esista in ogni build, quindi se manca si
            # ripiega sul semplice refresh (la traccia resta selezionata)
            try:
                pcbnew.FocusOnItem(track)
            except AttributeError:
                pass
            pcbnew.Refresh()
        except Exception as exc:
            # La traccia potrebbe essere stata cancellata dopo l'analisi
            self.status_label.SetLabel(_("Impossibile selezionare la traccia: {0}").format(exc))

    def on_select_all(self, event):
        """Seleziona in Pcbnew tutte le tracce con problemi della lista."""
        try:
            # Prima deseleziona tutto, poi seleziona le tracce segnalate
            for item in self.board.GetTracks():
                if item.IsSelected():
                    item.ClearSelected()
            for issue in self._issues:
                issue.track.SetSelected()
            pcbnew.Refresh()
            self.status_label.SetLabel(_("Selezionate {0} tracce.").format(len(self._issues)))
        except Exception as exc:
            self.status_label.SetLabel(_("Impossibile selezionare: {0}").format(exc))

    def on_cancel(self, event):
        self._cancel_requested = True
        self.status_label.SetLabel(_("Interruzione in corso..."))

    def on_clear(self, event):
        if self.dialog.markers:
            return_path.clear_highlight(self.board, self.dialog.markers)
            self.dialog.markers = []
        self.status_label.SetLabel("")
