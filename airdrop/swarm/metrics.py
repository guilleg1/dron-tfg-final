"""Métricas de operación del enjambre.

Registra qué pasó en cada entrega para poder **comparar los dos asignadores
sobre el enjambre real**, y no solo en las gráficas de ``research/``. El
experimento offline mide el algoritmo aislado; esto mide el sistema completo,
con las esperas del HUB, el escalonado de despegues y las cesiones por
separación incluidas. Son cosas distintas y las dos hacen falta en la memoria:
la primera demuestra que el algoritmo es mejor, la segunda que esa ventaja
sobrevive al vuelo.

Vive en memoria, como el resto del estado del enjambre. Lo que se quiere
conservar se exporta a CSV desde el panel.
"""

from __future__ import annotations

import threading
import time
from dataclasses import asdict, dataclass, field

DEFAULT_MAX_RECORDS = 500


@dataclass
class DeliveryRecord:
    """Lo que se sabe de una entrega terminada."""

    drone_id: str
    order_id: int
    algorithm: str
    category: str
    weight_kg: float
    distance_km: float
    energy_wh: float
    duration_s: float
    wait_s: float          # tiempo perdido esperando HUB o cediendo paso
    outcome: str           # entregado | error | cancelado | enlace_perdido
    finished_at: float = field(default_factory=time.time)

    @property
    def energy_per_km(self) -> float:
        return self.energy_wh / self.distance_km if self.distance_km > 0 else 0.0


class MetricsRegistry:
    """Acumula entregas terminadas. Seguro entre hilos."""

    CSV_HEADER = ("finished_at,algorithm,drone_id,category,order_id,weight_kg,"
                  "distance_km,energy_wh,duration_s,wait_s,outcome")

    def __init__(self, max_records: int = DEFAULT_MAX_RECORDS):
        self._records: list[DeliveryRecord] = []
        self._max = max_records
        self._lock = threading.RLock()

    def record(self, **kwargs) -> None:
        with self._lock:
            self._records.append(DeliveryRecord(**kwargs))
            # Se descartan las más viejas, no las nuevas: una demo larga
            # interesa por su final, no por su principio.
            if len(self._records) > self._max:
                del self._records[:-self._max]

    def all(self) -> list[dict]:
        with self._lock:
            return [asdict(r) for r in self._records]

    def clear(self) -> None:
        with self._lock:
            self._records.clear()

    def summary(self) -> list[dict]:
        """Resumen por algoritmo: es la comparativa que va a la memoria.

        Solo se promedia sobre entregas **completadas**: mezclar los abortos
        abarataría artificialmente la energía media de un algoritmo que falla
        más, que es justo al revés de lo que se quiere medir.
        """
        with self._lock:
            registros = list(self._records)

        resumen = {}
        for r in registros:
            fila = resumen.setdefault(r.algorithm, {
                "algorithm": r.algorithm, "delivered": 0, "failed": 0,
                "energy_wh": 0.0, "duration_s": 0.0, "wait_s": 0.0,
                "distance_km": 0.0,
            })
            if r.outcome != "entregado":
                fila["failed"] += 1
                continue
            fila["delivered"] += 1
            fila["energy_wh"] += r.energy_wh
            fila["duration_s"] += r.duration_s
            fila["wait_s"] += r.wait_s
            fila["distance_km"] += r.distance_km

        salida = []
        for fila in resumen.values():
            n = fila["delivered"]
            salida.append({
                "algorithm": fila["algorithm"],
                "delivered": n,
                "failed": fila["failed"],
                "energy_wh_per_delivery": round(fila["energy_wh"] / n, 2) if n else None,
                "duration_s_per_delivery": round(fila["duration_s"] / n, 1) if n else None,
                "wait_s_per_delivery": round(fila["wait_s"] / n, 1) if n else None,
                "energy_wh_per_km": (round(fila["energy_wh"] / fila["distance_km"], 2)
                                     if fila["distance_km"] > 0 else None),
            })
        return sorted(salida, key=lambda f: f["algorithm"])

    def to_csv(self) -> str:
        lineas = [self.CSV_HEADER]
        for r in self.all():
            lineas.append(
                f"{r['finished_at']:.0f},{r['algorithm']},{r['drone_id']},"
                f"{r['category']},{r['order_id']},{r['weight_kg']:g},"
                f"{r['distance_km']:.4f},{r['energy_wh']:.2f},"
                f"{r['duration_s']:.1f},{r['wait_s']:.1f},{r['outcome']}")
        return "\n".join(lineas) + "\n"
