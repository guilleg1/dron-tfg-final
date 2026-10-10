"""Lanzador de instancias SITL.

Lee la flota de la base de datos —la misma que usa el portal— y arranca un
``ArduCopter.exe`` por dron. Que la configuración la posea Python es
deliberado: si el script de PowerShell tuviera su propia copia de puertos y
posiciones, acabaría divergiendo del portal.

Las trampas del binario en Windows están documentadas en docs/swarm/SITL.md.
Las que afectan a este fichero:

- ``-I`` debe ir el primero de todos los argumentos, o el desplazamiento de
  puertos se ignora y todas las instancias pelean por el 5760.
- La ruta de ``--defaults`` lleva un espacio (``Mission Planner``) y necesita
  comillas dobles dentro de las simples al pasar por PowerShell.
- Las instancias se lanzan con ``Start-Process``, no con ``Popen``, o mueren
  con el shell que las arranca.
- El estado NO se comprueba sondeando el puerto: esa sonda mata instancias.

Uso:
    python -m airdrop.swarm.sitl launch
    python -m airdrop.swarm.sitl status
    python -m airdrop.swarm.sitl stop
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from airdrop.config import PROJECT_DIR

# Dónde busca Mission Planner su SITL. Son varias porque OneDrive redirige la
# carpeta de documentos y, además, el nombre cambia con el idioma de Windows:
# el mismo proyecto en dos equipos daba rutas distintas y había que definir
# SITL_BINARY a mano en cada uno. Se prueban todas y se usa la que exista.
_CARPETAS_DOCUMENTOS = (
    ("Documents",),
    ("Documentos",),
    ("OneDrive", "Documents"),
    ("OneDrive", "Documentos"),
)


def _candidatos_binario():
    for partes in _CARPETAS_DOCUMENTOS:
        yield Path.home().joinpath(*partes, "Mission Planner", "sitl",
                                   "ArduCopter.exe")


def _autodetectar_binario() -> Path:
    """Primera ruta que exista; si ninguna, la clásica para el mensaje de error."""
    for ruta in _candidatos_binario():
        if ruta.is_file():
            return ruta
    return Path.home() / "Documents" / "Mission Planner" / "sitl" / "ArduCopter.exe"


DEFAULT_BINARY = _autodetectar_binario()
RUN_ROOT = PROJECT_DIR / "sitl_run"
PIDS_FILE = RUN_ROOT / "pids.json"
BOOT_WAIT_S = 12


def binary_path() -> Path:
    """Binario a usar: ``SITL_BINARY`` si está definido, si no el que se encuentre.

    La búsqueda se repite en cada llamada y no se cachea en el import: el SITL
    aparece la primera vez que Mission Planner lanza una simulación, que
    normalmente es *después* de haber arrancado el portal.
    """
    definido = os.environ.get("SITL_BINARY")
    return Path(definido) if definido else _autodetectar_binario()


def defaults_path() -> Path:
    """Fichero de parámetros por defecto, junto al binario que se vaya a usar.

    Se deriva de ``binary_path()``, no de ``DEFAULT_BINARY``: con OneDrive
    redirigiendo «Documentos», la ruta por defecto no existe y hay que apuntar
    ``SITL_BINARY`` a otra copia. Derivándolo del binario por defecto, el
    ``.parm`` seguía buscándose en la carpeta que no existe, y la única salida
    era definir también ``SITL_PARAMS`` a mano.
    """
    return Path(os.environ.get("SITL_PARAMS")
                or binary_path().parent / "default_params" / "copter.parm")


def speedup() -> str:
    """Factor de aceleración de la simulación.

    1 es tiempo real, que es lo correcto para una demostración. Para verificar
    de extremo a extremo sin esperar siete minutos por reparto, SITL_SPEEDUP=5
    acorta mucho la espera sin alterar la lógica.
    """
    return str(os.environ.get("SITL_SPEEDUP") or "1")


def _ps_quote(value) -> str:
    """Entrecomilla un argumento para PowerShell.

    Doble entrecomillado a propósito. PowerShell consume las comillas simples
    al construir la lista de argumentos, así que un valor con espacios —como
    la ruta de ``--defaults``, que pasa por ``Mission Planner``— llegaría
    partido en dos al ejecutable. Las comillas dobles interiores sobreviven y
    mantienen el argumento entero.

    Sin esto, ArduCopter arranca, acepta la conexión TCP y muere después con
    ``PANIC: Failed to load defaults``, que en el cliente se ve como un reset
    de conexión y despista por completo.
    """
    text = str(value)
    if " " in text:
        text = '"' + text + '"'
    return "'" + text.replace("'", "''") + "'"


def _spawn(cmd, cwd, stdout_path, stderr_path):
    """Lanza una instancia SITL que sobrevive al proceso que la arranca.

    En Windows no vale ``subprocess.Popen`` a secas, ni siquiera con
    ``DETACHED_PROCESS`` y ``CREATE_BREAKAWAY_FROM_JOB``: si el shell agrupa
    sus procesos en un Job Object que no permite breakaway, las instancias
    caen con él y en su log solo queda un ``Closed connection on SERIAL0``.

    ``Start-Process`` de PowerShell sí crea procesos independientes, así que
    se delega en él. Devuelve el PID, que es lo único que necesita ``stop``.

    En Linux y macOS un Popen normal con ``start_new_session`` ya basta.
    """
    if os.name != "nt":
        proc = subprocess.Popen(
            cmd, cwd=cwd, start_new_session=True,
            stdout=open(stdout_path, "w", encoding="utf-8", errors="replace"),
            stderr=open(stderr_path, "w", encoding="utf-8", errors="replace"),
        )
        return proc.pid

    # El PID se escribe a un fichero en vez de capturarse por tubería: el
    # proceso nieto hereda los descriptores de `capture_output` y PowerShell
    # se queda esperando a que se cierren, colgando la llamada.
    pid_file = Path(cwd) / "pid.txt"
    pid_file.unlink(missing_ok=True)
    argumentos = ", ".join(_ps_quote(a) for a in cmd[1:])
    script = (
        f"$p = Start-Process -FilePath {_ps_quote(cmd[0])} "
        f"-ArgumentList {argumentos} "
        f"-WorkingDirectory {_ps_quote(cwd)} "
        f"-RedirectStandardOutput {_ps_quote(stdout_path)} "
        f"-RedirectStandardError {_ps_quote(stderr_path)} "
        f"-WindowStyle Hidden -PassThru; "
        f"Set-Content -Path {_ps_quote(pid_file)} -Value $p.Id"
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        timeout=30, check=True,
    )
    return int(pid_file.read_text(encoding="utf-8").strip())


def working_dir(record, root=None) -> Path:
    """Directorio propio por instancia.

    ArduPilot escribe su eeprom.bin y sus logs en el directorio de trabajo; dos
    instancias compartiéndolo se corrompen entre sí.
    """
    return Path(root or RUN_ROOT) / record.drone_id


def gcs_port(record) -> int:
    """Puerto TCP por el que Mission Planner mira este dron.

    SERIAL0 lo ocupa el portal y admite un solo cliente. Mission Planner usa
    SERIAL2, al que las instancias se conectan como clientes: es el reparto
    que ya hace el ``sitl.bat`` de Mission Planner.

    Se intentó dar a Mission Planner una salida UDP propia con
    ``--serial1 udpclient:...``, pero el binario que trae Mission Planner no
    acepta ese formato de dispositivo y aborta mostrando su ayuda.
    """
    base = int(os.environ.get("SITL_GCS_PORT") or 5772)
    return base + 10 * record.instance


def build_command(record, binary, defaults) -> list[str]:
    """Línea de comandos de una instancia. ``-I`` va el primero, siempre.

    Sin ``-P``. El binario que distribuye Mission Planner dejó de aceptar esa
    opción —``--help`` ya no la lista— y ante un argumento desconocido no
    avisa: imprime su ayuda por stdout y sale con el proceso muerto, que es
    como se manifiesta el fallo en ``status`` («PROCESO MUERTO», sin PANIC ni
    error en stderr). El síntoma es indistinguible de un fallo de arranque.

    Lo único que se pasaba por ahí era ``SERIAL1_PROTOCOL=2``, y resulta
    innecesario: 2 (MAVLink2) ya es el valor por defecto de ArduCopter, y la
    instancia abre SERIAL1 en 5762 + 10*instancia por su cuenta. Verificado a
    mano: ``bind port 5762 for SERIAL1``.

    Si algún día hiciera falta forzar parámetros, la vía que sí sobrevive es
    un fichero ``.parm`` propio añadido a ``--defaults`` separado por comas.
    """
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


def port_of(record) -> int:
    return int(record.connection.rsplit(":", 1)[1])


def _tasklist_matches(salida: str, pid: int, image: str) -> bool:
    """¿Dice esta salida de ``tasklist`` que el PID es de esa imagen?

    Separado para poder probarlo: la salida real depende del idioma de Windows
    y de que haya procesos que coincidan, y nada de eso se puede reproducir
    desde un test.
    """
    esperado = str(image).lower()
    for linea in salida.splitlines():
        campos = [campo.strip().strip('"') for campo in linea.split('","')]
        if len(campos) >= 2 and campos[1] == str(pid):
            return campos[0].lower() == esperado
    return False


def _is_alive(pid: int, image: str | None = None) -> bool:
    """¿Sigue vivo **este** proceso? Sin abrir sockets contra él.

    Deliberadamente NO se comprueba el estado sondeando el puerto TCP. SERIAL0
    de SITL admite un solo cliente, y abrir y cerrar una conexión para ver si
    responde deja al autopiloto con un ``Closed connection on SERIAL0`` y a
    veces lo tumba. La sonda que debía diagnosticar el problema lo causaba.
    """
    if os.name == "nt":
        # Salida en CSV y comparación por columna, no ``str(pid) in stdout``.
        # ``tasklist`` imprime también el consumo de memoria («12.032 KB»), así
        # que la búsqueda por subcadena daba por vivo un proceso muerto en
        # cuanto sus cifras aparecían en cualquier otra columna.
        #
        # Se comprueba además el nombre de la imagen. Windows reutiliza los
        # PID deprisa, y un PID de una instancia caída acaba siendo de un
        # ``svchost``: sin este filtro, ``status`` daba OK con las cuatro
        # instancias muertas, que es el peor error posible aquí.
        salida = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"],
            capture_output=True, text=True, check=False,
        )
        return _tasklist_matches(salida.stdout, pid, image or binary_path().name)
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _read_pids() -> dict:
    if not PIDS_FILE.exists():
        return {}
    try:
        return json.loads(PIDS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _records():
    from sqlalchemy import create_engine  # noqa: PLC0415

    from airdrop.api.data import DEFAULT_SQLITE, _normalize_url  # noqa: PLC0415
    from airdrop.swarm.repository import FleetRepository  # noqa: PLC0415
    from airdrop.swarm.scenario_repository import ScenarioRepository  # noqa: PLC0415

    url = _normalize_url(os.environ.get("DATABASE_URL") or DEFAULT_SQLITE)
    engine = create_engine(url, future=True)
    escenarios = ScenarioRepository(engine)
    escenarios.seed_if_empty()
    return FleetRepository(engine).seed_if_empty(escenarios.active())


def launch() -> int:
    binary, defaults = binary_path(), defaults_path()
    if not binary.exists():
        print(f"No se encontró el binario SITL en {binary}.")
        print("Define SITL_BINARY apuntando a ArduCopter.exe.")
        return 1

    # El fichero de parámetros se valida ANTES de lanzar nada. Ante un
    # ``--defaults`` que no es un .parm —el caso real fue SITL_PARAMS apuntando
    # por error al propio ArduCopter.exe— el autopiloto no protesta: arranca,
    # acepta la conexión, publica telemetría y GPS con fix... pero sin
    # FRAME_CLASS, así que rechaza todo armado con «PreArm: Motors: Check frame
    # class and type». Desde el portal eso se ve como «no se pudo armar» y no
    # apunta a la línea de comandos por ningún lado.
    if not defaults.is_file() or defaults.suffix.lower() != ".parm":
        print(f"El fichero de parámetros por defecto no es válido: {defaults}")
        if not defaults.is_file():
            print("      no existe.")
        else:
            print("      no es un .parm.")
        print("Define SITL_PARAMS apuntando a default_params/copter.parm, o")
        print("déjala sin definir para usar el que hay junto al binario:")
        print(f"      {binary.parent / 'default_params' / 'copter.parm'}")
        print("Sin él las instancias arrancan sin FRAME_CLASS y no arman.")
        return 1

    RUN_ROOT.mkdir(parents=True, exist_ok=True)
    pids = {}
    for record in _records():
        if not record.enabled:
            continue
        wd = working_dir(record)
        wd.mkdir(parents=True, exist_ok=True)
        cmd = build_command(record, binary, defaults)
        pid = _spawn(cmd, str(wd), wd / "stdout.log", wd / "stderr.log")
        pids[record.drone_id] = pid
        print(f"  {record.drone_id}  SYSID {record.sysid}  {record.connection}  pid {pid}")

    PIDS_FILE.write_text(json.dumps(pids), encoding="utf-8")
    print(f"\nEsperando {BOOT_WAIT_S} s a que arranquen...")
    time.sleep(BOOT_WAIT_S)
    return status()


def status() -> int:
    """Estado de cada instancia, a partir del proceso y de su log.

    Una instancia está sana si su proceso vive, su log dice que abrió el
    puerto al que va a conectarse el portal, y no hay ``PANIC``. El PANIC se
    comprueba siempre: el binario acepta la conexión TCP y muere justo
    después, así que mirar solo el puerto lo daría por bueno.

    El puerto se busca en **cualquier** SERIAL, no en SERIAL0. La instancia
    abre tres —SERIAL0 en 5760+10i, SERIAL1 en +2, SERIAL2 en +3— y el portal
    usa SERIAL1 para dejarle SERIAL0 a Mission Planner. Exigir
    ``SERIAL0 on TCP port <puerto de connection>`` no casaba nunca y daba
    «SIN SERIAL0» con las cuatro instancias sanas.

    Se distingue además el caso del argumento no soportado. Ante una opción
    que no reconoce, el binario no da error: vuelca su ayuda por stdout y
    sale. Sin mirar el log eso se ve solo como «PROCESO MUERTO», que apunta a
    cualquier sitio menos a la línea de comandos.
    """
    pids = _read_pids()
    fallos = 0
    for record in _records():
        if not record.enabled:
            continue
        port = port_of(record)
        wd = working_dir(record)
        texto = ""
        for nombre in ("stdout.log", "stderr.log"):
            fichero = wd / nombre
            if fichero.exists():
                texto += fichero.read_text(encoding="utf-8", errors="replace")

        pid = pids.get(record.drone_id)
        vivo = bool(pid) and _is_alive(int(pid))
        panic = "PANIC" in texto
        ayuda = "display this help information" in texto
        ocupado = "Address already in use" in texto
        escuchando = re.search(rf"SERIAL\d on TCP port {port}\b", texto) is not None
        ok = vivo and escuchando and not panic and not ayuda and not ocupado

        if ok:
            estado = "OK"
        elif panic:
            estado = "PANIC"
        elif ayuda:
            estado = "ARGUMENTO NO SOPORTADO"
        elif ocupado:
            estado = "PUERTO OCUPADO"
        elif not vivo:
            estado = "PROCESO MUERTO"
        else:
            estado = f"SIN PUERTO {port}"
        print(f"  {record.drone_id}  puerto {port}  {estado}")
        if panic:
            linea = next((l for l in texto.splitlines() if "PANIC" in l), "")
            print(f"      {linea.strip()}")
            print("      revisa docs/swarm/SITL.md")
        if ocupado:
            # Casi siempre son instancias de un lanzamiento anterior que no se
            # pararon, o una simulacion abierta dentro de Mission Planner, que
            # toma el 5760. Sin decirlo, esto se ve solo como PROCESO MUERTO.
            print("      el puerto ya estaba ocupado. Cierra la simulación de")
            print("      Mission Planner y mata las instancias anteriores:")
            print("      Get-Process ArduCopter | Stop-Process -Force")
        if ayuda:
            print("      el binario volcó su ayuda y salió: rechaza alguna")
            print("      opción de build_command(). Compara la línea de")
            print("      comandos con 'ArduCopter.exe --help'; el binario que")
            print("      trae Mission Planner cambia de opciones entre")
            print("      versiones. Ver docs/swarm/SITL.md")
        if not ok:
            fallos += 1
    return 1 if fallos else 0


def stop() -> int:
    if not PIDS_FILE.exists():
        print("No hay instancias registradas.")
        return 0
    pids = json.loads(PIDS_FILE.read_text(encoding="utf-8"))
    for drone_id, pid in pids.items():
        try:
            subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                           capture_output=True, check=False)
            print(f"  {drone_id}  pid {pid}  terminado")
        except OSError as exc:
            print(f"  {drone_id}  pid {pid}  no se pudo terminar: {exc}")
    PIDS_FILE.unlink(missing_ok=True)
    return 0


def write_bat() -> int:
    """Genera un .bat al estilo del de Mission Planner, con los home correctos.

    El ``sitl.bat`` que trae Mission Planner sitúa los drones donde estuviera
    la última simulación, que rara vez coincide con el escenario activo: con
    los pedidos en Castelldefels y los drones a 25 km, la geovalla rechaza
    todo y no es evidente por qué.

    Este .bat reparte los puertos como el de Mission Planner: SERIAL0 como
    servidor TCP para el portal, y SERIAL2 conectando hacia Mission Planner,
    que escucha en 5772 + 10·instancia.
    """
    binary, defaults = binary_path(), defaults_path()
    destino = PROJECT_DIR / "sitl_escenario.bat"
    lineas = ["@echo off",
              "REM Generado por: python -m airdrop.swarm.sitl bat",
              "REM Home de cada dron = su pad en el escenario activo.",
              "REM SERIAL0 (5760+10i) = portal. SERIAL2 -> Mission Planner (5772+10i).",
              ""]
    for record in _records():
        if not record.enabled:
            continue
        lineas += [
            f"mkdir {record.instance + 1} 2>nul",
            f"cd {record.instance + 1}",
            f'start "" /b "{binary}" -I {record.instance} --model + --speedup 1 '
            f'--defaults "{defaults}" '
            f"--home {record.home_lat},{record.home_lon},0,0 "
            f"--serial0 tcp:0 "
            f"--serial2 tcpclient:127.0.0.1:{gcs_port(record)} "
            f"-P SERIAL2_PROTOCOL=2 --sysid {record.sysid}",
            "cd ..",
            "",
        ]
    # Se une con \n y no con \r\n: write_text ya traduce los saltos en
    # Windows, y ponerlos a mano deja el .bat con lineas dobles.
    destino.write_text("\n".join(lineas), encoding="utf-8")
    print(f"Escrito {destino}")
    print("\nEjecutalo desde la carpeta sitl de Mission Planner:")
    print(f'  cd "{binary.parent}"')
    print(f'  "{destino}"')
    print("\nPuertos:")
    for record in _records():
        if record.enabled:
            print(f"  {record.drone_id}  portal {record.connection}"
                  f"   Mission Planner escucha en {gcs_port(record)}")
    print("\nSi Mission Planner no escucha en alguno de esos puertos, ese dron")
    print("no aparecera en su mapa. El portal lo pilota igual por SERIAL0.")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Instancias SITL del enjambre")
    parser.add_argument("accion", choices=["launch", "status", "stop", "bat"])
    args = parser.parse_args(argv)
    return {"launch": launch, "status": status, "stop": stop,
            "bat": write_bat}[args.accion]()


if __name__ == "__main__":
    sys.exit(main())
