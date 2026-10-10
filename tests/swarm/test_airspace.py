import pytest

from airdrop.swarm.airspace import AirspaceManager
from airdrop.swarm.models import IN_TRANSIT, DroneRuntime
from airdrop.swarm.scenario import OperationalScenario

ESCENARIO = OperationalScenario(
    name="Castelldefels", route_profile_name="Ruta1-Castelldefels",
    parking_lat=41.283720, parking_lon=1.985050,
)


def _runtime(drone_id, lat, lon, alt, battery_wh=200.0):
    return DroneRuntime(drone_id=drone_id, state=IN_TRANSIT, lat=lat, lon=lon,
                        alt=alt, cruise_alt_m=alt, battery_wh=battery_wh,
                        battery_capacity_wh=222.0)


# ── Slots de altitud ─────────────────────────────────────────────────────

def test_slots_are_handed_out_in_order():
    a = AirspaceManager(ESCENARIO, slot_count=4)

    assert a.reserve_slot("Dron-1") == 25.0
    assert a.reserve_slot("Dron-2") == 30.0
    assert a.reserve_slot("Dron-3") == 35.0


def test_a_released_slot_is_reused():
    a = AirspaceManager(ESCENARIO, slot_count=4)
    a.reserve_slot("Dron-1")
    a.reserve_slot("Dron-2")

    a.release_slot("Dron-1")

    assert a.reserve_slot("Dron-3") == 25.0, "el slot liberado vuelve al fondo comun"


def test_running_out_of_slots_returns_none():
    a = AirspaceManager(ESCENARIO, slot_count=2)
    a.reserve_slot("Dron-1")
    a.reserve_slot("Dron-2")

    assert a.reserve_slot("Dron-3") is None


def test_the_ceiling_limits_the_number_of_slots():
    indoor = OperationalScenario(
        name="DroneLab EETAC", route_profile_name="x",
        parking_lat=41.2757, parking_lon=1.9875,
        alt_base_m=2.0, alt_step_m=1.0, alt_ceiling_m=4.0,
    )
    a = AirspaceManager(indoor, slot_count=8)

    reservados = [a.reserve_slot(f"D{i}") for i in range(8)]

    assert [r for r in reservados if r is not None] == [2.0, 3.0, 4.0]


def test_reserving_twice_returns_the_same_slot():
    a = AirspaceManager(ESCENARIO, slot_count=4)

    assert a.reserve_slot("Dron-1") == a.reserve_slot("Dron-1")


# ── Escalonado de despegues ──────────────────────────────────────────────

def test_the_first_takeoff_has_no_delay():
    a = AirspaceManager(ESCENARIO, slot_count=4, clock=lambda: 1000.0)

    assert a.takeoff_delay_s("Dron-1") == 0.0


def test_a_second_takeoff_waits_the_configured_gap():
    reloj = {"t": 1000.0}
    a = AirspaceManager(ESCENARIO, slot_count=4, clock=lambda: reloj["t"])
    a.takeoff_delay_s("Dron-1")

    reloj["t"] = 1004.0
    assert a.takeoff_delay_s("Dron-2") == pytest.approx(6.0)


def test_after_the_gap_there_is_no_delay():
    reloj = {"t": 1000.0}
    a = AirspaceManager(ESCENARIO, slot_count=4, clock=lambda: reloj["t"])
    a.takeoff_delay_s("Dron-1")

    reloj["t"] = 1015.0
    assert a.takeoff_delay_s("Dron-2") == 0.0


# ── HUB exclusivo ────────────────────────────────────────────────────────

def test_the_hub_admits_one_drone_at_a_time():
    a = AirspaceManager(ESCENARIO, slot_count=4)

    assert a.acquire_hub("Dron-1")
    assert not a.acquire_hub("Dron-2")


def test_releasing_the_hub_lets_the_next_one_in():
    a = AirspaceManager(ESCENARIO, slot_count=4)
    a.acquire_hub("Dron-1")

    a.release_hub("Dron-1")

    assert a.acquire_hub("Dron-2")


def test_the_holder_can_reacquire_the_hub():
    a = AirspaceManager(ESCENARIO, slot_count=4)
    a.acquire_hub("Dron-1")

    assert a.acquire_hub("Dron-1")


def test_a_non_exclusive_hub_admits_everyone():
    abierto = OperationalScenario(
        name="x", route_profile_name="y", parking_lat=41.28, parking_lon=1.98,
        hub_exclusive=False)
    a = AirspaceManager(abierto, slot_count=4)

    assert a.acquire_hub("Dron-1")
    assert a.acquire_hub("Dron-2")


# ── Separación mínima ────────────────────────────────────────────────────

def test_distant_drones_do_not_conflict():
    a = AirspaceManager(ESCENARIO, slot_count=4)
    runtimes = {
        "Dron-1": _runtime("Dron-1", 41.2837, 1.9850, 25.0),
        "Dron-2": _runtime("Dron-2", 41.2900, 1.9900, 25.0),   # ~800 m
    }

    assert not a.must_yield("Dron-1", runtimes)
    assert not a.must_yield("Dron-2", runtimes)


def test_drones_on_different_layers_do_not_conflict():
    a = AirspaceManager(ESCENARIO, slot_count=4)
    runtimes = {
        "Dron-1": _runtime("Dron-1", 41.2837, 1.98500, 25.0),
        "Dron-2": _runtime("Dron-2", 41.2837, 1.98502, 40.0),   # encima, 15 m
    }

    assert not a.must_yield("Dron-1", runtimes)
    assert not a.must_yield("Dron-2", runtimes)


def test_the_drone_with_more_battery_yields():
    a = AirspaceManager(ESCENARIO, slot_count=4)
    runtimes = {
        "Dron-1": _runtime("Dron-1", 41.2837, 1.98500, 25.0, battery_wh=200.0),
        "Dron-2": _runtime("Dron-2", 41.2837, 1.98502, 25.0, battery_wh=80.0),
    }

    assert a.must_yield("Dron-1", runtimes), "el de mas bateria tiene mas margen"
    assert not a.must_yield("Dron-2", runtimes)


def test_only_one_of_the_pair_yields():
    a = AirspaceManager(ESCENARIO, slot_count=4)
    runtimes = {
        "Dron-1": _runtime("Dron-1", 41.2837, 1.98500, 25.0, battery_wh=150.0),
        "Dron-2": _runtime("Dron-2", 41.2837, 1.98502, 25.0, battery_wh=150.0),
    }

    cediendo = [d for d in runtimes if a.must_yield(d, runtimes)]
    assert len(cediendo) == 1, "un empate no puede bloquear a los dos"


def test_a_drone_on_the_ground_is_not_a_conflict():
    a = AirspaceManager(ESCENARIO, slot_count=4)
    runtimes = {
        "Dron-1": _runtime("Dron-1", 41.2837, 1.98500, 25.0),
        "Dron-2": DroneRuntime(drone_id="Dron-2", state="idle",
                               lat=41.2837, lon=1.98502, alt=0.0),
    }

    assert not a.must_yield("Dron-1", runtimes)


def test_the_hub_is_granted_in_arrival_order():
    # Regresion de una inanicion real: sin cola, el que pide justo al liberarse
    # se lo lleva siempre y otro puede esperar indefinidamente.
    a = AirspaceManager(ESCENARIO, slot_count=4)
    a.acquire_hub("Dron-1")
    assert not a.acquire_hub("Dron-2"), "Dron-2 se pone en cola"
    assert not a.acquire_hub("Dron-3"), "Dron-3 detras"

    a.release_hub("Dron-1")

    # Dron-3 lo pide primero, pero le toca a Dron-2 por orden de llegada.
    assert not a.acquire_hub("Dron-3")
    assert a.acquire_hub("Dron-2")


def test_leaving_the_queue_releases_the_turn():
    a = AirspaceManager(ESCENARIO, slot_count=4)
    a.acquire_hub("Dron-1")
    a.acquire_hub("Dron-2")          # en cola

    a.release_hub("Dron-2")          # se va sin llegar a entrar
    a.release_hub("Dron-1")

    assert a.hub_queue() == []
    assert a.acquire_hub("Dron-3")


def test_a_stuck_holder_is_evicted_from_the_hub():
    # Autocuracion: un dron atascado reteniendo el HUB bloquearia a la flota
    # hasta agotar el tiempo del tramo, que es mucho mas largo.
    reloj = {"t": 1000.0}
    a = AirspaceManager(ESCENARIO, slot_count=4, clock=lambda: reloj["t"],
                        hub_hold_timeout_s=60.0)
    a.acquire_hub("Dron-1")
    assert not a.acquire_hub("Dron-2")

    reloj["t"] = 1100.0   # 100 s despues, mas del limite

    assert a.acquire_hub("Dron-2")
    assert a.hub_holder() == "Dron-2"


def test_a_holder_within_the_limit_is_not_evicted():
    reloj = {"t": 1000.0}
    a = AirspaceManager(ESCENARIO, slot_count=4, clock=lambda: reloj["t"],
                        hub_hold_timeout_s=60.0)
    a.acquire_hub("Dron-1")

    reloj["t"] = 1030.0

    assert not a.acquire_hub("Dron-2")
    assert a.hub_holder() == "Dron-1"


def test_the_hub_holder_never_yields():
    # Regresion de un interbloqueo real: el que retiene el HUB cedia ante otro
    # que estaba esperando ese mismo HUB, y ninguno avanzaba.
    a = AirspaceManager(ESCENARIO, slot_count=4)
    runtimes = {
        "Dron-1": _runtime("Dron-1", 41.2837, 1.98500, 25.0, battery_wh=200.0),
        "Dron-2": _runtime("Dron-2", 41.2837, 1.98502, 25.0, battery_wh=80.0),
    }
    assert a.must_yield("Dron-1", runtimes), "sin el HUB si cederia"

    a.acquire_hub("Dron-1")

    assert not a.must_yield("Dron-1", runtimes), "el que ocupa el HUB tiene paso"
    assert not a.must_yield("Dron-2", runtimes)


def test_conflicting_pairs_are_reported_once():
    a = AirspaceManager(ESCENARIO, slot_count=4)
    runtimes = {
        "Dron-1": _runtime("Dron-1", 41.2837, 1.98500, 25.0),
        "Dron-2": _runtime("Dron-2", 41.2837, 1.98502, 25.0),
    }

    assert a.conflicts(runtimes) == [("Dron-1", "Dron-2")]


# ── Nivel de regreso ─────────────────────────────────────────────────────

def test_the_return_leg_flies_above_the_outbound_block():
    # El regreso rehace la ruta de ida, asi que sobre el mismo corredor hay
    # trafico en los dos sentidos: se separan por nivel, como en aviacion.
    a = AirspaceManager(ESCENARIO, slot_count=4)
    ida = a.reserve_slot("Dron-1")

    vuelta = a.return_altitude("Dron-1")

    assert ida == 25.0
    assert vuelta == 45.0, "un bloque completo por encima de las capas de ida"


def test_no_outbound_and_return_level_ever_coincide():
    a = AirspaceManager(ESCENARIO, slot_count=4)
    idas, vueltas = [], []
    for n in range(4):
        drone = f"Dron-{n + 1}"
        idas.append(a.reserve_slot(drone))
        vueltas.append(a.return_altitude(drone))

    assert not set(idas) & set(vueltas), "ida y vuelta no comparten nivel"


def test_the_return_level_never_breaks_the_ceiling():
    # Preferimos degradar a la capa de ida antes que romper el limite legal
    # de altura: la separacion la resuelven entonces las esperas tacticas.
    bajo = OperationalScenario(
        name="Techo bajo", route_profile_name="r",
        parking_lat=41.28, parking_lon=1.98, alt_ceiling_m=40.0,
    )
    a = AirspaceManager(bajo, slot_count=4)
    ida = a.reserve_slot("Dron-1")

    assert a.return_altitude("Dron-1") == ida


def test_a_drone_without_a_slot_has_no_return_level():
    a = AirspaceManager(ESCENARIO, slot_count=4)

    assert a.return_altitude("Dron-1") is None


# ── Aforo del HUB ────────────────────────────────────────────────────────

def _con_aforo(capacidad):
    return OperationalScenario(
        name="Castelldefels", route_profile_name="Ruta1-Castelldefels",
        parking_lat=41.283720, parking_lon=1.985050, hub_capacity=capacidad,
    )


def test_capacity_one_behaves_like_the_old_mutual_exclusion():
    # El defecto no cambia nada de lo ya verificado en B2.
    a = AirspaceManager(_con_aforo(1), slot_count=4)

    assert a.acquire_hub("Dron-1")
    assert not a.acquire_hub("Dron-2")


def test_the_hub_admits_as_many_drones_as_its_capacity():
    a = AirspaceManager(_con_aforo(2), slot_count=4)

    assert a.acquire_hub("Dron-1")
    assert a.acquire_hub("Dron-2"), "el aforo es 2"
    assert not a.acquire_hub("Dron-3"), "el tercero espera turno"


def test_releasing_a_slot_lets_the_next_in_line_in():
    a = AirspaceManager(_con_aforo(2), slot_count=4)
    a.acquire_hub("Dron-1")
    a.acquire_hub("Dron-2")
    a.acquire_hub("Dron-3")   # se pone a la cola

    a.release_hub("Dron-1")

    assert a.acquire_hub("Dron-3")
    assert set(a.hub_holders()) == {"Dron-2", "Dron-3"}


def test_a_latecomer_never_overtakes_the_queue():
    # Sin la comprobacion de turno, un recien llegado se cuela cada vez que
    # se libera plaza y el que espera desde hace rato no entra nunca.
    a = AirspaceManager(_con_aforo(1), slot_count=4)
    a.acquire_hub("Dron-1")
    a.acquire_hub("Dron-2")   # encola

    a.release_hub("Dron-1")

    assert not a.acquire_hub("Dron-3"), "Dron-2 llevaba esperando"
    assert a.acquire_hub("Dron-2")


def test_a_stuck_drone_is_evicted_so_it_does_not_eat_the_quota():
    reloj = {"t": 0.0}
    a = AirspaceManager(_con_aforo(1), slot_count=4,
                        clock=lambda: reloj["t"], hub_hold_timeout_s=10.0)
    a.acquire_hub("Dron-1")

    reloj["t"] = 11.0

    assert a.acquire_hub("Dron-2"), "el atascado libera plaza al caducar"


def test_capacity_is_never_below_one():
    a = AirspaceManager(_con_aforo(0), slot_count=4)

    assert a.hub_capacity == 1
    assert a.acquire_hub("Dron-1")


# ── Vertical del parking ─────────────────────────────────────────────────

def test_only_one_drone_manoeuvres_over_the_parking():
    # Despegar y aterrizar atraviesan todas las capas inferiores: ahi la
    # separacion vertical no protege, asi que se serializa el volumen.
    a = AirspaceManager(ESCENARIO, slot_count=4)

    assert a.acquire_pad("Dron-1")
    assert not a.acquire_pad("Dron-2"), "no puede haber dos maniobrando"

    a.release_pad("Dron-1")

    assert a.acquire_pad("Dron-2")


def test_asking_twice_is_not_a_conflict_with_itself():
    a = AirspaceManager(ESCENARIO, slot_count=4)
    a.acquire_pad("Dron-1")

    assert a.acquire_pad("Dron-1"), "el que ya lo tiene sigue teniendolo"


def test_a_drone_stuck_on_the_pad_is_evicted():
    reloj = {"t": 0.0}
    a = AirspaceManager(ESCENARIO, slot_count=4,
                        clock=lambda: reloj["t"], hub_hold_timeout_s=10.0)
    a.acquire_pad("Dron-1")

    reloj["t"] = 11.0

    assert a.acquire_pad("Dron-2"), "un atascado no bloquea el parking para siempre"


# ── Vertipuerto: varias plataformas a la vez ─────────────────────────────
#
# Con pad_separation_m a 0 el parking es un cerrojo unico y la flota despega y
# aterriza de uno en uno (los tests de arriba). Poniendolo, dos drones cuyos
# pads disten lo suficiente maniobran en paralelo, que es como opera un
# vertipuerto de verdad.

VERTIPUERTO = OperationalScenario(
    name="Castelldefels", route_profile_name="Ruta1-Castelldefels",
    parking_lat=41.283720, parking_lon=1.985050,
    pad_spacing_m=15.0, pad_separation_m=25.0,
)

# Cuatro pads en fila cada 15 m. Con 25 m de separacion exigida: contiguos
# (15 m) se estorban; a dos plazas o mas (30 m y 45 m) no.
PADS = VERTIPUERTO.parking_slots(4)


def _pad(a, drone_id, indice, maniobra="despegar"):
    lat, lon = PADS[indice]
    return a.acquire_pad(drone_id, lat, lon, maniobra)


def test_far_enough_pads_manoeuvre_at_the_same_time():
    a = AirspaceManager(VERTIPUERTO, slot_count=4)

    assert _pad(a, "Dron-1", 0)
    assert _pad(a, "Dron-4", 3), "45 m de separacion: caben los dos"
    assert sorted(a.pad_holders()) == ["Dron-1", "Dron-4"]


def test_neighbouring_pads_still_wait_their_turn():
    a = AirspaceManager(VERTIPUERTO, slot_count=4)

    assert _pad(a, "Dron-1", 0)
    assert not _pad(a, "Dron-2", 1), "15 m no es separacion suficiente"

    a.release_pad("Dron-1")

    assert _pad(a, "Dron-2", 1)


def test_a_landing_goes_before_a_waiting_take_off():
    """El que vuelve tiene la bateria gastada; el que despega, no."""
    a = AirspaceManager(VERTIPUERTO, slot_count=4)
    _pad(a, "Dron-1", 0)                       # ocupa la vertical
    assert not _pad(a, "Dron-2", 1, "despegar")     # se pone a la cola
    assert not _pad(a, "Dron-3", 1, "aterrizar")    # y este tambien

    a.release_pad("Dron-1")

    assert a.pad_queue()[0] == "Dron-3", "el aterrizaje va primero"
    assert not _pad(a, "Dron-2", 1, "despegar"), "no se cuela"
    assert _pad(a, "Dron-3", 1, "aterrizar")


def test_a_distant_pad_does_not_have_to_wait_for_the_queue():
    """La prioridad no serializa: solo ordena a los que se estorban."""
    a = AirspaceManager(VERTIPUERTO, slot_count=4)
    _pad(a, "Dron-1", 0)
    assert not _pad(a, "Dron-3", 1, "aterrizar"), "vecino del ocupante"

    assert _pad(a, "Dron-4", 3), "lejos de ambos: no le afecta la cola"


def test_the_take_off_stagger_only_counts_nearby_pads():
    """El escalonado se aplica a quien se estorba, no a toda la flota.

    Contarlo globalmente encadenaba 10, 20 y 30 s con cuatro drones, y al
    terminar la espera el dron se encontraba igualmente la vertical ocupada:
    el retardo no separaba nada, solo retrasaba.
    """
    reloj = {"t": 0.0}
    escenario = OperationalScenario(
        name="Castelldefels", route_profile_name="Ruta1-Castelldefels",
        parking_lat=41.283720, parking_lon=1.985050,
        pad_spacing_m=15.0, pad_separation_m=25.0, takeoff_gap_s=10.0,
    )
    a = AirspaceManager(escenario, slot_count=4, clock=lambda: reloj["t"])

    assert a.takeoff_delay_s("Dron-1", *PADS[0]) == 0.0
    assert a.takeoff_delay_s("Dron-4", *PADS[3]) == 0.0, "pad lejano: sin retardo"
    assert a.takeoff_delay_s("Dron-2", *PADS[1]) == pytest.approx(10.0), "pad vecino"


def test_without_pad_coordinates_the_behaviour_is_the_old_exclusive_one():
    """Compatibilidad: sin geometria no hay concurrencia que valga."""
    a = AirspaceManager(VERTIPUERTO, slot_count=4)

    assert a.acquire_pad("Dron-1")
    assert not a.acquire_pad("Dron-2")


def test_the_hard_capacity_caps_concurrency_below_the_geometry():
    limitado = OperationalScenario(
        name="Castelldefels", route_profile_name="Ruta1-Castelldefels",
        parking_lat=41.283720, parking_lon=1.985050,
        pad_spacing_m=15.0, pad_separation_m=25.0, vertiport_capacity=1,
    )
    a = AirspaceManager(limitado, slot_count=4)

    assert _pad(a, "Dron-1", 0)
    assert not _pad(a, "Dron-4", 3), "la geometria lo permitiria, el tope no"


def test_the_stagger_does_not_chain_through_an_incompatible_neighbour():
    """El escalonado busca hueco, no se pone detras del ultimo.

    Rejilla de tres columnas: la plaza 3 es compatible con la 1 (17 m) pero
    incompatible con la 2 (8,5 m). Encadenando, la 2 se iba a t=10 y la 3 a
    t=20, cuando podia haber salido con la 1 en t=0. Con seis drones eso
    convertia las tandas en seis despegues de uno en uno, y el escalonado
    anulaba justo la concurrencia que el vertipuerto acababa de conceder.
    """
    rejilla = OperationalScenario(
        name="Castelldefels", route_profile_name="Ruta1-Castelldefels",
        parking_lat=41.283720, parking_lon=1.985050,
        pad_layout="rejilla", pad_cols=3, pad_spacing_m=8.5,
        pad_separation_m=13.0, takeoff_gap_s=10.0,
    )
    pads = rejilla.parking_slots(6)
    a = AirspaceManager(rejilla, slot_count=6, clock=lambda: 0.0)

    retardos = [a.takeoff_delay_s(f"Dron-{k + 1}", *pads[k]) for k in range(6)]

    assert retardos[0] == retardos[2] == 0.0, "1 y 3 son compatibles: van juntos"
    assert retardos[3] == retardos[5], "4 y 6 tambien"
    assert retardos[1] >= 10.0, "el 2 se estorba con ambos y espera"
    assert max(retardos) == 30.0, "cuatro tandas, no seis despegues sueltos"


def test_a_free_slot_between_two_reserved_ones_is_used():
    """Si cabe en medio, se mete en medio en vez de irse al final."""
    escenario = OperationalScenario(
        name="Castelldefels", route_profile_name="Ruta1-Castelldefels",
        parking_lat=41.283720, parking_lon=1.985050,
        takeoff_gap_s=10.0,
    )
    reloj = {"t": 0.0}
    a = AirspaceManager(escenario, slot_count=4, clock=lambda: reloj["t"])

    # Sin coordenadas todos se estorban, asi que se reparten en el tiempo.
    assert a.takeoff_delay_s("Dron-1") == 0.0
    assert a.takeoff_delay_s("Dron-2") == pytest.approx(10.0)

    # Un tercero que llega en t=20 cabe justo ahi: a 10 s del segundo.
    reloj["t"] = 20.0
    assert a.takeoff_delay_s("Dron-3") == 0.0


def test_a_compatible_drone_joins_the_wave_despite_arriving_late():
    """Los ejecutores no arrancan a la vez, y por decimas no se pierde la tanda.

    Con el pad 4 saliendo en t=0 y el 5 en t=10, el 6 —compatible con el 4—
    pedia turno en t=0,2 y encontraba 9,8 s hasta el 5 en vez de 10. Le
    faltaban dos decimas y se iba una tanda entera mas tarde, justo el efecto
    que el vertipuerto acababa de eliminar.
    """
    rejilla = OperationalScenario(
        name="Castelldefels", route_profile_name="Ruta1-Castelldefels",
        parking_lat=41.283720, parking_lon=1.985050,
        pad_layout="rejilla", pad_cols=3, pad_spacing_m=8.5,
        pad_separation_m=13.0, takeoff_gap_s=10.0,
    )
    pads = rejilla.parking_slots(6)
    reloj = {"t": 0.0}
    a = AirspaceManager(rejilla, slot_count=6, clock=lambda: reloj["t"])

    # El orden es el que decide el asignador, no el de las plazas.
    salidas = {}
    for paso, dron in enumerate([4, 5, 6, 1, 3, 2]):
        reloj["t"] = paso * 0.1
        salidas[dron] = reloj["t"] + a.takeoff_delay_s(
            f"Dron-{dron}", *pads[dron - 1])

    assert salidas[6] == pytest.approx(salidas[4], abs=0.5), "4 y 6 son compatibles"
    assert salidas[3] == pytest.approx(salidas[1], abs=0.5), "1 y 3 tambien"
    assert max(salidas.values()) == pytest.approx(30.0, abs=0.5), "cuatro tandas"


def test_an_incompatible_drone_never_joins_a_wave():
    """El margen de la tanda no puede colar a quien se estorba."""
    rejilla = OperationalScenario(
        name="Castelldefels", route_profile_name="Ruta1-Castelldefels",
        parking_lat=41.283720, parking_lon=1.985050,
        pad_layout="rejilla", pad_cols=3, pad_spacing_m=8.5,
        pad_separation_m=13.0, takeoff_gap_s=10.0,
    )
    pads = rejilla.parking_slots(6)
    reloj = {"t": 0.0}
    a = AirspaceManager(rejilla, slot_count=6, clock=lambda: reloj["t"])

    a.takeoff_delay_s("Dron-1", *pads[0])
    reloj["t"] = 0.2

    # El pad 2 esta a 8,5 m del 1: no puede salir en su misma tanda.
    assert a.takeoff_delay_s("Dron-2", *pads[1]) >= 9.0
