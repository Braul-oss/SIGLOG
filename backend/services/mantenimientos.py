"""
SIG-LOG — Sistema Integral de Gestión Logística
backend/services/mantenimientos.py

REGLAS DEL MÓDULO MANTENIMIENTOS  (§11.9) Y ALERTA RF-16

Último módulo del dominio, y el que cierra la promesa que quedaba abierta:
RN-V6 prohibió capturar `fecha_ultimo_mantenimiento` y
`fecha_proximo_mantenimiento` desde la ficha del vehículo porque "se
derivan de la colección mantenimientos". Aquí se derivan.

Reglas de negocio (RN-M1 a RN-M7)
---------------------------------
RN-M1  El folio MTO-AAAAMMDD-NNNN lo genera el sistema y es inmutable.

RN-M2  El estatus va PROGRAMADO → REALIZADO o VENCIDO, y VENCIDO →
       REALIZADO. Esa última transición es deliberada: un servicio vencido
       se acaba haciendo, y hacerlo es precisamente lo que devuelve el
       vehículo a operación. De REALIZADO no se sale.

RN-M3  Una unidad no tiene dos servicios abiertos a la vez. Programar otro
       sobre uno pendiente duplicaría el trabajo y descuadraría la alerta
       de RF-16.

RN-M4  `duracion_dias` y `proximo_mantenimiento_fecha` se calculan al
       realizar el servicio. La próxima fecha sale de sumar la
       periodicidad de RNP-04 a la fecha realizada.

RN-M5  Realizar el servicio actualiza las fechas de mantenimiento del
       vehículo. Es la contraparte de RN-V6.

RN-M6  (RF-16) Un mantenimiento VENCIDO deja al vehículo EN_MANTENIMIENTO,
       fuera de operación. Al realizarlo vuelve a DISPONIBLE, pero solo si
       no le quedan otros vencidos: una unidad con dos servicios vencidos
       no vuelve a la calle por atender uno.

RN-M7  Un servicio no se da por vencido antes de su fecha programada.
       Vencer es constatar un incumplimiento, no anticiparlo.

Sobre la periodicidad (RNP-04)
------------------------------
El documento recomendaba la opción (c) —"lo primero que ocurra entre
calendario y kilometraje"—, pero la simulación implementó la (a): cada 30
días de calendario, y sobre esos datos se construyeron el DW y la variable
`dias_desde_mantenimiento`. Se mantiene el calendario para no contradecir
lo que el proyecto ya opera; pasar a la (c) sería un cambio de regla que
habría que acordar, no un ajuste de constante.
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from pymongo.database import Database

from backend.repositories.mantenimientos import RepositorioMantenimientos
from backend.schemas.mantenimientos import MantenimientoSalida
from backend.utils.errores import ReglaDeNegocio
from config import settings

CAMPOS_CALCULADOS = ("estatus", "duracion_dias", "proximo_mantenimiento_fecha",
                     "fecha_realizada", "odometro_km", "costo")


# ==========================================================================
# CONSULTA
# ==========================================================================
def listar(bd: Database, *, saltar: int = 0, limite: int = 50,
           vehiculo_id: str | None = None, tipo: str | None = None,
           estatus: str | None = None, fecha_desde: date | None = None,
           fecha_hasta: date | None = None
           ) -> tuple[list[dict[str, Any]], int]:
    repositorio = RepositorioMantenimientos(bd)
    filtro: dict[str, Any] = {}

    if tipo:
        tipo = tipo.strip().upper()
        if tipo not in settings.CATALOGO_TIPO_MANTENIMIENTO:
            raise ReglaDeNegocio(
                f"Tipo '{tipo}' no pertenece al catálogo "
                f"{list(settings.CATALOGO_TIPO_MANTENIMIENTO)}.")
        filtro["tipo"] = tipo
    if estatus:
        estatus = estatus.strip().upper()
        if estatus not in settings.CATALOGO_ESTATUS_MANTENIMIENTO:
            raise ReglaDeNegocio(
                f"Estatus '{estatus}' no pertenece al catálogo "
                f"{list(settings.CATALOGO_ESTATUS_MANTENIMIENTO)}.")
        filtro["estatus"] = estatus
    if vehiculo_id:
        filtro["vehiculo_id"] = repositorio.a_object_id(vehiculo_id)

    rango: dict[str, Any] = {}
    if fecha_desde:
        rango["$gte"] = _a_datetime(fecha_desde)
    if fecha_hasta:
        rango["$lte"] = _a_datetime(fecha_hasta).replace(hour=23, minute=59,
                                                         second=59)
    if rango:
        filtro["fecha_programada"] = rango

    documentos = repositorio.listar(
        filtro, saltar=saltar, limite=limite,
        orden=[("fecha_programada", -1)], incluir_inactivos=True)
    total = repositorio.contar(filtro, incluir_inactivos=True)
    return [_publico(d) for d in documentos], total


def obtener(bd: Database, identificador: str) -> dict[str, Any]:
    return _publico(
        RepositorioMantenimientos(bd).obtener(identificador,
                                              incluir_inactivos=True))


def pendientes(bd: Database, dias_aviso: int | None = None) -> dict[str, Any]:
    """
    RF-16: qué vehículos requieren atención.

    Separa tres situaciones que exigen respuestas distintas: los VENCIDOS
    —que ya sacaron la unidad de operación—, los ATRASADOS —programados
    cuya fecha pasó pero que aún no se han declarado vencidos— y los
    PRÓXIMOS, que todavía se pueden planificar sin parar nada.
    """
    repositorio = RepositorioMantenimientos(bd)
    dias = dias_aviso if dias_aviso is not None else settings.DIAS_AVISO_MANTENIMIENTO
    grupos = repositorio.pendientes(dias)

    vencidos = len(grupos["vencidos"])
    atrasados = len(grupos["atrasados"])
    proximos = len(grupos["proximos"])

    if vencidos:
        alerta = (f"{vencidos} servicio(s) vencido(s): esas unidades están "
                  "fuera de operación hasta que se atiendan.")
    elif atrasados:
        alerta = (f"{atrasados} servicio(s) con la fecha ya pasada y sin "
                  "declarar vencidos.")
    elif proximos:
        alerta = (f"{proximos} servicio(s) por vencer en los próximos "
                  f"{dias} días.")
    else:
        alerta = "No hay mantenimientos pendientes ni próximos."

    return {
        "dias_anticipacion": dias,
        "vencidos": [_pendiente_publico(m) for m in grupos["vencidos"]],
        "atrasados": [_pendiente_publico(m) for m in grupos["atrasados"]],
        "proximos": [_pendiente_publico(m) for m in grupos["proximos"]],
        "total_vencidos": vencidos,
        "total_atrasados": atrasados,
        "total_proximos": proximos,
        "alerta": alerta,
    }


def resumen(bd: Database) -> dict[str, Any]:
    repositorio = RepositorioMantenimientos(bd)
    por_tipo = {t: repositorio.contar({"tipo": t}, incluir_inactivos=True)
                for t in settings.CATALOGO_TIPO_MANTENIMIENTO}
    por_estatus = {
        e: repositorio.contar({"estatus": e}, incluir_inactivos=True)
        for e in settings.CATALOGO_ESTATUS_MANTENIMIENTO
    }
    return {
        "total": repositorio.contar(incluir_inactivos=True),
        "por_tipo": por_tipo,
        "por_estatus": por_estatus,
        "periodicidad_dias": settings.DIAS_PERIODICIDAD_MANTENIMIENTO,
        "costo_por_vehiculo": repositorio.costo_por_vehiculo(),
        "alerta": (f"{por_estatus[settings.ESTATUS_MTTO_VENCIDO]} "
                   "mantenimiento(s) vencido(s)."
                   if por_estatus[settings.ESTATUS_MTTO_VENCIDO]
                   else "Ningún mantenimiento vencido."),
    }


# ==========================================================================
# PROGRAMAR
# ==========================================================================
def programar(bd: Database, datos: dict[str, Any]) -> dict[str, Any]:
    """Programa el servicio (RN-M1, RN-M3)."""
    repositorio = RepositorioMantenimientos(bd)
    vehiculo = repositorio.vehiculo(
        repositorio.a_object_id(datos["vehiculo_id"]))
    if vehiculo is None:
        raise ReglaDeNegocio(f"No existe el vehículo '{datos['vehiculo_id']}'.")

    # RN-M3 — una unidad, un servicio abierto
    abierto = repositorio.abierto_del_vehiculo(vehiculo["_id"])
    if abierto:
        raise ReglaDeNegocio(
            f"El vehículo {vehiculo['codigo_vehiculo']} ya tiene el servicio "
            f"{abierto['folio_mantenimiento']} sin realizar "
            f"({abierto['estatus']}) (RN-M3). Atiéndelo antes de programar "
            "otro.",
            regla="M3",
            detalles=[{"folio_abierto": abierto["folio_mantenimiento"],
                       "estatus": abierto["estatus"]}])

    programada = _a_datetime(datos["fecha_programada"]).replace(hour=8)
    documento = {
        "folio_mantenimiento": repositorio.siguiente_folio(programada),  # RN-M1
        "vehiculo_id": vehiculo["_id"],
        "tipo": datos["tipo"],
        "estatus": settings.ESTATUS_MTTO_PROGRAMADO,
        "fecha_programada": programada,
        "fecha_realizada": None,
        "proximo_mantenimiento_fecha": None,
        "odometro_km": None,
        "costo": None,
        "costo_estimado": datos.get("costo_estimado"),
        "duracion_dias": None,
        "descripcion": datos.get("descripcion"),
    }
    return _publico(repositorio.crear(documento))


def actualizar(bd: Database, identificador: str,
               cambios: dict[str, Any]) -> dict[str, Any]:
    """Edita el servicio mientras siga sin realizarse."""
    repositorio = RepositorioMantenimientos(bd)

    prohibidos = [c for c in cambios if c in CAMPOS_CALCULADOS]
    if prohibidos:
        raise ReglaDeNegocio(
            f"Estos campos no se editan desde aquí: {', '.join(prohibidos)}. "
            "Realizar o vencer el servicio tiene sus propios endpoints, y "
            "la duración y la próxima fecha se calculan (RN-M4).",
            regla="M4")
    if not cambios:
        raise ReglaDeNegocio("No se envió ningún campo que actualizar.")

    mantenimiento = repositorio.obtener(identificador, incluir_inactivos=True)
    if mantenimiento.get("estatus") == settings.ESTATUS_MTTO_REALIZADO:
        raise ReglaDeNegocio(
            f"El servicio {mantenimiento['folio_mantenimiento']} ya está "
            "REALIZADO: es el registro de lo que se hizo y no se edita.",
            regla="M2")

    if "fecha_programada" in cambios:
        cambios["fecha_programada"] = _a_datetime(
            cambios["fecha_programada"]).replace(hour=8)

    return _publico(repositorio.actualizar(identificador, cambios,
                                           incluir_inactivos=True))


# ==========================================================================
# REALIZAR  (RN-M4, RN-M5, RN-M6)
# ==========================================================================
def realizar(bd: Database, identificador: str,
             datos: dict[str, Any]) -> dict[str, Any]:
    """
    Registra el servicio efectuado y devuelve la unidad a operación.

    Es el acto que cumple RN-V6: aquí se escriben las fechas de
    mantenimiento del vehículo, que su propia ficha no deja capturar.
    """
    repositorio = RepositorioMantenimientos(bd)
    mantenimiento = repositorio.obtener(identificador, incluir_inactivos=True)
    _exigir_transicion(mantenimiento, settings.ESTATUS_MTTO_REALIZADO)

    realizada = (_a_datetime(datos["fecha_realizada"]).replace(hour=8)
                 if datos.get("fecha_realizada") else _ahora())
    programada = _con_zona(mantenimiento["fecha_programada"])

    if realizada < programada - timedelta(days=1):
        raise ReglaDeNegocio(
            f"La fecha de realización ({realizada:%Y-%m-%d}) es anterior a la "
            f"programada ({programada:%Y-%m-%d}). Si el servicio se adelantó, "
            "corrige antes la fecha programada.")

    # RN-M4 — duración y próxima fecha
    duracion = datos.get("duracion_dias")
    if duracion is None:
        duracion = max((realizada - programada).days, 0)
    proxima = realizada + timedelta(
        days=settings.DIAS_PERIODICIDAD_MANTENIMIENTO)

    cambios = {
        "estatus": settings.ESTATUS_MTTO_REALIZADO,
        "fecha_realizada": realizada,
        "odometro_km": round(float(datos["odometro_km"]), 1),
        "costo": round(float(datos["costo"]), 2),
        "duracion_dias": float(duracion),
        "proximo_mantenimiento_fecha": proxima,
    }
    if datos.get("descripcion"):
        cambios["descripcion"] = datos["descripcion"]

    actualizado = repositorio.actualizar(identificador, cambios,
                                         incluir_inactivos=True)

    # RN-M5 y RN-M6 — efecto sobre el vehículo
    vehiculo = repositorio.vehiculo(mantenimiento["vehiculo_id"])
    cambios_vehiculo: dict[str, Any] = {
        "fecha_ultimo_mantenimiento": realizada,
        "fecha_proximo_mantenimiento": proxima,
    }
    pendientes_vencidos = repositorio.vencidos_del_vehiculo(
        mantenimiento["vehiculo_id"], excluir=mantenimiento["_id"])
    if (vehiculo and vehiculo.get("estado_operativo")
            == settings.ESTADO_EN_MANTENIMIENTO and not pendientes_vencidos):
        cambios_vehiculo["estado_operativo"] = settings.ESTADO_DISPONIBLE

    repositorio.actualizar_vehiculo(mantenimiento["vehiculo_id"],
                                    cambios_vehiculo)

    resultado = _publico(actualizado)
    resultado["vehiculo_liberado"] = (
        "estado_operativo" in cambios_vehiculo)
    resultado["vencidos_restantes"] = pendientes_vencidos
    return resultado


# ==========================================================================
# VENCER  (RF-16, RN-M6, RN-M7)
# ==========================================================================
def vencer(bd: Database, identificador: str,
           motivo: str | None = None) -> dict[str, Any]:
    """
    Declara el servicio vencido y saca la unidad de operación.

    Es la mitad operativa de RF-16: la alerta avisa, y esta acción es la
    que impide que un vehículo sin mantenimiento salga a ruta.
    """
    repositorio = RepositorioMantenimientos(bd)
    mantenimiento = repositorio.obtener(identificador, incluir_inactivos=True)
    _exigir_transicion(mantenimiento, settings.ESTATUS_MTTO_VENCIDO)

    # RN-M7 — vencer es constatar un incumplimiento, no anticiparlo
    programada = _con_zona(mantenimiento["fecha_programada"])
    if programada > _ahora():
        raise ReglaDeNegocio(
            f"El servicio {mantenimiento['folio_mantenimiento']} está "
            f"programado para el {programada:%Y-%m-%d}, que aún no llega "
            "(RN-M7). No se puede dar por vencido por anticipado.",
            regla="M7",
            detalles=[{"fecha_programada": str(programada.date())}])

    cambios: dict[str, Any] = {"estatus": settings.ESTATUS_MTTO_VENCIDO}
    if motivo:
        cambios["motivo_vencimiento"] = motivo
    actualizado = repositorio.actualizar(identificador, cambios,
                                         incluir_inactivos=True)

    # RN-M6 — la unidad queda fuera de operación
    repositorio.actualizar_vehiculo(
        mantenimiento["vehiculo_id"],
        {"estado_operativo": settings.ESTADO_EN_MANTENIMIENTO})

    resultado = _publico(actualizado)
    resultado["vehiculo_fuera_de_operacion"] = True
    return resultado


# ==========================================================================
# INTERNO
# ==========================================================================
def _exigir_transicion(mantenimiento: dict[str, Any], destino: str) -> None:
    """RN-M2."""
    actual = mantenimiento.get("estatus", settings.ESTATUS_MTTO_PROGRAMADO)
    permitidos = settings.TRANSICIONES_ESTATUS_MANTENIMIENTO.get(actual, ())
    if destino not in permitidos:
        cierre = ("Un servicio realizado es el registro de lo que se hizo y "
                  "no cambia de estatus."
                  if not permitidos else
                  f"Desde {actual} solo se admite: {', '.join(permitidos)}.")
        raise ReglaDeNegocio(
            f"El servicio {mantenimiento.get('folio_mantenimiento')} está "
            f"{actual} y no puede pasar a {destino}. {cierre}",
            regla="M2",
            detalles=[{"estatus_actual": actual,
                       "transiciones_validas": list(permitidos)}])


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _a_datetime(valor: Any) -> datetime:
    if isinstance(valor, datetime):
        return valor if valor.tzinfo else valor.replace(tzinfo=timezone.utc)
    if isinstance(valor, date):
        return datetime(valor.year, valor.month, valor.day, tzinfo=timezone.utc)
    return datetime.fromisoformat(str(valor)).replace(tzinfo=timezone.utc)


def _con_zona(valor: Any) -> datetime:
    return _a_datetime(valor)


def _publico(documento: dict[str, Any]) -> dict[str, Any]:
    return MantenimientoSalida.desde_documento(documento).model_dump()


def _pendiente_publico(fila: dict[str, Any]) -> dict[str, Any]:
    salida = dict(fila)
    if isinstance(salida.get("fecha_programada"), datetime):
        salida["fecha_programada"] = salida["fecha_programada"].isoformat()
    return salida
