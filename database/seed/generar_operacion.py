"""
SIG-LOG — Sistema Integral de Gestión Logística
database/seed/generar_operacion.py

ACTIVIDAD PA-2 — Generador de la operación simulada (DATOS SIMULADOS)

Recorre el calendario del 1-feb al 31-jul de 2026 (lunes a sábado) y simula,
en una sola pasada causal, las cinco colecciones operativas:

    viajes · entregas · incidentes · mantenimientos · combustible

Por qué una sola pasada
-----------------------
El Anexo B.4 establece que el retraso depende de los incidentes y de los días
transcurridos desde el último mantenimiento; a su vez, el mantenimiento
depende del kilometraje acumulado por los viajes, y el consumo de combustible
depende de esos mismos kilómetros. Separar estas colecciones en actividades
distintas obligaría a recorrer el mismo estado varias veces y abriría la
puerta a incoherencias. Se generan juntas y se reconcilian en PA-3.

EL PUNTO CRÍTICO DEL PROYECTO
-----------------------------
Si el retraso fuera ruido aleatorio, el R² sería ≈0 y la evidencia de la
Unidad III se caería. El modelo de retraso implementa literalmente los ocho
factores del Anexo B.4, y el script reporta al final si la proporción de
entregas retrasadas cae en el rango objetivo de 25 %–30 %.

Uso
---
    python -m database.seed.generar_operacion --dry-run
    python -m database.seed.generar_operacion
    python -m database.seed.generar_operacion --limpiar
"""

from __future__ import annotations

import argparse
import random
import statistics
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from bson import ObjectId

from config import settings
from config.mongo_conexion import cerrar_cliente, obtener_bd, verificar_conexion
from database.seed import comun as C
from database.seed import parametros as P

COLECCIONES_PA2 = ("viajes", "entregas", "incidentes", "mantenimientos", "combustible")


# ==========================================================================
# MODELO DEL FENÓMENO A PREDECIR (Anexo B.4)
# ==========================================================================
def _en_hora_pico(momento: datetime) -> bool:
    return any(ini <= momento.hour < fin for ini, fin in P.FRANJAS_PICO)


def factor_base_ruta(ruta: dict, antiguedad_anios: int) -> float:
    """
    Condiciones típicas que el planificador ya incorporó en el tiempo
    estimado de esta ruta con este vehículo.

    Se calcula con la exposición real de la ruta a la hora pico (según sus
    horarios planificados), la antigüedad del vehículo asignado y un ciclo
    de mantenimiento a la mitad. Es la referencia contra la que se mide el
    retraso: el tiempo real por encima de estas condiciones es retraso; por
    debajo, adelanto.
    """
    salida = C.a_datetime(P.FECHA_INICIO, ruta["hora_salida_programada"])
    acumulado = 0.0
    en_pico = 0
    for parada in ruta["paradas"]:
        acumulado += parada["tiempo_estimado_min"]
        if _en_hora_pico(salida + timedelta(minutes=acumulado)):
            en_pico += 1
    proporcion_pico = en_pico / len(ruta["paradas"])

    base = statistics.mean(P.FACTOR_DIA_SEMANA.values())
    base *= 1.0 + proporcion_pico * (P.FACTOR_PICO_TIPICO - 1.0)
    base *= 1.0 + P.FACTOR_ANTIGUEDAD_POR_ANIO * antiguedad_anios
    base *= 1.0 + P.FACTOR_MANTENIMIENTO_POR_DIA * P.DIAS_DESDE_MTTO_TIPICO
    return base * P.FACTOR_CONDICIONES_TIPICAS


def factor_tiempo_real(
    rng: random.Random,
    momento_estimado: datetime,
    dia_semana: int,
    antiguedad_anios: int,
    dias_desde_mantenimiento: int,
    base_ruta: float,
) -> float:
    """
    Multiplicador que convierte el tiempo estimado de un tramo en tiempo real.

    Implementa los ocho factores del Anexo B.4. Cada término es una relación
    que el modelo supervisado deberá redescubrir a partir de los datos.
    El resultado se normaliza contra las condiciones típicas de la ruta.
    """
    factor = P.FACTOR_DIA_SEMANA.get(dia_semana, 1.0)

    if _en_hora_pico(momento_estimado):
        factor *= rng.uniform(*P.FACTOR_HORA_PICO)

    factor *= 1.0 + P.FACTOR_ANTIGUEDAD_POR_ANIO * antiguedad_anios

    dias = min(dias_desde_mantenimiento, P.DIAS_MANTENIMIENTO_SATURACION)
    factor *= 1.0 + P.FACTOR_MANTENIMIENTO_POR_DIA * dias

    # Ruido controlado: sin él, el R² saldría artificialmente perfecto (≈1.0)
    factor *= rng.uniform(1.0 - P.RUIDO_RELATIVO, 1.0 + P.RUIDO_RELATIVO)

    return factor / base_ruta


def severidad_por_duracion(minutos: int) -> str:
    """
    Escala de severidad derivada de la duración.
    ⚠ La escala de severidad sigue siendo REGLA PENDIENTE de definición;
    esta derivación es una propuesta, no una regla confirmada.
    """
    if minutos < 30:
        return "BAJA"
    if minutos <= 90:
        return "MEDIA"
    return "ALTA"


# ==========================================================================
# ESTADO POR VEHÍCULO
# ==========================================================================
def _estado_inicial_vehiculos(rng: random.Random, vehiculos: list[dict]) -> dict:
    """Odómetro, mantenimiento y combustible al arrancar el periodo simulado."""
    estado: dict[Any, dict[str, Any]] = {}
    for v in vehiculos:
        antiguedad = max(P.FECHA_INICIO.year - v["anio"], 0)
        nominal = v["rendimiento_nominal_km_l"]
        # Rendimiento real: varía ±15 % sobre el nominal y se degrada con la edad
        real = nominal * (1 - 0.01 * antiguedad) * rng.uniform(
            1 - P.VARIACION_RENDIMIENTO_REAL, 1 + P.VARIACION_RENDIMIENTO_REAL
        )
        estado[v["_id"]] = {
            "vehiculo": v,
            "antiguedad_anios": antiguedad,
            "rendimiento_real": max(real, 1.5),
            "odometro": float(v["odometro_actual_km"]),
            "km_desde_mtto": rng.uniform(0, P.MANTENIMIENTO_KM * 0.6),
            "fecha_ultimo_mtto": P.FECHA_INICIO - timedelta(days=rng.randint(0, 29)),
            "km_desde_carga": 0.0,
            "litros_desde_carga": 0.0,
            "odometro_carga_anterior": float(v["odometro_actual_km"]),
            "no_disponible_hasta": None,
            "consecutivo_mtto": 0,
            "consecutivo_carga": 0,
        }
    return estado


def precio_combustible(rng: random.Random, dia: date) -> float:
    """Precio con tendencia creciente a lo largo del periodo (Anexo B.5)."""
    total = (P.FECHA_FIN - P.FECHA_INICIO).days
    avance = (dia - P.FECHA_INICIO).days / total if total else 0.0
    piso, techo = P.PRECIO_POR_LITRO
    return round(piso + (techo - piso) * avance + rng.gauss(0, 0.25), 2)


# ==========================================================================
# GENERACIÓN DE UN VIAJE Y SUS ENTREGAS
# ==========================================================================
def _generar_incidente(
    rng: random.Random, viaje: dict, ruta: dict, dia: date, n_paradas: int,
) -> dict[str, Any]:
    """Un incidente ubicado en una parada concreta del viaje."""
    tipo = C.elegir_ponderado(rng, P.INCIDENTES_FRECUENCIA)
    duracion = rng.randint(*P.INCIDENTES_DURACION_MIN[tipo])
    inicio = viaje["hora_salida_programada"] + timedelta(
        minutes=rng.randint(10, max(20, int(ruta["tiempo_estimado_total_min"])))
    )
    return {
        "_id": ObjectId(),
        "folio_incidente": None,          # se asigna al final, en orden cronológico
        "tipo": tipo,
        "severidad": severidad_por_duracion(duracion),
        "fecha_hora_inicio": inicio,
        "fecha_hora_fin": inicio + timedelta(minutes=duracion),
        "duracion_min": duracion,
        "viaje_id": viaje["_id"],
        "ruta_id": ruta["_id"],
        "entregas_afectadas": [],         # se llena al recorrer las paradas
        "ubicacion": {"zona": ruta["zona"], "referencia": ruta["nombre"]},
        "descripcion": rng.choice(P.DESCRIPCIONES_INCIDENTE[tipo]),
        "tiempo_perdido_estimado_min": duracion,
        "fuente": "SIMULADO",
        "_parada_afectada": rng.randint(1, n_paradas),   # campo temporal
        **C.campos_comunes(),
    }


def generar_viaje(
    rng: random.Random,
    dia: date,
    ruta: dict,
    estado_veh: dict,
    operador: dict,
    clientes_por_id: dict,
    consecutivos: dict[str, int],
) -> tuple[dict, list[dict], list[dict]]:
    """Genera un viaje con sus entregas y, si aplica, su incidente."""
    vehiculo = estado_veh["vehiculo"]
    salida_prog = C.a_datetime(dia, ruta["hora_salida_programada"])
    cancelado = rng.random() < P.PROPORCION_VIAJES_CANCELADOS

    consecutivos["viaje"] += 1
    viaje: dict[str, Any] = {
        "_id": ObjectId(),
        "folio_viaje": C.folio_fechado("VJE", dia, consecutivos["viaje"]),
        "fecha": C.a_datetime(dia, "00:00"),
        "ruta_id": ruta["_id"],
        "vehiculo_id": vehiculo["_id"],
        "operador_id": operador["_id"],
        "hora_salida_programada": salida_prog,
        "estatus": "CANCELADO" if cancelado else "FINALIZADO",
        "total_entregas_programadas": ruta["numero_paradas"],
        **C.campos_comunes(),
    }

    # ---------------- Viaje cancelado: no hay operación real ----------------
    if cancelado:
        viaje.update({
            "hora_salida_real": None, "hora_regreso_real": None,
            "odometro_inicial_km": round(estado_veh["odometro"], 1),
            "odometro_final_km": round(estado_veh["odometro"], 1),
            "km_recorridos": 0.0, "total_entregas_completadas": 0,
            "total_incidentes": 0, "duracion_real_min": None,
            "retraso_salida_min": None,
        })
        entregas = [
            _entrega_cancelada(rng, viaje, ruta, parada, vehiculo, operador,
                               clientes_por_id, dia, consecutivos)
            for parada in ruta["paradas"]
        ]
        return viaje, entregas, []

    # ---------------- Retraso de salida: se propaga íntegro -----------------
    retraso_salida = min(
        round(rng.gammavariate(P.RETRASO_SALIDA_FORMA, P.RETRASO_SALIDA_ESCALA)),
        P.RETRASO_SALIDA_MAX_MIN,
    )
    salida_real = salida_prog + timedelta(minutes=retraso_salida)

    # ---------------- Incidente del viaje (Anexo B.6) -----------------------
    incidentes: list[dict] = []
    if rng.random() < P.PROPORCION_VIAJES_CON_INCIDENTE:
        incidentes.append(
            _generar_incidente(rng, viaje, ruta, dia, ruta["numero_paradas"])
        )

    dias_desde_mtto = (dia - estado_veh["fecha_ultimo_mtto"]).days
    base_ruta = factor_base_ruta(ruta, estado_veh["antiguedad_anios"])
    entregas: list[dict] = []

    acum_estimado = 0.0        # minutos planificados desde la salida
    retraso_acum = float(retraso_salida)
    completadas = 0

    for parada in ruta["paradas"]:
        acum_estimado += parada["tiempo_estimado_min"]
        hora_estimada = salida_prog + timedelta(minutes=acum_estimado)

        factor = factor_tiempo_real(
            rng, hora_estimada, dia.weekday(),
            estado_veh["antiguedad_anios"], dias_desde_mtto, base_ruta,
        )
        # El retraso del tramo se ACUMULA a lo largo de la ruta (Anexo B.4)
        retraso_acum += parada["tiempo_estimado_min"] * (factor - 1.0)

        # El incidente suma su duración en su parada y persiste en las siguientes
        estatus = "ENTREGADA"
        causa = None
        ids_incidente: list[ObjectId] = []
        for inc in incidentes:
            if parada["orden"] == inc["_parada_afectada"]:
                retraso_acum += inc["duracion_min"]
            if parada["orden"] >= inc["_parada_afectada"]:
                ids_incidente.append(inc["_id"])
                causa = inc["tipo"]
                if inc["tipo"] == "CLIENTE_AUSENTE" and parada["orden"] == inc["_parada_afectada"]:
                    estatus = "NO_ENTREGADA"

        hora_real = hora_estimada + timedelta(minutes=retraso_acum)
        tiempo_real = round(parada["tiempo_estimado_min"] * factor, 1)
        retraso_min = round(retraso_acum, 1)

        # Retraso sin incidente registrado: se atribuye al tráfico, que es la
        # causa más frecuente del catálogo RNP-12 (Anexo B.6, 55%).
        if causa is None and retraso_min > P.UMBRAL_RETRASO_MIN:
            causa = "TRAFICO"

        cliente = clientes_por_id[parada["cliente_id"]]
        consecutivos["entrega"] += 1
        entrega = {
            "_id": ObjectId(),
            "folio_entrega": C.folio_fechado("ENT", dia, consecutivos["entrega"], 5),
            "viaje_id": viaje["_id"],
            "ruta_id": ruta["_id"],
            "cliente_id": cliente["_id"],
            "nombre_cliente": cliente["nombre"],
            "vehiculo_id": vehiculo["_id"],
            "placa": vehiculo["placa"],
            "operador_id": operador["_id"],
            "nombre_operador": operador["nombre_completo"],
            "orden_parada": parada["orden"],
            "fecha": C.a_datetime(dia, "00:00"),
            "hora_estimada_llegada": hora_estimada,
            "hora_real_llegada": hora_real,
            "hora_estimada_recalculada": None,
            "tiempo_estimado_min": parada["tiempo_estimado_min"],
            "tiempo_real_min": tiempo_real,
            "retraso_min": retraso_min,
            "es_retraso": 1 if retraso_min > P.UMBRAL_RETRASO_MIN else 0,
            "distancia_km": parada["distancia_desde_anterior_km"],
            "estatus": estatus,
            "historial_estatus": [
                {"estatus": "PROGRAMADA", "fecha_hora": viaje["fecha"]},
                {"estatus": "EN_RUTA", "fecha_hora": salida_real},
                {"estatus": estatus, "fecha_hora": hora_real},
            ],
            "incidentes_ids": ids_incidente,
            "causa_retraso": causa,
            "observaciones": (
                rng.choice(P.OBSERVACIONES_LIBRES)
                if rng.random() < P.PROPORCION_CON_OBSERVACIONES else None
            ),
            # dia_semana, franja_horaria y es_fin_semana NO se generan aquí:
            # son enriquecimiento del ETL (PA-6, evidencia de la Unidad II).
            **C.campos_comunes(),
        }

        # Defecto de calidad deliberado: captura de campo omitida
        if rng.random() < P.PROPORCION_SIN_HORA_REAL:
            entrega.update({
                "hora_real_llegada": None, "tiempo_real_min": None,
                "retraso_min": None, "es_retraso": None, "causa_retraso": None,
            })

        for inc in incidentes:
            if parada["orden"] >= inc["_parada_afectada"]:
                inc["entregas_afectadas"].append(entrega["_id"])

        entregas.append(entrega)
        if estatus == "ENTREGADA":
            completadas += 1

    # ---------------- Cierre del viaje --------------------------------------
    km = round(
        ruta["distancia_total_km"] * P.FACTOR_RETORNO_KM
        * rng.uniform(1 - P.VARIACION_KM_VIAJE, 1 + P.VARIACION_KM_VIAJE), 1
    )
    duracion_real = acum_estimado + retraso_acum
    odometro_inicial = estado_veh["odometro"]

    viaje.update({
        "hora_salida_real": salida_real,
        "hora_regreso_real": salida_prog + timedelta(minutes=duracion_real + 25),
        "odometro_inicial_km": round(odometro_inicial, 1),
        "odometro_final_km": round(odometro_inicial + km, 1),
        "km_recorridos": km,
        "total_entregas_completadas": completadas,
        "total_incidentes": len(incidentes),
        "duracion_real_min": round(duracion_real, 1),
        "retraso_salida_min": retraso_salida,
    })
    return viaje, entregas, incidentes


def _entrega_cancelada(rng, viaje, ruta, parada, vehiculo, operador,
                       clientes_por_id, dia, consecutivos) -> dict:
    """Entrega de un viaje cancelado: sin hora real ni retraso."""
    cliente = clientes_por_id[parada["cliente_id"]]
    consecutivos["entrega"] += 1
    hora_estimada = C.a_datetime(dia, ruta["hora_salida_programada"]) + timedelta(
        minutes=sum(p["tiempo_estimado_min"] for p in ruta["paradas"]
                    if p["orden"] <= parada["orden"])
    )
    return {
        "_id": ObjectId(),
        "folio_entrega": C.folio_fechado("ENT", dia, consecutivos["entrega"], 5),
        "viaje_id": viaje["_id"], "ruta_id": ruta["_id"],
        "cliente_id": cliente["_id"], "nombre_cliente": cliente["nombre"],
        "vehiculo_id": vehiculo["_id"], "placa": vehiculo["placa"],
        "operador_id": operador["_id"], "nombre_operador": operador["nombre_completo"],
        "orden_parada": parada["orden"], "fecha": C.a_datetime(dia, "00:00"),
        "hora_estimada_llegada": hora_estimada, "hora_real_llegada": None,
        "hora_estimada_recalculada": None,
        "tiempo_estimado_min": parada["tiempo_estimado_min"],
        "tiempo_real_min": None, "retraso_min": None, "es_retraso": None,
        "distancia_km": parada["distancia_desde_anterior_km"],
        "estatus": "CANCELADA",
        "historial_estatus": [
            {"estatus": "PROGRAMADA", "fecha_hora": viaje["fecha"]},
            {"estatus": "CANCELADA", "fecha_hora": viaje["fecha"]},
        ],
        "incidentes_ids": [], "causa_retraso": None, "observaciones": None,
        **C.campos_comunes(),
    }


# ==========================================================================
# MANTENIMIENTO Y COMBUSTIBLE
# ==========================================================================
def _crear_mantenimiento(rng, estado, dia: date, consecutivos: dict) -> dict:
    """RNP-04 / Anexo B.5: cada 30 días u 8,000 km, lo primero que ocurra."""
    v = estado["vehiculo"]
    estado["consecutivo_mtto"] += 1
    consecutivos["mtto"] += 1

    # ⚠ PREVENTIVO / CORRECTIVO sigue siendo REGLA PENDIENTE (RNP-05).
    tipo = "PREVENTIVO" if rng.random() < P.PROPORCION_PREVENTIVO else "CORRECTIVO"
    rango = (P.COSTO_MANTENIMIENTO_PREVENTIVO if tipo == "PREVENTIVO"
             else P.COSTO_MANTENIMIENTO_CORRECTIVO)
    duracion = rng.randint(*P.DURACION_MANTENIMIENTO_DIAS)
    vencido = rng.random() < P.PROPORCION_MANTENIMIENTO_VENCIDO

    return {
        "_id": ObjectId(),
        "folio_mantenimiento": C.folio_fechado("MTO", dia, consecutivos["mtto"]),
        "vehiculo_id": v["_id"],
        "tipo": tipo,
        "fecha_programada": C.a_datetime(dia, "08:00"),
        "fecha_realizada": None if vencido else C.a_datetime(dia, "08:00"),
        "odometro_km": round(estado["odometro"], 1),
        "descripcion": (
            "Servicio preventivo programado: aceite, filtros y revisión general"
            if tipo == "PREVENTIVO"
            else "Servicio correctivo por falla detectada en operación"
        ),
        "costo": round(rng.uniform(*rango), 2),
        "duracion_dias": duracion,
        "estatus": "VENCIDO" if vencido else "REALIZADO",
        "proximo_mantenimiento_fecha": C.a_datetime(
            dia + timedelta(days=P.MANTENIMIENTO_DIAS), "08:00"
        ),
        **C.campos_comunes(),
    }


def _crear_carga(rng, estado, dia: date, viaje_id, consecutivos: dict) -> dict:
    """Carga de combustible por reposición del consumo acumulado."""
    v = estado["vehiculo"]
    consecutivos["carga"] += 1
    litros = round(estado["litros_desde_carga"], 2)
    km = round(estado["km_desde_carga"], 1)
    precio = precio_combustible(rng, dia)

    return {
        "_id": ObjectId(),
        "folio_carga": C.folio_fechado("CMB", dia, consecutivos["carga"]),
        "vehiculo_id": v["_id"],
        "viaje_id": viaje_id,
        "fecha": C.a_datetime(dia, "18:00"),
        "litros": litros,
        "precio_por_litro": precio,
        "costo_total": round(litros * precio, 2),
        "odometro_km": round(estado["odometro"], 1),
        "km_recorridos_desde_carga_anterior": km,
        "rendimiento_km_l": round(km / litros, 2) if litros else None,
        "tipo_combustible": v.get("tipo_combustible", "DIESEL"),
        "estacion": rng.choice(P.ESTACIONES_SERVICIO),
        **C.campos_comunes(),
    }


# ==========================================================================
# PASADA PRINCIPAL SOBRE EL CALENDARIO
# ==========================================================================
def generar_operacion(rng: random.Random, catalogos: dict) -> dict[str, list[dict]]:
    clientes_por_id = {c["_id"]: c for c in catalogos["clientes"]}
    rutas = sorted(catalogos["rutas"], key=lambda r: r["codigo_ruta"])
    operadores = catalogos["operadores"]
    estado_veh = _estado_inicial_vehiculos(rng, catalogos["vehiculos"])

    viajes: list[dict] = []
    entregas: list[dict] = []
    incidentes: list[dict] = []
    mantenimientos: list[dict] = []
    cargas: list[dict] = []
    consecutivos = {"viaje": 0, "entrega": 0, "mtto": 0, "carga": 0}

    for dia in C.dias_de_operacion(P.FECHA_INICIO, P.FECHA_FIN):
        consecutivos["viaje"] = 0
        consecutivos["entrega"] = 0
        consecutivos["mtto"] = 0
        consecutivos["carga"] = 0

        # RNP-03 opción (b): los operadores rotan. 24 disponibles, 20 rutas.
        turno = rng.sample(operadores, len(rutas))

        for ruta, operador in zip(rutas, turno):
            estado = estado_veh[ruta["vehiculo_asignado_id"]]

            # El vehículo en taller no sale a ruta ese día
            if estado["no_disponible_hasta"] and dia <= estado["no_disponible_hasta"]:
                continue

            viaje, ents, incs = generar_viaje(
                rng, dia, ruta, estado, operador, clientes_por_id, consecutivos
            )
            viajes.append(viaje)
            entregas.extend(ents)
            incidentes.extend(incs)

            km = viaje["km_recorridos"]
            estado["odometro"] += km
            estado["km_desde_mtto"] += km
            estado["km_desde_carga"] += km
            estado["litros_desde_carga"] += km / estado["rendimiento_real"]

            # ---- Combustible: reposición del consumo acumulado -------------
            umbral = P.CAPACIDAD_TANQUE_L[estado["vehiculo"]["tipo_vehiculo"]] * P.FRACCION_TANQUE_RECARGA
            if estado["litros_desde_carga"] >= umbral:
                cargas.append(_crear_carga(rng, estado, dia, viaje["_id"], consecutivos))
                estado["km_desde_carga"] = 0.0
                estado["litros_desde_carga"] = 0.0
                estado["odometro_carga_anterior"] = estado["odometro"]

            # ---- Mantenimiento: 30 días u 8,000 km, lo primero -------------
            por_dias = (dia - estado["fecha_ultimo_mtto"]).days >= P.MANTENIMIENTO_DIAS
            por_km = estado["km_desde_mtto"] >= P.MANTENIMIENTO_KM
            if por_dias or por_km:
                mtto = _crear_mantenimiento(rng, estado, dia, consecutivos)
                mantenimientos.append(mtto)
                estado["fecha_ultimo_mtto"] = dia
                estado["km_desde_mtto"] = 0.0
                if mtto["estatus"] == "REALIZADO":
                    estado["no_disponible_hasta"] = dia + timedelta(days=mtto["duracion_dias"])

    _folios_incidentes(incidentes)
    _inyectar_duplicados(rng, entregas)

    for inc in incidentes:
        inc.pop("_parada_afectada", None)

    return {
        "viajes": viajes, "entregas": entregas, "incidentes": incidentes,
        "mantenimientos": mantenimientos, "combustible": cargas,
    }


def _folios_incidentes(incidentes: list[dict]) -> None:
    """Folios consecutivos por día, asignados en orden cronológico."""
    incidentes.sort(key=lambda i: i["fecha_hora_inicio"])
    por_dia: dict[date, int] = {}
    for inc in incidentes:
        dia = inc["fecha_hora_inicio"].date()
        por_dia[dia] = por_dia.get(dia, 0) + 1
        inc["folio_incidente"] = C.folio_fechado("INC", dia, por_dia[dia])


def _inyectar_duplicados(rng: random.Random, entregas: list[dict]) -> None:
    """
    Doble captura del mismo evento: misma entrega, folio e _id distintos.

    Defecto deliberado. Sin duplicados, la limpieza de PA-5 no tendría un
    caso real que resolver y la Unidad II quedaría sin evidencia.
    """
    candidatas = [e for e in entregas if e["estatus"] == "ENTREGADA"]
    cuantas = int(len(candidatas) * P.PROPORCION_ENTREGAS_DUPLICADAS)
    for original in rng.sample(candidatas, cuantas):
        copia = dict(original)
        copia["_id"] = ObjectId()
        copia["folio_entrega"] = original["folio_entrega"] + "-D"
        copia["historial_estatus"] = list(original["historial_estatus"])
        entregas.append(copia)


# ==========================================================================
# VALIDACIÓN Y CALIBRACIÓN
# ==========================================================================
def validar(datos: dict, catalogos: dict) -> list[tuple[str, bool, str]]:
    viajes, entregas = datos["viajes"], datos["entregas"]
    incidentes, mttos, cargas = datos["incidentes"], datos["mantenimientos"], datos["combustible"]

    ids_viaje = {v["_id"] for v in viajes}
    ids_ruta = {r["_id"] for r in catalogos["rutas"]}
    ids_cli = {c["_id"] for c in catalogos["clientes"]}
    ids_veh = {v["_id"] for v in catalogos["vehiculos"]}
    ids_ope = {o["_id"] for o in catalogos["operadores"]}

    con_retraso = [e for e in entregas if e["retraso_min"] is not None]
    retrasadas = sum(1 for e in con_retraso if e["es_retraso"] == 1)
    proporcion = retrasadas / len(con_retraso) if con_retraso else 0
    piso, techo = P.PROPORCION_RETRASOS_OBJETIVO

    todos = viajes + entregas + incidentes + mttos + cargas
    folios_ent = [e["folio_entrega"] for e in entregas]

    return [
        ("Viajes generados (≈3,100)", 2700 <= len(viajes) <= 3100, f"{len(viajes)}"),
        ("Entregas generadas (≈15,500)", 13000 <= len(entregas) <= 17500, f"{len(entregas)}"),
        ("Incidentes generados (≈370)", 250 <= len(incidentes) <= 500, f"{len(incidentes)}"),
        ("Mantenimientos generados (≈120)", 90 <= len(mttos) <= 220, f"{len(mttos)}"),
        ("Cargas de combustible (≈1,500)", 1100 <= len(cargas) <= 2000, f"{len(cargas)}"),
        ("*** Proporción de retrasos en 25 %–30 %",
         piso <= proporcion <= techo, f"{proporcion:.1%} ({retrasadas}/{len(con_retraso)})"),
        ("Folios de viaje únicos",
         len({v["folio_viaje"] for v in viajes}) == len(viajes), ""),
        ("Folios de entrega únicos",
         len(set(folios_ent)) == len(folios_ent), ""),
        ("Folios de incidente únicos",
         len({i["folio_incidente"] for i in incidentes}) == len(incidentes), ""),
        ("Folios de carga únicos",
         len({c["folio_carga"] for c in cargas}) == len(cargas), ""),
        ("Folios de mantenimiento únicos",
         len({m["folio_mantenimiento"] for m in mttos}) == len(mttos), ""),
        ("Toda entrega apunta a un viaje existente",
         all(e["viaje_id"] in ids_viaje for e in entregas), ""),
        ("Toda entrega apunta a ruta, cliente, vehículo y operador válidos",
         all(e["ruta_id"] in ids_ruta and e["cliente_id"] in ids_cli
             and e["vehiculo_id"] in ids_veh and e["operador_id"] in ids_ope
             for e in entregas), ""),
        ("Todo incidente apunta a un viaje existente",
         all(i["viaje_id"] in ids_viaje for i in incidentes), ""),
        ("Estatus de entrega dentro del catálogo RNP-08",
         all(e["estatus"] in settings.CATALOGO_ESTATUS_ENTREGA for e in entregas), ""),
        ("Tipos de incidente dentro del catálogo RNP-12",
         all(i["tipo"] in settings.CATALOGO_TIPOS_INCIDENTE for i in incidentes), ""),
        ("Mínimo de 1,000 registros para regresión (§16.2)",
         len(con_retraso) >= 1000, f"{len(con_retraso)} utilizables"),
        ("Mínimo de 300 registros por clase para clasificación (§16.2)",
         min(retrasadas, len(con_retraso) - retrasadas) >= 300,
         f"retrasadas {retrasadas} · a tiempo {len(con_retraso) - retrasadas}"),
        ("100 % de documentos marcados como SIMULADO",
         all(d["origen_dato"] == "SIMULADO" for d in todos), f"{len(todos)} documentos"),
    ]


def imprimir_resumen(datos: dict) -> None:
    entregas = datos["entregas"]
    con_retraso = [e["retraso_min"] for e in entregas if e["retraso_min"] is not None]

    C.encabezado("RESUMEN DE LA OPERACIÓN SIMULADA")
    for nombre in COLECCIONES_PA2:
        print(f"  {nombre:<18}{len(datos[nombre]):>7} documentos")

    print(f"\n  DISTRIBUCIÓN DEL RETRASO (minutos)  —  variable objetivo")
    print(f"      mínimo ......... {min(con_retraso):.1f}")
    print(f"      media .......... {statistics.mean(con_retraso):.1f}")
    print(f"      mediana ........ {statistics.median(con_retraso):.1f}")
    print(f"      desv. estándar . {statistics.pstdev(con_retraso):.1f}")
    print(f"      máximo ......... {max(con_retraso):.1f}")

    retrasadas = sum(1 for r in con_retraso if r > P.UMBRAL_RETRASO_MIN)
    print(f"\n      Umbral RNP-01 .. > {P.UMBRAL_RETRASO_MIN} min")
    print(f"      es_retraso = 1 . {retrasadas} ({retrasadas/len(con_retraso):.1%})")
    print(f"      es_retraso = 0 . {len(con_retraso)-retrasadas} "
          f"({1 - retrasadas/len(con_retraso):.1%})")

    print("\n  ESTATUS DE ENTREGA")
    for estatus in settings.CATALOGO_ESTATUS_ENTREGA:
        n = sum(1 for e in entregas if e["estatus"] == estatus)
        if n:
            print(f"      {estatus:<16}{n:>7}")

    print("\n  CAUSAS DE RETRASO (base del análisis de Pareto, pregunta 6)")
    causas: dict[str, int] = {}
    for e in entregas:
        if e.get("causa_retraso"):
            causas[e["causa_retraso"]] = causas.get(e["causa_retraso"], 0) + 1
    for causa, n in sorted(causas.items(), key=lambda x: -x[1]):
        print(f"      {causa:<18}{n:>7}")

    print("\n  DEFECTOS DE CALIDAD DELIBERADOS (insumo de PA-5, Unidad II)")
    nulos = sum(1 for e in entregas if e["hora_real_llegada"] is None
                and e["estatus"] != "CANCELADA")
    dup = sum(1 for e in entregas if e["folio_entrega"].endswith("-D"))
    obs = sum(1 for e in entregas if e.get("observaciones"))
    print(f"      Entregas sin hora real ....... {nulos}")
    print(f"      Entregas duplicadas .......... {dup}")
    print(f"      Con texto libre (no estruct.). {obs}")

    mttos = datos["mantenimientos"]
    print("\n  MANTENIMIENTOS")
    for estatus in ("REALIZADO", "VENCIDO", "PROGRAMADO"):
        n = sum(1 for m in mttos if m["estatus"] == estatus)
        if n:
            print(f"      {estatus:<16}{n:>7}")

    cargas = datos["combustible"]
    if cargas:
        rend = [c["rendimiento_km_l"] for c in cargas if c["rendimiento_km_l"]]
        costo = sum(c["costo_total"] for c in cargas)
        print("\n  COMBUSTIBLE")
        print(f"      Rendimiento medio ...... {statistics.mean(rend):.2f} km/l")
        print(f"      Costo total del periodo. {costo:,.2f}")


def imprimir_validaciones(resultados) -> bool:
    C.encabezado("VALIDACIONES DE COHERENCIA")
    for nombre, ok, detalle in resultados:
        print(f"  {'[OK]   ' if ok else '[FALLA]'} {nombre:<52}{detalle}")
    fallos = sum(1 for _, ok, _ in resultados if not ok)
    print(C.SUBLINEA)
    print(f"  {len(resultados) - fallos}/{len(resultados)} validaciones correctas")
    return fallos == 0


# ==========================================================================
# CARGA
# ==========================================================================
def leer_catalogos(bd) -> dict[str, list[dict]]:
    catalogos = {c: list(bd[c].find({})) for c in settings.COLECCIONES_CATALOGO}
    faltantes = [c for c, docs in catalogos.items() if not docs]
    if faltantes:
        raise RuntimeError(
            "Colecciones de catálogo vacías: " + ", ".join(faltantes)
            + ". Ejecuta primero PA-1: python -m database.seed.generar_catalogos"
        )
    return catalogos


def cargar(bd, datos: dict, limpiar: bool) -> None:
    if limpiar:
        C.encabezado("LIMPIEZA PREVIA")
        for nombre in COLECCIONES_PA2:
            print(f"  {nombre:<18}{bd[nombre].delete_many({}).deleted_count} eliminados")

    C.encabezado("CARGA EN MONGODB ATLAS")
    for nombre in COLECCIONES_PA2:
        documentos = datos[nombre]
        existentes = bd[nombre].count_documents({})
        if existentes and not limpiar:
            print(f"  {nombre:<18}OMITIDA — ya contiene {existentes} documentos. "
                  f"Usa --limpiar para regenerar.")
            continue
        insertados = 0
        for i in range(0, len(documentos), 1000):
            insertados += len(
                bd[nombre].insert_many(documentos[i:i + 1000], ordered=False).inserted_ids
            )
            print(f"  {nombre:<18}{insertados}/{len(documentos)}...", end="\r")
        print(f"  {nombre:<18}{insertados} documentos insertados" + " " * 20)


# ==========================================================================
# PUNTO DE ENTRADA
# ==========================================================================
def main() -> int:
    parser = argparse.ArgumentParser(
        description="PA-2 — Genera la operación simulada de SIG-LOG.",
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Genera y valida en memoria, sin escribir en Atlas.")
    parser.add_argument("--limpiar", action="store_true",
                        help="Borra viajes, entregas, incidentes, mantenimientos y combustible.")
    parser.add_argument("--semilla", type=int, default=P.SEMILLA)
    args = parser.parse_args()

    C.aviso_datos_simulados()

    if not verificar_conexion(verbose=True)["exito"]:
        return 1

    try:
        bd = obtener_bd()
        C.encabezado("LECTURA DE CATÁLOGOS (PA-1)")
        catalogos = leer_catalogos(bd)
        for nombre, docs in catalogos.items():
            print(f"  {nombre:<18}{len(docs):>7} documentos leídos")

        C.encabezado("SIMULACIÓN DEL CALENDARIO OPERATIVO")
        dias = C.dias_de_operacion(P.FECHA_INICIO, P.FECHA_FIN)
        print(f"  Periodo ......... {P.FECHA_INICIO} a {P.FECHA_FIN}")
        print(f"  Días operados ... {len(dias)} (lunes a sábado)")
        print(f"  Rutas por día ... {len(catalogos['rutas'])}")
        print("  Simulando...")

        datos = generar_operacion(C.crear_rng(args.semilla), catalogos)

        imprimir_resumen(datos)
        if not imprimir_validaciones(validar(datos, catalogos)):
            print("\n  Hay validaciones en falla. No se escribe nada en Atlas.")
            print("  Si falla la proporción de retrasos, ajusta los factores del")
            print("  Anexo B.4 en database/seed/parametros.py y vuelve a ejecutar.")
            return 1

        if args.dry_run:
            print("\n  --dry-run activo: no se escribió nada en MongoDB.")
            return 0

        cargar(bd, datos, args.limpiar)
        print()
        print(C.LINEA)
        print("  PA-2 TERMINADA. Siguiente actividad: PA-3 (reconciliación).")
        print(C.LINEA)
        return 0

    except RuntimeError as exc:
        print(f"\n  {exc}")
        return 1
    finally:
        cerrar_cliente()


if __name__ == "__main__":
    sys.exit(main())
