import argparse
import json
import sys
import threading
from pathlib import Path
from socket import AF_INET, SOCK_STREAM, SOL_SOCKET, SO_REUSEADDR, socket

# Allow importing dronLink from sibling project directory.
THIS_DIR = Path(__file__).resolve().parent
SIBLING_PROJECT = THIS_DIR.parent / "ProyectoDeDrones"
if str(SIBLING_PROJECT) not in sys.path:
    sys.path.insert(0, str(SIBLING_PROJECT))

from dronLink.Dron import Dron  # type: ignore[import-not-found]  # noqa: E402


MISSION_PLANNER_IP = "10.237.66.46"
MISSION_PLANNER_PORT = 14550
BAUD = 115200
LISTEN_HOST = "0.0.0.0"
LISTEN_PORT = 5000

client_socket = None
client_lock = threading.Lock()
dron = Dron()


def send_message(msg_type, **payload):
    global client_socket

    message = {"type": msg_type}
    message.update(payload)

    with client_lock:
        if client_socket is None:
            return
        try:
            client_socket.sendall((json.dumps(message) + "\n").encode("utf-8"))
        except OSError:
            client_socket = None


def publish_event(event):
    send_message("event", event=event)


def publish_telemetry_info(telemetry_info):
    send_message("telemetry", data=telemetry_info)


def ensure_connected_for_mission():
    if dron.state == "connected":
        return True

    try:
        connection_string = "tcp:" + MISSION_PLANNER_IP + ":" + str(MISSION_PLANNER_PORT)
        print("Estado actual para mision: " + str(dron.state) + ". Reintentando conexion en " + connection_string)
        dron.connect(connection_string, BAUD, freq=10)
        publish_event("connected")
        return True
    except Exception as ex:
        send_message("error", message="No se pudo conectar para mision: " + str(ex))
        return False


def start_loaded_mission_non_blocking():

    try:
        try:
            dron.executeMission(blocking=False)
        except TypeError:
            # Compatibilidad con versiones antiguas de dronLink.
            dron.executeMission(blocking=False)
        publish_event("missionStarted")
        return True
    except Exception as ex:
        send_message("error", message="No se pudo iniciar mision: " + str(ex))
        return False


def on_message(message):
    command = message.get("command")
    payload = message.get("payload")

    if command == "connect":
        connection_string = "tcp:" + MISSION_PLANNER_IP + ":" + str(MISSION_PLANNER_PORT)
        print("Conectando al SITL/Mission Planner en " + connection_string)
        dron.connect(connection_string, BAUD, freq=10)
        publish_event("connected")
        print("Conectado al SITL/Mission Planner")

    if command == "arm_takeOff":
        if dron.state == "connected":
            print("Armando...")
            dron.arm()
            print("Despegando...")
            dron.takeOff(5, blocking=False, callback=publish_event, params="flying")

    if command == "go":
        if dron.state == "flying" and isinstance(payload, str):
            print("Navegando: " + payload)
            dron.go(payload)

    if command == "Land":
        if dron.state == "flying":
            print("Aterrizando...")
            dron.Land(blocking=False, callback=publish_event, params="landed")

    if command == "RTL":
        if dron.state == "flying":
            print("Retornando a casa...")
            dron.RTL(blocking=False, callback=publish_event, params="atHome")

    if command == "startTelemetry":
        print("Iniciando envio de telemetria")
        dron.send_telemetry_info(publish_telemetry_info)

    if command == "stopTelemetry":
        print("Parando envio de telemetria")
        dron.stop_sending_telemetry_info()

    if command == "changeHeading":
        try:
            heading = int(payload)
        except (TypeError, ValueError):
            send_message("error", message="Payload de heading invalido")
            return
        print("Cambiando heading a: " + str(heading))
        dron.changeHeading(heading)

    if command == "changeNavSpeed":
        try:
            speed = float(payload)
        except (TypeError, ValueError):
            send_message("error", message="Payload de velocidad invalido")
            return
        print("Cambiando velocidad a: " + str(speed))
        dron.changeNavSpeed(speed)

    if command == "uploadMission":
        if not ensure_connected_for_mission():
            return
        if not isinstance(payload, dict):
            send_message("error", message="Payload de mision invalido")
            return
        try:
            print("Subiendo mision al autopiloto...")
            dron.uploadMission(payload, blocking=False, callback=publish_event, params="missionUploaded")
            publish_event("missionUploading")
        except Exception as ex:
            send_message("error", message="Error al subir mision: " + str(ex))

    if command == "executeMission":
        if not ensure_connected_for_mission():
            return
        try:
            print("Ejecutando mision cargada...")
            start_loaded_mission_non_blocking()
        except Exception as ex:
            send_message("error", message="Error al ejecutar mision: " + str(ex))

    if command == "startMission":
        if not ensure_connected_for_mission():
            return
        if not isinstance(payload, dict):
            send_message("error", message="Payload de mision invalido")
            return

        def upload_and_execute(mission):
            try:
                publish_event("missionUploading")
                dron.uploadMission(mission, blocking=True)
                publish_event("missionUploaded")
                start_loaded_mission_non_blocking()
            except Exception as ex:
                send_message("error", message="Error en startMission: " + str(ex))

        threading.Thread(target=upload_and_execute, args=(payload,), daemon=True).start()


def handle_client(conn, addr):
    global client_socket
    print("Cliente Desktop conectado desde " + str(addr[0]) + ":" + str(addr[1]))

    with client_lock:
        client_socket = conn

    try:
        with conn.makefile("r", encoding="utf-8", newline="\n") as reader:
            while True:
                line = reader.readline()
                if not line:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    send_message("error", message="JSON invalido")
                    continue

                if message.get("type") == "command":
                    on_message(message)
    except OSError:
        pass
    finally:
        with client_lock:
            if client_socket is conn:
                client_socket = None
        print("Cliente Desktop desconectado")


def serve_forever():
    server = socket(AF_INET, SOCK_STREAM)
    server.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)
    server.bind((LISTEN_HOST, LISTEN_PORT))
    server.listen(1)

    print("RaspiAutopilotLANService escuchando en " + LISTEN_HOST + ":" + str(LISTEN_PORT))

    while True:
        conn, addr = server.accept()
        threading.Thread(target=handle_client, args=(conn, addr), daemon=True).start()


def parse_args():
    parser = argparse.ArgumentParser(description="Servicio de piloto automatico por LAN")
    parser.add_argument("--host", default="0.0.0.0", help="IP de escucha en la Raspi")
    parser.add_argument("--port", type=int, default=5000, help="Puerto TCP de escucha")
    parser.add_argument("--sitl-ip", default="10.237.66.46", help="IP ZeroTier del PC con SITL/Mission Planner")
    parser.add_argument("--sitl-port", type=int, default=14550, help="Puerto TCP del SITL/Mission Planner")
    parser.add_argument("--baud", type=int, default=115200, help="Baudrate usado en dron.connect")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    LISTEN_HOST = args.host
    LISTEN_PORT = args.port
    MISSION_PLANNER_IP = args.sitl_ip
    MISSION_PLANNER_PORT = args.sitl_port
    BAUD = args.baud

    serve_forever()
