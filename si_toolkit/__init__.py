"""
Punto di ingresso del plugin "PCB Signal Integrity Toolkit" per KiCad.

KiCad carica questo file quando scansiona la cartella scripting/plugins
(o 3rdparty/plugins) all'avvio. Qui registriamo l'azione del plugin con
pcbnew.ActionPlugin: è il meccanismo standard per aggiungere una voce al
menu "Strumenti > Plugin Esterni" di Pcbnew.
"""
from .action import SIToolkitPlugin

# pcbnew vuole un'ISTANZA (non la classe) con register() chiamato su di essa.
SIToolkitPlugin().register()
