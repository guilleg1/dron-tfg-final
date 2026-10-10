"""Estilo común de las gráficas de la memoria: blanco y negro, trazo fino y la tipografía del texto.

Las series se distinguen por el tipo de línea y el marcador, no por el color, para que las figuras se lean
igual impresas en blanco y negro.
"""
import os

import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402

_HEROS = '/usr/share/texmf/fonts/opentype/public/tex-gyre/texgyreheros-regular.otf'
if os.path.exists(_HEROS):
    for f in ('regular', 'bold', 'italic', 'bolditalic'):
        p = _HEROS.replace('regular', f)
        if os.path.exists(p):
            font_manager.fontManager.addfont(p)
    FAMILIA = 'TeX Gyre Heros'
else:
    FAMILIA = 'DejaVu Sans'

plt.rcParams.update({
    'font.family': FAMILIA, 'font.size': 9, 'axes.titlesize': 9, 'axes.labelsize': 9,
    'xtick.labelsize': 8, 'ytick.labelsize': 8, 'legend.fontsize': 8,
    'axes.linewidth': 0.6, 'xtick.major.width': 0.6, 'ytick.major.width': 0.6,
    'xtick.major.size': 3, 'ytick.major.size': 3, 'xtick.direction': 'in', 'ytick.direction': 'in',
    'axes.spines.top': False, 'axes.spines.right': False,
    'lines.linewidth': 1.1, 'lines.markersize': 4,
    'legend.frameon': False, 'legend.handlelength': 2.6,
    'savefig.bbox': 'tight', 'savefig.pad_inches': 0.03, 'pdf.fonttype': 42,
    'axes.formatter.use_locale': False,
})

NEGRO, GRIS, GRIS_CLARO = '0.0', '0.45', '0.75'
COMA = FuncFormatter(lambda v, p: f'{v:g}'.replace('.', ','))

# Política: (clave en los resultados, etiqueta, color, línea, marcador)
POLITICAS = [
    ('FIFO', 'Voraz FIFO', NEGRO, '-', 'o'),
    ('JV', 'JV por ciclo', GRIS, '--', 's'),
    ('JV+antigüedad', 'JV con antigüedad', GRIS, ':', 'D'),
    ('MILP horizonte', 'MILP con horizonte', NEGRO, (0, (5, 1.5)), 'v'),
    ('MILP con previsión', 'MILP con previsión', NEGRO, '-.', '^'),
]


def rejilla(ax, eje='y'):
    ax.grid(axis=eje, color='0.88', lw=0.5)
    ax.set_axisbelow(True)


def coma(ax, ejes='xy'):
    if 'x' in ejes:
        ax.xaxis.set_major_formatter(COMA)
    if 'y' in ejes:
        ax.yaxis.set_major_formatter(COMA)
