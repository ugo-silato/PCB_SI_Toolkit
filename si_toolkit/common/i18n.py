"""
Traduzione dell'interfaccia del plugin (italiano / inglese).

I testi nel codice sono in italiano e passano dalla funzione _(): se la
lingua scelta e' l'inglese si cerca il testo nel dizionario EN (file
i18n_en.py), altrimenti resta l'italiano. Un testo che manca nel
dizionario resta in italiano: nessun errore.

I testi con valori variabili sono scritti come modello con segnaposto,
es. _("Net {0} evidenziata ({1} pad).").format(net, n): si traduce il
modello e poi si inseriscono i valori.
"""
from .i18n_en import EN

LANG = "en"  # "en" (default) oppure "it"; impostata all'apertura del dialog


def set_language(code):
    """Imposta la lingua dell'interfaccia ("it" o "en")."""
    global LANG
    LANG = "it" if str(code).lower().startswith("it") else "en"


def _(text):
    """Testo nella lingua scelta (l'italiano e' l'originale)."""
    if LANG == "en" and isinstance(text, str):
        return EN.get(text, text)
    return text
