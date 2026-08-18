"""
SIG-LOG — Sistema Integral de Gestión Logística
ml/no_supervisado/kmeans_rutas.py

ACTIVIDAD PA-9 (parte 2) — AGRUPAMIENTO DE RUTAS CON K-MEANS
EVIDENCIA DE APRENDIZAJE NO SUPERVISADO

Responde la pregunta del caso de estudio:
    "¿Podemos identificar grupos de rutas similares?"

Toma el k decidido en seleccion_k.py, agrupa las rutas y —lo que da
sentido a la actividad— traduce cada grupo a un perfil legible con una
recomendación operativa. Un número de grupo no le sirve a nadie; "estas
cinco rutas concentran los retrasos y conviene revisarles la
programación" sí.

Cómo se nombran los grupos (D-K4)
---------------------------------
Las etiquetas NO están escritas a mano: se derivan comparando el centro
de cada grupo contra la mediana de la flotilla en dos ejes que son los
que importan para gestionar —cuán problemática es la ruta (retraso e
incidentes) y cuán grande es (distancia y paradas)—. Así, si los datos
cambian, las etiquetas cambian con ellos en lugar de mentir.

Resultado
---------
Cada ruta queda con su grupo en la colección `clusters_rutas`, lista
para que el sistema web la muestre y para los reportes en PDF.

Uso
---
    python -m ml.no_supervisado.kmeans_rutas
    python -m ml.no_supervisado.kmeans_rutas --k 3
    python -m ml.no_supervisado.kmeans_rutas --sin-archivos
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

RAIZ = Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_samples, silhouette_score

from config.mongo_conexion import cerrar_cliente, obtener_bd, verificar_conexion
from etl.exploracion import ruta_legible, subtitulo, titulo
from ml.evaluacion import (
    SEMILLA,
    VARIABLES_RUTA,
    cargar_rutas,
    escalar_rutas,
    proyectar_pca,
)
from ml.no_supervisado.seleccion_k import COMPONENTES_PCA, RANGO_K, elegir_k, evaluar_k

ARCHIVO_REPORTE = RAIZ / "data" / "outputs" / "reporte_kmeans.txt"
ARCHIVO_CSV = RAIZ / "data" / "processed" / "clusters_rutas.csv"

# Variables que definen los dos ejes de gestión (D-K4)
EJE_PROBLEMA = ("retraso_medio_min", "incidentes_por_viaje")
EJE_TAMANO = ("distancia_total_km", "numero_paradas")


# ==========================================================================
# AGRUPAMIENTO
# ==========================================================================
def agrupar(rutas: pd.DataFrame, k: int) -> dict[str, Any]:
    """Ejecuta K-Means en el espacio PCA (decisión D-K2)."""
    X, escalador = escalar_rutas(rutas)
    X_pca, modelo_pca = proyectar_pca(X, COMPONENTES_PCA)

    modelo = KMeans(n_clusters=k, random_state=SEMILLA, n_init=10)
    etiquetas = modelo.fit_predict(X_pca)

    return {
        "k": k,
        "etiquetas": etiquetas,
        "modelo": modelo,
        "modelo_pca": modelo_pca,
        "X_pca": X_pca,
        "silueta_global": float(silhouette_score(X_pca, etiquetas)),
        "silueta_individual": silhouette_samples(X_pca, etiquetas),
        "inercia": float(modelo.inertia_),
    }


def perfilar(rutas: pd.DataFrame, resultado: dict[str, Any]) -> pd.DataFrame:
    """Centro de cada grupo expresado en las unidades originales."""
    df = rutas.assign(grupo=resultado["etiquetas"])
    perfil = (df.groupby("grupo")[list(VARIABLES_RUTA)].mean().round(2))
    perfil.insert(0, "rutas", df.groupby("grupo").size())
    perfil["silueta_media"] = (pd.Series(resultado["silueta_individual"])
                               .groupby(resultado["etiquetas"]).mean().round(3))
    return perfil


# ==========================================================================
# INTERPRETACIÓN  (D-K4)
# ==========================================================================
def _posicion(valor: float, mediana: float) -> int:
    """+1 por encima de la mediana de la flotilla, -1 por debajo."""
    return 1 if valor > mediana else -1


def etiquetar(rutas: pd.DataFrame, perfil: pd.DataFrame) -> pd.DataFrame:
    """
    Deriva nombre y recomendación de cada grupo a partir de su posición
    frente a la mediana de la flotilla en los dos ejes de gestión.
    """
    medianas = rutas[list(VARIABLES_RUTA)].median()

    nombres, descripciones, recomendaciones = [], [], []
    for grupo in perfil.index:
        fila = perfil.loc[grupo]
        problema = sum(_posicion(fila[v], medianas[v]) for v in EJE_PROBLEMA)
        tamano = sum(_posicion(fila[v], medianas[v]) for v in EJE_TAMANO)

        es_problematica = problema > 0
        es_grande = tamano > 0

        if es_problematica and es_grande:
            nombre = "RUTAS LARGAS CRÍTICAS"
            descripcion = ("recorridos extensos que además acumulan retraso "
                           "e incidentes por encima de la mediana")
            recomendacion = ("Prioridad de revisión: dividir la ruta o "
                             "adelantar la hora de salida. Es donde una mejora "
                             "rinde más, porque afecta a muchas entregas.")
        elif es_problematica and not es_grande:
            nombre = "RUTAS CORTAS PROBLEMÁTICAS"
            descripcion = ("recorridos breves que aun así se retrasan: el "
                           "problema no es la distancia")
            recomendacion = ("Revisar causas locales: tráfico en la zona, "
                             "ventanas horarias del cliente o disciplina de "
                             "salida. Alargar los tiempos no lo resolvería.")
        elif not es_problematica and es_grande:
            nombre = "RUTAS LARGAS ESTABLES"
            descripcion = ("recorridos extensos que cumplen: la longitud "
                           "está bien absorbida por la programación")
            recomendacion = ("Mantener la programación actual y usarlas como "
                             "referencia de buena práctica para rediseñar las "
                             "críticas.")
        else:
            nombre = "RUTAS CORTAS ESTABLES"
            descripcion = "recorridos breves y puntuales: el núcleo sano de la operación"
            recomendacion = ("Sin intervención. Son candidatas a absorber "
                             "paradas de las rutas críticas si hiciera falta "
                             "rebalancear.")

        nombres.append(nombre)
        descripciones.append(descripcion)
        recomendaciones.append(recomendacion)

    resultado = perfil.copy()
    resultado["nombre"] = nombres
    resultado["descripcion"] = descripciones
    resultado["recomendacion"] = recomendaciones
    return _desambiguar(resultado)


def _desambiguar(perfil: pd.DataFrame) -> pd.DataFrame:
    """
    Dos grupos pueden caer en la misma casilla de la matriz. Cuando pasa,
    se distinguen por su retraso medio para que ningún nombre se repita.
    """
    for nombre, repetidos in perfil.groupby("nombre").groups.items():
        if len(repetidos) < 2:
            continue
        orden = perfil.loc[repetidos].sort_values("retraso_medio_min",
                                                  ascending=False).index
        for posicion, grupo in enumerate(orden):
            sufijo = " (mayor retraso)" if posicion == 0 else " (menor retraso)"
            perfil.loc[grupo, "nombre"] = f"{nombre}{sufijo}"
    return perfil


# ==========================================================================
# PERSISTENCIA
# ==========================================================================
def guardar_clusters(bd, rutas: pd.DataFrame, resultado: dict[str, Any],
                     perfil: pd.DataFrame) -> pd.DataFrame:
    """Escribe una fila por ruta en `clusters_rutas` (carga idempotente)."""
    asignacion = rutas[["_id", "codigo_ruta", "nombre", "zona"]].copy()
    asignacion = asignacion.rename(columns={"nombre": "nombre_ruta"})
    asignacion["grupo"] = resultado["etiquetas"]
    asignacion["silueta"] = resultado["silueta_individual"].round(3)
    asignacion["nombre_grupo"] = asignacion["grupo"].map(perfil["nombre"])
    asignacion["descripcion_grupo"] = asignacion["grupo"].map(perfil["descripcion"])
    asignacion["recomendacion"] = asignacion["grupo"].map(perfil["recomendacion"])
    for variable in VARIABLES_RUTA:
        asignacion[variable] = rutas[variable].values
    asignacion["componente_1"] = resultado["X_pca"][:, 0].round(3)
    asignacion["componente_2"] = resultado["X_pca"][:, 1].round(3)

    documentos = []
    for registro in asignacion.to_dict("records"):
        documento = {clave: (valor.item() if isinstance(valor, np.generic) else valor)
                     for clave, valor in registro.items()}
        documento.update({
            "k": resultado["k"],
            "silueta_global": round(resultado["silueta_global"], 4),
            "algoritmo": "KMeans",
            "espacio": f"PCA-{COMPONENTES_PCA}",
            "semilla": SEMILLA,
            "origen_dato": "SIMULADO",
            "fecha_agrupamiento": datetime.now(timezone.utc),
        })
        documentos.append(documento)

    bd["clusters_rutas"].delete_many({})
    bd["clusters_rutas"].insert_many(documentos, ordered=False)
    return asignacion


# ==========================================================================
# REPORTE
# ==========================================================================
def imprimir_perfiles(perfil: pd.DataFrame, resultado: dict[str, Any]) -> None:
    titulo("2 · PERFIL DE CADA GRUPO")
    columnas = ["rutas", *VARIABLES_RUTA, "silueta_media"]
    print(perfil[columnas].to_string())
    print("\n  Valores en unidades originales (el agrupamiento se hizo sobre")
    print("  variables estandarizadas y proyectadas a componentes principales).")

    titulo("3 · LECTURA OPERATIVA DE CADA GRUPO  (D-K4)")
    for grupo in perfil.index:
        fila = perfil.loc[grupo]
        print(f"\n  GRUPO {grupo} — {fila['nombre']}  ({int(fila['rutas'])} rutas)")
        print(f"      {fila['descripcion'].capitalize()}.")
        print(f"      Retraso medio {fila['retraso_medio_min']:.1f} min · "
              f"{fila['distancia_total_km']:.0f} km · "
              f"{fila['numero_paradas']:.1f} paradas · "
              f"{fila['incidentes_por_viaje']:.2f} incidentes/viaje")
        print(f"      RECOMENDACIÓN: {fila['recomendacion']}")


def imprimir_asignacion(asignacion: pd.DataFrame, perfil: pd.DataFrame) -> None:
    titulo("4 · RUTAS POR GRUPO")
    for grupo in sorted(asignacion["grupo"].unique()):
        rutas_grupo = asignacion[asignacion["grupo"] == grupo]
        print(f"\n  GRUPO {grupo} — {perfil.loc[grupo, 'nombre']}")
        print(f"      {'RUTA':<10}{'ZONA':<10}{'RETRASO':>9}{'KM':>8}"
              f"{'PARADAS':>9}{'SILUETA':>9}")
        for _, fila in rutas_grupo.sort_values("retraso_medio_min",
                                               ascending=False).iterrows():
            print(f"      {fila['codigo_ruta']:<10}{fila['zona']:<10}"
                  f"{fila['retraso_medio_min']:>9.1f}"
                  f"{fila['distancia_total_km']:>8.1f}"
                  f"{fila['numero_paradas']:>9.0f}{fila['silueta']:>9.3f}")

    subtitulo("DISTRIBUCIÓN POR ZONA")
    tabla = pd.crosstab(asignacion["zona"], asignacion["nombre_grupo"])
    print(tabla.to_string())
    print("\n  Si un grupo se concentrara en una sola zona, el problema sería")
    print("  geográfico; si se reparte, es de diseño o programación de la ruta.")


def verificar(rutas: pd.DataFrame, resultado: dict[str, Any],
              perfil: pd.DataFrame, bd) -> list[tuple[str, bool, str]]:
    conteo = np.bincount(resultado["etiquetas"])
    en_bd = bd["clusters_rutas"].count_documents({})
    negativas = int((resultado["silueta_individual"] < 0).sum())
    return [
        ("Toda ruta quedó asignada a un grupo",
         len(resultado["etiquetas"]) == len(rutas), f"{len(rutas)} rutas"),
        ("Ningún grupo con una sola ruta", int(conteo.min()) >= 2,
         f"tamaños {sorted(conteo.tolist())}"),
        ("Silueta global por encima del azar",
         resultado["silueta_global"] > 0.25, f"{resultado['silueta_global']:.3f}"),
        ("Rutas mal asignadas (silueta < 0) acotadas",
         negativas <= 2, f"{negativas} de {len(rutas)}"),
        ("Cada grupo tiene nombre y recomendación propios",
         perfil["nombre"].nunique() == len(perfil), f"{len(perfil)} nombres únicos"),
        ("Persistido en `clusters_rutas`", en_bd == len(rutas),
         f"{en_bd} documentos"),
    ]


def imprimir_verificaciones(resultados: list[tuple[str, bool, str]]) -> bool:
    titulo("5 · VERIFICACIONES AUTOMÁTICAS")
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
        description="PA-9 — Agrupamiento de rutas con K-Means.",
    )
    parser.add_argument("--k", type=int, default=None,
                        help="Fuerza un número de grupos (por defecto: el que "
                             "decide seleccion_k.py).")
    parser.add_argument("--sin-archivos", action="store_true",
                        help="No escribe el CSV ni el reporte.")
    args = parser.parse_args()

    if not verificar_conexion(verbose=True)["exito"]:
        return 1

    memoria = io.StringIO()
    codigo = 0

    try:
        with contextlib.redirect_stdout(memoria):
            titulo("SIG-LOG · AGRUPAMIENTO DE RUTAS CON K-MEANS (PA-9)")
            print("  Los datos son SIMULADOS (decisión C-02).")

            bd = obtener_bd()
            rutas = cargar_rutas(bd)

            titulo("1 · CONFIGURACIÓN DEL AGRUPAMIENTO")
            if args.k:
                k = args.k
                print(f"  k = {k} (forzado por parámetro --k)")
            else:
                X, _ = escalar_rutas(rutas)
                X_pca, _ = proyectar_pca(X, COMPONENTES_PCA)
                k, justificacion = elegir_k(evaluar_k(X_pca, RANGO_K))
                print(f"  k = {k}, decidido por seleccion_k.py")
                print(f"  {justificacion}")

            resultado = agrupar(rutas, k)
            print(f"\n  Algoritmo ......... KMeans (semilla {SEMILLA}, 10 inicios)")
            print(f"  Espacio ........... {COMPONENTES_PCA} componentes principales")
            print(f"  Variables ......... {len(VARIABLES_RUTA)} del perfil de ruta")
            print(f"  Silueta global .... {resultado['silueta_global']:.3f}")
            print(f"  Inercia ........... {resultado['inercia']:.2f}")

            perfil = etiquetar(rutas, perfilar(rutas, resultado))
            imprimir_perfiles(perfil, resultado)

            asignacion = guardar_clusters(bd, rutas, resultado, perfil)
            imprimir_asignacion(asignacion, perfil)

            if not imprimir_verificaciones(verificar(rutas, resultado, perfil, bd)):
                codigo = 1

            if not args.sin_archivos:
                ARCHIVO_CSV.parent.mkdir(parents=True, exist_ok=True)
                asignacion.assign(_id=asignacion["_id"].astype(str)).to_csv(
                    ARCHIVO_CSV, index=False, encoding="utf-8")
                titulo("6 · ARCHIVOS GENERADOS")
                print(f"  {ruta_legible(ARCHIVO_CSV):<44}"
                      f"{ARCHIVO_CSV.stat().st_size/1024:>8.1f} KB")
                print(f"  {ruta_legible(ARCHIVO_REPORTE)}")
                print(f"\n  Colección `clusters_rutas`: {len(asignacion)} documentos.")

            print()
            print("=" * 78)
            print("  AGRUPAMIENTO TERMINADO." if codigo == 0
                  else "  AGRUPAMIENTO TERMINADO CON FALLAS.")
            print("  Sigue: python -m ml.no_supervisado.pca_rutas")
            print("=" * 78)

    except SystemExit as salida:
        codigo = int(salida.code or 0)
    except Exception:                              # noqa: BLE001
        codigo = 1
        memoria.write("\n" + "=" * 78 + "\n  ERROR EN EL AGRUPAMIENTO\n"
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
