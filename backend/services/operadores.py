"""
SIG-LOG — Sistema Integral de Gestión Logística
backend/services/operadores.py

REGLAS DEL MÓDULO OPERADORES  (§11.3)

Reglas de negocio (RN-O1 a RN-O6)
---------------------------------
RN-O1  `codigo_operador` lo genera el sistema (OPE-NNN) y es inmutable.

RN-O2  El número de licencia es único: es un documento oficial, y dos
       operadores con el mismo número significan que uno está mal
       capturado.

RN-O3  Un operador con la licencia VENCIDA no puede ponerse ACTIVO. No es
       burocracia: conducir sin licencia vigente es una infracción, y el
       sistema no debería ser quien la facilite. Para volver a activarlo
       hay que registrar antes la licencia renovada.

RN-O4  El sistema avisa de las licencias por vencer con antelación. Una
       licencia que caduca la semana próxima es legal hoy, pero programar
       rutas del mes siguiente con ella es un problema seguro.

RN-O5  No se da de baja a un operador con viajes en curso: está en la
       calle y el viaje quedaría sin responsable.

RN-O6  `total_entregas` y `porcentaje_entregas_a_tiempo` no se capturan:
       los mantienen la operación y el ETL.

Nota ética (§11.3)
------------------
El propio documento técnico advierte que usar el desempeño del operador
como variable de los modelos "puede derivar en evaluación del desempeño de
personas" y pide declararlo. El endpoint de desempeño lo declara en su
respuesta, junto al promedio de la flotilla: un porcentaje aislado invita
a comparar personas; situarlo frente al conjunto y frente al retraso de
sus rutas invita a entender por qué.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from backend.repositories.operadores import RepositorioOperadores
from backend.schemas.operadores import OperadorSalida
from backend.utils.errores import RecursoDuplicado, ReglaDeNegocio
from config import settings

CAMPOS_CALCULADOS = ("total_entregas", "porcentaje_entregas_a_tiempo",
                     "estado", "vehiculo_asignado_id")

AVISO_ETICO = (
    "Estas cifras describen el resultado de las rutas asignadas al "
    "operador, no su capacidad personal: el retraso depende sobre todo de "
    "la ruta, la franja horaria y los incidentes. Úsense para rediseñar "
    "rutas y turnos, no para evaluar a personas (advertencia del §11.3 del "
    "documento técnico)."
)


# ==========================================================================
# CONSULTA
# ==========================================================================
def listar(bd: Database, *, saltar: int = 0, limite: int = 50,
           busqueda: str | None = None, estado: str | None = None,
           licencia_vencida: bool | None = None,
           incluir_inactivos: bool = False
           ) -> tuple[list[dict[str, Any]], int]:
    repositorio = RepositorioOperadores(bd)
    filtro: dict[str, Any] = {}

    if busqueda:
        texto = busqueda.strip()
        filtro["$or"] = [
            {"nombre_completo": {"$regex": texto, "$options": "i"}},
            {"codigo_operador": {"$regex": texto, "$options": "i"}},
            {"licencia.numero": {"$regex": texto, "$options": "i"}},
        ]
    if estado:
        estado = estado.strip().upper()
        if estado not in settings.CATALOGO_ESTADO_OPERADOR:
            raise ReglaDeNegocio(
                f"Estado '{estado}' no pertenece al catálogo "
                f"{list(settings.CATALOGO_ESTADO_OPERADOR)}.")
        filtro["estado"] = estado
    if licencia_vencida is not None:
        comparador = "$lt" if licencia_vencida else "$gte"
        filtro["licencia.vigencia"] = {comparador: _ahora()}

    documentos = repositorio.listar(
        filtro, saltar=saltar, limite=limite,
        orden=[("codigo_operador", 1)], incluir_inactivos=incluir_inactivos)
    total = repositorio.contar(filtro, incluir_inactivos=incluir_inactivos)
    return [_publico(d) for d in documentos], total


def obtener(bd: Database, identificador: str) -> dict[str, Any]:
    return _publico(
        RepositorioOperadores(bd).obtener(identificador, incluir_inactivos=True))


def resumen(bd: Database) -> dict[str, Any]:
    repositorio = RepositorioOperadores(bd)
    total = repositorio.contar(incluir_inactivos=True)
    activos = repositorio.contar()
    vencidas = repositorio.contar_licencias_vencidas()
    por_vencer = len(repositorio.con_licencia_por_vencer(
        settings.DIAS_AVISO_LICENCIA))

    return {
        "total": total,
        "activos": activos,
        "inactivos": total - activos,
        "por_estado": {
            estado: repositorio.contar({"estado": estado})
            for estado in settings.CATALOGO_ESTADO_OPERADOR
        },
        "licencias_vencidas": vencidas,
        "licencias_por_vencer": por_vencer,
        "dias_aviso_licencia": settings.DIAS_AVISO_LICENCIA,
        "alerta": _alerta_licencias(vencidas, por_vencer),
    }


def licencias(bd: Database, dias: int | None = None) -> dict[str, Any]:
    """
    Licencias vencidas y por vencer (RN-O4).

    Es la consulta que permite actuar antes de que un operador quede sin
    poder conducir, en vez de descubrirlo el día que se le asigna una ruta.
    """
    repositorio = RepositorioOperadores(bd)
    dias = dias if dias is not None else settings.DIAS_AVISO_LICENCIA

    vencidas = [_ficha_licencia(o) for o in repositorio.con_licencia_vencida()]
    por_vencer = [_ficha_licencia(o)
                  for o in repositorio.con_licencia_por_vencer(dias)]

    return {
        "dias_anticipacion": dias,
        "vencidas": vencidas,
        "por_vencer": por_vencer,
        "total_vencidas": len(vencidas),
        "total_por_vencer": len(por_vencer),
        "alerta": _alerta_licencias(len(vencidas), len(por_vencer)),
    }


def desempenio(bd: Database, identificador: str) -> dict[str, Any]:
    """
    Desempeño del operador (§12.3), leído de `dim_operador`.

    No recalcula: la cifra es la misma que muestran el dashboard y los
    reportes. Se acompaña del promedio de la flotilla y de la advertencia
    ética del §11.3.
    """
    repositorio = RepositorioOperadores(bd)
    operador = repositorio.obtener(identificador, incluir_inactivos=True)

    metricas = repositorio.metricas_del_dw(operador["_id"]) or {}
    metricas.pop("_id", None)
    promedio = repositorio.promedio_de_la_flotilla()
    puntualidad = metricas.get("porcentaje_entregas_a_tiempo")

    return {
        "operador": {
            "id": str(operador["_id"]),
            "codigo_operador": operador.get("codigo_operador"),
            "nombre_completo": operador.get("nombre_completo"),
            "estado": operador.get("estado"),
        },
        "porcentaje_entregas_a_tiempo": puntualidad,
        "promedio_flotilla": promedio,
        "diferencia_vs_flotilla": (round(puntualidad - promedio, 1)
                                   if puntualidad is not None
                                   and promedio is not None else None),
        "metricas_periodo": metricas,
        "viajes_registrados": repositorio.viajes_realizados(operador["_id"]),
        "origen": ("dim_operador (ETL)" if metricas
                   else "no disponible: ejecuta python -m etl.run_etl"),
        "lectura": _interpretar_desempenio(operador, puntualidad, promedio,
                                           metricas),
        "aviso": AVISO_ETICO,
    }


# ==========================================================================
# ALTA
# ==========================================================================
def crear(bd: Database, datos: dict[str, Any]) -> dict[str, Any]:
    repositorio = RepositorioOperadores(bd)
    licencia = datos["licencia"]

    if repositorio.por_numero_de_licencia(licencia["numero"]):
        raise RecursoDuplicado(
            f"Ya existe un operador con la licencia '{licencia['numero']}' "
            "(RN-O2).")

    # RN-O3 desde el alta: no se registra a alguien ya vencido como ACTIVO.
    vencida = _fecha(licencia["vigencia"]) < _ahora()
    documento = {
        **datos,
        "licencia": {**licencia, "vigencia": _fecha(licencia["vigencia"])},
        "fecha_ingreso": _fecha(datos["fecha_ingreso"]),
        "codigo_operador": repositorio.siguiente_codigo(),      # RN-O1
        "estado": (settings.ESTADO_OPERADOR_INACTIVO if vencida
                   else settings.ESTADO_OPERADOR_ACTIVO),
        "vehiculo_asignado_id": None,        # RNP-03: rota, no tiene fijo
        "total_entregas": 0,
        "porcentaje_entregas_a_tiempo": None,
    }
    try:
        creado = repositorio.crear(documento)
    except DuplicateKeyError as exc:
        raise RecursoDuplicado(
            "El código de operador ya existe. Vuelve a intentarlo.") from exc
    return _publico(creado)


# ==========================================================================
# EDICIÓN
# ==========================================================================
def actualizar(bd: Database, identificador: str,
               cambios: dict[str, Any]) -> dict[str, Any]:
    repositorio = RepositorioOperadores(bd)

    if "codigo_operador" in cambios:
        raise ReglaDeNegocio(
            "El código de operador no se puede cambiar (RN-O1).", regla="O1")
    prohibidos = [c for c in cambios if c in CAMPOS_CALCULADOS]
    if prohibidos:
        raise ReglaDeNegocio(
            f"Estos campos no se editan desde aquí (RN-O6): "
            f"{', '.join(prohibidos)}. El estado tiene su propio endpoint, y "
            "las entregas y la puntualidad las mantienen la operación y el "
            "ETL.",
            regla="O6")
    if not cambios:
        raise ReglaDeNegocio("No se envió ningún campo que actualizar.")

    operador = repositorio.obtener(identificador, incluir_inactivos=True)

    if "licencia" in cambios:
        numero = cambios["licencia"]["numero"]
        if repositorio.por_numero_de_licencia(numero, excluir=operador["_id"]):
            raise RecursoDuplicado(
                f"Otro operador ya tiene la licencia '{numero}' (RN-O2).")
        cambios["licencia"] = {**cambios["licencia"],
                               "vigencia": _fecha(cambios["licencia"]["vigencia"])}
    if "fecha_ingreso" in cambios:
        cambios["fecha_ingreso"] = _fecha(cambios["fecha_ingreso"])

    return _publico(repositorio.actualizar(identificador, cambios,
                                           incluir_inactivos=True))


def cambiar_estado(bd: Database, identificador: str, estado_nuevo: str,
                   motivo: str | None = None) -> dict[str, Any]:
    """Aplica RN-O3: no se activa a nadie con la licencia vencida."""
    repositorio = RepositorioOperadores(bd)
    operador = repositorio.obtener(identificador, incluir_inactivos=True)

    if operador.get("estado") == estado_nuevo:
        raise ReglaDeNegocio(f"El operador ya está {estado_nuevo}.")

    if estado_nuevo == settings.ESTADO_OPERADOR_ACTIVO:
        vigencia = (operador.get("licencia") or {}).get("vigencia")
        if vigencia is None:
            raise ReglaDeNegocio(
                "No se puede activar a un operador sin licencia registrada "
                "(RN-O3).", regla="O3")
        if _fecha(vigencia) < _ahora():
            raise ReglaDeNegocio(
                f"No se puede activar a '{operador['codigo_operador']}': su "
                f"licencia venció el {_fecha(vigencia).date()} (RN-O3). "
                "Registra primero la licencia renovada.",
                regla="O3",
                detalles=[{"vigencia": str(_fecha(vigencia).date())}])

    cambios: dict[str, Any] = {"estado": estado_nuevo}
    if motivo:
        cambios["motivo_ultimo_cambio_estado"] = motivo
    return _publico(repositorio.actualizar(identificador, cambios,
                                           incluir_inactivos=True))


# ==========================================================================
# BAJA Y REACTIVACIÓN
# ==========================================================================
def desactivar(bd: Database, identificador: str) -> dict[str, Any]:
    """Baja lógica, con la comprobación de RN-O5."""
    repositorio = RepositorioOperadores(bd)
    operador = repositorio.obtener(identificador, incluir_inactivos=True)

    if not operador.get("activo", True):
        raise ReglaDeNegocio(
            f"El operador '{operador['codigo_operador']}' ya estaba dado de baja.")

    en_curso = repositorio.viajes_en_curso(operador["_id"])
    if en_curso:
        raise ReglaDeNegocio(
            f"No se puede dar de baja a '{operador['codigo_operador']}' "
            f"(RN-O5): tiene {en_curso} viaje(s) sin cerrar. Ciérralos o "
            "reasígnalos primero.",
            regla="O5",
            detalles=[{"viajes_en_curso": en_curso}])

    return _publico(repositorio.actualizar(
        identificador,
        {"activo": False, "estado": settings.ESTADO_OPERADOR_INACTIVO},
        incluir_inactivos=True))


def reactivar(bd: Database, identificador: str) -> dict[str, Any]:
    """
    Reactiva la ficha. Deja al operador INACTIVO a propósito: volver a
    ponerlo ACTIVO pasa por `cambiar_estado`, que comprueba la licencia
    (RN-O3). Reactivar y habilitar para conducir no son lo mismo.
    """
    repositorio = RepositorioOperadores(bd)
    operador = repositorio.obtener(identificador, incluir_inactivos=True)
    if operador.get("activo", True):
        raise ReglaDeNegocio(
            f"El operador '{operador['codigo_operador']}' ya está activo.")
    return _publico(repositorio.actualizar(
        identificador,
        {"activo": True, "estado": settings.ESTADO_OPERADOR_INACTIVO},
        incluir_inactivos=True))


# ==========================================================================
# INTERNO
# ==========================================================================
def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _fecha(valor: Any) -> datetime:
    """Normaliza date/datetime a datetime con zona UTC."""
    from datetime import date as _date

    if isinstance(valor, datetime):
        return valor if valor.tzinfo else valor.replace(tzinfo=timezone.utc)
    if isinstance(valor, _date):
        return datetime(valor.year, valor.month, valor.day, tzinfo=timezone.utc)
    return datetime.fromisoformat(str(valor)).replace(tzinfo=timezone.utc)


def _publico(documento: dict[str, Any]) -> dict[str, Any]:
    return OperadorSalida.desde_documento(documento).model_dump()


def _ficha_licencia(operador: dict[str, Any]) -> dict[str, Any]:
    licencia = operador.get("licencia") or {}
    vigencia = _fecha(licencia["vigencia"]) if licencia.get("vigencia") else None
    return {
        "id": str(operador["_id"]),
        "codigo_operador": operador.get("codigo_operador"),
        "nombre_completo": operador.get("nombre_completo"),
        "estado": operador.get("estado"),
        "tipo_licencia": licencia.get("tipo"),
        "vigencia": str(vigencia.date()) if vigencia else None,
        "dias": (vigencia - _ahora()).days if vigencia else None,
    }


def _alerta_licencias(vencidas: int, por_vencer: int) -> str:
    if not vencidas and not por_vencer:
        return "Todas las licencias están vigentes y ninguna caduca pronto."
    partes = []
    if vencidas:
        partes.append(
            f"{vencidas} operador(es) tienen la licencia VENCIDA y no "
            "deberían conducir")
    if por_vencer:
        partes.append(
            f"{por_vencer} la tienen por vencer en los próximos "
            f"{settings.DIAS_AVISO_LICENCIA} días")
    return ". ".join(partes) + "."


def _interpretar_desempenio(operador: dict[str, Any], puntualidad: float | None,
                            promedio: float | None,
                            metricas: dict[str, Any]) -> str:
    """Lectura en lenguaje natural del desempeño (RF-29)."""
    codigo = operador.get("codigo_operador")
    if puntualidad is None:
        return (f"Todavía no hay desempeño calculado para {codigo}. Se "
                "obtiene al ejecutar el ETL sobre sus entregas.")

    entregas = metricas.get("entregas_medibles", 0)
    retraso = metricas.get("retraso_medio_min")
    texto = (f"{codigo} entregó a tiempo el {puntualidad:.1f}% de sus "
             f"{entregas:,} entregas medibles")
    if retraso is not None:
        texto += f", con un retraso medio de {retraso:.1f} minutos"

    if promedio is not None:
        diferencia = puntualidad - promedio
        if abs(diferencia) < 2:
            texto += (f". Está en la media de la flotilla ({promedio:.1f}%), "
                      "así que su resultado lo explica la operación y no el "
                      "operador")
        elif diferencia > 0:
            texto += (f", {diferencia:.1f} puntos por encima de la media de "
                      f"la flotilla ({promedio:.1f}%)")
        else:
            texto += (f", {abs(diferencia):.1f} puntos por debajo de la media "
                      f"({promedio:.1f}%); conviene revisar qué rutas y "
                      "franjas horarias se le asignan antes de sacar "
                      "conclusiones sobre su desempeño")
    return texto + "."
