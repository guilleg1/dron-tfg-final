"""
Backend de dron del portal: abstrae de dónde sale la telemetría y a quién se le
envían las misiones, para poder cambiar el origen sin tocar el resto de la app.

Implementaciones:
  - StubBackend  : sin dron (nube). Telemetría vacía. Es el de `main`.
  - LocalBackend : dron real o SITL en local vía dronLink (Mission Planner por
                   TCP, `tcp:127.0.0.1:5763`). Reutiliza exactamente las mismas
                   llamadas que la app de escritorio, que ya funcionan.
  - (futuro)     : un MqttBackend que hable con la Raspberry por MQTT encaja aquí
                   sin cambiar los endpoints; solo se añade otra clase.

Se elige con la variable de entorno DRONE_BACKEND (stub | local). Por defecto
'stub', para que el despliegue en la nube nunca intente importar dronLink.
"""

import os
import sys
import threading
from pathlib import Path


class StubBackend:
    """Sin dron conectado (cloud). Telemetría vacía y despacho no disponible."""
    name = "stub"

    def telemetry(self):
        return {"state": "idle", "telemetry": {}, "backend": self.name}

    def dispatch(self, mission, order_id=None, client_lat=None, client_lon=None, on_state=None):
        raise RuntimeError("No hay dron en este backend (modo cloud).")

    def cancel(self):
        raise RuntimeError("No hay dron en este backend (modo cloud).")

    def rtl(self):
        raise RuntimeError("No hay dron en este backend (modo cloud).")

    def hold(self):
        raise RuntimeError("No hay dron en este backend (modo cloud).")

    def land(self):
        raise RuntimeError("No hay dron en este backend (modo cloud).")


def _add_dronlink_to_path():
    """Añade al sys.path la carpeta que contiene el paquete 'dronLink'.

    dronLink va vendorizado en vendor/. Con DRONLINK_PATH se puede forzar otra
    ubicación (por ejemplo, para probar contra una copia de desarrollo).
    """
    root = Path(__file__).resolve().parents[2]   # raíz del repositorio
    candidates = []
    if os.environ.get("DRONLINK_PATH"):
        candidates.append(Path(os.environ["DRONLINK_PATH"]))
    candidates.append(root / "vendor")
    for candidate in candidates:
        if candidate and (candidate / "dronLink").is_dir():
            if str(candidate) not in sys.path:
                sys.path.insert(0, str(candidate))
            return True
    return False


class LocalBackend:
    """Dron local/SITL vía dronLink. Conecta de forma perezosa en segundo plano."""
    name = "local"

    def __init__(self):
        self._dron = None
        self._latest = {}
        self._lock = threading.Lock()
        self._conn_lock = threading.Lock()  # serializa la conexión
        self._connecting = False
        self._busy = False        # hay una misión en curso
        self._cancelled = False   # se ha pedido abortar la misión

    # ── Conexión ─────────────────────────────────────────────────────────
    def _connection_string(self):
        from airdrop.config import (
            MISSION_PLANNER_TRANSPORT, MISSION_PLANNER_IP, MISSION_PLANNER_PORT,
            MISSION_PLANNER_CONNECTION_STRING,
        )
        return MISSION_PLANNER_CONNECTION_STRING or \
            f"{MISSION_PLANNER_TRANSPORT}:{MISSION_PLANNER_IP}:{MISSION_PLANNER_PORT}"

    def _connect(self):
        from airdrop.config import BAUD
        # Un único connect a la vez: si la telemetría y el despacho intentan
        # conectar en paralelo, dos connect simultáneos corrompen la conexión
        # (el dron arma pero el despegue no llega). El lock lo evita.
        with self._conn_lock:
            if self._dron is None:
                if not _add_dronlink_to_path():
                    raise RuntimeError(
                        "No se encontró dronLink. Define DRONLINK_PATH apuntando a la "
                        "carpeta que contiene 'dronLink' (ProyectoDeDrones).")
                from dronLink.Dron import Dron
                self._dron = Dron()
            if getattr(self._dron, "state", "disconnected") in ("connected", "flying", "returning", "landing"):
                return
            self._dron.connect(self._connection_string(), BAUD, freq=10)
            # Telemetría continua: dronLink invoca el callback en su propio hilo.
            self._dron.send_telemetry_info(self._on_telemetry)

    def _on_telemetry(self, info):
        with self._lock:
            self._latest = info or {}

    def _ensure_connecting(self):
        """Lanza la conexión en segundo plano la primera vez (no bloquea la API)."""
        if self._dron is None and not self._connecting:
            self._connecting = True
            threading.Thread(target=self._safe_connect, daemon=True).start()

    def _safe_connect(self):
        try:
            self._connect()
        except Exception as e:  # noqa: BLE001
            print("LocalBackend: no se pudo conectar al dron:", e)
        finally:
            self._connecting = False

    # ── API pública ──────────────────────────────────────────────────────
    def telemetry(self):
        self._ensure_connecting()
        state = getattr(self._dron, "state", None) or ("connecting" if self._connecting else "idle")
        with self._lock:
            tel = dict(self._latest)
        return {"state": state, "telemetry": tel, "backend": self.name}

    def dispatch(self, mission, order_id=None, client_lat=None, client_lon=None, on_state=None):
        """Ejecuta la entrega completa del pedido, punto a punto en GUIDED.

        Replica la secuencia de la app de escritorio (que encadena varias
        entregas sin problemas): despegue, ida por los waypoints de la ruta,
        aterrizaje en el cliente, espera, re-armado y retorno a central. Va
        actualizando el estado del pedido vía ``on_state(status, op)``.

        Importante: NO usa uploadMission/executeMission (modo AUTO), que no se
        reinicia limpio entre misiones; por eso la segunda no arrancaba.
        """
        if self._busy:
            raise RuntimeError("El dron ya está ejecutando una misión.")
        self._busy = True
        self._cancelled = False
        threading.Thread(
            target=self._run_delivery,
            args=(mission, order_id, client_lat, client_lon, on_state),
            daemon=True,
        ).start()

    class _Cancelled(Exception):
        pass

    def _run_delivery(self, mission, order_id, client_lat, client_lon, on_state):
        import time

        def st(status=None, op=None):
            print(f"[pedido {order_id}] {op or status}")
            if on_state:
                try:
                    on_state(status, op)
                except Exception:  # noqa: BLE001
                    pass

        def check():
            if self._cancelled:
                raise self._Cancelled()

        try:
            from airdrop.config import ORDER_TAKEOFF_ALT
            alt = float(ORDER_TAKEOFF_ALT)
            self._connect()
            dron = self._dron
            wps = mission.get("waypoints", [])
            if not isinstance(wps, list) or len(wps) < 2:
                raise ValueError("Ruta sin waypoints suficientes")
            central, route_wps, dest = wps[0], wps[1:-1], wps[-1]

            check()
            st("en_reparto", "despegando")
            if getattr(dron, "state", None) != "flying":
                self._arm_and_takeoff(alt)

            check()
            st("en_reparto", "yendo a central")
            dron.goto(float(central["lat"]), float(central["lon"]), alt, blocking=True)

            for idx, wp in enumerate(route_wps):
                check()
                st("en_reparto", "en ruta (hub)" if idx == 0 else "en ruta")
                dron.goto(float(wp["lat"]), float(wp["lon"]),
                          float(wp.get("alt", alt)), blocking=True)

            check()
            st("en_reparto", "llegando a destino")
            dron.goto(float(dest["lat"]), float(dest["lon"]),
                      float(dest.get("alt", alt)), blocking=True)

            if client_lat is not None and client_lon is not None:
                check()
                st("en_reparto", "yendo a cliente")
                dron.goto(float(client_lat), float(client_lon), alt, blocking=True)

            check()
            st("en_reparto", "aterrizando en cliente")
            dron.setFlightMode("LAND")
            self._wait_until_landed(dron)

            st("en_reparto", "entrega (espera 10s)")
            time.sleep(10)

            check()
            st("en_reparto", "volviendo a central")
            self._arm_and_takeoff(alt)
            dron.goto(float(central["lat"]), float(central["lon"]), alt, blocking=True)

            st("en_reparto", "aterrizando en central")
            dron.setFlightMode("LAND")
            self._wait_until_landed(dron)

            st("entregado", "entregado")
        except self._Cancelled:
            print(f"[pedido {order_id}] operación cancelada")
            st(None, "cancelado")
        except Exception as e:  # noqa: BLE001
            print(f"LocalBackend.dispatch (pedido {order_id}) error:", e)
            st(None, "error")
        finally:
            self._busy = False

    # ── Controles de seguridad ───────────────────────────────────────────
    def _abort(self, mode):
        """Interrumpe la misión en curso y pone el dron en el modo indicado."""
        self._cancelled = True
        self._busy = False
        if self._dron is None:
            raise RuntimeError("El dron no está conectado.")
        self._dron.setFlightMode(mode)

    def cancel(self):
        self._abort("BRAKE")    # detiene la misión y mantiene posición (sin depender de la emisora)

    def rtl(self):
        self._abort("RTL")      # vuelve al punto de despegue

    def hold(self):
        self._abort("BRAKE")    # mantiene posición (hover)

    def land(self):
        self._abort("LAND")     # aterriza donde está

    def _wait_until_landed(self, dron, timeout=120):
        """Espera a que el dron toque tierra sin depender de llegar a altitud 0.

        En terreno elevado el dron aterriza a una altitud relativa > 0 (p. ej.
        3 m), así que la condición de dronLink (relative_alt < 1 m) no se cumple
        nunca. Aquí damos por aterrizado cuando los motores se desarman (lo que
        ArduCopter hace al tocar tierra) o cuando la altitud deja de bajar.
        """
        import time
        start = time.time()
        last_alt, stable_since = None, None
        while time.time() - start < timeout:
            if self._cancelled:
                raise self._Cancelled()
            try:
                if not dron.vehicle.motors_armed():
                    return  # desarmado = en tierra
            except Exception:  # noqa: BLE001
                pass
            with self._lock:
                alt = self._latest.get("alt")
            if alt is not None:
                if last_alt is not None and abs(float(alt) - float(last_alt)) < 0.3:
                    if stable_since is None:
                        stable_since = time.time()
                    elif time.time() - stable_since >= 6:
                        return  # altitud estable 6 s = en tierra
                else:
                    stable_since = None
                last_alt = alt
            time.sleep(1)

    def _arm_and_takeoff(self, alt):
        """Arma y despega de forma robusta, sin depender de ``dron.state``.

        El gate de dronLink (``takeOff`` solo despega si ``state == 'armed'``) se
        rompe por una carrera: justo tras armar, el hilo de telemetría puede
        procesar un heartbeat de 'desarmado' que aún quedaba en el buffer y
        ``_handle_heartbeat`` revierte ``state`` a 'connected'; entonces
        ``takeOff`` ve ``state != 'armed'`` y no despega (el dron se queda armado
        y se auto-desarma). Aquí armamos por bajo nivel y llamamos directamente a
        ``_takeOff`` (que no comprueba ``state``), reintentando.
        """
        import time
        dron = self._dron
        armed = False
        for _ in range(5):
            try:
                # desarma por si venía de un estado intermedio, deja GUIDED y arma
                dron.vehicle.mav.command_long_send(
                    dron.vehicle.target_system, dron.vehicle.target_component,
                    400, 0, 0, 0, 0, 0, 0, 0, 0)
                time.sleep(1)
                dron.state = "connected"
                dron.setFlightMode("GUIDED")
                dron.vehicle.mav.command_long_send(
                    dron.vehicle.target_system, dron.vehicle.target_component,
                    400, 0, 1, 0, 0, 0, 0, 0, 0)
                dron.vehicle.motors_armed_wait()
                dron.state = "armed"
                armed = True
                break
            except Exception:  # noqa: BLE001
                time.sleep(2)
        if not armed:
            raise RuntimeError("No se pudo armar el dron")
        for _ in range(2):
            try:
                dron.state = "armed"   # reasegura el estado por si un heartbeat lo pisó
                dron._takeOff(alt)     # despegue directo, sin el gate de state
                return
            except Exception:  # noqa: BLE001
                time.sleep(1)
        raise RuntimeError("Fallo en el despegue")


def get_backend():
    kind = os.environ.get("DRONE_BACKEND", "stub").lower()
    if kind == "local":
        return LocalBackend()
    return StubBackend()
