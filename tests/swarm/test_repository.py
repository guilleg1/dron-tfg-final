import json

import pytest
from sqlalchemy import create_engine

from airdrop.swarm.repository import FleetRepository, build_records
from airdrop.swarm.scenario import OperationalScenario

FLEET_DOC = {
    "drones": [
        {"drone_id": "Dron-1", "sysid": 1, "instance": 0, "category": "ligero"},
        {"drone_id": "Dron-2", "sysid": 2, "instance": 1, "category": "ligero"},
        {"drone_id": "Dron-3", "sysid": 3, "instance": 2, "category": "medio"},
        {"drone_id": "Dron-4", "sysid": 4, "instance": 3, "category": "pesado"},
    ],
}

ESCENARIO = OperationalScenario(
    name="Castelldefels", route_profile_name="Ruta1-Castelldefels",
    parking_lat=41.283720590600794, parking_lon=1.9850507581982129,
)

INDOOR = OperationalScenario(
    name="DroneLab EETAC", route_profile_name="Ruta2-Castelldefels",
    parking_lat=41.2757, parking_lon=1.9875,
    pad_spacing_m=1.5, alt_base_m=2.0, alt_step_m=1.0, alt_ceiling_m=4.0,
)


@pytest.fixture()
def fleet_file(tmp_path):
    path = tmp_path / "fleet.json"
    path.write_text(json.dumps(FLEET_DOC), encoding="utf-8")
    return path


@pytest.fixture()
def repo(tmp_path, fleet_file):
    engine = create_engine("sqlite:///" + (tmp_path / "swarm.db").as_posix(), future=True)
    return FleetRepository(engine, fleet_file=fleet_file)


def test_ports_step_by_ten_per_instance_and_target_serial1():
    # SERIAL1, no SERIAL0: SERIAL0 admite un solo cliente y lo toma Mission
    # Planner al abrir la simulacion.
    records = build_records(FLEET_DOC, ESCENARIO)

    assert [r.connection for r in records] == [
        "tcp:127.0.0.1:5762",
        "tcp:127.0.0.1:5772",
        "tcp:127.0.0.1:5782",
        "tcp:127.0.0.1:5792",
    ]


def test_each_drone_gets_its_own_pad():
    records = build_records(FLEET_DOC, ESCENARIO)

    lons = [r.home_lon for r in records]
    assert len(set(lons)) == 4, "los pads deben ser distintos o los drones nacen encima"
    assert records[1].home_lon > records[0].home_lon
    assert all(r.home_lat == pytest.approx(ESCENARIO.parking_lat) for r in records)


def test_the_formation_is_centred_on_the_parking():
    """El parking es el centro de la formación, no el pad del primer dron.

    Antes el pad 0 caía exactamente sobre el parking y la fila crecía hacia el
    este, así que ampliar la flota desplazaba el conjunto a un lado y dejaba el
    marcador del mapa en un extremo. Centrando, añadir drones ensancha la
    formación de forma simétrica y las rejillas y círculos salen bien.
    """
    records = build_records(FLEET_DOC, ESCENARIO)

    medio = sum(r.home_lon for r in records) / len(records)
    assert medio == pytest.approx(ESCENARIO.parking_lon)


def test_the_pad_index_can_be_declared_apart_from_the_instance():
    """La instancia SITL y la plaza de parking son cosas distintas.

    La instancia fija los puertos TCP; el pad, dónde está el dron. Atarlas
    impedía dejar plazas libres o reordenar el parking sin renumerar los
    puertos, que es lo que rompe la correspondencia con las instancias SITL ya
    lanzadas.
    """
    doc = {"drones": [
        {"drone_id": "Dron-1", "sysid": 1, "instance": 0, "category": "ligero",
         "pad_index": 3},
        {"drone_id": "Dron-2", "sysid": 2, "instance": 1, "category": "ligero",
         "pad_index": 0},
    ]}
    records = build_records(doc, ESCENARIO)

    assert records[0].connection.endswith("5762"), "la instancia no cambia"
    assert records[0].home_lon > records[1].home_lon, "pero el pad sí"


def test_the_indoor_scenario_packs_the_pads_closer():
    fuera = build_records(FLEET_DOC, ESCENARIO)
    dentro = build_records(FLEET_DOC, INDOOR)

    separacion_fuera = fuera[1].home_lon - fuera[0].home_lon
    separacion_dentro = dentro[1].home_lon - dentro[0].home_lon
    assert separacion_dentro < separacion_fuera


def test_sysids_are_unique():
    records = build_records(FLEET_DOC, ESCENARIO)

    assert len({r.sysid for r in records}) == 4


def test_seeding_is_idempotent(repo):
    first = repo.seed_if_empty(ESCENARIO)
    second = repo.seed_if_empty(ESCENARIO)

    assert len(first) == 4
    assert len(second) == 4
    assert len(repo.list_drones()) == 4


def test_disabled_drones_are_filtered_out(tmp_path):
    doc = json.loads(json.dumps(FLEET_DOC))
    doc["drones"][2]["enabled"] = False
    path = tmp_path / "fleet.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    engine = create_engine("sqlite:///" + (tmp_path / "f.db").as_posix(), future=True)
    repo = FleetRepository(engine, fleet_file=path)
    repo.seed_if_empty(ESCENARIO)

    assert [d.drone_id for d in repo.list_drones()] == ["Dron-1", "Dron-2", "Dron-4"]
    assert len(repo.list_drones(only_enabled=False)) == 4


def test_records_survive_a_round_trip(repo):
    repo.seed_if_empty(ESCENARIO)

    stored = {d.drone_id: d for d in repo.list_drones()}

    assert stored["Dron-4"].category == "pesado"
    assert stored["Dron-4"].sysid == 4
    assert stored["Dron-4"].spec.max_payload_kg == 4.0


def test_reseating_the_fleet_moves_the_pads(repo):
    repo.seed_if_empty(ESCENARIO)
    fuera = {d.drone_id: d.home_lon for d in repo.list_drones()}

    repo.reseat(INDOOR)
    dentro = {d.drone_id: d.home_lon for d in repo.list_drones()}

    assert dentro["Dron-1"] != fuera["Dron-1"], "el parking del escenario cambio"


def test_removing_a_drone_keeps_the_others_untouched(repo):
    repo.seed_if_empty(ESCENARIO)
    antes = {d.drone_id: d for d in repo.list_drones()}

    assert repo.remove("Dron-2")
    despues = {d.drone_id: d for d in repo.list_drones()}

    assert set(despues) == {"Dron-1", "Dron-3", "Dron-4"}
    for nombre, dron in despues.items():
        assert dron == antes[nombre]
    assert not repo.remove("Dron-2")


def test_reseating_keeps_the_fleet_in_the_database(repo):
    """Cambiar de escenario no devuelve la flota a la del fichero."""
    repo.seed_if_empty(ESCENARIO)
    repo.remove("Dron-2")

    repo.reseat(INDOOR)
    flota = repo.list_drones()

    assert [d.drone_id for d in flota] == ["Dron-1", "Dron-3", "Dron-4"]
    assert [d.instance for d in flota] == [0, 2, 3]       # puertos intactos
    pads = INDOOR.parking_slots(3)
    assert [(d.home_lat, d.home_lon) for d in flota] == pads  # sin huecos


def test_factory_reset_goes_back_to_the_file(repo):
    repo.seed_if_empty(ESCENARIO)
    repo.remove("Dron-2")

    repo.reseat(ESCENARIO, desde_fichero=True)

    assert len(repo.list_drones()) == 4
