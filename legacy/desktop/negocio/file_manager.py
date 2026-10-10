"""
FileManager – Gestión de route_profiles.json.
Wrapper fino sobre RouteService para acceso directo al fichero.
"""

import json
from pathlib import Path
from utils.constants import PROFILES_FILE


def load_profiles(path=None):
    p = Path(path or PROFILES_FILE)
    if not p.exists():
        return {"profiles": []}
    try:
        with open(p, "r", encoding="utf-8") as fp:
            data = json.load(fp)
    except (OSError, json.JSONDecodeError):
        return {"profiles": []}
    if not isinstance(data, dict) or not isinstance(data.get("profiles"), list):
        return {"profiles": []}
    return data


def save_profiles(data, path=None):
    p = Path(path or PROFILES_FILE)
    with open(p, "w", encoding="utf-8") as fp:
        json.dump(data, fp, indent=2)
