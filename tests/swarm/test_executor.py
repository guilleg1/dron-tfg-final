import pytest

from airdrop.swarm.executor import DeliveryExecutor
from airdrop.swarm.fake import FakeDroneLink
from airdrop.swarm.airspace import AirspaceManager
from airdrop.swarm.models import ERROR, IDLE, DroneRecord, DroneRuntime
from airdrop.swarm.safety import SafetyPolicy
from airdrop.swarm.scenario import OperationalScenario

PAD_LAT, PAD_LON = 41.283720, 1.985050

MISSION = {
    "speed": 7.0,
    "takeOffAlt": 8.0,
    "waypoints": [
        {"lat": 41.283720, "lon": 1.985050, "alt": 0.0},    # parking del perfil
        {"lat": 41.282946, "lon": 1.986080, "alt": 20.0},   # hub
        {"lat": 41.285722, "lon": 1.980634, "alt": 20.0},   # intermedio
        {"lat": 41.284412, "lon": 1.978221, "alt": 15.0},   # destino de ruta
    ],
}

ORDER = {
    "id": 42,
    "weight_kg": 1.5,
    "client_latitude": 41.284500,
    "client_longitude": 1.978000,
    "assigned_distance_km": 0.8,
}


def _record(drone_id="Dron-1", category="medio", instance=0):
    return DroneRecord(
        drone_id=drone_id, sysid=instance + 1, instance=instance,
        category=category, connection="fake://",
        home_lat=PAD_LAT, home_lon=PAD_LON,
    )


ESCENARIO = OperationalScenario(
    name="Castelldefels", route_profile_name="Ruta1-Castelldefels",
    parking_lat=PAD_LAT, parking_lon=PAD_LON,
    delivery_pause_s=0.0, takeoff_gap_s=0.0, waypoint_tolerance_m=5.0,
)


def _setup(**link_kwargs):
    record = _record()
    runtime = DroneRuntime(
        drone_id=record.drone_id, state=IDLE,
        battery_wh=record.spec.battery_capacity_wh,
        battery_capacity_wh=record.spec.battery_capacity_wh,
    )
    link = FakeDroneLink(record.drone_id, PAD_LAT, PAD_LON, **link_kwargs)
    link.connect()
    estados = []
    executor = DeliveryExecutor(
        record=record, runtime=runtime, link=link,
        scenario=ESCENARIO, airspace=AirspaceManager(ESCENARIO, slot_count=4),
        safety=SafetyPolicy(ESCENARIO),
        on_order_state=lambda status, detail: estados.append((status, detail)),
        control_period_s=0.0,
    )
    return executor, link, runtime, estados


def test_a_delivery_ends_with_the_order_delivered():
    executor, _link, _runtime, estados = _setup()

    executor.run(ORDER, MISSION)

    assert estados[-1][0] == "entregado"


def test_the_drone_ends_idle_back_on_its_pad():
    executor, link, runtime, _ = _setup()

    executor.run(ORDER, MISSION)

    assert runtime.state == IDLE
    assert runtime.current_order_id is None
    assert link.visited[-1][0] == pytest.approx(PAD_LAT)
    assert link.visited[-1][1] == pytest.approx(PAD_LON)


def test_it_flies_hub_then_route_then_client_then_back():
    executor, link, _runtime, _ = _setup()

    executor.run(ORDER, MISSION)

    lats = [round(lat, 6) for lat, _lon, _alt in link.visited]
    # ida: hub, intermedio, destino, cliente
    assert lats[:4] == [41.282946, 41.285722, 41.284412, 41.284500]
    # vuelta: hub y pad
    assert lats[-2:] == [41.282946, round(PAD_LAT, 6)]


def test_the_return_retraces_the_outbound_route_backwards():
    # Volver en linea recta ignora que el corredor esta aprobado y que fuera
    # de el no hay garantia de obstaculos ni de sobrevuelo permitido.
    executor, link, _runtime, _ = _setup()

    executor.run(ORDER, MISSION)

    lats = [round(lat, 6) for lat, _lon, _alt in link.visited]
    # tras el cliente: destino, intermedio, aproximación al hub, hub y pad,
    # la ida al revés con un punto de espera antes de la confluencia
    assert lats[-5:-3] == [41.284412, 41.285722]
    assert lats[-2:] == [41.282946, round(PAD_LAT, 6)]
    aprox = lats[-3]
    assert min(41.282946, 41.285722) < aprox < max(41.282946, 41.285722)


def test_the_hub_is_requested_only_near_it_on_the_way_back():
    # El HUB protege la zona de confluencia: no se retiene durante todo el
    # último tramo del regreso, solo desde HUB_APPROACH_M antes de llegar.
    from airdrop.swarm.executor import HUB_APPROACH_M
    from core.geo import haversine_km

    executor, link, _runtime, _ = _setup()
    hub = MISSION["waypoints"][1]
    retenciones = []
    original = executor.airspace.acquire_hub

    def acquire(drone_id):
        lat, lon, _ = link.telemetry()["lat"], link.telemetry()["lon"], None
        retenciones.append(haversine_km(lat, lon, hub["lat"], hub["lon"]) * 1000.0)
        return original(drone_id)

    executor.airspace.acquire_hub = acquire
    executor.run(ORDER, MISSION)

    # dos peticiones: al salir (desde el pad) y al volver (desde la aproximación)
    assert len(retenciones) == 2
    assert retenciones[1] == pytest.approx(HUB_APPROACH_M, abs=10.0)


def test_it_cruises_at_the_reserved_slot():
    executor, link, _runtime, _ = _setup()

    executor.run(ORDER, MISSION)

    # El regreso rehace la ruta de ida, asi que sobre el mismo corredor hay
    # trafico en los dos sentidos: se separan por nivel. Con cuatro capas
    # (25/30/35/40) el bloque de vuelta empieza en 45.
    assert link.takeoffs == [25.0, 45.0], "ida en su slot, vuelta un bloque arriba"


def test_the_return_leg_never_shares_altitude_with_the_outbound():
    executor, link, _runtime, _ = _setup()

    executor.run(ORDER, MISSION)

    ida = {alt for _lat, _lon, alt in link.visited[:4]}
    vuelta = {alt for _lat, _lon, alt in link.visited[-4:]}

    assert not ida & vuelta, "ida y vuelta no pueden compartir nivel"


def test_it_lands_at_the_client_and_at_the_pad():
    executor, link, _runtime, _ = _setup()

    executor.run(ORDER, MISSION)

    assert link.landings == 2


def test_battery_drops_by_the_estimated_trip_energy():
    executor, _link, runtime, _ = _setup()
    antes = runtime.battery_wh

    executor.run(ORDER, MISSION)

    assert runtime.battery_wh < antes
    assert runtime.battery_wh == pytest.approx(antes - executor.last_energy_wh)


def test_a_failure_leaves_the_drone_in_error_and_the_order_flagged():
    executor, _link, runtime, estados = _setup(fail_on_goto=True)

    executor.run(ORDER, MISSION)

    assert runtime.state == ERROR
    assert estados[-1][1] == "error"


def test_cancelling_stops_the_delivery():
    executor, link, runtime, _ = _setup()
    executor.cancel()

    executor.run(ORDER, MISSION)

    assert link.aborted == "RTL"
    assert runtime.current_order_id is None
