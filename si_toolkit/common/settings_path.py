"""
Dove si salva il file delle impostazioni (settings.json).

Non nella cartella del plugin: installando con il Plugin Manager di KiCad,
a ogni aggiornamento quella cartella viene sostituita e le impostazioni
andrebbero perse. Si usa la cartella delle impostazioni utente di KiCad
(es. %APPDATA%\\kicad\\10.0 su Windows), in un file dedicato.
La prima volta, se esiste un settings.json nella cartella del plugin
(versioni precedenti), viene copiato li'.
"""
import os
import shutil

_PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_OLD_PATH = os.path.join(_PLUGIN_DIR, "settings.json")


def _user_config_dir():
    """Cartella delle impostazioni utente di KiCad, o None se non ricavabile."""
    try:
        import pcbnew

        path = pcbnew.SETTINGS_MANAGER.GetUserSettingsPath()
        if path and os.path.isdir(path):
            return path
    except Exception:
        pass
    return None


def settings_path():
    """Percorso del file impostazioni (lo crea dove serve, migrando il vecchio)."""
    base = _user_config_dir()
    if base is None:
        return _OLD_PATH  # ripiego: cartella del plugin, come prima
    path = os.path.join(base, "si_toolkit_settings.json")
    if not os.path.exists(path) and os.path.exists(_OLD_PATH):
        try:
            shutil.copy(_OLD_PATH, path)  # migrazione una tantum
        except Exception:
            return _OLD_PATH
    return path
