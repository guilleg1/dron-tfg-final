# 00 · Visión general — Gestión autónoma de enjambre de drones

> **TFG · ProyectoDrones_LOCAL · Entrega «Swarm Manager»**
> Versión 1.0 — documento maestro

---

## 1. Resumen ejecutivo

El proyecto actual (`Desktop Drone Control v2.0`) permite operar **un único dron**
contra un **Mission Planner / SITL** mediante `dronLink`, asignando a cada
pedido la ruta predefinida más cercana al cliente.

La **siguiente entrega** debe escalar el sistema a **un enjambre heterogéneo de
drones** que:

1. Parten todos de un **parking** (hub logístico).
2. Disponen de **rutas pre-aprobadas** (corredores aéreos seguros entre parking,
   *hub* y destinos, ya cargadas en `route_profiles.json`).
3. Cada dron tiene **batería/autonomía**, **categoría de carga** (payload máx.) y
   estado (idle, cargando, en vuelo, retornando…).
4. Cada pedido lleva un **peso** y una **dirección de cliente** que cae cerca de
   alguno de los destinos predefinidos.
5. Un **Swarm Manager** decide, de forma **autónoma y óptima**, qué dron coge
   qué pedido(s), en qué orden y por qué corredor, evitando conflictos y
   maximizando la utilización de la flota.

El objetivo no es resolver un *Vehicle Routing Problem* académico abstracto
sino entregar un **prototipo demostrable en SITL** que un tribunal de TFG pueda
ver funcionando: pedidos entrando por el portal web → el planificador asigna
flota → varios drones despegan en paralelo, entregan, vuelven al parking y
recargan/se hacen disponibles.

---

## 2. Alcance

### Dentro del alcance

- **Modelado de la flota**: dron con id, autonomía (Wh o min), payload máx, estado y
  posición.
- **Algoritmo de asignación** óptimo (o casi-óptimo) que considera:
  - peso del pedido vs. capacidad del dron,
  - autonomía restante vs. distancia total del trayecto (ida + retorno),
  - balanceo de carga entre drones,
  - tiempo total de entrega del lote (*makespan*).
- **Orquestador de ejecución**: traducción del plan a comandos MAVLink
  concurrentes (un hilo por dron, o instancias SITL independientes).
- **Deconflicción básica**: separación por **slot de altitud** y secuenciación
  de despegues para evitar colisiones en el HUB.
- **Visualización en el Mission Planner desktop**: panel de flota multi-dron,
  mapa con todos los marcadores y trayectorias activas.
- **Validación**: simulación con N drones (mínimo 3) en SITL contra el Mission
  Planner real, con M pedidos (mínimo 5) llegando a través del portal cliente.

### Fuera del alcance

- DAA reactivo (sensor-based detect-and-avoid) — solo deconflicción estratégica.
- Carga inalámbrica o estaciones de recarga distribuidas — solo se simula
  tiempo de recarga.
- Aprendizaje por refuerzo, RL, redes neuronales — usaremos optimización
  clásica (CVRP / asignación + metaheurística) que es defendible y reproducible.
- Hardware real — toda la entrega es SITL.

---

## 3. Estructura de esta carpeta

| Documento                              | Propósito                                                      |
| -------------------------------------- | -------------------------------------------------------------- |
| `00-OVERVIEW.md` (este)                | Visión, alcance, índice.                                       |
| `01-CURRENT-STATE.md`                  | Auditoría exhaustiva del código y datos actuales.              |
| `02-RESEARCH.md`                       | Estado del arte con referencias académicas y técnicas.         |
| `03-ARCHITECTURE.md`                   | Diseño técnico del módulo Swarm Manager (capas, módulos, API). |
| `04-ROADMAP.md`                        | Plan por fases con hitos y criterios de aceptación.            |
| `05-TASKS.md`                          | Lista granular de tareas ejecutables (input para `TaskCreate`).|

---

## 4. Decisiones de alto nivel ya tomadas

Estas decisiones marcan el resto del diseño. Si el tutor las cambia, hay que
revisar `03-ARCHITECTURE.md` y `04-ROADMAP.md`.

1. **Algoritmo principal**: *Capacitated VRP heterogéneo con restricción de
   energía* resuelto con **Google OR-Tools** + post-mejora por metaheurística
   ligera. Alternativa decentralizada documentada (CBBA) pero no implementada
   en la primera iteración.
2. **Stack tecnológico**: se mantiene PySide6 + dronLink + SQLite. Se añade
   `ortools` como dependencia.
3. **Conexión MAVLink**: cada dron simulado expone un puerto TCP distinto
   (5760, 5763, 5766…) y el Swarm Manager mantiene un `DroneService` por
   instancia.
4. **Deconflicción**: por **capas de altitud** asignadas dinámicamente a cada
   dron en vuelo + retraso de despegue (escalonado) en el HUB.
5. **Persistencia**: ampliación del schema SQLite con tablas `drones`,
   `drone_states`, `assignments` y `flight_segments`.

---

## 5. Cómo usar estos documentos

1. Lee `01-CURRENT-STATE.md` para entender qué tienes ahora mismo.
2. Lee `02-RESEARCH.md` para tener munición teórica para la memoria del TFG.
3. Lee `03-ARCHITECTURE.md` para entender qué vas a construir.
4. Sigue `04-ROADMAP.md` fase a fase. Cada fase deja el sistema funcionando
   end-to-end (no hay fases que rompan el repo).
5. Usa `05-TASKS.md` como check-list operativa. Cada bullet es un `TaskCreate`.
