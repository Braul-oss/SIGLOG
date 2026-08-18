"""
SIG-LOG — Sistema Integral de Gestión Logística
backend/routers/sistema.py

CAPA 1 — ENDPOINTS DEL MÓDULO SISTEMA

El router traduce HTTP y nada más: recibe la petición, llama al servicio y
envuelve el resultado en la respuesta uniforme del §12.2. No consulta
MongoDB ni decide reglas; si un endpoint futuro empieza a hacerlo, es señal
de que esa lógica pertenece a un servicio.

Endpoints (§12.3, recurso "Sistema"):

    GET /salud                      ¿responde la API?            público
    GET /salud/mongodb              ¿alcanza MongoDB Atlas?      público
    GET /info                       versión y capacidades        público
    GET /diagnostico/colecciones    conteo por colección         autenticado
    GET /diagnostico/muestra/{col}  documentos de una colección  autenticado

Los de diagnóstico exigen sesión desde que existe la autenticación: uno
revela la forma de la base y el otro devuelve documentos reales. Los de
salud siguen abiertos a propósito, porque un monitor externo debe poder
comprobar que el servicio vive sin tener credenciales.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Path, Query, status

from backend.dependencias import BaseDatos, UsuarioAutenticado
from backend.schemas.comunes import Respuesta
from backend.services import sistema as servicio
from backend.utils import respuestas
from config import settings

router = APIRouter(tags=["Sistema"])


@router.get(
    "/salud",
    response_model=Respuesta[dict[str, Any]],
    summary="Verificar que la API responde",
    description=(
        "Comprobación de vida del proceso. No consulta MongoDB a propósito: "
        "así distingue 'la API está caída' de 'la base de datos no responde'."
    ),
)
def salud() -> dict[str, Any]:
    return respuestas.exito(
        datos=servicio.estado_api(),
        mensaje="La API de SIG-LOG está operativa.",
    )


@router.get(
    "/salud/mongodb",
    response_model=Respuesta[dict[str, Any]],
    summary="Verificar la conexión con MongoDB Atlas",
    description=(
        "Ejecuta un ping contra el cluster y devuelve versión del servidor, "
        "base de datos y colecciones existentes. Responde 503 si la base no "
        "está accesible, con el motivo concreto del fallo."
    ),
    responses={503: {"description": "MongoDB Atlas no está accesible."}},
)
def salud_mongodb() -> dict[str, Any]:
    datos = servicio.estado_mongodb()
    return respuestas.exito(
        datos=datos,
        mensaje=f"Conexión establecida con la base de datos '{datos['base_datos']}'.",
        total=datos.get("total_colecciones"),
    )


@router.get(
    "/info",
    response_model=Respuesta[dict[str, Any]],
    summary="Información y capacidades de la API",
    description="Versión, entorno, prefijo y qué módulos están disponibles.",
)
def info() -> dict[str, Any]:
    return respuestas.exito(
        datos={**servicio.estado_api(), "capacidades": servicio.capacidades()},
        mensaje=f"{settings.APP_NOMBRE} v{settings.APP_VERSION}",
    )


@router.get(
    "/diagnostico/colecciones",
    response_model=Respuesta[dict[str, Any]],
    summary="Conteo de documentos por colección",
    description=(
        "Recorre el catálogo de colecciones del diseño (§11) y cuenta sus "
        "documentos, separando las operativas de las analíticas. Es la "
        "prueba de que la API consulta MongoDB de extremo a extremo. "
        "**Requiere sesión iniciada**: revela la estructura de la base."
    ),
    responses={
        401: {"description": "Requiere sesión iniciada."},
        503: {"description": "MongoDB Atlas no está accesible."},
    },
)
def diagnostico_colecciones(bd: BaseDatos,
                            usuario: UsuarioAutenticado) -> dict[str, Any]:
    inventario = servicio.inventario_colecciones(bd)
    return respuestas.exito(
        datos=inventario,
        mensaje=(f"{inventario['total_documentos']:,} documentos en la base "
                 f"'{inventario['base_datos']}'."),
        total=inventario["total_documentos"],
    )


@router.get(
    "/diagnostico/muestra/{coleccion}",
    response_model=Respuesta[list[dict[str, Any]]],
    summary="Muestra de documentos de una colección",
    description=(
        "Devuelve los primeros documentos de una colección del catálogo. "
        "Verifica el flujo completo Router → Service → Repository → MongoDB "
        "y la serialización de ObjectId y fechas. "
        "**Requiere sesión iniciada**: devuelve documentos reales."
    ),
    responses={
        401: {"description": "Requiere sesión iniciada."},
        404: {"description": "La colección no pertenece al catálogo del diseño."},
        503: {"description": "MongoDB Atlas no está accesible."},
    },
)
def diagnostico_muestra(
    bd: BaseDatos,
    usuario: UsuarioAutenticado,
    coleccion: str = Path(description="Nombre de la colección (§11)."),
    limite: int = Query(default=5, ge=1, le=50,
                        description="Número de documentos a devolver."),
) -> dict[str, Any]:
    documentos = servicio.muestra_de_coleccion(bd, coleccion, limite)
    return respuestas.exito(
        datos=documentos,
        mensaje=f"{len(documentos)} documento(s) de la colección '{coleccion}'.",
    )
