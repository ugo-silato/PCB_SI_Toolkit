# -*- coding: utf-8 -*-
"""
Verifica dell'installazione di openEMS usata dalla scheda openEMS.

Controlla, senza simulare nulla:
- che il Python indicato esista e sia a 64 bit;
- che quel Python importi i moduli necessari (CSXCAD, openEMS, numpy,
  h5py, matplotlib), con la cartella di openEMS fra quelle delle DLL;
- che la cartella di openEMS esista e contenga le DLL e l'eseguibile.

Dice cosa manca e prepara i comandi per installarlo: i pacchetti normali
(numpy, h5py, matplotlib) con pip da Internet, i moduli di openEMS dai file
.whl che si trovano nella cartella di openEMS (se ci sono).
"""
import glob
import json
import os
import subprocess
import sys

from ..common.i18n import _

# Moduli da controllare: (nome per import, nome per pip o None se viene
# dalla distribuzione di openEMS)
MODULES = [
    ("CSXCAD", None),
    ("openEMS", None),
    ("numpy", "numpy"),
    ("h5py", "h5py"),
    ("matplotlib", "matplotlib"),
]

# Script eseguito DAL Python esterno: imposta la cartella delle DLL come fa
# lo script di simulazione, prova gli import e stampa il risultato in JSON
_PROBE = r'''
import json, os, struct, sys
oe = sys.argv[1]
os.environ["OPENEMS_INSTALL_PATH"] = oe
os.environ["PATH"] = oe + os.pathsep + os.environ.get("PATH", "")
if hasattr(os, "add_dll_directory") and os.path.isdir(oe):
    os.add_dll_directory(oe)
out = {"version": sys.version.split()[0], "bits": struct.calcsize("P") * 8, "mods": {}}
for name in sys.argv[2:]:
    try:
        m = __import__(name)
        out["mods"][name] = ["ok", str(getattr(m, "__version__", ""))]
    except Exception as exc:
        out["mods"][name] = ["err", "%s: %s" % (type(exc).__name__, exc)]
print(json.dumps(out))
'''


def _no_window():
    """Flag per non aprire finestre nere durante il controllo (Windows)."""
    return subprocess.CREATE_NO_WINDOW if sys.platform.startswith("win") else 0


def check(python_exe, oe_dir):
    """
    Esegue tutti i controlli. Ritorna un dizionario:
      lines:    righe del rapporto, ciascuna (stato, testo) con stato
                "ok" / "warn" / "err";
      pip:      pacchetti mancanti installabili con pip;
      wheels:   file .whl di CSXCAD/openEMS trovati nella cartella openEMS,
                da installare se quei moduli mancano;
      ok:       True se tutto e' a posto.
    """
    lines, pip_missing, wheels = [], [], []

    # --- Cartella openEMS ---
    if not os.path.isdir(oe_dir):
        lines.append(("err", _("Cartella openEMS non trovata: {0}").format(oe_dir)))
    else:
        dlls = glob.glob(os.path.join(oe_dir, "*.dll"))
        exe = os.path.exists(os.path.join(oe_dir, "openEMS.exe"))
        if dlls and exe:
            lines.append(("ok", _("Cartella openEMS: {0} ({1} DLL, openEMS.exe presente)").format(oe_dir, len(dlls))))
        else:
            lines.append(("err", _("La cartella {0} non sembra un'installazione di openEMS "
                                   "(mancano openEMS.exe o le DLL).").format(oe_dir)))
        # File .whl dei moduli Python di openEMS (nelle distribuzioni Windows
        # stanno di solito in una sottocartella "python")
        for pattern in ("**/CSXCAD*.whl", "**/openEMS*.whl"):
            wheels += glob.glob(os.path.join(oe_dir, pattern), recursive=True)

    # --- Python esterno ---
    if not os.path.exists(python_exe):
        lines.append(("err", _("Python non trovato: {0}").format(python_exe)))
        return {"lines": lines, "pip": [], "wheels": wheels, "ok": False}
    try:
        res = subprocess.run(
            [python_exe, "-c", _PROBE, oe_dir] + [m for m, _p in MODULES],
            capture_output=True, text=True, timeout=120, creationflags=_no_window(),
        )
        info = json.loads(res.stdout.strip().splitlines()[-1])
    except Exception as exc:
        lines.append(("err", _("Impossibile eseguire il Python indicato: {0}").format(exc)))
        return {"lines": lines, "pip": [], "wheels": wheels, "ok": False}

    if info["bits"] != 64:
        lines.append(("err", _("Python {0} a {1} bit: openEMS richiede Python a 64 bit.").format(
            info["version"], info["bits"])))
    else:
        lines.append(("ok", _("Python {0} a 64 bit: {1}").format(info["version"], python_exe)))

    oe_missing = False
    for mod, pip_name in MODULES:
        state, detail = info["mods"].get(mod, ["err", "?"])
        if state == "ok":
            lines.append(("ok", _("Modulo {0} presente {1}").format(mod, detail).rstrip()))
        else:
            lines.append(("err", _("Modulo {0} mancante o non funzionante ({1})").format(mod, detail)))
            if pip_name:
                pip_missing.append(pip_name)
            else:
                oe_missing = True

    if oe_missing and not wheels:
        lines.append(("warn", _("I moduli CSXCAD/openEMS non si installano da Internet: usa i file .whl "
                                "della distribuzione di openEMS (cartella 'python') con "
                                "python -m pip install &lt;file.whl&gt;, oppure segui le istruzioni di openEMS.")))
    ok = all(state == "ok" for state, _t in lines)
    return {"lines": lines, "pip": pip_missing, "wheels": wheels if oe_missing else [], "ok": ok}


def install_command(python_exe, pip_pkgs, wheels):
    """
    Comando (lista) che installa i pacchetti mancanti: pip da Internet per
    numpy/h5py/matplotlib, i file .whl per CSXCAD/openEMS. Va eseguito in una
    finestra visibile, cosi' si vede l'avanzamento.
    """
    return [python_exe, "-m", "pip", "install"] + list(wheels) + list(pip_pkgs)
