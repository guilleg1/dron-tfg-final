# 03 · Arquitectura propuesta — Swarm Manager

> Diseño técnico del módulo a construir. Pensado para encajar **encima** del
> proyecto actual sin reescribirlo. Cada capa nueva se justifica con su
> responsabilidad y su API pública.

---

## 1. Vista de alto nivel

```
┌───────────────────────────────────────────────────────────────────────────┐
│                            UI (PySide6)                                   │
│   MainWindow  ←→  FleetPanel  ←→  DroneCard(s) (N)  ←→  MapWidget         │
└───────────────────────────────────────────────────────────────────────────┘
                                  ▲
                                  │ señales Qt / dicts
                                  ▼
┌───────────────────────────────────────────────────────────────────────────┐
│                         SwarmService (orquestador)                        │
│  ┌────────────┐  ┌──────────────┐  ┌──────────────┐  ┌─────────────────┐  │
│  │ FleetState │  │   Planner    │  │   Airspace   │  │  Executor (N×)  │  │
│  │ (drones,   │  │ (CVRP+energ.)│  │ deconflicción│  │ 1 task / dron   │  │
│  │  pedidos)  │  │  OR-Tools    │  │ (alts/slots) │  │ ejecuta plan    │  │
│  └────────────┘  └──────────────┘  └──────────────┘  └─────────────────┘  │
└───────────────────────────────────────────────────────────────────────────┘
                                  ▲
                                  │ comandos MAVLink (paralelo)
                                  ▼
┌──────────────────────────┐   ┌──────────────────────────┐
│  DroneService("Dron-1")  │   │  DroneService("Dron-2")  │   ...  (N veces)
│  dronLink → SITL :5760   │   │  dronLink → SITL :5763   │
└──────────────────────────┘   └──────────────────────────┘
                                  ▲
                                  │ TCP (un puerto por dron)
                                  ▼
                       Mission Planner / SITL multi-instancia
                            (SYSID_THISMAV únicos)
```

---

## 2. Nuevo árbol de paquetes

Solo se añaden ficheros nuevos; los existentes se modifican mínimamente.

```
ProyectoDrones_LOCAL/
├── ...
├── modelos/
│   ├── waypoint.py           (existente)
│   ├── drone.py              ★ NUEVO  – DTO de dron, batería, perfil
│   ├── assignment.py         ★ NUEVO  – Pedido↔Dron + ruta + ETA
│   └── flight_plan.py        ★ NUEVO  – Plan completo (varios assignments)
│
├── negocio/
│   ├── db_manager.py         (modificado: + tablas drones, assignments)
│   ├── fleet_repository.py   ★ NUEVO  – CRUD drones
│   └── ...
│
├── servicios/
│   ├── drone_service.py      (modificado: drone_id en señales)
│   ├── swarm_service.py      ★ NUEVO  – orquestador global
│   ├── planner_service.py    ★ NUEVO  – wrapper OR-Tools (CVRP)
│   ├── energy_model.py       ★ NUEVO  – consumo lineal
│   ├── airspace_manager.py   ★ NUEVO  – slots de altitud + escalonado
│   └── executor_service.py   ★ NUEVO  – ejecuta un assignment en un dron
│
├── widgets/
│   └── fleet_panel.py        (modificado: N tarjetas + estado por dron)
│
├── docs/
│   └── swarm/                (esta carpeta)
│
└── config/
    └── fleet.yaml            ★ NUEVO  – definición declarativa de la flota
```

---

## 3. Modelo de dominio

### 3.1 `modelos/drone.py`

```python
from dataclasses import dataclass, field
from typing import Literal

DroneState = Literal[
    "idle",          # en parking, listo
    "charging",      # batería baja, recargando
    "armed",         # armado, esperando
    "taking_off",
    "in_transit",    # camino al cliente
    "delivering",    # aterrizando/entregando en cliente
    "returning",     # de vuelta al parking
    "landing",
    "error",
    "offline",
]

@dataclass
class DroneSpec:
    """Especificación estática del dron."""
    drone_id: str                   # "Dron-1", "Dron-2", ...
    sysid: int                      # MAVLink SYSID_THISMAV (1..255)
    connection: str                 # "tcp:127.0.0.1:5760"
    max_payload_kg: float           # capacidad de carga
    battery_capacity_wh: float      # capacidad nominal
    cruise_speed_mps: float         # crucero típico
    base_consumption_w: float       # hover sin carga
    payload_consumption_w_per_kg: float
    home_parking_name: str          # parking físico de origen

@dataclass
class DroneRuntime:
    """Estado mutable en tiempo real."""
    state: DroneState = "idle"
    battery_wh: float = 0.0         # carga actual estimada
    battery_pct: float = 0.0        # 0..100
    lat: float = 0.0
    lon: float = 0.0
    alt: float = 0.0
    heading_deg: float = 0.0
    cruise_alt_slot: float | None = None  # asignado por Airspace
    current_assignment_id: int | None = None

@dataclass
class Drone:
    spec: DroneSpec
    runtime: DroneRuntime = field(default_factory=DroneRuntime)

    def can_carry(self, weight_kg: float) -> bool:
        return weight_kg <= self.spec.max_payload_kg
```

### 3.2 `modelos/assignment.py`

```python
@dataclass
class Assignment:
    """Una entrega = 1 dron, 1 pedido (o varios en cluster futuro)."""
    assignment_id: int
    drone_id: str
    order_id: int
    profile_name: str        # del route_profiles.json
    route_name: str
    cruise_alt_m: float      # slot asignado por Airspace
    takeoff_offset_s: float  # escalonado respecto al inicio del lote
    estimated_distance_km: float
    estimated_duration_s: float
    estimated_energy_wh: float
    status: str = "planned"  # planned|executing|done|aborted
```

### 3.3 `modelos/flight_plan.py`

```python
@dataclass
class FlightPlan:
    """Plan completo emitido por el Planner en un ciclo."""
    plan_id: int
    created_at: str          # ISO timestamp
    assignments: list[Assignment]
    unassigned_orders: list[int]    # pedidos que no caben hoy
    solver_objective: float         # coste total (s o Wh, según métrica)
```

---

## 4. Capa de persistencia

### 4.1 Nuevas tablas en `operations.db`

```sql
CREATE TABLE IF NOT EXISTS drones (
    drone_id TEXT PRIMARY KEY,
    sysid INTEGER NOT NULL UNIQUE,
    connection TEXT NOT NULL,
    max_payload_kg REAL NOT NULL,
    battery_capacity_wh REAL NOT NULL,
    cruise_speed_mps REAL NOT NULL,
    base_consumption_w REAL NOT NULL,
    payload_consumption_w_per_kg REAL NOT NULL,
    home_parking_name TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS drone_states (
    drone_id TEXT PRIMARY KEY,
    state TEXT NOT NULL,
    battery_pct REAL,
    battery_wh  REAL,
    lat REAL, lon REAL, alt REAL,
    cruise_alt_slot REAL,
    current_assignment_id INTEGER,
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (drone_id) REFERENCES drones(drone_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS flight_plans (
    plan_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    solver_objective REAL,
    unassigned_orders TEXT     -- JSON array
);

CREATE TABLE IF NOT EXISTS assignments (
    assignment_id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id INTEGER NOT NULL,
    drone_id TEXT NOT NULL,
    order_id INTEGER NOT NULL,
    profile_name TEXT NOT NULL,
    route_name TEXT NOT NULL,
    cruise_alt_m REAL NOT NULL,
    takeoff_offset_s REAL NOT NULL,
    estimated_distance_km REAL,
    estimated_duration_s REAL,
    estimated_energy_wh REAL,
    status TEXT NOT NULL DEFAULT 'planned',
    started_at TEXT,
    finished_at TEXT,
    FOREIGN KEY (plan_id) REFERENCES flight_plans(plan_id),
    FOREIGN KEY (drone_id) REFERENCES drones(drone_id),
    FOREIGN KEY (order_id) REFERENCES orders(id)
);

CREATE INDEX IF NOT EXISTS idx_assign_drone ON assignments(drone_id, status);
CREATE INDEX IF NOT EXISTS idx_assign_order ON assignments(order_id);
```

> El campo `orders.status` mantiene los mismos valores; **se añade**
> `asignado` entre `pendiente` y `en_reparto` para reflejar que el planner
> ya lo metió en un plan pero el dron aún no despegó.

### 4.2 `negocio/fleet_repository.py`

CRUD básico: `list_drones()`, `upsert_state(drone_id, runtime)`,
`save_plan(flight_plan)`, `update_assignment(assignment_id, status, ts)`.

### 4.3 Bootstrap declarativo — `config/fleet.yaml`

Para que el TFG sea reproducible la flota se declara en un YAML que
`SwarmService` carga al arrancar y mete en `drones` si están vacías:

```yaml
drones:
  - id: Dron-1
    sysid: 1
    connection: "tcp:127.0.0.1:5760"
    max_payload_kg: 2.0
    battery_capacity_wh: 222     # ~6S 5000mAh
    cruise_speed_mps: 7.0
    base_consumption_w: 180
    payload_consumption_w_per_kg: 22
    home_parking_name: "Central"
  - id: Dron-2
    sysid: 2
    connection: "tcp:127.0.0.1:5763"
    max_payload_kg: 1.0          # categoría pequeña
    battery_capacity_wh: 148
    cruise_speed_mps: 8.0
    base_consumption_w: 140
    payload_consumption_w_per_kg: 30
    home_parking_name: "Central"
  - id: Dron-3
    sysid: 3
    connection: "tcp:127.0.0.1:5766"
    max_payload_kg: 4.0          # categoría grande
    battery_capacity_wh: 360
    cruise_speed_mps: 6.0
    base_consumption_w: 280
    payload_consumption_w_per_kg: 18
    home_parking_name: "Central"
```

---

## 5. `servicios/energy_model.py`

Implementa el modelo lineal de la sección 3.1 de `02-RESEARCH.md`.

```python
def estimate_energy_wh(drone_spec, route_profile, weight_kg, distance_km,
                       altitude_gain_m) -> float:
    """
    E = (P_base + P_payload * w) * t  +  K_climb * altitude_gain * w_total
    donde t = distance_km*1000 / cruise_speed_mps
    Devuelve en Wh.
    """
```

Es **estático** y **puro** (sin estado), test unitario obligatorio.

---

## 6. `servicios/planner_service.py`

### Responsabilidad

Dado:
- estado actual de la flota (`list[Drone]`),
- lista de pedidos `pendiente` (`list[Order]`),
- catálogo de rutas (`route_profiles.json`),

devolver un `FlightPlan` que asigne pedidos a drones minimizando el **coste
total**, respetando capacidad, autonomía y disponibilidad.

### Algoritmo (v1)

**CVRP heterogéneo con restricciones de energía vía OR-Tools.**

1. Construir nodos: `0 = parking`, `1..M = pedidos`.
2. Para cada par (drone, pedido) calcular:
   - ruta candidata = la del `route_profiles.json` más cercana al cliente,
   - distancia_km = ruta candidata + tramo destino→cliente + retorno,
   - energía estimada (`energy_model.py`),
   - **viable** si `energy < battery_actual * 0.8` (margen 20 %) **y**
     `weight ≤ max_payload`.
3. Definir un `RoutingModel` de OR-Tools con:
   - `num_vehicles = len(drones_disponibles)`,
   - **dimensión "capacidad"** con `vehicle_capacities = [d.max_payload_kg]`,
   - **dimensión "energía"** con `vehicle_capacities = [d.battery_wh * 0.8]`,
   - matriz de coste = `tiempo_estimado_s` (ó energía, configurable).
4. Estrategia de primera solución: `PATH_CHEAPEST_ARC`;
   metaheurística: `GUIDED_LOCAL_SEARCH`, timeout 5 s.
5. Mapear la solución a `Assignment`s.
6. Pasar la lista de assignments al `AirspaceManager` para resolver
   conflictos de altitud / despegue.

### API

```python
class PlannerService:
    def __init__(self, route_service, energy_model, airspace_manager): ...

    def build_plan(
        self,
        drones: list[Drone],
        orders: list[Order],
        time_budget_s: float = 5.0,
    ) -> FlightPlan: ...

    # Para tests:
    def _build_cost_matrix(self, drones, orders) -> list[list[int]]: ...
    def _build_energy_matrix(self, drones, orders) -> list[list[int]]: ...
```

### Fallback

Si OR-Tools no encuentra solución (todos infeasibles), aplicar **Hungarian
sobre la submatriz drones-disponibles × pedidos** (solo 1 pedido por dron)
con `scipy.optimize.linear_sum_assignment`. Los pedidos sobrantes quedan
`unassigned_orders` y vuelven al siguiente ciclo.

---

## 7. `servicios/airspace_manager.py`

### Responsabilidades

- Mantener el conjunto de **slots de altitud libres** (p.ej. 25, 30, 35, 40 m).
- Asignar slot a cada `Assignment` saliente (round-robin, evitando colisiones).
- Liberar slot cuando el dron regresa al parking.
- Calcular **`takeoff_offset_s`** en función del tiempo estimado para
  liberar el HUB. Reglas:
  1. Dos drones del mismo parking no despegan en una ventana ≤ 10 s.
  2. Un dron no entra al HUB si otro está pasando por él (calcular ETAs).
  3. Garantizar separación temporal de al menos `TAKEOFF_GAP = 10 s`.

### API

```python
class AirspaceManager:
    DEFAULT_SLOTS_M = [25, 30, 35, 40, 45]
    TAKEOFF_GAP_S = 10

    def reserve(self, assignment: Assignment) -> Assignment:
        """Modifica in-place cruise_alt_m y takeoff_offset_s."""
    def release(self, assignment: Assignment) -> None: ...
    def in_flight(self) -> list[str]: ...
```

---

## 8. `servicios/executor_service.py`

Encapsula la ejecución de un único `Assignment` sobre un `DroneService`.
Toma la lógica que hoy vive en `DroneService.start_order_delivery()` y la
generaliza:

```python
class Executor(QObject):
    progress = Signal(str, str)      # drone_id, op_state
    finished = Signal(str, int)      # drone_id, assignment_id
    failed   = Signal(str, int, str)

    def __init__(self, drone_service, route_service, energy_model,
                 store, airspace_manager): ...

    @Slot(dict)
    def execute(self, assignment: Assignment): ...
        # 1. esperar takeoff_offset_s
        # 2. armar + takeoff a cruise_alt_m
        # 3. goto parking→hub→intermedios→destino→cliente
        # 4. land + sleep entrega
        # 5. re-arm + takeoff retorno
        # 6. goto cliente→destino→hub→parking
        # 7. land
        # 8. emitir finished, airspace.release(), update DB
```

Cada dron tiene **su propio `Executor`** corriendo en su hilo. El
`SwarmService` los crea y mata, nunca los reusa entre planes.

### Por qué un `Executor` aparte de `DroneService`

`DroneService` queda con un único cometido: **wrapper thread-safe del MAVLink**.
La orquestación (qué hacer ahora) sube al `Executor` / `SwarmService`. Esto
permite tests unitarios del flujo sin un autopiloto real.

---

## 9. `servicios/swarm_service.py`

Es el "director de orquesta". Es el único módulo que la `MainWindow` necesita
conocer del subsistema de enjambre.

### Responsabilidades

1. **Bootstrap**: cargar `fleet.yaml`, asegurar tablas en BD, crear un
   `DroneService` por dron, iniciar telemetría.
2. **Loop de planificación**: cada `PLANNING_PERIOD_S = 5 s` (configurable),
   leer pedidos `pendiente`, leer estado de flota, invocar
   `PlannerService.build_plan()`, persistir plan, lanzar `Executor`s.
3. **Ciclo de vida de los `Executor`s**: arrancarlos, recoger `finished` /
   `failed`, actualizar BD y notificar a la UI.
4. **API hacia la UI**:

```python
class SwarmService(QObject):
    plan_built = Signal(dict)         # FlightPlan serializado
    drone_state_changed = Signal(str, dict)
    assignment_progress = Signal(str, int, str)  # drone, assign, msg
    order_status_changed = Signal(int, str)

    def start(self) -> None: ...
    def stop(self) -> None: ...
    def pause_planning(self) -> None: ...
    def resume_planning(self) -> None: ...
    def force_replan(self) -> None: ...     # botón "Re-plan ahora"
    def cancel_assignment(self, assignment_id: int) -> None: ...
    def list_drones(self) -> list[Drone]: ...
```

---

## 10. Cambios en la UI

### 10.1 `cliente/main_window.py`

- Sustituir el **mono** `DroneService` por un **`SwarmService`**.
- Eliminar `DRONE_ID = "Dron-1"`.
- Reemplazar el polling de pedidos por suscripción a señales del swarm.
- Mantener el botón "Aceptar" como **override manual** (forzar replanificación).
- Añadir botón **"Auto"** que pausa/reanuda la planificación automática.

### 10.2 `widgets/fleet_panel.py`

- Ya soporta `add_drone(id)`, basta con llamar N veces.
- Cada `DroneCard` muestra: estado, batería %, pedido actual, ETA.
- Detalle: incluye `cruise_alt_slot`, distancia pendiente.

### 10.3 `widgets/map_widget.py`

- Cambiar `update_drone_position(lat, lon, hdg, spd)` por
  `update_drone_position(drone_id, lat, lon, hdg, spd)`.
- Mantener un *trail* por dron (color distinto).

---

## 11. Concurrencia y orden de eventos

- **Cada `DroneService` vive en su propio thread daemon** (igual que hoy).
- **`SwarmService.start()` corre un `QTimer`** cada `PLANNING_PERIOD_S`.
- **El Planner es síncrono y rápido** (≤5 s timeout); puede ejecutarse en el
  hilo de UI sin colgarla mucho, pero por seguridad se invoca dentro de un
  `QThreadPool`.
- **Los `Executor`s emiten señales Qt**; la `MainWindow` solo actualiza UI
  cuando llegan al hilo principal por la cola de eventos.

---

## 12. Modo SITL multi-instancia (entorno de pruebas)

Documentamos cómo arrancar la simulación con 3 drones:

```bash
# Terminal 1 — Dron 1 (SYSID=1, TCP:5760)
cd ~/ardupilot/ArduCopter && sim_vehicle.py -v ArduCopter --instance 0 \
    --sysid 1 --console --map -L Castelldefels

# Terminal 2 — Dron 2 (SYSID=2, TCP:5763)
sim_vehicle.py -v ArduCopter --instance 1 \
    --sysid 2 --console -L Castelldefels

# Terminal 3 — Dron 3 (SYSID=3, TCP:5766)
sim_vehicle.py -v ArduCopter --instance 2 \
    --sysid 3 --console -L Castelldefels
```

`fleet.yaml` enlaza esos puertos a Dron-1/2/3. La aplicación PySide6 conecta
los tres al arrancar.

---

## 13. Errores y robustez

| Fallo                          | Estrategia                                                          |
| ------------------------------ | ------------------------------------------------------------------- |
| Pérdida de conexión MAVLink    | `DroneService` marca estado `offline`, planner lo excluye del plan. |
| Energía estimada > umbral mid-flight | `Executor` aborta y manda RTL; replanifica al volver.         |
| Pedido sin destino válido      | Queda `unassigned`, alerta en UI.                                   |
| Conflicto en HUB no resuelto   | Airspace fuerza `takeoff_offset += 5s`, log de aviso.               |
| Solver infeasible              | Fallback Hungarian; los huérfanos esperan al siguiente ciclo.       |
| Crash de un `Executor`         | `SwarmService` lo captura, marca `assignment` como `aborted`.       |

---

## 14. Tests mínimos exigibles

- `tests/test_energy_model.py` — casos calibrados a mano.
- `tests/test_planner_service.py` — casos sintéticos: 2 drones, 3 pedidos;
  capacidad ajustada para forzar reparto; validar que la solución cumple
  capacidad/energía.
- `tests/test_airspace_manager.py` — slots únicos, escalonado correcto.
- `tests/test_fleet_repository.py` — persistencia y reapertura.

Sin tests de integración SITL automatizados (demasiado pesados).
