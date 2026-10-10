# Vertipuerto: del cerrojo único a las plataformas en paralelo

Prototipo. Rama `prototipo/vertipuerto-y-consola-sim`.

## El problema

La primera versión protegía el despegue y el aterrizaje con un cerrojo único:
un solo dron maniobrando en todo el parking. El razonamiento era correcto —al
subir de 0 a la capa de crucero se atraviesan todas las capas inferiores, así
que ahí la separación vertical no protege— pero la solución era demasiado
gruesa:

- La flota entera despega y aterriza de uno en uno, sin importar cuánto disten
  los pads. Con cuatro drones, tres esperan siempre.
- El escalonado de despegues (`takeoff_gap_s`) quedaba inservible. Contaba
  contra **toda** la flota, así que encadenaba 10, 20 y 30 s; y al terminar la
  espera el dron se encontraba la vertical ocupada y volvía a esperar, ahora
  sin plazo. Se veía en el registro:

```
escalonado   Dron-1: despegue retrasado 20 s
escalonado   Dron-2: despegue retrasado 30 s
espera_pad   Dron-3: vertical del parking ocupada; espera para despegar
espera_pad   Dron-1: vertical del parking ocupada; espera para despegar
```

  El escalonado retrasaba, pero no separaba: quien separaba era el cerrojo.

## La solución

Un vertipuerto real no tiene una plataforma, tiene varias, y opera en paralelo
las que están suficientemente separadas. Eso es lo que se modela ahora.

**Cada dron ocupa la vertical de su pad, no la del parking entero.** Dos drones
pueden maniobrar a la vez si sus pads distan al menos `pad_separation_m`.

- `pad_separation_m = 0` reproduce exactamente el cerrojo único, así que lo
  verificado en B2 sigue valiendo sin tocar nada.
- `vertiport_capacity` pone un tope duro por encima de lo que permita la
  geometría, para acotar un experimento sin mover las distancias.

**El escalonado pasa a ser por vecindad.** Solo se cuenta contra despegues de
pads que no pueden operar a la vez que el tuyo. Los pads lejanos no se
estorban, así que tampoco se escalonan.

**Los aterrizajes tienen prioridad sobre los despegues.** El que vuelve lleva
la batería gastada y está en el aire: cada segundo de espera se le descuenta
del margen. El que despega está en tierra, donde esperar no cuesta energía.
La cola respeta además el orden de llegada dentro de cada clase, y un dron
lejano no se queda esperando detrás de una cola que no le afecta.

## La geometría del parking

La formación dejó de estar escrita en el repositorio de la flota (una fila
hacia el este) y es ahora parámetro del escenario:

| Parámetro | Qué hace |
|---|---|
| `pad_layout` | `fila`, `rejilla` o `circulo` |
| `pad_spacing_m` | distancia entre plazas contiguas |
| `pad_cols` | columnas de la rejilla |
| `pad_heading_deg` | rumbo del eje de la formación (90 = este) |
| `pad_separation_m` | distancia mínima para maniobrar a la vez |
| `vertiport_capacity` | tope duro de maniobras simultáneas |

La formación se **centra** en el parking: antes el pad 0 caía exactamente
sobre él y la fila crecía hacia un lado, así que ampliar la flota desplazaba
el conjunto y dejaba el marcador del mapa en un extremo.

La instancia SITL y la plaza son ya cosas distintas: `pad_index` en
`fleet.json` permite reordenar el parking sin renumerar puertos.

### El compromiso, con números

Seis drones, 25 m de separación exigida:

| Formación | Espaciado | Maniobras a la vez |
|---|---|---|
| Fila | 15 m | 3 de 6 |
| Rejilla 2 columnas | 15 m | 2 de 6 |
| Círculo | 30 m | 6 de 6 |

La rejilla ocupa menos terreno pero junta las verticales. El círculo es el que
más concurrencia da por metro de perímetro. Es una decisión de diseño del
emplazamiento, y ahora se puede medir en vez de suponerla.

## Qué queda por hacer

- Separar el volumen de llegada del de salida. Ahora mismo un dron que
  desciende y otro que asciende sobre pads compatibles se cruzan en alturas
  distintas por casualidad, no por diseño. Los vertipuertos reales tienen
  rutas de aproximación y de salida separadas.
- Reservar la vertical **antes** de iniciar el regreso, no al llegar al
  parking: si al llegar no hay hueco, el dron espera en el aire gastando la
  batería que precisamente le falta.
- Llevar el editor de formación al portal. Hoy vive en la consola de
  simulación, pero la geometría del parking no es cosa de la simulación: un
  vertipuerto real también tiene plazas y distancias.
