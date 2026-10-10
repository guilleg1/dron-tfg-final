"""
greedy_assigner.py — Algoritmo de asignación voraz (Greedy) FIFO.

Procesa los pedidos en orden de llegada (FIFO) y asigna cada uno
al dron disponible con menor coste, que es la energía del viaje. Actualiza la batería del dron
tras cada asignación.

Limitación conocida: el greedy es sensible al orden de los pedidos
y no garantiza la solución óptima global. Es el baseline para
comparar con Jonker-Volgenant.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from core.cost import compute_cost
from core.energy import (
    DroneSpec,
    estimate_duration_s,
    estimate_trip_energy_wh,
)


@dataclass
class Assignment:
    """Una asignación dron↔pedido con métricas calculadas."""

    drone_id: str
    order_id: int
    cost: float
    energy_wh: float
    duration_s: float
    round_num: int = 0  # en qué ronda se asignó


@dataclass
class AssignmentResult:
    """Resultado completo de una asignación (greedy o JV)."""

    assignments: list[Assignment]
    unassigned_orders: list[int]
    total_energy_wh: float
    total_time_s: float

    @property
    def n_delivered(self) -> int:
        return len(self.assignments)

    @property
    def n_unassigned(self) -> int:
        return len(self.unassigned_orders)

    @property
    def avg_energy_per_delivery(self) -> float:
        if self.n_delivered == 0:
            return 0.0
        return self.total_energy_wh / self.n_delivered


@dataclass
class DroneState:
    """Estado mutable de un dron durante la simulación."""

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
    distance_km: float  # distancia parking → cliente (ida)
    client_lat: float = 0.0
    client_lon: float = 0.0
    destination_name: str = ""


def greedy_assign(
    drones: list[DroneState],
    orders: list[Order],
) -> AssignmentResult:
    """
    Asignación voraz FIFO: procesa pedidos en orden de llegada.

    Para cada pedido (en orden):
      1. Calcular el coste C(i,j) (energía del viaje) para todos los drones
      2. Asignar al dron con menor coste finito
      3. Actualizar batería del dron asignado
      4. Si todos los costes = ∞, pedido queda sin asignar

    Parameters
    ----------
    drones : list[DroneState]
        Estado actual de cada dron (se modifica in-place la batería).
    orders : list[Order]
        Pedidos a asignar, en orden FIFO.

    Returns
    -------
    AssignmentResult
        Asignaciones realizadas y pedidos sin asignar.
    """
    assignments: list[Assignment] = []
    unassigned: list[int] = []

    # Copiar baterías para no mutar el input directamente
    batteries = [d.battery_wh for d in drones]

    for order in orders:
        best_idx = -1
        best_cost = math.inf

        # Evaluar cada dron
        for i, drone in enumerate(drones):
            c = compute_cost(
                drone.spec,
                batteries[i],
                order.weight_kg,
                order.distance_km,
            )
            if c < best_cost:
                best_cost = c
                best_idx = i

        if best_idx < 0 or math.isinf(best_cost):
            unassigned.append(order.order_id)
            continue

        # Calcular métricas del viaje
        drone = drones[best_idx]
        e_trip = estimate_trip_energy_wh(drone.spec, order.distance_km, order.weight_kg)
        t_trip = estimate_duration_s(order.distance_km, drone.spec.cruise_speed_mps)

        assignments.append(
            Assignment(
                drone_id=drone.spec.drone_id,
                order_id=order.order_id,
                cost=best_cost,
                energy_wh=e_trip,
                duration_s=t_trip,
            )
        )

        # Actualizar batería
        batteries[best_idx] -= e_trip

    # Calcular totales
    total_energy = sum(a.energy_wh for a in assignments)
    # Makespan = máximo tiempo acumulado por dron
    drone_times: dict[str, float] = {}
    for a in assignments:
        drone_times[a.drone_id] = drone_times.get(a.drone_id, 0.0) + a.duration_s
    total_time = max(drone_times.values()) if drone_times else 0.0

    return AssignmentResult(
        assignments=assignments,
        unassigned_orders=unassigned,
        total_energy_wh=total_energy,
        total_time_s=total_time,
    )
