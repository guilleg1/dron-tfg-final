# `docs/swarm/` — Planificación de la entrega «Swarm Manager»

Esta carpeta contiene el plan completo para evolucionar el proyecto
`ProyectoDrones_LOCAL` desde un sistema **mono-dron** a un **gestor autónomo
de enjambre** capaz de repartir pedidos contra Mission Planner / SITL.

## Cómo leer estos documentos

Lee en orden:

1. [`00-OVERVIEW.md`](./00-OVERVIEW.md) — Visión, alcance, decisiones macro.
2. [`01-CURRENT-STATE.md`](./01-CURRENT-STATE.md) — Estado real del repo.
3. [`02-RESEARCH.md`](./02-RESEARCH.md) — Estado del arte y referencias.
4. [`03-ARCHITECTURE.md`](./03-ARCHITECTURE.md) — Diseño técnico propuesto.
5. [`04-ROADMAP.md`](./04-ROADMAP.md) — Plan por fases con criterios.
6. [`05-TASKS.md`](./05-TASKS.md) — Tareas atómicas listas para `TaskCreate`.

## TL;DR

- **Problema**: pasar de 1 dron a **N drones heterogéneos** repartiendo
  pedidos con peso, batería y rutas pre-aprobadas.
- **Solución**: capa nueva `SwarmService` + `PlannerService` (CVRP
  heterogéneo con restricción de energía vía Google **OR-Tools**) +
  `Executor` por dron + `AirspaceManager` para deconflicción por altitud.
- **Stack añadido**: `ortools`, `numpy`, `pyyaml`, `scipy`, `pytest`.
- **Tiempo estimado**: ~10 días de trabajo.
- **Entrega mínima defendible**: 2 drones simultáneos entregando ≥3 pedidos
  con planificación automática y deconflicción demostrada.
