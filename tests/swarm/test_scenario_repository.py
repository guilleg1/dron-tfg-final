import pytest
from sqlalchemy import create_engine

from airdrop.swarm.scenario_repository import ScenarioRepository


@pytest.fixture()
def repo(tmp_path):
    engine = create_engine("sqlite:///" + (tmp_path / "s.db").as_posix(), future=True)
    return ScenarioRepository(engine)


def test_seeding_creates_the_four_scenarios(repo):
    escenarios = repo.seed_if_empty()

    assert sorted(s.name for s in escenarios) == [
        "Castelldefels", "DroneLab EETAC", "Gava", "Viladecans",
    ]


def test_exactly_one_scenario_is_active(repo):
    repo.seed_if_empty()

    activos = [s for s in repo.list_scenarios() if s.active]
    assert len(activos) == 1
    assert activos[0].name == "Castelldefels"


def test_castelldefels_flies_above_the_castle_hill(repo):
    """El corredor del castillo sube hasta 40 m sobre el aparcamiento.

    La altura de crucero es relativa al punto de despegue, no al terreno.
    Con la capa base a 25 m, un SITL con datos de terreno chocaba contra la
    ladera antes de llegar al destino.
    """
    repo.seed_if_empty()

    s = next(x for x in repo.list_scenarios() if x.name == "Castelldefels")
    assert s.alt_base_m == 60.0
    assert s.slot_altitudes(4) == [60.0, 65.0, 70.0, 75.0]


def test_the_indoor_scenario_carries_reduced_parameters(repo):
    repo.seed_if_empty()

    lab = next(s for s in repo.list_scenarios() if s.name == "DroneLab EETAC")
    assert lab.alt_base_m == 2.0
    assert lab.alt_ceiling_m == 4.0
    assert lab.separation_min_m == 2.0
    assert lab.pad_spacing_m == 1.5
    assert lab.geofence_radius_m == 15.0


def test_every_scenario_has_real_coordinates(repo):
    # El DroneLab tenía coordenadas aproximadas; ahora está sobre la jaula real.
    repo.seed_if_empty()

    for escenario in repo.list_scenarios():
        assert not escenario.coords_approximate, escenario.name
    lab = repo.get("DroneLab EETAC")
    assert lab.route_profile_name == "DroneLab-EETAC"


def test_viladecans_has_its_own_route_profile_and_a_wider_geofence(repo):
    repo.seed_if_empty()

    vila = next(s for s in repo.list_scenarios() if s.name == "Viladecans")
    assert vila.route_profile_name == "Ruta3-Viladecans"
    # Can Calderon queda a unos 1,55 km del aparcamiento: con 1,5 km quedaría fuera.
    assert vila.geofence_radius_m == 2000.0


def test_activating_one_deactivates_the_rest(repo):
    repo.seed_if_empty()

    repo.activate("Gava")

    activos = [s.name for s in repo.list_scenarios() if s.active]
    assert activos == ["Gava"]
    assert repo.active().name == "Gava"


def test_updating_parameters_persists_them(repo):
    repo.seed_if_empty()

    repo.update("Castelldefels", {"separation_min_m": 45.0, "takeoff_gap_s": 15.0})

    s = next(x for x in repo.list_scenarios() if x.name == "Castelldefels")
    assert s.separation_min_m == 45.0
    assert s.takeoff_gap_s == 15.0


def test_updating_ignores_unknown_fields(repo):
    repo.seed_if_empty()

    repo.update("Castelldefels", {"separation_min_m": 45.0, "color_favorito": "azul"})

    s = next(x for x in repo.list_scenarios() if x.name == "Castelldefels")
    assert s.separation_min_m == 45.0


def test_seeding_is_idempotent(repo):
    repo.seed_if_empty()
    repo.activate("Gava")
    repo.seed_if_empty()

    assert repo.active().name == "Gava", "resembrar no debe pisar la seleccion"
