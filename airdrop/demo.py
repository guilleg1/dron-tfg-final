"""Escenarios de pedidos para demostraciones.

Siembra clientes simulados y sus pedidos para poder enseñar el enjambre en
marcha sin dar de alta cuentas a mano cada vez. Es la diferencia entre una
demo que arranca en diez segundos y una que se pasa cinco minutos rellenando
formularios delante del tribunal.

Los clientes se colocan **dentro de la geovalla del escenario activo** y sobre
la corona donde el reparto es interesante: pegados al parking no hay vuelo que
ver, y fuera de la geovalla la política de seguridad los rechaza —cosa que ya
pasó y parecía una avería del enjambre.

Los pesos nunca superan la capacidad del dron más capaz de la flota: un pedido
que nadie puede llevar se queda en la cola para siempre y desde fuera parece
que el sistema ha dejado de repartir.

Uso:
    python -m airdrop.demo list
    python -m airdrop.demo seed oleada
    python -m airdrop.demo seed mixto --seed 7
    python -m airdrop.demo clear
"""

from __future__ import annotations

import argparse
import math
import random
import sys
from dataclasses import dataclass

# Marca en el nombre y la dirección de todo lo que siembra este módulo. Es lo
# que permite que `clear` borre solo lo simulado y respete las cuentas reales.
MARCA = "[demo]"


@dataclass(frozen=True)
class Preset:
    """Un escenario de pedidos listo para lanzar."""

    nombre: str
    descripcion: str
    pesos_kg: tuple[float, ...]
    # Distancia del cliente al destino de ruta que le sirve, en metros. Es el
    # último tramo, el que el dron vuela fuera del corredor.
    salto_min_m: float = 60.0
    salto_max_m: float = 220.0
    # Si es mayor que cero, el número de pedidos es este por cada dron de la
    # flota, repitiendo los pesos en ciclo: la misma escasez a cualquier tamaño.
    por_dron: int = 0

    @property
    def n_pedidos(self) -> int:
        return len(self.pesos_kg)

    def pesos_para(self, n_drones: int, cantidad: int | None = None) -> list[float]:
        """Los pesos de la siembra: ``cantidad`` si se pide, o los del preset."""
        n = cantidad or (self.por_dron * n_drones if self.por_dron else self.n_pedidos)
        return [self.pesos_kg[k % len(self.pesos_kg)] for k in range(max(int(n), 0))]


PRESETS: dict[str, Preset] = {
    "oleada": Preset(
        nombre="oleada",
        descripcion=(
            "Oleada de escasez: ocho pedidos para cuatro drones. Es el caso "
            "que luce la diferencia entre el voraz y la asignación global, "
            "el mismo régimen que mide research/."
        ),
        pesos_kg=(0.8, 1.0, 1.2, 1.5, 2.0, 2.5, 3.0, 3.5),
    ),
    "oleada_flota": Preset(
        nombre="oleada_flota",
        descripcion=(
            "La oleada escalada a la flota: dos pedidos por dron con los pesos "
            "de la oleada en ciclo. Con 4 drones son los 8 de siempre; con 20, "
            "40. Mantiene la escasez al crecer la flota."
        ),
        pesos_kg=(0.8, 1.0, 1.2, 1.5, 2.0, 2.5, 3.0, 3.5),
        por_dron=2,
    ),
    "ligero": Preset(
        nombre="ligero",
        descripcion=(
            "Cuatro pedidos de 1 kg: cualquier dron puede con todos. Sirve "
            "para ver el escalonado y las capas sin que la capacidad estorbe."
        ),
        pesos_kg=(1.0, 1.0, 1.0, 1.0),
    ),
    "mixto": Preset(
        nombre="mixto",
        descripcion=(
            "Pesos repartidos entre las tres categorías. Enseña que el "
            "asignador respeta la capacidad: los ligeros nunca reciben más "
            "de 1 kg."
        ),
        pesos_kg=(0.5, 1.0, 2.0, 3.5, 1.0, 2.0),
    ),
    "lejano": Preset(
        nombre="lejano",
        descripcion=(
            "Seis pedidos pesados con el cliente alejado de su destino de "
            "ruta: el último tramo fuera del corredor se alarga y sube la "
            "energía por entrega. Es el escenario para ver la reserva de "
            "batería rechazando despachos."
        ),
        pesos_kg=(3.5, 3.0, 3.5, 2.5, 3.0, 3.5),
        salto_min_m=350.0,
        salto_max_m=600.0,
    ),
}


def _destinos_del_perfil(store, escenario) -> list[dict]:
    """Destinos que sirven las rutas del perfil del escenario activo.

    Los clientes se colocan junto a **estos** puntos y no en cualquier sitio.
    El matcher asigna a cada cliente la ruta cuyo destino tenga más cerca, así
    que sembrar al azar producía pedidos servidos por rutas de otro perfil
    —incluso de Gavà— que no era lo que se quería enseñar. Colocándolos junto
    a un destino real, cada pedido recorre una ruta definida del perfil, con
    su HUB y sus intermedios.

    Solo se toman los destinos que **alguna ruta** usa: un destino suelto sin
    ruta no es despachable.
    """
    perfil = next((p for p in store.get_profiles().get("profiles", [])
                   if p.get("name") == escenario.route_profile_name), None)
    if perfil is None:
        return []
    usados = {r.get("destination") for r in perfil.get("routes", [])}
    return [d for d in perfil.get("destinations", [])
            if d.get("name") in usados
            and d.get("lat") is not None and d.get("lon") is not None]


def _punto_cerca_de(rng, lat0, lon0, radio_min_m, radio_max_m):
    """Un punto aleatorio en la corona [radio_min, radio_max] alrededor de un punto.

    El radio se sortea sobre su cuadrado para repartir uniformemente por
    superficie; sortearlo lineal amontona los puntos cerca del centro.
    """
    rumbo = rng.uniform(0.0, 2.0 * math.pi)
    radio = math.sqrt(rng.uniform(radio_min_m ** 2, radio_max_m ** 2))
    norte_m = radio * math.cos(rumbo)
    este_m = radio * math.sin(rumbo)
    dlat = norte_m / 111_320.0
    dlon = este_m / (111_320.0 * math.cos(math.radians(lat0)) or 1.0)
    return lat0 + dlat, lon0 + dlon


def _tope_de_carga(store) -> float:
    from core.energy import DRONE_CATEGORIES
    from airdrop.swarm.repository import FleetRepository

    capacidades = [
        DRONE_CATEGORIES[d.category].max_payload_kg
        for d in FleetRepository(store.engine).list_drones(only_enabled=True)
        if d.category in DRONE_CATEGORIES
    ]
    return max(capacidades) if capacidades else 0.0


def _n_drones(store) -> int:
    from airdrop.swarm.repository import FleetRepository
    return len(FleetRepository(store.engine).list_drones(only_enabled=True))


def _contexto():
    """Almacén y escenario activo, sembrando lo que falte."""
    from airdrop.api.data import DataStore
    from airdrop.swarm.scenario_repository import ScenarioRepository

    store = DataStore()
    escenarios = ScenarioRepository(store.engine)
    escenarios.seed_if_empty()
    escenario = escenarios.active()
    if escenario is None:
        raise SystemExit("No hay escenario activo. Actívalo en /admin.html.")
    return store, escenario


def seed(preset_name: str, semilla: int | None = None,
         cantidad: int | None = None) -> int:
    preset = PRESETS.get(preset_name)
    if preset is None:
        raise SystemExit(
            f"Preset desconocido: {preset_name}. "
            f"Disponibles: {', '.join(PRESETS)}")

    store, escenario = _contexto()
    tope = _tope_de_carga(store)
    if tope <= 0:
        raise SystemExit("No hay drones habilitados en la flota.")

    destinos = _destinos_del_perfil(store, escenario)
    if not destinos:
        raise SystemExit(
            f"El perfil '{escenario.route_profile_name}' no tiene destinos con "
            f"ruta. Defínelos en /admin.html → Perfiles.")

    rng = random.Random(semilla)
    radio = float(escenario.geofence_radius_m)
    creados = 0
    rechazados = []
    fuera = 0

    print(f"Escenario: {escenario.name}  ·  perfil {escenario.route_profile_name}  "
          f"·  geovalla {radio:.0f} m  ·  carga máxima {tope:g} kg")
    print(f"Destinos con ruta: {', '.join(d['name'] for d in destinos)}")
    pesos = preset.pesos_para(_n_drones(store), cantidad)
    print(f"Preset '{preset.nombre}': {len(pesos)} pedidos\n")

    for indice, peso in enumerate(pesos, start=1):
        # Nunca por encima del tope: un pedido que nadie puede llevar se queda
        # en la cola para siempre y parece una avería.
        peso_real = min(float(peso), tope)

        # Se rota por los destinos en vez de sortearlos: con pocos pedidos, el
        # azar deja rutas sin usar y la demo enseña menos de lo que tiene.
        destino = destinos[(indice - 1) % len(destinos)]
        lat, lon = _punto_cerca_de(
            rng, float(destino["lat"]), float(destino["lon"]),
            preset.salto_min_m, preset.salto_max_m)

        if not escenario.is_inside_geofence(lat, lon):
            # Puede pasar con saltos grandes junto a un destino periférico.
            fuera += 1
            print(f"  (omitido) cerca de {destino['name']}: caería fuera "
                  f"de la geovalla")
            continue

        nombre = f"{MARCA} {preset.nombre}-{indice:02d}"
        cliente = store.create_client(
            name=nombre,
            address=f"{MARCA} junto a {destino['name']} ({escenario.name})",
            lat=lat, lon=lon)
        try:
            store.create_order(cliente["id"], peso_real)
        except Exception as exc:  # noqa: BLE001
            # El fallo típico es que no haya ninguna ruta cuyo destino sirva a
            # ese punto. Se informa y se sigue: media siembra es más útil que
            # ninguna, y el motivo queda a la vista.
            rechazados.append((nombre, str(exc)))
            continue
        creados += 1
        print(f"  {nombre}  {peso_real:g} kg  →  {destino['name']}  "
              f"({lat:.5f}, {lon:.5f})")

    print(f"\n{creados} pedido(s) listos.")
    if fuera:
        print(f"{fuera} omitido(s) por caer fuera de la geovalla.")
    if rechazados:
        print(f"{len(rechazados)} sin ruta asignable:")
        for nombre, motivo in rechazados:
            print(f"  {nombre}: {motivo}")
    print("Arranca el portal y pulsa «Iniciar repartos» en /admin.html.")
    return 0


def clear() -> int:
    """Borra clientes simulados y sus pedidos. No toca las cuentas reales."""
    from sqlalchemy import delete, select

    from airdrop.api.data import clients, orders
    store, _ = _contexto()

    with store.engine.begin() as conn:
        ids = [fila[0] for fila in conn.execute(
            select(clients.c.id).where(clients.c.name.like(f"%{MARCA}%")))]
        if ids:
            conn.execute(delete(orders).where(orders.c.client_id.in_(ids)))
            conn.execute(delete(clients).where(clients.c.id.in_(ids)))

    print(f"{len(ids)} cliente(s) simulados borrados con sus pedidos.")
    return 0


def listar() -> int:
    print("Presets disponibles:\n")
    for preset in PRESETS.values():
        cuantos = (f"{preset.por_dron} por dron" if preset.por_dron
                   else f"{preset.n_pedidos} pedidos")
        print(f"  {preset.nombre:12s} {cuantos}  "
              f"({min(preset.pesos_kg):g}–{max(preset.pesos_kg):g} kg)")
        print(f"           {preset.descripcion}\n")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m airdrop.demo",
        description="Escenarios de pedidos para demostraciones.")
    sub = parser.add_subparsers(dest="accion", required=True)

    sub.add_parser("list", help="lista los presets disponibles")

    p_seed = sub.add_parser("seed", help="siembra un escenario de pedidos")
    p_seed.add_argument("preset", choices=sorted(PRESETS))
    p_seed.add_argument("--seed", type=int, default=None,
                        help="semilla del generador, para repetir la misma demo")
    p_seed.add_argument("--pedidos", type=int, default=None,
                        help="número de pedidos; los pesos del preset se repiten en ciclo")

    sub.add_parser("clear", help="borra los clientes simulados y sus pedidos")

    args = parser.parse_args(argv)
    if args.accion == "list":
        return listar()
    if args.accion == "clear":
        return clear()
    return seed(args.preset, args.seed, args.pedidos)


if __name__ == "__main__":
    sys.exit(main())
