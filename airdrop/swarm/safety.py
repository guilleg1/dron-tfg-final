"""Capa de seguridad del enjambre.

Comprobaciones previas al despegue y vigilancia en vuelo, todas contra los
límites del escenario activo. Encaja con las mitigaciones que SORA exige para
la categoría específica: contención en un volumen operacional, reserva de
energía para el retorno y techo de altura sobre el terreno (Reglamento UE
2019/947).

La reserva de batería no es un porcentaje suelto: se compara la energía
estimada del viaje, calculada con ``core.energy``, contra la batería
utilizable. Es la misma función que usa el greedy para decidir, así que
planificación y seguridad no pueden discrepar.
"""

from __future__ import annotations

import threading
from collections import deque
from datetime import datetime, timezone

from airdrop.swarm.models import IDLE
from core.energy import estimate_trip_energy_wh

RTL = "rtl"
LINK_LOST = "link_lost"
DEFAULT_MAX_EVENTS = 200

# Sin telemetría durante este tiempo, se da el enlace por perdido.
#
# No es un parámetro del escenario a propósito: es una propiedad del enlace,
# no del emplazamiento, y añadir la columna no aportaba nada frente a poder
# ajustarla al construir la política.
TELEMETRY_TIMEOUT_S = 10.0


class SafetyPolicy:
    """Comprobaciones de seguridad y bitácora de eventos."""

    def __init__(self, scenario, max_events: int = DEFAULT_MAX_EVENTS,
                 telemetry_timeout_s: float = TELEMETRY_TIMEOUT_S):
        self.scenario = scenario
        self.telemetry_timeout_s = telemetry_timeout_s
        self._events = deque(maxlen=max_events)
        self._lock = threading.Lock()

    # ── Antes de despegar ────────────────────────────────────────────────
    def can_dispatch(self, record, runtime, order) -> tuple[bool, str]:
        """¿Puede este dron aceptar este pedido?"""
        if runtime.state != IDLE:
            return False, f"el dron no está disponible ({runtime.state})"

        spec = record.spec
        peso = float(order.get("weight_kg") or 0.0)
        if peso > spec.max_payload_kg:
            return False, (f"carga de {peso} kg por encima de los "
                           f"{spec.max_payload_kg} kg del dron")

        reserva_wh = spec.battery_capacity_wh * self.scenario.battery_reserve_pct / 100.0
        if runtime.battery_wh <= reserva_wh:
            return False, "batería por debajo de la reserva"

        distancia = float(order.get("assigned_distance_km") or 0.0)
        energia = estimate_trip_energy_wh(spec, distancia, peso)
        utilizable = runtime.battery_wh - reserva_wh
        if energia > utilizable:
            return False, (f"autonomía insuficiente: {energia:.0f} Wh estimados "
                           f"frente a {utilizable:.0f} Wh utilizables")

        if not self.scenario.is_inside_geofence(order.get("client_latitude"),
                                                order.get("client_longitude")):
            return False, "el cliente cae fuera de la geovalla del escenario"

        return True, "listo"

    # ── Durante el vuelo ─────────────────────────────────────────────────
    def check_in_flight(self, record, runtime, telemetry_age_s=None):
        """Devuelve ``(accion, motivo)`` o ``None`` si todo está bien.

        ``telemetry_age_s`` son los segundos desde el último paquete recibido.
        Se comprueba **primero**: sin enlace, el resto de comprobaciones se
        harían sobre datos viejos y darían por bueno un dron inalcanzable, que
        es exactamente el fallo que se observó contra SITL.
        """
        if runtime.state == IDLE or runtime.lat is None:
            return None

        if telemetry_age_s is not None and telemetry_age_s > self.telemetry_timeout_s:
            return LINK_LOST, (f"sin telemetría desde hace "
                               f"{telemetry_age_s:.0f} s: enlace perdido")

        reserva_wh = (record.spec.battery_capacity_wh
                      * self.scenario.battery_reserve_pct / 100.0)
        if runtime.battery_wh <= reserva_wh:
            return RTL, "batería por debajo de la reserva"

        if not self.scenario.is_inside_geofence(runtime.lat, runtime.lon):
            return RTL, "fuera de la geovalla del volumen operacional"

        if (runtime.alt or 0.0) > self.scenario.alt_ceiling_m:
            return RTL, (f"por encima del techo de "
                         f"{self.scenario.alt_ceiling_m} m")

        return None

    # ── Bitácora ─────────────────────────────────────────────────────────
    def record_event(self, drone_id: str, kind: str, reason: str) -> None:
        """Anota un evento.

        Sin esta bitácora, una espera por separación es indistinguible de un
        dron colgado, y en una demostración ante tribunal eso importa.
        """
        with self._lock:
            self._events.appendleft({
                "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "drone_id": drone_id,
                "kind": kind,
                "reason": reason,
            })

    def events(self) -> list[dict]:
        with self._lock:
            return list(self._events)
