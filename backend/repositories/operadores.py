"""
SIG-LOG — Sistema Integral de Gestión Logística
backend/repositories/operadores.py

ACCESO A DATOS DE LA COLECCIÓN `operadores`  (§11.3)

Añade al CRUD genérico el consecutivo del código, la búsqueda por número de
licencia y las consultas de vigencia, que son las que sostienen RN-O3.

El desempeño se LEE de `dim_operador`, donde lo dejó el ETL. No se
recalcula aquí por la misma razón que en vehículos: dos cifras distintas
del mismo indicador según por dónde se consultara sería peor que no
tenerlo.
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

COLECCION = "operadores"
PREFIJO_CODIGO = "OPE"


class RepositorioOperadores(RepositorioBase):
    def __init__(self, bd: Database) -> None:
        super().__init__(bd, COLECCION, nombre_singular="el operador")

    # ----------------------------------------------------------------------
    # Clave de negocio
    # ----------------------------------------------------------------------
    def siguiente_codigo(self) -> str:
        """Consecutivo OPE-NNN a partir del mayor existente (RN-O1)."""
        ultimo = self.coleccion.find_one(
            {"codigo_operador": {"$regex": f"^{PREFIJO_CODIGO}-"}},
            {"codigo_operador": 1},
            sort=[("codigo_operador", -1)],
        )
        siguiente = 1
        if ultimo:
            coincidencia = re.search(r"(\d+)$", ultimo["codigo_operador"])
            if coincidencia:
                siguiente = int(coincidencia.group(1)) + 1
        return f"{PREFIJO_CODIGO}-{siguiente:03d}"

    def por_numero_de_licencia(self, numero: str,
                               excluir: ObjectId | None = None
                               ) -> dict[str, Any] | None:
        """Busca por número de licencia; sostiene RN-O2."""
        filtro: dict[str, Any] = {"licencia.numero": numero}
        if excluir is not None:
            filtro["_id"] = {"$ne": excluir}
        return self.coleccion.find_one(filtro)

    # ----------------------------------------------------------------------
    # Vigencia de licencias  (RN-O3)
    # ----------------------------------------------------------------------
    def con_licencia_vencida(self) -> list[dict[str, Any]]:
        return list(self.coleccion.find(
            {"licencia.vigencia": {"$lt": _ahora()},
             "activo": {"$ne": False}},
            {"codigo_operador": 1, "nombre_completo": 1, "licencia": 1,
             "estado": 1},
        ).sort("licencia.vigencia", 1))

    def con_licencia_por_vencer(self, dias: int) -> list[dict[str, Any]]:
        """Licencias que caducan dentro del plazo indicado (aún vigentes)."""
        ahora = _ahora()
        return list(self.coleccion.find(
            {"licencia.vigencia": {"$gte": ahora,
                                   "$lte": ahora + timedelta(days=dias)},
             "activo": {"$ne": False}},
            {"codigo_operador": 1, "nombre_completo": 1, "licencia": 1,
             "estado": 1},
        ).sort("licencia.vigencia", 1))

    def contar_licencias_vencidas(self) -> int:
        return self.coleccion.count_documents(
            {"licencia.vigencia": {"$lt": _ahora()}, "activo": {"$ne": False}})

    # ----------------------------------------------------------------------
    # Desempeño  (§12.3: GET /operadores/{id}/desempenio)
    # ----------------------------------------------------------------------
    def metricas_del_dw(self, operador_id: ObjectId) -> dict[str, Any] | None:
        """Métricas que el ETL dejó en `dim_operador`."""
        return self.bd["dim_operador"].find_one(
            {"_id": str(operador_id)},
            {"entregas_medibles": 1, "a_tiempo": 1, "viajes": 1,
             "retraso_medio_min": 1, "porcentaje_entregas_a_tiempo": 1,
             "entregas_por_viaje": 1},
        )

    def promedio_de_la_flotilla(self) -> float | None:
        """
        Puntualidad media de todos los operadores, para poder situar al
        individuo. Un porcentaje suelto no dice si es bueno o malo.
        """
        resultado = list(self.bd["dim_operador"].aggregate([
            {"$group": {"_id": None,
                        "media": {"$avg": "$porcentaje_entregas_a_tiempo"}}},
        ]))
        return round(resultado[0]["media"], 1) if resultado else None

    def viajes_realizados(self, operador_id: ObjectId) -> int:
        return self.bd["viajes"].count_documents({"operador_id": operador_id})

    def viajes_en_curso(self, operador_id: ObjectId) -> int:
        """
        Viajes que aún no han cerrado. Es la comprobación de RN-O5: no se
        da de baja a alguien que está en la calle.
        """
        return self.bd["viajes"].count_documents(
            {"operador_id": operador_id,
             "estatus": {"$nin": ["FINALIZADO", "CANCELADO"]}})


def _ahora() -> datetime:
    return datetime.now(timezone.utc)
