# 04 · Roadmap

> 6 fases. Cada fase deja el sistema **arrancable y demostrable**; ninguna
> fase deja el repo a medias. Si te quedas sin tiempo en una fase, paras
> al final de la anterior y la entrega sigue siendo funcional.

| Fase | Tema                                       | Estim. | Bloquea a       |
| ---- | ------------------------------------------ | ------ | --------------- |
| 0    | Pre-flight: tooling, deps, branch          | 0.5 d  | Todo            |
| 1    | Modelo de dominio + persistencia           | 1 d    | 2, 3, 5         |
| 2    | Modelo de energía + Planner CVRP           | 2 d    | 3               |
| 3    | Executor + Airspace Manager                | 2 d    | 4, 5            |
| 4    | SwarmService + integración SITL multi-dron | 2 d    | 5               |
| 5    | UI multi-dron + portal                     | 1.5 d  | 6               |
| 6    | Validación, demo, memoria, vídeo           | 1 d    | —               |

Total estimado: **≈10 días de trabajo dedicado**. Ajusta a tu calendario.

---

## Fase 0 — Pre-flight (0.5 d)

**Meta:** dejar el entorno listo y un branch limpio.

1. `git init && git add -A && git commit -m "snapshot pre-swarm"` (estado actual).
2. Crear branch `feature/swarm-manager`.
3. Actualizar `requirements.txt` con `ortools`, `numpy`, `pyyaml`, `pytest`,
   `scipy`.
4. `pip install -r requirements.txt` y verificar que **`from ortools.constraint_solver import pywrapcp`** importa sin error en Windows.
5. Crear `tests/` con un `test_smoke.py` (`assert 1+1==2`) y configurar pytest.

**Criterio de aceptación:** `python -m pytest tests/` pasa.

---

## Fase 1 — Modelo de dominio + persistencia (1 d)

**Meta:** la BD ya conoce drones y assignments; el código tiene los DTOs.

### Pasos

1. Crear `modelos/drone.py` con `DroneSpec`, `DroneRuntime`, `Drone`.
2. Crear `modelos/assignment.py` y `modelos/flight_plan.py`.
3. Ampliar `negocio/db_manager.py`:
   - Añadir `SCHEMA_SQL` extra con tablas `drones`, `drone_states`,
     `flight_plans`, `assignments`.
   - Añadir migración idempotente (mismo patrón de `_ensure_columns`).
4. Crear `negocio/fleet_repository.py` con `list_drones`, `upsert_drone`,
   `upsert_state`, `save_plan`, `update_assignment_status`.
5. Crear `config/fleet.yaml` con 3 drones (ver `03-ARCHITECTURE.md §4.3`).
6. Crear `negocio/fleet_bootstrap.py` que carga `fleet.yaml` y rellena la
   tabla `drones` la primera vez.
7. Tests: `test_fleet_repository.py` (crear 3 drones, releerlos).

**Criterio de aceptación:**
- Tras arrancar la app, la tabla `drones` tiene 3 filas leídas desde YAML.
- Tests pasan.
- El mono-dron sigue funcionando exactamente como antes (no se ha
  cambiado nada del flujo aún).

---

## Fase 2 — Energía + Planner (2 d)

**Meta:** dado un estado de flota y unos pedidos, generar un `FlightPlan`
sin tocar todavía MAVLink.

### Pasos

1. Crear `servicios/energy_model.py` con `estimate_energy_wh()` y
   `estimate_duration_s()`. **Funciones puras**, sin estado.
2. Test `tests/test_energy_model.py` con 4-5 casos a mano calibrados.
3. Crear `servicios/planner_service.py`:
   - `__init__(route_service, energy_model)`.
   - `build_plan(drones, orders, time_budget_s=5)`.
   - Construcción de matriz coste/energía/capacidad.
   - Llamada a OR-Tools (`pywrapcp.RoutingModel`).
   - Mapeo solución → `Assignment`s.
   - Fallback Hungarian si solución vacía.
4. Test `tests/test_planner_service.py`:
   - 2 drones (cap 1 kg y cap 3 kg), 3 pedidos (0.5, 1.5, 2.5 kg).
   - Esperar que el de cap=3 coja el 2.5 kg sí o sí; el de cap=1 no.
5. **NO** conectar aún al UI ni al MAVLink. Solo unit-tests.

**Criterio de aceptación:**
- Tests pasan en <2 s.
- En un script manual (`python -m servicios.planner_service`) con datos
  reales del `route_profiles.json` se imprime un plan coherente.

---

## Fase 3 — Executor + AirspaceManager (2 d)

**Meta:** poder ejecutar 1 `Assignment` extraído de un `FlightPlan` en un
único dron contra SITL. Es el "saco" que sustituye a
`drone_service.start_order_delivery`.

### Pasos

1. Crear `servicios/airspace_manager.py` con `reserve()` / `release()`.
2. Test `tests/test_airspace_manager.py`: garantiza slots únicos y
   `takeoff_offset_s` creciente.
3. Crear `servicios/executor_service.py` con `Executor(QObject)` que
   reproduce **literalmente** el flujo actual de
   `DroneService.start_order_delivery` pero parametrizado por:
   - `drone_service` (1 sólo)
   - `assignment` (dict del DTO)
4. **Modificar `DroneService` mínimamente** para emitir señales con
   `drone_id` (parámetro de constructor).
5. Demo manual: con SITL en `:5760`, ejecutar un script
   `scripts/demo_phase3.py` que:
   - lee pedidos `pendiente` de la BD,
   - llama a `planner_service.build_plan()` con 1 dron,
   - coge el primer `Assignment`,
   - lanza un `Executor` y observa logs.

**Criterio de aceptación:**
- Un pedido se entrega end-to-end igual que antes pero **pasando por todas
  las capas nuevas** (planner + airspace + executor).
- Test de airspace pasa.

---

## Fase 4 — SwarmService + multi-SITL (2 d)

**Meta:** 3 drones simulados en paralelo entregando varios pedidos en un
único arranque de la aplicación.

### Pasos

1. Crear `servicios/swarm_service.py` con:
   - bootstrap de fleet,
   - `dict[str, DroneService]` con un `DroneService` por dron,
   - `QTimer` de planificación,
   - lifecycle de `Executor`s.
2. Cablear `SwarmService` desde `cliente/main_window.py`: reemplazar el único
   `DroneService` por `SwarmService`.
3. Cablear señales: `state_changed`, `progress`, `order_status_changed`.
4. Documentar en `docs/swarm/RUN_SITL.md` los comandos exactos para arrancar
   3 instancias SITL en local (Linux y WSL).
5. Probar con 2 drones primero (más fácil que 3) y luego 3.
6. **Cuello típico**: el reset del estado del dron entre vuelos.
   `Executor` debe esperar el `landed` event antes de devolver el dron a
   `idle` y liberar el slot.

**Criterio de aceptación:**
- Arrancas SITL ×3, lanzas la app, mandas 5 pedidos por el portal web,
  ves cómo 3 drones despegan en distintos slots de altitud, vuelven, y los
  pedidos quedan `entregado`.

---

## Fase 5 — UI multi-dron + portal (1.5 d)

**Meta:** la GUI es legible cuando vuelan varios drones a la vez.

### Pasos

1. `widgets/fleet_panel.py`: `add_drone(id)` por cada dron de la flota.
2. `widgets/drone_card.py`: añadir barra de batería y ETA del assignment
   activo.
3. `widgets/map_widget.py`: soporte de N marcadores y N trails (un color
   por dron).
4. `cliente/main_window.py`:
   - botón **"Auto / Manual"** (pausa/reanuda planning).
   - botón **"Re-plan ahora"**.
   - botón **"Cancelar assignment seleccionado"**.
5. Portal cliente: añadir campo opcional `priority` y mostrar estado del
   pedido en tiempo real (ya hay un endpoint `/api/orders`).

**Criterio de aceptación:**
- Demo visual con 3 drones moviéndose en el mapa al mismo tiempo.

---

## Fase 6 — Validación, memoria, vídeo (1 d)

**Meta:** evidencias y entregables.

### Pasos

1. **Escenario de validación**:
   - 3 drones (caps 1/2/4 kg, autonomías distintas).
   - 6 pedidos (pesos 0.5/1.0/1.5/2.0/3.0/3.5 kg).
   - Capturar logs del planner (qué dron coge qué).
2. **Métricas a reportar en la memoria**:
   - makespan total,
   - utilización media de la flota,
   - batería consumida vs. estimada (acierto del modelo de energía),
   - tiempo de cómputo del planner.
3. **Capturas**: panel multi-dron + Mission Planner con N vehículos.
4. **Vídeo demo**: 90–120 s, narrado, mostrando el escenario.
5. Pasar `02-RESEARCH.md` al capítulo "Marco teórico" de la memoria con las
   citas correctas.
6. Tag git: `git tag v2.0-swarm`.

**Criterio de aceptación:**
- Demo grabada, métricas en una tabla, memoria con bibliografía cuadrada.

---

## Riesgos y mitigaciones

| Riesgo                                              | Mitigación                                                              |
| --------------------------------------------------- | ----------------------------------------------------------------------- |
| OR-Tools no instala en tu Windows                   | Plan B: solo Hungarian. Documentado como degradación aceptable.         |
| SITL multi-instancia no arranca en tu máquina       | Usar máquina virtual / WSL2. Comandos en `RUN_SITL.md`.                 |
| dronLink tiene bugs con varias conexiones a la vez  | Cada `Dron()` en su thread; si peta, fallback a pymavlink directo.      |
| Te quedas sin tiempo en Fase 4                      | Defendible con 2 drones (queda como "demostración de escalabilidad").   |
| El modelo de energía es muy inexacto                | Es estimación. Defendible si reportas error y citas Zhang 2021.         |

---

## Definición de "Done" para el TFG

La entrega "Swarm Manager" está **terminada** cuando:

1. Existe un branch `feature/swarm-manager` mergeable a main.
2. `pytest` pasa todos los tests unitarios.
3. La aplicación arranca con `python main.py` con la flota cargada de YAML.
4. Demo SITL muestra ≥2 drones entregando ≥3 pedidos en paralelo.
5. Memoria del TFG incluye el marco teórico de `02-RESEARCH.md`.
6. Existe un vídeo demo.
