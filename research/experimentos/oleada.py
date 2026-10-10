"""Oleada aislada: voraz FIFO y JV frente al óptimo exacto (Figura 10.1). Escribe oleada.json.

Cada oleada parte de la flota por defecto con baterías parciales (50–90 %) y una
mezcla de pesos con mayoría de paquetes ligeros. No hay recarga: se mide cuántos
pedidos cabe servir con la energía que la flota tiene en ese momento.
"""
import json

import numpy as np

from comun import fifo, jv, milp_max, paired, scenarios

MIX = [(0.5, 0.2, 1.0), (0.3, 1.0, 2.0), (0.2, 2.0, 4.0)]

if __name__ == '__main__':
    out = {}
    for n in [5, 10, 20, 30, 40, 60]:
        sc = scenarios(60, 1000 + n, orders=n, mix=MIX)
        r = {'fifo': [fifo(s) for s in sc], 'jv': [jv(s) for s in sc],
             'milp': [milp_max(s, time_limit=20) for s in sc]}
        base = [x.delivered for x in r['fifo']]
        out[n] = {a: dict(rate=float(np.mean([x.rate for x in v])),
                          epd=float(np.nanmean([x.epd for x in v])),
                          ci=paired(base, [x.delivered for x in v]))
                  for a, v in r.items()}
        print(n, ' '.join(f"{a}:{out[n][a]['rate'] * 100:5.1f}%" for a in r), flush=True)
    json.dump(out, open('oleada.json', 'w'), default=float, indent=1)
