# AirDrop — gestión autónoma de un enjambre de drones de reparto

Trabajo de Fin de Grado (UPC). Reparto urbano con una flota de drones: cómo
asignar pedidos a drones de forma eficiente y cómo coordinar el tráfico del
enjambre de manera segura.

**Portal en vivo:** https://tfg-drones.up.railway.app/ (Railway, con cuatro autopilotos ArduCopter en SITL; ver [docs/swarm/NUBE.md](docs/swarm/NUBE.md))

## Estructura

El repositorio está dividido en cuatro zonas por ciclo de vida.

```
core/       Núcleo algorítmico: modelo de energía, función de costes y los dos
            asignadores (voraz y global por matriz de costes). No importa de
            ninguna otra zona.
airdrop/    El producto: API FastAPI, dominio, estáticos del portal, enlace con
            el autopiloto y orquestación del enjambre.
research/   Lo que valida `core`: simulador de jornadas de reparto, generador
            de escenarios y los experimentos del capítulo 10 de la memoria.
legacy/     Archivo histórico: primeras implementaciones. Congelado.
vendor/     dronLink, el enlace MAVLink.
```

La regla que las ordena: **`core` no importa de nadie; `airdrop` y `research`
importan de `core`; nadie importa de `legacy`.**

Esa regla es la tesis del trabajo hecha estructura. El algoritmo que despacha
drones reales (`core/greedy.py`) es literalmente el mismo que se valida
experimentalmente contra Jonker-Volgenant en `research/`.

## Cómo probarlo

```bash
pip install -e . -r requirements/dev.txt
python -m pytest -q
```

### Portal en local, sin dron

```bash
uvicorn airdrop.api.main:app --port 8080     # http://localhost:8080/
```

### Portal en local, contra Mission Planner

Requiere Mission Planner con SITL escuchando en `tcp:127.0.0.1:5763`.

```bash
pip install -r requirements/sitl.txt
./run_local.ps1
```

El backend de dron se elige con la variable de entorno `DRONE_BACKEND`:
`stub` (por defecto, sin dron) o `local` (Mission Planner por dronLink).

### Demostraciones

Escenarios de pedidos con clientes simulados, para enseñar el enjambre sin
rellenar formularios a mano:

```bash
python -m airdrop.demo list              # presets disponibles
python -m airdrop.demo seed oleada --seed 42
python -m airdrop.demo clear             # borra solo lo simulado
```

Los clientes caen dentro de la geovalla del escenario activo y los pesos nunca
superan la carga máxima de la flota. El guion completo de la demo está en
[`docs/swarm/DEMO.md`](docs/swarm/DEMO.md).

### Experimentos

```bash
pip install -r requirements/research.txt
cd research/experimentos
python oleada.py                          # oleada aislada frente al óptimo exacto
python barrido.py && python analisis.py   # 40 jornadas por nivel de demanda y flotas
python trazas.py && python figuras.py     # jornada de ejemplo y figuras
python oleada_sistema.py                  # los dos asignadores sobre el sistema completo
```

El coste de asignar un dron a un pedido es la energía del viaje
(`core/cost.py`). Los experimentos comparan el voraz FIFO, el asignador global
de Jonker-Volgenant y un planificador MILP con horizonte deslizante a lo largo
de jornadas completas de reparto. Qué mide cada guion está en
[`docs/swarm/SIMULACIONES.md`](docs/swarm/SIMULACIONES.md).

## Documentación

- [`docs/swarm/ARRANQUE.md`](docs/swarm/ARRANQUE.md) — arranque limpio y
  recorrido de la webapp
- [`docs/swarm/DEMO.md`](docs/swarm/DEMO.md) — guion de demostración
- [`docs/swarm/SIMULACIONES.md`](docs/swarm/SIMULACIONES.md) — qué mide cada
  experimento y cómo llevar los resultados al enjambre
- [`docs/swarm/MQTT.md`](docs/swarm/MQTT.md) — diseño de la conexión con drones
  reales (Raspberry Pi por broker, patrón DEE)
- [`docs/swarm/SITL.md`](docs/swarm/SITL.md) — SITL multi-instancia y sus
  trampas

- [`docs/swarm/`](docs/swarm/) — investigación previa sobre enjambres
  (ver la nota de vigencia)
