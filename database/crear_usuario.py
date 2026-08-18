"""
SIG-LOG — Sistema Integral de Gestión Logística
database/crear_usuario.py

ALTA DE USUARIOS DESDE LA LÍNEA DE COMANDOS  (RNP-11)

Resuelve el problema del primer arranque: la API exige sesión para las
operaciones protegidas, pero la gestión de usuarios se hará *desde* la
API. Sin una vía externa, un sistema recién instalado no tendría forma de
crear la primera cuenta.

Este script es esa vía. No sustituye a la administración de usuarios de la
actividad siguiente: sirve para arrancar, y para recuperar el acceso si se
pierde la contraseña del administrador.

Uso
---
    python -m database.crear_usuario                    # modo interactivo
    python -m database.crear_usuario --usuario admin --rol ADMINISTRADOR
    python -m database.crear_usuario --listar
    python -m database.crear_usuario --usuario admin --restablecer

La contraseña NUNCA se pasa por argumento: quedaría en el historial del
shell y en la lista de procesos. Se pide siempre por consola, oculta.
"""

from __future__ import annotations

import argparse
import getpass
import sys
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from pymongo.errors import DuplicateKeyError

from backend.utils.errores import DatosInvalidos
from backend.utils.seguridad import cifrar_contrasena
from config import settings
from config.mongo_conexion import cerrar_cliente, obtener_bd, verificar_conexion

COLECCION = "usuarios"


# ==========================================================================
# ENTRADA DE DATOS
# ==========================================================================
def pedir_contrasena(confirmar: bool = True) -> str:
    """Pide la contraseña por consola, sin eco, y la confirma."""
    while True:
        contrasena = getpass.getpass("  Contraseña: ")
        try:
            from backend.utils.seguridad import validar_fortaleza

            validar_fortaleza(contrasena)
        except DatosInvalidos as exc:
            print(f"  {exc.mensaje}")
            continue

        if not confirmar:
            return contrasena
        if contrasena == getpass.getpass("  Repite la contraseña: "):
            return contrasena
        print("  Las contraseñas no coinciden. Intenta de nuevo.")


def pedir_rol() -> str:
    """Menú de roles del catálogo (§3 y §12.3)."""
    descripciones = {
        settings.ROL_ADMINISTRADOR: "gestiona catálogos, configuración y usuarios",
        settings.ROL_DESPACHADOR: "registra la operación diaria del día a día",
        settings.ROL_ANALISTA: "consulta dashboard, reportes y resultados de ML",
    }
    print("\n  Roles disponibles:")
    for i, rol in enumerate(settings.CATALOGO_ROLES, start=1):
        print(f"    {i}. {rol:<16}{descripciones[rol]}")

    while True:
        eleccion = input("  Elige el rol [1]: ").strip() or "1"
        if eleccion.isdigit() and 1 <= int(eleccion) <= len(settings.CATALOGO_ROLES):
            return settings.CATALOGO_ROLES[int(eleccion) - 1]
        print("  Opción no válida.")


# ==========================================================================
# OPERACIONES
# ==========================================================================
def crear_usuario(bd, usuario: str, nombre: str, rol: str,
                  contrasena: str, correo: str | None = None) -> None:
    documento = {
        "usuario": usuario,
        "hash_contrasena": cifrar_contrasena(contrasena),
        "nombre_completo": nombre,
        "correo": correo,
        "rol": rol,
        "ultimo_acceso": None,
        "intentos_fallidos": 0,
        # `origen_dato: REAL` distingue estas cuentas de los datos SIMULADOS
        # del seed: un usuario del sistema no es un dato de la simulación.
        "origen_dato": "REAL",
        "activo": True,
        "fecha_creacion": datetime.now(timezone.utc),
        "fecha_modificacion": datetime.now(timezone.utc),
    }
    bd[COLECCION].insert_one(documento)


def restablecer_contrasena(bd, usuario: str, contrasena: str) -> bool:
    resultado = bd[COLECCION].update_one(
        {"usuario": usuario},
        {"$set": {"hash_contrasena": cifrar_contrasena(contrasena),
                  "intentos_fallidos": 0,
                  "fecha_modificacion": datetime.now(timezone.utc)}},
    )
    return resultado.matched_count > 0


def listar_usuarios(bd) -> None:
    """Listado de cuentas. Nunca imprime el hash."""
    cuentas = list(bd[COLECCION].find(
        {}, {"usuario": 1, "nombre_completo": 1, "rol": 1,
             "activo": 1, "ultimo_acceso": 1}).sort("usuario"))

    print("=" * 78)
    print(f"  USUARIOS REGISTRADOS ({len(cuentas)})")
    print("=" * 78)
    if not cuentas:
        print("  No hay ninguna cuenta. Crea la primera con:")
        print("      python -m database.crear_usuario")
        return

    print(f"  {'USUARIO':<18}{'ROL':<16}{'ESTADO':<10}{'ÚLTIMO ACCESO'}")
    print("-" * 78)
    for cuenta in cuentas:
        acceso = cuenta.get("ultimo_acceso")
        print(f"  {cuenta['usuario']:<18}{cuenta['rol']:<16}"
              f"{'activo' if cuenta.get('activo', True) else 'inactivo':<10}"
              f"{acceso.strftime('%Y-%m-%d %H:%M') if acceso else 'nunca'}")
    print("-" * 78)
    print("  El hash de la contraseña no se muestra ni se exporta.")


# ==========================================================================
# PUNTO DE ENTRADA
# ==========================================================================
def main() -> int:
    parser = argparse.ArgumentParser(
        description="Alta y restablecimiento de usuarios de SIG-LOG (RNP-11).")
    parser.add_argument("--usuario", help="Identificador de acceso.")
    parser.add_argument("--nombre", help="Nombre completo de la persona.")
    parser.add_argument("--correo", help="Correo electrónico (opcional).")
    parser.add_argument("--rol", choices=settings.CATALOGO_ROLES,
                        help="Rol de la cuenta.")
    parser.add_argument("--listar", action="store_true",
                        help="Muestra las cuentas existentes y termina.")
    parser.add_argument("--restablecer", action="store_true",
                        help="Cambia la contraseña de una cuenta existente.")
    args = parser.parse_args()

    if not verificar_conexion()["exito"]:
        print("  No hay conexión con MongoDB. Revisa el .env y la red.")
        return 1

    try:
        bd = obtener_bd()

        if args.listar:
            listar_usuarios(bd)
            return 0

        print("=" * 78)
        print("  SIG-LOG — Alta de usuario")
        print("=" * 78)

        usuario = args.usuario or input("  Usuario: ").strip()
        if not usuario:
            print("  El usuario no puede quedar vacío.")
            return 1

        existe = bd[COLECCION].find_one({"usuario": usuario}) is not None

        if args.restablecer:
            if not existe:
                print(f"  No existe la cuenta '{usuario}'.")
                return 1
            print(f"  Restableciendo la contraseña de '{usuario}'.")
            restablecer_contrasena(bd, usuario, pedir_contrasena())
            print(f"\n  Contraseña de '{usuario}' actualizada.")
            return 0

        if existe:
            print(f"  Ya existe la cuenta '{usuario}'. Para cambiar su "
                  "contraseña usa --restablecer.")
            return 1

        nombre = args.nombre or input("  Nombre completo: ").strip() or usuario
        correo = args.correo or (input("  Correo (opcional): ").strip() or None)
        rol = args.rol or pedir_rol()
        print()
        contrasena = pedir_contrasena()

        crear_usuario(bd, usuario, nombre, rol, contrasena, correo)
        print()
        print("=" * 78)
        print(f"  Usuario '{usuario}' creado con rol {rol}.")
        print("  Inicia sesión en: POST /api/v1/auth/login")
        print("  O desde la documentación interactiva: http://127.0.0.1:8000/docs")
        print("=" * 78)
        return 0

    except DuplicateKeyError:
        print(f"  Ya existe una cuenta con ese identificador.")
        return 1
    except DatosInvalidos as exc:
        print(f"  {exc.mensaje}")
        return 1
    except KeyboardInterrupt:
        print("\n  Cancelado.")
        return 1
    finally:
        cerrar_cliente()


if __name__ == "__main__":
    sys.exit(main())
