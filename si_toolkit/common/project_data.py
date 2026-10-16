"""
Data of the plugin that belong to ONE board, saved in a small file next to
it: "<board name>.si_toolkit.json" in the project folder.

Only what depends on the board goes there:
- the rows of the Layout checks that the user has excluded (accepted);
- the net data of the Layout checks: currents, voltages, length groups.
The thresholds and the other settings stay in the general settings file
(see gui/dialog.py), the same for every board.

If the board has never been saved (no file name), nothing can be stored
next to it: load() returns an empty dictionary and save() does nothing.
"""
import json
import os

SUFFIX = ".si_toolkit.json"


def path_for(board):
    """Path of the project file of the board, or None if the board has no file yet."""
    try:
        name = board.GetFileName()
    except Exception:
        return None
    if not name:
        return None
    base, _ext = os.path.splitext(name)
    return base + SUFFIX


def load(board):
    """Contents of the project file (empty dictionary if missing or unreadable)."""
    path = path_for(board)
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save(board, key, value):
    """
    Updates one key of the project file and rewrites it. Returns True if it
    was saved (False if the board has no file name or the folder is not
    writable: not a blocking error).
    """
    path = path_for(board)
    if not path:
        return False
    data = load(board)
    data[key] = value
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except Exception:
        return False
