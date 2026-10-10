"""
Constantes globales del proyecto Desktop Drone Control v2.0
"""

from pathlib import Path

# ── Directorios ──────────────────────────────────────────────────────────────
PROJECT_DIR = Path(__file__).resolve().parent.parent
ASSETS_DIR = PROJECT_DIR / "assets"
PROFILES_FILE = PROJECT_DIR / "route_profiles.json"
DB_FILE = PROJECT_DIR / "operations.db"

# ── Conexión SITL / Mission Planner (modo LOCAL directo) ─────────────────────
MISSION_PLANNER_TRANSPORT = "tcp"
MISSION_PLANNER_IP = "127.0.0.1"
MISSION_PLANNER_PORT = 5763
MISSION_PLANNER_CONNECTION_STRING = None   # Si se rellena, override completo
BAUD = 115200

# ── Vuelo ────────────────────────────────────────────────────────────────────
ORDER_TAKEOFF_ALT = 25          # Altitud de despegue para pedidos (m)
DEFAULT_TAKEOFF_ALT = 5         # Altitud de despegue manual (m)
TELEMETRY_INTERVAL_MS = 1000    # Intervalo telemetría (ms)
TRAIL_MAX_POINTS = 20           # Puntos máximos del trail en el mapa
ALEJAR_DISTANCE_M = 50          # Distancia del comando "ALEJAR" (m)

# ── Colores del marker según velocidad (m/s) ────────────────────────────────
SPEED_COLOR_THRESHOLDS = [
    (1.0,  "#4caf50"),   # 0–1   → verde   (hovering)
    (5.0,  "#ffeb3b"),   # 1–5   → amarillo (lento)
    (10.0, "#ff9800"),   # 5–10  → naranja  (medio)
    (999,  "#f44336"),   # >10   → rojo     (rápido)
]

# ── Dark Theme – Paleta ──────────────────────────────────────────────────────
COLORS = {
    "bg_main":       "#1e1e1e",
    "bg_panel":      "#2d2d2d",
    "bg_field":      "#3d3d3d",
    "text_primary":  "#e0e0e0",
    "text_secondary":"#a0a0a0",
    "accent_success":"#4caf50",
    "accent_danger": "#f44336",
    "accent_warning":"#ff9800",
    "accent_info":   "#2196f3",
    "border_active": "#64b5f6",
}

# ── Dimensiones UI ───────────────────────────────────────────────────────────
BTN_WIDTH = 80
BTN_HEIGHT = 30
NAV_BTN_SIZE = 40
MAP_SPLIT_RATIO = 70   # porcentaje del mapa en el splitter
