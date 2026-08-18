"""
SIG-LOG — Sistema Integral de Gestión Logística
backend/schemas/entregas.py

ESQUEMAS DEL MÓDULO ENTREGAS  (§11.6)

`entregas` es, en palabras del propio documento técnico, **la colección
crítica del proyecto**: aporta la variable objetivo y la mayoría de los
predictores de los modelos.

Eso condiciona los esquemas más que en ningún otro módulo. Tres campos NO
se aceptan por ningún formulario:

    tiempo_real_min   se calcula al registrar la llegada
    retraso_min       real − estimado; variable objetivo de la REGRESIÓN
    es_retraso        umbral RNP-01; variable objetivo de la CLASIFICACIÓN

Si pudieran teclearse, los modelos aprenderían de un dato inventado en
lugar de uno observado, y todo el proyecto se apoya en que esa cifra sea
la que de verdad ocurrió.

Tampoco se aceptan los campos denormalizados —`nombre_cliente`, `placa`,
`nombre_operador`—: se copian al crear y no se tocan. Según §10.4 su
razón de ser es preservar el nombre HISTÓRICO, de modo que la entrega de
marzo conserve el nombre que el cliente tenía en marzo. Editarlos
destruiría justamente eso.
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


class EntregaCrear(BaseModel):
    """
    Alta de una entrega dentro de un viaje.

    Solo se envía a qué viaje pertenece y qué parada es: el cliente, el
    vehículo, el operador y la fecha se heredan del viaje y de su ruta
    (RN-E7). Pedirlos de nuevo permitiría que la entrega contradijera al
    viaje que la contiene.
    """

    viaje_id: str = Field(description="Viaje al que pertenece la entrega.")
    cliente_id: str = Field(description="Cliente al que se entrega.")
    orden_parada: int = Field(ge=1, le=50,
                              description="Posición dentro del recorrido.")
    tiempo_estimado_min: float = Field(
        gt=0, le=600, description="Tiempo estimado del plan de ruta.")
    distancia_km: float = Field(
        gt=0, le=500, description="Distancia desde la parada anterior.")
    hora_estimada_llegada: datetime | None = Field(
        default=None,
        description="ETA planificado. Si se omite se calcula acumulando los "
                    "tiempos desde la salida programada del viaje.")
    observaciones: str | None = Field(
        default=None, max_length=300,
        description="Texto libre. Es el dato NO estructurado que el proyecto "
                    "usa como evidencia de la Unidad II.")

    model_config = {
        "json_schema_extra": {
            "example": {
                "viaje_id": "6a838e760f0c7319bce3ef6d",
                "cliente_id": "6a83893489a0d3691e054ed7",
                "orden_parada": 1,
                "tiempo_estimado_min": 25.7,
                "distancia_km": 6.1,
            }
        }
    }


class GenerarEntregas(BaseModel):
    """
    Generación de todas las entregas de un viaje a partir de las paradas
    de su ruta.

    Es la operación normal: un viaje ejecuta una ruta, y la ruta ya sabe a
    qué clientes se va y en qué orden. Capturarlas una a una repetiría a
    mano lo que el plan ya dice.
    """

    viaje_id: str = Field(description="Viaje cuyas entregas se van a generar.")


class RegistrarLlegada(BaseModel):
    """
    Registro de la llegada real (§12.3: PATCH /entregas/{id}/llegada).

    Este es el momento en que nace la variable objetivo del proyecto: con
    la hora real se calculan `tiempo_real_min`, `retraso_min` y
    `es_retraso`. Por eso el formulario pide la hora y nada más.
    """

    hora_real_llegada: datetime | None = Field(
        default=None,
        description="Momento real de llegada. Si se omite, se toma el actual.")
    causa_retraso: str | None = Field(
        default=None,
        description=f"Solo si la entrega llegó retrasada. Catálogo RNP-12: "
                    f"{list(settings.CATALOGO_TIPOS_INCIDENTE)}.")
    observaciones: str | None = Field(default=None, max_length=300)
    entregada: bool = Field(
        default=True,
        description="False si se llegó pero no se pudo entregar "
                    "(cliente ausente, rechazo). Deja la entrega "
                    "NO_ENTREGADA.")

    @field_validator("causa_retraso")
    @classmethod
    def validar_causa(cls, valor: str | None) -> str | None:
        if valor is None:
            return None
        valor = valor.strip().upper()
        if valor not in settings.CATALOGO_TIPOS_INCIDENTE:
            raise ValueError(
                f"Causa no válida. Debe ser una de "
                f"{list(settings.CATALOGO_TIPOS_INCIDENTE)} (RNP-12).")
        return valor


class CambioEstatusEntrega(BaseModel):
    """Cambio de estatus con constancia en el historial (§12.3)."""

    estatus: str = Field(
        description=f"Uno de {list(settings.CATALOGO_ESTATUS_ENTREGA)} (RNP-08).")
    motivo: str | None = Field(default=None, max_length=200)

    @field_validator("estatus")
    @classmethod
    def validar_estatus(cls, valor: str) -> str:
        valor = valor.strip().upper()
        if valor not in settings.CATALOGO_ESTATUS_ENTREGA:
            raise ValueError(
                f"Estatus no válido. Debe ser uno de "
                f"{list(settings.CATALOGO_ESTATUS_ENTREGA)}.")
        return valor


class EntregaSalida(BaseModel):
    """Representación pública de una entrega."""

    id: str
    folio_entrega: str
    viaje_id: str | None = None
    ruta_id: str | None = None
    cliente_id: str | None = None
    nombre_cliente: str | None = None
    vehiculo_id: str | None = None
    placa: str | None = None
    operador_id: str | None = None
    nombre_operador: str | None = None
    orden_parada: int | None = None
    fecha: datetime | None = None
    hora_estimada_llegada: datetime | None = None
    hora_real_llegada: datetime | None = None
    hora_estimada_recalculada: datetime | None = None
    tiempo_estimado_min: float | None = None
    tiempo_real_min: float | None = None
    retraso_min: float | None = Field(
        default=None, description="Variable objetivo de la regresión.")
    es_retraso: int | None = Field(
        default=None, description="Variable objetivo de la clasificación.")
    distancia_km: float | None = None
    estatus: str | None = None
    historial_estatus: list[dict] = Field(default_factory=list)
    incidentes_ids: list[str] = Field(default_factory=list)
    causa_retraso: str | None = None
    observaciones: str | None = None
    origen_dato: str | None = None

    @classmethod
    def desde_documento(cls, documento: dict) -> "EntregaSalida":
        def texto(valor):
            return str(valor) if valor is not None else None

        historial = [
            {**h, "fecha_hora": (h["fecha_hora"].isoformat()
                                 if isinstance(h.get("fecha_hora"), datetime)
                                 else h.get("fecha_hora"))}
            for h in documento.get("historial_estatus", [])
        ]
        return cls(
            id=str(documento["_id"]),
            folio_entrega=documento.get("folio_entrega", ""),
            viaje_id=texto(documento.get("viaje_id")),
            ruta_id=texto(documento.get("ruta_id")),
            cliente_id=texto(documento.get("cliente_id")),
            nombre_cliente=documento.get("nombre_cliente"),
            vehiculo_id=texto(documento.get("vehiculo_id")),
            placa=documento.get("placa"),
            operador_id=texto(documento.get("operador_id")),
            nombre_operador=documento.get("nombre_operador"),
            orden_parada=documento.get("orden_parada"),
            fecha=documento.get("fecha"),
            hora_estimada_llegada=documento.get("hora_estimada_llegada"),
            hora_real_llegada=documento.get("hora_real_llegada"),
            hora_estimada_recalculada=documento.get("hora_estimada_recalculada"),
            tiempo_estimado_min=documento.get("tiempo_estimado_min"),
            tiempo_real_min=documento.get("tiempo_real_min"),
            retraso_min=documento.get("retraso_min"),
            es_retraso=documento.get("es_retraso"),
            distancia_km=documento.get("distancia_km"),
            estatus=documento.get("estatus"),
            historial_estatus=historial,
            incidentes_ids=[str(i) for i in documento.get("incidentes_ids", [])],
            causa_retraso=documento.get("causa_retraso"),
            observaciones=documento.get("observaciones"),
            origen_dato=documento.get("origen_dato"),
        )
