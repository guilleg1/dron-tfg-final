"""Utilidades geográficas: distancia haversine y desplazamiento de coordenadas."""

import math


def haversine_km(lat1, lon1, lat2, lon2):
    """Distancia entre dos puntos en km (fórmula de Haversine)."""
    R = 6371.0
    lat1_r, lon1_r = math.radians(float(lat1)), math.radians(float(lon1))
    lat2_r, lon2_r = math.radians(float(lat2)), math.radians(float(lon2))

    dlat = lat2_r - lat1_r
    dlon = lon2_r - lon1_r

    a = math.sin(dlat / 2) ** 2 + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def offset_position(lat, lon, direction, distance_m):
    """
    Desplaza una coordenada lat/lon en una dirección cardinal una distancia
    en metros.  Devuelve (new_lat, new_lon).

    direction: "North", "South", "East", "West"
    """
    R = 6_378_137.0  # Radio terrestre en metros (WGS‑84)
    lat_r = math.radians(float(lat))

    d_lat = distance_m / R
    d_lon = distance_m / (R * math.cos(lat_r))

    offsets = {
        "North": (math.degrees(d_lat), 0),
        "South": (-math.degrees(d_lat), 0),
        "East":  (0, math.degrees(d_lon)),
        "West":  (0, -math.degrees(d_lon)),
    }

    delta = offsets.get(direction, (0, 0))
    return float(lat) + delta[0], float(lon) + delta[1]


def offset_xy(lat, lon, east_m, north_m):
    """Desplaza una coordenada un vector en metros (este, norte).

    ``offset_position`` solo admite las cuatro cardinales, y una formación de
    parking necesita colocar pads en dos ejes a la vez. Devuelve (lat, lon).
    """
    R = 6_378_137.0  # WGS-84
    lat_r = math.radians(float(lat))
    d_lat = math.degrees(float(north_m) / R)
    d_lon = math.degrees(float(east_m) / (R * math.cos(lat_r)))
    return float(lat) + d_lat, float(lon) + d_lon


def offset_bearing(lat, lon, bearing_deg, distance_m):
    """Desplaza una coordenada ``distance_m`` en el rumbo dado.

    Rumbo en grados desde el norte y hacia el este: 0 = norte, 90 = este.
    """
    rumbo = math.radians(float(bearing_deg))
    return offset_xy(lat, lon,
                     float(distance_m) * math.sin(rumbo),
                     float(distance_m) * math.cos(rumbo))
