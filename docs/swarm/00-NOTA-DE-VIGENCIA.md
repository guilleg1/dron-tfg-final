# Nota de vigencia

Estos documentos se redactaron para una versión anterior del proyecto, en la
que el enjambre se orquestaba desde la aplicación de escritorio PySide6 y se
planificaba con OR-Tools (CVRP heterogéneo).

**Qué sigue vigente:** el estado del arte (`02-RESEARCH.md`), el modelo de
dominio, el diseño del gestor de espacio aéreo y la tabla de estrategias frente
a fallos de `03-ARCHITECTURE.md`, y el modo SITL multi-instancia.

**Qué ha cambiado:** el enjambre se orquesta desde la webapp, no desde el
escritorio, que queda archivado en `legacy/`. La asignación es **greedy**
(`core/greedy.py`), el mismo algoritmo validado experimentalmente en
`research/`, en lugar de OR-Tools.

El diseño vigente está descrito en la memoria del TFG y en `docs/swarm/`.
