"""
SIG-LOG — Sistema Integral de Gestión Logística
backend/schemas/mantenimientos.py

ESQUEMAS DEL MÓDULO MANTENIMIENTOS  (§11.9)

Dos campos del §11.9 no se capturan porque el sistema los deriva:

    duracion_dias                días fuera de operación, del programado
                                 al realizado
    proximo_mantenimiento_fecha  la fecha realizada más la periodicidad
                                 de RNP-04

Y `estatus` tampoco: tiene sus propios endpoints, porque realizar un
mantenimiento y darlo por vencido son actos distintos con efectos
distintos sobre el vehículo.
"""

from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from pydantic import BaseModel, Field, field_validator

from config import settings


class MantenimientoProgramar(BaseModel):
    """Programación de un servicio."""

    vehiculo_id: str = Field(description="Unidad a la que se le programa.")
    tipo: str = Field(
        description=f"Uno de {list(settings.CATALOGO_TIPO_MANTENIMIENTO)} "
                    "(RNP-05). PREVENTIVO es el servicio planificado; "
                    "CORRECTIVO, la reparación por falla.")
    fecha_programada: date = Field(description="Día en que se hará el servicio.")
    descripcion: str | None = Field(
        default=None, max_length=300,
        description="Texto libre; dato NO estructurado (evidencia de U-II).")
    costo_estimado: float | None = Field(
        default=None, ge=0, le=1_000_000,
        description="Costo previsto. El real se registra al realizarlo.")

    @field_validator("tipo")
    @classmethod
    def validar_tipo(cls, valor: str) -> str:
        valor = valor.strip().upper()
        if valor not in settings.CATALOGO_TIPO_MANTENIMIENTO:
            raise ValueError(
                f"Tipo no válido. Debe ser uno de "
                f"{list(settings.CATALOGO_TIPO_MANTENIMIENTO)}.")
        return valor

    model_config = {
        "json_schema_extra": {
            "example": {
                "vehiculo_id": "6a83893489a0d3691e054f47",
                "tipo": "PREVENTIVO",
                "fecha_programada": "2026-09-15",
                "descripcion": "Servicio de 10,000 km",
                "costo_estimado": 8500,
            }
        }
    }


class MantenimientoActualizar(BaseModel):
    """
    Edición mientras el servicio sigue PROGRAMADO. Un mantenimiento ya
    realizado no se edita: es el registro de lo que se hizo.
    """

    fecha_programada: date | None = None
    tipo: str | None = None
    descripcion: str | None = Field(default=None, max_length=300)
    costo_estimado: float | None = Field(default=None, ge=0, le=1_000_000)

    _tipo = field_validator("tipo")(
        MantenimientoProgramar.validar_tipo.__func__)

    def cambios(self) -> dict:
        return self.model_dump(exclude_unset=True, exclude_none=True)


class RealizarMantenimiento(BaseModel):
    """
    Registro del servicio efectuado.

    Es el acto que devuelve el vehículo a operación y el que actualiza sus
    fechas de mantenimiento.
    """

    fecha_realizada: date | None = Field(
        default=None, description="Día en que se hizo; por omisión, hoy.")
    odometro_km: float = Field(
        ge=0, le=2_000_000,
        description="Kilometraje al momento del servicio.")
    costo: float = Field(ge=0, le=1_000_000, description="Costo real.")
    duracion_dias: float | None = Field(
        default=None, ge=0, le=365,
        description="Días fuera de operación. Si se omite, se calcula de la "
                    "fecha programada a la realizada.")
    descripcion: str | None = Field(default=None, max_length=300)


class VencerMantenimiento(BaseModel):
    """Marcado de un servicio como vencido (RF-16)."""

    motivo: str | None = Field(default=None, max_length=200)


class MantenimientoSalida(BaseModel):
    """Representación pública de un mantenimiento."""

    id: str
    folio_mantenimiento: str
    vehiculo_id: str | None = None
    tipo: str | None = None
    estatus: str | None = None
    fecha_programada: datetime | None = None
    fecha_realizada: datetime | None = None
    proximo_mantenimiento_fecha: datetime | None = None
    odometro_km: float | None = None
    costo: float | None = None
    costo_estimado: float | None = None
    duracion_dias: float | None = None
    descripcion: str | None = None
    dias_de_atraso: int | None = Field(
        default=None,
        description="Días transcurridos desde la fecha programada si el "
                    "servicio sigue sin hacerse. Negativo si aún falta.")
    origen_dato: str | None = None

    @classmethod
    def desde_documento(cls, documento: dict) -> "MantenimientoSalida":
        from datetime import timezone

        programada = documento.get("fecha_programada")
        atraso = None
        if programada is not None and documento.get("fecha_realizada") is None:
            if programada.tzinfo is None:
                programada = programada.replace(tzinfo=timezone.utc)
            atraso = (datetime.now(timezone.utc) - programada).days

        return cls(
            id=str(documento["_id"]),
            folio_mantenimiento=documento.get("folio_mantenimiento", ""),
            vehiculo_id=(str(documento["vehiculo_id"])
                         if documento.get("vehiculo_id") else None),
            tipo=documento.get("tipo"),
            estatus=documento.get("estatus"),
            fecha_programada=documento.get("fecha_programada"),
            fecha_realizada=documento.get("fecha_realizada"),
            proximo_mantenimiento_fecha=documento.get(
                "proximo_mantenimiento_fecha"),
            odometro_km=documento.get("odometro_km"),
            costo=documento.get("costo"),
            costo_estimado=documento.get("costo_estimado"),
            duracion_dias=documento.get("duracion_dias"),
            descripcion=documento.get("descripcion"),
            dias_de_atraso=atraso,
            origen_dato=documento.get("origen_dato"),
        )
