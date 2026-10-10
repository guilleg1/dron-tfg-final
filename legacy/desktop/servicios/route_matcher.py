"""
Selección del corredor pre-aprobado más cercano a un cliente.

Recorre los perfiles de route_profiles.json y devuelve la ruta cuyo destino
queda más cerca (haversine) de las coordenadas del cliente. Lo usan tanto la
capa de datos del escritorio (negocio/db_manager) como la del portal cloud
(webapp/data), para no duplicar el criterio de asignación.
"""

from utils.geo_utils import haversine_km


def find_best_route(profiles, client_lat, client_lon):
    """Devuelve el mejor candidato {profile_name, route_name, destination_name,
    destination_lat, destination_lon, distance_km} o lanza ValueError."""
    best = None
    for profile in profiles:
        pname = profile.get("name")
        dests = {d.get("name"): d for d in profile.get("destinations", []) if isinstance(d, dict)}
        for route in profile.get("routes", []):
            if not isinstance(route, dict):
                continue
            dest = dests.get(route.get("destination"))
            if dest is None:
                continue
            try:
                dlat, dlon = float(dest["lat"]), float(dest["lon"])
            except (TypeError, ValueError, KeyError):
                continue
            dist = haversine_km(client_lat, client_lon, dlat, dlon)
            if best is None or dist < best["distance_km"]:
                best = {
                    "profile_name": str(pname),
                    "route_name": str(route.get("name")),
                    "destination_name": str(route.get("destination")),
                    "destination_lat": dlat,
                    "destination_lon": dlon,
                    "distance_km": dist,
                }
    if best is None:
        raise ValueError("No se encontró ruta válida")
    return best
