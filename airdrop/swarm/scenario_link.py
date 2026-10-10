"""Enlace entre el escenario operacional y el escenario de rutas.

Un escenario operacional dice **dónde y con qué límites** se vuela; un escenario
de rutas dice **por dónde**. El punto que comparten es el parking: es a la vez
el origen de los corredores y el centro del volumen operacional.

Ese punto estaba duplicado. El escenario operacional guardaba sus propias
coordenadas —de ahí salían los pads de los drones y el centro de la geovalla—
mientras el escenario de rutas guardaba las suyas, que eran el primer waypoint
de la misión. Coincidían porque se sembraron a la vez, no porque nada lo
garantizase: mover el parking en el mapa no movía los pads ni la geovalla.

Aquí se resuelve la duplicación en una sola dirección: **manda el parking
dibujado en el mapa**. El escenario operacional solo dice cuál de ellos usa,
por nombre, igual que ya hacen las rutas con ``route.parking``.
"""

from __future__ import annotations

from dataclasses import replace


def _parkings_de(profiles, profile_name):
    perfil = next((p for p in (profiles or {}).get("profiles", [])
                   if p.get("name") == profile_name), None)
    return (perfil or {}).get("parkings", []) or []


def parking_options(profiles, profile_name) -> list[str]:
    """Nombres de parking disponibles para ese escenario de rutas."""
    return [str(p.get("name")) for p in _parkings_de(profiles, profile_name)
            if p.get("name")]


def resolve_parking(scenario, profiles):
    """Escenario con las coordenadas del parking que referencia.

    Si no tiene ``parking_name``, o el nombre ya no existe en el escenario de
    rutas, se devuelve tal cual: es preferible operar con las coordenadas
    guardadas que quedarse sin punto de referencia. Un parking que desaparece
    del mapa no puede dejar al enjambre sin geovalla.
    """
    if scenario is None or not getattr(scenario, "parking_name", ""):
        return scenario

    punto = next((p for p in _parkings_de(profiles, scenario.route_profile_name)
                  if str(p.get("name")) == scenario.parking_name), None)
    if punto is None or punto.get("lat") is None or punto.get("lon") is None:
        return scenario

    return replace(scenario,
                   parking_lat=float(punto["lat"]),
                   parking_lon=float(punto["lon"]))


def parking_mismatch(scenario, profiles) -> dict | None:
    """Discrepancia entre las coordenadas guardadas y las del mapa.

    Sirve para avisar en el panel de escenarios sembrados antes de que
    existiera el enlace, que siguen con coordenadas propias y ningún parking
    referenciado.
    """
    resuelto = resolve_parking(scenario, profiles)
    if resuelto is scenario:
        return None
    misma_lat = abs(resuelto.parking_lat - scenario.parking_lat) < 1e-7
    misma_lon = abs(resuelto.parking_lon - scenario.parking_lon) < 1e-7
    if misma_lat and misma_lon:
        return None
    return {
        "stored": [scenario.parking_lat, scenario.parking_lon],
        "resolved": [resuelto.parking_lat, resuelto.parking_lon],
        "parking_name": scenario.parking_name,
    }
