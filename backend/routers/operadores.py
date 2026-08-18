"""
SIG-LOG — Sistema Integral de Gestión Logística
backend/routers/operadores.py

ENDPOINTS DEL MÓDULO OPERADORES  (§12.3)

    GET    /operadores                   listar con filtros y paginación
    GET    /operadores/catalogos         estados y tipos de licencia
    GET    /operadores/resumen           conteo por estado y alerta de licencias
    GET    /operadores/licencias         vencidas y por vencer (RN-O4)
    GET    /operadores/{id}              detalle
    GET    /operadores/{id}/desempenio   entregas y puntualidad (§12.3)
    POST   /operadores                   alta
    PUT    /operadores/{id}              actualizar la ficha
    PATCH  /operadores/{id}/estado       activar o desactivar (RN-O3)
    DELETE /operadores/{id}              baja lógica
    PATCH  /operadores/{id}/reactivar    reactivar la ficha

No hay endpoint para asignar vehículo: RNP-03 se resolvió como ROTACIÓN
por jornada, así que la pareja operador-vehículo se decide en cada viaje y
ahí queda registrada. Ofrecer una asignación fija contradiría el modelo.

Permisos: consultar, cualquier sesión. Escribir, ADMINISTRADOR — salvo el
cambio de estado, que también puede hacer el DESPACHADOR, por la misma
razón que en vehículos: es quien lleva el día a día y sabe si un operador
está disponible o no.
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
from backend.schemas.operadores import (
    CambioEstadoOperador,
    OperadorActualizar,
    OperadorCrear,
    OperadorSalida,
)
from backend.services import operadores as servicio
from backend.utils import respuestas
from config import settings

router = APIRouter(
    prefix="/operadores",
    tags=["Operadores"],
    responses={401: {"description": "Requiere sesión iniciada."}},
)

SoloAdmin = Depends(requiere_rol(settings.ROL_ADMINISTRADOR))
AdminODespachador = Depends(requiere_rol(settings.ROL_ADMINISTRADOR,
                                         settings.ROL_DESPACHADOR))
RESPUESTAS_ADMIN = {403: {"description": "Requiere rol ADMINISTRADOR."}}


# ==========================================================================
# CONSULTA
# ==========================================================================
@router.get(
    "/catalogos",
    response_model=Respuesta[dict[str, Any]],
    summary="Catálogos del módulo",
)
def catalogos(usuario: UsuarioAutenticado) -> dict[str, Any]:
    return respuestas.exito(
        datos={
            "estados": list(settings.CATALOGO_ESTADO_OPERADOR),
            "tipos_licencia": list(settings.CATALOGO_TIPO_LICENCIA),
            "dias_aviso_licencia": settings.DIAS_AVISO_LICENCIA,
            "asignacion_vehiculo": (
                "Los operadores ROTAN de vehículo por jornada (RNP-03). La "
                "pareja operador-vehículo se registra en cada viaje, no en "
                "la ficha del operador."),
        },
        mensaje="Catálogos del módulo de operadores.",
    )


@router.get(
    "/resumen",
    response_model=Respuesta[dict[str, Any]],
    summary="Resumen de la plantilla y estado de las licencias",
)
def resumen(bd: BaseDatos, usuario: UsuarioAutenticado) -> dict[str, Any]:
    datos = servicio.resumen(bd)
    return respuestas.exito(datos=datos, mensaje=datos["alerta"],
                            total=datos["total"])


@router.get(
    "/licencias",
    response_model=Respuesta[dict[str, Any]],
    summary="Licencias vencidas y por vencer",
    description=(
        "**RN-O4**: permite actuar antes de que un operador quede sin poder "
        "conducir, en lugar de descubrirlo el día que se le asigna una "
        "ruta. `dias` controla la anticipación del aviso."
    ),
)
def licencias(bd: BaseDatos, usuario: UsuarioAutenticado,
              dias: int = Query(default=settings.DIAS_AVISO_LICENCIA,
                                ge=1, le=365),
              ) -> dict[str, Any]:
    datos = servicio.licencias(bd, dias)
    return respuestas.exito(
        datos=datos, mensaje=datos["alerta"],
        total=datos["total_vencidas"] + datos["total_por_vencer"])


@router.get(
    "",
    response_model=Respuesta[list[OperadorSalida]],
    summary="Listar operadores",
    description="Paginado, con búsqueda por nombre, código o número de "
                "licencia, y filtros por estado y por licencia vencida.",
)
def listar(bd: BaseDatos, usuario: UsuarioAutenticado, paginacion: PaginacionQuery,
           busqueda: str | None = Query(default=None),
           estado: str | None = Query(default=None),
           licencia_vencida: bool | None = Query(
               default=None, description="true: solo con licencia vencida."),
           incluir_inactivos: bool = Query(default=False),
           ) -> dict[str, Any]:
    operadores, total = servicio.listar(
        bd, saltar=paginacion.saltar, limite=paginacion.tamano,
        busqueda=busqueda, estado=estado, licencia_vencida=licencia_vencida,
        incluir_inactivos=incluir_inactivos)
    return respuestas.exito(
        datos=operadores,
        mensaje=(f"{len(operadores)} operador(es) en la página "
                 f"{paginacion.pagina} de {total} en total."),
        total=total,
    )


@router.get(
    "/{identificador}",
    response_model=Respuesta[OperadorSalida],
    summary="Detalle de un operador",
    responses={404: {"description": "No existe el operador."}},
)
def obtener(bd: BaseDatos, usuario: UsuarioAutenticado,
            identificador: str = Path(...)) -> dict[str, Any]:
    operador = servicio.obtener(bd, identificador)
    return respuestas.exito(
        datos=operador,
        mensaje=f"Operador {operador['codigo_operador']} — "
                f"{operador['nombre_completo']}.")


@router.get(
    "/{identificador}/desempenio",
    response_model=Respuesta[dict[str, Any]],
    summary="Desempeño del operador: entregas y puntualidad",
    description=(
        "Lee las métricas que el ETL dejó en `dim_operador` y las sitúa "
        "frente al promedio de la flotilla.\n\n"
        "**Advertencia ética (§11.3):** el propio documento técnico señala "
        "que usar el desempeño del operador como variable de los modelos "
        "puede derivar en evaluación de personas. La respuesta incluye esa "
        "advertencia, porque el retraso depende sobre todo de la ruta, la "
        "franja horaria y los incidentes, no de quién conduce."
    ),
    responses={404: {"description": "No existe el operador."}},
)
def desempenio(bd: BaseDatos, usuario: UsuarioAutenticado,
               identificador: str = Path(...)) -> dict[str, Any]:
    datos = servicio.desempenio(bd, identificador)
    return respuestas.exito(datos=datos, mensaje=datos["lectura"])


# ==========================================================================
# ESCRITURA
# ==========================================================================
@router.post(
    "",
    response_model=Respuesta[OperadorSalida],
    status_code=status.HTTP_201_CREATED,
    summary="Dar de alta un operador",
    description=(
        "El `codigo_operador` lo asigna el sistema (OPE-NNN, RN-O1) y el "
        "número de licencia debe ser único (RN-O2). Si la licencia que se "
        "registra ya está vencida, el operador nace INACTIVO (RN-O3)."
    ),
    responses={**RESPUESTAS_ADMIN,
               409: {"description": "La licencia ya está registrada (RN-O2)."},
               422: {"description": "Datos fuera de catálogo o mal formados."}},
)
def crear(bd: BaseDatos, datos: OperadorCrear,
          usuario: dict = SoloAdmin) -> dict[str, Any]:
    operador = servicio.crear(bd, datos.model_dump())
    nota = ("" if operador["licencia_vigente"]
            else " Nace INACTIVO: la licencia registrada ya está vencida.")
    return respuestas.exito(
        datos=operador,
        mensaje=f"Operador {operador['codigo_operador']} dado de alta.{nota}")


@router.put(
    "/{identificador}",
    response_model=Respuesta[OperadorSalida],
    summary="Actualizar la ficha de un operador",
    description=(
        "Edita nombre, licencia y fecha de ingreso. Enviar `licencia` es la "
        "vía para registrar una **renovación**. No acepta el estado ni los "
        "campos calculados (RN-O6)."
    ),
    responses={**RESPUESTAS_ADMIN,
               404: {"description": "No existe el operador."},
               409: {"description": "Viola RN-O1, RN-O2 o RN-O6."}},
)
def actualizar(bd: BaseDatos, datos: OperadorActualizar,
               identificador: str = Path(...),
               usuario: dict = SoloAdmin) -> dict[str, Any]:
    operador = servicio.actualizar(bd, identificador, datos.cambios())
    return respuestas.exito(
        datos=operador,
        mensaje=f"Operador {operador['codigo_operador']} actualizado.")


@router.patch(
    "/{identificador}/estado",
    response_model=Respuesta[OperadorSalida],
    summary="Activar o desactivar un operador",
    description=(
        "**RN-O3**: no se puede poner ACTIVO a un operador con la licencia "
        "vencida. Conducir sin licencia vigente es una infracción y el "
        "sistema no debería facilitarla; para reactivarlo hay que registrar "
        "antes la licencia renovada con `PUT /operadores/{id}`.\n\n"
        "Lo puede hacer el DESPACHADOR además del administrador."
    ),
    responses={403: {"description": "Requiere ADMINISTRADOR o DESPACHADOR."},
               404: {"description": "No existe el operador."},
               409: {"description": "Licencia vencida o estado sin cambio."}},
)
def cambiar_estado(bd: BaseDatos, datos: CambioEstadoOperador,
                   identificador: str = Path(...),
                   usuario: dict = AdminODespachador) -> dict[str, Any]:
    operador = servicio.cambiar_estado(bd, identificador, datos.estado,
                                       datos.motivo)
    return respuestas.exito(
        datos=operador,
        mensaje=f"Operador {operador['codigo_operador']} ahora está "
                f"{operador['estado']}.")


@router.delete(
    "/{identificador}",
    response_model=Respuesta[OperadorSalida],
    summary="Dar de baja un operador",
    description=(
        "Baja **lógica**: los viajes y las entregas que registró lo "
        "referencian.\n\n"
        "**RN-O5**: no se puede dar de baja a alguien con viajes sin "
        "cerrar; está en la calle y el viaje quedaría sin responsable."
    ),
    responses={**RESPUESTAS_ADMIN,
               404: {"description": "No existe el operador."},
               409: {"description": "Tiene viajes en curso (RN-O5)."}},
)
def desactivar(bd: BaseDatos, identificador: str = Path(...),
               usuario: dict = SoloAdmin) -> dict[str, Any]:
    operador = servicio.desactivar(bd, identificador)
    return respuestas.exito(
        datos=operador,
        mensaje=f"Operador {operador['codigo_operador']} dado de baja.")


@router.patch(
    "/{identificador}/reactivar",
    response_model=Respuesta[OperadorSalida],
    summary="Reactivar la ficha de un operador",
    description=(
        "Devuelve la ficha al sistema, pero lo deja **INACTIVO** a "
        "propósito: habilitarlo para conducir pasa por "
        "`PATCH /operadores/{id}/estado`, que comprueba la licencia. "
        "Recuperar el registro y autorizar a alguien a manejar no son la "
        "misma decisión."
    ),
    responses={**RESPUESTAS_ADMIN,
               404: {"description": "No existe el operador."},
               409: {"description": "El operador ya estaba activo."}},
)
def reactivar(bd: BaseDatos, identificador: str = Path(...),
              usuario: dict = SoloAdmin) -> dict[str, Any]:
    operador = servicio.reactivar(bd, identificador)
    return respuestas.exito(
        datos=operador,
        mensaje=(f"Operador {operador['codigo_operador']} reactivado, en "
                 "estado INACTIVO. Verifica su licencia antes de activarlo."))
