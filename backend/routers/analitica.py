"""
SIG-LOG — Sistema Integral de Gestión Logística
backend/routers/analitica.py

ENDPOINTS DE LA CAPA ANALÍTICA  (§12.3)

    GET /analitica/kpis                 indicadores del dashboard
    GET /analitica/rutas-mas-usadas     consulta agregada
    GET /analitica/causas-retraso       Pareto de causas
    GET /analitica/saturacion-horaria   entregas por franja y día

Todos son de consulta y quedan abiertos a cualquier sesión: el analista
—que no puede tocar nada de la operación— existe precisamente para leer
esto.

Cada respuesta trae su campo `lectura`: la interpretación en lenguaje
natural que pide RF-29. Un número sin contexto no ayuda a decidir, y el
frontend no debería tener que redactarla.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from backend.dependencias import BaseDatos, UsuarioAutenticado
from backend.schemas.comunes import Respuesta
from backend.services import analitica as servicio
from backend.utils import respuestas

router = APIRouter(
    prefix="/analitica",
    tags=["Analítica"],
    responses={401: {"description": "Requiere sesión iniciada."},
               503: {"description": "El data warehouse aún no se ha cargado."}},
)


@router.get(
    "/kpis",
    response_model=Respuesta[dict[str, Any]],
    summary="Indicadores del dashboard ejecutivo",
    description=(
        "Los diez indicadores del Panel A (§18.2), cada uno con su valor, "
        "su semáforo y su lectura en lenguaje natural (RF-29).\n\n"
        "Los calcula `analytics/kpis.py`, que sigue siendo el único lugar "
        "donde están definidos: el API no recalcula métricas por su cuenta "
        "(regla de la capa 8, §7.3)."
    ),
)
def kpis(bd: BaseDatos, usuario: UsuarioAutenticado) -> dict[str, Any]:
    datos = servicio.kpis(bd)
    return respuestas.exito(datos=datos, mensaje=datos["resumen_ejecutivo"],
                            total=datos["total_indicadores"])


@router.get(
    "/rutas-mas-usadas",
    response_model=Respuesta[dict[str, Any]],
    summary="Rutas por volumen, retraso o incidencia",
    description=(
        "Un mismo listado responde tres preguntas del proyecto según cómo se "
        "ordene:\n\n"
        "- `volumen` — **¿qué rutas son más utilizadas?**\n"
        "- `retraso` — **¿qué rutas presentan mayores retrasos?**\n"
        "- `incidencia` — ¿en qué rutas se retrasa una proporción mayor de "
        "entregas? No es lo mismo: una ruta puede desviarse pocos minutos "
        "cada vez y aun así incumplir casi siempre.\n\n"
        "Al ordenar por promedio se descartan las rutas con menos de 50 "
        "entregas: el promedio de una muestra diminuta es ruido con "
        "apariencia de dato."
    ),
    responses={409: {"description": "Criterio de orden no válido."}},
)
def rutas_mas_usadas(bd: BaseDatos, usuario: UsuarioAutenticado,
                     top: int = Query(default=10, ge=1, le=100),
                     orden: str = Query(
                         default="volumen",
                         description="volumen · retraso · incidencia"),
                     ) -> dict[str, Any]:
    datos = servicio.rutas_mas_usadas(bd, top, orden)
    return respuestas.exito(datos=datos, mensaje=datos["lectura"],
                            total=datos["total"])


@router.get(
    "/vehiculos",
    response_model=Respuesta[dict[str, Any]],
    summary="Desempeño de la flotilla",
    description=(
        "Una fila por vehículo con lo que decide si conviene mantenerlo en "
        "operación. Responde cuatro preguntas del proyecto según el "
        "criterio de orden:\n\n"
        "- `costo` — **¿qué vehículos generan mayores costos?**\n"
        "- `combustible` — **¿qué vehículos consumen más combustible?**\n"
        "- `entregas` — ¿cuáles trabajan más?\n"
        "- `retraso` — ¿cuáles llegan tarde con más frecuencia?\n"
        "- `rendimiento` — ¿cuáles se apartan más de su km/l de ficha?\n"
        "- `uso` — ¿cuáles acumulan más kilómetros?\n\n"
        "Los costos, los litros y el mantenimiento salen de `dim_vehiculo`, "
        "que es donde el ETL los consolidó; las entregas y los retrasos, de "
        "`hecho_entrega`. Ninguna cifra se recalcula aquí."
    ),
    responses={409: {"description": "Criterio no válido."},
               503: {"description": "El almacén analítico aún no se ha cargado."}},
)
def desempeno_vehiculos(bd: BaseDatos, usuario: UsuarioAutenticado,
                        orden: str = Query(
                            default="costo",
                            description="costo · combustible · entregas · "
                                        "retraso · rendimiento · uso"),
                        top: int = Query(default=20, ge=1, le=100),
                        ) -> dict[str, Any]:
    datos = servicio.desempeno_vehiculos(bd, orden, top)
    return respuestas.exito(datos=datos, mensaje=datos["lectura"],
                            total=datos["total"])


@router.get(
    "/operadores",
    response_model=Respuesta[dict[str, Any]],
    summary="Desempeño de los operadores",
    description=(
        "**¿Qué operadores realizan más entregas?**, y con qué puntualidad. "
        "Ordenable por `entregas`, `puntualidad` (de peor a mejor) o "
        "`retraso`.\n\n"
        "El volumen por sí solo no mide desempeño: la respuesta incluye la "
        "puntualidad media de la plantilla para poder situar a cada uno "
        "frente al resto."
    ),
    responses={409: {"description": "Criterio no válido."},
               503: {"description": "El almacén analítico aún no se ha cargado."}},
)
def desempeno_operadores(bd: BaseDatos, usuario: UsuarioAutenticado,
                         orden: str = Query(
                             default="entregas",
                             description="entregas · puntualidad · retraso"),
                         top: int = Query(default=30, ge=1, le=100),
                         ) -> dict[str, Any]:
    datos = servicio.desempeno_operadores(bd, orden, top)
    return respuestas.exito(datos=datos, mensaje=datos["lectura"],
                            total=datos["total"])


@router.get(
    "/tendencia",
    response_model=Respuesta[dict[str, Any]],
    summary="Evolución de las entregas y del retraso",
    description=(
        "Serie temporal por semana o por mes. Una cifra agregada no dice si "
        "la situación mejora o empeora, y esa es la pregunta de quien mira "
        "un panel.\n\n"
        "La lectura compara el primer tercio del periodo contra el último: "
        "enfrentar solo el primer punto con el último sería frágil, porque "
        "una semana atípica invertiría la conclusión."
    ),
    responses={409: {"description": "Agrupación no válida."}},
)
def tendencia(bd: BaseDatos, usuario: UsuarioAutenticado,
              agrupacion: str = Query(default="semana",
                                      description="semana · mes"),
              ) -> dict[str, Any]:
    datos = servicio.tendencia(bd, agrupacion)
    return respuestas.exito(datos=datos, mensaje=datos["lectura"],
                            total=datos["total"])


@router.get(
    "/causas-retraso",
    response_model=Respuesta[dict[str, Any]],
    summary="Pareto de las causas de retraso",
    description=(
        "Causas ordenadas por frecuencia, con su porcentaje acumulado. "
        "`es_vital` marca los *pocos vitales*: las causas necesarias para "
        "llegar al 80%, **incluida** la que cruza esa línea."
    ),
)
def causas_retraso(bd: BaseDatos, usuario: UsuarioAutenticado) -> dict[str, Any]:
    datos = servicio.causas_retraso(bd)
    return respuestas.exito(datos=datos, mensaje=datos["lectura"],
                            total=datos["total_retrasadas"])


@router.get(
    "/saturacion-horaria",
    response_model=Respuesta[dict[str, Any]],
    summary="Entregas por franja horaria y día de la semana",
    description=(
        "El data warehouse guarda la franja, no la hora exacta: es el grano "
        "al que el diseño decidió analizar la saturación (D-T1).\n\n"
        "La lectura solo recomienda mover carga cuando la franja más cargada "
        "no es ya la de menor retraso."
    ),
)
def saturacion_horaria(bd: BaseDatos, usuario: UsuarioAutenticado
                       ) -> dict[str, Any]:
    datos = servicio.saturacion_horaria(bd)
    return respuestas.exito(datos=datos, mensaje=datos["lectura"],
                            total=datos["total_entregas"])
