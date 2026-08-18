"""
SIG-LOG — Sistema Integral de Gestión Logística
backend/repositories/combustible.py

ACCESO A DATOS DE LA COLECCIÓN `combustible`  (§11.8)

Añade al CRUD genérico el folio fechado, la búsqueda de la carga anterior
de una unidad —de la que sale el tramo recorrido— y las agregaciones del
resumen de consumo y costo que pide el §12.3.
"""

from __future__ import annotations

import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from bson import ObjectId
from pymongo.database import Database

from backend.repositories.base import RepositorioBase

COLECCION = "combustible"
PREFIJO_FOLIO = "CMB"


class RepositorioCombustible(RepositorioBase):
    def __init__(self, bd: Database) -> None:
        super().__init__(bd, COLECCION, nombre_singular="la carga")

    # ----------------------------------------------------------------------
    # Folio
    # ----------------------------------------------------------------------
    def siguiente_folio(self, fecha: datetime) -> str:
        """Folio CMB-AAAAMMDD-NNNN, consecutivo dentro del día."""
        prefijo = f"{PREFIJO_FOLIO}-{fecha:%Y%m%d}"
        ultima = self.coleccion.find_one(
            {"folio_carga": {"$regex": f"^{prefijo}"}},
            {"folio_carga": 1},
            sort=[("folio_carga", -1)],
        )
        siguiente = 1
        if ultima:
            coincidencia = re.search(r"(\d+)$", ultima["folio_carga"])
            if coincidencia:
                siguiente = int(coincidencia.group(1)) + 1
        return f"{prefijo}-{siguiente:04d}"

    # ----------------------------------------------------------------------
    # Carga anterior  (de aquí sale el tramo recorrido)
    # ----------------------------------------------------------------------
    def carga_anterior(self, vehiculo_id: ObjectId,
                       antes_de: datetime) -> dict[str, Any] | None:
        """
        Última carga de la unidad previa a la fecha indicada.

        Se busca por fecha y no simplemente "la última insertada": una
        carga puede registrarse con retraso, y el tramo debe medirse
        contra la que de verdad le precede en el tiempo.
        """
        return self.coleccion.find_one(
            {"vehiculo_id": vehiculo_id, "fecha": {"$lt": antes_de}},
            {"folio_carga": 1, "fecha": 1, "odometro_km": 1},
            sort=[("fecha", -1)],
        )

    def carga_posterior(self, vehiculo_id: ObjectId,
                        despues_de: datetime) -> dict[str, Any] | None:
        """
        Primera carga posterior, si la hubiera.

        Sirve para detectar un registro fuera de orden: si ya existe una
        carga posterior, su tramo quedaría mal medido al insertar una
        intermedia.
        """
        return self.coleccion.find_one(
            {"vehiculo_id": vehiculo_id, "fecha": {"$gt": despues_de}},
            {"folio_carga": 1, "fecha": 1, "odometro_km": 1},
            sort=[("fecha", 1)],
        )

    # ----------------------------------------------------------------------
    # Documentos relacionados
    # ----------------------------------------------------------------------
    def vehiculo(self, vehiculo_id: ObjectId) -> dict[str, Any] | None:
        return self.bd["vehiculos"].find_one({"_id": vehiculo_id})

    def viaje(self, viaje_id: ObjectId) -> dict[str, Any] | None:
        return self.bd["viajes"].find_one({"_id": viaje_id})

    def actualizar_odometro_vehiculo(self, vehiculo_id: ObjectId,
                                     odometro: float) -> None:
        """
        El §11.2 dice que `odometro_actual_km` "se actualiza con cada
        carga/viaje". El cierre del viaje ya lo hace; esta es la otra
        mitad de esa promesa.
        """
        self.bd["vehiculos"].update_one(
            {"_id": vehiculo_id},
            {"$set": {"odometro_actual_km": round(odometro, 1),
                      "fecha_modificacion": datetime.now(timezone.utc)}},
        )

    # ----------------------------------------------------------------------
    # Agregaciones del resumen  (§12.3: GET /combustible/resumen)
    # ----------------------------------------------------------------------
    def totales(self, filtro: dict[str, Any] | None = None) -> dict[str, Any]:
        resultado = list(self.coleccion.aggregate([
            {"$match": filtro or {}},
            {"$group": {"_id": None,
                        "cargas": {"$sum": 1},
                        "litros": {"$sum": "$litros"},
                        "costo": {"$sum": "$costo_total"},
                        "km": {"$sum": "$km_recorridos_desde_carga_anterior"},
                        "precio_medio": {"$avg": "$precio_por_litro"}}},
        ]))
        return resultado[0] if resultado else {}

    def por_vehiculo(self, limite: int = 10) -> list[dict[str, Any]]:
        """Consumo y costo por unidad, de mayor a menor costo."""
        return list(self.coleccion.aggregate([
            {"$group": {"_id": "$vehiculo_id",
                        "cargas": {"$sum": 1},
                        "litros": {"$sum": "$litros"},
                        "costo": {"$sum": "$costo_total"},
                        "km": {"$sum": "$km_recorridos_desde_carga_anterior"}}},
            {"$sort": {"costo": -1}},
            {"$limit": limite},
            {"$lookup": {"from": "vehiculos", "localField": "_id",
                         "foreignField": "_id", "as": "vehiculo"}},
            {"$unwind": "$vehiculo"},
            {"$project": {
                "_id": 0,
                "vehiculo_id": {"$toString": "$_id"},
                "codigo_vehiculo": "$vehiculo.codigo_vehiculo",
                "placa": "$vehiculo.placa",
                "cargas": 1, "litros": {"$round": ["$litros", 1]},
                "costo": {"$round": ["$costo", 2]},
                "km": {"$round": ["$km", 1]},
                "rendimiento_km_l": {
                    "$cond": [{"$gt": ["$litros", 0]},
                              {"$round": [{"$divide": ["$km", "$litros"]}, 2]},
                              None]},
                "costo_por_km": {
                    "$cond": [{"$gt": ["$km", 0]},
                              {"$round": [{"$divide": ["$costo", "$km"]}, 2]},
                              None]},
            }},
        ]))

    def por_estacion(self) -> list[dict[str, Any]]:
        return list(self.coleccion.aggregate([
            {"$group": {"_id": "$estacion", "cargas": {"$sum": 1},
                        "litros": {"$sum": "$litros"},
                        "costo": {"$sum": "$costo_total"},
                        "precio_medio": {"$avg": "$precio_por_litro"}}},
            {"$sort": {"costo": -1}},
            {"$project": {"_id": 0, "estacion": "$_id", "cargas": 1,
                          "litros": {"$round": ["$litros", 1]},
                          "costo": {"$round": ["$costo", 2]},
                          "precio_medio": {"$round": ["$precio_medio", 2]}}},
        ]))

    def estaciones(self) -> list[str]:
        return sorted(e for e in self.coleccion.distinct("estacion") if e)
