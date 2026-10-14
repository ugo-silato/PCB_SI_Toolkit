"""
Solver of the resistive network for the DC current distribution.

This file does NOT depend on pcbnew: it receives a list of resistances
between generic nodes and solves Kirchhoff's laws. Keeping it separate from
KiCad has two benefits: it can be tested outside KiCad with example
networks, and if KiCad's API changes (the SWIG bindings will be removed)
the calculation does not need rewriting.

Method: nodal analysis. For every node, sum of outgoing currents = 0.
The source node is fixed at 0 V as reference, each load draws its current
(negative injection) and the system G * V = b is solved with the conjugate
gradient (the conductance matrix without the reference node is symmetric
and positive definite). Finally the voltages are shifted so that the
"farthest" load is at 0 V: this way each node voltage is the drop left down
to the worst load, and with a single load the result is identical to the
old scheme (source = total drop, output = 0 V).
"""
from collections import deque
from ..common.i18n import _

# Minimum accepted resistance (ohm): avoids infinite conductances
MIN_RESISTANCE = 1e-6


def solve_dc(edges, source, sink, current, loads=None):
    """
    edges: list of tuples (node_a, node_b, resistance_ohm, tag).
    source: node where the current enters.
    sink / current: single output node and total current (A). Ignored if
    'loads' is given.
    loads: list of (node, current_A) for several outputs; the current entering
    from the source is the sum of the load currents.

    Returns (potentials, currents): 'potentials' is a dict node -> volt,
    'currents' is a list parallel to 'edges' with the current (A) flowing from
    node_a to node_b (0 for branches outside the connected part).
    Raises ValueError if a load is not connected to the source.
    """
    if loads is None:
        loads = [(sink, current)]
    # Loads coinciding with the source: the current does not cross any copper
    loads = [(n, i) for n, i in loads if n != source and i != 0]
    if not loads:
        raise ValueError(_("Sorgente e ritorno coincidono."))

    # Adjacency list: node -> [(neighbour, conductance)]
    adj = {}
    for a, b, r, _tag in edges:
        if a == b:
            continue  # branch shorted on itself: no current
        g = 1.0 / max(r, MIN_RESISTANCE)
        adj.setdefault(a, []).append((b, g))
        adj.setdefault(b, []).append((a, g))

    if source not in adj or any(n not in adj for n, _i in loads):
        raise ValueError(_("Sorgente o ritorno non collegati ad alcun ramo."))

    # Connected component containing the source (BFS)
    comp = {source}
    queue = deque([source])
    while queue:
        n = queue.popleft()
        for m, _g in adj.get(n, []):
            if m not in comp:
                comp.add(m)
                queue.append(m)
    if any(n not in comp for n, _i in loads):
        raise ValueError(
            _("Sorgente e ritorno non sono collegati dal rame di tracce e via "
            "(forse il collegamento passa da una zona di rame, non considerata).")
        )

    # Unknowns: all the nodes of the component except the source (V = 0)
    unknowns = [n for n in comp if n != source]
    index = {n: i for i, n in enumerate(unknowns)}
    size = len(unknowns)

    # Right-hand side: each load draws its current (negative injection). With
    # the source at 0 V the loads end up at negative voltage.
    b = [0.0] * size
    for n, i_load in loads:
        b[index[n]] -= i_load

    # Diagonal (sum of conductances) for the Jacobi preconditioner
    diag = [0.0] * size
    for n in unknowns:
        diag[index[n]] = sum(g for _m, g in adj[n])

    def matvec(x):
        # Product G * x without building the matrix
        y = [0.0] * size
        for n in unknowns:
            i = index[n]
            acc = diag[i] * x[i]
            for m, g in adj[n]:
                j = index.get(m)
                if j is not None:
                    acc -= g * x[j]
            y[i] = acc
        return y

    # Preconditioned conjugate gradient
    x = [0.0] * size
    r = b[:]
    z = [r[i] / diag[i] for i in range(size)]
    p = z[:]
    rz = sum(r[i] * z[i] for i in range(size))
    b_norm = max(sum(v * v for v in b) ** 0.5, 1e-30)
    for _step in range(max(1000, 20 * size)):
        Ap = matvec(p)
        pAp = sum(p[i] * Ap[i] for i in range(size))
        if pAp <= 0:
            break
        alpha = rz / pAp
        for i in range(size):
            x[i] += alpha * p[i]
            r[i] -= alpha * Ap[i]
        if (sum(v * v for v in r) ** 0.5) / b_norm < 1e-12:
            break
        z = [r[i] / diag[i] for i in range(size)]
        rz_new = sum(r[i] * z[i] for i in range(size))
        beta = rz_new / rz
        rz = rz_new
        for i in range(size):
            p[i] = z[i] + beta * p[i]

    potentials = {n: x[index[n]] for n in unknowns}
    potentials[source] = 0.0
    # Shift: the load at the lowest voltage goes to 0 V, the source equals the
    # drop to that load (convention of the old scheme)
    v_min = min(potentials[n] for n, _i in loads)
    for n in potentials:
        potentials[n] -= v_min

    # Current in every branch (Ohm's law)
    currents = []
    for a, b_node, r_ohm, _tag in edges:
        if a == b_node or a not in potentials or b_node not in potentials:
            currents.append(0.0)
        else:
            currents.append((potentials[a] - potentials[b_node]) / max(r_ohm, MIN_RESISTANCE))
    return potentials, currents
