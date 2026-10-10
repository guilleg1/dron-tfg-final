"""
Capa de datos del portal cloud.

Agnóstica del motor: usa SQLAlchemy Core para hablar igual con SQLite (local,
desarrollo) o Postgres (Supabase, producción). El motor se elige por la
variable de entorno DATABASE_URL; si no está definida se cae a un fichero
SQLite local.

La asignación de ruta a cada pedido reutiliza airdrop.domain.matching, el
mismo criterio que la app de escritorio.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import (
    Column, DateTime, Float, ForeignKey, Integer, MetaData, String, Table, Text,
    create_engine, delete, func, select, text, update,
)

from airdrop.config import PROFILES_FILE, PROJECT_DIR
from airdrop.domain.matching import find_best_route

DEFAULT_SQLITE = "sqlite:///" + str(PROJECT_DIR / "operations.db")
PROFILES_KEY = "route_profiles"   # clave en la tabla config

metadata = MetaData()

clients = Table(
    "clients", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("name", String(255), nullable=False),
    Column("address", String(512), nullable=False),
    Column("latitude", Float),
    Column("longitude", Float),
    Column("created_at", DateTime, default=lambda: datetime.now(timezone.utc)),
)

orders = Table(
    "orders", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("client_id", Integer, ForeignKey("clients.id"), nullable=False),
    Column("weight_kg", Float, nullable=False),
    Column("status", String(32), nullable=False, default="pendiente"),
    Column("assigned_profile_name", String(255)),
    Column("assigned_route_name", String(255)),
    Column("assigned_destination_name", String(255)),
    Column("assigned_destination_lat", Float),
    Column("assigned_destination_lon", Float),
    Column("assigned_distance_km", Float),
    Column("operational_state", String(64)),
    Column("assigned_drone_id", String(64)),
    Column("created_at", DateTime, default=lambda: datetime.now(timezone.utc)),
)

# Administradores del portal (gestión de rutas y flota).
admins = Table(
    "admins", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("username", String(128), nullable=False, unique=True),
    Column("password_hash", String(256), nullable=False),
    Column("created_at", DateTime, default=lambda: datetime.now(timezone.utc)),
)

# Usuarios del portal de cliente (cuenta con contraseña ligada a un cliente).
users = Table(
    "users", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("username", String(128), nullable=False, unique=True),
    Column("password_hash", String(256), nullable=False),
    Column("client_id", Integer, ForeignKey("clients.id"), nullable=False),
    Column("created_at", DateTime, default=lambda: datetime.now(timezone.utc)),
)

# Configuración clave/valor (JSON). Aquí persisten los perfiles de ruta, que en
# el servicio desplegado no pueden vivir en un fichero porque el disco es efímero.
config = Table(
    "config", metadata,
    Column("key", String(64), primary_key=True),
    Column("value", Text, nullable=False),
)


def _normalize_url(url):
    # SQLAlchemy no acepta el viejo esquema postgres:// que sirven algunos
    # proveedores, y desde la 2.1 el esquema postgresql:// sin driver usa psycopg 3.
    # Se fija psycopg2, que es el que instala requirements/api.txt.
    for esquema in ("postgres://", "postgresql://"):
        if url.startswith(esquema):
            return "postgresql+psycopg2://" + url[len(esquema):]
    return url


class DataStore:
    def __init__(self, database_url=None, profiles_path=PROFILES_FILE):
        url = _normalize_url(database_url or os.environ.get("DATABASE_URL") or DEFAULT_SQLITE)
        self.engine = create_engine(url, future=True)
        self.profiles_path = Path(profiles_path)
        metadata.create_all(self.engine)
        self._ensure_columns()

    def _ensure_columns(self):
        """Añade columnas nuevas a bases de datos ya existentes.

        create_all() solo crea tablas que faltan; no altera las que ya están.
        Sin esto, una base de datos creada antes de B1 se queda sin
        assigned_drone_id y todas las consultas de pedidos fallan.
        """
        from sqlalchemy import inspect, text  # noqa: PLC0415

        inspector = inspect(self.engine)
        if "orders" not in inspector.get_table_names():
            return
        existing = {c["name"] for c in inspector.get_columns("orders")}
        if "assigned_drone_id" not in existing:
            with self.engine.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE orders ADD COLUMN assigned_drone_id VARCHAR(64)"))

    # ── Configuración clave/valor ────────────────────────────────────────

    def get_setting(self, key):
        """Ajuste de operación guardado en la base de datos (o None)."""
        return self._get_config(key)

    def set_setting(self, key, value):
        self._set_config(key, value)

    def _get_config(self, key):
        with self.engine.connect() as conn:
            row = conn.execute(select(config.c.value).where(config.c.key == key)).first()
        return row[0] if row else None

    def _set_config(self, key, value):
        with self.engine.begin() as conn:
            exists = conn.execute(select(config.c.key).where(config.c.key == key)).first()
            if exists:
                conn.execute(update(config).where(config.c.key == key).values(value=value))
            else:
                conn.execute(config.insert().values(key=key, value=value))

    # ── Perfiles de ruta (persistidos en BD, sembrados del fichero) ──────

    def _seed_profiles(self):
        try:
            with open(self.profiles_path, "r", encoding="utf-8") as fp:
                payload = json.load(fp)
        except (OSError, json.JSONDecodeError):
            return {"profiles": []}
        return payload if isinstance(payload, dict) and "profiles" in payload else {"profiles": []}

    def get_profiles(self):
        """Documento de perfiles desde la BD; si no existe, lo siembra del fichero."""
        raw = self._get_config(PROFILES_KEY)
        if raw is None:
            data = self._seed_profiles()
            self.save_profiles(data)
            return data
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"profiles": []}

    def reset_profiles(self):
        """Vuelve a los escenarios de rutas del fichero, descartando lo editado."""
        data = self._seed_profiles()
        self.save_profiles(data)
        return data

    def save_profiles(self, data):
        self._set_config(PROFILES_KEY, json.dumps(data, ensure_ascii=False))

    def _load_profiles(self):
        return self.get_profiles().get("profiles", [])

    def active_profile(self):
        """Escenario de rutas del escenario operacional activo, o None.

        Se lee de la tabla de escenarios directamente porque hay más de un
        DataStore sobre la misma base (el portal, la siembra de la demo) y
        todos tienen que asignar igual.
        """
        try:
            with self.engine.connect() as conn:
                fila = conn.execute(text(
                    "SELECT route_profile_name FROM scenarios WHERE active")).first()
        except Exception:  # noqa: BLE001  (sin tabla de escenarios todavía)
            return None
        return fila[0] if fila else None

    def _assign(self, lat, lon):
        """Corredor del escenario activo cuyo destino queda más cerca del cliente.

        Solo del escenario activo: buscando en todos, un cliente junto a la
        escuela caía en un punto de la jaula del DroneLab y el dron de
        Castelldefels recibía una misión dibujada en otro escenario.
        """
        if lat is None or lon is None:
            raise ValueError("Cliente sin coordenadas")
        perfiles = self._load_profiles()
        nombre = self.active_profile()
        if nombre:
            propios = [p for p in perfiles if p.get("name") == nombre]
            perfiles = propios or perfiles
        return find_best_route(perfiles, float(lat), float(lon))

    # ── Administradores ──────────────────────────────────────────────────

    def count_admins(self):
        with self.engine.connect() as conn:
            return conn.execute(select(func.count()).select_from(admins)).scalar() or 0

    def get_admin(self, username):
        with self.engine.connect() as conn:
            row = conn.execute(
                select(admins.c.id, admins.c.username, admins.c.password_hash)
                .where(admins.c.username == username)
            ).mappings().first()
        return dict(row) if row else None

    def create_admin(self, username, password_hash):
        with self.engine.begin() as conn:
            aid = conn.execute(
                admins.insert().values(username=username, password_hash=password_hash)
            ).inserted_primary_key[0]
        return {"id": aid, "username": username}

    # ── Clientes ─────────────────────────────────────────────────────────

    def list_clients(self):
        with self.engine.connect() as conn:
            rows = conn.execute(
                select(clients.c.id, clients.c.name, clients.c.address,
                       clients.c.latitude, clients.c.longitude)
                .order_by(clients.c.name)
            ).mappings().all()
        return [dict(r) for r in rows]

    def create_client(self, name, address, lat, lon):
        with self.engine.begin() as conn:
            cid = conn.execute(
                clients.insert().values(
                    name=name.strip(), address=address.strip(),
                    latitude=lat, longitude=lon,
                )
            ).inserted_primary_key[0]
        return {"id": cid, "name": name.strip(), "address": address.strip(),
                "latitude": lat, "longitude": lon}

    def get_client(self, client_id):
        with self.engine.connect() as conn:
            row = conn.execute(
                select(clients.c.id, clients.c.name, clients.c.address,
                       clients.c.latitude, clients.c.longitude)
                .where(clients.c.id == int(client_id))
            ).mappings().first()
        return dict(row) if row else None

    def update_client(self, client_id, name=None, address=None, lat=None, lon=None):
        values = {}
        if name is not None:
            values["name"] = name.strip()
        if address is not None:
            values["address"] = address.strip()
            values["latitude"] = lat
            values["longitude"] = lon
        if values:
            with self.engine.begin() as conn:
                conn.execute(update(clients).where(clients.c.id == int(client_id)).values(**values))
        return self.get_client(client_id)

    # ── Usuarios del portal ──────────────────────────────────────────────

    def get_user(self, username):
        with self.engine.connect() as conn:
            row = conn.execute(
                select(users.c.id, users.c.username, users.c.password_hash, users.c.client_id)
                .where(users.c.username == username)
            ).mappings().first()
        return dict(row) if row else None

    def create_user(self, username, password_hash, client_id):
        with self.engine.begin() as conn:
            uid = conn.execute(
                users.insert().values(
                    username=username, password_hash=password_hash, client_id=int(client_id),
                )
            ).inserted_primary_key[0]
        return {"id": uid, "username": username, "client_id": int(client_id)}

    # ── Pedidos ──────────────────────────────────────────────────────────

    def list_orders(self, client_id=None):
        j = orders.join(clients, clients.c.id == orders.c.client_id)
        stmt = (
            select(
                orders.c.id, orders.c.client_id, clients.c.name.label("client_name"),
                clients.c.latitude.label("client_latitude"),
                clients.c.longitude.label("client_longitude"),
                orders.c.weight_kg, orders.c.status,
                orders.c.assigned_profile_name, orders.c.assigned_route_name,
                orders.c.assigned_destination_name, orders.c.assigned_destination_lat,
                orders.c.assigned_destination_lon, orders.c.assigned_distance_km,
                orders.c.operational_state, orders.c.assigned_drone_id,
            )
            .select_from(j)
            .order_by(orders.c.id.desc())
        )
        if client_id is not None:
            stmt = stmt.where(orders.c.client_id == int(client_id))
        with self.engine.connect() as conn:
            rows = conn.execute(stmt).mappings().all()
        return [dict(r) for r in rows]

    def create_order(self, client_id, weight_kg, status="pendiente"):
        with self.engine.connect() as conn:
            row = conn.execute(
                select(clients.c.latitude, clients.c.longitude)
                .where(clients.c.id == int(client_id))
            ).first()
        if row is None:
            raise ValueError("Cliente no encontrado")
        a = self._assign(row[0], row[1])
        with self.engine.begin() as conn:
            conn.execute(orders.insert().values(
                client_id=int(client_id), weight_kg=float(weight_kg), status=status,
                assigned_profile_name=a["profile_name"],
                assigned_route_name=a["route_name"],
                assigned_destination_name=a["destination_name"],
                assigned_destination_lat=a["destination_lat"],
                assigned_destination_lon=a["destination_lon"],
                assigned_distance_km=a["distance_km"],
            ))
        return a

    def update_order(self, order_id, status=None, operational_state=None,
                     assigned_drone_id=None):
        values = {}
        if status is not None:
            values["status"] = status
        if operational_state is not None:
            values["operational_state"] = operational_state
        if assigned_drone_id is not None:
            values["assigned_drone_id"] = assigned_drone_id
        if not values:
            return
        with self.engine.begin() as conn:
            conn.execute(
                update(orders).where(orders.c.id == int(order_id)).values(**values)
            )

    def delete_order(self, order_id):
        with self.engine.begin() as conn:
            conn.execute(delete(orders).where(orders.c.id == int(order_id)))
