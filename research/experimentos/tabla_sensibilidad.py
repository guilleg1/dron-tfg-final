"""Genera la tabla LaTeX de la sensibilidad (35 pedidos por hora) a partir de sensibilidad_resumen.json."""
import json, os
AQUI = os.path.dirname(os.path.abspath(__file__))
F = json.load(open(os.path.join(AQUI, 'sensibilidad_resumen.json')))
NOMBRE = {'JV+antigüedad': 'JV con antigüedad', 'MILP horizonte': 'MILP con horizonte', 'MILP con previsión': 'MILP con previsión'}
def var(v):
    k, _, x = v.partition('=')
    if v == 'lexicografico': return 'lexicográfica'
    x = x.replace('.', '{,}')
    return {'beta': r'$\beta = %s$', 'bonus': r'$b = %s$', 'eps': r'$\varepsilon = %s$', 'phantom': r'previstos $%s$'}[k] % (
        x.replace('0{,}0001', r'10^{-4}').replace('0{,}01', r'10^{-2}'))
def cel(d, esc=1):
    s = f"{d['d']:+.1f}".replace('.', '{,}').replace('-', '$-$').replace('+', '$+$')
    return s + (r'\,$\ast$' if d.get('p_holm', 1) < 0.05 else '')
filas = []
for f in F:
    if f['lam'] != 35: continue
    filas.append(f"{NOMBRE[f['pol']]} & {var(f['var'])} & {cel(f['promise'])} & {cel(f['wait_p95'])} & {cel(f['promise_far'])} \\\\")
print('\n'.join(filas))
