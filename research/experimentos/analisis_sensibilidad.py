"""Resume el análisis de sensibilidad: cada variante frente a la referencia (mismas jornadas de barrido.json).

Para cada política, demanda y variante da la diferencia media con la configuración de referencia en
entregas a tiempo, espera P95 y clientes lejanos a tiempo, con su intervalo de confianza por remuestreo
y la prueba de Wilcoxon corregida por Holm sobre todas las comparaciones de la sensibilidad.
Escribe sensibilidad_resumen.json.
"""
import json
import os

import numpy as np

from comun import holm, paired

AQUI = os.path.dirname(os.path.abspath(__file__))
REF = {}
for kind, lam, seed, pol, fl, m in json.load(open(os.path.join(AQUI, 'barrido.json'))):
    if kind == 'demanda':
        REF[(pol, lam, seed)] = m
VAR = {}
ruta = os.path.join(AQUI, 'sensibilidad.jsonl')
for linea in open(ruta):
    pol, nombre, lam, seed, m = json.loads(linea)
    VAR.setdefault((pol, nombre, lam), {})[seed] = m

METRICAS = [('promise', 100), ('wait_p95', 1), ('promise_far', 100), ('served', 100)]
filas = []
for (pol, nombre, lam), dias in sorted(VAR.items()):
    ks = sorted(s for s in dias if (pol, lam, s) in REF)
    if len(ks) < 10:
        continue
    fila = dict(pol=pol, var=nombre, lam=lam, n=len(ks))
    for met, esc in METRICAS:
        x = [REF[(pol, lam, s)][met] for s in ks]
        y = [dias[s][met] for s in ks]
        r = paired(x, y)
        fila[met] = dict(ref=float(np.mean(x)) * esc, var=float(np.mean(y)) * esc,
                         d=float(r['mean']) * esc, lo=float(r['lo']) * esc, hi=float(r['hi']) * esc,
                         p=float(r['p']))
    filas.append(fila)
ps = [f[m]['p'] for f in filas for m, _ in METRICAS[:3]]
ph = iter(holm(ps))
for f in filas:
    for m, _ in METRICAS[:3]:
        f[m]['p_holm'] = float(next(ph))
json.dump(filas, open(os.path.join(AQUI, 'sensibilidad_resumen.json'), 'w'), indent=1)
for f in filas:
    def c(m):
        v = f[m]
        estrella = '*' if v.get('p_holm', 1) < 0.05 else ' '
        return f"{v['var']:6.1f} ({v['d']:+5.1f}){estrella}"
    print(f"{f['pol']:18s} {f['var']:14s} {f['lam']:3.0f} n={f['n']:2d}  a tiempo {c('promise')}  P95 {c('wait_p95')}  lejanos {c('promise_far')}  servidos {f['served']['var']:5.1f}")
