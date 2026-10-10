"""
DroneService – Wrapper thread-safe del dron con señales Qt.

Toda operación bloqueante se ejecuta en un QThread worker para no
congelar la interfaz.
"""

import sys
import time
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

# Importar Dron desde el proyecto hermano
_THIS_DIR = Path(__file__).resolve().parent.parent
_SIBLING_PROJECT = _THIS_DIR.parent / "ProyectoDeDrones"
if str(_SIBLING_PROJECT) not in sys.path:
    sys.path.insert(0, str(_SIBLING_PROJECT))

from dronLink.Dron import Dron  # type: ignore[import-not-found]  # noqa: E402

from utils.constants import (
    MISSION_PLANNER_TRANSPORT,
    MISSION_PLANNER_IP,
    MISSION_PLANNER_PORT,
    MISSION_PLANNER_CONNECTION_STRING,
    BAUD,
    DEFAULT_TAKEOFF_ALT,
    ORDER_TAKEOFF_ALT,
    DB_FILE,
)


class DroneService(QObject):
    """
    Señales principales:
      connected()
      armed()
      flying()
      landed()
      at_home()
      telemetry_updated(dict)
      state_changed(str)
      error_occurred(str)
      route_status(str, str)          – (texto, color)
      mission_uploading()
      mission_uploaded()
      mission_started()
      mission_finished()
    """

    connected = Signal()
    armed = Signal()
    flying = Signal()
    landed = Signal()
    at_home = Signal()
    telemetry_updated = Signal(dict)
    state_changed = Signal(str)
    error_occurred = Signal(str)
    route_status = Signal(str, str)
    mission_uploading = Signal()
    mission_uploaded = Signal()
    mission_started = Signal()
    mission_finished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.dron = Dron()
        self._lock = threading.Lock()
        self._destroyed = False
        self._latest_telemetry = {}

    def cleanup(self):
        """Llamar antes de destruir el objeto para parar threads del dron."""
        self._destroyed = True
        try:
            self.dron.stop_sending_telemetry_info()
        except Exception:
            pass

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _get_connection_string(self):
        if MISSION_PLANNER_CONNECTION_STRING:
            return MISSION_PLANNER_CONNECTION_STRING
        return "{}:{}:{}".format(
            MISSION_PLANNER_TRANSPORT, MISSION_PLANNER_IP, MISSION_PLANNER_PORT
        )

    def _run_in_thread(self, fn, *args):
        """Ejecuta una función en un daemon thread."""
        threading.Thread(target=self._safe_call, args=(fn, *args), daemon=True).start()

    def _safe_call(self, fn, *args):
        try:
            fn(*args)
        except RuntimeError:
            pass  # Signal source deleted – app closing
        except Exception as ex:
            if not self._destroyed:
                try:
                    self.error_occurred.emit(str(ex))
                except RuntimeError:
                    pass

    def _publish_event(self, event):
        """Callback compatible con el API del Dron."""
        if self._destroyed:
            return
        try:
            if event == "connected":
                self.connected.emit()
            elif event == "flying":
                self.flying.emit()
                self.state_changed.emit("flying")
            elif event == "landed":
                self.landed.emit()
                self.state_changed.emit("landed")
            elif event == "atHome":
                self.at_home.emit()
                self.state_changed.emit("atHome")
            elif event == "missionUploading":
                self.mission_uploading.emit()
            elif event == "missionUploaded":
                self.mission_uploaded.emit()
            elif event == "missionStarted":
                self.mission_started.emit()
            elif event == "missionFinished":
                self.mission_finished.emit()
        except RuntimeError:
            pass  # Signal source deleted

    def _publish_telemetry(self, telemetry_info):
        """Callback invocado desde un thread de dronLink – debe ser seguro."""
        self._latest_telemetry = telemetry_info
        if self._destroyed:
            return
        try:
            self.telemetry_updated.emit(telemetry_info)
        except RuntimeError:
            pass  # Signal source deleted

    def _ensure_connected(self):
        if self.dron.state in ("connected", "flying", "returning", "landing"):
            return True
        try:
            cs = self._get_connection_string()
            self.dron.connect(cs, BAUD, freq=10)
            self._publish_event("connected")
            return True
        except Exception as ex:
            self.error_occurred.emit("No se pudo conectar para misión: " + str(ex))
            return False

    # ── Comandos públicos (todos thread-safe) ────────────────────────────────

    @Slot()
    def connect_drone(self):
        def _do():
            cs = self._get_connection_string()
            print("Conectando a " + cs)
            self.dron.connect(cs, BAUD, freq=10)
            self._publish_event("connected")
            self.state_changed.emit("connected")
        self._run_in_thread(_do)

    @Slot()
    def arm_and_takeoff(self):
        def _do():
            if self.dron.state == "connected":
                self.dron.arm()
                self.dron.takeOff(
                    DEFAULT_TAKEOFF_ALT,
                    blocking=False,
                    callback=self._publish_event,
                    params="flying",
                )
        self._run_in_thread(_do)

    @Slot(str)
    def go(self, direction):
        def _do():
            if self.dron.state == "flying":
                self.dron.go(direction)
        self._run_in_thread(_do)

    @Slot()
    def land(self):
        def _do():
            if self.dron.state == "flying":
                self.dron.Land(
                    blocking=False,
                    callback=self._publish_event,
                    params="landed",
                )
        self._run_in_thread(_do)

    @Slot()
    def rtl(self):
        def _do():
            if self.dron.state == "flying":
                self.dron.RTL(
                    blocking=False,
                    callback=self._publish_event,
                    params="atHome",
                )
        self._run_in_thread(_do)

    @Slot()
    def hover(self):
        """Mantener posición actual (cambiar a GUIDED sin movimiento)."""
        def _do():
            if self.dron.state == "flying":
                try:
                    self.dron.setFlightMode("GUIDED")
                except Exception:
                    pass  # Ya en GUIDED o no soportado
        self._run_in_thread(_do)

    @Slot(str, float)
    def alejar(self, direction, distance_m):
        """
        Desplazar dron en una dirección cardinal una distancia.
        Calcula nueva posición y envía goto.
        """
        from utils.geo_utils import offset_position

        def _do():
            if self.dron.state != "flying":
                return
            tel = self._latest_telemetry
            lat = tel.get("lat")
            lon = tel.get("lon")
            alt = tel.get("alt", ORDER_TAKEOFF_ALT)
            if lat is None or lon is None:
                self.error_occurred.emit("Sin coordenadas actuales para ALEJAR")
                return
            new_lat, new_lon = offset_position(lat, lon, direction, distance_m)
            self.dron.goto(new_lat, new_lon, alt, blocking=False)

        self._run_in_thread(_do)

    @Slot(int)
    def change_heading(self, heading):
        def _do():
            self.dron.changeHeading(int(heading))
        self._run_in_thread(_do)

    @Slot(float)
    def change_nav_speed(self, speed):
        def _do():
            self.dron.changeNavSpeed(float(speed))
        self._run_in_thread(_do)

    @Slot()
    def start_telemetry(self):
        def _do():
            self.dron.send_telemetry_info(self._publish_telemetry)
        self._run_in_thread(_do)

    @Slot()
    def stop_telemetry(self):
        def _do():
            self.dron.stop_sending_telemetry_info()
        self._run_in_thread(_do)

    @Slot(dict)
    def upload_mission(self, mission_dict):
        def _do():
            if not self._ensure_connected():
                return
            self._publish_event("missionUploading")
            self.dron.uploadMission(
                mission_dict,
                blocking=False,
                callback=self._publish_event,
                params="missionUploaded",
            )
        self._run_in_thread(_do)

    @Slot(dict)
    def start_mission(self, mission_dict):
        def _do():
            if not self._ensure_connected():
                return
            self._publish_event("missionUploading")
            self.dron.uploadMission(mission_dict, blocking=True)
            self._publish_event("missionUploaded")
            try:
                self.dron.executeMission(blocking=False, wait_until_finish=False)
            except TypeError:
                self.dron.executeMission(blocking=False)
            self._publish_event("missionStarted")
        self._run_in_thread(_do)

    @Slot(dict)
    def start_order_delivery(self, payload):
        """Ejecuta el workflow completo de entrega de un pedido."""

        def _do():
            import sqlite3
            order_id = payload["order_id"]
            mission = payload["mission"]
            client_lat = payload.get("client_latitude")
            client_lon = payload.get("client_longitude")

            def set_order_state(status=None, operational_state=None):
                updates, params = [], []
                if status is not None:
                    updates.append("status = ?")
                    params.append(status)
                if operational_state is not None:
                    updates.append("operational_state = ?")
                    params.append(operational_state)
                if not updates:
                    return
                with sqlite3.connect(str(DB_FILE)) as conn:
                    cols = {r[1] for r in conn.execute("PRAGMA table_info(orders)").fetchall()}
                    if "operational_state" not in cols:
                        conn.execute("ALTER TABLE orders ADD COLUMN operational_state TEXT")
                    params.append(int(order_id))
                    conn.execute(
                        "UPDATE orders SET " + ", ".join(updates) + " WHERE id = ?",
                        tuple(params),
                    )

            try:
                if not self._ensure_connected():
                    raise ValueError("No se pudo conectar el dron")

                if client_lat is None or client_lon is None:
                    raise ValueError("El cliente no tiene coordenadas válidas")

                waypoints = mission.get("waypoints", [])
                if not isinstance(waypoints, list) or len(waypoints) < 2:
                    raise ValueError("Ruta sin waypoints suficientes")

                central_wp = waypoints[0]
                route_waypoints = waypoints[1:-1]
                destination_wp = waypoints[-1]

                set_order_state("en_reparto", "despegando (25m)")
                self.route_status.emit("Pedido #" + str(order_id) + ": despegando a 25m", "#2196f3")

                if self.dron.state != "flying":
                    self.dron.arm()
                    self.dron.takeOff(ORDER_TAKEOFF_ALT, blocking=True)
                    self._publish_event("flying")

                set_order_state("en_reparto", "yendo a central")
                self.route_status.emit("Pedido #" + str(order_id) + ": yendo a central", "#2196f3")
                self.dron.goto(float(central_wp["lat"]), float(central_wp["lon"]), ORDER_TAKEOFF_ALT, blocking=True)

                self._publish_event("missionStarted")
                for idx, wp in enumerate(route_waypoints):
                    if idx == 0:
                        set_order_state("en_reparto", "en ruta (pasando por hub)")
                        self.route_status.emit("Pedido #" + str(order_id) + ": en ruta (hub)", "#2196f3")
                    else:
                        set_order_state("en_reparto", "en ruta")
                        self.route_status.emit("Pedido #" + str(order_id) + ": en ruta", "#2196f3")
                    self.dron.goto(
                        float(wp["lat"]), float(wp["lon"]),
                        float(wp.get("alt", ORDER_TAKEOFF_ALT)),
                        blocking=True,
                    )

                set_order_state("en_reparto", "llegando a destino de ruta")
                self.route_status.emit("Pedido #" + str(order_id) + ": llegando a destino", "#2196f3")
                self.dron.goto(
                    float(destination_wp["lat"]),
                    float(destination_wp["lon"]),
                    float(destination_wp.get("alt", ORDER_TAKEOFF_ALT)),
                    blocking=True,
                )

                set_order_state("en_reparto", "yendo a cliente")
                self.route_status.emit("Pedido #" + str(order_id) + ": yendo a cliente", "#2196f3")
                self.dron.goto(float(client_lat), float(client_lon), ORDER_TAKEOFF_ALT, blocking=True)

                set_order_state("en_reparto", "aterrizando en cliente")
                self.route_status.emit("Pedido #" + str(order_id) + ": aterrizando en cliente", "#ff9800")
                self.dron.Land(blocking=True)
                self._publish_event("landed")

                set_order_state("en_reparto", "entrega (espera 10s)")
                self.route_status.emit("Pedido #" + str(order_id) + ": entrega, esperando 10s", "#ff9800")
                time.sleep(10)

                set_order_state("en_reparto", "despegando retorno (25m)")
                self.route_status.emit("Pedido #" + str(order_id) + ": despegando retorno", "#ff9800")

                armed = False
                for attempt in range(5):
                    try:
                        self.dron.vehicle.mav.command_long_send(
                            self.dron.vehicle.target_system,
                            self.dron.vehicle.target_component,
                            400, 0, 0, 0, 0, 0, 0, 0, 0,
                        )
                        time.sleep(1)
                        self.dron.state = "connected"
                        self.dron.setFlightMode("GUIDED")
                        self.dron.vehicle.mav.command_long_send(
                            self.dron.vehicle.target_system,
                            self.dron.vehicle.target_component,
                            400, 0, 1, 0, 0, 0, 0, 0, 0,
                        )
                        self.dron.vehicle.motors_armed_wait()
                        self.dron.state = "armed"
                        armed = True
                    except Exception:
                        armed = False
                    if armed:
                        break
                    time.sleep(2)

                if not armed:
                    raise RuntimeError("No se pudo armar para retorno")

                taken_off = False
                try:
                    self.dron._takeOff(ORDER_TAKEOFF_ALT)
                    taken_off = True
                except Exception:
                    pass
                if not taken_off:
                    time.sleep(1)
                    try:
                        self.dron._takeOff(ORDER_TAKEOFF_ALT)
                        taken_off = True
                    except Exception:
                        pass
                if not taken_off:
                    raise RuntimeError("Fallo en despegue para retorno")

                self._publish_event("flying")

                set_order_state("en_reparto", "volviendo...")
                self.route_status.emit("Pedido #" + str(order_id) + ": volviendo a central", "#ff9800")
                self.dron.goto(float(central_wp["lat"]), float(central_wp["lon"]), ORDER_TAKEOFF_ALT, blocking=True)

                set_order_state("en_reparto", "aterrizando en central")
                self.route_status.emit("Pedido #" + str(order_id) + ": aterrizando en central", "#ff9800")
                self.dron.Land(blocking=True)
                self._publish_event("landed")

                set_order_state("entregado", "esperando siguiente pedido")
                self.route_status.emit(
                    "Pedido #" + str(order_id) + " entregado. Dron en central",
                    "#4caf50",
                )
                self._publish_event("missionFinished")

            except Exception as ex:
                self.error_occurred.emit("Fallo en pedido #" + str(order_id) + ": " + str(ex))
                try:
                    set_order_state(operational_state="error")
                except Exception:
                    pass

        self._run_in_thread(_do)
