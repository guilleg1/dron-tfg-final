# Archivo histórico

Primeras implementaciones del TFG, conservadas como evidencia de la evolución
del trabajo. **Código congelado:** no se mantiene, no se instala, no se ejecuta
y no se testea. No es un paquete Python y no está declarado en
`pyproject.toml`.

Sus imports internos (`cliente.`, `widgets.`, `servicios.`, `utils.`...) se
dejaron tal cual estaban. Reescribirlos habría sido mantener código muerto. Por
eso cada carpeta conserva su estructura relativa original y hay copias de los
ficheros que en su día compartía con el resto del proyecto: así el archivo es
autocontenido y se entiende sin salir de él.

## `desktop/`

Aplicación de escritorio **Desktop Drone Control v2.0** (PySide6). Controlaba
un único dron contra Mission Planner por dronLink, con mapa Leaflet, panel de
flota y panel de emergencia. Punto de entrada: `desktop/main.py`.

Incluye `servidor/api_server.py`, una API HTTP mínima que exponía el estado del
dron en la red local.

## `lan/`

Iteración anterior a la aplicación de escritorio.

- `DesktopLAN.py` — versión monolítica, en un solo fichero, del control de dron.
- `business_manager.py` — gestor de pedidos y clientes de aquella versión.
- `RaspiAutopilotLANService.py` — servicio que corría en la Raspberry Pi a bordo
  y hacía de puente entre la red local y el autopiloto.

## Qué lo sustituyó

La webapp (`airdrop/`). El portal cubre alta de clientes, pedidos, gestión de
rutas y despacho de drones desde el navegador, y es lo que se despliega. El
enlace con Mission Planner vive ahora en `airdrop/drone/backend.py`.
