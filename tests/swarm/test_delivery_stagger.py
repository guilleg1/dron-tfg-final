"""El escalonado por destino es un parámetro del escenario y se puede cortar.

Dos garantías que el escalonado a la salida necesita para no estorbar a la
operación: que el operador lo pueda ajustar (o anular) sin tocar el código, y
que «Parar todo» no tenga que esperar a que termine un retardo de decenas de
segundos.
"""

import threading
import time

from sqlalchemy import create_engine

from airdrop.swarm.airspace import AirspaceManager
from airdrop.swarm.executor import DeliveryExecutor
from airdrop.swarm.fake import FakeDroneLink
from airdrop.swarm.models import IDLE, DroneRecord, DroneRuntime
from airdrop.swarm.safety import SafetyPolicy
from airdrop.swarm.scenario import OperationalScenario
from airdrop.swarm.scenario_repository import ScenarioRepository
from airdrop.swarm.service import DELIVERY_STAGGER_S

ESCENARIO = OperationalScenario(
    name="Castelldefels", route_profile_name="Ruta1-Castelldefels",
    parking_lat=41.283720, parking_lon=1.985050,
    delivery_pause_s=0.0, takeoff_gap_s=0.0, waypoint_tolerance_m=5.0,
)
MISSION = {
    "speed": 7.0, "takeOffAlt": 8.0,
    "waypoints": [
        {"lat": 41.283720, "lon": 1.985050, "alt": 0.0},
        {"lat": 41.282946, "lon": 1.986080, "alt": 20.0},
        {"lat": 41.284412, "lon": 1.978221, "alt": 15.0},
    ],
}
ORDER = {"id": 1, "weight_kg": 1.0, "assigned_distance_km": 0.8,
         "client_latitude": 41.284500, "client_longitude": 1.978000}


def test_the_default_stagger_is_the_documented_one():
    escenario = OperationalScenario(name="x", route_profile_name="r",
                                    parking_lat=0.0, parking_lon=0.0)

    assert escenario.delivery_stagger_s == DELIVERY_STAGGER_S
    assert escenario.as_dict()["delivery_stagger_s"] == DELIVERY_STAGGER_S


def test_the_stagger_is_stored_and_edited_like_any_other_parameter(tmp_path):
    engine = create_engine("sqlite:///" + (tmp_path / "e.db").as_posix(), future=True)
    repo = ScenarioRepository(engine)
    repo.seed_if_empty()

    assert repo.get("Castelldefels").delivery_stagger_s == DELIVERY_STAGGER_S

    repo.update("Castelldefels", {"delivery_stagger_s": 12.0})

    assert repo.get("Castelldefels").delivery_stagger_s == 12.0


def test_stop_interrupts_a_long_departure_delay():
    airspace = AirspaceManager(ESCENARIO, slot_count=1)
    record = DroneRecord(drone_id="Dron-1", sysid=1, instance=0, category="medio",
                         connection="fake://", home_lat=41.283720, home_lon=1.985050)
    runtime = DroneRuntime(drone_id="Dron-1", state=IDLE, battery_wh=222.0,
                           battery_capacity_wh=222.0)
    link = FakeDroneLink("Dron-1", 41.283720, 1.985050, steps_per_leg=3)
    link.connect()
    ejecutor = DeliveryExecutor(record=record, runtime=runtime, link=link,
                                scenario=ESCENARIO, airspace=airspace,
                                safety=SafetyPolicy(ESCENARIO),
                                control_period_s=0.0, extra_delay_s=30.0)

    hilo = threading.Thread(target=ejecutor.run, args=(ORDER, MISSION))
    inicio = time.time()
    hilo.start()
    time.sleep(0.2)
    ejecutor.cancel()
    hilo.join(timeout=5.0)

    assert not hilo.is_alive(), "el retardo de salida no atendió la cancelación"
    assert time.time() - inicio < 5.0
    assert runtime.state == IDLE
