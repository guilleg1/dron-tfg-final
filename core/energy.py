"""
energy_model.py — Modelo de energía lineal para drones de reparto.

Basado en Zhang et al. (2021) "Energy Consumption Models for Delivery Drones"
y la formulación del TFG (Investigación modulos y algoritmo.pdf):

    E_ida(%) = α · t_ida + β · m_payload · d_ida
    E_vuelta(%) = α · t_vuelta

Simplificado a:  E = (P_base + P_payload × weight) × t
donde t = distancia / velocidad.

Todas las funciones son puras (sin estado) para facilitar tests y reutilización.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DroneSpec:
    """Especificación estática de un dron (inmutable)."""

    drone_id: str
    max_payload_kg: float           # capacidad máxima de carga (kg)
    battery_capacity_wh: float      # capacidad total de batería (Wh)
    cruise_speed_mps: float         # velocidad de crucero (m/s)
    base_consumption_w: float       # potencia base hover sin carga (W)
    payload_factor_w_per_kg: float  # potencia adicional por kg de carga (W/kg)


# ── Catálogo de categorías (de fleet.yaml / 03-ARCHITECTURE.md) ──────────────

DRONE_CATEGORIES: dict[str, DroneSpec] = {
    "ligero": DroneSpec(
        drone_id="",
        max_payload_kg=1.0,
        battery_capacity_wh=148.0,
        cruise_speed_mps=8.0,
        base_consumption_w=140.0,
        payload_factor_w_per_kg=30.0,
    ),
    "medio": DroneSpec(
        drone_id="",
        max_payload_kg=2.0,
        battery_capacity_wh=222.0,
        cruise_speed_mps=7.0,
        base_consumption_w=180.0,
        payload_factor_w_per_kg=22.0,
    ),
    "pesado": DroneSpec(
        drone_id="",
        max_payload_kg=4.0,
        battery_capacity_wh=360.0,
        cruise_speed_mps=6.0,
        base_consumption_w=280.0,
        payload_factor_w_per_kg=18.0,
    ),
}

# Distribución de la flota de 5 drones: 2 ligeros, 2 medios, 1 pesado
DEFAULT_FLEET_DISTRIBUTION = [
    ("ligero", "D-1"),
    ("ligero", "D-2"),
    ("medio",  "D-3"),
    ("medio",  "D-4"),
    ("pesado", "D-5"),
]


# ── Funciones de estimación ──────────────────────────────────────────────────


def estimate_energy_wh(
    spec: DroneSpec,
    distance_km: float,
    weight_kg: float,
) -> float:
    """
    Estima la energía consumida en un tramo unidireccional (Wh).

    E = (P_base + P_payload × weight_kg) × t_horas
    t_horas = (distance_km × 1000) / cruise_speed_mps / 3600

    Parameters
    ----------
    spec : DroneSpec
        Especificaciones del dron.
    distance_km : float
        Distancia del tramo en kilómetros.
    weight_kg : float
        Peso de la carga en kilogramos (0 para vuelo sin carga).

    Returns
    -------
    float
        Energía consumida en Wh (siempre ≥ 0).
    """
    if distance_km <= 0:
        return 0.0
    power_w = spec.base_consumption_w + spec.payload_factor_w_per_kg * max(weight_kg, 0.0)
    time_h = (distance_km * 1000.0) / spec.cruise_speed_mps / 3600.0
    return power_w * time_h


def estimate_trip_energy_wh(
    spec: DroneSpec,
    distance_km: float,
    weight_kg: float,
) -> float:
    """
    Estima la energía total del viaje completo: ida (con carga) + vuelta (sin carga).

    Parameters
    ----------
    spec : DroneSpec
        Especificaciones del dron.
    distance_km : float
        Distancia de ida al cliente (km). La vuelta se asume igual.
    weight_kg : float
        Peso del paquete (kg).

    Returns
    -------
    float
        Energía total ida+vuelta en Wh.
    """
    e_ida = estimate_energy_wh(spec, distance_km, weight_kg)
    e_vuelta = estimate_energy_wh(spec, distance_km, 0.0)
    return e_ida + e_vuelta


def estimate_duration_s(distance_km: float, speed_mps: float) -> float:
    """
    Estima la duración del viaje ida+vuelta en segundos.

    Parameters
    ----------
    distance_km : float
        Distancia de ida (km).
    speed_mps : float
        Velocidad de crucero (m/s).

    Returns
    -------
    float
        Duración total ida+vuelta en segundos.
    """
    if distance_km <= 0 or speed_mps <= 0:
        return 0.0
    return (2.0 * distance_km * 1000.0) / speed_mps


def is_feasible(
    spec: DroneSpec,
    battery_wh: float,
    distance_km: float,
    weight_kg: float,
    safety_margin: float = 0.2,
) -> bool:
    """
    Verifica si el dron puede completar el viaje manteniendo un margen de seguridad.

    El dron es factible si:
      1. Puede cargar el peso (weight_kg ≤ max_payload_kg)
      2. E_viaje ≤ battery_wh − safety_margin × capacidad_nominal
         (la reserva se calcula sobre la capacidad nominal, como en airdrop/swarm/safety.py)

    Parameters
    ----------
    spec : DroneSpec
        Especificaciones del dron.
    battery_wh : float
        Batería actual disponible (Wh).
    distance_km : float
        Distancia de ida (km).
    weight_kg : float
        Peso del paquete (kg).
    safety_margin : float
        Fracción de la capacidad nominal reservada como margen (default 0.2 = 20%).

    Returns
    -------
    bool
        True si el viaje es factible.
    """
    if weight_kg > spec.max_payload_kg:
        return False
    e_trip = estimate_trip_energy_wh(spec, distance_km, weight_kg)
    usable_battery = battery_wh - safety_margin * spec.battery_capacity_wh
    return e_trip <= usable_battery


def estimate_charge_time_s(
    energy_needed_wh: float,
    charger_power_w: float,
) -> float:
    """
    Estima el tiempo de recarga necesario en segundos.

    T_carga = (E_necesaria / P_cargador) × 3600

    Parameters
    ----------
    energy_needed_wh : float
        Energía que falta por cargar (Wh).
    charger_power_w : float
        Potencia del cargador (W).

    Returns
    -------
    float
        Tiempo de recarga en segundos (≥ 0).
    """
    if energy_needed_wh <= 0 or charger_power_w <= 0:
        return 0.0
    return (energy_needed_wh / charger_power_w) * 3600.0
