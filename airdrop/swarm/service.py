"""Orquestador del enjambre.

Posee la flota: un ``DroneLink`` por dron y un ``DeliveryExecutor`` por entrega
en curso, cada uno en su propio hilo. Es lo único que la API necesita conocer
del subsistema.

El estado vivo se mantiene aquí, en memoria, y no se persiste. Lo único que se
escribe en la base de datos es el avance del pedido, a través del almacén que
se le pasa a ``start_deliveries``.

``link_factory`` y ``build_mission`` se inyectan para que los tests puedan usar
``FakeDroneLink`` y una misión fija sin levantar SITL ni tocar perfiles.
"""

from __future__ import annotations

import logging
import threading
import time

from airdrop.swarm.airspace import AirspaceManager
from airdrop.swarm.executor import CONTROL_PERIOD_S, DeliveryExecutor
from airdrop.swarm.models import ARMING, IDLE, OFFLINE, DroneRuntime
from airdrop.swarm.metrics import MetricsRegistry
from airdrop.swarm.planner import ALGORITHMS, GREEDY, plan_assignments
from airdrop.swarm.safety import SafetyPolicy

log = logging.getLogger(__name__)

PLANNING_PERIOD_S = 5.0

# Separacion a la salida entre dos drones de la misma oleada que van al mismo
# punto de entrega, si el escenario no fija otra (``delivery_stagger_s``).
DELIVERY_STAGGER_S = 30.0


def _destino_key(order) -> str:
    """Identifica el punto de entrega de un pedido.

    Se agrupa por coordenadas redondeadas -unos pocos metros- y no por id de
    cliente: dos clientes distintos del mismo portal comparten punto de
    aterrizaje y se estorban exactamente igual.
    """
    lat, lon = order.get("client_latitude"), order.get("client_longitude")
    if lat is None or lon is None:
        return f"pedido:{order.get('id')}"
    return f"{float(lat):.4f},{float(lon):.4f}"


class SwarmService:
    def __init__(self, scenario, repository, link_factory, build_mission,
                 planning_period_s=PLANNING_PERIOD_S,
                 control_period_s=CONTROL_PERIOD_S):
        self.scenario = scenario
        self.repository = repository
        self.link_factory = link_factory
        self.build_mission = build_mission
        self.planning_period_s = planning_period_s
        self.control_period_s = control_period_s

        self._records = [r for r in repository.seed_if_empty(scenario) if r.enabled]
        self._runtimes = {
            r.drone_id: DroneRuntime(
                drone_id=r.drone_id,
                battery_capacity_wh=r.spec.battery_capacity_wh,
            )
            for r in self._records
        }
        self.airspace = AirspaceManager(scenario, slot_count=len(self._records))
        self.safety = SafetyPolicy(scenario)

        self._links = {}
        self._executors = {}
        self._threads = {}
        self._lock = threading.RLock()
        self._auto_thread = None
        self._auto_stop = threading.Event()

        # Asignador en uso. Vive en el servicio y no en el escenario porque es
        # una decisión de operación —qué algoritmo demuestro ahora mismo— y no
        # un parámetro del emplazamiento. Se pierde al reiniciar el portal, que
        # para el caso es lo correcto: se vuelve al voraz validado.
        self.algorithm = GREEDY

        # Métricas de operación: permiten comparar los dos asignadores sobre
        # el enjambre real, con las esperas de coordinación incluidas.
        self.metrics = MetricsRegistry()

    # ── Conexión ─────────────────────────────────────────────────────────
    def connect_all(self, block: bool = True, timeout: float = 30.0) -> None:
        """Conecta con cada autopiloto, en paralelo. Los que fallen quedan ``offline``.

        Un dron por hilo, por dos motivos. Primero, ``dron.connect()`` espera un
        heartbeat y puede tardar o no llegar nunca: en serie, un autopiloto
        mudo impide conectar con los demás. Segundo, el portal lo llama al
        arrancar, así que en serie un dron colgado dejaría a uvicorn sin
        levantar y el portal entero caído por un dron.

        Con ``block=False`` la conexión sigue en segundo plano y los drones van
        apareciendo conectados según responden.
        """
        hilos = [
            threading.Thread(target=self._connect_one, args=(record,),
                             name=f"connect-{record.drone_id}", daemon=True)
            for record in self._records
        ]
        for hilo in hilos:
            hilo.start()
        if not block:
            return
        for hilo in hilos:
            hilo.join(timeout=timeout)

    def _connect_one(self, record) -> None:
        """Conecta un dron. El motivo del fallo se conserva y se registra:
        tragárselo deja un dron en offline sin ninguna pista de por qué."""
        runtime = self._runtimes[record.drone_id]
        try:
            link = self.link_factory(record)
            link.connect()
        except Exception as exc:  # noqa: BLE001
            runtime.state = OFFLINE
            runtime.detail = f"sin conexión ({record.connection}): {exc}"
            log.warning("%s: no se pudo conectar a %s: %s",
                        record.drone_id, record.connection, exc)
            return
        with self._lock:
            self._links[record.drone_id] = link
        runtime.state = IDLE
        runtime.detail = "en parking"
        log.info("%s conectado por MAVLink a %s", record.drone_id, record.connection)
        runtime.battery_wh = record.spec.battery_capacity_wh
        runtime.lat, runtime.lon = record.home_lat, record.home_lon
        runtime.alt = 0.0

    def reconnect(self, drone_id: str) -> bool:
        """Vuelve a conectar un dron que no está volando.

        Lo usa el puente: cuando el PC del laboratorio conecta un dron, el
        enlace que falló al arrancar el portal se reintenta sin reiniciarlo.
        """
        record = next((r for r in self._records if r.drone_id == drone_id), None)
        if record is None:
            return False
        with self._lock:
            hilo = self._threads.get(drone_id)
            if hilo is not None and hilo.is_alive():
                return False
            viejo = self._links.pop(drone_id, None)
        if viejo is not None:
            try:
                viejo.close()
            except Exception:  # noqa: BLE001
                pass
        self._connect_one(record)
        return drone_id in self._links

    def remove_drone(self, drone_id: str) -> bool:
        """Saca un dron del enjambre sin tocar a los demás.

        Los otros conservan su enlace abierto: rehacer el enjambre entero
        obligaría a reconectar con autopilotos que siguen en marcha. Un dron
        con una misión en curso no se quita.
        """
        with self._lock:
            hilo = self._threads.get(drone_id)
            if hilo is not None and hilo.is_alive():
                return False
            antes = len(self._records)
            self._records = [r for r in self._records if r.drone_id != drone_id]
            if len(self._records) == antes:
                return False
            self._runtimes.pop(drone_id, None)
            self._executors.pop(drone_id, None)
            self._threads.pop(drone_id, None)
            link = self._links.pop(drone_id, None)
            self.airspace.release_slot(drone_id)
            self.airspace._slot_count = len(self._records)
        if link is not None:
            try:
                link.close()
            except Exception:  # noqa: BLE001
                pass
        return True

    def close_all(self) -> None:
        for link in self._links.values():
            try:
                link.close()
            except Exception:  # noqa: BLE001
                pass
        self._links.clear()

    # ── Estado ───────────────────────────────────────────────────────────
    def fleet_status(self) -> list[dict]:
        return [
            {"record": r.as_dict(), "runtime": self._runtimes[r.drone_id].as_dict()}
            for r in self._records
        ]

    def undispatchable(self, orders_store) -> list[dict]:
        """Pedidos pendientes que **ningún** dron va a poder llevar nunca.

        Se distingue de «ahora mismo no hay dron libre»: esto son los que
        fallan por una razón permanente —fuera de la geovalla, por encima de
        la carga máxima de la flota, sin ruta asignable—. Sin este aviso se
        quedan en la cola en silencio y desde fuera parece que el enjambre ha
        dejado de repartir, que es justo lo que pasó con pedidos de 5, 7 y
        8 kg y una flota cuyo tope son 4 kg.

        La comprobación se hace contra una flota **ideal**: se pregunta si
        alguno de los drones podría con él suponiéndolos cargados al máximo.
        Un pedido que ni así entra, no entra nunca.
        """
        from dataclasses import replace  # noqa: PLC0415

        problemas = []
        for order in orders_store.list_pending():
            motivos = set()
            for record in self._records:
                runtime = self._runtimes[record.drone_id]
                ideal = replace(runtime, state=IDLE,
                                battery_wh=record.spec.battery_capacity_wh)
                permitido, motivo = self.safety.can_dispatch(record, ideal, order)
                if permitido:
                    motivos.clear()
                    break
                motivos.add(motivo)
            if motivos:
                problemas.append({
                    "order_id": order.get("id"),
                    "weight_kg": order.get("weight_kg"),
                    # Si todos los drones dan el mismo motivo, ese es el
                    # motivo; si difieren, se enseñan todos.
                    "reason": " / ".join(sorted(motivos)),
                })
        return problemas

    def set_algorithm(self, algorithm: str) -> str:
        """Cambia el asignador. Rechaza los desconocidos.

        No se permite a mitad de una oleada: cambiar de criterio con drones ya
        despachados mezclaría dos asignaciones y haría incomparable lo que se
        está observando, que es justo lo que se quiere medir.
        """
        if algorithm not in ALGORITHMS:
            raise ValueError(f"Algoritmo no válido: {algorithm}")
        if self.busy:
            raise RuntimeError("Hay drones en vuelo; para los repartos antes")
        # Se comprueba aquí y no en el primer ciclo de planificación: la
        # matriz de costes arrastra scipy, y descubrir que falta en mitad de
        # un despacho dejaría pedidos asignados sin nadie que los lleve.
        from airdrop.swarm.planner import _assigner  # noqa: PLC0415
        try:
            _assigner(algorithm)
        except ImportError as exc:
            raise ValueError(f"Asignador no disponible: {exc}") from exc
        self.algorithm = algorithm
        return self.algorithm

    def scenario_status(self) -> dict:
        return {**self.scenario.as_dict(),
                "slots": self.scenario.slot_altitudes(len(self._records)),
                "hub_holder": self.airspace.hub_holder(),
                "hub_holders": self.airspace.hub_holders(),
                "hub_queue": self.airspace.hub_queue()}

    def safety_events(self) -> list[dict]:
        return self.safety.events()

    def runtime(self, drone_id):
        return self._runtimes.get(drone_id)

    @property
    def busy(self) -> bool:
        return any(t.is_alive() for t in self._threads.values())

    def wait_idle(self, timeout: float = 60.0) -> bool:
        """Espera a que terminen todas las entregas. Para tests y para `stop`."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if not self.busy:
                return True
            time.sleep(0.05)
        return False

    # ── Repartos ─────────────────────────────────────────────────────────
    def plan_once(self, orders_store) -> list[dict]:
        """Un ciclo de planificación: asigna y lanza lo que se pueda."""
        with self._lock:
            pendientes = orders_store.list_pending()
            plan = plan_assignments(self._records, self._runtimes, pendientes,
                                    self.scenario, self.algorithm)
            lanzados = []
            # Cuando en la misma oleada salen varios pedidos hacia el mismo
            # punto de entrega, se escalonan a la salida. Separarlos en el
            # tiempo desde el principio sale mucho mas barato que resolver el
            # encuentro sobre el cliente, donde el segundo tendria que esperar
            # en el aire a que el primero entregue y despegue.
            #
            # Es la primera linea; la reserva de la vertical del cliente es la
            # segunda, por si aun asi coinciden -por ejemplo si una entrega se
            # alarga mas que el escalonado.
            por_destino: dict[str, int] = {}
            for asignacion in plan:
                record = next(r for r in self._records
                              if r.drone_id == asignacion.drone_id)
                runtime = self._runtimes[record.drone_id]
                permitido, motivo = self.safety.can_dispatch(
                    record, runtime, asignacion.order)
                if not permitido:
                    self.safety.record_event(record.drone_id, "rechazo", motivo)
                    continue

                clave = _destino_key(asignacion.order)
                orden = por_destino.get(clave, 0)
                por_destino[clave] = orden + 1
                retardo = orden * self._delivery_stagger_s()
                if retardo:
                    self.safety.record_event(
                        record.drone_id, "escalonado_destino",
                        f"otro dron va al mismo punto; salida retrasada "
                        f"{retardo:.0f} s")

                if self._launch(record, asignacion.order, orders_store,
                                extra_delay_s=retardo):
                    lanzados.append({"drone_id": record.drone_id,
                                     "order_id": asignacion.order["id"]})
            return lanzados

    # Nombre conservado por compatibilidad con el endpoint de B1.
    def start_deliveries(self, orders_store) -> list[dict]:
        return self.plan_once(orders_store)

    def start_auto(self, orders_store) -> None:
        """Arranca el modo autónomo: replanifica hasta vaciar la cola.

        Un despacho único deja pedidos colgados cuando hay más que drones. El
        bucle vuelve a mirar cada ``planning_period_s`` y va asignando según
        se liberan drones, que es lo que hace el enjambre autónomo de verdad.
        """
        if self.auto_running:
            return
        self._auto_stop.clear()
        self._auto_thread = threading.Thread(
            target=self._auto_loop, args=(orders_store,),
            name="swarm-planner", daemon=True)
        self._auto_thread.start()

    def stop_auto(self) -> None:
        self._auto_stop.set()
        # Se espera a que el planificador acabe el ciclo en curso: si no, puede
        # lanzar una entrega justo después de stop_all y dejarla volando.
        hilo = self._auto_thread
        if hilo is not None and hilo is not threading.current_thread():
            hilo.join(timeout=5)
        self.stop_all()

    @property
    def auto_running(self) -> bool:
        return self._auto_thread is not None and self._auto_thread.is_alive()

    def _auto_loop(self, orders_store) -> None:
        while not self._auto_stop.is_set():
            try:
                self.plan_once(orders_store)
            except Exception:  # noqa: BLE001
                log.exception("fallo en el ciclo de planificación")
            self._auto_stop.wait(self.planning_period_s)

    def dispatch_order(self, order, orders_store):
        """Despacha un pedido concreto al mejor dron libre que pueda con él."""
        with self._lock:
            plan = plan_assignments(self._records, self._runtimes, [order],
                                    self.scenario, self.algorithm)
            if not plan:
                return None
            record = next(r for r in self._records if r.drone_id == plan[0].drone_id)
            permitido, _motivo = self.safety.can_dispatch(
                record, self._runtimes[record.drone_id], order)
            if not permitido or not self._launch(record, order, orders_store):
                return None
            return record.drone_id

    def _delivery_stagger_s(self) -> float:
        """Escalonado por destino del escenario activo; se lee en cada oleada
        porque el escenario se edita en caliente desde el panel."""
        valor = getattr(self.scenario, "delivery_stagger_s", DELIVERY_STAGGER_S)
        return max(0.0, float(DELIVERY_STAGGER_S if valor is None else valor))

    def _launch(self, record, order, orders_store, extra_delay_s=0.0) -> bool:
        link = self._links.get(record.drone_id)
        if link is None:
            return False
        try:
            mission = self.build_mission(
                order.get("assigned_profile_name"), order.get("assigned_route_name"),
            )
        except Exception:  # noqa: BLE001
            return False

        runtime = self._runtimes[record.drone_id]
        order_id = order["id"]

        # Marcar el dron ocupado AQUI, no en el hilo del ejecutor. Entre que
        # arranca el hilo y este llega a cambiar el estado pasan milisegundos,
        # y el siguiente ciclo de planificacion veria el dron todavia idle y
        # le daria un segundo pedido, que se perderia. Es una carrera real,
        # observada contra SITL: pedidos en "asignado" sin nadie que los lleve.
        runtime.state = ARMING
        runtime.detail = "preparando despegue"
        runtime.current_order_id = order_id

        orders_store.update(order_id, status="asignado",
                            operational_state="asignado",
                            assigned_drone_id=record.drone_id)

        executor = DeliveryExecutor(
            record=record, runtime=runtime, link=link,
            extra_delay_s=extra_delay_s,
            scenario=self.scenario, airspace=self.airspace, safety=self.safety,
            fleet_runtimes=self._runtimes,
            control_period_s=self.control_period_s,
            on_order_state=lambda status, detail, oid=order_id: orders_store.update(
                oid, status=status, operational_state=detail),
        )
        # El algoritmo se captura AHORA, no al terminar: para cuando aterrice
        # el dron puede haberse cambiado el selector, y la entrega quedaría
        # atribuida al asignador que no la decidió.
        algoritmo = self.algorithm
        executor.on_finished = lambda datos: self.metrics.record(
            algorithm=algoritmo, **datos)
        self._executors[record.drone_id] = executor

        thread = threading.Thread(
            target=executor.run, args=(order, mission),
            name=f"delivery-{record.drone_id}-{order_id}", daemon=True,
        )
        self._threads[record.drone_id] = thread
        thread.start()
        return True

    # ── Controles ────────────────────────────────────────────────────────
    def stop_all(self) -> None:
        for executor in self._executors.values():
            executor.cancel()

    def control(self, drone_id: str, action: str) -> None:
        """Acción de seguridad sobre un dron: hold | rtl | land | cancel."""
        # BRAKE y no LOITER: LOITER sigue a la emisora y sin ella baja (link.hold).
        modes = {"hold": "BRAKE", "rtl": "RTL", "land": "LAND", "cancel": "BRAKE"}
        if action not in modes:
            raise ValueError(f"Acción no válida: {action}")
        link = self._links.get(drone_id)
        if link is None:
            raise ValueError(f"Dron no conectado: {drone_id}")
        executor = self._executors.get(drone_id)
        if executor is not None:
            executor.cancel()
        link.abort(modes[action])

    def control_all(self, action: str) -> None:
        for drone_id in list(self._links):
            try:
                self.control(drone_id, action)
            except ValueError:
                continue
