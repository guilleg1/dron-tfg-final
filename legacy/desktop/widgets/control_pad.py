"""
ControlPad – Pad de navegación 8 direcciones + Stop.
Grid 3×3 con botones compactos.
"""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget, QGridLayout, QPushButton, QSizePolicy


# Distribución del pad (fila, columna) → (etiqueta, dirección)
_PAD_LAYOUT = [
    (0, 0, "NW", "NorthWest"),
    (0, 1, "N",  "North"),
    (0, 2, "NE", "NorthEast"),
    (1, 0, "W",  "West"),
    (1, 1, "■",  "Stop"),
    (1, 2, "E",  "East"),
    (2, 0, "SW", "SouthWest"),
    (2, 1, "S",  "South"),
    (2, 2, "SE", "SouthEast"),
]


class ControlPad(QWidget):
    """Emite direction_clicked(str) con la dirección seleccionada."""

    direction_clicked = Signal(str)

    def __init__(self, btn_size=40, parent=None):
        super().__init__(parent)

        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(3)

        self._buttons = {}
        self._last_btn = None

        for row, col, label, direction in _PAD_LAYOUT:
            btn = QPushButton(label)
            btn.setFixedSize(btn_size, btn_size)
            btn.setProperty("class", "nav")
            btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            btn.clicked.connect(lambda checked=False, d=direction, b=btn: self._on_click(d, b))
            grid.addWidget(btn, row, col)
            self._buttons[direction] = btn

    def _on_click(self, direction, btn):
        # Reset del botón anterior
        if self._last_btn is not None and self._last_btn is not btn:
            self._last_btn.setProperty("class", "nav")
            self._last_btn.style().unpolish(self._last_btn)
            self._last_btn.style().polish(self._last_btn)

        btn.setProperty("class", "success")
        btn.style().unpolish(btn)
        btn.style().polish(btn)
        self._last_btn = btn

        self.direction_clicked.emit(direction)
