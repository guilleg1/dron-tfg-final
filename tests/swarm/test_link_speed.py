"""La velocidad de crucero se manda con el nombre nuevo y el viejo del parámetro."""
from airdrop.swarm.link import MavlinkDroneLink


class _DronFalso:
    def __init__(self):
        self.parametros = []

    def setParams(self, parametros, **_):
        self.parametros.extend(parametros)


def test_speed_is_sent_as_wp_spd_and_wpnav_speed():
    # ArduCopter 4.7 llama WP_SPD (m/s) a lo que antes era WPNAV_SPEED (cm/s)
    # y descarta el nombre que no conoce: hay que mandar los dos.
    enlace = MavlinkDroneLink("Dron-1", "tcp:127.0.0.1:5762", 41.0, 2.0)
    enlace._dron = _DronFalso()

    enlace.set_speed(7.0)

    valores = {p["ID"]: p["Value"] for p in enlace._dron.parametros}
    assert valores == {"WP_SPD": 7.0, "WPNAV_SPEED": 700.0}
