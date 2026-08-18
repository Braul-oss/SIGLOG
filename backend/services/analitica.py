"""
SIG-LOG — Sistema Integral de Gestión Logística
backend/services/analitica.py

CAPA ANALÍTICA EXPUESTA POR EL API  (§12.3, panel A del §18.2)

Este módulo **no calcula KPIs**. Los diez indicadores del dashboard salen
de `analytics.kpis.calcular()`, que es y sigue siendo el único lugar donde
se definen. Aquí solo se envuelven en el contrato de respuesta del API.

Regla de la capa 8 (§7.3): la visualización *comunica e interpreta, no
recalcula métricas por su cuenta*. El API es un consumidor más de esa capa,
y se sujeta a la misma regla.

Las tres consultas agregadas del §12.3 —rutas más usadas, causas de retraso
y saturación horaria— sí se resuelven aquí, con agregaciones de MongoDB.
No existían como función que devolviera datos: en `analytics/graficas.py`
viven dentro de las funciones que dibujan, que reciben un `ax` de
matplotlib y devuelven texto, no cifras. Sacarlas de ahí habría exigido
reescribir el módulo de gráficas, que el alcance del proyecto deja intacto.

Se sigue la misma decisión de diseño de `analytics/kpis.py`: agregar en el
motor de base de datos y devolver unas pocas cifras, en vez de traer 14,779
documentos a pandas para agrupar. Y para que las dos vías no se separen
nunca, `tests/test_analitica.py` compara cifra por cifra la salida de estos
endpoints con lo que las funciones de `analytics/graficas.py` calculan sobre
los mismos datos. Si alguien cambia una definición y no la otra, la prueba
falla.

El filtro `calidad_dato == "OK"` es el mismo que aplican
`analytics.graficas.cargar_hechos` y `ml.evaluacion.cargar_dataset`: las
entregas con captura omitida no tienen retraso medible y las canceladas
nunca ocurrieron (decisión D-L3 de PA-5).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from pymongo.database import Database

from analytics import kpis as kpis_analytics
from backend.utils.errores import ServicioNoDisponible
from config import settings

COLECCION_HECHOS = "hecho_entrega"
FILTRO_CALIDAD: dict[str, Any] = {"calidad_dato": "OK"}

ORDEN_FRANJAS = ("MADRUGADA", "PICO_MATUTINO", "VALLE",
                 "PICO_VESPERTINO", "NOCHE")
NOMBRES_DIA = ("Lunes", "Martes", "Miércoles", "Jueves", "Viernes",
               "Sábado", "Domingo")
CAUSA_SIN_REGISTRO = "NO REGISTRADA"


# ==========================================================================
# KPIs  —  delegación pura
# ==========================================================================
def kpis(bd: Database) -> dict[str, Any]:
    """
    Los diez indicadores del Panel A, tal como los define
    `analytics.kpis.calcular()`, más el resumen ejecutivo de RF-29.

    Si el data warehouse está vacío, `analytics.kpis` levanta un
    `RuntimeError` con la instrucción de correr el ETL. Se traduce a 503 y
    no a 500: no es un fallo del sistema, es una dependencia que todavía no
    se ha ejecutado, y el mensaje debe decir qué hacer.
    """
    try:
        indicadores = kpis_analytics.calcular(bd)
    except RuntimeError as error:
        raise ServicioNoDisponible(
            f"La capa analítica no está lista: {error}") from error

    # Vocabulario de `analytics.kpis._semaforo`: VERDE cumple la meta,
    # AMARILLO se queda cerca, ROJO lejos, NEUTRO no se juzga contra meta.
    semaforos = {"VERDE": 0, "AMARILLO": 0, "ROJO": 0, "NEUTRO": 0}
    for indicador in indicadores:
        semaforos[indicador["semaforo"]] = semaforos.get(
            indicador["semaforo"], 0) + 1

    return {
        "indicadores": indicadores,
        "total_indicadores": len(indicadores),
        "semaforos": semaforos,
        "resumen_ejecutivo": kpis_analytics.resumen_ejecutivo(indicadores),
        "metas": {
            "puntualidad_pct": kpis_analytics.META_PUNTUALIDAD_PCT,
            "retraso_medio_min": kpis_analytics.META_RETRASO_MEDIO_MIN,
            "vehiculos_en_mantenimiento": (
                kpis_analytics.LIMITE_VEHICULOS_MANTENIMIENTO),
        },
        "umbral_retraso_min": settings.UMBRAL_RETRASO_MIN,
    }


# ==========================================================================
# RUTAS MÁS USADAS
# ==========================================================================
def rutas_mas_usadas(bd: Database, top: int = 10) -> dict[str, Any]:
    """
    Volumen, viajes y retraso medio por ruta, de mayor a menor volumen.

    Misma definición que `graficas.rutas_mas_utilizadas`: las entregas se
    suman por `numero_entregas` (no se cuentan documentos) y los viajes son
    folios distintos, porque un viaje aporta varias paradas.
    """
    filas = list(bd[COLECCION_HECHOS].aggregate([
        {"$match": FILTRO_CALIDAD},
        {"$group": {
            "_id": "$ruta_id",
            "entregas": {"$sum": "$numero_entregas"},
            "viajes": {"$addToSet": "$folio_viaje"},
            "retraso_medio_min": {"$avg": "$retraso_min"},
            "retrasadas": {"$sum": "$es_retraso"},
        }},
        {"$sort": {"entregas": -1}},
        {"$limit": max(top, 1)},
        {"$lookup": {"from": "dim_ruta", "localField": "_id",
                     "foreignField": "_id", "as": "ruta"}},
        {"$unwind": {"path": "$ruta", "preserveNullAndEmptyArrays": True}},
        {"$project": {
            "_id": 0,
            "ruta_id": "$_id",
            "codigo_ruta": "$ruta.codigo_ruta",
            "nombre_ruta": "$ruta.nombre",
            "zona": "$ruta.zona",
            "entregas": 1,
            "viajes": {"$size": "$viajes"},
            "retraso_medio_min": {"$round": ["$retraso_medio_min", 2]},
            "retrasadas": 1,
        }},
    ]))

    umbral = settings.UMBRAL_RETRASO_MIN
    for fila in filas:
        fila["pct_retrasadas"] = (round(100 * fila["retrasadas"]
                                        / fila["entregas"], 1)
                                  if fila["entregas"] else 0.0)
        fila["sobre_umbral"] = fila["retraso_medio_min"] > umbral

    criticas = [f for f in filas if f["sobre_umbral"]]
    if not filas:
        lectura = "No hay entregas cargadas en el data warehouse."
    elif criticas:
        lectura = (
            f"La ruta de mayor volumen es {filas[0]['codigo_ruta']}, con "
            f"{filas[0]['entregas']:,} entregas. "
            f"{len(criticas)} de las {len(filas)} rutas más usadas superan en "
            f"promedio el umbral de {umbral} minutos "
            f"({', '.join(f['codigo_ruta'] for f in criticas)}): son "
            "prioritarias porque su impacto se multiplica por el volumen que "
            "mueven.")
    else:
        lectura = (
            f"La ruta de mayor volumen es {filas[0]['codigo_ruta']}, con "
            f"{filas[0]['entregas']:,} entregas. Ninguna de las "
            f"{len(filas)} más usadas supera en promedio el umbral de "
            f"{umbral} minutos: el retraso de la operación no viene del "
            "volumen, sino de rutas concretas con problemas propios.")

    return {"top": max(top, 1), "rutas": filas, "total": len(filas),
            "umbral_retraso_min": umbral, "lectura": lectura}


# ==========================================================================
# CAUSAS DE RETRASO  (Pareto)
# ==========================================================================
def causas_retraso(bd: Database) -> dict[str, Any]:
    """
    Pareto de las causas, sobre las entregas efectivamente retrasadas.

    "Pocos vitales" incluye la causa que **cruza** el 80% acumulado, no solo
    las que quedan por debajo. Es el mismo criterio que
    `graficas.pareto_causas`, y existe por una razón concreta: cuando una
    sola causa ya supera el 80%, marcar únicamente las que están por debajo
    dejaría fuera precisamente a la dominante.
    """
    filas = list(bd[COLECCION_HECHOS].aggregate([
        {"$match": {**FILTRO_CALIDAD, "es_retraso": 1}},
        {"$group": {
            "_id": {"$ifNull": ["$causa_retraso", CAUSA_SIN_REGISTRO]},
            "entregas": {"$sum": 1},
            "retraso_medio_min": {"$avg": "$retraso_min"},
        }},
        {"$sort": {"entregas": -1}},
        {"$project": {
            "_id": 0, "causa": "$_id", "entregas": 1,
            "retraso_medio_min": {"$round": ["$retraso_medio_min", 2]},
        }},
    ]))

    total = sum(f["entregas"] for f in filas)
    if not total:
        return {"causas": [], "total_retrasadas": 0, "pocos_vitales": 0,
                "lectura": "No hay entregas retrasadas en el periodo."}

    acumulado = 0.0
    vitales = 0
    cruzado = False
    for fila in filas:
        acumulado += 100 * fila["entregas"] / total
        fila["porcentaje"] = round(100 * fila["entregas"] / total, 1)
        fila["porcentaje_acumulado"] = round(acumulado, 1)
        # La causa que cruza el 80% entra; a partir de ahí, ninguna más.
        fila["es_vital"] = not cruzado
        if not cruzado:
            vitales += 1
            if acumulado >= 80:
                cruzado = True

    principales = ", ".join(f["causa"].replace("_", " ").lower()
                            for f in filas[:vitales])
    if vitales == 1:
        lectura = (
            f"Una sola de las {len(filas)} causas concentra el "
            f"{filas[0]['porcentaje_acumulado']:.0f}% de las entregas "
            f"retrasadas: {principales}, con {filas[0]['entregas']:,} "
            "entregas. Concentrar el esfuerzo en esa única causa rinde más "
            "que repartirlo entre todas.")
    else:
        lectura = (
            f"{vitales} de {len(filas)} causas concentran el "
            f"{filas[vitales - 1]['porcentaje_acumulado']:.0f}% de las "
            f"entregas retrasadas: {principales}. La primera aporta "
            f"{filas[0]['entregas']:,} entregas ({filas[0]['porcentaje']:.0f}%). "
            "Atacar esas pocas causas rinde más que repartir el esfuerzo "
            "entre todas.")

    return {"causas": filas, "total_retrasadas": total,
            "pocos_vitales": vitales, "lectura": lectura}


# ==========================================================================
# SATURACIÓN HORARIA
# ==========================================================================
def saturacion_horaria(bd: Database) -> dict[str, Any]:
    """
    Entregas por franja horaria y día de la semana.

    El data warehouse guarda la franja, no la hora exacta: es el grano al
    que el diseño (D-T1) decidió analizar la saturación, y el que usa el
    heatmap del Panel B.

    El consejo depende de si la celda más cargada coincide con la franja de
    menor retraso. Recomendar "mover carga al valle" cuando el pico ya está
    en el valle sería contradictorio, y lo fue en una versión anterior de la
    gráfica hasta que se corrigió.
    """
    celdas = list(bd[COLECCION_HECHOS].aggregate([
        {"$match": FILTRO_CALIDAD},
        {"$group": {
            "_id": {"franja": "$franja_horaria", "dia": "$dia_semana"},
            "entregas": {"$sum": "$numero_entregas"},
            "retraso_medio_min": {"$avg": "$retraso_min"},
        }},
        {"$project": {
            "_id": 0,
            "franja_horaria": "$_id.franja",
            "dia_semana": "$_id.dia",
            "dia_nombre": {"$arrayElemAt": [list(NOMBRES_DIA), "$_id.dia"]},
            "entregas": 1,
            "retraso_medio_min": {"$round": ["$retraso_medio_min", 2]},
        }},
    ]))

    por_franja = list(bd[COLECCION_HECHOS].aggregate([
        {"$match": FILTRO_CALIDAD},
        {"$group": {"_id": "$franja_horaria",
                    "entregas": {"$sum": "$numero_entregas"},
                    "retraso_medio_min": {"$avg": "$retraso_min"}}},
        {"$project": {"_id": 0, "franja_horaria": "$_id", "entregas": 1,
                      "retraso_medio_min": {"$round": ["$retraso_medio_min", 2]}}},
    ]))

    if not celdas:
        return {"celdas": [], "por_franja": [], "total_entregas": 0,
                "lectura": "No hay entregas cargadas en el data warehouse."}

    orden = {franja: i for i, franja in enumerate(ORDEN_FRANJAS)}
    celdas.sort(key=lambda c: (orden.get(c["franja_horaria"], 99),
                               c["dia_semana"]))
    por_franja.sort(key=lambda f: orden.get(f["franja_horaria"], 99))

    total = sum(c["entregas"] for c in celdas)
    pico = max(celdas, key=lambda c: c["entregas"])
    mejor = min(por_franja, key=lambda f: f["retraso_medio_min"])
    franja_pico = next(f for f in por_franja
                       if f["franja_horaria"] == pico["franja_horaria"])

    if pico["franja_horaria"] == mejor["franja_horaria"]:
        consejo = ("La mayor carga coincide con la franja de menor retraso: "
                   "la programación actual ya está aprovechando la mejor "
                   "ventana del día.")
    else:
        consejo = (
            f"Esa franja no es la de menor retraso: mover parte de la carga a "
            f"{mejor['franja_horaria'].replace('_', ' ').lower()}, que "
            f"promedia {mejor['retraso_medio_min']:.1f} min frente a "
            f"{franja_pico['retraso_medio_min']:.1f}, es la palanca más "
            "directa sobre el retraso.")

    lectura = (
        f"La mayor saturación ocurre en "
        f"{pico['franja_horaria'].replace('_', ' ').lower()} de "
        f"{pico['dia_nombre'].lower()}, con {pico['entregas']:,} entregas "
        f"({100 * pico['entregas'] / total:.1f}% del total). {consejo}")

    return {
        "celdas": celdas,
        "por_franja": por_franja,
        "total_entregas": total,
        "franja_pico": pico["franja_horaria"],
        "dia_pico": pico["dia_semana"],
        "franja_menor_retraso": mejor["franja_horaria"],
        "lectura": lectura,
    }
