"""
SIG-LOG — Sistema Integral de Gestión Logística
database/seed/generar_pendientes.py

ACTIVIDAD PA-2b — OPERACIÓN ABIERTA DEL DÍA + PREDICCIÓN DE RIESGO EN LOTE

Por qué existe este módulo
--------------------------
PA-2 simula el histórico CERRADO (1-feb a 31-jul de 2026). Al terminar, las
14 851 entregas están en ENTREGADA, NO_ENTREGADA o CANCELADA: ninguna sigue
abierta. Eso basta para entrenar los modelos de la Unidad III, pero deja al
sistema sin su otra mitad —la operación que todavía no ocurre— y con ella se
cae todo lo que mira hacia adelante.

Consecuencia observable: el panel «Entregas con riesgo de llegar tarde»
(panel.html) y el endpoint GET /ml/entregas-en-riesgo salían siempre vacíos.
No era un fallo del código: `predecir_retraso()` solo acepta entregas
PROGRAMADA o EN_RUTA (§15.4) y en la base no existía ninguna, de modo que no
había NADA que predecir ni, por tanto, nada que listar.

Este módulo genera esa operación abierta y lanza sobre ella la predicción en
lote. El propio servicio de ML documenta que predecir cientos de entregas no
es trabajo de un endpoint de lectura sino «de un proceso programado»: este
script es ese proceso.

Qué escribe
-----------
    viajes        EN_CURSO (hoy, ya salieron) y PROGRAMADO (mañana)
    entregas      EN_RUTA / PROGRAMADA, sin `hora_real_llegada`
    incidentes    los ya ocurridos en los viajes en curso (Anexo B.6)
    entregas      ← se actualizan con `probabilidad_retraso` y `riesgo_retraso`
    predicciones  traza del vector y del modelo usado (§15.4, punto 2)

Coherencia con las reglas de negocio
------------------------------------
  · Un viaje sale a la `hora_salida_programada` de SU ruta (igual que PA-2).
  · Solo se asignan vehículos operativos: nunca EN_MANTENIMIENTO ni BAJA.
  · Solo operadores ACTIVOS, y ni vehículo ni operador se repiten el mismo día.
  · La ruta se opera únicamente en sus `dias_operacion`.
  · El retraso se calcula con los ocho factores del Anexo B.4, reutilizando
    las funciones de PA-2 en lugar de duplicarlas: si mañana se recalibra el
    Anexo B.4, la operación abierta se recalibra con él.
  · Un incidente solo se ubica en un tramo YA RECORRIDO. Una entrega pendiente
    no puede «saber» de un incidente que aún no ha ocurrido; lo que sí arrastra
    es el retraso acumulado del que ya ocurrió, y ese es justamente el caso que
    el panel de riesgo existe para avisar.
  · Nunca se toca `hora_estimada_llegada`: el retraso se mide contra ella
    (RN-I5, y la misma razón por la que la predicción tiene prohibido moverla).

Los datos son SIMULADOS (decisión C-02): todo documento lleva
`origen_dato: "SIMULADO"`.

Uso
---
    python -m database.seed.generar_pendientes --dry-run
    python -m database.seed.generar_pendientes
    python -m database.seed.generar_pendientes --limpiar
"""

from __future__ import annotations

import argparse
import random
import sys
from datetime import date, datetime, timedelta, timezone
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

# El fenómeno del retraso NO se reimplementa aquí: se importa de PA-2 para que
# la operación abierta y el histórico obedezcan al mismo Anexo B.4.
from database.seed.generar_operacion import (
    _generar_incidente,
    factor_base_ruta,
    factor_tiempo_real,
)

# --------------------------------------------------------------------------
# Parámetros propios de la operación abierta
# --------------------------------------------------------------------------
NUM_VIAJES_EN_CURSO: int = 10        # ya salieron: escenario EN_RUTA
NUM_VIAJES_PROGRAMADOS: int = 12     # aún no salen: escenario PLANEACION

# Punto del recorrido en el que se corta el viaje en curso. Es un corte
# SIMULADO, no la hora del reloj: fijarlo como fracción de la ruta garantiza
# que siempre queden paradas cerradas detrás y paradas pendientes delante,
# ejecute uno el script a la hora que lo ejecute.
FRACCION_RECORRIDA: tuple[float, float] = (0.35, 0.65)

ESTATUS_VIAJE_ABIERTO = (settings.ESTATUS_VIAJE_PROGRAMADO,
                         settings.ESTATUS_VIAJE_EN_CURSO)
ESTATUS_ENTREGA_ABIERTA = ("PROGRAMADA", "EN_RUTA")

VEHICULO_NO_OPERATIVO = ("EN_MANTENIMIENTO", "BAJA")


# ==========================================================================
# CALENDARIO
# ==========================================================================
def dia_operativo(dia: date) -> date:
    """El domingo no se opera (RNP-06): se corre al lunes siguiente."""
    while dia.weekday() not in P.DIAS_OPERACION_SEMANA:
        dia += timedelta(days=1)
    return dia


def nombre_del_dia(dia: date) -> str:
    return P.DIAS_OPERACION_NOMBRES[dia.weekday()]


def rutas_del_dia(rutas: list[dict], dia: date) -> list[dict]:
    nombre = nombre_del_dia(dia)
    return [r for r in rutas if nombre in (r.get("dias_operacion") or [])]


# ==========================================================================
# ESTADO DE LA FLOTA
# ==========================================================================
def estado_de_vehiculo(vehiculo: dict, dia: date) -> dict[str, Any]:
    """Antigüedad y desgaste desde el último mantenimiento, para el Anexo B.4."""
    anio = int(vehiculo.get("anio") or dia.year)
    ultimo = vehiculo.get("fecha_ultimo_mantenimiento")
    if ultimo is not None:
        dias_mtto = max((dia - ultimo.date()).days, 0)
    else:
        dias_mtto = P.DIAS_DESDE_MTTO_TIPICO
    return {
        "vehiculo": vehiculo,
        "antiguedad_anios": max(dia.year - anio, 0),
        "dias_desde_mtto": dias_mtto,
        "odometro": float(vehiculo.get("odometro_actual_km") or 0.0),
    }


def vehiculos_operativos(vehiculos: list[dict]) -> list[dict]:
    return [v for v in vehiculos
            if v.get("estado_operativo") not in VEHICULO_NO_OPERATIVO
            and v.get("activo", True)]


def operadores_activos(operadores: list[dict]) -> list[dict]:
    return [o for o in operadores
            if o.get("estado") == "ACTIVO" and o.get("activo", True)]


def _asignar_vehiculo(rng: random.Random, ruta: dict,
                      disponibles: dict[ObjectId, dict],
                      usados: set[ObjectId]) -> dict | None:
    """
    Preferencia por el vehículo asignado a la ruta; si no está disponible,
    cualquier otro operativo. Un vehículo no hace dos viajes abiertos a la vez.
    """
    preferido = ruta.get("vehiculo_asignado_id")
    if preferido in disponibles and preferido not in usados:
        usados.add(preferido)
        return disponibles[preferido]

    libres = [vid for vid in disponibles if vid not in usados]
    if not libres:
        return None
    elegido = rng.choice(libres)
    usados.add(elegido)
    return disponibles[elegido]


def _asignar_operador(rng: random.Random, activos: list[dict],
                      usados: set[ObjectId]) -> dict | None:
    libres = [o for o in activos if o["_id"] not in usados]
    if not libres:
        return None
    elegido = rng.choice(libres)
    usados.add(elegido["_id"])
    return elegido


# ==========================================================================
# CONSTRUCCIÓN DE UN VIAJE ABIERTO
# ==========================================================================
def _entrega_base(ruta: dict, viaje: dict, parada: dict, cliente: dict,
                  vehiculo: dict, operador: dict, dia: date,
                  hora_estimada: datetime, consecutivos: dict) -> dict[str, Any]:
    """Campos comunes a toda entrega abierta: los reales aún no existen."""
    consecutivos["entrega"] += 1
    return {
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
        "hora_real_llegada": None,
        "hora_estimada_recalculada": None,
        "tiempo_estimado_min": parada["tiempo_estimado_min"],
        "tiempo_real_min": None,
        "retraso_min": None,
        "es_retraso": None,
        "distancia_km": parada["distancia_desde_anterior_km"],
        "incidentes_ids": [],
        "causa_retraso": None,
        "observaciones": None,
        **C.campos_comunes(),
    }


def viaje_programado(rng: random.Random, dia: date, ruta: dict,
                     estado_veh: dict, operador: dict,
                     clientes_por_id: dict, consecutivos: dict[str, int],
                     ) -> tuple[dict, list[dict]]:
    """
    Viaje que aún no sale: escenario PLANEACION.

    No hay `retraso_salida_min` ni incidentes porque todavía no ha ocurrido
    nada. El modelo solo puede apoyarse en lo que se conoce al programar.
    """
    vehiculo = estado_veh["vehiculo"]
    salida_prog = C.a_datetime(dia, ruta["hora_salida_programada"])

    consecutivos["viaje"] += 1
    viaje: dict[str, Any] = {
        "_id": ObjectId(),
        "folio_viaje": C.folio_fechado("VJE", dia, consecutivos["viaje"]),
        "fecha": C.a_datetime(dia, "00:00"),
        "ruta_id": ruta["_id"],
        "vehiculo_id": vehiculo["_id"],
        "operador_id": operador["_id"],
        "hora_salida_programada": salida_prog,
        "estatus": settings.ESTATUS_VIAJE_PROGRAMADO,
        "hora_salida_real": None,
        "hora_regreso_real": None,
        "odometro_inicial_km": round(estado_veh["odometro"], 1),
        "odometro_final_km": None,
        "km_recorridos": None,
        "total_entregas_programadas": ruta["numero_paradas"],
        "total_entregas_completadas": 0,
        "total_incidentes": 0,
        "duracion_real_min": None,
        "retraso_salida_min": None,
        **C.campos_comunes(),
    }

    entregas: list[dict] = []
    acumulado = 0.0
    for parada in ruta["paradas"]:
        acumulado += parada["tiempo_estimado_min"]
        entrega = _entrega_base(
            ruta, viaje, parada, clientes_por_id[parada["cliente_id"]],
            vehiculo, operador, dia,
            salida_prog + timedelta(minutes=acumulado), consecutivos,
        )
        entrega["estatus"] = "PROGRAMADA"
        entrega["historial_estatus"] = [
            {"estatus": "PROGRAMADA", "fecha_hora": viaje["fecha"]},
        ]
        entregas.append(entrega)

    return viaje, entregas


def viaje_en_curso(rng: random.Random, dia: date, ruta: dict,
                   estado_veh: dict, operador: dict,
                   clientes_por_id: dict, consecutivos: dict[str, int],
                   ) -> tuple[dict, list[dict], list[dict]]:
    """
    Viaje que ya salió: escenario EN_RUTA.

    Las paradas anteriores al corte quedan cerradas con su retraso real; las
    posteriores siguen abiertas y heredan el retraso acumulado, que es lo que
    el modelo aprovecha para avisar antes de que la entrega llegue tarde.
    """
    vehiculo = estado_veh["vehiculo"]
    salida_prog = C.a_datetime(dia, ruta["hora_salida_programada"])

    retraso_salida = min(
        round(rng.gammavariate(P.RETRASO_SALIDA_FORMA, P.RETRASO_SALIDA_ESCALA)),
        P.RETRASO_SALIDA_MAX_MIN,
    )
    salida_real = salida_prog + timedelta(minutes=retraso_salida)

    consecutivos["viaje"] += 1
    viaje: dict[str, Any] = {
        "_id": ObjectId(),
        "folio_viaje": C.folio_fechado("VJE", dia, consecutivos["viaje"]),
        "fecha": C.a_datetime(dia, "00:00"),
        "ruta_id": ruta["_id"],
        "vehiculo_id": vehiculo["_id"],
        "operador_id": operador["_id"],
        "hora_salida_programada": salida_prog,
        "estatus": settings.ESTATUS_VIAJE_EN_CURSO,
        "hora_salida_real": salida_real,
        "hora_regreso_real": None,
        "odometro_inicial_km": round(estado_veh["odometro"], 1),
        "odometro_final_km": None,
        "km_recorridos": None,
        "total_entregas_programadas": ruta["numero_paradas"],
        "duracion_real_min": None,
        "retraso_salida_min": retraso_salida,
        **C.campos_comunes(),
    }

    # Corte del recorrido: al menos una parada cerrada y una pendiente.
    total_paradas = len(ruta["paradas"])
    cerradas = max(1, min(total_paradas - 1,
                          round(total_paradas * rng.uniform(*FRACCION_RECORRIDA))))

    # El incidente se ubica en un tramo YA recorrido: solo así puede haber
    # ocurrido de verdad y arrastrar retraso hacia las paradas pendientes.
    incidentes: list[dict] = []
    if rng.random() < P.PROPORCION_VIAJES_CON_INCIDENTE:
        incidente = _generar_incidente(rng, viaje, ruta, dia, total_paradas)
        incidente["_parada_afectada"] = rng.randint(1, cerradas)
        incidentes.append(incidente)

    base_ruta = factor_base_ruta(ruta, estado_veh["antiguedad_anios"])
    entregas: list[dict] = []
    acumulado = 0.0
    retraso_acum = float(retraso_salida)
    completadas = 0

    for parada in ruta["paradas"]:
        acumulado += parada["tiempo_estimado_min"]
        hora_estimada = salida_prog + timedelta(minutes=acumulado)
        entrega = _entrega_base(
            ruta, viaje, parada, clientes_por_id[parada["cliente_id"]],
            vehiculo, operador, dia, hora_estimada, consecutivos,
        )

        ids_incidente = [inc["_id"] for inc in incidentes
                         if parada["orden"] >= inc["_parada_afectada"]]
        entrega["incidentes_ids"] = ids_incidente

        if parada["orden"] <= cerradas:
            # ---------------- Parada ya entregada ----------------
            factor = factor_tiempo_real(
                rng, hora_estimada, dia.weekday(),
                estado_veh["antiguedad_anios"], estado_veh["dias_desde_mtto"],
                base_ruta,
            )
            retraso_acum += parada["tiempo_estimado_min"] * (factor - 1.0)
            for inc in incidentes:
                if parada["orden"] == inc["_parada_afectada"]:
                    retraso_acum += inc["duracion_min"]

            retraso_min = round(retraso_acum, 1)
            causa = next((inc["tipo"] for inc in incidentes
                          if parada["orden"] >= inc["_parada_afectada"]), None)
            if causa is None and retraso_min > P.UMBRAL_RETRASO_MIN:
                causa = "TRAFICO"

            entrega.update({
                "estatus": "ENTREGADA",
                "hora_real_llegada": hora_estimada + timedelta(minutes=retraso_acum),
                "tiempo_real_min": round(parada["tiempo_estimado_min"] * factor, 1),
                "retraso_min": retraso_min,
                "es_retraso": 1 if retraso_min > P.UMBRAL_RETRASO_MIN else 0,
                "causa_retraso": causa,
                "historial_estatus": [
                    {"estatus": "PROGRAMADA", "fecha_hora": viaje["fecha"]},
                    {"estatus": "EN_RUTA", "fecha_hora": salida_real},
                    {"estatus": "ENTREGADA",
                     "fecha_hora": hora_estimada + timedelta(minutes=retraso_acum)},
                ],
            })
            completadas += 1
        else:
            # ---------------- Parada todavía pendiente ----------------
            entrega["estatus"] = "EN_RUTA"
            entrega["historial_estatus"] = [
                {"estatus": "PROGRAMADA", "fecha_hora": viaje["fecha"]},
                {"estatus": "EN_RUTA", "fecha_hora": salida_real},
            ]

        for inc in incidentes:
            if parada["orden"] >= inc["_parada_afectada"]:
                inc["entregas_afectadas"].append(entrega["_id"])

        entregas.append(entrega)

    viaje["total_entregas_completadas"] = completadas
    viaje["total_incidentes"] = len(incidentes)
    return viaje, entregas, incidentes


# ==========================================================================
# GENERACIÓN COMPLETA
# ==========================================================================
def generar_pendientes(rng: random.Random, catalogos: dict,
                       hoy: date) -> dict[str, list[dict]]:
    clientes_por_id = {c["_id"]: c for c in catalogos["clientes"]}
    operativos = {v["_id"]: v for v in vehiculos_operativos(catalogos["vehiculos"])}
    activos = operadores_activos(catalogos["operadores"])
    if not operativos or not activos:
        raise RuntimeError(
            "No hay vehículos operativos u operadores activos en los catálogos. "
            "Ejecuta antes PA-1: python -m database.seed.generar_catalogos")

    dia_hoy = dia_operativo(hoy)
    dia_manana = dia_operativo(dia_hoy + timedelta(days=1))

    viajes: list[dict] = []
    entregas: list[dict] = []
    incidentes: list[dict] = []
    consecutivos = {"viaje": 0, "entrega": 0}

    for dia, cuantos, en_curso in (
        (dia_hoy, NUM_VIAJES_EN_CURSO, True),
        (dia_manana, NUM_VIAJES_PROGRAMADOS, False),
    ):
        candidatas = rutas_del_dia(catalogos["rutas"], dia)
        if not candidatas:
            continue
        rng.shuffle(candidatas)
        usados_veh: set[ObjectId] = set()
        usados_ope: set[ObjectId] = set()
        # Los consecutivos son por día: el folio ya lleva la fecha embebida.
        consecutivos = {"viaje": 0, "entrega": 0}

        for ruta in candidatas[:cuantos]:
            vehiculo = _asignar_vehiculo(rng, ruta, operativos, usados_veh)
            operador = _asignar_operador(rng, activos, usados_ope)
            if vehiculo is None or operador is None:
                break
            estado_veh = estado_de_vehiculo(vehiculo, dia)

            if en_curso:
                viaje, sus_entregas, sus_incidentes = viaje_en_curso(
                    rng, dia, ruta, estado_veh, operador,
                    clientes_por_id, consecutivos)
                incidentes.extend(sus_incidentes)
            else:
                viaje, sus_entregas = viaje_programado(
                    rng, dia, ruta, estado_veh, operador,
                    clientes_por_id, consecutivos)

            viajes.append(viaje)
            entregas.extend(sus_entregas)

    _folios_de_incidentes(incidentes)
    for inc in incidentes:
        inc.pop("_parada_afectada", None)

    return {"viajes": viajes, "entregas": entregas, "incidentes": incidentes}


def _folios_de_incidentes(incidentes: list[dict]) -> None:
    """Folio consecutivo por día, en orden cronológico (igual que PA-2)."""
    incidentes.sort(key=lambda i: i["fecha_hora_inicio"])
    por_dia: dict[date, int] = {}
    for inc in incidentes:
        dia = inc["fecha_hora_inicio"].date()
        por_dia[dia] = por_dia.get(dia, 0) + 1
        inc["folio_incidente"] = C.folio_fechado("INC", dia, por_dia[dia])


# ==========================================================================
# VALIDACIÓN
# ==========================================================================
def validar(datos: dict, catalogos: dict) -> list[tuple[str, bool, str]]:
    viajes, entregas = datos["viajes"], datos["entregas"]
    abiertas = [e for e in entregas if e["estatus"] in ESTATUS_ENTREGA_ABIERTA]
    no_operativos = {v["_id"] for v in catalogos["vehiculos"]
                     if v.get("estado_operativo") in VEHICULO_NO_OPERATIVO}
    folios = [e["folio_entrega"] for e in entregas]

    return [
        ("Se generó al menos un viaje abierto",
         bool(viajes), f"{len(viajes)} viajes"),
        ("Hay entregas abiertas que predecir",
         bool(abiertas), f"{len(abiertas)} de {len(entregas)} entregas"),
        ("Ninguna entrega abierta tiene hora real de llegada",
         all(e["hora_real_llegada"] is None for e in abiertas), "RN §15.4"),
        ("Todo estatus de entrega está en el catálogo RNP-08",
         all(e["estatus"] in settings.CATALOGO_ESTATUS_ENTREGA for e in entregas), ""),
        ("Todo estatus de viaje es PROGRAMADO o EN_CURSO",
         all(v["estatus"] in ESTATUS_VIAJE_ABIERTO for v in viajes), ""),
        ("Ningún vehículo en mantenimiento o baja fue asignado",
         all(v["vehiculo_id"] not in no_operativos for v in viajes), ""),
        ("Los folios de entrega no se repiten",
         len(folios) == len(set(folios)), f"{len(folios)} folios"),
        ("Todo documento va marcado como SIMULADO",
         all(d.get("origen_dato") == P.ORIGEN_DATO
             for grupo in datos.values() for d in grupo), ""),
        ("Los dos escenarios de predicción están representados",
         any(v["estatus"] == settings.ESTATUS_VIAJE_EN_CURSO for v in viajes)
         and any(v["estatus"] == settings.ESTATUS_VIAJE_PROGRAMADO for v in viajes),
         "EN_RUTA y PLANEACION"),
    ]


def imprimir_validaciones(resultados) -> bool:
    C.encabezado("VALIDACIONES")
    todo_bien = True
    for descripcion, ok, detalle in resultados:
        marca = "OK  " if ok else "FALLA"
        print(f"  [{marca}] {descripcion}" + (f" — {detalle}" if detalle else ""))
        todo_bien = todo_bien and ok
    return todo_bien


def imprimir_resumen(datos: dict) -> None:
    C.encabezado("RESUMEN DE LA OPERACIÓN ABIERTA")
    viajes, entregas = datos["viajes"], datos["entregas"]
    en_curso = [v for v in viajes if v["estatus"] == settings.ESTATUS_VIAJE_EN_CURSO]
    programados = [v for v in viajes
                   if v["estatus"] == settings.ESTATUS_VIAJE_PROGRAMADO]
    print(f"  Viajes EN_CURSO ....... {len(en_curso):>4}  (escenario EN_RUTA)")
    print(f"  Viajes PROGRAMADO ..... {len(programados):>4}  (escenario PLANEACION)")
    print(f"  Incidentes ............ {len(datos['incidentes']):>4}")
    print()
    print("  ESTATUS DE ENTREGA")
    for estatus in settings.CATALOGO_ESTATUS_ENTREGA:
        cuantas = sum(1 for e in entregas if e["estatus"] == estatus)
        if cuantas:
            print(f"    {estatus:<16}{cuantas:>5}")
    abiertas = sum(1 for e in entregas if e["estatus"] in ESTATUS_ENTREGA_ABIERTA)
    print(f"\n  Entregas a predecir ... {abiertas}")


# ==========================================================================
# CARGA Y PREDICCIÓN
# ==========================================================================
def limpiar_operacion_abierta(bd) -> None:
    """
    Borra solo lo que este script produce.

    El histórico de PA-2 no tiene un solo viaje PROGRAMADO ni EN_CURSO —al
    cerrarse, todos quedaron FINALIZADO o CANCELADO—, así que filtrar por esos
    dos estatus alcanza exactamente a la operación abierta y a nada más.
    """
    C.encabezado("LIMPIEZA DE LA OPERACIÓN ABIERTA ANTERIOR")
    ids_viaje = [v["_id"] for v in bd["viajes"].find(
        {"estatus": {"$in": list(ESTATUS_VIAJE_ABIERTO)}}, {"_id": 1})]
    if not ids_viaje:
        print("  No había operación abierta previa.")
        return

    borradas = bd["entregas"].delete_many({"viaje_id": {"$in": ids_viaje}})
    print(f"  entregas          {borradas.deleted_count} eliminadas")
    print(f"  predicciones      "
          f"{bd['predicciones'].delete_many({'viaje_id': {'$in': ids_viaje}}).deleted_count} eliminadas")
    print(f"  incidentes        "
          f"{bd['incidentes'].delete_many({'viaje_id': {'$in': ids_viaje}}).deleted_count} eliminados")
    print(f"  viajes            "
          f"{bd['viajes'].delete_many({'_id': {'$in': ids_viaje}}).deleted_count} eliminados")


def cargar(bd, datos: dict) -> None:
    C.encabezado("CARGA EN MONGODB ATLAS")
    for nombre in ("viajes", "entregas", "incidentes"):
        documentos = datos[nombre]
        if not documentos:
            print(f"  {nombre:<18}sin documentos")
            continue
        insertados = len(
            bd[nombre].insert_many(documentos, ordered=False).inserted_ids)
        print(f"  {nombre:<18}{insertados} documentos insertados")


def predecir_en_lote(bd, entregas: list[dict]) -> dict[str, Any]:
    """
    Lanza la predicción sobre cada entrega abierta y deja la traza en la BD.

    Se llama al MISMO servicio que usa el endpoint (`backend.services.ml`), no
    a una copia: si el criterio de riesgo cambia, el lote cambia con él.
    """
    from backend.services import ml as servicio_ml

    C.encabezado("PREDICCIÓN DE RIESGO EN LOTE (§15.4)")
    abiertas = [e for e in entregas if e["estatus"] in ESTATUS_ENTREGA_ABIERTA]
    conteo = {"ALTO": 0, "MEDIO": 0, "BAJO": 0}
    fallos: list[str] = []

    for i, entrega in enumerate(abiertas, start=1):
        try:
            resultado = servicio_ml.predecir_retraso(bd, str(entrega["_id"]))
            conteo[resultado["riesgo"]] += 1
        except Exception as error:                       # noqa: BLE001
            fallos.append(f"{entrega['folio_entrega']}: {error}")
        if i % 20 == 0 or i == len(abiertas):
            print(f"  {i}/{len(abiertas)} entregas predichas...", end="\r")

    print(f"  {len(abiertas) - len(fallos)}/{len(abiertas)} entregas predichas"
          + " " * 20)
    print()
    for nivel in ("ALTO", "MEDIO", "BAJO"):
        print(f"    Riesgo {nivel:<7}{conteo[nivel]:>5}")
    if fallos:
        print(f"\n  {len(fallos)} predicciones fallaron. Primeras:")
        for linea in fallos[:5]:
            print(f"    · {linea}")
    return {"conteo": conteo, "fallos": fallos, "total": len(abiertas)}


# ==========================================================================
# PUNTO DE ENTRADA
# ==========================================================================
def main() -> int:
    parser = argparse.ArgumentParser(
        description="PA-2b — Genera la operación abierta y predice su riesgo.",
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Genera y valida en memoria, sin escribir en Atlas.")
    parser.add_argument("--limpiar", action="store_true",
                        help="Borra la operación abierta anterior antes de generar.")
    parser.add_argument("--semilla", type=int, default=P.SEMILLA)
    parser.add_argument("--dia", type=date.fromisoformat, default=None,
                        help="Día de la operación en curso (YYYY-MM-DD). "
                             "Por omisión, hoy.")
    args = parser.parse_args()

    C.aviso_datos_simulados()

    if not verificar_conexion(verbose=True)["exito"]:
        return 1

    try:
        bd = obtener_bd()
        C.encabezado("LECTURA DE CATÁLOGOS (PA-1)")
        catalogos = {c: list(bd[c].find({})) for c in settings.COLECCIONES_CATALOGO}
        faltantes = [c for c, docs in catalogos.items() if not docs]
        if faltantes:
            print("  Colecciones de catálogo vacías: " + ", ".join(faltantes))
            print("  Ejecuta primero: python -m database.seed.generar_catalogos")
            return 1
        for nombre, docs in catalogos.items():
            print(f"  {nombre:<18}{len(docs):>7} documentos leídos")

        hoy = args.dia or datetime.now(timezone.utc).date()
        print(f"\n  Operación en curso .. {dia_operativo(hoy)}")
        print(f"  Operación programada  {dia_operativo(dia_operativo(hoy) + timedelta(days=1))}")

        datos = generar_pendientes(C.crear_rng(args.semilla), catalogos, hoy)
        imprimir_resumen(datos)
        if not imprimir_validaciones(validar(datos, catalogos)):
            print("\n  Hay validaciones en falla. No se escribe nada en Atlas.")
            return 1

        if args.dry_run:
            print("\n  --dry-run activo: no se escribió nada en MongoDB.")
            return 0

        if args.limpiar:
            limpiar_operacion_abierta(bd)
        cargar(bd, datos)
        resumen = predecir_en_lote(bd, datos["entregas"])

        print()
        print(C.LINEA)
        if resumen["fallos"]:
            print("  Operación abierta cargada, con predicciones fallidas.")
            print("  Revisa que los modelos estén en ml/modelos_guardados/.")
            return 1
        print("  Operación abierta cargada y predicha.")
        print("  Compruébalo en el panel o con:")
        print("    GET /ml/entregas-en-riesgo")
        print(C.LINEA)
        return 0

    finally:
        cerrar_cliente()


if __name__ == "__main__":
    raise SystemExit(main())
