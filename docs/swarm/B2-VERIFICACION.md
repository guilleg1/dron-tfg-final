# B2 — acta de verificación contra SITL

Fecha: 2026-07-27
Flota: 4 drones (2 ligeros, 1 medio, 1 pesado), escenario Castelldefels.
Seis pedidos de 0,8 / 1,2 / 1,5 / 2,0 / 2,5 / 3,5 kg. Simulación a ×10.

**Estado: parcialmente verificado. Queda un fallo abierto, descrito abajo.**

## Lo que sí quedó verificado

| Comprobación | Resultado |
| ------------ | --------- |
| La lógica completa con `FakeDroneLink` | **199 tests en verde**, sin SITL |
| El escenario activo fija capas, separación y escalonado | sí: `capas=[25, 30, 35, 40] sep=30 m gap=10 s` |
| Despegues escalonados | sí: eventos `escalonado` de 10 s y 20 s |
| Cada dron cruza en su propia capa | sí: 25, 30 y 35 m simultáneos |
| Reserva y liberación de slots | sí: el slot vuelve al fondo común al aterrizar |
| El greedy respeta la capacidad | sí: los dos ligeros nunca reciben más de 1 kg |
| Esperas por HUB registradas en la bitácora | sí: eventos `espera` |
| Entregas completas contra autopilotos reales | sí, pero solo 1–2 por ejecución |

## Cinco fallos encontrados y corregidos

Ninguno era visible con los tests de doble instantáneo. Todos salieron al
volar contra SITL, y todos tienen ya test de regresión.

1. **Interbloqueo en el HUB.** Un dron retenía el HUB mientras cedía por
   separación ante otro que esperaba precisamente ese HUB. Ninguno avanzaba.
   Corregido dando prioridad de paso al que ocupa el HUB.

2. **Inanición en el HUB.** `acquire_hub` era por orden de petición sin cola,
   así que el que pedía justo al liberarse se lo llevaba una y otra vez.
   Corregido con cola FIFO.

3. **Carrera al lanzar una entrega.** El estado del dron pasaba a ocupado
   dentro del hilo del ejecutor, así que el siguiente ciclo de planificación
   lo veía todavía `idle` y le daba un segundo pedido, que se perdía. Se
   observó como cinco asignaciones para tres drones. Corregido marcando el
   estado de forma síncrona en `_launch`, bajo el lock.

4. **Pedidos huérfanos.** Si el ejecutor rechazaba por falta de slot, el
   pedido ya estaba marcado `asignado` y se quedaba así para siempre, fuera de
   la cola. Corregido devolviéndolo a `pendiente`.

5. **El panel mentía en el retorno.** El detalle se quedaba congelado en
   «esperando: HUB ocupado» aunque el dron ya hubiera entrado y estuviera
   volando. Además de engañar al operador, **desvió el diagnóstico del fallo
   abierto**: pareció una espera de HUB cuando era otra cosa. Corregido
   informando de cada fase del retorno.

Se añadieron además dos mitigaciones: reenvío del destino cada 5 s —un `goto`
en GUIDED es idempotente y así se cubren los comandos que el autopiloto
descarta mientras cambia de modo— y autoliberación del HUB si su ocupante
lleva más de 90 s dentro.

## Fallo abierto

**El tramo de retorno hasta el HUB no se completa** contra SITL real cuando
vuelan tres drones con `hub_exclusive` activo. Los drones entran en
«volviendo» y no llegan nunca, hasta que el tramo agota sus 300 s y quedan en
`error`. Se reproduce en las tres ejecuciones realizadas; entregan 1–2 pedidos
de 6 antes de atascarse.

Lo que ya está descartado:

- No es el interbloqueo del punto 1: se corrigió y el síntoma persiste.
- No es inanición de la cola: se corrigió y persiste.
- No es que se pierda el `goto` tras un `resume`: con reenvío cada 5 s
  persiste.

### Causa identificada

La última ejecución de diagnóstico lo aclara: el log se llena de

```
Connection reset or closed by peer on TCP socket
```

**No es un problema de vuelo: se caen las conexiones MAVLink.** Muerto el
socket, el `goto` no llega, la telemetría se congela, `has_arrived` no se
cumple nunca y el tramo agota sus 300 s. Los tres drones acaban en `error` por
la misma causa, a intervalos de 90 s, que es justo el orden en que se
quedaron sin enlace.

Queda descartada la hipótesis del re-armado tras aterrizar en el cliente.

### Causa raíz: el portal peleaba por SERIAL0

Con la simulación levantada por el usuario quedó claro. El log de cada
instancia muestra un único `New connection on SERIAL0` al arrancar: **es
Mission Planner**. SERIAL0 admite un solo cliente, así que el portal nunca
podía entrar por ahí, y sus intentos aparecían como resets.

Un escaneo contra esa simulación encontró los ocho endpoints libres —SERIAL1 y
SERIAL2 de los cuatro drones— y ninguno en SERIAL0. El puerto por defecto pasó
a **SERIAL1** (5762, 5772, 5782, 5792) y los cuatro drones conectan.

Dos fallos propios salieron por el camino:

- **La sonda usaba un timeout de 1 s para dos cosas distintas:** abrir el
  socket y esperar el heartbeat. Los heartbeats van a 1 Hz, así que la ventana
  los perdía casi siempre y el puerto parecía muerto teniendo un autopiloto
  detrás. Ahora son 0,3 s para el socket y 3 s para el heartbeat.
- **La siembra no pisa lo que ya existe,** así que una base de datos con
  puertos antiguos los conservaba aunque cambiara el valor por defecto. De ahí
  el botón «Restablecer puertos».

### Carencia propia, ya cerrada

El enjambre **no detectaba la pérdida de enlace**. La §6.2 del diseño pedía un
vigilante de telemetría congelada y se había quedado sin implementar: por eso
una caída de enlace se manifestaba como un atasco inexplicable —`runtime.lat`
conserva el último valor conocido en vez de quedar a `None`, así que el dron
parecía sano mientras era inalcanzable, y seguía reteniendo su slot y su turno
de HUB.

Implementado: `DroneLink.telemetry_age_s()`, la política devuelve `LINK_LOST`
pasados 10 s sin datos, y el ejecutor marca el dron en `error`, devuelve el
pedido a la cola y libera slot y HUB. Se comprueba **antes** que el resto,
porque sin enlace decidir un RTL por batería baja sería decidir sobre datos
viejos. Y no se manda ningún comando: no hay a quién.

### Pendiente

- Repetir la prueba de extremo a extremo con los cuatro drones conectados por
  SERIAL1, para ver si los retornos siguen atascándose. Es lo único que queda
  del bloque, y lo conduce el usuario.
- Reconexión automática en `MavlinkDroneLink`, que hoy no la tiene: detecta la
  pérdida pero no vuelve a intentarlo.

**Rodeo mientras tanto:** poner `hub_exclusive = false` en el escenario desde
el panel elimina la serialización del corredor. No resuelve la causa, pero
permite demostrar el resto del bloque.

## Nota de diseño

Tal como está implementado, `hub_exclusive` significa en la práctica *un dron
a la vez en todo el corredor de salida*, no solo en el HUB: se reserva tras
despegar y se libera al alcanzarlo. Es conservador y seguro, pero serializa
mucho más de lo que el nombre sugiere y amplifica cualquier atasco de un dron
hasta bloquear a la flota. Conviene reducir la ventana de reserva a las
proximidades del HUB.

## Tiempos observados

- Arranque de las cuatro instancias: 12 s
- Conexión del enjambre con la flota: < 5 s
- Primera entrega completa (×10): 100 s
- Tres drones volando en paralelo de forma sostenida: sí, hasta el atasco
