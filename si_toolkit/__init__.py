"""
Entry point of the "PCB Signal Integrity Toolkit" plugin for KiCad.

KiCad loads this file when it scans the scripting/plugins folder
(or 3rdparty/plugins) at startup. Here the plugin action is registered with
pcbnew.ActionPlugin: the standard way to add an entry to Pcbnew's
"Tools > External Plugins" menu.
"""
from .action import SIToolkitPlugin

# pcbnew wants an INSTANCE (not the class) with register() called on it.
SIToolkitPlugin().register()
