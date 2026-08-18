"""
SIG-LOG — Sistema Integral de Gestión Logística
backend/repositories/viajes.py

ACCESO A DATOS DE LA COLECCIÓN `viajes`  (§11.5)

Añade al CRUD genérico el folio fechado, las comprobaciones de
disponibilidad —¿está este vehículo o este operador ya comprometido?— y la
escritura del efecto que el viaje tiene sobre el vehículo.

Ese último punto merece atención: cerrar un viaje ACTUALIZA el odómetro
del vehículo. Es donde se cumple la promesa que hizo RN-V6 al prohibir
capturar el odómetro desde la ficha ("lo actualiza el cierre de cada
viaje"). Si esa escritura no existiera, el campo se quedaría congelado
para siempre.
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
from config import settings

COLECCION = "viajes"
PREFIJO_FOLIO = "VJE"


class RepositorioViajes(RepositorioBase):
    def __init__(self, bd: Database) -> None:
        super().__init__(bd, COLECCION, nombre_singular="el viaje")

    # ----------------------------------------------------------------------
    # Folio
    # ----------------------------------------------------------------------
    def siguiente_folio(self, fecha: datetime) -> str:
        """
        Folio VJE-AAAAMMDD-NNNN, consecutivo dentro del día.

        Lleva la fecha porque un viaje se identifica por el día en que se
        opera: es como lo busca quien trabaja con papeles del turno.
        """
        prefijo = f"{PREFIJO_FOLIO}-{fecha:%Y%m%d}"
        ultimo = self.coleccion.find_one(
            {"folio_viaje": {"$regex": f"^{prefijo}"}},
            {"folio_viaje": 1},
            sort=[("folio_viaje", -1)],
        )
        siguiente = 1
        if ultimo:
            coincidencia = re.search(r"(\d+)$", ultimo["folio_viaje"])
            if coincidencia:
                siguiente = int(coincidencia.group(1)) + 1
        return f"{prefijo}-{siguiente:04d}"

    # ----------------------------------------------------------------------
    # Disponibilidad  (RN-J3)
    # ----------------------------------------------------------------------
    def viaje_abierto_de(self, campo: str, identificador: ObjectId,
                         excluir: ObjectId | None = None
                         ) -> dict[str, Any] | None:
        """
        Viaje sin cerrar de un vehículo o de un operador.

        Nadie puede estar en dos jornadas a la vez, y una unidad tampoco.
        """
        filtro: dict[str, Any] = {
            campo: identificador,
            "estatus": {"$in": list(settings.ESTATUS_VIAJE_ABIERTOS)},
        }
        if excluir is not None:
            filtro["_id"] = {"$ne": excluir}
        return self.coleccion.find_one(
            filtro, {"folio_viaje": 1, "fecha": 1, "estatus": 1})

    def viaje_de_la_ruta_en_fecha(self, ruta_id: ObjectId,
                                  fecha: datetime) -> dict[str, Any] | None:
        """
        Viaje ya programado para esa ruta ese día.

        Una ruta se ejecuta una vez al día: dos viajes de la misma ruta en
        la misma fecha duplicarían las entregas y el kilometraje.
        """
        inicio = fecha.replace(hour=0, minute=0, second=0, microsecond=0)
        fin = inicio.replace(hour=23, minute=59, second=59)
        return self.coleccion.find_one(
            {"ruta_id": ruta_id, "fecha": {"$gte": inicio, "$lte": fin},
             "estatus": {"$ne": settings.ESTATUS_VIAJE_CANCELADO}},
            {"folio_viaje": 1, "estatus": 1})

    # ----------------------------------------------------------------------
    # Documentos relacionados
    # ----------------------------------------------------------------------
    def ruta(self, ruta_id: ObjectId) -> dict[str, Any] | None:
        return self.bd["rutas"].find_one({"_id": ruta_id})

    def vehiculo(self, vehiculo_id: ObjectId) -> dict[str, Any] | None:
        return self.bd["vehiculos"].find_one({"_id": vehiculo_id})

    def operador(self, operador_id: ObjectId) -> dict[str, Any] | None:
        return self.bd["operadores"].find_one({"_id": operador_id})

    def contar_entregas(self, viaje_id: ObjectId,
                        solo_completadas: bool = False) -> int:
        filtro: dict[str, Any] = {"viaje_id": viaje_id}
        if solo_completadas:
            filtro["estatus"] = "ENTREGADA"
        return self.bd["entregas"].count_documents(filtro)

    def contar_incidentes(self, viaje_id: ObjectId) -> int:
        return self.bd["incidentes"].count_documents({"viaje_id": viaje_id})

    # ----------------------------------------------------------------------
    # Efecto sobre el vehículo
    # ----------------------------------------------------------------------
    def marcar_vehiculo(self, vehiculo_id: ObjectId, estado: str,
                        odometro: float | None = None) -> None:
        """
        Refleja en el vehículo lo que le pasa por el viaje.

        Al salir queda EN_RUTA; al volver, DISPONIBLE y con el odómetro
        actualizado. Es el único punto del sistema que escribe ese campo, y
        por eso el módulo de vehículos lo prohíbe en su formulario (RN-V6).
        """
        cambios: dict[str, Any] = {
            "estado_operativo": estado,
            "fecha_modificacion": datetime.now(timezone.utc),
        }
        if odometro is not None:
            cambios["odometro_actual_km"] = round(odometro, 1)
        self.bd["vehiculos"].update_one({"_id": vehiculo_id}, {"$set": cambios})
