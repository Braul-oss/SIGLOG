"""
SIG-LOG — Sistema Integral de Gestión Logística
backend/routers/viajes.py

ENDPOINTS DEL MÓDULO VIAJES  (§12.3)

    GET   /viajes                  listar con filtros y paginación
    GET   /viajes/catalogos        estatus y transiciones válidas
    GET   /viajes/resumen          conteo por estatus y viajes abiertos
    GET   /viajes/{id}             detalle
    POST  /viajes                  programar la jornada
    PATCH /viajes/{id}/iniciar     registrar la salida real
    PATCH /viajes/{id}/finalizar   registrar el regreso y el odómetro
    PATCH /viajes/{id}/cancelar    cancelar con motivo

No hay DELETE, y es a propósito: el §11.5 establece que cada documento ES
el histórico y no se sobrescribe. Un viaje no se borra ni se da de baja;
se cancela dejando constancia del motivo (RN-J7). Es la única colección
del sistema sin baja lógica.

Permisos: consultar, cualquier sesión. Operar —programar, iniciar,
finalizar y cancelar— el ADMINISTRADOR y el **DESPACHADOR**, que según el
§3 es justamente quien "registra jornadas, entregas, horas reales e
incidentes". Este es su módulo.
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
from backend.schemas.viajes import (
    CancelarViaje,
    FinalizarViaje,
    IniciarViaje,
    ViajeProgramar,
    ViajeSalida,
)
from backend.services import viajes as servicio
from backend.utils import respuestas
from config import settings

router = APIRouter(
    prefix="/viajes",
    tags=["Viajes"],
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
    summary="Estatus y transiciones válidas",
)
def catalogos(usuario: UsuarioAutenticado) -> dict[str, Any]:
    return respuestas.exito(
        datos={
            "estatus": list(settings.CATALOGO_ESTATUS_VIAJE),
            "transiciones": {k: list(v) for k, v in
                             settings.TRANSICIONES_ESTATUS_VIAJE.items()},
            "abiertos": list(settings.ESTATUS_VIAJE_ABIERTOS),
            "nota": ("Un viaje no se borra ni se da de baja: se cancela. "
                     "Cada documento es el histórico de lo que ocurrió "
                     "(§11.5, RN-J7)."),
        },
        mensaje="Catálogos del módulo de viajes.",
    )


@router.get(
    "/resumen",
    response_model=Respuesta[dict[str, Any]],
    summary="Resumen de viajes por estatus",
)
def resumen(bd: BaseDatos, usuario: UsuarioAutenticado) -> dict[str, Any]:
    datos = servicio.resumen(bd)
    return respuestas.exito(datos=datos, mensaje=datos["alerta"],
                            total=datos["total"])


@router.get(
    "",
    response_model=Respuesta[list[ViajeSalida]],
    summary="Listar viajes",
    description="Paginado y ordenado del más reciente al más antiguo, con "
                "filtros por estatus, rango de fechas, ruta, vehículo y "
                "operador.",
)
def listar(bd: BaseDatos, usuario: UsuarioAutenticado, paginacion: PaginacionQuery,
           estatus: str | None = Query(default=None),
           fecha_desde: date | None = Query(default=None),
           fecha_hasta: date | None = Query(default=None),
           ruta_id: str | None = Query(default=None),
           vehiculo_id: str | None = Query(default=None),
           operador_id: str | None = Query(default=None),
           ) -> dict[str, Any]:
    viajes, total = servicio.listar(
        bd, saltar=paginacion.saltar, limite=paginacion.tamano,
        estatus=estatus, fecha_desde=fecha_desde, fecha_hasta=fecha_hasta,
        ruta_id=ruta_id, vehiculo_id=vehiculo_id, operador_id=operador_id)
    return respuestas.exito(
        datos=viajes,
        mensaje=(f"{len(viajes)} viaje(s) en la página {paginacion.pagina} "
                 f"de {total} en total."),
        total=total,
    )


@router.get(
    "/{identificador}",
    response_model=Respuesta[ViajeSalida],
    summary="Detalle de un viaje",
    responses={404: {"description": "No existe el viaje."}},
)
def obtener(bd: BaseDatos, usuario: UsuarioAutenticado,
            identificador: str = Path(...)) -> dict[str, Any]:
    viaje = servicio.obtener(bd, identificador)
    return respuestas.exito(
        datos=viaje,
        mensaje=f"Viaje {viaje['folio_viaje']} — {viaje['estatus']}.")


# ==========================================================================
# OPERACIÓN
# ==========================================================================
@router.post(
    "",
    response_model=Respuesta[ViajeSalida],
    status_code=status.HTTP_201_CREATED,
    summary="Programar la jornada",
    description=(
        "Da de alta el viaje tras comprobar que puede ejecutarse (RN-J3): "
        "ruta activa, vehículo DISPONIBLE, operador ACTIVO **y con licencia "
        "vigente**, y ni el vehículo ni el operador comprometidos en otra "
        "jornada sin cerrar. Además, una ruta se ejecuta una vez al día "
        "(RN-J4).\n\n"
        "La hora de salida programada se toma del plan de la ruta; el folio "
        "lo genera el sistema."
    ),
    responses={**RESPUESTAS_OPERACION,
               409: {"description": "Viola RN-J3 o RN-J4."}},
)
def programar(bd: BaseDatos, datos: ViajeProgramar,
              usuario: dict = Operacion) -> dict[str, Any]:
    viaje = servicio.programar(bd, datos.model_dump())
    return respuestas.exito(
        datos=viaje,
        mensaje=(f"Viaje {viaje['folio_viaje']} programado con "
                 f"{viaje['total_entregas_programadas']} entrega(s)."))


@router.patch(
    "/{identificador}/iniciar",
    response_model=Respuesta[ViajeSalida],
    summary="Registrar la salida real",
    description=(
        "Marca el viaje EN_CURSO, guarda la hora real y el odómetro de "
        "salida, y pone la unidad EN_RUTA.\n\n"
        "`retraso_salida_min` se **calcula** comparando la salida real con "
        "la programada; según el §11.5 es probablemente el predictor más "
        "fuerte del retraso de las entregas del día.\n\n"
        "**RN-J5**: el odómetro declarado no puede ser menor que el que ya "
        "tiene registrado la unidad."
    ),
    responses={**RESPUESTAS_OPERACION,
               404: {"description": "No existe el viaje."},
               409: {"description": "Transición inválida o odómetro menor."}},
)
def iniciar(bd: BaseDatos, datos: IniciarViaje,
            identificador: str = Path(...),
            usuario: dict = Operacion) -> dict[str, Any]:
    viaje = servicio.iniciar(bd, identificador, datos.model_dump())
    retraso = viaje.get("retraso_salida_min")
    nota = (f" Salió con {retraso:+.0f} min respecto de lo programado."
            if retraso is not None else "")
    return respuestas.exito(
        datos=viaje,
        mensaje=f"Viaje {viaje['folio_viaje']} en curso.{nota}")


@router.patch(
    "/{identificador}/finalizar",
    response_model=Respuesta[ViajeSalida],
    summary="Registrar el regreso y el odómetro",
    description=(
        "Cierra el viaje, calcula `km_recorridos` y `duracion_real_min`, "
        "cuenta entregas e incidentes, y devuelve la unidad a DISPONIBLE "
        "**actualizando su odómetro**.\n\n"
        "Esa actualización es la que hace cumplir a RN-V6: el módulo de "
        "vehículos prohíbe capturar el odómetro a mano precisamente porque "
        "lo escribe este cierre.\n\n"
        "**RN-J6**: el odómetro final debe ser mayor que el inicial y el "
        "regreso posterior a la salida."
    ),
    responses={**RESPUESTAS_OPERACION,
               404: {"description": "No existe el viaje."},
               409: {"description": "Transición inválida u odómetro/hora incoherentes."}},
)
def finalizar(bd: BaseDatos, datos: FinalizarViaje,
              identificador: str = Path(...),
              usuario: dict = Operacion) -> dict[str, Any]:
    viaje = servicio.finalizar(bd, identificador, datos.model_dump())
    return respuestas.exito(
        datos=viaje,
        mensaje=(f"Viaje {viaje['folio_viaje']} finalizado: "
                 f"{viaje['km_recorridos']} km en "
                 f"{viaje['duracion_real_min']} min, "
                 f"{viaje['total_entregas_completadas']} entrega(s)."))


@router.patch(
    "/{identificador}/cancelar",
    response_model=Respuesta[ViajeSalida],
    summary="Cancelar el viaje",
    description=(
        "Única forma de retirar un viaje: no hay borrado ni baja lógica "
        "(RN-J7). Exige un motivo, porque un viaje cancelado sin "
        "explicación no se puede analizar después. Si ya había salido, la "
        "unidad vuelve a DISPONIBLE."
    ),
    responses={**RESPUESTAS_OPERACION,
               404: {"description": "No existe el viaje."},
               409: {"description": "El viaje ya está cerrado."}},
)
def cancelar(bd: BaseDatos, datos: CancelarViaje,
             identificador: str = Path(...),
             usuario: dict = Operacion) -> dict[str, Any]:
    viaje = servicio.cancelar(bd, identificador, datos.motivo)
    return respuestas.exito(
        datos=viaje,
        mensaje=f"Viaje {viaje['folio_viaje']} cancelado: {datos.motivo}")
