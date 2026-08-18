"""
SIG-LOG — Sistema Integral de Gestión Logística
config/mongo_conexion.py

Propósito
---------
Única puerta de acceso al cliente de MongoDB Atlas. El API, el ETL, el
generador de datos simulados y los scripts de análisis deben obtener la base
de datos desde aquí, nunca creando su propio MongoClient.

Se mantiene un cliente único (patrón singleton) porque MongoClient ya
administra internamente un pool de conexiones: crear uno por script
desperdicia conexiones del cluster (relevante en el tier gratuito de Atlas).
"""

from __future__ import annotations

from typing import Any

from pymongo import MongoClient
from pymongo.database import Database
from pymongo.errors import (
    ConfigurationError,
    OperationFailure,
    ServerSelectionTimeoutError,
)

from config import settings

_cliente: MongoClient | None = None


def obtener_cliente() -> MongoClient:
    """Devuelve el MongoClient compartido, creándolo la primera vez."""
    global _cliente
    if _cliente is None:
        _cliente = MongoClient(
            settings.construir_uri(),
            serverSelectionTimeoutMS=settings.MONGO_TIMEOUT_MS,
            appname=settings.APP_NOMBRE,
            tz_aware=True,
        )
    return _cliente


def obtener_bd(nombre: str | None = None) -> Database:
    """
    Devuelve la base de datos de trabajo (por defecto `siglog`).

    No realiza ninguna operación de red: MongoDB resuelve la conexión de
    forma perezosa en la primera consulta.
    """
    return obtener_cliente()[nombre or settings.MONGO_DB]


def cerrar_cliente() -> None:
    """Cierra el cliente compartido. Útil al final de scripts por lotes."""
    global _cliente
    if _cliente is not None:
        _cliente.close()
        _cliente = None


def verificar_conexion(verbose: bool = False) -> dict[str, Any]:
    """
    Comprueba que la conexión con MongoDB Atlas funciona.

    Ejecuta `ping` contra la base admin (mismo mecanismo de verificación
    utilizado en los ejercicios de clase) y recupera metadatos del servidor.

    Devuelve un diccionario con el formato de respuesta uniforme del
    proyecto (§12.2): exito / mensaje / datos.
    """
    try:
        cliente = obtener_cliente()
        cliente.admin.command("ping")
        info = cliente.server_info()
        bd = obtener_bd()
        colecciones = sorted(bd.list_collection_names())

        datos: dict[str, Any] = {
            "base_datos": bd.name,
            "version_servidor": info.get("version", "desconocida"),
            "uri": settings.uri_enmascarada(),
            "colecciones": colecciones,
            "total_colecciones": len(colecciones),
        }
        resultado = {
            "exito": True,
            "mensaje": f"Conexión establecida con la base de datos '{bd.name}'.",
            "datos": datos,
        }

    except ValueError as exc:  # configuración incompleta (.env)
        resultado = {
            "exito": False,
            "mensaje": str(exc),
            "codigo_error": "CONFIGURACION_INCOMPLETA",
            "datos": {},
        }
    except ConfigurationError as exc:
        resultado = {
            "exito": False,
            "mensaje": (
                f"Cadena de conexión inválida o DNS no resuelto: {exc}. "
                "Revisa MONGO_CLUSTER y que esté instalado 'dnspython'."
            ),
            "codigo_error": "CONFIGURACION_INVALIDA",
            "datos": {},
        }
    except ServerSelectionTimeoutError as exc:
        resultado = {
            "exito": False,
            "mensaje": (
                f"No se pudo contactar al cluster: {exc}. "
                "Causas frecuentes: tu IP no está en la Network Access List "
                "de Atlas, o no hay salida a internet."
            ),
            "codigo_error": "SERVIDOR_INALCANZABLE",
            "datos": {},
        }
    except OperationFailure as exc:
        resultado = {
            "exito": False,
            "mensaje": (
                f"Autenticación o permisos rechazados: {exc}. "
                "Revisa usuario, contraseña y los roles del usuario en Atlas."
            ),
            "codigo_error": "AUTENTICACION_FALLIDA",
            "datos": {},
        }

    if verbose:
        _imprimir_verificacion(resultado)
    return resultado


def _imprimir_verificacion(resultado: dict[str, Any]) -> None:
    """Salida legible en consola para usar como evidencia de la prueba."""
    print("=" * 66)
    print(f"  {settings.APP_NOMBRE} — Verificación de conexión con MongoDB Atlas")
    print("=" * 66)

    for clave, valor in settings.resumen_configuracion().items():
        print(f"  {clave:.<26} {valor}")
    print("-" * 66)

    if resultado["exito"]:
        datos = resultado["datos"]
        print("  ESTADO ....................... CONEXIÓN EXITOSA")
        print(f"  Versión del servidor ......... {datos['version_servidor']}")
        print(f"  Base de datos ................ {datos['base_datos']}")
        print(f"  Colecciones existentes ....... {datos['total_colecciones']}")
        for nombre in datos["colecciones"]:
            print(f"      - {nombre}")
    else:
        print("  ESTADO ....................... ERROR DE CONEXIÓN")
        print(f"  Código ....................... {resultado.get('codigo_error')}")
        print(f"  Detalle ...................... {resultado['mensaje']}")
    print("=" * 66)


if __name__ == "__main__":
    import sys

    respuesta = verificar_conexion(verbose=True)
    sys.exit(0 if respuesta["exito"] else 1)
