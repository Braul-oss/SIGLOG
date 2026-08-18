"""
SIG-LOG — Sistema Integral de Gestión Logística
backend/schemas/clientes.py

ESQUEMAS DEL MÓDULO CLIENTES  (§11.1)

Un cliente es un catálogo con direcciones EMBEBIDAS: el documento técnico
decidió embeberlas en lugar de hacer una colección aparte porque siempre se
leen junto al cliente y no se consultan por sí solas (§10.3).

`codigo_cliente` no aparece en el esquema de alta a propósito: lo genera el
sistema (RN-C1). Es la clave de negocio, tiene un formato fijo —CLI-001— y
dejar que la escriba quien captura invita a duplicados y a formatos que
después no ordenan bien.
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

PATRON_CP = re.compile(r"^\d{5}$")
PATRON_TELEFONO = re.compile(r"^[\d\s()+-]{7,20}$")

DESCRIPCION_TIPO = (
    f"Uno de {list(settings.CATALOGO_TIPO_CLIENTE)} (RNP-07). "
    "Es una variable categórica de los modelos, así que debe venir del "
    "catálogo y no como texto libre."
)


class Direccion(BaseModel):
    """
    Punto de entrega del cliente.

    `ubicacion` (GeoJSON) queda fuera: la decisión D-4 del proyecto es que
    no se usan coordenadas GPS, y por eso el índice 2dsphere del §11.1
    está desactivado. Añadir el campo aquí sugeriría una capacidad que el
    sistema no tiene.
    """

    alias: str = Field(min_length=2, max_length=40,
                       description="Nombre corto: Matriz, Sucursal Norte, Bodega...")
    calle: str = Field(min_length=3, max_length=120)
    numero: str = Field(min_length=1, max_length=20)
    colonia: str = Field(min_length=2, max_length=80)
    municipio: str = Field(min_length=2, max_length=80,
                           description="Variable categórica de los modelos.")
    estado: str = Field(default="México", min_length=2, max_length=60)
    cp: str = Field(description="Código postal de 5 dígitos.")
    referencias: str = Field(default="", max_length=200)
    principal: bool = Field(
        default=False,
        description="Dirección de entrega por omisión. Debe haber "
                    "exactamente una por cliente (RN-C2).")

    @field_validator("cp")
    @classmethod
    def validar_cp(cls, valor: str) -> str:
        valor = valor.strip()
        if not PATRON_CP.match(valor):
            raise ValueError("El código postal debe tener 5 dígitos.")
        return valor


class ClienteCrear(BaseModel):
    """Alta de un cliente. El `codigo_cliente` lo asigna el sistema."""

    nombre: str = Field(min_length=3, max_length=150)
    razon_social: str | None = Field(default=None, max_length=180)
    tipo_cliente: str = Field(description=DESCRIPCION_TIPO)
    telefono: str | None = Field(default=None)
    email: str | None = Field(default=None, max_length=120)
    direcciones: list[Direccion] = Field(
        min_length=1,
        description="Al menos una dirección; exactamente una principal (RN-C2).")

    @field_validator("tipo_cliente")
    @classmethod
    def validar_tipo(cls, valor: str) -> str:
        valor = valor.strip().upper()
        if valor not in settings.CATALOGO_TIPO_CLIENTE:
            raise ValueError(
                f"Tipo de cliente no válido. Debe ser uno de "
                f"{list(settings.CATALOGO_TIPO_CLIENTE)}.")
        return valor

    @field_validator("telefono")
    @classmethod
    def validar_telefono(cls, valor: str | None) -> str | None:
        if valor is None or not valor.strip():
            return None
        valor = valor.strip()
        if not PATRON_TELEFONO.match(valor):
            raise ValueError("El teléfono solo admite dígitos, espacios, +, - y ().")
        return valor

    model_config = {
        "json_schema_extra": {
            "example": {
                "nombre": "Comercializadora del Valle S.A. de C.V.",
                "tipo_cliente": "MAYORISTA",
                "telefono": "7223334455",
                "email": "contacto@ejemplo-simulado.mx",
                "direcciones": [{
                    "alias": "Matriz",
                    "calle": "Avenida Independencia",
                    "numero": "145",
                    "colonia": "Centro",
                    "municipio": "Toluca",
                    "estado": "México",
                    "cp": "50000",
                    "principal": True,
                }],
            }
        }
    }


class ClienteActualizar(BaseModel):
    """
    Edición. Todos los campos son opcionales: se aplica solo lo enviado.

    No incluye `codigo_cliente` (RN-C1: inmutable) ni `total_entregas`, que
    es un contador que mantienen la operación y el ETL, no la captura.
    """

    nombre: str | None = Field(default=None, min_length=3, max_length=150)
    razon_social: str | None = Field(default=None, max_length=180)
    tipo_cliente: str | None = Field(default=None, description=DESCRIPCION_TIPO)
    telefono: str | None = None
    email: str | None = Field(default=None, max_length=120)
    direcciones: list[Direccion] | None = Field(
        default=None,
        description="Si se envía, REEMPLAZA la lista completa de direcciones.")

    _validar_tipo = field_validator("tipo_cliente")(
        ClienteCrear.validar_tipo.__func__)
    _validar_telefono = field_validator("telefono")(
        ClienteCrear.validar_telefono.__func__)

    def cambios(self) -> dict:
        """Solo los campos enviados, para no borrar los demás."""
        datos = self.model_dump(exclude_unset=True, exclude_none=True)
        if "direcciones" in datos:
            datos["direcciones"] = [
                d.model_dump() if hasattr(d, "model_dump") else d
                for d in datos["direcciones"]
            ]
        return datos


class ClienteSalida(BaseModel):
    """Representación pública de un cliente."""

    id: str
    codigo_cliente: str
    nombre: str
    razon_social: str | None = None
    tipo_cliente: str | None = None
    telefono: str | None = None
    email: str | None = None
    direcciones: list[dict] = Field(default_factory=list)
    total_entregas: int = 0
    activo: bool = True
    origen_dato: str | None = None

    @classmethod
    def desde_documento(cls, documento: dict) -> "ClienteSalida":
        return cls(
            id=str(documento["_id"]),
            codigo_cliente=documento.get("codigo_cliente", ""),
            nombre=documento.get("nombre", ""),
            razon_social=documento.get("razon_social"),
            tipo_cliente=documento.get("tipo_cliente"),
            telefono=documento.get("telefono"),
            email=documento.get("email"),
            direcciones=documento.get("direcciones", []),
            total_entregas=int(documento.get("total_entregas") or 0),
            activo=documento.get("activo", True),
            origen_dato=documento.get("origen_dato"),
        )
