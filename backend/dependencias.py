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
from pymongo.database import Database
from pymongo.errors import PyMongoError

from backend.schemas.comunes import Paginacion
from backend.utils.errores import ServicioNoDisponible
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

# --------------------------------------------------------------------------
# PUNTO DE EXTENSIÓN — AUTENTICACIÓN (actividad posterior)
# --------------------------------------------------------------------------
# Aquí se agregarán `usuario_actual()` y `requiere_rol(...)` cuando se
# implemente la seguridad. Los routers ya están escritos de forma que
# incorporarlas sea agregar un `Depends` a la firma, sin reestructurar
# nada. No se implementan todavía por indicación expresa del alcance.
