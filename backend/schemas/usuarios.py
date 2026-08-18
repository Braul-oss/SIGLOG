"""
SIG-LOG — Sistema Integral de Gestión Logística
backend/schemas/usuarios.py

ESQUEMAS DE GESTIÓN DE USUARIOS

Entradas de los endpoints de administración. La salida NO se define aquí:
se reutiliza `UsuarioSalida` de `schemas/autenticacion.py`, que ya es la
representación pública y no contempla el hash. Definir un segundo esquema
de salida sería justo la forma de que uno de los dos acabara filtrándolo.

Los esquemas de entrada están separados a propósito:

    UsuarioCrear       alta: exige contraseña y rol
    UsuarioActualizar  edición: todos los campos opcionales, y NI contraseña
                       NI rol, porque cada uno tiene su propio endpoint
    CambioRol          cambio de rol, con su regla de negocio
    RestablecerContrasena  el administrador asigna una nueva sin conocer
                       la anterior

Que la edición no acepte `rol` ni `contrasena` no es un olvido: son las dos
operaciones sensibles, y tenerlas en endpoints propios permite auditarlas y
protegerlas por separado en lugar de esconderlas dentro de un PUT genérico.
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

# Identificador de acceso: letras, dígitos, punto, guion y guion bajo.
# Se restringe para que el nombre no traiga espacios ni caracteres que
# después compliquen las URL o se confundan visualmente entre sí.
PATRON_USUARIO = re.compile(r"^[a-zA-Z0-9._-]+$")

DESCRIPCION_ROL = (
    f"Uno de {list(settings.CATALOGO_ROLES)}. "
    "ADMINISTRADOR gestiona catálogos, configuración y usuarios; "
    "DESPACHADOR registra la operación diaria; "
    "ANALISTA consulta dashboard, reportes y resultados de ML."
)


class _ValidadorUsuario(BaseModel):
    """Validación compartida del identificador de acceso."""

    @field_validator("usuario", check_fields=False)
    @classmethod
    def validar_usuario(cls, valor: str) -> str:
        valor = valor.strip()
        if not PATRON_USUARIO.match(valor):
            raise ValueError(
                "El usuario solo admite letras, dígitos, punto, guion y guion bajo.")
        return valor.lower()          # se normaliza: 'Admin' y 'admin' son el mismo


class UsuarioCrear(_ValidadorUsuario):
    """Alta de una cuenta."""

    usuario: str = Field(min_length=3, max_length=50,
                         description="Identificador de acceso, sin espacios.")
    contrasena: str = Field(min_length=8, max_length=72,
                            description="Contraseña inicial (mínimo 8 caracteres).")
    nombre_completo: str = Field(min_length=3, max_length=120)
    rol: str = Field(description=DESCRIPCION_ROL)
    correo: str | None = Field(default=None, max_length=120)

    @field_validator("rol")
    @classmethod
    def validar_rol(cls, valor: str) -> str:
        valor = valor.strip().upper()
        if valor not in settings.CATALOGO_ROLES:
            raise ValueError(
                f"Rol no válido. Debe ser uno de {list(settings.CATALOGO_ROLES)}.")
        return valor

    model_config = {
        "json_schema_extra": {
            "example": {
                "usuario": "jperez",
                "contrasena": "contrasena-segura",
                "nombre_completo": "Juana Pérez Ramírez",
                "rol": "DESPACHADOR",
                "correo": "jperez@ejemplo-simulado.mx",
            }
        }
    }


class UsuarioActualizar(BaseModel):
    """
    Edición de los datos descriptivos. No incluye `rol` ni `contrasena`:
    cada uno tiene su endpoint, con su propia regla de negocio.
    """

    nombre_completo: str | None = Field(default=None, min_length=3, max_length=120)
    correo: str | None = Field(default=None, max_length=120)

    def cambios(self) -> dict:
        """Solo los campos efectivamente enviados, para no borrar los demás."""
        return self.model_dump(exclude_unset=True, exclude_none=True)


class CambioRol(BaseModel):
    """Cambio del rol de una cuenta."""

    rol: str = Field(description=DESCRIPCION_ROL)

    @field_validator("rol")
    @classmethod
    def validar_rol(cls, valor: str) -> str:
        valor = valor.strip().upper()
        if valor not in settings.CATALOGO_ROLES:
            raise ValueError(
                f"Rol no válido. Debe ser uno de {list(settings.CATALOGO_ROLES)}.")
        return valor


class RestablecerContrasena(BaseModel):
    """
    Asignación de contraseña por un administrador.

    A diferencia del cambio de contraseña propia, no pide la anterior: el
    caso de uso es precisamente que el titular la olvidó. Por eso la
    operación está reservada al ADMINISTRADOR y queda registrada.
    """

    contrasena_nueva: str = Field(min_length=8, max_length=72)


class RolInfo(BaseModel):
    """Descripción de un rol, para que el frontend arme el selector."""

    rol: str
    descripcion: str
    actor: str
