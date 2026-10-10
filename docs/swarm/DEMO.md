# Guion de demostración

Secuencia reproducible para enseñar el sistema en unos quince minutos. Cada
paso dice **qué se ve** y **qué demuestra**, para poder narrarlo sin
improvisar.

Todo lo que hace falta está automatizado: los pedidos salen de
`python -m airdrop.demo`, no de rellenar formularios delante del tribunal.

---

## Antes de empezar (5 min, en frío)

```powershell
cd C:\Users\test\Desktop\TFG_FINAL\tfg-drones

# 1. Enjambre de cuatro instancias SITL
./run_swarm.ps1 launch
./run_swarm.ps1 status        # los cuatro en OK

# 2. Portal, en otra terminal
./run_local.ps1
```

Comprobaciones rápidas en `/admin.html` → **Enjambre**:

- «Probar conexión» → los cuatro en verde con su SYSID.
- La flota entera en `idle`.
- Escenario **Castelldefels** activo.

> Para ensayar sin esperar siete minutos por reparto:
> `./run_swarm.ps1 stop`, `$env:SITL_SPEEDUP = "5"`, `./run_swarm.ps1 launch`.
> Para la demo real, tiempo real (`SITL_SPEEDUP=1`).

---

## Acto 1 — El problema (2 min)

```powershell
python -m airdrop.demo list
python -m airdrop.demo seed oleada --seed 42
```

**Qué se ve:** ocho pedidos de 0,8 a 3,5 kg repartidos por Castelldefels, y
cuatro drones de tres categorías distintas.

**Qué demuestra:** hay más demanda que capacidad y los drones no son
intercambiables —los ligeros no pasan de 1 kg—. Ese es exactamente el régimen
de escasez donde la elección del asignador importa, y el mismo que mide
`research/`.

La semilla fija hace la demo repetible: el tribunal ve los mismos pedidos que
tú ensayaste.

---

## Acto 2 — Reparto autónomo (6 min)

En **Enjambre**, con `Asignación = Voraz (greedy)`, pulsar **Iniciar repartos**.

**Qué se ve, en orden:**

| Momento | Observable | Qué demuestra |
| --- | --- | --- |
| Despegue | Eventos `escalonado` de 10 y 20 s | Separación temporal en el pad |
| Subida | Cada dron a 25, 30, 35 y 40 m | Capas de altitud reservadas |
| Corredor | Eventos `espera` por HUB | Aforo del punto de confluencia |
| Cruce | Eventos `cesion` | Separación mínima en vuelo |
| Regreso | Vuelven **por la ruta de ida** a 45-60 m | Corredor aprobado y separación por sentido |
| Cola | Se vacía sola, sin volver a pulsar | Despacho autónomo |

Mientras vuelan: clicar una tarjeta de la flota **sigue** al dron en el mapa
con su ficha completa. En el portal de cliente, clicar un pedido en curso hace
lo mismo con menos detalle y muestra el tiempo estimado de entrega.

**El punto fuerte:** no hay que tocar nada. El bucle replanifica según se
liberan drones hasta vaciar la cola.

---

## Acto 3 — La aportación (4 min)

Cuando la flota vuelva a `idle`:

1. **Métricas por algoritmo** → «Actualizar». Anotar Wh/entrega y espera media.
2. Cambiar `Asignación` a **Óptima global (matriz de costes)**.
3. `python -m airdrop.demo clear` y `python -m airdrop.demo seed oleada --seed 42`
   — los **mismos** pedidos.
4. **Iniciar repartos** otra vez.
5. **Actualizar** métricas: ahora hay dos filas comparables.
6. **Descargar CSV** para la memoria.

**Qué demuestra:** que la ventaja del asignador global medida offline en
`research/` sobrevive al vuelo real, con las esperas de coordinación incluidas.
El experimento mide el algoritmo aislado; esto mide el sistema completo. Las
dos cosas hacen falta, y decir cuál es cuál es parte del argumento.

> Solo se promedian las entregas completadas. Mezclar los abortos abarataría
> artificialmente al algoritmo que más falla, que es lo contrario de lo que se
> quiere medir.

---

## Acto 4 — Seguridad (3 min)

Con un reparto en marcha, enseñar en **Eventos de seguridad**:

- `rechazo` por geovalla: `python -m airdrop.demo seed lejano` con
  `geofence_radius_m` bajado deja pedidos fuera del volumen operacional.
- `rtl` por reserva de batería: el preset `lejano` gasta mucho por entrega.
- `enlace_perdido`: parar una instancia SITL a mano
  (`taskkill /PID <pid> /F`, el PID está en `sitl_run/pids.json`). El dron sale
  de la flota operativa y **su pedido vuelve a la cola**, que es lo que hay que
  enseñar: el sistema no da por entregado lo que no lo está.

**Qué demuestra:** las mitigaciones que SORA exige para la categoría específica
—contención en un volumen, reserva de energía, techo de altura— no son
constantes escondidas en el código: salen del escenario y se pueden editar en
caliente.

---

## Cierre

```powershell
python -m airdrop.demo clear
./run_swarm.ps1 stop
```

## Si algo va mal en directo

| Síntoma | Causa más probable | Salida |
| --- | --- | --- |
| Los drones no arrancan | Argumento que el binario ya no acepta | `ArduCopter.exe --help` y comparar; ver `SITL.md` |
| «Ningún autopiloto responde» | Instancias caídas | `./run_swarm.ps1 status` |
| Pedidos rechazados | Cliente fuera de la geovalla | Subir `geofence_radius_m` |
| La cola no avanza | Pedidos por encima de la carga máxima | El portal ya los rechaza al crearlos |
| Retornos atascados | Aforo del HUB | Subir `hub_capacity` a 2 |
