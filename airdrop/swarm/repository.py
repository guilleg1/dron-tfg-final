"""Persistencia de la definición de la flota.

La flota se declara en ``airdrop/data/fleet.json`` y se siembra en la tabla
``drones`` la primera vez, igual que ``route_profiles.json`` siembra los
perfiles de ruta. A partir de ahí la base de datos manda, para que el
administrador pueda reconfigurarla sin tocar ficheros.

De cada dron solo se declaran identificador, SYSID, instancia y categoría. El
puerto TCP, el pad de parking y la altitud de crucero se **derivan** de la
instancia: si se declararan a mano acabarían siendo inconsistentes entre el
portal y el lanzador de SITL, que es justo el fallo que no queremos.
"""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import (
    Column, Float, Integer, MetaData, String, Table, delete, select, update,
)

from airdrop.config import FLEET_FILE
from airdrop.swarm.models import DroneRecord
from core.geo import offset_position

# ArduPilot desplaza todos sus puertos 10 por instancia (ver docs/swarm/SITL.md).
# Cada instancia expone SERIAL0 en 5760+10i, SERIAL1 en +2 y SERIAL2 en +3.
SERIAL0_BASE_PORT = 5760
PORT_STEP = 10

# El portal usa SERIAL1 por defecto, no SERIAL0.
#
# SERIAL0 admite un solo cliente y es el que toma Mission Planner al abrir la
# simulación. Si el portal lo reclama, uno de los dos se queda fuera. Con
# SERIAL1 conviven: comprobado contra una simulación real de cuatro drones,
# donde SERIAL0 estaba ocupado y SERIAL1 respondía en los cuatro.
SERIAL1_OFFSET = 2

metadata = MetaData()

drones = Table(
    "drones", metadata,
    Column("drone_id", String(64), primary_key=True),
    Column("sysid", Integer, nullable=False, unique=True),
    Column("instance", Integer, nullable=False),
    Column("category", String(32), nullable=False),
    Column("connection", String(128), nullable=False),
    Column("home_lat", Float, nullable=False),
    Column("home_lon", Float, nullable=False),
    Column("enabled", Integer, nullable=False, default=1),
)


def build_records(payload: dict, scenario) -> list[DroneRecord]:
    """Convierte el documento de flota en ``DroneRecord``.

    Solo se declaran identificador, SYSID, instancia y categoría. El puerto lo
    fija ArduPilot a partir de la instancia, y el pad sale del parking del
    escenario: así una flota vale para cualquier emplazamiento, y cambiar de
    escenario recoloca los drones sin tocar ``fleet.json``.

    La altitud de crucero ya no se deriva aquí. Es un slot que el gestor de
    espacio aéreo reserva por vuelo y libera al aterrizar.
    """
    entradas = list(payload.get("drones", []))

    # La formación la define el escenario (fila, rejilla o círculo). Antes
    # estaba escrita aquí como una fila hacia el este, así que cambiar la
    # disposición del parking obligaba a tocar el repositorio.
    #
    # Se piden tantos pads como índices distintos declare la flota, no tantos
    # como drones: con ``pad_index`` explícito puede haber huecos, y una
    # formación centrada tiene que contarlos para no descolocarse.
    indices = [int(e.get("pad_index", e["instance"])) for e in entradas]
    pads = scenario.parking_slots(max(indices) + 1 if indices else 0)

    records = []
    for entry in entradas:
        instance = int(entry["instance"])
        pad_index = int(entry.get("pad_index", instance))
        pad_lat, pad_lon = (pads[pad_index] if pad_index < len(pads)
                            else (scenario.parking_lat, scenario.parking_lon))
        records.append(DroneRecord(
            drone_id=str(entry["drone_id"]),
            sysid=int(entry["sysid"]),
            instance=instance,
            category=str(entry["category"]),
            connection=(f"tcp:127.0.0.1:"
                        f"{SERIAL0_BASE_PORT + PORT_STEP * instance + SERIAL1_OFFSET}"),
            home_lat=pad_lat,
            home_lon=pad_lon,
            enabled=bool(entry.get("enabled", True)),
        ))
    return records


class FleetRepository:
    """CRUD de la tabla ``drones``."""

    def __init__(self, engine, fleet_file=None):
        self.engine = engine
        self.fleet_file = Path(fleet_file or FLEET_FILE)
        metadata.create_all(self.engine)

    # ── Lectura ──────────────────────────────────────────────────────────
    def list_drones(self, only_enabled: bool = True) -> list[DroneRecord]:
        stmt = select(drones).order_by(drones.c.instance)
        if only_enabled:
            stmt = stmt.where(drones.c.enabled == 1)
        with self.engine.connect() as conn:
            rows = conn.execute(stmt).mappings().all()
        return [
            DroneRecord(
                drone_id=r["drone_id"], sysid=r["sysid"], instance=r["instance"],
                category=r["category"], connection=r["connection"],
                home_lat=r["home_lat"], home_lon=r["home_lon"],
                enabled=bool(r["enabled"]),
            )
            for r in rows
        ]

    # ── Escritura ────────────────────────────────────────────────────────
    def replace_all(self, records: list[DroneRecord]) -> list[DroneRecord]:
        with self.engine.begin() as conn:
            conn.execute(delete(drones))
            for r in records:
                conn.execute(drones.insert().values(
                    drone_id=r.drone_id, sysid=r.sysid, instance=r.instance,
                    category=r.category, connection=r.connection,
                    home_lat=r.home_lat, home_lon=r.home_lon,
                    enabled=1 if r.enabled else 0,
                ))
        return self.list_drones(only_enabled=False)

    def _load_payload(self) -> dict:
        try:
            return json.loads(self.fleet_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def update_connection(self, drone_id: str, connection: str):
        """Cambia la cadena de conexión de un dron.

        Editable porque el puerto depende de cómo se lancen las instancias:
        Mission Planner con su propio `sitl.bat`, el lanzador del proyecto o un
        dron real reparten los puertos de forma distinta, y adivinarlo desde
        aquí solo lleva a perder el tiempo.
        """
        with self.engine.begin() as conn:
            conn.execute(update(drones)
                         .where(drones.c.drone_id == drone_id)
                         .values(connection=connection))
        return next((d for d in self.list_drones(only_enabled=False)
                     if d.drone_id == drone_id), None)

    def seed_if_empty(self, scenario) -> list[DroneRecord]:
        """Siembra la flota desde el fichero si la tabla está vacía."""
        existing = self.list_drones(only_enabled=False)
        if existing:
            return existing
        return self.replace_all(build_records(self._load_payload(), scenario))

    def remove(self, drone_id: str) -> bool:
        """Quita un dron de la flota. Los demás conservan instancia y pad."""
        with self.engine.begin() as conn:
            borradas = conn.execute(delete(drones).where(drones.c.drone_id == drone_id))
        return bool(borradas.rowcount)

    def reseat(self, scenario, desde_fichero: bool = False) -> list[DroneRecord]:
        """Recoloca los pads al cambiar de escenario, conservando la flota.

        La flota es la de la base de datos: la que se haya dejado en la consola
        de simulación, con su número de drones y sus categorías. Antes se leía
        de ``fleet.json`` y cambiar de escenario devolvía la flota a los cuatro
        drones de fábrica. Los pads se reparten en orden, sin huecos, aunque se
        haya quitado algún dron. ``desde_fichero`` es para «Restaurar de
        fábrica», que sí quiere volver al fichero.
        """
        actuales = [] if desde_fichero else self.list_drones(only_enabled=False)
        if not actuales:
            return self.replace_all(build_records(self._load_payload(), scenario))
        payload = {"drones": [
            {"drone_id": d.drone_id, "sysid": d.sysid, "instance": d.instance,
             "category": d.category, "enabled": d.enabled, "pad_index": k}
            for k, d in enumerate(actuales)]}
        return self.replace_all(build_records(payload, scenario))
