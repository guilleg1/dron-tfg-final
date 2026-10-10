"""Consola de simulación: banco de pruebas del enjambre.

**No es parte del producto.** El portal (``airdrop``) es lo que volaría con
drones reales; esta consola existe solo para montar y desmontar experimentos
deprisa: levantar instancias SITL, cambiar la formación del parking, vaciar la
base de datos y volver a empezar.

La frontera es deliberada y es la respuesta a «¿esto serviría con drones de
verdad?»:

- Lo que **también vale con drones reales** vive en el portal. La formación
  del parking es configuración operativa —un vertipuerto real también tiene
  sus plazas y sus distancias— y por eso la geometría está en
  ``OperationalScenario``, no aquí. Esta consola solo la edita con un dibujo.
- Lo que **solo existe en simulación** vive aquí: lanzar y matar procesos
  SITL, elegir el factor de aceleración, vaciar tablas. Nada de esto tiene
  sentido contra un autopiloto físico.

En local se usa suelta (``python -m simtools``, en 127.0.0.1 y sin login). El
portal la sirve además en ``/simulacion/`` detrás del login de administrador
(``airdrop/api/sim_admin.py``), porque en la nube no hay otra forma de cambiar
la flota ni el SITL. Es la misma página: solo cambia a qué rutas llama.

Uso:
    python -m simtools
"""

__all__ = ["app"]
