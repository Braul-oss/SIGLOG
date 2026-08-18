"""
SIG-LOG — Sistema Integral de Gestión Logística
etl/limpieza.py

ACTIVIDAD PA-5 — LIMPIEZA DE DATOS
EVIDENCIA DE LA UNIDAD II (preparación de datos)

Parte del reporte de calidad de PA-3 y de las conclusiones de la
exploración de PA-4, que dejaron el diagnóstico por escrito:

    · 72 documentos duplicados por doble captura (folio terminado en "-D").
    · Nulos con DOS orígenes: legítimos (entregas CANCELADAS, que nunca
      ocurrieron) y de captura omitida (~3%, defecto real).
    · Outliers por IQR que incluyen retrasos legítimos por incidentes
      graves: la recomendación de PA-4 es MARCARLOS, no eliminarlos.

Decisiones de limpieza (D-L1 a D-L5)
------------------------------------
D-L1  Duplicados: se elimina la copia de la doble captura y se conserva el
      folio original. Clave de negocio: (viaje_id, cliente_id, orden_parada).
D-L2  Nulos legítimos (estatus CANCELADA): se CONSERVAN. Imputar la hora de
      una entrega que nunca ocurrió sería inventar datos.
D-L3  Nulos de captura omitida: se CONSERVAN pero quedan marcados. La
      columna perdida es la variable objetivo (`retraso_min`): imputarla
      contaminaría el entrenamiento, y borrar la fila distorsionaría los
      conteos operativos. PA-6 los excluye del dataset de ML filtrando
      por `calidad_dato`.
D-L4  Imputación categórica única: `causa_retraso = "NINGUNA"` en entregas
      a tiempo, donde el nulo significa "no aplica", no "se desconoce".
D-L5  Outliers: columna `es_outlier_iqr` calculada con la regla
      Q1 − 1.5·IQR / Q3 + 1.5·IQR sobre `retraso_min`. No se elimina
      ninguna fila por ser outlier.

Columnas que agrega esta actividad
----------------------------------
    calidad_dato    OK | SIN_HORA_REAL | NULO_LEGITIMO
    es_outlier_iqr  1 | 0 | <NA> (cuando retraso_min es nulo)

El ETL lee de MongoDB y NUNCA escribe en las colecciones operativas (§7.3).
La salida limpia va a data/processed/entregas_limpias.csv.

Uso
---
    python -m etl.limpieza
    python -m etl.limpieza --sin-archivos    # solo consola, no escribe nada
"""

from __future__ import annotations

import argparse
import contextlib
import io
import sys
import traceback
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

import numpy as np
import pandas as pd

from config import settings
from config.mongo_conexion import cerrar_cliente, obtener_bd, verificar_conexion
from etl import extraccion
from etl.exploracion import ruta_legible, subtitulo, titulo

CARPETA_PROCESSED = RAIZ / "data" / "processed"
ARCHIVO_LIMPIO = CARPETA_PROCESSED / "entregas_limpias.csv"
ARCHIVO_REPORTE = RAIZ / "data" / "outputs" / "reporte_limpieza.txt"

# Clave de negocio de una entrega: una parada de un viaje atiende a un
# cliente exactamente una vez (misma clave usada por PA-3 para detectarlos).
CLAVE_NEGOCIO = ["viaje_id", "cliente_id", "orden_parada"]

# Valores admitidos de las columnas de catálogo (RNP-08 y RNP-12 + D-L4).
CATALOGOS = {
    "estatus": set(settings.CATALOGO_ESTATUS_ENTREGA),
    "causa_retraso": set(settings.CATALOGO_TIPOS_INCIDENTE) | {"NINGUNA"},
}

ETIQUETAS_CALIDAD = ("OK", "SIN_HORA_REAL", "NULO_LEGITIMO")


# ==========================================================================
# 1 · DUPLICADOS  (D-L1)
# ==========================================================================
def quitar_duplicados(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    """
    Elimina las dobles capturas conservando el folio original.

    La copia lleva el folio original + "-D", así que al ordenar por
    `folio_entrega` el original queda primero y `keep="first"` lo conserva.
    """
    duplicada = df.sort_values("folio_entrega").duplicated(CLAVE_NEGOCIO, keep="first")
    duplicada = duplicada.reindex(df.index)

    eliminados = df.loc[duplicada]
    limpio = df.loc[~duplicada].copy()
    return limpio, {
        "grupos": int(df.duplicated(CLAVE_NEGOCIO, keep=False).sum() - len(eliminados)),
        "eliminados": len(eliminados),
        "folios_ejemplo": eliminados["folio_entrega"].head(3).tolist(),
    }


# ==========================================================================
# 2 · NULOS  (D-L2, D-L3, D-L4)
# ==========================================================================
def clasificar_calidad(df: pd.DataFrame) -> pd.DataFrame:
    """
    Agrega `calidad_dato` separando los dos orígenes de nulos que
    diagnosticó PA-4 (sección 6 del reporte de exploración).
    """
    copia = df.copy()
    sin_hora = copia["hora_real_llegada"].isna()
    cancelada = copia["estatus"] == "CANCELADA"

    copia["calidad_dato"] = np.select(
        [cancelada, sin_hora],
        ["NULO_LEGITIMO", "SIN_HORA_REAL"],
        default="OK",
    )
    return copia


def imputar_causa(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """
    D-L4: en las entregas a tiempo (`es_retraso == 0`) el nulo de
    `causa_retraso` significa "no aplica". Se vuelve explícito con la
    categoría NINGUNA para que la columna sea utilizable en agregaciones
    y como variable categórica. Los nulos de las filas SIN_HORA_REAL y
    CANCELADA se conservan: ahí sí se desconoce la causa.
    """
    copia = df.copy()
    imputable = copia["causa_retraso"].isna() & (copia["es_retraso"] == 0)
    copia.loc[imputable, "causa_retraso"] = "NINGUNA"
    return copia, int(imputable.sum())


# ==========================================================================
# 3 · OUTLIERS  (D-L5)
# ==========================================================================
def marcar_outliers(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, float]]:
    """
    Marca los outliers de `retraso_min` con la regla IQR vista en clase.

    Conclusión 5 de PA-4: muchos outliers son retrasos legítimos causados
    por incidentes graves; eliminarlos borraría precisamente los casos que
    el modelo de riesgo debe aprender. Se marcan y la decisión de uso se
    toma por análisis (PA-6 y los modelos deciden con la marca a la vista).
    """
    copia = df.copy()
    serie = copia["retraso_min"].dropna()
    q1, q3 = serie.quantile([0.25, 0.75])
    iqr = q3 - q1
    inferior, superior = q1 - 1.5 * iqr, q3 + 1.5 * iqr

    fuera = (copia["retraso_min"] < inferior) | (copia["retraso_min"] > superior)
    copia["es_outlier_iqr"] = fuera.astype("Int64").mask(copia["retraso_min"].isna())
    return copia, {
        "q1": float(q1), "q3": float(q3), "iqr": float(iqr),
        "inferior": float(inferior), "superior": float(superior),
        "marcados": int(fuera.sum()),
    }


# ==========================================================================
# 4 · NORMALIZACIÓN LIGERA DE TIPOS Y TEXTO
# ==========================================================================
def normalizar(df: pd.DataFrame) -> pd.DataFrame:
    """
    Deja los tipos listos para PA-6: fechas como datetime, `es_retraso`
    como entero anulable y texto de catálogo sin espacios accidentales.
    No toca el texto libre (`observaciones`): ese lo decide PA-6.
    """
    copia = df.copy()
    for columna in ("fecha", "hora_estimada_llegada", "hora_real_llegada"):
        copia[columna] = pd.to_datetime(copia[columna], errors="coerce", utc=True)
    copia["es_retraso"] = copia["es_retraso"].astype("Int64")
    for columna in ("estatus", "causa_retraso"):
        copia[columna] = copia[columna].str.strip().where(copia[columna].notna())
    return copia


def validar_catalogos(df: pd.DataFrame) -> list[tuple[str, int, list[str]]]:
    """Valores fuera de catálogo por columna: (columna, filas, ejemplos)."""
    hallazgos = []
    for columna, admitidos in CATALOGOS.items():
        fuera = df[columna].dropna().loc[lambda s: ~s.isin(admitidos)]
        hallazgos.append((columna, len(fuera), sorted(set(fuera))[:5]))
    return hallazgos


# ==========================================================================
# PIPELINE COMPLETO
# ==========================================================================
def limpiar_entregas(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Aplica D-L1…D-L5 en orden y devuelve el DataFrame limpio + bitácora."""
    bitacora: dict[str, Any] = {"filas_entrada": len(df)}

    df = normalizar(df)
    df, bitacora["duplicados"] = quitar_duplicados(df)
    df = clasificar_calidad(df)
    df, bitacora["causas_imputadas"] = imputar_causa(df)
    df, bitacora["outliers"] = marcar_outliers(df)

    bitacora["filas_salida"] = len(df)
    bitacora["calidad"] = df["calidad_dato"].value_counts().to_dict()
    bitacora["catalogos"] = validar_catalogos(df)
    return df, bitacora


def cargar_entregas_limpias(ruta: Path = ARCHIVO_LIMPIO) -> pd.DataFrame:
    """
    Punto de lectura para PA-6: recupera el CSV limpio con los tipos
    correctos (el CSV no conserva dtypes por sí mismo).
    """
    df = pd.read_csv(ruta, dtype={"calidad_dato": "string"})
    # Conversión explícita con format="ISO8601": pandas 2.x infiere el
    # formato de la primera fila y descartaría las horas sin microsegundos.
    for columna in ("fecha", "hora_estimada_llegada", "hora_real_llegada"):
        df[columna] = pd.to_datetime(df[columna], format="ISO8601", utc=True)
    df["es_retraso"] = df["es_retraso"].astype("Int64")
    df["es_outlier_iqr"] = df["es_outlier_iqr"].astype("Int64")
    return df


# ==========================================================================
# VERIFICACIONES AUTOMÁTICAS  (la prueba de la actividad)
# ==========================================================================
def verificar(df: pd.DataFrame, bitacora: dict[str, Any]) -> list[tuple[str, bool, str]]:
    duplicados_restantes = int(df.duplicated(CLAVE_NEGOCIO).sum())
    ok_sin_nulos = df.loc[df["calidad_dato"] == "OK",
                          ["hora_real_llegada", "retraso_min", "es_retraso"]]
    canceladas_mal = int(((df["estatus"] == "CANCELADA")
                          & (df["calidad_dato"] != "NULO_LEGITIMO")).sum())
    causa_nula_ok = int((df["causa_retraso"].isna()
                         & (df["calidad_dato"] == "OK")
                         & (df["es_retraso"] == 0)).sum())
    catalogos_fuera = sum(n for _, n, _ in bitacora["catalogos"])
    esperadas = bitacora["filas_entrada"] - bitacora["duplicados"]["eliminados"]

    return [
        ("Sin duplicados por clave de negocio", duplicados_restantes == 0,
         f"{duplicados_restantes} restantes"),
        ("Conteo de filas = entrada − duplicados", len(df) == esperadas,
         f"{len(df):,} de {esperadas:,} esperadas"),
        ("Filas OK sin nulos en columnas de llegada", not ok_sin_nulos.isna().any().any(),
         f"{int(ok_sin_nulos.isna().any(axis=1).sum())} filas OK con nulos"),
        ("Toda CANCELADA marcada NULO_LEGITIMO", canceladas_mal == 0,
         f"{canceladas_mal} mal clasificadas"),
        ("Sin causa nula en entregas a tiempo OK", causa_nula_ok == 0,
         f"{causa_nula_ok} sin imputar"),
        ("Valores dentro de catálogo (RNP-08/12)", catalogos_fuera == 0,
         f"{catalogos_fuera} valores fuera de catálogo"),
        ("Ningún outlier eliminado (D-L5)", "es_outlier_iqr" in df.columns,
         "columna de marca presente"),
    ]


# ==========================================================================
# REPORTE
# ==========================================================================
def imprimir_reporte(df: pd.DataFrame, bitacora: dict[str, Any]) -> None:
    dup = bitacora["duplicados"]
    out = bitacora["outliers"]

    titulo("1 · DUPLICADOS POR DOBLE CAPTURA  (D-L1)")
    print(f"  Filas de entrada ........... {bitacora['filas_entrada']:,}")
    print(f"  Copias eliminadas .......... {dup['eliminados']}")
    print(f"  Ejemplos de folio retirado . {', '.join(dup['folios_ejemplo'])}")
    print(f"  Filas tras la limpieza ..... {bitacora['filas_salida']:,}")

    titulo("2 · CLASIFICACIÓN DE NULOS  (D-L2 / D-L3)")
    for etiqueta in ETIQUETAS_CALIDAD:
        n = bitacora["calidad"].get(etiqueta, 0)
        detalle = {
            "OK": "completas: dataset de análisis y ML",
            "SIN_HORA_REAL": "captura omitida: se conservan marcadas, fuera del ML",
            "NULO_LEGITIMO": "canceladas: el nulo es correcto, no se imputa",
        }[etiqueta]
        print(f"  {etiqueta:<16}{n:>8,}  ({n/bitacora['filas_salida']:.1%})  {detalle}")

    titulo("3 · IMPUTACIÓN CATEGÓRICA  (D-L4)")
    print(f"  causa_retraso = NINGUNA en {bitacora['causas_imputadas']:,} entregas a tiempo.")
    print("  El nulo ahí significaba 'no aplica', no 'se desconoce'.")

    titulo("4 · OUTLIERS MARCADOS, NO ELIMINADOS  (D-L5)")
    print(f"  Q1 {out['q1']:.1f} · Q3 {out['q3']:.1f} · IQR {out['iqr']:.1f}"
          f" · límites {out['inferior']:.1f} a {out['superior']:.1f} min")
    print(f"  Marcados con es_outlier_iqr = 1: {out['marcados']:,}")
    print("  Motivo (conclusión 5 de PA-4): incluyen retrasos legítimos por")
    print("  incidentes graves, justo los casos que el modelo debe conocer.")

    titulo("5 · VALIDACIÓN DE CATÁLOGOS  (RNP-08 / RNP-12)")
    for columna, n, ejemplos in bitacora["catalogos"]:
        estado = "OK" if n == 0 else f"{n} fuera de catálogo: {ejemplos}"
        print(f"  {columna:<28}{estado}")


def imprimir_verificaciones(resultados: list[tuple[str, bool, str]]) -> bool:
    titulo("6 · VERIFICACIONES AUTOMÁTICAS")
    for nombre, ok, detalle in resultados:
        print(f"  {'[OK]   ' if ok else '[FALLA]'} {nombre:<42}{detalle}")
    fallos = sum(1 for _, ok, _ in resultados if not ok)
    print("-" * 78)
    print(f"  {len(resultados) - fallos}/{len(resultados)} verificaciones correctas")
    return fallos == 0


# ==========================================================================
# PUNTO DE ENTRADA
# ==========================================================================
def main() -> int:
    parser = argparse.ArgumentParser(
        description="PA-5 — Limpieza de datos. Evidencia de la Unidad II.",
    )
    parser.add_argument("--sin-archivos", action="store_true",
                        help="No escribe el CSV limpio ni el reporte de texto.")
    args = parser.parse_args()

    if not verificar_conexion(verbose=True)["exito"]:
        return 1

    memoria = io.StringIO()
    codigo = 0

    try:
        with contextlib.redirect_stdout(memoria):
            titulo("SIG-LOG · LIMPIEZA DE DATOS (PA-5) — EVIDENCIA DE LA UNIDAD II")
            print("  Los datos analizados son SIMULADOS (decisión C-02).")

            print("\n  Extrayendo `entregas` desde MongoDB Atlas...")
            df = extraccion.extraer("entregas")
            if df.empty:
                print("  La colección `entregas` está vacía. Ejecuta primero el seed.")
                raise SystemExit(1)

            limpio, bitacora = limpiar_entregas(df)
            imprimir_reporte(limpio, bitacora)
            if not imprimir_verificaciones(verificar(limpio, bitacora)):
                codigo = 1

            if not args.sin_archivos:
                CARPETA_PROCESSED.mkdir(parents=True, exist_ok=True)
                extraccion.aplanar_para_csv(limpio).to_csv(
                    ARCHIVO_LIMPIO, index=False, encoding="utf-8")
                titulo("ARCHIVOS GENERADOS")
                print(f"  {ruta_legible(ARCHIVO_LIMPIO):<40}"
                      f"{ARCHIVO_LIMPIO.stat().st_size/1024:>8.0f} KB")
                print(f"  {ruta_legible(ARCHIVO_REPORTE)}")
                print("\n  PA-6 debe leerlo con etl.limpieza.cargar_entregas_limpias()")
                print("  para recuperar los tipos correctos.")

            print()
            print("=" * 78)
            if codigo == 0:
                print("  PA-5 TERMINADA. Siguiente actividad: PA-6 (transformación).")
            else:
                print("  PA-5 TERMINADA CON FALLAS: revisa las verificaciones.")
            print("=" * 78)

    except SystemExit as salida:
        codigo = int(salida.code or 0)
    except Exception:                              # noqa: BLE001
        codigo = 1
        memoria.write("\n" + "=" * 78 + "\n  ERROR DURANTE LA LIMPIEZA\n" + "=" * 78 + "\n")
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
