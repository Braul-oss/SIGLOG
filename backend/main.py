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

Interfaz web:               http://127.0.0.1:8000/
Documentación interactiva:  http://127.0.0.1:8000/docs
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
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pymongo.errors import PyMongoError

from backend.routers import (analitica, autenticacion, clientes, combustible,
                             entregas, incidentes, mantenimientos, ml,
                             operadores, reportes, rutas, sistema, usuarios,
                             vehiculos, viajes, vistas)
from backend.schemas.comunes import RespuestaError
from backend.utils import respuestas
from backend.utils.errores import ErrorSIGLOG
from backend.utils.seguridad import CredencialesInvalidas, PermisoDenegado
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
    print(f"  Interfaz web .. http://{settings.API_HOST}:{settings.API_PUERTO}/")
    print(f"  Documentación . http://{settings.API_HOST}:{settings.API_PUERTO}/docs")
    print(f"  Datos ......... SIMULADOS (decisión C-02)")

    # Advertencias de seguridad: mejor verlas al arrancar que descubrirlas
    # cuando nadie pueda entrar o cuando la clave ya esté comprometida.
    if settings.jwt_clave_es_insegura():
        print("  SEGURIDAD ..... JWT_CLAVE es la de desarrollo. Genera una con")
        print("                  python -c \"import secrets; print(secrets.token_hex(32))\"")
    if respuesta["exito"]:
        try:
            from backend.repositories.usuarios import RepositorioUsuarios
            from config.mongo_conexion import obtener_bd

            if not RepositorioUsuarios(obtener_bd()).hay_usuarios():
                print("  SEGURIDAD ..... no hay ningún usuario registrado. Crea el")
                print("                  primero con: python -m database.crear_usuario")
        except Exception:            # noqa: BLE001 — el aviso no puede tumbar el arranque
            pass
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


@app.exception_handler(CredencialesInvalidas)
async def manejar_credenciales(_: Request,
                               exc: CredencialesInvalidas) -> JSONResponse:
    """
    401 — no se pudo verificar quién hace la petición.

    Lleva la cabecera `WWW-Authenticate`, que el estándar HTTP exige en un
    401 y que los clientes usan para saber cómo autenticarse.
    """
    return JSONResponse(
        status_code=status.HTTP_401_UNAUTHORIZED,
        content=respuestas.error(exc.mensaje, exc.codigo_error, exc.detalles),
        headers={"WWW-Authenticate": "Bearer"},
    )


@app.exception_handler(PermisoDenegado)
async def manejar_permiso(_: Request, exc: PermisoDenegado) -> JSONResponse:
    """403 — la identidad es válida pero el rol no alcanza."""
    return JSONResponse(
        status_code=status.HTTP_403_FORBIDDEN,
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
app.include_router(autenticacion.router, prefix=settings.API_PREFIJO)
app.include_router(usuarios.router, prefix=settings.API_PREFIJO)
app.include_router(clientes.router, prefix=settings.API_PREFIJO)
app.include_router(vehiculos.router, prefix=settings.API_PREFIJO)
app.include_router(operadores.router, prefix=settings.API_PREFIJO)
app.include_router(rutas.router, prefix=settings.API_PREFIJO)
app.include_router(viajes.router, prefix=settings.API_PREFIJO)
app.include_router(entregas.router, prefix=settings.API_PREFIJO)
app.include_router(incidentes.router, prefix=settings.API_PREFIJO)
app.include_router(combustible.router, prefix=settings.API_PREFIJO)
app.include_router(mantenimientos.router, prefix=settings.API_PREFIJO)
app.include_router(analitica.router, prefix=settings.API_PREFIJO)
app.include_router(ml.router, prefix=settings.API_PREFIJO)
app.include_router(reportes.router, prefix=settings.API_PREFIJO)
app.include_router(sistema.router, prefix=settings.API_PREFIJO)

# --------------------------------------------------------------------------
# INTERFAZ WEB  (§8.2)
# --------------------------------------------------------------------------
# Las páginas van SIN el prefijo `/api/v1`: `/panel`, `/modulos/viajes`. La
# separación es intencional —el API es un contrato versionado y la interfaz
# no— y deja libre la posibilidad de publicar `/api/v2` sin tocar una sola
# plantilla.
#
# Los estáticos se sirven desde este mismo proceso. No hay build ni npm:
# Bootstrap y Chart.js llegan por CDN y lo propio son dos archivos.
app.mount("/static",
          StaticFiles(directory=str(settings.FRONTEND_ESTATICOS)),
          name="static")
app.include_router(vistas.router)

# --------------------------------------------------------------------------
# PUNTOS DE EXTENSIÓN — actividades posteriores
# --------------------------------------------------------------------------
# Quedan los manuales técnico y de usuario.


# ==========================================================================
# ARRANQUE
# ==========================================================================
def puerto_ocupado(host: str, puerto: int) -> bool:
    """
    Si ya hay algo escuchando en esa dirección.

    Se comprueba **antes** de arrancar por dos razones. La primera es el
    mensaje: al fallar el enlace, Windows devuelve
    `[WinError 10013] An attempt was made to access a socket in a way
    forbidden by its access permissions`, que suena a problema de permisos
    y no dice lo único que hace falta saber — que el puerto está tomado.

    La segunda es peor. En Windows, si el proceso que ocupa el puerto lo
    abrió con `SO_REUSEADDR`, un segundo servidor **enlaza sin protestar**
    y las peticiones se reparten entre ambos de forma impredecible: se
    acaba depurando un sistema que responde con dos versiones distintas del
    código según la petición.
    """
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as prueba:
        prueba.settimeout(0.6)
        return prueba.connect_ex((host, puerto)) == 0


def iniciar() -> None:
    """Levanta uvicorn con la configuración del .env."""
    import uvicorn

    if puerto_ocupado(settings.API_HOST, settings.API_PUERTO):
        direccion = f"{settings.API_HOST}:{settings.API_PUERTO}"
        print("=" * 70)
        print(f"  NO SE PUEDE ARRANCAR: el puerto {settings.API_PUERTO} ya "
              "está ocupado")
        print("=" * 70)
        print(f"  Algo responde ya en http://{direccion}. Casi siempre es")
        print("  otro SIG-LOG que quedó levantado de un arranque anterior.")
        print()
        print("  Para ver quién lo tiene y detenerlo:")
        print(f"      netstat -ano | findstr :{settings.API_PUERTO}")
        print("      taskkill /PID <pid> /F")
        print()
        print("  O arranca en otro puerto:")
        print(f"      API_PUERTO=8001 python app.py")
        print("=" * 70)
        raise SystemExit(1)

    uvicorn.run(
        "backend.main:app",
        host=settings.API_HOST,
        port=settings.API_PUERTO,
        reload=settings.API_RECARGA,
    )


if __name__ == "__main__":
    iniciar()
