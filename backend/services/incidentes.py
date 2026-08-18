"""
SIG-LOG — Sistema Integral de Gestión Logística
backend/services/incidentes.py

REGLAS DEL MÓDULO INCIDENTES  (§11.7) Y RECÁLCULO DE ETA (RF-33)

Los incidentes son lo que explica los retrasos anómalos: sin ellos —dice
el §11.7— el modelo solo aprende la variación normal.

Reglas de negocio (RN-I1 a RN-I6)
---------------------------------
RN-I1  El folio INC-AAAAMMDD-NNN lo genera el sistema y es inmutable.

RN-I2  Un incidente pertenece a un viaje abierto: registrar uno sobre un
       viaje ya cerrado contradiría su cierre, y ese cierre ya declaró
       cuántos incidentes hubo.

RN-I3  `duracion_min` se calcula al cerrar el incidente, a partir del
       inicio y el fin. Mientras sigue abierto se trabaja con el tiempo
       perdido estimado, que sí lo aporta quien está en la calle.

RN-I4  El recálculo de ETA solo alcanza a las entregas PENDIENTES del
       viaje del incidente (§17.3, paso 2). A una entrega ya registrada no
       se le cambia la previsión de cuándo iba a llegar.

RN-I5  El recálculo escribe `hora_estimada_recalculada` y NUNCA pisa
       `hora_estimada_llegada`. Es la regla más importante del módulo: el
       plan original es la referencia contra la que se mide el retraso
       (`retraso_min = real − estimada`). Si se sobrescribiera, la entrega
       parecería puntual justo por el incidente que la retrasó, y los
       modelos perderían la señal que este módulo existe para darles.

RN-I6  Cada recálculo deja constancia en `seguimiento_eventos` con el ETA
       anterior y el nuevo (§17.3, paso 4). Sin ese rastro no se podría
       explicar después por qué una entrega tenía dos previsiones.

Sobre la linealidad del recálculo
---------------------------------
El §17.3 propone sumar los minutos perdidos al ETA de cada entrega
pendiente y **advierte que ese supuesto no está confirmado**: un incidente
de 25 minutos podría no retrasar 25 minutos a la última parada del día. Se
implementa como el documento indica, y la respuesta del API lleva esa
advertencia, para que la cifra no se tome por una certeza. El paso 5 del
§17.3 —sustituir la suma por una predicción del modelo de regresión—
queda como la evolución natural cuando se integre ML en la operación.
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from bson import ObjectId
from pymongo.database import Database

from backend.repositories.incidentes import RepositorioIncidentes
from backend.schemas.incidentes import IncidenteSalida
from backend.utils.errores import ReglaDeNegocio
from config import settings


# ==========================================================================
# CONSULTA
# ==========================================================================
def listar(bd: Database, *, saltar: int = 0, limite: int = 50,
           viaje_id: str | None = None, tipo: str | None = None,
           severidad: str | None = None, solo_abiertos: bool | None = None,
           fecha_desde: date | None = None, fecha_hasta: date | None = None
           ) -> tuple[list[dict[str, Any]], int]:
    repositorio = RepositorioIncidentes(bd)
    filtro: dict[str, Any] = {}

    if tipo:
        tipo = tipo.strip().upper()
        if tipo not in settings.CATALOGO_TIPOS_INCIDENTE:
            raise ReglaDeNegocio(
                f"Tipo '{tipo}' no pertenece al catálogo RNP-12 "
                f"{list(settings.CATALOGO_TIPOS_INCIDENTE)}.")
        filtro["tipo"] = tipo
    if severidad:
        severidad = severidad.strip().upper()
        if severidad not in settings.CATALOGO_SEVERIDAD_INCIDENTE:
            raise ReglaDeNegocio(
                f"Severidad '{severidad}' no pertenece al catálogo "
                f"{list(settings.CATALOGO_SEVERIDAD_INCIDENTE)}.")
        filtro["severidad"] = severidad
    if solo_abiertos is not None:
        filtro["fecha_hora_fin"] = None if solo_abiertos else {"$ne": None}
    if viaje_id:
        filtro["viaje_id"] = repositorio.a_object_id(viaje_id)

    rango: dict[str, Any] = {}
    if fecha_desde:
        rango["$gte"] = _a_datetime(fecha_desde)
    if fecha_hasta:
        rango["$lte"] = _a_datetime(fecha_hasta).replace(hour=23, minute=59,
                                                         second=59)
    if rango:
        filtro["fecha_hora_inicio"] = rango

    documentos = repositorio.listar(
        filtro, saltar=saltar, limite=limite,
        orden=[("fecha_hora_inicio", -1)], incluir_inactivos=True)
    total = repositorio.contar(filtro, incluir_inactivos=True)
    return [_publico(d) for d in documentos], total


def obtener(bd: Database, identificador: str) -> dict[str, Any]:
    return _publico(
        RepositorioIncidentes(bd).obtener(identificador, incluir_inactivos=True))


def resumen(bd: Database) -> dict[str, Any]:
    """
    Conteo por tipo y severidad: es la base del análisis de Pareto de
    causas que el dashboard presenta.
    """
    repositorio = RepositorioIncidentes(bd)
    por_tipo = {t: repositorio.contar({"tipo": t}, incluir_inactivos=True)
                for t in settings.CATALOGO_TIPOS_INCIDENTE}
    por_severidad = {
        s: repositorio.contar({"severidad": s}, incluir_inactivos=True)
        for s in settings.CATALOGO_SEVERIDAD_INCIDENTE
    }
    abiertos = repositorio.contar({"fecha_hora_fin": None},
                                  incluir_inactivos=True)
    total = repositorio.contar(incluir_inactivos=True)
    dominante = max(por_tipo, key=por_tipo.get) if total else None

    return {
        "total": total,
        "abiertos": abiertos,
        "cerrados": total - abiertos,
        "por_tipo": por_tipo,
        "por_severidad": por_severidad,
        "tipo_dominante": dominante,
        "alerta": (
            f"{abiertos} incidente(s) sin cerrar."
            if abiertos else
            (f"La causa más frecuente es {dominante} "
             f"({por_tipo[dominante]:,} de {total:,} incidentes)."
             if dominante else "No hay incidentes registrados.")),
    }


def bitacora(bd: Database, viaje_id: str) -> dict[str, Any]:
    """Eventos de seguimiento del viaje, en orden cronológico (§11.10)."""
    repositorio = RepositorioIncidentes(bd)
    viaje = repositorio.viaje(repositorio.a_object_id(viaje_id))
    if viaje is None:
        raise ReglaDeNegocio(f"No existe el viaje '{viaje_id}'.")

    eventos = repositorio.eventos_del_viaje(viaje["_id"])
    return {
        "viaje": viaje.get("folio_viaje"),
        "total_eventos": len(eventos),
        "eventos": [_evento_publico(e) for e in eventos],
    }


# ==========================================================================
# ALTA Y CIERRE
# ==========================================================================
def crear(bd: Database, datos: dict[str, Any]) -> dict[str, Any]:
    """Registra el incidente (RN-I1, RN-I2)."""
    repositorio = RepositorioIncidentes(bd)
    viaje = repositorio.viaje(repositorio.a_object_id(datos["viaje_id"]))
    if viaje is None:
        raise ReglaDeNegocio(f"No existe el viaje '{datos['viaje_id']}'.")

    # RN-I2 — no se registran incidentes sobre viajes cerrados
    if viaje.get("estatus") not in settings.ESTATUS_VIAJE_ABIERTOS:
        raise ReglaDeNegocio(
            f"El viaje {viaje['folio_viaje']} está {viaje.get('estatus')} "
            "(RN-I2): su cierre ya declaró cuántos incidentes hubo.",
            regla="I2",
            detalles=[{"estatus_viaje": viaje.get("estatus")}])

    inicio = _fecha_o_ahora(datos.get("fecha_hora_inicio"))
    documento = {
        "folio_incidente": repositorio.siguiente_folio(inicio),   # RN-I1
        "viaje_id": viaje["_id"],
        "ruta_id": viaje.get("ruta_id"),
        "tipo": datos["tipo"],
        "severidad": datos["severidad"],
        "fecha_hora_inicio": inicio,
        "fecha_hora_fin": None,
        "duracion_min": None,                                     # RN-I3
        "tiempo_perdido_estimado_min": round(
            float(datos["tiempo_perdido_estimado_min"]), 1),
        "entregas_afectadas": [],
        "ubicacion": None,
        "descripcion": datos.get("descripcion"),
        "fuente": datos.get("fuente", "MANUAL"),
    }
    creado = repositorio.crear(documento)

    repositorio.actualizar_total_del_viaje(viaje["_id"])
    repositorio.registrar_evento(
        viaje["_id"], "INCIDENTE",
        motivo=f"{documento['tipo']} ({documento['severidad']}): "
               f"{documento['folio_incidente']}")
    return _publico(creado)


def cerrar(bd: Database, identificador: str,
           fecha_fin: Any = None) -> dict[str, Any]:
    """Cierra el incidente y calcula su duración real (RN-I3)."""
    repositorio = RepositorioIncidentes(bd)
    incidente = repositorio.obtener(identificador, incluir_inactivos=True)

    if incidente.get("fecha_hora_fin") is not None:
        raise ReglaDeNegocio(
            f"El incidente {incidente['folio_incidente']} ya estaba cerrado.")

    fin = _fecha_o_ahora(fecha_fin)
    inicio = _con_zona(incidente["fecha_hora_inicio"])
    if fin <= inicio:
        raise ReglaDeNegocio(
            "La hora de fin debe ser posterior a la de inicio (RN-I3).",
            regla="I3")

    cambios = {
        "fecha_hora_fin": fin,
        "duracion_min": round((fin - inicio).total_seconds() / 60, 1),
    }
    return _publico(repositorio.actualizar(identificador, cambios,
                                           incluir_inactivos=True))


# ==========================================================================
# RECÁLCULO DE ETA  (§12.3, RF-33, §17.3)
# ==========================================================================
def afectar_entregas(bd: Database, identificador: str,
                     datos: dict[str, Any]) -> dict[str, Any]:
    """
    Asocia el incidente a las entregas y recalcula su ETA (RF-33).

    Sigue el procedimiento del §17.3: identifica las entregas pendientes,
    suma los minutos perdidos a su ETA, escribe el resultado en
    `hora_estimada_recalculada` —sin tocar el plan original— y deja el
    rastro en `seguimiento_eventos`.
    """
    repositorio = RepositorioIncidentes(bd)
    incidente = repositorio.obtener(identificador, incluir_inactivos=True)
    viaje = repositorio.viaje(incidente["viaje_id"])
    if viaje is None:
        raise ReglaDeNegocio("El incidente no tiene un viaje válido asociado.")

    minutos = _minutos_a_sumar(incidente, datos.get("minutos_perdidos"))
    entregas = _entregas_a_afectar(repositorio, incidente, viaje,
                                   datos.get("entregas_ids"))

    if not entregas:
        raise ReglaDeNegocio(
            f"El viaje {viaje['folio_viaje']} no tiene entregas pendientes "
            "que recalcular (RN-I4): todas tienen ya su desenlace "
            "registrado.",
            regla="I4")

    ajustadas: list[dict[str, Any]] = []
    for entrega in entregas:
        # El ETA de partida es el ya recalculado si lo hubiera: dos
        # incidentes en el mismo viaje deben acumularse, no pisarse.
        anterior = (_con_zona(entrega.get("hora_estimada_recalculada"))
                    or _con_zona(entrega.get("hora_estimada_llegada")))
        if anterior is None:
            continue
        nuevo = anterior + timedelta(minutes=minutos)

        # RN-I5 — se escribe el recalculado; el plan original no se toca
        repositorio.aplicar_recalculo(entrega["_id"], nuevo, incidente["_id"])
        # RN-I6 — constancia en la bitácora (§17.3, paso 4)
        repositorio.registrar_evento(
            viaje["_id"], "RECALCULO_ETA",
            entrega_id=entrega["_id"], eta_anterior=anterior, eta_nuevo=nuevo,
            motivo=(f"{incidente['folio_incidente']} "
                    f"({incidente['tipo']}): +{minutos:.0f} min"))

        ajustadas.append({
            "entrega": entrega.get("folio_entrega"),
            "orden_parada": entrega.get("orden_parada"),
            "eta_anterior": anterior.isoformat(),
            "eta_nuevo": nuevo.isoformat(),
        })

    repositorio.actualizar(
        identificador,
        {"entregas_afectadas": sorted(
            {*[e["_id"] for e in entregas],
             *incidente.get("entregas_afectadas", [])}, key=str)},
        incluir_inactivos=True)

    return {
        "incidente": incidente["folio_incidente"],
        "viaje": viaje.get("folio_viaje"),
        "minutos_perdidos": minutos,
        "entregas_afectadas": len(ajustadas),
        "detalle": ajustadas,
        "metodo": ("suma lineal (§17.3, paso 3)"
                   if settings.RECALCULO_ETA_ES_LINEAL else "modelo de regresión"),
        "advertencia": settings.ADVERTENCIA_RECALCULO_ETA,
        "nota_plan_original": (
            "Se escribió `hora_estimada_recalculada`. El plan original "
            "(`hora_estimada_llegada`) NO se modifica: es la referencia "
            "contra la que se mide el retraso, y sobrescribirlo haría que "
            "el incidente ocultara el retraso que él mismo causó."),
    }


# ==========================================================================
# INTERNO
# ==========================================================================
def _minutos_a_sumar(incidente: dict[str, Any],
                     solicitados: float | None) -> float:
    """
    Minutos a sumar al ETA: los indicados, o la duración real si el
    incidente ya cerró, o el tiempo estimado mientras sigue abierto.
    """
    if solicitados is not None:
        return round(float(solicitados), 1)
    if incidente.get("duracion_min"):
        return round(float(incidente["duracion_min"]), 1)
    estimado = incidente.get("tiempo_perdido_estimado_min")
    if not estimado:
        raise ReglaDeNegocio(
            "El incidente no tiene duración ni tiempo perdido estimado: no "
            "hay con qué recalcular el ETA.")
    return round(float(estimado), 1)


def _entregas_a_afectar(repositorio: RepositorioIncidentes,
                        incidente: dict[str, Any], viaje: dict[str, Any],
                        identificadores: list[str] | None
                        ) -> list[dict[str, Any]]:
    """RN-I4: solo entregas pendientes, y solo del viaje del incidente."""
    if not identificadores:
        return repositorio.entregas_pendientes(viaje["_id"])

    entregas = repositorio.entregas_por_id(
        [repositorio.a_object_id(i) for i in identificadores])
    if len(entregas) != len(identificadores):
        raise ReglaDeNegocio(
            "Alguna de las entregas indicadas no existe.")

    ajenas = [e["folio_entrega"] for e in entregas
              if e.get("viaje_id") != viaje["_id"]]
    if ajenas:
        raise ReglaDeNegocio(
            f"Estas entregas no pertenecen al viaje del incidente: "
            f"{', '.join(ajenas)} (RN-I4).", regla="I4")

    cerradas = [e["folio_entrega"] for e in entregas
                if e.get("estatus") in ("ENTREGADA", "NO_ENTREGADA",
                                        "CANCELADA")]
    if cerradas:
        raise ReglaDeNegocio(
            f"Estas entregas ya tienen su desenlace registrado y no admiten "
            f"recálculo: {', '.join(cerradas)} (RN-I4).", regla="I4")
    return entregas


def _a_datetime(valor: Any) -> datetime:
    if isinstance(valor, datetime):
        return valor if valor.tzinfo else valor.replace(tzinfo=timezone.utc)
    if isinstance(valor, date):
        return datetime(valor.year, valor.month, valor.day, tzinfo=timezone.utc)
    return datetime.fromisoformat(str(valor)).replace(tzinfo=timezone.utc)


def _con_zona(valor: Any) -> datetime | None:
    return _a_datetime(valor) if valor is not None else None


def _fecha_o_ahora(valor: Any) -> datetime:
    return _a_datetime(valor) if valor else datetime.now(timezone.utc)


def _publico(documento: dict[str, Any]) -> dict[str, Any]:
    return IncidenteSalida.desde_documento(documento).model_dump()


def _evento_publico(evento: dict[str, Any]) -> dict[str, Any]:
    salida = {clave: valor for clave, valor in evento.items()
              if clave not in ("origen_dato", "activo", "fecha_creacion",
                               "fecha_modificacion")}
    for clave, valor in list(salida.items()):
        if isinstance(valor, ObjectId):
            salida[clave] = str(valor)
        elif isinstance(valor, datetime):
            salida[clave] = valor.isoformat()
    return salida
