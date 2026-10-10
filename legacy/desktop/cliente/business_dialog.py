"""
BusinessDialog – Gestor de clientes y pedidos migrado a PySide6.
"""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget,
    QWidget, QListWidget, QLabel, QLineEdit,
    QComboBox, QPushButton, QGridLayout, QGroupBox,
    QMessageBox, QSplitter, QSizePolicy,
)

from negocio.db_manager import DeliveryDataStore, VALID_ORDER_STATUSES
from cliente.base_widgets import DarkButton
from utils.constants import DB_FILE, PROFILES_FILE


class BusinessDialog(QDialog):
    def __init__(self, drone_svc, route_svc, parent=None):
        super().__init__(parent)
        self.drone_svc = drone_svc
        self.route_svc = route_svc
        self.setWindowTitle("Gestión de Clientes y Pedidos")
        self.resize(1000, 640)

        try:
            self.store = DeliveryDataStore(DB_FILE, PROFILES_FILE)
        except Exception as e:
            QMessageBox.critical(self, "Error DB", str(e))
            return

        self.clients_cache = []
        self.orders_cache = []
        self.client_map = {}
        self.sel_client_id = None
        self.sel_order_id = None

        self._build_ui()
        self._refresh_clients()
        self._refresh_orders_deps()

        # Auto-refresh pedidos
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh_orders)
        self._timer.start(1500)

    def _build_ui(self):
        root = QVBoxLayout(self)
        tabs = QTabWidget()
        tabs.addTab(self._build_clients_tab(), "Clientes")
        tabs.addTab(self._build_orders_tab(), "Pedidos")
        root.addWidget(tabs)

        self.status_lbl = QLabel("Listo")
        self.status_lbl.setStyleSheet("color: #a0a0a0; background: transparent; padding: 4px;")
        root.addWidget(self.status_lbl)

    def _set_status(self, text, color="#a0a0a0"):
        self.status_lbl.setText(text)
        self.status_lbl.setStyleSheet("color: {}; background: transparent; padding: 4px;".format(color))

    # ══════════════════ CLIENTS TAB ══════════════════

    def _build_clients_tab(self):
        tab = QWidget()
        lay = QHBoxLayout(tab)

        self.clients_list = QListWidget()
        self.clients_list.currentRowChanged.connect(self._on_select_client)
        lay.addWidget(self.clients_list, 2)

        form = QGroupBox("Detalle cliente")
        fl = QGridLayout(form)
        fl.addWidget(QLabel("Nombre"), 0, 0)
        self.c_name = QLineEdit()
        fl.addWidget(self.c_name, 0, 1)
        fl.addWidget(QLabel("Dirección"), 1, 0)
        self.c_addr = QLineEdit()
        fl.addWidget(self.c_addr, 1, 1)
        fl.addWidget(QLabel("Latitud"), 2, 0)
        self.c_lat = QLineEdit()
        self.c_lat.setReadOnly(True)
        fl.addWidget(self.c_lat, 2, 1)
        fl.addWidget(QLabel("Longitud"), 3, 0)
        self.c_lon = QLineEdit()
        self.c_lon.setReadOnly(True)
        fl.addWidget(self.c_lon, 3, 1)

        btns = QHBoxLayout()
        for text, fn in [("Alta", self._create_client), ("Modificar", self._update_client),
                         ("Baja", self._delete_client), ("Limpiar", self._clear_client)]:
            b = DarkButton(text)
            b.clicked.connect(fn)
            btns.addWidget(b)
        fl.addLayout(btns, 4, 0, 1, 2)
        lay.addWidget(form, 3)
        return tab

    def _refresh_clients(self):
        self.clients_cache = self.store.list_clients()
        self.clients_list.clear()
        for c in self.clients_cache:
            self.clients_list.addItem("#{} | {} | {}".format(c["id"], c["name"], c["address"]))

    def _on_select_client(self, row):
        if row < 0 or row >= len(self.clients_cache):
            return
        c = self.clients_cache[row]
        self.sel_client_id = c["id"]
        self.c_name.setText(c["name"])
        self.c_addr.setText(c["address"])
        self.c_lat.setText(str(c.get("latitude") or ""))
        self.c_lon.setText(str(c.get("longitude") or ""))

    def _clear_client(self):
        self.sel_client_id = None
        self.clients_list.clearSelection()
        self.c_name.clear()
        self.c_addr.clear()
        self.c_lat.clear()
        self.c_lon.clear()

    def _create_client(self):
        n, a = self.c_name.text().strip(), self.c_addr.text().strip()
        if not n or not a:
            self._set_status("Nombre y dirección obligatorios", "#f44336")
            return
        try:
            cid, lat, lon = self.store.create_client(n, a)
        except Exception as e:
            self._set_status("Error: " + str(e), "#f44336")
            return
        self._refresh_clients()
        self._refresh_orders_deps()
        self.c_lat.setText(str(lat))
        self.c_lon.setText(str(lon))
        self._set_status("Cliente creado ID " + str(cid), "#4caf50")

    def _update_client(self):
        if self.sel_client_id is None:
            self._set_status("Selecciona un cliente", "#f44336")
            return
        n, a = self.c_name.text().strip(), self.c_addr.text().strip()
        if not n or not a:
            self._set_status("Nombre y dirección obligatorios", "#f44336")
            return
        try:
            lat, lon = self.store.update_client(self.sel_client_id, n, a)
        except Exception as e:
            self._set_status("Error: " + str(e), "#f44336")
            return
        self._refresh_clients()
        self._refresh_orders_deps()
        self.c_lat.setText(str(lat))
        self.c_lon.setText(str(lon))
        self._set_status("Cliente modificado", "#4caf50")

    def _delete_client(self):
        if self.sel_client_id is None:
            self._set_status("Selecciona un cliente", "#f44336")
            return
        r = QMessageBox.question(self, "Confirmar", "¿Eliminar cliente?")
        if r != QMessageBox.Yes:
            return
        linked = self.store.count_orders_for_client(self.sel_client_id)
        delete_orders = False
        if linked > 0:
            r2 = QMessageBox.question(
                self, "Pedidos vinculados",
                "Tiene {} pedido(s). ¿Eliminar todo?".format(linked))
            if r2 != QMessageBox.Yes:
                return
            delete_orders = True
        try:
            self.store.delete_client(self.sel_client_id, delete_related=delete_orders)
        except Exception as e:
            self._set_status("Error: " + str(e), "#f44336")
            return
        self._clear_client()
        self._refresh_clients()
        self._refresh_orders_deps()
        self._set_status("Cliente eliminado", "#4caf50")

    # ══════════════════ ORDERS TAB ══════════════════

    def _build_orders_tab(self):
        tab = QWidget()
        lay = QHBoxLayout(tab)

        self.orders_list = QListWidget()
        self.orders_list.currentRowChanged.connect(self._on_select_order)
        lay.addWidget(self.orders_list, 2)

        form = QGroupBox("Detalle pedido")
        fl = QGridLayout(form)
        fl.addWidget(QLabel("Cliente"), 0, 0)
        self.o_client = QComboBox()
        fl.addWidget(self.o_client, 0, 1)
        fl.addWidget(QLabel("Peso (kg)"), 1, 0)
        self.o_weight = QLineEdit()
        fl.addWidget(self.o_weight, 1, 1)
        fl.addWidget(QLabel("Estado"), 2, 0)
        self.o_status = QComboBox()
        self.o_status.addItems(VALID_ORDER_STATUSES)
        fl.addWidget(self.o_status, 2, 1)
        fl.addWidget(QLabel("Ruta asignada"), 3, 0)
        self.o_route_lbl = QLabel("Sin asignar")
        self.o_route_lbl.setStyleSheet("color: #a0a0a0; background: transparent;")
        fl.addWidget(self.o_route_lbl, 3, 1)

        btns = QHBoxLayout()
        for text, fn in [("Alta", self._create_order), ("Modificar", self._update_order),
                         ("Baja", self._delete_order), ("Limpiar", self._clear_order)]:
            b = DarkButton(text)
            b.clicked.connect(fn)
            btns.addWidget(b)
        fl.addLayout(btns, 4, 0, 1, 2)

        self.start_route_btn = DarkButton("🚀 Empezar ruta asignada", "success")
        self.start_route_btn.clicked.connect(self._start_route)
        fl.addWidget(self.start_route_btn, 5, 0, 1, 2)

        lay.addWidget(form, 3)
        return tab

    def _refresh_orders_deps(self):
        clients = self.store.list_clients()
        self.client_map = {"{} - {}".format(c["id"], c["name"]): c["id"] for c in clients}
        self.o_client.clear()
        self.o_client.addItems(list(self.client_map.keys()))
        self._refresh_orders()

    def _refresh_orders(self):
        self.orders_cache = self.store.list_orders()
        self.orders_list.clear()
        for o in self.orders_cache:
            route = "{}/{}".format(o.get("assigned_profile_name") or "-", o.get("assigned_route_name") or "-")
            op = o.get("operational_state") or "-"
            self.orders_list.addItem("#{} | {} | {}kg | {} | {} | {}".format(
                o["id"], o["client_name"], o["weight_kg"], o["status"], op, route))

    def _on_select_order(self, row):
        if row < 0 or row >= len(self.orders_cache):
            return
        o = self.orders_cache[row]
        self.sel_order_id = o["id"]
        # Set client combo
        for label, cid in self.client_map.items():
            if cid == o["client_id"]:
                self.o_client.setCurrentText(label)
                break
        self.o_weight.setText(str(o["weight_kg"]))
        st = o["status"] if o["status"] in VALID_ORDER_STATUSES else "pendiente"
        self.o_status.setCurrentText(st)
        dist = o.get("assigned_distance_km")
        dist_s = "{:.2f} km".format(dist) if dist else "?"
        self.o_route_lbl.setText("{}/{} → {} ({})".format(
            o.get("assigned_profile_name") or "-",
            o.get("assigned_route_name") or "-",
            o.get("assigned_destination_name") or "-", dist_s))

    def _clear_order(self):
        self.sel_order_id = None
        self.orders_list.clearSelection()
        self.o_weight.clear()
        self.o_status.setCurrentText("pendiente")
        self.o_route_lbl.setText("Sin asignar")

    def _get_client_id(self):
        sel = self.o_client.currentText()
        if sel not in self.client_map:
            raise ValueError("Selecciona un cliente")
        return self.client_map[sel]

    def _assignment_text(self, a):
        d = a.get("distance_km") or a.get("assigned_distance_km")
        ds = "{:.2f} km".format(float(d)) if d else "?"
        return "{}/{} → {} ({})".format(
            a.get("profile_name") or a.get("assigned_profile_name") or "-",
            a.get("route_name") or a.get("assigned_route_name") or "-",
            a.get("destination_name") or a.get("assigned_destination_name") or "-", ds)

    def _create_order(self):
        try:
            cid = self._get_client_id()
            w = float(self.o_weight.text())
            if w <= 0:
                raise ValueError("Peso > 0")
            s = self.o_status.currentText()
            a = self.store.create_order(cid, w, s)
        except Exception as e:
            self._set_status("Error: " + str(e), "#f44336")
            return
        self._refresh_orders()
        self.o_route_lbl.setText(self._assignment_text(a))
        self._set_status("Pedido creado. Ruta: " + self._assignment_text(a), "#4caf50")

    def _update_order(self):
        if self.sel_order_id is None:
            self._set_status("Selecciona un pedido", "#f44336")
            return
        try:
            cid = self._get_client_id()
            w = float(self.o_weight.text())
            s = self.o_status.currentText()
            a = self.store.update_order(self.sel_order_id, cid, w, s)
        except Exception as e:
            self._set_status("Error: " + str(e), "#f44336")
            return
        self._refresh_orders()
        self.o_route_lbl.setText(self._assignment_text(a))
        self._set_status("Pedido modificado", "#4caf50")

    def _delete_order(self):
        if self.sel_order_id is None:
            self._set_status("Selecciona un pedido", "#f44336")
            return
        r = QMessageBox.question(self, "Confirmar", "¿Eliminar pedido?")
        if r != QMessageBox.Yes:
            return
        try:
            self.store.delete_order(self.sel_order_id)
        except Exception as e:
            self._set_status("Error: " + str(e), "#f44336")
            return
        self._clear_order()
        self._refresh_orders()
        self._set_status("Pedido eliminado", "#4caf50")

    def _start_route(self):
        if self.sel_order_id is None:
            self._set_status("Selecciona un pedido", "#f44336")
            return
        order = None
        for o in self.orders_cache:
            if o["id"] == self.sel_order_id:
                order = o
                break
        if not order:
            return
        pname = str(order.get("assigned_profile_name") or "")
        rname = str(order.get("assigned_route_name") or "")
        if not pname or not rname:
            self._set_status("Pedido sin ruta asignada", "#f44336")
            return
        try:
            self.route_svc.load()
            mission = self.route_svc.build_mission(pname, rname)
        except Exception as e:
            self._set_status("Error: " + str(e), "#f44336")
            return
        clat = order.get("client_latitude")
        clon = order.get("client_longitude")
        self.drone_svc.start_order_delivery({
            "order_id": int(order["id"]),
            "profile_name": pname, "route_name": rname,
            "client_latitude": float(clat) if clat else None,
            "client_longitude": float(clon) if clon else None,
            "mission": mission,
        })
        self._set_status("Pedido #{} iniciado".format(order["id"]), "#2196f3")
