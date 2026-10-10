"""
MapWidget – Mapa Leaflet.js embebido en QWebEngineView.

Métodos Python → JavaScript:
  - update_drone_position(lat, lon, heading, speed)
  - add_waypoint(lat, lon, label)
  - clear_waypoints()
  - draw_route(waypoints)
  - set_view(lat, lon, zoom)
  - set_auto_follow(enabled)
  - clear_trail()
  - reset_map()
"""

import json
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEngineSettings

from utils.constants import ASSETS_DIR


class MapWidget(QWebEngineView):
    """Mapa 2D con Leaflet.js para seguimiento del dron en tiempo real."""

    def __init__(self, parent=None):
        super().__init__(parent)

        # Configurar WebEngine
        settings = self.settings()
        settings.setAttribute(QWebEngineSettings.JavascriptEnabled, True)
        settings.setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, True)
        settings.setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls, True)

        self._ready = False

        # Cargar map.html
        map_file = ASSETS_DIR / "map.html"
        if map_file.exists():
            self.setUrl(QUrl.fromLocalFile(str(map_file)))
        else:
            self.setHtml("<h1 style='color:red;background:#1e1e1e;'>map.html no encontrado</h1>")

        self.loadFinished.connect(self._on_load_finished)

    def _on_load_finished(self, ok):
        self._ready = ok

    def _run_js(self, js_code):
        """Ejecuta JavaScript en el mapa si está listo."""
        if self._ready:
            self.page().runJavaScript(js_code)

    # ── API pública ──────────────────────────────────────────────────────────

    def update_drone_position(self, lat, lon, heading, speed):
        """Actualiza posición, heading y color del dron en el mapa."""
        self._run_js(
            "updateDronePosition({}, {}, {}, {});".format(lat, lon, heading, speed)
        )

    def add_waypoint(self, lat, lon, label):
        """Añade un marcador de waypoint."""
        self._run_js(
            "addWaypoint({}, {}, {});".format(lat, lon, json.dumps(str(label)))
        )

    def clear_waypoints(self):
        """Elimina todos los waypoints y rutas."""
        self._run_js("clearWaypoints();")

    def draw_route(self, waypoints):
        """
        Dibuja una polyline de ruta.
        waypoints: lista de dicts con 'lat' y 'lon'.
        """
        data = json.dumps([{"lat": w["lat"], "lon": w["lon"]} for w in waypoints])
        self._run_js("drawRoute({});".format(data))

    def set_view(self, lat, lon, zoom=17):
        """Centra la vista del mapa."""
        self._run_js("setView({}, {}, {});".format(lat, lon, zoom))

    def set_auto_follow(self, enabled):
        """Activa/desactiva auto-follow del dron."""
        self._run_js("setAutoFollow({});".format("true" if enabled else "false"))

    def clear_trail(self):
        """Limpia el trail del dron."""
        self._run_js("clearTrail();")

    def reset_map(self):
        """Resetea todo: dron, trail, waypoints."""
        self._run_js("resetMap();")
