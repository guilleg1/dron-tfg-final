"""
scenario_generator.py — Generador de escenarios aleatorios reproducibles.

Genera escenarios con flota heterogénea de drones y pedidos aleatorios
usando los destinos reales de route_profiles.json como base geográfica.

La reproducibilidad se garantiza mediante semillas (seeds) controladas.
"""

from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass, field
from pathlib import Path

from core.energy import (
    DEFAULT_FLEET_DISTRIBUTION,
    DroneSpec,
    DRONE_CATEGORIES,
)


# ── Destinos reales del proyecto (de route_profiles.json) ────────────────────

# Parking "Central" de Castelldefels (origen de los drones)
PARKING_LAT = 41.283720590600794
PARKING_LON = 1.9850507581982129

# Destinos extraídos de route_profiles.json
DESTINATIONS = [
    {"name": "Castillo",      "lat": 41.284412643159115, "lon": 1.9782211905846054},
    {"name": "UPC",           "lat": 41.276446629191945, "lon": 1.9888945592449545},
    {"name": "SAFA",          "lat": 41.3080863096115,   "lon": 2.0034986926860086},
    {"name": "Campo-Futbol",  "lat": 41.304684136121914, "lon": 1.9960209046492707},
    {"name": "canal",         "lat": 41.279898995273015, "lon": 1.9924321974071972},
]

# ── Utilidades geográficas ───────────────────────────────────────────────────

def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distancia haversine entre dos puntos (km)."""
    R = 6371.0
    lat1_r, lon1_r = math.radians(lat1), math.radians(lon1)
    lat2_r, lon2_r = math.radians(lat2), math.radians(lon2)
    dlat = lat2_r - lat1_r
    dlon = lon2_r - lon1_r
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


# ── Dataclasses de escenario ─────────────────────────────────────────────────

@dataclass
class DroneState:
    """Estado de un dron al inicio de un escenario."""
    spec: DroneSpec
    battery_wh: float

    @property
    def battery_pct(self) -> float:
        if self.spec.battery_capacity_wh <= 0:
            return 0.0
        return (self.battery_wh / self.spec.battery_capacity_wh) * 100.0


@dataclass
class Order:
    """Pedido con peso y ubicación."""
    order_id: int
    weight_kg: float
    client_lat: float
    client_lon: float
    destination_name: str   # destino más cercano de route_profiles
    distance_km: float      # distancia parking → cliente (ida)


@dataclass
class Scenario:
    """Escenario completo: flota + pedidos."""
    scenario_id: int
    drones: list[DroneState]
    orders: list[Order]
    charger_power_w: float = 180.0


# ── Generadores ──────────────────────────────────────────────────────────────

def _create_fleet(
    n_drones: int,
    rng: random.Random,
    battery_min_pct: float = 0.6,
    battery_max_pct: float = 1.0,
    fleet_composition: dict[str, int] | None = None,
) -> list[DroneState]:
    """
    Crea una flota heterogénea de drones.

    Para n_drones=5, usa la distribución por defecto (2L+2M+1P) si no se especifica otra.
    Si se especifica fleet_composition (ej. {"ligero": 2, "medio": 2, "pesado": 1}), se usa.
    """
    if fleet_composition is not None:
        categories = []
        for cat_name, count in fleet_composition.items():
            for i in range(count):
                categories.append((cat_name, f"D-{cat_name[0].upper()}{i+1}"))
        fleet_dist = categories[:n_drones]
    elif n_drones == 5:
        fleet_dist = DEFAULT_FLEET_DISTRIBUTION
    else:
        # Distribución proporcional: ~40% ligeros, ~40% medios, ~20% pesados
        categories = []
        n_light = max(1, round(n_drones * 0.4))
        n_medium = max(1, round(n_drones * 0.4))
        n_heavy = max(1, n_drones - n_light - n_medium)
        for i in range(n_light):
            categories.append(("ligero", f"D-L{i + 1}"))
        for i in range(n_medium):
            categories.append(("medio", f"D-M{i + 1}"))
        for i in range(n_heavy):
            categories.append(("pesado", f"D-H{i + 1}"))
        fleet_dist = categories[:n_drones]

    drones = []
    for cat_name, drone_id in fleet_dist:
        template = DRONE_CATEGORIES[cat_name]
        spec = DroneSpec(
            drone_id=drone_id,
            max_payload_kg=template.max_payload_kg,
            battery_capacity_wh=template.battery_capacity_wh,
            cruise_speed_mps=template.cruise_speed_mps,
            base_consumption_w=template.base_consumption_w,
            payload_factor_w_per_kg=template.payload_factor_w_per_kg,
        )
        battery_pct = rng.uniform(battery_min_pct, battery_max_pct)
        battery_wh = spec.battery_capacity_wh * battery_pct
        drones.append(DroneState(spec=spec, battery_wh=battery_wh))

    return drones


def _create_orders(
    n_orders: int,
    rng: random.Random,
    weight_min_kg: float = 0.3,
    weight_max_kg: float = 4.0,
    scatter_km: float = 0.5,
) -> list[Order]:
    """
    Genera pedidos aleatorios alrededor de los destinos reales.

    Cada pedido:
      - Se asigna a un destino aleatorio de DESTINATIONS
      - Se desplaza con scatter gaussiano (σ ≈ scatter_km)
      - Peso uniforme entre weight_min y weight_max
      - Distancia calculada con haversine desde PARKING
    """
    orders = []
    for i in range(n_orders):
        # Elegir destino aleatorio
        dest = rng.choice(DESTINATIONS)

        # Scatter gaussiano alrededor del destino
        # 1 grado ≈ 111 km, scatter_km/111 ≈ desplazamiento en grados
        scatter_deg = scatter_km / 111.0
        client_lat = dest["lat"] + rng.gauss(0, scatter_deg)
        client_lon = dest["lon"] + rng.gauss(0, scatter_deg)

        # Peso del paquete
        weight = rng.uniform(weight_min_kg, weight_max_kg)

        # Distancia desde el parking
        distance = _haversine_km(PARKING_LAT, PARKING_LON, client_lat, client_lon)

        orders.append(
            Order(
                order_id=i + 1,
                weight_kg=round(weight, 2),
                client_lat=client_lat,
                client_lon=client_lon,
                destination_name=dest["name"],
                distance_km=round(distance, 3),
            )
        )

    return orders


def generate_scenario(
    n_drones: int = 5,
    n_orders: int = 30,
    seed: int | None = None,
    charger_power_w: float = 180.0,
    battery_min_pct: float = 0.6,
    battery_max_pct: float = 1.0,
    weight_min_kg: float = 0.3,
    weight_max_kg: float = 4.0,
    fleet_composition: dict[str, int] | None = None,
) -> Scenario:
    """
    Genera un escenario aleatorio reproducible.

    Parameters
    ----------
    n_drones : int
        Número de drones en la flota.
    n_orders : int
        Número de pedidos a generar.
    seed : int or None
        Semilla para reproducibilidad.
    charger_power_w : float
        Potencia del cargador (W).
    battery_min_pct, battery_max_pct : float
        Rango de batería inicial (fracción 0-1).
    weight_min_kg, weight_max_kg : float
        Rango de peso de pedidos (kg).

    Returns
    -------
    Scenario
    """
    rng = random.Random(seed)
    drones = _create_fleet(n_drones, rng, battery_min_pct, battery_max_pct, fleet_composition)
    orders = _create_orders(n_orders, rng, weight_min_kg, weight_max_kg)

    return Scenario(
        scenario_id=seed if seed is not None else 0,
        drones=drones,
        orders=orders,
        charger_power_w=charger_power_w,
    )


def generate_batch(
    n_scenarios: int,
    n_drones: int = 5,
    n_orders: int = 30,
    seed: int = 42,
    charger_power_w: float = 180.0,
    fleet_composition: dict[str, int] | None = None,
    weight_min_kg: float = 0.3,
    weight_max_kg: float = 4.0,
    battery_min_pct: float = 0.6,
    battery_max_pct: float = 1.0,
) -> list[Scenario]:
    """
    Genera múltiples escenarios para comparación estadística.

    Cada escenario usa una semilla distinta (seed + i) para reproducibilidad.

    Parameters
    ----------
    n_scenarios : int
        Número de escenarios a generar.
    n_drones, n_orders : int
        Tamaño de cada escenario.
    seed : int
        Semilla base (cada escenario usa seed+i).
    charger_power_w : float
        Potencia del cargador (W).
    battery_min_pct, battery_max_pct : float
        Rango de batería inicial. Bajarlo crea escenarios con escasez de
        autonomía, donde la asignación importa de verdad.

    Returns
    -------
    list[Scenario]
    """
    return [
        generate_scenario(
            n_drones=n_drones,
            n_orders=n_orders,
            seed=seed + i,
            charger_power_w=charger_power_w,
            fleet_composition=fleet_composition,
            weight_min_kg=weight_min_kg,
            weight_max_kg=weight_max_kg,
            battery_min_pct=battery_min_pct,
            battery_max_pct=battery_max_pct,
        )
        for i in range(n_scenarios)
    ]


# Escenario "exigente" por defecto para la comparación: un único ciclo de
# despacho en el que la flota arranca con poca batería y los paquetes son
# pesados, de modo que la demanda supera la capacidad disponible. Es el régimen
# realista (una oleada de reparto) en el que la asignación global se distingue
# de la voraz.
DEMANDING_PRESET = dict(
    n_orders=20,
    weight_min_kg=2.0,
    weight_max_kg=4.0,
    battery_min_pct=0.5,
    battery_max_pct=0.9,
)
