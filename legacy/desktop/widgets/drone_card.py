"""
DroneCard – Tarjeta visual que muestra el estado de un dron.
Diseñada para el Fleet Panel lateral.
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPainter, QColor, QLinearGradient
from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, QSizePolicy,
)


# Colores por estado
_STATE_COLORS = {
    "connected": "#4caf50",
    "flying":    "#2196f3",
    "landed":    "#ff9800",
    "atHome":    "#4caf50",
    "returning": "#ff9800",
    "armed":     "#ffeb3b",
    "error":     "#f44336",
    "idle":      "#666666",
}

_STATE_LABELS = {
    "connected": "Conectado",
    "flying":    "✈ En vuelo",
    "landed":    "En tierra",
    "atHome":    "En casa",
    "returning": "Retornando",
    "armed":     "Armado",
    "error":     "Error",
    "idle":      "Desconectado",
}


class DroneCard(QFrame):
    """
    Tarjeta clickable de un dron.
    Emite clicked() al pulsar.
    """

    clicked = Signal()

    def __init__(self, drone_id="Dron-1", parent=None):
        super().__init__(parent)
        self._drone_id = drone_id
        self._selected = False
        self._state = "idle"
        self._order_text = "Sin pedido asignado"
        self._telemetry_text = "--"
        self._op_state = ""

        self.setCursor(Qt.PointingHandCursor)
        self.setFrameShape(QFrame.NoFrame)
        self.setFixedHeight(100)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._apply_style()

        self._build_ui()

    def _apply_style(self):
        border = "#64b5f6" if self._selected else "#3d3d3d"
        bg = "#2a3040" if self._selected else "#2d2d2d"
        self.setStyleSheet("""
            DroneCard {{
                background-color: {bg};
                border: 2px solid {border};
                border-radius: 0px;
                padding: 8px;
            }}
            DroneCard:hover {{
                background-color: #333845;
                border-color: #5a8ac0;
            }}
        """.format(bg=bg, border=border))

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(4)

        # Row 1: LED + nombre + estado
        row1 = QHBoxLayout()
        row1.setSpacing(8)

        self._led = QLabel("●")
        self._led.setFixedWidth(16)
        self._led.setStyleSheet("color: #666; font-size: 14px; background: transparent;")
        row1.addWidget(self._led)

        self._name_lbl = QLabel(self._drone_id)
        self._name_lbl.setStyleSheet(
            "color: #e0e0e0; font-weight: bold; font-size: 14px; background: transparent;"
        )
        row1.addWidget(self._name_lbl)
        row1.addStretch()

        self._state_lbl = QLabel("Desconectado")
        self._state_lbl.setStyleSheet(
            "color: #666; font-size: 12px; font-weight: bold; background: transparent;"
        )
        row1.addWidget(self._state_lbl)
        root.addLayout(row1)

        # Row 2: Pedido/operación
        self._order_lbl = QLabel(self._order_text)
        self._order_lbl.setStyleSheet(
            "color: #a0a0a0; font-size: 12px; background: transparent;"
        )
        self._order_lbl.setWordWrap(True)
        root.addWidget(self._order_lbl)

        # Row 3: Telemetría compacta
        self._telem_lbl = QLabel(self._telemetry_text)
        self._telem_lbl.setStyleSheet(
            "color: #78909c; font-size: 11px; font-family: 'Consolas', monospace; background: transparent;"
        )
        root.addWidget(self._telem_lbl)

    def set_selected(self, selected):
        self._selected = selected
        self._apply_style()

    def update_state(self, state):
        self._state = state
        color = _STATE_COLORS.get(state, "#666")
        label = _STATE_LABELS.get(state, state)
        self._led.setStyleSheet(
            "color: {}; font-size: 14px; background: transparent;".format(color)
        )
        self._state_lbl.setText(label)
        self._state_lbl.setStyleSheet(
            "color: {}; font-size: 12px; font-weight: bold; background: transparent;".format(color)
        )

    def update_order(self, text):
        self._order_text = text
        self._order_lbl.setText(text)

    def update_telemetry(self, alt, hdg, spd):
        txt = "Alt: {:.0f}m   Hdg: {:.0f}°   Spd: {:.1f}m/s".format(alt, hdg, spd)
        self._telem_lbl.setText(txt)

    def update_op_state(self, op_state):
        self._op_state = op_state or ""
        if op_state:
            self._order_lbl.setStyleSheet(
                "color: #64b5f6; font-size: 12px; background: transparent;"
            )
        else:
            self._order_lbl.setStyleSheet(
                "color: #a0a0a0; font-size: 12px; background: transparent;"
            )

    def mousePressEvent(self, event):
        self.clicked.emit()
        super().mousePressEvent(event)
