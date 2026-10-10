

from PySide6.QtCore import Qt, Slot, QTimer
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QToolBar, QLabel, QSizePolicy,
)

from cliente.base_widgets import DarkButton, StatusIndicator
from widgets.map_widget import MapWidget
from widgets.fleet_panel import FleetPanel
from widgets.emergency_panel import EmergencyPanel
from widgets.status_bar import StatusBar
from servicios.drone_service import DroneService
from servicios.telemetry_service import TelemetryService
from servicios.route_service import RouteService
from negocio.db_manager import DeliveryDataStore
from utils.constants import (
    PROFILES_FILE, DB_FILE,
    TELEMETRY_INTERVAL_MS,
)
from servidor.api_server import ApiServer

DRONE_ID = "Dron-1"


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Desktop Drone Control v2.0 – Dashboard")
        self.resize(1280, 800)
        self.setWindowState(Qt.WindowMaximized)

        # Servicios
        self.drone_svc = DroneService(self)
        self.telemetry_svc = TelemetryService(
            self.drone_svc, TELEMETRY_INTERVAL_MS, self
        )
        self.route_svc = RouteService(PROFILES_FILE)
        self._active_order = None

        # Iniciar API Server
        self.api_server = ApiServer(self.drone_svc, port=8080)
        self.api_server.start()

        # DB para polling de pedidos
        try:
            self._store = DeliveryDataStore(DB_FILE, PROFILES_FILE)
        except Exception:
            self._store = None

        self._build_toolbar()
        self._build_ui()
        self._connect_signals()

        # Añadir el único dron
        self.fleet_panel.add_drone(DRONE_ID)

        # Timer para polling de pedidos activos
        self._order_timer = QTimer(self)
        self._order_timer.timeout.connect(self._poll_active_order)
        self._order_timer.start(2000)

    # ══════════════════════════════════════════════════════════════════════
    #  TOOLBAR
    # ══════════════════════════════════════════════════════════════════════

    def _build_toolbar(self):
        tb = QToolBar("Principal")
        tb.setMovable(False)
        tb.setFloatable(False)
        tb.setStyleSheet("""
            QToolBar {
                background-color: #252530;
                border-bottom: 1px solid #3d3d3d;
                spacing: 6px;
                padding: 4px 8px;
            }
        """)

        # Conectar
        self.led = StatusIndicator(10)
        tb.addWidget(self.led)

        self.connect_btn = DarkButton("Conectar", "info")
        self.connect_btn.setFixedWidth(110)
        tb.addWidget(self.connect_btn)

        tb.addSeparator()

        # Acciones
        self.orders_btn = DarkButton("Pedidos", "")
        self.routes_btn = DarkButton("Rutas", "")
        self.clients_btn = DarkButton("Clientes", "")
        self.manual_btn = DarkButton("Manual", "")

        for btn in [self.orders_btn, self.routes_btn, self.clients_btn]:
            btn.setFixedWidth(110)
            tb.addWidget(btn)

        tb.addSeparator()
        self.manual_btn.setFixedWidth(100)
        tb.addWidget(self.manual_btn)

        # Spacer
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        tb.addWidget(spacer)

        # Status label en la toolbar
        self._toolbar_status = QLabel("Listo")
        self._toolbar_status.setStyleSheet(
            "color: #78909c; font-size: 12px; padding-right: 10px; background: transparent;"
        )
        tb.addWidget(self._toolbar_status)

        self.addToolBar(tb)

    # ══════════════════════════════════════════════════════════════════════
    #  UI
    # ══════════════════════════════════════════════════════════════════════

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Splitter: Mapa (75%) | Fleet Panel (25%) ──
        splitter = QSplitter(Qt.Horizontal)
        self.map_widget = MapWidget()
        splitter.addWidget(self.map_widget)

        self.fleet_panel = FleetPanel()
        splitter.addWidget(self.fleet_panel)

        splitter.setSizes([750, 250])
        root.addWidget(splitter, 1)

        # ── Panel Emergencia ──
        self.emergency = EmergencyPanel()
        root.addWidget(self.emergency)

    # ══════════════════════════════════════════════════════════════════════
    #  SIGNALS
    # ══════════════════════════════════════════════════════════════════════

    def _connect_signals(self):
        # Toolbar
        self.connect_btn.clicked.connect(self._on_connect)
        self.orders_btn.clicked.connect(self._open_business_manager)
        self.routes_btn.clicked.connect(self._open_route_planner)
        self.clients_btn.clicked.connect(self._open_business_manager)
        self.manual_btn.clicked.connect(self._open_manual_controls)

        # Fleet panel
        self.fleet_panel.drone_selected.connect(self._on_drone_selected)
        self.fleet_panel.accept_order_clicked.connect(self._on_accept_order)
        self.fleet_panel.preview_order_clicked.connect(self._on_preview_order)
        self.fleet_panel.unassign_mission_clicked.connect(self._on_unassign_mission)

        # Telemetría
        self.telemetry_svc.telemetry_tick.connect(self._on_telemetry)

        # Emergencia
        self.emergency.rtl_clicked.connect(self.drone_svc.rtl)
        self.emergency.land_clicked.connect(self.drone_svc.land)
        self.emergency.hover_clicked.connect(self.drone_svc.hover)

        # Drone events
        self.drone_svc.connected.connect(self._on_drone_connected)
        self.drone_svc.state_changed.connect(self._on_state_changed)
        self.drone_svc.flying.connect(lambda: self._on_state_changed("flying"))
        self.drone_svc.landed.connect(lambda: self._on_state_changed("landed"))
        self.drone_svc.at_home.connect(lambda: self._on_state_changed("atHome"))
        self.drone_svc.error_occurred.connect(self._on_error)
        self.drone_svc.route_status.connect(self._on_route_status)

    # ══════════════════════════════════════════════════════════════════════
    #  SLOTS
    # ══════════════════════════════════════════════════════════════════════

    def _on_connect(self):
        self.connect_btn.set_state_text("Conectando...", "warning")
        self.drone_svc.connect_drone()

    def _on_drone_connected(self):
        self.connect_btn.set_state_text("✓ Conectado", "success")
        self.led.set_color("#4caf50")
        self._set_toolbar_status("Dron conectado", "#4caf50")

        # Auto-start telemetría
        self.telemetry_svc.start()

        # Actualizar card
        card = self.fleet_panel.get_card(DRONE_ID)
        if card:
            card.update_state("connected")

    def _on_state_changed(self, state):
        card = self.fleet_panel.get_card(DRONE_ID)
        if card:
            card.update_state(state)

        if state == "flying":
            self.led.set_color("#2196f3")
        elif state == "landed":
            self.led.set_color("#ff9800")
        elif state == "atHome":
            self.led.set_color("#4caf50")

    @Slot(dict)
    def _on_telemetry(self, data):
        alt = data.get("alt", 0)
        hdg = data.get("heading", 0)
        spd = data.get("groundSpeed", data.get("speed", 0))
        lat = data.get("lat")
        lon = data.get("lon")

        # Update drone card
        card = self.fleet_panel.get_card(DRONE_ID)
        if card:
            card.update_telemetry(alt, hdg, spd)

        # Update detail panel if selected
        if self.fleet_panel.selected_id() == DRONE_ID:
            self.fleet_panel.get_detail().update_telemetry(data)

        # Update map
        if lat is not None and lon is not None:
            self.map_widget.update_drone_position(lat, lon, hdg, spd)

    def _on_drone_selected(self, drone_id):
        """Al clickar en una tarjeta → follow en mapa + mostrar info."""
        self.map_widget.set_auto_follow(True)
        self._set_toolbar_status("Siguiendo " + drone_id, "#64b5f6")

        # Mostrar ruta activa en el mapa
        if self._active_order:
            self._show_route_on_map(self._active_order)

    def _on_route_status(self, text, color):
        self._set_toolbar_status(text, color)
        card = self.fleet_panel.get_card(DRONE_ID)
        if card:
            card.update_order(text)
            card.update_op_state(text)

    def _on_error(self, msg):
        self._set_toolbar_status("Error: " + msg, "#f44336")

    def _set_toolbar_status(self, text, color="#78909c"):
        self._toolbar_status.setText(text)
        self._toolbar_status.setStyleSheet(
            "color: {}; font-size: 12px; padding-right: 10px; background: transparent;".format(color)
        )

    # ══════════════════════════════════════════════════════════════════════
    #  ORDER POLLING
    # ══════════════════════════════════════════════════════════════════════

    def _poll_active_order(self):
        """Busca el pedido activo (en_reparto) y actualiza la UI."""
        if self._store is None:
            return
        try:
            orders = self._store.list_orders()
            self.fleet_panel.update_pending_orders(orders)
        except Exception:
            return

        active = None
        for o in orders:
            if o.get("status") == "en_reparto":
                active = o
                break

        self._active_order = active
        card = self.fleet_panel.get_card(DRONE_ID)
        detail = self.fleet_panel.get_detail()

        if active:
            op = active.get("operational_state") or "en reparto"
            card.update_order("Pedido #{} → {} | {}".format(
                active["id"], active.get("client_name", "?"), op
            ))
            card.update_op_state(op)
            if self.fleet_panel.selected_id() == DRONE_ID:
                detail.update_order_info(active)
        else:
            if card:
                card.update_order("Sin pedido asignado")
                card.update_op_state("")
            if self.fleet_panel.selected_id() == DRONE_ID:
                detail.update_order_info(None)

    def _show_route_on_map(self, order):
        """Dibuja la ruta asignada del pedido activo en el mapa."""
        pname = order.get("assigned_profile_name")
        rname = order.get("assigned_route_name")
        if not pname or not rname:
            return
        try:
            self.route_svc.load()
            mission = self.route_svc.build_mission(pname, rname)
            wps = mission.get("waypoints", [])
            if wps:
                self.map_widget.clear_waypoints()
                for i, wp in enumerate(wps):
                    self.map_widget.add_waypoint(wp["lat"], wp["lon"], str(i + 1))
                
                # Check for client coordinates
                clat = order.get("client_latitude")
                clon = order.get("client_longitude")
                if clat is not None and clon is not None:
                    # Append client coordinates to waypoints array so polyline draws there
                    wps.append({"lat": float(clat), "lon": float(clon)})
                    self.map_widget.add_waypoint(float(clat), float(clon), "Cliente")
                
                self.map_widget.draw_route(wps)
        except Exception:
            pass

    def _on_accept_order(self, order_id):
        if self._store is None:
            return
        
        # Start route for order
        self._store.set_order_status(order_id, "en_reparto", "yendo a cliente")
        orders = self._store.list_orders()
        self.fleet_panel.update_pending_orders(orders)
        self._poll_active_order()
        
        active = next((o for o in orders if o.get("id") == order_id), None)
        if active:
            pname = str(active.get("assigned_profile_name") or "")
            rname = str(active.get("assigned_route_name") or "")
            if not pname or not rname:
                self._on_error("Pedido sin ruta asignada")
                return

            try:
                self.route_svc.load()
                mission = self.route_svc.build_mission(pname, rname)
            except Exception as e:
                self._on_error(str(e))
                return

            self._show_route_on_map(active)
            self._set_toolbar_status(f"Ruta iniciada para el pedido #{order_id}", "#ff9800")
            
            # Start actual drone
            try:
                clat = active.get("client_latitude")
                clon = active.get("client_longitude")
                self.drone_svc.start_order_delivery({
                    "order_id": int(active["id"]),
                    "profile_name": pname, "route_name": rname,
                    "client_latitude": float(clat) if clat else None,
                    "client_longitude": float(clon) if clon else None,
                    "mission": mission,
                })
            except Exception as e:
                self._on_error(str(e))

    def _on_preview_order(self, order_id):
        if self._store is None:
            return
        orders = self._store.list_orders()
        target = next((o for o in orders if o.get("id") == order_id), None)
        if target:
            self._show_route_on_map(target)
            self._set_toolbar_status(f"Previsualizando ruta de pedido #{order_id}", "#64b5f6")

    def _on_unassign_mission(self):
        if self._active_order and self._store:
            order_id = self._active_order.get("id")
            # Devolvemos el pedido a pendiente
            self._store.set_order_status(order_id, "pendiente", "mision abortada")
            
            # Cancelamos la misión en el dron, enviando un RTL por seguridad si está en el aire
            try:
                self.drone_svc.rtl()
            except Exception as e:
                pass
            
            self._set_toolbar_status("Misión abortada. Dron volviendo a casa.", "#f44336")
            self.map_widget.clear_waypoints()
            self._active_order = None
            
            orders = self._store.list_orders()
            self.fleet_panel.update_pending_orders(orders)
            self._poll_active_order()

    # ══════════════════════════════════════════════════════════════════════
    #  CLEANUP
    # ══════════════════════════════════════════════════════════════════════

    def closeEvent(self, event):
        try:
            self._order_timer.stop()
        except Exception:
            pass
        try:
            self.api_server.stop()
        except Exception:
            pass
        try:
            self.telemetry_svc.stop()
        except Exception:
            pass
        try:
            self.drone_svc.cleanup()
        except Exception:
            pass
        super().closeEvent(event)

    # ══════════════════════════════════════════════════════════════════════
    #  DIALOGS
    # ══════════════════════════════════════════════════════════════════════

    def _open_route_planner(self):
        from cliente.route_planner_dialog import RoutePlannerDialog
        dlg = RoutePlannerDialog(self.route_svc, self.drone_svc, self)
        dlg.exec()

    def _open_business_manager(self):
        from cliente.business_dialog import BusinessDialog
        dlg = BusinessDialog(self.drone_svc, self.route_svc, self)
        dlg.exec()

    def _open_manual_controls(self):
        from cliente.manual_controls_dialog import ManualControlsDialog
        dlg = ManualControlsDialog(self.drone_svc, self)
        dlg.exec()
