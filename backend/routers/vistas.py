"""
SIG-LOG — Sistema Integral de Gestión Logística
backend/routers/vistas.py

PÁGINAS DE LA INTERFAZ WEB  (§8.2)

    GET  /                  entrada; lleva al panel o al formulario de acceso
    GET  /entrar            formulario de acceso
    POST /entrar            valida credenciales y abre la sesión
    GET  /salir             cierra la sesión
    GET  /panel             dashboard ejecutivo
    GET  /modulos/{clave}   pantalla de un módulo del dominio
    GET  /analitica         consultas agregadas
    GET  /ml                modelos, agrupamiento y predicción

Cómo se reparte el trabajo
--------------------------
Estas rutas devuelven **HTML**: la plantilla, el menú y la descripción de la
pantalla. Los datos los pide después el navegador al API que ya existe.

Es una decisión con una razón concreta. Si estas vistas leyeran y escribieran
por su cuenta, habría dos caminos hacia los mismos datos —el del API y el de
las páginas— y tarde o temprano se comportarían distinto: un filtro que en
una lista sí funciona y en la otra no, una regla que una valida y la otra se
salta. Con un solo camino de escritura, cualquier regla de negocio se aplica
una vez y vale para los dos clientes.

La única excepción son los KPIs del panel, que se piden en el servidor para
que la página llegue ya pintada. Es lectura pura y sale del mismo servicio
que atiende `/api/v1/analitica/kpis`, así que no abre un segundo camino.

Sobre el JavaScript
-------------------
Hay JavaScript, pero no hay framework, ni build, ni npm — que es lo que el
§8.2 descarta. Son dos archivos servidos como estáticos y Bootstrap por CDN.
El navegador manda la cookie de sesión sola; el JavaScript nunca ve el token
porque la cookie es HttpOnly.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated, Any

RAIZ = Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from fastapi import APIRouter, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from backend.dependencias import BaseDatos, UsuarioOpcional
from backend.services import analitica as servicio_analitica
from backend.services import autenticacion as servicio_autenticacion
from backend.utils.errores import ErrorSIGLOG
from backend.utils.seguridad import CredencialesInvalidas
from backend.vistas import catalogo
from backend.vistas.plantillas import plantillas
from config import settings

router = APIRouter(tags=["Interfaz web"], include_in_schema=False)


# ==========================================================================
# CONTEXTO COMÚN
# ==========================================================================
def _contexto(peticion: Request, usuario: dict | None,
              **extra: Any) -> dict[str, Any]:
    rol = usuario.get("rol") if usuario else None
    return {
        "request": peticion,
        "usuario": usuario,
        "rol": rol,
        "menu": catalogo.menu(rol),
        "app_nombre": settings.APP_NOMBRE,
        "app_version": settings.APP_VERSION,
        "entorno": settings.APP_ENTORNO,
        "prefijo_api": settings.API_PREFIJO,
        "es_admin": rol == settings.ROL_ADMINISTRADOR,
        **extra,
    }


def _al_acceso(destino: str = "/") -> RedirectResponse:
    """Sin sesión válida no hay página: al formulario de acceso."""
    return RedirectResponse(url=f"/entrar?destino={destino}",
                            status_code=status.HTTP_303_SEE_OTHER)


# ==========================================================================
# ACCESO
# ==========================================================================
@router.get("/", response_class=HTMLResponse)
def raiz(usuario: UsuarioOpcional) -> RedirectResponse:
    destino = "/panel" if usuario else "/entrar"
    return RedirectResponse(url=destino, status_code=status.HTTP_303_SEE_OTHER)


@router.get("/entrar", response_class=HTMLResponse)
def formulario_acceso(peticion: Request, usuario: UsuarioOpcional,
                      destino: str = "/panel"):
    if usuario:
        return RedirectResponse(url="/panel",
                                status_code=status.HTTP_303_SEE_OTHER)
    return plantillas.TemplateResponse(
        request=peticion, name="acceso.html", context=
        _contexto(peticion, None, destino=destino, error=None))


@router.post("/entrar", response_class=HTMLResponse)
def acceder(peticion: Request, bd: BaseDatos,
            usuario: Annotated[str, Form()],
            contrasena: Annotated[str, Form()],
            destino: Annotated[str, Form()] = "/panel"):
    """
    Valida las credenciales y guarda el token en la cookie de sesión.

    El fallo se responde con la misma página y un mensaje, no con un JSON:
    quien está viendo un formulario espera volver al formulario.

    El mensaje no distingue si falló el usuario o la contraseña. Es el mismo
    criterio del API: decir cuál de los dos era correcto convierte el
    formulario en un verificador de cuentas existentes.
    """
    try:
        sesion = servicio_autenticacion.iniciar_sesion(bd, usuario, contrasena)
    except (CredencialesInvalidas, ErrorSIGLOG) as error:
        return plantillas.TemplateResponse(
            request=peticion, name="acceso.html", context=
            _contexto(peticion, None, destino=destino, error=error.mensaje),
            status_code=status.HTTP_401_UNAUTHORIZED)

    # Solo se admiten destinos internos: un `destino` con dominio propio
    # convertiría el acceso en un trampolín hacia otro sitio.
    if not destino.startswith("/") or destino.startswith("//"):
        destino = "/panel"

    respuesta = RedirectResponse(url=destino,
                                 status_code=status.HTTP_303_SEE_OTHER)
    respuesta.set_cookie(
        key=settings.COOKIE_SESION,
        value=sesion["access_token"],
        max_age=settings.JWT_MINUTOS_EXPIRACION * 60,
        httponly=True,                       # el JavaScript no puede leerla
        samesite=settings.COOKIE_SAMESITE,   # defensa contra CSRF
        secure=settings.COOKIE_SEGURA,
        path="/",
    )
    return respuesta


@router.get("/salir")
def salir() -> RedirectResponse:
    """
    Cierra la sesión borrando la cookie.

    El token sigue siendo válido hasta que expire —así funciona un JWT, no
    hay lista de revocación—, pero deja de viajar en las peticiones del
    navegador, que es lo que el usuario entiende por salir.
    """
    respuesta = RedirectResponse(url="/entrar",
                                 status_code=status.HTTP_303_SEE_OTHER)
    respuesta.delete_cookie(settings.COOKIE_SESION, path="/")
    return respuesta


# ==========================================================================
# PANEL
# ==========================================================================
@router.get("/panel", response_class=HTMLResponse)
def panel(peticion: Request, bd: BaseDatos, usuario: UsuarioOpcional):
    """
    Dashboard ejecutivo: los diez indicadores del Panel A (§18.2).

    Los KPIs se piden aquí, en el servidor, para que la página llegue ya
    pintada. Si el data warehouse todavía no se ha cargado, la pantalla lo
    dice y explica qué ejecutar, en vez de quedarse en blanco.
    """
    if not usuario:
        return _al_acceso("/panel")

    indicadores: list[dict[str, Any]] = []
    resumen = ""
    aviso = ""
    try:
        datos = servicio_analitica.kpis(bd)
        indicadores = datos["indicadores"]
        resumen = datos["resumen_ejecutivo"]
    except ErrorSIGLOG as error:
        aviso = error.mensaje

    return plantillas.TemplateResponse(
        request=peticion, name="panel.html", context=
        _contexto(peticion, usuario, indicadores=indicadores,
                  resumen_ejecutivo=resumen, aviso=aviso,
                  umbral=settings.UMBRAL_RETRASO_MIN))


# ==========================================================================
# MÓDULOS DEL DOMINIO
# ==========================================================================
@router.get("/modulos/{clave}", response_class=HTMLResponse)
def modulo(peticion: Request, clave: str, usuario: UsuarioOpcional):
    if not usuario:
        return _al_acceso(f"/modulos/{clave}")

    definicion = catalogo.POR_CLAVE.get(clave)
    if definicion is None:
        return plantillas.TemplateResponse(
            request=peticion, name="error.html", context=
            _contexto(peticion, usuario, codigo=404,
                      titulo_error="Ese módulo no existe",
                      detalle=f"No hay ninguna pantalla con la clave "
                              f"'{clave}'."),
            status_code=status.HTTP_404_NOT_FOUND)

    rol = usuario.get("rol")
    if clave == "usuarios" and rol != settings.ROL_ADMINISTRADOR:
        return plantillas.TemplateResponse(
            request=peticion, name="error.html", context=
            _contexto(peticion, usuario, codigo=403,
                      titulo_error="Solo para administradores",
                      detalle="La gestión de cuentas está reservada al rol "
                              "ADMINISTRADOR."),
            status_code=status.HTTP_403_FORBIDDEN)

    return plantillas.TemplateResponse(
        request=peticion, name="modulo.html", context=
        _contexto(peticion, usuario, modulo=definicion,
                  modulo_json=definicion.a_json(),
                  puede_escribir=catalogo.puede_escribir(definicion, rol)))


# ==========================================================================
# ANALÍTICA Y ML
# ==========================================================================
@router.get("/analitica", response_class=HTMLResponse)
def analitica(peticion: Request, usuario: UsuarioOpcional):
    if not usuario:
        return _al_acceso("/analitica")
    return plantillas.TemplateResponse(
        request=peticion, name="analitica.html", context=
        _contexto(peticion, usuario, umbral=settings.UMBRAL_RETRASO_MIN))


@router.get("/ml", response_class=HTMLResponse)
def aprendizaje(peticion: Request, usuario: UsuarioOpcional):
    if not usuario:
        return _al_acceso("/ml")
    rol = usuario.get("rol")
    return plantillas.TemplateResponse(
        request=peticion, name="ml.html", context=
        _contexto(peticion, usuario,
                  puede_predecir=rol in (settings.ROL_ADMINISTRADOR,
                                         settings.ROL_DESPACHADOR),
                  umbral=settings.UMBRAL_RETRASO_MIN))
