"""
API Server para el Portal de Clientes.
Proporciona endpoints REST y sirve los archivos estáticos del portal web.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs
from pathlib import Path

from utils.constants import DB_FILE, PROFILES_FILE
from negocio.db_manager import DeliveryDataStore


class DroneAPIHandler(BaseHTTPRequestHandler):
    # Variables de clase que se inyectan al iniciar el servidor
    drone_svc = None
    portal_dir = None
    store = None

    def log_message(self, format, *args):
        # Silenciar logs para no ensuciar la consola
        pass

    def send_json(self, data, status=200):
        self.send_response(status)
        self.send_header('Content-type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode('utf-8'))

    def send_error_json(self, message, status=400):
        self.send_json({"error": message}, status)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path.startswith('/api/'):
            self.handle_api_get(path, parsed.query)
        else:
            self.serve_static(path)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path.startswith('/api/'):
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)
            try:
                data = json.loads(body.decode('utf-8'))
            except Exception:
                data = {}
            self.handle_api_post(path, data)
        else:
            self.send_error_json("Not found", 404)

    def handle_api_get(self, path, query_str):
        query = parse_qs(query_str)
        
        # ── Telemetría ──
        if path == '/api/drone/telemetry':
            state = self.drone_svc.dron.state if self.drone_svc else "idle"
            tel = self.drone_svc._latest_telemetry if self.drone_svc else {}
            self.send_json({
                "state": state,
                "telemetry": tel
            })
            return

        # ── Listar pedidos (todos o por cliente) ──
        if path == '/api/orders':
            try:
                orders = self.store.list_orders()
                client_id = query.get('client_id', [None])[0]
                if client_id:
                    orders = [o for o in orders if str(o['client_id']) == str(client_id)]
                
                # Add route_waypoints to each order if assigned
                from servicios.route_service import RouteService
                rs = RouteService(PROFILES_FILE)
                rs.load()
                for o in orders:
                    pname = o.get("assigned_profile_name")
                    rname = o.get("assigned_route_name")
                    if pname and rname:
                        try:
                            mission = rs.build_mission(pname, rname)
                            wps = mission.get("waypoints", [])
                            route_coords = [{"lat": float(wp["lat"]), "lon": float(wp["lon"])} for wp in wps]
                            clat = o.get("client_latitude")
                            clon = o.get("client_longitude")
                            if clat is not None and clon is not None:
                                route_coords.append({"lat": float(clat), "lon": float(clon)})
                            o["route_waypoints"] = route_coords
                        except Exception:
                            pass
                
                self.send_json({"orders": orders})
            except Exception as e:
                self.send_error_json(str(e))
            return

        self.send_error_json("Endpoint no encontrado", 404)

    def handle_api_post(self, path, data):
        # ── Registrar o buscar cliente ──
        if path == '/api/clients/login':
            name = data.get('name', '').strip()
            address = data.get('address', '').strip()
            if not name or not address:
                self.send_error_json("Nombre y dirección son obligatorios")
                return
            
            try:
                # Buscar si existe
                clients = self.store.list_clients()
                for c in clients:
                    if c['name'].lower() == name.lower() and c['address'].lower() == address.lower():
                        self.send_json({"client": c})
                        return
                
                # Crear nuevo
                cid, lat, lon = self.store.create_client(name, address)
                self.send_json({"client": {"id": cid, "name": name, "address": address, "latitude": lat, "longitude": lon}})
            except Exception as e:
                self.send_error_json(str(e))
            return

        # ── Crear pedido ──
        if path == '/api/orders':
            client_id = data.get('client_id')
            weight = data.get('weight_kg', 1.0)
            if not client_id:
                self.send_error_json("client_id obligatorio")
                return
            try:
                assign = self.store.create_order(client_id, weight, "pendiente")
                self.send_json({"success": True, "assignment": assign})
            except Exception as e:
                self.send_error_json(str(e))
            return

        self.send_error_json("Endpoint no encontrado", 404)

    def serve_static(self, path):
        if path == '/' or path == '':
            path = '/index.html'
        
        file_path = self.portal_dir / path.lstrip('/')
        if not file_path.exists() or file_path.is_dir():
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"404 Not Found")
            return

        ext = file_path.suffix.lower()
        mime_types = {
            '.html': 'text/html',
            '.css': 'text/css',
            '.js': 'application/javascript',
            '.json': 'application/json',
            '.png': 'image/png',
            '.jpg': 'image/jpeg',
            '.svg': 'image/svg+xml'
        }
        content_type = mime_types.get(ext, 'application/octet-stream')

        self.send_response(200)
        self.send_header('Content-type', content_type)
        self.end_headers()
        with open(file_path, 'rb') as f:
            self.wfile.write(f.read())


class ApiServer:
    def __init__(self, drone_svc, port=8080):
        self.drone_svc = drone_svc
        self.port = port
        self.server = None
        self.thread = None

    def start(self):
        project_dir = Path(__file__).resolve().parent.parent
        portal_dir = project_dir / "portal_cliente"
        
        DroneAPIHandler.drone_svc = self.drone_svc
        DroneAPIHandler.portal_dir = portal_dir
        DroneAPIHandler.store = DeliveryDataStore(DB_FILE, PROFILES_FILE)

        self.server = HTTPServer(('0.0.0.0', self.port), DroneAPIHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        print(f"API Server & Portal Web iniciados en http://localhost:{self.port}")

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
