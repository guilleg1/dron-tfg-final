# 01 · Estado actual del proyecto

> Snapshot real del repositorio `ProyectoDrones_LOCAL` antes de la entrega
> «Swarm Manager». Objetivo: dejar por escrito **qué hay, qué falta y qué hay
> que tocar** para construir el enjambre encima sin romper lo existente.

---

## 1. Mapa de carpetas

```
ProyectoDrones_LOCAL/
├── main.py                       # Punto de entrada PySide6
├── DesktopLAN.py                 # Versión LAN antigua (no se toca)
├── RaspiAutopilotLANService.py   # Servicio en Raspi que reenvía MAVLink
├── business_manager.py           # GUI Tkinter legacy (clientes/pedidos)
├── route_profiles.json           # Perfiles → parking, hub, destinos, rutas
├── operations.db                 # SQLite con clients + orders
├── requirements.txt              # SOLO PySide6>=6.5.0
│
├── cliente/                      # Capa GUI PySide6
│   ├── main_window.py            # Ventana principal con toolbar + splitter
│   ├── theme.py                  # Dark theme
│   ├── base_widgets.py           # DarkButton, StatusIndicator
│   ├── business_dialog.py        # Diálogo CRUD clientes/pedidos
│   ├── route_planner_dialog.py   # Diálogo edición de rutas
│   └── manual_controls_dialog.py # Diálogo control manual del dron
│
├── widgets/                      # Componentes UI reutilizables
│   ├── map_widget.py             # Leaflet embebido vía QWebEngineView
│   ├── fleet_panel.py            # Panel lateral con DroneCards y pendientes
│   ├── drone_card.py             # Tarjeta por dron (idle/connected/flying…)
│   ├── emergency_panel.py        # Botones RTL / LAND / HOVER
│   ├── status_bar.py             # Barra de estado
│   ├── control_pad.py            # Joystick virtual
│   └── compact_slider.py
│
├── servicios/                    # Capa de servicios (no GUI)
│   ├── drone_service.py          # Wrapper de dronLink.Dron con señales Qt
│   ├── telemetry_service.py      # Tick de telemetría a 1Hz
│   └── route_service.py          # Carga / construye misiones de route_profiles
│
├── negocio/                      # Capa de datos
│   ├── db_manager.py             # DeliveryDataStore (clients, orders)
│   ├── geocoder.py               # Nominatim
│   └── file_manager.py
│
├── modelos/                      # DTOs
│   └── waypoint.py               # Waypoint, Mission
│
├── servidor/                     # API server HTTP del portal cliente
│   └── api_server.py             # /api/clients/login, /api/orders, telemetría
│
├── portal_cliente/               # Frontend estático del cliente
│   ├── index.html
│   ├── app.js
│   └── style.css
│
└── utils/
    ├── constants.py              # Conexión SITL, alts, colores
    └── geo_utils.py              # haversine, offset, color por velocidad
```

---

## 2. Modelo de datos actual

### `operations.db`

```sql
clients(id, name, address, latitude, longitude, created_at, updated_at)

orders(
  id, client_id, weight_kg, status,
  assigned_profile_name, assigned_route_name,
  assigned_destination_name, assigned_destination_lat, assigned_destination_lon,
  assigned_distance_km, operational_state,
  created_at, updated_at
)
```

Estados válidos de `orders.status`:
`pendiente`, `planificado`, `en_reparto`, `entregado`, `cancelado`.

`operational_state` es texto libre tipo `"yendo a cliente"`, usado para
visualización en la `DroneCard`.

**No existe ninguna tabla `drones`.** Toda la lógica asume un único dron
identificado por la constante `DRONE_ID = "Dron-1"` (ver `cliente/main_window.py:24`).

### `route_profiles.json`

Estructura jerárquica:

```jsonc
{
  "profiles": [
    {
      "name": "Ruta1-Castelldefels",
      "takeOffAlt": 8.0,
      "speed": 7.0,
      "hub": { "lat": ..., "lon": ..., "alt": 20.0 },
      "parkings": [{ "name": "Central", "lat": ..., "lon": ..., "alt": 0.0 }],
      "destinations": [
        { "name": "Castillo", "lat": ..., "lon": ..., "alt": 15.0 },
        { "name": "UPC",      "lat": ..., "lon": ..., "alt": 15.0 }
      ],
      "routes": [
        { "name": "Ruta-Castillo", "parking": "Central",
          "destination": "Castillo", "intermediates": [...] }
      ]
    },
    ...
  ]
}
```

Conceptos clave que aparecen:

- **Parking**: punto físico donde despegan/aterrizan los drones (alt = 0).
- **Hub**: punto en altura cerca del parking donde convergen rutas (alt > 0).
- **Destinos**: puntos de "drop" cercanos a clientes.
- **Ruta**: secuencia `parking → hub → intermedios → destino`. Cliente final
  añade un último tramo `destino → cliente`.

> **Observación clave**: las rutas ya son corredores aéreos válidos. Esto
> simplifica enormemente la deconflicción: el espacio aéreo está
> pre-aprobado, solo hay que ordenar quién entra y a qué altitud.

---

## 3. Flujo de un pedido hoy (mono-dron)

1. **Cliente** entra en el portal web (`portal_cliente/index.html` servido por
   `servidor/api_server.py` en `:8080`), introduce nombre + dirección, crea
   pedido con peso.
2. **`POST /api/orders`** → `DeliveryDataStore.create_order()` →
   `_find_best_route()` busca el **destino más cercano por Haversine** entre
   *todos* los perfiles y lo asigna al pedido.
3. **`MainWindow._poll_active_order()`** sondea la BD cada 2 s y refresca el
   panel lateral con pedidos `pendiente`.
4. **Operador humano** pulsa "Aceptar" en `FleetPanel` →
   `MainWindow._on_accept_order()` cambia estado a `en_reparto` y llama
   `drone_svc.start_order_delivery()`.
5. **`DroneService.start_order_delivery()`** (en `servicios/drone_service.py:298`)
   ejecuta un workflow secuencial **bloqueante** dentro de un thread:
   - takeoff a 25 m
   - `goto` parking → hub (`waypoints[0]`)
   - `goto` por cada intermedio
   - `goto` destino
   - `goto` cliente
   - `Land`, esperar 10 s
   - re-arm, takeoff retorno, `goto` central, `Land`
6. Por el camino va actualizando `orders.operational_state` y emitiendo
   señales Qt que la UI escucha.

### Limitaciones actuales del flujo

| Problema                                                  | Consecuencia para enjambre                                   |
| --------------------------------------------------------- | ------------------------------------------------------------ |
| `DRONE_ID` hard-coded en `main_window.py:24`              | Toda la UI asume un dron. Hay que parametrizar.              |
| `DroneService` mantiene **un solo `Dron()`**              | No se puede orquestar más de un autopiloto.                  |
| Mission Planner está en `127.0.0.1:5763` único            | Multi-SITL requiere un puerto por dron.                      |
| `start_order_delivery()` es **bloqueante por dron**       | OK por hilo, pero no decide quién la coge.                   |
| El "matching" pedido→ruta usa **solo distancia**          | No considera peso, batería, ni dron concreto.                |
| No hay tabla `drones`, ni capacidad ni batería persistida | Hay que crear todo el modelo de flota.                       |
| No hay concepto de "cola de pedidos"                      | Aceptar un pedido es manual; el swarm debe ser autónomo.     |
| No hay deconflicción entre rutas                          | Si dos drones cogen rutas que comparten hub → conflicto.     |

---

## 4. Puntos de extensión naturales

El código **ya está bastante limpio** y separado en capas. Los enganches para
el enjambre son evidentes:

- **`servicios/`** es el lugar natural para `swarm_service.py` (orquestador) y
  `planner_service.py` (motor VRP).
- **`negocio/db_manager.py`** absorbe las nuevas tablas (`drones`,
  `assignments`).
- **`modelos/`** se amplía con `drone.py` (DTO), `assignment.py`,
  `flight_plan.py`.
- **`widgets/fleet_panel.py`** ya soporta `add_drone(drone_id)` para N
  tarjetas; basta con dejar de cablear `"Dron-1"`.
- **`cliente/main_window.py`** mantiene la idea de un `DroneService`; se
  generaliza a `dict[str, DroneService]`.
- **`servidor/api_server.py`** seguirá recibiendo pedidos por
  `POST /api/orders` — solo cambia que se encolen en lugar de asignarse
  estáticamente a una ruta.

---

## 5. Dependencias actuales y nuevas

`requirements.txt` actual:

```
PySide6>=6.5.0
```

Implícitas (no listadas): `dronLink` (sibling project `../ProyectoDeDrones`),
`pymavlink` (vía dronLink), `sqlite3` (stdlib).

**Nuevas dependencias necesarias** (a añadir en `requirements.txt`):

```
PySide6>=6.5.0
ortools>=9.10           # Solver CVRP / asignación
numpy>=1.26             # Cálculo vectorial (distancias, energías)
pyyaml>=6.0             # (opcional) configuración flota legible
pytest>=8.0             # Tests unitarios del planner
```

> `ortools` es el cuello del despliegue: instala bien en Windows con
> `pip install ortools`, sin compilación nativa. Probarlo en pre-fase.

---

## 6. Riesgos heredados que afectan al enjambre

1. **`DroneService` usa `_run_in_thread` con daemon threads**: la coordinación
   entre múltiples drones (esperar despegues, sincronizar) tendrá que vivir
   por encima, en el `SwarmService`, no dentro de cada `DroneService`.
2. **`route_status` es una señal de string libre**: para enjambre conviene
   emitirla siempre con `drone_id` incluido (`route_status(drone_id, text,
   color)`), si no la `MainWindow` no puede distinguir quién es.
3. **`_publish_event` no distingue dron**: misma observación.
4. **El portal cliente envía pedidos sin priorización ni SLA**: para el TFG
   basta FIFO, pero conviene dejar un campo `priority` desde ya.
5. **No hay tests**: cualquier refactor agresivo va a doler. Antes de cambiar
   `business_manager.py` o `db_manager.py` conviene capturar el comportamiento
   con tests sencillos.

---

## 7. Inventario rápido — referencias de fichero / línea

| Tema                                | Fichero : línea                                    |
| ----------------------------------- | -------------------------------------------------- |
| Constante `DRONE_ID = "Dron-1"`     | `cliente/main_window.py:24`                        |
| Conexión TCP SITL única             | `utils/constants.py:14-17`                         |
| Workflow de entrega bloqueante      | `servicios/drone_service.py:298-463`               |
| Matching pedido→ruta (Haversine)    | `negocio/db_manager.py:111-141`                    |
| Schema de `orders`                  | `negocio/db_manager.py:26-43`                      |
| Polling de pedidos en la UI         | `cliente/main_window.py:263-296`                   |
| Aceptar pedido (mono-dron)          | `cliente/main_window.py:325-365`                   |
| API HTTP de creación de pedidos     | `servidor/api_server.py:140-153`                   |
| Construcción de la `Mission`        | `servicios/route_service.py:63-94`                 |
| Add drone a la UI                   | `widgets/fleet_panel.py:150-161`                   |

Con este mapa cualquier cambio futuro puede saltar directo al sitio correcto.
