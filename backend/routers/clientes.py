"""
SIG-LOG — Sistema Integral de Gestión Logística
backend/routers/clientes.py

ENDPOINTS DEL MÓDULO CLIENTES  (§12.3)

    GET    /clientes                 listar con filtros y paginación
    GET    /clientes/catalogos       tipos y municipios, para los formularios
    GET    /clientes/resumen         conteo por tipo y estado
    GET    /clientes/{id}            detalle
    POST   /clientes                 crear
    PUT    /clientes/{id}            actualizar
    DELETE /clientes/{id}            baja lógica
    PATCH  /clientes/{id}/reactivar  reactivar

Permisos
--------
Consultar: cualquier sesión. El DESPACHADOR necesita ver a los clientes
para registrar entregas y el ANALISTA para interpretar los reportes;
negárselo obligaría a darles rol de administrador, que es peor.

Modificar: solo ADMINISTRADOR. El §3 asigna al Administrador / Coordinador
logístico el "alta/baja de clientes, vehículos, operadores y rutas".

Como el permiso NO es uniforme en todo el módulo, se declara endpoint por
endpoint y no en el router. Ponerlo en el router obligaría a que leer
exigiera ser administrador.
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
from backend.schemas.clientes import ClienteActualizar, ClienteCrear, ClienteSalida
from backend.schemas.comunes import Respuesta
from backend.services import clientes as servicio
from backend.utils import respuestas
from config import settings

router = APIRouter(
    prefix="/clientes",
    tags=["Clientes"],
    responses={401: {"description": "Requiere sesión iniciada."}},
)

# Alias del permiso de escritura, para no repetir la dependencia completa.
SoloAdmin = Depends(requiere_rol(settings.ROL_ADMINISTRADOR))
RESPUESTAS_ESCRITURA = {403: {"description": "Requiere rol ADMINISTRADOR."}}


# ==========================================================================
# CONSULTA  (cualquier sesión)
# ==========================================================================
@router.get(
    "/catalogos",
    response_model=Respuesta[dict[str, Any]],
    summary="Catálogos para los formularios",
    description="Tipos de cliente (RNP-07) y municipios ya registrados, "
                "para poblar los selectores del alta y del filtro.",
)
def catalogos(bd: BaseDatos, usuario: UsuarioAutenticado) -> dict[str, Any]:
    return respuestas.exito(
        datos={
            "tipos_cliente": list(settings.CATALOGO_TIPO_CLIENTE),
            "municipios": servicio.resumen(bd)["municipios"],
        },
        mensaje="Catálogos del módulo de clientes.",
    )


@router.get(
    "/resumen",
    response_model=Respuesta[dict[str, Any]],
    summary="Resumen de clientes por tipo y estado",
)
def resumen(bd: BaseDatos, usuario: UsuarioAutenticado) -> dict[str, Any]:
    datos = servicio.resumen(bd)
    return respuestas.exito(
        datos=datos,
        mensaje=f"{datos['activos']} cliente(s) activo(s) de {datos['total']}.",
        total=datos["total"],
    )


@router.get(
    "",
    response_model=Respuesta[list[ClienteSalida]],
    summary="Listar clientes",
    description=(
        "Listado paginado con filtros por texto (nombre o código), tipo y "
        "municipio. Por omisión muestra solo los activos."
    ),
)
def listar(bd: BaseDatos, usuario: UsuarioAutenticado, paginacion: PaginacionQuery,
           busqueda: str | None = Query(
               default=None, description="Texto en el nombre o el código."),
           tipo_cliente: str | None = Query(default=None),
           municipio: str | None = Query(default=None),
           incluir_inactivos: bool = Query(default=False),
           ) -> dict[str, Any]:
    clientes, total = servicio.listar(
        bd, saltar=paginacion.saltar, limite=paginacion.tamano,
        busqueda=busqueda, tipo_cliente=tipo_cliente, municipio=municipio,
        incluir_inactivos=incluir_inactivos)
    return respuestas.exito(
        datos=clientes,
        mensaje=(f"{len(clientes)} cliente(s) en la página "
                 f"{paginacion.pagina} de {total} en total."),
        total=total,
    )


@router.get(
    "/{identificador}",
    response_model=Respuesta[ClienteSalida],
    summary="Detalle de un cliente",
    responses={404: {"description": "No existe el cliente."}},
)
def obtener(bd: BaseDatos, usuario: UsuarioAutenticado,
            identificador: str = Path(...)) -> dict[str, Any]:
    cliente = servicio.obtener(bd, identificador)
    return respuestas.exito(
        datos=cliente,
        mensaje=f"Cliente {cliente['codigo_cliente']} — {cliente['nombre']}.")


# ==========================================================================
# ESCRITURA  (solo ADMINISTRADOR)
# ==========================================================================
@router.post(
    "",
    response_model=Respuesta[ClienteSalida],
    status_code=status.HTTP_201_CREATED,
    summary="Crear un cliente",
    description=(
        "El `codigo_cliente` lo asigna el sistema con el formato CLI-NNN "
        "(RN-C1). Debe enviarse al menos una dirección y exactamente una "
        "marcada como principal; si se envía una sola sin marcar, se marca "
        "automáticamente (RN-C2)."
    ),
    responses={**RESPUESTAS_ESCRITURA,
               409: {"description": "Direcciones inválidas (RN-C2)."},
               422: {"description": "Datos fuera de catálogo o mal formados."}},
)
def crear(bd: BaseDatos, datos: ClienteCrear,
          usuario: dict = SoloAdmin) -> dict[str, Any]:
    cliente = servicio.crear(bd, datos.model_dump())
    return respuestas.exito(
        datos=cliente,
        mensaje=f"Cliente {cliente['codigo_cliente']} creado.",
    )


@router.put(
    "/{identificador}",
    response_model=Respuesta[ClienteSalida],
    summary="Actualizar un cliente",
    description=(
        "Aplica solo los campos enviados. Si se envían `direcciones`, "
        "**reemplazan** la lista completa y vuelven a validarse contra "
        "RN-C2. El `codigo_cliente` no se puede cambiar (RN-C1)."
    ),
    responses={**RESPUESTAS_ESCRITURA,
               404: {"description": "No existe el cliente."},
               409: {"description": "Viola RN-C1 o RN-C2."}},
)
def actualizar(bd: BaseDatos, datos: ClienteActualizar,
               identificador: str = Path(...),
               usuario: dict = SoloAdmin) -> dict[str, Any]:
    cliente = servicio.actualizar(bd, identificador, datos.cambios())
    return respuestas.exito(
        datos=cliente,
        mensaje=f"Cliente {cliente['codigo_cliente']} actualizado.")


@router.delete(
    "/{identificador}",
    response_model=Respuesta[ClienteSalida],
    summary="Dar de baja un cliente",
    description=(
        "Baja **lógica** (RN-C4): el documento se conserva porque las "
        "entregas históricas lo referencian y sobre ellas se construyen el "
        "DW y los modelos.\n\n"
        "**RN-C3**: no se puede dar de baja un cliente que sea parada de "
        "una ruta activa; hay que quitarlo antes de esas rutas."
    ),
    responses={**RESPUESTAS_ESCRITURA,
               404: {"description": "No existe el cliente."},
               409: {"description": "Es parada de una ruta activa (RN-C3)."}},
)
def desactivar(bd: BaseDatos, identificador: str = Path(...),
               usuario: dict = SoloAdmin) -> dict[str, Any]:
    cliente = servicio.desactivar(bd, identificador)
    return respuestas.exito(
        datos=cliente,
        mensaje=f"Cliente {cliente['codigo_cliente']} dado de baja.")


@router.patch(
    "/{identificador}/reactivar",
    response_model=Respuesta[ClienteSalida],
    summary="Reactivar un cliente dado de baja",
    responses={**RESPUESTAS_ESCRITURA,
               404: {"description": "No existe el cliente."},
               409: {"description": "El cliente ya estaba activo."}},
)
def reactivar(bd: BaseDatos, identificador: str = Path(...),
              usuario: dict = SoloAdmin) -> dict[str, Any]:
    cliente = servicio.reactivar(bd, identificador)
    return respuestas.exito(
        datos=cliente,
        mensaje=f"Cliente {cliente['codigo_cliente']} reactivado.")
