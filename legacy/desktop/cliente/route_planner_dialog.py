"""
RoutePlannerDialog – Planificador de rutas migrado a PySide6.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QSplitter,
    QGroupBox, QListWidget, QLabel, QLineEdit,
    QPushButton, QGridLayout, QInputDialog, QMessageBox,
)

from widgets.map_widget import MapWidget
from cliente.base_widgets import DarkButton


class RoutePlannerDialog(QDialog):
    def __init__(self, route_svc, drone_svc, parent=None):
        super().__init__(parent)
        self.route_svc = route_svc
        self.drone_svc = drone_svc
        self.setWindowTitle("Planificador de Rutas y Perfiles")
        self.resize(1300, 760)
        self._build_ui()
        self._refresh_profiles()

    def _build_ui(self):
        root = QHBoxLayout(self)
        splitter = QSplitter(Qt.Horizontal)

        # Mapa
        self.map_w = MapWidget()
        splitter.addWidget(self.map_w)

        # Panel control
        ctrl = QWidget_with_layout()
        self.profiles_list = QListWidget()
        self.parking_list = QListWidget()
        self.dest_list = QListWidget()
        self.routes_list = QListWidget()
        self.inter_list = QListWidget()
        self.takeoff_entry = QLineEdit("8")
        self.speed_entry = QLineEdit("7")
        self.hub_lbl = QLabel("HUB: no definido")
        self.hub_lbl.setStyleSheet("color: #ff9800; background: transparent;")
        self.status_lbl = QLabel("Listo")
        self.status_lbl.setStyleSheet("color: #a0a0a0; background: transparent;")

        lay = ctrl.layout()
        lay.addWidget(QLabel("Perfiles"))
        lay.addWidget(self.profiles_list)

        row1 = QHBoxLayout()
        col_p = QVBoxLayout()
        col_p.addWidget(QLabel("Parkings"))
        col_p.addWidget(self.parking_list)
        col_d = QVBoxLayout()
        col_d.addWidget(QLabel("Destinos"))
        col_d.addWidget(self.dest_list)
        row1.addLayout(col_p)
        row1.addLayout(col_d)
        lay.addLayout(row1)

        lay.addWidget(QLabel("Rutas (parking → hub → destino)"))
        lay.addWidget(self.routes_list)
        lay.addWidget(QLabel("Intermedios de la ruta"))
        lay.addWidget(self.inter_list)

        nums = QHBoxLayout()
        nums.addWidget(QLabel("TakeOff Alt:"))
        nums.addWidget(self.takeoff_entry)
        nums.addWidget(QLabel("Speed:"))
        nums.addWidget(self.speed_entry)
        lay.addLayout(nums)

        lay.addWidget(self.hub_lbl)
        lay.addWidget(self.status_lbl)

        # Botones
        btns = QGridLayout()
        b1 = DarkButton("Nuevo perfil", "info")
        b2 = DarkButton("Eliminar perfil", "danger")
        b3 = DarkButton("Crear ruta", "info")
        b4 = DarkButton("Eliminar seleccionado", "danger")
        b5 = DarkButton("Guardar perfiles", "success")
        b6 = DarkButton("Recargar perfiles", "")
        b7 = DarkButton("Iniciar misión", "success")
        b8 = DarkButton("Detener misión (RTL)", "danger")

        btns.addWidget(b1, 0, 0)
        btns.addWidget(b2, 0, 1)
        btns.addWidget(b3, 1, 0)
        btns.addWidget(b4, 1, 1)
        btns.addWidget(b5, 2, 0)
        btns.addWidget(b6, 2, 1)
        btns.addWidget(b7, 3, 0)
        btns.addWidget(b8, 3, 1)
        lay.addLayout(btns)

        splitter.addWidget(ctrl)
        splitter.setSizes([700, 500])
        root.addWidget(splitter)

        # Signals
        b1.clicked.connect(self._create_profile)
        b2.clicked.connect(self._delete_profile)
        b3.clicked.connect(self._create_route)
        b4.clicked.connect(self._delete_selected)
        b5.clicked.connect(self._save)
        b6.clicked.connect(self._reload)
        b7.clicked.connect(self._start_mission)
        b8.clicked.connect(self._stop_mission)
        self.profiles_list.currentRowChanged.connect(self._on_profile_selected)
        self.routes_list.currentRowChanged.connect(self._on_route_selected)

    # ── Helpers ──
    def _set_status(self, text, color="#a0a0a0"):
        self.status_lbl.setText(text)
        self.status_lbl.setStyleSheet("color: {}; background: transparent;".format(color))

    def _selected_profile(self):
        row = self.profiles_list.currentRow()
        profiles = self.route_svc.list_profiles()
        if 0 <= row < len(profiles):
            return profiles[row]
        return None

    def _selected_route_name(self):
        item = self.routes_list.currentItem()
        return item.text() if item else None

    # ── Refresh ──
    def _refresh_profiles(self):
        self.profiles_list.clear()
        for p in self.route_svc.list_profiles():
            self.profiles_list.addItem(p.get("name", "?"))

    def _refresh_details(self, profile):
        self.parking_list.clear()
        self.dest_list.clear()
        self.routes_list.clear()
        self.inter_list.clear()
        if profile is None:
            self.hub_lbl.setText("HUB: no definido")
            return
        for pt in profile.get("parkings", []):
            self.parking_list.addItem(pt["name"])
        for pt in profile.get("destinations", []):
            self.dest_list.addItem(pt["name"])
        for r in profile.get("routes", []):
            self.routes_list.addItem(r["name"])
        self.takeoff_entry.setText(str(profile.get("takeOffAlt", 8)))
        self.speed_entry.setText(str(profile.get("speed", 7)))
        hub = profile.get("hub")
        if isinstance(hub, dict):
            self.hub_lbl.setText("HUB: {:.6f}, {:.6f}, alt {:.1f}".format(
                hub["lat"], hub["lon"], hub.get("alt", 8)))
            self.hub_lbl.setStyleSheet("color: #4caf50; background: transparent;")
            self.map_w.set_view(hub["lat"], hub["lon"], 15)
        else:
            self.hub_lbl.setText("HUB: no definido")
            self.hub_lbl.setStyleSheet("color: #ff9800; background: transparent;")
        self._draw_on_map(profile)

    def _draw_on_map(self, profile):
        self.map_w.clear_waypoints()
        idx = 1
        for pt in profile.get("parkings", []):
            self.map_w.add_waypoint(pt["lat"], pt["lon"], "P")
            idx += 1
        for pt in profile.get("destinations", []):
            self.map_w.add_waypoint(pt["lat"], pt["lon"], "D")
            idx += 1
        hub = profile.get("hub")
        if isinstance(hub, dict):
            self.map_w.add_waypoint(hub["lat"], hub["lon"], "H")
        for route in profile.get("routes", []):
            p = self.route_svc.find_named_point(profile.get("parkings", []), route.get("parking"))
            d = self.route_svc.find_named_point(profile.get("destinations", []), route.get("destination"))
            if p and d and isinstance(hub, dict):
                wps = [{"lat": p["lat"], "lon": p["lon"]}, {"lat": hub["lat"], "lon": hub["lon"]}]
                for im in route.get("intermediates", []):
                    wps.append({"lat": im["lat"], "lon": im["lon"]})
                wps.append({"lat": d["lat"], "lon": d["lon"]})
                self.map_w.draw_route(wps)

    # ── Slots ──
    def _on_profile_selected(self, row):
        self._refresh_details(self._selected_profile())

    def _on_route_selected(self, row):
        profile = self._selected_profile()
        if not profile:
            return
        self.inter_list.clear()
        rname = self._selected_route_name()
        if not rname:
            return
        for r in profile.get("routes", []):
            if r.get("name") == rname:
                for i, pt in enumerate(r.get("intermediates", []), 1):
                    self.inter_list.addItem("I{}: {:.6f}, {:.6f}".format(i, pt["lat"], pt["lon"]))
                break

    def _create_profile(self):
        name, ok = QInputDialog.getText(self, "Nuevo perfil", "Nombre:")
        if not ok or not name.strip():
            return
        try:
            self.route_svc.create_profile(name.strip())
            self._refresh_profiles()
            self._set_status("Perfil creado", "#4caf50")
        except ValueError as e:
            self._set_status(str(e), "#f44336")

    def _delete_profile(self):
        p = self._selected_profile()
        if not p:
            return
        self.route_svc.delete_profile(p["name"])
        self._refresh_profiles()
        self._refresh_details(None)
        self._set_status("Perfil eliminado", "#4caf50")

    def _create_route(self):
        p = self._selected_profile()
        if not p:
            self._set_status("Selecciona un perfil", "#f44336")
            return
        pk = self.parking_list.currentItem()
        dt = self.dest_list.currentItem()
        if not pk or not dt:
            self._set_status("Selecciona parking y destino", "#f44336")
            return
        name, ok = QInputDialog.getText(self, "Nueva ruta", "Nombre:")
        if not ok or not name.strip():
            return
        for r in p.get("routes", []):
            if r.get("name") == name.strip():
                self._set_status("Ruta ya existe", "#f44336")
                return
        p.setdefault("routes", []).append({
            "name": name.strip(), "parking": pk.text(),
            "destination": dt.text(), "intermediates": [],
        })
        self._refresh_details(p)
        self._set_status("Ruta creada", "#4caf50")

    def _delete_selected(self):
        p = self._selected_profile()
        if not p:
            return
        rname = self._selected_route_name()
        if rname:
            p["routes"] = [r for r in p.get("routes", []) if r.get("name") != rname]
            self._refresh_details(p)
            self._set_status("Ruta eliminada", "#4caf50")

    def _save(self):
        p = self._selected_profile()
        if p:
            try:
                p["takeOffAlt"] = float(self.takeoff_entry.text())
                p["speed"] = float(self.speed_entry.text())
            except ValueError:
                self._set_status("Valores numéricos inválidos", "#f44336")
                return
        self.route_svc.save()
        self._set_status("Perfiles guardados", "#4caf50")

    def _reload(self):
        self.route_svc.load()
        self._refresh_profiles()
        self._set_status("Perfiles recargados", "#4caf50")

    def _start_mission(self):
        p = self._selected_profile()
        rname = self._selected_route_name()
        if not p or not rname:
            self._set_status("Selecciona perfil y ruta", "#f44336")
            return
        try:
            p["takeOffAlt"] = float(self.takeoff_entry.text())
            p["speed"] = float(self.speed_entry.text())
            mission = self.route_svc.build_mission(p["name"], rname)
        except (ValueError, Exception) as e:
            self._set_status(str(e), "#f44336")
            return
        self.drone_svc.start_mission(mission)
        self._set_status("Misión iniciada", "#4caf50")

    def _stop_mission(self):
        self.drone_svc.rtl()
        self._set_status("RTL enviado", "#ff9800")


class QWidget_with_layout(QGroupBox):
    """Helper: QGroupBox con QVBoxLayout preconfigurado."""
    def __init__(self):
        super().__init__("Perfiles y Rutas")
        self.setLayout(QVBoxLayout())
        self.layout().setSpacing(4)
