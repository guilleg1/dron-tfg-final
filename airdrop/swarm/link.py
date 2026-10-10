"""Enlace con un autopiloto.

``DroneLink`` es la interfaz que el resto del enjambre conoce: el ejecutor y el
servicio nunca hablan con dronLink directamente. Eso permite sustituir el
autopiloto por ``FakeDroneLink`` en los tests y probar toda la lógica de vuelo
sin levantar SITL.

``MavlinkDroneLink`` es la implementación real. Hereda de ``LocalBackend`` la
experiencia acumulada con dronLink, que está llena de detalles no obvios:

- Se construye ``Dron(id=drone_id)``, y entonces el callback de telemetría
  recibe ``(drone_id, info)``. Con la firma de un argumento el hilo de
  telemetría muere con un ``TypeError`` dentro de dronLink, la conexión sigue
  viva y el dron aparece conectado pero sin datos.
- No se usa ``motors_armed_wait()``: no tiene timeout y bloquea el hilo para
  siempre si el autopiloto rechaza el armado, con lo que los reintentos nunca
  llegan a ejecutarse. Se sondea ``motors_armed()`` con límite.
- Tampoco se usa ``_takeOff()``, por lo mismo: espera con
  ``wait_for_message(timeout=None)`` y no vuelve nunca si el autopiloto se
  queda a media subida. El dron aparece «despegando» a una altura cualquiera,
  parado y sin error. Se manda ``MAV_CMD_NAV_TAKEOFF`` a mano y se vigila.
- No se usa ``uploadMission`` + AUTO: el modo no se reinicia limpio entre
  misiones y la segunda no arranca. Todo va punto a punto en GUIDED.
- El aterrizaje no se detecta por altitud relativa < 1 m, que en terreno
  elevado no se cumple nunca, sino por desarmado o altitud estable.

Ver docs/swarm/SITL.md.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import time
from pathlib import Path

log = logging.getLogger(__name__)

from core.geo import haversine_km

ARM_COMMAND = 400          # MAV_CMD_COMPONENT_ARM_DISARM
TAKEOFF_COMMAND = 22       # MAV_CMD_NAV_TAKEOFF
ARM_TIMEOUT_S = 8.0
ARM_ATTEMPTS = 6
LAND_TIMEOUT_S = 120.0
TAKEOFF_TIMEOUT_S = 90.0

# Rango que admite WPNAV_SPEED en ArduCopter (0,2-20 m/s). Un valor fuera de
# rango se descarta en silencio y el autopiloto se queda con su defecto.
MIN_NAV_SPEED_MPS = 0.2
MAX_NAV_SPEED_MPS = 20.0


class EnlaceCerrado(ConnectionError):
    """El autopiloto ha cerrado la conexión TCP."""


def cortar_en_eof(vehicle) -> None:
    """Hace que un EOF o un reset del socket terminen la lectura.

    pymavlink, sin reconexión automática, responde a un EOF imprimiendo
    «EOF on TCP socket» y devolviendo cero bytes, y ``recv_match`` bloqueante
    vuelve a intentarlo al instante. Si el SITL de un dron se para (al quitarlo
    de la flota, al relanzar o porque muere) el hilo lector de dronLink se queda
    girando en vacío: en Railway llegó a ocupar más de un procesador y a saturar
    el registro. Lanzando una excepción el lector termina; el dron deja de
    recibir telemetría y la vigilancia de enlace perdido hace el resto.
    """
    def _cerrado(*_args):
        raise EnlaceCerrado("el autopiloto ha cerrado la conexión")

    for nombre in ("handle_eof", "handle_disconnect"):
        if hasattr(vehicle, nombre):
            setattr(vehicle, nombre, _cerrado)


def cortar_en_eof_al_conectar() -> None:
    """Lo mismo que ``cortar_en_eof``, pero para toda conexión TCP de pymavlink.

    ``cortar_en_eof`` solo puede aplicarse cuando dronLink ya ha creado el
    vehículo, y dronLink lo crea y espera el primer heartbeat en la misma
    llamada. Si el otro extremo acepta y cierra durante esa espera, como hace
    la pasarela con un dron cuyo puente no está conectado, la espera gira sobre
    el EOF sin fin y el dron no vuelve a conectar aunque el puente llegue.
    """
    from pymavlink import mavutil  # noqa: PLC0415

    if getattr(mavutil.mavtcp, "_corte_eof", False):
        return

    def _cerrado(_self, *_args):
        raise EnlaceCerrado("el autopiloto ha cerrado la conexión")

    mavutil.mavtcp.handle_eof = _cerrado
    mavutil.mavtcp.handle_disconnect = _cerrado
    mavutil.mavtcp._corte_eof = True


class DroneLinkError(RuntimeError):
    """Fallo al operar el autopiloto."""


def _add_dronlink_to_path() -> bool:
    """Añade al sys.path la carpeta que contiene el paquete 'dronLink'."""
    root = Path(__file__).resolve().parents[2]
    candidates = []
    if os.environ.get("DRONLINK_PATH"):
        candidates.append(Path(os.environ["DRONLINK_PATH"]))
    candidates.append(root / "vendor")
    for candidate in candidates:
        if candidate and (candidate / "dronLink").is_dir():
            if str(candidate) not in sys.path:
                sys.path.insert(0, str(candidate))
            return True
    return False


class MavlinkDroneLink:
    """Enlace real con un autopiloto por dronLink."""

    def __init__(self, drone_id, connection, home_lat, home_lon, baud=115200, freq=5):
        self.drone_id = drone_id
        self.connection = connection
        self.home_lat = home_lat
        self.home_lon = home_lon
        self.baud = baud
        self.freq = freq
        self._dron = None
        self._telemetry = {}
        self._telemetry_at = None
        self._target = None
        self._lock = threading.Lock()
        # Lo pone el ejecutor para que el panel siga vivo durante despegue y
        # aterrizaje, que son esperas bloqueantes fuera de su bucle.
        self.on_progress = None
        # Avisos del autopiloto (PreArm y demas), para poder decir
        # POR QUE se rechazo un armado en vez de solo que se rechazo.
        self._prearm: list[str] = []

    # ── Conexión ─────────────────────────────────────────────────────────
    @property
    def is_connected(self) -> bool:
        return (self._dron is not None
                and getattr(self._dron, "state", "disconnected") != "disconnected")

    def connect(self) -> None:
        if not _add_dronlink_to_path():
            raise DroneLinkError(
                "No se encontró dronLink. Define DRONLINK_PATH apuntando a la "
                "carpeta que contiene 'dronLink'.")
        from dronLink.Dron import Dron  # noqa: PLC0415

        # Con id definido, dronLink invoca el callback como (id, info).
        cortar_en_eof_al_conectar()
        self._dron = Dron(id=self.drone_id)
        self._dron.connect(self.connection, self.baud, freq=self.freq)
        cortar_en_eof(self._dron.vehicle)
        self._dron.send_telemetry_info(self._on_telemetry)

    def _on_telemetry(self, _drone_id, info) -> None:
        with self._lock:
            self._telemetry = dict(info or {})
            self._telemetry_at = time.monotonic()

    def telemetry(self) -> dict:
        with self._lock:
            return dict(self._telemetry)

    def telemetry_age_s(self) -> float | None:
        """Segundos desde el último paquete recibido.

        ``None`` si aún no ha llegado ninguno. Es lo que permite distinguir un
        enlace caído de un dron parado: si el socket muere, la telemetría deja
        de llegar pero el último valor conocido sigue ahí, y el dron aparenta
        estar sano mientras es inalcanzable.
        """
        with self._lock:
            if self._telemetry_at is None:
                return None
            return time.monotonic() - self._telemetry_at

    def close(self) -> None:
        """Para la telemetría, el hilo lector de dronLink y el socket.

        Antes solo se paraba la telemetría y el hilo lector seguía vivo: al
        parar después su SITL, quedaba girando sobre un socket cerrado.
        """
        if self._dron is None:
            return
        dron, self._dron = self._dron, None
        try:
            dron.stop_sending_telemetry_info()
        except Exception:  # noqa: BLE001
            pass
        handler = getattr(dron, "message_handler", None)
        if handler is not None:
            handler.running = False
        try:
            dron.state = "disconnected"
            dron.vehicle.close()
        except Exception:  # noqa: BLE001
            pass

    # ── Vuelo ────────────────────────────────────────────────────────────
    def arm_and_takeoff(self, alt: float) -> None:
        dron = self._require()
        self._prearm = []
        for _ in range(ARM_ATTEMPTS):
            try:
                dron.setFlightMode("GUIDED")
                time.sleep(1)
                dron.vehicle.mav.command_long_send(
                    dron.vehicle.target_system, dron.vehicle.target_component,
                    ARM_COMMAND, 0, 1, 0, 0, 0, 0, 0, 0)
            except Exception:  # noqa: BLE001
                time.sleep(1)
                continue
            deadline = time.time() + ARM_TIMEOUT_S
            while time.time() < deadline:
                if dron.vehicle.motors_armed():
                    dron.state = "armed"
                    self._takeoff(alt)
                    return
                self._collect_statustext(dron)
                time.sleep(0.5)

        # El autopiloto explica por qué rechaza el armado en un STATUSTEXT
        # ("PreArm: ..."). Sin recogerlo, el error era un "no se pudo armar" a
        # secas y no había forma de saber si faltaba fix GPS, si el EKF no
        # había convergido o si era otra cosa. Diagnosticarlo obligaba a
        # conectar Mission Planner a mano.
        motivo = "; ".join(self._prearm[-3:]) if self._prearm else "sin motivo del autopiloto"
        raise DroneLinkError(f"{self.drone_id}: no se pudo armar — {motivo}")

    def _collect_statustext(self, dron) -> None:
        """Recoge los avisos del autopiloto sin bloquear."""
        try:
            while True:
                msg = dron.vehicle.recv_match(type="STATUSTEXT", blocking=False)
                if msg is None:
                    return
                texto = str(getattr(msg, "text", "")).strip()
                if texto and texto not in self._prearm:
                    self._prearm.append(texto)
                    log.warning("%s: %s", self.drone_id, texto)
        except Exception:  # noqa: BLE001
            return

    def _takeoff(self, alt: float) -> None:
        """Ordena el despegue y vigila la subida con límite de tiempo.

        **No** se usa ``dron._takeOff()``, por el mismo motivo por el que no se
        usa ``motors_armed_wait()``: espera con ``wait_for_message(timeout=None)``
        y se queda dentro de dronLink **para siempre** si el autopiloto no
        alcanza la altitud pedida. Cuando eso pasa, el hilo del ejecutor no
        vuelve nunca: el dron se queda a media subida, en estado «despegando»,
        sin avanzar y sin dar error, y el bucle de vigilancia de aquí abajo
        —que existe justo para esto— no llegaba a ejecutarse.

        Se manda el comando a mano y se vigila con ``TAKEOFF_TIMEOUT_S``. Si no
        sube, se recogen los avisos del autopiloto para poder decir por qué.
        """
        dron = self._require()
        dron.state = "armed"   # un heartbeat atrasado puede haberlo pisado
        self._prearm = []
        try:
            dron.vehicle.mav.command_long_send(
                dron.vehicle.target_system, dron.vehicle.target_component,
                TAKEOFF_COMMAND, 0, 0, 0, 0, 0, 0, 0, float(alt))
        except Exception as exc:  # noqa: BLE001
            raise DroneLinkError(f"{self.drone_id}: fallo en el despegue ({exc})") from exc
        dron.state = "flying"

        deadline = time.time() + TAKEOFF_TIMEOUT_S
        ultima_alt = 0.0
        while time.time() < deadline:
            self._notify_progress()
            actual = float(self.telemetry().get("alt") or 0.0)
            ultima_alt = max(ultima_alt, actual)
            if actual >= alt * 0.9:
                self._notify_progress()
                return
            self._collect_statustext(dron)
            time.sleep(1)

        motivo = "; ".join(self._prearm[-3:]) if self._prearm else "sin motivo del autopiloto"
        raise DroneLinkError(
            f"{self.drone_id}: no alcanzó la altitud de {alt:.0f} m "
            f"(se quedó en {ultima_alt:.1f} m) — {motivo}")

    def _notify_progress(self) -> None:
        """Avisa de que hay telemetría fresca durante una espera bloqueante.

        Despegue y aterrizaje son los dos tramos en los que el ejecutor no
        pasa por su bucle de control, así que nadie volcaba la telemetría al
        runtime: la altitud del panel saltaba de 0 a la de crucero de golpe y
        parecía congelada. Aquí se avisa desde dentro de la espera.

        No propaga: un fallo pintando el panel no puede tumbar un despegue.
        """
        if self.on_progress is None:
            return
        try:
            self.on_progress()
        except Exception:  # noqa: BLE001
            pass

    def goto(self, lat: float, lon: float, alt: float) -> None:
        """Ordena el desplazamiento y vuelve inmediatamente.

        No bloqueante a propósito. Con la versión bloqueante de dronLink el
        ejecutor se quedaba dentro de la librería durante todo el tramo, y no
        existía ningún instante en el que comprobar separación, ocupación del
        HUB ni batería. Sin esto, la deconflicción táctica es imposible.
        """
        self._target = (float(lat), float(lon), float(alt))
        self._require().goto(float(lat), float(lon), float(alt), blocking=False)

    def has_arrived(self, lat: float, lon: float, tol_m: float) -> bool:
        """¿Está el dron dentro de ``tol_m`` del punto?"""
        telemetria = self.telemetry()
        if telemetria.get("lat") is None or telemetria.get("lon") is None:
            return False
        distancia_m = haversine_km(
            telemetria["lat"], telemetria["lon"], float(lat), float(lon)) * 1000.0
        return distancia_m <= tol_m

    def set_speed(self, speed_mps: float) -> None:
        """Fija la velocidad de crucero en el autopiloto.

        La velocidad del escenario de rutas se enviaba en la misión y no la
        aplicaba nadie: los drones volaban al ``WPNAV_SPEED`` por defecto del
        autopiloto —10 m/s— dijera lo que dijera el formulario. Cambiarla no
        tenía efecto, que es peor que no ofrecerla.
        """
        if not speed_mps or speed_mps <= 0:
            return

        # ArduCopter acepta WPNAV_SPEED entre 0,2 y 20 m/s. Fuera de rango el
        # autopiloto **descarta el parámetro sin avisar** y se queda con su
        # valor por defecto —10 m/s—, así que pedir 30 daba exactamente el
        # mismo resultado que no pedir nada. Se recorta y se deja constancia.
        pedida = float(speed_mps)
        efectiva = max(MIN_NAV_SPEED_MPS, min(MAX_NAV_SPEED_MPS, pedida))
        if abs(efectiva - pedida) > 1e-6:
            log.warning(
                "%s: velocidad %.1f m/s fuera del rango admitido (%.1f-%.1f); "
                "se usa %.1f m/s", self.drone_id, pedida,
                MIN_NAV_SPEED_MPS, MAX_NAV_SPEED_MPS, efectiva)
        speed_mps = efectiva

        dron = self._require()
        try:
            # Se escribe WPNAV_SPEED directamente en vez de usar
            # ``changeNavSpeed``: ese método termina llamando a
            # ``go(self.direction)``, que reordena un desplazamiento en la
            # última dirección conocida y pisaría el destino que el ejecutor
            # acaba de fijar en GUIDED.
            #
            # Se mandan los dos nombres. ArduCopter 4.7 renombró WPNAV_SPEED
            # (cm/s) a WP_SPD (m/s) y descarta en silencio el nombre que no
            # conoce: con solo el antiguo, el SITL de Linux volaba siempre a
            # 10 m/s. El de Mission Planner puede ser anterior y usar el viejo.
            dron.setParams([{"ID": "WP_SPD", "Value": float(speed_mps)},
                            {"ID": "WPNAV_SPEED", "Value": float(speed_mps) * 100.0}])
            log.info("%s: velocidad de crucero fijada a %.1f m/s",
                     self.drone_id, speed_mps)
        except Exception as exc:  # noqa: BLE001
            # No es motivo para abortar una entrega: se vuela a la velocidad
            # por defecto y queda constancia.
            log.warning("%s: no se pudo fijar la velocidad a %.1f m/s (%s)",
                        self.drone_id, speed_mps, exc)

    def hold(self) -> None:
        """Mantiene la posición actual sin abortar la misión.

        BRAKE, nunca LAND: ceder el paso es esperar en el aire. Un dron que
        aterriza a mitad de corredor por un conflicto de separación queda
        fuera del alcance del ejecutor y bloquea el pedido.

        Tampoco LOITER, que era lo que se usaba: LOITER obedece al mando de
        la emisora y sin emisora el canal de gas está al mínimo, así que el
        dron «esperaba» bajando hasta posarse y desarmarse a mitad de ruta.
        Lo destapó la oleada completa contra el SITL de Linux, donde nadie
        manda RC. BRAKE frena y mantiene la posición sin mirar la emisora.
        """
        self._require().setFlightMode("BRAKE")

    def resume(self) -> None:
        """Vuelve a GUIDED y reenvía el último destino."""
        dron = self._require()
        dron.setFlightMode("GUIDED")
        if self._target is not None:
            lat, lon, alt = self._target
            dron.goto(lat, lon, alt, blocking=False)

    def land(self) -> None:
        dron = self._require()
        dron.setFlightMode("LAND")
        self._wait_until_landed()

    def _wait_until_landed(self) -> None:
        """Aterrizado = motores desarmados o altitud estable.

        La condición de dronLink (altitud relativa < 1 m) no se cumple nunca en
        terreno elevado, donde el dron toca tierra a 3 m relativos.
        """
        dron = self._dron
        deadline = time.time() + LAND_TIMEOUT_S
        last_alt, stable_since = None, None
        while time.time() < deadline:
            try:
                if not dron.vehicle.motors_armed():
                    return
            except Exception:  # noqa: BLE001
                pass
            self._notify_progress()
            alt = self.telemetry().get("alt")
            if alt is not None:
                if last_alt is not None and abs(float(alt) - float(last_alt)) < 0.3:
                    stable_since = stable_since or time.time()
                    if time.time() - stable_since >= 6:
                        return
                else:
                    stable_since = None
                last_alt = alt
            time.sleep(1)

    def abort(self, mode: str = "RTL") -> None:
        """Interrumpe lo que esté haciendo y pasa al modo indicado."""
        self._require().setFlightMode(mode)

    def _require(self):
        if self._dron is None:
            raise DroneLinkError(f"{self.drone_id}: no conectado")
        return self._dron
