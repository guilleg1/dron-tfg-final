"""
Dark theme QSS para Desktop Drone Control v2.0 (Bordes rectos)
"""

DARK_THEME_QSS = """
/* ═══════════════════ GLOBAL ═══════════════════ */
QWidget {
    background-color: #1e1e1e;
    color: #e0e0e0;
    font-family: "Segoe UI", "Inter", "Roboto", sans-serif;
    font-size: 13px;
}

/* ═══════════════════ MAIN WINDOW ═══════════════════ */
QMainWindow {
    background-color: #1e1e1e;
}

/* ═══════════════════ GROUP BOXES / FRAMES ═══════════════════ */
QGroupBox {
    background-color: #2d2d2d;
    border: 1px solid #444444;
    border-radius: 0px;
    margin-top: 14px;
    padding: 10px 8px 8px 8px;
    font-weight: bold;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 2px 10px;
    color: #64b5f6;
    font-size: 12px;
}

QFrame[frameShape="4"],   /* HLine */
QFrame[frameShape="5"] {  /* VLine */
    color: #3d3d3d;
}

/* ═══════════════════ PUSH BUTTONS ═══════════════════ */
QPushButton {
    background-color: #3d3d3d;
    color: #e0e0e0;
    border: 1px solid #555555;
    border-radius: 0px;
    padding: 4px 12px;
    min-height: 24px;
}

QPushButton:hover {
    background-color: #4d4d4d;
    border-color: #64b5f6;
}

QPushButton:pressed {
    background-color: #555555;
}

QPushButton:disabled {
    background-color: #2a2a2a;
    color: #666666;
    border-color: #333333;
}

/* Clases de color especiales */
QPushButton[class="success"] {
    background-color: #2e7d32;
    border-color: #4caf50;
    color: white;
}
QPushButton[class="success"]:hover {
    background-color: #388e3c;
}

QPushButton[class="danger"] {
    background-color: #c62828;
    border-color: #f44336;
    color: white;
    font-weight: bold;
}
QPushButton[class="danger"]:hover {
    background-color: #d32f2f;
}

QPushButton[class="warning"] {
    background-color: #e65100;
    border-color: #ff9800;
    color: white;
}
QPushButton[class="warning"]:hover {
    background-color: #f57c00;
}

QPushButton[class="info"] {
    background-color: #1565c0;
    border-color: #2196f3;
    color: white;
}
QPushButton[class="info"]:hover {
    background-color: #1976d2;
}

QPushButton[class="nav"] {
    background-color: #37474f;
    border: 1px solid #546e7a;
    border-radius: 0px;
    font-weight: bold;
    font-size: 12px;
    color: #e0e0e0;
}
QPushButton[class="nav"]:hover {
    background-color: #455a64;
    border-color: #64b5f6;
}
QPushButton[class="nav"]:pressed {
    background-color: #1976d2;
    color: white;
}

/* ═══════════════════ LINE EDITS ═══════════════════ */
QLineEdit {
    background-color: #3d3d3d;
    border: 1px solid #555555;
    border-radius: 0px;
    padding: 4px 8px;
    color: #e0e0e0;
    selection-background-color: #2196f3;
}
QLineEdit:focus {
    border-color: #64b5f6;
}
QLineEdit:read-only {
    background-color: #2a2a2a;
    color: #a0a0a0;
}

/* ═══════════════════ COMBO BOX ═══════════════════ */
QComboBox {
    background-color: #3d3d3d;
    border: 1px solid #555555;
    border-radius: 0px;
    padding: 4px 8px;
    color: #e0e0e0;
    min-height: 24px;
}
QComboBox:hover {
    border-color: #64b5f6;
}
QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 20px;
    border-left: 1px solid #555555;
}
QComboBox QAbstractItemView {
    background-color: #2d2d2d;
    border: 1px solid #555555;
    color: #e0e0e0;
    selection-background-color: #2196f3;
}

/* ═══════════════════ SLIDERS ═══════════════════ */
QSlider::groove:horizontal {
    border: none;
    height: 6px;
    background: #3d3d3d;
    border-radius: 0px;
}
QSlider::handle:horizontal {
    background: #64b5f6;
    border: none;
    width: 16px;
    height: 16px;
    margin: -5px 0;
    border-radius: 0px;
}
QSlider::handle:horizontal:hover {
    background: #90caf9;
}
QSlider::sub-page:horizontal {
    background: #2196f3;
    border-radius: 0px;
}

/* ═══════════════════ LABELS ═══════════════════ */
QLabel {
    background: transparent;
    color: #e0e0e0;
}
QLabel[class="secondary"] {
    color: #a0a0a0;
    font-size: 11px;
}
QLabel[class="title"] {
    font-size: 15px;
    font-weight: bold;
    color: #64b5f6;
}
QLabel[class="value"] {
    font-size: 18px;
    font-weight: bold;
    color: #ffffff;
    font-family: "Consolas", "Courier New", monospace;
}

/* ═══════════════════ LIST WIDGET ═══════════════════ */
QListWidget {
    background-color: #2d2d2d;
    border: 1px solid #3d3d3d;
    border-radius: 0px;
    color: #e0e0e0;
    padding: 2px;
}
QListWidget::item {
    padding: 4px 6px;
    border-radius: 0px;
}
QListWidget::item:selected {
    background-color: #1565c0;
    color: white;
}
QListWidget::item:hover {
    background-color: #37474f;
}

/* ═══════════════════ TAB WIDGET ═══════════════════ */
QTabWidget::pane {
    border: 1px solid #3d3d3d;
    background-color: #2d2d2d;
    border-radius: 0px;
}
QTabBar::tab {
    background-color: #2d2d2d;
    color: #a0a0a0;
    padding: 6px 16px;
    border: 1px solid #3d3d3d;
    border-bottom: none;
    border-radius: 0px;
    margin-right: 2px;
}
QTabBar::tab:selected {
    background-color: #3d3d3d;
    color: #64b5f6;
    font-weight: bold;
}
QTabBar::tab:hover:!selected {
    background-color: #353535;
    color: #e0e0e0;
}

/* ═══════════════════ SCROLL BARS ═══════════════════ */
QScrollBar:vertical {
    background: #1e1e1e;
    width: 10px;
    border: none;
}
QScrollBar::handle:vertical {
    background: #555555;
    border-radius: 0px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover {
    background: #777777;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: none;
    border: none;
    height: 0px;
}

QScrollBar:horizontal {
    background: #1e1e1e;
    height: 10px;
    border: none;
}
QScrollBar::handle:horizontal {
    background: #555555;
    border-radius: 0px;
    min-width: 30px;
}
QScrollBar::handle:horizontal:hover {
    background: #777777;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal,
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
    background: none;
    border: none;
    width: 0px;
}

/* ═══════════════════ SPLITTER ═══════════════════ */
QSplitter::handle {
    background-color: #3d3d3d;
    width: 3px;
}
QSplitter::handle:hover {
    background-color: #64b5f6;
}

/* ═══════════════════ DIALOG ═══════════════════ */
QDialog {
    background-color: #1e1e1e;
}

QInputDialog QLabel {
    color: #e0e0e0;
}

/* ═══════════════════ MESSAGE BOX ═══════════════════ */
QMessageBox {
    background-color: #2d2d2d;
}
QMessageBox QLabel {
    color: #e0e0e0;
}

/* ═══════════════════ STATUS BAR ═══════════════════ */
QStatusBar {
    background-color: #2d2d2d;
    color: #a0a0a0;
    border-top: 1px solid #3d3d3d;
    font-size: 12px;
}

/* ═══════════════════ EMERGENCY PANEL ═══════════════════ */
QWidget[class="emergency-panel"] {
    background-color: #1a1a2e;
    border: 2px solid #c62828;
    border-radius: 0px;
    padding: 4px;
}
"""

def apply_theme(app):
    """Aplica el dark theme a la aplicación QApplication."""
    app.setStyleSheet(DARK_THEME_QSS)
