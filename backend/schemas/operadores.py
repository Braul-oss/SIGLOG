"""
SIG-LOG — Sistema Integral de Gestión Logística
backend/schemas/operadores.py

ESQUEMAS DEL MÓDULO OPERADORES  (§11.3)

Dos campos del §11.3 no se aceptan por el formulario:

    total_entregas                 lo cuenta la operación
    porcentaje_entregas_a_tiempo   lo calcula el ETL

Y uno más no aparece en ningún esquema: `vehiculo_asignado_id`. El §11.3
lo condiciona a que RNP-03 se resuelva como asignación fija, y se resolvió
como ROTACIÓN por jornada — que es lo que la simulación implementó y por
lo que el campo está nulo en los 24 operadores. La pareja
operador-vehículo se decide en cada viaje y ahí queda registrada; ofrecer
aquí una asignación fija contradiría el modelo.
"""

from __future__ import annotations

import re
import sys
from datetime import date, datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from pydantic import BaseModel, Field, field_validator

from config import settings

# Licencia federal: letras y dígitos, sin espacios (p. ej. LF7227905).
PATRON_LICENCIA = re.compile(r"^[A-Z0-9-]{5,20}$")


class Licencia(BaseModel):
    """Licencia de conducir del operador."""

    numero: str = Field(min_length=5, max_length=20,
                        description="Número del documento. Único por operador.")
    tipo: str = Field(
        description=f"Tipo federal: {list(settings.CATALOGO_TIPO_LICENCIA)}. "
                    "La simulación opera con B, C y E.")
    vigencia: date = Field(
        description="Fecha de caducidad. Un operador con la licencia "
                    "vencida no puede quedar ACTIVO (RN-O3).")

    @field_validator("numero")
    @classmethod
    def validar_numero(cls, valor: str) -> str:
        valor = valor.strip().upper().replace(" ", "")
        if not PATRON_LICENCIA.match(valor):
            raise ValueError(
                "El número de licencia solo admite letras, dígitos y guion.")
        return valor

    @field_validator("tipo")
    @classmethod
    def validar_tipo(cls, valor: str) -> str:
        valor = valor.strip().upper()
        if valor not in settings.CATALOGO_TIPO_LICENCIA:
            raise ValueError(
                f"Tipo de licencia no válido. Debe ser uno de "
                f"{list(settings.CATALOGO_TIPO_LICENCIA)}.")
        return valor


class OperadorCrear(BaseModel):
    """Alta de un operador. El `codigo_operador` lo asigna el sistema."""

    nombre_completo: str = Field(min_length=5, max_length=120)
    licencia: Licencia
    fecha_ingreso: date = Field(
        description="Permite derivar la antigüedad, que es una de las "
                    "variables de los modelos.")

    @field_validator("fecha_ingreso")
    @classmethod
    def validar_ingreso(cls, valor: date) -> date:
        if valor > date.today():
            raise ValueError("La fecha de ingreso no puede estar en el futuro.")
        return valor

    model_config = {
        "json_schema_extra": {
            "example": {
                "nombre_completo": "María Elena Ramírez Solís",
                "licencia": {"numero": "LF1234567", "tipo": "C",
                             "vigencia": "2028-06-30"},
                "fecha_ingreso": "2025-03-15",
            }
        }
    }


class OperadorActualizar(BaseModel):
    """
    Edición de la ficha. No incluye `estado` —tiene endpoint propio, porque
    activar a alguien exige comprobar su licencia (RN-O3)— ni los campos
    calculados.
    """

    nombre_completo: str | None = Field(default=None, min_length=5, max_length=120)
    licencia: Licencia | None = Field(
        default=None,
        description="Si se envía, reemplaza la licencia completa. Es la vía "
                    "para registrar una renovación.")
    fecha_ingreso: date | None = None

    _ingreso = field_validator("fecha_ingreso")(
        OperadorCrear.validar_ingreso.__func__)

    def cambios(self) -> dict:
        datos = self.model_dump(exclude_unset=True, exclude_none=True)
        if "licencia" in datos and hasattr(datos["licencia"], "model_dump"):
            datos["licencia"] = datos["licencia"].model_dump()
        return datos


class CambioEstadoOperador(BaseModel):
    """Cambio del estado del operador (ACTIVO / INACTIVO)."""

    estado: str = Field(
        description=f"Uno de {list(settings.CATALOGO_ESTADO_OPERADOR)}.")
    motivo: str | None = Field(default=None, max_length=200)

    @field_validator("estado")
    @classmethod
    def validar_estado(cls, valor: str) -> str:
        valor = valor.strip().upper()
        if valor not in settings.CATALOGO_ESTADO_OPERADOR:
            raise ValueError(
                f"Estado no válido. Debe ser uno de "
                f"{list(settings.CATALOGO_ESTADO_OPERADOR)}.")
        return valor


class OperadorSalida(BaseModel):
    """Representación pública de un operador."""

    id: str
    codigo_operador: str
    nombre_completo: str
    licencia: dict | None = None
    licencia_vigente: bool | None = Field(
        default=None,
        description="Calculado al vuelo comparando la vigencia con hoy.")
    dias_para_vencer_licencia: int | None = None
    fecha_ingreso: datetime | None = None
    antiguedad_meses: int | None = None
    estado: str | None = None
    total_entregas: int = 0
    porcentaje_entregas_a_tiempo: float | None = Field(
        default=None, description="Calculado por el ETL; null si no ha corrido.")
    activo: bool = True
    origen_dato: str | None = None

    @classmethod
    def desde_documento(cls, documento: dict) -> "OperadorSalida":
        from datetime import timezone

        licencia = documento.get("licencia") or {}
        vigencia = licencia.get("vigencia")
        dias = None
        vigente = None
        if vigencia is not None:
            if vigencia.tzinfo is None:
                vigencia = vigencia.replace(tzinfo=timezone.utc)
            dias = (vigencia - datetime.now(timezone.utc)).days
            vigente = dias >= 0

        ingreso = documento.get("fecha_ingreso")
        antiguedad = None
        if ingreso is not None:
            if ingreso.tzinfo is None:
                ingreso = ingreso.replace(tzinfo=timezone.utc)
            antiguedad = int((datetime.now(timezone.utc) - ingreso).days / 30.44)

        return cls(
            id=str(documento["_id"]),
            codigo_operador=documento.get("codigo_operador", ""),
            nombre_completo=documento.get("nombre_completo", ""),
            licencia=_licencia_publica(documento.get("licencia")),
            licencia_vigente=vigente,
            dias_para_vencer_licencia=dias,
            fecha_ingreso=documento.get("fecha_ingreso"),
            antiguedad_meses=antiguedad,
            estado=documento.get("estado"),
            total_entregas=int(documento.get("total_entregas") or 0),
            porcentaje_entregas_a_tiempo=documento.get(
                "porcentaje_entregas_a_tiempo"),
            activo=documento.get("activo", True),
            origen_dato=documento.get("origen_dato"),
        )


def _licencia_publica(licencia: dict | None) -> dict | None:
    """Serializa la fecha de vigencia para que salga como texto ISO."""
    if not licencia:
        return None
    salida = dict(licencia)
    if isinstance(salida.get("vigencia"), datetime):
        salida["vigencia"] = salida["vigencia"].isoformat()
    return salida
