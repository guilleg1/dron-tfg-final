# SITL multi-instancia en Windows

Cómo levantar varias instancias de ArduCopter SITL en la misma máquina para
probar el enjambre. Verificado el 2026-07-27 con el binario que trae Mission
Planner.

## Binario

No hace falta ni WSL ni Docker ni compilar ArduPilot. Mission Planner instala
un SITL nativo de Windows (Cygwin):

```
C:\Users\test\Documents\Mission Planner\sitl\ArduCopter.exe
C:\Users\test\Documents\Mission Planner\sitl\default_params\copter.parm
```

La variable de entorno `SITL_BINARY` permite apuntar a otro.

## Invocación

```
ArduCopter.exe -I <instancia> --model + --speedup 1
               --defaults "<ruta a copter.parm>"
               --home <lat>,<lon>,<alt>,<heading>
               --serial0 tcp:0
               --sysid <n>
```

Cada instancia corre en **su propio directorio de trabajo**, porque ArduPilot
escribe ahí su `eeprom.bin` y sus logs; dos instancias en el mismo directorio
se corrompen entre sí.

## Tres trampas que cuestan una tarde

### 1. `-I` tiene que ir el primero de todos los argumentos

La ayuda del binario dice que `--instance|-I N` *«adds 10*instance to all port
numbers»*, y es verdad, pero **solo si aparece antes que las opciones que
consumen puertos**. Puesto después de `--model` o `--defaults` se ignora en
silencio para SERIAL0 y todas las instancias intentan enlazar 5760:

```
bind port 5760 for SERIAL0
bind failed on port 5760 - Address already in use
```

Colocado el primero, la instancia 1 enlaza 5770 y desplaza también el resto de
puertos (Irlock pasa de 9005 a 9015).

Puertos resultantes de SERIAL0: **5760 + 10 × instancia** → 5760, 5770, 5780,
5790.

### 2. La ruta de `--defaults` lleva un espacio

`Mission Planner` tiene un espacio en el nombre. Si el argumento no va
entrecomillado, el binario recibe la ruta partida y arranca hasta el final para
después morir con:

```
PANIC: Failed to load defaults from @ROMFS/default_params/copter.parm,C:\Users\test\Documents\Mission
```

Lo engañoso es que el proceso llega a aceptar la conexión TCP antes de caer, de
modo que el cliente MAVLink se conecta y acto seguido recibe un
`WinError 10054 / connection reset`, que parece un fallo del cliente y no lo es.

Desde Python con `subprocess` y lista de argumentos esto no pasa:
`list2cmdline` entrecomilla solo. Desde PowerShell con
`Start-Process -ArgumentList` hay que entrecomillar a mano.

### 3. `-M+` no llega entero

La forma corta pegada al valor (`-M+`, `-s1`) que usa el `sitl.bat` de Mission
Planner no sobrevive al paso por `Start-Process`. El binario responde con
*«You must specify a vehicle model»*. Usa las opciones largas separadas:
`--model +` y `--speedup 1`.

### 3-bis. El binario cambia de opciones entre versiones, y `-P` desapareció

Verificado el 2026-08-06. Tras redescargar el SITL —basta con borrar la carpeta
`sitl` y dejar que Mission Planner la reponga, o pasar a un build BETA— las
cuatro instancias empezaron a morir en el arranque con `PROCESO MUERTO`, sin
`PANIC` y con `stderr.log` vacío.

La causa estaba en `stdout.log`: **el volcado íntegro de la ayuda del binario**.
Ante una opción que no reconoce, ArduCopter no da error ni menciona cuál es;
imprime `--help` y sale. Desde fuera es indistinguible de un fallo de arranque,
y manda a buscar el problema a puertos, permisos o antivirus.

La opción rechazada era `-P SERIAL1_PROTOCOL=2`. `ArduCopter.exe --help` ya no
lista `-P` ni `--param`, aunque el `sitl_escenario.bat` generado el 2026-07-27
sí la usaba y funcionaba.

Resultó innecesaria: **2 (MAVLink2) ya es el valor por defecto de
`SERIAL1_PROTOCOL` en ArduCopter**, y la instancia abre SERIAL1 sola:

```
bind port 5762 for SERIAL1
SERIAL1 on TCP port 5762
```

Así que se eliminó de `build_command()`. Si en el futuro hiciera falta forzar
parámetros, la vía que sobrevive a los cambios de versión es un fichero
`.parm` propio añadido a `--defaults` separado por comas, no `-P`.

**Regla general:** ante cualquier fallo de arranque inexplicable, lo primero es
`ArduCopter.exe --help` y comparar con la línea de comandos que genera
`build_command()`. `status` ya distingue este caso y lo etiqueta
`ARGUMENTO NO SOPORTADO`.

## Diagnóstico

El arranque correcto deja en `stderr.log`:

```
bind port 5770 for SERIAL0
SERIAL0 on TCP port 5770
```

y en `stdout.log`:

```
Using Irlock at port : 9015
Connection on serial port 5770
```

Si aparece `PANIC` en `stdout.log`, mira el punto 2. Si aparece
`Address already in use`, mira el punto 1.

### 4. El proceso muere si se mata el árbol del shell que lo lanzó

`subprocess.Popen` no basta, ni siquiera con `DETACHED_PROCESS` y
`CREATE_BREAKAWAY_FROM_JOB`: si el shell agrupa sus procesos en un Job Object
que no permite breakaway, las instancias caen con él y dejan en `stdout.log`
un `Closed connection on SERIAL0` como última línea. Si los drones desaparecen
sin motivo aparente, es esto.

`Start-Process` de PowerShell sí crea procesos independientes. Es lo que usa
`airdrop/swarm/sitl.py`. Dos detalles al delegar en él desde Python:

- **El PID no puede capturarse por tubería.** Con `capture_output=True` el
  proceso nieto hereda los descriptores y PowerShell espera indefinidamente a
  que se cierren. Hay que escribirlo a un fichero.
- **Las comillas simples de PowerShell no protegen los espacios** al construir
  `-ArgumentList`: los valores con espacios necesitan comillas dobles
  *dentro* de las simples, o reaparece el PANIC del punto 2.

### 5. Sondear el puerto puede matar la instancia

SERIAL0 admite **un solo cliente**. Comprobar si el autopiloto está vivo
abriendo y cerrando un socket contra su puerto deja un
`Closed connection on SERIAL0` en el log y a veces tumba la instancia: la
comprobación que debía diagnosticar el problema lo causa.

Para saber si una instancia está sana, mira el proceso y su log:

```
proceso vivo  +  "SERIAL0 on TCP port N" en el log  +  sin "PANIC"
```

Es lo que hace `python -m airdrop.swarm.sitl status`.

Corolario operativo: si el portal se reinicia sin reiniciar las instancias, la
ranura de la conexión anterior puede seguir ocupada y ese dron responderá con
`WinError 10054` hasta que su instancia se reinicie. `./run_swarm.ps1 stop` y
volver a lanzar.

### 6. Mission Planner puede mirar por SERIAL2

Cada instancia expone además **SERIAL2** en el puerto base + 3: 5763, 5773,
5783 y 5793. Como SERIAL0 lo ocupa el portal, esa es la vía para conectar
Mission Planner y ver el vuelo durante una demostración.

## Resultado de la validación

Verificado el 2026-07-27 con dos instancias y dos objetos `dronLink.Dron` en
hilos separados:

| Comprobación | Resultado |
| ------------ | --------- |
| Instancias concurrentes en 5760 y 5770 | correcto |
| SYSID distintos vistos por el cliente | 1 y 2 |
| Telemetría aislada por dron | cada uno recibe la posición de su pad |
| Armado en paralelo | ambos a la primera |
| Despegue a 25 m | 24,45 m y 24,48 m |
| `goto` simultáneo | ambos +0,0009° de latitud, longitudes intactas |
| RTL | correcto |

Sin interferencia entre instancias en ningún punto.

### Armar con espera acotada

`vehicle.motors_armed_wait()` de pymavlink **no tiene timeout**: si el
autopiloto rechaza el armado, bloquea el hilo para siempre. Dentro de un bucle
de reintentos eso significa que el primer intento se cuelga y los reintentos no
llegan a ejecutarse nunca.

`LocalBackend._arm_and_takeoff` tiene ese defecto. El sustituto sondea:

```python
dron.vehicle.mav.command_long_send(
    dron.vehicle.target_system, dron.vehicle.target_component,
    400, 0, 1, 0, 0, 0, 0, 0, 0)
t0 = time.time()
while time.time() - t0 < 8:
    if dron.vehicle.motors_armed():
        armado = True
        break
    time.sleep(0.5)
```

## Home distinto por instancia

Todas las instancias arrancan donde diga `--home`. Si se les da el mismo punto
nacen una encima de otra. Cada dron despega de su **pad** de parking: posiciones
separadas `pad_spacing_m` (8 m por defecto) alrededor del centro del parking,
calculadas con `core.geo.offset_position`.

## Uso en el proyecto

```powershell
./run_swarm.ps1          # lanza una instancia por dron habilitado
./run_local.ps1          # portal con DRONE_BACKEND=sitl
```

`run_swarm.ps1` es un envoltorio fino sobre `python -m airdrop.swarm.sitl`, que
lee la flota de la base de datos. La configuración la posee Python para que el
script y el portal no puedan divergir.

Subcomandos: `launch`, `status`, `stop`.
