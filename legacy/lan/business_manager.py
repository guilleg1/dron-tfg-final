import json
import math
import sqlite3
import urllib.parse
import urllib.request
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk


SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS clients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL CHECK (length(trim(name)) > 0),
    address TEXT NOT NULL CHECK (length(trim(address)) > 0),
    latitude REAL,
    longitude REAL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER NOT NULL,
    weight_kg REAL NOT NULL CHECK (weight_kg > 0),
    status TEXT NOT NULL DEFAULT 'pendiente' CHECK (
        status IN ('pendiente', 'planificado', 'en_reparto', 'entregado', 'cancelado')
    ),
    assigned_profile_name TEXT,
    assigned_route_name TEXT,
    assigned_destination_name TEXT,
    assigned_destination_lat REAL,
    assigned_destination_lon REAL,
    assigned_distance_km REAL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (client_id) REFERENCES clients(id) ON DELETE RESTRICT ON UPDATE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_orders_client_id ON orders(client_id);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);

CREATE TRIGGER IF NOT EXISTS trg_clients_updated_at
AFTER UPDATE ON clients
FOR EACH ROW
BEGIN
    UPDATE clients SET updated_at = datetime('now') WHERE id = NEW.id;
END;

CREATE TRIGGER IF NOT EXISTS trg_orders_updated_at
AFTER UPDATE ON orders
FOR EACH ROW
BEGIN
    UPDATE orders SET updated_at = datetime('now') WHERE id = NEW.id;
END;
"""

VALID_ORDER_STATUSES = ["pendiente", "en_reparto", "entregado", "cancelado"]


class DeliveryDataStore:
    def __init__(self, db_path, route_profiles_path):
        self.db_path = Path(db_path)
        self.route_profiles_path = Path(route_profiles_path)
        self._init_db()

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_db(self):
        with self._connect() as conn:
            conn.executescript(SCHEMA_SQL)
            self._ensure_orders_route_columns(conn)

    def _ensure_orders_route_columns(self, conn):
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(orders)").fetchall()}
        required = {
            "assigned_profile_name": "TEXT",
            "assigned_route_name": "TEXT",
            "assigned_destination_name": "TEXT",
            "assigned_destination_lat": "REAL",
            "assigned_destination_lon": "REAL",
            "assigned_distance_km": "REAL",
            "operational_state": "TEXT",
        }
        for column_name, column_type in required.items():
            if column_name not in columns:
                conn.execute("ALTER TABLE orders ADD COLUMN " + column_name + " " + column_type)

    def _next_client_id(self):
        with self._connect() as conn:
            rows = conn.execute("SELECT id FROM clients ORDER BY id ASC").fetchall()

        expected = 1
        for row in rows:
            current = int(row["id"])
            if current != expected:
                break
            expected += 1
        return expected

    def _haversine_km(self, lat1, lon1, lat2, lon2):
        radius_km = 6371.0
        lat1_rad = math.radians(float(lat1))
        lon1_rad = math.radians(float(lon1))
        lat2_rad = math.radians(float(lat2))
        lon2_rad = math.radians(float(lon2))

        delta_lat = lat2_rad - lat1_rad
        delta_lon = lon2_rad - lon1_rad

        a = math.sin(delta_lat / 2) ** 2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon / 2) ** 2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return radius_km * c

    def _load_profiles(self):
        if not self.route_profiles_path.exists():
            raise ValueError("No existe route_profiles.json")
        with open(self.route_profiles_path, "r", encoding="utf-8") as fp:
            payload = json.load(fp)
        profiles = payload.get("profiles", []) if isinstance(payload, dict) else []
        if not isinstance(profiles, list):
            raise ValueError("Formato invalido de route_profiles.json")
        return profiles

    def _find_best_route_for_client(self, client_lat, client_lon):
        profiles = self._load_profiles()
        best = None

        for profile in profiles:
            profile_name = profile.get("name")
            destinations = {d.get("name"): d for d in profile.get("destinations", []) if isinstance(d, dict)}
            for route in profile.get("routes", []):
                if not isinstance(route, dict):
                    continue
                destination_name = route.get("destination")
                destination = destinations.get(destination_name)
                if destination is None:
                    continue
                try:
                    dest_lat = float(destination["lat"])
                    dest_lon = float(destination["lon"])
                except (TypeError, ValueError, KeyError):
                    continue

                distance_km = self._haversine_km(client_lat, client_lon, dest_lat, dest_lon)    
                candidate = {
                    "profile_name": str(profile_name),
                    "route_name": str(route.get("name")),
                    "destination_name": str(destination_name),
                    "destination_lat": dest_lat,
                    "destination_lon": dest_lon,
                    "distance_km": distance_km,
                }

                if best is None or candidate["distance_km"] < best["distance_km"]:
                    best = candidate

        if best is None:
            raise ValueError("No se ha encontrado ninguna ruta valida en route_profiles.json")
        return best

    def _build_route_assignment(self, client_id):
        with self._connect() as conn:
            row = conn.execute("SELECT latitude, longitude FROM clients WHERE id = ?", (int(client_id),)).fetchone()
        if row is None:
            raise ValueError("Cliente no encontrado")
        if row["latitude"] is None or row["longitude"] is None:
            raise ValueError("El cliente no tiene coordenadas validas")
        return self._find_best_route_for_client(float(row["latitude"]), float(row["longitude"]))

    def _reassign_orders_for_client(self, client_id):
        assignment = self._build_route_assignment(client_id)
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE orders
                SET
                    assigned_profile_name = ?,
                    assigned_route_name = ?,
                    assigned_destination_name = ?,
                    assigned_destination_lat = ?,
                    assigned_destination_lon = ?,
                    assigned_distance_km = ?
                WHERE client_id = ?
                """,
                (
                    assignment["profile_name"],
                    assignment["route_name"],
                    assignment["destination_name"],
                    assignment["destination_lat"],
                    assignment["destination_lon"],
                    assignment["distance_km"],
                    int(client_id),
                ),
            )

    def geocode_address(self, address):
        query = urllib.parse.urlencode({"q": address, "format": "json", "limit": 1})
        url = "https://nominatim.openstreetmap.org/search?" + query
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "ProyectoDronesLocal/1.0 (desktop manager)",
                "Accept": "application/json",
            },
        )

        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))

        if not payload:
            raise ValueError("No se han encontrado coordenadas para la direccion indicada")

        lat = float(payload[0]["lat"])
        lon = float(payload[0]["lon"])
        return lat, lon

    def list_clients(self):
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, name, address, latitude, longitude FROM clients ORDER BY name COLLATE NOCASE"
            ).fetchall()
        return [dict(row) for row in rows]

    def create_client(self, name, address):
        client_id = self._next_client_id()
        lat, lon = self.geocode_address(address)
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO clients(id, name, address, latitude, longitude) VALUES (?, ?, ?, ?, ?)",
                (client_id, name.strip(), address.strip(), lat, lon),
            )
        return client_id, lat, lon

    def update_client(self, client_id, name, address):
        lat, lon = self.geocode_address(address)
        with self._connect() as conn:
            conn.execute(
                "UPDATE clients SET name = ?, address = ?, latitude = ?, longitude = ? WHERE id = ?",
                (name.strip(), address.strip(), lat, lon, int(client_id)),
            )
        self._reassign_orders_for_client(client_id)
        return lat, lon

    def count_orders_for_client(self, client_id):
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM orders WHERE client_id = ?",
                (int(client_id),),
            ).fetchone()
        return int(row["cnt"])

    def delete_client(self, client_id, delete_related_orders=False):
        with self._connect() as conn:
            if delete_related_orders:
                conn.execute("DELETE FROM orders WHERE client_id = ?", (int(client_id),))
            conn.execute("DELETE FROM clients WHERE id = ?", (int(client_id),))

    def list_orders(self):
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    o.id,
                    o.client_id,
                    c.name AS client_name,
                    c.latitude AS client_latitude,
                    c.longitude AS client_longitude,
                    o.weight_kg,
                    o.status,
                    o.assigned_profile_name,
                    o.assigned_route_name,
                    o.assigned_destination_name,
                    o.assigned_destination_lat,
                    o.assigned_destination_lon,
                    o.assigned_distance_km,
                    o.operational_state
                FROM orders o
                JOIN clients c ON c.id = o.client_id
                ORDER BY o.id DESC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def set_order_status(self, order_id, status=None, operational_state=None):
        updates = []
        params = []

        if status is not None:
            if status not in VALID_ORDER_STATUSES:
                raise ValueError("Estado de pedido invalido")
            updates.append("status = ?")
            params.append(status)

        if operational_state is not None:
            updates.append("operational_state = ?")
            params.append(operational_state)

        if not updates:
            return

        params.append(int(order_id))
        with self._connect() as conn:
            conn.execute(
                "UPDATE orders SET " + ", ".join(updates) + " WHERE id = ?",
                tuple(params),
            )

    def create_order(self, client_id, weight_kg, status):
        assignment = self._build_route_assignment(client_id)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO orders(
                    client_id,
                    weight_kg,
                    status,
                    assigned_profile_name,
                    assigned_route_name,
                    assigned_destination_name,
                    assigned_destination_lat,
                    assigned_destination_lon,
                    assigned_distance_km
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(client_id),
                    float(weight_kg),
                    status,
                    assignment["profile_name"],
                    assignment["route_name"],
                    assignment["destination_name"],
                    assignment["destination_lat"],
                    assignment["destination_lon"],
                    assignment["distance_km"],
                ),
            )
        return assignment

    def update_order(self, order_id, client_id, weight_kg, status):
        assignment = self._build_route_assignment(client_id)
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE orders
                SET
                    client_id = ?,
                    weight_kg = ?,
                    status = ?,
                    assigned_profile_name = ?,
                    assigned_route_name = ?,
                    assigned_destination_name = ?,
                    assigned_destination_lat = ?,
                    assigned_destination_lon = ?,
                    assigned_distance_km = ?
                WHERE id = ?
                """,
                (
                    int(client_id),
                    float(weight_kg),
                    status,
                    assignment["profile_name"],
                    assignment["route_name"],
                    assignment["destination_name"],
                    assignment["destination_lat"],
                    assignment["destination_lon"],
                    assignment["distance_km"],
                    int(order_id),
                ),
            )
        return assignment

    def delete_order(self, order_id):
        with self._connect() as conn:
            conn.execute("DELETE FROM orders WHERE id = ?", (int(order_id),))


def open_business_manager(parent, db_path, route_profiles_path, start_route_callback=None):
    try:
        store = DeliveryDataStore(db_path, route_profiles_path)
    except sqlite3.Error as ex:
        messagebox.showerror("Base de datos", "No se pudo inicializar la base de datos: " + str(ex), parent=parent)
        return

    window = tk.Toplevel(parent)
    window.title("Gestion de clientes y pedidos")
    window.geometry("980x620")
    window.columnconfigure(0, weight=1)
    window.rowconfigure(0, weight=1)
    window.rowconfigure(1, weight=0)

    notebook = ttk.Notebook(window)
    notebook.grid(row=0, column=0, sticky=tk.N + tk.S + tk.E + tk.W, padx=8, pady=8)

    status_lbl = tk.Label(window, text="Listo", fg="black", anchor="w")
    status_lbl.grid(row=1, column=0, sticky=tk.E + tk.W, padx=8, pady=(0, 8))

    def set_status(text, color="black"):
        status_lbl["text"] = text
        status_lbl["fg"] = color

    clients_tab = ttk.Frame(notebook)
    orders_tab = ttk.Frame(notebook)
    notebook.add(clients_tab, text="Clientes")
    notebook.add(orders_tab, text="Pedidos")

    clients_tab.columnconfigure(0, weight=2)
    clients_tab.columnconfigure(1, weight=3)
    clients_tab.rowconfigure(0, weight=1)

    clients_list = tk.Listbox(clients_tab, exportselection=False)
    clients_list.grid(row=0, column=0, sticky=tk.N + tk.S + tk.E + tk.W, padx=(8, 4), pady=8)

    client_form = tk.LabelFrame(clients_tab, text="Detalle cliente")
    client_form.grid(row=0, column=1, sticky=tk.N + tk.S + tk.E + tk.W, padx=(4, 8), pady=8)
    client_form.columnconfigure(1, weight=1)

    tk.Label(client_form, text="Nombre").grid(row=0, column=0, sticky=tk.W, padx=6, pady=6)
    client_name_entry = tk.Entry(client_form)
    client_name_entry.grid(row=0, column=1, sticky=tk.E + tk.W, padx=6, pady=6)

    tk.Label(client_form, text="Direccion").grid(row=1, column=0, sticky=tk.W, padx=6, pady=6)
    client_address_entry = tk.Entry(client_form)
    client_address_entry.grid(row=1, column=1, sticky=tk.E + tk.W, padx=6, pady=6)

    tk.Label(client_form, text="Latitud").grid(row=2, column=0, sticky=tk.W, padx=6, pady=6)
    client_lat_entry = tk.Entry(client_form, state="readonly")
    client_lat_entry.grid(row=2, column=1, sticky=tk.E + tk.W, padx=6, pady=6)

    tk.Label(client_form, text="Longitud").grid(row=3, column=0, sticky=tk.W, padx=6, pady=6)
    client_lon_entry = tk.Entry(client_form, state="readonly")
    client_lon_entry.grid(row=3, column=1, sticky=tk.E + tk.W, padx=6, pady=6)

    clients_buttons = tk.Frame(client_form)
    clients_buttons.grid(row=4, column=0, columnspan=2, sticky=tk.E + tk.W, padx=6, pady=6)
    for i in range(4):
        clients_buttons.columnconfigure(i, weight=1)

    selected_client_id = {"value": None}
    clients_cache = []

    def set_readonly_entry(entry, value):
        entry.config(state="normal")
        entry.delete(0, tk.END)
        if value is not None:
            entry.insert(0, str(value))
        entry.config(state="readonly")

    def clear_client_form():
        selected_client_id["value"] = None
        clients_list.selection_clear(0, tk.END)
        client_name_entry.delete(0, tk.END)
        client_address_entry.delete(0, tk.END)
        set_readonly_entry(client_lat_entry, "")
        set_readonly_entry(client_lon_entry, "")

    def refresh_clients_list():
        nonlocal clients_cache
        selected_id = selected_client_id["value"]
        clients_cache = store.list_clients()
        clients_list.delete(0, tk.END)
        selected_index = None
        for idx, client in enumerate(clients_cache):
            line = "#{id} | {name} | {address}".format(**client)
            clients_list.insert(tk.END, line)
            if selected_id is not None and client["id"] == selected_id:
                selected_index = idx

        if selected_index is not None:
            clients_list.selection_set(selected_index)

    def resolve_selected_client_id():
        if selected_client_id["value"] is not None:
            return int(selected_client_id["value"])

        selection = clients_list.curselection()
        if not selection:
            return None

        idx = int(selection[0])
        if idx < 0 or idx >= len(clients_cache):
            return None

        cid = int(clients_cache[idx]["id"])
        selected_client_id["value"] = cid
        return cid

    def on_select_client(_event=None):
        selection = clients_list.curselection()
        if not selection:
            return
        client = clients_cache[selection[0]]
        selected_client_id["value"] = client["id"]
        client_name_entry.delete(0, tk.END)
        client_name_entry.insert(0, client["name"])
        client_address_entry.delete(0, tk.END)
        client_address_entry.insert(0, client["address"])
        set_readonly_entry(client_lat_entry, client.get("latitude"))
        set_readonly_entry(client_lon_entry, client.get("longitude"))

    def create_client():
        name = client_name_entry.get().strip()
        address = client_address_entry.get().strip()
        if not name or not address:
            set_status("Nombre y direccion son obligatorios", "red")
            return
        try:
            client_id, lat, lon = store.create_client(name, address)
        except Exception as ex:
            set_status("No se pudo crear cliente: " + str(ex), "red")
            return

        refresh_clients_list()
        refresh_orders_dependencies()
        selected_client_id["value"] = client_id
        refresh_clients_list()
        on_select_client()
        set_readonly_entry(client_lat_entry, lat)
        set_readonly_entry(client_lon_entry, lon)
        set_status("Cliente creado con ID " + str(client_id), "green")

    def update_client():
        client_id = resolve_selected_client_id()
        if client_id is None:
            set_status("Selecciona un cliente para modificar", "red")
            return

        name = client_name_entry.get().strip()
        address = client_address_entry.get().strip()
        if not name or not address:
            set_status("Nombre y direccion son obligatorios", "red")
            return

        try:
            lat, lon = store.update_client(client_id, name, address)
        except Exception as ex:
            set_status("No se pudo modificar cliente: " + str(ex), "red")
            return

        refresh_clients_list()
        refresh_orders_dependencies()
        set_readonly_entry(client_lat_entry, lat)
        set_readonly_entry(client_lon_entry, lon)
        set_status("Cliente modificado", "green")

    def delete_client():
        client_id = resolve_selected_client_id()
        if client_id is None:
            set_status("Selecciona un cliente para eliminar", "red")
            return

        if not messagebox.askyesno("Confirmar", "Eliminar cliente seleccionado?", parent=window):
            return

        delete_related_orders = False
        linked_orders = store.count_orders_for_client(client_id)
        if linked_orders > 0:
            response = messagebox.askyesno(
                "Cliente con pedidos",
                "Este cliente tiene " + str(linked_orders) + " pedido(s).\nSi continuas, tambien se eliminaran esos pedidos.\n\nQuieres continuar?",
                parent=window,
            )
            if not response:
                return
            delete_related_orders = True

        try:
            store.delete_client(client_id, delete_related_orders=delete_related_orders)
        except sqlite3.IntegrityError:
            set_status("No se puede eliminar: hay pedidos asociados", "red")
            return
        except Exception as ex:
            set_status("No se pudo eliminar cliente: " + str(ex), "red")
            return

        clear_client_form()
        refresh_clients_list()
        refresh_orders_dependencies()
        set_status("Cliente eliminado", "green")

    tk.Button(clients_buttons, text="Alta", command=create_client).grid(row=0, column=0, padx=3, pady=3, sticky=tk.E + tk.W)
    tk.Button(clients_buttons, text="Modificar", command=update_client).grid(row=0, column=1, padx=3, pady=3, sticky=tk.E + tk.W)
    tk.Button(clients_buttons, text="Baja", command=delete_client).grid(row=0, column=2, padx=3, pady=3, sticky=tk.E + tk.W)
    tk.Button(clients_buttons, text="Limpiar", command=clear_client_form).grid(row=0, column=3, padx=3, pady=3, sticky=tk.E + tk.W)

    clients_list.bind("<<ListboxSelect>>", on_select_client)

    orders_tab.columnconfigure(0, weight=2)
    orders_tab.columnconfigure(1, weight=3)
    orders_tab.rowconfigure(0, weight=1)

    orders_list = tk.Listbox(orders_tab, exportselection=False)
    orders_list.grid(row=0, column=0, sticky=tk.N + tk.S + tk.E + tk.W, padx=(8, 4), pady=8)

    order_form = tk.LabelFrame(orders_tab, text="Detalle pedido")
    order_form.grid(row=0, column=1, sticky=tk.N + tk.S + tk.E + tk.W, padx=(4, 8), pady=8)
    order_form.columnconfigure(1, weight=1)

    tk.Label(order_form, text="Cliente").grid(row=0, column=0, sticky=tk.W, padx=6, pady=6)
    order_client_combo = ttk.Combobox(order_form, state="readonly")
    order_client_combo.grid(row=0, column=1, sticky=tk.E + tk.W, padx=6, pady=6)

    tk.Label(order_form, text="Peso (kg)").grid(row=1, column=0, sticky=tk.W, padx=6, pady=6)
    order_weight_entry = tk.Entry(order_form)
    order_weight_entry.grid(row=1, column=1, sticky=tk.E + tk.W, padx=6, pady=6)

    tk.Label(order_form, text="Estado").grid(row=2, column=0, sticky=tk.W, padx=6, pady=6)
    order_status_combo = ttk.Combobox(order_form, state="readonly", values=VALID_ORDER_STATUSES)
    order_status_combo.grid(row=2, column=1, sticky=tk.E + tk.W, padx=6, pady=6)
    order_status_combo.set("pendiente")

    tk.Label(order_form, text="Ruta asignada").grid(row=3, column=0, sticky=tk.W, padx=6, pady=6)
    assigned_route_lbl = tk.Label(order_form, text="Sin asignar", anchor="w", fg="gray30", justify="left")
    assigned_route_lbl.grid(row=3, column=1, sticky=tk.E + tk.W, padx=6, pady=6)

    orders_buttons = tk.Frame(order_form)
    orders_buttons.grid(row=4, column=0, columnspan=2, sticky=tk.E + tk.W, padx=6, pady=6)
    for i in range(4):
        orders_buttons.columnconfigure(i, weight=1)

    start_route_btn = tk.Button(order_form, text="Empezar ruta asignada")
    start_route_btn.grid(row=5, column=0, columnspan=2, sticky=tk.E + tk.W, padx=6, pady=(0, 6))

    selected_order_id = {"value": None}
    orders_cache = []
    order_client_map = {}

    def refresh_orders_dependencies():
        nonlocal order_client_map
        clients = store.list_clients()
        order_client_map = {"{id} - {name}".format(**client): client["id"] for client in clients}
        order_client_combo["values"] = list(order_client_map.keys())
        if order_client_map and not order_client_combo.get():
            order_client_combo.current(0)
        refresh_orders_list()

    def refresh_orders_list():
        nonlocal orders_cache
        selected_id = selected_order_id["value"]
        orders_cache = store.list_orders()
        orders_list.delete(0, tk.END)
        selected_index = None
        for idx, order in enumerate(orders_cache):
            route_hint = "{} / {}".format(
                order.get("assigned_profile_name") or "sin perfil",
                order.get("assigned_route_name") or "sin ruta",
            )
            op_state = order.get("operational_state") or "-"
            line = "#{id} | {client_name} | {weight_kg} kg | {status} | {op} | {route}".format(
                id=order["id"],
                client_name=order["client_name"],
                weight_kg=order["weight_kg"],
                status=order["status"],
                op=op_state,
                route=route_hint,
            )
            orders_list.insert(tk.END, line)
            if selected_id is not None and order["id"] == selected_id:
                selected_index = idx

        if selected_index is not None:
            orders_list.selection_set(selected_index)

    def assignment_text(assignment):
        distance_km = assignment.get("distance_km")
        if distance_km is None:
            distance_km = assignment.get("assigned_distance_km")
        if distance_km is None:
            distance_part = "distancia desconocida"
        else:
            distance_part = "{:.2f} km".format(float(distance_km))
        return "{}/{} -> {} ({})".format(
            assignment.get("profile_name") or assignment.get("assigned_profile_name") or "-",
            assignment.get("route_name") or assignment.get("assigned_route_name") or "-",
            assignment.get("destination_name") or assignment.get("assigned_destination_name") or "-",
            distance_part,
        )

    def show_assigned_route(assignment):
        assigned_route_lbl["text"] = assignment_text(assignment)

    def clear_order_form():
        selected_order_id["value"] = None
        orders_list.selection_clear(0, tk.END)
        order_weight_entry.delete(0, tk.END)
        order_status_combo.set("pendiente")
        assigned_route_lbl["text"] = "Sin asignar"

    def on_select_order(_event=None):
        selection = orders_list.curselection()
        if not selection:
            return
        order = orders_cache[selection[0]]
        selected_order_id["value"] = order["id"]

        label_to_set = None
        for label, cid in order_client_map.items():
            if cid == order["client_id"]:
                label_to_set = label
                break
        if label_to_set is not None:
            order_client_combo.set(label_to_set)

        order_weight_entry.delete(0, tk.END)
        order_weight_entry.insert(0, str(order["weight_kg"]))
        if order["status"] in VALID_ORDER_STATUSES:
            order_status_combo.set(order["status"])
        else:
            order_status_combo.set("pendiente")
        show_assigned_route(order)

    def selected_client_id_from_combo():
        selected = order_client_combo.get()
        if selected not in order_client_map:
            raise ValueError("Selecciona un cliente valido")
        return order_client_map[selected]

    def get_selected_order():
        if selected_order_id["value"] is None:
            return None
        for order in orders_cache:
            if order.get("id") == selected_order_id["value"]:
                return order
        return None

    def selected_weight():
        weight = float(order_weight_entry.get())
        if weight <= 0:
            raise ValueError("El peso debe ser mayor que cero")
        return weight

    def selected_status():
        status = order_status_combo.get()
        if status not in VALID_ORDER_STATUSES:
            raise ValueError("Selecciona un estado valido")
        return status

    def create_order():
        try:
            client_id = selected_client_id_from_combo()
            weight = selected_weight()
            status = selected_status()
            assignment = store.create_order(client_id, weight, status)
        except Exception as ex:
            set_status("No se pudo crear pedido: " + str(ex), "red")
            return

        refresh_orders_list()
        show_assigned_route(assignment)
        set_status("Pedido creado. Ruta asignada: " + assignment_text(assignment), "green")

    def update_order():
        order_id = selected_order_id["value"]
        if order_id is None:
            set_status("Selecciona un pedido para modificar", "red")
            return
        try:
            client_id = selected_client_id_from_combo()
            weight = selected_weight()
            status = selected_status()
            assignment = store.update_order(order_id, client_id, weight, status)
        except Exception as ex:
            set_status("No se pudo modificar pedido: " + str(ex), "red")
            return

        refresh_orders_list()
        show_assigned_route(assignment)
        set_status("Pedido modificado. Ruta asignada: " + assignment_text(assignment), "green")

    def delete_order():
        order_id = selected_order_id["value"]
        if order_id is None:
            set_status("Selecciona un pedido para eliminar", "red")
            return

        if not messagebox.askyesno("Confirmar", "Eliminar pedido seleccionado?", parent=window):
            return

        try:
            store.delete_order(order_id)
        except Exception as ex:
            set_status("No se pudo eliminar pedido: " + str(ex), "red")
            return

        clear_order_form()
        refresh_orders_list()
        set_status("Pedido eliminado", "green")

    def start_route_for_selected_order():
        if start_route_callback is None:
            set_status("Accion no disponible en esta pantalla", "red")
            return

        order = get_selected_order()
        if order is None:
            set_status("Selecciona un pedido para iniciar ruta", "red")
            return

        try:
            start_route_callback(order)
        except Exception as ex:
            set_status("No se pudo iniciar ruta: " + str(ex), "red")
            return

        refresh_orders_list()
        set_status("Ruta iniciada para el pedido #" + str(order["id"]), "green")

    tk.Button(orders_buttons, text="Alta", command=create_order).grid(row=0, column=0, padx=3, pady=3, sticky=tk.E + tk.W)
    tk.Button(orders_buttons, text="Modificar", command=update_order).grid(row=0, column=1, padx=3, pady=3, sticky=tk.E + tk.W)
    tk.Button(orders_buttons, text="Baja", command=delete_order).grid(row=0, column=2, padx=3, pady=3, sticky=tk.E + tk.W)
    tk.Button(orders_buttons, text="Limpiar", command=clear_order_form).grid(row=0, column=3, padx=3, pady=3, sticky=tk.E + tk.W)

    start_route_btn.configure(command=start_route_for_selected_order)
    if start_route_callback is None:
        start_route_btn.configure(state="disabled")

    orders_list.bind("<<ListboxSelect>>", on_select_order)

    def periodic_orders_refresh():
        if not window.winfo_exists():
            return
        refresh_orders_list()
        window.after(1500, periodic_orders_refresh)

    refresh_clients_list()
    refresh_orders_dependencies()
    window.after(1500, periodic_orders_refresh)
