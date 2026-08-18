"""
SIG-LOG — Sistema Integral de Gestión Logística
ml/no_supervisado/pca_rutas.py

ACTIVIDAD PA-9 (parte 3) — ANÁLISIS DE COMPONENTES PRINCIPALES
EVIDENCIA DE APRENDIZAJE NO SUPERVISADO

El PCA cumple dos papeles distintos en esta actividad:

  1. ES EL ESPACIO DONDE SE AGRUPA. La decisión D-K2 de seleccion_k.py
     mostró que en el perfil completo las rutas no se separan (silueta
     ~0.16) y sobre componentes principales sí (~0.40). Aquí se explica
     POR QUÉ: qué mide cada componente y cuánta información conserva.

  2. HACE VISIBLE EL RESULTADO. Seis variables no se pueden dibujar;
     dos sí. La gráfica de dispersión permite ver si los grupos están
     realmente separados o si el algoritmo partió un continuo.

Lo que NO hay que perder de vista: los dos componentes conservan poco más
de la mitad de la varianza original. Es suficiente para agrupar y
visualizar, pero al leer la gráfica hay que recordar que se está viendo
una sombra del perfil completo, no el perfil entero.

Uso
---
    python -m ml.no_supervisado.pca_rutas
    python -m ml.no_supervisado.pca_rutas --sin-archivos
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

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.decomposition import PCA

from config.mongo_conexion import cerrar_cliente, obtener_bd, verificar_conexion
from etl.exploracion import ruta_legible, subtitulo, titulo
from ml.evaluacion import VARIABLES_RUTA, cargar_rutas, escalar_rutas
from ml.no_supervisado.seleccion_k import COMPONENTES_PCA

CARPETA_SALIDA = RAIZ / "data" / "outputs"
ARCHIVO_GRAFICA = CARPETA_SALIDA / "pca_clusters_rutas.png"
ARCHIVO_REPORTE = CARPETA_SALIDA / "reporte_pca.txt"

# El color transmite la severidad del grupo, no su orden alfabético: rojo
# para lo que exige intervención, verde para lo que funciona. Un dashboard
# donde el grupo crítico saliera en verde diría lo contrario del reporte.
COLOR_CRITICO = "#d62728"      # rojo
COLOR_PROBLEMATICO = "#ff7f0e"  # naranja
COLOR_ESTABLE = "#2ca02c"      # verde
COLOR_SANO = "#1f77b4"         # azul


def color_de(nombre_grupo: str) -> str:
    """Asigna color según lo que el nombre del grupo indica que hay que hacer."""
    if "CRÍTICAS" in nombre_grupo:
        return COLOR_CRITICO
    if "PROBLEMÁTICAS" in nombre_grupo:
        return COLOR_PROBLEMATICO
    if "LARGAS" in nombre_grupo:
        return COLOR_ESTABLE
    return COLOR_SANO


# ==========================================================================
# ANÁLISIS DE COMPONENTES
# ==========================================================================
def analizar_componentes(X: np.ndarray) -> tuple[PCA, pd.DataFrame, pd.DataFrame]:
    """Ajusta el PCA completo y devuelve varianza y cargas por componente."""
    modelo = PCA().fit(X)

    varianza = pd.DataFrame({
        "componente": [f"CP{i}" for i in range(1, len(VARIABLES_RUTA) + 1)],
        "varianza_pct": (100 * modelo.explained_variance_ratio_).round(1),
        "acumulada_pct": (100 * np.cumsum(modelo.explained_variance_ratio_)).round(1),
    })

    cargas = pd.DataFrame(
        modelo.components_[:COMPONENTES_PCA].T.round(3),
        index=list(VARIABLES_RUTA),
        columns=[f"CP{i}" for i in range(1, COMPONENTES_PCA + 1)],
    )
    return modelo, varianza, cargas


def interpretar_componente(cargas: pd.DataFrame, componente: str) -> str:
    """
    Traduce las cargas de un componente a una frase legible: qué
    variables lo empujan hacia arriba y cuáles hacia abajo.
    """
    serie = cargas[componente].sort_values(ascending=False)
    positivas = [v for v, peso in serie.items() if peso >= 0.3]
    negativas = [v for v, peso in serie.items() if peso <= -0.3]

    partes = []
    if positivas:
        partes.append("crece con " + ", ".join(positivas))
    if negativas:
        partes.append("decrece con " + ", ".join(negativas))
    return "; ".join(partes) if partes else "sin variables dominantes"


def cargar_clusters(bd) -> pd.DataFrame:
    """Lee la asignación producida por kmeans_rutas.py."""
    documentos = list(bd["clusters_rutas"].find({}))
    if not documentos:
        raise RuntimeError(
            "`clusters_rutas` está vacía. Ejecuta antes: "
            "python -m ml.no_supervisado.kmeans_rutas")
    return pd.DataFrame(documentos)


# ==========================================================================
# GRÁFICA
# ==========================================================================
def graficar(clusters: pd.DataFrame, cargas: pd.DataFrame,
             varianza: pd.DataFrame, destino: Path) -> Path:
    figura, (dispersion, contribucion) = plt.subplots(
        1, 2, figsize=(15, 6.5), gridspec_kw={"width_ratios": [1.35, 1]})
    figura.suptitle("SIG-LOG · Agrupamiento de rutas en el espacio de "
                    "componentes principales (datos simulados)",
                    fontsize=13, fontweight="bold")

    # --- Dispersión de las rutas, coloreadas por grupo ---------------------
    for nombre, grupo in clusters.groupby("nombre_grupo"):
        dispersion.scatter(grupo["componente_1"], grupo["componente_2"],
                           s=140, color=color_de(nombre),
                           edgecolor="white", linewidth=1.2,
                           label=f"{nombre} ({len(grupo)})", zorder=3)
    for _, fila in clusters.iterrows():
        dispersion.annotate(fila["codigo_ruta"].replace("RUT-", ""),
                            (fila["componente_1"], fila["componente_2"]),
                            fontsize=7, ha="center", va="center",
                            color="white", fontweight="bold", zorder=4)

    cp1, cp2 = varianza.loc[0, "varianza_pct"], varianza.loc[1, "varianza_pct"]
    dispersion.set_xlabel(f"Componente 1 — {cp1}% de la varianza")
    dispersion.set_ylabel(f"Componente 2 — {cp2}% de la varianza")
    dispersion.set_title(f"Grupos de rutas  (etiqueta = número de ruta)")
    dispersion.axhline(0, color="#cccccc", linewidth=0.8, zorder=1)
    dispersion.axvline(0, color="#cccccc", linewidth=0.8, zorder=1)
    dispersion.legend(fontsize=8, loc="best")
    dispersion.grid(alpha=0.25, zorder=0)

    # --- Contribución de cada variable a los componentes -------------------
    posiciones = np.arange(len(cargas))
    ancho = 0.38
    contribucion.barh(posiciones + ancho / 2, cargas["CP1"], ancho,
                      color="#1f77b4", label=f"CP1 ({cp1}%)")
    contribucion.barh(posiciones - ancho / 2, cargas["CP2"], ancho,
                      color="#ff7f0e", label=f"CP2 ({cp2}%)")
    contribucion.set_yticks(posiciones)
    contribucion.set_yticklabels([v.replace("_", " ") for v in cargas.index],
                                 fontsize=9)
    contribucion.set_xlabel("Carga (peso de la variable en el componente)")
    contribucion.set_title("Qué mide cada componente")
    contribucion.axvline(0, color="#333333", linewidth=0.8)
    contribucion.legend(fontsize=8)
    contribucion.grid(alpha=0.25, axis="x")

    figura.tight_layout()
    destino.parent.mkdir(parents=True, exist_ok=True)
    figura.savefig(destino, dpi=150)
    plt.close(figura)
    return destino


# ==========================================================================
# VERIFICACIONES
# ==========================================================================
def verificar(varianza: pd.DataFrame, cargas: pd.DataFrame,
              clusters: pd.DataFrame, X: np.ndarray) -> list[tuple[str, bool, str]]:
    acumulada = float(varianza.loc[COMPONENTES_PCA - 1, "acumulada_pct"])
    total = float(varianza["varianza_pct"].sum())
    # Las coordenadas guardadas por kmeans deben coincidir con las recalculadas
    recalculado = PCA(n_components=COMPONENTES_PCA, random_state=42).fit_transform(X)
    orden = clusters.sort_values("codigo_ruta").index
    guardado = clusters.loc[orden, ["componente_1", "componente_2"]].to_numpy()
    coinciden = bool(np.allclose(np.abs(guardado),
                                 np.abs(recalculado[np.argsort(
                                     clusters["codigo_ruta"].to_numpy())]),
                                 atol=0.01))
    return [
        ("La varianza explicada suma 100%", abs(total - 100) < 0.5,
         f"{total:.1f}%"),
        (f"Los {COMPONENTES_PCA} componentes conservan más de la mitad",
         acumulada > 50, f"{acumulada:.1f}%"),
        ("Cada componente tiene variables dominantes",
         bool((cargas.abs().max() >= 0.3).all()),
         f"carga máxima CP1 {cargas['CP1'].abs().max():.2f} · "
         f"CP2 {cargas['CP2'].abs().max():.2f}"),
        ("Coordenadas guardadas reproducibles", coinciden,
         "coinciden con el PCA recalculado"),
        ("Todas las rutas tienen grupo asignado",
         clusters["nombre_grupo"].notna().all(), f"{len(clusters)} rutas"),
    ]


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
        description="PA-9 — Análisis de componentes principales y visualización.",
    )
    parser.add_argument("--sin-archivos", action="store_true",
                        help="No escribe la gráfica ni el reporte.")
    args = parser.parse_args()

    if not verificar_conexion(verbose=True)["exito"]:
        return 1

    memoria = io.StringIO()
    codigo = 0

    try:
        with contextlib.redirect_stdout(memoria):
            titulo("SIG-LOG · COMPONENTES PRINCIPALES DE LAS RUTAS (PA-9)")
            print("  Los datos son SIMULADOS (decisión C-02).")

            bd = obtener_bd()
            rutas = cargar_rutas(bd)
            X, _ = escalar_rutas(rutas)
            modelo, varianza, cargas = analizar_componentes(X)

            titulo("1 · CUÁNTA INFORMACIÓN CONSERVA CADA COMPONENTE")
            print(varianza.to_string(index=False))
            acumulada = varianza.loc[COMPONENTES_PCA - 1, "acumulada_pct"]
            print(f"\n  Los {COMPONENTES_PCA} componentes usados para agrupar "
                  f"conservan el {acumulada}% de la varianza.")
            print("  Basta para separar los grupos y para dibujarlos, pero la")
            print("  gráfica es una sombra del perfil completo: dos rutas que")
            print("  aparecen cerca pueden diferir en lo que el resto de los")
            print("  componentes recoge.")

            titulo("2 · QUÉ MIDE CADA COMPONENTE  (cargas)")
            print(cargas.to_string())
            print()
            for componente in cargas.columns:
                print(f"  {componente}: {interpretar_componente(cargas, componente)}")
            print("\n  Lectura: el primer componente ordena las rutas por CARGA DE")
            print("  TRABAJO —distancia, paradas y el retraso que esa extensión")
            print("  arrastra—. El segundo separa por CONDICIONES DEL RECORRIDO:")
            print("  rutas fluidas pero expuestas a incidentes frente a rutas")
            print("  lentas con salidas tardías.")
            print("\n  Nota: `retraso_medio_min` pesa más en el primer componente")
            print("  que en el segundo, es decir, el retraso viene asociado sobre")
            print("  todo al tamaño de la ruta. Coincide con lo que encontró el")
            print("  agrupamiento: el grupo crítico es el de recorridos largos.")

            clusters = cargar_clusters(bd)
            titulo("3 · GRUPOS EN EL PLANO DE COMPONENTES")
            resumen = (clusters.groupby("nombre_grupo")
                       .agg(rutas=("codigo_ruta", "count"),
                            cp1_medio=("componente_1", "mean"),
                            cp2_medio=("componente_2", "mean"),
                            silueta_media=("silueta", "mean"))
                       .round(3))
            print(resumen.to_string())
            print(f"\n  Silueta global del agrupamiento: "
                  f"{clusters['silueta_global'].iloc[0]:.3f}")

            if not imprimir_verificaciones(verificar(varianza, cargas, clusters, X)):
                codigo = 1

            if not args.sin_archivos:
                destino = graficar(clusters, cargas, varianza, ARCHIVO_GRAFICA)
                titulo("5 · ARCHIVOS GENERADOS")
                print(f"  {ruta_legible(destino):<44}"
                      f"{destino.stat().st_size/1024:>8.0f} KB")
                print(f"  {ruta_legible(ARCHIVO_REPORTE)}")

            print()
            print("=" * 78)
            print("  PA-9 TERMINADA." if codigo == 0
                  else "  PA-9 TERMINADA CON FALLAS.")
            print("  El agrupamiento está en `clusters_rutas`, listo para el")
            print("  dashboard y los reportes.")
            print("=" * 78)

    except SystemExit as salida:
        codigo = int(salida.code or 0)
    except Exception:                              # noqa: BLE001
        codigo = 1
        memoria.write("\n" + "=" * 78 + "\n  ERROR EN EL ANÁLISIS PCA\n"
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
