"""Enlace simulado a velocidad realista (modo demostración del portal desplegado)."""
from airdrop.swarm.fake import FakeDroneLink


def _pasos_hasta_llegar(link, lat, lon, alt):
    link.goto(lat, lon, alt)
    pasos = 0
    while not link.has_arrived(lat, lon, 1.0):
        pasos += 1
    return pasos + 1


def test_leg_duration_follows_the_distance():
    link = FakeDroneLink("D", 41.2837, 1.9850, speed_mps=7.0, step_s=0.5)
    link.connect()
    # unos 700 m hacia el norte: 700 / (7 * 0,5) = 200 pasos
    pasos = _pasos_hasta_llegar(link, 41.2837 + 0.7 / 111.2, 1.9850, 20.0)
    assert 190 <= pasos <= 210


def test_without_speed_the_original_behaviour_is_kept():
    link = FakeDroneLink("D", 41.2837, 1.9850, steps_per_leg=3)
    link.connect()
    assert _pasos_hasta_llegar(link, 41.29, 1.99, 20.0) == 3
