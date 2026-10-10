# 05 · Lista granular de tareas

> Cada bullet es **una tarea** ejecutable, suficientemente atómica como para
> alimentarla a `TaskCreate` o trabajarla en una sesión. Están agrupadas por
> la fase de `04-ROADMAP.md`. Marca `[x]` al cerrar.

Convención: **(F)** = fichero(s) tocados. **(✓)** = criterio de verificación.

---

## Fase 0 — Pre-flight

- [ ] **T0.1** Hacer commit de snapshot inicial.
      (F) repo entero.
      (✓) `git log` muestra el commit.

- [ ] **T0.2** Crear branch `feature/swarm-manager`.
      (✓) `git status` indica branch correcto.

- [ ] **T0.3** Actualizar `requirements.txt`:
      añadir `ortools>=9.10`, `numpy>=1.26`, `pyyaml>=6.0`, `scipy>=1.11`,
      `pytest>=8.0`.
      (F) `requirements.txt`.
      (✓) `pip install -r requirements.txt` termina ok.

- [ ] **T0.4** Verificar instalación OR-Tools:
      script `python -c "from ortools.constraint_solver import pywrapcp; print('ok')"`.
      (✓) imprime `ok` sin trazas.

- [ ] **T0.5** Crear directorio `tests/` con `__init__.py` y
      `test_smoke.py` (`assert 1+1==2`).
      (F) `tests/test_smoke.py`.
      (✓) `pytest tests/` pasa.

---

## Fase 1 — Modelo de dominio + persistencia

- [ ] **T1.1** Crear `modelos/drone.py` con `DroneSpec`, `DroneRuntime`,
      `Drone` (dataclasses, sin lógica).
      (F) `modelos/drone.py`.

- [ ] **T1.2** Crear `modelos/assignment.py` con `Assignment`.
      (F) `modelos/assignment.py`.

- [ ] **T1.3** Crear `modelos/flight_plan.py` con `FlightPlan`.
      (F) `modelos/flight_plan.py`.

- [ ] **T1.4** Ampliar `negocio/db_manager.py`:
      añadir bloque SQL para `drones`, `drone_states`, `flight_plans`,
      `assignments` y la migración idempotente.
      (F) `negocio/db_manager.py`.
      (✓) tras correr la app, las tablas existen en `operations.db`.

- [ ] **T1.5** Añadir estado `asignado` al `CHECK` de `orders.status` (o
      relajar el CHECK y validar en código si SQLite no permite ALTER).
      (F) `negocio/db_manager.py`.

- [ ] **T1.6** Crear `negocio/fleet_repository.py`:
      `list_drones`, `upsert_drone`, `upsert_state`, `save_plan`,
      `update_assignment_status`, `list_active_assignments`.
      (F) `negocio/fleet_repository.py`.

- [ ] **T1.7** Crear `config/fleet.yaml` con 3 drones (specs de
      `03-ARCHITECTURE.md §4.3`).
      (F) `config/fleet.yaml`.

- [ ] **T1.8** Crear `negocio/fleet_bootstrap.py` que carga `fleet.yaml` y
      hace `upsert_drone` para cada uno.
      (F) `negocio/fleet_bootstrap.py`.

- [ ] **T1.9** Llamar al bootstrap desde `cliente/main_window.py:__init__`
      (antes de crear `DroneService`s).
      (F) `cliente/main_window.py`.
      (✓) primer arranque rellena la tabla.

- [ ] **T1.10** Tests `tests/test_fleet_repository.py`: alta de drones,
      lectura, actualización de estado.
      (✓) `pytest tests/test_fleet_repository.py` pasa.

---

## Fase 2 — Energía + Planner

- [ ] **T2.1** Crear `servicios/energy_model.py` con:
      - `estimate_duration_s(distance_km, cruise_speed_mps)`,
      - `estimate_energy_wh(drone_spec, distance_km, weight_kg,
        altitude_gain_m)`.
      (F) `servicios/energy_model.py`.

- [ ] **T2.2** Tests `tests/test_energy_model.py` con casos numéricos a mano
      (al menos 3).
      (✓) `pytest` pasa.

- [ ] **T2.3** Crear `servicios/planner_service.py` (esqueleto):
      `__init__`, `build_plan(drones, orders, time_budget_s)`,
      `_build_route_for(drone, order)`,
      `_build_distance_matrix`, `_build_energy_matrix`.
      (F) `servicios/planner_service.py`.

- [ ] **T2.4** Implementar la **construcción del modelo OR-Tools**:
      - `RoutingIndexManager(n_nodes, n_vehicles, depot=0)`,
      - `RoutingModel(manager)`,
      - callback de coste = tiempo estimado,
      - dimensión `Capacity` (peso),
      - dimensión `Energy` (Wh, con `vehicle_capacities` por dron),
      - `SetFixedCostOfVehicle` para favorecer drones grandes ocupados,
      - estrategia `PATH_CHEAPEST_ARC` + `GUIDED_LOCAL_SEARCH`,
      - `time_limit` 5 s.
      (F) `servicios/planner_service.py`.

- [ ] **T2.5** Implementar el **mapeo solución → list[Assignment]**.

- [ ] **T2.6** Implementar **fallback Hungarian** con
      `scipy.optimize.linear_sum_assignment` si OR-Tools devuelve solución
      vacía o todos los nodos infeasibles.
      (F) `servicios/planner_service.py`.

- [ ] **T2.7** Tests `tests/test_planner_service.py`:
      - **caso A**: 1 dron (cap 1 kg), 1 pedido 0.5 kg → asignado.
      - **caso B**: 1 dron (cap 1 kg), 1 pedido 2.0 kg → unassigned.
      - **caso C**: 2 drones (1, 3 kg), 3 pedidos (0.5, 1.5, 2.5) → cada
        uno coge los que puede.
      - **caso D**: 2 drones, batería insuficiente en uno → solo el otro.
      (✓) pasa.

- [ ] **T2.8** Script CLI de prueba manual:
      `scripts/run_planner_smoke.py` que lee la BD y `fleet.yaml` reales e
      imprime el plan.
      (✓) corre sin errores y muestra asignaciones plausibles.

---

## Fase 3 — Executor + Airspace

- [ ] **T3.1** Crear `servicios/airspace_manager.py` con
      `AirspaceManager.reserve(assignment)` y `.release(assignment)`.
      (F) `servicios/airspace_manager.py`.

- [ ] **T3.2** Tests `tests/test_airspace_manager.py`:
      - 3 reservas seguidas → slots 25, 30, 35.
      - reserva tras release → reutiliza slot libre más bajo.
      - escalonado: `takeoff_offset_s` creciente en ≥ `TAKEOFF_GAP_S`.
      (✓) pasa.

- [ ] **T3.3** Refactor `servicios/drone_service.py`:
      - aceptar `drone_id` en `__init__`,
      - emitir todas las señales con `drone_id` como primer parámetro:
        `connected(str)`, `state_changed(str, str)`, `route_status(str,str,str)`,
        `error_occurred(str, str)`, `telemetry_updated(str, dict)`.
      (F) `servicios/drone_service.py`.
      (✓) `python main.py` sigue funcionando (mono-dron) ⚠ adaptar
      `main_window.py` para consumir los nuevos parámetros.

- [ ] **T3.4** Crear `servicios/executor_service.py` con clase `Executor`:
      - hereda `QObject`,
      - señal `progress(drone_id, assignment_id, msg)`,
      - señal `finished(drone_id, assignment_id)`,
      - señal `failed(drone_id, assignment_id, err)`,
      - `execute(assignment)` reproduce el flujo de
        `DroneService.start_order_delivery` parametrizado.
      (F) `servicios/executor_service.py`.

- [ ] **T3.5** Eliminar / marcar deprecated
      `DroneService.start_order_delivery` (lo hace ahora el `Executor`).

- [ ] **T3.6** Script `scripts/demo_phase3.py`:
      - bootstrap fleet,
      - lee pedidos `pendiente`,
      - llama `planner_service.build_plan` con 1 dron,
      - lanza `Executor` con el primer assignment.
      (✓) corre contra SITL y entrega el pedido.

---

## Fase 4 — SwarmService + multi-SITL

- [ ] **T4.1** Crear `servicios/swarm_service.py` con:
      - constructor toma `route_service`, `planner_service`,
        `airspace_manager`, `db_store`, `fleet_repo`.
      - `start()`/`stop()`,
      - `dict[str, DroneService]` con un `DroneService` por dron,
      - timer de planificación cada `PLANNING_PERIOD_S=5`,
      - `force_replan()`, `pause_planning()`, `resume_planning()`,
      - señales: `plan_built`, `drone_state_changed`,
        `assignment_progress`, `order_status_changed`.

- [ ] **T4.2** En `cliente/main_window.py`: sustituir el `DroneService` único
      por un `SwarmService` y borrar `DRONE_ID = "Dron-1"`.
      (F) `cliente/main_window.py`.

- [ ] **T4.3** Cablear señales `SwarmService` ↔ `FleetPanel` para
      actualizar las cards. Ojo a `update_drone_position` ahora con
      `drone_id`.

- [ ] **T4.4** Documentar arranque multi-SITL en
      `docs/swarm/RUN_SITL.md` (comandos Linux/WSL).
      (F) `docs/swarm/RUN_SITL.md`.

- [ ] **T4.5** Prueba con 2 drones reales contra SITL:
      - lanzar 2 instancias,
      - lanzar app,
      - meter 3 pedidos por el portal,
      - verificar reparto correcto.

- [ ] **T4.6** Prueba con 3 drones — mismo escenario, más concurrencia.

- [ ] **T4.7** Manejar caída de un dron: matar una instancia SITL en mitad
      del vuelo y observar que el `DroneService` reporta `offline` y el
      planner lo excluye del siguiente ciclo.

---

## Fase 5 — UI multi-dron

- [ ] **T5.1** `widgets/drone_card.py`: añadir barra de batería (QProgressBar)
      y label de ETA.

- [ ] **T5.2** `widgets/map_widget.py`: aceptar `drone_id` en
      `update_drone_position` y mantener un marcador / color por dron.

- [ ] **T5.3** `widgets/fleet_panel.py`: que `_count_lbl` se actualice y la
      selección funcione con múltiples drones.

- [ ] **T5.4** Toolbar de `MainWindow`: botones **Auto/Manual**,
      **Re-plan ahora**.

- [ ] **T5.5** Portal cliente: mostrar estado del pedido (consulta
      `/api/orders?client_id=X`) con polling 2 s.

- [ ] **T5.6** Pulir leyenda de colores de drones en el mapa (lista al pie).

---

## Fase 6 — Validación + memoria + vídeo

- [ ] **T6.1** Definir escenario de validación reproducible
      (3 drones / 6 pedidos) en `docs/swarm/SCENARIO_DEMO.md`.

- [ ] **T6.2** Instrumentar logging:
      `swarm_service` escribe `logs/swarm.log` con cada plan y resultado.

- [ ] **T6.3** Ejecutar escenario, capturar pantallas y logs.

- [ ] **T6.4** Tabla de métricas:
      - makespan,
      - utilización por dron,
      - error de estimación de energía,
      - tiempo de cómputo del planner.

- [ ] **T6.5** Grabar vídeo demo de 90–120 s con voz en off.

- [ ] **T6.6** Pasar bibliografía de `02-RESEARCH.md` al capítulo de marco
      teórico del documento del TFG.

- [ ] **T6.7** `git tag v2.0-swarm` y entregar.

---

## Tareas transversales (no asociadas a fase)

- [ ] **TX.1** README del repo: actualizar con sección "Swarm Manager".
- [ ] **TX.2** Limpieza: borrar `business_manager_BACKUP.py` y
      `DesktopLAN_BACKUP.py` si tu tutor lo aprueba.
- [ ] **TX.3** Tipo-hinting en módulos nuevos (`from __future__ import
      annotations`).
- [ ] **TX.4** Pre-commit / black / ruff si tu workflow lo soporta
      (opcional).
