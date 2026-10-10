"""
cost_matrix_assigner.py — Asignación óptima global mediante Jonker-Volgenant.

Usa scipy.optimize.linear_sum_assignment (implementación del algoritmo
Jonker-Volgenant, O(n³)) para resolver el problema de asignación de coste
mínimo sobre la matriz de costes completa.

Cuando hay más pedidos que drones (caso habitual: 30 pedidos, 5 drones),
el algoritmo opera en rondas:
  - Ronda 1: asigna hasta N pedidos (uno por dron)
  - Actualiza baterías
  - Ronda 2: re-calcula costes, asigna los siguientes
  - ...hasta agotar pedidos o drones

Referencia: Investigación modulos y algoritmo.pdf
  "Jonker-Volgenant se basa en una matriz de costes para que dados
   una serie de drones se les asigne un coste para realizar una tarea"
"""

from __future__ import annotations

import math

import numpy as np
from scipy.optimize import linear_sum_assignment

from core.cost import build_cost_matrix
from core.energy import (
    DroneSpec,
    estimate_duration_s,
    estimate_trip_energy_wh,
)
from core.greedy import (
    Assignment,
    AssignmentResult,
    DroneState,
    Order,
)

# Umbral para considerar un coste como infactible (mismo valor que en cost_function)
_INF_THRESHOLD = 1e17


def cost_matrix_assign(
    drones: list[DroneState],
    orders: list[Order],
) -> AssignmentResult:
    """
    Asignación óptima global por rondas con Jonker-Volgenant.

    En cada ronda:
      1. Construir matriz de costes C[n_drones × m_pedidos_restantes]
      2. Resolver con linear_sum_assignment
      3. Filtrar asignaciones infactibles (coste ≥ 1e17)
      4. Actualizar baterías de drones asignados
      5. Pedidos no asignados pasan a la siguiente ronda

    Termina cuando:
      - No quedan pedidos
      - Ningún dron puede aceptar ningún pedido (toda la fila es inf)

    Parameters
    ----------
    drones : list[DroneState]
        Estado actual de cada dron.
    orders : list[Order]
        Pedidos a asignar.

    Returns
    -------
    AssignmentResult
        Asignaciones óptimas y pedidos sin asignar.
    """
    all_assignments: list[Assignment] = []
    pending_orders = list(orders)  # copia para no mutar input

    # Copiar baterías para no mutar el input
    batteries = [d.battery_wh for d in drones]
    specs = [d.spec for d in drones]

    round_num = 0
    max_rounds = len(orders) + 1  # safety: evitar loop infinito

    while pending_orders and round_num < max_rounds:
        round_num += 1

        n_drones = len(drones)
        m_orders = len(pending_orders)

        # Construir matrices de distancias y pesos
        order_weights = [o.weight_kg for o in pending_orders]
        distances = [[o.distance_km for o in pending_orders] for _ in range(n_drones)]

        # Construir matriz de costes (energía del viaje de cada pareja)
        cost_matrix = build_cost_matrix(specs, batteries, order_weights, distances)

        # Verificar si hay alguna asignación factible
        if np.all(cost_matrix >= _INF_THRESHOLD):
            break  # Ningún dron puede hacer ningún pedido

        # Resolver asignación óptima
        # linear_sum_assignment acepta matrices rectangulares
        row_ind, col_ind = linear_sum_assignment(cost_matrix)

        # Procesar asignaciones de esta ronda
        assigned_order_indices = set()
        made_assignment = False

        for r, c in zip(row_ind, col_ind):
            if cost_matrix[r, c] >= _INF_THRESHOLD:
                continue  # Asignación infactible, saltar

            drone = drones[r]
            order = pending_orders[c]

            e_trip = estimate_trip_energy_wh(drone.spec, order.distance_km, order.weight_kg)
            t_trip = estimate_duration_s(order.distance_km, drone.spec.cruise_speed_mps)

            all_assignments.append(
                Assignment(
                    drone_id=drone.spec.drone_id,
                    order_id=order.order_id,
                    cost=cost_matrix[r, c],
                    energy_wh=e_trip,
                    duration_s=t_trip,
                    round_num=round_num,
                )
            )

            # Actualizar batería
            batteries[r] -= e_trip
            assigned_order_indices.add(c)
            made_assignment = True

        if not made_assignment:
            break  # No se pudo asignar nada en esta ronda

        # Eliminar pedidos asignados (en orden inverso para mantener índices)
        pending_orders = [
            o for i, o in enumerate(pending_orders) if i not in assigned_order_indices
        ]

    # Pedidos sin asignar
    unassigned = [o.order_id for o in pending_orders]

    # Calcular totales
    total_energy = sum(a.energy_wh for a in all_assignments)
    drone_times: dict[str, float] = {}
    for a in all_assignments:
        drone_times[a.drone_id] = drone_times.get(a.drone_id, 0.0) + a.duration_s
    total_time = max(drone_times.values()) if drone_times else 0.0

    return AssignmentResult(
        assignments=all_assignments,
        unassigned_orders=unassigned,
        total_energy_wh=total_energy,
        total_time_s=total_time,
    )
