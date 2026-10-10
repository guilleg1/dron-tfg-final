"""Configuración del producto: rutas de datos y parámetros de vuelo.

Las rutas se resuelven relativas al paquete, no al directorio de trabajo, para
que el portal funcione se lance desde donde se lance.
"""

from pathlib import Path

# ── Rutas ────────────────────────────────────────────────────────────────────
PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = PACKAGE_DIR.parent
DATA_DIR = PACKAGE_DIR / "data"
WEB_DIR = PACKAGE_DIR / "web"
PROFILES_FILE = DATA_DIR / "route_profiles.json"
FLEET_FILE = DATA_DIR / "fleet.json"
SCENARIOS_FILE = DATA_DIR / "scenarios.json"

# ── Conexión SITL / Mission Planner ──────────────────────────────────────────
MISSION_PLANNER_TRANSPORT = "tcp"
MISSION_PLANNER_IP = "127.0.0.1"
MISSION_PLANNER_PORT = 5763
MISSION_PLANNER_CONNECTION_STRING = None   # Si se rellena, override completo
BAUD = 115200

# ── Vuelo ────────────────────────────────────────────────────────────────────
ORDER_TAKEOFF_ALT = 25          # Altitud de crucero para pedidos (m)
DEFAULT_TAKEOFF_ALT = 5         # Altitud de despegue manual (m)
TELEMETRY_INTERVAL_MS = 1000    # Intervalo de telemetría (ms)
