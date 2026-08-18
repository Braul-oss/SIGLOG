"""
SIG-LOG — Sistema Integral de Gestión Logística
backend/routers/rutas.py

ENDPOINTS DEL MÓDULO RUTAS  (§12.3)

    GET    /rutas                        listar con filtros y paginación
    GET    /rutas/catalogos              zonas y días de operación
    GET    /rutas/resumen                conteo por zona y rutas sin vehículo
    GET    /rutas/{id}                   detalle con sus paradas
    GET    /rutas/{id}/analisis          perfil del ETL y grupo del clustering
    POST   /rutas                        crear
    PUT    /rutas/{id}                   actualizar la cabecera
    POST   /rutas/{id}/paradas           agregar una parada
    PUT    /rutas/{id}/paradas           reemplazar el itinerario completo
    DELETE /rutas/{id}/paradas/{orden}   quitar una parada
    PUT    /rutas/{id}/asignar-vehiculo  asignar o quitar el vehículo (RN-04)
    DELETE /rutas/{id}                   baja lógica
    PATCH  /rutas/{id}/reactivar         reactivar

`POST /rutas/{id}/paradas` y `PUT /rutas/{id}/asignar-vehiculo` son los dos
que el §12.3 pide expresamente para este recurso.

Permisos: consultar, cualquier sesión. Modificar, solo ADMINISTRADOR — el
§3 le asigna el diseño de rutas y la asignación vehículo↔ruta. Aquí no hay
excepción para el despachador: cambiar el trazado de una ruta no es
operación diaria, es rediseño.
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
from backend.schemas.rutas import (
    AsignacionVehiculo,
    Parada,
    ParadasReemplazar,
    RutaActualizar,
    RutaCrear,
    RutaSalida,
)
from backend.services import rutas as servicio
from backend.utils import respuestas
from config import settings

router = APIRouter(
    prefix="/rutas",
    tags=["Rutas"],
    responses={401: {"description": "Requiere sesión iniciada."}},
)

SoloAdmin = Depends(requiere_rol(settings.ROL_ADMINISTRADOR))
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
            "zonas": list(settings.CATALOGO_ZONA),
            "dias_operacion": list(settings.CATALOGO_DIAS_OPERACION),
            "nota_totales": (
                "distancia_total_km, tiempo_estimado_total_min, "
                "numero_paradas y velocidad_efectiva_kmh los calcula el "
                "sistema a partir de las paradas (RN-R2)."),
        },
        mensaje="Catálogos del módulo de rutas.",
    )


@router.get(
    "/resumen",
    response_model=Respuesta[dict[str, Any]],
    summary="Resumen de rutas por zona y cobertura",
)
def resumen(bd: BaseDatos, usuario: UsuarioAutenticado) -> dict[str, Any]:
    datos = servicio.resumen(bd)
    return respuestas.exito(datos=datos, mensaje=datos["alerta"],
                            total=datos["total"])


@router.get(
    "",
    response_model=Respuesta[list[RutaSalida]],
    summary="Listar rutas",
    description="Paginado, con búsqueda por nombre o código y filtros por "
                "zona y por si tienen vehículo asignado.",
)
def listar(bd: BaseDatos, usuario: UsuarioAutenticado, paginacion: PaginacionQuery,
           busqueda: str | None = Query(default=None),
           zona: str | None = Query(default=None),
           sin_vehiculo: bool | None = Query(
               default=None, description="true: solo rutas sin vehículo."),
           incluir_inactivos: bool = Query(default=False),
           ) -> dict[str, Any]:
    rutas, total = servicio.listar(
        bd, saltar=paginacion.saltar, limite=paginacion.tamano,
        busqueda=busqueda, zona=zona, sin_vehiculo=sin_vehiculo,
        incluir_inactivos=incluir_inactivos)
    return respuestas.exito(
        datos=rutas,
        mensaje=(f"{len(rutas)} ruta(s) en la página {paginacion.pagina} "
                 f"de {total} en total."),
        total=total,
    )


@router.get(
    "/{identificador}",
    response_model=Respuesta[RutaSalida],
    summary="Detalle de una ruta con sus paradas",
    responses={404: {"description": "No existe la ruta."}},
)
def obtener(bd: BaseDatos, usuario: UsuarioAutenticado,
            identificador: str = Path(...)) -> dict[str, Any]:
    ruta = servicio.obtener(bd, identificador)
    return respuestas.exito(
        datos=ruta,
        mensaje=(f"Ruta {ruta['codigo_ruta']} — {ruta['nombre']}, "
                 f"{ruta['numero_paradas']} parada(s)."),
        total=ruta["numero_paradas"],
    )


@router.get(
    "/{identificador}/analisis",
    response_model=Respuesta[dict[str, Any]],
    summary="Análisis operativo y grupo del clustering",
    description=(
        "Une el catálogo con lo que el proyecto extrajo de los datos: el "
        "perfil que el ETL dejó en `dim_ruta` y el grupo que le asignó "
        "K-Means, con su recomendación.\n\n"
        "No recalcula nada: son las mismas cifras del dashboard y del "
        "reporte de clustering."
    ),
    responses={404: {"description": "No existe la ruta."}},
)
def analisis(bd: BaseDatos, usuario: UsuarioAutenticado,
             identificador: str = Path(...)) -> dict[str, Any]:
    datos = servicio.analisis(bd, identificador)
    return respuestas.exito(datos=datos, mensaje=datos["lectura"])


# ==========================================================================
# ESCRITURA
# ==========================================================================
@router.post(
    "",
    response_model=Respuesta[RutaSalida],
    status_code=status.HTTP_201_CREATED,
    summary="Crear una ruta",
    description=(
        "El `codigo_ruta` lo asigna el sistema (RUT-NNN, RN-R1) y los "
        "totales se calculan a partir de las paradas (RN-R2). Cada parada "
        "debe apuntar a un cliente activo y a una dirección suya que exista "
        "(RN-R4), sin repetir clientes (RN-R5). La ruta nace sin vehículo."
    ),
    responses={**RESPUESTAS_ADMIN,
               409: {"description": "Viola RN-R3, RN-R4 o RN-R5."},
               422: {"description": "Datos fuera de catálogo o mal formados."}},
)
def crear(bd: BaseDatos, datos: RutaCrear,
          usuario: dict = SoloAdmin) -> dict[str, Any]:
    ruta = servicio.crear(bd, datos.model_dump())
    return respuestas.exito(
        datos=ruta,
        mensaje=(f"Ruta {ruta['codigo_ruta']} creada con "
                 f"{ruta['numero_paradas']} parada(s) y "
                 f"{ruta['distancia_total_km']} km."))


@router.put(
    "/{identificador}",
    response_model=Respuesta[RutaSalida],
    summary="Actualizar la cabecera de una ruta",
    description=(
        "Edita nombre, zona, origen, días de operación y hora de salida. "
        "**No** acepta las paradas ni los totales (RN-R2): las paradas "
        "tienen endpoints propios y los totales se derivan de ellas."
    ),
    responses={**RESPUESTAS_ADMIN,
               404: {"description": "No existe la ruta."},
               409: {"description": "Viola RN-R1 o RN-R2."}},
)
def actualizar(bd: BaseDatos, datos: RutaActualizar,
               identificador: str = Path(...),
               usuario: dict = SoloAdmin) -> dict[str, Any]:
    ruta = servicio.actualizar(bd, identificador, datos.cambios())
    return respuestas.exito(datos=ruta,
                            mensaje=f"Ruta {ruta['codigo_ruta']} actualizada.")


# ==========================================================================
# PARADAS
# ==========================================================================
@router.post(
    "/{identificador}/paradas",
    response_model=Respuesta[RutaSalida],
    summary="Agregar una parada al final del itinerario",
    description=(
        "El `orden` lo asigna el sistema por la posición (RN-R3) y los "
        "totales se recalculan (RN-R2)."
    ),
    responses={**RESPUESTAS_ADMIN,
               404: {"description": "No existe la ruta."},
               409: {"description": "Viola RN-R4 o RN-R5."}},
)
def agregar_parada(bd: BaseDatos, parada: Parada,
                   identificador: str = Path(...),
                   usuario: dict = SoloAdmin) -> dict[str, Any]:
    ruta = servicio.agregar_parada(bd, identificador, parada.model_dump())
    return respuestas.exito(
        datos=ruta,
        mensaje=(f"Parada agregada. La ruta {ruta['codigo_ruta']} tiene ahora "
                 f"{ruta['numero_paradas']} parada(s) y "
                 f"{ruta['distancia_total_km']} km."))


@router.put(
    "/{identificador}/paradas",
    response_model=Respuesta[RutaSalida],
    summary="Reemplazar el itinerario completo",
    description="Sustituye todas las paradas y renumera de 1 a N. Es la vía "
                "para reordenar el recorrido.",
    responses={**RESPUESTAS_ADMIN,
               404: {"description": "No existe la ruta."},
               409: {"description": "Viola RN-R3, RN-R4 o RN-R5."}},
)
def reemplazar_paradas(bd: BaseDatos, datos: ParadasReemplazar,
                       identificador: str = Path(...),
                       usuario: dict = SoloAdmin) -> dict[str, Any]:
    ruta = servicio.reemplazar_paradas(
        bd, identificador, [p.model_dump() for p in datos.paradas])
    return respuestas.exito(
        datos=ruta,
        mensaje=(f"Itinerario de {ruta['codigo_ruta']} reemplazado: "
                 f"{ruta['numero_paradas']} parada(s), "
                 f"{ruta['distancia_total_km']} km."))


@router.delete(
    "/{identificador}/paradas/{orden}",
    response_model=Respuesta[RutaSalida],
    summary="Quitar una parada",
    description=(
        "Elimina la parada indicada y **renumera** las siguientes, para que "
        "el orden no quede con huecos (RN-R3). Una ruta no puede quedarse "
        "sin paradas."
    ),
    responses={**RESPUESTAS_ADMIN,
               404: {"description": "No existe la ruta."},
               409: {"description": "No existe esa parada o es la última."}},
)
def quitar_parada(bd: BaseDatos, identificador: str = Path(...),
                  orden: int = Path(ge=1, description="Orden de la parada."),
                  usuario: dict = SoloAdmin) -> dict[str, Any]:
    ruta = servicio.quitar_parada(bd, identificador, orden)
    return respuestas.exito(
        datos=ruta,
        mensaje=(f"Parada {orden} eliminada. La ruta {ruta['codigo_ruta']} "
                 f"queda con {ruta['numero_paradas']} parada(s)."))


# ==========================================================================
# VEHÍCULO  (§12.3, RN-04)
# ==========================================================================
@router.put(
    "/{identificador}/asignar-vehiculo",
    response_model=Respuesta[RutaSalida],
    summary="Asignar o quitar el vehículo de la ruta",
    description=(
        "Aplica **RN-04**: una ruta tiene un solo vehículo y un vehículo "
        "una sola ruta. Envía `vehiculo_id: null` para desasignar.\n\n"
        "Internamente delega en el servicio de vehículos, que es donde vive "
        "la regla: así los dos extremos de la relación no pueden "
        "discrepar."
    ),
    responses={**RESPUESTAS_ADMIN,
               404: {"description": "No existe la ruta."},
               409: {"description": "El vehículo ya cubre otra ruta (RN-04)."}},
)
def asignar_vehiculo(bd: BaseDatos, datos: AsignacionVehiculo,
                     identificador: str = Path(...),
                     usuario: dict = SoloAdmin) -> dict[str, Any]:
    ruta = servicio.asignar_vehiculo(bd, identificador, datos.vehiculo_id)
    destino = ("sin vehículo asignado" if not ruta["vehiculo_asignado_id"]
               else f"asignada al vehículo {ruta['vehiculo_asignado_id']}")
    return respuestas.exito(
        datos=ruta, mensaje=f"Ruta {ruta['codigo_ruta']} {destino}.")


# ==========================================================================
# BAJA Y REACTIVACIÓN
# ==========================================================================
@router.delete(
    "/{identificador}",
    response_model=Respuesta[RutaSalida],
    summary="Dar de baja una ruta",
    description=(
        "Baja **lógica**: los viajes y las entregas históricas la "
        "referencian, y sobre ellas se construyen el DW y el clustering.\n\n"
        "**RN-R6**: no se puede dar de baja una ruta con vehículo asignado "
        "—quedaría apuntando a una ruta inactiva— ni con viajes sin cerrar."
    ),
    responses={**RESPUESTAS_ADMIN,
               404: {"description": "No existe la ruta."},
               409: {"description": "Tiene vehículo o viajes abiertos (RN-R6)."}},
)
def desactivar(bd: BaseDatos, identificador: str = Path(...),
               usuario: dict = SoloAdmin) -> dict[str, Any]:
    ruta = servicio.desactivar(bd, identificador)
    return respuestas.exito(datos=ruta,
                            mensaje=f"Ruta {ruta['codigo_ruta']} dada de baja.")


@router.patch(
    "/{identificador}/reactivar",
    response_model=Respuesta[RutaSalida],
    summary="Reactivar una ruta dada de baja",
    responses={**RESPUESTAS_ADMIN,
               404: {"description": "No existe la ruta."},
               409: {"description": "La ruta ya estaba activa."}},
)
def reactivar(bd: BaseDatos, identificador: str = Path(...),
              usuario: dict = SoloAdmin) -> dict[str, Any]:
    ruta = servicio.reactivar(bd, identificador)
    return respuestas.exito(datos=ruta,
                            mensaje=f"Ruta {ruta['codigo_ruta']} reactivada.")
