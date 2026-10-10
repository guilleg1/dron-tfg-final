from airdrop.swarm.models import IDLE, IN_TRANSIT, OFFLINE, DroneRecord, DroneRuntime


def _record(drone_id="Dron-1", category="medio", instance=0):
    return DroneRecord(
        drone_id=drone_id, sysid=instance + 1, instance=instance,
        category=category, connection=f"tcp:127.0.0.1:{5760 + 10 * instance}",
        home_lat=41.2837, home_lon=1.9850,
    )


def test_spec_comes_from_the_category_with_the_real_drone_id():
    record = _record(drone_id="Dron-3", category="pesado")

    spec = record.spec

    assert spec.drone_id == "Dron-3"
    assert spec.max_payload_kg == 4.0
    assert spec.battery_capacity_wh == 360.0


def test_battery_pct_is_a_percentage_of_capacity():
    runtime = DroneRuntime(drone_id="Dron-1", battery_wh=111.0, battery_capacity_wh=222.0)

    assert runtime.battery_pct == 50.0


def test_battery_pct_is_zero_without_capacity():
    assert DroneRuntime(drone_id="Dron-1").battery_pct == 0.0


def test_only_an_idle_drone_is_available():
    assert DroneRuntime(drone_id="Dron-1", state=IDLE).is_available
    assert not DroneRuntime(drone_id="Dron-1", state=IN_TRANSIT).is_available
    assert not DroneRuntime(drone_id="Dron-1", state=OFFLINE).is_available


def test_as_dict_carries_what_the_admin_panel_needs():
    runtime = DroneRuntime(
        drone_id="Dron-2", state=IN_TRANSIT, battery_wh=74.0,
        battery_capacity_wh=148.0, lat=41.28, lon=1.98, alt=30.0,
        current_order_id=7, detail="yendo a cliente",
    )

    data = runtime.as_dict()

    assert data["drone_id"] == "Dron-2"
    assert data["state"] == IN_TRANSIT
    assert data["battery_pct"] == 50.0
    assert data["current_order_id"] == 7
    assert data["detail"] == "yendo a cliente"
