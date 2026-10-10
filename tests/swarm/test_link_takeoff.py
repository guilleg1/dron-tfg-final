"""El despegue no puede bloquear el hilo del ejecutor.

``dronLink._takeOff()`` espera la altitud con ``wait_for_message(timeout=None)``
y no vuelve nunca si el autopiloto se queda a media subida. El sintoma es un
dron parado en el parking, en estado «despegando», sin avanzar y sin error, y
con el resto de la flota esperando la vertical. Estas pruebas fijan que el
enlace manda el comando y vigila por su cuenta.
"""

import pytest

from airdrop.swarm import link as modulo
from airdrop.swarm.link import DroneLinkError, MavlinkDroneLink


class _Mav:
    def __init__(self):
        self.comandos = []

    def command_long_send(self, sistema, componente, comando, confirmacion, *params):
        self.comandos.append((comando, params))


class _Vehicle:
    def __init__(self):
        self.target_system = 1
        self.target_component = 1
        self.mav = _Mav()
        self.textos = []

    def motors_armed(self):
        return True

    def recv_match(self, type=None, blocking=False):  # noqa: A002
        return self.textos.pop(0) if self.textos else None


class _Dron:
    def __init__(self):
        self.vehicle = _Vehicle()
        self.state = "connected"


class _Texto:
    def __init__(self, texto):
        self.text = texto


def _enlace(alturas):
    """Enlace con una secuencia de altitudes simuladas."""
    enlace = MavlinkDroneLink("Dron-1", "tcp:127.0.0.1:5762", 41.28, 1.98)
    enlace._dron = _Dron()
    secuencia = list(alturas)

    def telemetria():
        return {"alt": secuencia.pop(0) if secuencia else (alturas[-1] if alturas else 0.0)}

    enlace.telemetry = telemetria
    return enlace


def test_the_takeoff_command_is_sent_with_the_target_altitude():
    enlace = _enlace([0.0, 10.0, 30.0, 50.0])

    enlace._takeoff(50.0)

    comando, params = enlace._dron.vehicle.mav.comandos[-1]
    assert comando == modulo.TAKEOFF_COMMAND
    assert params[-1] == pytest.approx(50.0), "la altitud va en el ultimo parametro"


def test_a_stalled_climb_fails_instead_of_hanging(monkeypatch):
    """Se queda a 8 m de los 50 pedidos: error, no espera infinita."""
    monkeypatch.setattr(modulo, "TAKEOFF_TIMEOUT_S", 2.0)
    enlace = _enlace([8.0])

    with pytest.raises(DroneLinkError) as fallo:
        enlace._takeoff(50.0)

    assert "no alcanzó la altitud" in str(fallo.value)
    assert "8.0 m" in str(fallo.value), "hay que decir hasta donde llego"


def test_the_autopilot_reason_is_reported_when_the_climb_stalls(monkeypatch):
    """Sin el motivo, «no subio» obliga a conectar Mission Planner a mano."""
    monkeypatch.setattr(modulo, "TAKEOFF_TIMEOUT_S", 2.0)
    enlace = _enlace([8.0])
    enlace._dron.vehicle.textos = [_Texto("EKF3 IMU0 stopped aiding")]

    with pytest.raises(DroneLinkError) as fallo:
        enlace._takeoff(50.0)

    assert "EKF3 IMU0 stopped aiding" in str(fallo.value)


def test_reaching_ninety_percent_of_the_altitude_is_enough():
    """Exigir el 100% dejaba el despegue colgado por unos centimetros."""
    enlace = _enlace([0.0, 45.5])

    enlace._takeoff(50.0)   # no debe lanzar
