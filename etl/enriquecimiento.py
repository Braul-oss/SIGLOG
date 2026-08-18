"""
SIG-LOG — Sistema Integral de Gestión Logística
etl/enriquecimiento.py

ACTIVIDAD PA-6 (parte 2) — ENRIQUECIMIENTO
EVIDENCIA DE LA UNIDAD II (preparación de datos)

Calcula los indicadores DERIVADOS que el diseño difirió al ETL y los
datasets agregados que consumirán las siguientes actividades:

  1. MÉTRICAS POR VEHÍCULO — incluye `rendimiento_real_km_l`, marcado en
     §11.2 como "calculado en el ETL" y dejado en null por PA-3 a
     propósito (docstring de database/seed/reconciliar.py).
  2. MÉTRICAS POR OPERADOR — incluye `porcentaje_entregas_a_tiempo`
     (§11.3, misma situación).
  3. DATASET DE RUTAS — una fila por ruta con su perfil operativo:
     el insumo del clustering K-Means (ml/no_supervisado/).

Decisión de arquitectura (§7.3): el ETL NO escribe en las colecciones
operativas, así que estos valores no se actualizan en `vehiculos` ni
`operadores` en MongoDB. Viven como salidas analíticas en data/processed/
y la actividad de carga los materializará en las dimensiones del DW
(dim_vehiculo, dim_operador, dim_ruta).

Las métricas se calculan sobre el dataset limpio de PA-5/PA-6 (sin
duplicados) — por eso difieren ligeramente de los contadores operativos
de PA-3, que por diseño incluyen la doble captura.

Uso
---
    python -m etl.enriquecimiento
    python -m etl.enriquecimiento --sin-archivos
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

import pandas as pd

from config.mongo_conexion import cerrar_cliente, verificar_conexion
from etl import extraccion
from etl.exploracion import ruta_legible, subtitulo, titulo
from etl.transformacion import ARCHIVO_DATASET, cargar_dataset_entregas, transformar

CARPETA_PROCESSED = RAIZ / "data" / "processed"
ARCHIVO_VEHICULOS = CARPETA_PROCESSED / "metricas_vehiculos.csv"
ARCHIVO_OPERADORES = CARPETA_PROCESSED / "metricas_operadores.csv"
ARCHIVO_RUTAS = CARPETA_PROCESSED / "dataset_rutas.csv"
ARCHIVO_REPORTE = RAIZ / "data" / "outputs" / "reporte_enriquecimiento.txt"


def _dataset_entregas(bd=None) -> pd.DataFrame:
    """Usa el CSV de la transformación si existe; si no, transforma en línea."""
    if ARCHIVO_DATASET.exists():
        return cargar_dataset_entregas()
    return transformar(bd=bd)[0]


# ==========================================================================
# 1 · MÉTRICAS POR VEHÍCULO  (rendimiento_real_km_l, §11.2)
# ==========================================================================
def metricas_vehiculos(bd=None) -> pd.DataFrame:
    vehiculos = extraccion.extraer("vehiculos", bd=bd)[
        ["_id", "codigo_vehiculo", "placa", "tipo_vehiculo", "anio",
         "rendimiento_nominal_km_l", "estado_operativo"]
    ].rename(columns={"_id": "vehiculo_id"})

    viajes = extraccion.extraer("viajes", bd=bd)
    km = (viajes[viajes["estatus"] == "FINALIZADO"]
          .groupby("vehiculo_id")
          .agg(km_recorridos=("km_recorridos", "sum"),
               n_viajes=("_id", "count")))

    combustible = (extraccion.extraer("combustible", bd=bd)
                   .groupby("vehiculo_id")
                   .agg(litros=("litros", "sum"),
                        costo_combustible=("costo_total", "sum"),
                        n_cargas=("_id", "count")))

    mantenimientos = extraccion.extraer("mantenimientos", bd=bd)
    mtto = (mantenimientos[mantenimientos["estatus"] == "REALIZADO"]
            .groupby("vehiculo_id")
            .agg(n_mantenimientos=("_id", "count"),
                 costo_mantenimiento=("costo", "sum")))

    df = (vehiculos.set_index("vehiculo_id")
          .join([km, combustible, mtto]).reset_index())

    # Indicadores derivados (el enriquecimiento propiamente dicho)
    df["rendimiento_real_km_l"] = (df["km_recorridos"] / df["litros"]).round(2)
    df["desviacion_rendimiento_pct"] = (
        100 * (df["rendimiento_real_km_l"] - df["rendimiento_nominal_km_l"])
        / df["rendimiento_nominal_km_l"]).round(1)
    df["costo_combustible_por_km"] = (
        df["costo_combustible"] / df["km_recorridos"]).round(2)
    df["costo_total_operacion"] = (
        df["costo_combustible"].fillna(0) + df["costo_mantenimiento"].fillna(0)
    ).round(2)
    df["costo_total_por_km"] = (
        df["costo_total_operacion"] / df["km_recorridos"]).round(2)
    return df.sort_values("codigo_vehiculo").reset_index(drop=True)


# ==========================================================================
# 2 · MÉTRICAS POR OPERADOR  (porcentaje_entregas_a_tiempo, §11.3)
# ==========================================================================
def metricas_operadores(entregas: pd.DataFrame, bd=None) -> pd.DataFrame:
    operadores = extraccion.extraer("operadores", bd=bd)[
        ["_id", "codigo_operador", "nombre_completo", "estado"]
    ].rename(columns={"_id": "operador_id"})
    operadores["operador_id"] = operadores["operador_id"].astype(str)

    ok = entregas[entregas["calidad_dato"] == "OK"].copy()
    ok["operador_id"] = ok["operador_id"].astype(str)
    metricas = (ok.assign(a_tiempo=(ok["es_retraso"] == 0).astype(int))
                .groupby("operador_id")
                .agg(entregas_medibles=("folio_entrega", "count"),
                     a_tiempo=("a_tiempo", "sum"),
                     retraso_medio_min=("retraso_min", "mean"),
                     viajes=("viaje_id", "nunique")))
    metricas["porcentaje_entregas_a_tiempo"] = (
        100 * metricas["a_tiempo"] / metricas["entregas_medibles"]).round(1)
    metricas["retraso_medio_min"] = metricas["retraso_medio_min"].round(1)
    metricas["entregas_por_viaje"] = (
        metricas["entregas_medibles"] / metricas["viajes"]).round(1)

    return (operadores.merge(metricas.reset_index(), on="operador_id", how="left")
            .sort_values("codigo_operador").reset_index(drop=True))


# ==========================================================================
# 3 · DATASET DE RUTAS  (insumo del clustering K-Means)
# ==========================================================================
def dataset_rutas(entregas: pd.DataFrame, bd=None) -> pd.DataFrame:
    rutas = extraccion.extraer("rutas", bd=bd)[
        ["_id", "codigo_ruta", "nombre", "zona", "numero_paradas",
         "distancia_total_km", "tiempo_estimado_total_min",
         "velocidad_efectiva_kmh"]
    ].rename(columns={"_id": "ruta_id"})
    rutas["ruta_id"] = rutas["ruta_id"].astype(str)

    ok = entregas[entregas["calidad_dato"] == "OK"].copy()
    ok["ruta_id"] = ok["ruta_id"].astype(str)
    perfil = (ok.assign(retrasada=(ok["es_retraso"] == 1).astype(int))
              .groupby("ruta_id")
              .agg(entregas=("folio_entrega", "count"),
                   viajes=("viaje_id", "nunique"),
                   retraso_medio_min=("retraso_min", "mean"),
                   retraso_maximo_min=("retraso_min", "max"),
                   pct_entregas_retrasadas=("retrasada", "mean"),
                   incidentes_por_viaje=("incidentes_viaje", "mean"),
                   retraso_salida_medio_min=("retraso_salida_min", "mean")))
    perfil["pct_entregas_retrasadas"] = (100 * perfil["pct_entregas_retrasadas"]).round(1)
    perfil = perfil.round(2)

    return (rutas.merge(perfil.reset_index(), on="ruta_id", how="left")
            .sort_values("codigo_ruta").reset_index(drop=True))


# ==========================================================================
# VERIFICACIONES AUTOMÁTICAS
# ==========================================================================
def verificar(veh: pd.DataFrame, ope: pd.DataFrame,
              rut: pd.DataFrame) -> list[tuple[str, bool, str]]:
    rendimiento = veh["rendimiento_real_km_l"].dropna()
    pct = ope["porcentaje_entregas_a_tiempo"].dropna()
    return [
        ("Un registro por vehículo de la flotilla", len(veh) == 20, f"{len(veh)} filas"),
        ("rendimiento_real_km_l calculado en todos",
         int(rendimiento.count()) == len(veh), f"{rendimiento.count()} de {len(veh)}"),
        ("Rendimiento real en rango plausible (2–20 km/l)",
         rendimiento.between(2, 20).all(),
         f"{rendimiento.min():.2f}–{rendimiento.max():.2f}"),
        ("Real por debajo del nominal en promedio",
         veh["desviacion_rendimiento_pct"].mean() < 0,
         f"desviación media {veh['desviacion_rendimiento_pct'].mean():.1f}%"),
        ("Un registro por operador", len(ope) == 24, f"{len(ope)} filas"),
        ("porcentaje_entregas_a_tiempo en 0–100",
         pct.between(0, 100).all(), f"{pct.min():.1f}–{pct.max():.1f}"),
        ("Un registro por ruta", len(rut) == 20, f"{len(rut)} filas"),
        ("Toda ruta tiene perfil operativo",
         rut["entregas"].notna().all(),
         f"{int(rut['entregas'].isna().sum())} rutas sin entregas"),
    ]


# ==========================================================================
# REPORTE
# ==========================================================================
def imprimir_reporte(veh: pd.DataFrame, ope: pd.DataFrame, rut: pd.DataFrame) -> None:
    titulo("1 · MÉTRICAS POR VEHÍCULO  (rendimiento_real_km_l, §11.2)")
    columnas = ["codigo_vehiculo", "tipo_vehiculo", "km_recorridos", "litros",
                "rendimiento_nominal_km_l", "rendimiento_real_km_l",
                "desviacion_rendimiento_pct", "costo_total_por_km"]
    print(veh[columnas].to_string(index=False))
    peor = veh.nsmallest(3, "desviacion_rendimiento_pct")
    print("\n  Mayor desviación vs nominal (candidatos a revisión):")
    for _, fila in peor.iterrows():
        print(f"      {fila['codigo_vehiculo']}  {fila['desviacion_rendimiento_pct']:+.1f}%"
              f"  ({fila['rendimiento_real_km_l']} vs {fila['rendimiento_nominal_km_l']} km/l)")

    titulo("2 · MÉTRICAS POR OPERADOR  (porcentaje_entregas_a_tiempo, §11.3)")
    columnas = ["codigo_operador", "entregas_medibles", "viajes",
                "porcentaje_entregas_a_tiempo", "retraso_medio_min"]
    print(ope[columnas].to_string(index=False))

    titulo("3 · DATASET DE RUTAS  (insumo del clustering)")
    columnas = ["codigo_ruta", "zona", "numero_paradas", "distancia_total_km",
                "entregas", "retraso_medio_min", "pct_entregas_retrasadas",
                "incidentes_por_viaje"]
    print(rut[columnas].to_string(index=False))
    subtitulo("RESUMEN POR ZONA")
    print(rut.groupby("zona")
             .agg(rutas=("codigo_ruta", "count"),
                  retraso_medio=("retraso_medio_min", "mean"),
                  pct_retrasadas=("pct_entregas_retrasadas", "mean"))
             .round(1).to_string())


def imprimir_verificaciones(resultados: list[tuple[str, bool, str]]) -> bool:
    titulo("4 · VERIFICACIONES AUTOMÁTICAS")
    for nombre, ok, detalle in resultados:
        print(f"  {'[OK]   ' if ok else '[FALLA]'} {nombre:<46}{detalle}")
    fallos = sum(1 for _, ok, _ in resultados if not ok)
    print("-" * 78)
    print(f"  {len(resultados) - fallos}/{len(resultados)} verificaciones correctas")
    return fallos == 0


# ==========================================================================
# PUNTO DE ENTRADA
# ==========================================================================
def main() -> int:
    parser = argparse.ArgumentParser(
        description="PA-6 (parte 2) — Enriquecimiento: métricas derivadas y dataset de rutas.",
    )
    parser.add_argument("--sin-archivos", action="store_true",
                        help="No escribe CSV ni el reporte de texto.")
    args = parser.parse_args()

    if not verificar_conexion(verbose=True)["exito"]:
        return 1

    memoria = io.StringIO()
    codigo = 0

    try:
        with contextlib.redirect_stdout(memoria):
            titulo("SIG-LOG · ENRIQUECIMIENTO (PA-6) — EVIDENCIA DE LA UNIDAD II")
            print("  Los datos analizados son SIMULADOS (decisión C-02).")
            print("\n  Calculando métricas derivadas...")

            entregas = _dataset_entregas()
            veh = metricas_vehiculos()
            ope = metricas_operadores(entregas)
            rut = dataset_rutas(entregas)

            imprimir_reporte(veh, ope, rut)
            if not imprimir_verificaciones(verificar(veh, ope, rut)):
                codigo = 1

            if not args.sin_archivos:
                CARPETA_PROCESSED.mkdir(parents=True, exist_ok=True)
                titulo("ARCHIVOS GENERADOS")
                for df, ruta in ((veh, ARCHIVO_VEHICULOS),
                                 (ope, ARCHIVO_OPERADORES),
                                 (rut, ARCHIVO_RUTAS)):
                    extraccion.aplanar_para_csv(df).to_csv(
                        ruta, index=False, encoding="utf-8")
                    print(f"  {ruta_legible(ruta):<40}{ruta.stat().st_size/1024:>8.1f} KB")
                print(f"  {ruta_legible(ARCHIVO_REPORTE)}")

            print()
            print("=" * 78)
            if codigo == 0:
                print("  PA-6 TERMINADA. Siguiente actividad: carga del data warehouse.")
            else:
                print("  PA-6 TERMINADA CON FALLAS: revisa las verificaciones.")
            print("=" * 78)

    except SystemExit as salida:
        codigo = int(salida.code or 0)
    except Exception:                              # noqa: BLE001
        codigo = 1
        memoria.write("\n" + "=" * 78 + "\n  ERROR DURANTE EL ENRIQUECIMIENTO\n"
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
