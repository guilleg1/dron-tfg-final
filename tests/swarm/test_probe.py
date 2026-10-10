import socket

from airdrop.swarm.probe import probe, scan


def _puerto_libre():
    """Un puerto que con seguridad no tiene nada escuchando."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_a_closed_port_is_reported_without_raising():
    resultado = probe(f"tcp:127.0.0.1:{_puerto_libre()}", timeout_s=0.5)

    assert resultado["ok"] is False
    assert resultado["error"] == "puerto cerrado"
    assert resultado["sysid"] is None


def test_the_probe_never_raises_on_a_malformed_connection():
    resultado = probe("esto-no-es-una-conexion", timeout_s=0.5)

    assert resultado["ok"] is False
    assert resultado["error"], "un fallo debe explicarse, no propagarse"


def test_the_result_always_carries_the_connection_string():
    conexion = f"tcp:127.0.0.1:{_puerto_libre()}"

    assert probe(conexion, timeout_s=0.5)["connection"] == conexion


def test_scanning_an_empty_range_finds_nothing_quickly():
    libre = _puerto_libre()

    assert scan(ports=[libre], timeout_s=0.3) == []


def test_serial0_is_refused_without_touching_the_socket():
    # SERIAL0 admite un solo cliente y sondearlo mata la instancia: se conecta,
    # se va, y el autopiloto cae con "Closed connection on SERIAL0". Pasó de
    # verdad el 2026-08-06: «Buscar autopilotos» dejó el enjambre muerto.
    resultado = probe("tcp:127.0.0.1:5760", timeout_s=0.5)

    assert resultado["ok"] is False
    assert "SERIAL0" in resultado["error"]


def test_the_scan_never_touches_serial0():
    from airdrop.swarm.probe import SCAN_PORTS

    assert SCAN_PORTS, "el escaneo no puede quedarse sin puertos"
    assert not [p for p in SCAN_PORTS if p % 10 == 0], (
        "escanear SERIAL0 mata las instancias que se venía a encontrar")


def test_a_tcp_port_with_no_mavlink_behind_is_not_reported_ok():
    # Un socket que acepta y no dice nada: el puerto esta abierto pero no hay
    # autopiloto. La sonda debe distinguirlo de un enlace bueno.
    servidor = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    servidor.bind(("127.0.0.1", 0))
    servidor.listen(1)
    puerto = servidor.getsockname()[1]
    try:
        resultado = probe(f"tcp:127.0.0.1:{puerto}", timeout_s=1.0)
        assert resultado["ok"] is False
        assert resultado["error"]
    finally:
        servidor.close()
