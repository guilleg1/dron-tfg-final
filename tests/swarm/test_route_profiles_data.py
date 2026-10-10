"""Los escenarios de rutas: cada destino tiene su ruta y cae dentro de la geovalla de su escenario."""
import json

from airdrop.config import DATA_DIR
from core.geo import haversine_km


def _cargar(nombre):
    return json.loads((DATA_DIR / nombre).read_text(encoding="utf-8"))


def _perfiles():
    return _cargar("route_profiles.json")["profiles"]


def _perfil(nombre):
    return next(p for p in _perfiles() if p["name"] == nombre)


def test_every_scenario_points_to_an_existing_profile():
    nombres = {p["name"] for p in _perfiles()}
    for s in _cargar("scenarios.json")["scenarios"]:
        assert s["route_profile_name"] in nombres, s["name"]


def test_every_destination_has_a_route():
    for perfil in _perfiles():
        con_ruta = {r["destination"] for r in perfil["routes"]}
        assert con_ruta == {d["name"] for d in perfil["destinations"]}, perfil["name"]


def test_destinations_and_corridors_fall_inside_the_geofence_of_their_scenario():
    for s in _cargar("scenarios.json")["scenarios"]:
        radio_km = s.get("geofence_radius_m", 1500.0) / 1000.0
        perfil = _perfil(s["route_profile_name"])
        puntos = [(d["name"], d) for d in perfil["destinations"]]
        puntos += [(r["name"], p) for r in perfil["routes"] for p in r["intermediates"]]
        for nombre, punto in puntos:
            dist = haversine_km(s["parking_lat"], s["parking_lon"], punto["lat"], punto["lon"])
            assert dist < radio_km, (s["name"], nombre, dist)


def test_the_hub_sits_close_to_the_parking():
    for perfil in _perfiles():
        parking = perfil["parkings"][0]
        dist = haversine_km(parking["lat"], parking["lon"], perfil["hub"]["lat"], perfil["hub"]["lon"])
        assert dist < 0.2, perfil["name"]


def test_the_lab_fits_inside_the_cage():
    # La jaula del DroneLab mide unos 80 x 39 m: todo cabe en 15 m alrededor de la plataforma.
    perfil = _perfil("DroneLab-EETAC")
    parking = perfil["parkings"][0]
    for d in perfil["destinations"]:
        assert haversine_km(parking["lat"], parking["lon"], d["lat"], d["lon"]) < 0.015
