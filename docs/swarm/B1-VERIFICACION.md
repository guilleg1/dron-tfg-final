# B1 — acta de verificación contra SITL

Fecha: 2026-07-27
Flota: 4 drones (2 ligeros, 1 medio, 1 pesado) desde el parking Central de
Castelldefels, pads separados 8 m.
Simulación acelerada `SITL_SPEEDUP=8`.

## Resultado

| Comprobación | Resultado |
| ------------ | --------- |
| Cuatro instancias arrancan y responden | **sí** — 5760/5770/5780/5790, SYSID 1–4 |
| El enjambre conecta con las cuatro | **sí** — las cuatro en `idle` al 100 % |
| Cada dron cruza a su altitud (25/30/35/40 m) | **sí** |
| Repartos concurrentes | **sí** — tres drones en vuelo a la vez |
| Cada dron vuelve a su propio pad | **sí** — los tres aterrizan en `alt≈0` |
| Los pedidos quedan `entregado` con su `assigned_drone_id` | **sí** |
| El filtro de carga funciona | **sí** — ver más abajo |
| Batería descontada con el modelo de energía | **sí** — 100 % → 98,5–98,7 % |

Ciclo completo de reparto —despegue, ida por hub y ruta, entrega, retorno y
aterrizaje— en **100 s** de reloj a velocidad ×8.

## El reparto de los cuatro pedidos

Pedidos de 0,8 / 1,5 / 2,5 / 3,5 kg. Resultado:

| Pedido | Peso | Estado | Dron |
| ------ | ---- | ------ | ---- |
| #1 | 0,8 kg | entregado | Dron-1 (ligero) |
| #2 | 1,5 kg | entregado | Dron-3 (medio) |
| #3 | 2,5 kg | **pendiente** | — |
| #4 | 3,5 kg | entregado | Dron-4 (pesado) |

Tres de cuatro. **No es un fallo**: los pedidos se listan por id descendente,
así que el planificador ve `[#4, #3, #2, #1]` y recorre los drones en orden.
Dron-1 y Dron-2 son ligeros (1 kg máximo) y solo el primero encuentra carga que
pueda llevar; Dron-3 (2 kg) coge el de 1,5 kg; Dron-4 (4 kg) coge el de 3,5 kg.
El de 2,5 kg se queda sin ningún dron libre capaz de llevarlo y espera al
siguiente ciclo, que es el comportamiento diseñado.

El filtro de capacidad se comporta como debe: ningún dron aceptó carga por
encima de su categoría.

## Incidencias encontradas y corregidas durante la verificación

Cuatro fallos reales, todos en el lanzador o en el servicio, ninguno en la
lógica de vuelo.

1. **Las instancias morían al terminar el shell que las lanzó.**
   `subprocess.Popen`, incluso con `DETACHED_PROCESS` y
   `CREATE_BREAKAWAY_FROM_JOB`, no basta si el shell agrupa sus procesos en un
   Job Object que no permite breakaway. Se delega en `Start-Process` de
   PowerShell, que sí crea procesos independientes.

2. **El PID no podía capturarse por tubería.** `capture_output=True` hace que
   el proceso nieto herede los descriptores y PowerShell se queda esperando a
   que se cierren, colgando la llamada indefinidamente. El PID se escribe a
   fichero.

3. **La ruta de `--defaults` volvía a partirse.** PowerShell consume las
   comillas simples al construir `-ArgumentList`, así que `Mission Planner`
   llegaba partido y ArduCopter moría con `PANIC` justo después de aceptar la
   conexión TCP. Hacen falta comillas dobles **dentro** de las simples.

4. **La sonda de estado tumbaba las instancias.** `status` comprobaba el puerto
   abriendo y cerrando un socket. SERIAL0 admite un solo cliente, y esa sonda
   dejaba al autopiloto con un `Closed connection on SERIAL0` y a veces lo
   mataba: la comprobación que debía diagnosticar el problema lo causaba. Ahora
   `status` mira el proceso y el log, sin tocar el puerto.

Además se corrigieron dos defectos de diseño que la verificación destapó:

- **`connect_all` bloqueaba el arranque del portal.** Corría en serie al
  importar el módulo, así que un autopiloto que no respondiera dejaba a uvicorn
  sin levantar: el portal entero caído por un dron. Ahora conecta un dron por
  hilo y el portal arranca sin esperar.
- **`connect_all` se tragaba el motivo del fallo.** Un dron quedaba `offline`
  sin ninguna pista. Ahora el motivo se conserva en `runtime.detail` y se
  registra.

## Limitación conocida

**SERIAL0 admite un único cliente.** Si el portal se reinicia sin reiniciar
también las instancias, la ranura de la conexión anterior puede seguir ocupada
y el dron afectado responde con `WinError 10054` hasta que su instancia se
reinicia. Se observó de forma reproducible en Dron-1 tras varios reinicios del
portal.

Para una sesión normal —levantar el enjambre y después el portal, una vez— no
se manifiesta. Si aparece, `./run_swarm.ps1 stop` y volver a lanzar.

Nota útil para la demostración: cada instancia expone además **SERIAL2** en el
puerto base + 3 (5763, 5773, 5783, 5793). Mission Planner puede conectarse ahí
para ver el vuelo mientras el portal usa SERIAL0.

## Tiempos observados

- Arranque de las cuatro instancias: **12 s**
- Conexión del enjambre con la flota: **< 5 s**
- Reparto completo (×8): **100 s** de reloj
- Cuatro instancias SITL simultáneas: la máquina las sostiene sin problema
