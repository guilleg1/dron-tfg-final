"""
cost.py — Coste de asignar un dron a un pedido.

El coste es la energía del viaje completo (ida con el paquete y vuelta en
vacío), en Wh, según el modelo de ``core.energy``. Dos restricciones lo hacen
infinito, es decir, descartan la pareja:

  - el peso del paquete supera la carga máxima del dron;
  - el viaje invadiría la reserva: E_viaje > batería_actual − 0,20 × capacidad_nominal.

Una versión anterior combinaba cinco términos normalizados con pesos
ajustables. El estudio de la memoria mostró que la asignación la decidía casi
solo la energía, así que el coste se quedó en esa única magnitud física, que
no necesita ni normalización ni pesos.
"""

from __future__ import annotations

import math

import numpy as np

from core.energy import DroneSpec, estimate_trip_energy_wh

SAFETY_MARGIN = 0.2       # 20 % de reserva sobre la capacidad nominal (airdrop/swarm/safety.py)
INFEASIBLE = 1e18         # valor de la matriz para parejas inviables (scipy no admite inf)


def compute_cost(
    drone_spec: DroneSpec,
    drone_battery_wh: float,
    order_weight_kg: float,
    distance_km: float,
) -> float:
    """Energía del viaje en Wh, o ``math.inf`` si la pareja es inviable."""
    if order_weight_kg > drone_spec.max_payload_kg:
        return math.inf
    e_trip = estimate_trip_energy_wh(drone_spec, distance_km, order_weight_kg)
    usable_battery = drone_battery_wh - SAFETY_MARGIN * drone_spec.battery_capacity_wh
    if e_trip > usable_battery:
        return math.inf
    return e_trip


def build_cost_matrix(
    drone_specs: list[DroneSpec],
    drone_batteries_wh: list[float],
    order_weights_kg: list[float],
    distances_km: list[list[float]],
) -> np.ndarray:
    """Matriz N_drones × M_pedidos de costes, con ``INFEASIBLE`` en las parejas inviables."""
    matrix = np.full((len(drone_specs), len(order_weights_kg)), INFEASIBLE, dtype=np.float64)
    for i, spec in enumerate(drone_specs):
        for j, peso in enumerate(order_weights_kg):
            c = compute_cost(spec, drone_batteries_wh[i], peso, distances_km[i][j])
            if not math.isinf(c):
                matrix[i, j] = c
    return matrix
