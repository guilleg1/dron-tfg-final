"""Simulación de una jornada de reparto con llegadas aleatorias, recarga en base y replanificación periódica.

Modelo (todo lo que no se dice aquí sale del Capítulo 7 de la memoria):
  - Flota por defecto: dos ligeros, dos medios y un pesado, que empiezan la jornada con la batería llena.
  - Pedidos: llegadas de Poisson a ritmo constante lam (pedidos/h) durante la ventana de servicio;
    destinos reales de Castelldefels con dispersión de 0,5 km; pesos de la mezcla realista S2.
  - Cada dron hace un viaje de ida y vuelta por pedido. Duración = crucero (2 d / v) + T_SERV en destino.
    Al volver pasa T_TURN en la base (carga del paquete y comprobaciones) antes de estar disponible.
  - Energía del viaje: modelo lineal de core/energy.py (solo crucero). Reserva del 20 % sobre la capacidad nominal.
  - Coste de una pareja dron-pedido: la energía del viaje (core/cost.py), el mismo que usa el sistema.
  - Recarga en la base a P_CHG W mientras el dron no vuela.
  - Cada DT segundos el planificador mira los drones disponibles y la cola de pedidos pendientes y decide.
  - La ventana de servicio dura T_OPEN; después se deja T_DRAIN para vaciar la cola sin admitir pedidos nuevos.
"""
import math, random, numpy as np
from comun import *
from scipy.optimize import linear_sum_assignment
from research.simulacion.scenario_generator import DESTINATIONS, PARKING_LAT, PARKING_LON, _haversine_km

DT = 120.0          # periodo de planificación (s)
T_OPEN = 4 * 3600.0 # ventana de admisión de pedidos (s)
T_DRAIN = 3600.0    # tiempo extra para vaciar la cola (s)
T_SERV = 60.0       # tiempo en el punto de entrega (s)
T_TURN = 180.0      # tiempo en la base entre misiones (s)
P_CHG = 180.0       # potencia del cargador (W), la del Capítulo 8
PROMISE = 3600.0    # promesa de servicio: entrega en menos de una hora
MIX = [(0.5, 0.2, 1.0), (0.3, 1.0, 2.0), (0.2, 2.0, 4.0)]
FLEET = [('D-1', 'ligero'), ('D-2', 'ligero'), ('D-3', 'medio'), ('D-4', 'medio'), ('D-5', 'pesado')]

class Ord:
    __slots__ = ('id', 'w', 'd', 't', 'done', 'drone', 'e')
    def __init__(s, i, w, d, t): s.id, s.w, s.d, s.t, s.done, s.drone = i, w, d, t, None, None

def sample_order(rng, i, t, mix=MIX, wmin=None, wmax=None):
    dest = rng.choice(DESTINATIONS); sc = 0.5 / 111.0
    lat = dest['lat'] + rng.gauss(0, sc); lon = dest['lon'] + rng.gauss(0, sc)
    d = _haversine_km(PARKING_LAT, PARKING_LON, lat, lon)
    if wmin is not None: w = rng.uniform(wmin, wmax)
    else:
        u = rng.random(); acc = 0
        for p, lo, hi in mix:
            acc += p
            if u <= acc: w = rng.uniform(lo, hi); break
    return Ord(i, round(w, 2), round(d, 3), t)

def make_day(lam, seed, mix=MIX, wmin=None, wmax=None, t_open=T_OPEN):
    rng = random.Random(seed); t = 0.0; orders = []
    while True:
        t += rng.expovariate(lam / 3600.0)
        if t >= t_open: break
        orders.append(sample_order(rng, len(orders), t, mix, wmin, wmax))
    return orders

class Drone:
    def __init__(s, did, cat):
        s.id = did; s.spec = DRONE_CATEGORIES[cat]; s.cap = s.spec.battery_capacity_wh
        s.B = s.cap; s.free_at = 0.0; s.flights = []   # (salida, vuelta, pedido)
    def trip_time(s, o): return estimate_duration_s(o.d, s.spec.cruise_speed_mps) + T_SERV

def charge(drones, t0, t1):
    """recarga a P_CHG los drones que están en la base entre t0 y t1"""
    for dr in drones:
        a = max(t0, dr.free_at - T_TURN)   # aterriza en free_at - T_TURN y ya carga durante el turno
        if t1 > a: dr.B = min(dr.cap, dr.B + P_CHG * (t1 - a) / 3600.0)

def cost_of(dr, o):
    """Energía del viaje (Wh) o infinito si la pareja es inviable. Se devuelve dos veces por comodidad."""
    c = compute_cost(dr.spec, dr.B, o.w, o.d)
    return c, c

# ───────────────────────── políticas ─────────────────────────
def pol_fifo(t, avail, queue, drones):
    out = []; av = list(avail)
    for o in sorted(queue, key=lambda o: o.t):
        best = (math.inf, None, None)
        for dr in av:
            c, e = cost_of(dr, o)
            if c < best[0]: best = (c, dr, e)
        if best[1] is not None:
            out.append((best[1], o, best[2])); av.remove(best[1])
        if not av: break
    return out

def _lsa(avail, queue, bonus):
    M = np.full((len(avail), len(queue)), 1e9); E = {}
    for i, dr in enumerate(avail):
        for j, o in enumerate(queue):
            c, e = cost_of(dr, o)
            if c < math.inf: E[i, j] = e
    if not E: return []
    e_med = float(np.mean(list(E.values())))     # energía media de las parejas viables del ciclo
    for (i, j), e in E.items(): M[i, j] = e - e_med * bonus(queue[j])
    ri, ci = linear_sum_assignment(M)
    return [(avail[i], queue[j], E[i, j]) for i, j in zip(ri, ci) if (i, j) in E]

def pol_jv(t, avail, queue, drones):
    return _lsa(avail, queue, lambda o: 0.0)

# Antigüedad: un pedido que lleva la promesa entera esperando descuenta BETA veces la energía de un viaje medio.
BETA = 1.0
def pol_jv_age(t, avail, queue, drones):
    return _lsa(avail, queue, lambda o: BETA * min((t - o.t) / PROMISE, 1.0))

H_PLAN = 3600.0
NOW_BONUS = 0.5
# desempate por energía: con EPS = 1e-3 y menos de mil pedidos en el plan, la energía nunca compensa una entrega
EPS = 1e-3
def pol_milp(t, avail, queue, drones, time_limit=3, phantoms=()):
    """Horizonte deslizante: planifica los próximos H_PLAN s para toda la flota (también los drones en vuelo,
    con la batería y la hora a la que volverán), maximiza los pedidos servidos dando más valor a los que más
    esperan y, a igualdad, menos energía. Solo se despachan las primeras salidas de los drones disponibles."""
    import pulp
    if not queue: return []
    real = len(queue); queue = list(queue) + list(phantoms)
    pr = pulp.LpProblem('plan', pulp.LpMaximize); x = {}; E = {}; TT = {}
    for i, dr in enumerate(drones):
        for j, o in enumerate(queue):
            if o.w > dr.spec.max_payload_kg: continue
            e = estimate_trip_energy_wh(dr.spec, o.d, o.w); E[i, j] = e; TT[i, j] = dr.trip_time(o) + T_TURN
            x[i, j] = pulp.LpVariable(f'x_{i}_{j}', cat='Binary')
    if not x: return []
    emax = max(E.values())
    val = {j: (1.0 + BETA * min((t - o.t) / PROMISE, 1.0)) if j < real else PHANTOM_VALUE for j, o in enumerate(queue)}
    now = {i for i, dr in enumerate(drones) if dr in avail}
    # un pedido que sale ahora vale algo más que el mismo pedido planificado para más tarde
    pr += pulp.lpSum(x[k] * (val[k[1]] + (NOW_BONUS if (k[0] in now and k[1] < real) else 0.0) - EPS * E[k] / emax) for k in x)
    for j in range(len(queue)): pr += pulp.lpSum(x[i, j] for i in range(len(drones)) if (i, j) in x) <= 1
    for i, dr in enumerate(drones):
        ks = [k for k in x if k[0] == i]
        if not ks: continue
        usable = dr.B - R * dr.cap                     # sin contar la recarga dentro del horizonte (conservador)
        # cada misión deja T_TURN s en la base, que el dron aprovecha para recargar
        pr += pulp.lpSum(x[k] * (E[k] - P_CHG * T_TURN / 3600.0) for k in ks) <= max(usable, 0)
        for k in ks:
            if E[k] > usable: pr += x[k] == 0
        pr += pulp.lpSum(x[k] * TT[k] for k in ks) <= max(H_PLAN - max(dr.free_at - t, 0), 0)
    pr.solve(pulp.PULP_CBC_CMD(msg=0, timeLimit=time_limit))
    out = []
    for i, dr in enumerate(drones):
        if dr not in avail: continue
        mine = [j for (ii, j) in x if ii == i and j < real and x[ii, j].value() and x[ii, j].value() > 0.5]
        if mine:
            j = max(mine, key=lambda j: (val[j], -E[i, j]))   # el más antiguo de su plan sale primero
            out.append((dr, queue[j], E[i, j]))
    return out


# ── horizonte deslizante con previsión: añade pedidos «previstos» muestreados de la propia demanda ──
LAM_FORECAST = {'lam': None}
PHANTOM_VALUE = 0.7
def pol_milp_fc(t, avail, queue, drones, time_limit=3):
    lam = LAM_FORECAST['lam']
    rng = random.Random(int(t) * 7 + 1)
    horizon = min(H_PLAN, max(T_OPEN - t, 0))
    nf = int(round(lam * horizon / 3600.0 * 0.5))           # media hora de demanda prevista dentro del plan
    ph = []
    ph = [sample_order(rng, -1 - k, t) for k in range(nf)]   # pedidos con la mezcla y los destinos reales
    return pol_milp(t, avail, queue, drones, time_limit, phantoms=ph)

POLICIES = {'FIFO': pol_fifo, 'JV': pol_jv, 'JV+antigüedad': pol_jv_age, 'MILP horizonte': pol_milp, 'MILP con previsión': pol_milp_fc}

# ───────────────────────── bucle de simulación ─────────────────────────
def simulate(orders, policy, keep_trace=False, fleet=None):
    drones = [Drone(i, c) for i, c in (fleet or FLEET)]
    pend = []; k = 0; t = 0.0; nxt = 0
    while t <= T_OPEN + T_DRAIN:
        while nxt < len(orders) and orders[nxt].t <= t: pend.append(orders[nxt]); nxt += 1
        avail = [dr for dr in drones if dr.free_at <= t]
        if avail and pend:
            for dr, o, e in policy(t, avail, pend, drones):
                if dr.B - e < R * dr.cap - 1e-9: continue           # comprobación de seguridad final
                tt = dr.trip_time(o)
                dr.B -= e; dr.free_at = t + tt + T_TURN
                o.done = t + (tt - T_SERV) / 2 + T_SERV; o.drone = dr.id    # entrega al terminar el servicio en destino
                o.e = e
                dr.flights.append((t, t + tt, o.id))
                pend.remove(o)
        charge(drones, t, t + DT); t += DT
    return metrics(orders, drones, keep_trace)

def metrics(orders, drones, keep_trace=False):
    n = len(orders); served = [o for o in orders if o.done is not None]
    waits = np.array([(o.done - o.t) / 60 for o in served]) if served else np.array([np.nan])
    in_promise = sum(1 for o in served if o.done - o.t <= PROMISE)
    kgkm_tot = sum(o.w * o.d for o in orders)
    E = sum(o.e for o in served)
    late_heavy = [o for o in orders if o.w > 2]
    far = sorted(orders, key=lambda o: -o.d)[:max(1, n // 4)]
    def p_in(lst): return np.mean([o.done is not None and o.done - o.t <= PROMISE for o in lst]) if lst else np.nan
    r = dict(n=n, served=len(served) / n, promise=in_promise / n,
             wait_mean=float(np.nanmean(waits)), wait_p95=float(np.nanpercentile(waits, 95)),
             backlog=n - len(served), e_per_kgkm=E / max(sum(o.w * o.d for o in served), 1e-9),
             e_per_del=E / max(len(served), 1), promise_heavy=p_in(late_heavy), promise_far=p_in(far),
             kgkm=sum(o.w * o.d for o in served) / kgkm_tot)
    if keep_trace:
        r['trace'] = {dr.id: dr.flights for dr in drones}
        r['waits'] = waits.tolist()
    return r

if __name__ == '__main__':
    import time, sys
    lam = float(sys.argv[1]) if len(sys.argv) > 1 else 20
    LAM_FORECAST['lam'] = lam
    for name, pol in POLICIES.items():
        t0 = time.time(); res = [simulate(make_day(lam, s), pol) for s in range(3)]
        print(f'{name:16s} lam={lam:4.0f}  servidos {np.mean([r["served"] for r in res])*100:5.1f}%  en promesa {np.mean([r["promise"] for r in res])*100:5.1f}%  '
              f'espera media {np.mean([r["wait_mean"] for r in res]):5.1f} min  p95 {np.mean([r["wait_p95"] for r in res]):5.1f}  '
              f'Wh/kgkm {np.mean([r["e_per_kgkm"] for r in res]):5.2f}   ({(time.time()-t0)/3:.1f} s/día)', flush=True)
