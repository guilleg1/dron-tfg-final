"""Barrido de demanda (cinco políticas, 40 jornadas por nivel) y de composición de la flota.

Cada jornada terminada se añade a barrido.jsonl, de modo que si el proceso se interrumpe basta con volver a
lanzarlo y continúa donde lo dejó. Al terminar escribe barrido.json, que es lo que lee analisis.py.
"""
import json
import multiprocessing as mp
import os

import jornada
from jornada import FLEET, POLICIES, make_day, simulate

FL = {'2L+2M+1P': FLEET,
      '1L+2M+2P': [('D-1', 'ligero'), ('D-3', 'medio'), ('D-4', 'medio'), ('D-5', 'pesado'), ('D-6', 'pesado')],
      '2L+1M+2P': [('D-1', 'ligero'), ('D-2', 'ligero'), ('D-3', 'medio'), ('D-5', 'pesado'), ('D-6', 'pesado')]}
PARCIAL = 'barrido.jsonl'


def job(a):
    kind, lam, seed, pol, fl = a
    jornada.LAM_FORECAST['lam'] = lam
    r = simulate(make_day(lam, 1000 * int(lam) + seed), POLICIES[pol], fleet=FL[fl])
    return (kind, lam, seed, pol, fl, {k: v for k, v in r.items() if k not in ('trace', 'waits')})


if __name__ == '__main__':
    ND = 40
    jobs = [('demanda', lam, s, p, '2L+2M+1P') for lam in [10, 15, 20, 25, 30, 35] for s in range(ND) for p in POLICIES]
    jobs += [('flota', lam, s, p, fl) for lam in [15, 20, 25, 30] for s in range(30)
             for p in ['FIFO', 'MILP con previsión'] for fl in FL if fl != '2L+2M+1P']
    hechos = []
    if os.path.exists(PARCIAL):
        hechos = [json.loads(l) for l in open(PARCIAL) if l.strip()]
    claves = {tuple(r[:5]) for r in hechos}
    pendientes = [j for j in jobs if tuple(j) not in claves]
    print(f'{len(hechos)} jornadas ya hechas, {len(pendientes)} pendientes', flush=True)
    with mp.Pool(2) as pool, open(PARCIAL, 'a') as f:
        for k, r in enumerate(pool.imap_unordered(job, pendientes, chunksize=2)):
            f.write(json.dumps(r) + '\n'); f.flush()
            if k % 50 == 0:
                print(k, len(pendientes), flush=True)
    hechos = [json.loads(l) for l in open(PARCIAL) if l.strip()]
    json.dump(hechos, open('barrido.json', 'w'))
    print('fin', len(hechos))
