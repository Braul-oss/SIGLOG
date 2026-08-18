"""
SIG-LOG — Sistema Integral de Gestión Logística
backend/services/usuarios.py

REGLAS DE GESTIÓN DE USUARIOS Y ROLES

Toda la administración de cuentas está reservada al ADMINISTRADOR, pero
eso no basta: un administrador con todos los permisos puede, sin querer,
dejar el sistema sin nadie que lo administre. Las reglas de este módulo
existen para impedirlo.

Reglas de negocio (RN-U1 a RN-U5)
---------------------------------
RN-U1  Nadie puede desactivar su propia cuenta. Quien lo hiciera perdería
       el acceso en la misma petición que lo pidió.

RN-U2  Nadie puede cambiar su propio rol. Un administrador que se degrada
       a ANALISTA no puede volver a subirse, porque para eso hace falta
       ser administrador.

RN-U3  No se puede quedar el sistema sin ningún administrador activo, ni
       desactivando al último ni degradándolo. Sin administradores, la
       gestión de usuarios solo se recupera desde la línea de comandos.

RN-U4  El identificador de acceso es único y no se puede cambiar. Cambiarlo
       rompería la trazabilidad de quién hizo qué; si hace falta otro
       nombre, se crea otra cuenta.

RN-U5  El hash de la contraseña nunca sale del servidor, en ninguna
       respuesta ni en ningún listado.

Las tres primeras son las que convierten esto en algo más que un CRUD.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from backend.repositories.usuarios import RepositorioUsuarios
from backend.schemas.autenticacion import UsuarioSalida
from backend.schemas.usuarios import RolInfo
from backend.utils.errores import RecursoDuplicado, ReglaDeNegocio
from backend.utils.seguridad import cifrar_contrasena
from config import settings

# Descripción de cada rol, tomada de los actores del §3.
DESCRIPCION_ROLES: dict[str, tuple[str, str]] = {
    settings.ROL_ADMINISTRADOR: (
        "Administrador / Coordinador logístico",
        "Gestiona catálogos, configuración del sistema y cuentas de usuario."),
    settings.ROL_DESPACHADOR: (
        "Despachador / Capturista",
        "Registra jornadas, entregas, incidentes y cargas de combustible."),
    settings.ROL_ANALISTA: (
        "Analista / Directivo",
        "Consulta el dashboard, los reportes y los resultados de los modelos."),
}


# ==========================================================================
# CONSULTA
# ==========================================================================
def listar(bd: Database, *, saltar: int = 0, limite: int = 50,
           rol: str | None = None, incluir_inactivos: bool = False
           ) -> tuple[list[dict[str, Any]], int]:
    """
    Listado paginado. Devuelve (cuentas, total) para que el cliente sepa
    cuántas páginas hay sin tener que pedirlas todas.
    """
    repositorio = RepositorioUsuarios(bd)
    filtro: dict[str, Any] = {}
    if rol:
        rol = rol.strip().upper()
        if rol not in settings.CATALOGO_ROLES:
            raise ReglaDeNegocio(
                f"Rol '{rol}' no pertenece al catálogo "
                f"{list(settings.CATALOGO_ROLES)}.")
        filtro["rol"] = rol

    documentos = repositorio.listar(
        filtro, saltar=saltar, limite=limite,
        orden=[("usuario", 1)], incluir_inactivos=incluir_inactivos)
    total = repositorio.contar(filtro, incluir_inactivos=incluir_inactivos)
    return [_publico(d) for d in documentos], total


def obtener(bd: Database, identificador: str) -> dict[str, Any]:
    """Detalle de una cuenta (incluidas las dadas de baja)."""
    return _publico(
        RepositorioUsuarios(bd).obtener(identificador, incluir_inactivos=True))


def catalogo_de_roles() -> list[dict[str, str]]:
    """Roles disponibles con su descripción, para poblar un selector."""
    return [
        RolInfo(rol=rol, actor=actor, descripcion=descripcion).model_dump()
        for rol, (actor, descripcion) in DESCRIPCION_ROLES.items()
    ]


def resumen(bd: Database) -> dict[str, Any]:
    """Conteo de cuentas por rol y por estado."""
    repositorio = RepositorioUsuarios(bd)
    por_rol = {
        rol: repositorio.contar({"rol": rol}) for rol in settings.CATALOGO_ROLES
    }
    total = repositorio.contar(incluir_inactivos=True)
    activos = repositorio.contar()
    return {
        "total": total,
        "activos": activos,
        "inactivos": total - activos,
        "por_rol": por_rol,
        "administradores_activos": por_rol[settings.ROL_ADMINISTRADOR],
    }


# ==========================================================================
# ALTA
# ==========================================================================
def crear(bd: Database, datos: dict[str, Any]) -> dict[str, Any]:
    """
    Da de alta una cuenta.

    La unicidad la garantiza el índice único de MongoDB; aquí se traduce el
    error del motor a un 409 con mensaje entendible. Comprobar antes con un
    `find_one` no bastaría: entre la comprobación y la inserción cabe otra
    petición idéntica.
    """
    repositorio = RepositorioUsuarios(bd)
    documento = {
        "usuario": datos["usuario"],
        "hash_contrasena": cifrar_contrasena(datos["contrasena"]),
        "nombre_completo": datos["nombre_completo"],
        "correo": datos.get("correo"),
        "rol": datos["rol"],
        "ultimo_acceso": None,
        "intentos_fallidos": 0,
    }
    try:
        creado = repositorio.crear(documento)
    except DuplicateKeyError as exc:
        raise RecursoDuplicado(
            f"Ya existe una cuenta con el usuario '{datos['usuario']}'.") from exc
    return _publico(creado)


# ==========================================================================
# EDICIÓN
# ==========================================================================
def actualizar(bd: Database, identificador: str,
               cambios: dict[str, Any]) -> dict[str, Any]:
    """
    Edita los datos descriptivos.

    RN-U4: el identificador de acceso no se cambia. El esquema de entrada
    ni siquiera lo acepta; esta comprobación es la segunda barrera, por si
    alguien llamara al servicio desde otro sitio.
    """
    if "usuario" in cambios:
        raise ReglaDeNegocio(
            "El identificador de acceso no se puede cambiar (RN-U4). "
            "Si hace falta otro nombre, crea una cuenta nueva.",
            regla="U4")
    if not cambios:
        raise ReglaDeNegocio("No se envió ningún campo que actualizar.")

    return _publico(RepositorioUsuarios(bd).actualizar(identificador, cambios,
                                                      incluir_inactivos=True))


def cambiar_rol(bd: Database, identificador: str, rol_nuevo: str,
                solicitante: dict[str, Any]) -> dict[str, Any]:
    """
    Cambia el rol de una cuenta, con las reglas RN-U2 y RN-U3.
    """
    repositorio = RepositorioUsuarios(bd)
    objetivo = repositorio.obtener(identificador, incluir_inactivos=True)

    # RN-U2 — nadie se cambia el rol a sí mismo
    if _es_el_mismo(objetivo, solicitante):
        raise ReglaDeNegocio(
            "No puedes cambiar tu propio rol (RN-U2). Si te degradaras, "
            "no podrías volver a subirte: para eso hace falta ser "
            "administrador. Pídeselo a otro administrador.",
            regla="U2")

    if objetivo["rol"] == rol_nuevo:
        raise ReglaDeNegocio(
            f"La cuenta '{objetivo['usuario']}' ya tiene el rol {rol_nuevo}.")

    # RN-U3 — no dejar el sistema sin administradores
    if (objetivo["rol"] == settings.ROL_ADMINISTRADOR
            and rol_nuevo != settings.ROL_ADMINISTRADOR):
        _exigir_otro_administrador(
            repositorio, objetivo,
            "degradar al último administrador activo")

    # incluir_inactivos: el rol de una cuenta dada de baja también se puede
    # corregir; su existencia ya se validó arriba.
    return _publico(repositorio.actualizar(identificador, {"rol": rol_nuevo},
                                           incluir_inactivos=True))


def restablecer_contrasena(bd: Database, identificador: str,
                           contrasena_nueva: str) -> dict[str, Any]:
    """
    Asigna una contraseña nueva sin pedir la anterior.

    Es la operación de recuperación: el titular la olvidó. Por eso está
    reservada al administrador y se registra en `fecha_modificacion`.
    """
    repositorio = RepositorioUsuarios(bd)
    objetivo = repositorio.obtener(identificador, incluir_inactivos=True)
    repositorio.actualizar_contrasena(objetivo["_id"],
                                      cifrar_contrasena(contrasena_nueva))
    return _publico(repositorio.obtener(identificador, incluir_inactivos=True))


# ==========================================================================
# BAJA Y REACTIVACIÓN
# ==========================================================================
def desactivar(bd: Database, identificador: str,
               solicitante: dict[str, Any]) -> dict[str, Any]:
    """
    Baja lógica de la cuenta (§12.3: DELETE es baja lógica).

    No se borra el documento: quedaría sin explicación quién realizó las
    operaciones que esa cuenta registró.
    """
    repositorio = RepositorioUsuarios(bd)
    objetivo = repositorio.obtener(identificador, incluir_inactivos=True)

    # RN-U1 — nadie se desactiva a sí mismo
    if _es_el_mismo(objetivo, solicitante):
        raise ReglaDeNegocio(
            "No puedes desactivar tu propia cuenta (RN-U1): perderías el "
            "acceso en esta misma operación. Pídeselo a otro administrador.",
            regla="U1")

    if not objetivo.get("activo", True):
        raise ReglaDeNegocio(
            f"La cuenta '{objetivo['usuario']}' ya estaba desactivada.")

    # RN-U3 — no dejar el sistema sin administradores
    if objetivo["rol"] == settings.ROL_ADMINISTRADOR:
        _exigir_otro_administrador(
            repositorio, objetivo,
            "desactivar al último administrador activo")

    return _publico(repositorio.baja_logica(identificador))


def reactivar(bd: Database, identificador: str) -> dict[str, Any]:
    """Devuelve el acceso a una cuenta dada de baja."""
    repositorio = RepositorioUsuarios(bd)
    objetivo = repositorio.obtener(identificador, incluir_inactivos=True)
    if objetivo.get("activo", True):
        raise ReglaDeNegocio(f"La cuenta '{objetivo['usuario']}' ya está activa.")

    return _publico(repositorio.actualizar(
        identificador, {"activo": True, "intentos_fallidos": 0},
        incluir_inactivos=True))


# ==========================================================================
# INTERNO
# ==========================================================================
def _publico(documento: dict[str, Any]) -> dict[str, Any]:
    """
    RN-U5: convierte el documento a su representación pública.

    Pasa por `UsuarioSalida`, que no contempla el hash: aunque el documento
    lo traiga, no puede salir por aquí.
    """
    return UsuarioSalida.desde_documento(documento).model_dump()


def _es_el_mismo(objetivo: dict[str, Any], solicitante: dict[str, Any]) -> bool:
    return str(objetivo["_id"]) == str(solicitante["_id"])


def _exigir_otro_administrador(repositorio: RepositorioUsuarios,
                               objetivo: dict[str, Any], accion: str) -> None:
    """
    RN-U3: comprueba que quede al menos otro administrador activo.

    Se cuentan los administradores activos DISTINTOS del afectado; si no
    hay ninguno, la operación dejaría el sistema sin gestión posible desde
    la aplicación.
    """
    otros = repositorio.contar({
        "rol": settings.ROL_ADMINISTRADOR,
        "_id": {"$ne": objetivo["_id"]},
    })
    if otros == 0:
        raise ReglaDeNegocio(
            f"No se puede {accion} (RN-U3): el sistema quedaría sin nadie "
            "que pueda gestionar usuarios desde la aplicación. Crea o "
            "promueve antes a otro administrador.",
            regla="U3")
