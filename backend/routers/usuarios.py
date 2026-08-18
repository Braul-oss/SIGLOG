"""
SIG-LOG — Sistema Integral de Gestión Logística
backend/routers/usuarios.py

ENDPOINTS DE GESTIÓN DE USUARIOS Y ROLES

    GET    /usuarios                      listar (paginado y filtrable)
    GET    /usuarios/roles                catálogo de roles
    GET    /usuarios/resumen              conteo por rol y estado
    GET    /usuarios/{id}                 detalle
    POST   /usuarios                      alta
    PUT    /usuarios/{id}                 editar datos descriptivos
    PATCH  /usuarios/{id}/rol             cambiar rol
    PATCH  /usuarios/{id}/contrasena      restablecer contraseña
    DELETE /usuarios/{id}                 baja lógica
    PATCH  /usuarios/{id}/reactivar       reactivar una cuenta

**Todo el módulo exige rol ADMINISTRADOR.** La restricción se declara una
sola vez, en `dependencies` del router, en lugar de repetirla endpoint por
endpoint: así no puede olvidarse en uno nuevo, que es como se abren los
agujeros de permisos.

Nota sobre el orden de las rutas: `/usuarios/roles` y `/usuarios/resumen`
se declaran ANTES que `/usuarios/{id}`. Si fuera al revés, FastAPI
interpretaría "roles" como un identificador y esas rutas nunca se
alcanzarían.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Path, Query, status

from backend.dependencias import BaseDatos, PaginacionQuery, requiere_rol
from backend.schemas.autenticacion import UsuarioSalida
from backend.schemas.comunes import Respuesta
from backend.schemas.usuarios import (
    CambioRol,
    RestablecerContrasena,
    RolInfo,
    UsuarioActualizar,
    UsuarioCrear,
)
from backend.services import usuarios as servicio
from backend.utils import respuestas
from config import settings

router = APIRouter(
    prefix="/usuarios",
    tags=["Usuarios y roles"],
    # Una sola declaración protege todo el módulo, presente y futuro.
    dependencies=[Depends(requiere_rol(settings.ROL_ADMINISTRADOR))],
    responses={
        401: {"description": "Requiere sesión iniciada."},
        403: {"description": "Requiere rol ADMINISTRADOR."},
    },
)


# ==========================================================================
# CONSULTA
# ==========================================================================
@router.get(
    "/roles",
    response_model=Respuesta[list[RolInfo]],
    summary="Catálogo de roles",
    description="Roles disponibles con su actor y su descripción, para "
                "poblar el selector del formulario de alta.",
)
def listar_roles() -> dict[str, Any]:
    return respuestas.exito(
        datos=servicio.catalogo_de_roles(),
        mensaje=f"{len(settings.CATALOGO_ROLES)} roles disponibles.",
    )


@router.get(
    "/resumen",
    response_model=Respuesta[dict[str, Any]],
    summary="Resumen de cuentas por rol y estado",
    description="Conteo de cuentas activas e inactivas y reparto por rol. "
                "Incluye `administradores_activos`, que es el número que "
                "protege la regla RN-U3.",
)
def resumen(bd: BaseDatos) -> dict[str, Any]:
    datos = servicio.resumen(bd)
    return respuestas.exito(
        datos=datos,
        mensaje=(f"{datos['activos']} cuenta(s) activa(s) de {datos['total']}."),
        total=datos["total"],
    )


@router.get(
    "",
    response_model=Respuesta[list[UsuarioSalida]],
    summary="Listar usuarios",
    description=(
        "Listado paginado. Por omisión muestra solo las cuentas activas; "
        "usa `incluir_inactivos=true` para ver también las dadas de baja. "
        "Nunca devuelve el hash de la contraseña."
    ),
)
def listar(bd: BaseDatos, paginacion: PaginacionQuery,
           rol: str | None = Query(default=None,
                                   description="Filtra por rol."),
           incluir_inactivos: bool = Query(
               default=False, description="Incluye las cuentas dadas de baja."),
           ) -> dict[str, Any]:
    cuentas, total = servicio.listar(
        bd, saltar=paginacion.saltar, limite=paginacion.tamano,
        rol=rol, incluir_inactivos=incluir_inactivos)
    return respuestas.exito(
        datos=cuentas,
        mensaje=(f"{len(cuentas)} usuario(s) en la página "
                 f"{paginacion.pagina} de {total} en total."),
        total=total,
    )


@router.get(
    "/{identificador}",
    response_model=Respuesta[UsuarioSalida],
    summary="Detalle de un usuario",
    responses={404: {"description": "No existe la cuenta."}},
)
def obtener(bd: BaseDatos,
            identificador: str = Path(description="Identificador del documento."),
            ) -> dict[str, Any]:
    cuenta = servicio.obtener(bd, identificador)
    return respuestas.exito(datos=cuenta,
                            mensaje=f"Usuario '{cuenta['usuario']}'.")


# ==========================================================================
# ALTA Y EDICIÓN
# ==========================================================================
@router.post(
    "",
    response_model=Respuesta[UsuarioSalida],
    status_code=status.HTTP_201_CREATED,
    summary="Crear un usuario",
    description=(
        "Da de alta una cuenta con su rol y su contraseña inicial. El "
        "identificador de acceso se normaliza a minúsculas y debe ser único."
    ),
    responses={
        409: {"description": "Ya existe una cuenta con ese identificador."},
        422: {"description": "Datos inválidos (usuario, rol o contraseña)."},
    },
)
def crear(bd: BaseDatos, datos: UsuarioCrear) -> dict[str, Any]:
    cuenta = servicio.crear(bd, datos.model_dump())
    return respuestas.exito(
        datos=cuenta,
        mensaje=f"Usuario '{cuenta['usuario']}' creado con rol {cuenta['rol']}.",
    )


@router.put(
    "/{identificador}",
    response_model=Respuesta[UsuarioSalida],
    summary="Editar los datos de un usuario",
    description=(
        "Actualiza nombre y correo. **No** cambia el rol ni la contraseña: "
        "cada uno tiene su propio endpoint, con su regla de negocio. El "
        "identificador de acceso no se puede cambiar (RN-U4)."
    ),
    responses={404: {"description": "No existe la cuenta."},
               409: {"description": "Se intentó cambiar el identificador (RN-U4)."}},
)
def actualizar(bd: BaseDatos, datos: UsuarioActualizar,
               identificador: str = Path(...)) -> dict[str, Any]:
    cuenta = servicio.actualizar(bd, identificador, datos.cambios())
    return respuestas.exito(datos=cuenta,
                            mensaje=f"Usuario '{cuenta['usuario']}' actualizado.")


@router.patch(
    "/{identificador}/rol",
    response_model=Respuesta[UsuarioSalida],
    summary="Cambiar el rol de un usuario",
    description=(
        "Reglas que aplica:\n\n"
        "- **RN-U2**: nadie puede cambiar su propio rol.\n"
        "- **RN-U3**: no se puede degradar al último administrador activo."
    ),
    responses={404: {"description": "No existe la cuenta."},
               409: {"description": "La operación viola RN-U2 o RN-U3."}},
)
def cambiar_rol(bd: BaseDatos, datos: CambioRol,
                solicitante: dict = Depends(requiere_rol(settings.ROL_ADMINISTRADOR)),
                identificador: str = Path(...)) -> dict[str, Any]:
    cuenta = servicio.cambiar_rol(bd, identificador, datos.rol, solicitante)
    return respuestas.exito(
        datos=cuenta,
        mensaje=f"Usuario '{cuenta['usuario']}' ahora tiene el rol {cuenta['rol']}.",
    )


@router.patch(
    "/{identificador}/contrasena",
    response_model=Respuesta[UsuarioSalida],
    summary="Restablecer la contraseña de un usuario",
    description=(
        "Asigna una contraseña nueva sin pedir la anterior; es la operación "
        "de recuperación cuando el titular la olvidó. Para cambiar la "
        "contraseña propia usa `/auth/cambiar-contrasena`, que sí exige la "
        "actual."
    ),
    responses={404: {"description": "No existe la cuenta."}},
)
def restablecer_contrasena(bd: BaseDatos, datos: RestablecerContrasena,
                           identificador: str = Path(...)) -> dict[str, Any]:
    cuenta = servicio.restablecer_contrasena(bd, identificador,
                                             datos.contrasena_nueva)
    return respuestas.exito(
        datos=cuenta,
        mensaje=(f"Contraseña de '{cuenta['usuario']}' restablecida. "
                 "Debe cambiarla en su próximo acceso."),
    )


# ==========================================================================
# BAJA Y REACTIVACIÓN
# ==========================================================================
@router.delete(
    "/{identificador}",
    response_model=Respuesta[UsuarioSalida],
    summary="Dar de baja un usuario",
    description=(
        "Baja **lógica**: la cuenta se marca inactiva y deja de poder "
        "entrar, pero el documento se conserva para no perder la "
        "trazabilidad de lo que registró.\n\n"
        "- **RN-U1**: nadie puede desactivar su propia cuenta.\n"
        "- **RN-U3**: no se puede desactivar al último administrador activo."
    ),
    responses={404: {"description": "No existe la cuenta."},
               409: {"description": "La operación viola RN-U1 o RN-U3."}},
)
def desactivar(bd: BaseDatos,
               solicitante: dict = Depends(requiere_rol(settings.ROL_ADMINISTRADOR)),
               identificador: str = Path(...)) -> dict[str, Any]:
    cuenta = servicio.desactivar(bd, identificador, solicitante)
    return respuestas.exito(
        datos=cuenta,
        mensaje=f"Usuario '{cuenta['usuario']}' dado de baja.",
    )


@router.patch(
    "/{identificador}/reactivar",
    response_model=Respuesta[UsuarioSalida],
    summary="Reactivar un usuario dado de baja",
    responses={404: {"description": "No existe la cuenta."},
               409: {"description": "La cuenta ya estaba activa."}},
)
def reactivar(bd: BaseDatos, identificador: str = Path(...)) -> dict[str, Any]:
    cuenta = servicio.reactivar(bd, identificador)
    return respuestas.exito(
        datos=cuenta,
        mensaje=f"Usuario '{cuenta['usuario']}' reactivado.",
    )
