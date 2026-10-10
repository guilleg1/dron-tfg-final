"""Un SITL que se para no puede dejar el hilo lector de dronLink girando."""
import socket
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

from pymavlink import mavutil

from airdrop.swarm.link import EnlaceCerrado, MavlinkDroneLink, cortar_en_eof

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "vendor"))
from dronLink.modules.message_handler import MessageHandler  # noqa: E402


def _servidor_que_cuelga():
    """Acepta una conexión y la cierra enseguida, como un SITL que se para."""
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    puerto = srv.getsockname()[1]

    def aceptar():
        conn, _ = srv.accept()
        time.sleep(0.2)
        conn.close()
        srv.close()

    threading.Thread(target=aceptar, daemon=True).start()
    return puerto


def test_the_reader_stops_when_the_autopilot_hangs_up():
    vehicle = mavutil.mavlink_connection(f"tcp:127.0.0.1:{_servidor_que_cuelga()}")
    cortar_en_eof(vehicle)
    lector = MessageHandler(vehicle)

    lector.thread.join(timeout=3)

    assert not lector.thread.is_alive()
    assert lector.running is False
    vehicle.close()


def test_eof_raises_instead_of_spinning():
    vehicle = SimpleNamespace(handle_eof=None, handle_disconnect=None)
    cortar_en_eof(vehicle)
    for nombre in ("handle_eof", "handle_disconnect"):
        try:
            getattr(vehicle, nombre)()
        except EnlaceCerrado:
            continue
        raise AssertionError(nombre)


def test_close_stops_the_reader_and_the_socket():
    cerrado = []
    handler = SimpleNamespace(running=True)
    dron = SimpleNamespace(
        message_handler=handler, state="connected",
        stop_sending_telemetry_info=lambda: None,
        vehicle=SimpleNamespace(close=lambda: cerrado.append(True)))
    link = MavlinkDroneLink("Dron-1", "tcp:127.0.0.1:5762", 41.0, 1.0)
    link._dron = dron

    link.close()

    assert handler.running is False and cerrado == [True]
    assert dron.state == "disconnected" and not link.is_connected
    link.close()   # una segunda vez no hace nada


def test_connect_gives_up_when_the_bridge_hangs_up():
    """La pasarela acepta y cierra si el puente de ese dron no está conectado.

    dronLink espera el primer heartbeat antes de que se pueda instalar el
    corte en el vehículo, así que el EOF tiene que cortar ya durante esa espera.
    """
    link = MavlinkDroneLink("Dron-1", f"tcp:127.0.0.1:{_servidor_que_cuelga()}", 41.0, 1.0)
    error = []

    def conectar():
        try:
            link.connect()
        except Exception as exc:  # noqa: BLE001
            error.append(exc)

    hilo = threading.Thread(target=conectar, daemon=True)
    hilo.start()
    hilo.join(timeout=5)

    assert not hilo.is_alive()
    assert error and isinstance(error[0], EnlaceCerrado)
