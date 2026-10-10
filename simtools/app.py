"""API local de la consola de simulación.

Sin autenticación **a propósito**: escucha solo en 127.0.0.1 y sus operaciones
—matar procesos, vaciar tablas— no tienen equivalente en producción. Si algún
día se expusiera fuera de localhost habría que ponerle la misma puerta que al
portal; mientras tanto, un login aquí sería teatro.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from simtools import sim

WEB_DIR = Path(__file__).resolve().parent / "web"

app = FastAPI(title="Consola de simulación del enjambre")


class Formacion(BaseModel):
    """Parámetros de la formación del parking."""

    n_drones: int = Field(4, ge=1, le=sim.MAX_DRONES)
    pad_layout: str = "fila"
    pad_spacing_m: float = Field(8.0, gt=0)
    pad_cols: int = Field(0, ge=0)
    pad_heading_deg: float = 90.0
    pad_separation_m: float = Field(0.0, ge=0)
    vertiport_capacity: int = Field(0, ge=0)
    takeoff_gap_s: float = Field(10.0, ge=0)
    # Una categoría por dron, en orden. Lo que falte cae al valor por defecto
    # de esa posición, así que la previsualización puede no mandarlas.
    categorias: list[str] = Field(default_factory=list)


class Lanzamiento(BaseModel):
    speedup: float = Field(1.0, gt=0, le=20)


class Limpieza(BaseModel):
    pedidos: bool = True
    clientes: bool = False


class Siembra(BaseModel):
    preset: str = "oleada"
    semilla: int | None = 42
    pedidos: int | None = Field(None, ge=1, le=sim.MAX_PEDIDOS)


def _banco() -> sim.Banco:
    return sim.Banco.desde_entorno()


def _activo(banco: sim.Banco):
    escenario = banco.escenarios().active()
    if escenario is None:
        raise HTTPException(400, "no hay ningún escenario activo")
    return escenario


@app.get("/api/estado")
def estado():
    banco = _banco()
    escenario = _activo(banco)
    drones = banco.flota().list_drones(only_enabled=False)
    return {
        "escenario": escenario.as_dict(),
        "drones": [d.as_dict() for d in drones],
        "parking": sim.parking_de_flota(escenario, drones),
        "sitl": sim.estado_sitl(banco),
        "categorias": sim.categorias_disponibles(),
        "presets": sim.presets(),
        "max_drones": sim.max_drones(),
    }


@app.post("/api/parking/previsualizar")
def previsualizar(formacion: Formacion):
    """Dibuja la formación **sin guardarla**.

    Que la previsualización no toque la base de datos es lo que permite girar
    la rejilla y mover el espaciado con el ratón mientras hay una simulación
    en marcha, sin recolocar drones que están volando.
    """
    escenario = _activo(_banco())
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


@app.post("/api/parking/aplicar")
def aplicar(formacion: Formacion):
    banco = _banco()
    try:
        return sim.aplicar_parking(banco, formacion.model_dump(),
                                   formacion.n_drones, formacion.categorias)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.delete("/api/flota/{drone_id}")
def quitar(drone_id: str):
    """Quita un dron y para su instancia SITL, sin tocar las demás."""
    try:
        restantes = sim.quitar_dron(_banco(), drone_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    sim.parar_instancia(drone_id)
    return {"drones": [d.as_dict() for d in restantes]}


@app.post("/api/sitl/lanzar")
def lanzar(peticion: Lanzamiento):
    """Lanza las instancias. Tarda: espera a que arranquen antes de responder."""
    return sim.lanzar_sitl(peticion.speedup)


@app.post("/api/sitl/parar")
def parar():
    return sim.parar_sitl()


@app.post("/api/bd/limpiar")
def limpiar(peticion: Limpieza):
    return sim.limpiar(_banco(), peticion.pedidos, peticion.clientes)


@app.post("/api/bd/sembrar")
def sembrar(peticion: Siembra):
    """Equivale a ``python -m airdrop.demo seed <preset> --seed <semilla>``."""
    try:
        return sim.sembrar(peticion.preset, peticion.semilla, peticion.pedidos)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/")
def consola():
    return FileResponse(WEB_DIR / "console.html")


app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
