"""
SIG-LOG — Sistema Integral de Gestión Logística
backend/routers/vehiculos.py

ENDPOINTS DEL MÓDULO VEHÍCULOS  (§12.3)

    GET    /vehiculos                    listar con filtros y paginación
    GET    /vehiculos/catalogos          estados, tipos y transiciones válidas
    GET    /vehiculos/resumen            conteo por estado y tipo
    GET    /vehiculos/{id}               detalle
    GET    /vehiculos/{id}/rendimiento   rendimiento histórico km/l
    POST   /vehiculos                    crear
    PUT    /vehiculos/{id}               actualizar la ficha
    PATCH  /vehiculos/{id}/estado        cambiar el estado operativo
    PATCH  /vehiculos/{id}/ruta          asignar o quitar la ruta (RN-04)
    DELETE /vehiculos/{id}               baja lógica
    PATCH  /vehiculos/{id}/reactivar     reactivar

Los dos primeros PATCH y el endpoint de rendimiento son los que el §12.3
pide expresamente para este recurso, además del CRUD.

Permisos: consultar, cualquier sesión. Modificar, solo ADMINISTRADOR — con
una excepción razonada: **cambiar el estado operativo también lo puede
hacer el DESPACHADOR**, porque es quien opera el día a día y registra que
una unidad salió a ruta o entró al taller (§3). Obligar a un administrador
para eso pararía la operación.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Path, Query, status

from backend.dependencias import (
    BaseDatos,
    PaginacionQuery,
    UsuarioAutenticado,
    requiere_rol,
)
from backend.schemas.comunes import Respuesta
from backend.schemas.vehiculos import (
    AsignacionRuta,
    CambioEstado,
    VehiculoActualizar,
    VehiculoCrear,
    VehiculoSalida,
)
from backend.services import vehiculos as servicio
from backend.utils import respuestas
from config import settings

router = APIRouter(
    prefix="/vehiculos",
    tags=["Vehículos"],
    responses={401: {"description": "Requiere sesión iniciada."}},
)

SoloAdmin = Depends(requiere_rol(settings.ROL_ADMINISTRADOR))
AdminODespachador = Depends(requiere_rol(settings.ROL_ADMINISTRADOR,
                                         settings.ROL_DESPACHADOR))
RESPUESTAS_ADMIN = {403: {"description": "Requiere rol ADMINISTRADOR."}}


# ==========================================================================
# CONSULTA  (cualquier sesión)
# ==========================================================================
@router.get(
    "/catalogos",
    response_model=Respuesta[dict[str, Any]],
    summary="Catálogos y transiciones de estado",
    description="Estados, tipos de unidad, combustibles y el mapa de "
                "transiciones válidas, para que el formulario solo ofrezca "
                "los cambios de estado que el sistema va a aceptar.",
)
def catalogos(usuario: UsuarioAutenticado) -> dict[str, Any]:
    return respuestas.exito(
        datos={
            "estados": list(settings.CATALOGO_ESTADO_VEHICULO),
            "tipos_vehiculo": list(settings.CATALOGO_TIPO_VEHICULO),
            "tipos_combustible": list(settings.CATALOGO_TIPO_COMBUSTIBLE),
            "transiciones": {k: list(v) for k, v in
                             settings.TRANSICIONES_ESTADO_VEHICULO.items()},
        },
        mensaje="Catálogos del módulo de vehículos.",
    )


@router.get(
    "/resumen",
    response_model=Respuesta[dict[str, Any]],
    summary="Resumen de la flotilla por estado y tipo",
)
def resumen(bd: BaseDatos, usuario: UsuarioAutenticado) -> dict[str, Any]:
    datos = servicio.resumen(bd)
    return respuestas.exito(
        datos=datos,
        mensaje=(f"{datos['activos']} vehículo(s) activo(s) de "
                 f"{datos['total']}; {datos['con_ruta_asignada']} con ruta."),
        total=datos["total"],
    )


@router.get(
    "",
    response_model=Respuesta[list[VehiculoSalida]],
    summary="Listar vehículos",
    description="Paginado, con búsqueda por placa, código, marca o modelo, "
                "y filtros por estado y tipo.",
)
def listar(bd: BaseDatos, usuario: UsuarioAutenticado, paginacion: PaginacionQuery,
           busqueda: str | None = Query(default=None),
           estado: str | None = Query(default=None),
           tipo_vehiculo: str | None = Query(default=None),
           incluir_inactivos: bool = Query(default=False),
           ) -> dict[str, Any]:
    vehiculos, total = servicio.listar(
        bd, saltar=paginacion.saltar, limite=paginacion.tamano,
        busqueda=busqueda, estado=estado, tipo_vehiculo=tipo_vehiculo,
        incluir_inactivos=incluir_inactivos)
    return respuestas.exito(
        datos=vehiculos,
        mensaje=(f"{len(vehiculos)} vehículo(s) en la página "
                 f"{paginacion.pagina} de {total} en total."),
        total=total,
    )


@router.get(
    "/{identificador}",
    response_model=Respuesta[VehiculoSalida],
    summary="Detalle de un vehículo",
    responses={404: {"description": "No existe el vehículo."}},
)
def obtener(bd: BaseDatos, usuario: UsuarioAutenticado,
            identificador: str = Path(...)) -> dict[str, Any]:
    vehiculo = servicio.obtener(bd, identificador)
    return respuestas.exito(
        datos=vehiculo,
        mensaje=f"Vehículo {vehiculo['codigo_vehiculo']} — {vehiculo['placa']}.")


@router.get(
    "/{identificador}/rendimiento",
    response_model=Respuesta[dict[str, Any]],
    summary="Rendimiento histórico del vehículo (km/l)",
    description=(
        "Rendimiento nominal, cargas de combustible con su km/l registrado y "
        "el agregado del periodo que calculó el ETL, más una lectura en "
        "lenguaje natural.\n\n"
        "**No recalcula nada**: lee el `rendimiento_km_l` que ya guarda cada "
        "carga y el agregado de `dim_vehiculo`. Así la cifra es la misma que "
        "muestran el dashboard y los reportes."
    ),
    responses={404: {"description": "No existe el vehículo."}},
)
def rendimiento(bd: BaseDatos, usuario: UsuarioAutenticado,
                identificador: str = Path(...),
                limite_cargas: int = Query(default=30, ge=1, le=200),
                ) -> dict[str, Any]:
    datos = servicio.rendimiento(bd, identificador, limite_cargas)
    return respuestas.exito(
        datos=datos,
        mensaje=datos["lectura"],
        total=datos["total_cargas"],
    )


# ==========================================================================
# ESCRITURA
# ==========================================================================
@router.post(
    "",
    response_model=Respuesta[VehiculoSalida],
    status_code=status.HTTP_201_CREATED,
    summary="Dar de alta un vehículo",
    description=(
        "El `codigo_vehiculo` lo asigna el sistema (VEH-NNN, RN-V1) y la "
        "placa debe ser única (RN-V2). Nace DISPONIBLE y sin ruta: "
        "asignarla es una decisión aparte, con su comprobación de RN-04."
    ),
    responses={**RESPUESTAS_ADMIN,
               409: {"description": "La placa ya existe (RN-V2)."},
               422: {"description": "Datos fuera de catálogo o mal formados."}},
)
def crear(bd: BaseDatos, datos: VehiculoCrear,
          usuario: dict = SoloAdmin) -> dict[str, Any]:
    vehiculo = servicio.crear(bd, datos.model_dump())
    return respuestas.exito(
        datos=vehiculo,
        mensaje=(f"Vehículo {vehiculo['codigo_vehiculo']} "
                 f"({vehiculo['placa']}) dado de alta."))


@router.put(
    "/{identificador}",
    response_model=Respuesta[VehiculoSalida],
    summary="Actualizar la ficha de un vehículo",
    description=(
        "Edita los datos de ficha. **No** acepta el estado, la ruta, el "
        "odómetro, el rendimiento real ni las fechas de mantenimiento "
        "(RN-V6): los dos primeros tienen endpoint propio y los demás los "
        "mantienen la operación y el ETL."
    ),
    responses={**RESPUESTAS_ADMIN,
               404: {"description": "No existe el vehículo."},
               409: {"description": "Viola RN-V1, RN-V2 o RN-V6."}},
)
def actualizar(bd: BaseDatos, datos: VehiculoActualizar,
               identificador: str = Path(...),
               usuario: dict = SoloAdmin) -> dict[str, Any]:
    vehiculo = servicio.actualizar(bd, identificador, datos.cambios())
    return respuestas.exito(
        datos=vehiculo,
        mensaje=f"Vehículo {vehiculo['codigo_vehiculo']} actualizado.")


@router.patch(
    "/{identificador}/estado",
    response_model=Respuesta[VehiculoSalida],
    summary="Cambiar el estado operativo",
    description=(
        "Aplica la máquina de estados de RN-V5. De EN_MANTENIMIENTO no se "
        "sale a EN_RUTA sin pasar por DISPONIBLE, y BAJA no es destino: se "
        "alcanza dando de baja el vehículo.\n\n"
        "Lo puede hacer el **DESPACHADOR** además del administrador: es "
        "quien registra que una unidad salió a ruta o entró al taller."
    ),
    responses={403: {"description": "Requiere ADMINISTRADOR o DESPACHADOR."},
               404: {"description": "No existe el vehículo."},
               409: {"description": "Transición no permitida (RN-V5)."}},
)
def cambiar_estado(bd: BaseDatos, datos: CambioEstado,
                   identificador: str = Path(...),
                   usuario: dict = AdminODespachador) -> dict[str, Any]:
    vehiculo = servicio.cambiar_estado(bd, identificador,
                                       datos.estado_operativo, datos.motivo)
    return respuestas.exito(
        datos=vehiculo,
        mensaje=(f"Vehículo {vehiculo['codigo_vehiculo']} ahora está "
                 f"{vehiculo['estado_operativo']}."))


@router.patch(
    "/{identificador}/ruta",
    response_model=Respuesta[VehiculoSalida],
    summary="Asignar o quitar la ruta del vehículo",
    description=(
        "Aplica RN-04: un vehículo tiene una sola ruta y una ruta un solo "
        "vehículo. Si la ruta ya está tomada, responde 409 diciendo qué "
        "unidad la cubre. Envía `ruta_id: null` para desasignar.\n\n"
        "Actualiza los dos extremos de la relación, para que la ruta no "
        "quede diciendo que la cubre un vehículo que ya no la tiene."
    ),
    responses={**RESPUESTAS_ADMIN,
               404: {"description": "No existe el vehículo."},
               409: {"description": "La ruta ya está asignada (RN-04)."}},
)
def asignar_ruta(bd: BaseDatos, datos: AsignacionRuta,
                 identificador: str = Path(...),
                 usuario: dict = SoloAdmin) -> dict[str, Any]:
    vehiculo = servicio.asignar_ruta(bd, identificador, datos.ruta_id)
    destino = (f"asignado a la ruta {vehiculo['ruta_asignada_id']}"
               if vehiculo["ruta_asignada_id"] else "sin ruta asignada")
    return respuestas.exito(
        datos=vehiculo,
        mensaje=f"Vehículo {vehiculo['codigo_vehiculo']} {destino}.")


@router.delete(
    "/{identificador}",
    response_model=Respuesta[VehiculoSalida],
    summary="Dar de baja un vehículo",
    description=(
        "Baja **lógica**: el documento se conserva porque los viajes, las "
        "cargas de combustible y los mantenimientos lo referencian.\n\n"
        "**RN-V4**: no se puede dar de baja un vehículo con ruta asignada; "
        "la ruta quedaría sin unidad. Desasígnalo primero."
    ),
    responses={**RESPUESTAS_ADMIN,
               404: {"description": "No existe el vehículo."},
               409: {"description": "Tiene ruta asignada (RN-V4)."}},
)
def desactivar(bd: BaseDatos, identificador: str = Path(...),
               usuario: dict = SoloAdmin) -> dict[str, Any]:
    vehiculo = servicio.desactivar(bd, identificador)
    return respuestas.exito(
        datos=vehiculo,
        mensaje=f"Vehículo {vehiculo['codigo_vehiculo']} dado de baja.")


@router.patch(
    "/{identificador}/reactivar",
    response_model=Respuesta[VehiculoSalida],
    summary="Reactivar un vehículo dado de baja",
    description="Vuelve a dejarlo activo y en estado DISPONIBLE.",
    responses={**RESPUESTAS_ADMIN,
               404: {"description": "No existe el vehículo."},
               409: {"description": "El vehículo ya estaba activo."}},
)
def reactivar(bd: BaseDatos, identificador: str = Path(...),
              usuario: dict = SoloAdmin) -> dict[str, Any]:
    vehiculo = servicio.reactivar(bd, identificador)
    return respuestas.exito(
        datos=vehiculo,
        mensaje=f"Vehículo {vehiculo['codigo_vehiculo']} reactivado.")
