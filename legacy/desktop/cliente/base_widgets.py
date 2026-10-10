"""
Widgets base reutilizables: DarkButton, StatusIndicator, CompactSlider.
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPainter, QColor
from PySide6.QtWidgets import (
    QPushButton, QWidget, QHBoxLayout, QVBoxLayout,
    QLabel, QSlider, QSizePolicy,
)


class DarkButton(QPushButton):
    """Botón compacto estilizado para el dark theme."""

    def __init__(self, text="", btn_class="", parent=None):
        super().__init__(text, parent)
        self.setMinimumHeight(28)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        if btn_class:
            self.setProperty("class", btn_class)

    def set_class(self, cls):
        """Cambia la clase CSS del botón y refresca estilos."""
        self.setProperty("class", cls)
        self.style().unpolish(self)
        self.style().polish(self)

    def set_state_text(self, text, cls=""):
        """Cambia texto y clase a la vez (útil para feedback de estado)."""
        self.setText(text)
        if cls:
            self.set_class(cls)


class StatusIndicator(QWidget):
    """LED circular que indica estado con un color."""

    def __init__(self, size=14, parent=None):
        super().__init__(parent)
        self._color = QColor("#a0a0a0")
        self._size = size
        self.setFixedSize(size + 4, size + 4)

    def set_color(self, hex_color):
        self._color = QColor(hex_color)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(self._color)
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(2, 2, self._size, self._size)
        painter.end()


class CompactSlider(QWidget):
    """
    Slider compacto con label de título, valor actual y unidad.
    Emite value_changed(int_or_float) al soltar el slider.
    """

    value_changed = Signal(float)

    def __init__(self, title, min_val, max_val, step=1, unit="", parent=None):
        super().__init__(parent)
        self._step = step
        self._unit = unit

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        # Cabecera: título + valor
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)

        self._title_lbl = QLabel(title)
        self._title_lbl.setProperty("class", "secondary")
        header.addWidget(self._title_lbl)

        header.addStretch()

        self._value_lbl = QLabel(str(min_val) + unit)
        self._value_lbl.setAlignment(Qt.AlignRight)
        self._value_lbl.setStyleSheet("color: #64b5f6; font-weight: bold;")
        header.addWidget(self._value_lbl)

        layout.addLayout(header)

        # Slider
        self._slider = QSlider(Qt.Horizontal)
        self._slider.setMinimum(int(min_val / step))
        self._slider.setMaximum(int(max_val / step))
        self._slider.setValue(int(min_val / step))
        self._slider.setTickPosition(QSlider.NoTicks)
        layout.addWidget(self._slider)

        self._slider.valueChanged.connect(self._on_value_changed)
        self._slider.sliderReleased.connect(self._on_released)

    def _on_value_changed(self, raw):
        val = raw * self._step
        if self._step >= 1:
            self._value_lbl.setText(str(int(val)) + self._unit)
        else:
            self._value_lbl.setText("{:.1f}{}".format(val, self._unit))

    def _on_released(self):
        val = self._slider.value() * self._step
        self.value_changed.emit(val)

    def value(self):
        return self._slider.value() * self._step

    def set_value(self, v):
        self._slider.setValue(int(v / self._step))
