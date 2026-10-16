# -*- coding: utf-8 -*-
"""
Builds the package for KiCad's "Plugin and Content Manager" (PCM).

Structure required by the PCM:
    metadata.json          package description (name, version, ...)
    plugins/               the plugin files, directly here (with __init__.py)
    resources/icon.png     64x64 icon shown in the PCM list

Usage:  python build_pcm.py [output_folder]
The resulting file is installed from KiCad: Plugin and Content Manager ->
"Install from File...".
"""
import json
import os
import sys
import zipfile

PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# The version is written in one place only: common/version.py (read as text,
# so this script runs with any Python, without importing the plugin)
with open(os.path.join(PLUGIN_DIR, "common", "version.py"), encoding="utf-8") as _f:
    VERSION = next(line.split("=", 1)[1].strip().strip('"') for line in _f if line.startswith("VERSION"))

METADATA = {
    "$schema": "https://go.kicad.org/pcm/schemas/v2",
    "name": "PCB Signal Integrity Toolkit",
    "description": "Layout checks, return path, DC current/IR drop, impedance, diff pairs, crosstalk, openEMS EM simulation.",
    "description_full": (
        "Signal and power integrity checks on the open board:\n"
        "- Layout checks: a smart DRC on the whole board (decoupling capacitor distance and"
        " ground vias, layer changes without a return via, stitching via spacing, tracks over"
        " plane gaps, plane edge, track width vs current, isolation, pair skew and length groups,"
        " dead branches, acute angles, width steps, vias in pads, tombstoning, via current, crystal,"
        " overlapping tracks)\n"
        "- Return Path: tracks crossing gaps in the reference plane; return current map"
        " (HF and DC) from an input pad to a ground exit, with loads found automatically"
        " and their currents estimated from type and value\n"
        "- DC Current: current, IR drop and IPC-2221 limit on tracks and vias, multiple loads, color map\n"
        "- Impedance: Z0 with a 2D field solver from the board stackup (coplanar, solder mask)\n"
        "- Diff. pairs: Zdiff and common-mode Z with the field solver\n"
        "- Crosstalk: parallel runs and estimated NEXT\n"
        "- openEMS: 3D FDTD simulation of a line (S-parameters, impedance, TDR/TDT, field GIFs);"
        " requires openEMS and a Python with numpy/h5py/matplotlib\n"
        "Interface in English and Italian."
    ),
    "identifier": "com.github.ugo-silato.sitoolkit",
    "type": "plugin",
    "author": {"name": "Ugo Silato"},
    "license": "MIT",
    "resources": {"homepage": "https://github.com/ugo-silato/PCB_SI_Toolkit"},
    "versions": [
        {
            "version": VERSION,
            "status": "stable",
            "kicad_version": "10.0",
        }
    ],
}

# What does NOT go into the package: Python caches, personal settings,
# development tools (this folder), test and diagnostic files
EXCLUDE_DIRS = {"__pycache__", "tools"}
EXCLUDE_FILES = {"settings.json", "dc_diagnostics.txt", "icon_64.png"}


def build(out_dir):
    out = os.path.join(out_dir, f"si_toolkit_pcm_{VERSION}.zip")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("metadata.json", json.dumps(METADATA, indent=4))
        # 64x64 icon for the PCM list
        z.write(os.path.join(PLUGIN_DIR, "icon_64.png"), "resources/icon.png")
        # Plugin files directly under plugins/
        for root, dirs, files in os.walk(PLUGIN_DIR):
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
            for name in files:
                if name in EXCLUDE_FILES or name.endswith((".pyc", ".txt", ".log")):
                    continue
                full = os.path.join(root, name)
                rel = os.path.relpath(full, PLUGIN_DIR).replace(os.sep, "/")
                z.write(full, "plugins/" + rel)
    return out


if __name__ == "__main__":
    print("Creato", build(sys.argv[1] if len(sys.argv) > 1 else os.getcwd()))
