"""
SIG-LOG — Sistema Integral de Gestión Logística
backend/schemas/incidentes.py

ESQUEMAS DEL MÓDULO INCIDENTES  (§11.7)

Un incidente es lo que explica los retrasos anómalos. Sin esta colección
—dice el §11.7— el modelo solo aprende la variación normal: sabe que la
hora pico retrasa, pero no por qué un martes concreto una ruta perdió
cuarenta minutos.

`duracion_min` no se captura: se calcula del inicio y el fin cuando el
incidente se cierra. Mientras sigue abierto se trabaja con
`tiempo_perdido_estimado_min`, que sí es una estimación de quien está en
la calle y por eso sí se pide.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from pydantic import BaseModel, Field, field_validator

from config import settings


def _catalogo(valor: str, catalogo: tuple[str, ...], nombre: str) -> str:
    valor = valor.strip().upper()
    if valor not in catalogo:
        raise ValueError(f"{nombre} no válido. Debe ser uno de {list(catalogo)}.")
    return valor


class IncidenteCrear(BaseModel):
    """Registro de un incidente ocurrido durante un viaje."""

    viaje_id: str = Field(description="Viaje en el que ocurre el incidente.")
    tipo: str = Field(
        description=f"Catálogo RNP-12: {list(settings.CATALOGO_TIPOS_INCIDENTE)}.")
    severidad: str = Field(
        description=f"Uno de {list(settings.CATALOGO_SEVERIDAD_INCIDENTE)}. "
                    "Junto con el tipo y la duración, es lo que permite a los "
                    "modelos explicar los retrasos anómalos.")
    fecha_hora_inicio: datetime | None = Field(
        default=None, description="Momento en que empezó; por omisión, ahora.")
    tiempo_perdido_estimado_min: float = Field(
        gt=0, le=1440,
        description="Minutos que se estima perder. Es la cifra con la que se "
                    "recalculan los ETA mientras el incidente sigue abierto.")
    descripcion: str | None = Field(
        default=None, max_length=300,
        description="Texto libre; dato NO estructurado (evidencia de U-II).")
    fuente: str = Field(
        default="MANUAL",
        description=f"Origen del registro: "
                    f"{list(settings.CATALOGO_FUENTE_INCIDENTE)}.")

    @field_validator("tipo")
    @classmethod
    def validar_tipo(cls, valor: str) -> str:
        return _catalogo(valor, settings.CATALOGO_TIPOS_INCIDENTE, "Tipo")

    @field_validator("severidad")
    @classmethod
    def validar_severidad(cls, valor: str) -> str:
        return _catalogo(valor, settings.CATALOGO_SEVERIDAD_INCIDENTE,
                         "Severidad")

    @field_validator("fuente")
    @classmethod
    def validar_fuente(cls, valor: str) -> str:
        return _catalogo(valor, settings.CATALOGO_FUENTE_INCIDENTE, "Fuente")

    model_config = {
        "json_schema_extra": {
            "example": {
                "viaje_id": "6a838e760f0c7319bce3ef6d",
                "tipo": "TRAFICO",
                "severidad": "MEDIA",
                "tiempo_perdido_estimado_min": 25,
                "descripcion": "Congestión en la vialidad principal",
            }
        }
    }


class CerrarIncidente(BaseModel):
    """Cierre del incidente: con el fin se calcula la duración real."""

    fecha_hora_fin: datetime | None = Field(
        default=None, description="Momento en que terminó; por omisión, ahora.")


class AfectarEntregas(BaseModel):
    """
    Asociación del incidente a las entregas y recálculo del ETA
    (§12.3, RF-33).

    Si no se envían entregas, se toman todas las del viaje que aún no se
    han entregado, que es el paso 2 del procedimiento del §17.3.
    """

    entregas_ids: list[str] | None = Field(
        default=None,
        description="Entregas concretas a afectar. Si se omite, se afectan "
                    "todas las pendientes del viaje.")
    minutos_perdidos: float | None = Field(
        default=None, gt=0, le=1440,
        description="Minutos a sumar al ETA. Si se omite, se usa la duración "
                    "real del incidente si ya cerró, o el tiempo estimado.")


class IncidenteSalida(BaseModel):
    """Representación pública de un incidente."""

    id: str
    folio_incidente: str
    viaje_id: str | None = None
    ruta_id: str | None = None
    tipo: str | None = None
    severidad: str | None = None
    fecha_hora_inicio: datetime | None = None
    fecha_hora_fin: datetime | None = None
    duracion_min: float | None = None
    tiempo_perdido_estimado_min: float | None = None
    entregas_afectadas: list[str] = Field(default_factory=list)
    descripcion: str | None = None
    fuente: str | None = None
    abierto: bool = True
    origen_dato: str | None = None

    @classmethod
    def desde_documento(cls, documento: dict) -> "IncidenteSalida":
        def texto(valor):
            return str(valor) if valor is not None else None

        return cls(
            id=str(documento["_id"]),
            folio_incidente=documento.get("folio_incidente", ""),
            viaje_id=texto(documento.get("viaje_id")),
            ruta_id=texto(documento.get("ruta_id")),
            tipo=documento.get("tipo"),
            severidad=documento.get("severidad"),
            fecha_hora_inicio=documento.get("fecha_hora_inicio"),
            fecha_hora_fin=documento.get("fecha_hora_fin"),
            duracion_min=documento.get("duracion_min"),
            tiempo_perdido_estimado_min=documento.get(
                "tiempo_perdido_estimado_min"),
            entregas_afectadas=[str(e) for e in
                                documento.get("entregas_afectadas", [])],
            descripcion=documento.get("descripcion"),
            fuente=documento.get("fuente"),
            abierto=documento.get("fecha_hora_fin") is None,
            origen_dato=documento.get("origen_dato"),
        )
