"""Modelo de dominio del enjambre.

Dos objetos con vidas muy distintas:

- ``DroneRecord`` es la definición del dron. Inmutable, vive en la base de
  datos y solo cambia si el administrador reconfigura la flota.
- ``DroneRuntime`` es su estado vivo. Cambia varias veces por segundo y no se
  persiste: escribir telemetría a 10 Hz en la base de datos no aporta nada.

Las specs físicas (carga, batería, velocidad, consumos) no se declaran aquí:
salen de ``core.energy.DRONE_CATEGORIES`` a partir de la categoría, para que
la flota que vuela use exactamente los mismos parámetros que la flota que se
simula en ``research/``.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from core.energy import DRONE_CATEGORIES, DroneSpec

# ── Estados del ciclo de vida ────────────────────────────────────────────────
OFFLINE = "offline"          # sin conexión con el autopiloto
IDLE = "idle"                # en su pad, listo
ARMING = "arming"
TAKING_OFF = "taking_off"
IN_TRANSIT = "in_transit"    # camino del cliente
DELIVERING = "delivering"    # aterrizado en el cliente, entregando
RETURNING = "returning"      # de vuelta al parking
LANDING = "landing"
ERROR = "error"

DRONE_STATES = (OFFLINE, IDLE, ARMING, TAKING_OFF, IN_TRANSIT,
                DELIVERING, RETURNING, LANDING, ERROR)

# Estados en los que el dron está ocupado con una entrega.
BUSY_STATES = (ARMING, TAKING_OFF, IN_TRANSIT, DELIVERING, RETURNING, LANDING)


@dataclass(frozen=True)
class DroneRecord:
    """Definición de un dron de la flota."""

    drone_id: str
    sysid: int
    instance: int
    category: str
    connection: str
    home_lat: float
    home_lon: float
    enabled: bool = True

    @property
    def spec(self) -> DroneSpec:
        """Specs de su categoría, con el identificador real de este dron.

        El catálogo de ``core.energy`` deja ``drone_id`` vacío porque describe
        categorías, no drones concretos.
        """
        return replace(DRONE_CATEGORIES[self.category], drone_id=self.drone_id)

    def as_dict(self) -> dict:
        spec = self.spec
        return {
            "drone_id": self.drone_id,
            "sysid": self.sysid,
            "instance": self.instance,
            "category": self.category,
            "connection": self.connection,
            "home_lat": self.home_lat,
            "home_lon": self.home_lon,
            "enabled": self.enabled,
            "max_payload_kg": spec.max_payload_kg,
            "battery_capacity_wh": spec.battery_capacity_wh,
            "cruise_speed_mps": spec.cruise_speed_mps,
        }


@dataclass
class DroneRuntime:
    """Estado vivo de un dron. Solo en memoria."""

    drone_id: str
    state: str = OFFLINE
    battery_wh: float = 0.0
    battery_capacity_wh: float = 0.0
    cruise_alt_m: float | None = None   # slot reservado para el vuelo en curso
    lat: float | None = None
    lon: float | None = None
    alt: float | None = None
    heading: float | None = None
    ground_speed: float | None = None
    current_order_id: int | None = None
    detail: str = ""

    @property
    def battery_pct(self) -> float:
        if self.battery_capacity_wh <= 0:
            return 0.0
        return max(0.0, min(100.0, self.battery_wh / self.battery_capacity_wh * 100.0))

    @property
    def is_available(self) -> bool:
        """Solo un dron parado en su pad puede recibir un pedido."""
        return self.state == IDLE

    def as_dict(self) -> dict:
        return {
            "drone_id": self.drone_id,
            "state": self.state,
            "battery_wh": round(self.battery_wh, 1),
            "battery_pct": round(self.battery_pct, 1),
            "cruise_alt_m": self.cruise_alt_m,
            "lat": self.lat,
            "lon": self.lon,
            "alt": self.alt,
            "heading": self.heading,
            "ground_speed": self.ground_speed,
            "current_order_id": self.current_order_id,
            "detail": self.detail,
        }
