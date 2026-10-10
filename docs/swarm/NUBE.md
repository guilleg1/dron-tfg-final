# El portal en la nube con SITL de verdad

El portal desplegado en Railway (https://tfg-drones.up.railway.app/) no vuela
una maqueta: lanza **cuatro autopilotos ArduCopter 4.7.1 en SITL**, uno por
dron, y el enjambre los opera por MAVLink exactamente igual que en local con
Mission Planner. El SITL de Linux es el mismo programa que lanza Mission
Planner en Windows; ArduPilot lo publica compilado en firmware.ardupilot.org.

```
                     Railway (servicio «portal»)
   navegador ──HTTP──▶ FastAPI ── enjambre ──MAVLink──▶ 4 × arducopter (SITL)
                                     ▲                     SERIAL1 5762+10i
   Mission Planner ──TCP proxy──▶ pasarela ──────────────▶ SERIAL0 5760+10i
   PC del laboratorio (puente) ──┘   └─▶ 127.0.0.1:6762+10i ─▶ enjambre
```

## Variables del servicio

| Variable | Valor | Para qué |
|---|---|---|
| `DRONE_BACKEND` | `sitl` | El enjambre usa MAVLink (con `simulado` vuelve al enlace en Python) |
| `SITL_EMBEDDED` | `1` | El portal descarga y lanza el SITL de Linux al arrancar |
| `PASARELA_PORT` | `5700` | Puerto interno de la pasarela; Railway lo publica con un proxy TCP |
| `PASARELA_TOKEN` | secreto | Contraseña del puente del PC |
| `PASARELA_GCS` | `1` | Deja entrar a Mission Planner por la pasarela (`0` para cerrarlo) |
| `SITL_SPEEDUP` | `1` | Tiempo real (por defecto) |

El binario se descarga la primera vez (7 MB) y se comprueba su SHA-256
(`airdrop/swarm/sitl_linux.py`). Cada instancia arranca en el pad que le toca
en el escenario activo; al activar otro escenario desde el panel, el portal
relanza las instancias en los pads nuevos sin reiniciarse.

## Cambiar la flota y el SITL desde el navegador

En el panel, pestaña Enjambre, **Consola de simulación** abre `/simulacion/`:
la misma herramienta que `python -m simtools` en local, con el login del
administrador. Desde ahí se cambia el número de drones (hasta 100, o `SIM_MAX_DRONES`) y su
categoría, la formación del parking (fila, rejilla o círculo, espaciado,
rumbo y separación para maniobrar a la vez), y se relanza el SITL con
aceleración ×1, ×2, ×5 o ×10. Con ×5 una oleada de ocho pedidos dura unos
diez minutos en vez de cincuenta. «Aplicar» rehace la flota y relanza las
instancias en los pads nuevos; no se puede con drones en vuelo. El ✕ de cada dron
lo quita al momento: para solo su instancia y el resto sigue conectado, sin
rehacer el enjambre. Al cambiar de escenario la flota se conserva (número y
categorías); solo «Restaurar de fábrica» vuelve a la de `fleet.json`.

Para sembrar pedidos, `oleada_flota` da dos por dron con los pesos de la
oleada (40 con 20 drones), y el campo «Pedidos» fija cualquier número hasta
500. En local: `python -m airdrop.demo seed oleada --pedidos 60`.

## Ver los drones en Mission Planner

1. En Railway, el servicio tiene un proxy TCP del tipo `xxx.proxy.rlwy.net:NNNNN`.
2. En Mission Planner: arriba a la derecha, **TCP**, **Connect**, y como host y
   puerto los del proxy.
3. Aparecen los cuatro drones (SYSID 1 a 4); se cambia de uno a otro con el
   selector de vehículo.

Mission Planner puede mandar órdenes a los drones. Si el portal se usa en una
presentación, conviene cerrar la entrada con `PASARELA_GCS=0`.

## Usar el SITL del PC del laboratorio (puente)

Cuando se quiere volar el SITL de Mission Planner del PC, o más adelante un
dron real con módem 4G, el portal no puede llamar al PC (está detrás de un
router). Es el PC el que llama:

1. En el PC, arrancar el SITL como siempre (`./run_swarm.ps1`).
2. En el PC, arrancar el puente:

   ```powershell
   python -m airdrop.swarm.puente --servidor xxx.proxy.rlwy.net:NNNNN --token <PASARELA_TOKEN>
   ```

3. En el panel, pestaña Enjambre, **Drones → SITL de mi PC (puente)**. El
   portal para el SITL de la nube y conecta cada dron en cuanto su túnel
   aparece. Para volver, **SITL en la nube**.

El escenario activo debe ser el mismo en el portal y en el PC, porque cada
instancia del PC arranca en los pads de su propio escenario.
