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
from backend.utils.errores import ReglaDeNegocio, ServicioNoDisponible
from config import settings

COLECCION_HECHOS = "hecho_entrega"
FILTRO_CALIDAD: dict[str, Any] = {"calidad_dato": "OK"}

ORDEN_FRANJAS = ("MADRUGADA", "PICO_MATUTINO", "VALLE",
                 "PICO_VESPERTINO", "NOCHE")
NOMBRES_DIA = ("Lunes", "Martes", "Miércoles", "Jueves", "Viernes",
               "Sábado", "Domingo")
MESES = ("", "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
         "agosto", "septiembre", "octubre", "noviembre", "diciembre")
CAUSA_SIN_REGISTRO = "NO REGISTRADA"

# Mínimo de entregas para entrar en un ranking de promedios.
#
# Sin este corte, una ruta con tres entregas y un mal día encabezaría la
# lista de "peores retrasos" por delante de otra con mil entregas y un
# problema sistemático. El promedio de una muestra diminuta no es una
# medida del desempeño: es ruido con apariencia de dato.
MINIMO_ENTREGAS_RANKING: int = 50


def periodo(bd: Database) -> dict[str, Any]:
    """
    Rango de fechas que cubren los datos, para rotularlo en las gráficas.

    Una cifra sin su periodo no se puede interpretar: "1,127 entregas" dice
    cosas muy distintas si son de una semana o de seis meses.
    """
    filas = list(bd[COLECCION_HECHOS].aggregate([
        {"$match": FILTRO_CALIDAD},
        {"$group": {"_id": None, "desde": {"$min": "$fecha"},
                    "hasta": {"$max": "$fecha"}}},
    ]))
    if not filas or not filas[0].get("desde"):
        return {"desde": None, "hasta": None, "etiqueta": "sin datos"}

    desde, hasta = filas[0]["desde"], filas[0]["hasta"]
    if desde.year == hasta.year:
        etiqueta = (f"{MESES[desde.month]} a {MESES[hasta.month]} "
                    f"de {hasta.year}")
    else:
        etiqueta = (f"{MESES[desde.month]} {desde.year} a "
                    f"{MESES[hasta.month]} {hasta.year}")
    return {"desde": desde.date().isoformat(),
            "hasta": hasta.date().isoformat(),
            "etiqueta": etiqueta.capitalize()}


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
ORDEN_RUTAS = ("volumen", "retraso", "incidencia")


def rutas_mas_usadas(bd: Database, top: int = 10,
                     orden: str = "volumen") -> dict[str, Any]:
    """
    Volumen, viajes y retraso medio por ruta.

    Responde a dos preguntas de negocio distintas según cómo se ordene, y
    por eso el criterio es un parámetro y no una segunda función:

        volumen     ¿qué rutas son más utilizadas?
        retraso     ¿qué rutas presentan mayores retrasos?
        incidencia  ¿en qué rutas se retrasa una proporción mayor de
                    entregas? No es lo mismo que la anterior: una ruta
                    puede tener un retraso medio bajo y aun así fallar en
                    la mitad de sus entregas.

    Las entregas se suman por `numero_entregas` —no se cuentan documentos—
    y los viajes son folios distintos, porque un viaje aporta varias
    paradas. Es la definición de `graficas.rutas_mas_utilizadas`, y
    `tests/test_analitica.py` comprueba que las dos sigan coincidiendo.

    Al ordenar por retraso se descartan las rutas con menos de
    `MINIMO_ENTREGAS_RANKING` entregas: una ruta con tres entregas y un mal
    día encabezaría la lista sin que eso signifique nada.
    """
    orden = (orden or "volumen").strip().lower()
    if orden not in ORDEN_RUTAS:
        raise ReglaDeNegocio(
            f"Orden '{orden}' no válido. Debe ser uno de {list(ORDEN_RUTAS)}.")

    filas = list(bd[COLECCION_HECHOS].aggregate([
        {"$match": FILTRO_CALIDAD},
        {"$group": {
            "_id": "$ruta_id",
            "entregas": {"$sum": "$numero_entregas"},
            "viajes": {"$addToSet": "$folio_viaje"},
            "retraso_medio_min": {"$avg": "$retraso_min"},
            "retrasadas": {"$sum": "$es_retraso"},
            "distancia_km": {"$avg": "$distancia_total_ruta_km"},
            "tiempo_estimado_min": {"$avg": "$tiempo_estimado_min"},
        }},
        {"$lookup": {"from": "dim_ruta", "localField": "_id",
                     "foreignField": "_id", "as": "ruta"}},
        {"$unwind": {"path": "$ruta", "preserveNullAndEmptyArrays": True}},
        {"$project": {
            "_id": 0,
            "ruta_id": "$_id",
            "codigo_ruta": "$ruta.codigo_ruta",
            "nombre_ruta": "$ruta.nombre",
            "zona": "$ruta.zona",
            "paradas": "$ruta.numero_paradas",
            "entregas": 1,
            "viajes": {"$size": "$viajes"},
            "retraso_medio_min": {"$round": ["$retraso_medio_min", 2]},
            "retrasadas": 1,
            "distancia_km": {"$round": ["$distancia_km", 1]},
            "tiempo_estimado_min": {"$round": ["$tiempo_estimado_min", 1]},
        }},
    ]))

    umbral = settings.UMBRAL_RETRASO_MIN
    for fila in filas:
        fila["pct_retrasadas"] = (round(100 * fila["retrasadas"]
                                        / fila["entregas"], 1)
                                  if fila["entregas"] else 0.0)
        fila["sobre_umbral"] = fila["retraso_medio_min"] > umbral

    if orden == "volumen":
        candidatas = filas
        candidatas.sort(key=lambda f: -f["entregas"])
    else:
        clave = ("retraso_medio_min" if orden == "retraso" else "pct_retrasadas")
        candidatas = [f for f in filas
                      if f["entregas"] >= MINIMO_ENTREGAS_RANKING]
        candidatas.sort(key=lambda f: -f[clave])

    seleccion = candidatas[:max(top, 1)]
    return {
        "top": max(top, 1),
        "orden": orden,
        "criterios": list(ORDEN_RUTAS),
        "rutas": seleccion,
        "total": len(seleccion),
        "total_rutas": len(filas),
        "minimo_entregas": MINIMO_ENTREGAS_RANKING if orden != "volumen" else 0,
        "umbral_retraso_min": umbral,
        "periodo": periodo(bd),
        "lectura": _lectura_rutas(seleccion, filas, orden, umbral),
    }


def _lectura_rutas(seleccion: list[dict[str, Any]], todas: list[dict[str, Any]],
                   orden: str, umbral: int) -> str:
    if not seleccion:
        return "No hay entregas cargadas en el almacén analítico."

    primera = seleccion[0]
    criticas = [f for f in seleccion if f["sobre_umbral"]]

    if orden == "volumen":
        base = (f"La ruta que más mueve es {primera['codigo_ruta']}, con "
                f"{primera['entregas']:,} entregas.")
        if criticas:
            return (f"{base} {len(criticas)} de las {len(seleccion)} rutas de "
                    f"mayor volumen superan en promedio los {umbral} minutos "
                    f"de retraso ({', '.join(f['codigo_ruta'] for f in criticas)}). "
                    "Son las prioritarias: su impacto se multiplica por las "
                    "entregas que mueven.")
        cuantas = ("Ninguna de las {n} de mayor volumen supera"
                   if len(seleccion) > 1 else "No supera").format(
                       n=len(seleccion))
        return (f"{base} {cuantas} en promedio los {umbral} minutos: el "
                "retraso de la operación no viene del volumen, sino de rutas "
                "concretas con problemas propios.")

    if orden == "retraso":
        peor = primera["retraso_medio_min"]
        media = (sum(f["retraso_medio_min"] for f in todas) / len(todas)
                 if todas else 0)
        exceso = ((peor - media) / media * 100) if media else 0
        return (f"La ruta con mayor retraso es {primera['codigo_ruta']}: "
                f"{peor:.1f} minutos de media, un {exceso:.0f}% por encima "
                f"del promedio de la operación ({media:.1f} min). "
                f"{primera['pct_retrasadas']:.0f}% de sus "
                f"{primera['entregas']:,} entregas llegan tarde.")

    return (f"En {primera['codigo_ruta']} se retrasa el "
            f"{primera['pct_retrasadas']:.0f}% de las entregas "
            f"({primera['retrasadas']:,} de {primera['entregas']:,}). "
            "Es la proporción de fallo, no el tamaño del retraso: una ruta "
            "puede desviarse poco cada vez y aun así incumplir casi siempre.")


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


# ==========================================================================
# DESEMPEÑO DE LA FLOTILLA
# ==========================================================================
# Responde cuatro de las nueve preguntas del proyecto en una sola consulta,
# porque las cuatro se contestan mirando la misma tabla:
#
#     ¿Qué vehículos generan mayores costos?
#     ¿Qué vehículos consumen más combustible?
#     ¿Qué vehículos tienen más entregas?
#     ¿Qué vehículos presentan más retrasos?
#
# Los costos, los litros y el mantenimiento salen de `dim_vehiculo`, que es
# donde el ETL los dejó consolidados. Las entregas y los retrasos salen de
# `hecho_entrega`, porque la dimensión no los guarda. Son una lectura de 20
# documentos y una agregación: no hace falta traer nada a pandas.
CRITERIOS_FLOTILLA = ("costo", "combustible", "entregas", "retraso",
                      "rendimiento", "uso")


def desempeno_vehiculos(bd: Database, orden: str = "costo",
                        top: int = 20) -> dict[str, Any]:
    """Una fila por vehículo con todo lo que decide si conviene o no."""
    orden = (orden or "costo").strip().lower()
    if orden not in CRITERIOS_FLOTILLA:
        raise ReglaDeNegocio(
            f"Criterio '{orden}' no válido. Debe ser uno de "
            f"{list(CRITERIOS_FLOTILLA)}.")

    dimension = {d["_id"]: d for d in bd["dim_vehiculo"].find({})}
    if not dimension:
        raise ServicioNoDisponible(
            "`dim_vehiculo` está vacía. Ejecuta antes: python -m etl.run_etl")

    operacion = {
        f["_id"]: f for f in bd[COLECCION_HECHOS].aggregate([
            {"$match": FILTRO_CALIDAD},
            {"$group": {
                "_id": "$vehiculo_id",
                "entregas": {"$sum": "$numero_entregas"},
                "retrasadas": {"$sum": "$es_retraso"},
                "retraso_medio_min": {"$avg": "$retraso_min"},
            }},
        ])
    }

    umbral = settings.UMBRAL_RETRASO_MIN
    filas: list[dict[str, Any]] = []
    for identificador, vehiculo in dimension.items():
        hechos = operacion.get(identificador, {})
        entregas = int(hechos.get("entregas") or 0)
        retrasadas = int(hechos.get("retrasadas") or 0)
        km = float(vehiculo.get("km_recorridos") or 0)
        costo = float(vehiculo.get("costo_total_operacion") or 0)

        filas.append({
            "vehiculo_id": identificador,
            # Identificación legible primero; el identificador queda de apoyo
            "codigo_vehiculo": vehiculo.get("codigo_vehiculo"),
            "descripcion": " ".join(
                str(p) for p in (vehiculo.get("marca"), vehiculo.get("modelo"))
                if p),
            "placa": vehiculo.get("placa"),
            "anio": vehiculo.get("anio"),
            "tipo_vehiculo": vehiculo.get("tipo_vehiculo"),
            "estado_operativo": vehiculo.get("estado_operativo"),
            # Uso
            "viajes": int(vehiculo.get("n_viajes") or 0),
            "km_recorridos": round(km, 1),
            "entregas": entregas,
            # Costos
            "costo_total": round(costo, 2),
            "costo_combustible": round(
                float(vehiculo.get("costo_combustible") or 0), 2),
            "costo_mantenimiento": round(
                float(vehiculo.get("costo_mantenimiento") or 0), 2),
            "costo_por_km": round(
                float(vehiculo.get("costo_total_por_km") or 0), 2),
            "costo_por_entrega": (round(costo / entregas, 2)
                                  if entregas else None),
            # Combustible
            "litros": round(float(vehiculo.get("litros") or 0), 1),
            "cargas": int(vehiculo.get("n_cargas") or 0),
            "rendimiento_real_km_l": vehiculo.get("rendimiento_real_km_l"),
            "rendimiento_nominal_km_l": vehiculo.get("rendimiento_nominal_km_l"),
            "desviacion_rendimiento_pct": vehiculo.get(
                "desviacion_rendimiento_pct"),
            # Puntualidad
            "retrasadas": retrasadas,
            "pct_retrasadas": (round(100 * retrasadas / entregas, 1)
                               if entregas else None),
            "retraso_medio_min": (round(float(hechos["retraso_medio_min"]), 1)
                                  if hechos.get("retraso_medio_min") is not None
                                  else None),
            # Mantenimiento
            "mantenimientos": int(vehiculo.get("n_mantenimientos") or 0),
            "fecha_ultimo_mantenimiento": vehiculo.get(
                "fecha_ultimo_mantenimiento"),
            "en_mantenimiento": (vehiculo.get("estado_operativo")
                                 == settings.ESTADO_EN_MANTENIMIENTO),
        })

    claves = {
        "costo": lambda f: -f["costo_total"],
        "combustible": lambda f: -f["litros"],
        "entregas": lambda f: -f["entregas"],
        "retraso": lambda f: -(f["retraso_medio_min"] or -999),
        "rendimiento": lambda f: (f["rendimiento_real_km_l"] or 999),
        "uso": lambda f: -f["km_recorridos"],
    }
    filas.sort(key=claves[orden])
    seleccion = filas[:max(top, 1)]

    return {
        "orden": orden,
        "criterios": list(CRITERIOS_FLOTILLA),
        "vehiculos": seleccion,
        "total": len(seleccion),
        "flotilla": len(filas),
        "totales": _totales_flotilla(filas),
        "umbral_retraso_min": umbral,
        "periodo": periodo(bd),
        "lectura": _lectura_flotilla(seleccion, filas, orden, umbral),
    }


def _totales_flotilla(filas: list[dict[str, Any]]) -> dict[str, Any]:
    """Agregados de referencia: sin ellos, una cifra por unidad no se juzga."""
    n = len(filas) or 1
    rendimientos = [f["rendimiento_real_km_l"] for f in filas
                    if f["rendimiento_real_km_l"]]
    costo_total = sum(f["costo_total"] for f in filas)
    return {
        "costo_total": round(costo_total, 2),
        "costo_combustible": round(sum(f["costo_combustible"] for f in filas), 2),
        "costo_mantenimiento": round(
            sum(f["costo_mantenimiento"] for f in filas), 2),
        "litros": round(sum(f["litros"] for f in filas), 1),
        "km_recorridos": round(sum(f["km_recorridos"] for f in filas), 1),
        "entregas": sum(f["entregas"] for f in filas),
        "viajes": sum(f["viajes"] for f in filas),
        "costo_medio_por_vehiculo": round(costo_total / n, 2),
        "rendimiento_medio_km_l": (round(sum(rendimientos) / len(rendimientos), 2)
                                   if rendimientos else None),
        "en_mantenimiento": sum(1 for f in filas if f["en_mantenimiento"]),
    }


def _lectura_flotilla(seleccion: list[dict[str, Any]],
                      todas: list[dict[str, Any]], orden: str,
                      umbral: int) -> str:
    if not seleccion:
        return "No hay vehículos cargados en el almacén analítico."

    v = seleccion[0]
    nombre = f"{v['codigo_vehiculo']} ({v['descripcion']})"

    if orden == "costo":
        total = sum(f["costo_total"] for f in todas) or 1
        return (f"{nombre} es la unidad más cara de operar: "
                f"${v['costo_total']:,.0f} en el periodo, el "
                f"{100 * v['costo_total'] / total:.1f}% del gasto de toda la "
                f"flotilla. De ese importe, ${v['costo_combustible']:,.0f} son "
                f"combustible y ${v['costo_mantenimiento']:,.0f} "
                "mantenimiento. Conviene ver cuál de los dos manda antes de "
                "decidir qué hacer con ella.")

    if orden == "combustible":
        litros = sum(f["litros"] for f in todas) or 1
        return (f"{nombre} es la unidad que más combustible consume: "
                f"{v['litros']:,.0f} litros, el "
                f"{100 * v['litros'] / litros:.1f}% del total. Recorrió "
                f"{v['km_recorridos']:,.0f} km, así que su rendimiento real "
                f"es de {v['rendimiento_real_km_l']} km/l. Consumir mucho no "
                "es un problema si se recorre mucho: lo es cuando el "
                "rendimiento se aparta del de ficha.")

    if orden == "entregas":
        costo_entrega = (f"${v['costo_por_entrega']:,.2f}"
                         if v["costo_por_entrega"] is not None else "—")
        return (f"{nombre} es la unidad con más entregas: {v['entregas']:,} en "
                f"{v['viajes']:,} viajes. Su costo por entrega es de "
                f"{costo_entrega}, que es la cifra a comparar entre unidades: "
                "el costo total premia a las que trabajan poco.")

    if orden == "retraso":
        if v["retraso_medio_min"] is None:
            return f"{nombre} no tiene entregas medibles en el periodo."
        return (f"{nombre} es la unidad con peor puntualidad: "
                f"{v['retraso_medio_min']:.1f} minutos de retraso medio y un "
                f"{v['pct_retrasadas']:.0f}% de entregas fuera del umbral de "
                f"{umbral} minutos. El retraso rara vez es culpa del "
                "vehículo: conviene cruzarlo con las rutas que cubre y con "
                "sus incidentes antes de concluir nada.")

    if orden == "rendimiento":
        desviacion = v.get("desviacion_rendimiento_pct")
        cierre = (f" ({desviacion:+.1f}%)." if desviacion is not None else ".")
        return (f"{nombre} es la unidad con peor rendimiento: "
                f"{v['rendimiento_real_km_l']} km/l frente a los "
                f"{v['rendimiento_nominal_km_l']} km/l de ficha{cierre}"
                " Una desviación negativa sostenida suele avisar de un "
                "problema mecánico antes de que aparezca como avería.")

    return (f"{nombre} es la unidad más rodada: {v['km_recorridos']:,.0f} km "
            f"en {v['viajes']:,} viajes. El kilometraje marca el ritmo del "
            "desgaste y, con él, la frecuencia del mantenimiento.")


# ==========================================================================
# DESEMPEÑO DE LOS OPERADORES
# ==========================================================================
CRITERIOS_OPERADORES = ("entregas", "puntualidad", "retraso")


def desempeno_operadores(bd: Database, orden: str = "entregas",
                         top: int = 30) -> dict[str, Any]:
    """
    ¿Qué operadores realizan más entregas, y con qué puntualidad?

    Sale íntegro de `dim_operador`, que el ETL ya dejó con las entregas, el
    porcentaje a tiempo y el retraso medio de cada uno. Aquí solo se ordena
    y se interpreta.
    """
    orden = (orden or "entregas").strip().lower()
    if orden not in CRITERIOS_OPERADORES:
        raise ReglaDeNegocio(
            f"Criterio '{orden}' no válido. Debe ser uno de "
            f"{list(CRITERIOS_OPERADORES)}.")

    documentos = list(bd["dim_operador"].find({}))
    if not documentos:
        raise ServicioNoDisponible(
            "`dim_operador` está vacía. Ejecuta antes: python -m etl.run_etl")

    filas = [{
        "operador_id": d["_id"],
        "codigo_operador": d.get("codigo_operador"),
        "nombre": d.get("nombre_completo"),
        "estado": d.get("estado"),
        "viajes": int(d.get("viajes") or 0),
        "entregas": int(d.get("entregas_medibles") or 0),
        "entregas_por_viaje": d.get("entregas_por_viaje"),
        "a_tiempo": int(d.get("a_tiempo") or 0),
        "pct_a_tiempo": d.get("porcentaje_entregas_a_tiempo"),
        "retraso_medio_min": d.get("retraso_medio_min"),
    } for d in documentos]

    claves = {
        "entregas": lambda f: -f["entregas"],
        "puntualidad": lambda f: (f["pct_a_tiempo"]
                                  if f["pct_a_tiempo"] is not None else 999),
        "retraso": lambda f: -(f["retraso_medio_min"] or -999),
    }
    filas.sort(key=claves[orden])
    seleccion = filas[:max(top, 1)]

    medibles = [f for f in filas
                if f["entregas"] >= MINIMO_ENTREGAS_RANKING
                and f["pct_a_tiempo"] is not None]
    media = (sum(f["pct_a_tiempo"] for f in medibles) / len(medibles)
             if medibles else 0.0)

    return {
        "orden": orden,
        "criterios": list(CRITERIOS_OPERADORES),
        "operadores": seleccion,
        "total": len(seleccion),
        "plantilla": len(filas),
        "puntualidad_media_pct": round(media, 1),
        "umbral_retraso_min": settings.UMBRAL_RETRASO_MIN,
        "periodo": periodo(bd),
        "lectura": _lectura_operadores(seleccion, media, orden),
    }


def _lectura_operadores(seleccion: list[dict[str, Any]], media: float,
                        orden: str) -> str:
    if not seleccion:
        return "No hay operadores cargados en el almacén analítico."

    o = seleccion[0]
    puntual = (f"{o['pct_a_tiempo']:.0f}%" if o["pct_a_tiempo"] is not None
               else "—")

    if orden == "entregas":
        return (f"{o['nombre']} ({o['codigo_operador']}) es quien más entregas "
                f"realiza: {o['entregas']:,} en {o['viajes']:,} viajes, con "
                f"{puntual} a tiempo frente al {media:.0f}% de la plantilla. "
                "El volumen por sí solo no mide desempeño: hay que leerlo "
                "junto a la puntualidad.")

    if orden == "puntualidad":
        return (f"{o['nombre']} ({o['codigo_operador']}) tiene la puntualidad "
                f"más baja: {puntual} de entregas a tiempo frente al "
                f"{media:.0f}% de la plantilla, sobre {o['entregas']:,} "
                "entregas. Antes de atribuirlo a la persona conviene ver qué "
                "rutas cubre: el retraso suele venir del recorrido, no del "
                "volante.")

    retraso = (f"{o['retraso_medio_min']:.1f}"
               if o["retraso_medio_min"] is not None else "—")
    return (f"{o['nombre']} ({o['codigo_operador']}) acumula el mayor retraso "
            f"medio: {retraso} minutos sobre {o['entregas']:,} entregas.")


# ==========================================================================
# TENDENCIA
# ==========================================================================
def tendencia(bd: Database, agrupacion: str = "semana") -> dict[str, Any]:
    """
    Cómo evolucionan las entregas y el retraso a lo largo del periodo.

    Una cifra agregada no dice si la situación mejora o empeora, y esa es
    justo la pregunta de quien mira un panel. Se agrupa por semana porque
    el día introduce demasiado ruido —hay días sin operación— y el mes deja
    solo seis puntos en todo el histórico.

    La serie de retraso se calcula sobre el mismo conjunto que el resto de
    la analítica (`calidad_dato == "OK"`), así que la media semanal es
    comparable con el retraso medio del panel.
    """
    agrupacion = (agrupacion or "semana").strip().lower()
    if agrupacion not in ("semana", "mes"):
        raise ReglaDeNegocio(
            "Agrupación no válida. Debe ser 'semana' o 'mes'.")

    if agrupacion == "semana":
        identificador = {"$dateTrunc": {"date": "$fecha", "unit": "week",
                                        "startOfWeek": "monday"}}
    else:
        identificador = {"$dateTrunc": {"date": "$fecha", "unit": "month"}}

    filas = list(bd[COLECCION_HECHOS].aggregate([
        {"$match": FILTRO_CALIDAD},
        {"$group": {
            "_id": identificador,
            "entregas": {"$sum": "$numero_entregas"},
            "retrasadas": {"$sum": "$es_retraso"},
            "retraso_medio_min": {"$avg": "$retraso_min"},
        }},
        {"$sort": {"_id": 1}},
        {"$project": {
            "_id": 0,
            "inicio": "$_id",
            "entregas": 1,
            "retrasadas": 1,
            "retraso_medio_min": {"$round": ["$retraso_medio_min", 2]},
        }},
    ]))

    for fila in filas:
        fila["pct_retrasadas"] = (round(100 * fila["retrasadas"]
                                        / fila["entregas"], 1)
                                  if fila["entregas"] else 0.0)
        fila["etiqueta"] = _etiqueta_periodo(fila["inicio"], agrupacion)
        fila["inicio"] = fila["inicio"].date().isoformat()

    return {
        "agrupacion": agrupacion,
        "puntos": filas,
        "total": len(filas),
        "umbral_retraso_min": settings.UMBRAL_RETRASO_MIN,
        "periodo": periodo(bd),
        "lectura": _lectura_tendencia(filas, agrupacion),
    }


def _etiqueta_periodo(inicio, agrupacion: str) -> str:
    if agrupacion == "mes":
        return f"{MESES[inicio.month][:3].capitalize()} {inicio.year}"
    return f"{inicio.day:02d} {MESES[inicio.month][:3]}"


def _lectura_tendencia(filas: list[dict[str, Any]], agrupacion: str) -> str:
    """
    Compara el primer tercio del periodo contra el último.

    Comparar solo el primer punto con el último sería frágil: una semana
    atípica al principio o al final invertiría la conclusión. Los tercios
    absorben esa variación sin esconder la tendencia.
    """
    if len(filas) < 3:
        return ("Todavía no hay suficientes periodos para hablar de "
                "tendencia.")

    corte = max(len(filas) // 3, 1)
    inicio = filas[:corte]
    final = filas[-corte:]
    unidad = "semanas" if agrupacion == "semana" else "meses"

    def media(bloque, clave):
        valores = [f[clave] for f in bloque if f[clave] is not None]
        return sum(valores) / len(valores) if valores else 0.0

    retraso_inicial = media(inicio, "retraso_medio_min")
    retraso_final = media(final, "retraso_medio_min")
    entregas_inicial = media(inicio, "entregas")
    entregas_final = media(final, "entregas")

    cambio = retraso_final - retraso_inicial
    if abs(cambio) < 0.5:
        rumbo = (f"El retraso se mantiene estable en torno a "
                 f"{retraso_final:.1f} minutos")
    elif cambio > 0:
        rumbo = (f"El retraso ha empeorado: de {retraso_inicial:.1f} a "
                 f"{retraso_final:.1f} minutos de media (+{cambio:.1f})")
    else:
        rumbo = (f"El retraso ha mejorado: de {retraso_inicial:.1f} a "
                 f"{retraso_final:.1f} minutos de media ({cambio:.1f})")

    volumen = ""
    if entregas_inicial:
        variacion = 100 * (entregas_final - entregas_inicial) / entregas_inicial
        if abs(variacion) >= 5:
            direccion = "subido" if variacion > 0 else "bajado"
            volumen = (f" El volumen ha {direccion} un {abs(variacion):.0f}%, "
                       f"de {entregas_inicial:.0f} a {entregas_final:.0f} "
                       f"entregas por {unidad[:-1]}.")

    pico = max(filas, key=lambda f: f["retraso_medio_min"] or 0)
    return (f"{rumbo} comparando las primeras {corte} {unidad} con las "
            f"últimas {corte}.{volumen} El peor tramo fue "
            f"{pico['etiqueta']}, con {pico['retraso_medio_min']:.1f} "
            f"minutos y un {pico['pct_retrasadas']:.0f}% de entregas fuera "
            "de hora.")
