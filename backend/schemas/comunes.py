"""
SIG-LOG — Sistema Integral de Gestión Logística
backend/schemas/comunes.py

ESQUEMAS COMPARTIDOS POR TODA LA API

Define el CONTRATO DE RESPUESTA del §12.2 del documento técnico:

    éxito:  { "exito": true,  "mensaje": "...", "datos": {...}, "total": 0 }
    error:  { "exito": false, "mensaje": "...", "codigo_error": "...",
              "detalles": [...] }

Que el contrato viva en un esquema de Pydantic y no en diccionarios sueltos
tiene dos consecuencias prácticas: FastAPI documenta la forma exacta de cada
respuesta en OpenAPI (entregable del §12.1), y ningún endpoint futuro puede
inventarse un formato distinto sin que se note.

`Respuesta` es genérica: `Respuesta[ClienteSalida]` documenta que `datos`
contiene un cliente, sin repetir la envoltura en cada módulo.
"""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class Respuesta(BaseModel, Generic[T]):
    """Respuesta uniforme de éxito (§12.2)."""

    exito: bool = Field(default=True, description="Siempre true en respuestas correctas.")
    mensaje: str = Field(description="Descripción legible del resultado.")
    datos: T | None = Field(default=None, description="Carga útil de la respuesta.")
    total: int | None = Field(
        default=None,
        description="Número de elementos cuando `datos` es una colección.",
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "exito": True,
                "mensaje": "Operación realizada correctamente.",
                "datos": {},
                "total": 0,
            }
        }
    }


class RespuestaError(BaseModel):
    """Respuesta uniforme de error (§12.2)."""

    exito: bool = Field(default=False)
    mensaje: str = Field(description="Qué salió mal, en lenguaje entendible.")
    codigo_error: str = Field(description="Identificador estable del tipo de error.")
    detalles: list[Any] = Field(
        default_factory=list,
        description="Detalle por campo cuando el error es de validación.",
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "exito": False,
                "mensaje": "Los datos enviados no son válidos.",
                "codigo_error": "ESQUEMA_INVALIDO",
                "detalles": [{"campo": "placa", "problema": "campo requerido"}],
            }
        }
    }


class Paginacion(BaseModel):
    """
    Parámetros de paginación de los listados (§12.3: "listar con filtros y
    paginación"). Se declara aquí desde ahora para que todos los módulos
    CRUD que vengan después paginen igual.
    """

    pagina: int = Field(default=1, ge=1, description="Página solicitada (base 1).")
    tamano: int = Field(default=50, ge=1, le=500,
                        description="Elementos por página (máximo 500).")

    @property
    def saltar(self) -> int:
        """Documentos a omitir; se pasa tal cual a `skip` de MongoDB."""
        return (self.pagina - 1) * self.tamano
