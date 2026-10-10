"""Una base de datos creada con los pesos de la antigua función de costes.

Las columnas w1 a w5 eran NOT NULL sin valor por defecto. Si no se quitan al
arrancar, cualquier escenario nuevo se rechaza al insertarlo.
"""

from sqlalchemy import create_engine, inspect, text

from airdrop.swarm.scenario_repository import ScenarioRepository


def _base_antigua(tmp_path):
    engine = create_engine("sqlite:///" + (tmp_path / "old.db").as_posix(), future=True)
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE scenarios (name VARCHAR(64) PRIMARY KEY, "
            "route_profile_name VARCHAR(128) NOT NULL, parking_lat FLOAT NOT NULL, "
            "parking_lon FLOAT NOT NULL, pad_spacing_m FLOAT NOT NULL, alt_base_m FLOAT NOT NULL, "
            "alt_step_m FLOAT NOT NULL, alt_ceiling_m FLOAT NOT NULL, geofence_radius_m FLOAT NOT NULL, "
            "separation_min_m FLOAT NOT NULL, takeoff_gap_s FLOAT NOT NULL, "
            "waypoint_tolerance_m FLOAT NOT NULL, hub_exclusive BOOLEAN NOT NULL, "
            "battery_reserve_pct FLOAT NOT NULL, delivery_pause_s FLOAT NOT NULL, "
            "w1 FLOAT NOT NULL, w2 FLOAT NOT NULL, w3 FLOAT NOT NULL, w4 FLOAT NOT NULL, "
            "w5 FLOAT NOT NULL, active BOOLEAN NOT NULL, coords_approximate BOOLEAN NOT NULL)"))
    return engine


def test_legacy_weight_columns_are_dropped(tmp_path):
    engine = _base_antigua(tmp_path)
    ScenarioRepository(engine)
    columnas = {c["name"] for c in inspect(engine).get_columns("scenarios")}
    assert not columnas & {"w1", "w2", "w3", "w4", "w5"}
    assert "delivery_stagger_s" in columnas


def test_a_legacy_database_accepts_new_scenarios(tmp_path):
    repo = ScenarioRepository(_base_antigua(tmp_path))
    creado = repo.create_for_profile("Prueba", parking_lat=41.27, parking_lon=1.98)
    assert repo.get("Prueba") == creado
