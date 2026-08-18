"""
SIG-LOG — Sistema Integral de Gestión Logística
ml/supervisado/regresion_retraso.py

ACTIVIDAD PA-8 (parte 2) — ESTIMACIÓN DE LA MAGNITUD DEL RETRASO
EVIDENCIA DE APRENDIZAJE SUPERVISADO

La clasificación responde "¿llegará tarde?" (sí/no). La regresión
responde la pregunta complementaria, que es la que permite actuar:

    "¿CUÁNTOS MINUTOS de retraso se esperan en esta entrega?"

Variable objetivo: `retraso_min` (continua, en minutos; puede ser
negativa cuando la entrega se adelanta).

La diferencia operativa es concreta: saber que una entrega viene tarde
no dice si conviene avisar al cliente. Saber que son 8 minutos o que son
50 sí lo dice.

Modelos comparados
------------------
    Base (media)        predice siempre el retraso promedio. Vara mínima:
                        su R² es 0 por definición.
    Regresión lineal    modelo clásico interpretable.
    Árbol de decisión   capta relaciones no lineales por tramos.
    Random Forest       conjunto de árboles, normalmente el más preciso.

Se entrenan en los dos escenarios de ml/evaluacion.py (PLANEACION y
EN_RUTA), con la misma partición y semilla que la clasificación para que
los resultados sean comparables entre sí.

Métricas
--------
    RMSE  error típico en minutos, penaliza más los errores grandes.
    MAE   error medio en minutos; es el número que se le dice al usuario.
    R²    proporción de la variación del retraso que el modelo explica.

Criterio de selección: RMSE (menor es mejor).

Uso
---
    python -m ml.supervisado.regresion_retraso
    python -m ml.supervisado.regresion_retraso --sin-archivos
"""

from __future__ import annotations

import argparse
import contextlib
import io
import sys
import traceback
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

import numpy as np
import pandas as pd
from sklearn.dummy import DummyRegressor
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import LinearRegression
from sklearn.model_selection import cross_val_score
from sklearn.tree import DecisionTreeRegressor

from config import settings
from config.mongo_conexion import cerrar_cliente, obtener_bd, verificar_conexion
from etl.exploracion import ruta_legible, subtitulo, titulo
from ml import evaluacion as ev

ARCHIVO_REPORTE = RAIZ / "data" / "outputs" / "reporte_regresion.txt"
OBJETIVO = "retraso_min"

METRICAS_MOSTRADAS = ("rmse", "mae", "r2")


def catalogo_modelos() -> dict[str, Any]:
    return {
        "Base (media)": DummyRegressor(strategy="mean"),
        "Regresión lineal": LinearRegression(),
        "Árbol de decisión": DecisionTreeRegressor(
            max_depth=10, min_samples_leaf=40, random_state=ev.SEMILLA),
        "Random Forest": RandomForestRegressor(
            n_estimators=200, max_depth=16, min_samples_leaf=5,
            n_jobs=-1, random_state=ev.SEMILLA),
    }


def entrenar_escenario(df: pd.DataFrame, escenario: str) -> dict[str, Any]:
    X, y = ev.preparar(df, escenario, OBJETIVO)
    X_ent, X_pru, y_ent, y_pru = ev.dividir(X, y)

    resultados: dict[str, dict[str, float]] = {}
    pipelines: dict[str, Any] = {}

    for nombre, modelo in catalogo_modelos().items():
        pipeline = ev.crear_pipeline(escenario, modelo)
        pipeline.fit(X_ent, y_ent)
        resultados[nombre] = ev.metricas_regresion(y_pru, pipeline.predict(X_pru))
        pipelines[nombre] = pipeline

    mejor = min((n for n in resultados if not n.startswith("Base")),
                key=lambda n: resultados[n]["rmse"])

    return {
        "escenario": escenario,
        "resultados": resultados,
        "pipelines": pipelines,
        "mejor": mejor,
        "X_prueba": X_pru, "y_prueba": y_pru,
        "X_entrenamiento": X_ent, "y_entrenamiento": y_ent,
        "n_variables": X.shape[1],
    }


def analisis_de_errores(salida: dict[str, Any]) -> pd.DataFrame:
    """
    Error absoluto por tramo de retraso real.

    Un R² global alto puede esconder que el modelo falla justo en los
    retrasos grandes, que son los que importan. Este desglose lo muestra.
    """
    y_real = salida["y_prueba"]
    y_pred = salida["pipelines"][salida["mejor"]].predict(salida["X_prueba"])
    tramos = pd.cut(y_real, [-np.inf, 0, 15, 30, 60, np.inf],
                    labels=["adelantada", "0-15", "15-30", "30-60", "más de 60"])
    return (pd.DataFrame({"tramo": tramos,
                          "error_abs": np.abs(y_real - y_pred),
                          "sesgo": y_pred - y_real})
            .groupby("tramo", observed=True)
            .agg(entregas=("error_abs", "size"),
                 error_medio_min=("error_abs", "mean"),
                 sesgo_medio_min=("sesgo", "mean"))
            .round(1))


# ==========================================================================
# REPORTE
# ==========================================================================
def imprimir_escenario(salida: dict[str, Any], numero: int) -> None:
    escenario = salida["escenario"]
    descripcion = {
        "PLANEACION": "solo información disponible ANTES de que salga el vehículo",
        "EN_RUTA": "agrega lo ya ocurrido en el viaje (retraso de salida e incidentes)",
    }[escenario]

    titulo(f"{numero} · ESCENARIO {escenario}  ({salida['n_variables']} variables)")
    print(f"  {descripcion}")
    print(f"  Entrenamiento {len(salida['y_entrenamiento']):,} filas · "
          f"Prueba {len(salida['y_prueba']):,} filas · semilla {ev.SEMILLA}")
    print()
    ev.imprimir_tabla_metricas(salida["resultados"], METRICAS_MOSTRADAS)

    mejor = salida["mejor"]
    metricas = salida["resultados"][mejor]
    base = salida["resultados"]["Base (media)"]
    print(f"\n  Mejor por RMSE: {mejor}")
    print(f"      Se equivoca en promedio {metricas['mae']:.1f} minutos "
          f"y explica el {metricas['r2']:.1%} de la variación del retraso.")
    print(f"      Predecir siempre el promedio erraría {base['mae']:.1f} minutos: "
          f"el modelo reduce el error {1 - metricas['mae']/base['mae']:.0%}.")

    subtitulo("DÓNDE SE EQUIVOCA (error por tramo de retraso real)")
    print(analisis_de_errores(salida).to_string())
    print("\n  El sesgo negativo en los tramos altos indica que el modelo tiende")
    print("  a QUEDARSE CORTO en los retrasos grandes: subestima lo excepcional.")
    print("  Es el comportamiento esperado al promediar árboles, y la razón de")
    print("  acompañar siempre la estimación con la alerta de la clasificación.")

    puntajes = cross_val_score(
        salida["pipelines"][mejor], salida["X_entrenamiento"],
        salida["y_entrenamiento"], cv=5,
        scoring="neg_root_mean_squared_error", n_jobs=-1)
    subtitulo("VALIDACIÓN CRUZADA (5 particiones, RMSE)")
    print(f"      RMSE medio {-puntajes.mean():.2f} ± {puntajes.std():.2f} min")

    subtitulo("VARIABLES MÁS INFLUYENTES")
    for variable, peso in ev.importancias(salida["pipelines"][mejor]).items():
        print(f"      {variable:<34}{peso:>7.3f}")


def imprimir_comparacion(salidas: dict[str, dict[str, Any]]) -> None:
    titulo("3 · COMPARACIÓN ENTRE ESCENARIOS")
    print(f"  {'ESCENARIO':<16}{'RMSE':>10}{'MAE':>10}{'R2':>10}   LECTURA")
    print("-" * 78)
    for escenario in ("PLANEACION", "EN_RUTA"):
        salida = salidas[escenario]
        m = salida["resultados"][salida["mejor"]]
        lectura = ("estimación al programar" if escenario == "PLANEACION"
                   else "estimación con el viaje en curso")
        print(f"  {escenario:<16}{m['rmse']:>10.2f}{m['mae']:>10.2f}"
              f"{m['r2']:>10.3f}   {lectura}")

    plan = salidas["PLANEACION"]["resultados"][salidas["PLANEACION"]["mejor"]]
    ruta = salidas["EN_RUTA"]["resultados"][salidas["EN_RUTA"]["mejor"]]
    print(f"\n  Reducción del error típico al seguir el viaje: "
          f"{plan['rmse'] - ruta['rmse']:.2f} min "
          f"({1 - ruta['rmse']/plan['rmse']:.0%} menos)")
    print("  Uso previsto: al programar, la estimación sirve para dimensionar")
    print("  ventanas de entrega; en ruta, para avisar al cliente con un número.")


def verificar(salidas: dict[str, dict[str, Any]]) -> list[tuple[str, bool, str]]:
    resultados = []
    for escenario, salida in salidas.items():
        mejor = salida["resultados"][salida["mejor"]]
        base = salida["resultados"]["Base (media)"]
        resultados.append(
            (f"{escenario}: RMSE mejor que la media", mejor["rmse"] < base["rmse"],
             f"{mejor['rmse']:.2f} vs {base['rmse']:.2f} min"))
        resultados.append(
            (f"{escenario}: R² positivo", mejor["r2"] > 0, f"{mejor['r2']:.3f}"))
        resultados.append(
            (f"{escenario}: sin variables con fuga",
             not set(salida["X_prueba"].columns) & set(ev.COLUMNAS_CON_FUGA),
             f"{salida['n_variables']} variables verificadas"))

    plan = salidas["PLANEACION"]["resultados"][salidas["PLANEACION"]["mejor"]]
    ruta = salidas["EN_RUTA"]["resultados"][salidas["EN_RUTA"]["mejor"]]
    resultados.append(("EN_RUTA reduce el error frente a PLANEACION",
                       ruta["rmse"] < plan["rmse"],
                       f"{ruta['rmse']:.2f} vs {plan['rmse']:.2f} min"))
    return resultados


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
        description="PA-8 — Regresión de la magnitud del retraso (aprendizaje supervisado).",
    )
    parser.add_argument("--sin-archivos", action="store_true",
                        help="No guarda el modelo, la ficha ni el reporte.")
    args = parser.parse_args()

    if not verificar_conexion(verbose=True)["exito"]:
        return 1

    memoria = io.StringIO()
    codigo = 0

    try:
        with contextlib.redirect_stdout(memoria):
            titulo("SIG-LOG · ESTIMACIÓN DE LA MAGNITUD DEL RETRASO (PA-8)")
            print("  Los datos son SIMULADOS (decisión C-02).")

            bd = obtener_bd()
            df = ev.cargar_dataset(bd)
            serie = df[OBJETIVO]
            print(f"\n  Dataset: {len(df):,} entregas de calidad OK")
            print(f"  Retraso real: media {serie.mean():.1f} min · "
                  f"mediana {serie.median():.1f} min · "
                  f"desviación {serie.std():.1f} min")

            salidas = {escenario: entrenar_escenario(df, escenario)
                       for escenario in ("PLANEACION", "EN_RUTA")}

            for i, escenario in enumerate(("PLANEACION", "EN_RUTA"), start=1):
                imprimir_escenario(salidas[escenario], i)
            imprimir_comparacion(salidas)

            if not imprimir_verificaciones(verificar(salidas)):
                codigo = 1

            if not args.sin_archivos:
                titulo("5 · MODELOS GUARDADOS")
                for escenario, salida in salidas.items():
                    nombre = f"regresion_retraso_{escenario.lower()}"
                    destino = ev.guardar_modelo(
                        salida["pipelines"][salida["mejor"]], nombre)
                    ev.registrar_modelo(
                        bd,
                        nombre=nombre,
                        tipo="REGRESION",
                        escenario=escenario,
                        algoritmo=salida["mejor"],
                        objetivo=OBJETIVO,
                        metricas=salida["resultados"][salida["mejor"]],
                        n_entrenamiento=len(salida["y_entrenamiento"]),
                        n_prueba=len(salida["y_prueba"]),
                        variables=list(salida["X_prueba"].columns),
                        archivo=str(destino.relative_to(RAIZ)),
                    )
                    print(f"  {escenario:<12}{salida['mejor']:<24}"
                          f"{ruta_legible(destino)}")
                print("\n  Ficha de cada modelo registrada en la colección `modelos_ml`.")

            print()
            print("=" * 78)
            print("  PA-8 TERMINADA." if codigo == 0
                  else "  PA-8 TERMINADA CON FALLAS.")
            print("  Siguiente actividad: ML no supervisado (clustering de rutas).")
            print("=" * 78)

    except SystemExit as salida:
        codigo = int(salida.code or 0)
    except Exception:                              # noqa: BLE001
        codigo = 1
        memoria.write("\n" + "=" * 78 + "\n  ERROR EN LA REGRESIÓN\n"
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
