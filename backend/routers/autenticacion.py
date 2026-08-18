"""
SIG-LOG — Sistema Integral de Gestión Logística
backend/routers/autenticacion.py

ENDPOINTS DE ACCESO  (RNP-11, opción b)

    POST /auth/login              iniciar sesión y obtener el token
    GET  /auth/yo                 quién soy (verifica el token)
    POST /auth/cambiar-contrasena cambiar la contraseña propia
    GET  /auth/estado             diagnóstico del subsistema (sin autenticar)

El login acepta el formulario estándar de OAuth2 (`username`/`password`),
que es lo que envía el botón «Authorize» de la documentación interactiva.
Esa compatibilidad es la que permite probar los endpoints protegidos desde
/docs sin herramientas externas.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, status
from fastapi.security import OAuth2PasswordRequestForm

from backend.dependencias import BaseDatos, UsuarioAutenticado
from backend.schemas.autenticacion import CambioContrasena, Token, UsuarioSalida
from backend.schemas.comunes import Respuesta
from backend.services import autenticacion as servicio
from backend.utils import respuestas

router = APIRouter(prefix="/auth", tags=["Autenticación"])


@router.post(
    "/login",
    response_model=Respuesta[Token],
    summary="Iniciar sesión y obtener un token",
    description=(
        "Valida las credenciales y devuelve un token JWT con vigencia "
        "limitada. Envíalo en las peticiones protegidas con la cabecera "
        "`Authorization: Bearer <token>`.\n\n"
        "Acepta el formulario estándar de OAuth2, de modo que el botón "
        "**Authorize** de esta documentación funciona directamente."
    ),
    responses={401: {"description": "Usuario o contraseña incorrectos."}},
)
def login(bd: BaseDatos,
          formulario: Annotated[OAuth2PasswordRequestForm, Depends()]
          ) -> dict[str, Any]:
    sesion = servicio.iniciar_sesion(bd, formulario.username, formulario.password)
    return respuestas.exito(
        datos=sesion,
        mensaje=f"Sesión iniciada como {sesion['usuario']} ({sesion['rol']}).",
    )


@router.get(
    "/yo",
    response_model=Respuesta[UsuarioSalida],
    summary="Datos del usuario autenticado",
    description=(
        "Devuelve la cuenta asociada al token. Sirve para que el frontend "
        "sepa quién entró y qué rol tiene, y para comprobar que un token "
        "sigue siendo válido. Nunca incluye el hash de la contraseña."
    ),
    responses={401: {"description": "Token ausente, inválido o expirado."}},
)
def yo(usuario: UsuarioAutenticado) -> dict[str, Any]:
    return respuestas.exito(
        datos=UsuarioSalida.desde_documento(usuario).model_dump(),
        mensaje=f"Sesión activa de {usuario['usuario']}.",
    )


@router.post(
    "/cambiar-contrasena",
    response_model=Respuesta[dict],
    status_code=status.HTTP_200_OK,
    summary="Cambiar la contraseña propia",
    description=(
        "Exige la contraseña actual además de la sesión iniciada, para que "
        "encontrarse una sesión abierta no baste para apropiarse de la "
        "cuenta."
    ),
    responses={
        400: {"description": "La contraseña nueva no cumple las reglas."},
        401: {"description": "La contraseña actual no es correcta."},
    },
)
def cambiar_contrasena(bd: BaseDatos, usuario: UsuarioAutenticado,
                       datos: CambioContrasena) -> dict[str, Any]:
    servicio.cambiar_contrasena(bd, usuario,
                                datos.contrasena_actual, datos.contrasena_nueva)
    return respuestas.exito(
        datos={"usuario": usuario["usuario"]},
        mensaje="Contraseña actualizada. Vuelve a iniciar sesión.",
    )


@router.get(
    "/estado",
    response_model=Respuesta[dict],
    summary="Estado del subsistema de seguridad",
    description=(
        "Informa del método de autenticación, los roles disponibles y las "
        "advertencias de configuración (por ejemplo, si aún no hay ningún "
        "usuario o si los tokens se firman con la clave de desarrollo). No "
        "requiere autenticación y no expone ninguna cuenta: sin él, un "
        "sistema recién instalado no tendría forma de decir por qué nadie "
        "puede entrar."
    ),
)
def estado(bd: BaseDatos) -> dict[str, Any]:
    diagnostico = servicio.estado_seguridad(bd)
    mensaje = ("Subsistema de seguridad configurado correctamente."
               if not diagnostico["advertencias"]
               else f"Atención: {len(diagnostico['advertencias'])} advertencia(s) "
                    "de configuración.")
    return respuestas.exito(datos=diagnostico, mensaje=mensaje)
