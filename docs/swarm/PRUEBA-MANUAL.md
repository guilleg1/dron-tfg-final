# Prueba manual con Mission Planner

Procedimiento para validar el enjambre tú mismo, levantando la simulación por
tu cuenta y dando feedback sobre lo que veas. El portal solo se conecta a los
puertos y manda comandos; no lanza nada.

## Puertos: quién usa cada uno

Cada instancia SITL abre tres puertos, con base 5760 y +10 por instancia:

| | Dron-1 | Dron-2 | Dron-3 | Dron-4 |
| --- | --- | --- | --- | --- |
| **SERIAL0** | 5760 | 5770 | 5780 | 5790 |
| SERIAL1 | 5762 | 5772 | 5782 | 5792 |
| SERIAL2 | 5763 | 5773 | 5783 | 5793 |

**SERIAL0 admite un solo cliente, y lo toma Mission Planner** al abrir la
simulación. Se ve en el log de cada instancia: un único
`New connection on SERIAL0` al arrancar.

> **SERIAL0 no se sondea.** Conectarse y marcharse deja al autopiloto con un
> `Closed connection on SERIAL0` y lo tumba. El 2026-08-06 «Buscar
> autopilotos» barría 5760-5800 —SERIAL0 incluido— y mataba las cuatro
> instancias: el primer clic devolvía poco y el segundo ya no encontraba nada,
> con `status` dando «PROCESO MUERTO» a los cuatro. Desde entonces el escaneo
> solo mira SERIAL1 y SERIAL2, y `probe()` rechaza SERIAL0 sin abrir el
> socket.

Por eso **el portal usa SERIAL1 por defecto**: 5762, 5772, 5782, 5792. Así
conviven. Verificado contra una simulación real de cuatro drones, donde un
escaneo encontró los ocho endpoints libres —SERIAL1 y SERIAL2 de cada dron— y
ninguno en SERIAL0.

Si tu montaje reparte los puertos de otra forma, no hay que adivinarlo: el
panel trae buscador y los puertos son editables.

## Aviso sobre `sitl.bat`

Los `--home` de tu `Documents\Mission Planner\sitl.bat` están en
**41.3809, 2.1228** (Sant Adrià), a unos 25 km de Castelldefels. Con el
escenario de Castelldefels activo, la geovalla de 1500 m rechazará todos los
pedidos.

Dos salidas:

1. Editar los `--home` de `sitl.bat` con los pads del escenario. Los da
   `python -c "from airdrop.swarm.sitl import _records; [print(r.drone_id, r.home_lat, r.home_lon) for r in _records()]"`
2. Usar `./run_swarm.ps1 launch`, que ya los pone bien, y conectar Mission
   Planner a las instancias que levanta.

## Procedimiento

1. **Levanta la simulación** como prefieras (Mission Planner o
   `./run_swarm.ps1 launch`).

2. **Arranca el portal** en otra terminal:

   ```powershell
   ./run_local.ps1
   ```

   Levanta aunque los drones no respondan; no se queda esperándolos.

3. **Entra en `/admin.html` → pestaña Enjambre.**

4. **Pulsa «Buscar autopilotos».** Escanea 5760-5800 y lista los que contestan
   con su SYSID y qué puerto serie son. Si no aparece ninguno, la simulación no
   está arrancada o los puertos son otros.

5. **Pulsa «Probar conexión».** Muestra una fila por dron con su puerto en un
   campo editable y el resultado del enlace: verde con el SYSID, o rojo con el
   motivo. Corrige los puertos que hagan falta y pulsa **Guardar** en cada uno.

   Si los puertos guardados son antiguos, **«Restablecer puertos»** los
   recalcula todos de golpe. La siembra no pisa lo que ya existe, así que una
   base de datos creada antes de un cambio conserva los valores viejos.

6. **Reinicia el portal** si has cambiado algún puerto: la conexión se
   establece al arrancar.

   Y una regla general: **el código nuevo no llega a un portal que ya está
   corriendo.** Si se toca el código, primero reiniciar y después pulsar
   botones — al revés se guardan valores calculados con el código viejo.

7. **Comprueba que la flota está `idle` al 100 %** en la tabla de drones.

8. **Crea pedidos** desde el portal de cliente con una dirección de la zona del
   escenario, y con pesos variados: los ligeros solo llevan 1 kg.

9. **Pulsa «Iniciar repartos»** y observa. Arranca el **despacho autónomo**: el
   planificador replanifica cada pocos segundos y va asignando según se
   liberan drones, hasta vaciar la cola. No hay que volver a pulsar por cada
   oleada. «Parar todo» detiene también el bucle, no solo las entregas en
   curso.

   El desplegable **Asignación** elige el algoritmo —voraz u óptima global por
   matriz de costes— y permite comparar ambos sobre el enjambre real y no solo
   en las gráficas de `research/`. No se puede cambiar con drones en vuelo:
   mezclar dos criterios a mitad de oleada haría incomparable lo observado.

## Regreso por la ruta de ida

El retorno **no** es en línea recta al parking: rehace los waypoints de la ida
en orden inverso (destino → … → HUB → parking). Volver campo a través ignora
que el corredor está aprobado y que fuera de él no hay garantía de obstáculos
ni de sobrevuelo permitido.

Como eso pone tráfico en los dos sentidos sobre el mismo corredor, ida y vuelta
se **separan por nivel**, igual que en aviación. Las capas de ida ocupan el
bloque `alt_base_m + k·alt_step_m` y el regreso usa el bloque inmediatamente
superior, desplazado tantas capas como drones haya:

| | Dron-1 | Dron-2 | Dron-3 | Dron-4 |
| --- | --- | --- | --- | --- |
| **Ida** | 25 m | 30 m | 35 m | 40 m |
| **Vuelta** | 45 m | 50 m | 55 m | 60 m |

Ningún par ida-vuelta comparte nivel. Si el bloque de vuelta no cabe bajo
`alt_ceiling_m`, se degrada a la capa de ida y se registra el evento
`nivel_retorno`: preferimos volver al comportamiento anterior —resuelto por las
esperas tácticas— antes que romper el límite regulatorio de altura.

## Qué mirar, y qué contarme

- ¿Despegan **escalonados** o a la vez? Debería haber unos 10 s entre ellos, y
  aparecer eventos `escalonado` en la bitácora.
- ¿Cada dron cruza a **su altitud**? 25, 30, 35 y 40 m. Se ve en la columna de
  crucero y en Mission Planner.
- ¿Aparecen eventos de **espera por HUB** o de **cesión por separación**?
- ¿Se **vacía la cola sola**, sin volver a pulsar nada?
- Si algo se atasca: **en qué fase** lo pone el detalle del dron
  («despegando para volver», «volviendo por el hub», «volviendo al parking»,
  «esperando: HUB ocupado»). Esa palabra es lo que distingue las hipótesis.
- Si un dron desaparece del mapa pero el panel lo da por vivo, es pérdida de
  enlace. El vigilante de telemetría congelada **ya está implementado**
  (`SafetyPolicy.check_in_flight`): sin paquetes durante
  `telemetry_timeout_s` el vuelo termina con evento `enlace_perdido` y el
  pedido vuelve a la cola.

## Fallo conocido y su mitigación

Con cuatro drones y `hub_exclusive` activo, los tramos de retorno se atascaban
y acababan en `error` a los 300 s. Detalle completo en
[`B2-VERIFICACION.md`](B2-VERIFICACION.md).

El HUB era un cerrojo: **un** dron dentro y el resto esperando. Con el regreso
por la ruta de ida se cruza dos veces por entrega, así que toda la flota se
serializaba en ese punto y los retornos agotaban el tiempo del tramo.

Ahora el HUB es una **zona con aforo** (`hub_capacity`), que es como se modelan
las puertas de corredor en U-space. `hub_capacity = 1` reproduce exactamente el
comportamiento anterior, así que lo verificado en B2 sigue valiendo; subirlo a
**2** descongestiona el punto de confluencia sin renunciar a la deconflicción.

Órdenes de mayor a menor intervención, si el atasco reapareciera:

1. `hub_capacity` a 2 (recomendado).
2. `hub_capacity` igual al tamaño de la flota: el HUB deja de limitar, pero la
   separación mínima y las capas siguen actuando.
3. `hub_exclusive` a 0: desactiva el control del HUB por completo. Útil para
   aislar si un problema viene de ahí o de otro sitio.
