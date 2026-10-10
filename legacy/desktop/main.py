"""
Desktop Drone Control v2.0 – Punto de entrada.

Aplicación PySide6 con dark theme, mapa Leaflet.js,
panel de emergencia y seguimiento en tiempo real del dron.
"""

import sys
from pathlib import Path

# Asegurar que el directorio del proyecto esté en sys.path
PROJECT_DIR = Path(__file__).resolve().parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

from cliente.theme import apply_theme
from cliente.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Desktop Drone Control v2.0")
    app.setOrganizationName("ProyectoDrones")

    # Aplicar dark theme
    apply_theme(app)

    # Crear y mostrar ventana principal
    window = MainWindow()
    window.show()

    # Asegurar limpieza al salir
    def _on_quit():
        try:
            window.telemetry_svc.stop()
        except Exception:
            pass
        try:
            window.drone_svc.cleanup()
        except Exception:
            pass

    app.aboutToQuit.connect(_on_quit)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
