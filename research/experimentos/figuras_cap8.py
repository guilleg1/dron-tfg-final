"""Figuras del Capítulo 8: comportamiento del modelo de energía y ejemplo de oleada con siete pedidos."""
import os

import numpy as np
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle

from comun import DRONE_CATEGORIES, R, compute_cost, estimate_trip_energy_wh, fifo, jv
from estilo_fig import COMA, GRIS, NEGRO, coma, plt, rejilla
from research.simulacion.scenario_generator import generate_scenario

OUT = os.environ.get('OUT', 'figuras')
os.makedirs(OUT, exist_ok=True)
CATS = [('ligero', 'Ligero', NEGRO, '-'), ('medio', 'Medio', GRIS, '--'), ('pesado', 'Pesado', NEGRO, ':')]

# ── Modelo de energía ──
fig, (a1, a2) = plt.subplots(1, 2, figsize=(5.9, 2.35))
d = np.linspace(0, 12, 200)
for cat, lab, col, ls in CATS:
    sp = DRONE_CATEGORIES[cat]
    a1.plot(d, [estimate_trip_energy_wh(sp, x, 1.0) for x in d], color=col, ls=ls, label=lab)
    a1.axhline((1 - R) * sp.battery_capacity_wh, color=col, ls=ls, lw=0.5, alpha=0.6)
    w = np.linspace(0, sp.max_payload_kg, 50)
    usable = (1 - R) * sp.battery_capacity_wh
    alcance = [usable / estimate_trip_energy_wh(sp, 1.0, x) for x in w]   # km de ida
    a2.plot(w, alcance, color=col, ls=ls, label=lab)
a1.set_xlabel('Distancia de ida (km)'); a1.set_ylabel('Energía del viaje (Wh)')
a1.set_title('(a) Viaje con 1 kg de carga', loc='left'); a1.set_xlim(0, 12); a1.set_ylim(0, 300)
a1.text(0.3, 0.8 * 360 + 4, 'batería utilizable', ha='left', va='bottom', fontsize=7, color=GRIS)
a2.set_xlabel('Peso del paquete (kg)'); a2.set_ylabel('Alcance de ida (km)')
a2.set_title('(b) Alcance máximo', loc='left'); a2.set_xlim(0, 4.1); a2.set_ylim(0, 15)
for a in (a1, a2):
    rejilla(a); coma(a)
a2.legend(loc='lower left')
fig.tight_layout(w_pad=2.5)
fig.savefig(os.path.join(OUT, 'modelo_energia.pdf')); plt.close(fig)

# ── Oleada de siete pedidos ──
s = generate_scenario(5, 7, seed=1806, battery_min_pct=0.3, battery_max_pct=0.8,
                      weight_min_kg=1.2, weight_max_kg=3.5)
M = np.full((5, 7), np.nan)
for i, dr in enumerate(s.drones):
    for j, o in enumerate(s.orders):
        c = compute_cost(dr.spec, dr.battery_wh, o.weight_kg, o.distance_km)
        if c < np.inf:
            M[i, j] = c
f, g = fifo(s), jv(s)
fig, ax = plt.subplots(figsize=(5.9, 2.75))
vmax = np.nanmax(M)
for i in range(5):
    for j in range(7):
        v = M[i, j]
        if np.isnan(v):
            ax.add_patch(Rectangle((j - 0.5, i - 0.5), 1, 1, facecolor='white', edgecolor='0.7', hatch='////', lw=0.3))
        else:
            ax.add_patch(Rectangle((j - 0.5, i - 0.5), 1, 1, facecolor=str(1 - 0.35 * v / vmax), edgecolor='white', lw=0.8))
            ax.text(j, i, f'{v:.1f}'.replace('.', ','), ha='center', va='center', fontsize=7.5)
for a, b, _ in f.assign:
    ax.add_patch(plt.Circle((b, a), 0.36, fill=False, ec=NEGRO, lw=1.0, ls='--'))
for a, b, _ in g.assign:
    ax.add_patch(Rectangle((b - 0.44, a - 0.42), 0.88, 0.84, fill=False, ec=NEGRO, lw=1.2))
nombres = ['ligero', 'ligero', 'medio', 'medio', 'pesado']
ax.set_yticks(range(5), [f'{dr.spec.drone_id}  {n}, {round(dr.battery_pct)} %' for dr, n in zip(s.drones, nombres)])
ax.set_xticks(range(7), [f'#{o.order_id}\n{o.weight_kg:.1f} kg\n{o.distance_km:.1f} km'.replace('.', ',') for o in s.orders])
ax.set_xlim(-0.5, 6.5); ax.set_ylim(4.5, -0.5); ax.tick_params(length=0)
for sp in ax.spines.values():
    sp.set_visible(False)
h = [Line2D([0], [0], marker='o', ls='', mfc='none', mec=NEGRO, ms=9, mew=1.0),
     Line2D([0], [0], marker='s', ls='', mfc='none', mec=NEGRO, ms=9, mew=1.2),
     Rectangle((0, 0), 1, 1, facecolor='white', edgecolor='0.7', hatch='////', lw=0.3)]
fig.legend(h, [f'Voraz FIFO: entrega {f.delivered} de 7', f'JV por rondas: entrega {g.delivered} de 7', 'Pareja inviable'],
           loc='lower center', ncol=3, bbox_to_anchor=(0.5, -0.06))
fig.subplots_adjust(bottom=0.28)
fig.savefig(os.path.join(OUT, 'oleada_siete.pdf')); plt.close(fig)
print('fifo', f.delivered, round(f.energy, 1), 'jv', g.delivered, round(g.energy, 1))
