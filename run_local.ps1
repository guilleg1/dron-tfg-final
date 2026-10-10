# Arranca el portal conectado al enjambre de instancias SITL.
# Lanza antes las instancias con ./run_swarm.ps1
#
# Con DRONE_BACKEND=stub el portal funciona igual pero sin drones, y con
# DRONE_BACKEND=simulado vuela el enjambre sobre el enlace simulado, que es
# como corre en Railway.

$env:DRONE_BACKEND = "sitl"

# dronLink va vendorizado en vendor/. Descomenta para forzar otra copia:
# $env:DRONLINK_PATH = "C:\Users\test\Desktop\TFG\ProyectoDeDrones"

# Sin DATABASE_URL usa SQLite local; con ella, Supabase:
# $env:DATABASE_URL = "postgresql://..."

# Se invoca como 'python -m uvicorn' para no depender de que el ejecutable
# uvicorn este en el PATH.
python -m uvicorn airdrop.api.main:app --host 0.0.0.0 --port 8080
