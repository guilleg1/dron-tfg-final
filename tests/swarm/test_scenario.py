import pytest

from airdrop.swarm.scenario import OperationalScenario


def _castelldefels(**kwargs):
    base = dict(
        name="Castelldefels", route_profile_name="Ruta1-Castelldefels",
        parking_lat=41.283720590600794, parking_lon=1.9850507581982129,
    )
    base.update(kwargs)
    return OperationalScenario(**base)


def test_outdoor_defaults_match_the_castelldefels_setup():
    s = _castelldefels()

    assert s.alt_base_m == 25.0
    assert s.alt_step_m == 5.0
    assert s.alt_ceiling_m == 120.0
    assert s.separation_min_m == 30.0
    assert s.pad_spacing_m == 8.0


def test_slot_altitudes_step_and_respect_the_ceiling():
    s = _castelldefels()

    assert s.slot_altitudes(4) == [25.0, 30.0, 35.0, 40.0]


def test_the_ceiling_caps_how_many_slots_exist():
    # base 2, paso 1, techo 4 -> solo caben 2, 3 y 4
    s = _castelldefels(alt_base_m=2.0, alt_step_m=1.0, alt_ceiling_m=4.0)

    assert s.slot_altitudes(10) == [2.0, 3.0, 4.0]


def test_the_indoor_scenario_operates_two_orders_of_magnitude_lower():
    s = _castelldefels(
        name="DroneLab EETAC", alt_base_m=2.0, alt_step_m=1.0, alt_ceiling_m=4.0,
        separation_min_m=2.0, pad_spacing_m=1.5, geofence_radius_m=15.0,
        waypoint_tolerance_m=0.5,
    )

    assert s.slot_altitudes(3) == [2.0, 3.0, 4.0]
    assert s.separation_min_m == 2.0
    assert s.geofence_radius_m == 15.0


def test_a_point_inside_the_geofence_is_accepted():
    s = _castelldefels(geofence_radius_m=1500.0)

    assert s.is_inside_geofence(41.2844, 1.9782)          # Castillo, ~600 m
    assert not s.is_inside_geofence(41.3039, 2.0097)      # Gava, ~3 km


def test_battery_reserve_is_a_fraction_of_capacity():
    s = _castelldefels(battery_reserve_pct=20.0)

    assert s.usable_fraction == pytest.approx(0.8)


# ── Formaciones del parking ──────────────────────────────────────────────

def _dist_m(a, b):
    from core.geo import haversine_km
    return haversine_km(a[0], a[1], b[0], b[1]) * 1000.0


def _escenario(**cambios):
    base = dict(name="X", route_profile_name="R",
                parking_lat=41.283720, parking_lon=1.985050)
    base.update(cambios)
    return OperationalScenario(**base)


def test_the_row_layout_spaces_the_pads_by_pad_spacing():
    pads = _escenario(pad_spacing_m=12.0).parking_slots(4)

    assert len(pads) == 4
    assert _dist_m(pads[0], pads[1]) == pytest.approx(12.0, abs=0.1)
    assert _dist_m(pads[0], pads[3]) == pytest.approx(36.0, abs=0.1)


def test_the_grid_layout_wraps_at_pad_cols():
    """Una rejilla 2x2 acerca los extremos: mismo numero de drones, menos frente.

    Es el compromiso del vertipuerto: la rejilla ocupa menos terreno pero
    junta las verticales, asi que admite menos maniobras simultaneas.
    """
    fila = _escenario(pad_spacing_m=12.0).parking_slots(4)
    rejilla = _escenario(pad_spacing_m=12.0, pad_layout="rejilla",
                         pad_cols=2).parking_slots(4)

    assert _dist_m(rejilla[0], rejilla[1]) == pytest.approx(12.0, abs=0.1)
    assert _dist_m(rejilla[0], rejilla[2]) == pytest.approx(12.0, abs=0.1), "fila de abajo"
    assert _dist_m(rejilla[0], rejilla[3]) < _dist_m(fila[0], fila[3])


def test_the_circle_layout_keeps_every_pad_at_the_same_distance_from_the_centre():
    escenario = _escenario(pad_spacing_m=20.0, pad_layout="circulo")
    pads = escenario.parking_slots(4)
    centro = (escenario.parking_lat, escenario.parking_lon)

    radios = [_dist_m(centro, p) for p in pads]
    assert max(radios) - min(radios) < 0.1
    assert _dist_m(pads[0], pads[1]) == pytest.approx(20.0, abs=0.2), "cuerda = espaciado"


def test_a_heading_turns_the_whole_formation():
    norte = _escenario(pad_spacing_m=12.0, pad_heading_deg=0.0).parking_slots(2)

    assert norte[1][0] > norte[0][0], "crece hacia el norte"
    assert norte[0][1] == pytest.approx(norte[1][1]), "sin componente este"


def test_pads_can_operate_together_only_beyond_the_separation():
    escenario = _escenario(pad_spacing_m=12.0, pad_separation_m=25.0)
    pads = escenario.parking_slots(4)

    assert not escenario.pads_can_operate_together(*pads[0], *pads[1])
    assert escenario.pads_can_operate_together(*pads[0], *pads[3])


def test_without_pad_separation_no_two_pads_operate_together():
    """El defecto es el cerrojo unico: lo verificado en B2 no cambia solo."""
    escenario = _escenario(pad_spacing_m=12.0)
    pads = escenario.parking_slots(4)

    assert not escenario.pads_can_operate_together(*pads[0], *pads[3])
