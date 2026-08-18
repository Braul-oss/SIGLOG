"""
SIG-LOG — Sistema Integral de Gestión Logística
backend/schemas/vehiculos.py

ESQUEMAS DEL MÓDULO VEHÍCULOS  (§11.2)

Tres campos del §11.2 NO se aceptan en el alta ni en la edición, y la razón
es la misma en los tres: no los captura una persona.

    odometro_actual_km     lo actualiza el cierre de cada viaje
    rendimiento_real_km_l  lo calcula el ETL a partir de `combustible`
    fecha_*_mantenimiento  se derivan de la colección `mantenimientos`

Aceptarlos por el formulario permitiría que un dato tecleado contradijera
al calculado, y entonces el dashboard y la operación dirían cosas
distintas sobre el mismo vehículo.

`estado_operativo` tampoco se edita por el PUT: tiene su propio endpoint
porque es una máquina de estados con transiciones válidas (RN-V5).
"""

from __future__ import annotations

import re
import sys
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from pydantic import BaseModel, Field, field_validator

from config import settings

# Placa mexicana de carga: 3 letras, guion y 3-4 dígitos (p. ej. VVR-797).
# Se admite con o sin guion y se normaliza al guardar.
PATRON_PLACA = re.compile(r"^[A-Z]{3}-?\d{3,4}$")

ANIO_MINIMO = 1990


def _validar_catalogo(valor: str, catalogo: tuple[str, ...], nombre: str) -> str:
    valor = valor.strip().upper()
    if valor not in catalogo:
        raise ValueError(f"{nombre} no válido. Debe ser uno de {list(catalogo)}.")
    return valor


class VehiculoCrear(BaseModel):
    """Alta de un vehículo. El `codigo_vehiculo` lo asigna el sistema."""

    placa: str = Field(min_length=6, max_length=10,
                       description="Placa única. Formato AAA-999 o AAA-9999.")
    marca: str = Field(min_length=2, max_length=60)
    modelo: str = Field(min_length=1, max_length=60)
    anio: int = Field(ge=ANIO_MINIMO, le=datetime.now().year + 1,
                      description="Año-modelo; de él se deriva la antigüedad "
                                  "que usan los modelos de ML.")
    tipo_vehiculo: str = Field(
        description=f"Uno de {list(settings.CATALOGO_TIPO_VEHICULO)} (supuesto S-03).")
    tipo_combustible: str = Field(
        default="DIESEL",
        description=f"Uno de {list(settings.CATALOGO_TIPO_COMBUSTIBLE)}.")
    capacidad_tanque_litros: float = Field(
        gt=0, le=1000,
        description="Necesaria para el análisis de consumo (§11.2).")
    rendimiento_nominal_km_l: float = Field(
        gt=0, le=50,
        description="Rendimiento de fábrica. Es la línea base contra la que "
                    "el ETL compara el rendimiento real.")
    odometro_actual_km: float = Field(
        default=0, ge=0,
        description="Kilometraje al darlo de alta. A partir de ahí lo "
                    "actualiza el cierre de cada viaje, no la captura.")

    @field_validator("placa")
    @classmethod
    def validar_placa(cls, valor: str) -> str:
        valor = valor.strip().upper().replace(" ", "")
        if not PATRON_PLACA.match(valor):
            raise ValueError(
                "La placa debe tener el formato AAA-999 o AAA-9999.")
        if "-" not in valor:                     # se normaliza con guion
            valor = f"{valor[:3]}-{valor[3:]}"
        return valor

    @field_validator("tipo_vehiculo")
    @classmethod
    def validar_tipo(cls, valor: str) -> str:
        return _validar_catalogo(valor, settings.CATALOGO_TIPO_VEHICULO,
                                 "Tipo de vehículo")

    @field_validator("tipo_combustible")
    @classmethod
    def validar_combustible(cls, valor: str) -> str:
        return _validar_catalogo(valor, settings.CATALOGO_TIPO_COMBUSTIBLE,
                                 "Tipo de combustible")

    model_config = {
        "json_schema_extra": {
            "example": {
                "placa": "XAB-1234",
                "marca": "Isuzu",
                "modelo": "ELF 400",
                "anio": 2023,
                "tipo_vehiculo": "MEDIANO",
                "tipo_combustible": "DIESEL",
                "capacidad_tanque_litros": 140,
                "rendimiento_nominal_km_l": 7.2,
                "odometro_actual_km": 15000,
            }
        }
    }


class VehiculoActualizar(BaseModel):
    """
    Edición de los datos de ficha.

    No incluye `estado_operativo` (tiene endpoint propio, RN-V5) ni los
    campos calculados. La placa sí se puede corregir: un error de captura
    o un reemplazo de placas son situaciones reales.
    """

    placa: str | None = Field(default=None, min_length=6, max_length=10)
    marca: str | None = Field(default=None, min_length=2, max_length=60)
    modelo: str | None = Field(default=None, min_length=1, max_length=60)
    anio: int | None = Field(default=None, ge=ANIO_MINIMO,
                             le=datetime.now().year + 1)
    tipo_vehiculo: str | None = None
    tipo_combustible: str | None = None
    capacidad_tanque_litros: float | None = Field(default=None, gt=0, le=1000)
    rendimiento_nominal_km_l: float | None = Field(default=None, gt=0, le=50)

    _placa = field_validator("placa")(VehiculoCrear.validar_placa.__func__)
    _tipo = field_validator("tipo_vehiculo")(VehiculoCrear.validar_tipo.__func__)
    _combustible = field_validator("tipo_combustible")(
        VehiculoCrear.validar_combustible.__func__)

    def cambios(self) -> dict:
        return self.model_dump(exclude_unset=True, exclude_none=True)


class CambioEstado(BaseModel):
    """Cambio del estado operativo (§12.3: PATCH /vehiculos/{id}/estado)."""

    estado_operativo: str = Field(
        description=(f"Destino. Transiciones válidas: "
                     f"{ {k: list(v) for k, v in settings.TRANSICIONES_ESTADO_VEHICULO.items()} }. "
                     "BAJA no es destino: se alcanza dando de baja el vehículo."))
    motivo: str | None = Field(default=None, max_length=200,
                               description="Nota opcional del cambio.")

    @field_validator("estado_operativo")
    @classmethod
    def validar_estado(cls, valor: str) -> str:
        return _validar_catalogo(valor, settings.CATALOGO_ESTADO_VEHICULO,
                                 "Estado operativo")


class AsignacionRuta(BaseModel):
    """Asignación de la ruta del vehículo (RN-04, relación 1:1)."""

    ruta_id: str | None = Field(
        default=None,
        description="Identificador de la ruta, o null para desasignar.")


class VehiculoSalida(BaseModel):
    """Representación pública de un vehículo."""

    id: str
    codigo_vehiculo: str
    placa: str
    marca: str | None = None
    modelo: str | None = None
    anio: int | None = None
    tipo_vehiculo: str | None = None
    tipo_combustible: str | None = None
    capacidad_tanque_litros: float | None = None
    rendimiento_nominal_km_l: float | None = None
    rendimiento_real_km_l: float | None = Field(
        default=None, description="Calculado por el ETL; null si aún no corrió.")
    odometro_actual_km: float | None = None
    estado_operativo: str | None = None
    ruta_asignada_id: str | None = None
    fecha_ultimo_mantenimiento: datetime | None = None
    fecha_proximo_mantenimiento: datetime | None = None
    activo: bool = True
    origen_dato: str | None = None

    @classmethod
    def desde_documento(cls, documento: dict) -> "VehiculoSalida":
        ruta = documento.get("ruta_asignada_id")
        return cls(
            id=str(documento["_id"]),
            codigo_vehiculo=documento.get("codigo_vehiculo", ""),
            placa=documento.get("placa", ""),
            marca=documento.get("marca"),
            modelo=documento.get("modelo"),
            anio=documento.get("anio"),
            tipo_vehiculo=documento.get("tipo_vehiculo"),
            tipo_combustible=documento.get("tipo_combustible"),
            capacidad_tanque_litros=documento.get("capacidad_tanque_litros"),
            rendimiento_nominal_km_l=documento.get("rendimiento_nominal_km_l"),
            rendimiento_real_km_l=documento.get("rendimiento_real_km_l"),
            odometro_actual_km=documento.get("odometro_actual_km"),
            estado_operativo=documento.get("estado_operativo"),
            ruta_asignada_id=str(ruta) if ruta else None,
            fecha_ultimo_mantenimiento=documento.get("fecha_ultimo_mantenimiento"),
            fecha_proximo_mantenimiento=documento.get("fecha_proximo_mantenimiento"),
            activo=documento.get("activo", True),
            origen_dato=documento.get("origen_dato"),
        )
