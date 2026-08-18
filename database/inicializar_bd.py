"""
SIG-LOG — Sistema Integral de Gestión Logística
database/inicializar_bd.py

Propósito
---------
Script ejecutable que deja la base de datos `siglog` de MongoDB Atlas lista
para operar: crea las colecciones del diseño (§11), les aplica el validador
de esquema y crea los índices declarados en §11.1–§11.10.

Es **idempotente**: puede ejecutarse las veces que sea necesario. Si una
colección ya existe, no la borra ni la vacía; solo actualiza su validador.
Este script NUNCA inserta datos.

Uso
---
    python -m database.inicializar_bd                # crea todo
    python -m database.inicializar_bd --verificar    # solo prueba de conexión
    python -m database.inicializar_bd --reporte      # estado actual + conteos
    python -m database.inicializar_bd --solo-operativas
    python -m database.inicializar_bd --validacion off
    python -m database.inicializar_bd --incluir-geo
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

# Permite ejecutar el archivo directamente además de con  python -m
RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from pymongo.database import Database
from pymongo.errors import OperationFailure, PyMongoError

from config import settings
from config.mongo_conexion import cerrar_cliente, obtener_bd, verificar_conexion
from database.esquemas.validadores import VALIDADORES
from database.indices import INDICES, crear_indices, listar_indices_existentes

LINEA = "=" * 72
SUBLINEA = "-" * 72


# --------------------------------------------------------------------------
# Creación de colecciones
# --------------------------------------------------------------------------
def crear_colecciones(
    bd: Database,
    colecciones: tuple[str, ...],
    validacion: str = "warn",
) -> list[dict[str, Any]]:
    """
    Crea las colecciones indicadas y aplica su validador de esquema.

    validacion:
        "warn"  -> el documento inválido se registra pero SÍ se guarda
        "error" -> el documento inválido se rechaza
        "off"   -> la colección se crea sin validador
    """
    existentes = set(bd.list_collection_names())
    resultados: list[dict[str, Any]] = []

    for nombre in colecciones:
        validador = VALIDADORES.get(nombre) if validacion != "off" else None
        opciones: dict[str, Any] = {}
        if validador is not None:
            opciones = {
                "validator": validador,
                "validationLevel": "moderate",
                "validationAction": validacion,
            }

        try:
            if nombre not in existentes:
                bd.create_collection(nombre, **opciones)
                estado = "CREADA"
            else:
                if opciones:
                    bd.command({"collMod": nombre, **opciones})
                    estado = "YA EXISTÍA (validador actualizado)"
                else:
                    estado = "YA EXISTÍA"

            detalle = (
                f"validador={validacion}" if validador is not None else "sin validador"
            )
            resultados.append({"coleccion": nombre, "estado": estado, "detalle": detalle})

        except OperationFailure as exc:
            resultados.append({"coleccion": nombre, "estado": "ERROR", "detalle": str(exc)})

    return resultados


# --------------------------------------------------------------------------
# Impresión de resultados
# --------------------------------------------------------------------------
def _encabezado(titulo: str) -> None:
    print()
    print(LINEA)
    print(f"  {titulo}")
    print(LINEA)


def _imprimir_colecciones(resultados: list[dict[str, Any]]) -> None:
    print(f"  {'COLECCIÓN':<24}{'ESTADO':<34}DETALLE")
    print(SUBLINEA)
    for fila in resultados:
        print(f"  {fila['coleccion']:<24}{fila['estado']:<34}{fila['detalle']}")
    creadas = sum(1 for f in resultados if f["estado"] == "CREADA")
    errores = sum(1 for f in resultados if f["estado"] == "ERROR")
    print(SUBLINEA)
    print(f"  Total: {len(resultados)}  |  Nuevas: {creadas}  |  Errores: {errores}")


def _imprimir_indices(resultados: list[dict[str, Any]]) -> None:
    print(f"  {'COLECCIÓN':<24}{'ÍNDICE':<34}ESTADO")
    print(SUBLINEA)
    for fila in resultados:
        sufijo = f"  ({fila['detalle']})" if fila["detalle"] and fila["estado"] != "OK" else ""
        marca = fila["detalle"] if fila["estado"] == "OK" and fila["detalle"] else ""
        print(f"  {fila['coleccion']:<24}{fila['indice']:<34}{fila['estado']}{marca and ' · ' + marca}{sufijo}")
    ok = sum(1 for f in resultados if f["estado"] == "OK")
    omitidos = sum(1 for f in resultados if f["estado"] == "OMITIDO")
    errores = sum(1 for f in resultados if f["estado"] == "ERROR")
    print(SUBLINEA)
    print(f"  Índices OK: {ok}  |  Omitidos: {omitidos}  |  Errores: {errores}")


def imprimir_reporte(bd: Database) -> None:
    """Estado actual de la base: colecciones, documentos e índices."""
    _encabezado(f"ESTADO ACTUAL DE LA BASE DE DATOS '{bd.name}'")
    existentes = set(bd.list_collection_names())
    print(f"  {'COLECCIÓN':<24}{'DOCUMENTOS':>12}   ÍNDICES")
    print(SUBLINEA)
    total_docs = 0
    for nombre in settings.TODAS_LAS_COLECCIONES:
        if nombre not in existentes:
            print(f"  {nombre:<24}{'NO EXISTE':>12}")
            continue
        conteo = bd[nombre].count_documents({})
        total_docs += conteo
        indices = listar_indices_existentes(bd, nombre)
        print(f"  {nombre:<24}{conteo:>12}   {len(indices)}: {', '.join(indices)}")
    print(SUBLINEA)
    print(f"  Documentos totales: {total_docs}")
    huerfanas = sorted(existentes - set(settings.TODAS_LAS_COLECCIONES))
    if huerfanas:
        print(f"  Colecciones fuera del diseño: {', '.join(huerfanas)}")


# --------------------------------------------------------------------------
# Punto de entrada
# --------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(
        description="Inicializa la base de datos siglog en MongoDB Atlas (colecciones e índices).",
    )
    parser.add_argument("--verificar", action="store_true",
                        help="Solo comprueba la conexión y termina.")
    parser.add_argument("--reporte", action="store_true",
                        help="Muestra el estado actual (colecciones, documentos, índices) y termina.")
    parser.add_argument("--solo-operativas", action="store_true",
                        help="Crea únicamente las 10 colecciones operativas.")
    parser.add_argument("--sin-indices", action="store_true",
                        help="Crea las colecciones pero no los índices.")
    parser.add_argument("--incluir-geo", action="store_true",
                        help="Crea también el índice 2dsphere de clientes.direcciones.ubicacion.")
    parser.add_argument("--validacion", choices=["warn", "error", "off"],
                        default=settings.NIVEL_VALIDACION,
                        help="Acción del validador de esquema (por defecto: warn).")
    args = parser.parse_args()

    # 1) Conexión ---------------------------------------------------------
    respuesta = verificar_conexion(verbose=True)
    if not respuesta["exito"]:
        return 1
    if args.verificar:
        return 0

    bd = obtener_bd()

    try:
        if args.reporte:
            imprimir_reporte(bd)
            return 0

        # 2) Colecciones --------------------------------------------------
        objetivo = (
            settings.COLECCIONES_OPERATIVAS
            if args.solo_operativas
            else settings.TODAS_LAS_COLECCIONES
        )
        _encabezado("PASO 1 — CREACIÓN DE COLECCIONES")
        _imprimir_colecciones(crear_colecciones(bd, objetivo, validacion=args.validacion))

        # 3) Índices ------------------------------------------------------
        if args.sin_indices:
            print("\n  (Índices omitidos por --sin-indices)")
        else:
            incluir_geo = args.incluir_geo or settings.CREAR_INDICE_GEOESPACIAL
            colecciones_con_indice = [c for c in objetivo if c in INDICES]
            _encabezado("PASO 2 — CREACIÓN DE ÍNDICES")
            _imprimir_indices(
                crear_indices(bd, incluir_geo=incluir_geo, colecciones=colecciones_con_indice)
            )

        # 4) Reporte final ------------------------------------------------
        imprimir_reporte(bd)
        print()
        print(LINEA)
        print("  INICIALIZACIÓN TERMINADA. No se insertó ningún documento.")
        print(LINEA)
        return 0

    except PyMongoError as exc:
        print(f"\n  ERROR de MongoDB: {exc}")
        return 1
    finally:
        cerrar_cliente()


if __name__ == "__main__":
    sys.exit(main())
