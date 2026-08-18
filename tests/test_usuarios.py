"""
SIG-LOG — Sistema Integral de Gestión Logística
tests/test_usuarios.py

PRUEBAS DE GESTIÓN DE USUARIOS Y ROLES

Lo importante de este módulo no es que el CRUD funcione —eso se comprueba
en unas pocas líneas—, sino que las reglas de negocio IMPIDAN dejar el
sistema sin administración:

    RN-U1  nadie desactiva su propia cuenta
    RN-U2  nadie cambia su propio rol
    RN-U3  no se puede quedar el sistema sin administradores activos
    RN-U4  el identificador de acceso no se puede cambiar
    RN-U5  el hash de la contraseña nunca sale en una respuesta

Las cuentas que crean estas pruebas se limpian al terminar, para que la
base quede como estaba.

Ejecución:
    pytest tests/test_usuarios.py -v
    python tests/test_usuarios.py
"""

from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from fastapi.testclient import TestClient

from backend.main import app
from config import settings
from config.mongo_conexion import obtener_bd

API = settings.API_PREFIJO

# Prefijo de las cuentas de prueba, para poder limpiarlas sin tocar otras.
PREFIJO = "zz-prueba-"


def crear_cliente() -> TestClient:
    return TestClient(app)


def token_de(cliente: TestClient, usuario: str, contrasena: str) -> str:
    respuesta = cliente.post(f"{API}/auth/login",
                             data={"username": usuario, "password": contrasena})
    assert respuesta.status_code == 200, respuesta.text
    return respuesta.json()["datos"]["access_token"]


def cabecera_admin(cliente: TestClient) -> dict[str, str]:
    return {"Authorization": f"Bearer {token_de(cliente, 'admin', 'siglog2026')}"}


def limpiar_cuentas_de_prueba() -> int:
    """Borra las cuentas creadas por estas pruebas."""
    return obtener_bd()["usuarios"].delete_many(
        {"usuario": {"$regex": f"^{PREFIJO}"}}).deleted_count


try:                                   # el módulo también corre sin pytest
    import pytest

    @pytest.fixture(scope="module", autouse=True)
    def _limpiar_al_terminar():
        """
        Borra las cuentas de prueba al acabar el módulo, también bajo
        pytest. Sin esto la limpieza solo ocurría en el modo manual y las
        corridas de pytest iban dejando cuentas `zz-prueba-*` en la base.
        """
        yield
        limpiar_cuentas_de_prueba()
except ImportError:                    # pragma: no cover
    pass


def crear_cuenta(cliente, cabecera, sufijo: str, rol: str = "DESPACHADOR") -> dict:
    respuesta = cliente.post(
        f"{API}/usuarios", headers=cabecera,
        json={"usuario": f"{PREFIJO}{sufijo}",
              "contrasena": "contrasena-prueba",
              "nombre_completo": f"Cuenta De Prueba {sufijo}",
              "rol": rol})
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()["datos"]


# ==========================================================================
# CONTROL DE ACCESO AL MÓDULO
# ==========================================================================
def test_sin_sesion_no_se_accede():
    with crear_cliente() as cliente:
        assert cliente.get(f"{API}/usuarios").status_code == 401


def test_rol_insuficiente_recibe_403():
    """
    Un DESPACHADOR autenticado NO puede gestionar usuarios.

    Es la prueba que de verdad importa del control de acceso: 401 se
    obtiene sin credenciales, pero 403 exige que la autorización por rol
    funcione de verdad.
    """
    with crear_cliente() as cliente:
        for usuario in ("despachador", "analista"):
            token = token_de(cliente, usuario, "siglog2026")
            respuesta = cliente.get(f"{API}/usuarios",
                                    headers={"Authorization": f"Bearer {token}"})
            assert respuesta.status_code == 403, f"{usuario}: {respuesta.status_code}"
            cuerpo = respuesta.json()
            assert cuerpo["codigo_error"] == "PERMISO_DENEGADO"
            assert cuerpo["detalles"][0]["rol_actual"] == usuario.upper()


def test_administrador_accede():
    with crear_cliente() as cliente:
        respuesta = cliente.get(f"{API}/usuarios", headers=cabecera_admin(cliente))
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["total"] >= 3


# ==========================================================================
# CONSULTA
# ==========================================================================
def test_listado_no_expone_el_hash():
    """RN-U5: ninguna respuesta puede llevar el hash de la contraseña."""
    with crear_cliente() as cliente:
        cuerpo = cliente.get(f"{API}/usuarios",
                             headers=cabecera_admin(cliente)).json()
    assert cuerpo["datos"], "el listado no debería venir vacío"
    for cuenta in cuerpo["datos"]:
        assert "hash_contrasena" not in cuenta
        assert "contrasena" not in cuenta
    assert "hash_contrasena" not in str(cuerpo)


def test_listado_pagina():
    with crear_cliente() as cliente:
        cabecera = cabecera_admin(cliente)
        cuerpo = cliente.get(f"{API}/usuarios?pagina=1&tamano=2",
                             headers=cabecera).json()
    assert len(cuerpo["datos"]) <= 2
    assert cuerpo["total"] >= len(cuerpo["datos"])


def test_listado_filtra_por_rol():
    with crear_cliente() as cliente:
        cuerpo = cliente.get(f"{API}/usuarios?rol=ADMINISTRADOR",
                             headers=cabecera_admin(cliente)).json()
    assert cuerpo["datos"]
    assert all(c["rol"] == "ADMINISTRADOR" for c in cuerpo["datos"])


def test_catalogo_de_roles():
    with crear_cliente() as cliente:
        cuerpo = cliente.get(f"{API}/usuarios/roles",
                             headers=cabecera_admin(cliente)).json()
    roles = {r["rol"] for r in cuerpo["datos"]}
    assert roles == set(settings.CATALOGO_ROLES)
    assert all(r["descripcion"] and r["actor"] for r in cuerpo["datos"])


def test_resumen_cuenta_administradores():
    with crear_cliente() as cliente:
        datos = cliente.get(f"{API}/usuarios/resumen",
                            headers=cabecera_admin(cliente)).json()["datos"]
    assert datos["administradores_activos"] >= 1
    assert datos["total"] == datos["activos"] + datos["inactivos"]


def test_rutas_fijas_no_se_confunden_con_un_id():
    """
    `/usuarios/roles` no debe interpretarse como `/usuarios/{id}`.

    Si el orden de declaración fuera el inverso, esta ruta respondería 400
    o 404 al tratar "roles" como identificador.
    """
    with crear_cliente() as cliente:
        cabecera = cabecera_admin(cliente)
        assert cliente.get(f"{API}/usuarios/roles", headers=cabecera).status_code == 200
        assert cliente.get(f"{API}/usuarios/resumen", headers=cabecera).status_code == 200


# ==========================================================================
# ALTA
# ==========================================================================
def test_crear_usuario():
    with crear_cliente() as cliente:
        cabecera = cabecera_admin(cliente)
        cuenta = crear_cuenta(cliente, cabecera, "alta")
    assert cuenta["usuario"] == f"{PREFIJO}alta"
    assert cuenta["rol"] == "DESPACHADOR"
    assert cuenta["activo"] is True
    assert "hash_contrasena" not in cuenta


def test_la_cuenta_creada_puede_entrar():
    """El alta deja la cuenta realmente utilizable."""
    with crear_cliente() as cliente:
        crear_cuenta(cliente, cabecera_admin(cliente), "entra")
        respuesta = cliente.post(
            f"{API}/auth/login",
            data={"username": f"{PREFIJO}entra", "password": "contrasena-prueba"})
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["datos"]["rol"] == "DESPACHADOR"


def test_usuario_duplicado_da_409():
    with crear_cliente() as cliente:
        cabecera = cabecera_admin(cliente)
        crear_cuenta(cliente, cabecera, "dup")
        respuesta = cliente.post(
            f"{API}/usuarios", headers=cabecera,
            json={"usuario": f"{PREFIJO}dup", "contrasena": "contrasena-prueba",
                  "nombre_completo": "Otra Cuenta Distinta", "rol": "ANALISTA"})
    assert respuesta.status_code == 409, respuesta.text
    assert respuesta.json()["codigo_error"] == "RECURSO_DUPLICADO"


def test_rol_invalido_se_rechaza():
    with crear_cliente() as cliente:
        respuesta = cliente.post(
            f"{API}/usuarios", headers=cabecera_admin(cliente),
            json={"usuario": f"{PREFIJO}rolmalo", "contrasena": "contrasena-prueba",
                  "nombre_completo": "Cuenta Rol Invalido", "rol": "SUPERUSUARIO"})
    assert respuesta.status_code == 422
    assert respuesta.json()["codigo_error"] == "ESQUEMA_INVALIDO"


def test_contrasena_corta_se_rechaza():
    with crear_cliente() as cliente:
        respuesta = cliente.post(
            f"{API}/usuarios", headers=cabecera_admin(cliente),
            json={"usuario": f"{PREFIJO}corta", "contrasena": "123",
                  "nombre_completo": "Cuenta Clave Corta", "rol": "ANALISTA"})
    assert respuesta.status_code == 422


def test_usuario_se_normaliza_a_minusculas():
    """'Admin' y 'admin' deben ser la misma cuenta, no dos distintas."""
    with crear_cliente() as cliente:
        respuesta = cliente.post(
            f"{API}/usuarios", headers=cabecera_admin(cliente),
            json={"usuario": f"{PREFIJO}MAYUSCULAS",
                  "contrasena": "contrasena-prueba",
                  "nombre_completo": "Cuenta En Mayusculas", "rol": "ANALISTA"})
    assert respuesta.status_code == 201, respuesta.text
    assert respuesta.json()["datos"]["usuario"] == f"{PREFIJO}mayusculas"


# ==========================================================================
# EDICIÓN
# ==========================================================================
def test_actualizar_datos():
    with crear_cliente() as cliente:
        cabecera = cabecera_admin(cliente)
        cuenta = crear_cuenta(cliente, cabecera, "editar")
        respuesta = cliente.put(f"{API}/usuarios/{cuenta['id']}", headers=cabecera,
                                json={"nombre_completo": "Nombre Ya Corregido"})
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["datos"]["nombre_completo"] == "Nombre Ya Corregido"


def test_no_se_puede_cambiar_el_identificador():
    """RN-U4: el identificador de acceso es inmutable."""
    with crear_cliente() as cliente:
        cabecera = cabecera_admin(cliente)
        cuenta = crear_cuenta(cliente, cabecera, "inmutable")
        respuesta = cliente.put(f"{API}/usuarios/{cuenta['id']}", headers=cabecera,
                                json={"usuario": "otro-nombre",
                                      "nombre_completo": "Sigue Siendo La Misma"})
        # El esquema ignora `usuario`; se comprueba que no cambió.
        assert respuesta.status_code == 200, respuesta.text
        actual = cliente.get(f"{API}/usuarios/{cuenta['id']}",
                             headers=cabecera).json()["datos"]
    assert actual["usuario"] == f"{PREFIJO}inmutable"


def test_restablecer_contrasena():
    """Tras el restablecimiento, la contraseña nueva sirve y la vieja no."""
    with crear_cliente() as cliente:
        cabecera = cabecera_admin(cliente)
        cuenta = crear_cuenta(cliente, cabecera, "reset")

        respuesta = cliente.patch(
            f"{API}/usuarios/{cuenta['id']}/contrasena", headers=cabecera,
            json={"contrasena_nueva": "contrasena-nueva-9"})
        assert respuesta.status_code == 200, respuesta.text

        nueva = cliente.post(f"{API}/auth/login",
                             data={"username": cuenta["usuario"],
                                   "password": "contrasena-nueva-9"})
        vieja = cliente.post(f"{API}/auth/login",
                             data={"username": cuenta["usuario"],
                                   "password": "contrasena-prueba"})
    assert nueva.status_code == 200, "la contraseña nueva debe funcionar"
    assert vieja.status_code == 401, "la contraseña anterior debe dejar de servir"


# ==========================================================================
# REGLAS DE NEGOCIO — lo que debe IMPEDIRSE
# ==========================================================================
def test_no_puedo_desactivarme_a_mi_mismo():
    """RN-U1."""
    with crear_cliente() as cliente:
        cabecera = cabecera_admin(cliente)
        yo = cliente.get(f"{API}/auth/yo", headers=cabecera).json()["datos"]
        respuesta = cliente.delete(f"{API}/usuarios/{yo['id']}", headers=cabecera)
    assert respuesta.status_code == 409, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["codigo_error"] == "REGLA_U1"
    assert "propia cuenta" in cuerpo["mensaje"]


def test_no_puedo_cambiar_mi_propio_rol():
    """RN-U2."""
    with crear_cliente() as cliente:
        cabecera = cabecera_admin(cliente)
        yo = cliente.get(f"{API}/auth/yo", headers=cabecera).json()["datos"]
        respuesta = cliente.patch(f"{API}/usuarios/{yo['id']}/rol",
                                  headers=cabecera, json={"rol": "ANALISTA"})
    assert respuesta.status_code == 409, respuesta.text
    assert respuesta.json()["codigo_error"] == "REGLA_U2"


def test_rn_u3_protege_al_ultimo_administrador():
    """
    RN-U3: no se puede desactivar ni degradar al último administrador
    activo, porque el sistema quedaría sin nadie que pueda gestionarlo
    desde la aplicación.

    Se prueba en la CAPA DE SERVICIO y no por la API, y la razón es
    interesante: por la API la regla es inalcanzable. Solo un
    ADMINISTRADOR puede llamar al endpoint, y si el objetivo es el último
    administrador, el solicitante tiene que ser él mismo — con lo que
    RN-U1 salta antes. RN-U3 es defensa en profundidad: cubre al servicio
    cuando se le llama desde otro sitio (un script de línea de comandos,
    una operación masiva futura) o si algún día RN-U1 cambiara.
    """
    from backend.services import usuarios as servicio
    from backend.utils.errores import ReglaDeNegocio

    bd = obtener_bd()
    admins = list(bd["usuarios"].find({"rol": settings.ROL_ADMINISTRADOR,
                                       "activo": {"$ne": False}}))
    assert len(admins) == 1, (
        f"la prueba asume un único administrador activo, hay {len(admins)}")

    unico = admins[0]
    # Solicitante distinto del objetivo, para que RN-U1 no intercepte.
    otro = bd["usuarios"].find_one({"_id": {"$ne": unico["_id"]}})
    assert otro is not None, "hace falta otra cuenta cualquiera"

    for operacion, llamada in (
        ("desactivar", lambda: servicio.desactivar(bd, str(unico["_id"]), otro)),
        ("degradar", lambda: servicio.cambiar_rol(
            bd, str(unico["_id"]), settings.ROL_ANALISTA, otro)),
    ):
        try:
            llamada()
            raise AssertionError(
                f"RN-U3 debió impedir {operacion} al último administrador")
        except ReglaDeNegocio as exc:
            assert exc.codigo_error == "REGLA_U3", (
                f"{operacion}: se esperaba REGLA_U3 y llegó {exc.codigo_error}")

    # La cuenta debe haber quedado intacta
    despues = bd["usuarios"].find_one({"_id": unico["_id"]})
    assert despues["rol"] == settings.ROL_ADMINISTRADOR
    assert despues.get("activo", True) is True


def test_rn_u1_intercepta_antes_que_rn_u3_en_la_api():
    """
    Documenta el orden de las reglas: por la API, el último administrador
    que intenta desactivarse recibe RN-U1, no RN-U3. Ambas lo protegen; la
    primera llega antes y con un mensaje más útil ("pídeselo a otro
    administrador").
    """
    with crear_cliente() as cliente:
        cabecera = cabecera_admin(cliente)
        yo = cliente.get(f"{API}/auth/yo", headers=cabecera).json()["datos"]
        respuesta = cliente.delete(f"{API}/usuarios/{yo['id']}", headers=cabecera)
    assert respuesta.status_code == 409
    assert respuesta.json()["codigo_error"] == "REGLA_U1"


def test_se_puede_desactivar_un_administrador_si_queda_otro():
    """
    La regla impide lo peligroso, no lo legítimo: con dos administradores,
    dar de baja a uno debe funcionar.

    Todo el cambio de estado va en un `try/finally`: si una aserción
    fallara, la restauración se ejecuta igual. (La versión anterior de esta
    prueba no lo hacía y dejó la cuenta `admin` desactivada al fallar.)
    """
    bd = obtener_bd()
    with crear_cliente() as cliente:
        cabecera = cabecera_admin(cliente)
        segundo = crear_cuenta(cliente, cabecera, "admin2",
                               rol=settings.ROL_ADMINISTRADOR)
        yo = cliente.get(f"{API}/auth/yo", headers=cabecera).json()["datos"]
        try:
            # El segundo administrador da de baja al primero: permitido,
            # porque él mismo queda como administrador activo.
            cabecera2 = {"Authorization": "Bearer " + token_de(
                cliente, segundo["usuario"], "contrasena-prueba")}
            respuesta = cliente.delete(f"{API}/usuarios/{yo['id']}",
                                       headers=cabecera2)
            assert respuesta.status_code == 200, respuesta.text
            assert respuesta.json()["datos"]["activo"] is False
        finally:
            # Se restaura SIEMPRE, falle o no la aserción anterior.
            from bson import ObjectId

            bd["usuarios"].update_one(
                {"_id": ObjectId(yo["id"])},
                {"$set": {"activo": True, "intentos_fallidos": 0}})

    # Se vuelve a pedir la base: al cerrarse el TestClient se cierra el
    # MongoClient compartido, y el handle capturado antes ya no sirve.
    assert obtener_bd()["usuarios"].find_one({"usuario": "admin"})["activo"] is True


def test_baja_logica_no_borra_el_documento():
    """
    El DELETE del §12.3 es baja lógica: la cuenta deja de entrar pero el
    documento se conserva, para no perder la trazabilidad de lo que
    registró.
    """
    bd = obtener_bd()
    with crear_cliente() as cliente:
        cabecera = cabecera_admin(cliente)
        cuenta = crear_cuenta(cliente, cabecera, "baja")

        assert cliente.delete(f"{API}/usuarios/{cuenta['id']}",
                              headers=cabecera).status_code == 200

        # El documento sigue existiendo
        assert bd["usuarios"].find_one({"usuario": cuenta["usuario"]}) is not None
        # Pero ya no puede iniciar sesión
        respuesta = cliente.post(f"{API}/auth/login",
                                 data={"username": cuenta["usuario"],
                                       "password": "contrasena-prueba"})
    assert respuesta.status_code == 401, "una cuenta dada de baja no debe entrar"


def test_reactivar_devuelve_el_acceso():
    with crear_cliente() as cliente:
        cabecera = cabecera_admin(cliente)
        cuenta = crear_cuenta(cliente, cabecera, "reactiva")
        cliente.delete(f"{API}/usuarios/{cuenta['id']}", headers=cabecera)

        respuesta = cliente.patch(f"{API}/usuarios/{cuenta['id']}/reactivar",
                                  headers=cabecera)
        assert respuesta.status_code == 200, respuesta.text

        acceso = cliente.post(f"{API}/auth/login",
                              data={"username": cuenta["usuario"],
                                    "password": "contrasena-prueba"})
    assert acceso.status_code == 200, "tras reactivar debe poder entrar"


def test_cambiar_rol_de_otro_si_funciona():
    """La regla impide lo peligroso, no lo legítimo."""
    with crear_cliente() as cliente:
        cabecera = cabecera_admin(cliente)
        cuenta = crear_cuenta(cliente, cabecera, "promocion", rol="ANALISTA")
        respuesta = cliente.patch(f"{API}/usuarios/{cuenta['id']}/rol",
                                  headers=cabecera, json={"rol": "DESPACHADOR"})
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["datos"]["rol"] == "DESPACHADOR"


def test_usuario_inexistente_da_404():
    with crear_cliente() as cliente:
        respuesta = cliente.get(f"{API}/usuarios/6a83893489a0d3691e05ffff",
                                headers=cabecera_admin(cliente))
    assert respuesta.status_code == 404
    assert respuesta.json()["codigo_error"] == "NO_ENCONTRADO"


def test_identificador_con_formato_invalido_da_400():
    with crear_cliente() as cliente:
        respuesta = cliente.get(f"{API}/usuarios/no-es-un-objectid",
                                headers=cabecera_admin(cliente))
    assert respuesta.status_code == 400
    assert respuesta.json()["codigo_error"] == "VALIDACION_FALLIDA"


# ==========================================================================
# Modo manual (sin pytest)
# ==========================================================================
if __name__ == "__main__":
    pruebas = [
        ("Sin sesión no se accede", test_sin_sesion_no_se_accede),
        ("Rol insuficiente recibe 403", test_rol_insuficiente_recibe_403),
        ("El administrador accede", test_administrador_accede),
        ("El listado no expone el hash (RN-U5)", test_listado_no_expone_el_hash),
        ("El listado pagina", test_listado_pagina),
        ("El listado filtra por rol", test_listado_filtra_por_rol),
        ("Catálogo de roles", test_catalogo_de_roles),
        ("Resumen cuenta administradores", test_resumen_cuenta_administradores),
        ("Las rutas fijas no se confunden con un id",
         test_rutas_fijas_no_se_confunden_con_un_id),
        ("Crear usuario", test_crear_usuario),
        ("La cuenta creada puede entrar", test_la_cuenta_creada_puede_entrar),
        ("Usuario duplicado da 409", test_usuario_duplicado_da_409),
        ("Rol inválido se rechaza", test_rol_invalido_se_rechaza),
        ("Contraseña corta se rechaza", test_contrasena_corta_se_rechaza),
        ("El usuario se normaliza a minúsculas",
         test_usuario_se_normaliza_a_minusculas),
        ("Actualizar datos", test_actualizar_datos),
        ("No se puede cambiar el identificador (RN-U4)",
         test_no_se_puede_cambiar_el_identificador),
        ("Restablecer contraseña", test_restablecer_contrasena),
        ("No puedo desactivarme a mí mismo (RN-U1)",
         test_no_puedo_desactivarme_a_mi_mismo),
        ("No puedo cambiar mi propio rol (RN-U2)",
         test_no_puedo_cambiar_mi_propio_rol),
        ("RN-U3 protege al último administrador",
         test_rn_u3_protege_al_ultimo_administrador),
        ("RN-U1 intercepta antes que RN-U3 en la API",
         test_rn_u1_intercepta_antes_que_rn_u3_en_la_api),
        ("Se puede dar de baja un administrador si queda otro",
         test_se_puede_desactivar_un_administrador_si_queda_otro),
        ("La baja lógica no borra el documento",
         test_baja_logica_no_borra_el_documento),
        ("Reactivar devuelve el acceso", test_reactivar_devuelve_el_acceso),
        ("Cambiar el rol de otro sí funciona", test_cambiar_rol_de_otro_si_funciona),
        ("Usuario inexistente da 404", test_usuario_inexistente_da_404),
        ("Identificador inválido da 400",
         test_identificador_con_formato_invalido_da_400),
    ]

    print("=" * 70)
    print("  SIG-LOG — Pruebas de gestión de usuarios y roles")
    print("=" * 70)

    fallos = 0
    for descripcion, prueba in pruebas:
        try:
            prueba()
            print(f"  [OK]    {descripcion}")
        except AssertionError as exc:
            fallos += 1
            print(f"  [FALLA] {descripcion}\n          {exc}")
        except Exception as exc:                    # noqa: BLE001
            fallos += 1
            print(f"  [ERROR] {descripcion}\n          {type(exc).__name__}: {exc}")

    borradas = limpiar_cuentas_de_prueba()
    print("-" * 70)
    print(f"  Cuentas de prueba eliminadas: {borradas}")
    print("=" * 70)
    print(f"  Resultado: {len(pruebas) - fallos}/{len(pruebas)} pruebas correctas")
    print("=" * 70)
    sys.exit(1 if fallos else 0)
