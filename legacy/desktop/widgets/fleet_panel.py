"""
FleetPanel – Panel lateral con lista de drones y detalle expandible.
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea,
    QFrame, QSizePolicy, QPushButton,
)

from widgets.drone_card import DroneCard


class FleetPanel(QWidget):
    """
    Panel lateral derecho con:
      - Cabecera "Flota"
      - Lista scrollable de DroneCards
      - Panel de detalle (expandible al clickar)

    Señales:
      drone_selected(str)  – id del dron seleccionado
      accept_order_clicked(int)  – id del pedido a aceptar
      preview_order_clicked(int)  – id del pedido a previsualizar
      unassign_mission_clicked()  – botón para abortar/desasignar
    """

    drone_selected = Signal(str)
    accept_order_clicked = Signal(int)
    preview_order_clicked = Signal(int)
    unassign_mission_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(320)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)

        self._cards = {}
        self._selected_id = None

        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(6)

        # ── Header ──
        header = QHBoxLayout()
        title = QLabel("Flota")
        title.setStyleSheet(
            "color: #64b5f6; font-size: 16px; font-weight: bold; background: transparent;"
        )
        header.addWidget(title)
        header.addStretch()

        self._count_lbl = QLabel("0 drones")
        self._count_lbl.setStyleSheet(
            "color: #78909c; font-size: 12px; background: transparent;"
        )
        header.addWidget(self._count_lbl)
        root.addLayout(header)

        # ── Scroll area for cards ──
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        self._cards_container = QWidget()
        self._cards_layout = QVBoxLayout(self._cards_container)
        self._cards_layout.setContentsMargins(0, 0, 0, 0)
        self._cards_layout.setSpacing(6)
        self._cards_layout.addStretch()

        self._scroll.setWidget(self._cards_container)
        root.addWidget(self._scroll, 1)

        # ── Detail Panel ──
        self._detail = _DetailPanel()
        self._detail.unassign_clicked.connect(self.unassign_mission_clicked)
        self._detail.setVisible(False)
        root.addWidget(self._detail, 0)

        # ── Pending Orders ──
        pend_hdr = QLabel("Pedidos Pendientes")
        pend_hdr.setStyleSheet(
            "color: #ff9800; font-size: 14px; font-weight: bold; margin-top: 10px; background: transparent;"
        )
        root.addWidget(pend_hdr)

        self._pending_scroll = QScrollArea()
        self._pending_scroll.setWidgetResizable(True)
        self._pending_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._pending_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        self._pending_container = QWidget()
        self._pending_layout = QVBoxLayout(self._pending_container)
        self._pending_layout.setContentsMargins(0, 0, 0, 0)
        self._pending_layout.setSpacing(4)
        self._pending_layout.addStretch()
        self._pending_scroll.setWidget(self._pending_container)
        root.addWidget(self._pending_scroll, 1)

    def update_pending_orders(self, orders):
        # Clear existing
        while self._pending_layout.count() > 1:
            item = self._pending_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        pending = [o for o in orders if o.get("status") == "pendiente"]
        
        if not pending:
            lbl = QLabel("No hay pedidos pendientes")
            lbl.setStyleSheet("color: #78909c; font-size: 12px; font-style: italic; background: transparent;")
            self._pending_layout.insertWidget(0, lbl)
            return

        for o in pending:
            w = QFrame()
            w.setStyleSheet("background-color: #2d2d2d; border: 1px solid #3d3d3d; border-radius: 0px; padding: 6px;")
            lay = QVBoxLayout(w)
            lay.setContentsMargins(4, 4, 4, 4)
            lay.setSpacing(2)
            
            lbl1 = QLabel(f"#{o.get('id')} - {o.get('client_name')}")
            lbl1.setStyleSheet("color: #e0e0e0; font-weight: bold; font-size: 12px; border: none; background: transparent;")
            lay.addWidget(lbl1)
            
            lbl2 = QLabel(f"{o.get('weight_kg')}kg | Ruta: {o.get('assigned_route_name')}")
            lbl2.setStyleSheet("color: #a0a0a0; font-size: 11px; border: none; background: transparent;")
            lay.addWidget(lbl2)
            
            btn_lay = QHBoxLayout()
            btn_lay.setContentsMargins(0,0,0,0)

            btn_view = QPushButton("Ver")
            btn_view.setToolTip("Ver ruta en el mapa")
            btn_view.setStyleSheet("background-color: #e0e0e0; color: #333333; font-weight: bold; border: 1px solid #cccccc; padding: 4px;")
            btn_view.setFixedWidth(40)
            btn_view.clicked.connect(lambda checked=False, oid=o.get('id'): self.preview_order_clicked.emit(oid))

            btn_acc = QPushButton("Aceptar")
            btn_acc.setStyleSheet("background-color: #ff9800; color: white; font-weight: bold; border: none; padding: 4px; border-radius: 0px;")
            btn_acc.clicked.connect(lambda checked=False, oid=o.get('id'): self.accept_order_clicked.emit(oid))
            
            btn_lay.addWidget(btn_view)
            btn_lay.addWidget(btn_acc, 1)
            lay.addLayout(btn_lay)
            
            self._pending_layout.insertWidget(self._pending_layout.count() - 1, w)

    def add_drone(self, drone_id):
        """Añade una tarjeta de dron al panel."""
        if drone_id in self._cards:
            return
        card = DroneCard(drone_id)
        card.clicked.connect(lambda did=drone_id: self._on_card_clicked(did))
        # Insert before stretch
        self._cards_layout.insertWidget(self._cards_layout.count() - 1, card)
        self._cards[drone_id] = card
        self._count_lbl.setText("{} dron{}".format(
            len(self._cards), "es" if len(self._cards) > 1 else ""
        ))

    def _on_card_clicked(self, drone_id):
        # Deselect previous
        if self._selected_id and self._selected_id in self._cards:
            self._cards[self._selected_id].set_selected(False)

        self._selected_id = drone_id
        self._cards[drone_id].set_selected(True)
        self._detail.setVisible(True)
        self.drone_selected.emit(drone_id)

    def get_card(self, drone_id):
        return self._cards.get(drone_id)

    def get_detail(self):
        return self._detail

    def selected_id(self):
        return self._selected_id


class _DetailPanel(QFrame):
    """Panel de detalle expandible debajo de las tarjetas."""
    unassign_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("""
            _DetailPanel {
                background-color: #252535;
                border: 1px solid #3d3d3d;
                border-radius: 0px;
                padding: 8px;
            }
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(4)

        hdr_lay = QHBoxLayout()
        hdr = QLabel("Detalle")
        hdr.setStyleSheet(
            "color: #64b5f6; font-weight: bold; font-size: 13px; background: transparent;"
        )
        hdr_lay.addWidget(hdr)
        
        self.btn_unassign = QPushButton("Desasignar")
        self.btn_unassign.setStyleSheet("background-color: #f44336; color: white; font-size: 10px; font-weight: bold; border: none; padding: 2px 6px;")
        self.btn_unassign.setVisible(False)
        self.btn_unassign.clicked.connect(self._on_unassign)
        hdr_lay.addWidget(self.btn_unassign, 0, Qt.AlignRight)
        
        root.addLayout(hdr_lay)

        self._fields = {}
        for key, label in [
            ("order", "Pedido"),
            ("client", "Cliente"),
            ("address", "Dirección"),
            ("weight", "Peso"),
            ("op_state", "Estado operativo"),
            ("route", "Ruta"),
            ("alt", "Altitud"),
            ("hdg", "Heading"),
            ("spd", "Velocidad"),
            ("lat", "Latitud"),
            ("lon", "Longitud"),
        ]:
            row = QHBoxLayout()
            row.setSpacing(6)
            lbl = QLabel(label + ":")
            lbl.setFixedWidth(100)
            lbl.setStyleSheet("color: #78909c; font-size: 11px; background: transparent;")
            val = QLabel("--")
            val.setStyleSheet("color: #e0e0e0; font-size: 12px; background: transparent;")
            val.setWordWrap(True)
            row.addWidget(lbl)
            row.addWidget(val, 1)
            root.addLayout(row)
            self._fields[key] = val

    def update_field(self, key, value):
        if key in self._fields:
            self._fields[key].setText(str(value))

    def update_telemetry(self, data):
        self.update_field("alt", "{:.1f} m".format(data.get("alt", 0)))
        self.update_field("hdg", "{:.0f}°".format(data.get("heading", 0)))
        spd = data.get("groundSpeed", data.get("speed", 0))
        self.update_field("spd", "{:.1f} m/s".format(spd))
        lat = data.get("lat")
        lon = data.get("lon")
        if lat is not None:
            self.update_field("lat", "{:.6f}".format(lat))
        if lon is not None:
            self.update_field("lon", "{:.6f}".format(lon))

    def update_order_info(self, order):
        """order: dict from list_orders or None."""
        if order is None:
            self.update_field("order", "Sin pedido")
            self.update_field("client", "--")
            self.update_field("address", "--")
            self.update_field("weight", "--")
            self.update_field("op_state", "--")
            self.update_field("route", "--")
            return
        self.update_field("order", "#{} ({})".format(order.get("id", "?"), order.get("status", "?")))
        self.update_field("client", str(order.get("client_name", "--")))
        self.update_field("address", "--")  # Could be fetched from clients table
        self.update_field("weight", "{} kg".format(order.get("weight_kg", "?")))
        self.update_field("op_state", str(order.get("operational_state") or "pendiente"))
        self.update_field("route", "{} / {}".format(
            order.get("assigned_profile_name") or "-",
            order.get("assigned_route_name") or "-",
        ))
        self.btn_unassign.setVisible(True)

    def _on_unassign(self):
        self.unassign_clicked.emit()
