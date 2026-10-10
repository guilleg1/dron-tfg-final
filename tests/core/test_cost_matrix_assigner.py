"""
Tests unitarios para cost_matrix_assigner.py.
"""

import pytest

from core.energy import DroneSpec, DRONE_CATEGORIES
from core.greedy import DroneState, Order
from core.cost_matrix import cost_matrix_assign



def test_jv_simple_case():
    """Un dron, un pedido, caso trivial."""
    drones = [DroneState(spec=DRONE_CATEGORIES["medio"], battery_wh=222.0)]
    orders = [Order(order_id=1, weight_kg=1.0, distance_km=1.0)]

    result = cost_matrix_assign(drones, orders)

    assert result.n_delivered == 1
    assert result.n_unassigned == 0
    assert len(result.assignments) == 1
    assert result.assignments[0].order_id == 1


def test_jv_infeasible_weight():
    """El pedido es muy pesado para el dron, no se asigna."""
    drones = [DroneState(spec=DRONE_CATEGORIES["ligero"], battery_wh=148.0)]
    orders = [Order(order_id=1, weight_kg=3.0, distance_km=1.0)]

    result = cost_matrix_assign(drones, orders)

    assert result.n_delivered == 0
    assert result.n_unassigned == 1
    assert result.unassigned_orders == [1]


def test_jv_rectangular_case():
    """Más pedidos que drones, requiere múltiples rondas."""
    # 1 dron, 3 pedidos pequeños
    drones = [DroneState(spec=DRONE_CATEGORIES["pesado"], battery_wh=360.0)]
    orders = [
        Order(order_id=1, weight_kg=1.0, distance_km=1.0),
        Order(order_id=2, weight_kg=1.0, distance_km=1.0),
        Order(order_id=3, weight_kg=1.0, distance_km=1.0),
    ]

    result = cost_matrix_assign(drones, orders)

    assert result.n_delivered == 3
    assert result.n_unassigned == 0

    # Deben haberse asignado en rondas distintas
    rounds = [a.round_num for a in result.assignments]
    assert len(set(rounds)) == 3


def test_jv_partial_infeasibility():
    """Algunos pedidos son factibles, otros no."""
    drones = [DroneState(spec=DRONE_CATEGORIES["ligero"], battery_wh=148.0)]
    orders = [
        Order(order_id=1, weight_kg=0.5, distance_km=1.0),  # OK
        Order(order_id=2, weight_kg=3.0, distance_km=1.0),  # Excede payload
    ]

    result = cost_matrix_assign(drones, orders)

    assert result.n_delivered == 1
    assert result.n_unassigned == 1
    assert result.assignments[0].order_id == 1
    assert result.unassigned_orders == [2]
