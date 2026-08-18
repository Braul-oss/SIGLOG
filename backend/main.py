"""
SIG-LOG — Sistema Integral de Gestión Logística
backend/main.py

PUNTO DE ENTRADA DE LA API  (§12 del documento técnico base)

Arranca FastAPI, registra los manejadores de error que garantizan el
formato uniforme del §12.2, monta los routers bajo `/api/v1` y verifica la
conexión con MongoDB al iniciar.

Arquitectura del flujo (§7.2)
-----------------------------
    Frontend → FastAPI → Router → Service → Repository → MongoDB

Cada capa habla solo con la siguiente. Para las funciones analíticas el
recorrido se acorta, porque la capa ya existe y está probada:

    Frontend → FastAPI → Service → analytics/ · ml/ → MongoDB → respuesta

La regla que sostiene todo el diseño: el backend **no reimplementa** ETL,
KPIs ni modelos. Los importa. Duplicar esa lógica haría que la API y los
scripts dieran cifras distintas sobre los mismos datos, que es exactamente
el problema que el proyecto vino a resolver.

Ejecución
---------
    python -m backend.main                       # con la config del .env
    uvicorn backend.main:app --reload            # equivalente, recarga activa

Documentación interactiva: http://127.0.0.1:8000/docs
"""

from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from pymongo.errors import PyMongoError

from backend.routers import sistema
from backend.schemas.comunes import RespuestaError
from backend.utils import respuestas
from backend.utils.errores import ErrorSIGLOG
from config import settings
from config.mongo_conexion import cerrar_cliente, verificar_conexion


# ==========================================================================
# CICLO DE VIDA
# ==========================================================================
@asynccontextmanager
async def ciclo_de_vida(app: FastAPI):
    """
    Al arrancar comprueba MongoDB; al apagar cierra el cliente compartido.

    La comprobación NO aborta el arranque si falla: se registra el motivo y
    la API queda en pie para poder responder `/salud` y decir qué pasa. Un
    servicio que no arranca por una base caída no puede explicar nada.
    """
    print("=" * 70)
    print(f"  {settings.APP_NOMBRE} API v{settings.APP_VERSION} "
          f"· entorno {settings.APP_ENTORNO}")
    print("=" * 70)

    respuesta = verificar_conexion()
    if respuesta["exito"]:
        datos = respuesta["datos"]
        print(f"  MongoDB ....... conectado a '{datos['base_datos']}' "
              f"({datos['total_colecciones']} colecciones)")
    else:
        print(f"  MongoDB ....... NO DISPONIBLE [{respuesta.get('codigo_error')}]")
        print(f"                  {respuesta['mensaje']}")
        print("                  La API arranca igual; consulta /api/v1/salud/mongodb.")

    print(f"  API ........... http://{settings.API_HOST}:{settings.API_PUERTO}"
          f"{settings.API_PREFIJO}")
    print(f"  Documentación . http://{settings.API_HOST}:{settings.API_PUERTO}/docs")
    print(f"  Datos ......... SIMULADOS (decisión C-02)")
    print("=" * 70)

    yield

    cerrar_cliente()
    print("\n  Cliente de MongoDB cerrado. API detenida.")


# ==========================================================================
# APLICACIÓN
# ==========================================================================
app = FastAPI(
    title=settings.API_TITULO,
    description=settings.API_DESCRIPCION,
    version=settings.APP_VERSION,
    lifespan=ciclo_de_vida,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    responses={
        400: {"model": RespuestaError, "description": "Validación fallida"},
        404: {"model": RespuestaError, "description": "Recurso no encontrado"},
        409: {"model": RespuestaError, "description": "Conflicto de regla de negocio"},
        422: {"model": RespuestaError, "description": "Esquema inválido"},
        500: {"model": RespuestaError, "description": "Error interno"},
    },
)

# --------------------------------------------------------------------------
# CORS
# --------------------------------------------------------------------------
# El frontend previsto es Jinja2 servido por este mismo proceso (§8.2), así
# que el navegador no cruza orígenes y CORS no haría falta. Se habilita con
# una lista EXPLÍCITA —nunca "*"— para permitir abrir un frontend en otro
# puerto durante el desarrollo sin volver a tocar el código.
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.CORS_ORIGENES),
    allow_credentials=True,          # necesario para las cookies de sesión futuras
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["*"],
)


# ==========================================================================
# MANEJADORES DE ERROR  (§12.2)
# ==========================================================================
@app.exception_handler(ErrorSIGLOG)
async def manejar_error_dominio(_: Request, exc: ErrorSIGLOG) -> JSONResponse:
    """Errores de negocio: cada uno ya trae su código HTTP y su codigo_error."""
    return JSONResponse(
        status_code=exc.estado_http,
        content=respuestas.error(exc.mensaje, exc.codigo_error, exc.detalles),
    )


@app.exception_handler(RequestValidationError)
async def manejar_error_validacion(_: Request,
                                   exc: RequestValidationError) -> JSONResponse:
    """
    422 de Pydantic reescrito al formato del §12.2.

    El detalle se traduce a `campo`/`problema`: el formato nativo de
    Pydantic es útil para un desarrollador, no para un formulario.
    """
    detalles = [
        {
            "campo": ".".join(str(parte) for parte in error["loc"] if parte != "body"),
            "problema": error["msg"],
        }
        for error in exc.errors()
    ]
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content=respuestas.error(
            "Los datos enviados no cumplen el esquema esperado.",
            "ESQUEMA_INVALIDO", detalles),
    )


@app.exception_handler(PyMongoError)
async def manejar_error_mongo(_: Request, exc: PyMongoError) -> JSONResponse:
    """
    Cualquier fallo de PyMongo que llegue sin traducir es 503, no 500: el
    problema está en una dependencia externa, no en el código de la API.
    """
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content=respuestas.error(
            f"La base de datos no está disponible: {exc}",
            "SERVICIO_NO_DISPONIBLE"),
    )


@app.exception_handler(Exception)
async def manejar_error_no_previsto(_: Request, exc: Exception) -> JSONResponse:
    """
    Red de seguridad: ningún error escapa sin el formato uniforme.

    El mensaje al cliente es genérico a propósito —una traza expone rutas y
    detalles internos—, pero se imprime completa en el log del servidor.
    """
    import traceback

    print("ERROR NO CONTROLADO EN LA API:")
    traceback.print_exc()
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=respuestas.error(
            "Ocurrió un error interno. Revisa el log del servidor.",
            "ERROR_INTERNO"),
    )


# ==========================================================================
# RUTAS
# ==========================================================================
app.include_router(sistema.router, prefix=settings.API_PREFIJO)

# --------------------------------------------------------------------------
# PUNTOS DE EXTENSIÓN — actividades posteriores
# --------------------------------------------------------------------------
# Cada módulo se incorporará con una línea como la anterior:
#     app.include_router(clientes.router, prefix=settings.API_PREFIJO)
# Los routers de autenticación, los ocho módulos CRUD, /analitica y /ml
# quedan pendientes por indicación expresa del alcance de esta actividad.


@app.get("/", include_in_schema=False)
async def raiz() -> RedirectResponse:
    """La raíz lleva a la documentación interactiva."""
    return RedirectResponse(url="/docs")


# ==========================================================================
# ARRANQUE
# ==========================================================================
def iniciar() -> None:
    """Levanta uvicorn con la configuración del .env."""
    import uvicorn

    uvicorn.run(
        "backend.main:app",
        host=settings.API_HOST,
        port=settings.API_PUERTO,
        reload=settings.API_RECARGA,
    )


if __name__ == "__main__":
    iniciar()
