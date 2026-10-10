"""
ManualControlsDialog – Diálogo con controles manuales del dron.
Se abre desde el botón ⚙ de la toolbar.
Contiene: pad de navegación, sliders de heading/velocidad, y telemetría start/stop.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel,
)

from cliente.base_widgets import DarkButton
from widgets.control_pad import ControlPad
from widgets.compact_slider import HeadingSpeedSliders


class ManualControlsDialog(QDialog):
    def __init__(self, drone_svc, parent=None):
        super().__init__(parent)
        self.drone_svc = drone_svc
        self.setWindowTitle("Control Manual del Dron")
        self.setMinimumSize(360, 400)
        self.setStyleSheet("background-color: #1e1e1e;")

        root = QVBoxLayout(self)
        root.setSpacing(10)

        # ── Pad de navegación ──
        nav_grp = QGroupBox("Navegación")
        nav_lay = QVBoxLayout(nav_grp)
        pad_row = QHBoxLayout()
        pad_row.addStretch()
        self.pad = ControlPad(42)
        pad_row.addWidget(self.pad)
        pad_row.addStretch()
        nav_lay.addLayout(pad_row)
        root.addWidget(nav_grp)

        # ── Sliders ──
        slider_grp = QGroupBox("Heading & Velocidad")
        slider_lay = QVBoxLayout(slider_grp)
        self.sliders = HeadingSpeedSliders()
        slider_lay.addWidget(self.sliders)
        root.addWidget(slider_grp)

        # ── Arm & Takeoff ──
        ctrl_grp = QGroupBox("Control")
        ctrl_lay = QHBoxLayout(ctrl_grp)
        self.arm_btn = DarkButton("Armar y Despegar", "warning")
        self.land_btn = DarkButton("Aterrizar", "danger")
        ctrl_lay.addWidget(self.arm_btn)
        ctrl_lay.addWidget(self.land_btn)
        root.addWidget(ctrl_grp)

        # ── Info ──
        info = QLabel("Usa estos controles solo si necesitas intervenir manualmente.")
        info.setWordWrap(True)
        info.setStyleSheet("color: #ff9800; font-size: 11px; padding: 4px; background: transparent;")
        root.addWidget(info)

        root.addStretch()

        # Señales
        self.pad.direction_clicked.connect(self._on_go)
        self.sliders.heading_changed.connect(lambda v: drone_svc.change_heading(int(v)))
        self.sliders.speed_changed.connect(lambda v: drone_svc.change_nav_speed(float(v)))
        self.arm_btn.clicked.connect(self._on_arm)
        self.land_btn.clicked.connect(drone_svc.land)

    def _on_go(self, direction):
        self.drone_svc.go(direction)

    def _on_arm(self):
        self.arm_btn.set_state_text("Despegando...", "warning")
        self.drone_svc.arm_and_takeoff()
