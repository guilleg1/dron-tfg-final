"""
Autenticación de administradores para el portal.

Sin dependencias externas: hash de contraseña con PBKDF2-HMAC-SHA256 (de la
librería estándar) y token de sesión firmado con HMAC. El token lleva el usuario
y una fecha de caducidad, y va firmado con una clave secreta del entorno
(SECRET_KEY); así el servidor puede validarlo sin guardar sesiones.
"""

import base64
import hashlib
import hmac
import json
import os
import secrets
import time

# Clave para firmar los tokens. En producción se define SECRET_KEY en el entorno
# (Railway); si no, se genera una efímera (los tokens dejan de valer al reiniciar).
_SECRET = os.environ.get("SECRET_KEY") or secrets.token_hex(32)

_PBKDF2_ROUNDS = 200_000
_TOKEN_TTL_S = 12 * 3600  # 12 horas


# ── Contraseñas ──────────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    """Devuelve 'salt$hash' (ambos en hex) para guardar en la BD."""
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ROUNDS)
    return f"{salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Comprueba una contraseña contra el 'salt$hash' almacenado."""
    try:
        salt_hex, hash_hex = stored.split("$", 1)
        salt = bytes.fromhex(salt_hex)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ROUNDS)
        return hmac.compare_digest(dk.hex(), hash_hex)
    except (ValueError, AttributeError):
        return False


# ── Tokens ───────────────────────────────────────────────────────────────────

def _sign(payload_b64: str) -> str:
    sig = hmac.new(_SECRET.encode(), payload_b64.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(sig).decode().rstrip("=")


def create_token(username: str, typ: str = "admin") -> str:
    """Token 'payload.firma' con el usuario, su rol y la caducidad.

    typ distingue administradores ('admin') de usuarios del portal ('user'),
    para que un token de un rol no valga en los endpoints del otro.
    """
    payload = {"sub": username, "typ": typ, "exp": int(time.time()) + _TOKEN_TTL_S}
    payload_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return f"{payload_b64}.{_sign(payload_b64)}"


def verify_token(token: str, typ: str | None = None) -> str | None:
    """Devuelve el usuario si el token es válido, no ha caducado y, si se pide,
    su rol coincide con ``typ``; si no, None."""
    if not token or "." not in token:
        return None
    payload_b64, sig = token.rsplit(".", 1)
    if not hmac.compare_digest(sig, _sign(payload_b64)):
        return None
    try:
        padded = payload_b64 + "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
    except (ValueError, json.JSONDecodeError):
        return None
    if payload.get("exp", 0) < time.time():
        return None
    if typ is not None and payload.get("typ") != typ:
        return None
    return payload.get("sub")
