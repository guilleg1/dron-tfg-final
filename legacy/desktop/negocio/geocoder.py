"""
Geocoder con respaldo: convierte una dirección de texto en coordenadas.

Usa dos proveedores en cadena vía geopy:
  1. Nominatim (OpenStreetMap) — preciso, pero su servidor público bloquea las
     IPs de datacenter (p. ej. Render), así que no siempre responde en la nube.
  2. Photon (komoot) — mismo dato de OSM, sí accesible desde datacenters; actúa
     de respaldo cuando Nominatim no contesta.

Así la geocodificación funciona tanto en local como en el despliegue cloud.
"""

from geopy.geocoders import Nominatim, Photon

_USER_AGENT = "proyecto_drones_tfg"

# Instancias globales reutilizables.
_nominatim = Nominatim(user_agent=_USER_AGENT)
_photon = Photon(user_agent=_USER_AGENT)

# Proveedores en orden de preferencia.
_PROVIDERS = (("Nominatim", _nominatim), ("Photon", _photon))


def geocode_address(address):
    """
    Convierte una dirección de texto a coordenadas (latitud, longitud).

    Prueba los proveedores en orden hasta que uno devuelve un resultado.

    Returns
    -------
    tuple
        (latitud, longitud)

    Raises
    ------
    ValueError
        Si la dirección está vacía o ningún proveedor encuentra coordenadas.
    """
    if not address or not str(address).strip():
        raise ValueError("La dirección está vacía")

    address = str(address).strip()
    last_error = None

    for name, provider in _PROVIDERS:
        try:
            location = provider.geocode(address, timeout=10)
            if location:
                return location.latitude, location.longitude
        except Exception as e:  # timeout, servicio no disponible, IP bloqueada…
            last_error = f"{name}: {e}"
            continue

    if last_error:
        raise ValueError(
            f"No se pudo geocodificar '{address}'. Último error: {last_error}"
        )
    raise ValueError(f"No se encontraron coordenadas para: {address}")
