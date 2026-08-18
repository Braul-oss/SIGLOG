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
    summary="Rutas por volumen, con su retraso medio",
    description="Ordenadas por entregas. La bandera `sobre_umbral` marca las "
                "que promedian más retraso del admitido: son las que más "
                "pesan, porque su impacto se multiplica por el volumen.",
)
def rutas_mas_usadas(bd: BaseDatos, usuario: UsuarioAutenticado,
                     top: int = Query(default=10, ge=1, le=100),
                     ) -> dict[str, Any]:
    datos = servicio.rutas_mas_usadas(bd, top)
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
