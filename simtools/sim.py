"""Operaciones del banco de pruebas, sin FastAPI de por medio.

Aquí está la lógica; ``app.py`` solo la expone. Separarlo permite probarla sin
levantar el servidor, que es la mitad del sentido de la herramienta.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

from sqlalchemy import create_engine, delete, func, select

from airdrop.api.data import DEFAULT_SQLITE, _normalize_url, clients, orders, users
from airdrop.swarm import sitl
from airdrop.swarm.repository import FleetRepository, build_records
from airdrop.swarm.scenario_repository import ScenarioRepository
from core.geo import haversine_km

# Categorías por defecto de una flota nueva, en este orden. Que no sean todas
# iguales importa: el greedy reparte por capacidad, y una flota homogénea no
# ejercita el criterio de asignación.
#
# A partir del quinto dron se rellena con «ligero» en vez de seguir rotando:
# ampliar la flota no debería meter pesados sin que nadie lo haya pedido, y el
# ligero es el que menos condiciona el reparto.
CATEGORIAS = ("ligero", "ligero", "medio", "pesado")
CATEGORIA_EXTRA = "ligero"

# Tope de la flota. No sale del rendimiento sino de los puertos: la instancia
# i del SITL ocupa 5760+10i a 5763+10i y la pasarela abre los del puente en
# 6762+10i, así que la instancia 100 caería encima del puente del dron 1. Por
# debajo de eso el límite real es la máquina (unos 100 MB por instancia) y el
# espacio aéreo: con capas de 5 m entre 25 y 120 m vuelan a la vez 20 drones y
# el resto espera capa en el pad. SIM_MAX_DRONES lo baja si la máquina no da.
PUERTOS_POR_INSTANCIA = 10
MAX_DRONES_PUERTOS = (6762 - 5762) // PUERTOS_POR_INSTANCIA   # 100


def max_drones() -> int:
    try:
        pedido = int(os.environ.get("SIM_MAX_DRONES") or MAX_DRONES_PUERTOS)
    except ValueError:
        pedido = MAX_DRONES_PUERTOS
    return max(1, min(pedido, MAX_DRONES_PUERTOS))


MAX_DRONES = MAX_DRONES_PUERTOS
MAX_PEDIDOS = 500


def categorias_disponibles() -> list[str]:
    """Categorías que conoce el catálogo de ``core.energy``.

    Se leen de ahí y no se declaran aquí para que el desplegable no pueda
    ofrecer una categoría que luego reviente al construir el ``DroneRecord``.
    """
    from core.energy import DRONE_CATEGORIES  # noqa: PLC0415
    return list(DRONE_CATEGORIES)


def categoria_por_defecto(indice: int) -> str:
    return CATEGORIAS[indice] if indice < len(CATEGORIAS) else CATEGORIA_EXTRA


@dataclass
class Banco:
    """Acceso a la base de datos del portal y a sus repositorios."""

    url: str

    @classmethod
    def desde_entorno(cls) -> "Banco":
        return cls(_normalize_url(os.environ.get("DATABASE_URL") or DEFAULT_SQLITE))

    @property
    def engine(self):
        return create_engine(self.url, future=True)

    def escenarios(self) -> ScenarioRepository:
        repo = ScenarioRepository(self.engine)
        repo.seed_if_empty()
        return repo

    def flota(self) -> FleetRepository:
        return FleetRepository(self.engine)


# ── Parking ──────────────────────────────────────────────────────────────
def parking_de_flota(escenario, drones) -> dict:
    """El parking tal como está: los pads reales de cada dron, con su número.

    Tras quitar un dron los demás no se mueven, así que la formación teórica
    de N drones ya no coincide con la real: queda un hueco donde estaba. Los
    turnos de despegue se calculan sobre estas posiciones, que son las que usa
    el gestor de espacio aéreo.
    """
    return previsualizar_parking(
        escenario, len(drones),
        pads=[(d.home_lat, d.home_lon) for d in drones],
        etiquetas=[d.drone_id.removeprefix("Dron-") for d in drones])


def previsualizar_parking(escenario, n_drones: int, pads=None, etiquetas=None) -> dict:
    """Pads en metros relativos al parking, y qué pares pueden operar juntos.

    Se devuelve en metros y no en lat/lon porque lo que dibuja la consola es
    un plano del parking, no un mapa: en grados, un parking de 40 m son cuatro
    decimales indistinguibles y el dibujo no se entiende.
    """
    if pads is None:
        pads = escenario.parking_slots(n_drones)
    centro = (escenario.parking_lat, escenario.parking_lon)

    posiciones = []
    for indice, (lat, lon) in enumerate(pads):
        # Componentes este/norte en metros, con signo.
        este = haversine_km(centro[0], centro[1], centro[0], lon) * 1000.0
        norte = haversine_km(centro[0], centro[1], lat, centro[1]) * 1000.0
        posiciones.append({
            "index": indice,
            "etiqueta": etiquetas[indice] if etiquetas else str(indice + 1),
            "lat": lat, "lon": lon,
            "x_m": round(este * (1 if lon >= centro[1] else -1), 2),
            "y_m": round(norte * (1 if lat >= centro[0] else -1), 2),
        })

    # Pares que NO pueden maniobrar a la vez, con la distancia que los separa.
    # La distancia viaja con el par porque es lo que hace entendible el
    # dibujo: una línea sin número no dice por qué esos dos se estorban.
    conflictos = []
    for i, a in enumerate(pads):
        for j, b in enumerate(pads[i + 1:], start=i + 1):
            if not escenario.pads_can_operate_together(a[0], a[1], b[0], b[1]):
                conflictos.append({
                    "a": i, "b": j,
                    "distancia_m": round(haversine_km(a[0], a[1], b[0], b[1]) * 1000.0, 1),
                })

    pares = [(c["a"], c["b"]) for c in conflictos]
    tandas = _tandas(len(pads), pares)
    return {
        "pads": posiciones,
        "conflictos": conflictos,
        "tandas": tandas,
        "n_tandas": (max(tandas) + 1) if tandas else 0,
        "simultaneos": _maniobras_simultaneas(len(pads), pares),
        "separacion_minima_m": _separacion_minima(pads),
        "separacion_exigida_m": escenario.pad_separation_m,
    }


# Hasta aquí el coloreado y el mayor conjunto compatible se buscan exactos.
# Los dos son exponenciales: con 30 pads la búsqueda exacta ya no acaba, así
# que por encima se usa DSatur y un voraz por grado mínimo, que en un parking
# (grafo geométrico, casi siempre una rejilla) suelen dar el óptimo.
EXACTO_HASTA = 12


def _vecinos(total: int, conflictos) -> list[set[int]]:
    vecinos = [set() for _ in range(total)]
    for a, b in conflictos:
        vecinos[a].add(b)
        vecinos[b].add(a)
    return vecinos


def _tandas(total: int, conflictos: list[tuple[int, int]]) -> list[int]:
    """Reparte los pads en turnos de despegue. Devuelve el turno de cada pad.

    Dos pads del mismo turno pueden maniobrar a la vez; hace falta un turno
    nuevo en cuanto se estorban. Es un coloreado del grafo de conflictos:
    exacto por backtracking hasta ``EXACTO_HASTA`` pads y DSatur por encima.

    Es la lectura que le falta al número de maniobras simultáneas: saber que
    caben tres a la vez no dice en cuántos turnos sale la flota entera.
    """
    if total == 0:
        return []
    vecinos = _vecinos(total, conflictos)
    if total > EXACTO_HASTA:
        return _dsatur(total, vecinos)

    for k in range(1, total + 1):
        asignacion = [-1] * total

        def colorear(indice: int) -> bool:
            if indice == total:
                return True
            for color in range(k):
                if all(asignacion[v] != color for v in vecinos[indice]):
                    asignacion[indice] = color
                    if colorear(indice + 1):
                        return True
                    asignacion[indice] = -1
            return False

        if colorear(0):
            return asignacion
    return list(range(total))


def _dsatur(total: int, vecinos: list[set[int]]) -> list[int]:
    """Coloreado DSatur: primero el pad con más turnos distintos alrededor."""
    asignacion = [-1] * total
    for _ in range(total):
        pendiente = max(
            (v for v in range(total) if asignacion[v] < 0),
            key=lambda v: (len({asignacion[u] for u in vecinos[v] if asignacion[u] >= 0}),
                           len(vecinos[v]), -v))
        usados = {asignacion[u] for u in vecinos[pendiente]}
        color = 0
        while color in usados:
            color += 1
        asignacion[pendiente] = color
    return asignacion


def _maniobras_simultaneas(total: int, conflictos: list[list[int]]) -> int:
    """Cuántos drones pueden maniobrar a la vez con esta formación.

    Es el mayor conjunto de pads compatibles dos a dos. Hasta
    ``EXACTO_HASTA`` pads se busca por fuerza bruta; por encima, un voraz que
    va cogiendo el pad con menos conflictos, que nunca sobrestima.
    """
    if total == 0:
        return 0
    if total > EXACTO_HASTA:
        vecinos = _vecinos(total, conflictos)
        libres = set(range(total))
        elegidos = 0
        while libres:
            pad = min(libres, key=lambda v: (len(vecinos[v] & libres), v))
            elegidos += 1
            libres -= vecinos[pad] | {pad}
        return elegidos

    incompatibles = {(a, b) for a, b in conflictos}
    mejor = 1
    for mascara in range(1, 1 << total):
        elegidos = [k for k in range(total) if mascara & (1 << k)]
        if len(elegidos) <= mejor:
            continue
        if all((a, b) not in incompatibles
               for i, a in enumerate(elegidos) for b in elegidos[i + 1:]):
            mejor = len(elegidos)
    return mejor


def _separacion_minima(pads) -> float:
    if len(pads) < 2:
        return 0.0
    return round(min(
        haversine_km(a[0], a[1], b[0], b[1]) * 1000.0
        for i, a in enumerate(pads) for b in pads[i + 1:]
    ), 2)


def aplicar_parking(banco: Banco, cambios: dict, n_drones: int,
                    categorias=None) -> dict:
    """Guarda la formación en el escenario activo y resiembra la flota."""
    escenarios = banco.escenarios()
    activo = escenarios.active()
    if activo is None:
        raise ValueError("no hay escenario activo")

    permitidos = ("pad_spacing_m", "pad_layout", "pad_cols", "pad_heading_deg",
                  "pad_separation_m", "vertiport_capacity", "takeoff_gap_s")
    actualizado = escenarios.update(
        activo.name, {k: v for k, v in cambios.items() if k in permitidos})

    registros = redimensionar_flota(banco, n_drones, actualizado, categorias)
    return {
        "escenario": actualizado.as_dict(),
        "drones": [r.as_dict() for r in registros],
        "parking": previsualizar_parking(actualizado, len(registros)),
    }


def redimensionar_flota(banco: Banco, n_drones: int, escenario,
                        categorias=None) -> list:
    """Deja la flota con ``n_drones``, recolocados según el escenario.

    Se reconstruye entera en vez de añadir o quitar filas: los pads dependen
    del total —la formación está centrada— así que cambiar el número de drones
    mueve también a los que ya estaban.

    ``categorias`` es la lista elegida en la consola, un elemento por dron.
    Lo que falte o no exista en el catálogo cae al valor por defecto de esa
    posición en vez de fallar: la consola manda el formulario entero y un
    hueco no debe tumbar el resto de la flota.
    """
    total = max(1, min(int(n_drones), max_drones()))
    validas = set(categorias_disponibles())
    pedidas = list(categorias or [])

    drones = []
    for k in range(total):
        categoria = pedidas[k] if k < len(pedidas) else None
        if categoria not in validas:
            categoria = categoria_por_defecto(k)
        drones.append({"drone_id": f"Dron-{k + 1}", "sysid": k + 1,
                       "instance": k, "category": categoria})

    registros = build_records({"drones": drones}, escenario)
    return banco.flota().replace_all(registros)


def quitar_dron(banco: Banco, drone_id: str) -> list:
    """Quita un dron concreto. Los demás conservan instancia, puertos y pad.

    No se recoloca nada: así sus instancias SITL siguen en marcha. La flota
    queda con un hueco en la numeración, que «Aplicar» vuelve a compactar.
    """
    flota = banco.flota()
    actuales = flota.list_drones(only_enabled=False)
    if not any(d.drone_id == drone_id for d in actuales):
        raise LookupError(f"No existe el dron {drone_id}")
    if len(actuales) <= 1:
        raise ValueError("La flota necesita al menos un dron")
    flota.remove(drone_id)
    return flota.list_drones(only_enabled=False)


def parar_instancia(drone_id: str) -> bool:
    """Para la instancia SITL local (Mission Planner) de un dron."""
    pids = sitl._read_pids()
    pid = pids.pop(drone_id, None)
    if pid is None:
        return False
    if os.name == "nt":
        import subprocess  # noqa: PLC0415
        subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                       capture_output=True, check=False)
    else:
        import signal  # noqa: PLC0415
        try:
            os.kill(int(pid), signal.SIGTERM)
        except OSError:
            pass
    if pids:
        sitl.PIDS_FILE.write_text(json.dumps(pids), encoding="utf-8")
    else:
        sitl.PIDS_FILE.unlink(missing_ok=True)
    return True


# ── Instancias SITL ──────────────────────────────────────────────────────
def estado_sitl(banco: Banco) -> dict:
    """Estado de cada instancia, sin abrir sockets contra ella.

    Sondear el puerto mata instancias (ver docs/swarm/SITL.md), así que el
    diagnóstico sale del proceso y de su log, igual que ``sitl status``.
    """
    pids = {}
    if sitl.PIDS_FILE.exists():
        try:
            pids = json.loads(sitl.PIDS_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pids = {}

    instancias = []
    for record in banco.flota().list_drones(only_enabled=False):
        wd = sitl.working_dir(record)
        texto = ""
        for nombre in ("stdout.log", "stderr.log"):
            fichero = wd / nombre
            if fichero.exists():
                texto += fichero.read_text(encoding="utf-8", errors="replace")
        pid = pids.get(record.drone_id)
        vivo = bool(pid) and sitl._is_alive(int(pid))
        puerto = sitl.port_of(record)
        instancias.append({
            "drone_id": record.drone_id,
            "sysid": record.sysid,
            "connection": record.connection,
            "pid": pid,
            "vivo": vivo,
            "escuchando": f"on TCP port {puerto}" in texto,
            "panic": "PANIC" in texto,
            "defaults_ok": "default_params" in texto or not texto,
        })
    return {
        "binario": str(sitl.binary_path()),
        "binario_ok": sitl.binary_path().exists(),
        "defaults": str(sitl.defaults_path()),
        "defaults_ok": (sitl.defaults_path().is_file()
                        and sitl.defaults_path().suffix.lower() == ".parm"),
        "speedup": sitl.speedup(),
        "instancias": instancias,
    }


def lanzar_sitl(speedup: float = 1.0) -> dict:
    """Lanza una instancia por dron habilitado. Devuelve la salida de sitl."""
    os.environ["SITL_SPEEDUP"] = str(speedup)
    codigo = sitl.launch()
    return {"ok": codigo == 0}


def parar_sitl() -> dict:
    return {"ok": sitl.stop() == 0}


# ── Base de datos ────────────────────────────────────────────────────────
def presets() -> list[dict]:
    """Escenarios de pedidos que ofrece ``airdrop.demo``."""
    from airdrop.demo import PRESETS  # noqa: PLC0415
    return [{"nombre": p.nombre, "descripcion": p.descripcion,
             "n_pedidos": p.n_pedidos, "por_dron": p.por_dron}
            for p in PRESETS.values()]


def sembrar(preset: str, semilla=None, pedidos=None) -> dict:
    """Siembra pedidos de prueba, como ``python -m airdrop.demo seed``.

    Se reutiliza el módulo de demo en vez de duplicar la lógica: colocar los
    clientes dentro de la geovalla y junto a un destino con ruta tiene bastante
    detalle acumulado, y dos copias divergirían.

    ``demo.seed`` está escrito para la línea de órdenes: informa por ``print``
    y aborta con ``SystemExit``. Aquí se captura lo uno y lo otro para poder
    devolverlo por HTTP, que es la única diferencia real entre las dos formas
    de invocarlo.
    """
    import contextlib  # noqa: PLC0415
    import io  # noqa: PLC0415

    from airdrop import demo  # noqa: PLC0415

    salida = io.StringIO()
    try:
        with contextlib.redirect_stdout(salida):
            demo.seed(preset, int(semilla) if semilla is not None else None,
                      int(pedidos) if pedidos else None)
    except SystemExit as exc:
        raise ValueError(str(exc)) from exc

    texto = salida.getvalue()
    creados = 0
    for linea in texto.splitlines():
        if linea.strip().endswith("pedido(s) listos."):
            creados = int(linea.split()[0])
    return {"creados": creados, "salida": texto}


def limpiar(banco: Banco, pedidos=True, clientes=False) -> dict:
    """Vacía las tablas del experimento. No toca escenarios ni flota.

    Los pedidos son lo que se ensucia entre pruebas; los clientes se conservan
    salvo que se pidan, porque volver a sembrarlos con coordenadas coherentes
    cuesta más que borrarlos.

    Borrar los clientes borra también sus pedidos y sus cuentas de acceso, que
    apuntan a ellos. PostgreSQL hace cumplir esas claves ajenas y rechazaba el
    DELETE; SQLite no las comprueba y por eso en local funcionaba.
    """
    # Instanciar el almacén crea las tablas si faltan. Contra una base de datos
    # recién hecha —la primera vez, o apuntando DATABASE_URL a otro sitio— el
    # DELETE fallaba con «no such table: orders» y salía por HTTP como un 500.
    from airdrop.api.data import DataStore  # noqa: PLC0415
    DataStore(banco.url)

    borrados = {}
    with banco.engine.begin() as conn:
        if pedidos or clientes:
            borrados["pedidos"] = conn.execute(
                select(func.count()).select_from(orders)).scalar_one()
            conn.execute(delete(orders))
        if clientes:
            borrados["cuentas"] = conn.execute(
                select(func.count()).select_from(users)).scalar_one()
            conn.execute(delete(users))
            borrados["clientes"] = conn.execute(
                select(func.count()).select_from(clients)).scalar_one()
            conn.execute(delete(clients))
    return {"borrados": borrados}
