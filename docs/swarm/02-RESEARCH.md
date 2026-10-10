# 02 · Estado del arte y referencias

> Investigación que justifica las decisiones del `03-ARCHITECTURE.md` y que
> sirve como base para el capítulo de marco teórico de la memoria del TFG.

Toda referencia lleva enlace directo a la fuente. Las que terminan en
`arxiv.org` son los originales libres; los `sciencedirect.com` y
`mdpi.com` están en abierto excepto cuando se indica con (📚 *paywall*).

---

## 1. Formulación del problema

El problema "**N drones desde un parking, M pedidos con peso, rutas
pre-aprobadas, drones heterogéneos con autonomía**" cae casi exactamente en la
familia del **Vehicle Routing Problem with Drones (VRPD)**, y más concretamente
en sus variantes:

| Variante                         | Aplica? | Por qué                                                                |
| -------------------------------- | ------- | ---------------------------------------------------------------------- |
| **CVRP** (Capacitated VRP)       | Sí      | Cada dron tiene capacidad de carga (peso) limitada.                    |
| **HFVRP** (Heterogeneous Fleet)  | Sí      | Drones con distinta autonomía y categoría de carga.                    |
| **E-VRP** (Energy-constrained)   | Sí      | Batería finita, consumo dependiente de payload y distancia.            |
| **MDVRP** (Multi-Depot)          | Parcial | Hay un único parking en el caso base, pero el código ya soporta varios |
| **VRPTW** (Time Windows)         | Futuro  | Si el TFG añade SLA por pedido. No es necesario en v1.                 |

La formulación canónica del **Drone Routing Problem** se introduce en
Dorling et al. (2016)¹ y se ha ampliado consistentemente desde entonces².

Para el TFG es suficiente dejar escrito que **resolvemos un CVRP heterogéneo
con restricción de energía** y citar la formulación de:

- **Dorling, K. et al. (2017)** — *Vehicle Routing Problems for Drone
  Delivery*. IEEE T-SMC, 47(1):70–85.
  [arxiv.org/pdf/1608.02305](https://arxiv.org/pdf/1608.02305)
- **Liu, Y. et al. (2024)** — *Drone Routing for Drone-Based Delivery Systems:
  A Review of Trajectory Planning, Charging, and Security*. Sensors, MDPI.
  [mdpi.com/1424-8220/23/3/1463](https://www.mdpi.com/1424-8220/23/3/1463)

---

## 2. Algoritmos de asignación y enrutado

### 2.1 Solvers exactos / centralizados — recomendado para v1

#### Google **OR-Tools** (CVRP / VRP)

- API Python madura, gratis, sin compilación nativa en Windows.
- Soporta restricciones de capacidad (`AddDimensionWithVehicleCapacity`) y de
  distancia/tiempo (`AddDimension`).
- Estrategia: **First-Solution + Guided Local Search** con timeout de pocos
  segundos.
- Es la opción **por defecto** del TFG.

📖 Ejemplos directamente aplicables:

- Tutorial Medium aplicado a CVRP: [medium.com/@nag96.chidara/capacitated-vehicle-routing-problem-cvrp-optimization-using-google-or-tools-and-python](https://medium.com/@nag96.chidara/capacitated-vehicle-routing-problem-cvrp-optimization-using-google-or-tools-and-python-7848fb5ffd16)
- Docs oficiales: [developers.google.com/optimization/routing](https://developers.google.com/optimization/routing) (CVRP, VRPTW, vehículos heterogéneos).

#### Asignación pura (sin secuenciar) — **Hungarian**

Si en cada turno de planning **cada dron solo coge 1 pedido**, el problema se
reduce a *minimum-cost assignment* y se resuelve en `O(n³)` con
`scipy.optimize.linear_sum_assignment`. Útil como **baseline** y para *fallback*
si OR-Tools no encuentra solución en tiempo.

### 2.2 Algoritmos descentralizados — referencia teórica del TFG

#### **CBBA** — *Consensus-Based Bundle Algorithm*

- Cada agente (dron) puja por tareas (pedidos) iterativamente; consenso
  distribuido resuelve conflictos.
- Apropiado cuando no hay un controlador central — **no es nuestro caso**,
  pero conviene citarlo en la memoria como alternativa "futuro trabajo".

📖 Referencias:

- **Choi, H.-L., Brunet, L., How, J. P. (2009)** — *Consensus-Based
  Decentralized Auctions for Robust Task Allocation*. IEEE T-RO 25(4).
  [researchgate.net/publication/228529155](https://www.researchgate.net/publication/228529155_Consensus-Based_Auction_Approaches_for_Decentralized_Task_Assignment)
- **Two-level clustered CBBA (2025)**:
  [mdpi.com/1424-8220/25/21/6738](https://www.mdpi.com/1424-8220/25/21/6738)
- **CBBA en entornos dinámicos** (2021):
  [link.springer.com/content/pdf/10.1007/s11227-021-03940-z.pdf](https://link.springer.com/content/pdf/10.1007/s11227-021-03940-z.pdf)

### 2.3 Metaheurísticas — mejora opcional sobre OR-Tools

- Algoritmos genéticos / *rescheduling-based*: Lin et al. (2023), ScienceDirect.
  [sciencedirect.com/.../S0360835223002036](https://www.sciencedirect.com/science/article/abs/pii/S0360835223002036) (📚)
- Hybrid Strategy multi-objetivo (MDPI Drones, 2025):
  [mdpi.com/2504-446X/10/1/7](https://www.mdpi.com/2504-446X/10/1/7)

> Para v1 NO añadimos metaheurística propia; OR-Tools incluye Guided Local
> Search internamente y es suficiente para los tamaños del TFG (≤10 drones,
> ≤30 pedidos).

---

## 3. Modelo de energía / autonomía

La autonomía es la restricción operativa más relevante. Hay dos enfoques:

### 3.1 Modelo lineal (recomendado para v1)

> Stolaroff et al. (2018) y reproducido por Zhang et al. (2021):
>
> `E_consumida = α · t_vuelo + β · m_payload · d_horizontal + γ · d_vertical`

donde `α, β, γ` se calibran experimentalmente y son aproximadamente lineales
en payload. Bibliografía clave:

- **Energy Consumption Models for Delivery Drones — Comparison & Assessment**
  (Z. Zhang, X. Liu et al.):
  [sciencedirect.com/.../S1361920920308531](https://www.sciencedirect.com/science/article/abs/pii/S1361920920308531) (📚)
  / preprint en [researchgate.net/publication/341945067](https://www.researchgate.net/publication/341945067_Energy_Consumption_Models_for_Delivery_Drones_A_Comparison_and_Assessment).
- **Energy-Constrained Delivery of Goods under Varying Wind** (S. Bryant et
  al., 2020): [arxiv.org/pdf/2012.08602](https://arxiv.org/pdf/2012.08602)

Para el TFG basta con:

```
batería_consumida_estimada(dron, ruta, pedido) =
    k_base · distancia_horizontal_km
  + k_payload · (peso_kg) · distancia_horizontal_km
  + k_subir  · max(altitud_máx_ruta - altitud_actual, 0)
```

con `k_*` calibrables y por defecto extraídos del modelo lineal de Zhang.
Si la energía estimada **del trayecto completo (ida + retorno al parking)**
supera la batería disponible **con margen de seguridad ≥20%**, ese dron NO
puede coger ese pedido.

### 3.2 Modelo battery-aware no lineal (futuro)

Cuando el SOC (state of charge) baja, la capacidad efectiva se degrada.
Modelo: Abeywickrama et al., *Battery-Aware Energy Model of Drone Delivery
Tasks* (2018), [researchgate.net/publication/330486353](https://www.researchgate.net/publication/330486353_Battery-Aware_Energy_Model_of_Drone_Delivery_Tasks).
Solo merece la pena si extendemos al modelo Peukert. Para el TFG es overkill.

### 3.3 Adaptive Policy / RL — referencia teórica

- **A-POMO: Adaptive Policy Optimization for Battery-Constrained Drone
  Delivery Routing** (AIAA, 2024):
  [arc.aiaa.org/doi/10.2514/1.I011709](https://arc.aiaa.org/doi/10.2514/1.I011709) (📚)
- **Provider-centric Allocation of Drone Swarm Services** (Lakhdari et al.):
  [arxiv.org/pdf/2107.05173](https://arxiv.org/pdf/2107.05173)
- **In-Flight Energy-Driven Composition of Drone Swarm Services** (Lakhdari et
  al., 2022): [arxiv.org/pdf/2210.17294](https://arxiv.org/pdf/2210.17294)

---

## 4. Coordinación multi-vehículo en ArduPilot / MAVLink

### 4.1 SYSID y multi-instancia SITL

- **ArduPilot Multi-Vehicle Flying**:
  [ardupilot.org/copter/docs/common-multi-vehicle-flying.html](https://ardupilot.org/copter/docs/common-multi-vehicle-flying.html)
- **Mission Planner Swarming (beta)**:
  [ardupilot.org/planner/docs/swarming.html](https://ardupilot.org/planner/docs/swarming.html)
- **MAVLink ID Assignment**:
  [mavlink.io/en/services/mavlink_id_assignment.html](https://mavlink.io/en/services/mavlink_id_assignment.html)
- **Drone Swarm Basics con ArduPilot (Zbotic, 2024)**:
  [zbotic.in/drone-swarm-basics-coordinate-multiple-uavs-with-ardupilot](https://zbotic.in/drone-swarm-basics-coordinate-multiple-uavs-with-ardupilot/)

> Configuración fundamental: cada autopiloto necesita un `SYSID_THISMAV`
> único (1..255). En SITL se consigue con `sim_vehicle.py --instance N
> --auto-sysid`. Cada instancia abre TCP en 5760, 5763, 5766, 5769…

### 4.2 Frameworks Python

- **DroneKit-Python**:
  [dronekit-python.readthedocs.io](https://dronekit-python.readthedocs.io/en/latest/examples/mission_basic.html)
- **pymavlink (mavgen)**:
  [mavlink.io/en/mavgen_python/](https://mavlink.io/en/mavgen_python/)
- **iq_tutorials/multi_mavros_drones** (ROS-MAVROS, referencia conceptual):
  [github.com/Intelligent-Quads/iq_tutorials/.../multi_mavros_drones.md](https://github.com/Intelligent-Quads/iq_tutorials/blob/master/docs/multi_mavros_drones.md)

> Nuestro proyecto NO usa MAVROS, pero el patrón "una conexión MAVLink por
> dron, comandos en paralelo desde el GCS" es idéntico. Mantenemos
> **dronLink + pymavlink**.

### 4.3 Mission Protocol

- **MAVLink Mission Protocol** (UPLOAD / DOWNLOAD / SET_CURRENT / MISSION_ACK):
  [mavlink.io/en/services/mission.html](https://mavlink.io/en/services/mission.html)

> Importa: cuando subimos misiones a `N` drones en paralelo el ACK puede
> tardar. Hacerlo en threads independientes y *no* serializar.

---

## 5. Deconflicción / Gestión del espacio aéreo

Para v1 sólo necesitamos **deconflicción estratégica** (en el plan, antes de
volar). Marco teórico:

- **UTM strategic / tactical / DAA layered model** — Yang Liu (Wayne State):
  [yliu.eng.wayne.edu/.../utm_flight_aiaa_final.pdf](https://yliu.eng.wayne.edu/research/utm_flight_aiaa_final.pdf)
- **Airspace Designs and Operations for UAS Traffic Management** (Aerospace
  MDPI, 2023): [mdpi.com/2226-4310/10/9/737](https://www.mdpi.com/2226-4310/10/9/737)
- **Designing airspace for urban air mobility** (Transport Reviews):
  [sciencedirect.com/.../S0376042121000312](https://www.sciencedirect.com/science/article/pii/S0376042121000312)
- **Layered airspace por altitud + heading**: ver review anterior, sección
  *Multi-Layer Airspace Approaches*.

### Estrategia que aplicamos al TFG

1. **Slot de altitud por dron en vuelo**: capas a 25 m, 30 m, 35 m, 40 m…
   El planner asigna a cada dron una altitud de crucero distinta de las que ya
   están "en vuelo".
2. **Escalonado de despegues**: si dos drones tienen que despegar del mismo
   parking en t≈0, retraso T=10 s entre uno y otro.
3. **El HUB es un punto sensible**: el planner garantiza que **a lo sumo un
   dron** ocupe el hub en un instante dado, calculando ETAs.
4. (Opcional) **Geofence virtual del parking**: la última zona de descenso
   solo admite un dron a la vez.

---

## 6. Tabla resumen de decisiones (con justificación)

| Decisión                          | Opción elegida           | Por qué                                                                         |
| --------------------------------- | ------------------------ | ------------------------------------------------------------------------------- |
| Algoritmo principal               | **CVRP heterogéneo + energía** vía OR-Tools | Madurez, soporte Python, suficiente para tamaños del TFG.        |
| Algoritmo fallback                | Hungarian (Scipy)        | Trivial, O(n³), siempre devuelve algo si OR-Tools falla.                        |
| Modelo de energía                 | Lineal (Stolaroff/Zhang) | Apto para optimización, parámetros simples, justificación bibliográfica sólida. |
| Arquitectura comms                | Centralizada (un GCS)    | Cuadra con `Desktop Drone Control`. CBBA citado como futuro trabajo.            |
| MAVLink multi-dron                | TCP por instancia SITL   | Documentado en ArduPilot oficial; encaja con `dronLink`.                        |
| Deconflicción                     | Layered altitudes + escalonado | Estrategia barata, demostrable visualmente; corredores ya pre-aprobados.  |
| UI                                | Extensión de `FleetPanel`| `add_drone` ya existe; basta con cablear N drones.                              |
| Persistencia                      | Ampliación SQLite        | Mínimo coste, no introduce dependencias.                                        |

---

## 7. Bibliografía completa (orden alfabético)

> Las referencias señaladas con (📚) son de pago; las demás son acceso libre.

1. Abeywickrama, H. V., Jayawickrama, B. A., He, Y., Dutkiewicz, E. (2018).
   *Battery-Aware Energy Model of Drone Delivery Tasks*.
   [researchgate.net/publication/330486353](https://www.researchgate.net/publication/330486353_Battery-Aware_Energy_Model_of_Drone_Delivery_Tasks)
2. Bryant, S., Yetkin, H., Hennig, T. (2020). *Energy-Constrained Delivery of
   Goods with Drones Under Varying Wind Conditions*. arXiv:2012.08602.
   [arxiv.org/pdf/2012.08602](https://arxiv.org/pdf/2012.08602)
3. Choi, H.-L., Brunet, L., How, J. P. (2009). *Consensus-Based Decentralized
   Auctions for Robust Task Allocation*. IEEE T-RO 25(4).
   [researchgate.net/publication/228529155](https://www.researchgate.net/publication/228529155_Consensus-Based_Auction_Approaches_for_Decentralized_Task_Assignment)
4. Dorling, K., Heinrichs, J., Messier, G., Magierowski, S. (2017). *Vehicle
   Routing Problems for Drone Delivery*. IEEE T-SMC 47(1).
   [arxiv.org/pdf/1608.02305](https://arxiv.org/pdf/1608.02305)
5. Google. (2024). *OR-Tools — Routing*.
   [developers.google.com/optimization/routing](https://developers.google.com/optimization/routing)
6. Lakhdari, A. et al. (2020). *Swarm-based Drone-as-a-Service (SDaaS) for
   Delivery*. arXiv:2005.06952.
   [arxiv.org/pdf/2005.06952](https://arxiv.org/pdf/2005.06952)
7. Lakhdari, A. et al. (2022). *In-Flight Energy-Driven Composition of Drone
   Swarm Services*. arXiv:2210.17294.
   [arxiv.org/pdf/2210.17294](https://arxiv.org/pdf/2210.17294)
8. Lin, Z. et al. (2023). *Optimal delivery route planning for a fleet of
   heterogeneous drones: A rescheduling-based GA approach*. Comp. & Ind. Eng.
   [sciencedirect.com/.../S0360835223002036](https://www.sciencedirect.com/science/article/abs/pii/S0360835223002036) (📚)
9. Liu, X., Hao, S., Zhou, Z. (2023). *Drone Routing for Drone-Based Delivery
   Systems: A Review*. Sensors 23(3):1463.
   [mdpi.com/1424-8220/23/3/1463](https://www.mdpi.com/1424-8220/23/3/1463)
10. Optimal Collaborative Transportation for Under-Capacitated VRP using
    Aerial Drone Swarms (2023). arXiv:2310.02726.
    [arxiv.org/pdf/2310.02726](https://arxiv.org/pdf/2310.02726)
11. Two-Level Clustered CBBA for Dynamic Heterogeneous Multi-UAV (2025).
    Sensors 25(21):6738.
    [mdpi.com/1424-8220/25/21/6738](https://www.mdpi.com/1424-8220/25/21/6738)
12. Zhang, J., Campbell, J., Sweeney, D., Hupman, A. (2021). *Energy
    Consumption Models for Delivery Drones: A Comparison and Assessment*.
    Transp. Res. D 90:102668.
    [sciencedirect.com/.../S1361920920308531](https://www.sciencedirect.com/science/article/abs/pii/S1361920920308531) (📚)
13. ArduPilot. (2024). *Multi-Vehicle Flying — Copter*.
    [ardupilot.org/copter/docs/common-multi-vehicle-flying.html](https://ardupilot.org/copter/docs/common-multi-vehicle-flying.html)
14. ArduPilot. (2024). *Mission Planner Swarming*.
    [ardupilot.org/planner/docs/swarming.html](https://ardupilot.org/planner/docs/swarming.html)
15. MAVLink. *MAVLink ID Assignment*.
    [mavlink.io/en/services/mavlink_id_assignment.html](https://mavlink.io/en/services/mavlink_id_assignment.html)
16. MAVLink. *Mission Protocol*.
    [mavlink.io/en/services/mission.html](https://mavlink.io/en/services/mission.html)
17. Yang Liu (Wayne State). *Strategic Deconfliction of Unmanned Aircraft*.
    [yliu.eng.wayne.edu/.../utm_flight_aiaa_final.pdf](https://yliu.eng.wayne.edu/research/utm_flight_aiaa_final.pdf)
