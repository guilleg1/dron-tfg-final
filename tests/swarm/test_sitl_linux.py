"""Lanzador del SITL de Linux que usa el portal en la nube."""
from types import SimpleNamespace

import pytest

from airdrop.swarm import sitl_linux


def _record(i=2):
    return SimpleNamespace(drone_id=f"Dron-{i + 1}", instance=i, sysid=i + 1,
                           home_lat=41.27, home_lon=1.98, enabled=True)


def test_the_command_starts_with_the_instance_and_does_not_wait_on_serial0():
    cmd = sitl_linux.build_command(_record(), "/x/arducopter", "/x/copter.parm")

    assert cmd[1:3] == ["-I", "2"]
    # Sin «:wait» la instancia no se queda esperando a una estación de tierra.
    assert cmd[cmd.index("--serial0") + 1] == "tcp:0"
    assert "--sysid" in cmd and cmd[cmd.index("--sysid") + 1] == "3"


def test_serial1_is_the_port_the_portal_connects_to():
    assert sitl_linux.serial1_port(_record(0)) == 5762
    assert sitl_linux.serial1_port(_record(3)) == 5792


def test_a_corrupt_download_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("SITL_DIR", str(tmp_path))

    def descarga_rota(url, destino):
        open(destino, "wb").write(b"no es un ejecutable")

    monkeypatch.setattr(sitl_linux.urllib.request, "urlretrieve", descarga_rota)
    with pytest.raises(RuntimeError):
        sitl_linux.ensure_files()
    assert not (tmp_path / "arducopter").exists()


def test_it_is_only_enabled_when_asked(monkeypatch):
    monkeypatch.delenv("SITL_EMBEDDED", raising=False)
    assert not sitl_linux.enabled()
    monkeypatch.setenv("SITL_EMBEDDED", "1")
    assert sitl_linux.enabled()


# ── Arranque incremental ──────────────────────────────────────────────────
FALSO = """#!/bin/sh
# Hace de ArduCopter: anuncia SERIAL1 en el puerto de su instancia y espera.
while [ $# -gt 0 ]; do [ "$1" = "-I" ] && I=$2; shift; done
echo "SERIAL1 on TCP port $((5762 + 10 * I))"
exec sleep 60
"""


@pytest.fixture()
def falso(tmp_path):
    binario = tmp_path / "arducopter"
    binario.write_text(FALSO)
    binario.chmod(0o755)
    sitl = sitl_linux.EmbeddedSitl(binary=binario, defaults=tmp_path / "copter.parm",
                                   root=tmp_path / "run")
    yield sitl
    sitl.stop()


def _pids(sitl):
    return {d: p.pid for d, p in sitl._procs.items() if p.poll() is None}


def test_removing_a_drone_stops_only_its_instance(falso):
    flota = [_record(i) for i in range(3)]
    assert all(falso.start(flota, timeout=5).values())
    antes = _pids(falso)

    listos = falso.start([flota[0], flota[2]], timeout=5)

    assert set(listos) == {"Dron-1", "Dron-3"} and all(listos.values())
    assert _pids(falso) == {"Dron-1": antes["Dron-1"], "Dron-3": antes["Dron-3"]}


def test_a_drone_that_moves_pad_is_relaunched_and_the_rest_are_not(falso):
    flota = [_record(i) for i in range(2)]
    falso.start(flota, timeout=5)
    antes = _pids(falso)

    movido = SimpleNamespace(**{**vars(flota[1]), "home_lat": 41.30})
    falso.start([flota[0], movido], timeout=5)

    despues = _pids(falso)
    assert despues["Dron-1"] == antes["Dron-1"]
    assert despues["Dron-2"] != antes["Dron-2"]


def test_stop_then_start_relaunches_everything(falso):
    flota = [_record(i) for i in range(2)]
    falso.start(flota, timeout=5)
    antes = _pids(falso)

    falso.stop()
    falso.start(flota, timeout=5)

    assert not set(_pids(falso).values()) & set(antes.values())
