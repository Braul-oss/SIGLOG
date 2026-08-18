"""
SIG-LOG — Sistema Integral de Gestión Logística
backend/services/viajes.py

REGLAS DEL MÓDULO VIAJES  (§11.5)

El viaje es donde el sistema deja de ser un catálogo y pasa a registrar
operación. También es donde se cobran las promesas que hicieron los
módulos anteriores: aquí se comprueba la licencia del operador (RN-O3),
se usa el estado del vehículo (RN-V5) y se actualiza su odómetro, que
RN-V6 prohibió capturar a mano precisamente porque lo escribe este cierre.

Reglas de negocio (RN-J1 a RN-J7)
---------------------------------
RN-J1  El folio VJE-AAAAMMDD-NNNN lo genera el sistema y es inmutable.

RN-J2  El estatus avanza y nunca retrocede:
       PROGRAMADO → EN_CURSO → FINALIZADO, y CANCELADO desde los dos
       primeros. El §11.5 dice que cada documento ES el histórico y no se
       sobrescribe; reabrir un viaje cerrado sería reescribir lo que ya
       ocurrió, y sobre esos documentos se construyen el DW y los modelos.

RN-J3  Al programar se comprueba que todo el mundo pueda: la ruta activa,
       el vehículo DISPONIBLE, el operador ACTIVO **y con licencia
       vigente**, y que ni el vehículo ni el operador tengan otro viaje
       sin cerrar. Nadie está en dos jornadas a la vez.

RN-J4  Una ruta se ejecuta una vez al día. Dos viajes de la misma ruta en
       la misma fecha duplicarían entregas y kilometraje.

RN-J5  Al iniciar, el odómetro declarado no puede ser menor que el que ya
       tiene la unidad: el kilometraje no baja.

RN-J6  Al finalizar, el odómetro final debe ser mayor que el inicial y la
       hora de regreso posterior a la de salida. De ahí salen
       `km_recorridos` y `duracion_real_min`.

RN-J7  Un viaje no se borra ni se da de baja: se CANCELA, con motivo. Es
       la única colección del sistema sin baja lógica, porque cada
       documento es un hecho ocurrido.
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from bson import ObjectId
from pymongo.database import Database

from backend.repositories.viajes import RepositorioViajes
from backend.schemas.viajes import ViajeSalida
from backend.utils.errores import ReglaDeNegocio
from config import settings


# ==========================================================================
# CONSULTA
# ==========================================================================
def listar(bd: Database, *, saltar: int = 0, limite: int = 50,
           estatus: str | None = None, fecha_desde: date | None = None,
           fecha_hasta: date | None = None, ruta_id: str | None = None,
           vehiculo_id: str | None = None, operador_id: str | None = None
           ) -> tuple[list[dict[str, Any]], int]:
    repositorio = RepositorioViajes(bd)
    filtro: dict[str, Any] = {}

    if estatus:
        estatus = estatus.strip().upper()
        if estatus not in settings.CATALOGO_ESTATUS_VIAJE:
            raise ReglaDeNegocio(
                f"Estatus '{estatus}' no pertenece al catálogo "
                f"{list(settings.CATALOGO_ESTATUS_VIAJE)}.")
        filtro["estatus"] = estatus

    rango: dict[str, Any] = {}
    if fecha_desde:
        rango["$gte"] = _a_datetime(fecha_desde)
    if fecha_hasta:
        rango["$lte"] = _a_datetime(fecha_hasta).replace(hour=23, minute=59,
                                                         second=59)
    if rango:
        filtro["fecha"] = rango

    for campo, valor in (("ruta_id", ruta_id), ("vehiculo_id", vehiculo_id),
                         ("operador_id", operador_id)):
        if valor:
            filtro[campo] = repositorio.a_object_id(valor)

    documentos = repositorio.listar(
        filtro, saltar=saltar, limite=limite,
        orden=[("fecha", -1), ("folio_viaje", -1)], incluir_inactivos=True)
    total = repositorio.contar(filtro, incluir_inactivos=True)
    return [_publico(d) for d in documentos], total


def obtener(bd: Database, identificador: str) -> dict[str, Any]:
    return _publico(
        RepositorioViajes(bd).obtener(identificador, incluir_inactivos=True))


def resumen(bd: Database) -> dict[str, Any]:
    repositorio = RepositorioViajes(bd)
    por_estatus = {
        estatus: repositorio.contar({"estatus": estatus}, incluir_inactivos=True)
        for estatus in settings.CATALOGO_ESTATUS_VIAJE
    }
    abiertos = sum(por_estatus[e] for e in settings.ESTATUS_VIAJE_ABIERTOS)
    return {
        "total": repositorio.contar(incluir_inactivos=True),
        "por_estatus": por_estatus,
        "abiertos": abiertos,
        "alerta": (f"{abiertos} viaje(s) sin cerrar."
                   if abiertos else "No hay viajes abiertos."),
    }


# ==========================================================================
# PROGRAMAR  (RN-J1, RN-J3, RN-J4)
# ==========================================================================
def programar(bd: Database, datos: dict[str, Any]) -> dict[str, Any]:
    """
    Da de alta la jornada tras comprobar que puede ejecutarse.

    Las validaciones se hacen ANTES de escribir nada: un viaje programado
    con un operador sin licencia o un vehículo en el taller es un problema
    que aparece el día de la salida, cuando ya no hay margen.
    """
    repositorio = RepositorioViajes(bd)
    fecha = _a_datetime(datos["fecha"])

    ruta = _validar_ruta(repositorio, datos["ruta_id"])
    vehiculo = _validar_vehiculo(repositorio, datos["vehiculo_id"])
    operador = _validar_operador(repositorio, datos["operador_id"])

    # RN-J4 — una ruta, una ejecución por día
    existente = repositorio.viaje_de_la_ruta_en_fecha(ruta["_id"], fecha)
    if existente:
        raise ReglaDeNegocio(
            f"La ruta {ruta['codigo_ruta']} ya tiene el viaje "
            f"{existente['folio_viaje']} para el {fecha:%Y-%m-%d} "
            f"({existente['estatus']}) (RN-J4).",
            regla="J4",
            detalles=[{"folio_existente": existente["folio_viaje"]}])

    # RN-J3 — ni el vehículo ni el operador pueden estar en otra jornada
    _validar_sin_viaje_abierto(repositorio, "vehiculo_id", vehiculo["_id"],
                               f"El vehículo {vehiculo['codigo_vehiculo']}")
    _validar_sin_viaje_abierto(repositorio, "operador_id", operador["_id"],
                               f"El operador {operador['codigo_operador']}")

    documento = {
        "folio_viaje": repositorio.siguiente_folio(fecha),      # RN-J1
        "fecha": fecha,
        "ruta_id": ruta["_id"],
        "vehiculo_id": vehiculo["_id"],
        "operador_id": operador["_id"],
        "hora_salida_programada": _hora_programada(
            fecha, ruta.get("hora_salida_programada")),
        "estatus": settings.ESTATUS_VIAJE_PROGRAMADO,
        "total_entregas_programadas": int(ruta.get("numero_paradas") or 0),
        "total_entregas_completadas": None,
        "total_incidentes": 0,
        "hora_salida_real": None,
        "hora_regreso_real": None,
        "odometro_inicial_km": None,
        "odometro_final_km": None,
        "km_recorridos": None,
        "duracion_real_min": None,
        "retraso_salida_min": None,
    }
    return _publico(repositorio.crear(documento))


# ==========================================================================
# INICIAR  (§12.3, RN-J5)
# ==========================================================================
def iniciar(bd: Database, identificador: str,
            datos: dict[str, Any]) -> dict[str, Any]:
    """
    Registra la salida real y pone la unidad en ruta.

    `retraso_salida_min` se calcula aquí y no se captura: según el §11.5
    es probablemente el predictor más fuerte del retraso de las entregas
    del día, y un valor tecleado podría contradecir a sus propias horas.
    """
    repositorio = RepositorioViajes(bd)
    viaje = repositorio.obtener(identificador, incluir_inactivos=True)
    _exigir_transicion(viaje, settings.ESTATUS_VIAJE_EN_CURSO)

    vehiculo = repositorio.vehiculo(viaje["vehiculo_id"])
    odometro = float(datos["odometro_inicial_km"])
    actual = float(vehiculo.get("odometro_actual_km") or 0)

    # RN-J5 — el kilometraje no baja
    if odometro < actual:
        raise ReglaDeNegocio(
            f"El odómetro declarado ({odometro:,.1f} km) es menor que el "
            f"registrado en {vehiculo['codigo_vehiculo']} ({actual:,.1f} km) "
            "(RN-J5). El kilometraje no baja: revisa la lectura.",
            regla="J5",
            detalles=[{"odometro_declarado": odometro,
                       "odometro_registrado": actual}])

    salida = _fecha_o_ahora(datos.get("hora_salida_real"))
    programada = viaje.get("hora_salida_programada")
    retraso = (round((salida - _con_zona(programada)).total_seconds() / 60, 1)
               if programada else None)

    cambios = {
        "estatus": settings.ESTATUS_VIAJE_EN_CURSO,
        "hora_salida_real": salida,
        "odometro_inicial_km": round(odometro, 1),
        "retraso_salida_min": retraso,
    }
    actualizado = repositorio.actualizar(identificador, cambios,
                                         incluir_inactivos=True)
    repositorio.marcar_vehiculo(viaje["vehiculo_id"], settings.ESTADO_EN_RUTA)
    return _publico(actualizado)


# ==========================================================================
# FINALIZAR  (§12.3, RN-J6)
# ==========================================================================
def finalizar(bd: Database, identificador: str,
              datos: dict[str, Any]) -> dict[str, Any]:
    """
    Registra el regreso, calcula los totales del viaje y libera la unidad.

    Aquí se actualiza el `odometro_actual_km` del vehículo. Es la promesa
    que hizo RN-V6 al prohibir capturarlo desde la ficha: se dijo que lo
    mantiene el cierre del viaje, y este es el cierre.
    """
    repositorio = RepositorioViajes(bd)
    viaje = repositorio.obtener(identificador, incluir_inactivos=True)
    _exigir_transicion(viaje, settings.ESTATUS_VIAJE_FINALIZADO)

    inicial = viaje.get("odometro_inicial_km")
    if inicial is None:
        raise ReglaDeNegocio(
            "El viaje no tiene odómetro inicial: no se registró la salida.")

    final = float(datos["odometro_final_km"])
    if final <= inicial:
        raise ReglaDeNegocio(
            f"El odómetro final ({final:,.1f} km) debe ser mayor que el "
            f"inicial ({inicial:,.1f} km) (RN-J6).",
            regla="J6",
            detalles=[{"odometro_inicial": inicial, "odometro_final": final}])

    regreso = _fecha_o_ahora(datos.get("hora_regreso_real"))
    salida = _con_zona(viaje.get("hora_salida_real"))
    if salida and regreso <= salida:
        raise ReglaDeNegocio(
            "La hora de regreso debe ser posterior a la de salida (RN-J6).",
            regla="J6")

    completadas = datos.get("total_entregas_completadas")
    if completadas is None:
        completadas = repositorio.contar_entregas(viaje["_id"],
                                                  solo_completadas=True)

    cambios = {
        "estatus": settings.ESTATUS_VIAJE_FINALIZADO,
        "hora_regreso_real": regreso,
        "odometro_final_km": round(final, 1),
        "km_recorridos": round(final - inicial, 1),
        "duracion_real_min": (round((regreso - salida).total_seconds() / 60, 1)
                              if salida else None),
        "total_entregas_completadas": int(completadas),
        "total_incidentes": repositorio.contar_incidentes(viaje["_id"]),
    }
    actualizado = repositorio.actualizar(identificador, cambios,
                                         incluir_inactivos=True)

    # El vehículo vuelve a estar disponible y con su odómetro al día.
    repositorio.marcar_vehiculo(viaje["vehiculo_id"],
                                settings.ESTADO_DISPONIBLE, odometro=final)
    return _publico(actualizado)


# ==========================================================================
# CANCELAR  (RN-J7)
# ==========================================================================
def cancelar(bd: Database, identificador: str, motivo: str) -> dict[str, Any]:
    """
    Cancela el viaje. Es la única forma de "quitarlo": no hay baja lógica.

    Si ya había salido, se libera la unidad, porque físicamente vuelve.
    """
    repositorio = RepositorioViajes(bd)
    viaje = repositorio.obtener(identificador, incluir_inactivos=True)
    _exigir_transicion(viaje, settings.ESTATUS_VIAJE_CANCELADO)

    estaba_en_curso = viaje.get("estatus") == settings.ESTATUS_VIAJE_EN_CURSO
    actualizado = repositorio.actualizar(
        identificador,
        {"estatus": settings.ESTATUS_VIAJE_CANCELADO,
         "motivo_cancelacion": motivo},
        incluir_inactivos=True)

    if estaba_en_curso:
        repositorio.marcar_vehiculo(viaje["vehiculo_id"],
                                    settings.ESTADO_DISPONIBLE)
    return _publico(actualizado)


# ==========================================================================
# VALIDACIONES  (RN-J3)
# ==========================================================================
def _validar_ruta(repositorio: RepositorioViajes, ruta_id: str) -> dict[str, Any]:
    ruta = repositorio.ruta(repositorio.a_object_id(ruta_id))
    if ruta is None:
        raise ReglaDeNegocio(f"No existe la ruta '{ruta_id}'.")
    if not ruta.get("activo", True):
        raise ReglaDeNegocio(
            f"La ruta {ruta['codigo_ruta']} está dada de baja y no se puede "
            "programar (RN-J3).", regla="J3")
    return ruta


def _validar_vehiculo(repositorio: RepositorioViajes,
                      vehiculo_id: str) -> dict[str, Any]:
    vehiculo = repositorio.vehiculo(repositorio.a_object_id(vehiculo_id))
    if vehiculo is None:
        raise ReglaDeNegocio(f"No existe el vehículo '{vehiculo_id}'.")
    if not vehiculo.get("activo", True):
        raise ReglaDeNegocio(
            f"El vehículo {vehiculo['codigo_vehiculo']} está dado de baja "
            "(RN-J3).", regla="J3")

    estado = vehiculo.get("estado_operativo")
    if estado != settings.ESTADO_DISPONIBLE:
        raise ReglaDeNegocio(
            f"El vehículo {vehiculo['codigo_vehiculo']} está {estado} y no "
            f"está disponible para una jornada (RN-J3).",
            regla="J3",
            detalles=[{"estado_operativo": estado}])
    return vehiculo


def _validar_operador(repositorio: RepositorioViajes,
                      operador_id: str) -> dict[str, Any]:
    """
    Comprueba que el operador pueda conducir hoy.

    Aquí se cobra RN-O3: de nada sirve impedir activar a alguien con la
    licencia vencida si luego se le puede programar un viaje igualmente.
    """
    operador = repositorio.operador(repositorio.a_object_id(operador_id))
    if operador is None:
        raise ReglaDeNegocio(f"No existe el operador '{operador_id}'.")
    if not operador.get("activo", True):
        raise ReglaDeNegocio(
            f"El operador {operador['codigo_operador']} está dado de baja "
            "(RN-J3).", regla="J3")
    if operador.get("estado") != settings.ESTADO_OPERADOR_ACTIVO:
        raise ReglaDeNegocio(
            f"El operador {operador['codigo_operador']} está "
            f"{operador.get('estado')} y no puede conducir (RN-J3).",
            regla="J3")

    vigencia = (operador.get("licencia") or {}).get("vigencia")
    if vigencia is None or _con_zona(vigencia) < _ahora():
        vencimiento = (f" (venció el {_con_zona(vigencia):%Y-%m-%d})"
                       if vigencia else " (sin licencia registrada)")
        raise ReglaDeNegocio(
            f"El operador {operador['codigo_operador']} no tiene licencia "
            f"vigente{vencimiento} y no puede conducir (RN-J3 / RN-O3).",
            regla="J3",
            detalles=[{"vigencia": (str(_con_zona(vigencia).date())
                                    if vigencia else None)}])
    return operador


def _validar_sin_viaje_abierto(repositorio: RepositorioViajes, campo: str,
                               identificador: ObjectId, quien: str) -> None:
    abierto = repositorio.viaje_abierto_de(campo, identificador)
    if abierto:
        raise ReglaDeNegocio(
            f"{quien} ya tiene el viaje {abierto['folio_viaje']} sin cerrar "
            f"({abierto['estatus']}) (RN-J3). Nadie puede estar en dos "
            "jornadas a la vez.",
            regla="J3",
            detalles=[{"folio_abierto": abierto["folio_viaje"]}])


def _exigir_transicion(viaje: dict[str, Any], destino: str) -> None:
    """RN-J2: el viaje avanza y nunca retrocede."""
    actual = viaje.get("estatus", settings.ESTATUS_VIAJE_PROGRAMADO)
    permitidos = settings.TRANSICIONES_ESTATUS_VIAJE.get(actual, ())
    if destino not in permitidos:
        cierre = ("Un viaje cerrado no se reabre: cada documento es el "
                  "histórico de lo que ocurrió (RN-J2)."
                  if not permitidos else
                  f"Desde {actual} solo se admite: {', '.join(permitidos)}.")
        raise ReglaDeNegocio(
            f"El viaje {viaje.get('folio_viaje')} está {actual} y no puede "
            f"pasar a {destino}. {cierre}",
            regla="J2",
            detalles=[{"estatus_actual": actual,
                       "transiciones_validas": list(permitidos)}])


# ==========================================================================
# INTERNO
# ==========================================================================
def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _a_datetime(valor: Any) -> datetime:
    if isinstance(valor, datetime):
        return valor if valor.tzinfo else valor.replace(tzinfo=timezone.utc)
    if isinstance(valor, date):
        return datetime(valor.year, valor.month, valor.day, tzinfo=timezone.utc)
    return datetime.fromisoformat(str(valor)).replace(tzinfo=timezone.utc)


def _con_zona(valor: datetime | None) -> datetime | None:
    if valor is None:
        return None
    return valor if valor.tzinfo else valor.replace(tzinfo=timezone.utc)


def _fecha_o_ahora(valor: Any) -> datetime:
    return _a_datetime(valor) if valor else _ahora()


def _hora_programada(fecha: datetime, hora: str | None) -> datetime:
    """Combina la fecha del viaje con la hora del plan de la ruta."""
    if not hora:
        return fecha
    try:
        horas, minutos = (int(parte) for parte in str(hora).split(":")[:2])
    except (ValueError, TypeError):
        return fecha
    return fecha.replace(hour=horas, minute=minutos, second=0, microsecond=0)


def _publico(documento: dict[str, Any]) -> dict[str, Any]:
    return ViajeSalida.desde_documento(documento).model_dump()
