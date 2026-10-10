# Arranca la consola de simulacion (banco de pruebas) en el 8090.
#
# No sustituye al portal: ./run_local.ps1 sigue siendo lo que se opera. Esta
# consola solo levanta y desmonta simulaciones SITL, cambia la formacion del
# parking y vacia la base de datos entre experimentos.
#
# El SITL de Mission Planner se busca solo: se prueban Documents, Documentos y
# sus versiones bajo OneDrive, que es donde acaba segun el idioma de Windows y
# si la carpeta esta redirigida. Solo hace falta SITL_BINARY si lo tienes en
# otro sitio:
#   $env:SITL_BINARY = "D:\ruta\a\ArduCopter.exe"

python -m simtools
