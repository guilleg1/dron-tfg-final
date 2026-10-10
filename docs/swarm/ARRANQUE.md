# Arranque limpio

Secuencia para dejar el sistema en un estado conocido y enseñar la webapp. El
orden importa: cada paso deja algo que el siguiente da por hecho.

## 1. Tierra quemada

Instancias SITL de un lanzamiento anterior, o una simulación abierta dentro de
Mission Planner, se quedan con los puertos y el arranque falla con
`Address already in use`. Es el fallo más frecuente y el más tonto.

```powershell
cd C:\Users\test\Desktop\TFG_FINAL\tfg-drones

./run_swarm.ps1 stop
Get-Process ArduCopter -ErrorAction SilentlyContinue | Stop-Process -Force
netstat -ano | Select-String ":5760 |:5770 |:5780 |:5790 "
```

El `netstat` no debe devolver nada. Si devuelve algo, cierra ese PID y la
simulación de Mission Planner si la tienes abierta.

## 2. Enjambre

```powershell
./run_swarm.ps1 launch
./run_swarm.ps1 status
```

Los cuatro en `OK`. Si no:

| Estado | Qué significa |
| --- | --- |
| `PUERTO OCUPADO` | Vuelve al paso 1 |
| `ARGUMENTO NO SOPORTADO` | El binario cambió de opciones; ver `SITL.md` |
| `PANIC` | Ruta de `--defaults` mal entrecomillada; ver `SITL.md` |
| `PROCESO MUERTO` | Mirar `sitl_run/Dron-1/stdout.log` |

## 3. Datos limpios

```powershell
python -m airdrop.demo clear
```

Borra clientes simulados y sus pedidos, y respeta las cuentas reales. Los
pedidos que quedaran en vuelo de una sesión anterior vuelven solos a la cola al
arrancar el portal.

## 4. Portal

En **otra** terminal, y se queda ahí:

```powershell
cd C:\Users\test\Desktop\TFG_FINAL\tfg-drones
./run_local.ps1
```

> Si has tocado código, **reinicia el portal y haz Ctrl+F5** en el navegador.
> El código nuevo no llega a un proceso ya arrancado, ni el JS nuevo a una
> pestaña con el viejo en caché. Es el error que más tiempo cuesta.

## 5. Comprobación previa

En `http://localhost:8080/admin.html` → **Enjambre**:

1. «Probar conexión» → los cuatro en verde con su SYSID.
2. Flota entera en `idle`.
3. Escenario **Castelldefels** activo.
4. `hub_capacity` a **2** y guardar.

## 6. Pedidos

```powershell
python -m airdrop.demo seed oleada --seed 42
```

Ocho pedidos junto a los destinos reales del perfil, con la semilla fija para
que la demo sea la misma que ensayaste.

---

## Recorrido de la webapp

Orden sugerido para enseñarla, de lo visible a lo argumentable.

### Portal de cliente (`http://localhost:8080/`)

Entrar con un cliente y enseñar: pedido con su peso, **tiempo estimado de
entrega**, el dron asignado con su altura y su fase, y el mapa con la ruta
—corredor en cian, último tramo al cliente discontinuo—. Clicar un pedido en
curso sigue a su dron.

**Qué demuestra:** el cliente ve el estado real del vuelo, no un «en camino»
genérico.

### Panel · Rutas

Perfil, parkings, destinos, HUB y rutas con sus intermedios, sobre el mapa.
Crear y eliminar perfiles desde el propio panel.

**Qué demuestra:** los corredores no están cableados en el código; se dibujan.

### Panel · Pedidos / Flota

Clicar un pedido enfoca su ruta; clicar fuera o cambiar de apartado vuelve a la
vista general.

### Panel · Enjambre

El apartado central:

- **Flota**: cada dron con su pedido y la fase concreta que ejecuta.
- **Asignación**: voraz u óptima global, conmutable en vivo.
- **Escenario operacional**: capas, separación, escalonado, geovalla, aforo del
  HUB, reserva de batería. Editable en caliente.
- **Métricas por algoritmo**: la comparativa, exportable a CSV.
- **Eventos de seguridad**: la bitácora que prueba que la coordinación actúa.

Las secciones vienen plegadas salvo las que se miran durante un reparto.

**Qué demuestra:** ningún parámetro de seguridad es una constante escondida.
Todos salen del escenario, y por eso el mismo enjambre vuela a 40 m sobre
Castelldefels y a 4 m dentro del DroneLab.

### El reparto

«Iniciar repartos» y narrar sobre el mapa: despegues escalonados, cada dron en
su capa, esperas por HUB, regreso por la ruta de ida a un bloque de altitud
superior, y la cola vaciándose sola.

Los drones se ven en el mapa desde **cualquier** pestaña.

## Cierre

```powershell
python -m airdrop.demo clear
./run_swarm.ps1 stop
```
