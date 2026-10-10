from airdrop.swarm.fake import FakeDroneLink


def _link():
    return FakeDroneLink(drone_id="Dron-1", home_lat=41.2837, home_lon=1.9850)


def test_starts_on_its_pad_and_disconnected():
    link = _link()

    assert not link.is_connected
    assert link.telemetry()["lat"] == 41.2837


def test_connecting_reports_the_pad_position():
    link = _link()

    link.connect()

    assert link.is_connected
    telemetry = link.telemetry()
    assert telemetry["lat"] == 41.2837
    assert telemetry["alt"] == 0.0


def test_takeoff_reaches_the_requested_altitude():
    link = _link()
    link.connect()

    link.arm_and_takeoff(30.0)

    assert link.telemetry()["alt"] == 30.0


def test_goto_records_the_waypoint_without_moving_yet():
    # goto es no bloqueante: ordena y vuelve. El dron avanza en has_arrived,
    # que es el punto de control donde el ejecutor comprueba conflictos.
    link = _link()
    link.connect()
    link.arm_and_takeoff(25.0)

    link.goto(41.2900, 1.9900, 25.0)

    assert link.visited == [(41.2900, 1.9900, 25.0)]
    assert link.telemetry()["lat"] == 41.2837, "aun no ha empezado a moverse"

    link.has_arrived(41.2900, 1.9900, 5.0)

    assert link.telemetry()["lat"] == 41.2900


def test_land_puts_it_back_on_the_ground():
    link = _link()
    link.connect()
    link.arm_and_takeoff(25.0)

    link.land()

    assert link.telemetry()["alt"] == 0.0


def test_abort_stops_accepting_movement():
    link = _link()
    link.connect()
    link.arm_and_takeoff(25.0)

    link.abort("RTL")

    assert link.aborted == "RTL"
    assert link.telemetry()["lat"] == 41.2837, "RTL devuelve el dron a su pad"


def test_a_link_that_cannot_connect_stays_offline():
    link = FakeDroneLink(drone_id="Dron-9", home_lat=0.0, home_lon=0.0,
                         fail_on_connect=True)

    try:
        link.connect()
    except ConnectionError:
        pass

    assert not link.is_connected
