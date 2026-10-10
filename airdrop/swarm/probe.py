"""Sonda de enlace MAVLink.

Comprueba si hay un autopiloto al otro lado de un puerto, sin implicar al
enjambre: abre una conexión efímera, espera un heartbeat, y la cierra. Es lo
que permite validar el enlace antes de lanzar ningún reparto.

**No usa dronLink a propósito.** dronLink arranca hilos de telemetría y deja la
conexión abierta, y SERIAL0 admite un solo cliente: una sonda que se quedara
con la conexión impediría que el enjambre se conectase después. Aquí se abre y
se cierra.

Los puertos habituales de una instancia SITL, con base 5760 y +10 por
instancia:

    SERIAL0   5760, 5770, 5780, 5790    normalmente el portal
    SERIAL1   5762, 5772, 5782, 5792
    SERIAL2   5763, 5773, 5783, 5793    normalmente Mission Planner

Cuál usa cada uno depende de cómo se lancen las instancias, y por eso la
cadena de conexión de cada dron es editable y existe ``scan``.
"""

from __future__ import annotations

import concurrent.futures
import socket

DEFAULT_TIMEOUT_S = 4.0

# Dos esperas distintas, y confundirlas es un error real que ya se cometió:
#
# - El socket se abre o no en milisegundos, así que 0,3 s sobra para descartar
#   un puerto cerrado y mantener el escaneo rápido.
# - El heartbeat va a **1 Hz**. Una ventana de un segundo lo pierde casi
#   siempre, y el puerto parece muerto teniendo un autopiloto detrás.
CONNECT_TIMEOUT_S = 0.3
HEARTBEAT_TIMEOUT_S = 3.0

# El escaneo NO toca SERIAL0 (5760 + 10i). Es el puerto que tumba instancias:
# admite un solo cliente, y una sonda que se conecta y se va deja
# ``Closed connection on SERIAL0`` y mata el proceso. Verificado el 2026-08-06:
# pulsar «Buscar autopilotos» con el enjambre sano dejaba las cuatro instancias
# muertas, y el segundo clic ya no encontraba nada. El mismo motivo por el que
# ``sitl.status`` no comprueba el estado sondeando puertos.
#
# Se sondean SERIAL1 (+2) y SERIAL2 (+3), que son los que puede usar el portal.
# Como efecto secundario el escaneo pasa de 41 puertos a 8 y es mucho más
# rápido.
SCAN_INSTANCES = range(8)
SCAN_PORTS = tuple(
    5760 + 10 * instancia + offset
    for instancia in SCAN_INSTANCES
    for offset in (2, 3)
)


def _puerto_abierto(host: str, port: int, timeout_s: float) -> bool:
    """Comprobación previa con un socket pelado.

    Existe para no dejar que ``mavutil`` intente conectar a puertos cerrados:
    reintenta en bucle imprimiendo por pantalla, y un escaneo de cuarenta
    puertos generaba cientos de kilobytes de ruido.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout_s)
        return sock.connect_ex((host, port)) == 0


def _partes(connection: str):
    """Extrae (host, puerto) de una cadena ``tcp:host:puerto``."""
    trozos = connection.split(":")
    if len(trozos) == 3 and trozos[0].lower() in ("tcp", "tcpin"):
        try:
            return trozos[1], int(trozos[2])
        except ValueError:
            return None
    return None


SERIAL0_BASE = 5760
SERIAL0_TOPE = 5760 + 10 * 16  # dieciséis instancias, de sobra


def _es_serial0(destino) -> bool:
    """¿Este puerto es el SERIAL0 de alguna instancia? (5760 + 10i)

    Acotado al rango de SITL a propósito. Sin el rango, cualquier puerto
    acabado en 0 —incluido un efímero que reparta el sistema operativo— se
    tomaría por SERIAL0 y la sonda se negaría a mirarlo.
    """
    if destino is None:
        return False
    puerto = destino[1]
    return SERIAL0_BASE <= puerto <= SERIAL0_TOPE and puerto % 10 == 0


def probe(connection: str, timeout_s: float = DEFAULT_TIMEOUT_S,
          connect_timeout_s: float = CONNECT_TIMEOUT_S,
          allow_serial0: bool = False) -> dict:
    """Intenta hablar MAVLink por ``connection`` y describe lo que encuentra.

    Devuelve siempre un diccionario, nunca lanza: una sonda que revienta no
    sirve para diagnosticar.

    ``timeout_s`` es la espera del heartbeat, que llega a 1 Hz;
    ``connect_timeout_s`` es solo la apertura del socket.

    **SERIAL0 se rechaza sin abrir el socket**, salvo ``allow_serial0``. Ese
    puerto admite un solo cliente y sondearlo mata la instancia: se conecta,
    se va, y el autopiloto cae con ``Closed connection on SERIAL0``. Una sonda
    que tumba lo que venía a diagnosticar es peor que no tenerla, así que aquí
    se prefiere un error explicativo a un dron muerto.
    """
    from pymavlink import mavutil  # noqa: PLC0415

    resultado = {"connection": connection, "ok": False, "sysid": None,
                 "error": None, "position": None}

    destino = _partes(connection)
    if not allow_serial0 and _es_serial0(destino):
        resultado["error"] = ("es SERIAL0: sondearlo mata la instancia. "
                              "Usa SERIAL1 (+2) o SERIAL2 (+3)")
        return resultado

    if destino is not None and not _puerto_abierto(*destino,
                                                   timeout_s=connect_timeout_s):
        resultado["error"] = "puerto cerrado"
        return resultado

    enlace = None
    try:
        enlace = mavutil.mavlink_connection(connection)
        latido = enlace.recv_match(type="HEARTBEAT", blocking=True, timeout=timeout_s)
        if latido is None:
            resultado["error"] = f"sin heartbeat en {timeout_s:.0f} s"
            return resultado
        resultado["ok"] = True
        resultado["sysid"] = latido.get_srcSystem()

        # Una posición, si llega rápido: confirma que el autopiloto no solo
        # responde sino que tiene estimación de dónde está.
        posicion = enlace.recv_match(type="GLOBAL_POSITION_INT",
                                     blocking=True, timeout=timeout_s)
        if posicion is not None:
            resultado["position"] = {
                "lat": posicion.lat / 1e7,
                "lon": posicion.lon / 1e7,
                "alt": posicion.relative_alt / 1000.0,
            }
    except Exception as exc:  # noqa: BLE001
        resultado["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if enlace is not None:
            try:
                enlace.close()
            except Exception:  # noqa: BLE001
                pass
    return resultado


def scan(host: str = "127.0.0.1", ports=SCAN_PORTS,
         timeout_s: float = HEARTBEAT_TIMEOUT_S) -> list[dict]:
    """Sondea varios puertos en paralelo y devuelve los que responden.

    En paralelo, y con una espera de heartbeat generosa: en serie, con
    cuarenta puertos y tres segundos cada uno, el botón tardaría dos minutos.
    """
    conexiones = [f"tcp:{host}:{puerto}" for puerto in ports]
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(conexiones) or 1) as pool:
        resultados = list(pool.map(lambda c: probe(c, timeout_s), conexiones))
    return [dict(r, serial=_serial_probable(r["connection"])) for r in resultados
            if r["ok"]]


def _serial_probable(connection: str) -> str | None:
    """Qué puerto serie de SITL es, deducido del número.

    Ayuda a elegir: SERIAL0 suele estar ocupado por Mission Planner, y en ese
    caso el portal tiene que ir por SERIAL1 o SERIAL2.
    """
    destino = _partes(connection)
    if destino is None:
        return None
    resto = destino[1] % 10
    return {0: "SERIAL0", 2: "SERIAL1", 3: "SERIAL2"}.get(resto)
