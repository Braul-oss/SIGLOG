"""
SIG-LOG — Sistema Integral de Gestión Logística
ml/evaluacion.py

MÉTRICAS Y UTILIDADES COMPARTIDAS DE MACHINE LEARNING

Este módulo concentra todo lo que comparten la clasificación y la
regresión, para que ambos modelos se midan exactamente con el mismo
criterio y sean comparables entre sí:

    · lectura del dataset de entrenamiento desde el DW;
    · definición de los ESCENARIOS de predicción (qué información está
      disponible en cada momento de la operación);
    · partición train/test reproducible (semilla 42, la misma de todos
      los ejercicios de clase y del generador de datos);
    · preprocesamiento (escalado de numéricas, one-hot de categóricas);
    · métricas de clasificación y de regresión;
    · registro del modelo entrenado en la colección `modelos_ml`.

EL PUNTO MÁS IMPORTANTE: FUGA DE INFORMACIÓN
--------------------------------------------
El dataset contiene columnas que solo existen DESPUÉS de que la entrega
ocurrió (`tiempo_real_min`, `causa_retraso`, `es_outlier_iqr`). Usarlas
para predecir el retraso produciría métricas casi perfectas y un modelo
inservible: en el momento en que hay que decidir, esos datos no existen.

Por eso las variables se declaran por ESCENARIO, según el instante de la
operación en que se haría la predicción:

    PLANEACION  lo que se conoce ANTES de que el vehículo salga.
                Responde: "¿esta entrega programada es de riesgo?"
    EN_RUTA     agrega lo ya ocurrido durante el viaje (retraso de
                salida e incidentes). Responde: "¿esta entrega en curso
                va a llegar tarde?"

Ambos son legítimos y responden preguntas distintas del caso de estudio.
Entrenar los dos y compararlos muestra cuánta información aporta el
seguimiento en tiempo real frente a la sola planeación.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    f1_score,
    mean_absolute_error,
    mean_squared_error,
    precision_score,
    r2_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from config import settings
from config.mongo_conexion import obtener_bd

# Semilla única del proyecto (la misma de database/seed/parametros.py)
SEMILLA: int = 42
PROPORCION_PRUEBA: float = 0.2

CARPETA_MODELOS = RAIZ / "ml" / "modelos_entrenados"

# --------------------------------------------------------------------------
# ESCENARIOS DE PREDICCIÓN
# --------------------------------------------------------------------------
# Conocido al programar el viaje: ruta, vehículo, operador, cliente y tiempo.
FEATURES_PLANEACION: dict[str, list[str]] = {
    "numericas": [
        "orden_parada", "tiempo_estimado_min", "distancia_km",
        "dia_semana", "es_fin_semana", "mes",
        "numero_paradas_ruta", "distancia_total_ruta_km",
        "velocidad_efectiva_kmh", "antiguedad_vehiculo_anios",
        "rendimiento_nominal_km_l", "experiencia_operador_meses",
    ],
    "categoricas": ["franja_horaria", "zona", "tipo_vehiculo", "tipo_cliente"],
}

# Conocido una vez que el viaje está en curso: se suma lo ya ocurrido.
FEATURES_EN_RUTA: dict[str, list[str]] = {
    "numericas": FEATURES_PLANEACION["numericas"] + [
        "retraso_salida_min", "n_incidentes_acumulados", "incidentes_viaje",
    ],
    "categoricas": FEATURES_PLANEACION["categoricas"],
}

ESCENARIOS: dict[str, dict[str, list[str]]] = {
    "PLANEACION": FEATURES_PLANEACION,
    "EN_RUTA": FEATURES_EN_RUTA,
}

# Columnas prohibidas: se conocen solo después del hecho que se predice.
COLUMNAS_CON_FUGA = (
    "tiempo_real_min", "retraso_min", "es_retraso",
    "causa_retraso", "es_outlier_iqr", "hora_real_llegada",
)


# ==========================================================================
# 1 · DATASET DE ENTRENAMIENTO
# ==========================================================================
def cargar_dataset(bd=None) -> pd.DataFrame:
    """
    Lee `hecho_entrega` del data warehouse y devuelve solo las filas
    utilizables para entrenar.

    El filtro `calidad_dato == "OK"` aplica la decisión D-L3 de PA-5: las
    entregas con captura omitida no tienen variable objetivo, y las
    canceladas nunca ocurrieron.
    """
    base = bd if bd is not None else obtener_bd()
    documentos = list(base["hecho_entrega"].find({"calidad_dato": "OK"}, {"_id": 0}))
    if not documentos:
        raise RuntimeError(
            "`hecho_entrega` está vacía o sin filas OK. Ejecuta antes: "
            "python -m etl.run_etl"
        )
    return pd.DataFrame(documentos)


def columnas_del_escenario(escenario: str) -> list[str]:
    definicion = ESCENARIOS[escenario]
    return definicion["numericas"] + definicion["categoricas"]


def preparar(df: pd.DataFrame, escenario: str, objetivo: str
             ) -> tuple[pd.DataFrame, pd.Series]:
    """Devuelve (X, y) para el escenario indicado, sin columnas con fuga."""
    columnas = columnas_del_escenario(escenario)
    filtradas = [c for c in columnas if c in COLUMNAS_CON_FUGA]
    if filtradas:                                   # salvaguarda explícita
        raise ValueError(f"Variables con fuga en el escenario: {filtradas}")

    datos = df.dropna(subset=[objetivo]).copy()
    return datos[columnas], datos[objetivo]


def dividir(X: pd.DataFrame, y: pd.Series, estratificar: bool = False):
    """Partición train/test reproducible (semilla 42, como en clase)."""
    return train_test_split(
        X, y,
        test_size=PROPORCION_PRUEBA,
        random_state=SEMILLA,
        stratify=y if estratificar else None,
    )


# ==========================================================================
# 2 · PREPROCESAMIENTO
# ==========================================================================
def crear_preprocesador(escenario: str) -> ColumnTransformer:
    """
    Escala las numéricas y codifica las categóricas con one-hot.

    El escalado es indispensable para los modelos lineales (regresión
    logística y lineal), donde variables en escalas distintas
    distorsionan los coeficientes; los modelos de árbol lo ignoran sin
    verse afectados, así que un solo preprocesador sirve para todos.
    """
    definicion = ESCENARIOS[escenario]
    return ColumnTransformer([
        ("numericas", StandardScaler(), definicion["numericas"]),
        ("categoricas", OneHotEncoder(handle_unknown="ignore", drop="first"),
         definicion["categoricas"]),
    ])


def crear_pipeline(escenario: str, modelo) -> Pipeline:
    """Preprocesamiento + modelo en un solo objeto entrenable y guardable."""
    return Pipeline([
        ("preparacion", crear_preprocesador(escenario)),
        ("modelo", modelo),
    ])


# ==========================================================================
# 3 · MÉTRICAS
# ==========================================================================
def metricas_clasificacion(y_real, y_pred, y_proba=None) -> dict[str, float]:
    """
    Métricas de clasificación binaria.

    PA-4 dejó la instrucción explícita: con 27.8% de positivos, la
    exactitud sola engaña (un modelo que nunca predice retraso acierta
    72%). Por eso se reportan siempre recall y F1.
    """
    metricas = {
        "exactitud": accuracy_score(y_real, y_pred),
        "precision": precision_score(y_real, y_pred, zero_division=0),
        "recall": recall_score(y_real, y_pred, zero_division=0),
        "f1": f1_score(y_real, y_pred, zero_division=0),
    }
    if y_proba is not None:
        metricas["roc_auc"] = roc_auc_score(y_real, y_proba)
    return metricas


def metricas_regresion(y_real, y_pred) -> dict[str, float]:
    return {
        "rmse": float(np.sqrt(mean_squared_error(y_real, y_pred))),
        "mae": float(mean_absolute_error(y_real, y_pred)),
        "r2": float(r2_score(y_real, y_pred)),
    }


# ==========================================================================
# 4 · PRESENTACIÓN
# ==========================================================================
def imprimir_tabla_metricas(resultados: dict[str, dict[str, float]],
                            columnas: tuple[str, ...]) -> None:
    """Tabla comparativa modelo × métrica."""
    print(f"  {'MODELO':<28}" + "".join(f"{c.upper():>10}" for c in columnas))
    print("-" * 78)
    for nombre, metricas in resultados.items():
        valores = "".join(f"{metricas.get(c, float('nan')):>10.3f}" for c in columnas)
        print(f"  {nombre:<28}{valores}")


def imprimir_matriz_confusion(y_real, y_pred) -> None:
    """Matriz de confusión con lectura operativa de cada celda."""
    (vn, fp), (fn, vp) = confusion_matrix(y_real, y_pred)
    print(f"  {'':<22}{'Predicho: A TIEMPO':>22}{'Predicho: RETRASO':>20}")
    print(f"  {'Real: A TIEMPO':<22}{vn:>22,}{fp:>20,}")
    print(f"  {'Real: RETRASO':<22}{fn:>22,}{vp:>20,}")
    print()
    print(f"      Verdaderos positivos {vp:>6,}  retrasos detectados a tiempo")
    print(f"      Falsos negativos     {fn:>6,}  retrasos que el sistema NO avisó")
    print(f"      Falsos positivos     {fp:>6,}  alertas en entregas que sí llegaron bien")
    print(f"      Verdaderos negativos {vn:>6,}  entregas correctamente descartadas")


def importancias(pipeline: Pipeline, n: int = 12) -> pd.Series:
    """
    Importancia de variables del modelo final, con los nombres reales
    después del one-hot. Es lo que permite explicar el resultado en
    lenguaje de negocio y no solo como métrica.
    """
    modelo = pipeline.named_steps["modelo"]
    nombres = pipeline.named_steps["preparacion"].get_feature_names_out()
    nombres = [n.split("__", 1)[-1] for n in nombres]

    if hasattr(modelo, "feature_importances_"):
        valores = modelo.feature_importances_
    elif hasattr(modelo, "coef_"):
        valores = np.abs(np.ravel(modelo.coef_))
    else:
        return pd.Series(dtype=float)
    return pd.Series(valores, index=nombres).sort_values(ascending=False).head(n)


# ==========================================================================
# 5 · PERSISTENCIA DEL MODELO
# ==========================================================================
def guardar_modelo(pipeline: Pipeline, nombre_archivo: str) -> Path:
    """Serializa el pipeline entrenado (preprocesamiento incluido)."""
    import joblib

    CARPETA_MODELOS.mkdir(parents=True, exist_ok=True)
    destino = CARPETA_MODELOS / f"{nombre_archivo}.joblib"
    joblib.dump(pipeline, destino)
    return destino


def registrar_modelo(bd, *, nombre: str, tipo: str, escenario: str,
                     algoritmo: str, objetivo: str, metricas: dict[str, float],
                     n_entrenamiento: int, n_prueba: int,
                     variables: list[str], archivo: str | None = None) -> None:
    """
    Deja constancia del modelo entrenado en la colección `modelos_ml`.

    Guarda la ficha (algoritmo, escenario, métricas, tamaño de las
    particiones), no el binario: así el sistema web puede mostrar qué
    modelo está vigente y con qué desempeño se aprobó.
    """
    bd["modelos_ml"].replace_one(
        {"nombre": nombre},
        {
            "nombre": nombre,
            "tipo": tipo,
            "escenario": escenario,
            "algoritmo": algoritmo,
            "variable_objetivo": objetivo,
            "metricas": {k: round(float(v), 4) for k, v in metricas.items()},
            "n_entrenamiento": int(n_entrenamiento),
            "n_prueba": int(n_prueba),
            "n_variables": len(variables),
            "variables": variables,
            "semilla": SEMILLA,
            "archivo": archivo,
            "umbral_retraso_min": settings.UMBRAL_RETRASO_MIN,
            "origen_dato": "SIMULADO",
            "fecha_entrenamiento": datetime.now(timezone.utc),
        },
        upsert=True,
    )
