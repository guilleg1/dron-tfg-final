import json
import sqlite3
import sys
import threading
import time
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, simpledialog

try:
    import tkintermapview  # type: ignore[import-not-found]
except ImportError:
    tkintermapview = None


THIS_DIR = Path(__file__).resolve().parent
SIBLING_PROJECT = THIS_DIR.parent / "ProyectoDeDrones"
if str(SIBLING_PROJECT) not in sys.path:
    sys.path.insert(0, str(SIBLING_PROJECT))

from dronLink.Dron import Dron  # type: ignore[import-not-found]  # noqa: E402
from business_manager import open_business_manager


previousBtn = None

MISSION_PLANNER_TRANSPORT = "tcp"
MISSION_PLANNER_IP = "127.0.0.1"
MISSION_PLANNER_PORT = 5763
MISSION_PLANNER_CONNECTION_STRING = None
BAUD = 115200
ORDER_TAKEOFF_ALT = 25

dron = Dron()

PROFILES_FILE = Path(__file__).resolve().parent / "route_profiles.json"
DB_FILE = Path(__file__).resolve().parent / "operations.db"
profiles_data = {"profiles": []}
active_profile_name = None
active_route_name = None


def set_order_state(order_id, status=None, operational_state=None):
    updates = []
    params = []

    if status is not None:
        updates.append("status = ?")
        params.append(status)

    if operational_state is not None:
        updates.append("operational_state = ?")
        params.append(operational_state)

    if not updates:
        return

    with sqlite3.connect(DB_FILE) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(orders)").fetchall()}
        if "operational_state" not in columns:
            conn.execute("ALTER TABLE orders ADD COLUMN operational_state TEXT")
        params.append(int(order_id))
        conn.execute(
            "UPDATE orders SET " + ", ".join(updates) + " WHERE id = ?",
            tuple(params),
        )


def run_order_delivery_workflow(order_id, mission, profile_name, route_name, client_latitude, client_longitude):
    try:
        if not ensure_connected_for_mission():
            raise ValueError("No se pudo conectar el dron")

        if client_latitude is None or client_longitude is None:
            raise ValueError("El cliente no tiene coordenadas validas")

        waypoints = mission.get("waypoints", [])
        if not isinstance(waypoints, list) or len(waypoints) < 2:
            raise ValueError("La ruta del pedido no tiene waypoints suficientes")

        central_wp = waypoints[0]
        route_waypoints = waypoints[1:-1]
        destination_wp = waypoints[-1]

        set_order_state(order_id, status="en_reparto", operational_state="despegando (25m)")
        publish_route_status("Pedido #" + str(order_id) + ": despegando a 25m", "blue")

        if dron.state != "flying":
            dron.arm()
            dron.takeOff(ORDER_TAKEOFF_ALT, blocking=True)
            publish_event("flying")

        set_order_state(order_id, status="en_reparto", operational_state="yendo a central")
        publish_route_status("Pedido #" + str(order_id) + ": yendo a central", "blue")
        dron.goto(float(central_wp["lat"]), float(central_wp["lon"]), ORDER_TAKEOFF_ALT, blocking=True)

        publish_event("missionStarted")
        for idx, wp in enumerate(route_waypoints):
            if idx == 0:
                set_order_state(order_id, status="en_reparto", operational_state="en ruta (pasando por hub)")
                publish_route_status("Pedido #" + str(order_id) + ": en ruta (hub)", "blue")
            else:
                set_order_state(order_id, status="en_reparto", operational_state="en ruta")
                publish_route_status("Pedido #" + str(order_id) + ": en ruta", "blue")

            dron.goto(float(wp["lat"]), float(wp["lon"]), float(wp.get("alt", ORDER_TAKEOFF_ALT)), blocking=True)

        set_order_state(order_id, status="en_reparto", operational_state="llegando a destino de ruta")
        publish_route_status("Pedido #" + str(order_id) + ": llegando a destino de ruta", "blue")
        dron.goto(
            float(destination_wp["lat"]),
            float(destination_wp["lon"]),
            float(destination_wp.get("alt", ORDER_TAKEOFF_ALT)),
            blocking=True,
        )

        set_order_state(order_id, status="en_reparto", operational_state="yendo a cliente")
        publish_route_status("Pedido #" + str(order_id) + ": yendo a direccion del cliente", "blue")
        dron.goto(float(client_latitude), float(client_longitude), ORDER_TAKEOFF_ALT, blocking=True)

        set_order_state(order_id, status="en_reparto", operational_state="aterrizando en cliente")
        publish_route_status("Pedido #" + str(order_id) + ": aterrizando en cliente", "dark orange")
        dron.Land(blocking=True)
        publish_event("landed")

        set_order_state(order_id, status="en_reparto", operational_state="entrega (espera 10s)")
        publish_route_status("Pedido #" + str(order_id) + ": entrega, esperando 10s", "dark orange")
        time.sleep(10)

        set_order_state(order_id, status="en_reparto", operational_state="despegando retorno (25m)")
        publish_route_status("Pedido #" + str(order_id) + ": despegando retorno a 25m", "dark orange")

        # Asegurar que estamos conectados y reintentar el armado/despegue si falla.
        # Algunas veces el dron puede no aceptar el arm inmediatamente tras aterrizar,
        # así que intentamos reconectar y rearmar hasta 3 veces antes de fallar.
        armed = False
        for attempt in range(3):
            if dron.state != "connected":
                ensure_connected_for_mission()
            try:
                armed = dron.arm()
            except Exception:
                armed = False
            if armed:
                break
            time.sleep(1)

        if not armed:
            raise RuntimeError("No se pudo armar el dron para el retorno")

        taken_off = dron.takeOff(ORDER_TAKEOFF_ALT, blocking=True)
        if not taken_off:
            # Intentar un pequeño reintento de takeOff
            time.sleep(1)
            taken_off = dron.takeOff(ORDER_TAKEOFF_ALT, blocking=True)
        if not taken_off:
            raise RuntimeError("Fallo en despegue para retorno")

        publish_event("flying")

        set_order_state(order_id, status="en_reparto", operational_state="volviendo...")
        publish_route_status("Pedido #" + str(order_id) + ": volviendo a central", "dark orange")
        dron.goto(float(central_wp["lat"]), float(central_wp["lon"]), ORDER_TAKEOFF_ALT, blocking=True)

        set_order_state(order_id, status="en_reparto", operational_state="aterrizando en central")
        publish_route_status("Pedido #" + str(order_id) + ": aterrizando en central", "dark orange")
        dron.Land(blocking=True)
        publish_event("landed")

        set_order_state(order_id, status="entregado", operational_state="esperando siguiente pedido")
        publish_route_status(
            "Pedido #" + str(order_id) + " entregado. Dron en central esperando siguiente pedido",
            "green",
        )
        publish_event("missionFinished")
    except Exception as ex:
        publish_error("Fallo en pedido #" + str(order_id) + ": " + str(ex))
        try:
            set_order_state(order_id, operational_state="error")
        except Exception:
            pass


def publish_route_status(text, color="black"):
    ventana.after(0, set_route_status, text, color)


def load_profiles_from_disk():
    global profiles_data
    if not PROFILES_FILE.exists():
        profiles_data = {"profiles": []}
        return

    try:
        with open(PROFILES_FILE, "r", encoding="utf-8") as fp:
            data = json.load(fp)
    except (OSError, json.JSONDecodeError):
        profiles_data = {"profiles": []}
        return

    if not isinstance(data, dict) or "profiles" not in data or not isinstance(data["profiles"], list):
        profiles_data = {"profiles": []}
        return

    for profile in data["profiles"]:
        profile.setdefault("parkings", [])
        profile.setdefault("destinations", [])
        profile.setdefault("routes", [])
        profile.setdefault("hub", None)
        profile.setdefault("takeOffAlt", 8)
        profile.setdefault("speed", 7)
        for route in profile["routes"]:
            route.setdefault("intermediates", [])

    profiles_data = data


def save_profiles_to_disk():
    try:
        with open(PROFILES_FILE, "w", encoding="utf-8") as fp:
            json.dump(profiles_data, fp, indent=2)
    except OSError as ex:
        messagebox.showerror("Error", "No se pudo guardar route_profiles.json: " + str(ex))


def find_profile(profile_name):
    for profile in profiles_data["profiles"]:
        if profile.get("name") == profile_name:
            return profile
    return None


def find_named_point(points, name):
    for point in points:
        if point.get("name") == name:
            return point
    return None


def build_mission_from_profile(profile, route_name):
    route = None
    for item in profile.get("routes", []):
        if item.get("name") == route_name:
            route = item
            break

    if route is None:
        raise ValueError("Ruta no encontrada")

    parking = find_named_point(profile.get("parkings", []), route.get("parking"))
    destination = find_named_point(profile.get("destinations", []), route.get("destination"))
    hub = profile.get("hub")

    if parking is None:
        raise ValueError("Parking de la ruta no encontrado")
    if destination is None:
        raise ValueError("Destino de la ruta no encontrado")
    if not isinstance(hub, dict):
        raise ValueError("Falta definir el punto HUB comun")

    waypoints = [
        {"lat": float(parking["lat"]), "lon": float(parking["lon"]), "alt": float(parking.get("alt", 8))},
        {"lat": float(hub["lat"]), "lon": float(hub["lon"]), "alt": float(hub.get("alt", 8))},
    ]

    for point in route.get("intermediates", []):
        waypoints.append(
            {
                "lat": float(point["lat"]),
                "lon": float(point["lon"]),
                "alt": float(point.get("alt", hub.get("alt", 8))),
            }
        )

    waypoints.append(
        {"lat": float(destination["lat"]), "lon": float(destination["lon"]), "alt": float(destination.get("alt", 8))}
    )

    return {
        "speed": float(profile.get("speed", 7)),
        "takeOffAlt": float(profile.get("takeOffAlt", 8)),
        "waypoints": waypoints,
    }


def set_route_status(text, color="black"):
    if "routeStatusLbl" in globals() and routeStatusLbl is not None:
        routeStatusLbl["text"] = text
        routeStatusLbl["fg"] = color


def send_message(command, payload=None):
    threading.Thread(target=execute_command, args=(command, payload), daemon=True).start()


def restart():
    time.sleep(5)
    arm_takeOffBtn["text"] = "Armar y Despegar"
    arm_takeOffBtn["fg"] = "black"
    arm_takeOffBtn["bg"] = "dark orange"

    landBtn["text"] = "Aterrizar"
    landBtn["fg"] = "black"
    landBtn["bg"] = "dark orange"

    RTLBtn["text"] = "RTL"
    RTLBtn["fg"] = "black"
    RTLBtn["bg"] = "dark orange"

    if previousBtn:
        previousBtn["fg"] = "black"
        previousBtn["bg"] = "dark orange"


def showTelemetryInfo(telemetry_info):
    altShowLbl["text"] = round(telemetry_info.get("alt", 0), 2)
    headingShowLbl["text"] = round(telemetry_info.get("heading", 0), 2)
    stateShowLbl["text"] = telemetry_info.get("state", "")


def publish_event(event):
    ventana.after(0, on_message, {"type": "event", "event": event})


def publish_error(error_text):
    ventana.after(0, on_message, {"type": "error", "message": error_text})


def publish_telemetry_info(telemetry_info):
    ventana.after(0, on_message, {"type": "telemetry", "data": telemetry_info})


def get_connection_string():
    if MISSION_PLANNER_CONNECTION_STRING:
        return MISSION_PLANNER_CONNECTION_STRING
    return MISSION_PLANNER_TRANSPORT + ":" + MISSION_PLANNER_IP + ":" + str(MISSION_PLANNER_PORT)


def ensure_connected_for_mission():
    if dron.state in ("connected", "flying", "returning", "landing"):
        return True

    try:
        connection_string = get_connection_string()
        dron.connect(connection_string, BAUD, freq=10)
        publish_event("connected")
        return True
    except Exception as ex:
        publish_error("No se pudo conectar para mision: " + str(ex))
        return False


def start_loaded_mission_non_blocking():
    try:
        try:
            dron.executeMission(blocking=False, wait_until_finish=False)
        except TypeError:
            dron.executeMission(blocking=False)
        publish_event("missionStarted")
        return True
    except Exception as ex:
        publish_error("No se pudo iniciar mision: " + str(ex))
        return False


def execute_command(command, payload=None):
    try:
        if command == "connect":
            connection_string = get_connection_string()
            print("Conectando a " + connection_string)
            dron.connect(connection_string, BAUD, freq=10)
            publish_event("connected")

        if command == "arm_takeOff":
            if dron.state == "connected":
                dron.arm()
                dron.takeOff(5, blocking=False, callback=publish_event, params="flying")

        if command == "go":
            if dron.state == "flying" and isinstance(payload, str):
                dron.go(payload)

        if command == "Land":
            if dron.state == "flying":
                dron.Land(blocking=False, callback=publish_event, params="landed")

        if command == "RTL":
            if dron.state == "flying":
                dron.RTL(blocking=False, callback=publish_event, params="atHome")

        if command == "startTelemetry":
            dron.send_telemetry_info(publish_telemetry_info)

        if command == "stopTelemetry":
            dron.stop_sending_telemetry_info()

        if command == "changeHeading":
            try:
                heading = int(payload)
            except (TypeError, ValueError):
                publish_error("Payload de heading invalido")
                return
            dron.changeHeading(heading)

        if command == "changeNavSpeed":
            try:
                speed = float(payload)
            except (TypeError, ValueError):
                publish_error("Payload de velocidad invalido")
                return
            dron.changeNavSpeed(speed)

        if command == "uploadMission":
            if not ensure_connected_for_mission():
                return
            if not isinstance(payload, dict):
                publish_error("Payload de mision invalido")
                return
            publish_event("missionUploading")
            dron.uploadMission(payload, blocking=False, callback=publish_event, params="missionUploaded")

        if command == "executeMission":
            if not ensure_connected_for_mission():
                return
            start_loaded_mission_non_blocking()

        if command == "startMission":
            if not ensure_connected_for_mission():
                return
            if not isinstance(payload, dict):
                publish_error("Payload de mision invalido")
                return

            def upload_and_execute(mission):
                try:
                    publish_event("missionUploading")
                    dron.uploadMission(mission, blocking=True)
                    publish_event("missionUploaded")
                    start_loaded_mission_non_blocking()
                except Exception as ex:
                    publish_error("Error en startMission: " + str(ex))

            threading.Thread(target=upload_and_execute, args=(payload,), daemon=True).start()

        if command == "startOrderDelivery":
            if not isinstance(payload, dict):
                publish_error("Payload de pedido invalido")
                return

            mission = payload.get("mission")
            order_id = payload.get("order_id")
            profile_name = str(payload.get("profile_name") or "")
            route_name = str(payload.get("route_name") or "")
            client_latitude = payload.get("client_latitude")
            client_longitude = payload.get("client_longitude")

            if not isinstance(mission, dict):
                publish_error("Mision de pedido invalida")
                return
            if order_id is None:
                publish_error("Falta order_id en pedido")
                return

            threading.Thread(
                target=run_order_delivery_workflow,
                args=(int(order_id), mission, profile_name, route_name, client_latitude, client_longitude),
                daemon=True,
            ).start()

    except Exception as ex:
        publish_error(str(ex))


def on_message(message):
    msg_type = message.get("type")

    if msg_type == "telemetry":
        ventana.after(0, showTelemetryInfo, message.get("data", {}))

    if msg_type == "event":
        event = message.get("event")

        if event == "connected":
            connectBtn["text"] = "Dron conectado"
            connectBtn["fg"] = "white"
            connectBtn["bg"] = "green"

        if event == "flying":
            arm_takeOffBtn["text"] = "En el aire"
            arm_takeOffBtn["fg"] = "white"
            arm_takeOffBtn["bg"] = "green"

        if event == "missionUploading":
            set_route_status("Subiendo mision al dron...", "dark orange")

        if event == "missionUploaded":
            set_route_status("Mision subida correctamente", "green")

        if event == "missionStarted":
            set_route_status("Mision iniciada", "green")

        if event == "missionFinished":
            set_route_status("Mision finalizada", "green")

        if event == "landed":
            landBtn["text"] = "En tierra"
            landBtn["fg"] = "white"
            landBtn["bg"] = "green"
            threading.Thread(target=restart, daemon=True).start()

        if event == "atHome":
            RTLBtn["text"] = "En tierra"
            RTLBtn["fg"] = "white"
            RTLBtn["bg"] = "green"
            threading.Thread(target=restart, daemon=True).start()

    if msg_type == "error":
        error_text = str(message.get("message"))
        print("Error:", error_text)
        set_route_status("Error: " + error_text, "red")


def connect_drone():
    connectBtn["text"] = "Conectando..."
    connectBtn["fg"] = "black"
    connectBtn["bg"] = "yellow"
    send_message("connect")


def takeoff():
    send_message("arm_takeOff")
    arm_takeOffBtn["text"] = "Despegando..."
    arm_takeOffBtn["fg"] = "black"
    arm_takeOffBtn["bg"] = "yellow"


def land():
    send_message("Land")
    landBtn["text"] = "Aterrizando..."
    landBtn["fg"] = "black"
    landBtn["bg"] = "yellow"


def RTL():
    send_message("RTL")
    RTLBtn["text"] = "Retornando..."
    RTLBtn["fg"] = "black"
    RTLBtn["bg"] = "yellow"


def go(direction, btn):
    global previousBtn
    if previousBtn:
        previousBtn["fg"] = "black"
        previousBtn["bg"] = "dark orange"

    send_message("go", direction)
    btn["fg"] = "white"
    btn["bg"] = "green"
    previousBtn = btn


def startTelem():
    send_message("startTelemetry")


def stopTelem():
    send_message("stopTelemetry")


def changeHeading(_event):
    heading_value = int(gradesSldr.get())
    send_message("changeHeading", heading_value)


def changeNavSpeed(_event):
    speed_value = float(speedSldr.get())
    send_message("changeNavSpeed", speed_value)


def open_clients_orders_manager():
    open_business_manager(ventana, DB_FILE, PROFILES_FILE, start_route_callback=start_route_for_order)


def start_route_for_order(order):
    global active_profile_name, active_route_name

    profile_name = str(order.get("assigned_profile_name") or "")
    route_name = str(order.get("assigned_route_name") or "")
    if not profile_name or not route_name:
        raise ValueError("El pedido no tiene ruta asignada")

    load_profiles_from_disk()
    profile = find_profile(profile_name)
    if profile is None:
        raise ValueError("Perfil no encontrado: " + profile_name)

    mission = build_mission_from_profile(profile, route_name)
    order_id = order.get("id")
    if order_id is None:
        raise ValueError("El pedido no tiene id valido")

    client_latitude = order.get("client_latitude")
    client_longitude = order.get("client_longitude")
    if client_latitude is None or client_longitude is None:
        raise ValueError("El pedido no tiene coordenadas de cliente")

    send_message(
        "startOrderDelivery",
        {
            "order_id": int(order_id),
            "profile_name": profile_name,
            "route_name": route_name,
            "client_latitude": float(client_latitude),
            "client_longitude": float(client_longitude),
            "mission": mission,
        },
    )

    active_profile_name = profile_name
    active_route_name = route_name
    set_route_status("Pedido #" + str(order_id) + " iniciado: " + profile_name + " / " + route_name, "blue")


def crear_ventana():
    global altShowLbl, headingShowLbl, speedSldr, gradesSldr, stateShowLbl
    global connectBtn, arm_takeOffBtn, landBtn, RTLBtn
    global routeStatusLbl
    global previousBtn

    previousBtn = None

    root = tk.Tk()
    root.title("Desktop Local - Mission Planner Directo")
    root.geometry("500x700")

    for i in range(13):
        root.rowconfigure(i, weight=1)
    root.columnconfigure(0, weight=1)
    root.columnconfigure(1, weight=1)

    connectBtn = tk.Button(root, text="Conectar Dron", bg="dark orange", command=connect_drone)
    connectBtn.grid(row=0, column=0, columnspan=2, padx=5, pady=5, sticky=tk.N + tk.S + tk.E + tk.W)

    arm_takeOffBtn = tk.Button(root, text="Armar y Despegar", bg="dark orange", command=takeoff)
    arm_takeOffBtn.grid(row=1, column=0, columnspan=2, padx=5, pady=5, sticky=tk.N + tk.S + tk.E + tk.W)

    gradesSldr = tk.Scale(root, label="Grados:", resolution=5, from_=0, to=360, tickinterval=45, orient=tk.HORIZONTAL)
    gradesSldr.grid(row=2, column=0, columnspan=2, padx=5, pady=5, sticky=tk.N + tk.S + tk.E + tk.W)
    gradesSldr.bind("<ButtonRelease-1>", changeHeading)

    landBtn = tk.Button(root, text="Aterrizar", bg="dark orange", command=land)
    landBtn.grid(row=3, column=0, padx=5, pady=5, sticky=tk.N + tk.S + tk.E + tk.W)

    RTLBtn = tk.Button(root, text="RTL", bg="dark orange", command=RTL)
    RTLBtn.grid(row=3, column=1, padx=5, pady=5, sticky=tk.N + tk.S + tk.E + tk.W)

    navFrame = tk.LabelFrame(root, text="Navegacion")
    navFrame.grid(row=4, column=0, columnspan=2, padx=50, pady=5, sticky=tk.N + tk.S + tk.E + tk.W)

    for i in range(3):
        navFrame.rowconfigure(i, weight=1)
        navFrame.columnconfigure(i, weight=1)

    NWBtn = tk.Button(navFrame, text="NW", bg="dark orange", command=lambda: go("NorthWest", NWBtn))
    NWBtn.grid(row=0, column=0, padx=2, pady=2, sticky=tk.N + tk.S + tk.E + tk.W)

    NoBtn = tk.Button(navFrame, text="No", bg="dark orange", command=lambda: go("North", NoBtn))
    NoBtn.grid(row=0, column=1, padx=2, pady=2, sticky=tk.N + tk.S + tk.E + tk.W)

    NEBtn = tk.Button(navFrame, text="NE", bg="dark orange", command=lambda: go("NorthEast", NEBtn))
    NEBtn.grid(row=0, column=2, padx=2, pady=2, sticky=tk.N + tk.S + tk.E + tk.W)

    WeBtn = tk.Button(navFrame, text="We", bg="dark orange", command=lambda: go("West", WeBtn))
    WeBtn.grid(row=1, column=0, padx=2, pady=2, sticky=tk.N + tk.S + tk.E + tk.W)

    StopBtn = tk.Button(navFrame, text="St", bg="dark orange", command=lambda: go("Stop", StopBtn))
    StopBtn.grid(row=1, column=1, padx=2, pady=2, sticky=tk.N + tk.S + tk.E + tk.W)

    EaBtn = tk.Button(navFrame, text="Ea", bg="dark orange", command=lambda: go("East", EaBtn))
    EaBtn.grid(row=1, column=2, padx=2, pady=2, sticky=tk.N + tk.S + tk.E + tk.W)

    SWBtn = tk.Button(navFrame, text="SW", bg="dark orange", command=lambda: go("Down", SWBtn))
    SWBtn.grid(row=2, column=0, padx=2, pady=2, sticky=tk.N + tk.S + tk.E + tk.W)

    SoBtn = tk.Button(navFrame, text="So", bg="dark orange", command=lambda: go("South", SoBtn))
    SoBtn.grid(row=2, column=1, padx=2, pady=2, sticky=tk.N + tk.S + tk.E + tk.W)

    SEBtn = tk.Button(navFrame, text="SE", bg="dark orange", command=lambda: go("Up", SEBtn))
    SEBtn.grid(row=2, column=2, padx=2, pady=2, sticky=tk.N + tk.S + tk.E + tk.W)

    speedSldr = tk.Scale(root, label="Velocidad (m/s):", resolution=1, from_=0, to=20, tickinterval=5, orient=tk.HORIZONTAL)
    speedSldr.grid(row=5, column=0, columnspan=2, padx=5, pady=5, sticky=tk.N + tk.S + tk.E + tk.W)
    speedSldr.bind("<ButtonRelease-1>", changeNavSpeed)

    StartTelemBtn = tk.Button(root, text="Empezar telemetria", bg="dark orange", command=startTelem)
    StartTelemBtn.grid(row=6, column=0, padx=5, pady=5, sticky=tk.N + tk.S + tk.E + tk.W)

    StopTelemBtn = tk.Button(root, text="Parar telemetria", bg="dark orange", command=stopTelem)
    StopTelemBtn.grid(row=6, column=1, padx=5, pady=5, sticky=tk.N + tk.S + tk.E + tk.W)

    plannerBtn = tk.Button(root, text="Planificador de rutas", bg="light steel blue", command=open_route_planner)
    plannerBtn.grid(row=7, column=0, columnspan=2, padx=5, pady=5, sticky=tk.N + tk.S + tk.E + tk.W)

    managerBtn = tk.Button(root, text="Gestor de clientes y pedidos", bg="light cyan", command=open_clients_orders_manager)
    managerBtn.grid(row=8, column=0, columnspan=2, padx=5, pady=5, sticky=tk.N + tk.S + tk.E + tk.W)

    routeStatusLbl = tk.Label(root, text="Sin ruta activa", fg="black")
    routeStatusLbl.grid(row=9, column=0, columnspan=2, padx=5, pady=2, sticky=tk.W)

    telemetryFrame = tk.LabelFrame(root, text="Telemetria")
    telemetryFrame.grid(row=10, column=0, columnspan=2, padx=10, pady=10, sticky=tk.N + tk.S + tk.E + tk.W)

    telemetryFrame.rowconfigure(0, weight=1)
    telemetryFrame.rowconfigure(1, weight=1)
    telemetryFrame.columnconfigure(0, weight=1)
    telemetryFrame.columnconfigure(1, weight=1)
    telemetryFrame.columnconfigure(2, weight=1)

    altLbl = tk.Label(telemetryFrame, text="Altitud")
    altLbl.grid(row=0, column=0, padx=5, pady=5, sticky=tk.N + tk.S + tk.E + tk.W)

    headingLbl = tk.Label(telemetryFrame, text="Heading")
    headingLbl.grid(row=0, column=1, padx=5, pady=5, sticky=tk.N + tk.S + tk.E + tk.W)

    stateLbl = tk.Label(telemetryFrame, text="Estado")
    stateLbl.grid(row=0, column=2, padx=5, pady=5, sticky=tk.N + tk.S + tk.E + tk.W)

    altShowLbl = tk.Label(telemetryFrame, text="")
    altShowLbl.grid(row=1, column=0, padx=5, pady=5, sticky=tk.N + tk.S + tk.E + tk.W)

    headingShowLbl = tk.Label(telemetryFrame, text="")
    headingShowLbl.grid(row=1, column=1, padx=5, pady=5, sticky=tk.N + tk.S + tk.E + tk.W)

    stateShowLbl = tk.Label(telemetryFrame, text="")
    stateShowLbl.grid(row=1, column=2, padx=5, pady=5, sticky=tk.N + tk.S + tk.E + tk.W)

    return root


def open_route_planner():
    global active_profile_name, active_route_name

    if tkintermapview is None:
        messagebox.showerror(
            "Dependencia faltante",
            "Falta tkintermapview. Instala con: pip install tkintermapview",
        )
        return

    load_profiles_from_disk()

    planner = tk.Toplevel(ventana)
    planner.title("Planificador de rutas y perfiles")
    planner.geometry("1300x760")

    planner.columnconfigure(0, weight=3)
    planner.columnconfigure(1, weight=2)
    planner.rowconfigure(0, weight=1)

    map_frame = tk.LabelFrame(planner, text="Mapa")
    map_frame.grid(row=0, column=0, padx=8, pady=8, sticky=tk.N + tk.S + tk.E + tk.W)
    map_frame.rowconfigure(0, weight=1)
    map_frame.columnconfigure(0, weight=1)

    map_widget = tkintermapview.TkinterMapView(map_frame)
    map_widget.grid(row=0, column=0, sticky=tk.N + tk.S + tk.E + tk.W)
    map_widget.set_tile_server(
        "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        max_zoom=19,
    )
    map_widget.set_position(40.4168, -3.7038)
    map_widget.set_zoom(6)

    control = tk.LabelFrame(planner, text="Perfiles y rutas")
    control.grid(row=0, column=1, padx=8, pady=8, sticky=tk.N + tk.S + tk.E + tk.W)

    for r in range(18):
        control.rowconfigure(r, weight=1)
    control.columnconfigure(0, weight=1)
    control.columnconfigure(1, weight=1)

    marker_refs = []
    path_refs = []

    selected_profile = tk.StringVar(value="")

    tk.Label(control, text="Perfiles").grid(row=0, column=0, columnspan=2, sticky=tk.W, padx=4)
    profiles_list = tk.Listbox(control, height=5, exportselection=False)
    profiles_list.grid(row=1, column=0, columnspan=2, sticky=tk.N + tk.S + tk.E + tk.W, padx=4, pady=2)

    tk.Label(control, text="Parkings").grid(row=2, column=0, sticky=tk.W, padx=4)
    tk.Label(control, text="Destinos").grid(row=2, column=1, sticky=tk.W, padx=4)

    parking_list = tk.Listbox(control, height=5, exportselection=False)
    parking_list.grid(row=3, column=0, sticky=tk.N + tk.S + tk.E + tk.W, padx=4, pady=2)

    destination_list = tk.Listbox(control, height=5, exportselection=False)
    destination_list.grid(row=3, column=1, sticky=tk.N + tk.S + tk.E + tk.W, padx=4, pady=2)

    tk.Label(control, text="Rutas (parking -> hub -> destino)").grid(row=4, column=0, columnspan=2, sticky=tk.W, padx=4)
    routes_list = tk.Listbox(control, height=6, exportselection=False)
    routes_list.grid(row=5, column=0, columnspan=2, sticky=tk.N + tk.S + tk.E + tk.W, padx=4, pady=2)

    tk.Label(control, text="Intermedios de la ruta seleccionada").grid(row=6, column=0, columnspan=2, sticky=tk.W, padx=4)
    intermediates_list = tk.Listbox(control, height=4, exportselection=False)
    intermediates_list.grid(row=7, column=0, columnspan=2, sticky=tk.N + tk.S + tk.E + tk.W, padx=4, pady=2)

    tk.Label(control, text="TakeOff Alt (m)").grid(row=8, column=0, sticky=tk.W, padx=4)
    tk.Label(control, text="Speed (m/s)").grid(row=8, column=1, sticky=tk.W, padx=4)

    takeoff_entry = tk.Entry(control)
    takeoff_entry.grid(row=9, column=0, sticky=tk.E + tk.W, padx=4, pady=2)

    speed_entry = tk.Entry(control)
    speed_entry.grid(row=9, column=1, sticky=tk.E + tk.W, padx=4, pady=2)

    hub_info_lbl = tk.Label(control, text="HUB: no definido", fg="dark orange")
    hub_info_lbl.grid(row=10, column=0, columnspan=2, sticky=tk.W, padx=4)

    status_lbl = tk.Label(control, text="Click derecho en el mapa para agregar puntos.", fg="black")
    status_lbl.grid(row=11, column=0, columnspan=2, sticky=tk.W, padx=4)

    def set_local_status(text, color="black"):
        status_lbl["text"] = text
        status_lbl["fg"] = color

    def get_selected_name(listbox):
        sel = listbox.curselection()
        if not sel:
            return None
        return listbox.get(sel[0])

    def refresh_profiles_list():
        profiles_list.delete(0, tk.END)
        for profile in profiles_data["profiles"]:
            profiles_list.insert(tk.END, profile.get("name", "sin_nombre"))

    def clear_map_objects():
        for marker in marker_refs:
            try:
                marker.delete()
            except Exception:
                pass
        marker_refs.clear()

        for path in path_refs:
            try:
                path.delete()
            except Exception:
                pass
        path_refs.clear()

    def draw_profile_on_map(profile):
        clear_map_objects()

        for point in profile.get("parkings", []):
            marker_refs.append(map_widget.set_marker(point["lat"], point["lon"], text="P: " + point["name"]))

        for point in profile.get("destinations", []):
            marker_refs.append(map_widget.set_marker(point["lat"], point["lon"], text="D: " + point["name"]))

        hub = profile.get("hub")
        if isinstance(hub, dict):
            marker_refs.append(map_widget.set_marker(hub["lat"], hub["lon"], text="HUB"))
            hub_info_lbl["text"] = "HUB: lat={:.6f} lon={:.6f} alt={:.1f}".format(hub["lat"], hub["lon"], hub.get("alt", 8.0))
            hub_info_lbl["fg"] = "green"
            map_widget.set_position(hub["lat"], hub["lon"])
        else:
            hub_info_lbl["text"] = "HUB: no definido"
            hub_info_lbl["fg"] = "dark orange"

        for route in profile.get("routes", []):
            parking = find_named_point(profile.get("parkings", []), route.get("parking"))
            destination = find_named_point(profile.get("destinations", []), route.get("destination"))
            if parking is None or destination is None or not isinstance(hub, dict):
                continue
            route_coords = [
                (parking["lat"], parking["lon"]),
                (hub["lat"], hub["lon"]),
            ]
            for p in route.get("intermediates", []):
                route_coords.append((p["lat"], p["lon"]))
            route_coords.append((destination["lat"], destination["lon"]))
            path_refs.append(map_widget.set_path(route_coords))

    def get_route_by_name(profile, route_name):
        if profile is None:
            return None
        for route in profile.get("routes", []):
            if route.get("name") == route_name:
                return route
        return None

    def refresh_intermediates_list(profile):
        intermediates_list.delete(0, tk.END)
        if profile is None:
            return

        route_name = get_selected_name(routes_list) or active_route_name
        route = get_route_by_name(profile, route_name)
        if route is None:
            return

        for index, point in enumerate(route.get("intermediates", []), start=1):
            label = "I{}: {:.6f}, {:.6f}, alt {:.1f}".format(index, point["lat"], point["lon"], point.get("alt", 8.0))
            intermediates_list.insert(tk.END, label)

    def refresh_profile_details(profile):
        parking_list.delete(0, tk.END)
        destination_list.delete(0, tk.END)
        routes_list.delete(0, tk.END)

        if profile is None:
            takeoff_entry.delete(0, tk.END)
            speed_entry.delete(0, tk.END)
            intermediates_list.delete(0, tk.END)
            hub_info_lbl["text"] = "HUB: no definido"
            hub_info_lbl["fg"] = "dark orange"
            clear_map_objects()
            return

        for point in profile.get("parkings", []):
            parking_list.insert(tk.END, point["name"])

        for point in profile.get("destinations", []):
            destination_list.insert(tk.END, point["name"])

        for route in profile.get("routes", []):
            routes_list.insert(tk.END, route["name"])

        takeoff_entry.delete(0, tk.END)
        takeoff_entry.insert(0, str(profile.get("takeOffAlt", 8)))

        speed_entry.delete(0, tk.END)
        speed_entry.insert(0, str(profile.get("speed", 7)))

        refresh_intermediates_list(profile)
        draw_profile_on_map(profile)

    def update_profile_numeric_fields(profile):
        try:
            profile["takeOffAlt"] = float(takeoff_entry.get())
            profile["speed"] = float(speed_entry.get())
        except ValueError:
            raise ValueError("TakeOffAlt y Speed deben ser numericos")

    def on_select_profile(_event=None):
        global active_profile_name, active_route_name
        profile_name = get_selected_name(profiles_list)
        if not profile_name and selected_profile.get():
            return
        selected_profile.set(profile_name or "")
        active_profile_name = profile_name
        active_route_name = None
        profile = find_profile(profile_name) if profile_name else None
        refresh_profile_details(profile)

    def add_point(point_type, coords):
        profile_name = selected_profile.get()
        if not profile_name:
            set_local_status("Selecciona primero un perfil", "red")
            return

        profile = find_profile(profile_name)
        if profile is None:
            set_local_status("Perfil no encontrado", "red")
            return

        lat, lon = float(coords[0]), float(coords[1])
        name = simpledialog.askstring("Nombre", "Nombre del punto:", parent=planner)
        if not name:
            return

        alt_str = simpledialog.askstring("Altitud", "Altitud relativa (m):", parent=planner, initialvalue="8")
        if not alt_str:
            return
        try:
            alt = float(alt_str)
        except ValueError:
            set_local_status("Altitud invalida", "red")
            return

        new_point = {"name": name.strip(), "lat": lat, "lon": lon, "alt": alt}

        if point_type == "parking":
            if find_named_point(profile.get("parkings", []), new_point["name"]) is not None:
                set_local_status("Ya existe un parking con ese nombre", "red")
                return
            profile.setdefault("parkings", []).append(new_point)

        if point_type == "destination":
            if find_named_point(profile.get("destinations", []), new_point["name"]) is not None:
                set_local_status("Ya existe un destino con ese nombre", "red")
                return
            profile.setdefault("destinations", []).append(new_point)

        refresh_profile_details(profile)
        set_local_status("Punto agregado", "green")

    def set_hub(coords):
        profile_name = selected_profile.get()
        if not profile_name:
            set_local_status("Selecciona primero un perfil", "red")
            return

        profile = find_profile(profile_name)
        if profile is None:
            set_local_status("Perfil no encontrado", "red")
            return

        alt_str = simpledialog.askstring("Altitud HUB", "Altitud del HUB (m):", parent=planner, initialvalue="8")
        if not alt_str:
            return
        try:
            alt = float(alt_str)
        except ValueError:
            set_local_status("Altitud invalida", "red")
            return

        profile["hub"] = {"lat": float(coords[0]), "lon": float(coords[1]), "alt": alt}
        refresh_profile_details(profile)
        set_local_status("HUB actualizado", "green")

    def create_profile():
        profile_name = simpledialog.askstring("Nuevo perfil", "Nombre del perfil:", parent=planner)
        if not profile_name:
            return
        profile_name = profile_name.strip()
        if not profile_name:
            return

        if find_profile(profile_name) is not None:
            set_local_status("Ya existe ese perfil", "red")
            return

        profiles_data["profiles"].append(
            {
                "name": profile_name,
                "takeOffAlt": 8,
                "speed": 7,
                "hub": None,
                "parkings": [],
                "destinations": [],
                "routes": [],
            }
        )
        refresh_profiles_list()
        set_local_status("Perfil creado", "green")

    def delete_profile():
        profile_name = selected_profile.get()
        if not profile_name:
            return

        response = messagebox.askyesno("Confirmar", "Eliminar perfil '" + profile_name + "'?", parent=planner)
        if not response:
            return

        profiles_data["profiles"] = [p for p in profiles_data["profiles"] if p.get("name") != profile_name]
        selected_profile.set("")
        refresh_profiles_list()
        refresh_profile_details(None)
        set_local_status("Perfil eliminado", "green")

    def delete_selected_point(listbox, collection_name):
        profile_name = selected_profile.get()
        if not profile_name:
            return
        profile = find_profile(profile_name)
        if profile is None:
            return

        point_name = get_selected_name(listbox)
        if not point_name:
            return

        profile[collection_name] = [p for p in profile.get(collection_name, []) if p.get("name") != point_name]
        profile["routes"] = [
            route for route in profile.get("routes", [])
            if route.get("parking") != point_name and route.get("destination") != point_name
        ]
        refresh_profile_details(profile)
        set_local_status("Punto eliminado", "green")

    def create_route():
        profile_name = selected_profile.get()
        if not profile_name:
            set_local_status("Selecciona un perfil", "red")
            return
        profile = find_profile(profile_name)
        if profile is None:
            return

        parking_name = get_selected_name(parking_list)
        destination_name = get_selected_name(destination_list)
        if not parking_name or not destination_name:
            set_local_status("Selecciona parking y destino", "red")
            return

        route_name = simpledialog.askstring("Nueva ruta", "Nombre de la ruta:", parent=planner)
        if not route_name:
            return
        route_name = route_name.strip()
        if not route_name:
            return

        for route in profile.get("routes", []):
            if route.get("name") == route_name:
                set_local_status("Ya existe una ruta con ese nombre", "red")
                return

        profile.setdefault("routes", []).append(
            {
                "name": route_name,
                "parking": parking_name,
                "destination": destination_name,
                "intermediates": [],
            }
        )
        refresh_profile_details(profile)
        set_local_status("Ruta creada", "green")

    def delete_route():
        profile_name = selected_profile.get()
        if not profile_name:
            return
        profile = find_profile(profile_name)
        if profile is None:
            return

        route_name = get_selected_name(routes_list)
        if not route_name:
            return

        profile["routes"] = [route for route in profile.get("routes", []) if route.get("name") != route_name]
        refresh_profile_details(profile)
        set_local_status("Ruta eliminada", "green")

    def select_route():
        global active_profile_name, active_route_name
        profile_name = selected_profile.get()
        route_name = get_selected_name(routes_list)
        if not profile_name or not route_name:
            set_local_status("Selecciona perfil y ruta", "red")
            return

        active_profile_name = profile_name
        active_route_name = route_name
        profile = find_profile(profile_name)
        refresh_intermediates_list(profile)
        set_local_status("Ruta activa: " + profile_name + " / " + route_name, "blue")
        set_route_status("Ruta activa: " + profile_name + " / " + route_name, "blue")

    def add_intermediate_to_route(coords):
        profile_name = selected_profile.get()
        route_name = get_selected_name(routes_list)
        if not profile_name or not route_name:
            set_local_status("Selecciona perfil y ruta antes de agregar intermedios", "red")
            return

        profile = find_profile(profile_name)
        route = get_route_by_name(profile, route_name)
        if profile is None or route is None:
            set_local_status("Ruta no encontrada", "red")
            return

        alt_str = simpledialog.askstring("Altitud intermedio", "Altitud del punto intermedio (m):", parent=planner, initialvalue="8")
        if not alt_str:
            return
        try:
            alt = float(alt_str)
        except ValueError:
            set_local_status("Altitud invalida", "red")
            return

        route.setdefault("intermediates", []).append(
            {"lat": float(coords[0]), "lon": float(coords[1]), "alt": alt}
        )

        refresh_profile_details(profile)
        set_local_status("Intermedio agregado", "green")

    def delete_selected_intermediate():
        profile_name = selected_profile.get()
        route_name = get_selected_name(routes_list)
        if not profile_name or not route_name:
            set_local_status("Selecciona perfil y ruta", "red")
            return

        sel = intermediates_list.curselection()
        if not sel:
            set_local_status("Selecciona un intermedio", "red")
            return

        profile = find_profile(profile_name)
        route = get_route_by_name(profile, route_name)
        if route is None:
            return

        index = sel[0]
        if 0 <= index < len(route.get("intermediates", [])):
            del route["intermediates"][index]
            refresh_profile_details(profile)
            set_local_status("Intermedio eliminado", "green")

    def build_selected_mission():
        profile_name = selected_profile.get() or active_profile_name
        route_name = get_selected_name(routes_list) or active_route_name
        if not profile_name or not route_name:
            raise ValueError("Selecciona perfil y ruta")

        profile = find_profile(profile_name)
        if profile is None:
            raise ValueError("Perfil no encontrado")

        update_profile_numeric_fields(profile)
        return build_mission_from_profile(profile, route_name)

    def upload_selected_mission():
        try:
            mission = build_selected_mission()
        except ValueError as ex:
            set_local_status(str(ex), "red")
            return

        send_message("uploadMission", mission)
        set_local_status("Subida de mision solicitada", "green")

    def start_selected_mission():
        try:
            mission = build_selected_mission()
        except ValueError as ex:
            set_local_status(str(ex), "red")
            return

        send_message("startMission", mission)
        set_local_status("Inicio de mision solicitado", "green")

    def stop_selected_mission():
        send_message("RTL")
        set_local_status("Detencion solicitada (RTL)", "dark orange")

    def delete_selected_element():
        if intermediates_list.curselection():
            delete_selected_intermediate()
            return
        if routes_list.curselection():
            delete_route()
            return
        if parking_list.curselection():
            delete_selected_point(parking_list, "parkings")
            return
        if destination_list.curselection():
            delete_selected_point(destination_list, "destinations")
            return
        set_local_status("Selecciona elemento a borrar (intermedio/ruta/parking/destino)", "red")

    def save_all_profiles():
        profile_name = selected_profile.get()
        if profile_name:
            profile = find_profile(profile_name)
            if profile is not None:
                try:
                    update_profile_numeric_fields(profile)
                except ValueError as ex:
                    set_local_status(str(ex), "red")
                    return
        save_profiles_to_disk()
        set_local_status("Perfiles guardados", "green")

    map_widget.add_right_click_menu_command("Agregar parking", lambda coords: add_point("parking", coords), pass_coords=True)
    map_widget.add_right_click_menu_command("Agregar destino", lambda coords: add_point("destination", coords), pass_coords=True)
    map_widget.add_right_click_menu_command("Definir HUB", set_hub, pass_coords=True)
    map_widget.add_right_click_menu_command("Agregar intermedio a ruta", add_intermediate_to_route, pass_coords=True)

    tk.Label(control, text="Flujo: perfil -> ruta -> iniciar/detener", fg="gray30").grid(row=12, column=0, columnspan=2, sticky=tk.W, padx=4)

    tk.Button(control, text="Nuevo perfil", command=create_profile).grid(row=13, column=0, sticky=tk.E + tk.W, padx=4, pady=2)
    tk.Button(control, text="Eliminar perfil", command=delete_profile).grid(row=13, column=1, sticky=tk.E + tk.W, padx=4, pady=2)

    tk.Button(control, text="Crear ruta", command=create_route).grid(row=14, column=0, sticky=tk.E + tk.W, padx=4, pady=2)
    tk.Button(control, text="Eliminar seleccionado", command=delete_selected_element).grid(row=14, column=1, sticky=tk.E + tk.W, padx=4, pady=2)

    tk.Button(control, text="Guardar perfiles", command=save_all_profiles).grid(row=15, column=0, sticky=tk.E + tk.W, padx=4, pady=2)
    tk.Button(control, text="Recargar perfiles", command=lambda: (load_profiles_from_disk(), refresh_profiles_list(), set_local_status("Perfiles recargados", "green"))).grid(row=15, column=1, sticky=tk.E + tk.W, padx=4, pady=2)

    tk.Button(control, text="Iniciar mision", command=start_selected_mission).grid(row=16, column=0, sticky=tk.E + tk.W, padx=4, pady=2)
    tk.Button(control, text="Detener mision", command=stop_selected_mission).grid(row=16, column=1, sticky=tk.E + tk.W, padx=4, pady=2)

    tk.Button(control, text="Subir mision (opcional)", command=upload_selected_mission).grid(row=17, column=0, columnspan=2, sticky=tk.E + tk.W, padx=4, pady=2)

    profiles_list.bind("<<ListboxSelect>>", on_select_profile)

    def on_select_route(_event=None):
        profile = find_profile(selected_profile.get())
        refresh_intermediates_list(profile)
        select_route()

    routes_list.bind("<<ListboxSelect>>", on_select_route)

    refresh_profiles_list()


if __name__ == "__main__":
    load_profiles_from_disk()

    ventana = crear_ventana()
    ventana.mainloop()
