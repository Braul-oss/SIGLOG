"""
SIG-LOG — Sistema Integral de Gestión Logística
ml/supervisado/clasificacion_retraso.py

ACTIVIDAD PA-8 (parte 1) — CLASIFICACIÓN DEL RIESGO DE RETRASO
EVIDENCIA DE APRENDIZAJE SUPERVISADO

Responde la pregunta del caso de estudio:
    "¿Es posible predecir si una entrega llegará tarde?"

Variable objetivo: `es_retraso` (1 si el retraso supera el umbral RNP-01
de 15 minutos). Es un problema de clasificación binaria con 27.8% de
positivos.

Modelos comparados
------------------
    Base (mayoría)        nunca predice retraso. Es la vara mínima: si un
                          modelo no lo supera, no aporta nada.
    Regresión logística   modelo lineal interpretable, referencia clásica.
    Árbol de decisión     reglas legibles, capta no linealidades.
    Random Forest         conjunto de árboles; suele dar el mejor
                          desempeño y entrega importancia de variables.

Los cuatro se entrenan en los DOS escenarios definidos en ml/evaluacion.py
(PLANEACION y EN_RUTA), de modo que el reporte muestre cuánto mejora la
predicción cuando el sistema ya está siguiendo el viaje.

Criterio de selección: F1 sobre la clase "retraso". No exactitud —con
27.8% de positivos, el modelo base ya alcanza 72% de exactitud sin
predecir un solo retraso, como advirtió la exploración de PA-4.

Uso
---
    python -m ml.supervisado.clasificacion_retraso
    python -m ml.supervisado.clasificacion_retraso --sin-archivos
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

import pandas as pd
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import cross_val_score
from sklearn.tree import DecisionTreeClassifier

from config import settings
from config.mongo_conexion import cerrar_cliente, obtener_bd, verificar_conexion
from etl.exploracion import ruta_legible, subtitulo, titulo
from ml import evaluacion as ev

ARCHIVO_REPORTE = RAIZ / "data" / "outputs" / "reporte_clasificacion.txt"
OBJETIVO = "es_retraso"

METRICAS_MOSTRADAS = ("exactitud", "precision", "recall", "f1", "roc_auc")


def catalogo_modelos() -> dict[str, Any]:
    """
    Modelos a comparar.

    `class_weight="balanced"` compensa el desbalance 72/28 penalizando
    más los errores sobre la clase minoritaria: sin él, los modelos
    tienden a no avisar de los retrasos, que es justo lo que interesa
    detectar.
    """
    return {
        "Base (siempre a tiempo)": DummyClassifier(strategy="most_frequent"),
        "Regresión logística": LogisticRegression(
            max_iter=1000, class_weight="balanced", random_state=ev.SEMILLA),
        "Árbol de decisión": DecisionTreeClassifier(
            max_depth=8, min_samples_leaf=50, class_weight="balanced",
            random_state=ev.SEMILLA),
        "Random Forest": RandomForestClassifier(
            n_estimators=200, max_depth=14, min_samples_leaf=5,
            class_weight="balanced", n_jobs=-1, random_state=ev.SEMILLA),
    }


def entrenar_escenario(df: pd.DataFrame, escenario: str) -> dict[str, Any]:
    """Entrena y evalúa todos los modelos en un escenario."""
    X, y = ev.preparar(df, escenario, OBJETIVO)
    X_ent, X_pru, y_ent, y_pru = ev.dividir(X, y, estratificar=True)

    resultados: dict[str, dict[str, float]] = {}
    pipelines: dict[str, Any] = {}

    for nombre, modelo in catalogo_modelos().items():
        pipeline = ev.crear_pipeline(escenario, modelo)
        pipeline.fit(X_ent, y_ent)

        y_pred = pipeline.predict(X_pru)
        try:
            y_proba = pipeline.predict_proba(X_pru)[:, 1]
        except (AttributeError, IndexError):
            y_proba = None

        resultados[nombre] = ev.metricas_clasificacion(y_pru, y_pred, y_proba)
        pipelines[nombre] = pipeline

    mejor = max((n for n in resultados if not n.startswith("Base")),
                key=lambda n: resultados[n]["f1"])

    return {
        "escenario": escenario,
        "resultados": resultados,
        "pipelines": pipelines,
        "mejor": mejor,
        "X_prueba": X_pru, "y_prueba": y_pru,
        "X_entrenamiento": X_ent, "y_entrenamiento": y_ent,
        "n_variables": X.shape[1],
    }


def validacion_cruzada(salida: dict[str, Any]) -> tuple[float, float]:
    """5-fold sobre el conjunto de entrenamiento: mide si el desempeño
    es estable o dependía de una partición afortunada."""
    puntajes = cross_val_score(
        salida["pipelines"][salida["mejor"]],
        salida["X_entrenamiento"], salida["y_entrenamiento"],
        cv=5, scoring="f1", n_jobs=-1,
    )
    return float(puntajes.mean()), float(puntajes.std())


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
    base = salida["resultados"]["Base (siempre a tiempo)"]
    print(f"\n  Mejor por F1: {mejor}")
    print(f"      Detecta el {metricas['recall']:.1%} de los retrasos reales; "
          f"de cada 100 alertas, {metricas['precision']*100:.0f} son ciertas.")
    print(f"      El modelo base alcanza {base['exactitud']:.1%} de exactitud "
          "sin detectar un solo retraso:")
    print("      por eso el criterio es F1 y no exactitud.")

    subtitulo("MATRIZ DE CONFUSIÓN DEL MEJOR MODELO (conjunto de prueba)")
    y_pred = salida["pipelines"][mejor].predict(salida["X_prueba"])
    ev.imprimir_matriz_confusion(salida["y_prueba"], y_pred)

    media, desviacion = validacion_cruzada(salida)
    subtitulo("VALIDACIÓN CRUZADA (5 particiones, F1)")
    print(f"      F1 medio {media:.3f} ± {desviacion:.3f}")
    print("      Desviación baja = el desempeño no dependió de la partición.")

    subtitulo("VARIABLES MÁS INFLUYENTES")
    for variable, peso in ev.importancias(salida["pipelines"][mejor]).items():
        print(f"      {variable:<34}{peso:>7.3f}")


def imprimir_comparacion(salidas: dict[str, dict[str, Any]]) -> None:
    titulo("3 · QUÉ APORTA EL SEGUIMIENTO EN TIEMPO REAL")
    plan = salidas["PLANEACION"]
    ruta = salidas["EN_RUTA"]
    f1_plan = plan["resultados"][plan["mejor"]]["f1"]
    f1_ruta = ruta["resultados"][ruta["mejor"]]["f1"]
    rec_plan = plan["resultados"][plan["mejor"]]["recall"]
    rec_ruta = ruta["resultados"][ruta["mejor"]]["recall"]

    print(f"  {'ESCENARIO':<16}{'F1':>10}{'RECALL':>10}   LECTURA OPERATIVA")
    print("-" * 78)
    print(f"  {'PLANEACION':<16}{f1_plan:>10.3f}{rec_plan:>10.3f}   "
          "riesgo estimado al programar la ruta")
    print(f"  {'EN_RUTA':<16}{f1_ruta:>10.3f}{rec_ruta:>10.3f}   "
          "alerta con el viaje ya iniciado")
    print(f"\n  Ganancia de F1 al seguir el viaje: {f1_ruta - f1_plan:+.3f}")
    print("  Interpretación: el retraso de salida y los incidentes ocurridos")
    print("  son la información que más mejora la predicción. Justifica que el")
    print("  sistema web capture esos eventos durante la operación, no al cierre.")


def verificar(salidas: dict[str, dict[str, Any]]) -> list[tuple[str, bool, str]]:
    resultados = []
    for escenario, salida in salidas.items():
        mejor = salida["resultados"][salida["mejor"]]
        base = salida["resultados"]["Base (siempre a tiempo)"]
        resultados.append(
            (f"{escenario}: supera al modelo base en F1",
             mejor["f1"] > base["f1"], f"{mejor['f1']:.3f} vs {base['f1']:.3f}"))
        resultados.append(
            (f"{escenario}: ROC-AUC mejor que el azar",
             mejor.get("roc_auc", 0) > 0.5, f"{mejor.get('roc_auc', 0):.3f}"))
        resultados.append(
            (f"{escenario}: sin variables con fuga",
             not set(salida["X_prueba"].columns) & set(ev.COLUMNAS_CON_FUGA),
             f"{salida['n_variables']} variables verificadas"))

    plan, ruta = salidas["PLANEACION"], salidas["EN_RUTA"]
    resultados.append(
        ("EN_RUTA mejora sobre PLANEACION",
         ruta["resultados"][ruta["mejor"]]["f1"] > plan["resultados"][plan["mejor"]]["f1"],
         "más información, mejor predicción"))
    return resultados


def imprimir_verificaciones(resultados: list[tuple[str, bool, str]]) -> bool:
    titulo("4 · VERIFICACIONES AUTOMÁTICAS")
    for nombre, ok, detalle in resultados:
        print(f"  {'[OK]   ' if ok else '[FALLA]'} {nombre:<44}{detalle}")
    fallos = sum(1 for _, ok, _ in resultados if not ok)
    print("-" * 78)
    print(f"  {len(resultados) - fallos}/{len(resultados)} verificaciones correctas")
    return fallos == 0


# ==========================================================================
# PUNTO DE ENTRADA
# ==========================================================================
def main() -> int:
    parser = argparse.ArgumentParser(
        description="PA-8 — Clasificación del riesgo de retraso (aprendizaje supervisado).",
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
            titulo("SIG-LOG · CLASIFICACIÓN DEL RIESGO DE RETRASO (PA-8)")
            print("  Los datos son SIMULADOS (decisión C-02).")
            print(f"  Umbral de retraso (RNP-01): {settings.UMBRAL_RETRASO_MIN} minutos.")

            bd = obtener_bd()
            df = ev.cargar_dataset(bd)
            positivos = int(df[OBJETIVO].sum())
            print(f"\n  Dataset: {len(df):,} entregas de calidad OK · "
                  f"{positivos:,} con retraso ({positivos/len(df):.1%})")

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
                    nombre = f"clasificacion_retraso_{escenario.lower()}"
                    destino = ev.guardar_modelo(salida["pipelines"][salida["mejor"]],
                                                nombre)
                    ev.registrar_modelo(
                        bd,
                        nombre=nombre,
                        tipo="CLASIFICACION",
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
            print("  CLASIFICACIÓN TERMINADA." if codigo == 0
                  else "  CLASIFICACIÓN TERMINADA CON FALLAS.")
            print("  Sigue: python -m ml.supervisado.regresion_retraso")
            print("=" * 78)

    except SystemExit as salida:
        codigo = int(salida.code or 0)
    except Exception:                              # noqa: BLE001
        codigo = 1
        memoria.write("\n" + "=" * 78 + "\n  ERROR EN LA CLASIFICACIÓN\n"
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
