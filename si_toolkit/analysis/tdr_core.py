"""
TDR / TDT simulati a partire dai parametri S (S11, S21) di una linea.

Il file NON dipende da KiCad ne' da openEMS: usa solo numpy. Viene copiato
accanto allo script di simulazione (simulate.py) e importato da li', cosi'
lo stesso codice si puo' provare anche fuori da KiCad.

Idea: la linea e' un sistema lineare. Se conosco la sua risposta in
frequenza (parametri S) posso calcolare cosa succede quando in ingresso
arriva un gradino con un certo tempo di salita:
- TDR (riflettometria): la parte del gradino che torna indietro, rho(t).
  Da rho si ricava l'impedenza "vista" nel tempo: Z = 50 (1+rho)/(1-rho).
  Ogni tratto della linea compare a un tempo pari al doppio del suo
  ritardo (andata e ritorno).
- TDT (trasmissione): il gradino che arriva in fondo, con ritardo,
  tempo di salita peggiorato ed eventuale sovraelongazione (overshoot).

Il fronte e' una funzione erf (integrale di una gaussiana): ha uno spettro
che cade molto in fretta, cosi' le frequenze sopra f_max (dove la
simulazione non ha dati) sono trascurabili.
"""
import math

import numpy as np

# Per una gaussiana: tempo di salita 10-90% = 2.563 * sigma
_TR_PER_SIGMA = 2.563


def min_rise_time(f_max):
    """
    Tempo di salita (10-90%) piu' corto che si puo' rappresentare con dati
    fino a f_max: lo spettro del fronte a f_max deve essere sceso sotto
    circa l'1% (esponente 4.5 -> e^-4.5 = 1.1%). Regola pratica: tr >= 1.2/f_max.
    """
    sigma = 3.0 / (2 * math.pi * f_max)
    return _TR_PER_SIGMA * sigma


def step_responses(s_of_f, f_max, t_rise, t_window=None, f_low=None):
    """
    Calcola TDR e TDT per un gradino con tempo di salita t_rise (s).

    s_of_f(f): funzione che, dato un vettore di frequenze (Hz, tutte > 0),
               ritorna (s11, s21) complessi sulle stesse frequenze.
    f_max:     frequenza massima per cui i dati sono validi (Hz).
    t_window:  durata della finestra temporale (s). Default: abbastanza
               lunga da contenere linea e riflessioni (>= 50 ns).
    f_low:     sotto questa frequenza i dati della simulazione sono poco
               affidabili e si raccordano al valore in continua
               (S11 -> 0, S21 -> 1: linea senza perdite in DC). Default f_max/100.

    Ritorna un dizionario con: t (s), v_in (gradino in ingresso, 0..1),
    rho (TDR), z (ohm), v_out (TDT, 0..1), t_rise_used, clamped (True se
    il tempo di salita e' stato allungato perche' f_max non bastava).
    """
    clamped = False
    tr_min = min_rise_time(f_max)
    if t_rise < tr_min:
        t_rise, clamped = tr_min, True
    sigma = t_rise / _TR_PER_SIGMA
    if f_low is None:
        f_low = f_max / 100
    if t_window is None:
        t_window = max(50e-9, 60 * t_rise)

    # Griglia: passo in frequenza df = 1/T (T = finestra), frequenze da 0
    # a f_max. Con la FFT reale (rfft) N campioni nel tempo corrispondono a
    # N/2+1 frequenze: dt = 1 / (N * df).
    df = 1.0 / t_window
    n_f = int(math.ceil(f_max / df)) + 1
    n_t = 2 * (n_f - 1)
    dt = 1.0 / (n_t * df)
    f = np.arange(n_f) * df

    # Parametri S sulla griglia: dalla simulazione sopra f_low, raccordo
    # lineare verso il valore in continua sotto f_low
    s11 = np.zeros(n_f, dtype=complex)
    s21 = np.ones(n_f, dtype=complex)
    hi = f >= f_low
    s11_hi, s21_hi = s_of_f(f[hi])
    s11[hi], s21[hi] = s11_hi, s21_hi
    lo = ~hi
    if lo.any() and hi.any():
        k = f[lo] / f[hi][0]  # 0 in continua, 1 al primo punto valido
        s11[lo] = s11_hi[0] * k
        s21[lo] = 1 + (s21_hi[0] - 1) * k

    # Derivata del gradino = gaussiana centrata a t0 (area 1). Il suo
    # spettro e' noto in forma chiusa: niente FFT dell'ingresso.
    t0 = 4 * sigma + 0.5e-9  # un po' di "prima" del fronte, per vedere la base
    H = np.exp(-0.5 * (2 * np.pi * f * sigma) ** 2) * np.exp(-2j * np.pi * f * t0)

    # Risposta all'impulso-gaussiano nel tempo, poi integrale -> gradino
    def to_step(spectrum):
        imp = np.fft.irfft(spectrum, n=n_t) / dt  # densita' nel tempo
        return np.cumsum(imp) * dt

    t = np.arange(n_t) * dt
    v_in = to_step(H)
    rho = to_step(s11 * H)
    v_out = to_step(s21 * H)
    # Impedenza vista dal TDR (rho limitato per non dividere per zero)
    rho_c = np.clip(rho, -0.99, 0.99)
    z = 50.0 * (1 + rho_c) / (1 - rho_c)
    return {
        "t": t, "v_in": v_in, "rho": rho, "z": z, "v_out": v_out,
        "t_rise_used": t_rise, "clamped": clamped, "t0": t0,
    }


def edge_metrics(t, v):
    """
    Misure su un fronte di salita normalizzato: istante al 50%, tempo di
    salita 10-90% e sovraelongazione (overshoot) in % rispetto al valore
    finale. Ritorna (t50, t10_90, overshoot_pct) o None se il fronte manca.
    """
    final = float(np.median(v[int(len(v) * 0.8):]))  # valore a regime
    if final <= 0.05:
        return None

    def cross(level):
        idx = np.nonzero(v >= level * final)[0]
        if not len(idx) or idx[0] == 0:
            return None
        i = idx[0]
        # interpolazione lineare fra i due campioni a cavallo della soglia
        return t[i - 1] + (level * final - v[i - 1]) * (t[i] - t[i - 1]) / (v[i] - v[i - 1])

    t10, t50, t90 = cross(0.1), cross(0.5), cross(0.9)
    if None in (t10, t50, t90):
        return None
    overshoot = max(0.0, (float(v.max()) - final) / final * 100)
    return t50, t90 - t10, overshoot
