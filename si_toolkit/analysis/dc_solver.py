"""
Solutore della rete resistiva per la distribuzione di corrente DC.

Questo file NON dipende da pcbnew: riceve una lista di resistenze fra nodi
generici e risolve le leggi di Kirchhoff. Tenerlo separato da KiCad serve a
due cose: si puo' provare fuori da KiCad con reti di esempio, e se l'API di
KiCad cambia (le SWIG verranno rimosse) il calcolo non va riscritto.

Metodo: analisi nodale. Per ogni nodo, somma delle correnti uscenti = 0.
Si fissa a 0 V il nodo sorgente come riferimento, ogni carico preleva la
sua corrente (iniezione negativa) e si risolve il sistema G * V = b con il
gradiente coniugato (la matrice delle conduttanze, senza il nodo di
riferimento, e' simmetrica e definita positiva). Alla fine le tensioni
vengono spostate in modo che il carico piu' "lontano" sia a 0 V: cosi'
la tensione di ogni nodo e' la caduta che resta fino al carico peggiore,
e con un solo carico il risultato e' identico al vecchio schema
(sorgente = caduta totale, uscita = 0 V).
"""
from collections import deque
from ..common.i18n import _

# Resistenza minima accettata (ohm): evita conduttanze infinite
MIN_RESISTANCE = 1e-6


def solve_dc(edges, source, sink, current, loads=None):
    """
    edges: lista di tuple (nodo_a, nodo_b, resistenza_ohm, tag).
    source: nodo dove entra la corrente.
    sink / current: unico nodo di uscita e corrente totale (A). Ignorati se
    si passa 'loads'.
    loads: lista di (nodo, corrente_A) per piu' uscite; la corrente che
    entra dalla sorgente e' la somma di quelle dei carichi.

    Ritorna (potenziali, correnti): 'potenziali' e' un dict nodo -> volt,
    'correnti' e' una lista parallela a 'edges' con la corrente (A) che
    scorre da nodo_a a nodo_b (0 per i rami fuori dalla parte connessa).
    Solleva ValueError se un carico non e' collegato alla sorgente.
    """
    if loads is None:
        loads = [(sink, current)]
    # Carichi coincidenti con la sorgente: la corrente non attraversa rame
    loads = [(n, i) for n, i in loads if n != source and i != 0]
    if not loads:
        raise ValueError(_("Sorgente e ritorno coincidono."))

    # Lista di adiacenza: nodo -> [(vicino, conduttanza)]
    adj = {}
    for a, b, r, _tag in edges:
        if a == b:
            continue  # ramo in corto su se stesso: nessuna corrente
        g = 1.0 / max(r, MIN_RESISTANCE)
        adj.setdefault(a, []).append((b, g))
        adj.setdefault(b, []).append((a, g))

    if source not in adj or any(n not in adj for n, _i in loads):
        raise ValueError(_("Sorgente o ritorno non collegati ad alcun ramo."))

    # Componente connessa che contiene la sorgente (BFS)
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

    # Incognite: tutti i nodi della componente tranne la sorgente (V = 0)
    unknowns = [n for n in comp if n != source]
    index = {n: i for i, n in enumerate(unknowns)}
    size = len(unknowns)

    # Termine noto: ogni carico preleva la sua corrente (iniezione negativa).
    # Con la sorgente a 0 V i carichi risultano a tensione negativa.
    b = [0.0] * size
    for n, i_load in loads:
        b[index[n]] -= i_load

    # Diagonale (somma conduttanze) per il precondizionatore di Jacobi
    diag = [0.0] * size
    for n in unknowns:
        diag[index[n]] = sum(g for _m, g in adj[n])

    def matvec(x):
        # Prodotto G * x senza costruire la matrice
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

    # Gradiente coniugato precondizionato
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
    # Spostamento: il carico a tensione piu' bassa va a 0 V, la sorgente
    # vale la caduta verso quel carico (convenzione del vecchio schema)
    v_min = min(potentials[n] for n, _i in loads)
    for n in potentials:
        potentials[n] -= v_min

    # Corrente in ogni ramo (legge di Ohm)
    currents = []
    for a, b_node, r_ohm, _tag in edges:
        if a == b_node or a not in potentials or b_node not in potentials:
            currents.append(0.0)
        else:
            currents.append((potentials[a] - potentials[b_node]) / max(r_ohm, MIN_RESISTANCE))
    return potentials, currents
