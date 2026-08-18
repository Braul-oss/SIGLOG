"""
SIG-LOG — Sistema Integral de Gestión Logística
backend/repositories/entregas.py

ACCESO A DATOS DE LA COLECCIÓN `entregas`  (§11.6)

La colección crítica del proyecto: de aquí salen la variable objetivo y la
mayoría de los predictores de los modelos.

Añade al CRUD genérico el folio fechado, la lectura de los documentos que
se denormalizan al crear (§10.4) y el conteo de entregas por viaje, que el
cierre del viaje usa para su total.
"""

from __future__ import annotations

import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from bson import ObjectId
from pymongo.database import Database

from backend.repositories.base import RepositorioBase

COLECCION = "entregas"
PREFIJO_FOLIO = "ENT"


class RepositorioEntregas(RepositorioBase):
    def __init__(self, bd: Database) -> None:
        super().__init__(bd, COLECCION, nombre_singular="la entrega")

    # ----------------------------------------------------------------------
    # Folio
    # ----------------------------------------------------------------------
    def siguiente_folio(self, fecha: datetime) -> str:
        """Folio ENT-AAAAMMDD-NNNNN, consecutivo dentro del día."""
        prefijo = f"{PREFIJO_FOLIO}-{fecha:%Y%m%d}"
        ultima = self.coleccion.find_one(
            {"folio_entrega": {"$regex": f"^{prefijo}"}},
            {"folio_entrega": 1},
            sort=[("folio_entrega", -1)],
        )
        siguiente = 1
        if ultima:
            coincidencia = re.search(r"(\d+)$", ultima["folio_entrega"])
            if coincidencia:
                siguiente = int(coincidencia.group(1)) + 1
        return f"{prefijo}-{siguiente:05d}"

    # ----------------------------------------------------------------------
    # Documentos relacionados  (para la denormalización de §10.4)
    # ----------------------------------------------------------------------
    def viaje(self, viaje_id: ObjectId) -> dict[str, Any] | None:
        return self.bd["viajes"].find_one({"_id": viaje_id})

    def cliente(self, cliente_id: ObjectId) -> dict[str, Any] | None:
        return self.bd["clientes"].find_one(
            {"_id": cliente_id}, {"codigo_cliente": 1, "nombre": 1, "activo": 1})

    def vehiculo(self, vehiculo_id: ObjectId) -> dict[str, Any] | None:
        return self.bd["vehiculos"].find_one(
            {"_id": vehiculo_id}, {"codigo_vehiculo": 1, "placa": 1})

    def operador(self, operador_id: ObjectId) -> dict[str, Any] | None:
        return self.bd["operadores"].find_one(
            {"_id": operador_id}, {"codigo_operador": 1, "nombre_completo": 1})

    def ruta(self, ruta_id: ObjectId) -> dict[str, Any] | None:
        return self.bd["rutas"].find_one({"_id": ruta_id})

    # ----------------------------------------------------------------------
    # Consultas del módulo
    # ----------------------------------------------------------------------
    def del_viaje(self, viaje_id: ObjectId) -> list[dict[str, Any]]:
        return list(self.coleccion.find({"viaje_id": viaje_id})
                    .sort("orden_parada", 1))

    def existe_parada(self, viaje_id: ObjectId, orden: int) -> bool:
        """Una parada del viaje no se registra dos veces."""
        return self.coleccion.count_documents(
            {"viaje_id": viaje_id, "orden_parada": orden}, limit=1) > 0

    def contar_por_estatus(self, estatus: str) -> int:
        return self.coleccion.count_documents({"estatus": estatus})

    def estadisticas_de_retraso(self) -> dict[str, Any]:
        """
        Resumen de la variable objetivo, leído con una agregación.

        Son las mismas cifras que el dashboard calcula sobre el DW; aquí se
        obtienen de la colección operativa para poder verlas sin haber
        corrido el ETL.
        """
        resultado = list(self.coleccion.aggregate([
            {"$match": {"retraso_min": {"$ne": None}}},
            {"$group": {"_id": None,
                        "medibles": {"$sum": 1},
                        "retrasadas": {"$sum": "$es_retraso"},
                        "retraso_medio": {"$avg": "$retraso_min"},
                        "retraso_maximo": {"$max": "$retraso_min"}}},
        ]))
        return resultado[0] if resultado else {}
