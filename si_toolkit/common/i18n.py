"""
Translation of the plugin interface (Italian / English).

The texts in the code are in Italian and go through the _() function: if
the chosen language is English the text is looked up in the EN dictionary
(file i18n_en.py), otherwise the Italian stays. A text missing from the
dictionary stays in Italian: no error.

Texts with variable values are written as templates with placeholders,
e.g. _("Net {0} evidenziata ({1} pad).").format(net, n): the template is
translated and then the values are inserted.
"""
from .i18n_en import EN

LANG = "en"  # "en" (default) or "it"; set when the dialog opens


def set_language(code):
    """Sets the interface language ("it" or "en")."""
    global LANG
    LANG = "it" if str(code).lower().startswith("it") else "en"


def _(text):
    """Text in the chosen language (Italian is the original)."""
    if LANG == "en" and isinstance(text, str):
        return EN.get(text, text)
    return text
