"""La consola de simulación dentro del portal, para el administrador.

Es la misma herramienta que ``python -m simtools`` (formación del parking,
número y categoría de los drones, lanzar y parar el SITL con su aceleración,
sembrar y vaciar pedidos), servida en ``/simulacion.html`` y detrás del login
de administrador. En local basta con la consola suelta; en la nube no hay otra
forma de cambiar la flota que volar, así que el portal la incorpora.

Lo que cambia según el modo de vuelo es qué significa «lanzar»:

- **SITL embebido** (la nube, o Linux con ``SITL_EMBEDDED=1``): el portal
  relanza sus instancias de ArduCopter con la aceleración elegida.
- **SITL de Mission Planner** (Windows): se lanzan con el lanzador de siempre
  y el enjambre se reconecta a ellas.
- **Enlace simulado**: no hay procesos; la aceleración multiplica la velocidad.

El enlace con el portal (reconstruir el enjambre, saber si hay drones en vuelo)
llega por ``Hooks``, que rellena ``main``: así este módulo no importa el
portal y el portal no se llena de rutas de una herramienta de banco.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from simtools import sim

SPEEDUP_KEY = "sim_speedup"
SITL_ON_KEY = "sim_sitl_activo"
MAX_SPEEDUP = 10.0


class Formacion(BaseModel):
    n_drones: int = Field(4, ge=1, le=sim.MAX_DRONES)
    pad_layout: str = "fila"
    pad_spacing_m: float = Field(8.0, gt=0)
    pad_cols: int = Field(0, ge=0)
    pad_heading_deg: float = 90.0
    pad_separation_m: float = Field(0.0, ge=0)
    vertiport_capacity: int = Field(0, ge=0)
    takeoff_gap_s: float = Field(10.0, ge=0)
    categorias: list[str] = Field(default_factory=list)


class Lanzamiento(BaseModel):
    speedup: float = Field(1.0, gt=0, le=MAX_SPEEDUP)


class Limpieza(BaseModel):
    pedidos: bool = True
    clientes: bool = False


class Siembra(BaseModel):
    preset: str = "oleada"
    semilla: int | None = 42
    pedidos: int | None = Field(None, ge=1, le=sim.MAX_PEDIDOS)


@dataclass
class Hooks:
    """Lo que la consola necesita del portal."""

    banco: Callable[[], sim.Banco]
    store: object                       # DataStore: ajustes en la tabla config
    backend: Callable[[], str]          # "sitl", "simulado", "stub"
    embedded: Callable[[], bool]        # ¿lanza el portal su propio SITL?
    busy: Callable[[], bool]            # ¿hay drones en vuelo?
    rebuild: Callable[[], object]       # rehace el enjambre con la flota y el escenario
    embedded_status: Callable[[], list]  # instancias del SITL embebido
    stop_embedded: Callable[[], object] = lambda: None  # para todo el SITL embebido
    remove_drone: Callable[[str], object] = lambda _id: None  # saca un dron del enjambre


hooks: Hooks | None = None


def speedup(store) -> float:
    try:
        valor = float(store.get_setting(SPEEDUP_KEY) or 1.0)
    except (TypeError, ValueError):
        valor = 1.0
    return min(max(valor, 0.1), MAX_SPEEDUP)


def sitl_on(store) -> bool:
    """¿Debe el SITL embebido estar en marcha? Por defecto sí."""
    return (store.get_setting(SITL_ON_KEY) or "1") != "0"


def _hooks() -> Hooks:
    if hooks is None:
        raise HTTPException(503, "la consola de simulación no está disponible")
    return hooks


def _sin_vuelos(h: Hooks) -> None:
    if h.busy():
        raise HTTPException(409, "Hay drones en vuelo; para los repartos antes")


def _activo(banco: sim.Banco):
    escenario = banco.escenarios().active()
    if escenario is None:
        raise HTTPException(400, "no hay ningún escenario activo")
    return escenario


def _estado_sitl(h: Hooks, banco: sim.Banco) -> dict:
    modo = h.backend()
    if modo == "sitl" and not h.embedded():
        estado = sim.estado_sitl(banco)          # Windows: SITL de Mission Planner
        estado["modo"] = "mission_planner"
        return estado
    base = {"speedup": speedup(h.store), "binario_ok": True, "defaults_ok": True}
    if modo == "sitl":
        return {**base, "modo": "embebido", "binario": "ArduCopter SITL para Linux",
                "defaults": "copter.parm", "instancias": h.embedded_status()}
    return {**base, "modo": "simulado", "binario": "enlace simulado (sin SITL)",
            "defaults": "", "instancias": []}


def build_router(require_admin) -> APIRouter:
    router = APIRouter(prefix="/api/admin/sim", dependencies=[Depends(require_admin)])

    @router.get("/estado")
    def estado():
        h = _hooks()
        banco = h.banco()
        escenario = _activo(banco)
        drones = banco.flota().list_drones(only_enabled=False)
        return {
            "escenario": escenario.as_dict(),
            "drones": [d.as_dict() for d in drones],
            "parking": sim.parking_de_flota(escenario, drones),
            "sitl": _estado_sitl(h, banco),
            "categorias": sim.categorias_disponibles(),
            "presets": sim.presets(),
            "max_drones": sim.max_drones(),
        }

    @router.post("/parking/previsualizar")
    def previsualizar(formacion: Formacion):
        """Dibuja la formación sin guardarla."""
        escenario = _activo(_hooks().banco())
        hipotesis = replace(
            escenario,
            pad_layout=formacion.pad_layout,
            pad_spacing_m=formacion.pad_spacing_m,
            pad_cols=formacion.pad_cols,
            pad_heading_deg=formacion.pad_heading_deg,
            pad_separation_m=formacion.pad_separation_m,
        )
        return {"parking": sim.previsualizar_parking(hipotesis, formacion.n_drones),
                "escenario": hipotesis.as_dict()}

    @router.post("/parking/aplicar")
    def aplicar(formacion: Formacion):
        """Guarda la formación, rehace la flota y, si puede, el enjambre."""
        h = _hooks()
        _sin_vuelos(h)
        try:
            resultado = sim.aplicar_parking(h.banco(), formacion.model_dump(),
                                            formacion.n_drones, formacion.categorias)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        if h.backend() in ("sitl", "simulado"):
            h.rebuild()
        return resultado

    @router.post("/sitl/lanzar")
    def lanzar(peticion: Lanzamiento):
        h = _hooks()
        _sin_vuelos(h)
        h.store.set_setting(SPEEDUP_KEY, str(peticion.speedup))
        h.store.set_setting(SITL_ON_KEY, "1")
        if h.backend() == "sitl" and not h.embedded():
            ok = sim.lanzar_sitl(peticion.speedup)["ok"]
            h.rebuild()       # el enjambre se conecta a las instancias nuevas
            return {"ok": ok}
        # «Lanzar» es empezar de cero: sin esto el arranque incremental dejaría
        # vivas las instancias que no cambian, con su batería y su estado.
        h.stop_embedded()
        h.rebuild()
        estados = h.embedded_status()
        return {"ok": all(i["vivo"] for i in estados) if estados else True}

    @router.post("/sitl/parar")
    def parar():
        h = _hooks()
        _sin_vuelos(h)
        if h.backend() == "sitl" and not h.embedded():
            return sim.parar_sitl()
        h.store.set_setting(SITL_ON_KEY, "0")
        h.rebuild()
        return {"ok": True}

    @router.delete("/flota/{drone_id}")
    def quitar(drone_id: str):
        """Quita un dron de la flota y para su instancia, sin tocar los demás."""
        h = _hooks()
        _sin_vuelos(h)
        try:
            restantes = sim.quitar_dron(h.banco(), drone_id)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        if h.backend() == "sitl" and not h.embedded():
            sim.parar_instancia(drone_id)     # SITL de Mission Planner, en Windows
        # Sin rehacer el enjambre: los demás drones no pierden su enlace.
        h.remove_drone(drone_id)
        return {"drones": [d.as_dict() for d in restantes]}

    @router.post("/bd/limpiar")
    def limpiar(peticion: Limpieza):
        return sim.limpiar(_hooks().banco(), peticion.pedidos, peticion.clientes)

    @router.post("/bd/sembrar")
    def sembrar(peticion: Siembra):
        try:
            return sim.sembrar(peticion.preset, peticion.semilla, peticion.pedidos)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    return router
