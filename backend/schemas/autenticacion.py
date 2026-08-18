"""
SIG-LOG — Sistema Integral de Gestión Logística
backend/schemas/autenticacion.py

ESQUEMAS DE AUTENTICACIÓN

Definen qué entra y qué sale de los endpoints de acceso. El detalle que
más importa está en `UsuarioSalida`: es la representación PÚBLICA de un
usuario y no incluye `hash_contrasena`. Que el esquema de salida ni
siquiera contemple el campo evita que un descuido futuro lo filtre en una
respuesta.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from pydantic import BaseModel, Field

from config import settings


class Credenciales(BaseModel):
    """Cuerpo del inicio de sesión en formato JSON."""

    usuario: str = Field(min_length=3, max_length=50,
                         description="Identificador de acceso.")
    contrasena: str = Field(min_length=1, max_length=128,
                            description="Contraseña en texto; viaja cifrada por HTTPS.")

    model_config = {
        "json_schema_extra": {
            "example": {"usuario": "admin", "contrasena": "siglog2026"}
        }
    }


class Token(BaseModel):
    """
    Token emitido tras un inicio de sesión correcto.

    `tipo` y el nombre `access_token` siguen el estándar OAuth2 para que la
    documentación interactiva de FastAPI pueda usarlo sin adaptaciones.
    """

    access_token: str = Field(description="Token JWT firmado.")
    token_type: str = Field(default="bearer", description="Esquema de autorización.")
    expira_en: datetime = Field(description="Momento en que el token deja de ser válido.")
    usuario: str
    rol: str


class UsuarioSalida(BaseModel):
    """
    Representación pública de un usuario. **Nunca** incluye el hash.
    """

    id: str = Field(description="Identificador del documento.")
    usuario: str
    nombre_completo: str
    rol: str = Field(description=f"Uno de {list(settings.CATALOGO_ROLES)}.")
    correo: str | None = None
    activo: bool = True
    ultimo_acceso: datetime | None = None

    @classmethod
    def desde_documento(cls, documento: dict) -> "UsuarioSalida":
        """Construye la salida a partir del documento de MongoDB."""
        return cls(
            id=str(documento["_id"]),
            usuario=documento["usuario"],
            nombre_completo=documento["nombre_completo"],
            rol=documento["rol"],
            correo=documento.get("correo"),
            activo=documento.get("activo", True),
            ultimo_acceso=documento.get("ultimo_acceso"),
        )


class CambioContrasena(BaseModel):
    """Cambio de la contraseña propia; exige conocer la actual."""

    contrasena_actual: str = Field(min_length=1, max_length=128)
    contrasena_nueva: str = Field(min_length=8, max_length=72)
