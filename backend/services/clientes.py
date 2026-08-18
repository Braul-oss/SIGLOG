"""
SIG-LOG — Sistema Integral de Gestión Logística
backend/services/clientes.py

REGLAS DEL MÓDULO CLIENTES  (§11.1)

Reglas de negocio (RN-C1 a RN-C4)
---------------------------------
RN-C1  `codigo_cliente` lo genera el sistema con el formato CLI-NNN y es
       inmutable. Es la clave de negocio: aparece denormalizada en las
       entregas y ordena los listados; dejarla a la captura produciría
       duplicados y formatos que no ordenan.

RN-C2  Un cliente tiene al menos una dirección y EXACTAMENTE una marcada
       como principal. Sin esa garantía, la ruta no sabría a cuál de las
       direcciones ir. Si se envía una sola dirección sin marcar, se marca
       sola; si se envían varias sin marcar o con más de una, se rechaza,
       porque ahí la intención es ambigua y adivinarla sería peor.

RN-C3  No se puede dar de baja un cliente que sea parada de una ruta
       activa. La ruta quedaría apuntando a un cliente inexistente y el
       viaje siguiente fallaría en operación. Hay que quitarlo antes de la
       ruta.

RN-C4  La baja es lógica, nunca borrado. Las entregas históricas
       referencian al cliente, y el ETL, el DW y los modelos se construyen
       sobre ellas: borrarlo dejaría huérfano el histórico.

Las reglas C2 y C3 son las que impiden dejar la operación en un estado
imposible; el resto del módulo es un CRUD.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from backend.repositories.clientes import RepositorioClientes
from backend.schemas.clientes import ClienteSalida
from backend.utils.errores import RecursoDuplicado, ReglaDeNegocio
from config import settings


# ==========================================================================
# CONSULTA
# ==========================================================================
def listar(bd: Database, *, saltar: int = 0, limite: int = 50,
           busqueda: str | None = None, tipo_cliente: str | None = None,
           municipio: str | None = None, incluir_inactivos: bool = False
           ) -> tuple[list[dict[str, Any]], int]:
    """
    Listado paginado con los filtros del §12.3 ("listar con filtros y
    paginación").

    La búsqueda por nombre usa una expresión regular sin distinguir
    mayúsculas en lugar del índice de texto: el índice `tx_clientes_nombre`
    solo encuentra palabras completas, y quien busca en un formulario
    espera que "valle" encuentre "Comercializadora del Valle".
    """
    repositorio = RepositorioClientes(bd)
    filtro: dict[str, Any] = {}

    if busqueda:
        filtro["$or"] = [
            {"nombre": {"$regex": busqueda.strip(), "$options": "i"}},
            {"codigo_cliente": {"$regex": busqueda.strip(), "$options": "i"}},
        ]
    if tipo_cliente:
        tipo_cliente = tipo_cliente.strip().upper()
        if tipo_cliente not in settings.CATALOGO_TIPO_CLIENTE:
            raise ReglaDeNegocio(
                f"Tipo de cliente '{tipo_cliente}' no pertenece al catálogo "
                f"{list(settings.CATALOGO_TIPO_CLIENTE)}.")
        filtro["tipo_cliente"] = tipo_cliente
    if municipio:
        filtro["direcciones.municipio"] = {
            "$regex": f"^{municipio.strip()}$", "$options": "i"}

    documentos = repositorio.listar(
        filtro, saltar=saltar, limite=limite,
        orden=[("codigo_cliente", 1)], incluir_inactivos=incluir_inactivos)
    total = repositorio.contar(filtro, incluir_inactivos=incluir_inactivos)
    return [_publico(d) for d in documentos], total


def obtener(bd: Database, identificador: str) -> dict[str, Any]:
    return _publico(
        RepositorioClientes(bd).obtener(identificador, incluir_inactivos=True))


def resumen(bd: Database) -> dict[str, Any]:
    """Conteo por tipo y por municipio, para el panel del módulo."""
    repositorio = RepositorioClientes(bd)
    total = repositorio.contar(incluir_inactivos=True)
    activos = repositorio.contar()
    return {
        "total": total,
        "activos": activos,
        "inactivos": total - activos,
        "por_tipo": {
            tipo: repositorio.contar({"tipo_cliente": tipo})
            for tipo in settings.CATALOGO_TIPO_CLIENTE
        },
        "municipios": repositorio.municipios(),
        "catalogo_tipos": list(settings.CATALOGO_TIPO_CLIENTE),
    }


# ==========================================================================
# ALTA
# ==========================================================================
def crear(bd: Database, datos: dict[str, Any]) -> dict[str, Any]:
    """Da de alta un cliente aplicando RN-C1 y RN-C2."""
    repositorio = RepositorioClientes(bd)

    documento = {
        **datos,
        "direcciones": _normalizar_direcciones(datos["direcciones"]),
        "codigo_cliente": repositorio.siguiente_codigo(),   # RN-C1
        "total_entregas": 0,
    }
    try:
        creado = repositorio.crear(documento)
    except DuplicateKeyError as exc:
        # Solo puede ocurrir si dos altas simultáneas toman el mismo
        # consecutivo; el índice único es la última defensa.
        raise RecursoDuplicado(
            "Otra alta tomó el mismo código de cliente. Vuelve a intentarlo."
        ) from exc
    return _publico(creado)


# ==========================================================================
# EDICIÓN
# ==========================================================================
def actualizar(bd: Database, identificador: str,
               cambios: dict[str, Any]) -> dict[str, Any]:
    if "codigo_cliente" in cambios:
        raise ReglaDeNegocio(
            "El código de cliente no se puede cambiar (RN-C1): aparece "
            "denormalizado en las entregas ya registradas.",
            regla="C1")
    if not cambios:
        raise ReglaDeNegocio("No se envió ningún campo que actualizar.")

    if "direcciones" in cambios:
        cambios["direcciones"] = _normalizar_direcciones(cambios["direcciones"])

    return _publico(RepositorioClientes(bd).actualizar(
        identificador, cambios, incluir_inactivos=True))


# ==========================================================================
# BAJA Y REACTIVACIÓN
# ==========================================================================
def desactivar(bd: Database, identificador: str) -> dict[str, Any]:
    """Baja lógica, con la comprobación de RN-C3."""
    repositorio = RepositorioClientes(bd)
    cliente = repositorio.obtener(identificador, incluir_inactivos=True)

    if not cliente.get("activo", True):
        raise ReglaDeNegocio(
            f"El cliente '{cliente['codigo_cliente']}' ya estaba dado de baja.")

    rutas = repositorio.rutas_que_lo_atienden(cliente["_id"])
    if rutas:
        codigos = ", ".join(sorted(r["codigo_ruta"] for r in rutas))
        raise ReglaDeNegocio(
            f"No se puede dar de baja al cliente "
            f"'{cliente['codigo_cliente']}' (RN-C3): es parada de "
            f"{len(rutas)} ruta(s) activa(s) ({codigos}). Quítalo primero "
            "de esas rutas.",
            regla="C3",
            detalles=[{"rutas_afectadas": codigos}])

    return _publico(repositorio.baja_logica(identificador))


def reactivar(bd: Database, identificador: str) -> dict[str, Any]:
    repositorio = RepositorioClientes(bd)
    cliente = repositorio.obtener(identificador, incluir_inactivos=True)
    if cliente.get("activo", True):
        raise ReglaDeNegocio(
            f"El cliente '{cliente['codigo_cliente']}' ya está activo.")
    return _publico(repositorio.actualizar(identificador, {"activo": True},
                                           incluir_inactivos=True))


# ==========================================================================
# INTERNO
# ==========================================================================
def _normalizar_direcciones(direcciones: list[Any]) -> list[dict[str, Any]]:
    """
    RN-C2: al menos una dirección y exactamente una principal.

    Si viene una sola sin marcar, se marca sola: la intención es evidente y
    exigir la marca sería burocracia. Con varias, se exige que se declare
    cuál es la principal.
    """
    lista = [d.model_dump() if hasattr(d, "model_dump") else dict(d)
             for d in direcciones]
    if not lista:
        raise ReglaDeNegocio(
            "El cliente necesita al menos una dirección de entrega (RN-C2).",
            regla="C2")

    principales = [d for d in lista if d.get("principal")]

    if len(principales) == 1:
        return lista
    if not principales and len(lista) == 1:
        lista[0]["principal"] = True
        return lista
    if not principales:
        raise ReglaDeNegocio(
            "Con varias direcciones hay que marcar cuál es la principal "
            "(RN-C2): es la que usarán las rutas por omisión.",
            regla="C2")
    alias = ", ".join(str(d.get("alias", "?")) for d in principales)
    raise ReglaDeNegocio(
        f"Solo puede haber una dirección principal (RN-C2). Vienen "
        f"{len(principales)}: {alias}.",
        regla="C2")


def _publico(documento: dict[str, Any]) -> dict[str, Any]:
    return ClienteSalida.desde_documento(documento).model_dump()
