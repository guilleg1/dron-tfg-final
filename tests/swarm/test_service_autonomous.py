import json
import threading
import time

import pytest
from sqlalchemy import create_engine

from airdrop.swarm.fake import FakeDroneLink
from airdrop.swarm.repository import FleetRepository
from airdrop.swarm.scenario import OperationalScenario
from airdrop.swarm.service import SwarmService

FLEET_DOC = {
    "drones": [
        {"drone_id": "Dron-1", "sysid": 1, "instance": 0, "category": "medio"},
        {"drone_id": "Dron-2", "sysid": 2, "instance": 1, "category": "medio"},
    ],
}

ESCENARIO = OperationalScenario(
    name="Test", route_profile_name="Ruta1-Castelldefels",
    parking_lat=41.283720, parking_lon=1.985050,
    delivery_pause_s=0.0, takeoff_gap_s=0.0, delivery_stagger_s=0.0,
)

MISSION = {
    "speed": 7.0, "takeOffAlt": 8.0,
    "waypoints": [
        {"lat": 41.283720, "lon": 1.985050, "alt": 0.0},
        {"lat": 41.282946, "lon": 1.986080, "alt": 20.0},
        {"lat": 41.284412, "lon": 1.978221, "alt": 15.0},
    ],
}


class FakeOrders:
    def __init__(self, orders):
        self.orders = {o["id"]: dict(o) for o in orders}

    def list_pending(self):
        return [o for o in self.orders.values() if o["status"] == "pendiente"]

    def get(self, order_id):
        return self.orders.get(order_id)

    def update(self, order_id, status=None, operational_state=None, assigned_drone_id=None):
        order = self.orders[order_id]
        if status is not None:
            order["status"] = status
        if operational_state is not None:
            order["operational_state"] = operational_state
        if assigned_drone_id is not None:
            order["assigned_drone_id"] = assigned_drone_id


def _order(order_id, weight=1.0):
    return {
        "id": order_id, "weight_kg": weight, "status": "pendiente",
        "client_latitude": 41.2845, "client_longitude": 1.9780,
        "assigned_profile_name": "Ruta1-Castelldefels",
        "assigned_route_name": "Ruta-Castillo",
        "assigned_distance_km": 0.8,
    }


@pytest.fixture()
def service(tmp_path):
    fleet_file = tmp_path / "fleet.json"
    fleet_file.write_text(json.dumps(FLEET_DOC), encoding="utf-8")
    engine = create_engine("sqlite:///" + (tmp_path / "s.db").as_posix(), future=True)
    repo = FleetRepository(engine, fleet_file=fleet_file)
    svc = SwarmService(
        scenario=ESCENARIO, repository=repo,
        link_factory=lambda r: FakeDroneLink(r.drone_id, r.home_lat, r.home_lon),
        build_mission=lambda p, r: MISSION,
        planning_period_s=0.05, control_period_s=0.0,
    )
    svc.connect_all()
    yield svc
    svc.stop_auto()


def _esperar(condicion, timeout=20.0):
    limite = time.time() + timeout
    while time.time() < limite:
        if condicion():
            return True
        time.sleep(0.05)
    return False


def test_autonomous_mode_empties_a_queue_larger_than_the_fleet(service):
    orders = FakeOrders([_order(n) for n in range(1, 6)])

    service.start_auto(orders)

    entregados = _esperar(
        lambda: all(o["status"] == "entregado" for o in orders.orders.values()))
    assert entregados, (
        "el bucle debe seguir asignando segun se liberan drones: "
        + str({n: o["status"] for n, o in orders.orders.items()}))


def test_autonomous_mode_stops_on_request(service):
    orders = FakeOrders([_order(n) for n in range(1, 20)])
    service.start_auto(orders)
    _esperar(lambda: any(o["status"] == "entregado" for o in orders.orders.values()))

    service.stop_auto()
    service.wait_idle(timeout=10)
    entregados_al_parar = sum(1 for o in orders.orders.values()
                              if o["status"] == "entregado")
    time.sleep(0.4)

    assert not service.auto_running
    assert sum(1 for o in orders.orders.values()
               if o["status"] == "entregado") == entregados_al_parar


def test_an_order_nobody_can_carry_does_not_block_the_queue(service):
    orders = FakeOrders([_order(1, weight=9.0), _order(2), _order(3)])

    service.start_auto(orders)

    assert _esperar(lambda: all(orders.orders[n]["status"] == "entregado"
                                for n in (2, 3)))
    assert orders.orders[1]["status"] == "pendiente", "el imposible sigue esperando"


def test_a_launched_drone_is_marked_busy_synchronously(tmp_path):
    """Regresion de una carrera real observada contra SITL.

    El estado se cambiaba en el hilo del ejecutor, asi que el siguiente ciclo
    de planificacion veia el dron todavia idle y le daba un segundo pedido,
    que se perdia. Hacen falta enlaces lentos: con el doble instantaneo la
    entrega ya ha terminado cuando se comprueba y el dron esta idle con razon.
    """
    class EnlaceBloqueado(FakeDroneLink):
        """No despega hasta que se le suelta. Hace el test determinista."""

        def __init__(self, *args, puerta, **kwargs):
            super().__init__(*args, **kwargs)
            self.puerta = puerta

        def arm_and_takeoff(self, alt):
            self.puerta.wait(timeout=5)
            super().arm_and_takeoff(alt)

    puerta = threading.Event()
    fleet_file = tmp_path / "fleet.json"
    fleet_file.write_text(json.dumps(FLEET_DOC), encoding="utf-8")
    engine = create_engine("sqlite:///" + (tmp_path / "s.db").as_posix(), future=True)
    lento = SwarmService(
        scenario=ESCENARIO, repository=FleetRepository(engine, fleet_file=fleet_file),
        link_factory=lambda r: EnlaceBloqueado(r.drone_id, r.home_lat, r.home_lon,
                                               puerta=puerta),
        build_mission=lambda p, r: MISSION,
        planning_period_s=0.05, control_period_s=0.0,
    )
    lento.connect_all()
    orders = FakeOrders([_order(n) for n in range(1, 6)])

    lanzados = lento.plan_once(orders)

    # Sin esperar a los hilos: los lanzados ya no pueden recibir nada mas.
    estados = {d["record"]["drone_id"]: d["runtime"]["state"]
               for d in lento.fleet_status()}
    assert lanzados, "deberia haber lanzado algo"
    for a in lanzados:
        assert estados[a["drone_id"]] != "idle", (
            f"{a['drone_id']} sigue idle tras lanzarlo")
    assert lento.plan_once(orders) == [], "no puede asignarse un segundo pedido"

    puerta.set()
    lento.stop_all()
    lento.wait_idle(timeout=10)


def test_no_order_is_left_assigned_without_a_drone(service):
    orders = FakeOrders([_order(n) for n in range(1, 8)])

    service.start_auto(orders)
    assert _esperar(
        lambda: all(o["status"] == "entregado" for o in orders.orders.values()))

    huerfanos = [o for o in orders.orders.values() if o["status"] == "asignado"]
    assert huerfanos == [], "un pedido asignado sin dron no lo entrega nadie"


def test_safety_events_are_exposed(service):
    orders = FakeOrders([_order(n) for n in range(1, 4)])
    service.start_auto(orders)
    time.sleep(0.3)

    assert isinstance(service.safety_events(), list)


def test_the_scenario_is_exposed_with_its_slots(service):
    estado = service.scenario_status()

    assert estado["name"] == "Test"
    assert estado["slots"] == [25.0, 30.0]
