"""
SIG-LOG — Sistema Integral de Gestión Logística
backend/schemas/combustible.py

ESQUEMAS DEL MÓDULO COMBUSTIBLE  (§11.8)

Cada carga es un hecho inmutable: se registra y no se edita. Por eso solo
hay esquema de alta — ni actualización ni baja.

Tres campos del §11.8 no se capturan porque el sistema los deriva:

    costo_total                        litros × precio_por_litro
    km_recorridos_desde_carga_anterior odómetro actual − el de la anterior
    rendimiento_km_l                   km entre cargas / litros

El `odometro_km` sí se pide, y es el dato crítico: el §11.8 lo marca como
"Crítico (RNP-10): sin él no hay km/l". Es la lectura que convierte una
factura de gasolinera en información de rendimiento.
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


class CargaCrear(BaseModel):
    """Registro de una carga de combustible."""

    vehiculo_id: str = Field(description="Unidad que se carga.")
    litros: float = Field(
        gt=0, le=1000,
        description="Litros cargados. No pueden superar la capacidad del "
                    "tanque de la unidad (RN-F6).")
    precio_por_litro: float = Field(
        gt=0, le=100, description="Precio unitario del combustible.")
    odometro_km: float = Field(
        ge=0, le=2_000_000,
        description="Lectura del odómetro al cargar. Es el dato crítico "
                    "(RNP-10): sin él no se puede calcular el rendimiento.")
    fecha: datetime | None = Field(
        default=None, description="Momento de la carga; por omisión, ahora.")
    viaje_id: str | None = Field(
        default=None,
        description="Viaje al que se atribuye la carga, si aplica (RNP-09).")
    tipo_combustible: str | None = Field(
        default=None,
        description=f"Uno de {list(settings.CATALOGO_TIPO_COMBUSTIBLE)}. Si se "
                    "omite, se toma el de la unidad. Debe coincidir con el "
                    "suyo (RN-F7).")
    estacion: str | None = Field(default=None, max_length=120)

    @field_validator("tipo_combustible")
    @classmethod
    def validar_tipo(cls, valor: str | None) -> str | None:
        if valor is None:
            return None
        valor = valor.strip().upper()
        if valor not in settings.CATALOGO_TIPO_COMBUSTIBLE:
            raise ValueError(
                f"Tipo de combustible no válido. Debe ser uno de "
                f"{list(settings.CATALOGO_TIPO_COMBUSTIBLE)}.")
        return valor

    model_config = {
        "json_schema_extra": {
            "example": {
                "vehiculo_id": "6a83893489a0d3691e054f47",
                "litros": 85.5,
                "precio_por_litro": 24.10,
                "odometro_km": 385_120.4,
                "estacion": "Estación Aeropuerto",
            }
        }
    }


class CargaSalida(BaseModel):
    """Representación pública de una carga."""

    id: str
    folio_carga: str
    vehiculo_id: str | None = None
    viaje_id: str | None = None
    fecha: datetime | None = None
    litros: float | None = None
    precio_por_litro: float | None = None
    costo_total: float | None = None
    odometro_km: float | None = None
    km_recorridos_desde_carga_anterior: float | None = None
    rendimiento_km_l: float | None = Field(
        default=None,
        description="km entre cargas / litros. Null en la primera carga de "
                    "una unidad: sin carga anterior no hay tramo que medir.")
    tipo_combustible: str | None = None
    estacion: str | None = None
    origen_dato: str | None = None

    @classmethod
    def desde_documento(cls, documento: dict) -> "CargaSalida":
        def texto(valor):
            return str(valor) if valor is not None else None

        return cls(
            id=str(documento["_id"]),
            folio_carga=documento.get("folio_carga", ""),
            vehiculo_id=texto(documento.get("vehiculo_id")),
            viaje_id=texto(documento.get("viaje_id")),
            fecha=documento.get("fecha"),
            litros=documento.get("litros"),
            precio_por_litro=documento.get("precio_por_litro"),
            costo_total=documento.get("costo_total"),
            odometro_km=documento.get("odometro_km"),
            km_recorridos_desde_carga_anterior=documento.get(
                "km_recorridos_desde_carga_anterior"),
            rendimiento_km_l=documento.get("rendimiento_km_l"),
            tipo_combustible=documento.get("tipo_combustible"),
            estacion=documento.get("estacion"),
            origen_dato=documento.get("origen_dato"),
        )
