# Guía de simulaciones

Qué mide cada experimento de `research/experimentos` y cómo se relaciona con lo
que se ve en el panel. Es el material del capítulo 10 de la memoria.

## Dos mediciones distintas

| | `research/experimentos` | Métricas del panel |
| --- | --- | --- |
| Qué mide | El criterio de asignación aislado | El sistema completo |
| Sobre qué | Jornadas de reparto simuladas, 40 por nivel de demanda | Oleadas reales del orquestador |
| Incluye | Energía, recarga, llegadas de pedidos | Además: esperas del HUB, escalonado, plazas |
| Para qué | Comparar políticas con potencia estadística | Comprobar que la diferencia sobrevive a la coordinación |

## El coste

Asignar el dron *i* al pedido *j* cuesta la energía del viaje de ida y vuelta,
en Wh (`core/cost.py`). Es infinito si el paquete supera la carga del dron o si
el viaje invadiría la reserva del 20 % de la batería. No hay pesos que ajustar.

## Los guiones

```powershell
pip install -r requirements/research.txt
cd research/experimentos
python oleada.py                 # oleada aislada: FIFO y JV frente al óptimo exacto (MILP)
python barrido.py                # 1680 jornadas: 6 niveles de demanda x 5 políticas x 40 + flotas
python analisis.py               # medias, intervalos de confianza y Wilcoxon con Holm
python trazas.py                 # una jornada de ejemplo y las esperas por peso del paquete
python figuras.py                # figuras del capítulo 10
python figuras_cap8.py           # figuras del capítulo 8
python oleada_sistema.py         # PO-8: los dos asignadores sobre el orquestador real
```

`barrido.py` guarda cada jornada en `barrido.jsonl` y, si se interrumpe, continúa
donde lo dejó. Tarda alrededor de una hora en dos núcleos; casi todo el tiempo
es de los planes MILP, que necesitan **PuLP 2.9** (la 4.0 cambió la interfaz).

## Las políticas

- **FIFO**: el voraz del sistema. Cada pedido, por orden de llegada, al dron disponible que menos gasta.
- **JV**: el asignador global del sistema. En cada ciclo, el reparto de mínima energía total.
- **JV con antigüedad**: lo mismo, restando al coste de cada pedido la energía de un viaje medio por cada hora de espera.
- **MILP con horizonte**: planifica la hora siguiente para toda la flota y despacha solo las primeras salidas.
- **MILP con previsión**: además, reserva capacidad para la media hora de pedidos que se espera que lleguen.

## Del simulador al enjambre

El panel deja elegir entre el voraz y el global. Para comparar los dos sobre el
sistema completo, `oleada_sistema.py` reparte la misma oleada con cada uno y
compara energía, duración y esperas de coordinación. En el panel se hace lo
mismo a mano: sembrar con `python -m airdrop.demo seed oleada --seed 42`,
repartir, vaciar las métricas, volver a sembrar y repetir con el otro asignador.
