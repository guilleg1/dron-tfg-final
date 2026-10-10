"""Seguridad en el punto de entrega.

Bajar sobre el cliente atraviesa todos los niveles inferiores, igual que
despegar del pad: la separacion por capas no protege ahi. Dos medidas, en este
orden: escalonar a la salida los pedidos de la misma oleada que van al mismo
punto, y reservar la vertical del cliente por si aun asi coinciden.
"""

from airdrop.swarm.airspace import ATERRIZAJE, AirspaceManager
from airdrop.swarm.executor import HOLD_BACK_M, DeliveryExecutor
from airdrop.swarm.scenario import OperationalScenario
from airdrop.swarm.service import DELIVERY_STAGGER_S, _destino_key
from core.geo import haversine_km

ESCENARIO = OperationalScenario(
    name="Castelldefels", route_profile_name="r",
    parking_lat=41.283720, parking_lon=1.985050,
)

CLIENTE = (41.284500, 1.978000)
RUTA = [
    {"lat": 41.282946, "lon": 1.986080},   # hub
    {"lat": 41.285722, "lon": 1.980634},   # intermedio
    {"lat": 41.284412, "lon": 1.978221},   # destino de ruta
]


def _metros(a, b):
    return haversine_km(a[0], a[1], b[0], b[1]) * 1000.0


# ── Escalonado a la salida ───────────────────────────────────────────────

def test_orders_to_the_same_point_share_a_key():
    # Se agrupa por coordenadas, no por cliente: dos vecinos del mismo portal
    # comparten punto de aterrizaje y se estorban igual.
    a = {"id": 1, "client_latitude": 41.2845, "client_longitude": 1.9780}
    b = {"id": 2, "client_latitude": 41.28450004, "client_longitude": 1.9780}
    c = {"id": 3, "client_latitude": 41.2900, "client_longitude": 1.9900}

    assert _destino_key(a) == _destino_key(b)
    assert _destino_key(a) != _destino_key(c)


def test_an_order_without_coordinates_never_groups():
    # Sin coordenadas no se puede afirmar que compartan destino; cada uno va
    # por su cuenta en vez de escalonarse sin motivo.
    a = {"id": 1, "client_latitude": None, "client_longitude": None}
    b = {"id": 2, "client_latitude": None, "client_longitude": None}

    assert _destino_key(a) != _destino_key(b)


def test_the_stagger_grows_with_each_drone_to_the_same_point():
    pedidos = [
        {"id": 1, "client_latitude": 41.2845, "client_longitude": 1.9780},
        {"id": 2, "client_latitude": 41.2845, "client_longitude": 1.9780},
        {"id": 3, "client_latitude": 41.2900, "client_longitude": 1.9900},
        {"id": 4, "client_latitude": 41.2845, "client_longitude": 1.9780},
    ]
    vistos, retardos = {}, []
    for o in pedidos:
        clave = _destino_key(o)
        n = vistos.get(clave, 0)
        vistos[clave] = n + 1
        retardos.append(n * DELIVERY_STAGGER_S)

    assert retardos == [0.0, DELIVERY_STAGGER_S, 0.0, 2 * DELIVERY_STAGGER_S]


# ── Vertical del punto de entrega ────────────────────────────────────────

def test_only_one_drone_may_descend_on_a_client():
    a = AirspaceManager(ESCENARIO, slot_count=4)

    assert a.acquire_pad("Dron-1", CLIENTE[0], CLIENTE[1], ATERRIZAJE)
    assert not a.acquire_pad("Dron-2", CLIENTE[0], CLIENTE[1], ATERRIZAJE)

    a.release_pad("Dron-1")

    assert a.acquire_pad("Dron-2", CLIENTE[0], CLIENTE[1], ATERRIZAJE)


# ── Punto de espera ──────────────────────────────────────────────────────

def test_the_holding_point_sits_on_the_approach_not_beside_it():
    espera = DeliveryExecutor._punto_de_espera(RUTA, *CLIENTE)

    al_cliente = _metros(espera, CLIENTE)
    al_destino = _metros(espera, (RUTA[-1]["lat"], RUTA[-1]["lon"]))
    tramo = _metros((RUTA[-1]["lat"], RUTA[-1]["lon"]), CLIENTE)

    assert abs(al_cliente - HOLD_BACK_M) < 1.0, "20 m antes de llegar"
    # Si estuviera a un lado, la suma seria mayor que el tramo.
    assert abs((al_cliente + al_destino) - tramo) < 1.0, "sobre la recta"


def test_a_short_final_leg_falls_back_to_the_waypoint():
    # Retroceder 20 m en un tramo de 13 dejaria al dron detras del waypoint,
    # fuera del corredor.
    corta = [{"lat": 41.284500, "lon": 1.978150}]

    espera = DeliveryExecutor._punto_de_espera(corta, *CLIENTE)

    assert espera == (corta[0]["lat"], corta[0]["lon"])


def test_a_waypoint_on_top_of_the_client_is_ignored():
    ruta = RUTA + [{"lat": CLIENTE[0], "lon": CLIENTE[1]}]

    espera = DeliveryExecutor._punto_de_espera(ruta, *CLIENTE)

    assert _metros(espera, CLIENTE) > 1.0, "no se espera encima del cliente"
