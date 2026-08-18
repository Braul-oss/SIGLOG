"""
SIG-LOG — Sistema Integral de Gestión Logística
backend/routers/entregas.py

ENDPOINTS DEL MÓDULO ENTREGAS  (§12.3)

    GET   /entregas                 listar con filtros y paginación
    GET   /entregas/catalogos       estatus, transiciones y causas
    GET   /entregas/resumen         conteo y estado de la variable objetivo
    GET   /entregas/{id}            detalle con su historial
    POST  /entregas                 crear una entrega
    POST  /entregas/generar         generarlas todas desde la ruta del viaje
    PATCH /entregas/{id}/llegada    registrar la hora real → calcula el retraso
    PATCH /entregas/{id}/estatus    cambiar estatus + historial

Los dos PATCH son los que el §12.3 pide expresamente para este recurso.
`/llegada` es el endpoint más importante del sistema: es donde nacen
`retraso_min` y `es_retraso`, las dos variables que los modelos aprenden a
predecir.

Igual que en viajes, no hay DELETE: una entrega registrada es un hecho.
Se cancela cambiando su estatus, y el historial conserva quién lo hizo.

Permisos: consultar, cualquier sesión. Registrar, ADMINISTRADOR y
DESPACHADOR — el §3 le asigna a este último "registra jornadas, entregas,
horas reales, incidentes".
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
from backend.schemas.entregas import (
    CambioEstatusEntrega,
    EntregaCrear,
    EntregaSalida,
    GenerarEntregas,
    RegistrarLlegada,
)
from backend.services import entregas as servicio
from backend.services.entregas import TRANSICIONES_ENTREGA
from backend.utils import respuestas
from config import settings

router = APIRouter(
    prefix="/entregas",
    tags=["Entregas"],
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
    summary="Estatus, transiciones y causas de retraso",
)
def catalogos(usuario: UsuarioAutenticado) -> dict[str, Any]:
    return respuestas.exito(
        datos={
            "estatus": list(settings.CATALOGO_ESTATUS_ENTREGA),
            "transiciones": {k: list(v) for k, v in TRANSICIONES_ENTREGA.items()},
            "causas_retraso": list(settings.CATALOGO_TIPOS_INCIDENTE),
            "umbral_retraso_min": settings.UMBRAL_RETRASO_MIN,
            "nota_variable_objetivo": (
                "retraso_min y es_retraso los calcula el sistema al "
                "registrar la llegada. Son las variables objetivo de los "
                "modelos y no se capturan (RN-E2)."),
        },
        mensaje="Catálogos del módulo de entregas.",
    )


@router.get(
    "/resumen",
    response_model=Respuesta[dict[str, Any]],
    summary="Resumen de entregas y de la variable objetivo",
    description="Conteo por estatus y estado del retraso: entregas "
                "medibles, puntualidad y retraso medio, con el umbral "
                "RNP-01 que separa una entrega puntual de una retrasada.",
)
def resumen(bd: BaseDatos, usuario: UsuarioAutenticado) -> dict[str, Any]:
    datos = servicio.resumen(bd)
    return respuestas.exito(datos=datos, mensaje=datos["alerta"],
                            total=datos["total"])


@router.get(
    "",
    response_model=Respuesta[list[EntregaSalida]],
    summary="Listar entregas",
    description="Paginado, con filtros por viaje, cliente, ruta, estatus, "
                "rango de fechas y si llegaron retrasadas.",
)
def listar(bd: BaseDatos, usuario: UsuarioAutenticado, paginacion: PaginacionQuery,
           viaje_id: str | None = Query(default=None),
           cliente_id: str | None = Query(default=None),
           ruta_id: str | None = Query(default=None),
           estatus: str | None = Query(default=None),
           solo_retrasadas: bool | None = Query(
               default=None, description="true: solo las que superan el umbral."),
           fecha_desde: date | None = Query(default=None),
           fecha_hasta: date | None = Query(default=None),
           ) -> dict[str, Any]:
    entregas, total = servicio.listar(
        bd, saltar=paginacion.saltar, limite=paginacion.tamano,
        viaje_id=viaje_id, cliente_id=cliente_id, ruta_id=ruta_id,
        estatus=estatus, solo_retrasadas=solo_retrasadas,
        fecha_desde=fecha_desde, fecha_hasta=fecha_hasta)
    return respuestas.exito(
        datos=entregas,
        mensaje=(f"{len(entregas)} entrega(s) en la página "
                 f"{paginacion.pagina} de {total} en total."),
        total=total,
    )


@router.get(
    "/{identificador}",
    response_model=Respuesta[EntregaSalida],
    summary="Detalle de una entrega con su historial",
    responses={404: {"description": "No existe la entrega."}},
)
def obtener(bd: BaseDatos, usuario: UsuarioAutenticado,
            identificador: str = Path(...)) -> dict[str, Any]:
    entrega = servicio.obtener(bd, identificador)
    return respuestas.exito(
        datos=entrega,
        mensaje=(f"Entrega {entrega['folio_entrega']} — {entrega['estatus']} "
                 f"({entrega['nombre_cliente']})."))


# ==========================================================================
# ALTA
# ==========================================================================
@router.post(
    "",
    response_model=Respuesta[EntregaSalida],
    status_code=status.HTTP_201_CREATED,
    summary="Crear una entrega",
    description=(
        "Da de alta una entrega dentro de un viaje abierto. La ruta, el "
        "vehículo, el operador y la fecha se **heredan del viaje** (RN-E7), "
        "y el nombre del cliente, la placa y el nombre del operador se "
        "copian ahora para preservar el dato histórico (§10.4)."
    ),
    responses={**RESPUESTAS_OPERACION,
               409: {"description": "Viaje cerrado, parada repetida o cliente inválido."}},
)
def crear(bd: BaseDatos, datos: EntregaCrear,
          usuario: dict = Operacion) -> dict[str, Any]:
    entrega = servicio.crear(bd, datos.model_dump(), usuario["usuario"])
    return respuestas.exito(
        datos=entrega,
        mensaje=(f"Entrega {entrega['folio_entrega']} creada para "
                 f"{entrega['nombre_cliente']}."))


@router.post(
    "/generar",
    response_model=Respuesta[dict[str, Any]],
    status_code=status.HTTP_201_CREATED,
    summary="Generar las entregas de un viaje desde su ruta",
    description=(
        "Crea de una vez todas las entregas del viaje a partir de las "
        "paradas de su ruta, calculando el ETA de cada una acumulando los "
        "tiempos desde la salida programada.\n\n"
        "Es la operación normal: la ruta ya sabe a qué clientes se va y en "
        "qué orden; capturarlas una a una repetiría a mano lo que el plan "
        "ya dice."
    ),
    responses={**RESPUESTAS_OPERACION,
               409: {"description": "El viaje ya tiene entregas o su ruta no tiene paradas."}},
)
def generar(bd: BaseDatos, datos: GenerarEntregas,
            usuario: dict = Operacion) -> dict[str, Any]:
    resultado = servicio.generar_de_viaje(bd, datos.viaje_id, usuario["usuario"])
    return respuestas.exito(
        datos=resultado,
        mensaje=(f"{resultado['generadas']} entrega(s) generadas para el "
                 f"viaje {resultado['viaje']}."),
        total=resultado["generadas"])


# ==========================================================================
# OPERACIÓN  (§12.3)
# ==========================================================================
@router.patch(
    "/{identificador}/llegada",
    response_model=Respuesta[EntregaSalida],
    summary="Registrar la hora real de llegada",
    description=(
        "**El endpoint más importante del sistema.** Con la hora real se "
        "calculan `tiempo_real_min`, `retraso_min` y `es_retraso`: las dos "
        "últimas son las variables objetivo de la regresión y de la "
        "clasificación (RN-E2). Nunca se capturan; se derivan de las "
        "horas, porque los modelos deben aprender de lo que ocurrió y no "
        "de lo que alguien tecleó.\n\n"
        "**RN-E4**: el viaje debe estar EN_CURSO. No se entrega antes de "
        "salir, ni se registra una llegada sobre un viaje ya cerrado.\n\n"
        "**RN-E6**: la causa de retraso solo se acepta si la entrega "
        "efectivamente superó el umbral de "
        f"{settings.UMBRAL_RETRASO_MIN} minutos."
    ),
    responses={**RESPUESTAS_OPERACION,
               404: {"description": "No existe la entrega."},
               409: {"description": "Viaje no EN_CURSO, llegada ya registrada o causa improcedente."}},
)
def registrar_llegada(bd: BaseDatos, datos: RegistrarLlegada,
                      identificador: str = Path(...),
                      usuario: dict = Operacion) -> dict[str, Any]:
    entrega = servicio.registrar_llegada(bd, identificador, datos.model_dump(),
                                         usuario["usuario"])
    retraso = entrega.get("retraso_min")
    if retraso is None:
        detalle = ""
    elif entrega.get("es_retraso"):
        detalle = (f" Llegó con {retraso:+.1f} min: supera el umbral de "
                   f"{settings.UMBRAL_RETRASO_MIN} min.")
    else:
        detalle = f" Llegó con {retraso:+.1f} min, dentro del umbral."
    return respuestas.exito(
        datos=entrega,
        mensaje=f"Entrega {entrega['folio_entrega']} {entrega['estatus']}.{detalle}")


@router.patch(
    "/{identificador}/estatus",
    response_model=Respuesta[EntregaSalida],
    summary="Cambiar el estatus de la entrega",
    description=(
        "Aplica el catálogo RNP-08 y deja constancia en "
        "`historial_estatus` de **qué, cuándo y quién** (RN-E3). Sin esa "
        "constancia no se puede reconstruir qué pasó con una entrega.\n\n"
        "Los estatus finales —ENTREGADA, NO_ENTREGADA, CANCELADA— no "
        "admiten más cambios: el registro es el histórico."
    ),
    responses={**RESPUESTAS_OPERACION,
               404: {"description": "No existe la entrega."},
               409: {"description": "Transición no permitida (RN-E3)."}},
)
def cambiar_estatus(bd: BaseDatos, datos: CambioEstatusEntrega,
                    identificador: str = Path(...),
                    usuario: dict = Operacion) -> dict[str, Any]:
    entrega = servicio.cambiar_estatus(bd, identificador, datos.estatus,
                                       usuario["usuario"], datos.motivo)
    return respuestas.exito(
        datos=entrega,
        mensaje=(f"Entrega {entrega['folio_entrega']} ahora está "
                 f"{entrega['estatus']}."))
