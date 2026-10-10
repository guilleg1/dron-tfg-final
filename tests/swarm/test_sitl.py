from airdrop.swarm import sitl
from airdrop.swarm.models import DroneRecord
from airdrop.swarm.sitl import build_command


def _record(instance=1):
    return DroneRecord(
        drone_id=f"Dron-{instance + 1}", sysid=instance + 1, instance=instance,
        category="medio", connection=f"tcp:127.0.0.1:{5760 + 10 * instance}",
        home_lat=41.283720, home_lon=1.985150,
    )


def test_instance_flag_comes_first():
    cmd = build_command(_record(1), binary="C:/sitl/ArduCopter.exe",
                        defaults="C:/Mission Planner/copter.parm")

    assert cmd[1:3] == ["-I", "1"], (
        "-I debe ir el primero o todas las instancias pelean por el 5760")


def test_it_uses_long_model_options():
    cmd = build_command(_record(0), binary="a.exe", defaults="b.parm")

    assert "--model" in cmd and "+" in cmd
    assert "-M+" not in cmd and "-s1" not in cmd


def test_it_does_not_pass_parameters_with_dash_p():
    # El binario de Mission Planner dejó de aceptar -P (2026-08-06). Ante una
    # opción desconocida no da error: vuelca su ayuda y sale, y las instancias
    # solo se ven como "PROCESO MUERTO". SERIAL1_PROTOCOL=2 era lo único que
    # se pasaba así y ya es el valor por defecto de ArduCopter.
    cmd = build_command(_record(0), binary="a.exe", defaults="b.parm")

    assert "-P" not in cmd and "--param" not in cmd


def test_home_is_the_drones_pad():
    record = _record(2)
    cmd = build_command(record, binary="a.exe", defaults="b.parm")

    home = cmd[cmd.index("--home") + 1]
    assert home.startswith(f"{record.home_lat},{record.home_lon}")


def test_sysid_is_passed_explicitly():
    cmd = build_command(_record(3), binary="a.exe", defaults="b.parm")

    assert cmd[cmd.index("--sysid") + 1] == "4"


def test_defaults_path_is_passed_as_a_single_argument():
    # subprocess entrecomilla solo; lo que no puede es venir partido en dos.
    cmd = build_command(_record(0), binary="a.exe",
                        defaults="C:/Mission Planner/sitl/copter.parm")

    assert cmd[cmd.index("--defaults") + 1] == "C:/Mission Planner/sitl/copter.parm"


def test_each_instance_gets_its_own_working_directory(tmp_path):
    from airdrop.swarm.sitl import working_dir

    first = working_dir(_record(0), root=tmp_path)
    second = working_dir(_record(1), root=tmp_path)

    assert first != second
    assert first.name == "Dron-1"


def test_port_is_derived_from_the_connection_string():
    from airdrop.swarm.sitl import port_of

    assert port_of(_record(0)) == 5760
    assert port_of(_record(3)) == 5790


# ── Vitalidad del proceso ────────────────────────────────────────────────

def test_a_recycled_pid_of_another_program_is_not_our_instance():
    """Windows reutiliza los PID: sin mirar la imagen, 'status' miente.

    Una instancia caida deja su PID en pids.json, Windows se lo da a otro
    proceso y el diagnostico daba las cuatro instancias como sanas estando
    muertas, que es el peor error posible en esta herramienta.
    """
    salida = '"svchost.exe","12032","Services","0","14.716 KB"\n'

    assert not sitl._tasklist_matches(salida, 12032, "ArduCopter.exe")


def test_a_live_instance_is_recognised():
    salida = '"ArduCopter.exe","12032","Console","1","30.000 KB"\n'

    assert sitl._tasklist_matches(salida, 12032, "ArduCopter.exe")


def test_the_memory_column_is_not_mistaken_for_the_pid():
    """La busqueda por subcadena daba por vivo cualquier PID que apareciera
    en la columna de memoria, que trae puntos de millar."""
    salida = '"svchost.exe","900","Services","0","12.032 KB"\n'

    assert not sitl._tasklist_matches(salida, 12032, "ArduCopter.exe")


def test_no_matching_process_is_not_alive():
    vacia = ("INFORMACION: no hay tareas ejecutandose que coincidan con los\n"
             "criterios especificados.\n")

    assert not sitl._tasklist_matches(vacia, 12032, "ArduCopter.exe")
