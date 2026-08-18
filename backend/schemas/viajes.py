"""
SIG-LOG — Sistema Integral de Gestión Logística
backend/schemas/viajes.py

ESQUEMAS DEL MÓDULO VIAJES  (§11.5)

Un viaje es la EJECUCIÓN de una ruta en una fecha, por un vehículo y un
operador. La ruta es el plan; el viaje, lo que de verdad pasó.

Los esquemas están partidos por momento de la operación, no por entidad, y
eso es deliberado: programar, salir y regresar son tres actos distintos,
separados en el tiempo, y cada uno captura lo suyo.

    ViajeProgramar   qué ruta, qué vehículo, qué operador y qué día
    IniciarViaje     la salida real y el odómetro con el que arranca
    FinalizarViaje   el regreso y el odómetro con el que vuelve

Ocho campos del §11.5 no aparecen en ningún esquema de entrada porque el
sistema los calcula: `km_recorridos`, `duracion_real_min`,
`retraso_salida_min`, los tres contadores y el folio. Capturarlos
permitiría que el resumen del viaje contradijera a sus propias horas y
odómetros — y `retraso_salida_min` es, según el propio §11.5, el
predictor más fuerte del retraso de las entregas del día.
"""

from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from pydantic import BaseModel, Field

from config import settings


class ViajeProgramar(BaseModel):
    """
    Alta de la jornada (§12.3: "listar / iniciar jornada").

    La hora de salida programada no se envía: se toma del plan de la ruta,
    que es donde vive. Duplicarla aquí permitiría programar un viaje que
    contradijera a su propia ruta.
    """

    ruta_id: str = Field(description="Ruta que se va a ejecutar.")
    vehiculo_id: str = Field(description="Unidad asignada a esta jornada.")
    operador_id: str = Field(description="Operador que la conduce.")
    fecha: date = Field(description="Día de operación.")

    model_config = {
        "json_schema_extra": {
            "example": {
                "ruta_id": "6a83893489a0d3691e054f67",
                "vehiculo_id": "6a83893489a0d3691e054f47",
                "operador_id": "6a83893489a0d3691e054f5a",
                "fecha": "2026-08-19",
            }
        }
    }


class IniciarViaje(BaseModel):
    """Registro de la salida real (§12.3: PATCH /viajes/{id}/iniciar)."""

    hora_salida_real: datetime | None = Field(
        default=None,
        description="Momento real de salida. Si se omite, se toma el actual, "
                    "que es el caso normal cuando se captura al salir.")
    odometro_inicial_km: float = Field(
        ge=0, le=2_000_000,
        description="Kilometraje con el que arranca la unidad.")


class FinalizarViaje(BaseModel):
    """Registro del regreso (§12.3: PATCH /viajes/{id}/finalizar)."""

    hora_regreso_real: datetime | None = Field(
        default=None, description="Momento real de regreso; por omisión, ahora.")
    odometro_final_km: float = Field(
        ge=0, le=2_000_000,
        description="Kilometraje de regreso. Debe ser mayor que el inicial.")
    total_entregas_completadas: int | None = Field(
        default=None, ge=0,
        description="Entregas efectivamente realizadas. Si se omite, se "
                    "cuenta de las entregas registradas del viaje.")


class CancelarViaje(BaseModel):
    """Cancelación del viaje, con su motivo."""

    motivo: str = Field(
        min_length=5, max_length=200,
        description="Por qué no se ejecuta. Queda en el histórico: un viaje "
                    "cancelado sin explicación no se puede analizar después.")


class ViajeSalida(BaseModel):
    """Representación pública de un viaje."""

    id: str
    folio_viaje: str
    fecha: datetime | None = None
    ruta_id: str | None = None
    vehiculo_id: str | None = None
    operador_id: str | None = None
    estatus: str | None = None
    hora_salida_programada: datetime | None = None
    hora_salida_real: datetime | None = None
    hora_regreso_real: datetime | None = None
    odometro_inicial_km: float | None = None
    odometro_final_km: float | None = None
    km_recorridos: float | None = None
    duracion_real_min: float | None = None
    retraso_salida_min: float | None = None
    total_entregas_programadas: int | None = None
    total_entregas_completadas: int | None = None
    total_incidentes: int | None = None
    motivo_cancelacion: str | None = None
    origen_dato: str | None = None

    @classmethod
    def desde_documento(cls, documento: dict) -> "ViajeSalida":
        def texto(valor):
            return str(valor) if valor is not None else None

        return cls(
            id=str(documento["_id"]),
            folio_viaje=documento.get("folio_viaje", ""),
            fecha=documento.get("fecha"),
            ruta_id=texto(documento.get("ruta_id")),
            vehiculo_id=texto(documento.get("vehiculo_id")),
            operador_id=texto(documento.get("operador_id")),
            estatus=documento.get("estatus"),
            hora_salida_programada=documento.get("hora_salida_programada"),
            hora_salida_real=documento.get("hora_salida_real"),
            hora_regreso_real=documento.get("hora_regreso_real"),
            odometro_inicial_km=documento.get("odometro_inicial_km"),
            odometro_final_km=documento.get("odometro_final_km"),
            km_recorridos=documento.get("km_recorridos"),
            duracion_real_min=documento.get("duracion_real_min"),
            retraso_salida_min=documento.get("retraso_salida_min"),
            total_entregas_programadas=documento.get("total_entregas_programadas"),
            total_entregas_completadas=documento.get("total_entregas_completadas"),
            total_incidentes=documento.get("total_incidentes"),
            motivo_cancelacion=documento.get("motivo_cancelacion"),
            origen_dato=documento.get("origen_dato"),
        )


DESCRIPCION_ESTATUS = (
    f"Uno de {list(settings.CATALOGO_ESTATUS_VIAJE)}. "
    "El viaje avanza y nunca retrocede: de FINALIZADO y CANCELADO no sale "
    "ninguna transición."
)
