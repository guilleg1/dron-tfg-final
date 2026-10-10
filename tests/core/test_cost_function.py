"""
Tests unitarios de core/cost.py: el coste es la energía del viaje.
"""

import math

import pytest

from core.cost import SAFETY_MARGIN, build_cost_matrix, compute_cost
from core.energy import DRONE_CATEGORIES, estimate_trip_energy_wh

LIGERO = DRONE_CATEGORIES["ligero"]
MEDIO = DRONE_CATEGORIES["medio"]
PESADO = DRONE_CATEGORIES["pesado"]


class TestHardConstraints:
    """Parejas inviables: coste infinito."""

    def test_weight_exceeds_payload(self):
        assert math.isinf(compute_cost(LIGERO, LIGERO.battery_capacity_wh, 2.0, 1.0))

    def test_energy_exceeds_battery(self):
        assert math.isinf(compute_cost(MEDIO, 5.0, 1.5, 1.0))

    def test_exact_payload_is_feasible(self):
        assert not math.isinf(compute_cost(LIGERO, LIGERO.battery_capacity_wh, 1.0, 0.5))

    def test_reserve_limit(self):
        """Justo en el límite de la reserva es viable; un poco por debajo, no."""
        e = estimate_trip_energy_wh(MEDIO, 2.0, 1.0)
        limite = e + SAFETY_MARGIN * MEDIO.battery_capacity_wh
        assert compute_cost(MEDIO, limite, 1.0, 2.0) == pytest.approx(e)
        assert math.isinf(compute_cost(MEDIO, limite - 0.1, 1.0, 2.0))


class TestCostValue:
    """El coste de una pareja viable es la energía del viaje."""

    def test_cost_is_trip_energy(self):
        c = compute_cost(MEDIO, MEDIO.battery_capacity_wh, 1.0, 1.0)
        assert c == pytest.approx(estimate_trip_energy_wh(MEDIO, 1.0, 1.0))

    def test_cost_increases_with_distance(self):
        b = MEDIO.battery_capacity_wh
        assert compute_cost(MEDIO, b, 1.0, 2.0) > compute_cost(MEDIO, b, 1.0, 0.5)

    def test_cost_increases_with_payload(self):
        b = PESADO.battery_capacity_wh
        assert compute_cost(PESADO, b, 3.5, 1.0) > compute_cost(PESADO, b, 0.5, 1.0)

    def test_cost_does_not_depend_on_battery_level(self):
        """La batería solo decide si el viaje es viable, no cuánto cuesta."""
        assert compute_cost(MEDIO, 222.0, 1.0, 1.0) == compute_cost(MEDIO, 150.0, 1.0, 1.0)

    def test_light_drone_is_cheaper_for_a_light_parcel(self):
        """Para 1 kg a 3 km el ligero gasta unas 2,5 veces menos que el pesado."""
        c_l = compute_cost(LIGERO, LIGERO.battery_capacity_wh, 1.0, 3.0)
        c_p = compute_cost(PESADO, PESADO.battery_capacity_wh, 1.0, 3.0)
        assert c_l < c_p
        assert c_p / c_l == pytest.approx(2.5, abs=0.1)


class TestCostMatrix:
    """build_cost_matrix."""

    def test_matrix_shape(self):
        mat = build_cost_matrix([LIGERO, MEDIO], [148.0, 222.0], [0.5, 1.0, 2.0],
                                [[1.0] * 3, [1.0] * 3])
        assert mat.shape == (2, 3)

    def test_infeasible_cells_are_large(self):
        mat = build_cost_matrix([LIGERO], [148.0], [5.0], [[1.0]])
        assert mat[0, 0] >= 1e17

    def test_feasible_cells_match_compute_cost(self):
        mat = build_cost_matrix([MEDIO], [222.0], [1.0], [[0.5]])
        assert mat[0, 0] == pytest.approx(compute_cost(MEDIO, 222.0, 1.0, 0.5))
