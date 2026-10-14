"""
Where the settings file is saved (settings.json).

Not in the plugin folder: when installed with KiCad's Plugin Manager, that
folder is replaced at every update and the settings would be lost. KiCad's
user settings folder is used instead (e.g. %APPDATA%\\kicad\\10.0 on
Windows), in a dedicated file.
The first time, if a settings.json exists in the plugin folder (previous
versions), it is copied there.
"""
import os
import shutil

_PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_OLD_PATH = os.path.join(_PLUGIN_DIR, "settings.json")


def _user_config_dir():
    """KiCad user settings folder, or None if it cannot be determined."""
    try:
        import pcbnew

        path = pcbnew.SETTINGS_MANAGER.GetUserSettingsPath()
        if path and os.path.isdir(path):
            return path
    except Exception:
        pass
    return None


def settings_path():
    """Path of the settings file (creates it where needed, migrating the old one)."""
    base = _user_config_dir()
    if base is None:
        return _OLD_PATH  # fallback: plugin folder, as before
    path = os.path.join(base, "si_toolkit_settings.json")
    if not os.path.exists(path) and os.path.exists(_OLD_PATH):
        try:
            shutil.copy(_OLD_PATH, path)  # one-time migration
        except Exception:
            return _OLD_PATH
    return path
