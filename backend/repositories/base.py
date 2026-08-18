"""
SIG-LOG — Sistema Integral de Gestión Logística
backend/repositories/base.py

CAPA 3 — ACCESO A DATOS

Único lugar del backend que habla con PyMongo. Los servicios piden
documentos a un repositorio; nunca construyen un filtro de MongoDB ni
tocan una colección directamente. Esa frontera es la que permite que las
reglas de negocio se prueben sin base de datos y que un cambio de esquema
no se derrame por toda la API.

`RepositorioBase` trae las operaciones que todo módulo CRUD va a repetir
—listar con filtros y paginación, obtener por id, crear, actualizar y dar
de baja lógica—. Los repositorios concretos (clientes, vehículos…) se
crearán heredando de aquí en su propia actividad; hoy solo se usa la
lectura, en el endpoint de diagnóstico.

Baja lógica: el §12.3 define DELETE como "baja lógica". Por eso el
repositorio nunca borra: marca `activo: False`. Los datos de la operación
son la materia prima del ETL y del ML, y borrarlos rompería el histórico.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from bson.errors import InvalidId
from pymongo.collection import Collection
from pymongo.database import Database

from backend.utils.errores import DatosInvalidos, NoEncontrado


class RepositorioBase:
    """Operaciones comunes sobre una colección de MongoDB."""

    def __init__(self, bd: Database, coleccion: str,
                 nombre_singular: str | None = None) -> None:
        self.bd = bd
        self.nombre = coleccion
        self.nombre_singular = nombre_singular or coleccion.rstrip("s")

    @property
    def coleccion(self) -> Collection:
        return self.bd[self.nombre]

    # ----------------------------------------------------------------------
    # Utilidades
    # ----------------------------------------------------------------------
    def a_object_id(self, identificador: str) -> ObjectId:
        """Convierte el id de la URL a ObjectId, o falla con 400 y no con 500."""
        try:
            return ObjectId(identificador)
        except (InvalidId, TypeError) as exc:
            raise DatosInvalidos(
                f"El identificador '{identificador}' no tiene formato válido."
            ) from exc

    @staticmethod
    def _ahora() -> datetime:
        return datetime.now(timezone.utc)

    # ----------------------------------------------------------------------
    # Lectura
    # ----------------------------------------------------------------------
    def contar(self, filtro: dict[str, Any] | None = None,
               incluir_inactivos: bool = False) -> int:
        return self.coleccion.count_documents(
            self._con_activo(filtro, incluir_inactivos))

    def listar(self, filtro: dict[str, Any] | None = None, *,
               saltar: int = 0, limite: int = 50,
               orden: list[tuple[str, int]] | None = None,
               incluir_inactivos: bool = False) -> list[dict[str, Any]]:
        cursor = self.coleccion.find(self._con_activo(filtro, incluir_inactivos))
        if orden:
            cursor = cursor.sort(orden)
        return list(cursor.skip(saltar).limit(limite))

    def obtener(self, identificador: str,
                incluir_inactivos: bool = False) -> dict[str, Any]:
        """Devuelve el documento o lanza `NoEncontrado` (404)."""
        filtro = self._con_activo({"_id": self.a_object_id(identificador)},
                                  incluir_inactivos)
        documento = self.coleccion.find_one(filtro)
        if documento is None:
            raise NoEncontrado(self.nombre_singular, identificador)
        return documento

    def existe(self, filtro: dict[str, Any]) -> bool:
        return self.coleccion.count_documents(filtro, limit=1) > 0

    # ----------------------------------------------------------------------
    # Escritura  (la usarán los módulos CRUD; aquí queda lista y probada)
    # ----------------------------------------------------------------------
    def crear(self, documento: dict[str, Any]) -> dict[str, Any]:
        """
        Inserta agregando los campos comunes del modelo de datos.

        `origen_dato` se marca REAL porque lo captura el sistema web: es la
        distinción que el proyecto sostiene desde el seed frente a los
        documentos SIMULADOS.
        """
        ahora = self._ahora()
        nuevo = {
            **documento,
            "origen_dato": documento.get("origen_dato", "REAL"),
            "activo": True,
            "fecha_creacion": ahora,
            "fecha_modificacion": ahora,
        }
        resultado = self.coleccion.insert_one(nuevo)
        nuevo["_id"] = resultado.inserted_id
        return nuevo

    def actualizar(self, identificador: str, cambios: dict[str, Any],
                   incluir_inactivos: bool = False) -> dict[str, Any]:
        """
        Aplica los cambios y devuelve el documento ya actualizado.

        `incluir_inactivos` es necesario en dos casos que de otro modo
        fallarían con un 404 desconcertante: al dar de baja (tras escribir
        `activo: False`, la relectura ya no encontraría el documento) y al
        reactivar (el documento parte de estar inactivo).
        """
        self.obtener(identificador, incluir_inactivos)   # valida existencia → 404
        self.coleccion.update_one(
            {"_id": self.a_object_id(identificador)},
            {"$set": {**cambios, "fecha_modificacion": self._ahora()}},
        )
        return self.obtener(identificador, incluir_inactivos=True)

    def baja_logica(self, identificador: str) -> dict[str, Any]:
        """DELETE del §12.3: marca inactivo, nunca elimina el documento."""
        return self.actualizar(identificador, {"activo": False},
                               incluir_inactivos=True)

    # ----------------------------------------------------------------------
    # Interno
    # ----------------------------------------------------------------------
    @staticmethod
    def _con_activo(filtro: dict[str, Any] | None,
                    incluir_inactivos: bool) -> dict[str, Any]:
        """
        Añade `activo: True` salvo que se pidan también los dados de baja.

        Los documentos del seed no siempre traen el campo, así que el
        filtro acepta su ausencia en lugar de esconderlos.
        """
        base = dict(filtro or {})
        if not incluir_inactivos and "activo" not in base:
            base["activo"] = {"$ne": False}
        return base
