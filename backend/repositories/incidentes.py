"""
SIG-LOG — Sistema Integral de Gestión Logística
backend/repositories/incidentes.py

ACCESO A DATOS DE LA COLECCIÓN `incidentes`  (§11.7)

Añade al CRUD genérico el folio fechado, la búsqueda de las entregas
pendientes de un viaje —lo que necesita el recálculo de ETA— y la
escritura en `seguimiento_eventos`.

Sobre esa última: `seguimiento_eventos` (§11.10) llevaba vacía desde que
se creó la base. Se dijo entonces que la llenaría el sistema web durante
la operación, y este es el módulo que lo hace: el recálculo de ETA deja
ahí su rastro, que es el paso 4 del procedimiento del §17.3.
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

COLECCION = "incidentes"
PREFIJO_FOLIO = "INC"

# Entregas que ya no admiten recálculo: su desenlace está registrado.
ESTATUS_CERRADOS_ENTREGA = ("ENTREGADA", "NO_ENTREGADA", "CANCELADA")


class RepositorioIncidentes(RepositorioBase):
    def __init__(self, bd: Database) -> None:
        super().__init__(bd, COLECCION, nombre_singular="el incidente")

    # ----------------------------------------------------------------------
    # Folio
    # ----------------------------------------------------------------------
    def siguiente_folio(self, fecha: datetime) -> str:
        """Folio INC-AAAAMMDD-NNN, consecutivo dentro del día."""
        prefijo = f"{PREFIJO_FOLIO}-{fecha:%Y%m%d}"
        ultimo = self.coleccion.find_one(
            {"folio_incidente": {"$regex": f"^{prefijo}"}},
            {"folio_incidente": 1},
            sort=[("folio_incidente", -1)],
        )
        siguiente = 1
        if ultimo:
            coincidencia = re.search(r"(\d+)$", ultimo["folio_incidente"])
            if coincidencia:
                siguiente = int(coincidencia.group(1)) + 1
        return f"{prefijo}-{siguiente:04d}"

    # ----------------------------------------------------------------------
    # Documentos relacionados
    # ----------------------------------------------------------------------
    def viaje(self, viaje_id: ObjectId) -> dict[str, Any] | None:
        return self.bd["viajes"].find_one({"_id": viaje_id})

    def entregas_pendientes(self, viaje_id: ObjectId) -> list[dict[str, Any]]:
        """
        Entregas del viaje que aún no tienen desenlace (§17.3, paso 2).

        Solo estas admiten recálculo: a una entrega ya registrada no se le
        puede cambiar la previsión de cuándo iba a llegar.
        """
        return list(self.bd["entregas"].find(
            {"viaje_id": viaje_id,
             "estatus": {"$nin": list(ESTATUS_CERRADOS_ENTREGA)}},
            {"folio_entrega": 1, "orden_parada": 1, "estatus": 1,
             "hora_estimada_llegada": 1, "hora_estimada_recalculada": 1,
             "incidentes_ids": 1},
        ).sort("orden_parada", 1))

    def entregas_por_id(self, identificadores: list[ObjectId]
                        ) -> list[dict[str, Any]]:
        return list(self.bd["entregas"].find(
            {"_id": {"$in": identificadores}},
            {"folio_entrega": 1, "orden_parada": 1, "estatus": 1,
             "viaje_id": 1, "hora_estimada_llegada": 1,
             "hora_estimada_recalculada": 1, "incidentes_ids": 1},
        ).sort("orden_parada", 1))

    # ----------------------------------------------------------------------
    # Efecto sobre las entregas  (RF-33)
    # ----------------------------------------------------------------------
    def aplicar_recalculo(self, entrega_id: ObjectId, eta_nuevo: datetime,
                          incidente_id: ObjectId) -> None:
        """
        Escribe el ETA recalculado y asocia el incidente.

        Se guarda en `hora_estimada_recalculada` y NUNCA se pisa
        `hora_estimada_llegada`: el plan original es la referencia contra
        la que se mide el retraso. Sobrescribirlo haría que la entrega
        pareciera puntual justo por el incidente que la retrasó, y los
        modelos perderían la señal que este módulo existe para darles.
        """
        self.bd["entregas"].update_one(
            {"_id": entrega_id},
            {"$set": {"hora_estimada_recalculada": eta_nuevo,
                      "fecha_modificacion": datetime.now(timezone.utc)},
             "$addToSet": {"incidentes_ids": incidente_id}},
        )

    def contar_incidentes_del_viaje(self, viaje_id: ObjectId) -> int:
        return self.coleccion.count_documents({"viaje_id": viaje_id})

    def actualizar_total_del_viaje(self, viaje_id: ObjectId) -> None:
        """Mantiene al día `viajes.total_incidentes`, que el §11.5 marca derivado."""
        self.bd["viajes"].update_one(
            {"_id": viaje_id},
            {"$set": {"total_incidentes":
                      self.contar_incidentes_del_viaje(viaje_id)}},
        )

    # ----------------------------------------------------------------------
    # Bitácora de seguimiento  (§11.10, §17.3 paso 4)
    # ----------------------------------------------------------------------
    def registrar_evento(self, viaje_id: ObjectId, tipo_evento: str, *,
                         entrega_id: ObjectId | None = None,
                         eta_anterior: datetime | None = None,
                         eta_nuevo: datetime | None = None,
                         motivo: str | None = None) -> None:
        """Deja constancia en `seguimiento_eventos` de lo que acaba de pasar."""
        self.bd["seguimiento_eventos"].insert_one({
            "viaje_id": viaje_id,
            "entrega_id": entrega_id,
            "tipo_evento": tipo_evento,
            "fecha_hora": datetime.now(timezone.utc),
            "ubicacion": None,
            "eta_anterior": eta_anterior,
            "eta_nuevo": eta_nuevo,
            "motivo": motivo,
            "origen_dato": "REAL",
            "activo": True,
            "fecha_creacion": datetime.now(timezone.utc),
            "fecha_modificacion": datetime.now(timezone.utc),
        })

    def eventos_del_viaje(self, viaje_id: ObjectId) -> list[dict[str, Any]]:
        return list(self.bd["seguimiento_eventos"]
                    .find({"viaje_id": viaje_id})
                    .sort("fecha_hora", 1))
