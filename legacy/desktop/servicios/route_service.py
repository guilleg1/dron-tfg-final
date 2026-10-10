"""
RouteService – Gestión de perfiles y rutas, desacoplada de la GUI.
Migrado desde las funciones globales de DesktopLAN.py.
"""

import json
from pathlib import Path
from utils.constants import PROFILES_FILE


class RouteService:
    def __init__(self, profiles_path=None):
        self.profiles_path = Path(profiles_path or PROFILES_FILE)
        self.profiles_data = {"profiles": []}
        self.active_profile_name = None
        self.active_route_name = None
        self.load()

    @classmethod
    def from_profiles(cls, profiles_data):
        """Crea una instancia a partir de un documento de perfiles en memoria,
        sin tocar el fichero. La usa el portal cloud, que guarda los perfiles en
        la base de datos en vez de en disco."""
        inst = cls.__new__(cls)
        inst.profiles_path = None
        inst.profiles_data = profiles_data if isinstance(profiles_data, dict) else {"profiles": []}
        inst.profiles_data.setdefault("profiles", [])
        inst.active_profile_name = None
        inst.active_route_name = None
        return inst

    def load(self):
        if not self.profiles_path.exists():
            self.profiles_data = {"profiles": []}
            return
        try:
            with open(self.profiles_path, "r", encoding="utf-8") as fp:
                data = json.load(fp)
        except (OSError, json.JSONDecodeError):
            self.profiles_data = {"profiles": []}
            return
        if not isinstance(data, dict) or not isinstance(data.get("profiles"), list):
            self.profiles_data = {"profiles": []}
            return
        for p in data["profiles"]:
            p.setdefault("parkings", [])
            p.setdefault("destinations", [])
            p.setdefault("routes", [])
            p.setdefault("hub", None)
            p.setdefault("takeOffAlt", 8)
            p.setdefault("speed", 7)
            for r in p["routes"]:
                r.setdefault("intermediates", [])
        self.profiles_data = data

    def save(self):
        with open(self.profiles_path, "w", encoding="utf-8") as fp:
            json.dump(self.profiles_data, fp, indent=2)

    def list_profiles(self):
        return self.profiles_data.get("profiles", [])

    def find_profile(self, name):
        for p in self.profiles_data.get("profiles", []):
            if p.get("name") == name:
                return p
        return None

    @staticmethod
    def find_named_point(points, name):
        for pt in points:
            if pt.get("name") == name:
                return pt
        return None

    def build_mission(self, profile_name, route_name):
        profile = self.find_profile(profile_name)
        if profile is None:
            raise ValueError("Perfil no encontrado: " + str(profile_name))
        route = None
        for r in profile.get("routes", []):
            if r.get("name") == route_name:
                route = r
                break
        if route is None:
            raise ValueError("Ruta no encontrada")
        parking = self.find_named_point(profile.get("parkings", []), route.get("parking"))
        destination = self.find_named_point(profile.get("destinations", []), route.get("destination"))
        hub = profile.get("hub")
        if parking is None:
            raise ValueError("Parking no encontrado")
        if destination is None:
            raise ValueError("Destino no encontrado")
        if not isinstance(hub, dict):
            raise ValueError("Falta definir el HUB")
        wps = [
            {"lat": float(parking["lat"]), "lon": float(parking["lon"]), "alt": float(parking.get("alt", 8))},
            {"lat": float(hub["lat"]), "lon": float(hub["lon"]), "alt": float(hub.get("alt", 8))},
        ]
        for pt in route.get("intermediates", []):
            wps.append({"lat": float(pt["lat"]), "lon": float(pt["lon"]), "alt": float(pt.get("alt", hub.get("alt", 8)))})
        wps.append({"lat": float(destination["lat"]), "lon": float(destination["lon"]), "alt": float(destination.get("alt", 8))})
        return {
            "speed": float(profile.get("speed", 7)),
            "takeOffAlt": float(profile.get("takeOffAlt", 8)),
            "waypoints": wps,
        }

    def create_profile(self, name):
        if self.find_profile(name) is not None:
            raise ValueError("Ya existe ese perfil")
        self.profiles_data["profiles"].append({
            "name": name, "takeOffAlt": 8, "speed": 7,
            "hub": None, "parkings": [], "destinations": [], "routes": [],
        })

    def delete_profile(self, name):
        self.profiles_data["profiles"] = [
            p for p in self.profiles_data["profiles"] if p.get("name") != name
        ]
