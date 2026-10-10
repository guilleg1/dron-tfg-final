# Conexión con drones reales por MQTT

Diseño para que el enjambre vuele contra Raspberry Pi reales a través de un
broker MQTT, siguiendo el patrón del
[Drone Engineering Ecosystem](https://github.com/dronsEETAC/DroneEngineeringEcosystemDEE)
de la EETAC.

**Estado: diseñado, no implementado.** Este documento es el plan.

---

## Por qué encaja sin reescribir el enjambre

El ejecutor no sabe de MAVLink: habla con un `DroneLink`. Esa abstracción ya
existe y ya tiene dos implementaciones —`MavlinkDroneLink` contra SITL y
`FakeDroneLink` para los tests—. Añadir una tercera que hable MQTT deja
intactos el planificador, el gestor de espacio aéreo, la política de seguridad
y el portal.

```
DeliveryExecutor ─┬─ FakeDroneLink      (tests, sin nada)
                  ├─ MavlinkDroneLink   (SITL / MAVLink directo)
                  └─ MqttDroneLink      (Raspi por broker)   ← nuevo
```

Que este cambio sea aditivo y no invasivo es, de hecho, el argumento de que la
arquitectura estaba bien planteada. Merece decirse en la defensa.

## El patrón del DEE

De `RaspiAutopilotService.py` (carpeta `TFG/ProyectoDeDrones`):

- Broker por defecto `broker.hivemq.com`, puerto **8000**, transporte
  **websockets**.
- El servicio se suscribe a `+/raspiAutopilotService/#`.
- Comando: `<origen>/raspiAutopilotService/<comando>`, carga útil en el body.
- Respuesta: `raspiAutopilotService/<origen>/<evento>`, y la telemetría en
  `raspiAutopilotService/<origen>/telemetryInfo` como JSON.

Comandos existentes: `connect`, `arm_takeOff`, `go`, `Land`, `RTL`,
`startTelemetry`, `stopTelemetry`, `changeHeading`, `changeNavSpeed`.

## El hueco: no hay `goto(lat, lon, alt)`

`go(direccion)` mueve el dron en una dirección relativa. El enjambre necesita
navegar a coordenadas: sin eso no hay corredores, ni HUB, ni capas de altitud,
ni reparto autónomo.

La versión LAN de este mismo proyecto (`TFG/ProyectoDrones_LAN`) ya resolvió
algo equivalente añadiendo `uploadMission`, `executeMission` y `startMission`.
El camino es el mismo por MQTT.

### Extensión propuesta del servicio de la Raspi

Un dron con topic base `<drone_id>` en vez del `raspiAutopilotService` fijo,
para que varios convivan en el mismo broker:

| Comando | Carga útil | Qué hace |
| --- | --- | --- |
| `connect` | — | Conecta con el autopiloto |
| `goto` | `{"lat":…, "lon":…, "alt":…}` | Navega a un punto, **no bloqueante** |
| `arm_takeOff` | `{"alt":…}` | Arma y despega a esa altura |
| `land` | — | Aterriza |
| `rtl` | — | Vuelve a casa |
| `hold` | — | Mantiene posición (LOITER) |
| `resume` | — | Vuelve a GUIDED y reanuda |
| `startTelemetry` | `{"freq":…}` | Empieza a publicar telemetría |
| `capabilities` | — | Responde qué comandos soporta |

Que `goto` sea **no bloqueante** es un requisito, no un detalle: si el servicio
se queda dentro de la librería durante todo el tramo, no hay ningún instante en
el que comprobar separación, HUB ni batería, y la deconflicción táctica se
vuelve imposible. Es exactamente el problema que ya se resolvió en
`MavlinkDroneLink.goto`.

`capabilities` permite degradar con elegancia ante drones de otros equipos que
no tengan la extensión: se habilita lo que haya y se avisa de lo que falta.

### Telemetría

Mismo formato que ya consume el portal, para no tocar nada aguas arriba:

```json
{"lat": 41.2837, "lon": 1.9850, "alt": 25.4, "heading": 137,
 "groundSpeed": 6.2, "battery": 87, "flightMode": "GUIDED", "state": "flying"}
```

A **1-5 Hz**. Por debajo de 1 Hz, la vigilancia de telemetría congelada
—`TELEMETRY_TIMEOUT_S = 10 s`— empieza a dar falsos positivos de enlace
perdido.

## Lo que hay que construir

### 1. `airdrop/swarm/mqtt_link.py`

`MqttDroneLink` con la misma interfaz que `MavlinkDroneLink`: `connect`,
`is_connected`, `telemetry`, `telemetry_age_s`, `arm_and_takeoff`, `goto`,
`has_arrived`, `hold`, `resume`, `land`, `abort`, `close`, `on_progress`.

Dos puntos delicados:

- **`has_arrived` se calcula en el portal**, con la última telemetría, igual
  que ahora. No se delega en la Raspi: el enjambre necesita la misma noción de
  llegada para todos los drones.
- **La latencia del broker entra en el bucle de control.** Con
  `CONTROL_PERIOD_S = 0.5` y un broker público a 200 ms de ida y vuelta, las
  órdenes de `hold` por separación llegan tarde. Habrá que subir la separación
  mínima o bajar el periodo, y **medirlo**: es un resultado publicable del
  TFG, no un inconveniente.

### 2. Backend `mqtt`

`DRONE_BACKEND=mqtt` en `_build_swarm()`, junto a `stub`, `local` y `sitl`. El
resto del portal no se entera.

### 3. Conexión desde el panel

En **Enjambre**, una sección plegable *Broker MQTT*:

- Host y puerto (por defecto `broker.hivemq.com:8000`), editables para apuntar
  a un Mosquitto del DroneLab.
- Estado del broker: conectado / desconectado / reintentando.
- Por dron: su topic base, un semáforo de telemetría (edad del último paquete)
  y las capacidades que anunció.
- Botón **Descubrir drones**: se suscribe a `+/+/telemetryInfo` unos segundos y
  lista los que estén publicando. Es el equivalente al «Buscar autopilotos» que
  ya existe para SITL, y evita teclear topics a mano.

La conexión de cada dron pasa a ser `mqtt://<topic_base>`, reutilizando el
campo `connection` que ya existe en la flota.

### 4. Seguridad

El broker público es un canal abierto: cualquiera que conozca el topic puede
mandar `land`. Para el DroneLab es asumible; para volar de verdad, no. Las
mitigaciones —broker propio con TLS y credenciales, o firmar los comandos— se
documentan como trabajo futuro, pero **hay que decirlo en la memoria**. Un
tribunal lo va a preguntar.

## Plan de pruebas

Por orden, cada paso verificable sin el siguiente:

1. **Servicio simulado en el portátil.** Un script que se suscribe a los topics
   y responde con telemetría sintética. Valida `MqttDroneLink` sin hardware.
2. **Servicio contra SITL.** El `RaspiAutopilotService` extendido corriendo en
   el portátil, hablando con una instancia SITL local. Valida el protocolo
   completo con vuelo real simulado.
3. **Una Raspi, un dron, en el DroneLab.** Escenario DroneLab (4 m de techo,
   geovalla de 15 m), un solo pedido.
4. **Dos drones.** Es donde aparecen los conflictos de espacio aéreo, y donde
   la latencia del broker se nota.

Los pasos 1 y 2 se pueden hacer sin salir de casa, y cubren la mayor parte del
riesgo.

## Lo que no cambia

Ni el planificador, ni el gestor de espacio aéreo, ni la política de seguridad,
ni los tests, ni el portal de cliente. Toda la lógica que se validó contra SITL
sigue siendo la misma línea de código volando drones reales.

Ese es el resultado que hay que enseñar.
