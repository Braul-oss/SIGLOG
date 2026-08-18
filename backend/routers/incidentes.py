"""
SIG-LOG — Sistema Integral de Gestión Logística
backend/routers/incidentes.py

ENDPOINTS DEL MÓDULO INCIDENTES  (§12.3)

    GET   /incidentes                        listar con filtros
    GET   /incidentes/catalogos              tipos, severidades y fuentes
    GET   /incidentes/resumen                conteo por tipo y severidad
    GET   /incidentes/bitacora/{viaje_id}    eventos de seguimiento del viaje
    GET   /incidentes/{id}                   detalle
    POST  /incidentes                        registrar
    POST  /incidentes/{id}/afectar-entregas  asociar y recalcular ETA (RF-33)
    PATCH /incidentes/{id}/cerrar            registrar el fin y la duración

`/afectar-entregas` es el que el §12.3 pide expresamente y el que
implementa RF-33 siguiendo el procedimiento del §17.3.

Permisos: consultar, cualquier sesión. Registrar, ADMINISTRADOR y
DESPACHADOR — el §3 le asigna a este último registrar los incidentes, que
además es quien está en contacto con la operación cuando ocurren.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Path, Query, status

from backend.dependencias import (
    BaseDatos,
    PaginacionQuery,
    UsuarioAutenticado,
    requiere_rol,
)
from backend.schemas.comunes import Respuesta
from backend.schemas.incidentes import (
    AfectarEntregas,
    CerrarIncidente,
    IncidenteCrear,
    IncidenteSalida,
)
from backend.services import incidentes as servicio
from backend.utils import respuestas
from config import settings

router = APIRouter(
    prefix="/incidentes",
    tags=["Incidentes"],
    responses={401: {"description": "Requiere sesión iniciada."}},
)

Operacion = Depends(requiere_rol(settings.ROL_ADMINISTRADOR,
                                 settings.ROL_DESPACHADOR))
RESPUESTAS_OPERACION = {
    403: {"description": "Requiere rol ADMINISTRADOR o DESPACHADOR."}}


# ==========================================================================
# CONSULTA
# ==========================================================================
@router.get(
    "/catalogos",
    response_model=Respuesta[dict[str, Any]],
    summary="Tipos, severidades y fuentes",
)
def catalogos(usuario: UsuarioAutenticado) -> dict[str, Any]:
    return respuestas.exito(
        datos={
            "tipos": list(settings.CATALOGO_TIPOS_INCIDENTE),
            "severidades": list(settings.CATALOGO_SEVERIDAD_INCIDENTE),
            "fuentes": list(settings.CATALOGO_FUENTE_INCIDENTE),
            "recalculo_eta": {
                "metodo": "suma lineal de los minutos perdidos (§17.3)",
                "advertencia": settings.ADVERTENCIA_RECALCULO_ETA,
            },
        },
        mensaje="Catálogos del módulo de incidentes.",
    )


@router.get(
    "/resumen",
    response_model=Respuesta[dict[str, Any]],
    summary="Resumen por tipo y severidad",
    description="Conteo que sirve de base al análisis de Pareto de causas "
                "del dashboard, y los incidentes que siguen abiertos.",
)
def resumen(bd: BaseDatos, usuario: UsuarioAutenticado) -> dict[str, Any]:
    datos = servicio.resumen(bd)
    return respuestas.exito(datos=datos, mensaje=datos["alerta"],
                            total=datos["total"])


@router.get(
    "/bitacora/{viaje_id}",
    response_model=Respuesta[dict[str, Any]],
    summary="Bitácora de seguimiento de un viaje",
    description=(
        "Eventos de `seguimiento_eventos` (§11.10) en orden cronológico: "
        "incidentes registrados y recálculos de ETA con su valor anterior y "
        "el nuevo. Es lo que permite reconstruir después por qué una "
        "entrega tuvo dos previsiones distintas."
    ),
)
def bitacora(bd: BaseDatos, usuario: UsuarioAutenticado,
             viaje_id: str = Path(...)) -> dict[str, Any]:
    datos = servicio.bitacora(bd, viaje_id)
    return respuestas.exito(
        datos=datos,
        mensaje=(f"{datos['total_eventos']} evento(s) del viaje "
                 f"{datos['viaje']}."),
        total=datos["total_eventos"])


@router.get(
    "",
    response_model=Respuesta[list[IncidenteSalida]],
    summary="Listar incidentes",
    description="Paginado, con filtros por viaje, tipo, severidad, rango de "
                "fechas y si siguen abiertos.",
)
def listar(bd: BaseDatos, usuario: UsuarioAutenticado, paginacion: PaginacionQuery,
           viaje_id: str | None = Query(default=None),
           tipo: str | None = Query(default=None),
           severidad: str | None = Query(default=None),
           solo_abiertos: bool | None = Query(default=None),
           fecha_desde: date | None = Query(default=None),
           fecha_hasta: date | None = Query(default=None),
           ) -> dict[str, Any]:
    incidentes, total = servicio.listar(
        bd, saltar=paginacion.saltar, limite=paginacion.tamano,
        viaje_id=viaje_id, tipo=tipo, severidad=severidad,
        solo_abiertos=solo_abiertos, fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta)
    return respuestas.exito(
        datos=incidentes,
        mensaje=(f"{len(incidentes)} incidente(s) en la página "
                 f"{paginacion.pagina} de {total} en total."),
        total=total,
    )


@router.get(
    "/{identificador}",
    response_model=Respuesta[IncidenteSalida],
    summary="Detalle de un incidente",
    responses={404: {"description": "No existe el incidente."}},
)
def obtener(bd: BaseDatos, usuario: UsuarioAutenticado,
            identificador: str = Path(...)) -> dict[str, Any]:
    incidente = servicio.obtener(bd, identificador)
    estado = "abierto" if incidente["abierto"] else "cerrado"
    return respuestas.exito(
        datos=incidente,
        mensaje=(f"Incidente {incidente['folio_incidente']} — "
                 f"{incidente['tipo']} ({incidente['severidad']}), {estado}."))


# ==========================================================================
# REGISTRO
# ==========================================================================
@router.post(
    "",
    response_model=Respuesta[IncidenteSalida],
    status_code=status.HTTP_201_CREATED,
    summary="Registrar un incidente",
    description=(
        "Da de alta el incidente sobre un viaje abierto y actualiza el "
        "contador de incidentes del viaje.\n\n"
        "**RN-I2**: no se registran incidentes sobre viajes cerrados; ese "
        "cierre ya declaró cuántos hubo.\n\n"
        "`duracion_min` no se captura: se calcula al cerrar el incidente. "
        "Mientras sigue abierto se trabaja con el tiempo perdido estimado."
    ),
    responses={**RESPUESTAS_OPERACION,
               409: {"description": "El viaje no existe o está cerrado (RN-I2)."}},
)
def crear(bd: BaseDatos, datos: IncidenteCrear,
          usuario: dict = Operacion) -> dict[str, Any]:
    incidente = servicio.crear(bd, datos.model_dump())
    return respuestas.exito(
        datos=incidente,
        mensaje=(f"Incidente {incidente['folio_incidente']} registrado: "
                 f"{incidente['tipo']} ({incidente['severidad']}), "
                 f"{incidente['tiempo_perdido_estimado_min']:.0f} min "
                 "estimados de pérdida."))


@router.post(
    "/{identificador}/afectar-entregas",
    response_model=Respuesta[dict[str, Any]],
    summary="Asociar el incidente a las entregas y recalcular su ETA",
    description=(
        "Implementa **RF-33** siguiendo el procedimiento del §17.3: "
        "identifica las entregas del viaje que aún no tienen desenlace, "
        "les suma los minutos perdidos al ETA y deja constancia en "
        "`seguimiento_eventos` con el valor anterior y el nuevo.\n\n"
        "**RN-I5, la regla clave**: se escribe `hora_estimada_recalculada` "
        "y **nunca** se toca `hora_estimada_llegada`. El plan original es "
        "la referencia contra la que se mide el retraso; sobrescribirlo "
        "haría que el incidente ocultara el retraso que él mismo causó, y "
        "los modelos perderían la señal que este módulo existe para "
        "darles.\n\n"
        "La respuesta incluye la advertencia del §17.3 sobre la linealidad "
        "del recálculo, que el documento marca como supuesto no confirmado."
    ),
    responses={**RESPUESTAS_OPERACION,
               404: {"description": "No existe el incidente."},
               409: {"description": "Sin entregas pendientes o entregas ajenas al viaje (RN-I4)."}},
)
def afectar_entregas(bd: BaseDatos, datos: AfectarEntregas,
                     identificador: str = Path(...),
                     usuario: dict = Operacion) -> dict[str, Any]:
    resultado = servicio.afectar_entregas(bd, identificador, datos.model_dump())
    return respuestas.exito(
        datos=resultado,
        mensaje=(f"{resultado['entregas_afectadas']} entrega(s) del viaje "
                 f"{resultado['viaje']} recalculadas: "
                 f"+{resultado['minutos_perdidos']:.0f} min."),
        total=resultado["entregas_afectadas"])


@router.patch(
    "/{identificador}/cerrar",
    response_model=Respuesta[IncidenteSalida],
    summary="Cerrar el incidente y calcular su duración",
    description=(
        "Registra el fin y calcula `duracion_min` (RN-I3). Esa duración es "
        "uno de los predictores con que los modelos explican los retrasos "
        "anómalos, así que se deriva de las horas y no se captura."
    ),
    responses={**RESPUESTAS_OPERACION,
               404: {"description": "No existe el incidente."},
               409: {"description": "Ya estaba cerrado o el fin precede al inicio."}},
)
def cerrar(bd: BaseDatos, datos: CerrarIncidente,
           identificador: str = Path(...),
           usuario: dict = Operacion) -> dict[str, Any]:
    incidente = servicio.cerrar(bd, identificador, datos.fecha_hora_fin)
    return respuestas.exito(
        datos=incidente,
        mensaje=(f"Incidente {incidente['folio_incidente']} cerrado: "
                 f"{incidente['duracion_min']:.0f} minutos de duración."))
