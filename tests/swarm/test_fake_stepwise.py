from airdrop.swarm.fake import FakeDroneLink


def _link(**kwargs):
    link = FakeDroneLink(drone_id="Dron-1", home_lat=41.2837, home_lon=1.9850, **kwargs)
    link.connect()
    return link


def test_by_default_a_leg_completes_in_one_check():
    link = _link()
    link.arm_and_takeoff(25.0)

    link.goto(41.2900, 1.9900, 25.0)

    assert link.has_arrived(41.2900, 1.9900, 5.0)


def test_stepwise_flight_needs_several_checks():
    link = _link(steps_per_leg=4)
    link.arm_and_takeoff(25.0)

    link.goto(41.2900, 1.9900, 25.0)

    llegadas = [link.has_arrived(41.2900, 1.9900, 5.0) for _ in range(4)]
    assert llegadas == [False, False, False, True]


def test_the_drone_moves_gradually_towards_the_target():
    link = _link(steps_per_leg=4)
    link.arm_and_takeoff(25.0)
    origen = link.telemetry()["lat"]

    link.goto(41.2900, 1.9900, 25.0)
    link.has_arrived(41.2900, 1.9900, 5.0)
    intermedio = link.telemetry()["lat"]

    assert origen < intermedio < 41.2900


def test_holding_position_freezes_progress():
    link = _link(steps_per_leg=4)
    link.arm_and_takeoff(25.0)
    link.goto(41.2900, 1.9900, 25.0)
    link.has_arrived(41.2900, 1.9900, 5.0)
    antes = link.telemetry()["lat"]

    link.hold()
    for _ in range(5):
        link.has_arrived(41.2900, 1.9900, 5.0)

    assert link.telemetry()["lat"] == antes
    assert link.held_times == 1


def test_resuming_after_a_hold_continues_the_leg():
    link = _link(steps_per_leg=4)
    link.arm_and_takeoff(25.0)
    link.goto(41.2900, 1.9900, 25.0)
    link.hold()
    link.has_arrived(41.2900, 1.9900, 5.0)
    link.resume()

    for _ in range(4):
        llegado = link.has_arrived(41.2900, 1.9900, 5.0)

    assert llegado
