"""Pasarela MAVLink: troceado de mensajes, puente con token y reparto a Mission Planner."""
import asyncio
import socket
import time

import pytest

from airdrop.swarm import pasarela as mod
from airdrop.swarm.pasarela import Pasarela, split_frames


def _v2(payload=b"\x01\x02\x03", sysid=1):
    return bytes([0xFD, len(payload), 0, 0, 0, sysid, 1, 0, 0, 0]) + payload + b"\xAA\xBB"


def _v1(payload=b"\x09" * 9, sysid=2):
    return bytes([0xFE, len(payload), 0, sysid, 1, 0]) + payload + b"\xAA\xBB"


def _libre():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    puerto = s.getsockname()[1]
    s.close()
    return puerto


def test_split_frames_returns_whole_messages_and_keeps_the_rest():
    a, b = _v2(), _v1()
    buffer = bytearray(b"\x00\x13" + a + b + a[:5])

    assert split_frames(buffer) == [a, b]
    assert bytes(buffer) == a[:5], "el trozo incompleto espera al resto"


def test_split_frames_counts_the_signature_of_signed_v2_messages():
    firmado = bytes([0xFD, 2, 0x01, 0, 0, 1, 1, 0, 0, 0]) + b"\x05\x06" + b"\xCC\xDD" + bytes(13)
    assert split_frames(bytearray(firmado)) == [firmado]


@pytest.fixture()
def puertos(monkeypatch):
    base = _libre()
    monkeypatch.setattr(mod, "BRIDGE_BASE", base)
    monkeypatch.setattr(mod, "SERIAL0_BASE", _libre())
    return base


def _conectar(puerto, intentos=50):
    for _ in range(intentos):
        try:
            return socket.create_connection(("127.0.0.1", puerto), timeout=2)
        except OSError:
            time.sleep(0.05)
    raise AssertionError(f"nadie escucha en {puerto}")


def test_the_bridge_tunnels_a_drone_to_its_local_port(puertos):
    avisos = []
    p = Pasarela(port=_libre(), token="secreto", host="127.0.0.1", on_agent=avisos.append)
    p.start()

    agente = _conectar(p.port)
    agente.sendall(b"AIRDROP secreto 0\n")
    assert agente.recv(3) == b"OK\n"
    time.sleep(0.2)
    assert avisos == [0], "el portal se entera para reconectar el dron"

    enjambre = _conectar(mod.bridge_port(0))
    time.sleep(0.2)
    agente.sendall(b"telemetria")
    assert enjambre.recv(64) == b"telemetria"
    enjambre.sendall(b"orden")
    assert agente.recv(64) == b"orden"
    agente.close()
    enjambre.close()


def test_a_new_swarm_link_takes_over_from_the_old_one(puertos):
    """Al rehacer el enjambre, el enlace nuevo llega antes de que se cierre el viejo.

    El cierre del viejo no puede dejar al nuevo sin telemetría: el dron se
    quedaba esperando el primer heartbeat para siempre.
    """
    p = Pasarela(port=_libre(), token="secreto", host="127.0.0.1")
    p.start()
    agente = _conectar(p.port)
    agente.sendall(b"AIRDROP secreto 0\n")
    assert agente.recv(3) == b"OK\n"
    time.sleep(0.2)

    viejo = _conectar(mod.bridge_port(0))
    time.sleep(0.2)
    nuevo = _conectar(mod.bridge_port(0))
    time.sleep(0.2)
    viejo.close()
    time.sleep(0.2)

    agente.sendall(b"heartbeat")
    assert nuevo.recv(64) == b"heartbeat"
    nuevo.sendall(b"orden")
    assert agente.recv(64) == b"orden"
    agente.close()
    nuevo.close()

def test_the_bridge_rejects_a_wrong_token(puertos):
    p = Pasarela(port=_libre(), token="secreto", host="127.0.0.1")
    p.start()

    agente = _conectar(p.port)
    agente.sendall(b"AIRDROP otro 0\n")
    assert agente.recv(16).startswith(b"ERROR")
    assert p.status()["agents"] == []


def test_mission_planner_sees_every_drone_through_one_port(puertos):
    # Dos «autopilotos» falsos en SERIAL0 de las instancias 0 y 1.
    recibido = {0: bytearray(), 1: bytearray()}
    servidores = []
    for instancia in (0, 1):
        srv = socket.socket()
        srv.bind(("127.0.0.1", mod.SERIAL0_BASE + 10 * instancia))
        srv.listen()
        servidores.append(srv)

    p = Pasarela(port=_libre(), host="127.0.0.1", gcs_enabled=True, instances=lambda: [0, 1])
    p.start()
    gcs = _conectar(p.port)
    gcs.sendall(_v2(sysid=255))          # Mission Planner se presenta con un heartbeat
    conexiones = [srv.accept()[0] for srv in servidores]
    time.sleep(0.2)

    conexiones[0].sendall(_v2(sysid=1))
    conexiones[1].sendall(_v1(sysid=2))
    datos = b""
    limite = time.time() + 3
    while len(datos) < len(_v2()) + len(_v1()) and time.time() < limite:
        datos += gcs.recv(256)
    assert sorted(split_frames(bytearray(datos))) == sorted([_v2(sysid=1), _v1(sysid=2)])

    gcs.sendall(_v2(sysid=255))
    for c in conexiones:
        c.settimeout(2)
        assert _v2(sysid=255) in c.recv(256), "lo que manda Mission Planner llega a todos"
    for s in servidores + conexiones + [gcs]:
        s.close()


def test_without_gcs_enabled_a_planner_is_turned_away(puertos):
    p = Pasarela(port=_libre(), host="127.0.0.1", gcs_enabled=False)
    p.start()
    gcs = _conectar(p.port)
    gcs.sendall(_v2())
    gcs.settimeout(3)
    assert gcs.recv(16) == b""


def test_the_gateway_never_takes_the_web_port(monkeypatch):
    monkeypatch.setenv("PASARELA_PORT", "5700")
    monkeypatch.setenv("PORT", "5700")
    assert mod.from_env(lambda: []) is None
