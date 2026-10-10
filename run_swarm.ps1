# Lanza una instancia SITL por dron habilitado de la flota.
#
# La configuracion (puertos, SYSID, pads) la posee Python y sale de la base de
# datos, la misma que usa el portal: este script es solo un envoltorio para no
# tener que recordar el comando.
#
# Requiere el SITL que instala Mission Planner. Con SITL_BINARY se puede
# apuntar a otro ArduCopter.exe.

param(
    [ValidateSet("launch", "status", "stop")]
    [string]$Accion = "launch"
)

python -m airdrop.swarm.sitl $Accion
