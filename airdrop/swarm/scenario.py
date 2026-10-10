"""Escenario operacional: dónde vuela el enjambre y con qué límites.

Ningún parámetro de seguridad es una constante del código. Todos viven aquí,
porque el mismo enjambre tiene que funcionar a 40 m sobre Castelldefels y a
4 m dentro del DroneLab de la EETAC. Esa diferencia de dos órdenes de magnitud
es lo que demuestra que la parametrización es real.

Los límites siguen el Reglamento UE 2019/947 (categoría específica): el techo
por defecto de 120 m es la altura máxima sobre el terreno. Que sea parámetro y
no constante permite justificar por qué en interior se opera a 4 m.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from core.geo import haversine_km, offset_bearing

@dataclass(frozen=True)
class OperationalScenario:
    """Parámetros operativos y de seguridad de un emplazamiento."""

    name: str
    route_profile_name: str

    # Coordenadas **derivadas**, no fuente de verdad. La fuente es el parking
    # llamado ``parking_name`` dentro del escenario de rutas
    # ``route_profile_name``, que es el que se dibuja en el mapa.
    #
    # Estaban duplicadas: el parking del escenario decidía dónde nacen los
    # drones y dónde se centra la geovalla, mientras el parking del escenario
    # de rutas decidía el primer waypoint de la misión. Nada garantizaba que
    # coincidieran, y mover uno en el mapa no movía el otro.
    #
    # Se conservan como campo porque son lo que consultan el gestor de espacio
    # aéreo, la geovalla y el sembrado de pads; ``resolve_parking`` las
    # refresca desde el perfil antes de usar el escenario.
    parking_lat: float
    parking_lon: float

    # Qué parking del escenario de rutas se usa. Vacío = quedarse con las
    # coordenadas guardadas, que es como se comportaba antes.
    parking_name: str = ""

    # Geometría
    pad_spacing_m: float = 8.0
    # Formación de los pads en el parking. "fila" reproduce el reparto
    # original (todos hacia el este); "rejilla" los coloca en pad_cols
    # columnas; "circulo" los reparte en una corona alrededor del centro.
    pad_layout: str = "fila"
    pad_cols: int = 0            # 0 = una sola fila
    pad_heading_deg: float = 90.0  # eje de la formación; 90 = este
    alt_base_m: float = 25.0
    alt_step_m: float = 5.0
    alt_ceiling_m: float = 120.0
    geofence_radius_m: float = 1500.0

    # Separación
    separation_min_m: float = 30.0
    takeoff_gap_s: float = 10.0
    waypoint_tolerance_m: float = 5.0
    hub_exclusive: bool = True

    # Distancia mínima entre dos pads para que sus drones puedan maniobrar a
    # la vez. Es lo que convierte el parking en un vertipuerto con varias
    # plataformas en vez de en un cerrojo único: dos drones que suben por
    # columnas separadas más que esto no se estorban, aunque ambos atraviesen
    # todas las capas de altitud.
    #
    # 0 desactiva la concurrencia y vuelve al comportamiento de exclusión
    # total, que es lo verificado en B2.
    pad_separation_m: float = 0.0

    # Tope duro de drones maniobrando a la vez, por encima de lo que permita
    # la geometría. 0 = sin tope. Sirve para acotar el experimento sin tocar
    # las distancias.
    vertiport_capacity: int = 0

    # Cuántos drones caben a la vez en el HUB. La exclusión binaria original
    # (uno y solo uno) modelaba mal el punto de confluencia: las puertas de
    # corredor de U-space tienen capacidad, no exclusión. Con el regreso por
    # la ruta de ida el HUB se cruza dos veces por entrega, y serializar toda
    # la flota en ese punto es lo que atascaba los retornos con cuatro drones
    # (fallo abierto de B2-VERIFICACION.md).
    #
    # 1 reproduce exactamente el comportamiento anterior, así que el valor por
    # defecto no cambia lo ya verificado; subirlo es lo que descongestiona.
    hub_capacity: int = 1

    # Seguridad
    battery_reserve_pct: float = 20.0
    delivery_pause_s: float = 10.0
    # Separación a la salida entre dos drones de la misma oleada que van al
    # mismo punto de entrega. 0 la desactiva y deja solo la reserva de la
    # vertical del cliente.
    delivery_stagger_s: float = 30.0

    active: bool = False
    coords_approximate: bool = False

    # ── Derivados ────────────────────────────────────────────────────────
    def slot_altitudes(self, count: int) -> list[float]:
        """Capas de crucero disponibles, sin pasar del techo."""
        alturas = []
        for k in range(max(count, 0)):
            alt = self.alt_base_m + k * self.alt_step_m
            if alt > self.alt_ceiling_m:
                break
            alturas.append(alt)
        return alturas

    def parking_slots(self, count: int) -> list[tuple[float, float]]:
        """Coordenadas de los ``count`` pads del parking, en orden de índice.

        La fila hacia el este era la única formación posible y estaba escrita
        dentro del sembrado de la flota, así que cambiarla obligaba a tocar el
        repositorio. Aquí es geometría del escenario, que es donde vive el
        resto de la parametrización.

        Las tres formaciones comparten centro: el pad 0 no está en el centro
        del parking sino que la formación se centra en él, para que ampliar la
        flota no desplace a los drones ya colocados hacia un lado.
        """
        total = max(int(count or 0), 0)
        if total == 0:
            return []

        espaciado = max(float(self.pad_spacing_m), 0.0)
        rumbo = float(self.pad_heading_deg)
        layout = (self.pad_layout or "fila").strip().lower()

        if layout == "circulo":
            # Radio tal que la cuerda entre pads contiguos sea el espaciado.
            radio = (espaciado / (2.0 * math.sin(math.pi / total))
                     if total > 1 else 0.0)
            return [offset_bearing(self.parking_lat, self.parking_lon,
                                   rumbo + 360.0 * k / total, radio)
                    for k in range(total)]

        columnas = int(self.pad_cols or 0) if layout == "rejilla" else 0
        if columnas <= 0:
            columnas = total
        filas = math.ceil(total / columnas)

        # Se centra la formación para que el conjunto quede sobre el parking.
        offset_col = (columnas - 1) / 2.0
        offset_fila = (filas - 1) / 2.0

        posiciones = []
        for k in range(total):
            fila, columna = divmod(k, columnas)
            a_lo_largo = (columna - offset_col) * espaciado
            a_lo_ancho = (fila - offset_fila) * espaciado
            # El eje "a lo largo" sigue el rumbo; el "a lo ancho", el rumbo
            # girado 90 grados a la derecha.
            lat, lon = offset_bearing(self.parking_lat, self.parking_lon,
                                      rumbo, a_lo_largo)
            posiciones.append(offset_bearing(lat, lon, rumbo + 90.0, a_lo_ancho))
        return posiciones

    def pads_can_operate_together(self, lat_a, lon_a, lat_b, lon_b) -> bool:
        """¿Pueden dos pads tener drones maniobrando a la vez?

        Con ``pad_separation_m`` a 0 nunca: es la exclusión total original.
        """
        if self.pad_separation_m <= 0:
            return False
        distancia_m = haversine_km(lat_a, lon_a, lat_b, lon_b) * 1000.0
        return distancia_m >= self.pad_separation_m

    @property
    def usable_fraction(self) -> float:
        """Fracción de batería utilizable, descontada la reserva."""
        return max(0.0, 1.0 - self.battery_reserve_pct / 100.0)

    def is_inside_geofence(self, lat, lon) -> bool:
        """¿Está el punto dentro del volumen operacional?

        El volumen es un círculo alrededor del parking. Una geovalla
        poligonal sería más fiel, pero para corredores radiales desde un
        único parking el círculo cubre el caso sin añadir complejidad.
        """
        if lat is None or lon is None:
            return False
        distancia_m = haversine_km(self.parking_lat, self.parking_lon,
                                   float(lat), float(lon)) * 1000.0
        return distancia_m <= self.geofence_radius_m

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "route_profile_name": self.route_profile_name,
            "parking_name": self.parking_name,
            "parking_lat": self.parking_lat,
            "parking_lon": self.parking_lon,
            "pad_spacing_m": self.pad_spacing_m,
            "pad_layout": self.pad_layout,
            "pad_cols": self.pad_cols,
            "pad_heading_deg": self.pad_heading_deg,
            "pad_separation_m": self.pad_separation_m,
            "vertiport_capacity": self.vertiport_capacity,
            "alt_base_m": self.alt_base_m,
            "alt_step_m": self.alt_step_m,
            "alt_ceiling_m": self.alt_ceiling_m,
            "geofence_radius_m": self.geofence_radius_m,
            "separation_min_m": self.separation_min_m,
            "takeoff_gap_s": self.takeoff_gap_s,
            "waypoint_tolerance_m": self.waypoint_tolerance_m,
            "hub_exclusive": self.hub_exclusive,
            "hub_capacity": self.hub_capacity,
            "battery_reserve_pct": self.battery_reserve_pct,
            "delivery_pause_s": self.delivery_pause_s,
            "delivery_stagger_s": self.delivery_stagger_s,
            "active": self.active,
            "coords_approximate": self.coords_approximate,
        }
