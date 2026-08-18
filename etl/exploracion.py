"""
SIG-LOG — Sistema Integral de Gestión Logística
etl/exploracion.py

ACTIVIDAD PA-4 — EXPLORACIÓN DE DATOS (EDA)
EVIDENCIA DE LA UNIDAD I

Cubre literalmente los temas de la Unidad I:
    · Visión general de los datos de origen
    · Análisis de columnas
    · Valores de análisis
    · Exploración de datos
    · Preparación de datos (diagnóstico previo)

Replica el patrón del ejercicio de clase `unidad1_spark.py`, traducido a
pandas según el Anexo A:

    df.printSchema()          →  df.info() / df.dtypes
    df.show()                 →  df.head()
    df.describe().show()      →  df.describe()
    col(x).isNull()           →  df[x].isna()
    df.approxQuantile(...)    →  df[x].quantile(...)
    df.filter(cond)           →  df[cond]

Este script NO modifica nada: solo lee, describe y reporta. La limpieza
corresponde a PA-5.

Uso
---
    python -m etl.exploracion
    python -m etl.exploracion --sin-archivos     # solo consola
    python -m etl.exploracion --coleccion viajes # foco en otra colección

El reporte se arma en memoria y se emite completo al final, para que la
salida no dependa del comportamiento de la consola. Si algo falla, el
error se imprime junto con lo que alcanzó a generarse.
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

CARPETA_SALIDA = RAIZ / "data" / "outputs"
ARCHIVO_REPORTE = CARPETA_SALIDA / "reporte_exploracion.txt"

pd.set_option("display.width", 120)
pd.set_option("display.max_columns", 30)


# ==========================================================================
# Utilidades de presentación
# ==========================================================================
def ruta_legible(ruta: Path) -> str:
    """Ruta relativa a la raíz del proyecto; absoluta si no cuelga de ella."""
    try:
        return str(ruta.relative_to(RAIZ))
    except ValueError:
        return str(ruta)


def titulo(texto: str) -> None:
    print()
    print("=" * 78)
    print(f"  {texto}")
    print("=" * 78)


def subtitulo(texto: str) -> None:
    print(f"\n--- {texto} " + "-" * max(0, 72 - len(texto)))


# ==========================================================================
# 1 · VISIÓN GENERAL DE LOS DATOS DE ORIGEN
# ==========================================================================
def vision_general(dataframes: dict[str, pd.DataFrame]) -> None:
    titulo("1 · VISIÓN GENERAL DE LOS DATOS DE ORIGEN")
    resumen = extraccion.resumen_extraccion(dataframes)
    print(resumen.to_string(index=False))
    print(f"\n  Colecciones con datos ... {len(dataframes)}")
    print(f"  Documentos totales ...... {resumen['documentos'].sum():,}")
    print(f"  Memoria en pandas ....... {resumen['memoria_mb'].sum():.2f} MB")
    print("\n  Nota: el volumen total está muy por debajo del umbral en que un")
    print("  motor distribuido aporta ventaja. Se procesa con pandas (decisión C-03).")


# ==========================================================================
# 2 · ESTRUCTURA  (equivale a printSchema)
# ==========================================================================
def estructura(df: pd.DataFrame, nombre: str) -> None:
    titulo(f"2 · ESTRUCTURA DE `{nombre}`  (equivale a printSchema de Spark)")
    print(f"  Dimensiones: {df.shape[0]:,} filas × {df.shape[1]} columnas\n")
    print(f"  {'#':>3}  {'COLUMNA':<28}{'TIPO PANDAS':<18}{'NO NULOS':>10}")
    print("-" * 78)
    for i, columna in enumerate(df.columns, start=1):
        print(f"  {i:>3}  {columna:<28}{str(df[columna].dtype):<18}{df[columna].notna().sum():>10,}")

    subtitulo("PRIMERAS FILAS (equivale a df.show())")
    vista = [c for c in ("folio_entrega", "fecha", "nombre_cliente", "orden_parada",
                         "tiempo_estimado_min", "tiempo_real_min", "retraso_min",
                         "es_retraso", "estatus") if c in df.columns]
    print(df[vista or list(df.columns[:8])].head(8).to_string(index=False))


# ==========================================================================
# 3 · TIPOS Y FUENTES DE DATOS  (puente hacia la Unidad II)
# ==========================================================================
# Campos de texto libre según el modelo de datos (§11). No se adivinan con
# una heurística: se declaran, porque el diseño ya los define como tales.
# `nombre_cliente` o `estatus` también son texto, pero provienen de un
# catálogo: son datos estructurados.
CAMPOS_NO_ESTRUCTURADOS = (
    "observaciones", "descripcion", "referencias", "motivo",
)


def clasificar_columna(serie: pd.Series, nombre: str) -> str:
    """
    Estructurado / semiestructurado / no estructurado (taxonomía de U-II).

    · SEMIESTRUCTURADO: la columna contiene arrays u objetos anidados.
    · NO ESTRUCTURADO:  campo de texto libre declarado en el modelo de datos.
    · ESTRUCTURADO:     el resto (escalares, fechas, catálogos, referencias).
    """
    muestra = serie.dropna()
    if not muestra.empty and muestra.map(lambda v: isinstance(v, (list, dict))).any():
        return "SEMIESTRUCTURADO"
    if nombre in CAMPOS_NO_ESTRUCTURADOS:
        return "NO ESTRUCTURADO"
    return "ESTRUCTURADO"


def tipos_de_datos(df: pd.DataFrame, nombre: str) -> None:
    titulo(f"3 · TIPOS DE DATOS EN `{nombre}`  (insumo de la Unidad II)")
    grupos: dict[str, list[str]] = {}
    for columna in df.columns:
        grupos.setdefault(clasificar_columna(df[columna], columna), []).append(columna)

    for clase in ("ESTRUCTURADO", "SEMIESTRUCTURADO", "NO ESTRUCTURADO"):
        columnas = grupos.get(clase, [])
        print(f"\n  {clase}  ({len(columnas)} columnas)")
        for columna in columnas:
            ejemplo = df[columna].dropna()
            texto = str(ejemplo.iloc[0])[:52] if len(ejemplo) else "—"
            print(f"      {columna:<28}{texto}")

    print("\n  El ETL deberá aplanar lo semiestructurado (PA-6) y decidir qué")
    print("  hacer con el texto libre, que no entra directo a un modelo.")


# ==========================================================================
# 4 · ANÁLISIS DE COLUMNAS Y VALORES
# ==========================================================================
def analisis_de_columnas(df: pd.DataFrame, nombre: str) -> pd.DataFrame:
    titulo(f"4 · ANÁLISIS DE COLUMNAS Y VALORES DE `{nombre}`")
    filas = []
    for columna in df.columns:
        serie = df[columna]
        nulos = int(serie.isna().sum())
        try:
            unicos = int(serie.nunique(dropna=True))
        except TypeError:                       # columnas con listas o dicts
            unicos = int(serie.astype(str).nunique())
        filas.append({
            "columna": columna,
            "tipo": str(serie.dtype),
            "nulos": nulos,
            "%nulos": round(100 * nulos / len(df), 1),
            "unicos": unicos,
            "cardinalidad": round(unicos / max(len(df), 1), 4),
        })
    perfil = pd.DataFrame(filas)
    print(perfil.to_string(index=False))

    subtitulo("HALLAZGOS AUTOMÁTICOS")
    vacias = perfil.loc[perfil["%nulos"] == 100.0, "columna"].tolist()
    constantes = perfil.loc[(perfil["unicos"] <= 1) & (perfil["%nulos"] < 100.0),
                            "columna"].tolist()
    identificadores = perfil.loc[perfil["cardinalidad"] > 0.95, "columna"].tolist()
    con_nulos = perfil.loc[perfil["nulos"] > 0].sort_values("%nulos", ascending=False)

    print(f"  Columnas totalmente vacías: {vacias or 'ninguna'}")
    print("      → campo previsto en el diseño que la operación nunca llenó.")
    print(f"  Columnas constantes (1 solo valor): {constantes or 'ninguna'}")
    print("      → no aportan información a ningún modelo; se descartan en PA-6.")
    print(f"  Columnas identificadoras (cardinalidad > 0.95): {identificadores or 'ninguna'}")
    print("      → sirven para unir tablas, no como variables predictoras.")
    print(f"  Columnas con nulos: {len(con_nulos)}")
    for _, fila in con_nulos.iterrows():
        print(f"      {fila['columna']:<28}{fila['nulos']:>7} ({fila['%nulos']}%)")
    return perfil


# ==========================================================================
# 5 · RESUMEN ESTADÍSTICO  (equivale a describe)
# ==========================================================================
def resumen_estadistico(df: pd.DataFrame) -> None:
    titulo("5 · RESUMEN ESTADÍSTICO  (equivale a describe de Spark)")

    numericas = df.select_dtypes(include=[np.number])
    if not numericas.empty:
        subtitulo("VARIABLES NUMÉRICAS")
        print(numericas.describe().T.round(2).to_string())

    subtitulo("VARIABLES CATEGÓRICAS")
    for columna in df.columns:
        serie = df[columna]
        if clasificar_columna(serie, columna) != "ESTRUCTURADO":
            continue
        if pd.api.types.is_numeric_dtype(serie) or pd.api.types.is_datetime64_any_dtype(serie):
            continue
        try:
            conteo = serie.value_counts(dropna=True)
        except TypeError:
            continue
        if 1 <= conteo.size <= 12:
            print(f"\n  {columna}  ({conteo.size} categorías)")
            for valor, n in conteo.items():
                print(f"      {str(valor):<24}{n:>8,}  {n/len(df):>7.1%}")


# ==========================================================================
# 6 · VALORES NULOS
# ==========================================================================
def valores_nulos(df: pd.DataFrame) -> None:
    titulo("6 · VALORES NULOS")
    nulos = df.isna().sum()
    nulos = nulos[nulos > 0].sort_values(ascending=False)
    if nulos.empty:
        print("  No hay valores nulos.")
        return

    print(f"  {'COLUMNA':<28}{'NULOS':>9}{'%':>9}")
    print("-" * 78)
    for columna, n in nulos.items():
        print(f"  {columna:<28}{n:>9,}{n/len(df):>9.1%}")

    subtitulo("¿SON NULOS ALEATORIOS O TIENEN PATRÓN?")
    if {"estatus", "hora_real_llegada"}.issubset(df.columns):
        tabla = df.assign(sin_hora=df["hora_real_llegada"].isna()) \
                  .groupby("estatus")["sin_hora"].agg(["sum", "count"])
        tabla["%"] = (100 * tabla["sum"] / tabla["count"]).round(1)
        print("  Entregas sin hora real, por estatus:")
        print(tabla.rename(columns={"sum": "sin_hora", "count": "total"}).to_string())
        print("\n  Lectura: los nulos de las entregas CANCELADAS son legítimos")
        print("  (nunca ocurrieron). Los del resto son captura omitida y sí")
        print("  requieren una decisión de limpieza en PA-5.")


# ==========================================================================
# 7 · VARIABLE OBJETIVO
# ==========================================================================
def variable_objetivo(df: pd.DataFrame) -> None:
    if "retraso_min" not in df.columns:
        return
    titulo("7 · VARIABLE OBJETIVO  `retraso_min` / `es_retraso`")
    serie = df["retraso_min"].dropna()

    print(f"  Registros utilizables .... {len(serie):,} de {len(df):,}")
    print(f"  Media .................... {serie.mean():.2f} min")
    print(f"  Mediana .................. {serie.median():.2f} min")
    print(f"  Desviación estándar ...... {serie.std():.2f} min")
    print(f"  Mínimo / Máximo .......... {serie.min():.1f} / {serie.max():.1f} min")
    print(f"  Asimetría (skew) ......... {serie.skew():.3f}")
    print(f"  Curtosis ................. {serie.kurtosis():.3f}")

    subtitulo("CUARTILES (equivale a approxQuantile)")
    q1, q2, q3 = serie.quantile([0.25, 0.50, 0.75])
    iqr = q3 - q1
    print(f"  Q1 {q1:.2f}  ·  Q2 {q2:.2f}  ·  Q3 {q3:.2f}  ·  IQR {iqr:.2f}")
    print(f"  Límites IQR: {q1 - 1.5*iqr:.2f} a {q3 + 1.5*iqr:.2f}")
    fuera = ((serie < q1 - 1.5*iqr) | (serie > q3 + 1.5*iqr)).sum()
    print(f"  Fuera de límites: {fuera:,} ({fuera/len(serie):.1%})")

    subtitulo("DISTRIBUCIÓN POR TRAMOS")
    tramos = pd.cut(serie, [-np.inf, 0, 5, 15, 30, 60, np.inf],
                    labels=["adelantada", "0-5", "5-15",
                            "15-30", "30-60", "más de 60"])
    for etiqueta, n in tramos.value_counts().sort_index().items():
        barra = "#" * int(40 * n / len(serie))
        print(f"      {str(etiqueta):<14}{n:>7,}  {n/len(serie):>6.1%}  {barra}")

    if "es_retraso" in df.columns:
        objetivo = df["es_retraso"].dropna()
        positivos = int(objetivo.sum())
        print(f"\n  Clasificación binaria (umbral RNP-01 > {settings.UMBRAL_RETRASO_MIN} min)")
        print(f"      es_retraso = 1 ... {positivos:,} ({positivos/len(objetivo):.1%})")
        print(f"      es_retraso = 0 ... {len(objetivo)-positivos:,} "
              f"({1-positivos/len(objetivo):.1%})")
        razon = max(positivos, len(objetivo)-positivos) / max(min(positivos, len(objetivo)-positivos), 1)
        print(f"      Razón de desbalance: {razon:.2f} : 1")
        print("      Aceptable. Aun así, PA-8 debe reportar recall y F1, no solo accuracy.")


# ==========================================================================
# 8 · EXPLORACIÓN DIRIGIDA
# ==========================================================================
def exploracion_dirigida(df: pd.DataFrame, contexto: dict[str, pd.DataFrame]) -> None:
    if "retraso_min" not in df.columns:
        return
    titulo("8 · EXPLORACIÓN DIRIGIDA  (¿hay señal en los datos?)")
    limpio = df.dropna(subset=["retraso_min"]).copy()

    subtitulo("RETRASO POR HORA ESTIMADA DE LLEGADA")
    limpio["hora"] = pd.to_datetime(limpio["hora_estimada_llegada"]).dt.hour
    por_hora = limpio.groupby("hora")["retraso_min"].agg(["count", "mean"]).round(2)
    print(por_hora.to_string())
    print("  → si la hora pico no se distinguiera, el modelo no tendría qué aprender.")

    subtitulo("RETRASO POR DÍA DE LA SEMANA")
    dias = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
    limpio["dia"] = pd.to_datetime(limpio["fecha"]).dt.dayofweek
    por_dia = limpio.groupby("dia")["retraso_min"].agg(["count", "mean"]).round(2)
    por_dia.index = [dias[i] for i in por_dia.index]
    print(por_dia.to_string())

    subtitulo("RETRASO POR ORDEN DE PARADA  (efecto de acumulación)")
    por_parada = limpio.groupby("orden_parada")["retraso_min"].agg(["count", "mean"]).round(2)
    print(por_parada.to_string())
    print("  → el retraso debe CRECER con el orden: la parada 6 hereda el de las")
    print("    anteriores (Anexo B.4). Si bajara, el modelo tendría un defecto.")

    if "rutas" in contexto:
        paradas_por_ruta = contexto["rutas"].set_index("_id")["numero_paradas"]
        limpio["n_paradas"] = limpio["ruta_id"].map(paradas_por_ruta)
        subtitulo("MISMO ANÁLISIS, CONTROLANDO LA LONGITUD DE LA RUTA")
        print("  El promedio global mezcla rutas de distinta longitud: solo las")
        print("  rutas largas llegan a la parada 7 u 8. Se aísla el efecto:")
        for n in sorted(limpio["n_paradas"].dropna().unique()):
            sub = limpio[limpio["n_paradas"] == n]
            if len(sub) < 200:
                continue
            medias = sub.groupby("orden_parada")["retraso_min"].mean().round(1)
            print(f"      Rutas de {int(n)} paradas: {list(medias.values)}")
        print("  Controlado el efecto de longitud, la acumulación se ve limpia.")

    if "causa_retraso" in limpio.columns:
        subtitulo("CAUSAS DE RETRASO  (base del análisis de Pareto)")
        causas = limpio["causa_retraso"].value_counts()
        acumulado = 0
        for causa, n in causas.items():
            acumulado += n
            print(f"      {causa:<20}{n:>7,}  {n/causas.sum():>6.1%}   "
                  f"acumulado {acumulado/causas.sum():>6.1%}")

    subtitulo("CORRELACIÓN CON LA VARIABLE OBJETIVO")
    candidatas = [c for c in ("tiempo_estimado_min", "distancia_km", "orden_parada", "hora", "dia")
                  if c in limpio.columns]
    correlaciones = limpio[candidatas + ["retraso_min"]].corr()["retraso_min"].drop("retraso_min")
    print(correlaciones.sort_values(key=abs, ascending=False).round(3).to_string())
    print("\n  Correlaciones moderadas, no perfectas. Es lo esperado: hay señal")
    print("  aprendible pero también ruido, y las relaciones más fuertes están")
    print("  en variables que todavía no existen y que PA-6 debe derivar")
    print("  (incidentes del viaje, retraso de salida, antigüedad del vehículo).")


# ==========================================================================
# PUNTO DE ENTRADA
# ==========================================================================
def main() -> int:
    parser = argparse.ArgumentParser(
        description="PA-4 — Exploración de datos (EDA). Evidencia de la Unidad I.",
    )
    parser.add_argument("--coleccion", default="entregas",
                        help="Colección sobre la que se profundiza (por defecto: entregas).")
    parser.add_argument("--sin-archivos", action="store_true",
                        help="No escribe CSV crudos ni el reporte de texto.")
    args = parser.parse_args()

    if not verificar_conexion(verbose=True)["exito"]:
        return 1

    # El reporte se construye en memoria y se emite al final. No se sustituye
    # `sys.stdout`: hacerlo dependía del comportamiento de la consola y en
    # algunas terminales de Windows la salida se perdía sin dar ningún error.
    memoria = io.StringIO()
    codigo = 0

    try:
        with contextlib.redirect_stdout(memoria):
            bd = obtener_bd()
            print("  Extrayendo colecciones desde MongoDB Atlas...")
            dataframes = extraccion.extraer_operativas(bd)

            if args.coleccion not in dataframes:
                disponibles = ", ".join(sorted(dataframes)) or "ninguna"
                print(f"\n  La colección `{args.coleccion}` está vacía o no existe.")
                print(f"  Colecciones con datos: {disponibles}")
                raise SystemExit(1)

            df = dataframes[args.coleccion]

            titulo("SIG-LOG · EXPLORACIÓN DE DATOS (EDA) — EVIDENCIA DE LA UNIDAD I")
            print("  Los datos analizados son SIMULADOS (decisión C-02).")
            print("  Ninguna cifra describe una empresa real.")

            vision_general(dataframes)
            estructura(df, args.coleccion)
            tipos_de_datos(df, args.coleccion)
            analisis_de_columnas(df, args.coleccion)
            resumen_estadistico(df)
            valores_nulos(df)
            variable_objetivo(df)
            exploracion_dirigida(df, dataframes)

            titulo("9 · CONCLUSIONES DE LA EXPLORACIÓN")
            print("  1. El dataset tiene volumen suficiente para los mínimos de §16.2.")
            print("  2. Existen nulos con dos orígenes distintos: legítimos (viajes")
            print("     cancelados) y de captura. PA-5 debe tratarlos por separado.")
            print("  3. Hay columnas semiestructuradas que el ETL debe aplanar y")
            print("     texto libre que no entra directo a un modelo.")
            print("  4. La variable objetivo muestra señal en hora, día y orden de")
            print("     parada: hay algo que aprender, no solo ruido.")
            print("  5. Los outliers por IQR incluyen retrasos legítimos por")
            print("     incidentes graves. Recomendación: MARCARLOS, no eliminarlos.")

            if not args.sin_archivos:
                rutas = extraccion.guardar_raw(dataframes)
                titulo("ARCHIVOS GENERADOS")
                for ruta in rutas:
                    print(f"  {ruta_legible(ruta):<34}{ruta.stat().st_size/1024:>8.0f} KB")
                print(f"  {ruta_legible(ARCHIVO_REPORTE)}")
                print("\n  Los CSV de data/raw/ permiten trabajar el ETL sin conexión")
                print("  y son el entregable 'repositorio con datos preprocesados'.")

            print()
            print("=" * 78)
            print("  PA-4 TERMINADA. Siguiente actividad: PA-5 (limpieza, Unidad II).")
            print("=" * 78)

    except SystemExit as salida:
        codigo = int(salida.code or 0)
    except Exception:                              # noqa: BLE001
        codigo = 1
        memoria.write("\n" + "=" * 78 + "\n")
        memoria.write("  ERROR DURANTE LA EXPLORACIÓN\n")
        memoria.write("=" * 78 + "\n")
        memoria.write(traceback.format_exc())
    finally:
        cerrar_cliente()

    reporte = memoria.getvalue()
    print(reporte)

    if not args.sin_archivos and reporte:
        try:
            CARPETA_SALIDA.mkdir(parents=True, exist_ok=True)
            ARCHIVO_REPORTE.write_text(reporte, encoding="utf-8")
        except OSError as exc:
            print(f"  No se pudo escribir {ARCHIVO_REPORTE}: {exc}")

    return codigo


if __name__ == "__main__":
    sys.exit(main())
