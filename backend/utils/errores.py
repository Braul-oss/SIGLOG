"""
SIG-LOG — Sistema Integral de Gestión Logística
backend/utils/errores.py

ERRORES DE DOMINIO Y SU TRADUCCIÓN A HTTP

El §12.2 fija los códigos de estado y el formato del error. Para cumplirlo
sin repetir `try/except` en cada endpoint, la API trabaja con EXCEPCIONES
DE DOMINIO: los servicios lanzan `NoEncontrado` o `ReglaDeNegocio` —que
hablan del problema, no de HTTP— y los manejadores registrados en
`main.py` las convierten en la respuesta correcta.

La ventaja aparece al crecer: cuando un servicio de entregas rechace un
cambio de estatus inválido, lanza `ReglaDeNegocio` y automáticamente
responde 409 con el formato uniforme, sin tocar el router.

Mapa de §12.2:
    400 validación            → DatosInvalidos
    404 no encontrado         → NoEncontrado
    409 conflicto de negocio  → ReglaDeNegocio
    422 esquema inválido      → lo genera Pydantic (se reformatea)
    500 error interno         → cualquier excepción no prevista
    503 dependencia caída     → ServicioNoDisponible (MongoDB inalcanzable)
"""

from __future__ import annotations

from typing import Any


class ErrorSIGLOG(Exception):
    """
    Raíz de los errores propios del sistema.

    Todo error de dominio lleva su código de estado y su `codigo_error`
    estable, para que el frontend pueda reaccionar a un identificador y no
    al texto del mensaje, que puede cambiar.
    """

    estado_http: int = 500
    codigo_error: str = "ERROR_INTERNO"

    def __init__(self, mensaje: str, detalles: list[Any] | None = None) -> None:
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.detalles = detalles or []


class DatosInvalidos(ErrorSIGLOG):
    """400 — la petición es sintácticamente correcta pero pide un imposible."""

    estado_http = 400
    codigo_error = "VALIDACION_FALLIDA"


class NoEncontrado(ErrorSIGLOG):
    """404 — el recurso solicitado no existe."""

    estado_http = 404
    codigo_error = "NO_ENCONTRADO"

    def __init__(self, recurso: str, identificador: Any = None) -> None:
        detalle = f" con identificador '{identificador}'" if identificador else ""
        super().__init__(f"No se encontró {recurso}{detalle}.")


class ReglaDeNegocio(ErrorSIGLOG):
    """
    409 — la operación es válida en forma pero viola una regla del negocio.

    Ejemplos que llegarán con los módulos: asignar un vehículo que ya está
    en otra ruta (RN-04) o cerrar un viaje con odómetro menor al inicial.
    """

    estado_http = 409
    codigo_error = "REGLA_DE_NEGOCIO"

    def __init__(self, mensaje: str, regla: str | None = None,
                 detalles: list[Any] | None = None) -> None:
        super().__init__(mensaje, detalles)
        self.codigo_error = f"REGLA_{regla}" if regla else self.codigo_error


class ServicioNoDisponible(ErrorSIGLOG):
    """503 — una dependencia externa (MongoDB Atlas) no responde."""

    estado_http = 503
    codigo_error = "SERVICIO_NO_DISPONIBLE"


class RecursoDuplicado(ErrorSIGLOG):
    """409 — ya existe un documento con la misma clave única."""

    estado_http = 409
    codigo_error = "RECURSO_DUPLICADO"
