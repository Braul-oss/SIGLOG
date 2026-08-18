"""
SIG-LOG — Sistema Integral de Gestión Logística
analytics/dashboard.py

ACTIVIDAD PA-10 (parte 3) — COMPOSICIÓN DEL DASHBOARD
§18.2 del documento técnico base

Arma los tres paneles que definió el diseño y, junto a cada uno, el texto
que lo explica (RF-29). El resultado son tres PNG en data/outputs/ y un
reporte de interpretaciones que alimentará el reporte en PDF y las
vistas del sistema web.

    Panel A — Tablero ejecutivo         los 10 KPIs (analytics/kpis.py)
    Panel B — Dashboard analítico 2×3   histograma, boxplot por ruta,
                                        violín por franja, heatmap de
                                        saturación, serie temporal y
                                        Pareto de causas
    Panel C — Resultados de ML 2×2      codo, silueta, clusters en PCA y
                                        real contra predicho

Se agrega un Panel D (operativo) con las gráficas de §18.1 que no caben
en los tres anteriores pero que los módulos del sistema sí necesitan:
rutas más utilizadas, costo por vehículo, puntualidad por operador y
mantenimiento pendiente.

Ninguna gráfica recalcula métricas: todas consumen el DW y los resultados
de ML ya persistidos (regla de la capa 8, §7.3).

Uso
---
    python -m analytics.dashboard
    python -m analytics.dashboard --panel B
"""

from __future__ import annotations

import argparse
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score

from analytics import graficas as g
from analytics import kpis as k
from config.mongo_conexion import cerrar_cliente, obtener_bd, verificar_conexion
from ml.evaluacion import SEMILLA, cargar_rutas, escalar_rutas, proyectar_pca
from ml.no_supervisado.seleccion_k import COMPONENTES_PCA, RANGO_K, evaluar_k

CARPETA_SALIDA = RAIZ / "data" / "outputs"
ARCHIVO_REPORTE = CARPETA_SALIDA / "reporte_dashboard.txt"

PIE_SIMULADO = ("Datos SIMULADOS con fines académicos (decisión C-02). "
                "Ninguna cifra describe una empresa real.")


def _pie_de_figura(figura, titulo: str) -> None:
    figura.suptitle(titulo, fontsize=15, fontweight="bold", y=0.99)
    figura.text(0.5, 0.005, PIE_SIMULADO, ha="center", fontsize=8,
                color="#666666", style="italic")


def _guardar(figura, nombre: str) -> Path:
    CARPETA_SALIDA.mkdir(parents=True, exist_ok=True)
    destino = CARPETA_SALIDA / nombre
    figura.savefig(destino, dpi=140, bbox_inches="tight")
    plt.close(figura)
    return destino


# ==========================================================================
# PANEL A — TABLERO EJECUTIVO (KPIs)
# ==========================================================================
COLOR_SEMAFORO = {"VERDE": "#2ca02c", "AMARILLO": "#ff7f0e",
                  "ROJO": "#d62728", "NEUTRO": "#7f7f7f"}


# Decimales por unidad: un porcentaje con dos decimales o un kilometraje
# con centésimas se leen peor y no aportan precisión útil en un tablero.
DECIMALES_POR_UNIDAD = {"%": 1, "min": 1, "km/l": 2, "MXN/km": 2,
                        "km": 0, "MXN": 0}


def _formato(valor: Any, unidad: str) -> str:
    if isinstance(valor, float):
        return f"{valor:,.{DECIMALES_POR_UNIDAD.get(unidad, 2)}f}"
    return f"{valor:,}"


def panel_a(indicadores: list[dict[str, Any]]) -> tuple[Path, list[str]]:
    """Tarjetas de KPI: el valor grande, el semáforo y la unidad."""
    figura, ejes = plt.subplots(2, 5, figsize=(19, 6.5))
    _pie_de_figura(figura, "SIG-LOG · Panel A — Tablero ejecutivo")

    for ax, kpi in zip(ejes.flat, indicadores):
        color = COLOR_SEMAFORO[kpi["semaforo"]]
        ax.set_facecolor("#fafafa")
        for lado in ("top", "right", "bottom"):
            ax.spines[lado].set_visible(False)
        ax.spines["left"].set_color(color)
        ax.spines["left"].set_linewidth(5)

        valor = _formato(kpi["valor"], kpi["unidad"])
        ax.text(0.5, 0.68, valor, ha="center", va="center", fontsize=21,
                fontweight="bold", color=color, transform=ax.transAxes)
        ax.text(0.5, 0.45, kpi["unidad"], ha="center", va="center", fontsize=9,
                color="#555555", transform=ax.transAxes)
        ax.text(0.5, 0.24, kpi["titulo"], ha="center", va="center", fontsize=9.5,
                fontweight="bold", transform=ax.transAxes, wrap=True)
        ax.set_xticks([])
        ax.set_yticks([])

    figura.tight_layout(rect=(0, 0.02, 1, 0.96))
    destino = _guardar(figura, "panel_a_kpis.png")
    return destino, [f"{kpi['titulo']}: {kpi['lectura']}" for kpi in indicadores]


# ==========================================================================
# PANEL B — DASHBOARD ANALÍTICO 2×3
# ==========================================================================
def panel_b(hechos: pd.DataFrame, dim_ruta: pd.DataFrame) -> tuple[Path, list[str]]:
    figura, ejes = plt.subplots(2, 3, figsize=(19, 11))
    _pie_de_figura(figura, "SIG-LOG · Panel B — Dashboard analítico")

    lecturas = [
        g.histograma_retraso(ejes[0, 0], hechos),
        g.boxplot_retraso_por_ruta(ejes[0, 1], hechos, dim_ruta),
        g.violin_por_franja(ejes[0, 2], hechos),
        g.heatmap_saturacion(ejes[1, 0], hechos),
        g.serie_temporal(ejes[1, 1], hechos),
        g.pareto_causas(ejes[1, 2], hechos),
    ]
    figura.tight_layout(rect=(0, 0.02, 1, 0.96))
    return _guardar(figura, "panel_b_analitico.png"), lecturas


# ==========================================================================
# PANEL C — RESULTADOS DE MACHINE LEARNING 2×2
# ==========================================================================
def panel_c(hechos: pd.DataFrame, clusters: pd.DataFrame) -> tuple[Path, list[str]]:
    figura, ejes = plt.subplots(2, 2, figsize=(15, 11))
    _pie_de_figura(figura, "SIG-LOG · Panel C — Resultados de Machine Learning")

    # Codo y silueta se recalculan aquí porque son diagnósticos del propio
    # agrupamiento, no métricas de negocio: el DW guarda el resultado, no
    # la curva que llevó a elegir k.
    X, _ = escalar_rutas(cargar_rutas())
    X_pca, _ = proyectar_pca(X, COMPONENTES_PCA)
    tabla = evaluar_k(X_pca, RANGO_K)
    k_elegido = int(clusters["k"].iloc[0])

    codo = ejes[0, 0]
    codo.plot(tabla["k"], tabla["inercia"], marker="o", color="#1f77b4")
    codo.axvline(k_elegido, color=g.COLOR_ALERTA, linestyle="--",
                 label=f"k elegido = {k_elegido}")
    codo.set_title("Método del codo: dónde deja de rendir agregar grupos",
                   fontsize=10, fontweight="bold")
    codo.set_xlabel("Número de grupos (k)")
    codo.set_ylabel("Inercia (suma de distancias al centro)")
    codo.legend(fontsize=7)
    codo.grid(alpha=0.25)

    silueta = ejes[0, 1]
    validas = tabla[tabla["valida"]]
    invalidas = tabla[~tabla["valida"]]
    silueta.plot(tabla["k"], tabla["silueta"], color="#2ca02c", zorder=1)
    silueta.scatter(validas["k"], validas["silueta"], color="#2ca02c", zorder=2,
                    label="k válida")
    silueta.scatter(invalidas["k"], invalidas["silueta"], color="#999999",
                    marker="x", zorder=2, label="deja grupos de 1 ruta")
    silueta.axvline(k_elegido, color=g.COLOR_ALERTA, linestyle="--",
                    label=f"k elegido = {k_elegido}")
    silueta.set_title("Coeficiente de silueta por número de grupos",
                      fontsize=10, fontweight="bold")
    silueta.set_xlabel("Número de grupos (k)")
    silueta.set_ylabel("Silueta media (-1 a 1)")
    silueta.legend(fontsize=7)
    silueta.grid(alpha=0.25)

    lectura_clusters = g.clusters_rutas(ejes[1, 0], clusters)
    lectura_modelo = g.real_vs_predicho(ejes[1, 1], hechos)

    mejor_valida = validas.loc[validas["silueta"].idxmax()]
    lectura_k = (
        f"Se evaluaron k de {RANGO_K[0]} a {RANGO_K[-1]}. La inercia siempre "
        f"decrece, así que el codo por sí solo no decide; la silueta sí tiene "
        f"máximo. Descartando las k que dejan grupos de una sola ruta, el mejor "
        f"valor es k={int(mejor_valida['k'])} con silueta "
        f"{mejor_valida['silueta']:.3f}.")

    figura.tight_layout(rect=(0, 0.02, 1, 0.96))
    return (_guardar(figura, "panel_c_machine_learning.png"),
            [lectura_k, lectura_k, lectura_clusters, lectura_modelo])


# ==========================================================================
# PANEL D — VISTAS OPERATIVAS POR MÓDULO
# ==========================================================================
def panel_d(hechos: pd.DataFrame, dim_ruta: pd.DataFrame,
            dim_vehiculo: pd.DataFrame,
            dim_operador: pd.DataFrame) -> tuple[Path, list[str]]:
    figura, ejes = plt.subplots(2, 2, figsize=(17, 11))
    _pie_de_figura(figura, "SIG-LOG · Panel D — Vistas operativas por módulo")

    lecturas = [
        g.rutas_mas_utilizadas(ejes[0, 0], hechos, dim_ruta),
        g.costo_por_vehiculo(ejes[0, 1], dim_vehiculo),
        g.desempeno_operadores(ejes[1, 0], dim_operador),
        g.mantenimiento_pendiente(ejes[1, 1], hechos, dim_vehiculo),
    ]
    figura.tight_layout(rect=(0, 0.02, 1, 0.96))
    return _guardar(figura, "panel_d_operativo.png"), lecturas


# ==========================================================================
# REPORTE
# ==========================================================================
TITULOS = {
    "A": ("Panel A — Tablero ejecutivo", "10 indicadores"),
    "B": ("Panel B — Dashboard analítico", "6 gráficas"),
    "C": ("Panel C — Resultados de Machine Learning", "4 gráficas"),
    "D": ("Panel D — Vistas operativas por módulo", "4 gráficas"),
}


def imprimir_panel(letra: str, destino: Path, lecturas: list[str]) -> None:
    titulo, contenido = TITULOS[letra]
    print()
    print("=" * 78)
    print(f"  {titulo.upper()}  ({contenido})")
    print("=" * 78)
    print(f"  Archivo: {destino.relative_to(RAIZ)}  "
          f"({destino.stat().st_size / 1024:.0f} KB)")
    print()
    vistas = set()
    for lectura in lecturas:
        if lectura in vistas:          # el panel C comparte una lectura
            continue
        vistas.add(lectura)
        for i, linea in enumerate(textwrap.wrap(lectura, 72)):
            print(f"      {'· ' if i == 0 else '  '}{linea}")
        print()


def verificar(paneles: dict[str, tuple[Path, list[str]]]
              ) -> list[tuple[str, bool, str]]:
    resultados = [
        ("Los cuatro paneles fueron generados", len(paneles) == 4,
         ", ".join(sorted(paneles))),
    ]
    for letra, (destino, lecturas) in sorted(paneles.items()):
        resultados.append(
            (f"Panel {letra}: archivo escrito y con contenido",
             destino.exists() and destino.stat().st_size > 20_000,
             f"{destino.stat().st_size / 1024:.0f} KB"))
        resultados.append(
            (f"Panel {letra}: toda gráfica trae interpretación (RF-29)",
             all(len(t) > 60 for t in lecturas),
             f"{len(lecturas)} lecturas"))
    return resultados


def imprimir_verificaciones(resultados: list[tuple[str, bool, str]]) -> bool:
    print()
    print("=" * 78)
    print("  VERIFICACIONES AUTOMÁTICAS")
    print("=" * 78)
    for nombre, ok, detalle in resultados:
        print(f"  {'[OK]   ' if ok else '[FALLA]'} {nombre:<52}{detalle}")
    fallos = sum(1 for _, ok, _ in resultados if not ok)
    print("-" * 78)
    print(f"  {len(resultados) - fallos}/{len(resultados)} verificaciones correctas")
    return fallos == 0


# ==========================================================================
# PUNTO DE ENTRADA
# ==========================================================================
def main() -> int:
    parser = argparse.ArgumentParser(
        description="PA-10 — Composición del dashboard (§18.2).")
    parser.add_argument("--panel", choices=["A", "B", "C", "D"], default=None,
                        help="Genera un solo panel (por defecto: todos).")
    parser.add_argument("--sin-archivos", action="store_true",
                        help="No escribe el reporte de texto.")
    args = parser.parse_args()

    if not verificar_conexion(verbose=True)["exito"]:
        return 1

    import contextlib
    import io

    memoria = io.StringIO()
    codigo = 0

    try:
        with contextlib.redirect_stdout(memoria):
            print("=" * 78)
            print("  SIG-LOG · DASHBOARD (PA-10)")
            print("=" * 78)
            print(f"  Generado: {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC")
            print(f"  {PIE_SIMULADO}")

            bd = obtener_bd()
            print("\n  Leyendo el data warehouse...")
            hechos = g.cargar_hechos(bd)
            dim_ruta = g.cargar_dimension("dim_ruta", bd)
            dim_vehiculo = g.cargar_dimension("dim_vehiculo", bd)
            dim_operador = g.cargar_dimension("dim_operador", bd)
            clusters = g.cargar_dimension("clusters_rutas", bd)
            print(f"  {len(hechos):,} entregas · {len(dim_ruta)} rutas · "
                  f"{len(dim_vehiculo)} vehículos · {len(dim_operador)} operadores")

            constructores: dict[str, Callable[[], tuple[Path, list[str]]]] = {
                "A": lambda: panel_a(k.calcular(bd)),
                "B": lambda: panel_b(hechos, dim_ruta),
                "C": lambda: panel_c(hechos, clusters),
                "D": lambda: panel_d(hechos, dim_ruta, dim_vehiculo, dim_operador),
            }
            seleccion = [args.panel] if args.panel else list(constructores)

            paneles: dict[str, tuple[Path, list[str]]] = {}
            for letra in seleccion:
                paneles[letra] = constructores[letra]()
                imprimir_panel(letra, *paneles[letra])

            if not args.panel and not imprimir_verificaciones(verificar(paneles)):
                codigo = 1

            print()
            print("=" * 78)
            print("  DASHBOARD GENERADO." if codigo == 0
                  else "  DASHBOARD GENERADO CON FALLAS.")
            print("  Las interpretaciones de este reporte alimentan el PDF y las")
            print("  vistas del sistema web.")
            print("=" * 78)

    except Exception:                              # noqa: BLE001
        import traceback
        codigo = 1
        memoria.write("\n" + "=" * 78 + "\n  ERROR AL GENERAR EL DASHBOARD\n"
                      + "=" * 78 + "\n" + traceback.format_exc())
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
