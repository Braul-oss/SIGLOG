"""
SIG-LOG — Sistema Integral de Gestión Logística
backend/utils/seguridad.py

PRIMITIVAS DE SEGURIDAD: CONTRASEÑAS Y TOKENS

Dos responsabilidades, deliberadamente juntas y aisladas del resto: cifrar
y verificar contraseñas, y emitir y validar los tokens JWT. Ningún otro
módulo debe importar `bcrypt` ni `jwt` directamente; si la política de
seguridad cambia —otro algoritmo de hash, otra vigencia—, se cambia aquí.

Contraseñas
-----------
Se guarda el **hash bcrypt**, nunca la contraseña. bcrypt incorpora una
sal aleatoria en cada hash (dos usuarios con la misma contraseña producen
hashes distintos) y es deliberadamente lento, lo que encarece un ataque
por fuerza bruta sobre la base robada.

Tokens
------
JWT firmado con HS256. El token lleva quién es el usuario (`sub`), su rol
y cuándo expira, y va firmado con la clave del `.env`: el servidor puede
verificarlo sin consultar la base en cada petición, pero nadie puede
fabricar uno sin la clave.

Lo que el token **no** lleva: la contraseña, el hash ni ningún dato
sensible. Un JWT va firmado, no cifrado — cualquiera que lo intercepte
puede leer su contenido.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

import bcrypt
import jwt

from backend.utils.errores import DatosInvalidos
from config import settings

# bcrypt trunca en 72 bytes; una contraseña más larga se aceptaría en
# silencio ignorando el resto, así que se rechaza explícitamente.
LIMITE_BYTES_CONTRASENA = 72
LONGITUD_MINIMA_CONTRASENA = 8


# ==========================================================================
# CONTRASEÑAS
# ==========================================================================
def validar_fortaleza(contrasena: str) -> None:
    """
    Reglas mínimas de una contraseña aceptable.

    No se pide una combinación barroca de símbolos: la longitud aporta más
    resistencia real que obligar a poner un signo de admiración.
    """
    if len(contrasena) < LONGITUD_MINIMA_CONTRASENA:
        raise DatosInvalidos(
            f"La contraseña debe tener al menos {LONGITUD_MINIMA_CONTRASENA} "
            "caracteres.")
    if len(contrasena.encode("utf-8")) > LIMITE_BYTES_CONTRASENA:
        raise DatosInvalidos(
            f"La contraseña no puede superar {LIMITE_BYTES_CONTRASENA} bytes.")


def cifrar_contrasena(contrasena: str) -> str:
    """Devuelve el hash bcrypt (con su sal incorporada) listo para guardar."""
    validar_fortaleza(contrasena)
    return bcrypt.hashpw(contrasena.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verificar_contrasena(contrasena: str, hash_guardado: str) -> bool:
    """
    Compara la contraseña con el hash almacenado.

    Un hash corrupto o de otro formato devuelve False en lugar de propagar
    la excepción: para quien intenta entrar, "no es válida" y "el registro
    está dañado" deben ser indistinguibles.
    """
    try:
        return bcrypt.checkpw(contrasena.encode("utf-8"),
                              hash_guardado.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# ==========================================================================
# TOKENS JWT
# ==========================================================================
def crear_token(usuario: str, rol: str,
                minutos: int | None = None) -> tuple[str, datetime]:
    """
    Emite un token firmado. Devuelve (token, momento de expiración).

    Claims estándar: `sub` (el usuario), `exp` (expiración) e `iat`
    (emisión). `rol` es propio del sistema y evita consultar la base en
    cada petición solo para saber qué puede hacer quien pregunta.
    """
    ahora = datetime.now(timezone.utc)
    expira = ahora + timedelta(
        minutes=minutos if minutos is not None else settings.JWT_MINUTOS_EXPIRACION)

    token = jwt.encode(
        {
            "sub": usuario,
            "rol": rol,
            "iat": ahora,
            "exp": expira,
            "iss": settings.APP_NOMBRE,
        },
        settings.JWT_CLAVE,
        algorithm=settings.JWT_ALGORITMO,
    )
    return token, expira


def leer_token(token: str) -> dict[str, Any]:
    """
    Verifica firma y vigencia, y devuelve el contenido.

    Distingue el token caducado del inválido: al usuario le sirve saber
    que debe volver a entrar, y no es información que ayude a un atacante.
    """
    try:
        return jwt.decode(token, settings.JWT_CLAVE,
                          algorithms=[settings.JWT_ALGORITMO],
                          issuer=settings.APP_NOMBRE)
    except jwt.ExpiredSignatureError as exc:
        raise CredencialesInvalidas(
            "La sesión expiró. Inicia sesión de nuevo.") from exc
    except jwt.InvalidTokenError as exc:
        raise CredencialesInvalidas("El token no es válido.") from exc


# ==========================================================================
# ERROR DE AUTENTICACIÓN
# ==========================================================================
class CredencialesInvalidas(Exception):
    """
    401 — no se pudo verificar quién hace la petición.

    Vive aquí y no en `errores.py` porque necesita una respuesta HTTP
    especial: el estándar exige acompañar el 401 con la cabecera
    `WWW-Authenticate`, que ningún otro error del sistema lleva.
    """

    estado_http = 401
    codigo_error = "CREDENCIALES_INVALIDAS"

    def __init__(self, mensaje: str = "No fue posible verificar tus credenciales.") -> None:
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.detalles: list[Any] = []


class PermisoDenegado(Exception):
    """
    403 — sabemos quién eres, pero tu rol no alcanza para esta operación.

    Es distinto del 401 a propósito: volver a iniciar sesión no lo
    resuelve, y confundirlos manda al usuario a repetir el login en vano.
    """

    estado_http = 403
    codigo_error = "PERMISO_DENEGADO"

    def __init__(self, mensaje: str, rol_actual: str | None = None,
                 roles_requeridos: tuple[str, ...] = ()) -> None:
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.detalles = [{
            "rol_actual": rol_actual,
            "roles_autorizados": list(roles_requeridos),
        }] if rol_actual else []
