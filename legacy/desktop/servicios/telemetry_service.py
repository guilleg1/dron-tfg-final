"""
TelemetryService – Emite datos de telemetría a 1Hz mediante QTimer.
"""

from PySide6.QtCore import QObject, QTimer, Signal


class TelemetryService(QObject):
    telemetry_tick = Signal(dict)

    def __init__(self, drone_service, interval_ms=1000, parent=None):
        super().__init__(parent)
        self._drone_service = drone_service
        self._latest = {}
        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self._emit_tick)
        self._drone_service.telemetry_updated.connect(self._on_telemetry)

    def _on_telemetry(self, data):
        self._latest = data

    def _emit_tick(self):
        if self._latest:
            self.telemetry_tick.emit(self._latest)

    def start(self):
        self._drone_service.start_telemetry()
        self._timer.start()

    def stop(self):
        self._timer.stop()
        self._drone_service.stop_telemetry()

    def is_running(self):
        return self._timer.isActive()
