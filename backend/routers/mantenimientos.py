"""
SIG-LOG — Sistema Integral de Gestión Logística
backend/routers/mantenimientos.py

ENDPOINTS DEL MÓDULO MANTENIMIENTOS  (§12.3)

    GET   /mantenimientos              listar con filtros
    GET   /mantenimientos/catalogos    tipos, estatus y transiciones
    GET   /mantenimientos/pendientes   vehículos por atender (RF-16)
    GET   /mantenimientos/resumen      conteo y costo por vehículo
    GET   /mantenimientos/{id}         detalle
    POST  /mantenimientos              programar un servicio
    PUT   /mantenimientos/{id}         editar mientras siga sin realizarse
    PATCH /mantenimientos/{id}/realizar  registrar el servicio efectuado
    PATCH /mantenimientos/{id}/vencer    declararlo vencido

`/pendientes` es el que el §12.3 pide expresamente y el que implementa la
alerta RF-16.

Permisos: consultar, cualquier sesión. Programar y editar, ADMINISTRADOR;
registrar el servicio o declararlo vencido, también el DESPACHADOR, que es
quien ve pasar la unidad por el taller.
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
from backend.schemas.mantenimientos import (
    MantenimientoActualizar,
    MantenimientoProgramar,
    MantenimientoSalida,
    RealizarMantenimiento,
    VencerMantenimiento,
)
from backend.services import mantenimientos as servicio
from backend.utils import respuestas
from config import settings

router = APIRouter(
    prefix="/mantenimientos",
    tags=["Mantenimiento"],
    responses={401: {"description": "Requiere sesión iniciada."}},
)

SoloAdmin = Depends(requiere_rol(settings.ROL_ADMINISTRADOR))
Operacion = Depends(requiere_rol(settings.ROL_ADMINISTRADOR,
                                 settings.ROL_DESPACHADOR))


# ==========================================================================
# CONSULTA
# ==========================================================================
@router.get(
    "/catalogos",
    response_model=Respuesta[dict[str, Any]],
    summary="Tipos, estatus y transiciones",
)
def catalogos(usuario: UsuarioAutenticado) -> dict[str, Any]:
    return respuestas.exito(
        datos={
            "tipos": list(settings.CATALOGO_TIPO_MANTENIMIENTO),
            "estatus": list(settings.CATALOGO_ESTATUS_MANTENIMIENTO),
            "transiciones": {k: list(v) for k, v in
                             settings.TRANSICIONES_ESTATUS_MANTENIMIENTO.items()},
            "periodicidad_dias": settings.DIAS_PERIODICIDAD_MANTENIMIENTO,
            "dias_aviso": settings.DIAS_AVISO_MANTENIMIENTO,
            "nota_periodicidad": (
                "RNP-04 se aplica por calendario: la próxima fecha sale de "
                "sumar la periodicidad a la fecha realizada. Es lo que la "
                "simulación implementó y sobre lo que se construyó el DW."),
        },
        mensaje="Catálogos del módulo de mantenimiento.",
    )


@router.get(
    "/pendientes",
    response_model=Respuesta[dict[str, Any]],
    summary="Vehículos que requieren mantenimiento (RF-16)",
    description=(
        "Separa tres situaciones que piden respuestas distintas:\n\n"
        "- **vencidos**: ya sacaron la unidad de operación;\n"
        "- **atrasados**: programados cuya fecha pasó pero que aún no se "
        "han declarado vencidos — son los que hay que atender hoy;\n"
        "- **próximos**: todavía se pueden planificar sin parar nada.\n\n"
        "Cada fila trae el vehículo, su estado operativo y los días de "
        "diferencia respecto de la fecha programada."
    ),
)
def pendientes(bd: BaseDatos, usuario: UsuarioAutenticado,
               dias: int = Query(default=settings.DIAS_AVISO_MANTENIMIENTO,
                                 ge=1, le=365,
                                 description="Anticipación del aviso."),
               ) -> dict[str, Any]:
    datos = servicio.pendientes(bd, dias)
    return respuestas.exito(
        datos=datos, mensaje=datos["alerta"],
        total=(datos["total_vencidos"] + datos["total_atrasados"]
               + datos["total_proximos"]))


@router.get(
    "/resumen",
    response_model=Respuesta[dict[str, Any]],
    summary="Resumen por tipo, estatus y costo por vehículo",
)
def resumen(bd: BaseDatos, usuario: UsuarioAutenticado) -> dict[str, Any]:
    datos = servicio.resumen(bd)
    return respuestas.exito(datos=datos, mensaje=datos["alerta"],
                            total=datos["total"])


@router.get(
    "",
    response_model=Respuesta[list[MantenimientoSalida]],
    summary="Listar mantenimientos",
    description="Paginado, con filtros por vehículo, tipo, estatus y rango "
                "de fechas programadas.",
)
def listar(bd: BaseDatos, usuario: UsuarioAutenticado, paginacion: PaginacionQuery,
           vehiculo_id: str | None = Query(default=None),
           tipo: str | None = Query(default=None),
           estatus: str | None = Query(default=None),
           fecha_desde: date | None = Query(default=None),
           fecha_hasta: date | None = Query(default=None),
           ) -> dict[str, Any]:
    mantenimientos, total = servicio.listar(
        bd, saltar=paginacion.saltar, limite=paginacion.tamano,
        vehiculo_id=vehiculo_id, tipo=tipo, estatus=estatus,
        fecha_desde=fecha_desde, fecha_hasta=fecha_hasta)
    return respuestas.exito(
        datos=mantenimientos,
        mensaje=(f"{len(mantenimientos)} mantenimiento(s) en la página "
                 f"{paginacion.pagina} de {total} en total."),
        total=total,
    )


@router.get(
    "/{identificador}",
    response_model=Respuesta[MantenimientoSalida],
    summary="Detalle de un mantenimiento",
    responses={404: {"description": "No existe el mantenimiento."}},
)
def obtener(bd: BaseDatos, usuario: UsuarioAutenticado,
            identificador: str = Path(...)) -> dict[str, Any]:
    mantenimiento = servicio.obtener(bd, identificador)
    return respuestas.exito(
        datos=mantenimiento,
        mensaje=(f"Mantenimiento {mantenimiento['folio_mantenimiento']} — "
                 f"{mantenimiento['tipo']}, {mantenimiento['estatus']}."))


# ==========================================================================
# PROGRAMACIÓN
# ==========================================================================
@router.post(
    "",
    response_model=Respuesta[MantenimientoSalida],
    status_code=status.HTTP_201_CREATED,
    summary="Programar un mantenimiento",
    description=(
        "**RN-M3**: una unidad no puede tener dos servicios abiertos a la "
        "vez; programar otro sobre uno pendiente duplicaría el trabajo y "
        "descuadraría la alerta de RF-16."
    ),
    responses={403: {"description": "Requiere rol ADMINISTRADOR."},
               409: {"description": "La unidad ya tiene un servicio abierto (RN-M3)."}},
)
def programar(bd: BaseDatos, datos: MantenimientoProgramar,
              usuario: dict = SoloAdmin) -> dict[str, Any]:
    mantenimiento = servicio.programar(bd, datos.model_dump())
    return respuestas.exito(
        datos=mantenimiento,
        mensaje=(f"Mantenimiento {mantenimiento['folio_mantenimiento']} "
                 f"({mantenimiento['tipo']}) programado."))


@router.put(
    "/{identificador}",
    response_model=Respuesta[MantenimientoSalida],
    summary="Editar un mantenimiento no realizado",
    description="Un servicio ya REALIZADO no se edita: es el registro de "
                "lo que se hizo.",
    responses={403: {"description": "Requiere rol ADMINISTRADOR."},
               404: {"description": "No existe el mantenimiento."},
               409: {"description": "Ya está realizado o se enviaron campos calculados."}},
)
def actualizar(bd: BaseDatos, datos: MantenimientoActualizar,
               identificador: str = Path(...),
               usuario: dict = SoloAdmin) -> dict[str, Any]:
    mantenimiento = servicio.actualizar(bd, identificador, datos.cambios())
    return respuestas.exito(
        datos=mantenimiento,
        mensaje=(f"Mantenimiento {mantenimiento['folio_mantenimiento']} "
                 "actualizado."))


# ==========================================================================
# EJECUCIÓN
# ==========================================================================
@router.patch(
    "/{identificador}/realizar",
    response_model=Respuesta[dict[str, Any]],
    summary="Registrar el servicio efectuado",
    description=(
        "Calcula la duración y la próxima fecha (**RN-M4**), y actualiza "
        "las fechas de mantenimiento del vehículo (**RN-M5**).\n\n"
        "Esa actualización cierra la promesa de RN-V6: la ficha del "
        "vehículo prohíbe capturar esas fechas precisamente porque se "
        "derivan de aquí.\n\n"
        "**RN-M6**: si la unidad estaba fuera de operación, vuelve a "
        "DISPONIBLE — pero solo si no le quedan otros servicios vencidos. "
        "Un vehículo con dos vencidos no vuelve a la calle por atender uno."
    ),
    responses={403: {"description": "Requiere ADMINISTRADOR o DESPACHADOR."},
               404: {"description": "No existe el mantenimiento."},
               409: {"description": "Transición inválida o fecha incoherente."}},
)
def realizar(bd: BaseDatos, datos: RealizarMantenimiento,
             identificador: str = Path(...),
             usuario: dict = Operacion) -> dict[str, Any]:
    resultado = servicio.realizar(bd, identificador, datos.model_dump())
    if resultado["vehiculo_liberado"]:
        nota = " La unidad vuelve a estar DISPONIBLE."
    elif resultado["vencidos_restantes"]:
        nota = (f" La unidad sigue fuera de operación: le quedan "
                f"{resultado['vencidos_restantes']} servicio(s) vencido(s).")
    else:
        nota = ""
    return respuestas.exito(
        datos=resultado,
        mensaje=(f"Mantenimiento {resultado['folio_mantenimiento']} "
                 f"realizado. Próximo servicio: "
                 f"{resultado['proximo_mantenimiento_fecha']}.{nota}"))


@router.patch(
    "/{identificador}/vencer",
    response_model=Respuesta[dict[str, Any]],
    summary="Declarar vencido un mantenimiento",
    description=(
        "Mitad operativa de **RF-16**: la alerta avisa y esta acción es la "
        "que impide que un vehículo sin mantenimiento salga a ruta. La "
        "unidad queda EN_MANTENIMIENTO y, por RN-J3, deja de poder "
        "programarse en una jornada.\n\n"
        "**RN-M7**: no se puede dar por vencido antes de su fecha "
        "programada. Vencer es constatar un incumplimiento, no anticiparlo."
    ),
    responses={403: {"description": "Requiere ADMINISTRADOR o DESPACHADOR."},
               404: {"description": "No existe el mantenimiento."},
               409: {"description": "Aún no llega su fecha o ya está realizado."}},
)
def vencer(bd: BaseDatos, datos: VencerMantenimiento,
           identificador: str = Path(...),
           usuario: dict = Operacion) -> dict[str, Any]:
    resultado = servicio.vencer(bd, identificador, datos.motivo)
    return respuestas.exito(
        datos=resultado,
        mensaje=(f"Mantenimiento {resultado['folio_mantenimiento']} "
                 "declarado VENCIDO. La unidad queda fuera de operación "
                 "hasta que se atienda."))
