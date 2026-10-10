"""
StatusBar – Barra de estado inferior con texto de feedback.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel


class StatusBar(QWidget):
    """Barra de estado simple con texto y color."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(28)
        self.setStyleSheet("background-color: #2d2d2d; border-top: 1px solid #3d3d3d;")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 10, 0)

        self._label = QLabel("Listo")
        self._label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self._label.setStyleSheet("color: #a0a0a0; font-size: 12px; background: transparent;")
        layout.addWidget(self._label)

    def set_status(self, text, color="#a0a0a0"):
        """Actualiza el texto y color del status."""
        self._label.setText(text)
        self._label.setStyleSheet(
            "color: {}; font-size: 12px; background: transparent;".format(color)
        )

    def set_success(self, text):
        self.set_status(text, "#4caf50")

    def set_error(self, text):
        self.set_status(text, "#f44336")

    def set_warning(self, text):
        self.set_status(text, "#ff9800")

    def set_info(self, text):
        self.set_status(text, "#2196f3")
