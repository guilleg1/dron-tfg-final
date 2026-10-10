# Experimentos del capítulo 10

Guiones con los que se generan los resultados del estudio en simulación de la memoria.
Se ejecutan desde esta carpeta; cada uno escribe su JSON aquí.

| Guion | Qué genera |
|---|---|
| `jornada.py` | Simulador de jornada: llegadas de Poisson, recarga en la base y las cinco políticas (FIFO, JV, JV con antigüedad, MILP con horizonte y MILP con previsión) |
| `barrido.py`, `analisis.py` | 40 jornadas por nivel de demanda y composición de la flota; medias, intervalos y Wilcoxon con Holm (Figuras 10.3 y 10.5, Tablas 10.2 y 10.3) |
| `trazas.py` | Jornada de ejemplo y esperas por peso del paquete (Figuras 10.2 y 10.4) |
| `oleada.py` | Oleada aislada frente al óptimo exacto (Figura 10.1) |
| `oleada_sistema.py` | Los dos asignadores sobre el orquestador real con el enlace simulado (Tabla 11.3) |
| `sensibilidad.py`, `analisis_sensibilidad.py`, `tabla_sensibilidad.py` | Sensibilidad de los coeficientes ($\beta$, $b$, $\varepsilon$, valor de los previstos y variante lexicográfica) con 30 y 35 pedidos por hora (Tabla 10.4) |
| `figuras.py`, `figuras_cap8.py` | Figuras de los capítulos 10 y 8, en blanco y negro |
| `comun.py` | Asignadores de oleada, óptimo exacto y estadística, sobre `core/cost.py` |

El coste de cada pareja dron-pedido es el del sistema: la energía del viaje (`core/cost.py`).

Dependencias: numpy, scipy, matplotlib y **PuLP 2.9.0** (la 4.0 cambió la interfaz).
`barrido.py` y `sensibilidad.py` guardan cada jornada en su `.jsonl` y continúan donde lo dejaron si se interrumpen.
