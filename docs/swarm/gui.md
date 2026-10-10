# Guion para la reunión con el tutor

Todo en local. Al final se menciona el despliegue previsto (Railway con PostgreSQL)
como paso pendiente, cuando la versión esté cerrada.

Duración: 35-40 min. Orden: primero lo que se ve, después lo que se argumenta.

---

## 0. Antes de que entre (5 min)

```powershell
cd C:\Users\guill\OneDrive\Escritorio\TFG_FINAL\dron-tfg-final
./run_swarm.ps1 stop
Get-Process ArduCopter -ErrorAction SilentlyContinue | Stop-Process -Force
./run_swarm.ps1 launch ; ./run_swarm.ps1 status
python -m airdrop.demo clear
```

Terminal 2: `./run_local.ps1` — el portal, en el 8080.
Terminal 3: `./run_console.ps1` — el ParkingTool, en el 8090.

**El SITL se detecta solo.** Se prueban `Documents`, `Documentos` y sus
versiones bajo `OneDrive`, así que el mismo repo funciona en equipos con la
carpeta redirigida o con Windows en otro idioma. Define `SITL_BINARY` solo si
lo tienes fuera de esas rutas.

Comprobar en `/admin.html` → Enjambre: los drones en verde, flota `idle`,
escenario Castelldefels activo, `hub_capacity` = 2.

Comprobar en el ParkingTool que la formación es la que quieres enseñar. **Si
tocas algo ahí, reinicia el portal**: el gestor de espacio aéreo se construye
al arrancar y no relee la formación en caliente.

Terminal 4, cuando vayas a empezar:
`python -m airdrop.demo seed oleada --seed 42`
(o el botón **Sembrar** del ParkingTool, que hace exactamente eso).

---

## 1. Portal de cliente (5 min)

**Entrar en `http://localhost:8080/` con un cliente.**

Qué enseñar, en este orden:

1. **Alta y dirección.** El cliente escribe una dirección y se geocodifica a
   coordenadas. Su posición es la que determina qué ruta le sirve.
2. **Crear un pedido.** Solo se elige el **peso**. El destino lo asigna el
   sistema: busca la ruta cuyo destino esté más cerca del cliente.
3. **Que rechace un pedido imposible.** Pide 10 kg: lo rechaza diciendo que el
   máximo son 4 kg. *Antes no lo hacía, y esos pedidos se quedaban en la cola
   para siempre pareciendo una avería del enjambre.*
4. **La tarjeta del pedido**: peso, destino asignado, **tiempo estimado de
   entrega**, el dron que lo lleva, su altura y la fase concreta en la que
   está.
5. **El mapa**: corredor en cian, último tramo al cliente discontinuo en
   naranja, y el dron moviéndose. Clicar el pedido sigue al dron; al arrastrar
   el mapa deja de seguirlo.

**La frase:** «el cliente no ve un *en camino* genérico, ve en qué punto del
vuelo está su paquete».

---

## 2. Panel de administración

### 2.1 Rutas (3 min)

Un **escenario de rutas** contiene: parkings, destinos, HUB y las rutas que los
unen con sus waypoints intermedios. Todo se dibuja sobre el mapa; nada está
cableado en el código.

- Selector de escenario, **Nuevo** y **Eliminar** (avisa si algún escenario
  operacional lo está usando).
- **Fijar HUB en el mapa**: el punto de confluencia por el que pasan todos.
- Parkings, Destinos, Rutas con sus intermedios.

> Ojo con el vocabulario: aquí «escenario» son las rutas; en Enjambre,
> «escenario operacional» son los límites de seguridad. Si pregunta, es un
> cambio de nombre reciente.

### 2.2 Pedidos / Flota (2 min)

Lista de pedidos y flota de referencia. Clicar un pedido enfoca su ruta;
clicar fuera o cambiar de pestaña vuelve a la vista general.

---

## 3. Enjambre — el apartado central (12 min)

Aquí es donde hay que ir despacio.

### 3.1 Escenario operacional

La lista es **la misma que la de Rutas**: cada escenario de rutas tiene aquí
sus límites de vuelo. El parking no se teclea, se elige entre los que dibujaste
en Rutas — es una sola fuente de coordenadas.

Los parámetros, agrupados como en el panel:

**Geometría**

| Parámetro | Qué es | Por qué importa |
| --- | --- | --- |
| **Espaciado entre plazas (m)** | Distancia entre plazas contiguas del parking | Dos drones en el mismo pad chocarían. Define dónde nace cada uno |
| **Disposición** | `fila`, `rejilla` o `circulo`, con sus columnas y su rumbo | La formación decide cuántos drones pueden maniobrar a la vez. Se edita en el ParkingTool (§3.8) |
| **Separación para operar a la vez (m)** | Distancia mínima entre dos plazas para que sus drones suban o bajen simultáneamente. 0 = uno cada vez | Es **el parámetro del vertipuerto**. Ver §3.8 |
| **Tope de maniobras simultáneas** | Límite duro por encima de lo que permita la geometría. 0 = sin tope | Para acotar un experimento sin mover las distancias |
| **Altitud base (m)** | Altura de la primera capa de crucero. 25 m | Es el suelo del espacio aéreo operativo: por debajo hay edificios y personas |
| **Salto capas (m)** | Separación vertical entre capas. 5 m | Con 4 drones da 25/30/35/40 m. Es la separación vertical que evita colisiones sin necesidad de esperas |
| **Techo (m)** | Altura máxima. 120 m | **Límite legal**, no técnico: Reglamento UE 2019/947 para categoría específica. Que sea parámetro permite justificar los 4 m del DroneLab |
| **Geovalla (m)** | Radio del volumen operacional alrededor del parking | Es la *contención* que exige SORA. Un cliente fuera de este círculo se rechaza; un dron que se salga entra en RTL |

**Separación**

| Parámetro | Qué es | Por qué importa |
| --- | --- | --- |
| **Separación mín. (m)** | Distancia horizontal mínima entre dos drones en vuelo. 30 m | Si dos se acercan más *y* están a menos de un salto de capa en vertical, uno cede el paso. En capas distintas la separación vertical ya basta |
| **Escalonado (s)** | Intervalo mínimo entre **tandas** de despegue. 10 s | Por la estela del anterior. Ya **no** separa a toda la flota: solo a las tandas, y una tanda son los pads que pueden salir juntos. Ver §3.8 |
| **Tolerancia wp (m)** | A qué distancia se da por alcanzado un waypoint. 5 m | Sin tolerancia un dron nunca "llega": el GPS oscila. Muy grande, corta las esquinas de la ruta |
| **Hub exclusivo (1/0)** | Si el HUB controla el paso | Con 0 se desactiva el control del punto de confluencia. Útil para aislar si un atasco viene de ahí |
| **Aforo del HUB (drones)** | Cuántos caben a la vez dentro | Era un cerrojo de uno; ahora es una zona con capacidad, como las puertas de corredor de U-space. **Es lo que resolvió el atasco de retornos** de B2 |

**Seguridad**

| Parámetro | Qué es | Por qué importa |
| --- | --- | --- |
| **Reserva batería (%)** | Energía intocable | No es un porcentaje suelto: se compara la energía **estimada del viaje completo** (`core/energy.py`) contra la batería utilizable. Es la misma función que usa el asignador, así que planificación y seguridad no pueden discrepar |
| **Pausa entrega (s)** | Tiempo en tierra en el cliente | Modela la entrega física. Ocupa al dron y por tanto entra en la planificación |

**El coste de asignación** no tiene parámetros en el panel: asignar un dron a
un pedido cuesta la energía del viaje (`core/cost.py`), y la pareja es inviable
si el paquete supera la carga o el viaje invadiría la reserva.

**Botones:** *Guardar parámetros* (aplica en caliente, incluso con drones
volando) y *Activar escenario* (cambia de emplazamiento; se rechaza con drones
en vuelo, porque cambiar altitudes a mitad de reparto es justo lo que no debe
poder hacerse desde un formulario).

**La frase clave:** «ningún parámetro de seguridad es una constante escondida
en el código. Por eso el mismo enjambre vuela a 40 m sobre Castelldefels y a
4 m dentro del DroneLab: es el mismo software con otro escenario».

### 3.2 Iniciar repartos / Parar todo

- **Iniciar repartos**: hace un ciclo de planificación y **deja el despacho
  autónomo en marcha**. El planificador vuelve a mirar cada pocos segundos y va
  asignando según se liberan drones, hasta vaciar la cola. No hay que volver a
  pulsar nada.
- Si hay pedidos que **nadie** puede llevar, avisa al instante y dice por qué
  (fuera de geovalla, por encima de la carga máxima…). No se quedan callados en
  la cola.
- **Parar todo**: aborta las entregas **y** detiene el bucle. Si solo abortara
  las entregas, el planificador las relanzaría cinco segundos después y el
  botón no pararía nada.

### 3.3 Asignación: voraz vs óptima global

**El problema.** Hay N drones libres y M pedidos, con M > N. Los drones no son
iguales: un ligero carga 1 kg, un medio 2 kg, un pesado 4 kg, y cada uno tiene
su batería y su consumo. ¿Qué pedido le doy a cada dron?

**Voraz (greedy).** Va pedido por pedido, en orden de llegada, y a cada uno le
asigna el dron más barato *disponible en ese momento*. Decide y no se
replantea.

- Ventaja: instantáneo y trivial de explicar.
- Problema: decisiones tempranas estropean las tardías. Si al primer pedido —de
  0,5 kg— le doy el dron pesado porque en ese instante salía barato, cuando
  llegue el de 3,5 kg ya no tengo dron capaz y **ese pedido no se entrega**.

**Óptima global (matriz de costes, Jonker-Volgenant).** Construye la matriz de
coste de *todos* los drones contra *todos* los pedidos y resuelve la asignación
completa de una vez, minimizando el coste total. Es el algoritmo húngaro
optimizado, O(n³).

- Ventaja: no se puede pintar en una esquina; ve el conjunto.
- Coste: más caro de calcular, y necesita conocer todos los pedidos a la vez.

**Analogía para explicarlo:** el voraz es repartir las cartas una a una dándole
la mejor a quien pase; el global es mirar todas las manos posibles y repartir
para que la mesa entera salga ganando.

> No se puede cambiar de algoritmo con drones en vuelo: mezclar dos criterios a
> mitad de oleada haría incomparable justo lo que se quiere medir.

### 3.4 Probar conexión · Buscar autopilotos · Restablecer puertos

Los tres son de diagnóstico del enlace. Conviene entender los puertos primero:

Cada instancia SITL abre **tres** puertos, base 5760 y +10 por dron:

| | Dron-1 | Dron-2 | Dron-3 | Dron-4 |
| --- | --- | --- | --- | --- |
| SERIAL0 | 5760 | 5770 | 5780 | 5790 |
| **SERIAL1** (portal) | **5762** | **5772** | **5782** | **5792** |
| SERIAL2 (Mission Planner) | 5763 | 5773 | 5783 | 5793 |

**Probar conexión.** Comprueba el enlace de cada dron de la flota. Si el portal
ya lo tiene conectado, informa de ese enlace vivo; si no, abre una conexión
efímera, espera un latido y la cierra.

> Detalle que merece contarse: SITL admite **un solo cliente por puerto**.
> Sondear un puerto que el propio portal ocupa fallaba siempre y el panel decía
> «puerto cerrado» teniendo el enlace perfectamente sano. Falso negativo
> corregido.

**Buscar autopilotos.** Escanea el rango y lista lo que responda con su SYSID y
qué puerto serie es. Sirve cuando no sabes qué puertos usa tu montaje.

> **No escanea SERIAL0 a propósito.** Ese puerto admite un cliente y sondearlo
> —conectarse e irse— **mata la instancia**: se conecta, se va, y el autopiloto
> cae con `Closed connection on SERIAL0`. Pulsar el botón dejaba el enjambre
> entero muerto. Es un buen ejemplo de fallo que solo aparece volando.

**Restablecer puertos.** Recalcula los puertos de toda la flota según la
fórmula estándar. Para cuando la base de datos guarda valores viejos de otro
montaje. Se rechaza con drones en vuelo.

### 3.5 Flota

Cada dron: estado, **pedido que lleva y la fase concreta** («volviendo por el
hub», «esperando: HUB ocupado», «entregando»), batería, capa de crucero
asignada, altitud real, posición.

Clicar una tarjeta **centra el mapa y sigue** a ese dron con su ficha completa;
al arrastrar el mapa se cancela el seguimiento. Los drones se ven en el mapa
desde cualquier pestaña.

### 3.6 Métricas por algoritmo

Cada entrega terminada registra: energía consumida, duración, **tiempo perdido
esperando** (HUB, escalonado, vertical del parking) y desenlace, junto al
algoritmo que la decidió.

La tabla compara los dos asignadores: entregas, fallos, Wh por entrega, Wh por
km, segundos por entrega y espera media. **Descargar CSV** para la memoria.

**Por qué importa, y esto es lo más defendible del proyecto:** las simulaciones
miden el algoritmo *aislado*; esto mide el *sistema completo volando*, con el
coste de la coordinación incluido. Un algoritmo puede ganar en la simulación y
perder esa ventaja al volar porque genera más conflictos. Medir las dos cosas
es lo que permite afirmar que la mejora es real.

> Solo se promedian las entregas completadas. Mezclar los abortos abarataría
> artificialmente al algoritmo que más falla, que es lo contrario de lo que se
> quiere medir.

### 3.7 Eventos de seguridad

La bitácora que **demuestra que la coordinación actúa**. Sin ella, todo lo
anterior es una afirmación: cualquiera puede decir que su sistema respeta
separaciones; esto lo enseña con hora y motivo.

Cada evento lleva dron, tipo, motivo y marca de tiempo, y se guardan los 200
últimos en memoria.

Van agrupados por lo que demuestran:

**Coordinación del tráfico** — el enjambre se organiza solo:

| Evento | Qué pasó exactamente | Qué demuestra |
| --- | --- | --- |
| `escalonado` | *«despegue retrasado 20 s»*. Al dron le tocaba una tanda posterior a la que ya estaba saliendo | Separación **temporal entre tandas**. No se retrasa a quien puede salir con los que ya van |
| `espera_pad` | *«vertical del parking ocupada; espera para despegar / aterrizar»*. Su plaza está demasiado cerca de otra que ya está maniobrando | Separación **en el volumen del vertipuerto**. Es la única regla que actúa en despegue y aterrizaje, donde las capas de altitud no protegen |
| `espera` | *«HUB ocupado por otro dron»*. Llegó al punto de confluencia sin plaza libre, se puso en LOITER y entró en cola | Control de **capacidad** en el punto crítico. El reparto es por orden de llegada, no por quién empuje más |
| `proximidad` | *«otro dron cerca en planta; separados por capa de altitud»*. Dos drones se cruzaron a menos de 30 m en horizontal, pero en capas distintas | Que la separación **vertical** está haciendo su trabajo. **No frena a nadie**, y es deliberado: ver el aviso de abajo |
| `nivel_retorno` | *«regreso por la ruta de ida a 45 m (ida a 25 m)»* | Separación **por sentido**, como en aviación. Ida y vuelta comparten corredor pero nunca nivel |

**Filtros previos al despegue** — lo que no debe salir, no sale:

| Evento | Qué pasó | Qué demuestra |
| --- | --- | --- |
| `rechazo` | El pedido no se despachó. Motivos: cliente **fuera de la geovalla**, peso **superior a la capacidad** del dron, o **el viaje completo no cabe** en la batería utilizable | Contención y reserva de energía, las dos mitigaciones que SORA exige. Se comprueban *antes* de armar |
| `sin_slot` | No quedaban capas de altitud libres, y el pedido **vuelve a la cola** | El espacio aéreo tiene aforo. Preferimos no despachar a meter dos drones en la misma capa |

**Reacciones en vuelo** — cuando algo se tuerce:

| Evento | Qué pasó | Qué demuestra |
| --- | --- | --- |
| `rtl` | Retorno forzado a mitad de misión. Tres causas: batería por debajo de la reserva, salida de la geovalla, o superar el techo | La vigilancia no es solo previa: se comprueba **en cada latido** del bucle de control |
| `enlace_perdido` | Sin telemetría durante 10 s. El dron sale de la flota operativa, se liberan su capa y su plaza de HUB, y **el pedido vuelve a la cola** | Que no se dé por entregado lo que no lo está. Deliberadamente **no** se manda RTL: no hay a quién mandárselo, y el autopiloto tiene su propio failsafe |

**Cómo enseñarlo en vivo.** Tras una oleada, abre el desplegable y recorre la
lista de abajo arriba: se lee la historia completa del reparto —quién esperó,
quién cedió, quién volvió y por qué—.

**Las dos frases:**

- «Cada regla de seguridad deja rastro. No hay que creerse que funciona.»
- «Los eventos que más me interesan no son los errores, son los `espera` y los
  `espera_pad`: significan que dos drones iban a estorbarse y el sistema lo
  resolvió antes de que pasara.»

> **Por qué `proximidad` no frena.** Es una pregunta que va a salir, y la
> respuesta es un fallo encontrado volando. Al principio el dron sí mantenía
> posición al acercarse a otro en planta. El resultado era un interbloqueo:
> uno saliendo del parking y otro volviendo a él se estorban mutuamente, y el
> conflicto **no se resuelve solo**: ninguno de los dos puede alejarse sin
> avanzar. El que esperaba agotaba el tiempo del tramo y perdía la entrega.
>
> Como la separación la garantizan las capas —cada vuelo tiene su nivel, y el
> regreso va en un bloque por encima—, dos drones cercanos en planta están
> separados en vertical. Frenar además por distancia horizontal no añadía
> seguridad y sí quitaba entregas. Se dejó el aviso y se quitó la frenada.

> Si en tu demo salen **pocos** eventos de coordinación, es buena señal de
> tráfico fluido pero mala señal para enseñar. Para forzarlos: baja el aforo
> del HUB a 1, y en el ParkingTool aprieta el parking (menos espaciado, más
> separación exigida); verás `espera` y `espera_pad` inmediatamente.

### 3.8 El vertipuerto y el ParkingTool (8 min)

Esta es la parte nueva, y la que más se defiende sola porque se **ve**.
Enséñala en `http://127.0.0.1:8090` **antes** de volar.

#### El problema que resuelve

Despegue y aterrizaje son los dos únicos momentos en los que **la separación
por capas no protege**. Un dron que sube de 0 a su nivel de crucero atraviesa
todos los niveles inferiores; el que baja hace lo mismo al revés. Pedir que «no
coincidan en altura» ahí es imposible: van a coincidir con todas.

Lo que sí se puede exigir es que no coincidan en el **volumen**.

#### Las tres versiones, y por qué cada una

Cuéntalo como una progresión — es una historia de diseño, no una lista de
características:

1. **Sin nada.** Los drones despegaban y aterrizaban cuando les tocaba. Con
   cuatro drones sobre pads a 8 m, dos podían cruzarse en la vertical del
   parking sin que nada lo impidiera.

2. **Cerrojo único.** Un solo dron maniobrando en todo el parking. Correcto,
   pero **serializa la flota entera**: seis drones despegan y aterrizan de uno
   en uno aunque sus plazas estén a 40 m. Y deja el escalonado sin efecto,
   porque al agotar su retardo el dron se encuentra la vertical ocupada
   igualmente. Es el estado del que partía esta sesión.

3. **Vertipuerto con varias plataformas** (lo actual). Cada dron ocupa **la
   vertical de su plaza**, no la del parking. Dos drones maniobran a la vez si
   sus plazas distan al menos `pad_separation_m`.

**La frase:** «un vertipuerto real no tiene una plataforma, tiene varias, y
opera en paralelo las que están suficientemente separadas. Eso es lo que
modela ahora».

> **Compatibilidad hacia atrás, y por qué importa.** Con
> `pad_separation_m = 0` el comportamiento vuelve a ser el cerrojo único. No es
> pereza: es que todo lo verificado en `B2-VERIFICACION.md` se hizo con esa
> regla, y quería poder volver a ella sin tocar código para comparar.

#### Qué enseñar en la herramienta

Mueve los controles delante de él. La lectura es inmediata:

| Elemento | Qué es |
| --- | --- |
| Cuadro numerado | La plaza. El número es el dron; el color, su turno de despegue |
| Círculo | La **burbuja de maniobra**: radio = la mitad de la separación exigida |
| Línea roja | Une el par que se estorba |

**El detalle que hace que se entienda de golpe:** el radio es la *mitad* de la
separación a propósito. Así «dos burbujas que se tocan» equivale exactamente a
«dos plazas más cerca que la separación exigida», que es la condición que
aplica el gestor de espacio aéreo. El solape **es** la restricción dibujada.

Y arriba, en palabras: *«3 a la vez · 2 turnos para sacar los 6»*. Los turnos
salen de un coloreado del grafo de conflictos, resuelto exacto por
backtracking — con diez plazas como máximo es instantáneo y no hay que
justificar ninguna heurística.

**Compara tres formaciones en vivo** (esto es el momento fuerte):

| Formación | Con 6 drones a 8,5 m y 13 m exigidos |
| --- | --- |
| Rejilla 3×2 | 2 a la vez, 4 turnos. La plaza del centro se estorba con las cinco restantes: siempre sale sola y la última |
| Fila | 3 a la vez, 2 turnos |
| Círculo (30 m) | Los 6 a la vez, 1 turno |

**La frase:** «la formación del parking no es estética: decide cuántos drones
puede sacar el sistema a la vez. Y se puede ver antes de volar».

#### Por qué esto no es solo del simulador

Es la pregunta que va a hacer, así que adelántate. La frontera está trazada a
propósito:

- **La geometría del parking vive en el portal**, en `OperationalScenario`,
  porque es configuración **operativa**: un vertipuerto real también tiene sus
  plazas y sus distancias mínimas. Con drones de verdad esto vale igual.
- **El ParkingTool solo la edita con un dibujo**, y añade lo que sí es
  exclusivo de simulación: lanzar y matar procesos `ArduCopter.exe`, elegir el
  factor de aceleración, vaciar tablas, sembrar pedidos de prueba.

Meter los botones de SITL en el portal habría obligado a esconderlos luego
detrás de un modo. Separarlos deja el portal limpio para volar de verdad.

#### El escalonado, después de todo esto

Merece explicarse porque **cambió de trabajo** y porque tiene una anécdota
buena:

- El **cerrojo de la plaza** protege el volumen: se retiene desde antes de
  armar hasta que el dron alcanza su capa de crucero.
- El **escalonado** protege el tiempo: la estela de un multirrotor no
  desaparece en el instante en que despeja la vertical.

Los despegues se organizan en **tandas**: cada tanda agrupa plazas compatibles
entre sí, y lo que se separa por `takeoff_gap_s` son las tandas, **no los
drones**.

> **La anécdota, si hay confianza.** Antes el escalonado ponía a cada dron
> detrás del último, y encadenaba: en una rejilla de tres columnas, la plaza 3
> es compatible con la 1 pero no con la 2, así que la 2 se iba a t=10 y la 3 a
> t=20 — cuando podía haber salido con la 1 en t=0. El escalonado anulaba justo
> la concurrencia que el vertipuerto acababa de conceder.
>
> Y al arreglarlo apareció un segundo fallo más fino todavía: los ejecutores no
> arrancan en el mismo instante, entre uno y otro pasa una décima. Un dron
> compatible con los que ya salían pedía turno 0,2 s tarde, se encontraba con
> 9,8 s hasta la siguiente tanda en vez de 10, y **por dos décimas se iba una
> tanda entera más tarde**. Por eso las tandas siguen abiertas 3 s.
>
> Los dos fallos tienen su test de regresión. Ninguno de los dos se veía en los
> tests: se vieron mirando el registro de eventos de un vuelo.

---

## 4. El reparto en vivo (8 min)

**Iniciar repartos** y narrar sobre el mapa:

1. **Despegues por tandas.** Los que la herramienta pintó del mismo color salen
   juntos; entre tandas pasan los 10 s del escalonado. **Vuelve al ParkingTool
   y compáralo**: es la comprobación de que la herramienta no dibuja un
   folleto, describe lo que va a pasar.
2. **Los que no caben en la tanda esperan** → eventos `espera_pad`, con
   «espera para despegar» o «espera para aterrizar».
3. **Cada dron sube a su capa**: con 6 drones, 25/30/35/40/45/50 m. Nunca dos
   en la misma.
4. **Paso por el HUB**, con esperas si está lleno → eventos `espera`.
5. **Entrega**: aterriza en el cliente, pausa, despega.
6. **Regreso por la ruta de ida**, no en línea recta, y en el bloque superior:
   55-80 m. Ida y vuelta nunca comparten nivel, como en aviación.
7. **La cola se vacía sola.**

> **Sobre el orden de despegue**, que despista y conviene tener preparado. Son
> dos capas independientes:
>
> - **El asignador decide qué dron coge qué pedido**, y con ello quién pide
>   turno antes. Si los `pesado` salen primero es porque `oleada` trae paquetes
>   de 3,5 kg que **solo ellos pueden llevar**.
> - **El vertipuerto decide cuándo puede maniobrar cada uno.** No reordena
>   nada: reparte en tandas a los que ya han pedido.
>
> Que se separen así es una decisión de diseño, no una casualidad: la
> asignación es un problema de optimización y el espacio aéreo es un problema
> de seguridad. Mezclarlos haría que un cambio de algoritmo alterase las
> separaciones, y entonces no se podrían comparar dos algoritmos.

Si algo se atasca, el detalle del dron dice en qué fase está. Esa palabra es lo
que distingue una hipótesis de otra.

---

## 5. Simulaciones: los resultados (10 min)

El material está en `docs/swarm/SIMULACIONES.md` y en el capítulo 10 de la
memoria: jornadas completas de reparto con llegadas de pedidos, recarga en la
base y cinco políticas (voraz FIFO, JV, JV con antigüedad y dos planes MILP),
40 jornadas por nivel de demanda y comparación pareada con Wilcoxon y Holm.

## 6. Cierre (3 min)

**Lo que está hecho:** el algoritmo validado experimentalmente es literalmente
el mismo que despacha los drones (`core/greedy.py`); el enjambre vuela contra
cuatro SITL con deconflicción real; y hay dos mediciones independientes —la
sintética y la de vuelo— que apuntan en la misma dirección.

**Lo que falta:**

1. **Llevar el planificador MILP al enjambre** como tercer asignador, que es la
   política que mejor sale en simulación.
2. **Conexión MQTT con las Raspi** siguiendo el patrón del DEE de la EETAC. El
   diseño está en `docs/swarm/MQTT.md`. Lo importante: **encaja sin reescribir
   el enjambre**, porque el ejecutor no habla MAVLink sino con una abstracción
   `DroneLink` que ya tiene dos implementaciones. Falta `goto(lat,lon,alt)` en
   el servicio del DEE, y hay que medir cómo afecta la latencia del broker al
   bucle de control.
3. **Despliegue**: Railway con PostgreSQL y el enjambre simulado (`DRONE_BACKEND=simulado`).

**Trabajo futuro para la memoria:** detect-and-avoid reactivo (hoy los
conflictos se resuelven esperando, no esquivando) y recarga de baterías entre
oleadas.

---

## Preguntas que probablemente hará

**«¿Por qué greedy si el global es mejor?»** Porque el global necesita conocer
todos los pedidos a la vez y es O(n³); el voraz decide al instante y sirve
cuando los pedidos llegan de uno en uno. El sistema permite ambos y **mide** la
diferencia.

**«¿Por qué el dron X despega antes que el Y?»** El asignador decide quién pide
turno; el vertipuerto, cuándo puede. Son dos capas separadas a propósito (§4).

**«¿De dónde sale el valor de la separación entre plazas?»** Es un parámetro,
no una constante, igual que el techo de 120 m. Lo honesto es decir que **no
está calibrado contra una norma**: la geometría de vertipuertos de EASA está
todavía en borrador y no hay un número cerrado para multirrotores pequeños. Lo
que aporta el trabajo es el **mecanismo** —la restricción, su efecto medible en
turnos de despegue, y la herramienta para explorarla— no el valor concreto.
Reconocerlo vale más que inventarse una cifra.

**«¿No es redundante el escalonado con el cerrojo de la plaza?»** Se solapan
bastante: subir a 25 m lleva del orden de 10 s, que es el intervalo. El cerrojo
cubre el volumen durante toda la subida; el escalonado añade separación
temporal por la estela, que persiste después. Se puede bajar a 5 s sin perder
la garantía geométrica, y ponerlo a 0 para medir el efecto del vertipuerto
aislado.

**«¿Y si un dron se queda a medio despegar?»** Pasó, y era un bloqueo real:
`dronLink._takeOff()` espera la altitud con `wait_for_message(timeout=None)` y
no vuelve nunca si el autopiloto se para a media subida. El dron aparecía
«despegando» a 8 m, parado y sin error. Ahora el enlace manda
`MAV_CMD_NAV_TAKEOFF` y vigila la subida él, con límite de tiempo, y reporta el
`STATUSTEXT` del autopiloto: *«no alcanzó la altitud de 50 m (se quedó en
8,0 m) — EKF3 IMU0 stopped aiding»*. Mismo criterio que ya se aplicaba a
`motors_armed_wait()`.

**«¿Esto vale para drones reales?»** La lógica es la misma; lo que cambia es el
enlace. Está diseñado en `docs/swarm/MQTT.md` y es aditivo.

**«¿Y si se pierde la conexión?»** Sin telemetría durante 10 s se da el enlace
por perdido: el dron sale de la flota operativa y **su pedido vuelve a la
cola**. No se da por entregado lo que no lo está.

**«¿Cuántos drones aguanta?»** El límite práctico son las capas de altitud:
techo 120 m con saltos de 5 m, y el bloque de retorno duplica el consumo de
capas. Con la geometría actual, unos 12 drones simultáneos.

**«¿Está probado?»** Suite de tests con `FakeDroneLink` que cubre la secuencia
completa sin SITL, más un acta de verificación contra SITL real
(`B2-VERIFICACION.md`) con cinco fallos encontrados volando que los tests no
veían — cada uno con su test de regresión.
