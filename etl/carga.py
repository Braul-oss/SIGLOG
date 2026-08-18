"""
SIG-LOG — Sistema Integral de Gestión Logística
etl/carga.py

ACTIVIDAD PA-7 — CARGA DEL DATA WAREHOUSE
EVIDENCIA DE LA UNIDAD II (cierre del ETL)

Materializa el modelo dimensional en las colecciones analíticas de
MongoDB (§11, colecciones analíticas):

    hecho_entrega   una fila por entrega, con las 33 columnas del dataset
                    de PA-6 más la clave `fecha_id` hacia dim_tiempo.
    dim_tiempo      calendario de operación (una fila por fecha).
    dim_cliente     catálogo + perfil de entregas del cliente.
    dim_vehiculo    catálogo + métricas de PA-6 (rendimiento_real_km_l...).
    dim_operador    catálogo + métricas de PA-6 (porcentaje a tiempo...).
    dim_ruta        catálogo + perfil operativo de PA-6 (insumo del clustering).

Decisiones de la carga
----------------------
D-C1  Las referencias del DW se guardan como TEXTO (str del ObjectId).
      El DW es autocontenido: los joins son hecho↔dimensiones, nunca
      contra las colecciones operativas, y el texto sobrevive intacto el
      paso por CSV. `dim_tiempo._id` es un entero AAAAMMDD.
D-C2  La carga es IDEMPOTENTE: cada corrida reemplaza el contenido
      completo (delete_many + insert_many). El DW se reconstruye desde
      la fuente operativa, no se edita.
D-C3  Los índices de `hecho_entrega` quedaron declarados en
      database/indices.py (los crea esta actividad, como anunciaba la
      nota "se definirán en la actividad de ETL").

Escribir aquí NO viola §7.3: la restricción aplica a las colecciones
OPERATIVAS; las analíticas son precisamente la salida del ETL.

Uso
---
    python -m etl.carga
    python -m etl.carga --dry-run     # construye y verifica sin escribir
"""

from __future__ import annotations

import argparse
import contextlib
import io
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

import numpy as np
import pandas as pd

from config import settings
from config.mongo_conexion import cerrar_cliente, obtener_bd, verificar_conexion
from database.indices import crear_indices
from etl.enriquecimiento import dataset_rutas, metricas_operadores, metricas_vehiculos
from etl.exploracion import ruta_legible, titulo
from etl.transformacion import transformar

ARCHIVO_REPORTE = RAIZ / "data" / "outputs" / "reporte_carga.txt"

NOMBRES_DIA = ("LUNES", "MARTES", "MIERCOLES", "JUEVES",
               "VIERNES", "SABADO", "DOMINGO")
NOMBRES_MES = ("", "ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO",
               "JULIO", "AGOSTO", "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE")

DIMENSIONES = ("dim_tiempo", "dim_cliente", "dim_vehiculo",
               "dim_operador", "dim_ruta")


# ==========================================================================
# CONVERSIÓN DataFrame → documentos BSON
# ==========================================================================
def a_documentos(df: pd.DataFrame) -> list[dict[str, Any]]:
    """
    Convierte un DataFrame en documentos insertables por PyMongo.

    PyMongo no codifica escalares de NumPy ni pd.NA, así que todo valor
    se lleva a tipos nativos de Python y los faltantes quedan como None.
    """
    comunes = _comunes()
    documentos = []
    for registro in df.to_dict("records"):
        limpio: dict[str, Any] = dict(comunes)
        for clave, valor in registro.items():
            if valor is None or (isinstance(valor, float) and np.isnan(valor)) \
                    or valor is pd.NaT or valor is pd.NA:
                limpio[clave] = None
            elif isinstance(valor, np.generic):
                limpio[clave] = valor.item()
            elif isinstance(valor, pd.Timestamp):
                limpio[clave] = valor.to_pydatetime()
            else:
                limpio[clave] = valor
        documentos.append(limpio)
    return documentos


def _comunes() -> dict[str, Any]:
    return {"origen_dato": "SIMULADO",
            "fecha_carga": datetime.now(timezone.utc)}


# ==========================================================================
# CONSTRUCCIÓN DEL MODELO DIMENSIONAL
# ==========================================================================
def construir_hecho(dataset: pd.DataFrame) -> pd.DataFrame:
    """Hecho = dataset de PA-6 con ids en texto (D-C1) y clave fecha_id."""
    hecho = dataset.copy()
    for columna in ("viaje_id", "ruta_id", "cliente_id",
                    "vehiculo_id", "operador_id"):
        hecho[columna] = hecho[columna].astype(str)
    fecha = pd.to_datetime(hecho["fecha"], utc=True)
    hecho.insert(1, "fecha_id",
                 (fecha.dt.year * 10000 + fecha.dt.month * 100
                  + fecha.dt.day).astype(int))
    return hecho


def construir_dim_tiempo(hecho: pd.DataFrame) -> pd.DataFrame:
    fechas = pd.to_datetime(hecho["fecha"], utc=True).dt.normalize().drop_duplicates()
    dim = pd.DataFrame({"fecha": fechas.sort_values().reset_index(drop=True)})
    serie = pd.to_datetime(dim["fecha"], utc=True)
    dim.insert(0, "_id", (serie.dt.year * 10000 + serie.dt.month * 100
                          + serie.dt.day).astype(int))
    dim["anio"] = serie.dt.year
    dim["mes"] = serie.dt.month
    dim["nombre_mes"] = dim["mes"].map(lambda m: NOMBRES_MES[m])
    dim["dia"] = serie.dt.day
    dim["dia_semana"] = serie.dt.dayofweek
    dim["nombre_dia"] = dim["dia_semana"].map(lambda d: NOMBRES_DIA[d])
    dim["es_fin_semana"] = (dim["dia_semana"] >= 5).astype(int)
    dim["trimestre"] = serie.dt.quarter
    dim["semana_anio"] = serie.dt.isocalendar().week.astype(int)
    return dim


def _municipio_principal(direcciones: Any) -> str | None:
    """Municipio de la dirección marcada como principal (o la primera)."""
    if not isinstance(direcciones, list) or not direcciones:
        return None
    principal = next((d for d in direcciones if d.get("principal")), direcciones[0])
    return principal.get("municipio")


def construir_dim_cliente(hecho: pd.DataFrame, bd=None) -> pd.DataFrame:
    from etl import extraccion
    clientes = extraccion.extraer("clientes", bd=bd)[
        ["_id", "codigo_cliente", "nombre", "tipo_cliente", "direcciones"]]
    clientes["_id"] = clientes["_id"].astype(str)

    # §14.2 pide `municipio` y `zona` en la dimensión. El municipio sale de
    # la dirección marcada como principal; la zona no vive en el cliente,
    # sino en las rutas que lo atienden, así que se toma la más frecuente.
    clientes["municipio"] = clientes["direcciones"].map(_municipio_principal)
    zonas = (hecho.groupby("cliente_id")["zona"]
             .agg(lambda s: s.mode().iat[0] if not s.mode().empty else None)
             .rename("zona"))
    clientes = clientes.drop(columns=["direcciones"]).merge(
        zonas.reset_index().rename(columns={"cliente_id": "_id"}),
        on="_id", how="left")

    ok = hecho[hecho["calidad_dato"] == "OK"]
    perfil = (ok.assign(retrasada=(ok["es_retraso"] == 1).astype(int))
              .groupby("cliente_id")
              .agg(entregas=("folio_entrega", "count"),
                   retraso_medio_min=("retraso_min", "mean"),
                   pct_entregas_retrasadas=("retrasada", "mean")))
    perfil["retraso_medio_min"] = perfil["retraso_medio_min"].round(1)
    perfil["pct_entregas_retrasadas"] = (100 * perfil["pct_entregas_retrasadas"]).round(1)

    return clientes.merge(perfil.reset_index().rename(columns={"cliente_id": "_id"}),
                          on="_id", how="left")


def _con_id_texto(df: pd.DataFrame, columna_id: str) -> pd.DataFrame:
    dim = df.rename(columns={columna_id: "_id"}).copy()
    dim["_id"] = dim["_id"].astype(str)
    return dim


def construir_dimensiones(hecho: pd.DataFrame, bd=None) -> dict[str, pd.DataFrame]:
    entregas_para_metricas = hecho          # ya tiene ids en texto
    return {
        "dim_tiempo": construir_dim_tiempo(hecho),
        "dim_cliente": construir_dim_cliente(hecho, bd=bd),
        "dim_vehiculo": _con_id_texto(metricas_vehiculos(bd=bd), "vehiculo_id"),
        "dim_operador": _con_id_texto(
            metricas_operadores(entregas_para_metricas, bd=bd), "operador_id"),
        "dim_ruta": _con_id_texto(
            dataset_rutas(entregas_para_metricas, bd=bd), "ruta_id"),
    }


# ==========================================================================
# CARGA IDEMPOTENTE  (D-C2)
# ==========================================================================
def cargar_dw(bd, hecho: pd.DataFrame,
              dimensiones: dict[str, pd.DataFrame]) -> dict[str, int]:
    conteos: dict[str, int] = {}
    for nombre, df in {"hecho_entrega": hecho, **dimensiones}.items():
        bd[nombre].delete_many({})
        bd[nombre].insert_many(a_documentos(df), ordered=False)
        conteos[nombre] = bd[nombre].count_documents({})
    return conteos


# ==========================================================================
# VERIFICACIONES AUTOMÁTICAS
# ==========================================================================
def verificar(bd, hecho: pd.DataFrame,
              dimensiones: dict[str, pd.DataFrame]) -> list[tuple[str, bool, str]]:
    resultados = []
    for nombre, df in {"hecho_entrega": hecho, **dimensiones}.items():
        en_bd = bd[nombre].count_documents({})
        resultados.append((f"{nombre}: documentos cargados", en_bd == len(df),
                           f"{en_bd:,} de {len(df):,}"))

    # Integridad hecho → dimensiones (sobre lo cargado en Atlas)
    referencias = (
        ("fecha_id", "dim_tiempo"), ("cliente_id", "dim_cliente"),
        ("vehiculo_id", "dim_vehiculo"), ("operador_id", "dim_operador"),
        ("ruta_id", "dim_ruta"),
    )
    for campo, dimension in referencias:
        ids_dim = {d["_id"] for d in bd[dimension].find({}, {"_id": 1})}
        huerfanos = sum(1 for d in bd["hecho_entrega"].aggregate(
            [{"$group": {"_id": f"${campo}"}}]) if d["_id"] not in ids_dim)
        resultados.append((f"hecho.{campo} → {dimension}", huerfanos == 0,
                           "sin huérfanos" if huerfanos == 0
                           else f"{huerfanos} valores huérfanos"))

    ejemplo = bd["hecho_entrega"].find_one({"calidad_dato": "OK"})
    campos_clave = {"folio_entrega", "fecha_id", "retraso_min", "es_retraso",
                    "franja_horaria", "origen_dato"}
    faltantes = sorted(campos_clave - set(ejemplo)) if ejemplo else []
    resultados.append(("Documento de hecho con campos clave",
                       ejemplo is not None and not faltantes,
                       "verificado" if ejemplo and not faltantes
                       else f"faltan: {faltantes}" if ejemplo else "colección vacía"))

    # Regla académica: ningún documento puede confundirse con dato real.
    sin_marca = sum(bd[c].count_documents({"origen_dato": {"$ne": "SIMULADO"}})
                    for c in ("hecho_entrega", *DIMENSIONES))
    resultados.append(("Todo el DW marcado origen_dato=SIMULADO", sin_marca == 0,
                       "completo" if sin_marca == 0 else f"{sin_marca} sin marca"))
    return resultados


def imprimir_verificaciones(resultados: list[tuple[str, bool, str]]) -> bool:
    titulo("3 · VERIFICACIONES AUTOMÁTICAS")
    for nombre, ok, detalle in resultados:
        print(f"  {'[OK]   ' if ok else '[FALLA]'} {nombre:<44}{detalle}")
    fallos = sum(1 for _, ok, _ in resultados if not ok)
    print("-" * 78)
    print(f"  {len(resultados) - fallos}/{len(resultados)} verificaciones correctas")
    return fallos == 0


# ==========================================================================
# EJECUCIÓN COMPLETA (reutilizable por run_etl)
# ==========================================================================
def ejecutar_carga(bd, dataset: pd.DataFrame, aplicar: bool = True
                   ) -> tuple[int, pd.DataFrame, dict[str, pd.DataFrame]]:
    """Construye el modelo dimensional y, si `aplicar`, lo carga y verifica.
    Devuelve (código de salida, hecho, dimensiones)."""
    hecho = construir_hecho(dataset)
    dimensiones = construir_dimensiones(hecho, bd=bd)

    titulo("1 · MODELO DIMENSIONAL CONSTRUIDO")
    print(f"  {'COLECCIÓN':<18}{'FILAS':>8}   {'COLUMNAS':>8}")
    print("-" * 78)
    for nombre, df in {"hecho_entrega": hecho, **dimensiones}.items():
        print(f"  {nombre:<18}{len(df):>8,}   {df.shape[1]:>8}")

    if not aplicar:
        print("\n  --dry-run activo: no se escribió nada en MongoDB.")
        return 0, hecho, dimensiones

    titulo("2 · CARGA EN MONGODB ATLAS  (idempotente, D-C2)")
    conteos = cargar_dw(bd, hecho, dimensiones)
    for nombre, n in conteos.items():
        print(f"  {nombre:<18}{n:>8,} documentos")

    print("\n  Índices de hecho_entrega (D-C3, declarados en database/indices.py):")
    for resultado in crear_indices(bd, colecciones=["hecho_entrega"]):
        print(f"      [{resultado['estado']}] {resultado['indice']}")

    ok = imprimir_verificaciones(verificar(bd, hecho, dimensiones))
    return (0 if ok else 1), hecho, dimensiones


# ==========================================================================
# PUNTO DE ENTRADA
# ==========================================================================
def main() -> int:
    parser = argparse.ArgumentParser(
        description="PA-7 — Carga del data warehouse (hecho_entrega + dimensiones).",
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Construye el modelo y lo muestra sin escribir en MongoDB.")
    parser.add_argument("--sin-archivos", action="store_true",
                        help="No escribe el reporte de texto.")
    args = parser.parse_args()

    if not verificar_conexion(verbose=True)["exito"]:
        return 1

    memoria = io.StringIO()
    codigo = 0

    try:
        with contextlib.redirect_stdout(memoria):
            titulo("SIG-LOG · CARGA DEL DATA WAREHOUSE (PA-7) — UNIDAD II")
            print("  Los datos cargados son SIMULADOS (decisión C-02).")
            print("\n  Ejecutando el pipeline (limpieza + transformación de PA-5/PA-6)...")

            bd = obtener_bd()
            dataset, _ = transformar(bd=bd)
            codigo, _, _ = ejecutar_carga(bd, dataset, aplicar=not args.dry_run)

            print()
            print("=" * 78)
            if codigo == 0:
                print("  PA-7 TERMINADA. El DW está listo para KPIs, gráficas y ML.")
            else:
                print("  PA-7 TERMINADA CON FALLAS: revisa las verificaciones.")
            print("=" * 78)

    except SystemExit as salida:
        codigo = int(salida.code or 0)
    except Exception:                              # noqa: BLE001
        codigo = 1
        memoria.write("\n" + "=" * 78 + "\n  ERROR DURANTE LA CARGA\n" + "=" * 78 + "\n")
        memoria.write(traceback.format_exc())
    finally:
        cerrar_cliente()

    reporte = memoria.getvalue()
    print(reporte)

    if not args.sin_archivos and reporte:
        try:
            ARCHIVO_REPORTE.parent.mkdir(parents=True, exist_ok=True)
            ARCHIVO_REPORTE.write_text(reporte, encoding="utf-8")
        except OSError as exc:
            print(f"  No se pudo escribir {ARCHIVO_REPORTE}: {exc}")

    return codigo


if __name__ == "__main__":
    sys.exit(main())
