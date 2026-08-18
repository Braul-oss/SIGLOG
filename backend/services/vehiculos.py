"""
SIG-LOG — Sistema Integral de Gestión Logística
backend/services/vehiculos.py

REGLAS DEL MÓDULO VEHÍCULOS  (§11.2)

Reglas de negocio (RN-V1 a RN-V6)
---------------------------------
RN-V1  `codigo_vehiculo` lo genera el sistema (VEH-NNN) y es inmutable.

RN-V2  La placa es única en la flotilla. Sí se puede corregir —un error de
       captura o un reemplazo de placas ocurren—, pero no puede chocar con
       la de otra unidad.

RN-V3  (RN-04 del documento) Un vehículo tiene UNA sola ruta y una ruta UN
       solo vehículo. Se comprueba en LOS DOS SENTIDOS: que la ruta esté
       libre y que el vehículo no cubra ya otra. Sin la segunda, mover un
       vehículo de la ruta A a la B dejaba a la A sin unidad en silencio,
       que es exactamente el estado que RN-R6 impide al dar de baja una
       ruta. Además se actualizan los dos extremos de la relación: si solo
       se escribiera uno, la ruta seguiría diciendo que la cubre un
       vehículo que ya no la tiene.

RN-V4  No se puede dar de baja un vehículo con ruta asignada: la ruta
       quedaría sin unidad y el viaje siguiente no podría salir. Hay que
       desasignarlo antes.

RN-V5  El estado operativo es una máquina de estados, no un campo libre.
       De EN_MANTENIMIENTO no se sale a EN_RUTA sin pasar por DISPONIBLE:
       el taller libera la unidad y solo entonces puede salir. BAJA no es
       destino de ninguna transición; se alcanza dando de baja el
       vehículo, para que ese camino pase por sus comprobaciones.

RN-V6  `odometro_actual_km`, `rendimiento_real_km_l` y las fechas de
       mantenimiento no se capturan por el API después del alta: los
       mantienen la operación y el ETL. Un dato tecleado que contradijera
       al calculado haría que el dashboard y la operación dijeran cosas
       distintas del mismo vehículo.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from backend.repositories.vehiculos import RepositorioVehiculos
from backend.schemas.vehiculos import VehiculoSalida
from backend.utils.errores import RecursoDuplicado, ReglaDeNegocio
from config import settings

# Campos que el API no acepta modificar tras el alta (RN-V6).
CAMPOS_CALCULADOS = (
    "odometro_actual_km", "rendimiento_real_km_l",
    "fecha_ultimo_mantenimiento", "fecha_proximo_mantenimiento",
    "estado_operativo", "ruta_asignada_id",
)


# ==========================================================================
# CONSULTA
# ==========================================================================
def listar(bd: Database, *, saltar: int = 0, limite: int = 50,
           busqueda: str | None = None, estado: str | None = None,
           tipo_vehiculo: str | None = None, incluir_inactivos: bool = False
           ) -> tuple[list[dict[str, Any]], int]:
    repositorio = RepositorioVehiculos(bd)
    filtro: dict[str, Any] = {}

    if busqueda:
        texto = busqueda.strip()
        filtro["$or"] = [
            {"placa": {"$regex": texto, "$options": "i"}},
            {"codigo_vehiculo": {"$regex": texto, "$options": "i"}},
            {"marca": {"$regex": texto, "$options": "i"}},
            {"modelo": {"$regex": texto, "$options": "i"}},
        ]
    if estado:
        estado = estado.strip().upper()
        if estado not in settings.CATALOGO_ESTADO_VEHICULO:
            raise ReglaDeNegocio(
                f"Estado '{estado}' no pertenece al catálogo "
                f"{list(settings.CATALOGO_ESTADO_VEHICULO)}.")
        filtro["estado_operativo"] = estado
    if tipo_vehiculo:
        tipo_vehiculo = tipo_vehiculo.strip().upper()
        if tipo_vehiculo not in settings.CATALOGO_TIPO_VEHICULO:
            raise ReglaDeNegocio(
                f"Tipo '{tipo_vehiculo}' no pertenece al catálogo "
                f"{list(settings.CATALOGO_TIPO_VEHICULO)}.")
        filtro["tipo_vehiculo"] = tipo_vehiculo

    documentos = repositorio.listar(
        filtro, saltar=saltar, limite=limite,
        orden=[("codigo_vehiculo", 1)], incluir_inactivos=incluir_inactivos)
    total = repositorio.contar(filtro, incluir_inactivos=incluir_inactivos)
    return [_publico(d) for d in documentos], total


def obtener(bd: Database, identificador: str) -> dict[str, Any]:
    return _publico(
        RepositorioVehiculos(bd).obtener(identificador, incluir_inactivos=True))


def resumen(bd: Database) -> dict[str, Any]:
    repositorio = RepositorioVehiculos(bd)
    total = repositorio.contar(incluir_inactivos=True)
    activos = repositorio.contar()
    return {
        "total": total,
        "activos": activos,
        "inactivos": total - activos,
        "por_estado": {
            estado: repositorio.contar({"estado_operativo": estado})
            for estado in settings.CATALOGO_ESTADO_VEHICULO
        },
        "por_tipo": {
            tipo: repositorio.contar({"tipo_vehiculo": tipo})
            for tipo in settings.CATALOGO_TIPO_VEHICULO
        },
        "con_ruta_asignada": repositorio.contar(
            {"ruta_asignada_id": {"$ne": None}}),
    }


def rendimiento(bd: Database, identificador: str,
                limite_cargas: int = 30) -> dict[str, Any]:
    """
    Historial de rendimiento del vehículo (§12.3).

    Combina tres fuentes que YA EXISTEN, sin recalcular ninguna:
      · el rendimiento nominal, de la ficha del vehículo;
      · el `rendimiento_km_l` de cada carga, que registra `combustible`;
      · el agregado del periodo, que el ETL dejó en `dim_vehiculo`.

    Si el ETL no ha corrido, el agregado viene vacío y se dice
    explícitamente, en lugar de calcularlo aquí y arriesgar que difiera del
    que muestra el dashboard.
    """
    repositorio = RepositorioVehiculos(bd)
    vehiculo = repositorio.obtener(identificador, incluir_inactivos=True)

    cargas = repositorio.cargas_de_combustible(vehiculo["_id"], limite_cargas)
    metricas = repositorio.metricas_del_dw(vehiculo["_id"]) or {}
    metricas.pop("_id", None)

    nominal = vehiculo.get("rendimiento_nominal_km_l")
    real = metricas.get("rendimiento_real_km_l")

    return {
        "vehiculo": {
            "id": str(vehiculo["_id"]),
            "codigo_vehiculo": vehiculo.get("codigo_vehiculo"),
            "placa": vehiculo.get("placa"),
            "tipo_vehiculo": vehiculo.get("tipo_vehiculo"),
        },
        "rendimiento_nominal_km_l": nominal,
        "rendimiento_real_km_l": real,
        "desviacion_pct": metricas.get("desviacion_rendimiento_pct"),
        "metricas_periodo": metricas,
        "cargas": [_carga_publica(c) for c in cargas],
        "total_cargas": len(cargas),
        "origen_agregado": ("dim_vehiculo (ETL)" if metricas
                            else "no disponible: ejecuta python -m etl.run_etl"),
        "lectura": _interpretar_rendimiento(nominal, real, len(cargas)),
    }


# ==========================================================================
# ALTA
# ==========================================================================
def crear(bd: Database, datos: dict[str, Any]) -> dict[str, Any]:
    repositorio = RepositorioVehiculos(bd)

    if repositorio.por_placa(datos["placa"]):
        raise RecursoDuplicado(
            f"Ya existe un vehículo con la placa '{datos['placa']}' (RN-V2).")

    documento = {
        **datos,
        "codigo_vehiculo": repositorio.siguiente_codigo(),      # RN-V1
        # Nace disponible y sin ruta: asignarla es una decisión aparte,
        # con su propia comprobación de RN-04.
        "estado_operativo": settings.ESTADO_DISPONIBLE,
        "ruta_asignada_id": None,
        "fecha_ultimo_mantenimiento": None,
        "fecha_proximo_mantenimiento": None,
        "rendimiento_real_km_l": None,                          # lo calcula el ETL
    }
    try:
        creado = repositorio.crear(documento)
    except DuplicateKeyError as exc:
        raise RecursoDuplicado(
            "La placa o el código ya existen. Vuelve a intentarlo.") from exc
    return _publico(creado)


# ==========================================================================
# EDICIÓN
# ==========================================================================
def actualizar(bd: Database, identificador: str,
               cambios: dict[str, Any]) -> dict[str, Any]:
    repositorio = RepositorioVehiculos(bd)

    if "codigo_vehiculo" in cambios:
        raise ReglaDeNegocio(
            "El código de vehículo no se puede cambiar (RN-V1).", regla="V1")
    prohibidos = [c for c in cambios if c in CAMPOS_CALCULADOS]
    if prohibidos:
        raise ReglaDeNegocio(
            f"Estos campos no se editan desde aquí (RN-V6): "
            f"{', '.join(prohibidos)}. El estado tiene su propio endpoint, "
            "la ruta también, y el odómetro, el rendimiento real y las "
            "fechas de mantenimiento los mantienen la operación y el ETL.",
            regla="V6")
    if not cambios:
        raise ReglaDeNegocio("No se envió ningún campo que actualizar.")

    vehiculo = repositorio.obtener(identificador, incluir_inactivos=True)

    if "placa" in cambios and repositorio.por_placa(cambios["placa"],
                                                    excluir=vehiculo["_id"]):
        raise RecursoDuplicado(
            f"Otro vehículo ya tiene la placa '{cambios['placa']}' (RN-V2).")

    return _publico(repositorio.actualizar(identificador, cambios,
                                           incluir_inactivos=True))


def cambiar_estado(bd: Database, identificador: str, estado_nuevo: str,
                   motivo: str | None = None) -> dict[str, Any]:
    """Aplica RN-V5: solo se permiten las transiciones declaradas."""
    repositorio = RepositorioVehiculos(bd)
    vehiculo = repositorio.obtener(identificador, incluir_inactivos=True)
    estado_actual = vehiculo.get("estado_operativo", settings.ESTADO_DISPONIBLE)

    if estado_nuevo == settings.ESTADO_BAJA:
        raise ReglaDeNegocio(
            "BAJA no se asigna por aquí (RN-V5). Da de baja el vehículo con "
            "DELETE, para que la operación pase por sus comprobaciones.",
            regla="V5")
    if estado_nuevo == estado_actual:
        raise ReglaDeNegocio(
            f"El vehículo ya está en estado {estado_actual}.")

    permitidos = settings.TRANSICIONES_ESTADO_VEHICULO.get(estado_actual, ())
    if estado_nuevo not in permitidos:
        raise ReglaDeNegocio(
            f"No se puede pasar de {estado_actual} a {estado_nuevo} (RN-V5). "
            f"Desde {estado_actual} solo se admite: "
            f"{', '.join(permitidos) if permitidos else 'ningún cambio'}.",
            regla="V5",
            detalles=[{"estado_actual": estado_actual,
                       "transiciones_validas": list(permitidos)}])

    cambios: dict[str, Any] = {"estado_operativo": estado_nuevo}
    if motivo:
        cambios["motivo_ultimo_cambio_estado"] = motivo
    return _publico(repositorio.actualizar(identificador, cambios,
                                           incluir_inactivos=True))


def asignar_ruta(bd: Database, identificador: str,
                 ruta_id: str | None) -> dict[str, Any]:
    """
    Asigna o quita la ruta del vehículo, aplicando RN-V3 (RN-04).

    Escribe los dos extremos de la relación para que no queden
    contradiciéndose.
    """
    repositorio = RepositorioVehiculos(bd)
    vehiculo = repositorio.obtener(identificador, incluir_inactivos=True)
    ruta_anterior = vehiculo.get("ruta_asignada_id")

    if ruta_id is None:                                   # desasignar
        if ruta_anterior is None:
            raise ReglaDeNegocio("El vehículo no tiene ninguna ruta asignada.")
        repositorio.sincronizar_ruta(ruta_anterior, None)
        return _publico(repositorio.actualizar(
            identificador, {"ruta_asignada_id": None}, incluir_inactivos=True))

    objeto_ruta = repositorio.a_object_id(ruta_id)
    ruta = repositorio.ruta(objeto_ruta)
    if ruta is None:
        raise ReglaDeNegocio(f"No existe la ruta con identificador '{ruta_id}'.")

    # RN-04, primer sentido: la ruta no puede estar tomada por otro vehículo.
    ocupante = repositorio.vehiculo_de_la_ruta(objeto_ruta,
                                               excluir=vehiculo["_id"])
    if ocupante:
        raise ReglaDeNegocio(
            f"La ruta {ruta.get('codigo_ruta')} ya está asignada al vehículo "
            f"{ocupante.get('codigo_vehiculo')} (RN-04: una ruta, un "
            "vehículo). Desasígnala de ese vehículo primero.",
            regla="V3",
            detalles=[{"ruta": ruta.get("codigo_ruta"),
                       "vehiculo_actual": ocupante.get("codigo_vehiculo")}])

    # RN-04, segundo sentido: el vehículo tampoco puede saltar de una ruta a
    # otra sin liberarse antes. Permitirlo dejaba la ruta anterior SIN
    # vehículo en silencio, que es justo el estado que RN-R6 impide al dar
    # de baja una ruta. La regla debe valer en los dos sentidos o no vale.
    if ruta_anterior and ruta_anterior != objeto_ruta:
        anterior = repositorio.ruta(ruta_anterior)
        codigo_anterior = anterior.get("codigo_ruta") if anterior else "?"
        raise ReglaDeNegocio(
            f"El vehículo {vehiculo.get('codigo_vehiculo')} ya cubre la ruta "
            f"{codigo_anterior} (RN-04: un vehículo, una ruta). Desasígnalo "
            f"primero, o {codigo_anterior} quedaría sin unidad.",
            regla="V3",
            detalles=[{"ruta_actual": codigo_anterior,
                       "ruta_solicitada": ruta.get("codigo_ruta")}])

    repositorio.sincronizar_ruta(objeto_ruta, vehiculo["_id"])

    return _publico(repositorio.actualizar(
        identificador, {"ruta_asignada_id": objeto_ruta}, incluir_inactivos=True))


# ==========================================================================
# BAJA Y REACTIVACIÓN
# ==========================================================================
def desactivar(bd: Database, identificador: str) -> dict[str, Any]:
    """Baja lógica del vehículo, con la comprobación de RN-V4."""
    repositorio = RepositorioVehiculos(bd)
    vehiculo = repositorio.obtener(identificador, incluir_inactivos=True)

    if not vehiculo.get("activo", True):
        raise ReglaDeNegocio(
            f"El vehículo '{vehiculo['codigo_vehiculo']}' ya estaba dado de baja.")

    if vehiculo.get("ruta_asignada_id"):
        ruta = repositorio.ruta(vehiculo["ruta_asignada_id"])
        codigo = ruta.get("codigo_ruta") if ruta else "?"
        raise ReglaDeNegocio(
            f"No se puede dar de baja el vehículo "
            f"'{vehiculo['codigo_vehiculo']}' (RN-V4): cubre la ruta "
            f"{codigo} y quedaría sin unidad. Desasígnalo primero.",
            regla="V4",
            detalles=[{"ruta_asignada": codigo}])

    # La baja marca el registro inactivo y deja el estado operativo en BAJA:
    # así la flotilla y el registro cuentan lo mismo.
    return _publico(repositorio.actualizar(
        identificador,
        {"activo": False, "estado_operativo": settings.ESTADO_BAJA},
        incluir_inactivos=True))


def reactivar(bd: Database, identificador: str) -> dict[str, Any]:
    repositorio = RepositorioVehiculos(bd)
    vehiculo = repositorio.obtener(identificador, incluir_inactivos=True)
    if vehiculo.get("activo", True):
        raise ReglaDeNegocio(
            f"El vehículo '{vehiculo['codigo_vehiculo']}' ya está activo.")
    return _publico(repositorio.actualizar(
        identificador,
        {"activo": True, "estado_operativo": settings.ESTADO_DISPONIBLE},
        incluir_inactivos=True))


# ==========================================================================
# INTERNO
# ==========================================================================
def _publico(documento: dict[str, Any]) -> dict[str, Any]:
    return VehiculoSalida.desde_documento(documento).model_dump()


def _carga_publica(carga: dict[str, Any]) -> dict[str, Any]:
    carga = dict(carga)
    carga["_id"] = str(carga.pop("_id"))
    return carga


def _interpretar_rendimiento(nominal: float | None, real: float | None,
                             n_cargas: int) -> str:
    """
    Lectura en lenguaje natural del rendimiento (RF-29).

    Es el mismo criterio que usa el dashboard: una brecha creciente frente
    al nominal suele anticipar necesidad de mantenimiento.
    """
    if real is None or nominal is None:
        return ("Todavía no hay rendimiento real calculado para este "
                "vehículo. Se obtiene al ejecutar el ETL sobre sus cargas "
                "de combustible.")
    desviacion = 100 * (real - nominal) / nominal
    if desviacion >= -5:
        estado = "está en línea con el nominal de fábrica"
    elif desviacion >= -15:
        estado = ("rinde por debajo del nominal; conviene vigilarlo en las "
                  "próximas cargas")
    else:
        estado = ("rinde muy por debajo del nominal, lo que suele anticipar "
                  "necesidad de revisión mecánica")
    return (f"Con {n_cargas} carga(s) registrada(s), el vehículo promedia "
            f"{real:.2f} km/l frente a los {nominal:.2f} km/l nominales "
            f"({desviacion:+.1f}%): {estado}.")
