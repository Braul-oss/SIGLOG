"""
SIG-LOG — Sistema Integral de Gestión Logística
backend/utils/respuestas.py

CONSTRUCTORES DE LA RESPUESTA UNIFORME

Un par de funciones cortas para que ningún endpoint arme el diccionario de
respuesta a mano. Además de la uniformidad, resuelven un detalle que de
otro modo aparecería en cada módulo: MongoDB devuelve `ObjectId` y
`datetime`, que no son serializables a JSON tal cual.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from bson import ObjectId


def serializable(valor: Any) -> Any:
    """
    Convierte a tipos JSON lo que viene de MongoDB.

    `ObjectId` pasa a texto y las fechas a ISO-8601. Se recorre en
    profundidad porque los documentos del dominio llevan listas y objetos
    anidados (direcciones, paradas, historial de estatus).
    """
    if isinstance(valor, ObjectId):
        return str(valor)
    if isinstance(valor, datetime):
        # Siempre UTC y con sufijo Z. Es el formato que Pydantic emite en los
        # endpoints con modelo de respuesta tipado; sin esta normalización, el
        # mismo campo salía como "+00:00" desde los que devuelven un
        # diccionario libre, y un cliente que comparase marcas de tiempo como
        # texto vería diferencias donde no las hay.
        if valor.tzinfo is None:
            valor = valor.replace(tzinfo=timezone.utc)
        return valor.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(valor, date):
        return valor.isoformat()
    if isinstance(valor, dict):
        return {clave: serializable(v) for clave, v in valor.items()}
    if isinstance(valor, (list, tuple)):
        return [serializable(v) for v in valor]
    return valor


def exito(datos: Any = None, mensaje: str = "Operación realizada correctamente.",
          total: int | None = None) -> dict[str, Any]:
    """
    Respuesta de éxito con el formato del §12.2.

    Si `datos` es una lista y no se indica `total`, se cuenta sola: es el
    caso de todos los listados.
    """
    if total is None and isinstance(datos, list):
        total = len(datos)
    return {
        "exito": True,
        "mensaje": mensaje,
        "datos": serializable(datos),
        "total": total,
    }


def error(mensaje: str, codigo_error: str,
          detalles: list[Any] | None = None) -> dict[str, Any]:
    """Respuesta de error con el formato del §12.2."""
    return {
        "exito": False,
        "mensaje": mensaje,
        "codigo_error": codigo_error,
        "detalles": serializable(detalles or []),
    }
