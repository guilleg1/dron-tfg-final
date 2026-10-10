"""
DeliveryDataStore – Capa de datos SQLite para clientes y pedidos.
Migrado desde business_manager.py, usando el nuevo geocoder.
"""

import json
import sqlite3
from pathlib import Path

from negocio.geocoder import geocode_address
from servicios.route_matcher import find_best_route

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
AFTER UPDATE ON clients FOR EACH ROW
BEGIN UPDATE clients SET updated_at = datetime('now') WHERE id = NEW.id; END;

CREATE TRIGGER IF NOT EXISTS trg_orders_updated_at
AFTER UPDATE ON orders FOR EACH ROW
BEGIN UPDATE orders SET updated_at = datetime('now') WHERE id = NEW.id; END;
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
            self._ensure_columns(conn)

    def _ensure_columns(self, conn):
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(orders)").fetchall()}
        needed = {
            "assigned_profile_name": "TEXT",
            "assigned_route_name": "TEXT",
            "assigned_destination_name": "TEXT",
            "assigned_destination_lat": "REAL",
            "assigned_destination_lon": "REAL",
            "assigned_distance_km": "REAL",
            "operational_state": "TEXT",
        }
        for name, typ in needed.items():
            if name not in cols:
                conn.execute("ALTER TABLE orders ADD COLUMN " + name + " " + typ)

    def _next_client_id(self):
        with self._connect() as conn:
            rows = conn.execute("SELECT id FROM clients ORDER BY id ASC").fetchall()
        expected = 1
        for row in rows:
            if int(row["id"]) != expected:
                break
            expected += 1
        return expected

    def _load_profiles(self):
        if not self.route_profiles_path.exists():
            raise ValueError("No existe route_profiles.json")
        with open(self.route_profiles_path, "r", encoding="utf-8") as fp:
            payload = json.load(fp)
        profiles = payload.get("profiles", []) if isinstance(payload, dict) else []
        if not isinstance(profiles, list):
            raise ValueError("Formato inválido de route_profiles.json")
        return profiles

    def _find_best_route(self, client_lat, client_lon):
        return find_best_route(self._load_profiles(), client_lat, client_lon)

    def _build_assignment(self, client_id):
        with self._connect() as conn:
            row = conn.execute("SELECT latitude, longitude FROM clients WHERE id = ?", (int(client_id),)).fetchone()
        if row is None:
            raise ValueError("Cliente no encontrado")
        if row["latitude"] is None or row["longitude"] is None:
            raise ValueError("Cliente sin coordenadas")
        return self._find_best_route(float(row["latitude"]), float(row["longitude"]))

    def _reassign_orders(self, client_id):
        a = self._build_assignment(client_id)
        with self._connect() as conn:
            conn.execute(
                """UPDATE orders SET
                    assigned_profile_name=?, assigned_route_name=?,
                    assigned_destination_name=?, assigned_destination_lat=?,
                    assigned_destination_lon=?, assigned_distance_km=?
                WHERE client_id=?""",
                (a["profile_name"], a["route_name"], a["destination_name"],
                 a["destination_lat"], a["destination_lon"], a["distance_km"],
                 int(client_id)),
            )

    # ── Clientes ─────────────────────────────────────────────────────────

    def list_clients(self):
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, name, address, latitude, longitude FROM clients ORDER BY name COLLATE NOCASE"
            ).fetchall()
        return [dict(r) for r in rows]

    def create_client(self, name, address):
        cid = self._next_client_id()
        lat, lon = geocode_address(address)
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO clients(id, name, address, latitude, longitude) VALUES (?,?,?,?,?)",
                (cid, name.strip(), address.strip(), lat, lon),
            )
        return cid, lat, lon

    def update_client(self, client_id, name, address):
        lat, lon = geocode_address(address)
        with self._connect() as conn:
            conn.execute(
                "UPDATE clients SET name=?, address=?, latitude=?, longitude=? WHERE id=?",
                (name.strip(), address.strip(), lat, lon, int(client_id)),
            )
        self._reassign_orders(client_id)
        return lat, lon

    def count_orders_for_client(self, client_id):
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS cnt FROM orders WHERE client_id=?", (int(client_id),)).fetchone()
        return int(row["cnt"])

    def delete_client(self, client_id, delete_related=False):
        with self._connect() as conn:
            if delete_related:
                conn.execute("DELETE FROM orders WHERE client_id=?", (int(client_id),))
            conn.execute("DELETE FROM clients WHERE id=?", (int(client_id),))

    # ── Pedidos ──────────────────────────────────────────────────────────

    def list_orders(self):
        with self._connect() as conn:
            rows = conn.execute("""
                SELECT o.id, o.client_id, c.name AS client_name,
                       c.latitude AS client_latitude, c.longitude AS client_longitude,
                       o.weight_kg, o.status, o.assigned_profile_name,
                       o.assigned_route_name, o.assigned_destination_name,
                       o.assigned_destination_lat, o.assigned_destination_lon,
                       o.assigned_distance_km, o.operational_state
                FROM orders o JOIN clients c ON c.id = o.client_id
                ORDER BY o.id DESC
            """).fetchall()
        return [dict(r) for r in rows]

    def set_order_status(self, order_id, status=None, operational_state=None):
        updates, params = [], []
        if status is not None:
            if status not in VALID_ORDER_STATUSES:
                raise ValueError("Estado inválido")
            updates.append("status = ?")
            params.append(status)
        if operational_state is not None:
            updates.append("operational_state = ?")
            params.append(operational_state)
        if not updates:
            return
        params.append(int(order_id))
        with self._connect() as conn:
            conn.execute("UPDATE orders SET " + ", ".join(updates) + " WHERE id = ?", tuple(params))

    def create_order(self, client_id, weight_kg, status):
        a = self._build_assignment(client_id)
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO orders(client_id, weight_kg, status,
                   assigned_profile_name, assigned_route_name,
                   assigned_destination_name, assigned_destination_lat,
                   assigned_destination_lon, assigned_distance_km)
                VALUES (?,?,?,?,?,?,?,?,?)""",
                (int(client_id), float(weight_kg), status,
                 a["profile_name"], a["route_name"], a["destination_name"],
                 a["destination_lat"], a["destination_lon"], a["distance_km"]),
            )
        return a

    def update_order(self, order_id, client_id, weight_kg, status):
        a = self._build_assignment(client_id)
        with self._connect() as conn:
            conn.execute(
                """UPDATE orders SET client_id=?, weight_kg=?, status=?,
                   assigned_profile_name=?, assigned_route_name=?,
                   assigned_destination_name=?, assigned_destination_lat=?,
                   assigned_destination_lon=?, assigned_distance_km=?
                WHERE id=?""",
                (int(client_id), float(weight_kg), status,
                 a["profile_name"], a["route_name"], a["destination_name"],
                 a["destination_lat"], a["destination_lon"], a["distance_km"],
                 int(order_id)),
            )
        return a

    def delete_order(self, order_id):
        with self._connect() as conn:
            conn.execute("DELETE FROM orders WHERE id=?", (int(order_id),))
