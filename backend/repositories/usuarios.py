"""
SIG-LOG — Sistema Integral de Gestión Logística
backend/repositories/usuarios.py

ACCESO A DATOS DE LA COLECCIÓN `usuarios`

Hereda de `RepositorioBase` y añade lo propio del control de acceso. Las
operaciones de administración de usuarios (alta, edición, cambio de rol)
llegarán en la actividad siguiente; aquí solo está lo que la autenticación
necesita: buscar por identificador de acceso, registrar la entrada y
cambiar la contraseña propia.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from pymongo.database import Database

from backend.repositories.base import RepositorioBase

COLECCION = "usuarios"


class RepositorioUsuarios(RepositorioBase):
    def __init__(self, bd: Database) -> None:
        super().__init__(bd, COLECCION, nombre_singular="el usuario")

    def por_nombre_de_usuario(self, usuario: str,
                              incluir_inactivos: bool = False) -> dict[str, Any] | None:
        """
        Busca por identificador de acceso. Devuelve `None` si no existe, en
        vez de lanzar 404: en un inicio de sesión, "el usuario no existe" no
        debe distinguirse de "la contraseña es incorrecta". Revelar cuál de
        las dos falló permite enumerar cuentas válidas.
        """
        filtro: dict[str, Any] = {"usuario": usuario}
        if not incluir_inactivos:
            filtro["activo"] = {"$ne": False}
        return self.coleccion.find_one(filtro)

    def registrar_acceso(self, identificador: Any) -> None:
        """Sella la fecha del último ingreso y reinicia los intentos fallidos."""
        self.coleccion.update_one(
            {"_id": identificador},
            {"$set": {"ultimo_acceso": datetime.now(timezone.utc),
                      "intentos_fallidos": 0}},
        )

    def contar_intento_fallido(self, identificador: Any) -> None:
        """
        Lleva la cuenta de intentos fallidos por cuenta.

        Hoy solo se registra —queda como evidencia de qué cuentas están
        siendo atacadas—; el bloqueo automático corresponde a la actividad
        de gestión de usuarios, donde habrá forma de desbloquear.
        """
        self.coleccion.update_one({"_id": identificador},
                                  {"$inc": {"intentos_fallidos": 1}})

    def actualizar_contrasena(self, identificador: Any, hash_nuevo: str) -> None:
        self.coleccion.update_one(
            {"_id": identificador},
            {"$set": {"hash_contrasena": hash_nuevo,
                      "fecha_modificacion": datetime.now(timezone.utc)}},
        )

    def hay_usuarios(self) -> bool:
        """¿Existe al menos una cuenta? Lo consulta el arranque de la API."""
        return self.coleccion.count_documents({}, limit=1) > 0
