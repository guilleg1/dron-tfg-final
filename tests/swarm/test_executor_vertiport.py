"""El ejecutor pide de verdad la vertical de SU pad antes de maniobrar.

Que el gestor de espacio aereo sepa decidir no sirve de nada si el ejecutor no
le pasa las coordenadas del pad: caeria siempre a exclusion total y la
formacion del parking no cambiaria nada en vuelo. Estas pruebas cierran ese
hueco de cableado, que es el que no se ve en el registro de eventos.
"""

import threading
import time

from airdrop.swarm.airspace import AirspaceManager
from airdrop.swarm.executor import DeliveryExecutor
from airdrop.swarm.fake import FakeDroneLink
from airdrop.swarm.models import IDLE, DroneRecord, DroneRuntime
from airdrop.swarm.safety import SafetyPolicy
from airdrop.swarm.scenario import OperationalScenario

PARKING_LAT, PARKING_LON = 41.283720, 1.985050

# Cuatro plazas en fila cada 15 m, con 25 m exigidos para operar a la vez:
# contiguas se estorban, a dos plazas o mas no.
ESCENARIO = OperationalScenario(
    name="Castelldefels", route_profile_name="Ruta1-Castelldefels",
    parking_lat=PARKING_LAT, parking_lon=PARKING_LON,
    pad_spacing_m=15.0, pad_separation_m=25.0,
    delivery_pause_s=0.0, takeoff_gap_s=0.0, waypoint_tolerance_m=5.0,
)
PADS = ESCENARIO.parking_slots(4)

MISSION = {
    "speed": 7.0, "takeOffAlt": 8.0,
    "waypoints": [
        {"lat": PARKING_LAT, "lon": PARKING_LON, "alt": 0.0},
        {"lat": 41.282946, "lon": 1.986080, "alt": 20.0},
        {"lat": 41.284412, "lon": 1.978221, "alt": 15.0},
    ],
}

ORDER = {"id": 1, "weight_kg": 1.0, "assigned_distance_km": 0.8,
         "client_latitude": 41.284500, "client_longitude": 1.978000}


def _executor(drone_id, pad_index, airspace, steps=3):
    pad_lat, pad_lon = PADS[pad_index]
    record = DroneRecord(
        drone_id=drone_id, sysid=pad_index + 1, instance=pad_index,
        category="medio", connection="fake://",
        home_lat=pad_lat, home_lon=pad_lon,
    )
    runtime = DroneRuntime(drone_id=drone_id, state=IDLE, battery_wh=222.0,
                           battery_capacity_wh=222.0)
    link = FakeDroneLink(drone_id, pad_lat, pad_lon, steps_per_leg=steps)
    link.connect()
    ejecutor = DeliveryExecutor(
        record=record, runtime=runtime, link=link, scenario=ESCENARIO,
        airspace=airspace, safety=SafetyPolicy(ESCENARIO),
        control_period_s=0.0,
    )
    return ejecutor, link


def _espiar(airspace):
    """Registra cada peticion de vertical, con sus argumentos."""
    llamadas = []
    original = airspace.acquire_pad

    def espia(drone_id, lat=None, lon=None, maniobra="despegar"):
        llamadas.append((drone_id, lat, lon, maniobra))
        return original(drone_id, lat, lon, maniobra)

    airspace.acquire_pad = espia
    return llamadas


def test_the_executor_asks_for_its_own_pad_not_for_the_parking():
    """Sin las coordenadas, el vertipuerto no puede distinguir un pad de otro."""
    airspace = AirspaceManager(ESCENARIO, slot_count=4)
    llamadas = _espiar(airspace)
    ejecutor, _link = _executor("Dron-3", 2, airspace)

    ejecutor.run(ORDER, MISSION)

    assert llamadas, "el ejecutor no pidio la vertical"
    # En el parking pide siempre la de SU pad. La otra vertical que reserva
    # es la del punto de entrega (ver test_executor_delivery_zone.py).
    cliente = (ORDER["client_latitude"], ORDER["client_longitude"])
    en_parking = [(lat, lon) for _id, lat, lon, _m in llamadas
                  if (lat, lon) != cliente]
    assert en_parking, "no pidio la vertical del parking"
    assert all(p == PADS[2] for p in en_parking), \
        "pidio otra vertical del parking que la de su pad"


def test_the_manoeuvre_type_reaches_the_vertiport():
    """Sin el tipo, los aterrizajes no podrian adelantar a los despegues."""
    airspace = AirspaceManager(ESCENARIO, slot_count=4)
    llamadas = _espiar(airspace)
    ejecutor, _link = _executor("Dron-1", 0, airspace)

    ejecutor.run(ORDER, MISSION)

    maniobras = [m for _id, _lat, _lon, m in llamadas]
    assert maniobras[0] == "despegar"
    assert "aterrizar" in maniobras, "el aterrizaje en el parking no se anuncio"


def test_far_apart_drones_take_off_without_waiting_for_each_other():
    """Dos pads a 45 m: el vertipuerto los deja subir a la vez."""
    airspace = AirspaceManager(ESCENARIO, slot_count=4)
    uno, _ = _executor("Dron-1", 0, airspace)
    otro, _ = _executor("Dron-4", 3, airspace)

    eventos = []
    for ejecutor in (uno, otro):
        ejecutor.safety.record_event = (
            lambda drone_id, tipo, detalle: eventos.append(tipo))

    hilos = [threading.Thread(target=e.run, args=(ORDER, MISSION), daemon=True)
             for e in (uno, otro)]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join(timeout=10.0)

    assert "espera_pad" not in eventos, "esperaron sin necesidad"


def test_neighbouring_drones_wait_before_starting_the_manoeuvre():
    """Dos pads a 15 m: el segundo no empieza hasta que el primero suelta.

    Y espera **antes** de armar: en el registro esto es el `espera_pad` que
    aparece sin que el dron haya despegado.
    """
    airspace = AirspaceManager(ESCENARIO, slot_count=4)
    airspace.acquire_pad("Dron-1", *PADS[0], "despegar")   # ocupa la vertical

    ejecutor, link = _executor("Dron-2", 1, airspace)
    eventos = []
    ejecutor.safety.record_event = (
        lambda drone_id, tipo, detalle: eventos.append(tipo))

    hilo = threading.Thread(target=ejecutor.run, args=(ORDER, MISSION),
                            daemon=True)
    hilo.start()
    time.sleep(0.3)

    assert "espera_pad" in eventos
    assert link.takeoffs == [], "armo con la vertical del vecino ocupada"

    airspace.release_pad("Dron-1")
    hilo.join(timeout=10.0)

    assert link.takeoffs, "no despego al quedar libre"
