"""Análisis de sensibilidad de los coeficientes de las políticas con antigüedad y de los planes MILP.

Varía un coeficiente cada vez (el resto en su valor de referencia) con 30 y 35 pedidos por hora y las mismas
40 jornadas que el barrido principal (semilla 1000*lam + s), de modo que cada variante se compara por parejas
con la referencia de barrido.jsonl. Incluye una variante «lexicográfica» del MILP en la que la antigüedad y la
salida inmediata solo desempatan, para ver qué cambia si el plan maximiza primero el número de entregas.

Reanudable: cada jornada se añade a sensibilidad.jsonl.
"""
import json
import multiprocessing as mp
import os

import jornada
from jornada import make_day, simulate

REF = dict(BETA=1.0, NOW_BONUS=0.5, PHANTOM_VALUE=0.7, EPS=1e-3)
VARIANTES = []   # (política, nombre, cambios)
for b in [0.0, 0.25, 0.5, 2.0, 4.0]:
    VARIANTES.append(('JV+antigüedad', f'beta={b}', {'BETA': b}))
for b in [0.0, 0.5, 2.0]:
    VARIANTES.append(('MILP horizonte', f'beta={b}', {'BETA': b}))
for nb in [0.0, 0.25, 1.0]:
    VARIANTES.append(('MILP horizonte', f'bonus={nb}', {'NOW_BONUS': nb}))
for e in [1e-4, 1e-2]:
    VARIANTES.append(('MILP horizonte', f'eps={e}', {'EPS': e}))
VARIANTES.append(('MILP horizonte', 'lexicografico', {'BETA': 0.01, 'NOW_BONUS': 0.01}))
for pv in [0.35, 1.0]:
    VARIANTES.append(('MILP con previsión', f'phantom={pv}', {'PHANTOM_VALUE': pv}))
VARIANTES.append(('MILP con previsión', 'lexicografico', {'BETA': 0.01, 'NOW_BONUS': 0.01}))
PARCIAL = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sensibilidad.jsonl')


def job(a):
    pol, nombre, lam, seed = a
    cambios = dict(next(c for p, n, c in VARIANTES if p == pol and n == nombre))
    for k, v in {**REF, **cambios}.items():
        setattr(jornada, k, v)
    jornada.LAM_FORECAST['lam'] = lam
    r = simulate(make_day(lam, 1000 * int(lam) + seed), jornada.POLICIES[pol])
    return (pol, nombre, lam, seed, {k: v for k, v in r.items() if k not in ('trace', 'waits')})


if __name__ == '__main__':
    ND = 40
    # primero las variantes baratas y la del horizonte, después las de previsión, que tardan más
    orden = sorted(VARIANTES, key=lambda v: {'JV+antigüedad': 0, 'MILP horizonte': 1, 'MILP con previsión': 2}[v[0]])
    jobs = [(p, n, lam, s) for p, n, _ in orden for lam in [35, 30] for s in range(ND)]
    hechos = [json.loads(l) for l in open(PARCIAL)] if os.path.exists(PARCIAL) else []
    claves = {tuple(r[:4]) for r in hechos}
    pend = [j for j in jobs if tuple(j) not in claves]
    print(f'{len(hechos)} hechas, {len(pend)} pendientes', flush=True)
    with mp.Pool(2) as pool, open(PARCIAL, 'a') as f:
        for k, r in enumerate(pool.imap_unordered(job, pend, chunksize=1)):
            f.write(json.dumps(r) + '\n'); f.flush()
            if k % 20 == 0:
                print(k, len(pend), r[0], r[1], r[2], flush=True)
    print('fin', flush=True)
