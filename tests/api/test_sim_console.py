"""La consola de simulación dentro del portal: solo para el administrador."""


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_the_console_needs_an_admin(client):
    assert client.get("/api/admin/sim/estado").status_code == 401


def test_the_console_page_is_served(client):
    respuesta = client.get("/simulacion/")
    assert respuesta.status_code == 200
    assert "ParkingTool" in respuesta.text


def test_state_shows_fleet_parking_and_sitl(client, admin_token):
    datos = client.get("/api/admin/sim/estado", headers=_auth(admin_token)).json()

    assert datos["escenario"]["name"]
    assert len(datos["parking"]["pads"]) == len(datos["drones"])
    assert datos["sitl"]["modo"] in ("simulado", "embebido", "mission_planner")
    assert "oleada" in {p["nombre"] for p in datos["presets"]}


def test_applying_a_formation_resizes_the_fleet(client, admin_token):
    formacion = {"n_drones": 6, "pad_layout": "rejilla", "pad_cols": 3,
                 "pad_spacing_m": 8, "pad_separation_m": 25, "takeoff_gap_s": 10,
                 "categorias": ["ligero", "ligero", "medio", "pesado", "medio", "medio"]}
    try:
        r = client.post("/api/admin/sim/parking/aplicar", json=formacion,
                        headers=_auth(admin_token))
        assert r.status_code == 200, r.text
        assert [d["category"] for d in r.json()["drones"]] == formacion["categorias"]
        estado = client.get("/api/admin/sim/estado", headers=_auth(admin_token)).json()
        assert len(estado["drones"]) == 6
    finally:
        client.post("/api/admin/sim/parking/aplicar",
                    json={**formacion, "n_drones": 4, "pad_layout": "fila",
                          "categorias": ["ligero", "ligero", "medio", "pesado"]},
                    headers=_auth(admin_token))


def test_the_fleet_is_not_capped_at_ten(client, admin_token):
    """Treinta drones: el tope lo ponen los puertos (100), no la consola."""
    formacion = {"n_drones": 30, "pad_layout": "rejilla", "pad_cols": 6,
                 "pad_spacing_m": 6, "pad_separation_m": 25, "takeoff_gap_s": 10}
    try:
        estado = client.get("/api/admin/sim/estado", headers=_auth(admin_token)).json()
        assert estado["max_drones"] == 100
        r = client.post("/api/admin/sim/parking/aplicar", json=formacion,
                        headers=_auth(admin_token))
        assert r.status_code == 200, r.text
        drones = r.json()["drones"]
        assert len(drones) == 30
        assert len({(d["home_lat"], d["home_lon"]) for d in drones}) == 30
        assert sorted(d["sysid"] for d in drones) == list(range(1, 31))
    finally:
        client.post("/api/admin/sim/parking/aplicar",
                    json={**formacion, "n_drones": 4, "pad_layout": "fila",
                          "categorias": ["ligero", "ligero", "medio", "pesado"]},
                    headers=_auth(admin_token))


def test_the_port_limit_and_the_env_override(monkeypatch):
    from simtools import sim

    assert sim.MAX_DRONES_PUERTOS == 100
    # La instancia 99 no pisa el primer puerto del puente (6762).
    assert 5763 + 10 * (sim.MAX_DRONES_PUERTOS - 1) < 6762
    monkeypatch.setenv("SIM_MAX_DRONES", "12")
    assert sim.max_drones() == 12
    monkeypatch.setenv("SIM_MAX_DRONES", "500")
    assert sim.max_drones() == 100


def test_the_speedup_is_kept_for_the_next_launch(client, admin_token):
    from airdrop.api import main as portal
    from airdrop.api import sim_admin

    r = client.post("/api/admin/sim/sitl/lanzar", json={"speedup": 5},
                    headers=_auth(admin_token))

    assert r.status_code == 200
    assert sim_admin.speedup(portal.store) == 5.0
    client.post("/api/admin/sim/sitl/lanzar", json={"speedup": 1}, headers=_auth(admin_token))


def test_big_parkings_are_coloured_without_exponential_search():
    """Rejilla 10x10 con conflictos entre vecinos: 2 turnos y 50 a la vez."""
    import time

    from simtools import sim

    n = 100
    pares = [(k, k + 1) for k in range(n) if (k + 1) % 10] + \
            [(k, k + 10) for k in range(n - 10)]
    inicio = time.time()
    tandas = sim._tandas(n, pares)
    simultaneos = sim._maniobras_simultaneas(n, pares)
    assert time.time() - inicio < 2.0
    assert all(tandas[a] != tandas[b] for a, b in pares)
    assert max(tandas) + 1 == 2
    assert simultaneos == 50


def test_a_drone_can_be_removed_on_its_own(client, admin_token):
    base = {"pad_layout": "fila", "pad_spacing_m": 8, "pad_separation_m": 25,
            "takeoff_gap_s": 10}
    try:
        client.post("/api/admin/sim/parking/aplicar", headers=_auth(admin_token),
                    json={**base, "n_drones": 5})
        antes = {d["drone_id"]: d for d in client.get(
            "/api/admin/sim/estado", headers=_auth(admin_token)).json()["drones"]}

        r = client.delete("/api/admin/sim/flota/Dron-3", headers=_auth(admin_token))

        assert r.status_code == 200, r.text
        despues = {d["drone_id"]: d for d in r.json()["drones"]}
        assert set(despues) == {"Dron-1", "Dron-2", "Dron-4", "Dron-5"}
        assert all(despues[k] == antes[k] for k in despues)
        assert client.delete("/api/admin/sim/flota/Dron-3",
                             headers=_auth(admin_token)).status_code == 404
        # El plano enseña el parking real: el hueco de Dron-3 y los nombres.
        estado = client.get("/api/admin/sim/estado", headers=_auth(admin_token)).json()
        pads = estado["parking"]["pads"]
        assert [p["etiqueta"] for p in pads] == ["1", "2", "4", "5"]
        assert [(p["lat"], p["lon"]) for p in pads] == \
            [(antes[k]["home_lat"], antes[k]["home_lon"]) for k in ("Dron-1", "Dron-2", "Dron-4", "Dron-5")]
    finally:
        client.post("/api/admin/sim/parking/aplicar", headers=_auth(admin_token),
                    json={**base, "n_drones": 4,
                          "categorias": ["ligero", "ligero", "medio", "pesado"]})


def test_the_last_drone_cannot_be_removed(client, admin_token):
    base = {"pad_layout": "fila", "pad_spacing_m": 8, "pad_separation_m": 25,
            "takeoff_gap_s": 10}
    try:
        client.post("/api/admin/sim/parking/aplicar", headers=_auth(admin_token),
                    json={**base, "n_drones": 1})
        r = client.delete("/api/admin/sim/flota/Dron-1", headers=_auth(admin_token))
        assert r.status_code == 400
    finally:
        client.post("/api/admin/sim/parking/aplicar", headers=_auth(admin_token),
                    json={**base, "n_drones": 4,
                          "categorias": ["ligero", "ligero", "medio", "pesado"]})


def test_waves_scale_with_the_fleet():
    from airdrop.demo import PRESETS

    oleada = PRESETS["oleada_flota"]
    assert len(oleada.pesos_para(4)) == 8
    assert len(oleada.pesos_para(20)) == 40
    assert oleada.pesos_para(20)[8:16] == list(PRESETS["oleada"].pesos_kg)
    assert len(PRESETS["oleada"].pesos_para(4, cantidad=100)) == 100
    assert len(PRESETS["oleada"].pesos_para(4)) == 8
