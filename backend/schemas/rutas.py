"""
SIG-LOG — Sistema Integral de Gestión Logística
backend/schemas/rutas.py

ESQUEMAS DEL MÓDULO RUTAS  (§11.4)

Una ruta es el PLAN del recorrido, no su ejecución —eso son los viajes—.
Lleva sus paradas embebidas y en orden, porque solo tienen sentido dentro
de la ruta y siempre se leen con ella (§10.3).

Cuatro campos del §11.4 no se aceptan por el formulario porque son SUMAS
de las paradas y el sistema los recalcula solo:

    distancia_total_km          suma de las distancias entre paradas
    tiempo_estimado_total_min   suma de los tiempos
    numero_paradas              longitud del array
    velocidad_efectiva_kmh      distancia / tiempo

Aceptarlos permitiría que el total contradijera a sus partes, y esos
mismos totales son las variables centrales del clustering de rutas.
Tampoco se acepta `vehiculo_asignado_id`: tiene endpoint propio, porque
asignar un vehículo es aplicar RN-04.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from pydantic import BaseModel, Field, field_validator

from config import settings

PATRON_HORA = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


class Parada(BaseModel):
    """
    Punto de entrega dentro de la ruta.

    `orden` no se envía: lo asigna el sistema por la posición en la lista.
    Dejarlo a la captura permitiría huecos y repeticiones, y el orden es lo
    que define el recorrido y el efecto de acumulación del retraso.
    """

    cliente_id: str = Field(description="Cliente que se atiende en esta parada.")
    direccion_alias: str = Field(
        min_length=2, max_length=40,
        description="Alias de la dirección del cliente a la que se entrega. "
                    "Debe existir entre sus direcciones registradas.")
    distancia_desde_anterior_km: float = Field(
        gt=0, le=500,
        description="Kilómetros desde la parada anterior (o desde el origen, "
                    "si es la primera).")
    tiempo_estimado_min: float = Field(
        gt=0, le=600,
        description="Minutos estimados de traslado y entrega.")


class Origen(BaseModel):
    """Punto de partida de la ruta: el centro de distribución."""

    nombre: str = Field(min_length=3, max_length=120)
    calle: str = Field(min_length=3, max_length=120)
    numero: str = Field(min_length=1, max_length=20)
    colonia: str = Field(min_length=2, max_length=80)
    municipio: str = Field(min_length=2, max_length=80)
    estado: str = Field(default="México", max_length=60)
    cp: str = Field(pattern=r"^\d{5}$")


def _validar_zona(valor: str) -> str:
    valor = valor.strip().upper()
    if valor not in settings.CATALOGO_ZONA:
        raise ValueError(
            f"Zona no válida. Debe ser una de {list(settings.CATALOGO_ZONA)}.")
    return valor


def _validar_dias(valores: list[str]) -> list[str]:
    dias = [d.strip().upper() for d in valores]
    invalidos = [d for d in dias if d not in settings.CATALOGO_DIAS_OPERACION]
    if invalidos:
        raise ValueError(
            f"Días no válidos: {invalidos}. Deben venir de "
            f"{list(settings.CATALOGO_DIAS_OPERACION)}.")
    if len(set(dias)) != len(dias):
        raise ValueError("Hay días repetidos en `dias_operacion`.")
    # Se ordenan como la semana, no como llegaron: el listado se lee mejor
    # y el análisis por día no depende del orden de captura.
    return sorted(set(dias), key=settings.CATALOGO_DIAS_OPERACION.index)


def _validar_hora(valor: str) -> str:
    valor = valor.strip()
    if not PATRON_HORA.match(valor):
        raise ValueError("La hora debe tener el formato HH:MM (24 horas).")
    return valor


class RutaCrear(BaseModel):
    """Alta de una ruta. El `codigo_ruta` lo asigna el sistema."""

    nombre: str = Field(min_length=3, max_length=120)
    zona: str = Field(description=f"Una de {list(settings.CATALOGO_ZONA)}.")
    origen: Origen
    paradas: list[Parada] = Field(
        min_length=1, description="Al menos una parada, en el orden del recorrido.")
    dias_operacion: list[str] = Field(
        min_length=1,
        description=f"Días en que opera (RNP-06). De "
                    f"{list(settings.CATALOGO_DIAS_OPERACION)}.")
    hora_salida_programada: str = Field(
        description="Hora de salida en formato HH:MM. Es la base del "
                    "análisis de saturación horaria.")

    @field_validator("zona")
    @classmethod
    def validar_zona(cls, valor: str) -> str:
        return _validar_zona(valor)

    @field_validator("dias_operacion")
    @classmethod
    def validar_dias(cls, valores: list[str]) -> list[str]:
        return _validar_dias(valores)

    @field_validator("hora_salida_programada")
    @classmethod
    def validar_hora(cls, valor: str) -> str:
        return _validar_hora(valor)

    model_config = {
        "json_schema_extra": {
            "example": {
                "nombre": "Zona Norte 21",
                "zona": "NORTE",
                "origen": {"nombre": "Centro de Distribución SIG-LOG",
                           "calle": "Vialidad Adolfo López Mateos",
                           "numero": "1200", "colonia": "Parque Industrial",
                           "municipio": "Toluca", "estado": "México",
                           "cp": "50200"},
                "paradas": [{"cliente_id": "6a83893489a0d3691e054ed7",
                             "direccion_alias": "Matriz",
                             "distancia_desde_anterior_km": 6.1,
                             "tiempo_estimado_min": 25.7}],
                "dias_operacion": ["LUNES", "MIERCOLES", "VIERNES"],
                "hora_salida_programada": "06:30",
            }
        }
    }


class RutaActualizar(BaseModel):
    """
    Edición de la cabecera. Las paradas tienen sus propios endpoints,
    porque cambiarlas obliga a recalcular los totales y a revalidar los
    clientes.
    """

    nombre: str | None = Field(default=None, min_length=3, max_length=120)
    zona: str | None = None
    origen: Origen | None = None
    dias_operacion: list[str] | None = Field(default=None, min_length=1)
    hora_salida_programada: str | None = None

    @field_validator("zona")
    @classmethod
    def validar_zona(cls, valor: str) -> str:
        return _validar_zona(valor)

    @field_validator("dias_operacion")
    @classmethod
    def validar_dias(cls, valores: list[str]) -> list[str]:
        return _validar_dias(valores)

    @field_validator("hora_salida_programada")
    @classmethod
    def validar_hora(cls, valor: str) -> str:
        return _validar_hora(valor)

    def cambios(self) -> dict:
        datos = self.model_dump(exclude_unset=True, exclude_none=True)
        if "origen" in datos and hasattr(datos["origen"], "model_dump"):
            datos["origen"] = datos["origen"].model_dump()
        return datos


class ParadasReemplazar(BaseModel):
    """Sustitución completa del itinerario."""

    paradas: list[Parada] = Field(min_length=1)


class AsignacionVehiculo(BaseModel):
    """Asignación del vehículo de la ruta (§12.3, RN-04)."""

    vehiculo_id: str | None = Field(
        default=None,
        description="Identificador del vehículo, o null para desasignar.")


class RutaSalida(BaseModel):
    """Representación pública de una ruta."""

    id: str
    codigo_ruta: str
    nombre: str
    zona: str | None = None
    origen: dict | None = None
    paradas: list[dict] = Field(default_factory=list)
    numero_paradas: int = 0
    distancia_total_km: float = 0
    tiempo_estimado_total_min: float = 0
    velocidad_efectiva_kmh: float | None = None
    dias_operacion: list[str] = Field(default_factory=list)
    hora_salida_programada: str | None = None
    vehiculo_asignado_id: str | None = None
    activo: bool = True
    origen_dato: str | None = None

    @classmethod
    def desde_documento(cls, documento: dict) -> "RutaSalida":
        vehiculo = documento.get("vehiculo_asignado_id")
        paradas = [
            {**p, "cliente_id": str(p["cliente_id"])}
            for p in documento.get("paradas", [])
        ]
        return cls(
            id=str(documento["_id"]),
            codigo_ruta=documento.get("codigo_ruta", ""),
            nombre=documento.get("nombre", ""),
            zona=documento.get("zona"),
            origen=documento.get("origen"),
            paradas=paradas,
            numero_paradas=int(documento.get("numero_paradas") or len(paradas)),
            distancia_total_km=float(documento.get("distancia_total_km") or 0),
            tiempo_estimado_total_min=float(
                documento.get("tiempo_estimado_total_min") or 0),
            velocidad_efectiva_kmh=documento.get("velocidad_efectiva_kmh"),
            dias_operacion=documento.get("dias_operacion", []),
            hora_salida_programada=documento.get("hora_salida_programada"),
            vehiculo_asignado_id=str(vehiculo) if vehiculo else None,
            activo=documento.get("activo", True),
            origen_dato=documento.get("origen_dato"),
        )
