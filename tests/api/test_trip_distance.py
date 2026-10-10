"""La distancia que guarda un pedido es el viaje de ida completo, no el último tramo."""
from airdrop.domain.matching import find_best_route, trip_length_km
from core.geo import haversine_km

PERFIL = {
    "name": "P",
    "hub": {"lat": 41.0010, "lon": 2.0},
    "parkings": [{"name": "Base", "lat": 41.0, "lon": 2.0}],
    "destinations": [{"name": "Lejos", "lat": 41.0200, "lon": 2.0}],
    "routes": [{"name": "R", "parking": "Base", "destination": "Lejos",
                "intermediates": [{"lat": 41.0100, "lon": 2.0010}]}],
}


def test_the_trip_is_parking_hub_corridor_destination_and_client():
    cliente = (41.0205, 2.0)
    esperado = (haversine_km(41.0, 2.0, 41.0010, 2.0)
                + haversine_km(41.0010, 2.0, 41.0100, 2.0010)
                + haversine_km(41.0100, 2.0010, 41.0200, 2.0)
                + haversine_km(41.0200, 2.0, *cliente))
    assert abs(trip_length_km(PERFIL, PERFIL["routes"][0], *cliente) - esperado) < 1e-9


def test_the_order_stores_the_whole_trip_and_not_the_last_leg():
    a = find_best_route([PERFIL], 41.0205, 2.0)

    assert a["offset_km"] < 0.1, "el cliente está junto al destino"
    assert a["distance_km"] > 2.2, "pero el viaje desde la base pasa de 2 km"


def test_orders_are_matched_only_against_the_active_scenario(client, admin_token):
    # Un cliente junto a la escuela está más cerca de un punto de la jaula del
    # DroneLab que del destino UPC de Castelldefels, pero el escenario activo
    # es Castelldefels y su pedido debe ir por un corredor de Castelldefels.
    from airdrop.api import main as portal

    perfil = portal.store.active_profile()
    a = portal.store._assign(41.27640, 1.98870)

    assert perfil == "Ruta1-Castelldefels"
    assert a["profile_name"] == "Ruta1-Castelldefels"
