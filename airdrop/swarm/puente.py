"""Puente del PC del laboratorio al portal desplegado.

Conecta el SITL de Mission Planner (o un dron real) de este PC con el portal en
la nube. Abre una conexión por dron hacia la pasarela del portal, se presenta
con el token y a partir de ahí reenvía los bytes en los dos sentidos entre el
SERIAL1 local del dron (127.0.0.1:5762+10i) y la nube. Si algo se corta, lo
vuelve a intentar cada pocos segundos, así que se puede dejar en marcha.

En el portal, pestaña Enjambre, hay que elegir «SITL de mi PC» como origen de
los drones.

    python -m airdrop.swarm.puente --servidor HOST:PUERTO --token TOKEN
    python -m airdrop.swarm.puente --servidor HOST:PUERTO --token TOKEN --instancias 0,1

HOST:PUERTO es el proxy TCP que Railway da al portal y TOKEN el valor de la
variable PASARELA_TOKEN del servicio.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

log = logging.getLogger("puente")

SERIAL1_BASE = 5762
PORT_STEP = 10
RETRY_S = 5.0


async def _pipe(reader, writer) -> None:
    try:
        while True:
            datos = await reader.read(4096)
            if not datos:
                break
            writer.write(datos)
            await writer.drain()
    except (ConnectionError, OSError):
        pass


async def un_dron(servidor: str, puerto: int, token: str, instancia: int,
                  local_host: str = "127.0.0.1") -> None:
    """Mantiene el túnel de un dron, reconectando cuando se cae."""
    local_port = SERIAL1_BASE + PORT_STEP * instancia
    while True:
        try:
            lr, lw = await asyncio.open_connection(local_host, local_port)
        except OSError:
            log.info("dron %d: sin SITL en %s:%d, reintento", instancia, local_host, local_port)
            await asyncio.sleep(RETRY_S)
            continue
        try:
            rr, rw = await asyncio.open_connection(servidor, puerto)
            rw.write(f"AIRDROP {token} {instancia}\n".encode())
            await rw.drain()
            respuesta = await asyncio.wait_for(rr.readline(), 10)
            if respuesta.strip() != b"OK":
                log.error("dron %d: el portal rechaza el puente (%s)", instancia,
                          respuesta.decode(errors="replace").strip() or "sin respuesta")
                lw.close()
                rw.close()
                await asyncio.sleep(RETRY_S * 6)
                continue
        except (OSError, asyncio.TimeoutError):
            log.info("dron %d: portal inalcanzable, reintento", instancia)
            lw.close()
            await asyncio.sleep(RETRY_S)
            continue
        log.info("dron %d: conectado", instancia)
        tareas = [asyncio.ensure_future(_pipe(lr, rw)), asyncio.ensure_future(_pipe(rr, lw))]
        await asyncio.wait(tareas, return_when=asyncio.FIRST_COMPLETED)
        for t in tareas:
            t.cancel()
        lw.close()
        rw.close()
        log.info("dron %d: túnel cerrado, reintento", instancia)
        await asyncio.sleep(RETRY_S)


async def _main(args) -> None:
    host, _, puerto = args.servidor.rpartition(":")
    instancias = [int(x) for x in args.instancias.split(",") if x.strip()]
    await asyncio.gather(*(un_dron(host, int(puerto), args.token, i) for i in instancias))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--servidor", required=True, help="HOST:PUERTO de la pasarela del portal")
    parser.add_argument("--token", required=True)
    parser.add_argument("--instancias", default="0,1,2,3")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    try:
        asyncio.run(_main(args))
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
