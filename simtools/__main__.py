"""Arranca la consola de simulación.

    python -m simtools

Escucha solo en 127.0.0.1: es una herramienta de banco, no un servicio.
"""

from __future__ import annotations

import os
import sys

import uvicorn

PUERTO = int(os.environ.get("SIMTOOLS_PORT") or 8090)


def main() -> int:
    print(f"Consola de simulación en http://127.0.0.1:{PUERTO}")
    print("El portal sigue siendo el de siempre: ./run_local.ps1 en el 8080.")
    uvicorn.run("simtools.app:app", host="127.0.0.1", port=PUERTO, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
