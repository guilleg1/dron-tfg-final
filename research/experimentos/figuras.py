"""Figuras del Capítulo 10, en blanco y negro y a la anchura de la caja de texto (15 cm).

    python figuras.py            # todas
    python figuras.py 1 3        # solo algunas
"""
import json
import os
import sys

import numpy as np
from matplotlib.patches import Patch

from estilo_fig import GRIS, NEGRO, POLITICAS, coma, plt, rejilla

AQUI = os.path.dirname(os.path.abspath(__file__))
OUT = os.environ.get('OUT', os.path.join(AQUI, 'figuras'))
os.makedirs(OUT, exist_ok=True)
ANCHO = 5.9
cual = sys.argv[1:] or ['1', '2', '3', '4', '5']


def J(f):
    return json.load(open(os.path.join(AQUI, f)))


def serie(ax, x, y, col, ls, mk, lab):
    ax.plot(x, y, color=col, ls=ls, marker=mk, mfc='white', mec=col, mew=0.9, label=lab)


# ── Oleada aislada frente al óptimo ──
if '1' in cual:
    R = J('oleada.json')
    ns = sorted(int(n) for n in R)
    fig, ax = plt.subplots(figsize=(ANCHO * 0.62, 2.45))
    for k, lab, col, ls, mk in [('milp', 'Óptimo exacto', NEGRO, ':', 's'), ('jv', 'JV por rondas', GRIS, '--', 's'),
                                ('fifo', 'Voraz FIFO', NEGRO, '-', 'o')]:
        serie(ax, ns, [R[str(n)][k]['rate'] * 100 for n in ns], col, ls, mk, lab)
    ax.set_xlabel('Pedidos en la oleada'); ax.set_ylabel('Pedidos entregados (%)')
    ax.set_xticks(ns); ax.set_ylim(30, 102); rejilla(ax); ax.legend(loc='lower left')
    fig.savefig(os.path.join(OUT, 'oleada_optimo.pdf')); plt.close(fig)

# ── Jornada de ejemplo ──
if '2' in cual:
    T = J('trazas.json')['gantt']
    fig, axs = plt.subplots(2, 1, figsize=(ANCHO, 3.6), sharex=True)
    clases = [(1.0, 'white', 'hasta 1 kg'), (2.0, '0.62', 'de 1 a 2 kg'), (9, '0.15', 'más de 2 kg')]
    cat = {'D-1': 'ligero', 'D-2': 'ligero', 'D-3': 'medio', 'D-4': 'medio', 'D-5': 'pesado'}
    for ax, (p, lab) in zip(axs, [('FIFO', 'Voraz FIFO'), ('MILP con previsión', 'MILP con previsión')]):
        tr = T[p]['trace']; m = T[p]['metrics']; ids = sorted(tr)
        for y, did in enumerate(ids):
            for a, b, w, d in tr[did]:
                col = next(c for lim, c, _ in clases if w <= lim)
                ax.barh(y, (b - a) / 3600, left=a / 3600, height=0.6, color=col, edgecolor='black', lw=0.35)
        ax.set_yticks(range(len(ids)), [f'{i} ({cat[i]})' for i in ids]); ax.invert_yaxis()
        ax.axvline(4, color=NEGRO, lw=0.7, ls=':')
        ax.set_title(f"{lab}: {m['promise'] * 100:.1f} % entregados en menos de una hora".replace('.', ','), loc='left')
        rejilla(ax, 'x'); ax.tick_params(axis='y', length=0)
    axs[1].set_xlabel('Hora de la jornada (h)'); axs[1].set_xlim(0, 5.05); coma(axs[1], 'x')
    fig.legend([Patch(facecolor=c, edgecolor='black', lw=0.35) for _, c, _ in clases], [l for *_, l in clases],
               loc='lower center', ncol=3, bbox_to_anchor=(0.55, -0.04), title='Peso del paquete', title_fontsize=8)
    fig.tight_layout(rect=(0, 0.07, 1, 1)); fig.savefig(os.path.join(OUT, 'jornada.pdf')); plt.close(fig)

# ── Resultados frente a la demanda ──
if '3' in cual:
    S = J('analisis.json')['summary']
    lams = sorted({float(k.split('|')[0]) for k in S})
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(ANCHO, 2.5))
    for k, lab, col, ls, mk in POLITICAS:
        if k == 'MILP horizonte':
            continue
        serie(a1, lams, [S[f'{l:g}|{k}']['promise'][0] * 100 for l in lams], col, ls, mk, lab)
        serie(a2, lams, [S[f'{l:g}|{k}']['wait_p95'][0] for l in lams], col, ls, mk, lab)
    a1.set_ylabel('Entregados en menos de 1 h (%)'); a2.set_ylabel('Espera del percentil 95 (min)')
    a1.set_title('(a) Cumplimiento de la promesa', loc='left'); a2.set_title('(b) Los clientes peor atendidos', loc='left')
    for a in (a1, a2):
        a.set_xlabel('Demanda (pedidos por hora)'); a.set_xticks(lams); rejilla(a); coma(a, 'y')
    h, l = a1.get_legend_handles_labels()
    fig.legend(h, l, loc='lower center', ncol=4, bbox_to_anchor=(0.5, -0.02))
    fig.tight_layout(rect=(0, 0.08, 1, 1), w_pad=2.5); fig.savefig(os.path.join(OUT, 'demanda.pdf')); plt.close(fig)

# ── Cumplimiento por peso del paquete ──
if '4' in cual:
    Wt = J('trazas.json')['waits']
    clases = [(0, 1, 'Hasta 1 kg\n(cualquier dron)'), (1, 2, 'De 1 a 2 kg\n(medio o pesado)'), (2, 9, 'Más de 2 kg\n(solo el pesado)')]
    pols = [p for p in POLITICAS if p[0] in Wt]
    rellenos = [('white', ''), ('0.8', ''), ('white', '////'), ('0.3', '')]
    fig, ax = plt.subplots(figsize=(ANCHO, 2.5)); x = np.arange(3); bw = 0.19
    for k, ((key, lab, *_), (fc, ht)) in enumerate(zip(pols, rellenos)):
        v = [100 * np.mean([w is not None and w <= 60 for w, kg in Wt[key] if lo < kg <= hi]) for lo, hi, _ in clases]
        xs = x + (k - (len(pols) - 1) / 2) * (bw + 0.02)
        ax.bar(xs, v, bw, color=fc, hatch=ht, edgecolor='black', lw=0.5, label=lab)
        for xi, vi in zip(xs, v):
            ax.text(xi, vi + 1.5, f'{vi:.0f}', ha='center', va='bottom', fontsize=7)
    ax.set_xticks(x, [c[2] for c in clases]); ax.set_ylabel('Entregados en menos de 1 h (%)')
    ax.set_ylim(0, 105); ax.set_yticks([0, 20, 40, 60, 80, 100]); rejilla(ax); ax.tick_params(axis='x', length=0)
    ax.legend(loc='upper center', ncol=4, bbox_to_anchor=(0.5, -0.2))
    fig.savefig(os.path.join(OUT, 'por_peso.pdf')); plt.close(fig)

# ── Composición de la flota ──
if '5' in cual:
    F = J('analisis.json')['fleet']; lams = [15, 20, 25, 30]
    flotas = [('2L+2M+1P', 'Dos ligeros, dos medios y un pesado', NEGRO, '-', 'o'),
              ('2L+1M+2P', 'Dos ligeros, un medio y dos pesados', GRIS, '--', 'D'),
              ('1L+2M+2P', 'Un ligero, dos medios y dos pesados', NEGRO, ':', 's')]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(ANCHO, 2.5))
    for k, lab, col, ls, mk in flotas:
        serie(a1, lams, [F[f'{l}|MILP con previsión|{k}']['promise'] * 100 for l in lams], col, ls, mk, lab)
        serie(a2, lams, [F[f'{l}|MILP con previsión|{k}']['e_per_kgkm'] for l in lams], col, ls, mk, lab)
    a1.set_ylabel('Entregados en menos de 1 h (%)'); a2.set_ylabel('Energía por kg·km servido (Wh)')
    a1.set_title('(a) Cumplimiento de la promesa', loc='left'); a2.set_title('(b) Coste energético', loc='left')
    for a in (a1, a2):
        a.set_xlabel('Demanda (pedidos por hora)'); a.set_xticks(lams); rejilla(a); coma(a, 'y')
    h, l = a1.get_legend_handles_labels()
    fig.legend(h, l, loc='lower center', ncol=2, bbox_to_anchor=(0.5, -0.06))
    fig.tight_layout(rect=(0, 0.12, 1, 1), w_pad=2.5); fig.savefig(os.path.join(OUT, 'flota.pdf')); plt.close(fig)
print('ok', cual)
