"""SITL de ArduCopter en Linux, lanzado por el propio portal.

En la nube no hay Mission Planner ni Windows, pero ArduPilot publica el mismo
SITL compilado para Linux. Con ``DRONE_BACKEND=sitl`` y ``SITL_EMBEDDED=1`` el
portal arranca una instancia por dron al levantar el enjambre, en el pad que
le toca dentro del escenario activo, y se conecta a ellas por 127.0.0.1 igual
que en local: los puertos y el enlace MAVLink son los mismos.

Diferencias con el lanzador de Windows (``sitl.py``):

- El binario no viene con Mission Planner: se descarga una sola vez de
  firmware.ardupilot.org, con la versión fijada y comprobada por SHA-256, y
  el fichero de parámetros por defecto del mismo tag de ArduPilot.
- ``--serial0 tcp:0`` sin ``:wait``. Con el valor por defecto la instancia se
  queda en «Waiting for connection» hasta que alguien se conecta a SERIAL0,
  que en Windows es Mission Planner y aquí no hay nadie.
- Los procesos son hijos del portal y mueren con él. Al cambiar de escenario
  se relanzan en los pads nuevos sin reiniciar el portal.

Uso suelto, para probar sin portal:
    python -m airdrop.swarm.sitl_linux download
"""

from __future__ import annotations

import hashlib
import logging
import os
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from airdrop.config import PROJECT_DIR

log = logging.getLogger(__name__)

VERSION = "4.7.1"
BINARY_URL = (f"https://firmware.ardupilot.org/Copter/stable-{VERSION}/"
              "SITL_x86_64_linux_gnu/arducopter")
BINARY_SHA256 = "011627d41dd95640c3aca02d45283474be48721c8b1bb7a4b234d38b69063482"
DEFAULTS_URL = ("https://raw.githubusercontent.com/ArduPilot/ardupilot/"
                f"Copter-{VERSION}/Tools/autotest/default_params/copter.parm")

BOOT_TIMEOUT_S = 30.0


def sitl_dir() -> Path:
    return Path(os.environ.get("SITL_DIR") or PROJECT_DIR / "sitl")


def run_dir() -> Path:
    return Path(os.environ.get("SITL_RUN_DIR") or "/tmp/airdrop-sitl")


def speedup() -> str:
    # En la nube los drones vuelan para que los vea un visitante: tiempo real.
    return os.environ.get("SITL_SPEEDUP") or "1"


def enabled() -> bool:
    return (os.environ.get("SITL_EMBEDDED") or "").strip().lower() in ("1", "true", "si", "sí")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fp:
        for bloque in iter(lambda: fp.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def ensure_files() -> tuple[Path, Path]:
    """Binario y parámetros por defecto, descargados si faltan.

    El binario se comprueba por hash: si la descarga se corta, un ejecutable a
    medias no arranca y el síntoma sería un enjambre entero sin conexión.
    """
    carpeta = sitl_dir()
    carpeta.mkdir(parents=True, exist_ok=True)
    binario = carpeta / "arducopter"
    defaults = carpeta / "copter.parm"

    if not binario.exists() or _sha256(binario) != BINARY_SHA256:
        log.info("descargando el SITL de ArduCopter %s", VERSION)
        temporal = binario.with_suffix(".part")
        urllib.request.urlretrieve(BINARY_URL, temporal)
        if _sha256(temporal) != BINARY_SHA256:
            temporal.unlink(missing_ok=True)
            raise RuntimeError("el SITL descargado no coincide con el hash esperado")
        temporal.replace(binario)
        binario.chmod(0o755)
    if not defaults.exists():
        urllib.request.urlretrieve(DEFAULTS_URL, defaults)
    log.info("SITL de ArduCopter %s en %s, SHA-256 comprobado", VERSION, binario)
    return binario, defaults


def build_command(record, binary, defaults) -> list[str]:
    """Línea de comandos de una instancia. ``-I`` va el primero, como en Windows."""
    return [
        str(binary),
        "-I", str(record.instance),
        "--model", "+",
        "--speedup", speedup(),
        "--defaults", str(defaults),
        "--home", f"{record.home_lat},{record.home_lon},0,0",
        "--serial0", "tcp:0",
        "--sysid", str(record.sysid),
    ]


def serial1_port(record) -> int:
    return 5762 + 10 * int(record.instance)


class EmbeddedSitl:
    """Las instancias SITL de la flota, como procesos hijos del portal."""

    def __init__(self, binary=None, defaults=None, root=None):
        self.binary = binary
        self.defaults = defaults
        self.root = Path(root) if root else run_dir()
        self._procs: dict[str, subprocess.Popen] = {}
        self._firmas: dict[str, tuple] = {}

    @staticmethod
    def _firma(record) -> tuple:
        """Lo que obliga a relanzar una instancia si cambia."""
        return (int(record.instance), int(record.sysid),
                round(float(record.home_lat), 7), round(float(record.home_lon), 7),
                speedup())

    def start(self, records, timeout: float = BOOT_TIMEOUT_S) -> dict[str, bool]:
        """Deja en marcha una instancia por dron habilitado.

        Solo se relanzan las que hace falta: las nuevas, las muertas y las que
        cambian de pad, de identificador o de aceleración. Las demás siguen
        volando sin enterarse, así que quitar un dron de la flota para solo su
        instancia y no reinicia las de los otros. Para empezar de cero, ``stop``
        antes.

        Devuelve qué instancias están listas. Una que no arranca no impide las
        demás: su dron aparecerá sin conexión en el panel, como en local.
        """
        if self.binary is None or self.defaults is None:
            self.binary, self.defaults = ensure_files()
        deseados = {r.drone_id: r for r in records if r.enabled}
        for drone_id in list(self._procs):
            record = deseados.get(drone_id)
            if (record is None or self._procs[drone_id].poll() is not None
                    or self._firmas.get(drone_id) != self._firma(record)):
                self.stop_one(drone_id)
        nuevos = [r for r in deseados.values() if r.drone_id not in self._procs]
        for record in nuevos:
            carpeta = self.root / record.drone_id
            carpeta.mkdir(parents=True, exist_ok=True)
            # Cada instancia en su carpeta: eeprom.bin y logs no se comparten.
            # Se borra la eeprom para que el home y los parámetros no arrastren
            # los de un escenario anterior.
            (carpeta / "eeprom.bin").unlink(missing_ok=True)
            salida = open(carpeta / "sitl.log", "wb")
            self._procs[record.drone_id] = subprocess.Popen(
                build_command(record, self.binary, self.defaults),
                cwd=carpeta, stdout=salida, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL)
            self._firmas[record.drone_id] = self._firma(record)
            log.info("SITL %s lanzado: SYSID %s, pid %d, SERIAL0 %d, SERIAL1 %d, "
                     "home %.6f,%.6f, x%s", record.drone_id, record.sysid,
                     self._procs[record.drone_id].pid, serial1_port(record) - 2,
                     serial1_port(record), record.home_lat, record.home_lon, speedup())
        listos = self._wait_ready(nuevos, timeout) if nuevos else {}
        for drone_id in deseados:
            listos.setdefault(drone_id, self._procs[drone_id].poll() is None)
        return listos

    def _wait_ready(self, records, timeout) -> dict[str, bool]:
        """Listo = el log dice que SERIAL1 escucha y el proceso sigue vivo.

        No se sondea el puerto: un cliente que se conecta y se va le cuesta al
        autopiloto un hueco en el enlace, y en Windows llegaba a matarlo.
        """
        pendientes = {r.drone_id: r for r in records if r.drone_id in self._procs}
        listos: dict[str, bool] = {}
        limite = time.time() + timeout
        while pendientes and time.time() < limite:
            for drone_id, record in list(pendientes.items()):
                proc = self._procs[drone_id]
                if proc.poll() is not None:
                    listos[drone_id] = False
                    del pendientes[drone_id]
                    continue
                log_file = self.root / drone_id / "sitl.log"
                texto = log_file.read_text(errors="replace") if log_file.exists() else ""
                if f"SERIAL1 on TCP port {serial1_port(record)}" in texto:
                    listos[drone_id] = True
                    del pendientes[drone_id]
            time.sleep(0.2)
        for drone_id in pendientes:
            listos[drone_id] = False
        # SERIAL1 abre antes de que el EKF tenga posición; el enlace espera a
        # su vez el heartbeat, así que basta con un margen corto.
        time.sleep(1.0)
        listos_ok = [d for d, ok in listos.items() if ok]
        if listos_ok:
            log.info("SITL listo (SERIAL1 escuchando): %s", ", ".join(listos_ok))
        fallidos = [d for d, ok in listos.items() if not ok]
        if fallidos:
            log.error("SITL sin arrancar: %s", ", ".join(fallidos))
        return listos

    def status(self) -> dict[str, bool]:
        return {d: p.poll() is None for d, p in self._procs.items()}

    def instances(self, records) -> list[dict]:
        """Estado de cada instancia para la consola, sin abrir sockets."""
        filas = []
        for record in records:
            proc = self._procs.get(record.drone_id)
            log_file = self.root / record.drone_id / "sitl.log"
            texto = log_file.read_text(errors="replace") if log_file.exists() else ""
            filas.append({
                "drone_id": record.drone_id,
                "sysid": record.sysid,
                "connection": record.connection,
                "pid": proc.pid if proc is not None else None,
                "vivo": proc is not None and proc.poll() is None,
                "escuchando": f"SERIAL1 on TCP port {serial1_port(record)}" in texto,
                "panic": "PANIC" in texto,
                "defaults_ok": True,
            })
        return filas

    def stop_one(self, drone_id: str) -> None:
        """Para la instancia de un dron, si la hay."""
        proc = self._procs.pop(drone_id, None)
        self._firmas.pop(drone_id, None)
        if proc is None or proc.poll() is not None:
            return
        log.info("SITL %s parado (pid %d)", drone_id, proc.pid)
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

    def stop(self) -> None:
        self._firmas.clear()
        for proc in self._procs.values():
            if proc.poll() is None:
                proc.send_signal(signal.SIGTERM)
        for proc in self._procs.values():
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        self._procs.clear()


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["download"]:
        binario, defaults = ensure_files()
        print(binario, defaults)
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
