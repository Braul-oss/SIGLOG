"""
SIG-LOG — Sistema Integral de Gestión Logística
etl/extraccion.py

CAPA 4 DEL ETL — EXTRACCIÓN

Única puerta de lectura desde MongoDB hacia pandas. Lo usan la exploración
(PA-4), la limpieza (PA-5) y la transformación (PA-6).

Principio de la capa (§7.3): el ETL **lee** de la base operativa y nunca la
modifica. Ninguna función de este archivo escribe en las colecciones
operativas.

Equivalencia con los ejercicios de clase (Anexo A):
    spark.read.format("mongodb").load()   →   pd.DataFrame(list(coleccion.find()))
El volumen del proyecto (≈20,000 documentos, <20 MB) está tres órdenes de
magnitud por debajo del umbral en que un motor distribuido aporta ventaja.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

import pandas as pd

from config import settings
from config.mongo_conexion import obtener_bd

# Carpeta de extracciones crudas (§9.1: "extracciones sin tocar")
CARPETA_RAW = RAIZ / "data" / "raw"

# Columnas que guardan referencias entre colecciones
COLUMNAS_REFERENCIA = (
    "_id", "viaje_id", "ruta_id", "cliente_id", "vehiculo_id",
    "operador_id", "ruta_asignada_id", "vehiculo_asignado_id", "entrega_id",
)


def extraer(coleccion: str, filtro: dict[str, Any] | None = None,
            bd=None) -> pd.DataFrame:
    """
    Lee una colección completa y la devuelve como DataFrame.

    No aplica ninguna transformación: los documentos llegan tal como están
    almacenados, incluidos los arrays y objetos anidados. Esa es
    precisamente la materia prima de la limpieza posterior.
    """
    base = bd if bd is not None else obtener_bd()
    documentos = list(base[coleccion].find(filtro or {}))
    return pd.DataFrame(documentos)


def extraer_operativas(bd=None) -> dict[str, pd.DataFrame]:
    """Extrae las colecciones operativas que tienen documentos."""
    base = bd if bd is not None else obtener_bd()
    resultado: dict[str, pd.DataFrame] = {}
    for coleccion in settings.COLECCIONES_OPERATIVAS:
        df = extraer(coleccion, bd=base)
        if not df.empty:
            resultado[coleccion] = df
    return resultado


def aplanar_para_csv(df: pd.DataFrame) -> pd.DataFrame:
    """
    Convierte ObjectId y estructuras anidadas a texto para poder exportar.

    Solo se usa al escribir archivos. El DataFrame que consumen la limpieza
    y la transformación conserva los tipos originales.
    """
    copia = df.copy()
    for columna in copia.columns:
        if copia[columna].map(lambda v: isinstance(v, (list, dict))).any():
            copia[columna] = copia[columna].astype(str)
        elif columna in COLUMNAS_REFERENCIA:
            copia[columna] = copia[columna].astype(str)
    return copia


def guardar_raw(dataframes: dict[str, pd.DataFrame],
                carpeta: Path = CARPETA_RAW) -> list[Path]:
    """
    Escribe las extracciones crudas en data/raw/.

    Sirven para tres cosas: desarrollar el ETL sin depender de Atlas,
    entregar el repositorio de datos preprocesados que exige la secuencia
    didáctica, y alimentar Excel o Power BI.
    """
    carpeta.mkdir(parents=True, exist_ok=True)
    rutas: list[Path] = []
    for nombre, df in dataframes.items():
        destino = carpeta / f"{nombre}.csv"
        aplanar_para_csv(df).to_csv(destino, index=False, encoding="utf-8")
        rutas.append(destino)
    return rutas


def resumen_extraccion(dataframes: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Tabla de control de la extracción: filas, columnas y memoria."""
    filas = [
        {
            "coleccion": nombre,
            "documentos": len(df),
            "columnas": df.shape[1],
            "memoria_mb": round(df.memory_usage(deep=True).sum() / 1024**2, 2),
        }
        for nombre, df in dataframes.items()
    ]
    return pd.DataFrame(filas).sort_values("documentos", ascending=False)
