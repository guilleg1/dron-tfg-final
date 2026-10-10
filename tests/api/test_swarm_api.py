"""La API del enjambre con backend stub.

En `stub` no hay drones, así que la flota sale vacía y arrancar repartos no
hace nada. Lo que se comprueba aquí es el contrato y la autorización; el vuelo
de verdad se prueba en tests/swarm con FakeDroneLink.
"""


def _auth(token):
    return {"Authorization": "Bearer " + token}


def test_fleet_requires_an_admin_token(client, user):
    assert client.get("/api/admin/swarm/fleet").status_code == 401
    assert client.get("/api/admin/swarm/fleet",
                      headers=_auth(user["token"])).status_code == 401


def test_fleet_is_empty_with_the_stub_backend(client, admin_token):
    response = client.get("/api/admin/swarm/fleet", headers=_auth(admin_token))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["backend"] == "stub"
    assert body["drones"] == []


def test_starting_deliveries_without_a_swarm_reports_it(client, admin_token):
    response = client.post("/api/admin/swarm/start", headers=_auth(admin_token))

    assert response.status_code == 400
    assert "enjambre" in response.json()["error"].lower()


def test_swarm_telemetry_is_public_and_returns_a_list(client):
    response = client.get("/api/swarm/telemetry")

    assert response.status_code == 200
    assert response.json()["drones"] == []


def test_orders_carry_the_assigned_drone_column(client, user):
    creado = client.post("/api/orders", json={"weight_kg": 1.0},
                         headers=_auth(user["token"]))
    assert creado.status_code == 200, creado.text

    pedidos = client.get("/api/orders", headers=_auth(user["token"])).json()["orders"]

    assert "assigned_drone_id" in pedidos[0]
    assert pedidos[0]["assigned_drone_id"] is None


def test_drone_control_rejects_an_unknown_action(client, admin_token):
    response = client.post("/api/admin/swarm/drones/Dron-1/despegar",
                           headers=_auth(admin_token))

    assert response.status_code == 400


def test_the_drone_source_cannot_be_changed_without_sitl(client, admin_token):
    response = client.post("/api/admin/swarm/source", json={"source": "puente"},
                           headers={"Authorization": f"Bearer {admin_token}"})

    assert response.status_code == 400
