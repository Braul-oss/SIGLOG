"""
SIG-LOG — Sistema Integral de Gestión Logística
backend/routers/ml.py

ENDPOINTS DE MACHINE LEARNING  (§12.3, §15.4)

    GET  /ml/modelos             modelos entrenados y sus métricas
    GET  /ml/clusters-rutas      grupos de rutas (PA-9)
    GET  /ml/entregas-en-riesgo  pendientes ordenadas por riesgo
    POST /ml/predecir-retraso    predicción para una entrega

Consultar es de cualquier sesión. `predecir-retraso` está restringido a
administrador y despachador porque **escribe**: guarda la predicción en la
entrega, como pide el §15.4. No es una consulta disfrazada de POST.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from backend.dependencias import BaseDatos, UsuarioAutenticado, requiere_rol
from backend.schemas.comunes import Respuesta
from backend.schemas.ml import PrediccionSolicitud
from backend.services import ml as servicio
from backend.utils import respuestas
from config import settings

router = APIRouter(
    prefix="/ml",
    tags=["Machine Learning"],
    responses={401: {"description": "Requiere sesión iniciada."},
               503: {"description": "Los modelos aún no se han entrenado."}},
)

Operacion = Depends(requiere_rol(settings.ROL_ADMINISTRADOR,
                                 settings.ROL_DESPACHADOR))


@router.get(
    "/modelos",
    response_model=Respuesta[dict[str, Any]],
    summary="Modelos entrenados y sus métricas",
    description=(
        "Ficha de cada modelo vigente, tal como quedó registrada al "
        "entrenarlo: algoritmo, escenario, métricas de prueba, variables y "
        "semilla.\n\n"
        "`binario_disponible` avisa si el `.joblib` sigue en disco. Un "
        "modelo registrado cuyo archivo se borró aparecería como usable y "
        "fallaría al primer intento de predecir."
    ),
)
def modelos(bd: BaseDatos, usuario: UsuarioAutenticado) -> dict[str, Any]:
    datos = servicio.modelos(bd)
    return respuestas.exito(datos=datos, mensaje=datos["lectura"],
                            total=datos["total"])


@router.get(
    "/clusters-rutas",
    response_model=Respuesta[dict[str, Any]],
    summary="Agrupamiento de rutas (K-Means sobre PCA)",
    description=(
        "Los grupos de PA-9, con el perfil y la recomendación de cada uno.\n\n"
        "Se publica la silueta global a propósito: indica una **segmentación "
        "operativa útil**, no categorías naturales bien separadas. Las rutas "
        "forman un continuo, y el agrupamiento sirve para ordenarlo y "
        "priorizar, no para afirmar que existen tipos de ruta."
    ),
)
def clusters_rutas(bd: BaseDatos, usuario: UsuarioAutenticado) -> dict[str, Any]:
    datos = servicio.clusters_rutas(bd)
    return respuestas.exito(datos=datos, mensaje=datos["lectura"],
                            total=datos["total_rutas"])


@router.get(
    "/entregas-en-riesgo",
    response_model=Respuesta[dict[str, Any]],
    summary="Entregas pendientes ordenadas por riesgo",
    description=(
        "El punto 3 del §15.4: el conocimiento extraído vuelve a la pantalla "
        "de operación.\n\n"
        "Lista lo ya predicho; no predice en masa. Predecir cientos de "
        "entregas dentro de una petición convertiría una consulta en un "
        "trabajo por lotes."
    ),
)
def entregas_en_riesgo(bd: BaseDatos, usuario: UsuarioAutenticado,
                       limite: int = Query(default=20, ge=1, le=200),
                       ) -> dict[str, Any]:
    datos = servicio.entregas_en_riesgo(bd, limite)
    return respuestas.exito(datos=datos, mensaje=datos["lectura"],
                            total=datos["total"])


@router.post(
    "/predecir-retraso",
    response_model=Respuesta[dict[str, Any]],
    summary="Predecir el retraso de una entrega",
    description=(
        "Aplica el clasificador y el regresor del escenario que corresponda "
        "y devuelve las dos cifras: la **probabilidad**, para ordenar por "
        "riesgo y decidir a quién llamar, y los **minutos estimados**, para "
        "reprogramar una ventana concreta.\n\n"
        "El escenario no se elige: lo determina el estado del viaje. "
        "Mientras el viaje no haya salido no existen el retraso de salida ni "
        "los incidentes, y pedir EN_RUTA sería inventar datos — la misma "
        "fuga de información que se cuidó al entrenar (§15.1).\n\n"
        "**RN-ML1**: no se predice sobre una entrega ya cerrada. Su retraso "
        "está medido; una predicción sobre ella no es una predicción.\n\n"
        "La predicción **nunca toca** `hora_estimada_llegada`, por la misma "
        "razón que RN-I5 se lo prohíbe al recálculo de ETA: el retraso se "
        "mide contra ella."
    ),
    responses={403: {"description": "Requiere ADMINISTRADOR o DESPACHADOR."},
               404: {"description": "No existe la entrega."},
               409: {"description": "Entrega cerrada o sin datos de contexto."}},
)
def predecir_retraso(bd: BaseDatos, datos: PrediccionSolicitud,
                     usuario: dict = Operacion) -> dict[str, Any]:
    resultado = servicio.predecir_retraso(bd, datos.entrega_id,
                                          guardar=datos.guardar)
    return respuestas.exito(datos=resultado, mensaje=resultado["lectura"])
