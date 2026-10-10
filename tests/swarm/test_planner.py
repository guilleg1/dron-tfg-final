from airdrop.swarm.models import IDLE, IN_TRANSIT, OFFLINE, DroneRecord, DroneRuntime
from airdrop.swarm.planner import greedy_plan
from airdrop.swarm.scenario import OperationalScenario

ESCENARIO = OperationalScenario(
    name="Castelldefels", route_profile_name="Ruta1-Castelldefels",
    parking_lat=41.283720, parking_lon=1.985050,
)


def _record(drone_id, instance, category="medio"):
    return DroneRecord(
        drone_id=drone_id, sysid=instance + 1, instance=instance,
        category=category, connection="fake://",
        home_lat=41.28, home_lon=1.98,
    )


def _fleet(specs):
    """specs: lista de (estado, categoria, bateria_wh)."""
    records, runtimes = [], {}
    for index, (state, category, battery) in enumerate(specs):
        drone_id = f"Dron-{index + 1}"
        record = _record(drone_id, index, category)
        records.append(record)
        runtimes[drone_id] = DroneRuntime(
            drone_id=drone_id, state=state, battery_wh=battery,
            battery_capacity_wh=record.spec.battery_capacity_wh,
        )
    return records, runtimes


def _orders(count, weight=1.0, distance=0.5):
    return [{"id": n, "weight_kg": weight, "assigned_distance_km": distance}
            for n in range(1, count + 1)]


def test_one_order_per_free_drone():
    records, runtimes = _fleet([(IDLE, "medio", 222.0)] * 3)

    plan = greedy_plan(records, runtimes, _orders(3), ESCENARIO)

    assert len(plan) == 3
    assert len({a.drone_id for a in plan}) == 3, "un dron no puede llevar dos"


def test_a_drone_never_gets_two_orders_in_one_cycle():
    # greedy_assign puede asignar varios al mismo dron; el adaptador se queda
    # con el primero y devuelve el resto a la cola.
    records, runtimes = _fleet([(IDLE, "pesado", 360.0)])

    plan = greedy_plan(records, runtimes, _orders(5), ESCENARIO)

    assert len(plan) == 1


def test_busy_and_offline_drones_are_skipped():
    records, runtimes = _fleet([
        (IN_TRANSIT, "medio", 222.0),
        (IDLE, "medio", 222.0),
        (OFFLINE, "medio", 222.0),
        (IDLE, "medio", 222.0),
    ])

    plan = greedy_plan(records, runtimes, _orders(4), ESCENARIO)

    assert sorted(a.drone_id for a in plan) == ["Dron-2", "Dron-4"]


def test_an_order_nobody_can_carry_stays_unassigned():
    records, runtimes = _fleet([(IDLE, "medio", 222.0)] * 2)

    plan = greedy_plan(records, runtimes, _orders(1, weight=3.5), ESCENARIO)

    assert plan == []


def test_a_drone_without_enough_battery_is_not_chosen():
    records, runtimes = _fleet([(IDLE, "medio", 10.0)])

    plan = greedy_plan(records, runtimes, _orders(1, distance=5.0), ESCENARIO)

    assert plan == []


def test_it_prefers_the_cheaper_drone_not_the_first():
    # Un ligero y un pesado para un paquete de 0.5 kg: el pesado desperdicia
    # capacidad, y w3 (exceso de capacidad) es el peso dominante con 0.49.
    # Costes comprobados: ligero 0.2478, medio 0.3704, pesado 0.4320.
    records, runtimes = _fleet([
        (IDLE, "pesado", 360.0),
        (IDLE, "ligero", 148.0),
    ])

    plan = greedy_plan(records, runtimes, _orders(1, weight=0.5), ESCENARIO)

    assert [a.drone_id for a in plan] == ["Dron-2"]


def test_no_orders_means_no_plan():
    records, runtimes = _fleet([(IDLE, "medio", 222.0)] * 2)

    assert greedy_plan(records, runtimes, [], ESCENARIO) == []


def test_no_free_drones_means_no_plan():
    records, runtimes = _fleet([(IN_TRANSIT, "medio", 222.0), (OFFLINE, "medio", 222.0)])

    assert greedy_plan(records, runtimes, _orders(3), ESCENARIO) == []


# ── Seleccion de algoritmo ───────────────────────────────────────────────

def test_the_planner_accepts_both_assigners():
    # Los dos asignadores que valida research/ comparten firma en core, y el
    # panel deja cambiar de uno a otro en vivo.
    from airdrop.swarm.planner import ALGORITHMS, COST_MATRIX, GREEDY

    assert set(ALGORITHMS) == {GREEDY, COST_MATRIX}


def test_greedy_plan_is_an_alias_of_plan_assignments():
    # El nombre viejo sigue vivo porque es el que aparece en la memoria.
    from airdrop.swarm.planner import GREEDY, plan_assignments

    records, runtimes = _fleet([(IDLE, "medio", 222.0)] * 3)
    orders = _orders(3)

    assert (greedy_plan(records, runtimes, orders, ESCENARIO)
            == plan_assignments(records, runtimes, orders, ESCENARIO, GREEDY))


def test_the_cost_matrix_assigner_also_produces_a_valid_plan():
    from airdrop.swarm.planner import COST_MATRIX, plan_assignments

    records, runtimes = _fleet([(IDLE, "medio", 222.0)] * 3)

    plan = plan_assignments(records, runtimes, _orders(3), ESCENARIO, COST_MATRIX)

    assert len(plan) == 3
    assert len({a.drone_id for a in plan}) == 3, "un dron no puede llevar dos"
