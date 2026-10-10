import json

import pytest
from sqlalchemy import create_engine

from airdrop.swarm.fake import FakeDroneLink
from airdrop.swarm.models import IDLE, OFFLINE
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
    """Doble del almacén de pedidos, con lo justo que usa SwarmService."""

    def __init__(self, orders):
        self.orders = {o["id"]: dict(o) for o in orders}
        self.updates = []

    def list_pending(self):
        return [o for o in self.orders.values() if o["status"] == "pendiente"]

    def get(self, order_id):
        return self.orders.get(order_id)

    def update(self, order_id, status=None, operational_state=None, assigned_drone_id=None):
        self.updates.append((order_id, status, operational_state, assigned_drone_id))
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

    def link_factory(record):
        return FakeDroneLink(record.drone_id, record.home_lat, record.home_lon)

    return SwarmService(
        scenario=ESCENARIO,
        repository=repo,
        link_factory=link_factory,
        build_mission=lambda profile, route: MISSION,
        planning_period_s=0.05,
    )


def test_before_connecting_every_drone_is_offline(service):
    fleet = service.fleet_status()

    assert len(fleet) == 2
    assert all(d["runtime"]["state"] == OFFLINE for d in fleet)


def test_connecting_leaves_the_fleet_idle_with_full_batteries(service):
    service.connect_all()

    fleet = service.fleet_status()
    assert all(d["runtime"]["state"] == IDLE for d in fleet)
    assert all(d["runtime"]["battery_pct"] == 100.0 for d in fleet)


def test_start_deliveries_assigns_one_order_per_drone(service):
    service.connect_all()
    orders = FakeOrders([_order(1), _order(2), _order(3)])

    plan = service.start_deliveries(orders)

    assert sorted(a["drone_id"] for a in plan) == ["Dron-1", "Dron-2"]
    service.wait_idle(timeout=10)


def test_a_full_run_marks_the_orders_delivered(service):
    service.connect_all()
    orders = FakeOrders([_order(1), _order(2)])

    service.start_deliveries(orders)
    service.wait_idle(timeout=10)

    assert orders.orders[1]["status"] == "entregado"
    assert orders.orders[2]["status"] == "entregado"


def test_the_delivering_drone_is_recorded_on_the_order(service):
    service.connect_all()
    orders = FakeOrders([_order(1)])

    service.start_deliveries(orders)
    service.wait_idle(timeout=10)

    assert orders.orders[1]["assigned_drone_id"] in ("Dron-1", "Dron-2")


def test_drones_end_idle_and_with_less_battery(service):
    service.connect_all()
    orders = FakeOrders([_order(1), _order(2)])

    service.start_deliveries(orders)
    service.wait_idle(timeout=10)

    fleet = service.fleet_status()
    assert all(d["runtime"]["state"] == IDLE for d in fleet)
    assert all(d["runtime"]["battery_pct"] < 100.0 for d in fleet)


def test_starting_twice_does_not_double_assign(service):
    service.connect_all()
    orders = FakeOrders([_order(1), _order(2)])

    service.start_deliveries(orders)
    segundo = service.start_deliveries(orders)

    assert segundo == [], "los drones ya estan ocupados"
    service.wait_idle(timeout=10)


def test_stop_all_aborts_and_frees_the_fleet(service):
    service.connect_all()
    orders = FakeOrders([_order(1), _order(2)])
    service.start_deliveries(orders)

    service.stop_all()
    service.wait_idle(timeout=10)

    assert all(d["runtime"]["state"] == IDLE for d in service.fleet_status())


def test_a_drone_that_fails_to_connect_stays_offline(tmp_path):
    fleet_file = tmp_path / "fleet.json"
    fleet_file.write_text(json.dumps(FLEET_DOC), encoding="utf-8")
    engine = create_engine("sqlite:///" + (tmp_path / "s.db").as_posix(), future=True)
    repo = FleetRepository(engine, fleet_file=fleet_file)

    def link_factory(record):
        return FakeDroneLink(record.drone_id, record.home_lat, record.home_lon,
                             fail_on_connect=(record.drone_id == "Dron-2"))

    service = SwarmService(scenario=ESCENARIO, repository=repo, link_factory=link_factory,
                           build_mission=lambda p, r: MISSION, planning_period_s=0.05)
    service.connect_all()

    estados = {d["record"]["drone_id"]: d["runtime"]["state"] for d in service.fleet_status()}
    assert estados["Dron-1"] == IDLE
    assert estados["Dron-2"] == OFFLINE


def test_removing_a_drone_keeps_the_other_links_open(service):
    service.connect_all()
    enlace = service._links["Dron-1"]

    assert service.remove_drone("Dron-2")

    assert [d["record"]["drone_id"] for d in service.fleet_status()] == ["Dron-1"]
    assert service._links == {"Dron-1": enlace}
    assert service.airspace._slot_count == 1
    assert not service.remove_drone("Dron-2")
