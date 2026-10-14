"""
2D field solver (quasi-TEM) for the impedance of PCB lines.

It draws the line CROSS-SECTION (track, side ground, plane below/above,
dielectric, air) on a non-uniform rectangular grid, finer near the
conductor edges, and solves Laplace's equation
    div( eps * grad V ) = 0
with the track at 1 V and the grounds at 0 V (conjugate gradient).

From the solution the capacitance per unit length is obtained as field
energy: C = sum over the grid edges of a * (dV)^2. It is solved twice, with
the dielectric (C) and all in air (C0), and:
    Z0   = eta0 / sqrt(C * C0)        (eta0 = 376.73 ohm, C in eps0 units)
    eeff = C / C0

It is the same principle as the "field solver" calculators (e.g. those of
PCB manufacturers): unlike closed-form formulas it holds for any geometry
(narrow gaps, thick dielectrics, thick copper).

Uses numpy if available (fast), otherwise pure Python (slower).
Units: meters.
"""
import math

ETA0 = 376.730313668

try:
    import numpy as _np
except ImportError:  # KiCad Python without numpy: the pure version is used
    _np = None

_cache = {}


def _graded_lines(keys, lo, hi, fine, coarse, ratio=1.3):
    """
    Grid lines between lo and hi: they pass through all the 'keys' points and
    have a 'fine' step near those points, growing by 'ratio' up to 'coarse'.
    """
    keys = sorted(set([lo, hi] + [k for k in keys if lo <= k <= hi]))
    lines = [keys[0]]
    for a, b in zip(keys, keys[1:]):
        length = b - a
        if length <= 0:
            continue
        # Sizes growing from both ends towards the middle of the interval
        steps_left, steps_right = [], []
        s = fine
        total = 0.0
        while total + 2 * s < length and s < coarse:
            steps_left.append(s)
            steps_right.append(s)
            total += 2 * s
            s *= ratio
        middle = length - total
        n_mid = max(1, int(math.ceil(middle / min(s, coarse))))
        mid_steps = [middle / n_mid] * n_mid
        x = a
        for st in steps_left + mid_steps + steps_right[::-1]:
            x += st
            lines.append(x)
        lines[-1] = b
    return lines


def _solve(xs, ys, eps_cell, fixed):
    """
    Solves Laplace on the grid (xs, ys). eps_cell[i][j]: permittivity of the
    cell between xs[i]..xs[i+1] and ys[j]..ys[j+1]. fixed[i][j]: None (unknown)
    or the imposed potential. Left edge (x = xs[0]) = symmetry axis (Neumann).
    Returns the capacitance (eps0 units) of the half domain.
    """
    nx, ny = len(xs), len(ys)
    dx = [xs[i + 1] - xs[i] for i in range(nx - 1)]
    dy = [ys[j + 1] - ys[j] for j in range(ny - 1)]

    # Edge coefficients: horizontal (i,j)-(i+1,j) and vertical (i,j)-(i,j+1)
    ah = [[0.0] * ny for _ in range(nx - 1)]
    for i in range(nx - 1):
        for j in range(ny):
            w = 0.0
            if j > 0:
                w += eps_cell[i][j - 1] * dy[j - 1] / 2
            if j < ny - 1:
                w += eps_cell[i][j] * dy[j] / 2
            ah[i][j] = w / dx[i]
    av = [[0.0] * (ny - 1) for _ in range(nx)]
    for i in range(nx):
        for j in range(ny - 1):
            w = 0.0
            if i > 0:
                w += eps_cell[i - 1][j] * dx[i - 1] / 2
            if i < nx - 1:
                w += eps_cell[i][j] * dx[i] / 2
            av[i][j] = w / dy[j]

    if _np is not None:
        return _solve_numpy(nx, ny, ah, av, fixed)
    return _solve_python(nx, ny, ah, av, fixed)


def _solve_numpy(nx, ny, ah, av, fixed):
    np = _np
    AH = np.array(ah)  # (nx-1, ny)
    AV = np.array(av)  # (nx, ny-1)
    free = np.array([[fixed[i][j] is None for j in range(ny)] for i in range(nx)])
    V0 = np.array([[0.0 if fixed[i][j] is None else fixed[i][j] for j in range(ny)]
                   for i in range(nx)])

    diag = np.zeros((nx, ny))
    diag[:-1, :] += AH
    diag[1:, :] += AH
    diag[:, :-1] += AV
    diag[:, 1:] += AV

    def apply(V):
        # (A V) = diag*V - weighted sum of the neighbours
        out = diag * V
        out[:-1, :] -= AH * V[1:, :]
        out[1:, :] -= AH * V[:-1, :]
        out[:, :-1] -= AV * V[:, 1:]
        out[:, 1:] -= AV * V[:, :-1]
        return out

    # System on the unknowns only: A_ff x = -A_fc Vc
    b = -apply(V0)
    b[~free] = 0.0
    x = np.zeros((nx, ny))
    r = b.copy()
    dinv = np.where(free, 1.0 / np.where(diag > 0, diag, 1.0), 0.0)
    z = r * dinv
    p = z.copy()
    rz = float((r * z).sum())
    bnorm = math.sqrt(float((b * b).sum())) or 1.0
    for _ in range(20000):
        Ap = apply(p)
        Ap[~free] = 0.0
        alpha = rz / float((p * Ap).sum())
        x += alpha * p
        r -= alpha * Ap
        if math.sqrt(float((r * r).sum())) / bnorm < 1e-9:
            break
        z = r * dinv
        rz_new = float((r * z).sum())
        p = z + (rz_new / rz) * p
        rz = rz_new
    V = np.where(free, x, V0)
    energy = float((AH * (V[1:, :] - V[:-1, :]) ** 2).sum()
                   + (AV * (V[:, 1:] - V[:, :-1]) ** 2).sum())
    return energy


def _solve_python(nx, ny, ah, av, fixed):
    idx = {}
    for i in range(nx):
        for j in range(ny):
            if fixed[i][j] is None:
                idx[(i, j)] = len(idx)
    n = len(idx)
    nb = [[] for _ in range(n)]  # (unknown index or None, coeff, fixed potential)
    diag = [0.0] * n
    b = [0.0] * n
    for (i, j), k in idx.items():
        for (ii, jj, a) in (
            (i + 1, j, ah[i][j] if i < nx - 1 else 0.0),
            (i - 1, j, ah[i - 1][j] if i > 0 else 0.0),
            (i, j + 1, av[i][j] if j < ny - 1 else 0.0),
            (i, j - 1, av[i][j - 1] if j > 0 else 0.0),
        ):
            if a == 0.0:
                continue
            diag[k] += a
            kk = idx.get((ii, jj))
            if kk is None:
                b[k] += a * fixed[ii][jj]
            else:
                nb[k].append((kk, a))

    def matvec(v):
        return [diag[k] * v[k] - sum(a * v[kk] for kk, a in nb[k]) for k in range(n)]

    x = [0.0] * n
    r = b[:]
    z = [r[k] / diag[k] for k in range(n)]
    p = z[:]
    rz = sum(r[k] * z[k] for k in range(n))
    bnorm = math.sqrt(sum(v * v for v in b)) or 1.0
    for _ in range(5000):
        Ap = matvec(p)
        alpha = rz / sum(p[k] * Ap[k] for k in range(n))
        for k in range(n):
            x[k] += alpha * p[k]
            r[k] -= alpha * Ap[k]
        if math.sqrt(sum(v * v for v in r)) / bnorm < 1e-8:
            break
        z = [r[k] / diag[k] for k in range(n)]
        rz_new = sum(r[k] * z[k] for k in range(n))
        beta = rz_new / rz
        rz = rz_new
        p = [z[k] + beta * p[k] for k in range(n)]

    def V(i, j):
        k = idx.get((i, j))
        return x[k] if k is not None else fixed[i][j]

    energy = 0.0
    for i in range(nx - 1):
        for j in range(ny):
            energy += ah[i][j] * (V(i + 1, j) - V(i, j)) ** 2
    for i in range(nx):
        for j in range(ny - 1):
            energy += av[i][j] * (V(i, j + 1) - V(i, j)) ** 2
    return energy


def line_z0(w, h, er, t=0.0, gap=None, h_top=None, fine=None, sm_t=0.0, sm_er=1.0):
    """
    Impedance Z0 (ohm) and effective dielectric constant of a track of width w
    and thickness t:
    - h: dielectric between the track and the plane below;
    - gap: distance from the ground on the same layer (None = no side
      ground);
    - h_top: dielectric between the track and a plane above (stripline);
      None = air above (microstrip).
    - sm_t, sm_er: solder mask (microstrip only), CONFORMAL layer of thickness
      sm_t: it covers the track on top and on the sides, the dielectric in the
      gap and the side ground. sm_t = 0: no solder mask.
    Returns (z0, eeff).
    """
    key = (round(w, 9), round(h, 9), round(er, 4), round(t, 9),
           None if gap is None else round(gap, 9),
           None if h_top is None else round(h_top, 9), fine,
           round(sm_t, 9), round(sm_er, 4))
    if h_top is not None:
        sm_t = 0.0  # stripline: no solder mask
    if key in _cache:
        return _cache[key]

    if fine is None:
        # Grid: fine step about 1/12 of the smallest dimension
        smallest = min(v for v in (w, h, gap or w, h_top or h, max(t, w / 20)) if v > 0)
        fine = smallest / 12.0
    coarse = max(w, h) / 3.0
    x_far = w / 2 + (gap or 0) + max(12 * h, 6 * w)
    y_top = h + t + (h_top if h_top is not None else max(12 * h, 6 * w))

    xk = [0.0, w / 2]
    if gap is not None:
        xk.append(w / 2 + gap)
    yk = [0.0, h, h + t]
    if sm_t > 0:
        # Grid lines on the solder mask edges
        yk += [h + sm_t, h + t + sm_t]
        xk += [w / 2 + sm_t]
        if gap is not None:
            xk.append(max(w / 2 + sm_t, w / 2 + gap - sm_t))
    xs = _graded_lines(xk, 0.0, x_far, fine, coarse)
    ys = _graded_lines(yk, 0.0, y_top, fine, coarse)
    nx, ny = len(xs), len(ys)

    def fixed_grid():
        f = [[None] * ny for _ in range(nx)]
        for i, x in enumerate(xs):
            for j, y in enumerate(ys):
                on_metal_layer = h - 1e-12 <= y <= h + t + 1e-12
                if j == 0 or j == ny - 1 or i == nx - 1:
                    f[i][j] = 0.0  # plane below, far edge / plane above
                elif on_metal_layer and x <= w / 2 + 1e-12:
                    f[i][j] = 1.0  # track
                elif on_metal_layer and gap is not None and x >= w / 2 + gap - 1e-12:
                    f[i][j] = 0.0  # coplanar ground
        return f

    def eps_grid(e, sm_eps):
        cells = [[1.0] * (ny - 1) for _ in range(nx - 1)]
        for i in range(nx - 1):
            for j in range(ny - 1):
                yc = (ys[j] + ys[j + 1]) / 2
                if yc < h or (h_top is not None and yc > h + t):
                    cells[i][j] = e
                elif h_top is not None and h <= yc <= h + t:
                    cells[i][j] = e  # stripline: dielectric also beside the track
                elif sm_t > 0 and yc > h:
                    # Conformal solder mask: on the bare dielectric (gap and
                    # surroundings) for sm_t, and around the track and the side
                    # ground (top and sides) for sm_t
                    xc = (xs[i] + xs[i + 1]) / 2
                    over_trace = xc <= w / 2 + sm_t and yc <= h + t + sm_t
                    over_gnd = (gap is not None and xc >= w / 2 + gap - sm_t
                                and yc <= h + t + sm_t)
                    on_substrate = yc <= h + sm_t
                    if over_trace or over_gnd or on_substrate:
                        cells[i][j] = sm_eps
        return cells

    fixed = fixed_grid()
    c = 2 * _solve(xs, ys, eps_grid(er, sm_er), fixed)    # x2: full domain (symmetry)
    c0 = 2 * _solve(xs, ys, eps_grid(1.0, 1.0), fixed)
    z0 = ETA0 / math.sqrt(c * c0)
    result = (z0, c / c0)
    _cache[key] = result
    return result


def pair_z0(w, s, h, er, t=0.0, gap=None, h_top=None, fine=None, sm_t=0.0, sm_er=1.0):
    """
    Edge-coupled differential pair: two tracks of width w, with edge-to-edge
    spacing s. Same parameters as line_z0; 'gap' is the distance from the side
    ground on the OUTER side of each track.

    Symmetry is exploited: only half of the cross-section (one track) is
    solved, with the axis between the two tracks as left edge:
    - ODD mode (tracks at +1 V and -1 V, differential signal): the axis is at
      0 V (Dirichlet edge) -> Z_odd;
    - EVEN mode (both at +1 V, common mode): the axis is a "free" edge
      (Neumann), as in line_z0 -> Z_even.
    Zdiff = 2 * Z_odd, Zcommon = Z_even / 2.
    Returns (zdiff, zcomm, z_odd, z_even). Units: meters.
    """
    key = ("pair", round(w, 9), round(s, 9), round(h, 9), round(er, 4), round(t, 9),
           None if gap is None else round(gap, 9),
           None if h_top is None else round(h_top, 9), fine, round(sm_t, 9), round(sm_er, 4))
    if h_top is not None:
        sm_t = 0.0  # stripline: no solder mask
    if key in _cache:
        return _cache[key]

    x1 = s / 2          # inner edge of the track (from the pair axis)
    x2 = s / 2 + w      # outer edge
    if fine is None:
        smallest = min(v for v in (w, h, s / 2, gap or w, h_top or h, max(t, w / 20)) if v > 0)
        fine = smallest / 12.0
    coarse = max(w, h) / 3.0
    x_far = x2 + (gap or 0) + max(12 * h, 6 * w)
    y_top = h + t + (h_top if h_top is not None else max(12 * h, 6 * w))

    xk = [0.0, x1, x2]
    if gap is not None:
        xk.append(x2 + gap)
    yk = [0.0, h, h + t]
    if sm_t > 0:
        yk += [h + sm_t, h + t + sm_t]
        xk += [max(0.0, x1 - sm_t), x2 + sm_t]
        if gap is not None:
            xk.append(max(x2 + sm_t, x2 + gap - sm_t))
    xs = _graded_lines(xk, 0.0, x_far, fine, coarse)
    ys = _graded_lines(yk, 0.0, y_top, fine, coarse)
    nx, ny = len(xs), len(ys)

    def fixed_grid(odd):
        f = [[None] * ny for _ in range(nx)]
        for i, x in enumerate(xs):
            for j, y in enumerate(ys):
                on_metal_layer = h - 1e-12 <= y <= h + t + 1e-12
                if j == 0 or j == ny - 1 or i == nx - 1:
                    f[i][j] = 0.0  # plane below, far edge / plane above
                elif odd and i == 0:
                    f[i][j] = 0.0  # pair axis at 0 V (odd mode)
                elif on_metal_layer and x1 - 1e-12 <= x <= x2 + 1e-12:
                    f[i][j] = 1.0  # track
                elif on_metal_layer and gap is not None and x >= x2 + gap - 1e-12:
                    f[i][j] = 0.0  # outer coplanar ground
        return f

    def eps_grid(e, sm_eps):
        cells = [[1.0] * (ny - 1) for _ in range(nx - 1)]
        for i in range(nx - 1):
            xc = (xs[i] + xs[i + 1]) / 2
            for j in range(ny - 1):
                yc = (ys[j] + ys[j + 1]) / 2
                if yc < h or (h_top is not None and yc > h + t):
                    cells[i][j] = e
                elif h_top is not None and h <= yc <= h + t:
                    cells[i][j] = e  # stripline: dielectric also between the tracks
                elif sm_t > 0 and yc > h:
                    # Conformal solder mask on top of/beside tracks and ground
                    # and on the bare dielectric (also between the two tracks)
                    over_trace = x1 - sm_t <= xc <= x2 + sm_t and yc <= h + t + sm_t
                    over_gnd = (gap is not None and xc >= x2 + gap - sm_t
                                and yc <= h + t + sm_t)
                    on_substrate = yc <= h + sm_t
                    if over_trace or over_gnd or on_substrate:
                        cells[i][j] = sm_eps
        return cells

    eps_d, eps_0 = eps_grid(er, sm_er), eps_grid(1.0, 1.0)
    z = {}
    for odd in (True, False):
        fixed = fixed_grid(odd)
        # Half domain = one whole track: the energy is already the capacitance
        # of one line in the considered mode (eps0 units)
        c = _solve(xs, ys, eps_d, fixed)
        c0 = _solve(xs, ys, eps_0, fixed)
        z[odd] = ETA0 / math.sqrt(c * c0)
    result = (2 * z[True], z[False] / 2, z[True], z[False])
    _cache[key] = result
    return result
