"""
SIG-LOG — Sistema Integral de Gestión Logística
backend/services/sistema.py

CAPA 2 — REGLAS Y ORQUESTACIÓN (servicios del módulo Sistema)

Los servicios contienen la lógica; los routers solo traducen HTTP. Este,
el primero, atiende las consultas de estado que necesita cualquier
despliegue: ¿está viva la API?, ¿alcanza MongoDB?, ¿qué hay cargado?

La verificación de conexión NO se reimplementa: se delega en
`config.mongo_conexion.verificar_conexion`, que ya existe desde la primera
actividad y es la misma que usan las pruebas y los scripts del ETL. Un
segundo mecanismo de diagnóstico solo serviría para que ambos se
contradijeran.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from pymongo.database import Database
from pymongo.errors import PyMongoError

from backend.repositories.base import RepositorioBase
from backend.utils.errores import NoEncontrado, ServicioNoDisponible
from config import settings
from config.mongo_conexion import verificar_conexion


def estado_api() -> dict[str, Any]:
    """
    Estado del proceso, sin tocar la base de datos.

    Es lo que debe consultar un orquestador para saber si el servicio
    responde: si dependiera de MongoDB, una caída de la base marcaría la
    API como muerta cuando en realidad está viva y sabe reportar el fallo.
    """
    return {
        "aplicacion": settings.APP_NOMBRE,
        "version": settings.APP_VERSION,
        "entorno": settings.APP_ENTORNO,
        "estado": "OPERATIVO",
        "origen_datos": "SIMULADO",
    }


def estado_mongodb() -> dict[str, Any]:
    """
    Comprobación real contra MongoDB Atlas (ping + metadatos).

    Reutiliza `verificar_conexion`, que ya distingue los cuatro modos de
    fallo típicos: .env incompleto, DNS/cadena inválida, IP fuera de la
    lista de acceso de Atlas y credenciales rechazadas.
    """
    respuesta = verificar_conexion()
    if not respuesta["exito"]:
        raise ServicioNoDisponible(respuesta["mensaje"])
    return respuesta["datos"]


def inventario_colecciones(bd: Database) -> dict[str, Any]:
    """
    Conteo por colección, separando lo operativo de lo analítico.

    Es el endpoint que demuestra que la API consulta MongoDB de verdad, y
    de paso deja ver de un vistazo si el ETL ya corrió: si las colecciones
    analíticas están en cero, el DW aún no se ha cargado.
    """
    try:
        existentes = set(bd.list_collection_names())
        operativas = {
            nombre: bd[nombre].count_documents({})
            for nombre in settings.COLECCIONES_OPERATIVAS
            if nombre in existentes
        }
        analiticas = {
            nombre: bd[nombre].count_documents({})
            for nombre in settings.COLECCIONES_ANALITICAS
            if nombre in existentes
        }
    except PyMongoError as exc:
        raise ServicioNoDisponible(f"MongoDB no respondió: {exc}") from exc

    total_analiticas = sum(analiticas.values())
    return {
        "base_datos": bd.name,
        "operativas": operativas,
        "analiticas": analiticas,
        "total_operativas": sum(operativas.values()),
        "total_analiticas": total_analiticas,
        "total_documentos": sum(operativas.values()) + total_analiticas,
        "etl_ejecutado": analiticas.get("hecho_entrega", 0) > 0,
    }


def muestra_de_coleccion(bd: Database, coleccion: str,
                         limite: int = 5) -> list[dict[str, Any]]:
    """
    Primeros documentos de una colección, para verificar de extremo a
    extremo que el flujo Router → Service → Repository → MongoDB funciona
    y que la serialización de `ObjectId` y fechas es correcta.

    Solo admite colecciones del catálogo declarado en `settings`: evita que
    el parámetro de la URL se convierta en un acceso libre a la base.
    """
    if coleccion not in settings.TODAS_LAS_COLECCIONES:
        raise NoEncontrado("la colección", coleccion)

    repositorio = RepositorioBase(bd, coleccion)
    try:
        return repositorio.listar(limite=limite, incluir_inactivos=True)
    except PyMongoError as exc:
        raise ServicioNoDisponible(f"MongoDB no respondió: {exc}") from exc


def capacidades() -> dict[str, Any]:
    """
    Qué expone hoy la API y qué queda por construir.

    Sirve de contrato vivo para el frontend y de guía del avance del
    proyecto: cada actividad posterior enciende una de estas banderas.
    """
    return {
        "prefijo": settings.API_PREFIJO,
        "documentacion": "/docs",
        "modulos_disponibles": ["sistema", "autenticacion", "usuarios",
                                "clientes", "vehiculos", "operadores",
                                "rutas", "viajes", "entregas",
                                "incidentes", "combustible",
                                "mantenimientos"],
        "modulos_pendientes": ["analitica", "ml"],
        "seguridad": {
            "metodo": "JWT (HS256)",
            "roles": list(settings.CATALOGO_ROLES),
            "endpoints_publicos": ["/salud", "/salud/mongodb", "/info",
                                   "/auth/login", "/auth/estado"],
        },
        "capa_analitica": {
            "etl": "etl/run_etl.py",
            "kpis": "analytics/kpis.py",
            "graficas": "analytics/dashboard.py",
            "ml_supervisado": "ml/supervisado/",
            "ml_no_supervisado": "ml/no_supervisado/",
            "nota": ("La capa analítica ya está construida y opera por línea de "
                     "comandos. Los endpoints /analitica y /ml la expondrán "
                     "reutilizando esos módulos, sin duplicar su lógica."),
        },
    }
