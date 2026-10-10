"""Pasarela MAVLink del portal desplegado: Mission Planner y el puente al PC.

El portal en la nube abre un único puerto TCP público (``PASARELA_PORT``, que
Railway publica con un proxy TCP) y por él atiende a dos tipos de cliente:

**Mission Planner** (con ``PASARELA_GCS=1``). Se conecta como a cualquier
dron, «TCP» y el host y puerto públicos, y ve los cuatro a la vez: la
pasarela abre SERIAL0 de cada instancia SITL, reenvía a Mission Planner los
mensajes de todas y a todas los que manda Mission Planner. Cada dron tiene su
``SYSID`` y por eso Mission Planner los distingue en el mismo enlace. Se
reenvían mensajes enteros, nunca trozos: con cuatro flujos mezclados byte a
byte, un mensaje cortado por otro se pierde y Mission Planner ve el enlace
lleno de errores.

**El puente** (``python -m airdrop.swarm.puente`` en el PC del laboratorio).
Cuando los drones son el SITL de Mission Planner en un PC detrás de un router,
la nube no puede conectarse a él; es el PC el que llama. El puente abre una
conexión por dron, se presenta con ``AIRDROP <token> <instancia>`` y desde
ese momento la pasarela sirve en 127.0.0.1:6762+10i lo que llega por ella. El
enlace MAVLink del enjambre se conecta a ese puerto sin saber que al otro
lado hay un túnel. El mismo puente servirá para un dron real con módem 4G.

Mission Planner no se presenta: si el cliente no manda nada en dos segundos,
o lo primero que manda es un mensaje MAVLink, es una estación de tierra.

La pasarela corre en su propio hilo con un bucle asyncio y no toca el
enjambre: lo único que comparte con él son puertos de 127.0.0.1.
"""

from __future__ import annotations

import asyncio
import hmac
import logging
import os
import threading

log = logging.getLogger(__name__)

HELLO = b"AIRDROP "
SERIAL0_BASE = 5760
BRIDGE_BASE = 6762       # puertos locales del puente: 6762 + 10*instancia
PORT_STEP = 10
HELLO_TIMEOUT_S = 2.0


def bridge_port(instance: int) -> int:
    return BRIDGE_BASE + PORT_STEP * int(instance)


# ── Troceado de MAVLink ──────────────────────────────────────────────────────

def split_frames(buffer: bytearray) -> list[bytes]:
    """Saca del buffer los mensajes MAVLink completos y deja el resto.

    Solo mira la cabecera (v1 0xFE, v2 0xFD) para saber la longitud; no
    comprueba el CRC, que ya comprueban los extremos. Un byte que no empieza
    un mensaje se descarta.
    """
    frames = []
    while buffer:
        magic = buffer[0]
        if magic == 0xFD:
            if len(buffer) < 10:
                break
            longitud = 12 + buffer[1] + (13 if buffer[2] & 0x01 else 0)
        elif magic == 0xFE:
            if len(buffer) < 6:
                break
            longitud = 8 + buffer[1]
        else:
            del buffer[0]
            continue
        if len(buffer) < longitud:
            break
        frames.append(bytes(buffer[:longitud]))
        del buffer[:longitud]
    return frames


class Pasarela:
    def __init__(self, port: int, token: str = "", gcs_enabled: bool = False,
                 instances=lambda: [], on_agent=None, host: str | None = None):
        """``instances`` devuelve las instancias SITL locales (para Mission
        Planner); ``on_agent(instancia)`` se llama cuando un puente se conecta,
        para que el enjambre reconecte ese dron."""
        self.port = int(port)
        self.token = token or ""
        self.gcs_enabled = gcs_enabled
        self.instances = instances
        self.on_agent = on_agent
        self.host = host
        self.loop = None
        self._agents: dict[int, tuple] = {}
        self._local_servers: dict[int, asyncio.base_events.Server] = {}
        self._gcs_clients: set = set()
        self._upstreams: dict[int, tuple] = {}
        self._attached: set[int] = set()
        # Conexión del enjambre que recibe cada dron. Al rehacer el enjambre
        # llega la nueva antes de que se cierre la vieja: manda la última.
        self._locales: dict[int, asyncio.StreamWriter] = {}
        self._ready = threading.Event()

    # ── Arranque ─────────────────────────────────────────────────────────
    def start(self) -> None:
        hilo = threading.Thread(target=self._run, name="pasarela-mavlink", daemon=True)
        hilo.start()
        self._ready.wait(timeout=5)

    def _run(self) -> None:
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self._serve())
        self._ready.set()
        self.loop.run_forever()

    async def _serve(self) -> None:
        # host None: todas las interfaces, IPv4 e IPv6 (la red de Railway es IPv6).
        await asyncio.start_server(self._handle, self.host, self.port)
        log.info("pasarela MAVLink en el puerto %d", self.port)

    def status(self) -> dict:
        return {"port": self.port, "agents": sorted(self._agents),
                "gcs_clients": len(self._gcs_clients), "gcs_enabled": self.gcs_enabled}

    # ── Clasificación del cliente ────────────────────────────────────────
    async def _handle(self, reader, writer) -> None:
        try:
            primero = await asyncio.wait_for(reader.read(256), HELLO_TIMEOUT_S)
        except asyncio.TimeoutError:
            primero = b""
        if primero.startswith(HELLO):
            await self._agent(primero, reader, writer)
        elif self.gcs_enabled:
            await self._gcs(primero, reader, writer)
        else:
            writer.close()

    # ── Puente ───────────────────────────────────────────────────────────
    async def _agent(self, primero, reader, writer) -> None:
        cabecera, _, resto = primero.partition(b"\n")
        partes = cabecera.decode(errors="replace").split()
        try:
            token, instance = partes[1], int(partes[2])
        except (IndexError, ValueError):
            writer.close()
            return
        if not self.token or not hmac.compare_digest(token, self.token):
            log.warning("puente rechazado: token incorrecto")
            writer.write(b"ERROR token\n")
            writer.close()
            return
        anterior = self._agents.pop(instance, None)
        if anterior is not None:
            anterior[1].close()
        cola = asyncio.Queue()
        if resto:
            cola.put_nowait(resto)
        self._agents[instance] = (reader, writer, cola)
        await self._ensure_local_server(instance)
        writer.write(b"OK\n")
        log.info("puente conectado: instancia %d", instance)
        if self.on_agent is not None:
            threading.Thread(target=self.on_agent, args=(instance,), daemon=True).start()
        try:
            while True:
                datos = await reader.read(4096)
                if not datos:
                    break
                # Sin el enjambre conectado se tira: si se guardara, al
                # conectarse recibiría de golpe minutos de telemetría vieja.
                if instance in self._attached:
                    await cola.put(datos)
        finally:
            if self._agents.get(instance, (None, None))[1] is writer:
                del self._agents[instance]
                await cola.put(None)
            writer.close()
            log.info("puente desconectado: instancia %d", instance)

    async def _ensure_local_server(self, instance: int) -> None:
        if instance in self._local_servers:
            return

        async def local(reader, writer, instance=instance):
            agente = self._agents.get(instance)
            if agente is None:
                writer.close()
                return
            _, agent_writer, cola = agente
            anterior = self._locales.get(instance)
            if anterior is not None:
                anterior.close()
            self._locales[instance] = writer
            self._attached.add(instance)

            async def subida():
                while True:
                    datos = await reader.read(4096)
                    if not datos:
                        break
                    agent_writer.write(datos)
                    await agent_writer.drain()

            async def bajada():
                while True:
                    datos = await cola.get()
                    if datos is None:
                        break
                    writer.write(datos)
                    await writer.drain()

            tareas = [asyncio.ensure_future(subida()), asyncio.ensure_future(bajada())]
            await asyncio.wait(tareas, return_when=asyncio.FIRST_COMPLETED)
            for t in tareas:
                t.cancel()
            # Solo si sigue siendo la vigente: si ya la ha relevado otra, quitar
            # la marca dejaría al enlace nuevo sin telemetría.
            if self._locales.get(instance) is writer:
                del self._locales[instance]
                self._attached.discard(instance)
            writer.close()

        self._local_servers[instance] = await asyncio.start_server(
            local, "127.0.0.1", bridge_port(instance))

    # ── Mission Planner ──────────────────────────────────────────────────
    async def _gcs(self, primero, reader, writer) -> None:
        self._gcs_clients.add(writer)
        log.info("Mission Planner conectado (%d)", len(self._gcs_clients))
        await self._ensure_upstreams()
        buffer = bytearray(primero)
        try:
            while True:
                for frame in split_frames(buffer):
                    for _, up_writer in self._upstreams.values():
                        up_writer.write(frame)
                datos = await reader.read(4096)
                if not datos:
                    break
                buffer.extend(datos)
        except (ConnectionError, OSError):
            pass
        finally:
            self._gcs_clients.discard(writer)
            writer.close()
            if not self._gcs_clients:
                for _, up_writer in self._upstreams.values():
                    up_writer.close()
                self._upstreams.clear()

    async def _ensure_upstreams(self) -> None:
        """Una conexión por instancia SITL, a su SERIAL0, mientras haya alguna
        estación de tierra conectada (SERIAL0 admite un solo cliente)."""
        for instance in self.instances():
            if instance in self._upstreams:
                continue
            try:
                r, w = await asyncio.open_connection(
                    "127.0.0.1", SERIAL0_BASE + PORT_STEP * int(instance))
            except OSError:
                continue
            self._upstreams[instance] = (r, w)
            asyncio.ensure_future(self._fan_out(instance, r))

    async def _fan_out(self, instance, reader) -> None:
        buffer = bytearray()
        while True:
            datos = await reader.read(4096)
            if not datos:
                break
            buffer.extend(datos)
            for frame in split_frames(buffer):
                for gcs in list(self._gcs_clients):
                    gcs.write(frame)
        self._upstreams.pop(instance, None)


def from_env(instances, on_agent=None) -> Pasarela | None:
    """La pasarela del portal, si ``PASARELA_PORT`` está definido."""
    puerto = os.environ.get("PASARELA_PORT")
    if not puerto:
        return None
    if puerto == os.environ.get("PORT"):
        # Pasó en Railway: al crear el proxy TCP la plataforma le dio a PORT el
        # mismo valor y la pasarela, que abre antes, le quitaba el puerto a la
        # web. Mejor un portal sin pasarela que un portal caído.
        log.error("PASARELA_PORT coincide con PORT (%s): la pasarela no se abre", puerto)
        return None
    return Pasarela(
        port=int(puerto),
        token=os.environ.get("PASARELA_TOKEN", ""),
        gcs_enabled=(os.environ.get("PASARELA_GCS") or "").lower() in ("1", "true", "si", "sí"),
        instances=instances,
        on_agent=on_agent,
    )
