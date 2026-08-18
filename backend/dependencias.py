"""
SIG-LOG — Sistema Integral de Gestión Logística
backend/dependencias.py

INYECCIÓN DE DEPENDENCIAS DE FASTAPI

Un endpoint que necesite la base de datos la declara como parámetro:

    def listar(bd: Database = Depends(obtener_base_datos)): ...

De ahí salen dos cosas que importan: la API **reutiliza el cliente único**
de `config/mongo_conexion.py` en lugar de abrir el suyo —el pool de
conexiones del tier gratuito de Atlas es limitado y el ETL, el seed y los
scripts de ML ya comparten ese cliente—, y una prueba puede sustituir la
base real con `app.dependency_overrides` sin tocar el código.

Aquí vivirán también, cuando llegue su actividad, las dependencias de
autenticación (`usuario_actual`, `requiere_rol`). Se deja el punto de
extensión indicado, sin implementarlo.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from pymongo.database import Database
from pymongo.errors import PyMongoError

from backend.schemas.comunes import Paginacion
from backend.utils.errores import ServicioNoDisponible
from config import settings
from config.mongo_conexion import obtener_bd


def obtener_base_datos() -> Database:
    """
    Base de datos de trabajo, tomada del cliente compartido del proyecto.

    No abre conexión: PyMongo la resuelve de forma perezosa en la primera
    consulta. Si la configuración está incompleta responde 503 en lugar de
    reventar con un error interno sin explicación.
    """
    try:
        return obtener_bd()
    except (ValueError, PyMongoError) as exc:
        raise ServicioNoDisponible(
            f"No se pudo obtener la base de datos: {exc}"
        ) from exc


def obtener_paginacion(pagina: int = 1, tamano: int = 50) -> Paginacion:
    """Parámetros de consulta `?pagina=1&tamano=50` de todos los listados."""
    return Paginacion(pagina=pagina, tamano=tamano)


# Alias que hacen legible la firma de los endpoints
BaseDatos = Annotated[Database, Depends(obtener_base_datos)]
PaginacionQuery = Annotated[Paginacion, Depends(obtener_paginacion)]

# ==========================================================================
# AUTENTICACIÓN Y AUTORIZACIÓN  (RNP-11, opción b)
# ==========================================================================
# `tokenUrl` es la ruta donde la documentación interactiva pedirá las
# credenciales: al pulsar "Authorize" en /docs, Swagger llama a ese
# endpoint, guarda el token y lo adjunta en las peticiones siguientes.
esquema_oauth2 = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_PREFIJO}/auth/login",
    auto_error=False,          # el 401 lo emite el servicio, con su formato
)


def usuario_actual(bd: Database = Depends(obtener_base_datos),
                   token: str | None = Depends(esquema_oauth2)) -> dict:
    """
    Usuario autenticado que hace la petición.

    Un endpoint que la declare queda protegido:

        def listar(usuario: UsuarioAutenticado): ...

    Si no llega token, o es inválido o caducado, responde 401 antes de
    ejecutar nada del endpoint.
    """
    from backend.services import autenticacion
    from backend.utils.seguridad import CredencialesInvalidas

    if not token:
        raise CredencialesInvalidas(
            "Esta operación requiere iniciar sesión.")
    return autenticacion.usuario_desde_token(bd, token)


def requiere_rol(*roles: str):
    """
    Dependencia que además exige uno de los roles indicados:

        def crear(usuario: dict = Depends(requiere_rol("ADMINISTRADOR"))): ...

    Devuelve el usuario, de modo que el endpoint no necesita pedirlo dos
    veces. Los roles no autorizados reciben 403, no 401.
    """
    def verificar(usuario: dict = Depends(usuario_actual)) -> dict:
        from backend.services import autenticacion

        autenticacion.exigir_rol(usuario, roles)
        return usuario

    return verificar


# Alias legibles para las firmas de los endpoints
UsuarioAutenticado = Annotated[dict, Depends(usuario_actual)]
SoloAdministrador = Annotated[dict, Depends(requiere_rol(settings.ROL_ADMINISTRADOR))]
AdministradorODespachador = Annotated[
    dict, Depends(requiere_rol(settings.ROL_ADMINISTRADOR, settings.ROL_DESPACHADOR))]
