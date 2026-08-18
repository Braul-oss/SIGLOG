"""
SIG-LOG — Sistema Integral de Gestión Logística
ml/no_supervisado/seleccion_k.py

ACTIVIDAD PA-9 (parte 1) — ELECCIÓN DEL NÚMERO DE GRUPOS
EVIDENCIA DE APRENDIZAJE NO SUPERVISADO

K-Means exige decidir de antemano en cuántos grupos se parten los datos,
y esa decisión no puede tomarse a ojo: cambia por completo el resultado.
Se toma con los dos criterios vistos en clase:

    MÉTODO DEL CODO       mide la inercia (suma de distancias al centro
                          del grupo). Siempre baja al aumentar k, así que
                          no se busca el mínimo sino el "codo": el punto
                          a partir del cual agregar grupos ya casi no
                          reduce el error.

    COEFICIENTE DE        para cada elemento, compara qué tan cerca está
    SILUETA               de su grupo frente al grupo vecino más próximo.
                          Va de -1 a 1 y, a diferencia de la inercia, sí
                          tiene un máximo con significado.

Hallazgo que condiciona toda la actividad (D-K2)
------------------------------------------------
Con el perfil completo, las 20 rutas NO forman grupos naturalmente
separados: la silueta se queda plana alrededor de 0.16 para cualquier k,
que es tanto como decir que las rutas se distribuyen en un continuo. Es
un resultado legítimo y hay que reportarlo, no maquillarlo.

Al proyectar el perfil sobre sus dos componentes principales, en cambio,
la silueta sube a ~0.40. La reducción de dimensión elimina el ruido que
aportan seis variables medidas sobre apenas veinte elementos y deja ver
la estructura. Por eso el agrupamiento se hace en el espacio PCA, y el
reporte muestra ambos espacios para que la diferencia quede a la vista.

La lectura correcta del resultado es una SEGMENTACIÓN OPERATIVA útil
para gestionar (qué rutas atender con qué criterio), no el
descubrimiento de "especies" de rutas separadas por naturaleza.

Regla de decisión (D-K3)
------------------------
Elegir el máximo de silueta sin más produce soluciones degeneradas: con
k alto aparecen grupos de una sola ruta, que tienen silueta excelente y
valor nulo. La regla descarta primero toda k que deje un grupo con menos
de 2 rutas y, entre las válidas, prefiere la de mayor silueta; si dos
quedan a menos de 0.02, se queda con la más simple (menor k).

Uso
---
    python -m ml.no_supervisado.seleccion_k
    python -m ml.no_supervisado.seleccion_k --sin-archivos
"""

from __future__ import annotations

import argparse
import contextlib
import io
import sys
import traceback
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

import matplotlib

matplotlib.use("Agg")                      # backend sin ventana, para scripts
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score

from config.mongo_conexion import cerrar_cliente, obtener_bd, verificar_conexion
from etl.exploracion import ruta_legible, subtitulo, titulo
from ml.evaluacion import (
    SEMILLA,
    UMBRAL_REDUNDANCIA,
    VARIABLES_RUTA,
    VARIABLES_RUTA_CANDIDATAS,
    analizar_redundancia,
    cargar_rutas,
    escalar_rutas,
    proyectar_pca,
)

CARPETA_SALIDA = RAIZ / "data" / "outputs"
ARCHIVO_GRAFICA = CARPETA_SALIDA / "seleccion_k_rutas.png"
ARCHIVO_REPORTE = CARPETA_SALIDA / "reporte_seleccion_k.txt"

RANGO_K: tuple[int, ...] = (2, 3, 4, 5, 6, 7, 8)
COMPONENTES_PCA: int = 2
MINIMO_POR_GRUPO: int = 2
TOLERANCIA_SILUETA: float = 0.02


# ==========================================================================
# EVALUACIÓN DE k
# ==========================================================================
def evaluar_k(X: np.ndarray, rango: tuple[int, ...] = RANGO_K) -> pd.DataFrame:
    """Inercia, silueta y tamaño del grupo menor para cada k."""
    filas = []
    for k in rango:
        modelo = KMeans(n_clusters=k, random_state=SEMILLA, n_init=10)
        etiquetas = modelo.fit_predict(X)
        filas.append({
            "k": k,
            "inercia": round(float(modelo.inertia_), 2),
            "silueta": round(float(silhouette_score(X, etiquetas)), 4),
            "grupo_menor": int(np.bincount(etiquetas).min()),
            "valida": bool(np.bincount(etiquetas).min() >= MINIMO_POR_GRUPO),
        })
    tabla = pd.DataFrame(filas)
    tabla["reduccion_inercia_pct"] = (-100 * tabla["inercia"].pct_change()).round(1)
    return tabla


def k_por_codo(tabla: pd.DataFrame) -> int:
    """
    Localiza el codo por la mayor distancia a la recta que une el primer
    y el último punto de la curva de inercia: la versión reproducible de
    "mirar dónde se dobla la curva".
    """
    k = tabla["k"].to_numpy(dtype=float)
    inercia = tabla["inercia"].to_numpy(dtype=float)

    p_inicio = np.array([k[0], inercia[0]])
    recta = np.array([k[-1], inercia[-1]]) - p_inicio
    recta = recta / np.linalg.norm(recta)

    distancias = []
    for punto in np.column_stack([k, inercia]):
        vector = punto - p_inicio
        distancias.append(np.linalg.norm(vector - np.dot(vector, recta) * recta))
    return int(k[int(np.argmax(distancias))])


def elegir_k(tabla: pd.DataFrame) -> tuple[int, str]:
    """
    Aplica D-K3: descarta las k degeneradas y, entre las válidas, toma la
    de mayor silueta prefiriendo la más simple ante empates técnicos.
    """
    validas = tabla[tabla["valida"]]
    if validas.empty:
        k = int(tabla.loc[tabla["silueta"].idxmax(), "k"])
        return k, ("Ninguna k evita grupos de una sola ruta; se reporta el "
                   "máximo de silueta, pero el resultado no es utilizable.")

    mejor = validas["silueta"].max()
    candidatas = validas[validas["silueta"] >= mejor - TOLERANCIA_SILUETA]
    k = int(candidatas["k"].min())
    codo = k_por_codo(tabla)

    descartadas = tabla.loc[~tabla["valida"], "k"].tolist()
    detalle = (f"Se descartaron k={descartadas} por dejar grupos con menos de "
               f"{MINIMO_POR_GRUPO} rutas. " if descartadas else "")
    coincidencia = ("El codo coincide con la silueta."
                    if codo == k else
                    f"El codo sugiere k={codo}; se prefiere la silueta, que "
                    "tiene un máximo con significado.")
    return k, (f"{detalle}Entre las válidas, k={k} maximiza la silueta "
               f"({mejor:.3f}). {coincidencia}")


def comparar_espacios(X: np.ndarray) -> pd.DataFrame:
    """
    Silueta en el espacio completo frente al espacio PCA (D-K2).

    Es la evidencia de por qué el agrupamiento final se hace sobre
    componentes principales y no sobre las variables originales.
    """
    X_pca, _ = proyectar_pca(X, COMPONENTES_PCA)
    filas = []
    for k in RANGO_K:
        etiquetas_completo = KMeans(k, random_state=SEMILLA, n_init=10).fit_predict(X)
        etiquetas_pca = KMeans(k, random_state=SEMILLA, n_init=10).fit_predict(X_pca)
        filas.append({
            "k": k,
            "silueta_completo": round(float(silhouette_score(X, etiquetas_completo)), 3),
            "silueta_pca": round(float(silhouette_score(X_pca, etiquetas_pca)), 3),
        })
    return pd.DataFrame(filas)


# ==========================================================================
# GRÁFICA DIAGNÓSTICA
# ==========================================================================
def graficar(tabla: pd.DataFrame, comparacion: pd.DataFrame,
             k_elegido: int, destino: Path) -> Path:
    figura, ejes = plt.subplots(1, 3, figsize=(16, 4.6))
    figura.suptitle("SIG-LOG · Elección del número de grupos de rutas "
                    "(datos simulados)", fontsize=13, fontweight="bold")

    codo, silueta, espacios = ejes
    codo.plot(tabla["k"], tabla["inercia"], marker="o", color="#1f77b4")
    codo.axvline(k_elegido, color="#d62728", linestyle="--",
                 label=f"k elegido = {k_elegido}")
    codo.set_title("Método del codo")
    codo.set_xlabel("Número de grupos (k)")
    codo.set_ylabel("Inercia")
    codo.legend()
    codo.grid(alpha=0.3)

    validas = tabla[tabla["valida"]]
    invalidas = tabla[~tabla["valida"]]
    silueta.plot(tabla["k"], tabla["silueta"], color="#2ca02c", zorder=1)
    silueta.scatter(validas["k"], validas["silueta"], color="#2ca02c",
                    zorder=2, label="k válida")
    silueta.scatter(invalidas["k"], invalidas["silueta"], color="#999999",
                    marker="x", zorder=2, label="grupo de 1 ruta (descartada)")
    silueta.axvline(k_elegido, color="#d62728", linestyle="--",
                    label=f"k elegido = {k_elegido}")
    silueta.set_title("Coeficiente de silueta (espacio PCA)")
    silueta.set_xlabel("Número de grupos (k)")
    silueta.set_ylabel("Silueta media (-1 a 1)")
    silueta.legend(fontsize=8)
    silueta.grid(alpha=0.3)

    espacios.plot(comparacion["k"], comparacion["silueta_completo"],
                  marker="s", color="#999999", label="perfil completo (6 var.)")
    espacios.plot(comparacion["k"], comparacion["silueta_pca"],
                  marker="o", color="#9467bd",
                  label=f"componentes principales ({COMPONENTES_PCA})")
    espacios.set_title("Por qué se agrupa sobre componentes")
    espacios.set_xlabel("Número de grupos (k)")
    espacios.set_ylabel("Silueta media")
    espacios.legend(fontsize=8)
    espacios.grid(alpha=0.3)

    figura.tight_layout()
    destino.parent.mkdir(parents=True, exist_ok=True)
    figura.savefig(destino, dpi=150)
    plt.close(figura)
    return destino


# ==========================================================================
# VERIFICACIONES
# ==========================================================================
def verificar(df: pd.DataFrame, tabla: pd.DataFrame, comparacion: pd.DataFrame,
              k_elegido: int) -> list[tuple[str, bool, str]]:
    fila = tabla.loc[tabla["k"] == k_elegido].iloc[0]
    mejora = (comparacion["silueta_pca"] > comparacion["silueta_completo"]).all()
    return [
        ("Perfil de ruta completo (sin nulos)",
         not df[list(VARIABLES_RUTA)].isna().any().any(),
         f"{len(df)} rutas × {len(VARIABLES_RUTA)} variables"),
        ("k evaluado en todo el rango previsto",
         list(tabla["k"]) == list(RANGO_K), f"k de {RANGO_K[0]} a {RANGO_K[-1]}"),
        ("La inercia decrece al aumentar k",
         bool((tabla["inercia"].diff().dropna() < 0).all()), "monótona decreciente"),
        ("El espacio PCA mejora la separación (D-K2)", bool(mejora),
         f"silueta PCA superior en las {len(comparacion)} k evaluadas"),
        ("Silueta del k elegido por encima del azar", float(fila["silueta"]) > 0.25,
         f"{float(fila['silueta']):.3f}"),
        ("Ningún grupo queda con una sola ruta (D-K3)",
         int(fila["grupo_menor"]) >= MINIMO_POR_GRUPO,
         f"grupo más pequeño: {int(fila['grupo_menor'])} rutas"),
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
        description="PA-9 — Elección de k por codo y silueta.",
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
            titulo("SIG-LOG · ELECCIÓN DEL NÚMERO DE GRUPOS DE RUTAS (PA-9)")
            print("  Los datos son SIMULADOS (decisión C-02).")

            bd = obtener_bd()
            rutas = cargar_rutas(bd)
            X, _ = escalar_rutas(rutas)

            titulo("1 · DEPURACIÓN DE VARIABLES REDUNDANTES  (D-K1)")
            print(f"  {len(rutas)} rutas · {len(VARIABLES_RUTA_CANDIDATAS)} "
                  "variables candidatas en `dim_ruta`")
            print(f"\n  Pares de candidatas con |r| ≥ {UMBRAL_REDUNDANCIA}:")
            for primera, segunda, r in analizar_redundancia(rutas):
                print(f"      {primera:<28}{segunda:<28}r = {r:+.2f}")
            print("\n  Miden el mismo concepto. Conservarlos haría que el 'tamaño'")
            print("  de la ruta pese varias veces más que los incidentes al medir")
            print("  distancias. Se conserva un representante por concepto.")
            print(f"\n  Variables finales ({len(VARIABLES_RUTA)}): "
                  f"{', '.join(VARIABLES_RUTA)}")
            print("\n  Estandarizadas antes de agrupar: sin escalar, los kilómetros")
            print("  aplastarían a los incidentes por viaje.")

            titulo("2 · ¿EXISTEN GRUPOS NATURALES?  (D-K2)")
            comparacion = comparar_espacios(X)
            print("  Silueta media según el espacio en que se mide la distancia:\n")
            print(comparacion.to_string(index=False))
            print(f"\n  En el perfil completo la silueta se queda plana alrededor de "
                  f"{comparacion['silueta_completo'].mean():.2f}: las rutas se")
            print("  distribuyen en un CONTINUO, no en grupos separados por naturaleza.")
            print(f"  Sobre {COMPONENTES_PCA} componentes principales sube a "
                  f"{comparacion['silueta_pca'].max():.2f}: al quitar el ruido de seis")
            print("  variables medidas en veinte elementos, la estructura aparece.")
            print("\n  Decisión: el agrupamiento se hace en el espacio PCA, y el")
            print("  resultado se interpreta como SEGMENTACIÓN OPERATIVA para")
            print("  gestionar las rutas, no como categorías naturales.")

            X_pca, modelo_pca = proyectar_pca(X, COMPONENTES_PCA)
            titulo("3 · EVALUACIÓN DE k EN EL ESPACIO PCA  (codo + silueta)")
            print(f"  Varianza explicada por los {COMPONENTES_PCA} componentes: "
                  f"{modelo_pca.explained_variance_ratio_.sum():.1%}")
            print("  (el detalle de los componentes se analiza en pca_rutas.py)\n")
            tabla = evaluar_k(X_pca)
            print(tabla.to_string(index=False))
            print("\n  valida = ningún grupo queda con menos de "
                  f"{MINIMO_POR_GRUPO} rutas (D-K3).")

            k_elegido, justificacion = elegir_k(tabla)
            titulo("4 · DECISIÓN")
            print(f"  Codo .............. k = {k_por_codo(tabla)}")
            print(f"  Silueta (válidas) . k = {k_elegido}")
            print(f"\n  K ELEGIDO: {k_elegido}")
            print(f"  {justificacion}")

            if not imprimir_verificaciones(
                    verificar(rutas, tabla, comparacion, k_elegido)):
                codigo = 1

            if not args.sin_archivos:
                destino = graficar(tabla, comparacion, k_elegido, ARCHIVO_GRAFICA)
                titulo("6 · ARCHIVOS GENERADOS")
                print(f"  {ruta_legible(destino):<44}"
                      f"{destino.stat().st_size/1024:>8.0f} KB")
                print(f"  {ruta_legible(ARCHIVO_REPORTE)}")

            print()
            print("=" * 78)
            print(f"  SELECCIÓN DE k TERMINADA. k = {k_elegido}")
            print("  Sigue: python -m ml.no_supervisado.kmeans_rutas")
            print("=" * 78)

    except SystemExit as salida:
        codigo = int(salida.code or 0)
    except Exception:                              # noqa: BLE001
        codigo = 1
        memoria.write("\n" + "=" * 78 + "\n  ERROR EN LA SELECCIÓN DE k\n"
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
