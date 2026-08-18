"""
SIG-LOG — Sistema Integral de Gestión Logística
backend/routers/combustible.py

ENDPOINTS DEL MÓDULO COMBUSTIBLE  (§12.3)

    GET  /combustible             listar con filtros y paginación
    GET  /combustible/catalogos   tipos y estaciones registradas
    GET  /combustible/resumen     consumo y costo agregado
    GET  /combustible/{id}        detalle de una carga
    POST /combustible             registrar una carga

`/resumen` es el que el §12.3 pide expresamente y el que responde dos
preguntas del caso de estudio: qué vehículos generan mayores costos y
cuáles consumen más combustible.

No hay PUT ni DELETE: el §11.8 establece que cada carga es un hecho
inmutable. Una carga mal registrada se corrige registrando el dato
correcto, no reescribiendo el histórico del que salen el rendimiento y el
costo por kilómetro.

Permisos: consultar, cualquier sesión. Registrar, ADMINISTRADOR y
DESPACHADOR — el §3 le asigna a este último las cargas de combustible.
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
from backend.schemas.combustible import CargaCrear, CargaSalida
from backend.schemas.comunes import Respuesta
from backend.services import combustible as servicio
from backend.utils import respuestas
from config import settings

router = APIRouter(
    prefix="/combustible",
    tags=["Combustible"],
    responses={401: {"description": "Requiere sesión iniciada."}},
)

Operacion = Depends(requiere_rol(settings.ROL_ADMINISTRADOR,
                                 settings.ROL_DESPACHADOR))


# ==========================================================================
# CONSULTA
# ==========================================================================
@router.get(
    "/catalogos",
    response_model=Respuesta[dict[str, Any]],
    summary="Tipos de combustible y estaciones registradas",
)
def catalogos(bd: BaseDatos, usuario: UsuarioAutenticado) -> dict[str, Any]:
    return respuestas.exito(
        datos=servicio.catalogos(bd),
        mensaje="Catálogos del módulo de combustible.")


@router.get(
    "/resumen",
    response_model=Respuesta[dict[str, Any]],
    summary="Consumo y costo agregado",
    description=(
        "Litros, costo, kilómetros y rendimiento de la flotilla, con el "
        "desglose por vehículo y por estación.\n\n"
        "Responde dos preguntas del caso de estudio: **qué vehículos "
        "generan mayores costos** y **cuáles consumen más combustible**. "
        "Incluye una lectura en lenguaje natural del conjunto."
    ),
)
def resumen(bd: BaseDatos, usuario: UsuarioAutenticado,
            top: int = Query(default=10, ge=1, le=50,
                             description="Vehículos a incluir en el desglose."),
            ) -> dict[str, Any]:
    datos = servicio.resumen(bd, top)
    return respuestas.exito(datos=datos, mensaje=datos["lectura"],
                            total=datos["cargas"])


@router.get(
    "",
    response_model=Respuesta[list[CargaSalida]],
    summary="Listar cargas de combustible",
    description="Paginado y ordenado de la más reciente a la más antigua, "
                "con filtros por vehículo, viaje, estación y fechas.",
)
def listar(bd: BaseDatos, usuario: UsuarioAutenticado, paginacion: PaginacionQuery,
           vehiculo_id: str | None = Query(default=None),
           viaje_id: str | None = Query(default=None),
           estacion: str | None = Query(default=None),
           fecha_desde: date | None = Query(default=None),
           fecha_hasta: date | None = Query(default=None),
           ) -> dict[str, Any]:
    cargas, total = servicio.listar(
        bd, saltar=paginacion.saltar, limite=paginacion.tamano,
        vehiculo_id=vehiculo_id, viaje_id=viaje_id, estacion=estacion,
        fecha_desde=fecha_desde, fecha_hasta=fecha_hasta)
    return respuestas.exito(
        datos=cargas,
        mensaje=(f"{len(cargas)} carga(s) en la página {paginacion.pagina} "
                 f"de {total} en total."),
        total=total,
    )


@router.get(
    "/{identificador}",
    response_model=Respuesta[CargaSalida],
    summary="Detalle de una carga",
    responses={404: {"description": "No existe la carga."}},
)
def obtener(bd: BaseDatos, usuario: UsuarioAutenticado,
            identificador: str = Path(...)) -> dict[str, Any]:
    carga = servicio.obtener(bd, identificador)
    rendimiento = (f"{carga['rendimiento_km_l']} km/l"
                   if carga["rendimiento_km_l"] else "sin tramo previo")
    return respuestas.exito(
        datos=carga,
        mensaje=(f"Carga {carga['folio_carga']}: {carga['litros']} L por "
                 f"${carga['costo_total']:,.2f} ({rendimiento})."))


# ==========================================================================
# REGISTRO
# ==========================================================================
@router.post(
    "",
    response_model=Respuesta[CargaSalida],
    status_code=status.HTTP_201_CREATED,
    summary="Registrar una carga de combustible",
    description=(
        "Registra la carga y calcula el costo, el tramo recorrido desde la "
        "carga anterior y el rendimiento km/l. También actualiza el "
        "odómetro del vehículo (**RN-F8**), completando lo que el §11.2 "
        "dice de ese campo: se actualiza con cada carga o viaje.\n\n"
        "Comprobaciones antes de aceptar:\n\n"
        "- **RN-F5**: el odómetro debe superar al de la carga anterior; el "
        "kilometraje no baja.\n"
        "- **RN-F6**: no caben más litros que la capacidad del tanque.\n"
        "- **RN-F7**: el combustible debe ser el de la unidad — no se le "
        "pone gasolina a un diésel.\n\n"
        "En la **primera carga** de un vehículo, `rendimiento_km_l` queda "
        "en null: sin carga previa no hay tramo que medir, y poner cero "
        "fingiría un recorrido que no ocurrió."
    ),
    responses={403: {"description": "Requiere rol ADMINISTRADOR o DESPACHADOR."},
               409: {"description": "Viola RN-F5, RN-F6 o RN-F7."}},
)
def registrar(bd: BaseDatos, datos: CargaCrear,
              usuario: dict = Operacion) -> dict[str, Any]:
    carga = servicio.registrar(bd, datos.model_dump())
    detalle = (f" Rendimiento del tramo: {carga['rendimiento_km_l']} km/l."
               if carga["rendimiento_km_l"] else
               " Primera carga de la unidad: sin tramo previo que medir.")
    return respuestas.exito(
        datos=carga,
        mensaje=(f"Carga {carga['folio_carga']} registrada: "
                 f"{carga['litros']} L por ${carga['costo_total']:,.2f}."
                 f"{detalle}"))
