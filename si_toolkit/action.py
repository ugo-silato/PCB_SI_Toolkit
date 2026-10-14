"""
Main plugin action: defines the menu entry, the icon and what happens when
the user clicks the entry in Pcbnew's "External Plugins" menu (or the
toolbar button, if enabled).
"""
import os

import pcbnew
import wx

from .gui.dialog import SIToolkitDialog


class SIToolkitPlugin(pcbnew.ActionPlugin):
    """
    ActionPlugin subclass: the interface Pcbnew uses to know how to show the
    plugin in the menu and what to run on click.
    """

    def defaults(self):
        # Text and description shown in the "Tools > External Plugins" menu
        self.name = "PCB Signal Integrity Toolkit"
        self.category = "Signal/Power Integrity"
        # Description in the language chosen in the Options tab (settings file)
        lang = "en"  # default: English
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

        # If an icon exists in the same folder we use it, otherwise Pcbnew
        # shows a generic icon: no problem, it is not blocking.
        icon_path = os.path.join(os.path.dirname(__file__), "icon.png")
        if os.path.exists(icon_path):
            self.icon_file_name = icon_path
        # Variant for KiCad's dark theme (if present)
        dark_path = os.path.join(os.path.dirname(__file__), "icon_dark.png")
        if os.path.exists(dark_path):
            self.dark_icon_file_name = dark_path

    def Run(self):
        """
        Called by Pcbnew when the menu entry is clicked. Takes the open board and
        opens the main plugin dialog, passing the board to it.
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

        # If the dialog is already open we bring it to the front instead of
        # creating a second one. If the C++ object has been destroyed, wx
        # raises RuntimeError and we fall back to creating a new one.
        if _open_dialog is not None:
            try:
                _open_dialog.Raise()
                return
            except RuntimeError:
                _open_dialog = None

        # The dialog is NON-modal: Pcbnew can still be used (zoom, selection,
        # looking at the markers) while it is open. Pcbnew's window is used as
        # parent, so the dialog always stays above it. A global reference must
        # be kept, otherwise Python destroys it as soon as Run() returns.
        parent = wx.FindWindowByName("PcbFrame")
        _open_dialog = SIToolkitDialog(parent, board)
        _open_dialog.Show()


# Reference to the open dialog (see Run)
_open_dialog = None
