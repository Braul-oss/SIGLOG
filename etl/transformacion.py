"""
SIG-LOG — Sistema Integral de Gestión Logística
etl/transformacion.py

ACTIVIDAD PA-6 (parte 1) — TRANSFORMACIÓN
EVIDENCIA DE LA UNIDAD II (preparación de datos)

Construye el DATASET ANALÍTICO DE ENTREGAS: la tabla plana que alimentará
la carga del data warehouse (`hecho_entrega`) y los modelos de ML.

Qué hace, en orden:

  1. Extrae `entregas` de MongoDB y le aplica la limpieza de PA-5 en
     memoria (etl.limpieza.limpiar_entregas): el pipeline es una cadena,
     no scripts sueltos.
  2. APLANA lo semiestructurado (diagnóstico de PA-4, sección 3):
     `incidentes_ids` se convierte en el conteo `n_incidentes_acumulados`
     y se descartan `historial_estatus` y el texto libre `observaciones`,
     que no entran a un modelo.
  3. DERIVA las variables temporales que el seed dejó a propósito para el
     ETL (nota en generar_operacion.py): `dia_semana`, `es_fin_semana`,
     `franja_horaria` y `mes`. Las franjas se definen con los mismos
     rangos pico del Anexo B (7-10 y 17-20 h) para que la variable capture
     el fenómeno que genera los retrasos.
  4. UNE los catálogos (viajes, rutas, vehículos, operadores, clientes)
     para traer las variables que la exploración de PA-4 señaló como las
     de mayor señal esperada: retraso de salida e incidentes del viaje,
     antigüedad del vehículo, experiencia del operador, zona y longitud
     de la ruta.

Los nombres `dia_semana`, `franja_horaria` y `es_fin_semana` son los que
el modelo de datos ya anticipa (validador de `entregas`, §11.6). La lista
definitiva de columnas del DW se fija aquí, como indica la nota de
database/esquemas/validadores.py.

El ETL lee de MongoDB y NUNCA escribe en las colecciones operativas (§7.3).
Salida: data/processed/dataset_entregas.csv

Uso
---
    python -m etl.transformacion
    python -m etl.transformacion --sin-archivos
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

from config.mongo_conexion import cerrar_cliente, verificar_conexion
from etl import extraccion
from etl.exploracion import ruta_legible, subtitulo, titulo
from etl.limpieza import limpiar_entregas

CARPETA_PROCESSED = RAIZ / "data" / "processed"
ARCHIVO_DATASET = CARPETA_PROCESSED / "dataset_entregas.csv"
ARCHIVO_REPORTE = RAIZ / "data" / "outputs" / "reporte_transformacion.txt"

# Franjas horarias (D-T1). Cortes alineados con las horas pico del Anexo B
# (FRANJAS_PICO = 7-10 y 17-20): así la categoría refleja el fenómeno real.
FRANJAS = (
    (0, 7, "MADRUGADA"),
    (7, 10, "PICO_MATUTINO"),
    (10, 17, "VALLE"),
    (17, 20, "PICO_VESPERTINO"),
    (20, 24, "NOCHE"),
)

DIAS_SEMANA = ("LUNES", "MARTES", "MIERCOLES", "JUEVES",
               "VIERNES", "SABADO", "DOMINGO")

# Columnas finales del dataset, agrupadas por papel. Este orden ES el
# diseño de columnas del futuro `hecho_entrega`.
COLUMNAS_ID = [
    "folio_entrega", "viaje_id", "ruta_id", "cliente_id",
    "vehiculo_id", "operador_id",
]
COLUMNAS_FEATURES = [
    "fecha", "orden_parada", "tiempo_estimado_min", "distancia_km",
    "dia_semana", "es_fin_semana", "franja_horaria", "mes",
    "n_incidentes_acumulados", "retraso_salida_min", "incidentes_viaje",
    "zona", "numero_paradas_ruta", "distancia_total_ruta_km",
    "velocidad_efectiva_kmh", "tipo_vehiculo", "antiguedad_vehiculo_anios",
    "rendimiento_nominal_km_l", "experiencia_operador_meses", "tipo_cliente",
]
COLUMNAS_OBJETIVO = ["tiempo_real_min", "retraso_min", "es_retraso"]
COLUMNAS_CONTROL = ["estatus", "causa_retraso", "calidad_dato", "es_outlier_iqr"]


# ==========================================================================
# 1 · APLANADO DE LO SEMIESTRUCTURADO
# ==========================================================================
def aplanar(df: pd.DataFrame) -> pd.DataFrame:
    """
    `incidentes_ids` (array) → `n_incidentes_acumulados`: incidentes que ya
    habían ocurrido en el viaje al llegar a esta parada. Es información
    disponible en el momento, no filtración del futuro.

    `historial_estatus` y `observaciones` se descartan del dataset: el
    primero duplica columnas ya presentes; el segundo es texto libre.
    """
    copia = df.copy()
    copia["n_incidentes_acumulados"] = copia["incidentes_ids"].map(
        lambda v: len(v) if isinstance(v, list) else 0)
    return copia.drop(columns=["historial_estatus", "observaciones",
                               "incidentes_ids", "hora_estimada_recalculada"],
                      errors="ignore")


# ==========================================================================
# 2 · DERIVACIÓN DE VARIABLES TEMPORALES
# ==========================================================================
def franja_de(hora: int) -> str:
    for inicio, fin, nombre in FRANJAS:
        if inicio <= hora < fin:
            return nombre
    return "NOCHE"


def derivar_temporales(df: pd.DataFrame) -> pd.DataFrame:
    """dia_semana / es_fin_semana / franja_horaria / mes, desde la hora
    estimada de llegada (existe en todas las filas, sin nulos)."""
    copia = df.copy()
    estimada = pd.to_datetime(copia["hora_estimada_llegada"], utc=True)
    copia["dia_semana"] = estimada.dt.dayofweek          # 0 = lunes
    copia["es_fin_semana"] = (copia["dia_semana"] >= 5).astype(int)
    copia["franja_horaria"] = estimada.dt.hour.map(franja_de)
    copia["mes"] = estimada.dt.month
    return copia


# ==========================================================================
# 3 · UNIÓN CON LOS CATÁLOGOS
# ==========================================================================
def unir_catalogos(df: pd.DataFrame, bd=None) -> pd.DataFrame:
    """
    Left-joins por ObjectId. La integridad referencial ya fue verificada
    en PA-3 (9/9 sin huérfanos), así que ningún join debe perder filas.
    """
    copia = df.copy()

    viajes = extraccion.extraer("viajes", bd=bd)[
        ["_id", "retraso_salida_min", "total_incidentes"]
    ].rename(columns={"_id": "viaje_id", "total_incidentes": "incidentes_viaje"})

    rutas = extraccion.extraer("rutas", bd=bd)[
        ["_id", "zona", "numero_paradas", "distancia_total_km",
         "velocidad_efectiva_kmh"]
    ].rename(columns={"_id": "ruta_id",
                      "numero_paradas": "numero_paradas_ruta",
                      "distancia_total_km": "distancia_total_ruta_km"})

    vehiculos = extraccion.extraer("vehiculos", bd=bd)[
        ["_id", "tipo_vehiculo", "anio", "rendimiento_nominal_km_l"]
    ].rename(columns={"_id": "vehiculo_id"})

    operadores = extraccion.extraer("operadores", bd=bd)[
        ["_id", "fecha_ingreso"]
    ].rename(columns={"_id": "operador_id"})

    clientes = extraccion.extraer("clientes", bd=bd)[
        ["_id", "tipo_cliente"]
    ].rename(columns={"_id": "cliente_id"})

    for catalogo, clave in ((viajes, "viaje_id"), (rutas, "ruta_id"),
                            (vehiculos, "vehiculo_id"),
                            (operadores, "operador_id"),
                            (clientes, "cliente_id")):
        copia = copia.merge(catalogo, on=clave, how="left", validate="m:1")

    # Derivadas de los catálogos, evaluadas A LA FECHA de la entrega
    fecha = pd.to_datetime(copia["fecha"], utc=True)
    copia["antiguedad_vehiculo_anios"] = (fecha.dt.year - copia["anio"]).clip(lower=0)
    ingreso = pd.to_datetime(copia["fecha_ingreso"], utc=True)
    copia["experiencia_operador_meses"] = (
        (fecha - ingreso).dt.days / 30.44).round(1).clip(lower=0)

    return copia.drop(columns=["anio", "fecha_ingreso"])


# ==========================================================================
# PIPELINE COMPLETO
# ==========================================================================
def transformar(bd=None) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Extracción → limpieza (PA-5) → aplanado → derivación → joins."""
    entregas = extraccion.extraer("entregas", bd=bd)
    limpio, bitacora_limpieza = limpiar_entregas(entregas)

    df = aplanar(limpio)
    df = derivar_temporales(df)
    df = unir_catalogos(df, bd=bd)

    columnas = COLUMNAS_ID + COLUMNAS_FEATURES + COLUMNAS_OBJETIVO + COLUMNAS_CONTROL
    dataset = df[columnas].copy()

    bitacora = {
        "limpieza": bitacora_limpieza,
        "filas": len(dataset),
        "columnas": len(dataset.columns),
        "filas_ml": int((dataset["calidad_dato"] == "OK").sum()),
    }
    return dataset, bitacora


def cargar_dataset_entregas(ruta: Path = ARCHIVO_DATASET) -> pd.DataFrame:
    """Punto de lectura para la carga del DW y los módulos de ML."""
    df = pd.read_csv(ruta, dtype={"calidad_dato": "string"})
    df["fecha"] = pd.to_datetime(df["fecha"], format="ISO8601", utc=True)
    for columna in ("es_retraso", "es_outlier_iqr", "es_fin_semana",
                    "dia_semana", "mes"):
        df[columna] = df[columna].astype("Int64")
    return df


# ==========================================================================
# VERIFICACIONES AUTOMÁTICAS
# ==========================================================================
def verificar(df: pd.DataFrame, bitacora: dict[str, Any]) -> list[tuple[str, bool, str]]:
    ok = df[df["calidad_dato"] == "OK"]
    features_nulas = ok[COLUMNAS_FEATURES].isna().any(axis=1).sum()
    objetivo_nulo = ok[COLUMNAS_OBJETIVO].isna().any(axis=1).sum()
    franjas_validas = set(df["franja_horaria"].unique()) <= {f[2] for f in FRANJAS}
    esperadas = bitacora["limpieza"]["filas_salida"]

    return [
        ("Sin filas perdidas en los joins", len(df) == esperadas,
         f"{len(df):,} de {esperadas:,} tras la limpieza"),
        ("Features sin nulos en filas OK", features_nulas == 0,
         f"{int(features_nulas)} filas OK con features nulas"),
        ("Objetivos sin nulos en filas OK", objetivo_nulo == 0,
         f"{int(objetivo_nulo)} filas OK con objetivo nulo"),
        ("Franja horaria dentro del catálogo", franjas_validas,
         str(sorted(df['franja_horaria'].unique()))),
        ("dia_semana en 0..6", df["dia_semana"].between(0, 6).all(),
         f"rango {df['dia_semana'].min()}–{df['dia_semana'].max()}"),
        ("Antigüedad del vehículo no negativa",
         (df["antiguedad_vehiculo_anios"].dropna() >= 0).all(),
         f"mín {df['antiguedad_vehiculo_anios'].min()}"),
        ("Experiencia del operador no negativa",
         (df["experiencia_operador_meses"].dropna() >= 0).all(),
         f"mín {df['experiencia_operador_meses'].min()}"),
    ]


# ==========================================================================
# REPORTE
# ==========================================================================
def imprimir_reporte(df: pd.DataFrame, bitacora: dict[str, Any]) -> None:
    titulo("1 · DATASET ANALÍTICO DE ENTREGAS")
    print(f"  Filas ........... {bitacora['filas']:,} "
          f"(de ellas, {bitacora['filas_ml']:,} calidad OK para ML)")
    print(f"  Columnas ........ {bitacora['columnas']} "
          f"({len(COLUMNAS_ID)} id · {len(COLUMNAS_FEATURES)} features · "
          f"{len(COLUMNAS_OBJETIVO)} objetivo · {len(COLUMNAS_CONTROL)} control)")

    titulo("2 · VARIABLES TEMPORALES DERIVADAS  (evidencia U-II)")
    subtitulo("RETRASO MEDIO POR FRANJA HORARIA (filas OK)")
    ok = df[df["calidad_dato"] == "OK"]
    por_franja = ok.groupby("franja_horaria")["retraso_min"].agg(["count", "mean"])
    orden = [f[2] for f in FRANJAS if f[2] in por_franja.index]
    for franja in orden:
        fila = por_franja.loc[franja]
        print(f"      {franja:<18}{int(fila['count']):>7,}  {fila['mean']:>7.1f} min")
    print("  → las franjas pico deben destacar: son el mecanismo generador")
    print("    del retraso (Anexo B). Si no destacaran, la derivada estaría mal.")

    subtitulo("RETRASO MEDIO POR DÍA (filas OK)")
    por_dia = ok.groupby("dia_semana")["retraso_min"].mean()
    for dia, valor in por_dia.items():
        print(f"      {DIAS_SEMANA[int(dia)]:<12}{valor:>7.1f} min")

    titulo("3 · VARIABLES TRAÍDAS DE LOS CATÁLOGOS")
    correlaciones = ok[
        ["retraso_salida_min", "incidentes_viaje", "n_incidentes_acumulados",
         "antiguedad_vehiculo_anios", "experiencia_operador_meses",
         "orden_parada", "retraso_min"]
    ].corr()["retraso_min"].drop("retraso_min")
    subtitulo("CORRELACIÓN CON `retraso_min` (la señal que PA-4 anticipó)")
    print(correlaciones.sort_values(key=abs, ascending=False).round(3).to_string())


def imprimir_verificaciones(resultados: list[tuple[str, bool, str]]) -> bool:
    titulo("4 · VERIFICACIONES AUTOMÁTICAS")
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
        description="PA-6 (parte 1) — Transformación: dataset analítico de entregas.",
    )
    parser.add_argument("--sin-archivos", action="store_true",
                        help="No escribe el CSV ni el reporte de texto.")
    args = parser.parse_args()

    if not verificar_conexion(verbose=True)["exito"]:
        return 1

    memoria = io.StringIO()
    codigo = 0

    try:
        with contextlib.redirect_stdout(memoria):
            titulo("SIG-LOG · TRANSFORMACIÓN (PA-6) — EVIDENCIA DE LA UNIDAD II")
            print("  Los datos analizados son SIMULADOS (decisión C-02).")
            print("\n  Extrayendo y transformando...")

            dataset, bitacora = transformar()
            imprimir_reporte(dataset, bitacora)
            if not imprimir_verificaciones(verificar(dataset, bitacora)):
                codigo = 1

            if not args.sin_archivos:
                CARPETA_PROCESSED.mkdir(parents=True, exist_ok=True)
                extraccion.aplanar_para_csv(dataset).to_csv(
                    ARCHIVO_DATASET, index=False, encoding="utf-8")
                titulo("ARCHIVOS GENERADOS")
                print(f"  {ruta_legible(ARCHIVO_DATASET):<40}"
                      f"{ARCHIVO_DATASET.stat().st_size/1024:>8.0f} KB")
                print(f"  {ruta_legible(ARCHIVO_REPORTE)}")
                print("\n  Leerlo con etl.transformacion.cargar_dataset_entregas().")

            print()
            print("=" * 78)
            if codigo == 0:
                print("  TRANSFORMACIÓN TERMINADA. Sigue: python -m etl.enriquecimiento")
            else:
                print("  TRANSFORMACIÓN CON FALLAS: revisa las verificaciones.")
            print("=" * 78)

    except SystemExit as salida:
        codigo = int(salida.code or 0)
    except Exception:                              # noqa: BLE001
        codigo = 1
        memoria.write("\n" + "=" * 78 + "\n  ERROR DURANTE LA TRANSFORMACIÓN\n"
                      + "=" * 78 + "\n")
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
