"""
SIG-LOG — Sistema Integral de Gestión Logística
backend/services/entregas.py

REGLAS DEL MÓDULO ENTREGAS  (§11.6)

Esta es la colección crítica del proyecto. Todo lo que se construyó antes
—el ETL, el data warehouse, los modelos, el dashboard— se apoya en que el
retraso registrado aquí sea el que de verdad ocurrió.

Reglas de negocio (RN-E1 a RN-E7)
---------------------------------
RN-E1  El folio ENT-AAAAMMDD-NNNNN lo genera el sistema y es inmutable.

RN-E2  `tiempo_real_min`, `retraso_min` y `es_retraso` se CALCULAN al
       registrar la llegada; no se capturan nunca. Son las variables
       objetivo de la regresión y de la clasificación: un valor tecleado
       haría que los modelos aprendieran de un dato inventado.

RN-E3  El estatus sigue el catálogo RNP-08 y cada cambio queda en
       `historial_estatus` con quién lo hizo y cuándo. Sin esa constancia
       no se puede reconstruir qué pasó con una entrega.

RN-E4  No se registra la llegada de una entrega cuyo viaje no está
       EN_CURSO. No se puede entregar antes de salir, y una llegada
       registrada sobre un viaje cerrado contradiría su cierre.

RN-E5  Los campos denormalizados —`nombre_cliente`, `placa`,
       `nombre_operador`— se copian al crear y NO se editan. Su razón de
       ser (§10.4) es preservar el nombre histórico: la entrega de marzo
       debe conservar el nombre que el cliente tenía en marzo.

RN-E6  `causa_retraso` solo se acepta si la entrega llegó retrasada.
       Atribuir una causa a una entrega puntual es un error de captura, y
       ensuciaría el análisis de Pareto de causas.

RN-E7  Una entrega hereda del viaje su ruta, vehículo, operador y fecha.
       No se envían: pedirlos otra vez permitiría que la entrega
       contradijera al viaje que la contiene.
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

from backend.repositories.entregas import RepositorioEntregas
from backend.schemas.entregas import EntregaSalida
from backend.utils.errores import ReglaDeNegocio
from config import settings

# Transiciones válidas del estatus de la entrega (RNP-08).
TRANSICIONES_ENTREGA: dict[str, tuple[str, ...]] = {
    "PROGRAMADA": ("EN_RUTA", "CANCELADA"),
    "EN_RUTA": ("ENTREGADA", "NO_ENTREGADA", "CANCELADA"),
    "ENTREGADA": (),
    "NO_ENTREGADA": (),
    "CANCELADA": (),
}


# ==========================================================================
# CONSULTA
# ==========================================================================
def listar(bd: Database, *, saltar: int = 0, limite: int = 50,
           viaje_id: str | None = None, cliente_id: str | None = None,
           ruta_id: str | None = None, estatus: str | None = None,
           solo_retrasadas: bool | None = None,
           fecha_desde: date | None = None, fecha_hasta: date | None = None
           ) -> tuple[list[dict[str, Any]], int]:
    repositorio = RepositorioEntregas(bd)
    filtro: dict[str, Any] = {}

    if estatus:
        estatus = estatus.strip().upper()
        if estatus not in settings.CATALOGO_ESTATUS_ENTREGA:
            raise ReglaDeNegocio(
                f"Estatus '{estatus}' no pertenece al catálogo "
                f"{list(settings.CATALOGO_ESTATUS_ENTREGA)} (RNP-08).")
        filtro["estatus"] = estatus
    if solo_retrasadas is not None:
        filtro["es_retraso"] = 1 if solo_retrasadas else 0

    for campo, valor in (("viaje_id", viaje_id), ("cliente_id", cliente_id),
                         ("ruta_id", ruta_id)):
        if valor:
            filtro[campo] = repositorio.a_object_id(valor)

    rango: dict[str, Any] = {}
    if fecha_desde:
        rango["$gte"] = _a_datetime(fecha_desde)
    if fecha_hasta:
        rango["$lte"] = _a_datetime(fecha_hasta).replace(hour=23, minute=59,
                                                         second=59)
    if rango:
        filtro["fecha"] = rango

    documentos = repositorio.listar(
        filtro, saltar=saltar, limite=limite,
        orden=[("fecha", -1), ("orden_parada", 1)], incluir_inactivos=True)
    total = repositorio.contar(filtro, incluir_inactivos=True)
    return [_publico(d) for d in documentos], total


def obtener(bd: Database, identificador: str) -> dict[str, Any]:
    return _publico(
        RepositorioEntregas(bd).obtener(identificador, incluir_inactivos=True))


def resumen(bd: Database) -> dict[str, Any]:
    """Conteo por estatus y estado de la variable objetivo."""
    repositorio = RepositorioEntregas(bd)
    por_estatus = {
        estatus: repositorio.contar_por_estatus(estatus)
        for estatus in settings.CATALOGO_ESTATUS_ENTREGA
    }
    retraso = repositorio.estadisticas_de_retraso()
    medibles = retraso.get("medibles", 0)
    retrasadas = retraso.get("retrasadas", 0) or 0

    return {
        "total": repositorio.contar(incluir_inactivos=True),
        "por_estatus": por_estatus,
        "variable_objetivo": {
            "entregas_medibles": medibles,
            "retrasadas": retrasadas,
            "puntualidad_pct": (round(100 * (1 - retrasadas / medibles), 1)
                                if medibles else None),
            "retraso_medio_min": (round(retraso["retraso_medio"], 1)
                                  if retraso.get("retraso_medio") is not None
                                  else None),
            "retraso_maximo_min": retraso.get("retraso_maximo"),
            "umbral_min": settings.UMBRAL_RETRASO_MIN,
        },
        "alerta": (f"{medibles:,} entregas con retraso medible; "
                   f"{retrasadas:,} superan el umbral de "
                   f"{settings.UMBRAL_RETRASO_MIN} minutos (RNP-01)."
                   if medibles else
                   "Aún no hay entregas con llegada registrada."),
    }


# ==========================================================================
# ALTA  (RN-E1, RN-E5, RN-E7)
# ==========================================================================
def crear(bd: Database, datos: dict[str, Any], usuario: str) -> dict[str, Any]:
    """Da de alta una entrega dentro de un viaje."""
    repositorio = RepositorioEntregas(bd)
    viaje = _validar_viaje_abierto(repositorio, datos["viaje_id"])

    if repositorio.existe_parada(viaje["_id"], datos["orden_parada"]):
        raise ReglaDeNegocio(
            f"El viaje {viaje['folio_viaje']} ya tiene una entrega con orden "
            f"de parada {datos['orden_parada']}.")

    cliente = repositorio.cliente(repositorio.a_object_id(datos["cliente_id"]))
    if cliente is None:
        raise ReglaDeNegocio(f"No existe el cliente '{datos['cliente_id']}'.")

    documento = _armar_documento(
        repositorio, viaje, cliente,
        orden=datos["orden_parada"],
        tiempo_estimado=datos["tiempo_estimado_min"],
        distancia=datos["distancia_km"],
        hora_estimada=datos.get("hora_estimada_llegada"),
        observaciones=datos.get("observaciones"),
        usuario=usuario)
    return _publico(repositorio.crear(documento))


def generar_de_viaje(bd: Database, viaje_id: str,
                     usuario: str) -> dict[str, Any]:
    """
    Genera todas las entregas del viaje a partir de las paradas de su ruta.

    Es la operación normal: la ruta ya sabe a qué clientes se va, en qué
    orden y con qué tiempos. La hora estimada de cada parada se calcula
    acumulando los tiempos desde la salida programada, que es exactamente
    como se planifica un recorrido.
    """
    repositorio = RepositorioEntregas(bd)
    viaje = _validar_viaje_abierto(repositorio, viaje_id)

    if repositorio.del_viaje(viaje["_id"]):
        raise ReglaDeNegocio(
            f"El viaje {viaje['folio_viaje']} ya tiene entregas registradas. "
            "Agrégalas una a una si falta alguna.")

    ruta = repositorio.ruta(viaje["ruta_id"])
    if ruta is None or not ruta.get("paradas"):
        raise ReglaDeNegocio(
            "La ruta del viaje no tiene paradas: no hay entregas que generar.")

    salida = _con_zona(viaje.get("hora_salida_programada")) or _con_zona(
        viaje.get("fecha"))
    acumulado = 0.0
    creadas: list[dict[str, Any]] = []

    for parada in sorted(ruta["paradas"], key=lambda p: p["orden"]):
        cliente = repositorio.cliente(parada["cliente_id"])
        if cliente is None:
            raise ReglaDeNegocio(
                f"La parada {parada['orden']} apunta a un cliente que ya no "
                "existe. Corrige la ruta antes de generar las entregas.")

        acumulado += float(parada["tiempo_estimado_min"])
        documento = _armar_documento(
            repositorio, viaje, cliente,
            orden=parada["orden"],
            tiempo_estimado=parada["tiempo_estimado_min"],
            distancia=parada["distancia_desde_anterior_km"],
            hora_estimada=salida + timedelta(minutes=acumulado),
            observaciones=None,
            usuario=usuario)
        creadas.append(repositorio.crear(documento))

    return {
        "viaje": viaje["folio_viaje"],
        "generadas": len(creadas),
        "entregas": [_publico(e) for e in creadas],
    }


# ==========================================================================
# LLEGADA  (§12.3, RN-E2, RN-E4, RN-E6)
# ==========================================================================
def registrar_llegada(bd: Database, identificador: str, datos: dict[str, Any],
                      usuario: str) -> dict[str, Any]:
    """
    Registra la llegada real y CALCULA la variable objetivo.

    Es el momento más importante del sistema: aquí nacen `retraso_min` y
    `es_retraso`, que son lo que los modelos aprenden a predecir. Por eso
    se derivan de las horas y nunca se aceptan del formulario (RN-E2).
    """
    repositorio = RepositorioEntregas(bd)
    entrega = repositorio.obtener(identificador, incluir_inactivos=True)

    if entrega.get("hora_real_llegada") is not None:
        raise ReglaDeNegocio(
            f"La entrega {entrega['folio_entrega']} ya tiene registrada su "
            "llegada. Corregirla reescribiría la variable objetivo de los "
            "modelos.")

    # RN-E4 — no se entrega antes de salir
    viaje = repositorio.viaje(entrega["viaje_id"])
    if viaje is None:
        raise ReglaDeNegocio("La entrega no tiene un viaje válido asociado.")
    if viaje.get("estatus") != settings.ESTATUS_VIAJE_EN_CURSO:
        raise ReglaDeNegocio(
            f"El viaje {viaje['folio_viaje']} está "
            f"{viaje.get('estatus')} y no EN_CURSO (RN-E4): no se puede "
            "registrar una llegada sobre un viaje que no ha salido o que ya "
            "cerró.",
            regla="E4",
            detalles=[{"estatus_viaje": viaje.get("estatus")}])

    llegada = _fecha_o_ahora(datos.get("hora_real_llegada"))
    estimada = _con_zona(entrega.get("hora_estimada_llegada"))
    estimado_min = float(entrega.get("tiempo_estimado_min") or 0)

    # RN-E2 — aquí se calcula la variable objetivo
    retraso = (round((llegada - estimada).total_seconds() / 60, 1)
               if estimada else None)
    tiempo_real = (round(estimado_min + retraso, 1)
                   if retraso is not None else None)
    es_retraso = (int(retraso > settings.UMBRAL_RETRASO_MIN)
                  if retraso is not None else None)

    # RN-E6 — la causa solo tiene sentido si hubo retraso
    causa = datos.get("causa_retraso")
    if causa and not es_retraso:
        raise ReglaDeNegocio(
            f"La entrega llegó dentro del umbral de "
            f"{settings.UMBRAL_RETRASO_MIN} minutos, así que no se le puede "
            "atribuir una causa de retraso (RN-E6). Atribuir causas a "
            "entregas puntuales distorsionaría el análisis de Pareto.",
            regla="E6")

    entregada = datos.get("entregada", True)
    estatus = "ENTREGADA" if entregada else "NO_ENTREGADA"

    cambios: dict[str, Any] = {
        "hora_real_llegada": llegada,
        "tiempo_real_min": tiempo_real,
        "retraso_min": retraso,
        "es_retraso": es_retraso,
        "causa_retraso": causa,
        "estatus": estatus,
        "historial_estatus": _con_historial(entrega, estatus, usuario,
                                            motivo=datos.get("observaciones")),
    }
    if datos.get("observaciones"):
        cambios["observaciones"] = datos["observaciones"]

    return _publico(repositorio.actualizar(identificador, cambios,
                                           incluir_inactivos=True))


# ==========================================================================
# ESTATUS  (§12.3, RN-E3)
# ==========================================================================
def cambiar_estatus(bd: Database, identificador: str, estatus_nuevo: str,
                    usuario: str, motivo: str | None = None) -> dict[str, Any]:
    """Cambia el estatus dejando constancia de quién y cuándo (RN-E3)."""
    repositorio = RepositorioEntregas(bd)
    entrega = repositorio.obtener(identificador, incluir_inactivos=True)
    actual = entrega.get("estatus", "PROGRAMADA")

    if estatus_nuevo == actual:
        raise ReglaDeNegocio(f"La entrega ya está {actual}.")

    permitidos = TRANSICIONES_ENTREGA.get(actual, ())
    if estatus_nuevo not in permitidos:
        cierre = ("Una entrega cerrada no cambia de estatus: su registro es "
                  "el histórico de lo que pasó."
                  if not permitidos else
                  f"Desde {actual} solo se admite: {', '.join(permitidos)}.")
        raise ReglaDeNegocio(
            f"La entrega {entrega['folio_entrega']} está {actual} y no puede "
            f"pasar a {estatus_nuevo}. {cierre}",
            regla="E3",
            detalles=[{"estatus_actual": actual,
                       "transiciones_validas": list(permitidos)}])

    cambios = {
        "estatus": estatus_nuevo,
        "historial_estatus": _con_historial(entrega, estatus_nuevo, usuario,
                                            motivo),
    }
    return _publico(repositorio.actualizar(identificador, cambios,
                                           incluir_inactivos=True))


# ==========================================================================
# INTERNO
# ==========================================================================
def _validar_viaje_abierto(repositorio: RepositorioEntregas,
                           viaje_id: str) -> dict[str, Any]:
    viaje = repositorio.viaje(repositorio.a_object_id(viaje_id))
    if viaje is None:
        raise ReglaDeNegocio(f"No existe el viaje '{viaje_id}'.")
    if viaje.get("estatus") not in settings.ESTATUS_VIAJE_ABIERTOS:
        raise ReglaDeNegocio(
            f"El viaje {viaje['folio_viaje']} está {viaje.get('estatus')}: no "
            "se le pueden agregar entregas.",
            detalles=[{"estatus_viaje": viaje.get("estatus")}])
    return viaje


def _armar_documento(repositorio: RepositorioEntregas, viaje: dict[str, Any],
                     cliente: dict[str, Any], *, orden: int,
                     tiempo_estimado: float, distancia: float,
                     hora_estimada: Any, observaciones: str | None,
                     usuario: str) -> dict[str, Any]:
    """
    Construye el documento con la denormalización de §10.4.

    Los nombres y la placa se copian AHORA: si mañana el cliente cambia de
    razón social, esta entrega seguirá diciendo con quién se operó hoy.
    """
    vehiculo = repositorio.vehiculo(viaje["vehiculo_id"]) or {}
    operador = repositorio.operador(viaje["operador_id"]) or {}
    fecha = _con_zona(viaje.get("fecha"))

    return {
        "folio_entrega": repositorio.siguiente_folio(fecha),      # RN-E1
        "viaje_id": viaje["_id"],
        "ruta_id": viaje["ruta_id"],
        "cliente_id": cliente["_id"],
        "nombre_cliente": cliente.get("nombre"),                  # §10.4
        "vehiculo_id": viaje["vehiculo_id"],
        "placa": vehiculo.get("placa"),                           # §10.4
        "operador_id": viaje["operador_id"],
        "nombre_operador": operador.get("nombre_completo"),       # §10.4
        "orden_parada": int(orden),
        "fecha": fecha,
        "hora_estimada_llegada": (_con_zona(hora_estimada) if hora_estimada
                                  else _estimada_por_defecto(viaje, orden,
                                                             tiempo_estimado)),
        "hora_real_llegada": None,
        "hora_estimada_recalculada": None,
        "tiempo_estimado_min": round(float(tiempo_estimado), 1),
        "tiempo_real_min": None,
        "retraso_min": None,
        "es_retraso": None,
        "distancia_km": round(float(distancia), 2),
        "estatus": "PROGRAMADA",
        "historial_estatus": [_evento("PROGRAMADA", usuario, None)],
        "incidentes_ids": [],
        "causa_retraso": None,
        "observaciones": observaciones,
    }


def _estimada_por_defecto(viaje: dict[str, Any], orden: int,
                          tiempo_estimado: float) -> datetime:
    """ETA aproximado cuando no se envía: salida + tiempo de esta parada."""
    salida = _con_zona(viaje.get("hora_salida_programada")) or _con_zona(
        viaje.get("fecha"))
    return salida + timedelta(minutes=float(tiempo_estimado) * orden)


def _evento(estatus: str, usuario: str, motivo: str | None) -> dict[str, Any]:
    """Entrada del historial: qué, cuándo y QUIÉN (§11.6)."""
    evento = {"estatus": estatus, "fecha_hora": _ahora(), "usuario": usuario}
    if motivo:
        evento["motivo"] = motivo
    return evento


def _con_historial(entrega: dict[str, Any], estatus: str, usuario: str,
                   motivo: str | None) -> list[dict[str, Any]]:
    return [*entrega.get("historial_estatus", []),
            _evento(estatus, usuario, motivo)]


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _a_datetime(valor: Any) -> datetime:
    if isinstance(valor, datetime):
        return valor if valor.tzinfo else valor.replace(tzinfo=timezone.utc)
    if isinstance(valor, date):
        return datetime(valor.year, valor.month, valor.day, tzinfo=timezone.utc)
    return datetime.fromisoformat(str(valor)).replace(tzinfo=timezone.utc)


def _con_zona(valor: Any) -> datetime | None:
    if valor is None:
        return None
    return _a_datetime(valor)


def _fecha_o_ahora(valor: Any) -> datetime:
    return _a_datetime(valor) if valor else _ahora()


def _publico(documento: dict[str, Any]) -> dict[str, Any]:
    return EntregaSalida.desde_documento(documento).model_dump()
