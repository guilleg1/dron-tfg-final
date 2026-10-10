"""Gestión del espacio aéreo del enjambre.

Dos capas, siguiendo el modelo por niveles de U-space:

- **Estratégica**, al planificar: reserva de una capa de altitud por vuelo y
  escalonado de despegues del mismo parking.
- **Táctica**, en vuelo: exclusión mutua en el HUB y vigilancia de la
  separación mínima.

No hay detect-and-avoid reactivo: el enjambre resuelve conflictos esperando,
no esquivando. Es lo apropiado para corredores pre-aprobados y deja la evasión
con maniobras como trabajo futuro.
"""

from __future__ import annotations

import itertools
import threading
import time
from dataclasses import dataclass

from airdrop.swarm.models import BUSY_STATES
from core.geo import haversine_km

DESPEGUE = "despegar"
ATERRIZAJE = "aterrizar"

# Cuánto sigue abierta una tanda de despegue después de su instante. Los
# ejecutores no arrancan a la vez —entre uno y otro pasan décimas—, así que sin
# este margen un dron compatible con los que acaban de salir llega «tarde» a su
# propia tanda por unas milésimas y se va a la siguiente.
TANDA_ABIERTA_S = 3.0


@dataclass
class _Maniobra:
    """Un dron ocupando (o pidiendo) la vertical de su pad."""

    drone_id: str
    lat: float | None
    lon: float | None
    tipo: str
    desde: float
    orden: int

    @property
    def prioridad(self) -> tuple[int, int]:
        """Menor es antes. Los aterrizajes van primero.

        Un dron que vuelve lleva la batería gastada y está en el aire: cada
        segundo de espera se le descuenta del margen. El que despega está en
        tierra, donde esperar no cuesta energía.
        """
        return (0 if self.tipo == ATERRIZAJE else 1, self.orden)


class AirspaceManager:
    """Arbitra altitudes, despegues y conflictos. Seguro entre hilos."""

    # Cuánto puede un dron retener el HUB antes de que se le expulse. Si uno
    # se atasca, el resto de la flota no puede quedarse esperándolo.
    HUB_HOLD_TIMEOUT_S = 90.0

    def __init__(self, scenario, slot_count: int, clock=time.monotonic,
                 hub_hold_timeout_s: float = HUB_HOLD_TIMEOUT_S):
        self.scenario = scenario
        self._clock = clock
        self._slot_count = slot_count
        self.hub_hold_timeout_s = hub_hold_timeout_s
        self._reserved: dict[str, float] = {}
        # Ocupantes del HUB con el instante en que entraron. Antes era un solo
        # ocupante; ahora caben `hub_capacity` a la vez y cada uno lleva su
        # propio reloj para el desalojo por tiempo.
        self._hub_holders: dict[str, float] = {}
        self._hub_queue: list[str] = []
        # Verticales del parking en uso, una por dron que maniobra.
        self._pad_holders: dict[str, _Maniobra] = {}
        self._pad_waiting: dict[str, _Maniobra] = {}
        self._orden = itertools.count()
        # Tandas de despegue ya formadas: cada una, un instante y los pads que
        # salen en ella. Los pads de una misma tanda son compatibles entre sí.
        self._tandas: list[dict] = []
        self._lock = threading.RLock()

    @property
    def _slots(self) -> list[float]:
        """Capas disponibles según el escenario vigente.

        Se recalcula en cada consulta porque el escenario puede editarse en
        caliente desde el panel: cachearlas dejaría el gestor operando con
        límites viejos.
        """
        return self.scenario.slot_altitudes(self._slot_count)

    # ── Capa estratégica ─────────────────────────────────────────────────
    def reserve_slot(self, drone_id: str) -> float | None:
        """Reserva una capa de crucero. ``None`` si no queda ninguna libre."""
        with self._lock:
            if drone_id in self._reserved:
                return self._reserved[drone_id]
            ocupadas = set(self._reserved.values())
            for altitud in self._slots:
                if altitud not in ocupadas:
                    self._reserved[drone_id] = altitud
                    return altitud
            return None

    def release_slot(self, drone_id: str) -> None:
        with self._lock:
            self._reserved.pop(drone_id, None)

    def reserved_slot(self, drone_id: str) -> float | None:
        with self._lock:
            return self._reserved.get(drone_id)

    def return_altitude(self, drone_id: str) -> float | None:
        """Nivel de crucero para el tramo de regreso.

        El regreso rehace la ruta de ida al revés, así que sobre el mismo
        corredor puede haber tráfico en los dos sentidos. La solución es la de
        la aviación: **separar por sentido**. Las capas de ida ocupan el bloque
        ``base + k·step``; el regreso usa el bloque inmediatamente superior,
        desplazado tantas capas como drones tenga la flota. Con cuatro drones y
        el escenario por defecto, ida a 25/30/35/40 y vuelta a 45/50/55/60:
        ningún par ida-vuelta comparte nivel y cada dron conserva su índice.

        Si el bloque de vuelta no cabe bajo el techo se devuelve la capa de
        ida. Es una degradación consciente: preferimos volver al
        comportamiento anterior —resuelto por la separación táctica y las
        esperas— antes que romper el límite regulatorio de altura.
        """
        with self._lock:
            ida = self._reserved.get(drone_id)
            if ida is None:
                return None
            slots = self._slots
            if not slots:
                return ida
            candidata = ida + len(slots) * self.scenario.alt_step_m
            return candidata if candidata <= self.scenario.alt_ceiling_m else ida

    def takeoff_delay_s(self, drone_id: str, lat=None, lon=None) -> float:
        """Retardo que debe esperar este dron, y registra su despegue.

        Dos drones no despegan en una ventana menor que ``takeoff_gap_s``: la
        estela y el margen de maniobra en el pad lo desaconsejan, y escalonar
        reduce los conflictos aguas abajo.

        El escalonado es **por vecindad**, no global. Aplicarlo a toda la
        flota encadenaba retardos crecientes —10 s, 20 s, 30 s con cuatro
        drones— que además quedaban inservibles: al terminar la espera, el
        dron se encontraba con la vertical del parking ocupada y volvía a
        esperar, ahora sin plazo. Se cuenta solo contra los despegues de pads
        que no pueden operar a la vez que el suyo, que son los únicos a los
        que la razón física del escalonado se aplica.

        Los despegues se organizan en **tandas**, no uno a uno: cada tanda
        agrupa pads compatibles entre sí, y son las tandas —no los drones— las
        que se separan por ``takeoff_gap_s``. Es el mismo reparto que dibuja el
        ParkingTool, y hacer que el vuelo lo respete es lo que da sentido a
        enseñarlo.

        Tratarlas de una en una fallaba por márgenes ridículos. Los ejecutores
        no arrancan en el mismo instante: entre uno y otro pasa una décima. Con
        el pad 4 saliendo en t=0 y el 5 en t=10, el 6 —compatible con el 4—
        pedía su turno en t=0,2 y se encontraba con que hasta el 5 quedaban
        9,8 s en vez de 10. Le faltaban dos décimas, y se iba una tanda entera
        más tarde. Uniéndose a la tanda del 4, sale con él.

        Sin coordenadas de pad cada dron forma su propia tanda, que es el
        escalonado global de antes.
        """
        with self._lock:
            ahora = self._clock()
            intervalo = self.scenario.takeoff_gap_s
            self._tandas = [t for t in self._tandas
                            if ahora - t["cuando"] < max(intervalo, 1.0) * 4]

            tanda = self._tanda_a_la_que_unirse(ahora, lat, lon, intervalo)
            if tanda is None:
                # Ninguna sirve: se abre una nueva en el primer hueco que
                # respete la separación con las tandas que sí estorban.
                ocupadas = [t["cuando"] for t in self._tandas
                            if self._estorba(lat, lon, t)]
                tanda = {"cuando": self._primer_hueco(ahora, ocupadas, intervalo),
                         "pads": []}
                self._tandas.append(tanda)

            tanda["pads"].append((lat, lon))
            return max(0.0, tanda["cuando"] - ahora)

    def _tanda_a_la_que_unirse(self, ahora, lat, lon, intervalo):
        """La tanda más temprana en la que cabe este pad, o ``None``.

        Cabe si es compatible con todos sus miembros y si su instante respeta
        la separación con las demás tandas que sí le estorban.
        """
        for tanda in sorted(self._tandas, key=lambda t: t["cuando"]):
            # Una tanda que ya despegó hace rato no admite a nadie más. Se
            # tolera un margen porque los ejecutores no arrancan a la vez y la
            # tanda sigue formándose durante unos instantes.
            if tanda["cuando"] < ahora - TANDA_ABIERTA_S:
                continue
            if any(not self._pads_compatibles(lat, lon, pad_lat, pad_lon)
                   for pad_lat, pad_lon in tanda["pads"]):
                continue
            if all(abs(tanda["cuando"] - otra["cuando"]) >= intervalo - 1e-9
                   for otra in self._tandas
                   if otra is not tanda and self._estorba(lat, lon, otra)):
                return tanda
        return None

    def _estorba(self, lat, lon, tanda) -> bool:
        """¿Hay en esta tanda algún pad incompatible con el nuestro?"""
        return any(not self._pads_compatibles(lat, lon, pad_lat, pad_lon)
                   for pad_lat, pad_lon in tanda["pads"])

    @staticmethod
    def _primer_hueco(ahora: float, ocupados: list[float],
                      intervalo: float) -> float:
        """Primer instante desde ``ahora`` a ``intervalo`` de todo lo ocupado.

        Los candidatos son ``ahora`` y el final de cada ventana ya reservada:
        el óptimo siempre es uno de ellos, porque entre dos candidatos
        consecutivos la restricción no cambia. Con la flota acotada a diez
        drones la lista es minúscula.
        """
        if not ocupados or intervalo <= 0:
            return ahora
        candidatos = sorted({ahora} | {t + intervalo for t in ocupados
                                       if t + intervalo >= ahora})
        for candidato in candidatos:
            if all(abs(candidato - t) >= intervalo - 1e-9 for t in ocupados):
                return candidato
        return max(ocupados) + intervalo

    # ── Capa táctica ─────────────────────────────────────────────────────
    @property
    def hub_capacity(self) -> int:
        """Aforo del HUB, nunca menor que 1.

        Se lee del escenario en cada consulta porque se edita en caliente
        desde el panel.
        """
        return max(1, int(getattr(self.scenario, "hub_capacity", 1) or 1))

    # ── Verticales del parking ───────────────────────────────────────────
    #
    # Despegue y aterrizaje son los dos momentos en los que **no** hay
    # separación por capas: un dron que sube de 0 a su nivel atraviesa todos
    # los niveles inferiores, y el que baja hace lo mismo al revés. Pedir que
    # "no coincidan en altura" ahí es imposible; lo que se puede exigir es que
    # no coincidan en el **volumen**.
    #
    # La primera versión lo resolvía con un cerrojo único: un solo dron
    # maniobrando en todo el parking. Es correcto pero serializa la flota
    # entera —los cuatro drones despegan y aterrizan de uno en uno— y deja el
    # escalonado sin efecto, porque al agotar su retardo el dron se encuentra
    # la vertical ocupada.
    #
    # Un vertipuerto real no funciona así: tiene varias plataformas y opera en
    # paralelo las que están suficientemente separadas. Eso es lo que se
    # modela ahora: cada dron ocupa **la vertical de su pad**, y dos drones
    # pueden maniobrar a la vez si sus pads distan al menos
    # ``pad_separation_m``. Con ese parámetro a 0 el comportamiento vuelve a
    # ser el cerrojo único, así que lo verificado en B2 se conserva.
    def acquire_pad(self, drone_id: str, lat=None, lon=None,
                    maniobra: str = DESPEGUE) -> bool:
        """Reserva la vertical de un pad para maniobrar. ``False`` si espera.

        ``lat``/``lon`` son las del pad. Sin ellas no hay geometría que
        comprobar y se cae al comportamiento exclusivo.
        """
        with self._lock:
            self._expulsar_pads_caducados()
            if drone_id in self._pad_holders:
                return True

            solicitud = self._pad_waiting.get(drone_id)
            if solicitud is None:
                solicitud = _Maniobra(drone_id, lat, lon, maniobra,
                                      self._clock(), next(self._orden))
                self._pad_waiting[drone_id] = solicitud
            else:
                # El tipo de maniobra puede cambiar entre intentos (el mismo
                # dron vuelve a pedir la vertical para aterrizar).
                solicitud.lat, solicitud.lon, solicitud.tipo = lat, lon, maniobra

            if not self._puede_maniobrar(solicitud):
                return False

            del self._pad_waiting[drone_id]
            solicitud.desde = self._clock()
            self._pad_holders[drone_id] = solicitud
            return True

    def _puede_maniobrar(self, solicitud: _Maniobra) -> bool:
        """¿Puede este dron empezar su maniobra ahora mismo?

        Dos condiciones, y la segunda es la que evita la inanición: no basta
        con no estorbar a los que ya maniobran, hay que no estorbar tampoco a
        quien lleva esperando más y tiene más prioridad. Sin ella, el dron
        cuyo pad queda libre antes se cuela una y otra vez delante de un
        aterrizaje en espera, que es justo el que no puede permitírselo.
        """
        tope = self.vertiport_capacity
        if tope and len(self._pad_holders) >= tope:
            return False
        for ocupante in self._pad_holders.values():
            if not self._pads_compatibles(solicitud.lat, solicitud.lon,
                                          ocupante.lat, ocupante.lon):
                return False
        for otro in self._pad_waiting.values():
            if otro.drone_id == solicitud.drone_id:
                continue
            if otro.prioridad < solicitud.prioridad and not self._pads_compatibles(
                    solicitud.lat, solicitud.lon, otro.lat, otro.lon):
                return False
        return True

    def _pads_compatibles(self, lat_a, lon_a, lat_b, lon_b) -> bool:
        """¿Pueden estos dos pads operar a la vez?"""
        if None in (lat_a, lon_a, lat_b, lon_b):
            return False  # sin geometría, exclusión total
        return self.scenario.pads_can_operate_together(lat_a, lon_a, lat_b, lon_b)

    def _expulsar_pads_caducados(self) -> None:
        """Autocuración: un dron atascado no bloquea su vertical para siempre."""
        ahora = self._clock()
        for drone_id, ocupante in list(self._pad_holders.items()):
            if ahora - ocupante.desde > self.hub_hold_timeout_s:
                del self._pad_holders[drone_id]

    @property
    def vertiport_capacity(self) -> int:
        """Tope de maniobras simultáneas. 0 = solo lo limita la geometría."""
        return max(0, int(getattr(self.scenario, "vertiport_capacity", 0) or 0))

    def release_pad(self, drone_id: str) -> None:
        with self._lock:
            self._pad_holders.pop(drone_id, None)
            self._pad_waiting.pop(drone_id, None)

    def pad_holders(self) -> list[str]:
        with self._lock:
            return list(self._pad_holders)

    def pad_queue(self) -> list[str]:
        """Drones esperando vertical, en el orden en que entrarán."""
        with self._lock:
            return [m.drone_id for m in sorted(self._pad_waiting.values(),
                                               key=lambda m: m.prioridad)]

    def pad_holder(self) -> str | None:
        """Primer ocupante. Se conserva para el panel y los tests previos."""
        with self._lock:
            return next(iter(self._pad_holders), None)

    def acquire_hub(self, drone_id: str) -> bool:
        """Intenta entrar en el HUB. ``False`` si hay que esperar turno.

        El HUB es una zona con **aforo**, no un cerrojo: caben
        ``hub_capacity`` drones a la vez. Con aforo 1 se comporta igual que la
        exclusión mutua original, así que lo ya verificado no cambia.

        Reparto **por orden de llegada**. Sin cola, un dron que pide el HUB
        justo cuando se libera se lo lleva una y otra vez, y otro que lleva
        esperando desde hace minutos no entra nunca: inanición observada
        contra SITL, con un dron bloqueado en «volviendo» durante todo el
        experimento mientras su vecino encadenaba entregas.
        """
        with self._lock:
            if not self.scenario.hub_exclusive:
                return True
            self._expulsar_si_lleva_demasiado()
            if drone_id in self._hub_holders:
                return True
            if drone_id not in self._hub_queue:
                self._hub_queue.append(drone_id)
            # Solo entra si hay hueco y además le toca: sin la segunda
            # condición, un recién llegado adelantaría a los que esperan.
            if (len(self._hub_holders) < self.hub_capacity
                    and self._hub_queue[0] == drone_id):
                self._hub_holders[self._hub_queue.pop(0)] = self._clock()
                return True
            return False

    def _expulsar_si_lleva_demasiado(self) -> None:
        """Desaloja a los que llevan demasiado tiempo dentro del HUB.

        Autocuración sin hilo aparte: se comprueba al pedirlo. Un dron que se
        atasca ocupando plaza consumiría aforo hasta agotar el tiempo del
        tramo, que es mucho más largo.
        """
        ahora = self._clock()
        caducados = [d for d, desde in self._hub_holders.items()
                     if ahora - desde > self.hub_hold_timeout_s]
        for drone_id in caducados:
            del self._hub_holders[drone_id]

    def release_hub(self, drone_id: str) -> None:
        with self._lock:
            self._hub_holders.pop(drone_id, None)
            if drone_id in self._hub_queue:
                self._hub_queue.remove(drone_id)

    def hub_queue(self) -> list[str]:
        with self._lock:
            return list(self._hub_queue)

    def hub_holders(self) -> list[str]:
        with self._lock:
            return list(self._hub_holders)

    def hub_holder(self) -> str | None:
        """Primer ocupante del HUB.

        Se conserva por compatibilidad con el panel y los tests previos al
        aforo. Con capacidad mayor que 1 da una foto incompleta: para eso está
        ``hub_holders``.
        """
        with self._lock:
            return next(iter(self._hub_holders), None)

    def must_yield(self, drone_id: str, runtimes: dict) -> bool:
        """¿Debe este dron mantener posición por separación?

        Hay conflicto cuando dos drones en vuelo están a menos de
        ``separation_min_m`` en horizontal y a menos de ``alt_step_m`` en
        vertical: si están en capas distintas, la separación vertical basta.

        Cede el que tenga **más** batería. Suena al revés, pero es lo
        defendible: el que va más justo de energía tiene menos margen para
        esperas y maniobras, así que se le deja pasar. Los empates los rompe
        el identificador, para que el resultado sea determinista y solo uno de
        los dos ceda.
        """
        propio = runtimes.get(drone_id)
        if propio is None or not self._en_vuelo(propio):
            return False

        # El que ocupa el HUB tiene prioridad de paso. Sin esta regla aparece
        # un interbloqueo real, observado contra SITL: un dron retiene el HUB
        # mientras cede por separación ante otro que está esperando
        # precisamente ese HUB, y ninguno de los dos avanza nunca. Darle paso
        # al que ya está dentro de la zona controlada rompe el ciclo, y es
        # además lo razonable: se le deja salir en vez de bloquear el paso.
        if drone_id in self._hub_holders:
            return False

        for otro_id, otro in runtimes.items():
            if otro_id == drone_id or not self._en_vuelo(otro):
                continue
            if not self._en_conflicto(propio, otro):
                continue
            if otro.battery_wh < propio.battery_wh:
                return True
            if otro.battery_wh == propio.battery_wh and otro_id < drone_id:
                return True
        return False

    def conflicts(self, runtimes: dict) -> list[tuple[str, str]]:
        """Pares en conflicto, para el registro de eventos y el panel."""
        vivos = [(i, r) for i, r in runtimes.items() if self._en_vuelo(r)]
        pares = []
        for idx, (id_a, a) in enumerate(vivos):
            for id_b, b in vivos[idx + 1:]:
                if self._en_conflicto(a, b):
                    pares.append(tuple(sorted((id_a, id_b))))
        return pares

    # ── Internos ─────────────────────────────────────────────────────────
    @staticmethod
    def _en_vuelo(runtime) -> bool:
        return (runtime.state in BUSY_STATES
                and runtime.lat is not None
                and (runtime.alt or 0.0) > 0.5)

    def _en_conflicto(self, a, b) -> bool:
        horizontal_m = haversine_km(a.lat, a.lon, b.lat, b.lon) * 1000.0
        vertical_m = abs((a.alt or 0.0) - (b.alt or 0.0))
        return (horizontal_m < self.scenario.separation_min_m
                and vertical_m < self.scenario.alt_step_m)
