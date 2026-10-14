"""
Azione principale del plugin: definisce voce di menu, icona e cosa
succede quando l'utente clicca sulla voce dal menu "Plugin Esterni" di
Pcbnew (o sul bottone nella toolbar, se abilitato).
"""
import os

import pcbnew
import wx

from .gui.dialog import SIToolkitDialog


class SIToolkitPlugin(pcbnew.ActionPlugin):
    """
    Sottoclasse di ActionPlugin: è l'interfaccia che Pcbnew usa per
    sapere come mostrare il plugin nel menu e cosa eseguire al click.
    """

    def defaults(self):
        # Testo e descrizione mostrati nel menu "Strumenti > Plugin Esterni"
        self.name = "PCB Signal Integrity Toolkit"
        self.category = "Signal/Power Integrity"
        # Descrizione nella lingua scelta nella scheda Opzioni (file impostazioni)
        lang = "en"  # default: inglese
        try:
            import json

            from .common.settings_path import settings_path

            with open(settings_path(), encoding="utf-8") as f:
                lang = json.load(f).get("lang", "en")
        except Exception:
            pass
        if lang == "en":
            self.description = ("Return path, DC current, impedance, differential pairs, "
                                "crosstalk and openEMS simulation on the current board")
        else:
            self.description = ("Ritorno di corrente, corrente DC, impedenza, coppie "
                                "differenziali, crosstalk e simulazione openEMS sulla board")
        self.show_toolbar_button = True

        # Se esiste un'icona nella stessa cartella la usiamo, altrimenti
        # Pcbnew mostra un'icona generica: nessun problema, non è bloccante.
        icon_path = os.path.join(os.path.dirname(__file__), "icon.png")
        if os.path.exists(icon_path):
            self.icon_file_name = icon_path
        # Variante per il tema scuro di KiCad (se presente)
        dark_path = os.path.join(os.path.dirname(__file__), "icon_dark.png")
        if os.path.exists(dark_path):
            self.dark_icon_file_name = dark_path

    def Run(self):
        """
        Richiamato da Pcbnew al click sulla voce di menu. Prende la board
        aperta e apre il dialog principale del plugin, passandogliela.
        """
        board = pcbnew.GetBoard()
        if board is None:
            wx.MessageBox(
                "Nessuna board aperta in Pcbnew.",
                "SI Toolkit",
                wx.OK | wx.ICON_WARNING,
            )
            return

        global _open_dialog

        # Se il dialog è già aperto lo riportiamo in primo piano invece di
        # crearne un secondo. Se l'oggetto C++ è stato distrutto, wx
        # solleva RuntimeError e si ricade nella creazione di uno nuovo.
        if _open_dialog is not None:
            try:
                _open_dialog.Raise()
                return
            except RuntimeError:
                _open_dialog = None

        # Il dialog è NON modale: così si può continuare a usare Pcbnew
        # (zoom, selezione, guardare i marker) mentre è aperto. Come
        # parent usiamo la finestra di Pcbnew, in modo che il dialog
        # resti sempre sopra di essa. Va tenuto un riferimento globale,
        # altrimenti Python lo distrugge appena Run() ritorna.
        parent = wx.FindWindowByName("PcbFrame")
        _open_dialog = SIToolkitDialog(parent, board)
        _open_dialog.Show()


# Riferimento al dialog aperto (vedi Run)
_open_dialog = None
