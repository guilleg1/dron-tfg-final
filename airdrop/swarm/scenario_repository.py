"""Persistencia de los escenarios operacionales.

Mismo patrón que la flota y los perfiles de ruta: se siembran de un fichero la
primera vez y a partir de ahí manda la base de datos, para que el
administrador pueda reconfigurarlos sin tocar el repositorio.

Exactamente uno está activo. La activación es la única operación que toca a
más de una fila, y por eso vive aquí y no en el servicio.
"""

from __future__ import annotations

import json
from dataclasses import fields
from pathlib import Path

from sqlalchemy import (
    Boolean, Column, Float, Integer, MetaData, String, Table, inspect, select,
    text, update,
)

from airdrop.config import SCENARIOS_FILE
from airdrop.swarm.scenario import OperationalScenario

metadata = MetaData()

scenarios = Table(
    "scenarios", metadata,
    Column("name", String(64), primary_key=True),
    Column("route_profile_name", String(128), nullable=False),
    Column("parking_name", String(64), nullable=False, default=""),
    Column("parking_lat", Float, nullable=False),
    Column("parking_lon", Float, nullable=False),
    Column("pad_spacing_m", Float, nullable=False),
    Column("pad_layout", String(16), nullable=False, default="fila"),
    Column("pad_cols", Integer, nullable=False, default=0),
    Column("pad_heading_deg", Float, nullable=False, default=90.0),
    Column("pad_separation_m", Float, nullable=False, default=0.0),
    Column("vertiport_capacity", Integer, nullable=False, default=0),
    Column("alt_base_m", Float, nullable=False),
    Column("alt_step_m", Float, nullable=False),
    Column("alt_ceiling_m", Float, nullable=False),
    Column("geofence_radius_m", Float, nullable=False),
    Column("separation_min_m", Float, nullable=False),
    Column("takeoff_gap_s", Float, nullable=False),
    Column("waypoint_tolerance_m", Float, nullable=False),
    Column("hub_exclusive", Boolean, nullable=False),
    Column("hub_capacity", Integer, nullable=False, default=1),
    Column("battery_reserve_pct", Float, nullable=False),
    Column("delivery_pause_s", Float, nullable=False),
    Column("delivery_stagger_s", Float, nullable=False, default=30.0),
    Column("active", Boolean, nullable=False, default=False),
    Column("coords_approximate", Boolean, nullable=False, default=False),
)

_CAMPOS = {f.name for f in fields(OperationalScenario)}


class ScenarioRepository:
    def __init__(self, engine, scenarios_file=None):
        self.engine = engine
        self.scenarios_file = Path(scenarios_file or SCENARIOS_FILE)
        metadata.create_all(self.engine)
        self._add_missing_columns()

    def _add_missing_columns(self) -> None:
        """Añade las columnas nuevas a una tabla que ya existía.

        ``create_all`` crea tablas pero no las altera, así que una base de
        datos creada antes de un campo nuevo se queda sin él y revienta al
        leerla. Un ALTER TABLE por columna ausente basta —son todas anulables
        o con defecto— y evita arrastrar una herramienta de migraciones para
        un puñado de parámetros.
        """
        try:
            existentes = {c["name"] for c in inspect(self.engine).get_columns("scenarios")}
        except Exception:  # noqa: BLE001
            return
        nuevas = {
            "hub_capacity": "INTEGER NOT NULL DEFAULT 1",
            "parking_name": "VARCHAR(64) NOT NULL DEFAULT ''",
            "pad_layout": "VARCHAR(16) NOT NULL DEFAULT 'fila'",
            "pad_cols": "INTEGER NOT NULL DEFAULT 0",
            "pad_heading_deg": "FLOAT NOT NULL DEFAULT 90.0",
            "pad_separation_m": "FLOAT NOT NULL DEFAULT 0.0",
            "vertiport_capacity": "INTEGER NOT NULL DEFAULT 0",
            "delivery_stagger_s": "FLOAT NOT NULL DEFAULT 30.0",
        }
        for nombre, tipo in nuevas.items():
            if nombre in existentes:
                continue
            with self.engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE scenarios ADD COLUMN {nombre} {tipo}"))
        # Los pesos de la antigua función de costes de cinco términos. Eran
        # NOT NULL sin valor por defecto, así que una base de datos antigua
        # rechazaría los escenarios nuevos si no se quitan.
        for nombre in ("w1", "w2", "w3", "w4", "w5"):
            if nombre in existentes:
                with self.engine.begin() as conn:
                    conn.execute(text(f"ALTER TABLE scenarios DROP COLUMN {nombre}"))

    # ── Lectura ──────────────────────────────────────────────────────────
    def list_scenarios(self) -> list[OperationalScenario]:
        with self.engine.connect() as conn:
            filas = conn.execute(select(scenarios).order_by(scenarios.c.name)).mappings().all()
        return [OperationalScenario(**{k: v for k, v in fila.items() if k in _CAMPOS})
                for fila in filas]

    def active(self) -> OperationalScenario | None:
        return next((s for s in self.list_scenarios() if s.active), None)

    def get(self, name) -> OperationalScenario | None:
        return next((s for s in self.list_scenarios() if s.name == name), None)

    # ── Escritura ────────────────────────────────────────────────────────
    def seed_if_empty(self) -> list[OperationalScenario]:
        if self.list_scenarios():
            return self.list_scenarios()
        try:
            payload = json.loads(self.scenarios_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        with self.engine.begin() as conn:
            for entrada in payload.get("scenarios", []):
                escenario = OperationalScenario(
                    **{k: v for k, v in entrada.items() if k in _CAMPOS})
                conn.execute(scenarios.insert().values(**escenario.as_dict()))
        return self.list_scenarios()

    def update(self, name, cambios: dict) -> OperationalScenario | None:
        """Actualiza parámetros. Los campos desconocidos se ignoran.

        Ignorarlos en vez de fallar mantiene el endpoint tolerante a que el
        formulario mande algún campo de más.
        """
        valores = {k: v for k, v in cambios.items()
                   if k in _CAMPOS and k not in ("name", "active")}
        if valores:
            with self.engine.begin() as conn:
                conn.execute(update(scenarios)
                             .where(scenarios.c.name == name).values(**valores))
        return self.get(name)

    def reset_to_defaults(self) -> list[OperationalScenario]:
        """Borra los escenarios guardados y los vuelve a sembrar del fichero.

        El que estaba activo sigue activo si existe en el fichero; si no, se
        queda el que el fichero marca como activo.
        """
        activo = self.active()
        with self.engine.begin() as conn:
            conn.execute(scenarios.delete())
        sembrados = self.seed_if_empty()
        if activo is not None and any(s.name == activo.name for s in sembrados):
            self.activate(activo.name)
        return self.list_scenarios()

    def delete(self, name) -> None:
        with self.engine.begin() as conn:
            conn.execute(scenarios.delete().where(scenarios.c.name == name))

    def create_for_profile(self, profile_name, parking_name="",
                           parking_lat=0.0, parking_lon=0.0) -> OperationalScenario:
        """Crea los parámetros operacionales de un escenario de rutas.

        El escenario operacional **se llama igual** que el escenario de rutas
        al que pertenece. Eran dos entidades con nombres distintos describiendo
        el mismo emplazamiento, y esa duplicidad no se podía explicar sin
        dibujar un diagrama.

        Los valores arrancan en los del dataclass, que son los del escenario
        urbano por defecto; se ajustan luego en el formulario.
        """
        escenario = OperationalScenario(
            name=str(profile_name), route_profile_name=str(profile_name),
            parking_name=str(parking_name),
            parking_lat=float(parking_lat), parking_lon=float(parking_lon),
        )
        with self.engine.begin() as conn:
            conn.execute(scenarios.insert().values(**escenario.as_dict()))
        return escenario

    def activate(self, name) -> OperationalScenario | None:
        if self.get(name) is None:
            return None
        with self.engine.begin() as conn:
            conn.execute(update(scenarios).values(active=False))
            conn.execute(update(scenarios).where(scenarios.c.name == name)
                         .values(active=True))
        return self.get(name)
