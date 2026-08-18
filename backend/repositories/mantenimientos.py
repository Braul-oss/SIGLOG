"""
SIG-LOG — Sistema Integral de Gestión Logística
backend/repositories/mantenimientos.py

ACCESO A DATOS DE LA COLECCIÓN `mantenimientos`  (§11.9)

Añade al CRUD genérico el folio fechado, las consultas de RF-16 —qué
vehículos requieren atención— y la escritura de las fechas de
mantenimiento en el vehículo.

Esa escritura cierra la última promesa pendiente del módulo de vehículos:
RN-V6 prohibió capturar `fecha_ultimo_mantenimiento` y
`fecha_proximo_mantenimiento` desde la ficha porque "se derivan de la
colección `mantenimientos`". Aquí es donde se derivan.
"""

from __future__ import annotations

import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from bson import ObjectId
from pymongo.database import Database

from backend.repositories.base import RepositorioBase
from config import settings

COLECCION = "mantenimientos"
PREFIJO_FOLIO = "MTO"


class RepositorioMantenimientos(RepositorioBase):
    def __init__(self, bd: Database) -> None:
        super().__init__(bd, COLECCION, nombre_singular="el mantenimiento")

    # ----------------------------------------------------------------------
    # Folio
    # ----------------------------------------------------------------------
    def siguiente_folio(self, fecha: datetime) -> str:
        """Folio MTO-AAAAMMDD-NNNN, consecutivo dentro del día."""
        prefijo = f"{PREFIJO_FOLIO}-{fecha:%Y%m%d}"
        ultimo = self.coleccion.find_one(
            {"folio_mantenimiento": {"$regex": f"^{prefijo}"}},
            {"folio_mantenimiento": 1},
            sort=[("folio_mantenimiento", -1)],
        )
        siguiente = 1
        if ultimo:
            coincidencia = re.search(r"(\d+)$", ultimo["folio_mantenimiento"])
            if coincidencia:
                siguiente = int(coincidencia.group(1)) + 1
        return f"{prefijo}-{siguiente:04d}"

    # ----------------------------------------------------------------------
    # Consultas del módulo
    # ----------------------------------------------------------------------
    def abierto_del_vehiculo(self, vehiculo_id: ObjectId,
                             excluir: ObjectId | None = None
                             ) -> dict[str, Any] | None:
        """Servicio sin realizar de esa unidad, si lo hay."""
        filtro: dict[str, Any] = {
            "vehiculo_id": vehiculo_id,
            "estatus": {"$ne": settings.ESTATUS_MTTO_REALIZADO},
        }
        if excluir is not None:
            filtro["_id"] = {"$ne": excluir}
        return self.coleccion.find_one(
            filtro, {"folio_mantenimiento": 1, "estatus": 1,
                     "fecha_programada": 1})

    def vencidos_del_vehiculo(self, vehiculo_id: ObjectId,
                              excluir: ObjectId | None = None) -> int:
        """
        Cuántos servicios vencidos le quedan a la unidad.

        Es lo que decide si al realizar uno el vehículo vuelve a operación
        o sigue fuera por otro pendiente (RF-16).
        """
        filtro: dict[str, Any] = {
            "vehiculo_id": vehiculo_id,
            "estatus": settings.ESTATUS_MTTO_VENCIDO,
        }
        if excluir is not None:
            filtro["_id"] = {"$ne": excluir}
        return self.coleccion.count_documents(filtro)

    def ultimo_realizado(self, vehiculo_id: ObjectId) -> dict[str, Any] | None:
        return self.coleccion.find_one(
            {"vehiculo_id": vehiculo_id,
             "estatus": settings.ESTATUS_MTTO_REALIZADO},
            {"fecha_realizada": 1, "proximo_mantenimiento_fecha": 1},
            sort=[("fecha_realizada", -1)],
        )

    def pendientes(self, dias_aviso: int) -> dict[str, list[dict[str, Any]]]:
        """
        RF-16: servicios vencidos y próximos a vencer, con su vehículo.

        Se resuelve con una agregación y un `$lookup` en lugar de consultar
        el vehículo uno por uno: el listado es para una pantalla de alertas
        y debe responder de una sola vez.
        """
        ahora = _ahora()
        limite = ahora + timedelta(days=dias_aviso)

        def consultar(filtro: dict[str, Any]) -> list[dict[str, Any]]:
            return list(self.coleccion.aggregate([
                {"$match": filtro},
                {"$sort": {"fecha_programada": 1}},
                {"$lookup": {"from": "vehiculos", "localField": "vehiculo_id",
                             "foreignField": "_id", "as": "vehiculo"}},
                {"$unwind": "$vehiculo"},
                {"$project": {
                    "_id": 0,
                    "id": {"$toString": "$_id"},
                    "folio_mantenimiento": 1, "tipo": 1, "estatus": 1,
                    "fecha_programada": 1,
                    "vehiculo_id": {"$toString": "$vehiculo_id"},
                    "codigo_vehiculo": "$vehiculo.codigo_vehiculo",
                    "placa": "$vehiculo.placa",
                    "estado_operativo": "$vehiculo.estado_operativo",
                    "dias": {"$dateDiff": {"startDate": "$fecha_programada",
                                           "endDate": ahora, "unit": "day"}},
                }},
            ]))

        return {
            "vencidos": consultar({"estatus": settings.ESTATUS_MTTO_VENCIDO}),
            "atrasados": consultar({
                "estatus": settings.ESTATUS_MTTO_PROGRAMADO,
                "fecha_programada": {"$lt": ahora}}),
            "proximos": consultar({
                "estatus": settings.ESTATUS_MTTO_PROGRAMADO,
                "fecha_programada": {"$gte": ahora, "$lte": limite}}),
        }

    def costo_por_vehiculo(self, limite: int = 10) -> list[dict[str, Any]]:
        return list(self.coleccion.aggregate([
            {"$match": {"estatus": settings.ESTATUS_MTTO_REALIZADO}},
            {"$group": {"_id": "$vehiculo_id", "servicios": {"$sum": 1},
                        "costo": {"$sum": "$costo"},
                        "dias_fuera": {"$sum": "$duracion_dias"}}},
            {"$sort": {"costo": -1}},
            {"$limit": limite},
            {"$lookup": {"from": "vehiculos", "localField": "_id",
                         "foreignField": "_id", "as": "vehiculo"}},
            {"$unwind": "$vehiculo"},
            {"$project": {
                "_id": 0,
                "vehiculo_id": {"$toString": "$_id"},
                "codigo_vehiculo": "$vehiculo.codigo_vehiculo",
                "servicios": 1, "costo": {"$round": ["$costo", 2]},
                "dias_fuera": 1,
            }},
        ]))

    # ----------------------------------------------------------------------
    # Efecto sobre el vehículo
    # ----------------------------------------------------------------------
    def vehiculo(self, vehiculo_id: ObjectId) -> dict[str, Any] | None:
        return self.bd["vehiculos"].find_one({"_id": vehiculo_id})

    def actualizar_vehiculo(self, vehiculo_id: ObjectId,
                            cambios: dict[str, Any]) -> None:
        """
        Escribe en el vehículo lo que este módulo deriva: sus fechas de
        mantenimiento y, cuando corresponde, su estado operativo.

        Es la contraparte de RN-V6, que prohíbe capturar esos campos desde
        la ficha del vehículo precisamente porque salen de aquí.
        """
        self.bd["vehiculos"].update_one(
            {"_id": vehiculo_id},
            {"$set": {**cambios,
                      "fecha_modificacion": datetime.now(timezone.utc)}},
        )


def _ahora() -> datetime:
    return datetime.now(timezone.utc)
