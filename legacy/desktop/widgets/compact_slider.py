"""
Sliders compactos de heading y velocidad, listos para insertar en paneles.
"""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout

from cliente.base_widgets import CompactSlider


class HeadingSpeedSliders(QWidget):
    """
    Contiene dos CompactSliders:
      - Heading (0–360°, step 5)
      - Speed   (0–20 m/s, step 1)

    Señales:
      heading_changed(float)
      speed_changed(float)
    """

    heading_changed = Signal(float)
    speed_changed = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.heading_slider = CompactSlider("Heading", 0, 360, step=5, unit="°")
        self.speed_slider = CompactSlider("Velocidad", 0, 20, step=1, unit=" m/s")

        layout.addWidget(self.heading_slider)
        layout.addWidget(self.speed_slider)

        self.heading_slider.value_changed.connect(self.heading_changed)
        self.speed_slider.value_changed.connect(self.speed_changed)
