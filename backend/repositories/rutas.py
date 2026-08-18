"""
SIG-LOG — Sistema Integral de Gestión Logística
backend/repositories/rutas.py

ACCESO A DATOS DE LA COLECCIÓN `rutas`  (§11.4)

Añade al CRUD genérico el consecutivo del código, la validación de los
clientes de las paradas y la lectura del análisis que dejaron el ETL y el
clustering.

Como en vehículos y operadores, el análisis se LEE de `dim_ruta` y
`clusters_rutas`: son las mismas cifras del dashboard y del reporte de
K-Means, no una segunda versión calculada aquí.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from bson import ObjectId
from pymongo.database import Database

from backend.repositories.base import RepositorioBase

COLECCION = "rutas"
PREFIJO_CODIGO = "RUT"


class RepositorioRutas(RepositorioBase):
    def __init__(self, bd: Database) -> None:
        super().__init__(bd, COLECCION, nombre_singular="la ruta")

    # ----------------------------------------------------------------------
    # Clave de negocio
    # ----------------------------------------------------------------------
    def siguiente_codigo(self) -> str:
        """Consecutivo RUT-NNN a partir del mayor existente (RN-R1)."""
        ultima = self.coleccion.find_one(
            {"codigo_ruta": {"$regex": f"^{PREFIJO_CODIGO}-"}},
            {"codigo_ruta": 1},
            sort=[("codigo_ruta", -1)],
        )
        siguiente = 1
        if ultima:
            coincidencia = re.search(r"(\d+)$", ultima["codigo_ruta"])
            if coincidencia:
                siguiente = int(coincidencia.group(1)) + 1
        return f"{PREFIJO_CODIGO}-{siguiente:03d}"

    # ----------------------------------------------------------------------
    # Validación de las paradas
    # ----------------------------------------------------------------------
    def clientes_por_id(self, identificadores: list[ObjectId]
                        ) -> dict[ObjectId, dict[str, Any]]:
        """
        Trae de una sola consulta los clientes de todas las paradas.

        Se consultan juntos y no uno por uno: una ruta de ocho paradas
        haría ocho viajes a la base para validar lo mismo.
        """
        return {
            c["_id"]: c
            for c in self.bd["clientes"].find(
                {"_id": {"$in": identificadores}},
                {"codigo_cliente": 1, "nombre": 1, "direcciones": 1,
                 "activo": 1})
        }

    def vehiculo(self, vehiculo_id: ObjectId) -> dict[str, Any] | None:
        return self.bd["vehiculos"].find_one({"_id": vehiculo_id})

    # ----------------------------------------------------------------------
    # Análisis  (lo calcularon el ETL y el clustering)
    # ----------------------------------------------------------------------
    def perfil_del_dw(self, ruta_id: ObjectId) -> dict[str, Any] | None:
        """Perfil operativo que el ETL dejó en `dim_ruta`."""
        return self.bd["dim_ruta"].find_one(
            {"_id": str(ruta_id)},
            {"entregas": 1, "viajes": 1, "retraso_medio_min": 1,
             "retraso_maximo_min": 1, "pct_entregas_retrasadas": 1,
             "incidentes_por_viaje": 1, "retraso_salida_medio_min": 1},
        )

    def cluster(self, ruta_id: ObjectId) -> dict[str, Any] | None:
        """Grupo asignado por K-Means, con su nombre y su recomendación."""
        return self.bd["clusters_rutas"].find_one(
            {"_id": str(ruta_id)},
            {"grupo": 1, "nombre_grupo": 1, "descripcion_grupo": 1,
             "recomendacion": 1, "silueta": 1, "silueta_global": 1, "k": 1},
        )

    def promedio_retraso_flotilla(self) -> float | None:
        resultado = list(self.bd["dim_ruta"].aggregate([
            {"$group": {"_id": None, "media": {"$avg": "$retraso_medio_min"}}},
        ]))
        return round(resultado[0]["media"], 2) if resultado else None

    def viajes_registrados(self, ruta_id: ObjectId) -> int:
        return self.bd["viajes"].count_documents({"ruta_id": ruta_id})

    def viajes_en_curso(self, ruta_id: ObjectId) -> int:
        return self.bd["viajes"].count_documents(
            {"ruta_id": ruta_id,
             "estatus": {"$nin": ["FINALIZADO", "CANCELADO"]}})
