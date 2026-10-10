"""Fixtures para los tests del portal.

La API se apunta a una base de datos SQLite temporal y el geocoder se
sustituye por uno determinista: los tests no deben salir a la red.

Las variables de entorno se fijan ANTES de importar el módulo de la API
porque este crea su ``DataStore`` a nivel de módulo, al importarse.

IMPORTANTE: cuando el portal se mueva a ``airdrop/api``, la única línea que
cambia en todo este directorio es el import de ``api_module``.
"""

import os
import tempfile
import uuid
from pathlib import Path

import pytest

# Coordenadas fijas en Castelldefels, junto al destino "Anec_Blau" de
# route_profiles.json, para que la asignación de corredor encuentre ruta.
FAKE_COORDS = (41.2813, 1.9912)

_DB_PATH = Path(tempfile.mkdtemp(prefix="airdrop-tests-")) / "test.db"
os.environ["DATABASE_URL"] = "sqlite:///" + _DB_PATH.as_posix()
os.environ["SECRET_KEY"] = "clave-de-pruebas-no-usar-en-produccion"

from airdrop.api import main as api_module  # noqa: E402  ← única línea a cambiar


@pytest.fixture()
def client(monkeypatch):
    """Cliente HTTP contra la app, con el geocoder neutralizado."""
    from fastapi.testclient import TestClient

    monkeypatch.setattr(api_module, "geocode_address", lambda address: FAKE_COORDS)
    with TestClient(api_module.app) as test_client:
        yield test_client


@pytest.fixture()
def user(client):
    """Un cliente registrado. Devuelve credenciales, token y ficha."""
    creds = {
        "username": "cliente-" + uuid.uuid4().hex[:8],
        "password": "secreto123",
        "name": "Cliente de prueba",
        "address": "Carrer Major 1, Castelldefels",
    }
    response = client.post("/api/users/register", json=creds)
    assert response.status_code == 200, response.text
    body = response.json()
    return {**creds, "token": body["token"], "client": body["client"]}


@pytest.fixture()
def admin_token(client):
    """Token de administrador.

    El alta de admin es de un solo uso (bootstrap), así que si ya existe de
    un test anterior de la misma sesión, se entra por login.
    """
    creds = {"username": "admin-tests", "password": "secreto123"}
    response = client.post("/api/admin/register", json=creds)
    if response.status_code == 403:
        response = client.post("/api/admin/login", json=creds)
    assert response.status_code == 200, response.text
    return response.json()["token"]
