"""
TDR / TDT simulated from the S-parameters (S11, S21) of a line.

This file does NOT depend on KiCad nor on openEMS: it only uses numpy. It
is copied next to the simulation script (simulate.py) and imported from
there, so the same code can also be tested outside KiCad.

Idea: the line is a linear system. Knowing its frequency response
(S-parameters), we can compute what happens when a step with a given rise
time arrives at the input:
- TDR (reflectometry): the part of the step coming back, rho(t).
  From rho the impedance "seen" over time is obtained:
  Z = 50 (1+rho)/(1-rho). Each part of the line shows up at a time equal to
  twice its delay (round trip).
- TDT (transmission): the step reaching the far end, with delay, degraded
  rise time and possible overshoot.

The edge is an erf function (integral of a Gaussian): its spectrum falls
off very quickly, so the frequencies above f_max (where the simulation has
no data) are negligible.
"""
import math

import numpy as np

# For a Gaussian: 10-90% rise time = 2.563 * sigma
_TR_PER_SIGMA = 2.563


def min_rise_time(f_max):
    """
    Shortest rise time (10-90%) that can be represented with data up to f_max:
    the edge spectrum at f_max must have fallen below about 1% (exponent 4.5 ->
    e^-4.5 = 1.1%). Rule of thumb: tr >= 1.2/f_max.
    """
    sigma = 3.0 / (2 * math.pi * f_max)
    return _TR_PER_SIGMA * sigma


def step_responses(s_of_f, f_max, t_rise, t_window=None, f_low=None):
    """
    Computes TDR and TDT for a step with rise time t_rise (s).

    s_of_f(f): function that, given a vector of frequencies (Hz, all > 0),
               returns the complex (s11, s21) at the same frequencies.
    f_max:     maximum frequency for which the data are valid (Hz).
    t_window:  length of the time window (s). Default: long enough to
               contain the line and the reflections (>= 50 ns).
    f_low:     below this frequency the simulation data are not very
               reliable and are blended into the DC value
               (S11 -> 0, S21 -> 1: lossless line at DC). Default f_max/100.

    Returns a dictionary with: t (s), v_in (input step, 0..1), rho (TDR),
    z (ohm), v_out (TDT, 0..1), t_rise_used, clamped (True if the rise time
    was lengthened because f_max was not enough).
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

    # Grid: frequency step df = 1/T (T = window), frequencies from 0 to f_max.
    # With the real FFT (rfft) N time samples correspond to N/2+1 frequencies:
    # dt = 1 / (N * df).
    df = 1.0 / t_window
    n_f = int(math.ceil(f_max / df)) + 1
    n_t = 2 * (n_f - 1)
    dt = 1.0 / (n_t * df)
    f = np.arange(n_f) * df

    # S-parameters on the grid: from the simulation above f_low, linear blend
    # towards the DC value below f_low
    s11 = np.zeros(n_f, dtype=complex)
    s21 = np.ones(n_f, dtype=complex)
    hi = f >= f_low
    s11_hi, s21_hi = s_of_f(f[hi])
    s11[hi], s21[hi] = s11_hi, s21_hi
    lo = ~hi
    if lo.any() and hi.any():
        k = f[lo] / f[hi][0]  # 0 at DC, 1 at the first valid point
        s11[lo] = s11_hi[0] * k
        s21[lo] = 1 + (s21_hi[0] - 1) * k

    # Derivative of the step = Gaussian centred at t0 (area 1). Its spectrum is
    # known in closed form: no FFT of the input needed.
    t0 = 4 * sigma + 0.5e-9  # a bit of time "before" the edge, to see the baseline
    H = np.exp(-0.5 * (2 * np.pi * f * sigma) ** 2) * np.exp(-2j * np.pi * f * t0)

    # Response to the Gaussian impulse over time, then integral -> step
    def to_step(spectrum):
        imp = np.fft.irfft(spectrum, n=n_t) / dt  # density over time
        return np.cumsum(imp) * dt

    t = np.arange(n_t) * dt
    v_in = to_step(H)
    rho = to_step(s11 * H)
    v_out = to_step(s21 * H)
    # Impedance seen by the TDR (rho clamped to avoid dividing by zero)
    rho_c = np.clip(rho, -0.99, 0.99)
    z = 50.0 * (1 + rho_c) / (1 - rho_c)
    return {
        "t": t, "v_in": v_in, "rho": rho, "z": z, "v_out": v_out,
        "t_rise_used": t_rise, "clamped": clamped, "t0": t0,
    }


def edge_metrics(t, v):
    """
    Measurements on a normalized rising edge: 50% crossing time, 10-90% rise
    time and overshoot in % of the final value.
    Returns (t50, t10_90, overshoot_pct) or None if there is no edge.
    """
    final = float(np.median(v[int(len(v) * 0.8):]))  # steady-state value
    if final <= 0.05:
        return None

    def cross(level):
        idx = np.nonzero(v >= level * final)[0]
        if not len(idx) or idx[0] == 0:
            return None
        i = idx[0]
        # linear interpolation between the two samples straddling the threshold
        return t[i - 1] + (level * final - v[i - 1]) * (t[i] - t[i - 1]) / (v[i] - v[i - 1])

    t10, t50, t90 = cross(0.1), cross(0.5), cross(0.9)
    if None in (t10, t50, t90):
        return None
    overshoot = max(0.0, (float(v.max()) - final) / final * 100)
    return t50, t90 - t10, overshoot
