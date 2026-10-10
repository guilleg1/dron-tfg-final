"""Contrato de la API del portal.

Estos tests describen el comportamiento que la reestructuración debe
preservar intacto. No prueban implementación: prueban respuestas HTTP.
"""

import uuid


def _auth(token):
    return {"Authorization": "Bearer " + token}


# ── Alta y acceso de clientes ────────────────────────────────────────────

def test_register_creates_account_and_returns_token(client):
    username = "cliente-" + uuid.uuid4().hex[:8]
    response = client.post("/api/users/register", json={
        "username": username,
        "password": "secreto123",
        "name": "Ana Ruiz",
        "address": "Avinguda Constitucio 1, Castelldefels",
    })

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["token"]
    assert body["client"]["name"] == "Ana Ruiz"
    assert body["client"]["latitude"] is not None


def test_register_rejects_short_password(client):
    response = client.post("/api/users/register", json={
        "username": "cliente-" + uuid.uuid4().hex[:8],
        "password": "123",
        "name": "Ana Ruiz",
        "address": "Avinguda Constitucio 1, Castelldefels",
    })

    assert response.status_code == 400


def test_register_rejects_duplicate_username(client, user):
    response = client.post("/api/users/register", json={
        "username": user["username"],
        "password": "otracontrasena",
        "name": "Impostor",
        "address": "Carrer Major 2, Castelldefels",
    })

    assert response.status_code == 409


def test_login_accepts_correct_credentials(client, user):
    response = client.post("/api/users/login", json={
        "username": user["username"], "password": user["password"],
    })

    assert response.status_code == 200, response.text
    assert response.json()["token"]


def test_login_rejects_wrong_password(client, user):
    response = client.post("/api/users/login", json={
        "username": user["username"], "password": "contrasena-incorrecta",
    })

    assert response.status_code == 401


# ── Pedidos ──────────────────────────────────────────────────────────────

def test_create_order_assigns_a_corridor(client, user):
    response = client.post("/api/orders", json={"weight_kg": 1.5},
                           headers=_auth(user["token"]))

    assert response.status_code == 200, response.text
    assignment = response.json()["assignment"]
    assert assignment["profile_name"]
    assert assignment["route_name"]
    assert assignment["destination_name"]
    assert assignment["distance_km"] >= 0


def test_orders_require_authentication(client):
    assert client.get("/api/orders").status_code == 401
    assert client.post("/api/orders", json={"weight_kg": 1.0}).status_code == 401


def test_orders_are_scoped_to_the_authenticated_user(client, user):
    client.post("/api/orders", json={"weight_kg": 1.0}, headers=_auth(user["token"]))

    otras_creds = {
        "username": "cliente-" + uuid.uuid4().hex[:8],
        "password": "secreto123",
        "name": "Otro Cliente",
        "address": "Carrer Major 9, Castelldefels",
    }
    otro = client.post("/api/users/register", json=otras_creds).json()

    mios = client.get("/api/orders", headers=_auth(user["token"])).json()["orders"]
    suyos = client.get("/api/orders", headers=_auth(otro["token"])).json()["orders"]

    assert len(mios) >= 1
    assert all(o["client_id"] == user["client"]["id"] for o in mios)
    assert suyos == []


# ── Administración ───────────────────────────────────────────────────────

def test_admin_bootstrap_allows_only_one_admin(client, admin_token):
    response = client.post("/api/admin/register", json={
        "username": "segundo-admin", "password": "secreto123",
    })

    assert response.status_code == 403


def test_admin_login_rejects_wrong_password(client, admin_token):
    response = client.post("/api/admin/login", json={
        "username": "admin-tests", "password": "contrasena-incorrecta",
    })

    assert response.status_code == 401


def test_admin_orders_requires_an_admin_token(client, user):
    assert client.get("/api/admin/orders").status_code == 401
    assert client.get("/api/admin/orders",
                      headers=_auth(user["token"])).status_code == 401


def test_admin_orders_lists_orders_from_every_client(client, user, admin_token):
    client.post("/api/orders", json={"weight_kg": 2.0}, headers=_auth(user["token"]))

    response = client.get("/api/admin/orders", headers=_auth(admin_token))

    assert response.status_code == 200, response.text
    pedidos = response.json()["orders"]
    assert any(o["client_id"] == user["client"]["id"] for o in pedidos)


def test_admin_fleet_returns_categories_and_default_fleet(client, admin_token):
    response = client.get("/api/admin/fleet", headers=_auth(admin_token))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["categories"]
    assert body["fleet"]
    assert {"id", "category"} <= set(body["fleet"][0])


# ── Backend de dron ──────────────────────────────────────────────────────

def test_telemetry_reports_the_stub_backend_by_default(client):
    response = client.get("/api/drone/telemetry")

    assert response.status_code == 200, response.text
    assert response.json()["backend"] == "stub"


def test_dispatch_fails_gracefully_without_a_drone(client, user, admin_token):
    creado = client.post("/api/orders", json={"weight_kg": 1.0},
                         headers=_auth(user["token"]))
    assert creado.status_code == 200, creado.text
    pedidos = client.get("/api/admin/orders", headers=_auth(admin_token)).json()["orders"]
    order_id = pedidos[0]["id"]

    response = client.post(f"/api/admin/orders/{order_id}/dispatch",
                           headers=_auth(admin_token))

    assert response.status_code == 400
    assert "modo cloud" in response.json()["error"]


def test_drone_control_rejects_an_unknown_action(client, admin_token):
    response = client.post("/api/admin/drone/despegar", headers=_auth(admin_token))

    assert response.status_code == 400
    assert response.json()["error"] == "Acción no válida"
