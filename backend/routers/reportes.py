"""
SIG-LOG — Sistema Integral de Gestión Logística
backend/routers/reportes.py

DESCARGA DE INFORMES EN PDF

    GET /reportes             qué informes hay y qué responde cada uno
    GET /reportes/{tipo}      descarga el PDF

El endpoint **no arma el documento**: llama a `reportes.generar.generar()`,
que es la misma función que usa la línea de comandos. Si hubiera dos
caminos de construcción, el PDF que descarga un usuario acabaría siendo
distinto del que se archiva, y nadie sabría cuál es el bueno.

Consultar es de cualquier sesión: un informe es lectura, y el analista —que
no puede tocar nada de la operación— existe justamente para leerlos.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from fastapi import APIRouter, Path as RutaPath
from fastapi.responses import Response

from backend.dependencias import BaseDatos, UsuarioAutenticado
from backend.schemas.comunes import Respuesta
from backend.utils import respuestas
from backend.utils.errores import NoEncontrado
from reportes import generar as generador

router = APIRouter(
    prefix="/reportes",
    tags=["Informes"],
    responses={401: {"description": "Requiere sesión iniciada."}},
)

DESCRIPCIONES = {
    "ejecutivo": {
        "titulo": "Informe ejecutivo",
        "para": "Dirección",
        "responde": [
            "¿Cómo va la operación?",
            "¿Mejora o empeora?",
            "¿Qué rutas presentan mayores retrasos?",
            "¿Qué vehículos generan mayores costos?",
            "¿Cuáles son las causas principales de retraso?",
            "¿Podemos identificar grupos de rutas similares?",
        ],
    },
    "flotilla": {
        "titulo": "Informe de flotilla",
        "para": "Coordinación de flotilla",
        "responde": [
            "¿Qué vehículos generan mayores costos?",
            "¿Qué vehículos consumen más combustible?",
            "¿Qué vehículos tienen más entregas?",
            "¿Qué vehículos presentan más retrasos?",
            "¿Qué vehículos requieren mantenimiento?",
        ],
    },
    "operativo": {
        "titulo": "Informe operativo",
        "para": "Despacho",
        "responde": [
            "¿Qué unidades están paradas ahora mismo?",
            "¿Qué operadores no pueden conducir?",
            "¿Qué incidentes siguen abiertos?",
            "¿Es posible predecir si una entrega llegará tarde?",
        ],
    },
}


@router.get(
    "",
    response_model=Respuesta[dict[str, Any]],
    summary="Informes disponibles",
    description="Qué informes se pueden descargar y qué pregunta de negocio "
                "responde cada uno.",
)
def catalogo(usuario: UsuarioAutenticado) -> dict[str, Any]:
    informes = [
        {"tipo": tipo, "archivo": generador.nombre_archivo(tipo),
         "url": f"/api/v1/reportes/{tipo}", **datos}
        for tipo, datos in DESCRIPCIONES.items()
    ]
    return respuestas.exito(
        datos={"informes": informes,
               "formato": "PDF",
               "nota": ("Cada página lleva la marca de datos simulados: un "
                        "PDF se reenvía y se imprime fuera del sistema, "
                        "donde ya no hay una pantalla que avise.")},
        mensaje=f"{len(informes)} informes disponibles en PDF.",
        total=len(informes))


@router.get(
    "/{tipo}",
    summary="Descargar un informe en PDF",
    description=(
        "Devuelve el documento generado en el momento, con los datos "
        "actuales. No se sirve ningún PDF guardado en disco: un informe "
        "archivado envejece y el lector no tendría forma de saberlo.\n\n"
        "Las gráficas se dibujan llamando a `analytics/graficas.py`, las "
        "mismas funciones que alimentan el dashboard."
    ),
    response_class=Response,
    responses={
        200: {"content": {"application/pdf": {}},
              "description": "El informe en PDF."},
        404: {"description": "Ese informe no existe."},
        503: {"description": "La capa analítica aún no está lista."},
    },
)
def descargar(bd: BaseDatos, usuario: UsuarioAutenticado,
              tipo: str = RutaPath(..., description="ejecutivo · flotilla · "
                                                    "operativo"),
              ) -> Response:
    if tipo not in generador.INFORMES:
        raise NoEncontrado(
            f"el informe '{tipo}'. Los disponibles son: "
            f"{', '.join(sorted(generador.INFORMES))}")

    contenido = generador.generar(tipo, bd)
    archivo = generador.nombre_archivo(tipo)
    return Response(
        content=contenido,
        media_type="application/pdf",
        headers={
            # `inline` para que el navegador lo abra en una pestaña; el
            # usuario decide si lo guarda. Forzar la descarga obligaría a
            # abrirlo desde el disco solo para echarle un vistazo.
            "Content-Disposition": f'inline; filename="{archivo}"',
            "X-Generado": datetime.now().isoformat(timespec="seconds"),
        },
    )
