"""
SIG-LOG — Sistema Integral de Gestión Logística
database/indices.py

Propósito
---------
Declara y crea los índices de MongoDB. Cada índice de este archivo está
tomado literalmente de la línea "**Índices:**" de las secciones §11.1 a
§11.10 del documento técnico base. Se agregan únicamente los índices aprobados en las decisiones D-1 y D-2 (16/08/2026),
marcados con su identificador en el propio código.

Los índices son, además, la evidencia del tema "Optimización" de la
Unidad I (§6 de la matriz de trazabilidad).

Convención de nombres
---------------------
    ux_<coleccion>_<campos>  índice único
    ix_<coleccion>_<campos>  índice simple o compuesto
    tx_<coleccion>_<campos>  índice de texto
    gx_<coleccion>_<campos>  índice geoespacial (2dsphere)
"""

from __future__ import annotations

from typing import Any

from pymongo import ASCENDING, GEOSPHERE, TEXT
from pymongo.database import Database
from pymongo.errors import OperationFailure

# --------------------------------------------------------------------------
# Catálogo de índices por colección
#   claves       : lista de tuplas (campo, dirección/tipo)
#   nombre       : nombre explícito del índice
#   unico        : True si es índice único
#   geoespacial  : True si requiere confirmación del uso de GPS
#   origen       : sección del documento técnico de la que proviene
# --------------------------------------------------------------------------
INDICES: dict[str, list[dict[str, Any]]] = {
    # ---------------- §11.1 clientes ----------------
    "clientes": [
        {"claves": [("codigo_cliente", ASCENDING)], "nombre": "ux_clientes_codigo", "unico": True},
        {"claves": [("nombre", TEXT)], "nombre": "tx_clientes_nombre"},
        {"claves": [("direcciones.municipio", ASCENDING)], "nombre": "ix_clientes_municipio"},
        {
            "claves": [("direcciones.ubicacion", GEOSPHERE)],
            "nombre": "gx_clientes_ubicacion",
            "geoespacial": True,
        },
    ],
    # ---------------- §11.2 vehiculos ----------------
    "vehiculos": [
        {"claves": [("placa", ASCENDING)], "nombre": "ux_vehiculos_placa", "unico": True},
        {"claves": [("codigo_vehiculo", ASCENDING)], "nombre": "ux_vehiculos_codigo", "unico": True},
        {"claves": [("estado_operativo", ASCENDING)], "nombre": "ix_vehiculos_estado"},
        {"claves": [("ruta_asignada_id", ASCENDING)], "nombre": "ix_vehiculos_ruta_asignada"},
        {"claves": [("fecha_proximo_mantenimiento", ASCENDING)], "nombre": "ix_vehiculos_prox_mtto"},
    ],
    # ---------------- §11.3 operadores ----------------
    "operadores": [
        {"claves": [("codigo_operador", ASCENDING)], "nombre": "ux_operadores_codigo", "unico": True},
        {"claves": [("estado", ASCENDING)], "nombre": "ix_operadores_estado"},
        {"claves": [("licencia.vigencia", ASCENDING)], "nombre": "ix_operadores_licencia_vigencia"},
    ],
    # ---------------- §11.4 rutas ----------------
    "rutas": [
        {"claves": [("codigo_ruta", ASCENDING)], "nombre": "ux_rutas_codigo", "unico": True},
        {"claves": [("zona", ASCENDING)], "nombre": "ix_rutas_zona"},
        {"claves": [("vehiculo_asignado_id", ASCENDING)], "nombre": "ix_rutas_vehiculo_asignado"},
        {"claves": [("paradas.cliente_id", ASCENDING)], "nombre": "ix_rutas_paradas_cliente"},
    ],
    # ---------------- §11.5 viajes ----------------
    "viajes": [
        {"claves": [("folio_viaje", ASCENDING)], "nombre": "ux_viajes_folio", "unico": True},   # D-1
        {"claves": [("fecha", ASCENDING)], "nombre": "ix_viajes_fecha"},
        {"claves": [("ruta_id", ASCENDING), ("fecha", ASCENDING)], "nombre": "ix_viajes_ruta_fecha"},
        {"claves": [("vehiculo_id", ASCENDING)], "nombre": "ix_viajes_vehiculo"},
        {"claves": [("operador_id", ASCENDING)], "nombre": "ix_viajes_operador"},
        {"claves": [("estatus", ASCENDING)], "nombre": "ix_viajes_estatus"},
    ],
    # ---------------- §11.6 entregas ----------------
    "entregas": [
        {"claves": [("folio_entrega", ASCENDING)], "nombre": "ux_entregas_folio", "unico": True},
        {"claves": [("fecha", ASCENDING)], "nombre": "ix_entregas_fecha"},
        {"claves": [("cliente_id", ASCENDING), ("fecha", ASCENDING)], "nombre": "ix_entregas_cliente_fecha"},
        {"claves": [("ruta_id", ASCENDING), ("fecha", ASCENDING)], "nombre": "ix_entregas_ruta_fecha"},
        {"claves": [("viaje_id", ASCENDING)], "nombre": "ix_entregas_viaje"},   # D-2
        {"claves": [("vehiculo_id", ASCENDING)], "nombre": "ix_entregas_vehiculo"},
        {"claves": [("estatus", ASCENDING)], "nombre": "ix_entregas_estatus"},
        {"claves": [("es_retraso", ASCENDING)], "nombre": "ix_entregas_es_retraso"},
    ],
    # ---------------- §11.7 incidentes ----------------
    "incidentes": [
        {"claves": [("folio_incidente", ASCENDING)], "nombre": "ux_incidentes_folio", "unico": True},   # D-1
        {"claves": [("fecha_hora_inicio", ASCENDING)], "nombre": "ix_incidentes_fecha_inicio"},
        {"claves": [("tipo", ASCENDING)], "nombre": "ix_incidentes_tipo"},
        {"claves": [("viaje_id", ASCENDING)], "nombre": "ix_incidentes_viaje"},
        {"claves": [("ruta_id", ASCENDING)], "nombre": "ix_incidentes_ruta"},
        {"claves": [("severidad", ASCENDING)], "nombre": "ix_incidentes_severidad"},
    ],
    # ---------------- §11.8 combustible ----------------
    "combustible": [
        {"claves": [("folio_carga", ASCENDING)], "nombre": "ux_combustible_folio", "unico": True},   # D-1
        {"claves": [("vehiculo_id", ASCENDING), ("fecha", ASCENDING)], "nombre": "ix_combustible_vehiculo_fecha"},
        {"claves": [("fecha", ASCENDING)], "nombre": "ix_combustible_fecha"},
        {"claves": [("viaje_id", ASCENDING)], "nombre": "ix_combustible_viaje"},
    ],
    # ---------------- §11.9 mantenimientos ----------------
    "mantenimientos": [
        {"claves": [("folio_mantenimiento", ASCENDING)], "nombre": "ux_mtto_folio", "unico": True},   # D-1
        {"claves": [("vehiculo_id", ASCENDING), ("fecha_programada", ASCENDING)], "nombre": "ix_mtto_vehiculo_fecha"},
        {"claves": [("estatus", ASCENDING)], "nombre": "ix_mtto_estatus"},
        {"claves": [("tipo", ASCENDING)], "nombre": "ix_mtto_tipo"},
    ],
    # ---------------- §11.10 seguimiento_eventos ----------------
    "seguimiento_eventos": [
        {"claves": [("viaje_id", ASCENDING), ("fecha_hora", ASCENDING)], "nombre": "ix_seguimiento_viaje_fecha"},
        {"claves": [("tipo_evento", ASCENDING)], "nombre": "ix_seguimiento_tipo_evento"},
    ],
    # ---------------- hecho_entrega (esquema fijado en la carga del DW) ------
    # Las dimensiones no llevan índices adicionales: se consultan por _id.
    "hecho_entrega": [
        {"claves": [("folio_entrega", ASCENDING)], "nombre": "ux_hecho_folio", "unico": True},
        {"claves": [("fecha_id", ASCENDING)], "nombre": "ix_hecho_fecha"},
        {"claves": [("ruta_id", ASCENDING), ("fecha_id", ASCENDING)], "nombre": "ix_hecho_ruta_fecha"},
        {"claves": [("vehiculo_id", ASCENDING)], "nombre": "ix_hecho_vehiculo"},
        {"claves": [("operador_id", ASCENDING)], "nombre": "ix_hecho_operador"},
        {"claves": [("cliente_id", ASCENDING)], "nombre": "ix_hecho_cliente"},
        {"claves": [("es_retraso", ASCENDING)], "nombre": "ix_hecho_es_retraso"},
        {"claves": [("calidad_dato", ASCENDING)], "nombre": "ix_hecho_calidad"},
    ],
}


def contar_indices_declarados(incluir_geo: bool = False) -> int:
    """Total de índices que se intentarán crear con la configuración dada."""
    total = 0
    for definiciones in INDICES.values():
        for definicion in definiciones:
            if definicion.get("geoespacial") and not incluir_geo:
                continue
            total += 1
    return total


def crear_indices(
    bd: Database,
    incluir_geo: bool = False,
    colecciones: list[str] | None = None,
) -> list[dict[str, Any]]:
    """
    Crea (de forma idempotente) los índices declarados en INDICES.

    `create_index` no falla si el índice ya existe con la misma
    especificación, por lo que este script puede ejecutarse las veces que
    haga falta.

    Devuelve una lista de resultados por índice para poder imprimirlos como
    evidencia de la actividad.
    """
    resultados: list[dict[str, Any]] = []
    objetivo = colecciones if colecciones is not None else list(INDICES.keys())

    for coleccion in objetivo:
        for definicion in INDICES.get(coleccion, []):
            nombre = definicion["nombre"]

            if definicion.get("geoespacial") and not incluir_geo:
                resultados.append({
                    "coleccion": coleccion,
                    "indice": nombre,
                    "estado": "OMITIDO",
                    "detalle": "Índice geoespacial: requiere confirmar el uso de GPS (SIGLOG_INDICE_GEO=true).",
                })
                continue

            try:
                bd[coleccion].create_index(
                    definicion["claves"],
                    name=nombre,
                    unique=bool(definicion.get("unico", False)),
                )
                resultados.append({
                    "coleccion": coleccion,
                    "indice": nombre,
                    "estado": "OK",
                    "detalle": "único" if definicion.get("unico") else "",
                })
            except OperationFailure as exc:
                resultados.append({
                    "coleccion": coleccion,
                    "indice": nombre,
                    "estado": "ERROR",
                    "detalle": str(exc),
                })

    return resultados


def listar_indices_existentes(bd: Database, coleccion: str) -> list[str]:
    """Nombres de los índices actualmente presentes en una colección."""
    try:
        return sorted(bd[coleccion].index_information().keys())
    except OperationFailure:
        return []
