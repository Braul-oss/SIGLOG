"""
SIG-LOG — Sistema Integral de Gestión Logística
backend/services/autenticacion.py

REGLAS DE AUTENTICACIÓN Y CONTROL DE ACCESO  (RNP-11, opción b)

Aquí viven las decisiones de seguridad; el router solo las expone y
`utils/seguridad.py` solo aporta las primitivas (hash y firma).

Tres reglas que conviene tener presentes al leer el código:

1. Un fallo de acceso responde SIEMPRE lo mismo, dé igual si el usuario no
   existe, si la contraseña es incorrecta o si la cuenta está desactivada.
   Diferenciarlos permitiría averiguar qué cuentas existen probando
   nombres.

2. Autenticar (401) y autorizar (403) son distintos. El primero significa
   "no sé quién eres"; el segundo, "sé quién eres y no te alcanza". Volver
   a iniciar sesión arregla el primero y nunca el segundo.

3. El rol viaja dentro del token, pero la cuenta se vuelve a leer de la
   base en cada petición. Así, desactivar a alguien surte efecto de
   inmediato en lugar de esperar a que su token expire.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from pymongo.database import Database

from backend.repositories.usuarios import RepositorioUsuarios
from backend.utils.errores import DatosInvalidos
from backend.utils.seguridad import (
    CredencialesInvalidas,
    PermisoDenegado,
    cifrar_contrasena,
    crear_token,
    leer_token,
    verificar_contrasena,
)
from config import settings

# Mensaje único de fallo de acceso (regla 1).
MENSAJE_ACCESO_FALLIDO = "Usuario o contraseña incorrectos."


# ==========================================================================
# INICIO DE SESIÓN
# ==========================================================================
def autenticar(bd: Database, usuario: str, contrasena: str) -> dict[str, Any]:
    """
    Comprueba las credenciales y devuelve el documento del usuario.

    Se verifica la contraseña incluso cuando la cuenta no existe, contra un
    hash de descarte. Sin eso, un usuario inexistente respondería más
    rápido que uno real, y esa diferencia de tiempo delata qué cuentas
    existen.
    """
    repositorio = RepositorioUsuarios(bd)
    documento = repositorio.por_nombre_de_usuario(usuario)

    if documento is None:
        _consumir_tiempo_de_verificacion(contrasena)
        raise CredencialesInvalidas(MENSAJE_ACCESO_FALLIDO)

    if not verificar_contrasena(contrasena, documento.get("hash_contrasena", "")):
        repositorio.contar_intento_fallido(documento["_id"])
        raise CredencialesInvalidas(MENSAJE_ACCESO_FALLIDO)

    repositorio.registrar_acceso(documento["_id"])
    return documento


def iniciar_sesion(bd: Database, usuario: str, contrasena: str) -> dict[str, Any]:
    """Autentica y emite el token de sesión."""
    documento = autenticar(bd, usuario, contrasena)
    token, expira = crear_token(documento["usuario"], documento["rol"])
    return {
        "access_token": token,
        "token_type": "bearer",
        "expira_en": expira,
        "usuario": documento["usuario"],
        "rol": documento["rol"],
    }


def _consumir_tiempo_de_verificacion(contrasena: str) -> None:
    """
    Gasta el mismo tiempo que una verificación real cuando el usuario no
    existe, para no filtrar su existencia por la duración de la respuesta.
    """
    hash_de_descarte = (
        "$2b$12$" + "0123456789012345678901"          # sal de 22 caracteres
        + "0123456789012345678901234567890"           # hash de 31
    )
    verificar_contrasena(contrasena, hash_de_descarte)


# ==========================================================================
# IDENTIFICACIÓN A PARTIR DEL TOKEN
# ==========================================================================
def usuario_desde_token(bd: Database, token: str) -> dict[str, Any]:
    """
    Traduce un token en el usuario que lo posee.

    Vuelve a leer la cuenta de la base a propósito (regla 3): si alguien es
    dado de baja, su token deja de servir en la siguiente petición y no al
    cabo de ocho horas.
    """
    contenido = leer_token(token)
    nombre = contenido.get("sub")
    if not nombre:
        raise CredencialesInvalidas("El token no identifica a ningún usuario.")

    documento = RepositorioUsuarios(bd).por_nombre_de_usuario(nombre)
    if documento is None:
        raise CredencialesInvalidas(
            "La cuenta ya no existe o fue desactivada.")

    # El rol del token pudo cambiar desde que se emitió; manda la base.
    documento["rol_en_token"] = contenido.get("rol")
    return documento


# ==========================================================================
# AUTORIZACIÓN POR ROL
# ==========================================================================
def exigir_rol(usuario: dict[str, Any], roles: tuple[str, ...]) -> None:
    """
    Comprueba que el rol del usuario esté entre los autorizados.

    El ADMINISTRADOR no recibe paso libre automático: si un endpoint es
    solo para despachadores, lo es también para el administrador. Las
    excepciones implícitas son las que después nadie sabe explicar.
    """
    if usuario["rol"] not in roles:
        raise PermisoDenegado(
            f"Tu rol ({usuario['rol']}) no tiene permiso para esta operación.",
            rol_actual=usuario["rol"],
            roles_requeridos=roles,
        )


# ==========================================================================
# CAMBIO DE CONTRASEÑA PROPIA
# ==========================================================================
def cambiar_contrasena(bd: Database, usuario: dict[str, Any],
                       actual: str, nueva: str) -> None:
    """
    Cambia la contraseña del usuario autenticado.

    Exige la actual aunque la sesión ya esté iniciada: impide que quien se
    encuentre una sesión abierta se apropie de la cuenta.
    """
    if not verificar_contrasena(actual, usuario.get("hash_contrasena", "")):
        raise CredencialesInvalidas("La contraseña actual no es correcta.")
    if actual == nueva:
        raise DatosInvalidos("La contraseña nueva debe ser distinta de la actual.")

    RepositorioUsuarios(bd).actualizar_contrasena(
        usuario["_id"], cifrar_contrasena(nueva))


# ==========================================================================
# ESTADO DEL SUBSISTEMA
# ==========================================================================
def estado_seguridad(bd: Database) -> dict[str, Any]:
    """
    Diagnóstico del control de acceso, sin exponer ninguna cuenta.

    Avisa de las dos situaciones que dejan el sistema desprotegido: no
    haber creado ningún usuario todavía, y seguir firmando los tokens con
    la clave de desarrollo.
    """
    repositorio = RepositorioUsuarios(bd)
    hay_usuarios = repositorio.hay_usuarios()

    advertencias = []
    if not hay_usuarios:
        advertencias.append(
            "No existe ningún usuario. Crea el primero con: "
            "python -m database.crear_usuario")
    if settings.jwt_clave_es_insegura():
        advertencias.append(
            "JWT_CLAVE tiene el valor de desarrollo. Genera una propia con "
            "python -c \"import secrets; print(secrets.token_hex(32))\" "
            "y colócala en el .env.")

    return {
        "autenticacion": "JWT (HS256)",
        "roles": list(settings.CATALOGO_ROLES),
        "vigencia_token_min": settings.JWT_MINUTOS_EXPIRACION,
        "usuarios_registrados": hay_usuarios,
        "clave_segura": not settings.jwt_clave_es_insegura(),
        "advertencias": advertencias,
    }
