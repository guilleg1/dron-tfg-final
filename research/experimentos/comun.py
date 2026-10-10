"""Piezas comunes de los experimentos del Capítulo 10.

El coste de cada pareja dron-pedido es el mismo que usa el sistema
(``core.cost.compute_cost``): la energía del viaje en Wh, o infinito si la
pareja es inviable por peso o porque el viaje invadiría la reserva del 20 %.

Contiene los dos asignadores de oleada (voraz FIFO y Jonker-Volgenant por
rondas), el óptimo exacto de una oleada por programación lineal entera y la
estadística pareada con la que se comparan las políticas.
"""
import math
import os
import random
import sys

import numpy as np
from scipy import stats
from scipy.optimize import linear_sum_assignment

_AQUI = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('AIRDROP_REPO') or os.path.abspath(os.path.join(_AQUI, '..', '..'))
sys.path.insert(0, REPO)

from core.cost import SAFETY_MARGIN as R, compute_cost          # noqa: E402
from core.energy import DRONE_CATEGORIES, estimate_duration_s, estimate_trip_energy_wh  # noqa: E402,F401
from research.simulacion.scenario_generator import generate_batch  # noqa: E402

INF = 1e18


class Res:
    """Resultado de asignar una oleada: lista de (dron, pedido, energía)."""

    def __init__(self, n):
        self.assign = []
        self.n = n

    @property
    def delivered(self):
        return len(self.assign)

    @property
    def rate(self):
        return self.delivered / self.n

    @property
    def energy(self):
        return sum(a[2] for a in self.assign)

    @property
    def epd(self):
        return self.energy / self.delivered if self.delivered else np.nan


def fifo(sc):
    """Voraz FIFO: cada pedido, en orden de llegada, al dron viable que menos gasta."""
    B = [d.battery_wh for d in sc.drones]
    r = Res(len(sc.orders))
    for j, o in enumerate(sc.orders):
        best = (math.inf, -1)
        for i, dr in enumerate(sc.drones):
            c = compute_cost(dr.spec, B[i], o.weight_kg, o.distance_km)
            if c < best[0]:
                best = (c, i)
        if best[1] >= 0:
            B[best[1]] -= best[0]
            r.assign.append((best[1], j, best[0]))
    return r


def jv(sc):
    """Jonker-Volgenant por rondas: en cada ronda, el reparto de mínima energía total."""
    B = [d.battery_wh for d in sc.drones]
    pend = list(range(len(sc.orders)))
    r = Res(len(sc.orders))
    while pend:
        M = np.full((len(B), len(pend)), INF)
        for i, dr in enumerate(sc.drones):
            for k, j in enumerate(pend):
                o = sc.orders[j]
                c = compute_cost(dr.spec, B[i], o.weight_kg, o.distance_km)
                if c < math.inf:
                    M[i, k] = c
        if np.all(M >= INF):
            break
        filas, cols = linear_sum_assignment(M)
        hechos = {k for i, k in zip(filas, cols) if M[i, k] < INF}
        if not hechos:
            break
        for i, k in zip(filas, cols):
            if M[i, k] < INF:
                B[i] -= M[i, k]
                r.assign.append((i, pend[k], M[i, k]))
        pend = [j for k, j in enumerate(pend) if k not in hechos]
    return r


def milp_max(sc, eps=1e-4, time_limit=30):
    """Óptimo exacto de la oleada: máximo de entregas y, a igualdad, mínima energía."""
    import pulp
    n, m = len(sc.drones), len(sc.orders)
    x, e = {}, {}
    pr = pulp.LpProblem('oleada', pulp.LpMaximize)
    for i, dr in enumerate(sc.drones):
        for j, o in enumerate(sc.orders):
            if o.weight_kg <= dr.spec.max_payload_kg:
                e[i, j] = estimate_trip_energy_wh(dr.spec, o.distance_km, o.weight_kg)
                x[i, j] = pulp.LpVariable(f'x_{i}_{j}', cat='Binary')
    emax = max(e.values()) if e else 1
    pr += pulp.lpSum(x[k] * (1 - eps * e[k] / emax) for k in x)
    for j in range(m):
        pr += pulp.lpSum(x[i, j] for i in range(n) if (i, j) in x) <= 1
    for i, dr in enumerate(sc.drones):
        usable = dr.battery_wh - R * dr.spec.battery_capacity_wh
        pr += pulp.lpSum(x[i, j] * e[i, j] for j in range(m) if (i, j) in x) <= max(usable, 0)
    pr.solve(pulp.PULP_CBC_CMD(msg=0, timeLimit=time_limit))
    r = Res(m)
    for (i, j), v in x.items():
        if v.value() and v.value() > 0.5:
            r.assign.append((i, j, e[i, j]))
    return r


def scenarios(n, seed, orders=20, bmin=0.5, bmax=0.9, mix=None):
    """Oleadas de la flota por defecto con baterías parciales y la mezcla de pesos indicada."""
    sc = generate_batch(n, 5, orders, seed=seed, weight_min_kg=0.2, weight_max_kg=4.0,
                        battery_min_pct=bmin, battery_max_pct=bmax)
    if mix is not None:
        for s in sc:
            rng = random.Random(s.scenario_id * 7919 + 13)
            for o in s.orders:
                u = rng.random()
                acc = 0
                for p, lo, hi in mix:
                    acc += p
                    if u <= acc:
                        o.weight_kg = round(rng.uniform(lo, hi), 2)
                        break
    return sc


def paired(x, y, nboot=10000, seed=0):
    """y − x: media, IC95 bootstrap, Wilcoxon (Pratt), r biserial de rangos y fracción a favor."""
    x = np.asarray(x, float)
    y = np.asarray(y, float)
    d = y - x
    d = d[~np.isnan(d)]
    rng = np.random.default_rng(seed)
    lo, hi = np.percentile(rng.choice(d, (nboot, len(d))).mean(1), [2.5, 97.5])
    nz = d[d != 0]
    if len(nz) == 0:
        p, rb = 1.0, 0.0
    else:
        p = stats.wilcoxon(d, zero_method='pratt').pvalue
        rk = stats.rankdata(np.abs(nz))
        rb = (rk[nz > 0].sum() - rk[nz < 0].sum()) / rk.sum()
    return dict(mean=d.mean(), lo=lo, hi=hi, p=p, rb=rb, win=np.mean(d > 0),
                tie=np.mean(d == 0), loss=np.mean(d < 0), n=len(d))


def holm(ps):
    """Corrección de Holm-Bonferroni."""
    idx = np.argsort(ps)
    m = len(ps)
    out = np.empty(m)
    prev = 0
    for k, i in enumerate(idx):
        prev = max(prev, min(1, (m - k) * ps[i]))
        out[i] = prev
    return out
