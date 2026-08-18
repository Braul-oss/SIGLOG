"""
SIG-LOG — Sistema Integral de Gestión Logística
backend/repositories/vehiculos.py

ACCESO A DATOS DE LA COLECCIÓN `vehiculos`  (§11.2)

Añade al CRUD genérico las consultas propias del módulo: el consecutivo del
código, la comprobación de la relación 1:1 con las rutas (RN-04) y la
lectura del historial de rendimiento.

Sobre el rendimiento: **no se recalcula nada aquí**. Cada carga de
`combustible` ya trae su `rendimiento_km_l` (§11.8), y el agregado del
periodo lo dejó el ETL en `dim_vehiculo`. Este repositorio los lee. Volver
a calcularlos daría dos cifras distintas del mismo dato según por dónde se
consultara, que es justo lo que el proyecto vino a evitar.
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

COLECCION = "vehiculos"
PREFIJO_CODIGO = "VEH"


class RepositorioVehiculos(RepositorioBase):
    def __init__(self, bd: Database) -> None:
        super().__init__(bd, COLECCION, nombre_singular="el vehículo")

    # ----------------------------------------------------------------------
    # Clave de negocio
    # ----------------------------------------------------------------------
    def siguiente_codigo(self) -> str:
        """Consecutivo VEH-NNN a partir del mayor existente (RN-V1)."""
        ultimo = self.coleccion.find_one(
            {"codigo_vehiculo": {"$regex": f"^{PREFIJO_CODIGO}-"}},
            {"codigo_vehiculo": 1},
            sort=[("codigo_vehiculo", -1)],
        )
        siguiente = 1
        if ultimo:
            coincidencia = re.search(r"(\d+)$", ultimo["codigo_vehiculo"])
            if coincidencia:
                siguiente = int(coincidencia.group(1)) + 1
        return f"{PREFIJO_CODIGO}-{siguiente:03d}"

    def por_placa(self, placa: str,
                  excluir: ObjectId | None = None) -> dict[str, Any] | None:
        """Busca por placa; `excluir` evita que un vehículo choque consigo mismo."""
        filtro: dict[str, Any] = {"placa": placa}
        if excluir is not None:
            filtro["_id"] = {"$ne": excluir}
        return self.coleccion.find_one(filtro)

    # ----------------------------------------------------------------------
    # Relación 1:1 con rutas  (RN-04)
    # ----------------------------------------------------------------------
    def vehiculo_de_la_ruta(self, ruta_id: ObjectId,
                            excluir: ObjectId | None = None) -> dict[str, Any] | None:
        """
        Vehículo que ya tiene asignada esa ruta, si lo hay.

        Es la comprobación que sostiene RN-04: una ruta no puede quedar
        asignada a dos vehículos.
        """
        filtro: dict[str, Any] = {"ruta_asignada_id": ruta_id,
                                  "activo": {"$ne": False}}
        if excluir is not None:
            filtro["_id"] = {"$ne": excluir}
        return self.coleccion.find_one(filtro)

    def ruta(self, ruta_id: ObjectId) -> dict[str, Any] | None:
        return self.bd["rutas"].find_one({"_id": ruta_id})

    def sincronizar_ruta(self, ruta_id: ObjectId | None,
                         vehiculo_id: ObjectId | None) -> None:
        """
        Mantiene coherente el otro extremo de la relación.

        `rutas.vehiculo_asignado_id` y `vehiculos.ruta_asignada_id` apuntan
        el uno al otro. Si solo se escribiera un lado, la ruta seguiría
        diciendo que la cubre un vehículo que ya no la tiene.
        """
        if ruta_id is None:
            return
        self.bd["rutas"].update_one({"_id": ruta_id},
                                    {"$set": {"vehiculo_asignado_id": vehiculo_id}})

    # ----------------------------------------------------------------------
    # Historial de rendimiento  (§12.3: GET /vehiculos/{id}/rendimiento)
    # ----------------------------------------------------------------------
    def cargas_de_combustible(self, vehiculo_id: ObjectId,
                              limite: int = 100) -> list[dict[str, Any]]:
        """Cargas del vehículo, de la más reciente a la más antigua."""
        return list(self.bd["combustible"].find(
            {"vehiculo_id": vehiculo_id},
            {"folio_carga": 1, "fecha": 1, "litros": 1, "costo_total": 1,
             "odometro_km": 1, "km_recorridos_desde_carga_anterior": 1,
             "rendimiento_km_l": 1, "estacion": 1},
        ).sort("fecha", -1).limit(limite))

    def metricas_del_dw(self, vehiculo_id: ObjectId) -> dict[str, Any] | None:
        """
        Métricas que el ETL dejó en `dim_vehiculo`.

        Se lee la dimensión en lugar de recalcular: es la misma cifra que
        muestran el dashboard y los reportes.
        """
        return self.bd["dim_vehiculo"].find_one(
            {"_id": str(vehiculo_id)},
            {"rendimiento_real_km_l": 1, "desviacion_rendimiento_pct": 1,
             "km_recorridos": 1, "litros": 1, "costo_combustible": 1,
             "costo_combustible_por_km": 1, "costo_total_por_km": 1,
             "n_viajes": 1, "n_cargas": 1},
        )

    def viajes_registrados(self, vehiculo_id: ObjectId) -> int:
        return self.bd["viajes"].count_documents({"vehiculo_id": vehiculo_id})
