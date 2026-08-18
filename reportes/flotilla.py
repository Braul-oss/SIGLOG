"""
SIG-LOG — Sistema Integral de Gestión Logística
reportes/flotilla.py

INFORME DE FLOTILLA

Responde las cuatro preguntas del proyecto que se contestan mirando los
vehículos:

    ¿Qué vehículos generan mayores costos?
    ¿Qué vehículos consumen más combustible?
    ¿Qué vehículos tienen más entregas?
    ¿Qué vehículos presentan más retrasos?

Y una quinta que aparece al cruzarlas: qué unidades cuestan mucho para lo
poco que mueven. El costo total premia a las que trabajan menos, así que la
cifra que decide es el costo por entrega.

Cada unidad se identifica por su código y su modelo. El identificador
interno no aparece en ninguna parte del documento: a quien lee un informe
no le dice nada.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from pymongo.database import Database

from backend.services import analitica, mantenimientos as servicio_mtto
from backend.utils.errores import ErrorSIGLOG
from config import settings
from reportes import comun

TITULO = "Informe de flotilla"
SUBTITULO = ("Desempeño de los vehículos: qué cuestan, qué consumen, cuánto "
             "trabajan y con qué puntualidad.")


def construir(bd: Database) -> bytes:
    datos = analitica.desempeno_vehiculos(bd, "costo", 100)
    totales = datos["totales"]
    periodo = datos["periodo"]
    umbral = datos["umbral_retraso_min"]
    flota = datos["vehiculos"]

    elementos: list = comun.portada(TITULO, SUBTITULO, periodo)

    # -------------------------------------------------------- el conjunto --
    elementos += comun.seccion(
        "1. La flotilla en conjunto",
        f"{datos['flotilla']} unidades en operación durante el periodo. "
        "Estas cifras son la referencia contra la que se juzga cada "
        "vehículo: una unidad cara solo lo es comparada con las demás.")

    elementos.append(comun.tabla(
        ["Costo de operación", "Combustible", "Distancia", "Entregas",
         "Rendimiento medio", "Fuera de operación"],
        [[comun.dinero(totales["costo_total"]),
          f"{comun.numero(totales['litros'], 0)} litros<br/>"
          f"<font size=6 color='#667589'>"
          f"{comun.dinero(totales['costo_combustible'])}</font>",
          f"{comun.numero(totales['km_recorridos'], 0)} km",
          f"{comun.entero(totales['entregas'])}<br/>"
          f"<font size=6 color='#667589'>en "
          f"{comun.entero(totales['viajes'])} viajes</font>",
          f"{comun.numero(totales['rendimiento_medio_km_l'], 2)} km/l",
          f"{comun.entero(totales['en_mantenimiento'])} unidades"]],
        alinear_derecha=(0, 1, 2, 3, 4, 5)))

    costo_medio_entrega = (totales["costo_total"] / totales["entregas"]
                           if totales["entregas"] else 0)
    elementos.append(comun.lectura(
        f"La operación de la flotilla costó "
        f"{comun.dinero(totales['costo_total'])} en el periodo, de los que "
        f"{comun.dinero(totales['costo_combustible'])} son combustible y "
        f"{comun.dinero(totales['costo_mantenimiento'])} mantenimiento. "
        f"Repartido entre las {comun.entero(totales['entregas'])} entregas "
        f"realizadas, sale a {comun.dinero(costo_medio_entrega, 2)} por "
        "entrega: esa es la cifra contra la que conviene comparar cada "
        "unidad."))

    # ------------------------------------------------------ las preguntas --
    elementos += _ranking(bd, "costo", "2. ¿Qué unidades cuestan más?",
                          "Combustible más mantenimiento acumulados en el "
                          "periodo. Una unidad cara no es necesariamente un "
                          "problema: puede ser la que más trabaja. Eso se "
                          "resuelve en el apartado 6.")

    elementos += _ranking(bd, "combustible",
                          "3. ¿Qué unidades consumen más combustible?",
                          "Litros cargados en el periodo. Consumir mucho es "
                          "esperable en una unidad que rueda mucho; el aviso "
                          "está en el rendimiento, no en el consumo.")

    elementos.append(comun.salto())

    elementos += _ranking(bd, "entregas", "4. ¿Qué unidades trabajan más?",
                          "Entregas realizadas. Junto al costo por entrega "
                          "es lo que permite saber si una unidad rinde lo "
                          "que cuesta.")

    elementos += _ranking(bd, "retraso", "5. ¿Qué unidades llegan tarde?",
                          "Retraso medio de sus entregas. El retraso rara "
                          "vez es culpa del vehículo: conviene cruzarlo con "
                          "las rutas que cubre antes de concluir nada.",
                          umbral=umbral)

    # ------------------------------------------------- costo frente a uso --
    elementos.append(comun.salto())
    elementos += _costo_frente_a_trabajo(flota, totales, datos["flotilla"])

    # ------------------------------------------------------- el detalle ---
    elementos.append(comun.salto())
    elementos += _detalle(flota, umbral)

    # ------------------------------------------------------ mantenimiento --
    elementos += _mantenimiento(bd)

    return comun.documento(TITULO, SUBTITULO, elementos)


# ==========================================================================
# BLOQUES
# ==========================================================================
_EJES = {
    "costo": ("costo_total", "Costo de operación (MXN)", "#d62728"),
    "combustible": ("litros", "Combustible consumido (litros)", "#ff7f0e"),
    "entregas": ("entregas", "Entregas realizadas", "#1f4e79"),
    "retraso": ("retraso_medio_min", "Retraso medio (minutos)", "#d62728"),
}


def _ranking(bd: Database, criterio: str, titulo: str, explicacion: str,
             umbral: int | None = None) -> list:
    datos = analitica.desempeno_vehiculos(bd, criterio, 8)
    filas = datos["vehiculos"]
    campo, eje, color = _EJES[criterio]

    def dibujar(ax):
        orden = list(reversed(filas))
        etiquetas = [v["codigo_vehiculo"] for v in orden]
        valores = [v[campo] or 0 for v in orden]
        colores = color
        if umbral is not None:
            colores = ["#d62728" if (v[campo] or 0) > umbral else "#1f4e79"
                       for v in orden]
        ax.barh(etiquetas, valores, color=colores, alpha=.9)
        if umbral is not None:
            ax.axvline(umbral, color="#8c9bb0", linestyle="--", linewidth=1.2)
            ax.text(umbral, -0.7, f"  umbral {umbral} min", fontsize=6,
                    color="#667589")
        ax.set_xlabel(eje)
        ax.set_ylabel("Vehículo")
        ax.set_title(titulo.split(". ", 1)[-1], fontsize=9, fontweight="bold")
        ax.grid(alpha=.25, axis="x")
        for i, valor in enumerate(valores):
            texto = (comun.dinero(valor) if criterio == "costo"
                     else comun.numero(valor, 0 if criterio != "retraso" else 1))
            ax.text(valor * 1.01, i, f" {texto}", va="center", fontsize=6)

    partes = comun.seccion(titulo, explicacion)
    partes.append(comun.grafica(dibujar, alto_cm=6.0))
    partes.append(comun.lectura(datos["lectura"]))
    return partes


def _costo_frente_a_trabajo(flota: list[dict[str, Any]],
                            totales: dict[str, Any], tamano: int) -> list:
    """
    El cruce que ninguna de las cuatro preguntas resuelve por separado.

    Una unidad cara que entrega mucho está bien; una unidad cara que entrega
    poco es donde hay dinero que recuperar.
    """
    costo_medio = totales["costo_medio_por_vehiculo"]
    entregas_media = totales["entregas"] / (tamano or 1)
    ineficientes = [v for v in flota
                    if v["costo_total"] > costo_medio
                    and v["entregas"] < entregas_media]

    def dibujar(ax):
        for grupo, color, etiqueta in (
            (ineficientes, "#d62728", "Cuesta más de lo que trabaja"),
            ([v for v in flota if v not in ineficientes], "#1f4e79",
             "Dentro de lo esperado"),
        ):
            ax.scatter([v["entregas"] for v in grupo],
                       [v["costo_total"] for v in grupo],
                       s=[30 + 170 * v["litros"] / (totales["litros"] or 1)
                          * tamano for v in grupo],
                       color=color, alpha=.6, label=etiqueta,
                       edgecolors="white", linewidth=.5)
        for v in ineficientes:
            ax.annotate(v["codigo_vehiculo"],
                        (v["entregas"], v["costo_total"]),
                        fontsize=6, xytext=(5, 4),
                        textcoords="offset points", color="#8a2020")
        ax.axhline(costo_medio, color="#8c9bb0", linestyle=":", linewidth=1)
        ax.axvline(entregas_media, color="#8c9bb0", linestyle=":", linewidth=1)
        ax.set_xlabel("Entregas realizadas")
        ax.set_ylabel("Costo de operación (MXN)")
        ax.set_title("Costo de operación frente a entregas realizadas",
                     fontsize=9, fontweight="bold")
        ax.legend(fontsize=7, loc="upper left")
        ax.grid(alpha=.2)

    partes = comun.seccion(
        "6. ¿Qué unidades cuestan más de lo que trabajan?",
        "Cada punto es un vehículo; el tamaño indica los litros consumidos. "
        "Las líneas punteadas marcan la media de la flotilla. Las unidades "
        "del cuadrante superior izquierdo —por encima del costo medio y por "
        "debajo de las entregas medias— son las primeras a revisar.")
    partes.append(comun.grafica(dibujar, alto_cm=8.0))

    if ineficientes:
        peor = max(ineficientes, key=lambda v: v["costo_por_entrega"] or 0)
        medio = (totales["costo_total"] / totales["entregas"]
                 if totales["entregas"] else 0)
        partes.append(comun.lectura(
            f"{len(ineficientes)} de las {tamano} unidades gastan por encima "
            f"de la media ({comun.dinero(costo_medio)}) y entregan por debajo "
            f"de ella ({comun.numero(entregas_media, 0)} entregas). La más "
            f"desproporcionada es {peor['codigo_vehiculo']} "
            f"({peor['descripcion']}), con "
            f"{comun.dinero(peor['costo_por_entrega'], 2)} por entrega frente "
            f"a los {comun.dinero(medio, 2)} del promedio de la flotilla."))
    else:
        partes.append(comun.lectura(
            "Ninguna unidad gasta por encima de la media entregando por "
            "debajo de ella: el costo de la flotilla acompaña al trabajo que "
            "hace cada vehículo."))
    return partes


def _detalle(flota: list[dict[str, Any]], umbral: int) -> list:
    partes = comun.seccion(
        "7. Detalle por unidad",
        "Todas las unidades, ordenadas por costo de operación. En rojo, las "
        f"que promedian más de {umbral} minutos de retraso o cuyo "
        "rendimiento real queda por debajo del de ficha.")

    filas = []
    for v in flota:
        filas.append([
            f"<b>{v['codigo_vehiculo']}</b><br/>"
            f"<font size=6 color='#667589'>{v['descripcion']}<br/>"
            f"{v['placa']}</font>",
            v["tipo_vehiculo"] or "—",
            comun.entero(v["viajes"]),
            comun.entero(v["entregas"]),
            comun.numero(v["km_recorridos"], 0),
            comun.dinero(v["costo_total"]),
            comun.dinero(v["costo_por_entrega"], 2),
            comun.numero(v["litros"], 0),
            f"{comun.numero(v['rendimiento_real_km_l'], 2)}<br/>"
            f"<font size=6 color='#667589'>ficha "
            f"{comun.numero(v['rendimiento_nominal_km_l'], 2)}</font>",
            (f"{comun.numero(v['retraso_medio_min'], 1)}<br/>"
             f"<font size=6 color='#667589'>"
             f"{comun.porcentaje(v['pct_retrasadas'])} tarde</font>"
             if v["retraso_medio_min"] is not None else "—"),
            comun.entero(v["mantenimientos"]),
        ])

    def problematica(i: int) -> bool:
        v = flota[i]
        tarde = (v["retraso_medio_min"] or 0) > umbral
        flojo = (v["desviacion_rendimiento_pct"] or 0) < 0
        return tarde or flojo

    partes.append(comun.tabla(
        ["Vehículo", "Tipo", "Viajes", "Entregas", "Km",
         "Costo total<br/>(MXN)", "Costo/entrega<br/>(MXN)",
         "Combustible<br/>(litros)", "Rendimiento<br/>(km/l)",
         "Retraso medio<br/>(minutos)", "Servicios"],
        filas,
        anchos=[comun.ANCHO_UTIL * p for p in
                (.15, .07, .06, .07, .08, .10, .09, .09, .10, .11, .08)],
        alinear_derecha=(2, 3, 4, 5, 6, 7, 8, 9, 10),
        destacar=problematica))
    return partes


def _mantenimiento(bd: Database) -> list:
    try:
        datos = servicio_mtto.pendientes(bd)
    except ErrorSIGLOG as error:
        return [comun.aviso(f"<b>Mantenimiento.</b> No disponible: "
                            f"{error.mensaje}")]

    partes = comun.seccion(
        "8. ¿Qué unidades requieren mantenimiento?",
        "Los servicios vencidos ya sacaron la unidad de operación y no "
        "puede programarse en una jornada. Los atrasados son los que hay "
        "que atender hoy. Los próximos aún se pueden planificar sin parar "
        "nada.")

    filas = []
    etiquetas = {"vencidos": "Vencido — unidad parada",
                 "atrasados": "Atrasado — atender hoy",
                 "proximos": "Próximo — planificable"}
    for grupo, etiqueta in etiquetas.items():
        for m in datos[grupo]:
            filas.append([
                f"<b>{m['codigo_vehiculo']}</b> "
                f"<font size=6 color='#667589'>{m.get('placa') or ''}</font>",
                etiqueta,
                m["tipo"] or "—",
                comun.fecha(m["fecha_programada"]),
                comun.entero(m["dias"]),
                (m["estado_operativo"] or "—").replace("_", " ").title(),
            ])

    if not filas:
        partes.append(comun.lectura(datos["alerta"]))
        return partes

    vencidos = datos["total_vencidos"]
    partes.append(comun.tabla(
        ["Vehículo", "Situación", "Tipo de servicio",
         "Fecha programada", "Días de diferencia", "Estado de la unidad"],
        filas,
        anchos=[comun.ANCHO_UTIL * p for p in
                (.16, .24, .14, .16, .15, .15)],
        alinear_derecha=(4,),
        destacar=lambda i: i < vencidos))
    partes.append(comun.lectura(datos["alerta"]))
    return partes
