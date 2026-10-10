"""
simulator.py — Motor de simulación con rondas y recarga.

Ejecuta lotes de pedidos sobre una flota de drones, simulando:
  - Consumo de batería (modelo de energía lineal)
  - Tiempos de vuelo (distancia / velocidad)
  - Recarga entre rondas (T_carga = E_necesaria / P_cargador)
  - Drones que agotan batería

Soporta dos algoritmos: Greedy (FIFO) y Jonker-Volgenant (matriz de costes).
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field

from core.energy import (
    DroneSpec,
    estimate_charge_time_s,
    estimate_trip_energy_wh,
    is_feasible,
)
from core.greedy import (
    Assignment,
    AssignmentResult,
    DroneState,
    Order,
    greedy_assign,
)
from core.cost_matrix import cost_matrix_assign
from research.simulacion.scenario_generator import Scenario


@dataclass
class DroneMetrics:
    """Métricas acumuladas por dron en una simulación."""
    drone_id: str
    category: str
    energy_used_wh: float = 0.0
    n_trips: int = 0
    total_flight_time_s: float = 0.0
    total_charge_time_s: float = 0.0
    initial_battery_wh: float = 0.0
    final_battery_wh: float = 0.0

    @property
    def utilization_pct(self) -> float:
        """Porcentaje de batería usado respecto a la inicial."""
        if self.initial_battery_wh <= 0:
            return 0.0
        return (self.energy_used_wh / self.initial_battery_wh) * 100.0


@dataclass
class SimulationResult:
    """Resultado completo de una simulación."""
    algorithm: str                        # "greedy" o "cost_matrix"
    total_energy_wh: float                # energía total consumida
    total_time_s: float                   # makespan (tiempo total del escenario)
    total_charge_time_s: float            # tiempo total en recargas
    n_delivered: int                      # pedidos entregados
    n_unassigned: int                     # pedidos sin asignar
    n_rounds: int                         # rondas necesarias
    assignments: list[Assignment]         # detalle por asignación
    drone_metrics: dict[str, DroneMetrics]  # métricas por dron

    @property
    def avg_energy_per_delivery(self) -> float:
        if self.n_delivered == 0:
            return 0.0
        return self.total_energy_wh / self.n_delivered

    @property
    def delivery_rate(self) -> float:
        total = self.n_delivered + self.n_unassigned
        if total == 0:
            return 0.0
        return self.n_delivered / total


def _categorize_drone(spec: DroneSpec) -> str:
    """Determina la categoría de un dron por su payload."""
    if spec.max_payload_kg <= 1.0:
        return "ligero"
    elif spec.max_payload_kg <= 2.0:
        return "medio"
    else:
        return "pesado"


def _can_any_drone_serve(
    drones: list[DroneState],
    orders: list[Order],
) -> bool:
    """Verifica si algún dron puede servir al menos un pedido."""
    for drone in drones:
        for order in orders:
            if is_feasible(drone.spec, drone.battery_wh, order.distance_km, order.weight_kg):
                return True
    return False


class Simulator:
    """
    Motor de simulación con rondas y recarga.

    En cada ronda:
      1. Asignar pedidos pendientes a drones disponibles
      2. Simular vuelos (energía + tiempo)
      3. Actualizar baterías
      4. Si hay pedidos restantes, recargar drones y volver a ronda 1
    """

    def __init__(self, charger_power_w: float = 180.0,
                 partial_recharge: bool = True,
                 recharge_safety: float = 0.3):
        """
        Parameters
        ----------
        charger_power_w : float
            Potencia del cargador (W).
        partial_recharge : bool
            Si True (mejora), recarga solo lo necesario para la cuota de viajes
            pendientes de cada dron (reduce el makespan, sobre todo en rondas
            finales). Si False, recarga al 100% como la solución base.
        recharge_safety : float
            Margen de seguridad sobre la energía estimada al recargar parcial.
        """
        self.charger_power_w = charger_power_w
        self.partial_recharge = partial_recharge
        self.recharge_safety = recharge_safety

    def run(
        self,
        scenario: Scenario,
        algorithm: str,
    ) -> SimulationResult:
        """
        Ejecuta una simulación completa.

        Parameters
        ----------
        scenario : Scenario
            Escenario con drones y pedidos.
        algorithm : str
            "greedy" o "cost_matrix" (Jonker-Volgenant).

        Returns
        -------
        SimulationResult
        """
        # Deep copy para no mutar el escenario original
        drones = [DroneState(spec=d.spec, battery_wh=d.battery_wh) for d in scenario.drones]
        pending_orders = list(scenario.orders)

        # Inicializar métricas por dron
        drone_metrics: dict[str, DroneMetrics] = {}
        for d in drones:
            drone_metrics[d.spec.drone_id] = DroneMetrics(
                drone_id=d.spec.drone_id,
                category=_categorize_drone(d.spec),
                initial_battery_wh=d.battery_wh,
                final_battery_wh=d.battery_wh,
            )

        all_assignments: list[Assignment] = []
        total_charge_time = 0.0
        n_rounds = 0
        max_rounds = len(scenario.orders) + 1

        while pending_orders and n_rounds < max_rounds:
            n_rounds += 1

            # Verificar si algún dron puede servir algún pedido
            if not _can_any_drone_serve(drones, pending_orders):
                # Intentar recargar
                recharged = self._recharge_drones(drones, pending_orders, drone_metrics)
                total_charge_time += recharged
                if recharged <= 0:
                    break  # No se pudo recargar → fin
                if not _can_any_drone_serve(drones, pending_orders):
                    break  # Ni con recarga → fin

            # Convertir al formato de los asignadores
            assigner_drones = [DroneState(spec=d.spec, battery_wh=d.battery_wh) for d in drones]
            assigner_orders = [
                Order(
                    order_id=o.order_id,
                    weight_kg=o.weight_kg,
                    distance_km=o.distance_km,
                    client_lat=getattr(o, 'client_lat', 0.0),
                    client_lon=getattr(o, 'client_lon', 0.0),
                    destination_name=getattr(o, 'destination_name', ''),
                )
                for o in pending_orders
            ]

            # Ejecutar asignador
            if algorithm == "greedy":
                result = greedy_assign(assigner_drones, assigner_orders)
            elif algorithm == "cost_matrix":
                result = cost_matrix_assign(assigner_drones, assigner_orders)
            else:
                raise ValueError(f"Algoritmo desconocido: {algorithm}")

            if not result.assignments:
                # No se pudo asignar nada → intentar recargar
                recharged = self._recharge_drones(drones, pending_orders, drone_metrics)
                total_charge_time += recharged
                if recharged <= 0:
                    break
                continue

            # Procesar asignaciones: actualizar baterías y métricas
            assigned_order_ids = set()
            for assignment in result.assignments:
                assignment.round_num = n_rounds
                all_assignments.append(assignment)
                assigned_order_ids.add(assignment.order_id)

                # Actualizar batería del dron
                for d in drones:
                    if d.spec.drone_id == assignment.drone_id:
                        d.battery_wh -= assignment.energy_wh
                        break

                # Actualizar métricas del dron
                dm = drone_metrics[assignment.drone_id]
                dm.energy_used_wh += assignment.energy_wh
                dm.n_trips += 1
                dm.total_flight_time_s += assignment.duration_s

            # Actualizar baterías finales
            for d in drones:
                drone_metrics[d.spec.drone_id].final_battery_wh = d.battery_wh

            # Eliminar pedidos asignados
            pending_orders = [o for o in pending_orders if o.order_id not in assigned_order_ids]

            # Si quedan pedidos, recargar drones antes de siguiente ronda
            if pending_orders:
                recharged = self._recharge_drones(drones, pending_orders, drone_metrics)
                total_charge_time += recharged

        # Calcular totales
        total_energy = sum(a.energy_wh for a in all_assignments)
        unassigned_ids = [o.order_id for o in pending_orders]

        # Makespan: máximo tiempo por dron (vuelo + recarga)
        drone_total_times: dict[str, float] = {}
        for dm in drone_metrics.values():
            drone_total_times[dm.drone_id] = dm.total_flight_time_s + dm.total_charge_time_s
        total_time = max(drone_total_times.values()) if drone_total_times else 0.0

        return SimulationResult(
            algorithm=algorithm,
            total_energy_wh=total_energy,
            total_time_s=total_time,
            total_charge_time_s=total_charge_time,
            n_delivered=len(all_assignments),
            n_unassigned=len(unassigned_ids),
            n_rounds=n_rounds,
            assignments=all_assignments,
            drone_metrics=drone_metrics,
        )

    def _recharge_drones(
        self,
        drones: list[DroneState],
        pending_orders: list,
        drone_metrics: dict[str, DroneMetrics],
    ) -> float:
        """
        Recarga los drones para poder seguir sirviendo pedidos pendientes.

        Dos políticas según ``self.partial_recharge``:
          - False (base): recarga al 100% cualquier dron con déficit > 10%.
          - True (mejora): recarga solo lo necesario para la cuota de viajes
            pendientes que le corresponde a cada dron (energía media por viaje
            × cuota + margen), acotado al 100%. Además, NO recarga drones que no
            pueden servir ningún pedido pendiente por carga útil (evita tiempo
            de recarga inútil). En las rondas finales (pocos pedidos) esto
            recorta drásticamente el makespan.

        Devuelve el tiempo máximo de recarga (los drones cargan en paralelo).
        """
        if not self.partial_recharge:
            return self._recharge_full(drones, drone_metrics)

        max_charge_time = 0.0
        any_recharged = False

        n_pending = len(pending_orders)
        n_drones = max(1, len(drones))
        # Cuota de viajes por dron (techo de la división entera).
        trips_quota = max(1, -(-n_pending // n_drones))

        for d in drones:
            cap = d.spec.battery_capacity_wh
            # Pedidos que este dron puede servir por carga útil.
            feasible = [o for o in pending_orders if o.weight_kg <= d.spec.max_payload_kg]
            if not feasible:
                continue  # recargar no le permite servir nada pendiente

            trip_energies = [
                estimate_trip_energy_wh(d.spec, o.distance_km, o.weight_kg)
                for o in feasible
            ]
            e_max = max(trip_energies)            # el viaje factible más caro
            e_avg = sum(trip_energies) / len(trip_energies)

            # Energía objetivo: cuota de viajes a coste medio, con margen, pero
            # como mínimo poder afrontar el viaje más caro. Acotada a la batería.
            needed_usable = max(e_max, e_avg * trips_quota)
            target_battery = min(cap, needed_usable + self.recharge_safety * cap)   # reserva sobre la capacidad nominal

            if target_battery - d.battery_wh > cap * 0.01:
                deficit = target_battery - d.battery_wh
                charge_time = estimate_charge_time_s(deficit, self.charger_power_w)
                d.battery_wh = target_battery
                max_charge_time = max(max_charge_time, charge_time)
                drone_metrics[d.spec.drone_id].total_charge_time_s += charge_time
                drone_metrics[d.spec.drone_id].final_battery_wh = d.battery_wh
                any_recharged = True

        return max_charge_time if any_recharged else 0.0

    def _recharge_full(self, drones, drone_metrics) -> float:
        """Política base: recarga al 100% (déficit > 10%)."""
        max_charge_time = 0.0
        any_recharged = False
        for d in drones:
            energy_deficit = d.spec.battery_capacity_wh - d.battery_wh
            if energy_deficit > d.spec.battery_capacity_wh * 0.1:
                charge_time = estimate_charge_time_s(energy_deficit, self.charger_power_w)
                d.battery_wh = d.spec.battery_capacity_wh
                max_charge_time = max(max_charge_time, charge_time)
                drone_metrics[d.spec.drone_id].total_charge_time_s += charge_time
                drone_metrics[d.spec.drone_id].final_battery_wh = d.battery_wh
                any_recharged = True
        return max_charge_time if any_recharged else 0.0

    def run_comparison(
        self,
        scenario: Scenario,
    ) -> tuple[SimulationResult, SimulationResult]:
        """
        Ejecuta el mismo escenario con ambos algoritmos.

        Returns
        -------
        tuple[SimulationResult, SimulationResult]
            (resultado_greedy, resultado_cost_matrix)
        """
        greedy_result = self.run(scenario, "greedy")
        jv_result = self.run(scenario, "cost_matrix")
        return greedy_result, jv_result

    def run_batch(
        self,
        scenarios: list[Scenario],
        algorithm: str,
    ) -> list[SimulationResult]:
        """Ejecuta múltiples escenarios con el mismo algoritmo."""
        return [self.run(s, algorithm) for s in scenarios]


def dispatch_single_cycle(
    scenario: Scenario,
    algorithm: str,
) -> AssignmentResult:
    """
    Ejecuta un único ciclo de despacho, sin recarga entre rondas.

    Modela una oleada de reparto: dada la batería actual de la flota, se sirven
    los pedidos pendientes hasta agotar la autonomía disponible. Es el régimen
    donde la capacidad escasea y la asignación importa: el greedy (FIFO) puede
    malgastar los drones capaces en los primeros pedidos y dejar el resto sin
    servir, mientras que la asignación global por matriz de costes reparte mejor.

    A diferencia de ``Simulator.run``, aquí NO se recargan baterías: el resultado
    refleja cuántos pedidos cabe servir en una sola tanda.

    Parameters
    ----------
    scenario : Scenario
        Escenario con flota y pedidos.
    algorithm : str
        "greedy" o "cost_matrix".

    Returns
    -------
    AssignmentResult
        Asignaciones, pedidos sin servir y totales (energía y makespan).
    """
    drones = [DroneState(spec=d.spec, battery_wh=d.battery_wh) for d in scenario.drones]
    orders = [
        Order(order_id=o.order_id, weight_kg=o.weight_kg, distance_km=o.distance_km,
              client_lat=getattr(o, "client_lat", 0.0),
              client_lon=getattr(o, "client_lon", 0.0),
              destination_name=getattr(o, "destination_name", ""))
        for o in scenario.orders
    ]
    if algorithm == "greedy":
        return greedy_assign(drones, orders)
    elif algorithm == "cost_matrix":
        return cost_matrix_assign(drones, orders)
    raise ValueError(f"Algoritmo desconocido: {algorithm}")
