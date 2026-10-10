"""
Selección del corredor pre-aprobado más cercano a un cliente.

Recorre los perfiles de route_profiles.json y devuelve la ruta cuyo destino
queda más cerca (haversine) de las coordenadas del cliente. Lo usan tanto la
capa de datos del escritorio (negocio/db_manager) como la del portal cloud
(webapp/data), para no duplicar el criterio de asignación.
"""

from core.geo import haversine_km


def _punto(p):
    try:
        return float(p["lat"]), float(p["lon"])
    except (TypeError, ValueError, KeyError):
        return None


def trip_length_km(profile, route, client_lat, client_lon) -> float:
    """Longitud del viaje de ida tal como se vuela: parking, HUB, puntos
    intermedios, destino y cliente.

    Es la distancia que necesita el modelo de energía. La que decide qué
    corredor toca (cliente a destino) es solo el último tramo y no sirve para
    estimar el consumo: con ella un pedido a la playa, a 2 km, costaba lo
    mismo que uno junto al aparcamiento.
    """
    parkings = {p.get("name"): p for p in profile.get("parkings", []) if isinstance(p, dict)}
    dests = {d.get("name"): d for d in profile.get("destinations", []) if isinstance(d, dict)}
    puntos = [_punto(parkings.get(route.get("parking"), {})), _punto(profile.get("hub") or {})]
    puntos += [_punto(p) for p in route.get("intermediates", []) if isinstance(p, dict)]
    puntos += [_punto(dests.get(route.get("destination"), {})), (float(client_lat), float(client_lon))]
    puntos = [p for p in puntos if p is not None]
    return sum(haversine_km(a[0], a[1], b[0], b[1]) for a, b in zip(puntos, puntos[1:]))


def find_best_route(profiles, client_lat, client_lon):
    """Devuelve el mejor candidato {profile_name, route_name, destination_name,
    destination_lat, destination_lon, distance_km, offset_km} o lanza ValueError.

    Gana el corredor cuyo destino queda más cerca del cliente (``offset_km``).
    ``distance_km`` es el viaje de ida completo (``trip_length_km``)."""
    best = None
    best_route = best_profile = None
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
            if best is None or dist < best["offset_km"]:
                best = {
                    "profile_name": str(pname),
                    "route_name": str(route.get("name")),
                    "destination_name": str(route.get("destination")),
                    "destination_lat": dlat,
                    "destination_lon": dlon,
                    "offset_km": dist,
                }
                best_route, best_profile = route, profile
    if best is None:
        raise ValueError("No se encontró ruta válida")
    best["distance_km"] = trip_length_km(best_profile, best_route, client_lat, client_lon)
    return best
