"""Asignación de pedidos a drones.

Envuelve ``core.greedy``, el asignador voraz que ``research/`` valida contra
Jonker-Volgenant sobre 200 escenarios. El algoritmo que despacha drones reales
es literalmente el mismo que se validó experimentalmente; aquí solo se traduce
entre el modelo del enjambre y el del núcleo.

El coste de cada pareja dron-pedido es la energía del viaje (``core.cost``).
"""

from __future__ import annotations

from dataclasses import dataclass

from core.greedy import DroneState, Order, greedy_assign

# Los dos asignadores que valida research/, con la misma firma
# ``(drones, orders) -> AssignmentResult``. Poder cambiar de uno a
# otro en vivo es lo que permite enseñar la diferencia sobre el enjambre real
# y no solo en las gráficas del experimento.
GREEDY = "greedy"
COST_MATRIX = "cost_matrix"
ALGORITHMS = (GREEDY, COST_MATRIX)


def _assigner(algorithm):
    if algorithm == COST_MATRIX:
        # Import perezoso: cost_matrix arrastra scipy, que no hace falta para
        # operar con el voraz.
        from core.cost_matrix import cost_matrix_assign  # noqa: PLC0415
        return cost_matrix_assign
    return greedy_assign


@dataclass(frozen=True)
class Assignment:
    """Un pedido asignado a un dron."""

    drone_id: str
    order: dict


def plan_assignments(records, runtimes, orders, scenario,
                     algorithm: str = GREEDY) -> list[Assignment]:
    """Asigna pedidos pendientes a los drones libres.

    Parameters
    ----------
    records : list[DroneRecord]
        Definición de la flota.
    runtimes : dict[str, DroneRuntime]
        Estado vivo indexado por ``drone_id``.
    orders : list[dict]
        Pedidos pendientes, en orden FIFO.
    scenario : OperationalScenario
        Escenario activo. No interviene en el coste; se mantiene en la firma
        para que el servicio no tenga que distinguir entre asignadores.
    algorithm : str
        ``greedy`` (voraz) o ``cost_matrix`` (óptimo global por
        Jonker-Volgenant). Ambos exponen la misma firma en ``core``.

    Returns
    -------
    list[Assignment]
        Como mucho un pedido por dron. Los sobrantes se quedan en la cola y
        los recoge el siguiente ciclo de planificación.
    """
    asignar = _assigner(algorithm)
    libres = [r for r in records
              if r.drone_id in runtimes and runtimes[r.drone_id].is_available]
    if not libres or not orders:
        return []

    por_id = {o["id"]: o for o in orders}

    # greedy_assign asume que un dron puede encadenar viajes: recorre los
    # pedidos y le da todos al más barato, descontando batería pero sin
    # marcarlo ocupado. En vivo un dron lleva un paquete y se va, así que hay
    # que retirarlo de la puja y volver a resolver. Quedarse simplemente con
    # su primera asignación desperdiciaría el resto de la flota.
    plan: list[Assignment] = []
    disponibles = list(libres)
    pendientes = list(orders)

    while disponibles and pendientes:
        estados = [
            DroneState(spec=r.spec, battery_wh=runtimes[r.drone_id].battery_wh)
            for r in disponibles
        ]
        pedidos = [
            Order(
                order_id=o["id"],
                weight_kg=float(o.get("weight_kg") or 0.0),
                distance_km=float(o.get("assigned_distance_km") or 0.0),
                destination_name=str(o.get("assigned_destination_name") or ""),
            )
            for o in pendientes
        ]
        resultado = asignar(estados, pedidos)
        if not resultado.assignments:
            break

        elegida = resultado.assignments[0]
        plan.append(Assignment(drone_id=elegida.drone_id,
                               order=por_id[elegida.order_id]))
        disponibles = [r for r in disponibles if r.drone_id != elegida.drone_id]
        pendientes = [o for o in pendientes if o["id"] != elegida.order_id]

    return plan


def greedy_plan(records, runtimes, orders, scenario) -> list[Assignment]:
    """Alias histórico: planifica con el voraz.

    Se conserva porque es el nombre con el que entró en la memoria y con el
    que lo llaman los tests.
    """
    return plan_assignments(records, runtimes, orders, scenario, GREEDY)
