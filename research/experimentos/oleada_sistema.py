"""Oleada de demostración sobre el sistema completo (pruebas PO-8 y PV-9, Tablas 11.3 y 11.5).

Monta el orquestador real (planificador, espacio aéreo, seguridad, ejecutores y métricas) con el escenario
activo de Castelldefels y la flota por defecto. Siembra la oleada de demostración con semilla fija y la
reparte dos veces, una con cada asignador, en bases de datos limpias.

Por defecto los drones son ``FakeDroneLink`` (PO-8). Con ``--sitl`` son autopilotos ArduCopter de verdad:
el SITL de Linux, una instancia por dron en su pad, por MAVLink (PV-9). En tiempo real tarda unos
cincuenta minutos por asignador; con ``SITL_SPEEDUP=5`` el simulador va cinco veces más rápido y la
prueba entera, con los dos, cabe en unos veinte minutos.

    python oleada_sistema.py            # escribe oleada_sistema.json
    SITL_SPEEDUP=5 python oleada_sistema.py --sitl     # escribe oleada_sitl.json
"""
import collections
import json
import os
import sys
import tempfile
import time

_AQUI = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('AIRDROP_REPO') or os.path.abspath(os.path.join(_AQUI, '..', '..'))
STEPS = int(os.environ.get('PASOS_TRAMO', '8'))
SEMILLA = 42
CON_SITL = '--sitl' in sys.argv


def una_oleada(algoritmo):
    tmp = tempfile.mkdtemp()
    os.environ['DATABASE_URL'] = 'sqlite:///' + os.path.join(tmp, 'po8.db').replace('\\', '/')
    for m in [m for m in sys.modules if m.startswith('airdrop')]:
        del sys.modules[m]
    sys.path.insert(0, REPO)
    import contextlib
    import io
    from airdrop.api import main as portal
    from airdrop import demo
    from airdrop.swarm.fake import FakeDroneLink
    from airdrop.swarm.repository import FleetRepository
    from airdrop.swarm.service import SwarmService

    flota = FleetRepository(portal.store.engine)
    flota.seed_if_empty(portal._active_scenario())
    with contextlib.redirect_stdout(io.StringIO()):
        demo.seed('oleada', SEMILLA)
    pedidos = portal._OrdersStore(portal.store)
    n = len(pedidos.list_pending())
    sitl = None
    if CON_SITL:
        from airdrop.swarm.link import MavlinkDroneLink
        from airdrop.swarm.sitl_linux import EmbeddedSitl
        sitl = EmbeddedSitl(root=os.path.join(tmp, 'sitl'))
        arrancados = sitl.start(flota.list_drones())
        assert all(arrancados.values()), arrancados

        def enlace(r):
            return MavlinkDroneLink(r.drone_id, r.connection, r.home_lat, r.home_lon)
    else:
        def enlace(r):
            return FakeDroneLink(r.drone_id, r.home_lat, r.home_lon, steps_per_leg=STEPS)
    svc = SwarmService(
        scenario=portal._active_scenario(), repository=flota,
        link_factory=enlace, build_mission=portal._build_mission)
    svc.connect_all()
    svc.set_algorithm(algoritmo)
    t0 = time.time()
    svc.start_auto(pedidos)
    # Contra SITL el pesado encadena cuatro o cinco pedidos: en tiempo real la
    # oleada entera ronda los 50 minutos.
    limite = 4800 if CON_SITL else 1800
    while time.time() - t0 < limite:
        estados = [o['status'] for o in portal.store.list_orders(None)]
        if all(s in ('entregado', 'cancelado') for s in estados) and not svc.busy:
            break
        time.sleep(0.5)
    svc.stop_auto()
    svc.wait_idle(30)
    resumen = svc.metrics.summary()
    eventos = collections.Counter(e['kind'] for e in svc.safety.events())
    estados = collections.Counter(o['status'] for o in portal.store.list_orders(None))
    if sitl is not None:
        svc.close_all()
        sitl.stop()
    return dict(algoritmo=algoritmo, enlace='sitl' if CON_SITL else 'simulado', pedidos=n,
                speedup=float(os.environ.get('SITL_SPEEDUP') or 1) if CON_SITL else None,
                segundos=round(time.time() - t0, 1), estados=dict(estados),
                resumen=resumen, eventos=dict(eventos), entregas=svc.metrics.all())


if __name__ == '__main__':
    out = [una_oleada(a) for a in ('greedy', 'cost_matrix')]
    for o in out:
        print(o['algoritmo'], o['pedidos'], o['segundos'], o['resumen'], o['eventos'])
    nombre = 'oleada_sitl.json' if CON_SITL else 'oleada_sistema.json'
    json.dump(out, open(os.path.join(_AQUI, nombre), 'w'), indent=1, default=str)
