import threading

from airdrop.swarm.airspace import AirspaceManager
from airdrop.swarm.executor import DeliveryExecutor
from airdrop.swarm.fake import FakeDroneLink
from airdrop.swarm.models import IDLE, DroneRecord, DroneRuntime
from airdrop.swarm.safety import SafetyPolicy
from airdrop.swarm.scenario import OperationalScenario

PAD_LAT, PAD_LON = 41.283720, 1.985050

ESCENARIO = OperationalScenario(
    name="Castelldefels", route_profile_name="Ruta1-Castelldefels",
    parking_lat=PAD_LAT, parking_lon=PAD_LON,
    delivery_pause_s=0.0, takeoff_gap_s=0.0, waypoint_tolerance_m=5.0,
)

MISSION = {
    "speed": 7.0, "takeOffAlt": 8.0,
    "waypoints": [
        {"lat": PAD_LAT, "lon": PAD_LON, "alt": 0.0},
        {"lat": 41.282946, "lon": 1.986080, "alt": 20.0},   # hub
        {"lat": 41.284412, "lon": 1.978221, "alt": 15.0},   # destino
    ],
}

ORDER = {"id": 1, "weight_kg": 1.0, "assigned_distance_km": 0.8,
         "client_latitude": 41.284500, "client_longitude": 1.978000}


def _make(drone_id="Dron-1", instance=0, steps=3, airspace=None, safety=None,
          runtimes=None, battery_wh=222.0):
    record = DroneRecord(
        drone_id=drone_id, sysid=instance + 1, instance=instance,
        category="medio", connection="fake://",
        home_lat=PAD_LAT, home_lon=PAD_LON,
    )
    runtime = DroneRuntime(drone_id=drone_id, state=IDLE, battery_wh=battery_wh,
                           battery_capacity_wh=222.0)
    link = FakeDroneLink(drone_id, PAD_LAT, PAD_LON, steps_per_leg=steps)
    link.connect()
    executor = DeliveryExecutor(
        record=record, runtime=runtime, link=link, scenario=ESCENARIO,
        airspace=airspace or AirspaceManager(ESCENARIO, slot_count=4),
        safety=safety or SafetyPolicy(ESCENARIO),
        fleet_runtimes=runtimes,
        control_period_s=0.0,
    )
    return executor, link, runtime


def test_without_a_free_slot_the_delivery_is_refused():
    airspace = AirspaceManager(ESCENARIO, slot_count=1)
    airspace.reserve_slot("otro-dron")
    executor, link, runtime = _make(airspace=airspace)
    estados = []
    executor.on_order_state = lambda status, detail: estados.append((status, detail))

    executor.run(ORDER, MISSION)

    assert link.takeoffs == [], "no debe despegar sin slot"
    assert runtime.state == IDLE
    assert estados[-1][0] == "pendiente", (
        "el servicio ya lo marco asignado; si no vuelve a la cola se pierde")


def test_an_occupied_hub_makes_the_drone_wait():
    airspace = AirspaceManager(ESCENARIO, slot_count=4)
    airspace.acquire_hub("otro-dron")
    executor, link, _runtime = _make(airspace=airspace)

    hilo = threading.Thread(target=executor.run, args=(ORDER, MISSION), daemon=True)
    hilo.start()
    hilo.join(timeout=1.0)

    assert link.held_times >= 1, "debe mantener posicion con el HUB ocupado"
    executor.cancel()
    hilo.join(timeout=2.0)


def test_the_hub_is_released_when_the_delivery_ends():
    airspace = AirspaceManager(ESCENARIO, slot_count=4)
    executor, _link, _runtime = _make(airspace=airspace)

    executor.run(ORDER, MISSION)

    assert airspace.hub_holder() is None


def test_the_slot_is_released_when_the_delivery_ends():
    airspace = AirspaceManager(ESCENARIO, slot_count=4)
    executor, _link, runtime = _make(airspace=airspace)

    executor.run(ORDER, MISSION)

    assert airspace.reserved_slot("Dron-1") is None
    assert runtime.cruise_alt_m is None


def test_a_separation_conflict_is_recorded_without_stopping_the_drone():
    """La proximidad se anota, pero ya no frena.

    Esta prueba exigia un ``hold`` porque en su dia el ejecutor se detenia por
    distancia horizontal. Se quito a proposito: dos drones separados por capa
    de altitud no estan en conflicto, y frenar ademas por planta bloqueaba
    indefinidamente al que salia del parking contra el que volvia a el. Lo que
    debe seguir ocurriendo es que quede constancia del cruce.
    """
    airspace = AirspaceManager(ESCENARIO, slot_count=4)
    # Un vecino inmovil pegado al hub, con menos bateria: el nuestro cede.
    vecino = DroneRuntime(drone_id="Dron-9", state="in_transit",
                          lat=41.282946, lon=1.986080, alt=25.0,
                          battery_wh=50.0, battery_capacity_wh=222.0)
    runtimes = {"Dron-9": vecino}
    executor, link, runtime = _make(airspace=airspace, runtimes=runtimes)
    runtimes["Dron-1"] = runtime

    eventos = []
    executor.safety.record_event = lambda drone_id, tipo, detalle: eventos.append(tipo)

    hilo = threading.Thread(target=executor.run, args=(ORDER, MISSION), daemon=True)
    hilo.start()
    hilo.join(timeout=2.0)

    assert "proximidad" in eventos
    assert link.held_times == 0, "la proximidad no debe detener al dron"
    executor.cancel()
    hilo.join(timeout=2.0)


def test_battery_below_the_reserve_aborts_with_rtl():
    executor, link, _runtime = _make()
    safety = executor.safety

    # A mitad de vuelo la bateria se desploma.
    original = safety.check_in_flight
    llamadas = {"n": 0}

    def caida(record, rt, telemetry_age_s=None):
        llamadas["n"] += 1
        if llamadas["n"] > 2:
            rt.battery_wh = 10.0
        return original(record, rt, telemetry_age_s=telemetry_age_s)

    safety.check_in_flight = caida

    executor.run(ORDER, MISSION)

    assert link.aborted == "RTL"
    assert any(e["kind"] == "rtl" for e in safety.events())


def test_an_aborted_order_goes_back_to_the_queue():
    executor, _link, _runtime = _make()
    safety = executor.safety
    estados = []
    executor.on_order_state = lambda status, detail: estados.append((status, detail))

    original = safety.check_in_flight
    llamadas = {"n": 0}

    def caida(record, rt, telemetry_age_s=None):
        llamadas["n"] += 1
        if llamadas["n"] > 2:
            rt.battery_wh = 10.0
        return original(record, rt, telemetry_age_s=telemetry_age_s)

    safety.check_in_flight = caida

    executor.run(ORDER, MISSION)

    assert estados[-1][0] == "pendiente", "el pedido no se pierde"


def test_a_lost_link_frees_the_hub_and_the_slot():
    """Lo que faltaba del diseno: sin esto, una caida de enlace se manifiesta
    como un atasco inexplicable y el dron perdido retiene el HUB."""
    airspace = AirspaceManager(ESCENARIO, slot_count=4)
    executor, link, runtime = _make(airspace=airspace)
    link.stale_telemetry_s = 60.0          # telemetria congelada
    estados = []
    executor.on_order_state = lambda status, detail: estados.append((status, detail))

    executor.run(ORDER, MISSION)

    assert runtime.state == "error"
    assert "enlace perdido" in runtime.detail
    assert estados[-1][0] == "pendiente", "el pedido vuelve a la cola"
    assert airspace.hub_holder() is None
    assert airspace.reserved_slot("Dron-1") is None
    assert any(e["kind"] == "enlace_perdido" for e in executor.safety.events())


def test_a_lost_link_does_not_try_to_command_the_drone():
    # No se manda RTL: no hay a quien mandarselo.
    executor, link, _runtime = _make()
    link.stale_telemetry_s = 60.0

    executor.run(ORDER, MISSION)

    assert link.aborted is None


def test_waiting_for_the_hub_is_recorded_as_an_event():
    airspace = AirspaceManager(ESCENARIO, slot_count=4)
    airspace.acquire_hub("otro-dron")
    safety = SafetyPolicy(ESCENARIO)
    executor, _link, _runtime = _make(airspace=airspace, safety=safety)

    hilo = threading.Thread(target=executor.run, args=(ORDER, MISSION), daemon=True)
    hilo.start()
    hilo.join(timeout=1.0)
    executor.cancel()
    hilo.join(timeout=2.0)

    assert any("HUB" in e["reason"] for e in safety.events())
