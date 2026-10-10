"""
Portal cliente + panel de administración sobre FastAPI, desplegable en cloud.

Sirve los estáticos de airdrop/web/ y expone la API REST que consumen el
portal de cliente (alta/login de cliente, alta y listado de pedidos) y el panel
de administrador (login admin, gestión de perfiles de ruta y de pedidos/flota).

Los perfiles de ruta y los administradores se guardan en la base de datos
(PostgreSQL en producción), no en disco, porque el sistema de ficheros del
servicio desplegado es efímero. En la nube no hay SITL ni dron real: con
DRONE_BACKEND=simulado el enjambre vuela sobre el enlace simulado.
"""

import atexit
import logging
import os
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from airdrop.api import auth, sim_admin
from airdrop.api.data import DataStore
from airdrop.config import WEB_DIR
from airdrop.domain.geocoding import geocode_address
from airdrop.domain.routes import RouteService

log = logging.getLogger(__name__)

# Uvicorn solo configura sus propios registros. Sin esto, los avisos del
# enjambre, del SITL y de la pasarela (nivel INFO) no salían en el registro del
# servicio. Se escriben en stdout para que Railway no los marque como errores.
if not logging.getLogger().handlers:
    import sys as _sys
    logging.basicConfig(level=logging.INFO, stream=_sys.stdout,
                        format="%(levelname)s %(name)s: %(message)s")
from airdrop.drone.backend import get_backend
from airdrop.swarm.scenario_repository import ScenarioRepository
from core.energy import DEFAULT_FLEET_DISTRIBUTION, DRONE_CATEGORIES

app = FastAPI(title="Portal Drones")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

store = DataStore()
# Origen de telemetría y destino de misiones. En cloud es un stub; en local
# (DRONE_BACKEND=local) se conecta a Mission Planner por dronLink.
drone = get_backend()


def _build_mission(profile_name, route_name):
    """Construye la misión (waypoints) usando los perfiles guardados en BD."""
    rs = RouteService.from_profiles(store.get_profiles())
    return rs.build_mission(profile_name, route_name)


def _resolved_scenario(scenario):
    """Escenario con el parking resuelto contra el escenario de rutas.

    El parking lo dibuja el administrador en el mapa; el escenario operacional
    solo dice cual usa. Antes eran dos coordenadas independientes que podian
    discrepar sin que nada avisara.
    """
    from airdrop.swarm.scenario_link import resolve_parking  # noqa: PLC0415

    return resolve_parking(scenario, store.get_profiles())


def _active_scenario():
    return _resolved_scenario(scenarios_repo.active())


class _OrdersStore:
    """Vista del DataStore que necesita SwarmService.

    Existe para que el enjambre no dependa de toda la API del DataStore: le
    basta con listar pendientes, leer uno y actualizar su avance.
    """

    def __init__(self, data_store):
        self.store = data_store

    def list_pending(self):
        # Por orden de llegada. ``list_orders`` devuelve los más recientes
        # primero, que es lo que quiere ver el panel, pero el planificador los
        # necesita al revés: el voraz es FIFO y sin esto atendía primero al
        # último en llegar.
        pendientes = [o for o in self.store.list_orders(None) if o.get("status") == "pendiente"]
        return sorted(pendientes, key=lambda o: o["id"])

    def get(self, order_id):
        return next((o for o in self.store.list_orders(None) if o["id"] == order_id), None)

    def update(self, order_id, status=None, operational_state=None, assigned_drone_id=None):
        self.store.update_order(order_id, status=status,
                                operational_state=operational_state,
                                assigned_drone_id=assigned_drone_id)


scenarios_repo = ScenarioRepository(store.engine)
scenarios_repo.seed_if_empty()


_BACKEND = os.environ.get("DRONE_BACKEND", "stub").lower()


_SITL = None   # instancias SITL que lanza el propio portal (solo en la nube)


def _launch_embedded_sitl(flota, escenario):
    global _SITL
    from airdrop.swarm import sitl_linux  # noqa: PLC0415

    if _SITL is None:
        _SITL = sitl_linux.EmbeddedSitl()
        atexit.register(_SITL.stop)
    # La aceleración la elige la consola de simulación y se guarda en la BD.
    os.environ["SITL_SPEEDUP"] = f"{sim_admin.speedup(store):g}"
    try:
        return _SITL.start(flota.seed_if_empty(escenario))
    except Exception:  # noqa: BLE001
        # Sin SITL el portal sigue sirviendo; los drones salen sin conexión.
        log.exception("no se pudo lanzar el SITL embebido")
        return {}


SITL_SOURCE_KEY = "sitl_source"
SITL_SOURCES = ("nube", "puente")


def _sitl_source() -> str:
    """De dónde salen los drones con DRONE_BACKEND=sitl.

    «nube»: el SITL que lanza el propio portal (o, en local, el de Mission
    Planner en este mismo equipo). «puente»: el SITL de Mission Planner de
    otro PC, que llega por la pasarela. Se guarda en la base de datos para
    que sobreviva a los reinicios del portal.
    """
    valor = store.get_setting(SITL_SOURCE_KEY)
    return valor if valor in SITL_SOURCES else "nube"


def _swarm_rebuildable() -> bool:
    """¿Puede el portal rehacer el enjambre él solo, sin reiniciarse?

    Con el enlace simulado y con el SITL embebido sí: los drones nacen en el
    portal. Con el SITL de Mission Planner no, porque esas instancias viven
    fuera y hay que relanzarlas en los pads nuevos.
    """
    from airdrop.swarm import sitl_linux  # noqa: PLC0415

    return (_BACKEND == "simulado"
            or (_BACKEND == "sitl" and (sitl_linux.enabled() or _sitl_source() == "puente")))


def _rebuild_swarm():
    """Para el enjambre y lo vuelve a crear con el escenario activo."""
    global swarm
    if swarm is not None:
        swarm.stop_auto()
        swarm.wait_idle(timeout=10)
        swarm.close_all()
    swarm = _build_swarm()
    return swarm


def _build_swarm():
    """Crea el enjambre solo si hay backend de vuelo.

    En cloud (DRONE_BACKEND=stub) no hay autopilotos, así que no se crea nada y
    los endpoints del enjambre responden que no está disponible.

    Solo "sitl". Con "local", get_backend() ya devuelve un LocalBackend que
    conecta al 5763 por su cuenta; construir además el enjambre daría dos
    clientes MAVLink peleándose por los mismos autopilotos.
    """
    backend = os.environ.get("DRONE_BACKEND", "stub").lower()
    if backend not in ("sitl", "simulado"):
        return None
    from airdrop.swarm.repository import FleetRepository  # noqa: PLC0415
    from airdrop.swarm.service import SwarmService  # noqa: PLC0415

    flota = FleetRepository(store.engine)
    if backend == "simulado":
        # Demostración en la nube: el orquestador real (planificador, espacio
        # aéreo, seguridad y ejecutores) sobre el enlace simulado, que vuela a
        # la velocidad de crucero del perfil. Sin autopilotos ni SITL.
        from airdrop.swarm.fake import FakeDroneLink  # noqa: PLC0415

        flota.seed_if_empty(_active_scenario())
        # La aceleración de la consola de simulación multiplica la velocidad.
        velocidad = float(os.environ.get("SIM_SPEED_MPS") or 7.0) * sim_admin.speedup(store)

        def link_factory(r):
            return FakeDroneLink(r.drone_id, r.home_lat, r.home_lon,
                                 speed_mps=velocidad)
    else:
        from airdrop.swarm import sitl_linux  # noqa: PLC0415
        from airdrop.swarm.link import MavlinkDroneLink  # noqa: PLC0415

        origen = _sitl_source()
        if sitl_linux.enabled() and origen == "nube" and sim_admin.sitl_on(store):
            # En la nube el portal lanza su propio SITL de Linux, una
            # instancia por dron en su pad, antes de conectarse a ellas.
            _launch_embedded_sitl(flota, _active_scenario())
        elif _SITL is not None:
            _SITL.stop()

        def link_factory(r):
            if origen == "puente":
                # El SITL está en el PC del laboratorio y llega por el túnel
                # de la pasarela, que lo sirve en 127.0.0.1:6762+10i.
                from airdrop.swarm.pasarela import bridge_port  # noqa: PLC0415

                conexion = f"tcp:127.0.0.1:{bridge_port(r.instance)}"
            else:
                conexion = r.connection
            return MavlinkDroneLink(r.drone_id, conexion, r.home_lat, r.home_lon)

    service = SwarmService(
        scenario=_active_scenario(),
        repository=flota,
        link_factory=link_factory,
        build_mission=_build_mission,
    )
    # Sin bloquear: el portal debe levantar aunque un autopiloto no responda.
    # Los drones van apareciendo conectados según contestan.
    service.connect_all(block=False)
    return service


def _requeue_orphan_orders() -> int:
    """Devuelve a la cola los pedidos que quedaron en vuelo sin ejecutor.

    El estado vivo del enjambre está en memoria: al reiniciar el portal, los
    pedidos que estaban ``asignado`` o ``en_reparto`` conservan ese estado en
    la base de datos pero ya no tiene nadie que los lleve. Quedan como pedidos
    fantasma —el panel los muestra en reparto y su dron no se mueve nunca— y
    tampoco vuelven a la cola, así que no los recoge ningún ciclo.

    Se ejecuta al arrancar, que es el único momento en que se puede afirmar
    que no hay ejecutores vivos.
    """
    devueltos = 0
    try:
        for o in store.list_orders(None):
            if o.get("status") in ("asignado", "en_reparto"):
                store.update_order(o["id"], status="pendiente",
                                   operational_state="devuelto a la cola tras reinicio")
                devueltos += 1
    except Exception:  # noqa: BLE001
        log.exception("no se pudieron recuperar los pedidos huérfanos")
    if devueltos:
        log.warning("%d pedido(s) en vuelo sin ejecutor devueltos a la cola", devueltos)
    return devueltos


def _autolink_scenario_parkings() -> int:
    """Enlaza cada escenario con el parking del mapa que ya está usando.

    Migración de datos para las bases creadas antes de que el parking tuviera
    dueño único. Solo se enlaza cuando las coordenadas guardadas **ya
    coinciden** con las de un parking del escenario de rutas: ahí el enlace no
    cambia ni un metro de comportamiento, solo hace explícito lo que era
    implícito.

    Los que discrepan se dejan como están y el panel los marca en rojo. Mover
    el parking de un escenario un kilómetro por iniciativa propia, y con ello
    los pads y la geovalla, no es cosa de una migración automática.
    """
    from core.geo import haversine_km  # noqa: PLC0415
    from airdrop.swarm.scenario_link import _parkings_de  # noqa: PLC0415

    profiles = store.get_profiles()
    enlazados = 0
    for s in scenarios_repo.list_scenarios():
        if s.parking_name:
            continue
        for punto in _parkings_de(profiles, s.route_profile_name):
            if punto.get("lat") is None or punto.get("lon") is None:
                continue
            metros = haversine_km(s.parking_lat, s.parking_lon,
                                  float(punto["lat"]), float(punto["lon"])) * 1000.0
            if metros <= 1.0:
                scenarios_repo.update(s.name, {"parking_name": str(punto["name"])})
                enlazados += 1
                break
    if enlazados:
        log.info("%d escenario(s) enlazados a su parking del mapa", enlazados)
    return enlazados


try:
    _autolink_scenario_parkings()
except Exception:  # noqa: BLE001
    # Una migración que falla no puede impedir que el portal arranque.
    log.exception("no se pudieron enlazar los parkings de los escenarios")

swarm = _build_swarm()
if swarm is not None:
    _requeue_orphan_orders()


def _pasarela_instances():
    """Instancias SITL locales que la pasarela ofrece a Mission Planner."""
    if _SITL is None or _sitl_source() != "nube":
        return []
    return [r.instance for r in swarm._records] if swarm is not None else []


def _pasarela_agent(instance):
    """Un puente acaba de conectar un dron: el enjambre lo reconecta."""
    if swarm is None or _sitl_source() != "puente":
        return
    record = next((r for r in swarm._records if r.instance == instance), None)
    if record is not None:
        swarm.reconnect(record.drone_id)


pasarela = None
if _BACKEND == "sitl":
    from airdrop.swarm import pasarela as _pasarela_mod  # noqa: E402

    pasarela = _pasarela_mod.from_env(_pasarela_instances, _pasarela_agent)
    if pasarela is not None:
        try:
            pasarela.start()
        except Exception:  # noqa: BLE001
            log.exception("no se pudo abrir la pasarela MAVLink")
            pasarela = None


# ── Modelos de entrada ───────────────────────────────────────────────────────

class LoginIn(BaseModel):
    name: str = ""
    address: str = ""


class OrderIn(BaseModel):
    weight_kg: float = 1.0


class AdminCredentials(BaseModel):
    username: str = ""
    password: str = ""


class UserRegister(BaseModel):
    username: str = ""
    password: str = ""
    name: str = ""
    address: str = ""


class UserLogin(BaseModel):
    username: str = ""
    password: str = ""


class AccountUpdate(BaseModel):
    name: str | None = None
    address: str | None = None


class OrderStateIn(BaseModel):
    status: str | None = None
    operational_state: str | None = None


# ── Portal de cliente ────────────────────────────────────────────────────────

@app.post("/api/clients/login")
def login(data: LoginIn):
    name, address = data.name.strip(), data.address.strip()
    if not name or not address:
        return JSONResponse({"error": "Nombre y dirección son obligatorios"}, 400)
    for c in store.list_clients():
        if c["name"].lower() == name.lower() and c["address"].lower() == address.lower():
            return {"client": c}
    try:
        lat, lon = geocode_address(address)
    except Exception:
        # Si el geocoder falla (rate-limit/timeout en cloud) no bloqueamos el
        # alta: el cliente queda sin coordenadas y se podrá corregir luego.
        lat, lon = None, None
    return {"client": store.create_client(name, address, lat, lon)}


# ── Cuentas de usuario (portal de cliente) ───────────────────────────────────

def require_user(authorization: str = Header(default="")):
    """Dependencia: exige un token de usuario válido y devuelve su cuenta."""
    token = authorization[7:] if authorization.lower().startswith("bearer ") else authorization
    username = auth.verify_token(token, "user")
    user = store.get_user(username) if username else None
    if not user:
        raise HTTPException(status_code=401, detail="No autorizado")
    return user


@app.post("/api/users/register")
def user_register(data: UserRegister):
    username, password = data.username.strip(), data.password
    name, address = data.name.strip(), data.address.strip()
    if not username or len(password) < 6 or not name or not address:
        return JSONResponse(
            {"error": "Usuario, contraseña (6+), nombre y dirección son obligatorios"}, 400)
    if store.get_user(username):
        return JSONResponse({"error": "Ese usuario ya existe"}, 409)
    try:
        lat, lon = geocode_address(address)
    except Exception:
        lat, lon = None, None
    client = store.create_client(name, address, lat, lon)
    store.create_user(username, auth.hash_password(password), client["id"])
    return {"token": auth.create_token(username, "user"), "client": client}


@app.post("/api/users/login")
def user_login(data: UserLogin):
    user = store.get_user(data.username.strip())
    if not user or not auth.verify_password(data.password, user["password_hash"]):
        return JSONResponse({"error": "Credenciales incorrectas"}, 401)
    client = store.get_client(user["client_id"])
    return {"token": auth.create_token(user["username"], "user"), "client": client}


def _apply_account_update(client_id, name, address):
    """Actualiza nombre y/o dirección de un cliente, re-geocodificando si cambia."""
    name = (name or "").strip()
    address = (address or "").strip()
    if address:
        try:
            lat, lon = geocode_address(address)
        except Exception:
            lat, lon = None, None
        return store.update_client(client_id, name=name or None, address=address, lat=lat, lon=lon)
    return store.update_client(client_id, name=name or None)


@app.put("/api/users/me")
def user_update_me(data: AccountUpdate, user=Depends(require_user)):
    """El usuario edita su propia dirección (y nombre)."""
    if not (data.address or "").strip() and not (data.name or "").strip():
        return JSONResponse({"error": "Nada que actualizar"}, 400)
    client = _apply_account_update(user["client_id"], data.name, data.address)
    return {"client": client}


def _attach_waypoints(order_list):
    """Añade a cada pedido los waypoints de su ruta para dibujarla en el mapa."""
    for o in order_list:
        pname, rname = o.get("assigned_profile_name"), o.get("assigned_route_name")
        if pname and rname:
            try:
                wps = _build_mission(pname, rname).get("waypoints", [])
                coords = [{"lat": float(w["lat"]), "lon": float(w["lon"])} for w in wps]
                clat, clon = o.get("client_latitude"), o.get("client_longitude")
                if clat is not None and clon is not None:
                    coords.append({"lat": float(clat), "lon": float(clon)})
                o["route_waypoints"] = coords
            except Exception:
                pass
    return order_list


def _fleet_specs():
    """Spec física por dron, en una sola consulta.

    Se resuelve de golpe y no dron a dron: el portal de cliente sondea cada
    dos segundos y una consulta por pedido convierte un listado en un N+1
    contra la base de datos.
    """
    from core.energy import DRONE_CATEGORIES  # noqa: PLC0415
    from airdrop.swarm.repository import FleetRepository  # noqa: PLC0415

    try:
        return {d.drone_id: DRONE_CATEGORIES.get(d.category)
                for d in FleetRepository(store.engine).list_drones(only_enabled=False)}
    except Exception:  # noqa: BLE001
        return {}


def _attach_tracking(order_list):
    """Añade a cada pedido el dron que lo lleva y una estimación de entrega.

    El portal de cliente pedía la telemetría a ``/api/drone/telemetry``, que
    con ``DRONE_BACKEND=sitl`` devuelve el stub: el enjambre no pasa por ahí,
    así que el cliente nunca veía moverse nada. Aquí la posición sale del
    runtime del enjambre, que es donde está de verdad.

    El ETA es deliberadamente simple —distancia restante entre velocidad de
    crucero— y se marca como estimación. No modela viento, esperas por HUB ni
    la pausa de entrega, así que es una cota inferior útil para el cliente, no
    una promesa.
    """
    from core.geo import haversine_km  # noqa: PLC0415

    specs = _fleet_specs()
    for o in order_list:
        o["drone"] = None
        o["eta_s"] = None

        spec = specs.get(o.get("assigned_drone_id"))
        velocidad = spec.cruise_speed_mps if spec else 7.0

        runtime = None
        if swarm is not None and o.get("assigned_drone_id"):
            runtime = swarm.runtime(o["assigned_drone_id"])

        if runtime is not None and runtime.lat is not None and runtime.lon is not None:
            o["drone"] = {
                "drone_id": runtime.drone_id,
                "lat": runtime.lat,
                "lon": runtime.lon,
                "alt": runtime.alt,
                "heading": runtime.heading,
                "ground_speed": runtime.ground_speed,
                "state": runtime.state,
                "detail": runtime.detail,
                "battery_pct": round(runtime.battery_pct, 1),
            }
            clat, clon = o.get("client_latitude"), o.get("client_longitude")
            if clat is not None and clon is not None:
                restante_km = haversine_km(runtime.lat, runtime.lon,
                                           float(clat), float(clon))
                o["eta_s"] = round(restante_km * 1000.0 / max(velocidad, 0.1))
        elif o.get("status") == "pendiente":
            # Aún sin dron: se estima el trayecto completo desde el parking.
            distancia = o.get("assigned_distance_km")
            if distancia:
                o["eta_s"] = round(float(distancia) * 1000.0 / max(velocidad, 0.1))
    return order_list


@app.get("/api/orders")
def list_orders(user=Depends(require_user)):
    try:
        result = store.list_orders(user["client_id"])
    except Exception as e:
        return JSONResponse({"error": str(e)}, 400)
    return {"orders": _attach_tracking(_attach_waypoints(result))}


def _max_payload_kg() -> float | None:
    """Carga máxima que admite el dron más capaz de la flota habilitada."""
    from core.energy import DRONE_CATEGORIES  # noqa: PLC0415
    from airdrop.swarm.repository import FleetRepository  # noqa: PLC0415

    try:
        capacidades = [
            DRONE_CATEGORIES[d.category].max_payload_kg
            for d in FleetRepository(store.engine).list_drones(only_enabled=True)
            if d.category in DRONE_CATEGORIES
        ]
    except Exception:  # noqa: BLE001
        return None
    return max(capacidades) if capacidades else None


@app.post("/api/orders")
def create_order(data: OrderIn, user=Depends(require_user)):
    # Un pedido que supera la capacidad del dron más capaz no lo puede llevar
    # nadie: el planificador lo descarta cada ciclo y se queda en la cola para
    # siempre, en silencio. Pasó de verdad —pedidos de 5, 7 y 8 kg con una
    # flota cuyo tope son 4 kg— y desde fuera parecía que el enjambre había
    # dejado de repartir. Es mejor rechazarlo aquí y decir por qué.
    tope = _max_payload_kg()
    if tope is not None and float(data.weight_kg) > tope:
        return JSONResponse(
            {"error": f"Ningún dron de la flota puede con {data.weight_kg} kg. "
                      f"La carga máxima es {tope:g} kg."}, 400)
    try:
        assignment = store.create_order(user["client_id"], data.weight_kg)
    except Exception as e:
        return JSONResponse({"error": str(e)}, 400)
    return {"success": True, "assignment": assignment}


@app.get("/api/drone/telemetry")
def telemetry():
    # En cloud el backend es un stub; en local devuelve la telemetría real de
    # Mission Planner (posición, altitud, velocidad, rumbo).
    return drone.telemetry()


# ── Autenticación de administrador ───────────────────────────────────────────

def require_admin(authorization: str = Header(default="")):
    """Dependencia: exige un token de admin válido en la cabecera Authorization."""
    token = authorization[7:] if authorization.lower().startswith("bearer ") else authorization
    username = auth.verify_token(token, "admin")
    if not username:
        raise HTTPException(status_code=401, detail="No autorizado")
    return username


@app.get("/api/admin/needs-setup")
def admin_needs_setup():
    """Indica si aún no hay ningún administrador (para mostrar el alta inicial)."""
    return {"needs_setup": store.count_admins() == 0}


@app.post("/api/admin/register")
def admin_register(data: AdminCredentials):
    # Solo se permite crear el primer admin (bootstrap). Después, ninguno más
    # por esta vía pública.
    if store.count_admins() > 0:
        return JSONResponse({"error": "Ya existe un administrador"}, 403)
    username, password = data.username.strip(), data.password
    if not username or len(password) < 6:
        return JSONResponse({"error": "Usuario obligatorio y contraseña de 6+ caracteres"}, 400)
    store.create_admin(username, auth.hash_password(password))
    return {"token": auth.create_token(username, "admin"), "username": username}


@app.post("/api/admin/login")
def admin_login(data: AdminCredentials):
    admin = store.get_admin(data.username.strip())
    if not admin or not auth.verify_password(data.password, admin["password_hash"]):
        return JSONResponse({"error": "Credenciales incorrectas"}, 401)
    return {"token": auth.create_token(admin["username"], "admin"), "username": admin["username"]}


# ── Panel de administrador: perfiles de ruta ─────────────────────────────────

@app.get("/api/admin/profiles")
def admin_get_profiles(_: str = Depends(require_admin)):
    return store.get_profiles()


@app.put("/api/admin/profiles")
def admin_save_profiles(payload: dict, _: str = Depends(require_admin)):
    if not isinstance(payload.get("profiles"), list):
        return JSONResponse({"error": "Formato inválido: falta 'profiles'"}, 400)
    store.save_profiles(payload)
    return {"success": True}


# ── Panel de administrador: pedidos y flota ──────────────────────────────────

@app.get("/api/admin/orders")
def admin_orders(_: str = Depends(require_admin)):
    return {"orders": _attach_waypoints(store.list_orders(None))}


@app.post("/api/admin/orders/{order_id}/state")
def admin_order_state(order_id: int, data: OrderStateIn, _: str = Depends(require_admin)):
    store.update_order(order_id, status=data.status, operational_state=data.operational_state)
    return {"success": True}


@app.delete("/api/admin/orders/{order_id}")
def admin_delete_order(order_id: int, _: str = Depends(require_admin)):
    store.delete_order(order_id)
    return {"success": True}


@app.post("/api/admin/orders/{order_id}/dispatch")
def admin_dispatch(order_id: int, _: str = Depends(require_admin)):
    """Despacha un pedido al primer dron libre del enjambre."""
    orders_store = _OrdersStore(store)
    order = orders_store.get(order_id)
    if not order:
        return JSONResponse({"error": "Pedido no encontrado"}, 404)
    pname, rname = order.get("assigned_profile_name"), order.get("assigned_route_name")
    if not pname or not rname:
        return JSONResponse({"error": "El pedido no tiene ruta asignada"}, 400)

    if swarm is None:
        # Sin enjambre seguimos delegando en el backend, que en cloud es el
        # stub y responde que no hay dron.
        try:
            drone.dispatch(
                _build_mission(pname, rname), order_id=order_id,
                client_lat=order.get("client_latitude"),
                client_lon=order.get("client_longitude"),
                on_state=lambda status, op: store.update_order(
                    order_id, status=status, operational_state=op),
            )
        except Exception as e:
            return JSONResponse({"error": str(e)}, 400)
        store.update_order(order_id, status="en_reparto", operational_state="iniciando")
        return {"success": True, "backend": drone.name}

    drone_id = swarm.dispatch_order(order, orders_store)
    if drone_id is None:
        return JSONResponse({"error": "No hay ningún dron libre que pueda con el pedido"}, 409)
    return {"success": True, "backend": _BACKEND, "drone_id": drone_id}


@app.post("/api/admin/drone/{action}")
def admin_drone_control(action: str, _: str = Depends(require_admin)):
    """Controles de seguridad sobre toda la flota: cancel | rtl | hold | land."""
    if action not in ("cancel", "rtl", "hold", "land"):
        return JSONResponse({"error": "Acción no válida"}, 400)
    if swarm is not None:
        swarm.control_all(action)
        return {"success": True}
    fn = {"cancel": drone.cancel, "rtl": drone.rtl,
          "hold": drone.hold, "land": drone.land}[action]
    try:
        fn()
    except Exception as e:
        return JSONResponse({"error": str(e)}, 400)
    return {"success": True}


# ── Panel de administrador: enjambre ─────────────────────────────────────────

def _require_swarm():
    if swarm is None:
        raise HTTPException(
            status_code=400,
            detail="No hay enjambre disponible: arranca el portal con DRONE_BACKEND=sitl")
    return swarm


@app.get("/api/admin/swarm/fleet")
def admin_swarm_fleet(_: str = Depends(require_admin)):
    """Definición y estado vivo de cada dron.

    Con DRONE_BACKEND=sitl, get_backend() devuelve el stub —el enjambre no pasa
    por él—, así que el nombre del backend se reporta a partir de si hay
    enjambre, no de drone.name.
    """
    if swarm is None:
        return {"backend": drone.name, "drones": []}
    return {"backend": _BACKEND, "drones": swarm.fleet_status(),
            "scenario": swarm.scenario_status(),
            "auto_running": swarm.auto_running,
            "algorithm": swarm.algorithm,
            "source": _sitl_source() if _BACKEND == "sitl" else None,
            "sources": _available_sources(),
            "pasarela": pasarela.status() if pasarela is not None else None}


def _available_sources() -> list[str]:
    """Orígenes que tiene sentido ofrecer en el panel."""
    from airdrop.swarm import sitl_linux  # noqa: PLC0415

    if _BACKEND != "sitl":
        return []
    origenes = ["nube"] if sitl_linux.enabled() else []
    if pasarela is not None:
        origenes.append("puente")
    return origenes


@app.post("/api/admin/swarm/source")
def admin_set_source(payload: dict, _: str = Depends(require_admin)):
    """Cambia el origen de los drones (SITL en la nube o del PC por el puente)."""
    origen = (payload or {}).get("source")
    if origen not in _available_sources():
        return JSONResponse({"error": "Origen no disponible en este despliegue"}, 400)
    if swarm is not None and swarm.busy:
        return JSONResponse({"error": "Hay drones en vuelo; para los repartos antes"}, 409)
    store.set_setting(SITL_SOURCE_KEY, origen)
    _rebuild_swarm()
    return {"success": True, "source": origen}


@app.post("/api/admin/swarm/algorithm")
def admin_set_algorithm(payload: dict, _: str = Depends(require_admin)):
    """Elige el asignador: voraz u óptimo global por matriz de costes."""
    try:
        service = _require_swarm()
    except HTTPException as exc:
        return JSONResponse({"error": exc.detail}, exc.status_code)
    try:
        elegido = service.set_algorithm((payload or {}).get("algorithm", ""))
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, 400)
    except RuntimeError as exc:
        return JSONResponse({"error": str(exc)}, 409)
    return {"algorithm": elegido}


@app.post("/api/admin/swarm/start")
def admin_swarm_start(_: str = Depends(require_admin)):
    """Arranca el despacho autónomo hasta vaciar la cola.

    Antes se llamaba a ``start_deliveries``, que es **un solo** ciclo de
    planificación: con más pedidos que drones, la primera oleada salía y al
    volver a base nadie recogía el resto, así que había que pulsar el botón
    otra vez por cada tanda. El modo autónomo ya existía en el servicio y no
    lo usaba nadie.

    Se hace un ciclo síncrono primero para poder responder con lo que sale en
    esta oleada, y después queda el bucle replanificando cada
    ``planning_period_s`` según se liberan drones.
    """
    try:
        service = _require_swarm()
    except HTTPException as exc:
        return JSONResponse({"error": exc.detail}, exc.status_code)
    tienda = _OrdersStore(store)
    # Se calcula ANTES de despachar: después, los que salgan ya no están
    # pendientes y el aviso perdería la mitad de los casos.
    bloqueados = service.undispatchable(tienda)
    lanzados = service.plan_once(tienda)
    service.start_auto(tienda)
    return {"success": True, "dispatched": lanzados, "auto": True,
            "undispatchable": bloqueados}


@app.post("/api/admin/swarm/stop")
def admin_swarm_stop(_: str = Depends(require_admin)):
    """Aborta las entregas en curso y detiene el despacho autónomo.

    Para el bucle además de los ejecutores: si solo se abortasen las entregas,
    el planificador volvería a lanzarlas cinco segundos después y el botón de
    parada no pararía nada.
    """
    try:
        service = _require_swarm()
    except HTTPException as exc:
        return JSONResponse({"error": exc.detail}, exc.status_code)
    service.stop_auto()
    return {"success": True}


@app.post("/api/admin/swarm/drones/{drone_id}/{action}")
def admin_swarm_drone_control(drone_id: str, action: str, _: str = Depends(require_admin)):
    """Acción de seguridad sobre un dron: hold | rtl | land | cancel.

    La acción se valida antes de exigir enjambre, para que una acción
    inventada dé 400 con backend stub y no un mensaje sobre enjambres.
    """
    if action not in ("hold", "rtl", "land", "cancel"):
        return JSONResponse({"error": "Acción no válida"}, 400)
    try:
        service = _require_swarm()
    except HTTPException as exc:
        return JSONResponse({"error": exc.detail}, exc.status_code)
    try:
        service.control(drone_id, action)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, 400)
    return {"success": True}


@app.get("/api/swarm/telemetry")
def swarm_telemetry():
    """Posiciones de la flota para el mapa. Sin autenticación, como la del dron."""
    if swarm is None:
        return {"drones": []}
    return {"drones": [d["runtime"] for d in swarm.fleet_status()]}


# ── Panel de administrador: escenarios operacionales ─────────────────────────

@app.get("/api/admin/scenarios")
def admin_scenarios(_: str = Depends(require_admin)):
    """Escenarios con el parking ya resuelto contra su escenario de rutas.

    Se devuelven las coordenadas **efectivas**, las que va a usar el enjambre,
    y no las guardadas: enseñar unas y operar con otras es lo que hacía
    incomprensible el apartado. ``parking_options`` alimenta el selector y
    ``parking_mismatch`` avisa de los escenarios antiguos que todavía no
    referencian ningún parking.
    """
    from airdrop.swarm.scenario_link import (  # noqa: PLC0415
        parking_mismatch, parking_options,
    )

    profiles = store.get_profiles()

    # Un escenario de rutas debe tener UN juego de parámetros. Si hay varios
    # apuntando al mismo, quedarse con uno en silencio hace que el desplegable
    # enseñe unos valores y el enjambre opere con otros: se marcan como
    # duplicados para poder borrarlos.
    todos = scenarios_repo.list_scenarios()
    existentes, duplicados = {}, []
    for s in sorted(todos, key=lambda x: (not x.active, x.name)):
        if s.route_profile_name in existentes:
            duplicados.append(s)
        else:
            existentes[s.route_profile_name] = s

    salida = []
    for perfil in profiles.get("profiles", []):
        nombre = perfil.get("name")
        if not nombre:
            continue
        s = existentes.get(nombre)
        if s is None:
            # Un escenario de rutas recién creado no tiene todavía parámetros
            # operacionales. Se crean al vuelo con los valores por defecto y
            # enlazados a su primer parking, para que no haya que acordarse de
            # un segundo paso: son la misma cosa.
            opciones = parking_options(profiles, nombre)
            primero = next((p for p in perfil.get("parkings", [])), None)
            s = scenarios_repo.create_for_profile(
                nombre,
                parking_name=(opciones[0] if opciones else ""),
                parking_lat=float((primero or {}).get("lat") or 0.0),
                parking_lon=float((primero or {}).get("lon") or 0.0),
            )
        resuelto = _resolved_scenario(s)
        salida.append({
            **resuelto.as_dict(),
            "parking_options": parking_options(profiles, s.route_profile_name),
            "parking_mismatch": parking_mismatch(s, profiles),
        })

    # Parámetros huérfanos: su escenario de rutas ya no existe. Se enseñan
    # marcados para poder borrarlos, no se ocultan.
    nombres = {p.get("name") for p in profiles.get("profiles", [])}
    for s in todos:
        if s.route_profile_name not in nombres:
            salida.append({**s.as_dict(), "parking_options": [],
                           "parking_mismatch": None, "orphan": True})
    for s in duplicados:
        salida.append({**s.as_dict(), "parking_options": [],
                       "parking_mismatch": None, "duplicate": True})
    return {"scenarios": salida}


@app.delete("/api/admin/scenarios/{name}")
def admin_delete_scenario(name: str, _: str = Depends(require_admin)):
    """Borra los parámetros operacionales de un escenario."""
    if scenarios_repo.get(name) is None:
        return JSONResponse({"error": "Escenario no encontrado"}, 404)
    if swarm is not None and swarm.busy:
        return JSONResponse({"error": "Hay drones en vuelo; para los repartos antes"}, 409)
    scenarios_repo.delete(name)
    return {"success": True}


@app.put("/api/admin/scenarios/{name}")
def admin_update_scenario(name: str, payload: dict, _: str = Depends(require_admin)):
    """Edita los parámetros operativos y de seguridad de un escenario."""
    if scenarios_repo.get(name) is None:
        return JSONResponse({"error": "Escenario no encontrado"}, 404)
    actualizado = scenarios_repo.update(name, payload)

    # Enlazar un parking **mueve** el escenario a ese punto. Antes solo se
    # guardaba el nombre y las coordenadas viejas se quedaban ahí, así que el
    # panel avisaba de una discrepancia que él mismo acababa de crear y que no
    # había forma de resolver. Si manda el mapa, que mande del todo.
    if "parking_name" in (payload or {}):
        resuelto = _resolved_scenario(actualizado)
        if resuelto is not actualizado:
            actualizado = scenarios_repo.update(name, {
                "parking_lat": resuelto.parking_lat,
                "parking_lon": resuelto.parking_lon,
            })

    actualizado = _resolved_scenario(actualizado)
    if swarm is not None and actualizado.active:
        # El cambio se aplica al siguiente ciclo de planificación. Se propaga a
        # los tres, porque cada uno guarda su propia referencia al escenario.
        swarm.scenario = actualizado
        swarm.safety.scenario = actualizado
        swarm.airspace.scenario = actualizado
    return {"scenario": actualizado.as_dict()}


@app.post("/api/admin/scenarios/reset-defaults")
def admin_reset_scenarios(_: str = Depends(require_admin)):
    """Restaura los escenarios de rutas y los operacionales del repositorio.

    Ambos se guardan en la base de datos la primera vez que arranca el portal,
    así que un despliegue ya en marcha no ve los escenarios nuevos del
    repositorio hasta que se restauran. Se pierden los cambios hechos en el panel.
    """
    if swarm is not None and swarm.busy:
        return JSONResponse({"error": "Hay drones en vuelo; para los repartos antes"}, 409)
    store.reset_profiles()
    escenarios = scenarios_repo.reset_to_defaults()
    activo = _active_scenario()
    if swarm is not None and activo is not None:
        from airdrop.swarm.repository import FleetRepository  # noqa: PLC0415

        FleetRepository(store.engine).reseat(activo, desde_fichero=True)
        if _swarm_rebuildable():
            _rebuild_swarm()
    return {"scenarios": [s.name for s in escenarios],
            "restart_required": swarm is not None and not _swarm_rebuildable()}


@app.post("/api/admin/scenarios/{name}/activate")
def admin_activate_scenario(name: str, _: str = Depends(require_admin)):
    """Activa un escenario y recoloca la flota.

    Se rechaza con drones en vuelo: cambiar altitudes y separaciones a mitad
    de un reparto es justo lo que no debe poder hacerse desde un formulario.
    """
    if scenarios_repo.get(name) is None:
        return JSONResponse({"error": "Escenario no encontrado"}, 404)
    if swarm is not None and swarm.busy:
        return JSONResponse(
            {"error": "Hay drones en vuelo; para los repartos antes de cambiar"}, 409)
    activo = _resolved_scenario(scenarios_repo.activate(name))
    if swarm is not None:
        from airdrop.swarm.repository import FleetRepository  # noqa: PLC0415

        FleetRepository(store.engine).reseat(activo)
        if _swarm_rebuildable():
            # Los drones nacen en el portal: se rehacen en los pads nuevos.
            _rebuild_swarm()
    return {"scenario": activo.as_dict(),
            "restart_required": swarm is not None and not _swarm_rebuildable()}


@app.put("/api/admin/swarm/drones/{drone_id}/connection")
def admin_set_connection(drone_id: str, payload: dict, _: str = Depends(require_admin)):
    """Cambia el puerto MAVLink de un dron.

    Editable porque depende de cómo se levante la simulación: el `sitl.bat` de
    Mission Planner, el lanzador del proyecto o un dron real reparten los
    puertos de forma distinta.
    """
    from airdrop.swarm.repository import FleetRepository  # noqa: PLC0415

    conexion = str(payload.get("connection") or "").strip()
    if not conexion:
        return JSONResponse({"error": "Falta la cadena de conexión"}, 400)
    actualizado = FleetRepository(store.engine).update_connection(drone_id, conexion)
    if actualizado is None:
        return JSONResponse({"error": "Dron no encontrado"}, 404)
    return {"drone": actualizado.as_dict(), "restart_required": True}


@app.post("/api/admin/swarm/reseat")
def admin_reseat_fleet(_: str = Depends(require_admin)):
    """Recalcula puertos y pads de toda la flota desde el escenario activo.

    Hace falta porque la siembra no pisa lo que ya existe: una base de datos
    creada con puertos antiguos los conserva aunque cambie el valor por
    defecto, y el síntoma es una flota entera sin conectar.
    """
    from airdrop.swarm.repository import FleetRepository  # noqa: PLC0415

    if swarm is not None and swarm.busy:
        return JSONResponse(
            {"error": "Hay drones en vuelo; para los repartos antes"}, 409)
    flota = FleetRepository(store.engine).reseat(_active_scenario())
    return {"drones": [d.as_dict() for d in flota], "restart_required": True}


@app.post("/api/admin/swarm/probe")
def admin_probe_fleet(_: str = Depends(require_admin)):
    """Estado del enlace de cada dron, sin lanzar nada.

    Un dron que el portal ya tiene conectado **no se sondea**: se informa de su
    enlace vivo. SITL admite un solo cliente por puerto, así que abrir un
    segundo socket contra un puerto que el propio portal ocupa falla siempre, y
    el panel lo mostraba como «puerto cerrado» teniendo el enlace perfectamente
    sano. Es un falso negativo que costó una mañana: los cuatro drones
    aparecían caídos mientras sus logs decían ``New connection on SERIAL1`` sin
    cerrar.

    Para los que no tiene conectados sí se sondea: conexión efímera, heartbeat
    y cierre. Eso es lo que valida los puertos antes de arrancar repartos.
    """
    from airdrop.swarm.probe import probe  # noqa: PLC0415
    from airdrop.swarm.repository import FleetRepository  # noqa: PLC0415

    enlaces = getattr(swarm, "_links", {}) if swarm is not None else {}
    resultados = []
    for d in FleetRepository(store.engine).list_drones(only_enabled=False):
        enlace = enlaces.get(d.drone_id)
        if enlace is not None and enlace.is_connected:
            edad = enlace.telemetry_age_s()
            resultados.append({
                "drone_id": d.drone_id,
                "connection": d.connection,
                "ok": True,
                "sysid": d.sysid,
                "error": None,
                "position": (enlace.telemetry() or {}).get("position"),
                "source": "enlace del portal",
                "telemetry_age_s": edad,
            })
            continue
        resultados.append({"drone_id": d.drone_id, **probe(d.connection),
                           "source": "sonda"})
    return {"results": resultados}


@app.post("/api/admin/swarm/scan")
def admin_scan_ports(_: str = Depends(require_admin)):
    """Busca autopilotos escuchando en el rango habitual de SITL."""
    from airdrop.swarm.probe import scan  # noqa: PLC0415

    return {"found": scan()}


@app.get("/api/admin/swarm/metrics")
def admin_swarm_metrics(_: str = Depends(require_admin)):
    """Entregas medidas y resumen por algoritmo."""
    try:
        service = _require_swarm()
    except HTTPException as exc:
        return JSONResponse({"error": exc.detail}, exc.status_code)
    return {"summary": service.metrics.summary(),
            "records": service.metrics.all()}


@app.get("/api/admin/swarm/metrics.csv")
def admin_swarm_metrics_csv(_: str = Depends(require_admin)):
    """Las mismas métricas en CSV, para llevarlas a la memoria."""
    from fastapi.responses import Response  # noqa: PLC0415

    try:
        service = _require_swarm()
    except HTTPException as exc:
        return JSONResponse({"error": exc.detail}, exc.status_code)
    return Response(
        service.metrics.to_csv(), media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=airdrop-metrics.csv"})


@app.post("/api/admin/swarm/metrics/clear")
def admin_swarm_metrics_clear(_: str = Depends(require_admin)):
    """Vacía el registro, para empezar una comparativa limpia."""
    try:
        service = _require_swarm()
    except HTTPException as exc:
        return JSONResponse({"error": exc.detail}, exc.status_code)
    service.metrics.clear()
    return {"success": True}


@app.get("/api/admin/swarm/events")
def admin_swarm_events(_: str = Depends(require_admin)):
    """Bitácora de eventos de seguridad y deconflicción."""
    if swarm is None:
        return {"events": []}
    return {"events": swarm.safety_events()}


@app.post("/api/admin/demo/{preset}")
def admin_demo_seed(preset: str, semilla: int | None = None,
                    _: str = Depends(require_admin)):
    """Siembra un escenario de pedidos de demostración (lo mismo que
    ``python -m airdrop.demo seed``), para enseñar el enjambre desde el panel
    del portal desplegado sin dar de alta clientes a mano."""
    from airdrop import demo  # noqa: PLC0415
    if preset == "clear":
        demo.clear()
        return {"success": True}
    try:
        demo.seed(preset, semilla)
        return {"success": True}
    except SystemExit as exc:
        return JSONResponse({"error": str(exc)}, 400)


@app.get("/api/admin/clients")
def admin_clients(_: str = Depends(require_admin)):
    return {"clients": store.list_clients()}


@app.put("/api/admin/clients/{client_id}")
def admin_update_client(client_id: int, data: AccountUpdate, _: str = Depends(require_admin)):
    """El admin edita nombre/dirección de cualquier cuenta."""
    if not store.get_client(client_id):
        return JSONResponse({"error": "Cliente no encontrado"}, 404)
    client = _apply_account_update(client_id, data.name, data.address)
    return {"client": client}


@app.get("/api/admin/fleet")
def admin_fleet(_: str = Depends(require_admin)):
    """Flota de referencia: categorías de dron y composición por defecto.

    Es informativa: la flota real se controla desde la app de escritorio (SITL);
    aquí se expone la configuración del modelo de simulación.
    """
    categories = {
        name: {
            "max_payload_kg": spec.max_payload_kg,
            "battery_capacity_wh": spec.battery_capacity_wh,
            "cruise_speed_mps": spec.cruise_speed_mps,
        }
        for name, spec in DRONE_CATEGORIES.items()
    }
    fleet = [{"id": drone_id, "category": cat} for cat, drone_id in DEFAULT_FLEET_DISTRIBUTION]
    return {"categories": categories, "fleet": fleet}


# ── Consola de simulación ────────────────────────────────────────────────────
# La misma herramienta que «python -m simtools», detrás del login de
# administrador: en la nube es la única forma de cambiar la flota y el SITL.

def _sim_banco():
    from simtools import sim  # noqa: PLC0415

    return sim.Banco(store.engine.url.render_as_string(hide_password=False))


def _sim_embedded_status():
    from airdrop.swarm.repository import FleetRepository  # noqa: PLC0415

    if _SITL is None:
        return []
    return _SITL.instances(FleetRepository(store.engine).list_drones(only_enabled=False))


def _sim_embedded() -> bool:
    from airdrop.swarm import sitl_linux  # noqa: PLC0415

    return sitl_linux.enabled()


def _sim_remove_drone(drone_id: str) -> None:
    """Para la instancia embebida de un dron y lo saca del enjambre."""
    if _SITL is not None:
        _SITL.stop_one(drone_id)
    if swarm is not None:
        swarm.remove_drone(drone_id)


sim_admin.hooks = sim_admin.Hooks(
    banco=_sim_banco,
    store=store,
    backend=lambda: _BACKEND,
    embedded=_sim_embedded,
    busy=lambda: swarm is not None and swarm.busy,
    rebuild=lambda: _rebuild_swarm(),
    embedded_status=_sim_embedded_status,
    stop_embedded=lambda: _SITL.stop() if _SITL is not None else None,
    remove_drone=_sim_remove_drone,
)
app.include_router(sim_admin.build_router(require_admin))

_SIM_WEB = Path(__file__).resolve().parents[2] / "simtools" / "web"


@app.get("/simulacion")
def sim_console_redirect():
    return RedirectResponse("/simulacion/")


@app.get("/simulacion/")
def sim_console():
    return FileResponse(_SIM_WEB / "console.html")


app.mount("/simulacion/static", StaticFiles(directory=str(_SIM_WEB)), name="simulacion")
app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="portal")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
