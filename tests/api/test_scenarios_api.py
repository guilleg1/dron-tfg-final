def _auth(token):
    return {"Authorization": "Bearer " + token}


def test_scenarios_require_an_admin_token(client, user):
    assert client.get("/api/admin/scenarios").status_code == 401
    assert client.get("/api/admin/scenarios",
                      headers=_auth(user["token"])).status_code == 401


def test_the_four_scenarios_are_listed(client, admin_token):
    response = client.get("/api/admin/scenarios", headers=_auth(admin_token))

    assert response.status_code == 200, response.text
    nombres = sorted(s["name"] for s in response.json()["scenarios"])
    assert nombres == ["Castelldefels", "DroneLab EETAC", "Gava", "Viladecans"]


def test_exactly_one_is_active(client, admin_token):
    escenarios = client.get("/api/admin/scenarios",
                            headers=_auth(admin_token)).json()["scenarios"]

    assert sum(1 for s in escenarios if s["active"]) == 1


def test_parameters_can_be_edited(client, admin_token):
    response = client.put("/api/admin/scenarios/Castelldefels",
                          json={"separation_min_m": 45.0},
                          headers=_auth(admin_token))

    assert response.status_code == 200, response.text
    assert response.json()["scenario"]["separation_min_m"] == 45.0


def test_editing_an_unknown_scenario_gives_404(client, admin_token):
    response = client.put("/api/admin/scenarios/Marte", json={"separation_min_m": 1.0},
                          headers=_auth(admin_token))

    assert response.status_code == 404


def test_a_scenario_can_be_activated(client, admin_token):
    response = client.post("/api/admin/scenarios/Gava/activate",
                           headers=_auth(admin_token))

    assert response.status_code == 200, response.text
    escenarios = client.get("/api/admin/scenarios",
                            headers=_auth(admin_token)).json()["scenarios"]
    activos = [s["name"] for s in escenarios if s["active"]]
    assert activos == ["Gava"]


def test_activating_an_unknown_scenario_gives_404(client, admin_token):
    response = client.post("/api/admin/scenarios/Marte/activate",
                           headers=_auth(admin_token))

    assert response.status_code == 404


def test_the_indoor_scenario_keeps_its_reduced_limits(client, admin_token):
    escenarios = client.get("/api/admin/scenarios",
                            headers=_auth(admin_token)).json()["scenarios"]

    lab = next(s for s in escenarios if s["name"] == "DroneLab EETAC")
    assert lab["alt_ceiling_m"] == 4.0
    assert lab["separation_min_m"] == 2.0
    assert lab["coords_approximate"] is False, "la jaula tiene coordenadas reales"
    assert lab["geofence_radius_m"] == 15.0


def test_safety_events_endpoint_returns_a_list(client, admin_token):
    response = client.get("/api/admin/swarm/events", headers=_auth(admin_token))

    assert response.status_code == 200
    assert isinstance(response.json()["events"], list)


def test_reset_defaults_brings_back_the_repository_scenarios(client, admin_token):
    # Un despliegue guarda los escenarios de su primer arranque; restaurar
    # descarta lo editado y vuelve a los del repositorio.
    client.delete("/api/admin/scenarios/Gava", headers=_auth(admin_token))

    response = client.post("/api/admin/scenarios/reset-defaults", headers=_auth(admin_token))

    assert response.status_code == 200
    assert "Gava" in response.json()["scenarios"]
    assert "DroneLab EETAC" in response.json()["scenarios"]
    perfiles = client.get("/api/admin/profiles", headers=_auth(admin_token)).json()["profiles"]
    assert "DroneLab-EETAC" in {p["name"] for p in perfiles}
