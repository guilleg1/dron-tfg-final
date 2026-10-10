"""Ejecución de una entrega sobre un dron.

A diferencia de B1, el ejecutor no se queda bloqueado dentro de dronLink
durante cada tramo: ordena el desplazamiento y entra en un bucle que comprueba
llegada, cancelación, conflictos de espacio aéreo y seguridad cada
``control_period_s``. Ese latido es lo que hace posible mantener posición por
un HUB ocupado o abortar por batería a mitad de tramo.

El ejecutor no sabe de MAVLink: habla con un ``DroneLink``. Por eso la
secuencia completa, incluidas las esperas y los abortos, se prueba con
``FakeDroneLink``.
"""

from __future__ import annotations

import logging
import time

from airdrop.swarm.airspace import ATERRIZAJE
from airdrop.swarm.models import (
    DELIVERING, ERROR, IDLE, IN_TRANSIT, LANDING, RETURNING, TAKING_OFF,
)
from airdrop.swarm.safety import LINK_LOST, RTL
from core.energy import estimate_trip_energy_wh
from core.geo import haversine_km, offset_position

log = logging.getLogger(__name__)

CONTROL_PERIOD_S = 0.5
LEG_TIMEOUT_S = 300.0
# Trozo máximo de cada espera, para atender una cancelación sin retraso.
SLEEP_SLICE_S = 0.1

# Cuanto se retrocede sobre la ruta para esperar turno de entrega. Lo bastante
# para dejar despejada la vertical del que esta abajo y que pueda despegar.
HOLD_BACK_M = 20.0

# Cada cuánto se reenvía el destino del tramo en curso.
#
# Un `goto` en GUIDED es idempotente, y reenviarlo cubre los comandos que se
# pierden: sobre todo justo después de un `resume()`, cuando el autopiloto
# todavía está cambiando de BRAKE a GUIDED y descarta la orden. Sin esto el
# dron se queda flotando indefinidamente y el tramo agota su tiempo, lo que
# además bloquea el HUB si lo tenía reservado. Observado contra SITL.
GOTO_REFRESH_S = 5.0

# Cuánto puede un dron retener el HUB antes de que se le fuerce a soltarlo.
# Muy por debajo de LEG_TIMEOUT_S: si un dron se atasca, el resto de la flota
# no puede quedarse esperándolo cinco minutos.
HUB_HOLD_TIMEOUT_S = 90.0

# En el regreso, el HUB se pide a esta distancia de él y no al empezar el
# último tramo. Si se pidiera al salir del destino, el dron retendría el HUB
# durante todo el camino de vuelta (cientos de metros) y el resto de la flota
# esperaría sin motivo: la zona que hay que proteger es la de confluencia.
HUB_APPROACH_M = 60.0

# Conservado por compatibilidad: la pausa real la fija el escenario.
DELIVERY_PAUSE_S = 10.0


class _Cancelled(Exception):
    """Señal interna de cancelación."""


class _Aborted(Exception):
    """Aborto por seguridad: el pedido vuelve a la cola."""

    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


class _LinkLost(Exception):
    """Se perdió la telemetría: el dron es inalcanzable."""

    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


class DeliveryExecutor:
    """Vuela un pedido con un dron. Un ejecutor por entrega, no se reutiliza."""

    def __init__(self, record, runtime, link, scenario, airspace, safety,
                 on_order_state=None, fleet_runtimes=None,
                 control_period_s=CONTROL_PERIOD_S, extra_delay_s=0.0):
        self.record = record
        self.runtime = runtime
        self.link = link
        self.scenario = scenario
        self.airspace = airspace
        self.safety = safety
        self.on_order_state = on_order_state or (lambda status, detail: None)
        # Se invoca al terminar, pase lo que pase, con el desenlace. Lo pone
        # el servicio, que es quien sabe con qué algoritmo se asignó.
        self.on_finished = None
        self.fleet_runtimes = fleet_runtimes if fleet_runtimes is not None else {}
        self.control_period_s = control_period_s
        self.last_energy_wh = 0.0
        self._cancelled = False
        # Tiempo perdido sin avanzar: esperas de HUB, escalonado y cesiones
        # por separación. Se contabiliza aparte del tiempo de vuelo porque es
        # el coste que introduce la coordinación, y es lo que distingue medir
        # el algoritmo de medir el sistema.
        self.wait_s = 0.0
        # Retardo adicional a la salida, ademas del escalonado por tandas del
        # vertipuerto. Lo pone el servicio cuando otro dron de la misma oleada
        # va al mismo punto de entrega.
        self.extra_delay_s = float(extra_delay_s or 0.0)

    def cancel(self) -> None:
        self._cancelled = True

    # ── Ciclo de la entrega ──────────────────────────────────────────────
    def run(self, order, mission) -> None:
        order_id = order["id"]
        waypoints = mission.get("waypoints", [])
        if len(waypoints) < 2:
            self._fail(order_id, "ruta sin waypoints suficientes")
            return

        alt = self.airspace.reserve_slot(self.record.drone_id)
        if alt is None:
            self.safety.record_event(self.record.drone_id, "sin_slot",
                                     "no queda capa de altitud libre")
            # El pedido vuelve a la cola. El servicio ya lo marcó "asignado"
            # antes de lanzarnos; si no lo devolviéramos, se quedaría ahí para
            # siempre, fuera de la cola y sin que nadie lo entregue.
            self.on_order_state("pendiente", "sin slot de altitud")
            return
        self.runtime.cruise_alt_m = alt
        self.runtime.current_order_id = order_id

        inicio = time.time()
        # Si algo revienta antes de llegar al try, el desenlace sigue siendo
        # informativo en vez de quedar sin definir.
        desenlace = "error"

        # Despegue y aterrizaje bloquean fuera del bucle de control, así que
        # el enlace avisa desde dentro para que la altitud del panel no salte
        # de 0 a la de crucero de golpe.
        self.link.on_progress = self._sync_position

        # La velocidad del escenario de rutas se enviaba en la misión y no la
        # aplicaba nadie: se volaba al WPNAV_SPEED por defecto (10 m/s) dijera
        # lo que dijera el formulario.
        velocidad = mission.get("speed")
        if velocidad and hasattr(self.link, "set_speed"):
            try:
                self.link.set_speed(float(velocidad))
            except Exception:  # noqa: BLE001
                log.warning("%s: no se pudo fijar la velocidad", self.record.drone_id)

        # waypoints[0] es el parking. La ruta operativa empieza en el HUB y
        # termina en el destino; el regreso la recorre al reves.
        ruta = waypoints[1:]

        try:
            retardo = self.airspace.takeoff_delay_s(
                self.record.drone_id, self.record.home_lat, self.record.home_lon)
            retardo += self.extra_delay_s
            if retardo > 0:
                self.safety.record_event(self.record.drone_id, "escalonado",
                                         f"despegue retrasado {retardo:.0f} s")
                self._sleep(retardo)

            self._check()
            # Subir de 0 a la capa de crucero atraviesa todos los niveles
            # inferiores: durante la maniobra no hay separación vertical que
            # valga. Se exige tener la vertical del parking para uno solo.
            self._enter_pad("despegar")
            self._progress(order_id, "en_reparto", "despegando", TAKING_OFF)
            self.link.arm_and_takeoff(alt)
            self.airspace.release_pad(self.record.drone_id)

            self._enter_hub()
            for index, wp in enumerate(ruta):
                detalle = "en ruta (hub)" if index == 0 else "en ruta"
                self._progress(order_id, "en_reparto", detalle, IN_TRANSIT)
                self._fly_to(float(wp["lat"]), float(wp["lon"]), alt)
                if index == 0:
                    self.airspace.release_hub(self.record.drone_id)

            client_lat = order.get("client_latitude")
            client_lon = order.get("client_longitude")
            if client_lat is None or client_lon is None:
                raise ValueError("el cliente no tiene coordenadas")

            # La vertical del cliente se reserva igual que la del pad: bajar
            # sobre el punto de entrega atraviesa todos los niveles y anula la
            # separacion por capas. Se pide ANTES de acercarse, para poder
            # esperar sobre la ruta en vez de encima del que ya esta abajo.
            cli_lat, cli_lon = float(client_lat), float(client_lon)
            if not self.airspace.acquire_pad(self.record.drone_id, cli_lat,
                                             cli_lon, ATERRIZAJE):
                espera = self._punto_de_espera(ruta, cli_lat, cli_lon)
                self._progress(order_id, "en_reparto",
                               "esperando turno de entrega", IN_TRANSIT)
                self.safety.record_event(
                    self.record.drone_id, "espera_entrega",
                    "otro dron en el punto de entrega; espera sobre la ruta")
                self._fly_to(espera[0], espera[1], alt)
                self._wait_for_pad(cli_lat, cli_lon)

            self._progress(order_id, "en_reparto", "yendo a cliente", IN_TRANSIT)
            self._fly_to(cli_lat, cli_lon, alt)

            self._progress(order_id, "en_reparto", "aterrizando en cliente", LANDING)
            self.link.land()

            self._progress(order_id, "en_reparto", "entregando", DELIVERING)
            self._sleep(self.scenario.delivery_pause_s)

            self._check()
            self._progress(order_id, "en_reparto", "despegando para volver", RETURNING)

            # Regreso por la ruta de ida al reves, no en linea recta. Volver
            # campo a traves ignora que el corredor esta aprobado y que fuera
            # de el no hay garantia de obstaculos ni de sobrevuelo permitido.
            alt_vuelta = self.airspace.return_altitude(self.record.drone_id) or alt
            if alt_vuelta != alt:
                self.safety.record_event(
                    self.record.drone_id, "nivel_retorno",
                    f"regreso por la ruta de ida a {alt_vuelta:.0f} m "
                    f"(ida a {alt:.0f} m)")
            else:
                self.safety.record_event(
                    self.record.drone_id, "nivel_retorno",
                    f"sin bloque de vuelta bajo el techo; regreso a {alt:.0f} m")

            self.link.arm_and_takeoff(alt_vuelta)
            self.runtime.cruise_alt_m = alt_vuelta
            # Ya esta en su nivel: la vertical del cliente queda libre para el
            # siguiente. Antes de subir seguia ocupandola.
            self.airspace.release_pad(self.record.drone_id)

            # El HUB es ahora el ULTIMO punto antes del parking, no el
            # primero: pedirlo al empezar el regreso lo retendria durante todo
            # el camino de vuelta y bloquearia a la flota sin necesidad.
            regreso = list(reversed(ruta))
            for index, wp in enumerate(regreso):
                es_hub = index == len(regreso) - 1
                if es_hub:
                    previo = regreso[index - 1] if index > 0 else None
                    aproximacion = self._punto_de_aproximacion(previo, wp)
                    if aproximacion is not None:
                        self._progress(order_id, "en_reparto",
                                       "aproximándose al hub", RETURNING)
                        self._fly_to(aproximacion[0], aproximacion[1], alt_vuelta)
                    self._enter_hub()
                # Cada tramo del retorno informa de su fase. Sin esto el
                # detalle se quedaba congelado en "esperando: HUB ocupado"
                # aunque el dron ya estuviera volando, y el panel mentia.
                self._progress(order_id, "en_reparto",
                               "volviendo por el hub" if es_hub else "volviendo por la ruta",
                               RETURNING)
                self._fly_to(float(wp["lat"]), float(wp["lon"]), alt_vuelta)

            self.airspace.release_hub(self.record.drone_id)
            self._progress(order_id, "en_reparto", "volviendo al parking", RETURNING)
            self._fly_to(self.record.home_lat, self.record.home_lon, alt_vuelta)

            # Igual que en el despegue: bajar atraviesa todas las capas. Se
            # espera a tener la vertical libre antes de iniciar el descenso.
            self._enter_pad("aterrizar")
            self._progress(order_id, "en_reparto", "aterrizando en parking", LANDING)
            self.link.land()
            self.airspace.release_pad(self.record.drone_id)

            self._consume_battery(order)
            self._progress(order_id, "entregado", "entregado", IDLE)
            desenlace = "entregado"
        except _Cancelled:
            self._abort("cancelado")
            desenlace = "cancelado"
        except _LinkLost as perdido:
            self._link_lost(perdido.reason)
            desenlace = "enlace_perdido"
        except _Aborted as abortado:
            self._abort(abortado.reason, return_to_queue=True)
            desenlace = "abortado"
        except Exception as exc:  # noqa: BLE001
            self._fail(order_id, str(exc))
            desenlace = "error"
        finally:
            self.airspace.release_hub(self.record.drone_id)
            # Si la entrega muere a mitad de una maniobra, el parking no puede
            # quedarse bloqueado esperando a un dron que ya no vuela.
            self.airspace.release_pad(self.record.drone_id)
            self.airspace.release_slot(self.record.drone_id)
            self.runtime.cruise_alt_m = None
            self.runtime.current_order_id = None
            self._notify_finished(order, desenlace, time.time() - inicio)

    def _notify_finished(self, order, outcome, duration_s) -> None:
        """Avisa del desenlace. Nunca propaga: medir no puede tumbar un vuelo."""
        if self.on_finished is None:
            return
        try:
            self.on_finished({
                "drone_id": self.record.drone_id,
                "order_id": order.get("id"),
                "category": self.record.category,
                "weight_kg": float(order.get("weight_kg") or 0.0),
                "distance_km": float(order.get("assigned_distance_km") or 0.0),
                "energy_wh": self.last_energy_wh,
                "duration_s": duration_s,
                "wait_s": self.wait_s,
                "outcome": outcome,
            })
        except Exception:  # noqa: BLE001
            log.exception("no se pudo registrar la métrica de la entrega")

    # ── Tramos ───────────────────────────────────────────────────────────
    def _fly_to(self, lat, lon, alt) -> None:
        """Vuela a un punto, comprobando estado en cada latido."""
        self.link.goto(lat, lon, alt)
        deadline = time.time() + LEG_TIMEOUT_S
        proximo_reenvio = time.time() + GOTO_REFRESH_S
        avisado_proximidad = False
        while time.time() < deadline:
            self._check()
            self._enforce_safety()

            # La proximidad horizontal ya **no detiene** al dron. La separación
            # la garantiza el reparto en capas: cada vuelo tiene su nivel y el
            # regreso va en un bloque por encima, así que dos drones cercanos
            # en planta están separados en vertical.
            #
            # Frenar además por distancia horizontal causaba bloqueos reales:
            # un dron saliendo del parking y otro volviendo a él se estorban
            # indefinidamente, porque el conflicto no se resuelve solo. El que
            # esperaba agotaba el tiempo del tramo y perdía la entrega.
            #
            # El conflicto se sigue anotando, sin frenar: interesa saber
            # cuántas veces la separación vertical fue lo único que separó a
            # dos drones. Una vez por tramo, no en cada latido.
            if not avisado_proximidad and self.airspace.must_yield(
                    self.record.drone_id, self._runtimes()):
                avisado_proximidad = True
                self.safety.record_event(
                    self.record.drone_id, "proximidad",
                    "otro dron cerca en planta; separados por capa de altitud")

            if self.link.has_arrived(lat, lon, self.scenario.waypoint_tolerance_m):
                self._sync_position()
                return

            # Reenvío periódico: cubre los goto que el autopiloto descarta
            # mientras cambia de modo.
            if time.time() >= proximo_reenvio:
                self.link.goto(lat, lon, alt)
                proximo_reenvio = time.time() + GOTO_REFRESH_S

            self._sync_position()
            self._sleep(self.control_period_s)
        raise TimeoutError(f"tramo no completado en {LEG_TIMEOUT_S:.0f} s")

    @staticmethod
    def _punto_de_espera(ruta, cli_lat, cli_lon):
        """Punto donde aguardar turno: sobre la ruta, antes de llegar.

        Se retrocede ``HOLD_BACK_M`` desde el cliente **en la direccion por la
        que se viene**, no a un rumbo fijo. Esperar a un lado obligaria a
        salirse del corredor aprobado; sobre la ruta el dron se queda en el
        camino que ya tenia autorizado, simplemente sin llegar.

        Quedarse *antes* y no encima es lo que permite que el de abajo
        despegue: la vertical del cliente queda despejada, que es justo de
        quien depende que se libere.
        """
        origen = None
        for wp in reversed(ruta or []):
            try:
                lat, lon = float(wp["lat"]), float(wp["lon"])
            except (KeyError, TypeError, ValueError):
                continue
            if haversine_km(lat, lon, cli_lat, cli_lon) * 1000.0 > 1.0:
                origen = (lat, lon)
                break
        if origen is None:
            # Sin ruta utilizable no hay direccion de aproximacion: se retrocede
            # al norte, que al menos deja libre la vertical.
            return offset_position(cli_lat, cli_lon, "North", HOLD_BACK_M)

        # Interpolacion sobre el segmento origen->cliente, retrocediendo desde
        # el cliente la distancia pedida.
        largo_m = haversine_km(origen[0], origen[1], cli_lat, cli_lon) * 1000.0
        if largo_m <= HOLD_BACK_M:
            return origen           # el tramo es mas corto: se espera en el wp
        f = HOLD_BACK_M / largo_m
        return (cli_lat + (origen[0] - cli_lat) * f,
                cli_lon + (origen[1] - cli_lon) * f)

    @staticmethod
    def _punto_de_aproximacion(previo, hub):
        """Punto del último tramo del regreso a ``HUB_APPROACH_M`` del HUB.

        Es donde el dron pide paso: hasta ahí vuela por su corredor sin
        ocupar el HUB. ``None`` si el tramo es tan corto que no merece la
        pena partirlo.
        """
        try:
            p_lat, p_lon = float(previo["lat"]), float(previo["lon"])
            h_lat, h_lon = float(hub["lat"]), float(hub["lon"])
        except (KeyError, TypeError, ValueError):
            return None
        largo_m = haversine_km(p_lat, p_lon, h_lat, h_lon) * 1000.0
        if largo_m <= HUB_APPROACH_M + 10.0:
            return None
        f = HUB_APPROACH_M / largo_m
        return (h_lat + (p_lat - h_lat) * f, h_lon + (p_lon - h_lon) * f)

    def _wait_for_pad(self, lat, lon) -> None:
        """Mantiene posicion hasta poder ocupar la vertical del punto."""
        self.link.hold()
        deadline = time.time() + LEG_TIMEOUT_S
        while not self.airspace.acquire_pad(self.record.drone_id, lat, lon,
                                            ATERRIZAJE):
            self._check()
            self._enforce_safety()
            if time.time() > deadline:
                raise _Aborted("el punto de entrega no se liberó a tiempo")
            self.wait_s += self.control_period_s
            self._sleep(self.control_period_s)
        self.link.resume()
        self.runtime.detail = "punto de entrega libre"

    def _enter_pad(self, maniobra: str) -> None:
        """Espera a tener libre la vertical de su pad.

        A diferencia del HUB, aquí no se manda ``hold``: en el despegue el
        dron sigue en tierra —no hay nada que mantener— y en el aterrizaje ya
        está parado sobre su pad esperando a bajar. Basta con no empezar la
        maniobra.

        Se pasan las coordenadas del pad porque el vertipuerto decide por
        geometría: dos drones cuyos pads estén suficientemente separados
        maniobran a la vez. Sin ellas cae a exclusión total.
        """
        avisado = False
        deadline = time.time() + LEG_TIMEOUT_S
        while not self.airspace.acquire_pad(
                self.record.drone_id, self.record.home_lat,
                self.record.home_lon, maniobra):
            self._check()
            if not avisado:
                self.runtime.detail = f"esperando turno para {maniobra}"
                self.safety.record_event(
                    self.record.drone_id, "espera_pad",
                    f"vertical del parking ocupada; espera para {maniobra}")
                avisado = True
            if time.time() > deadline:
                raise TimeoutError("la vertical del parking no se liberó a tiempo")
            self.wait_s += self.control_period_s
            self._sleep(self.control_period_s)

    def _enter_hub(self) -> None:
        """Espera a que el HUB quede libre antes de entrar en el corredor."""
        avisado = False
        deadline = time.time() + LEG_TIMEOUT_S
        while not self.airspace.acquire_hub(self.record.drone_id):
            self._check()
            if not avisado:
                self.link.hold()
                self.runtime.detail = "esperando: HUB ocupado"
                self.safety.record_event(self.record.drone_id, "espera",
                                         "HUB ocupado por otro dron")
                avisado = True
            if time.time() > deadline:
                raise TimeoutError("el HUB no se libero a tiempo")
            self.wait_s += self.control_period_s
            self._sleep(self.control_period_s)
        if avisado:
            self.link.resume()
            self.runtime.detail = "HUB libre, entrando"

    # ── Comprobaciones ───────────────────────────────────────────────────
    def _check(self) -> None:
        if self._cancelled:
            raise _Cancelled()

    def _enforce_safety(self) -> None:
        edad = None
        if hasattr(self.link, "telemetry_age_s"):
            edad = self.link.telemetry_age_s()
        veredicto = self.safety.check_in_flight(self.record, self.runtime,
                                                telemetry_age_s=edad)
        if veredicto is None:
            return
        accion, motivo = veredicto
        if accion == LINK_LOST:
            # No se manda RTL: no hay a quien mandarselo. El autopiloto tiene
            # su propio failsafe; aqui lo que toca es dejar de fingir que el
            # dron esta operativo, liberar su slot y su turno de HUB, y
            # devolver el pedido a la cola.
            self.safety.record_event(self.record.drone_id, "enlace_perdido", motivo)
            raise _LinkLost(motivo)
        if accion == RTL:
            self.safety.record_event(self.record.drone_id, "rtl", motivo)
            raise _Aborted(motivo)

    def _runtimes(self) -> dict:
        runtimes = dict(self.fleet_runtimes)
        runtimes[self.record.drone_id] = self.runtime
        return runtimes

    def _sleep(self, seconds) -> None:
        """Espera interrumpible: se corta en cuanto se cancela la entrega.

        El escalonado de salida puede durar decenas de segundos; dormirlo de un
        tirón dejaba «Parar todo» sin efecto hasta que terminaba. Quien llama
        comprueba después con ``_check()`` y aborta.
        """
        if not seconds or seconds <= 0:
            return
        fin = time.time() + seconds
        while not self._cancelled:
            resto = fin - time.time()
            if resto <= 0:
                return
            time.sleep(min(resto, SLEEP_SLICE_S))

    # ── Estado ───────────────────────────────────────────────────────────
    def _progress(self, order_id, status, detail, state) -> None:
        self.runtime.state = state
        self.runtime.detail = detail
        self._sync_position()
        self.on_order_state(status, detail)

    def _sync_position(self) -> None:
        telemetry = self.link.telemetry()
        self.runtime.lat = telemetry.get("lat")
        self.runtime.lon = telemetry.get("lon")
        self.runtime.alt = telemetry.get("alt")
        self.runtime.heading = telemetry.get("heading")
        self.runtime.ground_speed = telemetry.get("groundSpeed")

    def _consume_battery(self, order) -> None:
        """Descuenta la energía estimada del viaje.

        La batería la lleva el modelo, no el voltaje del SITL: en vuelos de
        dos minutos el voltaje simulado apenas se mueve, y el modelo es lo que
        el greedy necesita para decidir.
        """
        distancia = float(order.get("assigned_distance_km") or 0.0)
        self.last_energy_wh = estimate_trip_energy_wh(
            self.record.spec, distancia, float(order.get("weight_kg") or 0.0))
        self.runtime.battery_wh = max(0.0, self.runtime.battery_wh - self.last_energy_wh)

    def _abort(self, detail, return_to_queue=False) -> None:
        try:
            self.link.abort("RTL")
        except Exception:  # noqa: BLE001
            pass
        self.runtime.state = IDLE
        self.runtime.detail = detail
        # El pedido vuelve a la cola: no se ha entregado y otro dron podra
        # cogerlo en el siguiente ciclo de planificacion.
        self.on_order_state("pendiente" if return_to_queue else None, detail)

    def _link_lost(self, detail) -> None:
        """El dron es inalcanzable: se marca y se devuelve el pedido.

        No se intenta ningún comando porque no llegaría. El `finally` de `run`
        libera su slot de altitud y su turno de HUB, que es lo importante: un
        dron perdido reteniendo el HUB bloquea a toda la flota.
        """
        self.runtime.state = ERROR
        self.runtime.detail = detail
        self.on_order_state("pendiente", detail)

    def _fail(self, order_id, message) -> None:
        self.runtime.state = ERROR
        self.runtime.detail = f"error: {message}"
        self.safety.record_event(self.record.drone_id, "error", message)
        self.on_order_state(None, "error")
