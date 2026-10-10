from airdrop.swarm.models import ERROR, IDLE, IN_TRANSIT, DroneRecord, DroneRuntime
from airdrop.swarm.safety import LINK_LOST, RTL, SafetyPolicy
from airdrop.swarm.scenario import OperationalScenario

ESCENARIO = OperationalScenario(
    name="Castelldefels", route_profile_name="Ruta1-Castelldefels",
    parking_lat=41.283720, parking_lon=1.985050,
    geofence_radius_m=1500.0, battery_reserve_pct=20.0,
)

RECORD = DroneRecord(
    drone_id="Dron-1", sysid=1, instance=0, category="medio",
    connection="fake://", home_lat=41.283720, home_lon=1.985050,
)

ORDER = {"id": 1, "weight_kg": 1.0, "assigned_distance_km": 0.8,
         "client_latitude": 41.2844, "client_longitude": 1.9782}


def _runtime(state=IDLE, battery_wh=222.0, lat=41.283720, lon=1.985050, alt=0.0):
    return DroneRuntime(drone_id="Dron-1", state=state, battery_wh=battery_wh,
                        battery_capacity_wh=222.0, lat=lat, lon=lon, alt=alt)


def _policy():
    return SafetyPolicy(ESCENARIO)


# ── Antes de despegar ────────────────────────────────────────────────────

def test_a_healthy_drone_is_cleared_to_fly():
    ok, motivo = _policy().can_dispatch(RECORD, _runtime(), ORDER)

    assert ok, motivo


def test_a_busy_drone_is_not_cleared():
    ok, motivo = _policy().can_dispatch(RECORD, _runtime(state=IN_TRANSIT), ORDER)

    assert not ok
    assert "disponible" in motivo


def test_a_drone_in_error_is_not_cleared():
    ok, _ = _policy().can_dispatch(RECORD, _runtime(state=ERROR), ORDER)

    assert not ok


def test_a_drone_below_the_battery_reserve_is_not_cleared():
    ok, motivo = _policy().can_dispatch(RECORD, _runtime(battery_wh=30.0), ORDER)

    assert not ok
    assert "reserva" in motivo


def test_a_trip_that_does_not_fit_in_the_usable_battery_is_refused():
    lejos = dict(ORDER, assigned_distance_km=40.0)

    ok, motivo = _policy().can_dispatch(RECORD, _runtime(), lejos)

    assert not ok
    assert "autonomía" in motivo


def test_a_client_outside_the_geofence_is_refused():
    fuera = dict(ORDER, client_latitude=41.3039, client_longitude=2.0097)  # Gava

    ok, motivo = _policy().can_dispatch(RECORD, _runtime(), fuera)

    assert not ok
    assert "geovalla" in motivo


def test_an_overweight_order_is_refused():
    pesado = dict(ORDER, weight_kg=9.0)

    ok, motivo = _policy().can_dispatch(RECORD, _runtime(), pesado)

    assert not ok
    assert "carga" in motivo


# ── Durante el vuelo ─────────────────────────────────────────────────────

def test_a_normal_flight_needs_no_action():
    runtime = _runtime(state=IN_TRANSIT, lat=41.2844, lon=1.9782, alt=25.0)

    assert _policy().check_in_flight(RECORD, runtime) is None


def test_battery_below_the_reserve_forces_rtl():
    runtime = _runtime(state=IN_TRANSIT, battery_wh=20.0,
                       lat=41.2844, lon=1.9782, alt=25.0)

    accion, motivo = _policy().check_in_flight(RECORD, runtime)

    assert accion == RTL
    assert "batería" in motivo


def test_leaving_the_geofence_forces_rtl():
    runtime = _runtime(state=IN_TRANSIT, lat=41.3039, lon=2.0097, alt=25.0)

    accion, motivo = _policy().check_in_flight(RECORD, runtime)

    assert accion == RTL
    assert "geovalla" in motivo


def test_flying_above_the_ceiling_forces_rtl():
    runtime = _runtime(state=IN_TRANSIT, lat=41.2844, lon=1.9782, alt=140.0)

    accion, motivo = _policy().check_in_flight(RECORD, runtime)

    assert accion == RTL
    assert "techo" in motivo


def test_frozen_telemetry_is_reported_as_a_lost_link():
    runtime = _runtime(state=IN_TRANSIT, lat=41.2844, lon=1.9782, alt=25.0)

    accion, motivo = _policy().check_in_flight(RECORD, runtime, telemetry_age_s=30.0)

    assert accion == LINK_LOST
    assert "enlace perdido" in motivo


def test_fresh_telemetry_raises_nothing():
    runtime = _runtime(state=IN_TRANSIT, lat=41.2844, lon=1.9782, alt=25.0)

    assert _policy().check_in_flight(RECORD, runtime, telemetry_age_s=1.0) is None


def test_a_lost_link_takes_priority_over_the_other_checks():
    # Con el enlace caido los demas datos son viejos: dar RTL por bateria
    # baja seria decidir sobre informacion que ya no vale.
    runtime = _runtime(state=IN_TRANSIT, battery_wh=5.0,
                       lat=41.3039, lon=2.0097, alt=200.0)

    accion, _ = _policy().check_in_flight(RECORD, runtime, telemetry_age_s=60.0)

    assert accion == LINK_LOST


def test_the_timeout_is_adjustable():
    politica = SafetyPolicy(ESCENARIO, telemetry_timeout_s=2.0)
    runtime = _runtime(state=IN_TRANSIT, lat=41.2844, lon=1.9782, alt=25.0)

    assert politica.check_in_flight(RECORD, runtime, telemetry_age_s=3.0)[0] == LINK_LOST
    assert politica.check_in_flight(RECORD, runtime, telemetry_age_s=1.0) is None


def test_a_grounded_drone_is_not_checked():
    assert _policy().check_in_flight(RECORD, _runtime(state=IDLE)) is None


# ── Registro de eventos ──────────────────────────────────────────────────

def test_events_are_recorded_newest_first():
    politica = _policy()

    politica.record_event("Dron-1", "espera", "HUB ocupado")
    politica.record_event("Dron-2", "cesion", "separación mínima")

    eventos = politica.events()
    assert eventos[0]["drone_id"] == "Dron-2"
    assert eventos[1]["reason"] == "HUB ocupado"


def test_the_event_log_is_bounded():
    politica = SafetyPolicy(ESCENARIO, max_events=5)

    for n in range(20):
        politica.record_event("Dron-1", "espera", f"evento {n}")

    assert len(politica.events()) == 5
