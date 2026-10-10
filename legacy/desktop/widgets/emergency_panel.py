"""
EmergencyPanel – Panel de emergencia siempre visible.
Solo 3 botones: RTL, LAND, HOVER. Sin confirmación.
"""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget, QHBoxLayout, QPushButton, QSizePolicy


class EmergencyPanel(QWidget):
    rtl_clicked = Signal()
    land_clicked = Signal()
    hover_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty("class", "emergency-panel")
        self.setFixedHeight(52)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 4, 12, 4)
        layout.setSpacing(10)

        layout.addStretch()

        self._rtl_btn = self._make_btn("RTL", "danger")
        self._land_btn = self._make_btn("LAND", "danger")
        self._hover_btn = self._make_btn("HOVER", "warning")

        self._rtl_btn.clicked.connect(self.rtl_clicked)
        self._land_btn.clicked.connect(self.land_clicked)
        self._hover_btn.clicked.connect(self.hover_clicked)

        layout.addWidget(self._rtl_btn)
        layout.addWidget(self._land_btn)
        layout.addWidget(self._hover_btn)

        layout.addStretch()

    def _make_btn(self, text, cls):
        btn = QPushButton(text)
        btn.setProperty("class", cls)
        btn.setMinimumWidth(120)
        btn.setFixedHeight(38)
        btn.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        return btn
