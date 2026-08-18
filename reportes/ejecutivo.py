"""
SIG-LOG — Sistema Integral de Gestión Logística
reportes/ejecutivo.py

INFORME EJECUTIVO

Para quien decide y no conoce el modelo de datos. Responde, en este orden:

    ¿Cómo va la operación?          los diez indicadores con su lectura
    ¿Mejora o empeora?              la evolución semanal
    ¿Dónde están los problemas?     rutas y unidades que se salen de lo normal
    ¿Por qué ocurren?               las causas, y qué tipos de ruta hay

Es la misma jerarquía del panel, y a propósito: quien vio la pantalla debe
reconocer el documento.

Ninguna cifra se calcula aquí. Los indicadores salen de `analytics.kpis` y
el resto de los servicios de analítica, exactamente igual que el dashboard.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from pymongo.database import Database

from backend.services import analitica, ml as servicio_ml
from backend.utils.errores import ErrorSIGLOG
from config import settings
from reportes import comun

TITULO = "Informe ejecutivo"
SUBTITULO = ("Estado de la operación logística: qué está pasando, dónde "
             "están los problemas y qué los explica.")


def construir(bd: Database) -> bytes:
    datos = analitica.kpis(bd)
    periodo = analitica.periodo(bd)
    umbral = settings.UMBRAL_RETRASO_MIN

    elementos: list = comun.portada(TITULO, SUBTITULO, periodo)

    # ---------------------------------------------------------- resumen --
    elementos.append(comun.aviso(
        f"<b>En resumen.</b> {datos['resumen_ejecutivo']}"))
    elementos.append(comun.espacio(0.5))

    # -------------------------------------------------------- 1 · cifras --
    elementos += comun.seccion(
        "1. Las cifras del periodo",
        "Cada indicador se juzga contra una meta: la franja de color sobre "
        "la tarjeta indica si la cumple (verde), si se queda cerca (ámbar) "
        "o si se aleja (rojo). Los grises no se comparan contra ninguna "
        "meta: describen el tamaño de la operación.")
    elementos.append(comun.indicadores(datos["indicadores"]))
    elementos.append(comun.espacio(0.3))

    for kpi in datos["indicadores"]:
        if kpi["semaforo"] in ("ROJO", "AMARILLO"):
            elementos.append(comun.lectura(
                f"<b>{kpi['titulo']}.</b> {kpi['lectura']}"))

    elementos.append(comun.salto())

    # ----------------------------------------------------- 2 · tendencia --
    elementos += _tendencia(bd)

    # ----------------------------------------------------- 3 · problemas --
    elementos += _problemas(bd, umbral)

    # ------------------------------------------------------- 4 · causas --
    elementos.append(comun.salto())
    elementos += _causas(bd)
    elementos += _tipos_de_ruta(bd)

    return comun.documento(TITULO, SUBTITULO, elementos)


# ==========================================================================
# BLOQUES
# ==========================================================================
def _tendencia(bd: Database) -> list:
    datos = analitica.tendencia(bd, "semana")
    puntos = datos["puntos"]
    umbral = datos["umbral_retraso_min"]

    partes = comun.seccion(
        "2. Cómo evoluciona",
        "Una cifra del periodo no dice si la situación mejora o empeora. "
        "Las barras son las entregas realizadas cada semana; la línea, el "
        "retraso medio de esa semana. La línea discontinua marca el umbral "
        f"de {umbral} minutos a partir del cual una entrega cuenta como "
        "retrasada.")

    def dibujar(ax):
        etiquetas = [p["etiqueta"] for p in puntos]
        ax.bar(etiquetas, [p["entregas"] for p in puntos],
               color="#1f4e79", alpha=.35, label="Entregas realizadas")
        ax.set_xlabel("Semana (fecha de inicio)")
        ax.set_ylabel("Entregas realizadas")
        ax.tick_params(axis="x", rotation=90, labelsize=6)

        eje = ax.twinx()
        eje.plot(etiquetas, [p["retraso_medio_min"] for p in puntos],
                 color="#d62728", marker="o", markersize=3, linewidth=1.5,
                 label="Retraso medio (minutos)")
        eje.axhline(umbral, color="#8c9bb0", linestyle="--", linewidth=1.2,
                    label=f"Umbral de {umbral} minutos")
        eje.set_ylabel("Retraso medio (minutos)")
        eje.set_ylim(bottom=0)

        lineas = ax.get_legend_handles_labels()
        otras = eje.get_legend_handles_labels()
        ax.legend(lineas[0] + otras[0], lineas[1] + otras[1],
                  fontsize=6.5, loc="upper left", ncol=3)
        ax.set_title("Entregas y retraso medio por semana", fontsize=9,
                     fontweight="bold")

    partes.append(comun.grafica(dibujar, alto_cm=7.5))
    partes.append(comun.lectura(datos["lectura"]))
    return partes


def _problemas(bd: Database, umbral: int) -> list:
    rutas = analitica.rutas_mas_usadas(bd, 8, "retraso")
    flotilla = analitica.desempeno_vehiculos(bd, "costo", 8)

    partes = comun.seccion(
        "3. Dónde están los problemas",
        "Las rutas que más se desvían de su hora prometida y las unidades "
        "que más cuestan operar. Del ranking de retrasos se excluyen las "
        f"rutas con menos de {analitica.MINIMO_ENTREGAS_RANKING} entregas: "
        "el promedio de una muestra pequeña es ruido con apariencia de "
        "dato.")

    # --- rutas ---
    partes.append(comun.juntos([
        comun.Paragraph("Rutas con mayor retraso medio",
                        comun.ESTILOS["subseccion"]),
        comun.tabla(
            ["Ruta", "Zona", "Entregas", "Retraso medio<br/>(minutos)",
             "Fuera de hora", "Distancia<br/>(km)"],
            [[f"<b>{f['codigo_ruta']}</b><br/>"
              f"<font size=6 color='#667589'>{f['nombre_ruta'] or ''}</font>",
              f["zona"] or "—",
              comun.entero(f["entregas"]),
              comun.numero(f["retraso_medio_min"]),
              comun.porcentaje(f["pct_retrasadas"]),
              comun.numero(f["distancia_km"])]
             for f in rutas["rutas"]],
            anchos=[comun.ANCHO_UTIL * p for p in
                    (.28, .12, .13, .17, .15, .15)],
            alinear_derecha=(2, 3, 4, 5),
            destacar=lambda i: rutas["rutas"][i]["sobre_umbral"]),
    ]))
    partes.append(comun.lectura(rutas["lectura"]))

    # --- vehículos ---
    def dibujar(ax):
        filas = list(reversed(flotilla["vehiculos"]))
        etiquetas = [v["codigo_vehiculo"] for v in filas]
        combustible = [v["costo_combustible"] for v in filas]
        mantenimiento = [v["costo_mantenimiento"] for v in filas]
        ax.barh(etiquetas, combustible, color="#ff7f0e", label="Combustible")
        ax.barh(etiquetas, mantenimiento, left=combustible, color="#1f4e79",
                label="Mantenimiento")
        ax.set_xlabel("Costo de operación acumulado (MXN)")
        ax.set_ylabel("Vehículo")
        ax.set_title("Costo de operación por vehículo", fontsize=9,
                     fontweight="bold")
        ax.legend(fontsize=7)
        ax.grid(alpha=.25, axis="x")
        for i, v in enumerate(filas):
            ax.text(v["costo_total"] * 1.01, i,
                    f"{comun.dinero(v['costo_total'])}", va="center",
                    fontsize=6)

    partes.append(comun.espacio(0.3))
    partes.append(comun.Paragraph("Unidades de mayor costo de operación",
                                  comun.ESTILOS["subseccion"]))
    partes.append(comun.grafica(dibujar, alto_cm=6.5))
    partes.append(comun.lectura(flotilla["lectura"]))
    return partes


def _causas(bd: Database) -> list:
    datos = analitica.causas_retraso(bd)
    causas = datos["causas"]

    partes = comun.seccion(
        "4. Por qué ocurre",
        "Las causas del retraso ordenadas de mayor a menor frecuencia, con "
        "el porcentaje acumulado. Las marcadas en rojo son las pocas que "
        "explican la mayor parte del problema: atacarlas rinde más que "
        "repartir el esfuerzo entre todas.")

    def dibujar(ax):
        etiquetas = [c["causa"].replace("_", " ").lower() for c in causas]
        valores = [c["entregas"] for c in causas]
        colores = ["#d62728" if c["es_vital"] else "#8c9bb0" for c in causas]
        ax.bar(etiquetas, valores, color=colores, alpha=.9)
        ax.set_xlabel("Causa del retraso")
        ax.set_ylabel("Entregas retrasadas")
        ax.tick_params(axis="x", rotation=25, labelsize=7)
        ax.grid(alpha=.25, axis="y")
        ax.set_title("Causas del retraso, de mayor a menor frecuencia",
                     fontsize=9, fontweight="bold")

        eje = ax.twinx()
        eje.plot(etiquetas, [c["porcentaje_acumulado"] for c in causas],
                 color="#16202e", marker="o", markersize=3, linewidth=1.3)
        eje.axhline(80, color="#ff7f0e", linestyle="--", linewidth=1)
        eje.set_ylabel("Acumulado (%)")
        eje.set_ylim(0, 105)

    partes.append(comun.grafica(dibujar, alto_cm=6.5))
    partes.append(comun.lectura(datos["lectura"]))
    return partes


def _tipos_de_ruta(bd: Database) -> list:
    """
    Los grupos del agrupamiento, en lenguaje de negocio.

    Se nombran y se explican en vez de presentarlos como «grupo 0» y
    «grupo 1»: un identificador técnico no le dice nada a quien decide.
    """
    try:
        datos = servicio_ml.clusters_rutas(bd)
    except ErrorSIGLOG as error:
        return [comun.aviso(f"<b>Tipos de ruta.</b> No disponible: "
                            f"{error.mensaje}")]

    partes = comun.seccion(
        "5. Qué tipos de ruta hay",
        "Las rutas agrupadas por comportamiento parecido —distancia, "
        "paradas, velocidad, retraso e incidentes—. Cada grupo lleva la "
        "recomendación que le corresponde.")

    partes.append(comun.tabla(
        ["Tipo de ruta", "Rutas", "Qué caracteriza al grupo",
         "Qué conviene hacer"],
        [[f"<b>{g['nombre']}</b>", comun.entero(g["total_rutas"]),
          g["descripcion"] or "—", g["recomendacion"] or "—"]
         for g in datos["grupos"]],
        anchos=[comun.ANCHO_UTIL * p for p in (.20, .07, .36, .37)]))

    partes.append(comun.lectura(datos["lectura"]))
    partes.append(comun.aviso(
        "<b>Cómo leer estos grupos.</b> No son categorías cerradas. Las "
        "rutas forman un continuo y muchas quedan cerca de la frontera "
        "entre dos grupos; el agrupamiento sirve para ordenar la operación "
        "y priorizar, no para afirmar que existen tipos de ruta bien "
        "separados."))
    return partes
