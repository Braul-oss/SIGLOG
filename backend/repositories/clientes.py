"""
SIG-LOG — Sistema Integral de Gestión Logística
backend/repositories/clientes.py

ACCESO A DATOS DE LA COLECCIÓN `clientes`  (§11.1)

Hereda el CRUD genérico de `RepositorioBase` y añade lo propio del módulo:
generar el consecutivo del código de negocio, listar los municipios y
averiguar si un cliente es parada de alguna ruta.

La consulta contra `rutas` vive aquí y no en el servicio porque es una
consulta a MongoDB, y esa frontera es la que sostiene la arquitectura: los
servicios deciden reglas, los repositorios saben de la base.
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

COLECCION = "clientes"
PREFIJO_CODIGO = "CLI"


class RepositorioClientes(RepositorioBase):
    def __init__(self, bd: Database) -> None:
        super().__init__(bd, COLECCION, nombre_singular="el cliente")

    # ----------------------------------------------------------------------
    # Clave de negocio
    # ----------------------------------------------------------------------
    def siguiente_codigo(self) -> str:
        """
        Consecutivo CLI-NNN a partir del mayor código existente (RN-C1).

        Se toma el máximo y no el conteo de documentos: si alguna vez se
        borrara un cliente, contar reutilizaría un código ya usado, y ese
        código aparece denormalizado en entregas históricas.
        """
        ultimo = self.coleccion.find_one(
            {"codigo_cliente": {"$regex": f"^{PREFIJO_CODIGO}-"}},
            {"codigo_cliente": 1},
            sort=[("codigo_cliente", -1)],
        )
        siguiente = 1
        if ultimo:
            coincidencia = re.search(r"(\d+)$", ultimo["codigo_cliente"])
            if coincidencia:
                siguiente = int(coincidencia.group(1)) + 1
        return f"{PREFIJO_CODIGO}-{siguiente:03d}"

    # ----------------------------------------------------------------------
    # Consultas propias del módulo
    # ----------------------------------------------------------------------
    def municipios(self) -> list[str]:
        """Municipios presentes en las direcciones, para poblar un filtro."""
        return sorted(m for m in self.coleccion.distinct("direcciones.municipio")
                      if m)

    def rutas_que_lo_atienden(self, cliente_id: ObjectId,
                              solo_activas: bool = True) -> list[dict[str, Any]]:
        """
        Rutas en cuyas paradas figura el cliente (RN-C3).

        Es la comprobación que impide dejar una ruta apuntando a un cliente
        dado de baja.
        """
        filtro: dict[str, Any] = {"paradas.cliente_id": cliente_id}
        if solo_activas:
            filtro["activo"] = {"$ne": False}
        return list(self.bd["rutas"].find(filtro, {"codigo_ruta": 1, "nombre": 1}))

    def total_entregas_registradas(self, cliente_id: ObjectId) -> int:
        """Entregas históricas del cliente; explica por qué la baja es lógica."""
        return self.bd["entregas"].count_documents({"cliente_id": cliente_id})
