"""
SIG-LOG — Sistema Integral de Gestión Logística
tests/test_autenticacion.py

PRUEBAS DEL SUBSISTEMA DE AUTENTICACIÓN  (RNP-11, opción b)

Cubren tres cosas distintas, y conviene no confundirlas:

  · que las primitivas de seguridad funcionen (hash y token);
  · que el flujo de acceso funcione (login → token → endpoint protegido);
  · que la seguridad **niegue** lo que debe negar, que es lo que de verdad
    hay que probar. Un sistema que deja entrar a todo el mundo pasa
    cualquier prueba escrita solo sobre el camino feliz.

Requieren las cuentas de prueba. Si no existen, créalas con:
    python -m database.crear_usuario --usuario admin --rol ADMINISTRADOR

Ejecución:
    pytest tests/test_autenticacion.py -v
    python tests/test_autenticacion.py
"""

from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from fastapi.testclient import TestClient

from backend.main import app
from backend.utils.seguridad import (
    cifrar_contrasena,
    crear_token,
    leer_token,
    verificar_contrasena,
)
from config import settings

API = settings.API_PREFIJO

# Cuentas de prueba (creadas con database/crear_usuario.py)
CUENTAS = {
    "ADMINISTRADOR": ("admin", "siglog2026"),
    "DESPACHADOR": ("despachador", "siglog2026"),
    "ANALISTA": ("analista", "siglog2026"),
}


def crear_cliente() -> TestClient:
    return TestClient(app)


def obtener_token(cliente: TestClient, rol: str = "ADMINISTRADOR") -> str:
    usuario, contrasena = CUENTAS[rol]
    respuesta = cliente.post(f"{API}/auth/login",
                             data={"username": usuario, "password": contrasena})
    assert respuesta.status_code == 200, respuesta.text
    return respuesta.json()["datos"]["access_token"]


def cabecera(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ==========================================================================
# PRIMITIVAS DE SEGURIDAD
# ==========================================================================
def test_hash_no_guarda_la_contrasena():
    """El hash no contiene la contraseña y verifica correctamente."""
    hash_generado = cifrar_contrasena("contrasena-de-prueba")
    assert "contrasena-de-prueba" not in hash_generado
    assert hash_generado.startswith("$2b$"), "debe ser un hash bcrypt"
    assert verificar_contrasena("contrasena-de-prueba", hash_generado)
    assert not verificar_contrasena("otra-cosa", hash_generado)


def test_hash_usa_sal_aleatoria():
    """
    La misma contraseña produce hashes distintos.

    Sin sal, dos usuarios con la misma contraseña tendrían el mismo hash y
    una tabla precalculada rompería ambas cuentas de una vez.
    """
    assert cifrar_contrasena("misma-contrasena") != cifrar_contrasena("misma-contrasena")


def test_token_lleva_usuario_y_rol():
    token, expira = crear_token("prueba", "ANALISTA")
    contenido = leer_token(token)
    assert contenido["sub"] == "prueba"
    assert contenido["rol"] == "ANALISTA"
    assert contenido["iss"] == settings.APP_NOMBRE


def test_token_manipulado_se_rechaza():
    """Alterar un carácter del token invalida la firma."""
    from backend.utils.seguridad import CredencialesInvalidas

    token, _ = crear_token("prueba", "ANALISTA")
    manipulado = token[:-4] + ("abcd" if not token.endswith("abcd") else "efgh")
    try:
        leer_token(manipulado)
        raise AssertionError("un token manipulado no debe aceptarse")
    except CredencialesInvalidas:
        pass


def test_token_expirado_se_rechaza():
    from backend.utils.seguridad import CredencialesInvalidas

    token, _ = crear_token("prueba", "ANALISTA", minutos=-1)
    try:
        leer_token(token)
        raise AssertionError("un token expirado no debe aceptarse")
    except CredencialesInvalidas as exc:
        assert "expir" in str(exc).lower()


def test_token_no_lleva_datos_sensibles():
    """El JWT va firmado, no cifrado: nada sensible debe viajar dentro."""
    token, _ = crear_token("prueba", "ANALISTA")
    contenido = leer_token(token)
    for prohibido in ("hash_contrasena", "contrasena", "password"):
        assert prohibido not in contenido


# ==========================================================================
# INICIO DE SESIÓN
# ==========================================================================
def test_login_correcto_devuelve_token():
    with crear_cliente() as cliente:
        respuesta = cliente.post(f"{API}/auth/login",
                                 data={"username": "admin", "password": "siglog2026"})
    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["exito"] is True
    datos = cuerpo["datos"]
    assert datos["token_type"] == "bearer"
    assert datos["rol"] == "ADMINISTRADOR"
    assert datos["access_token"]


def test_login_con_contrasena_incorrecta():
    with crear_cliente() as cliente:
        respuesta = cliente.post(f"{API}/auth/login",
                                 data={"username": "admin", "password": "equivocada"})
    assert respuesta.status_code == 401
    cuerpo = respuesta.json()
    assert cuerpo["exito"] is False
    assert cuerpo["codigo_error"] == "CREDENCIALES_INVALIDAS"


def test_login_no_revela_si_el_usuario_existe():
    """
    Usuario inexistente y contraseña incorrecta responden IGUAL.

    Si difirieran, se podrían enumerar las cuentas válidas probando
    nombres y mirando cuál responde distinto.
    """
    with crear_cliente() as cliente:
        inexistente = cliente.post(
            f"{API}/auth/login",
            data={"username": "no-existe-jamas", "password": "loquesea"})
        incorrecta = cliente.post(
            f"{API}/auth/login",
            data={"username": "admin", "password": "equivocada"})

    assert inexistente.status_code == incorrecta.status_code == 401
    assert inexistente.json()["mensaje"] == incorrecta.json()["mensaje"]


def test_login_registra_el_acceso():
    """Un inicio de sesión correcto sella `ultimo_acceso`."""
    with crear_cliente() as cliente:
        token = obtener_token(cliente, "ANALISTA")
        cuerpo = cliente.get(f"{API}/auth/yo", headers=cabecera(token)).json()
    assert cuerpo["datos"]["ultimo_acceso"] is not None


# ==========================================================================
# IDENTIDAD Y PROTECCIÓN DE ENDPOINTS
# ==========================================================================
def test_yo_devuelve_el_usuario_sin_el_hash():
    with crear_cliente() as cliente:
        token = obtener_token(cliente)
        respuesta = cliente.get(f"{API}/auth/yo", headers=cabecera(token))
    assert respuesta.status_code == 200, respuesta.text
    datos = respuesta.json()["datos"]
    assert datos["usuario"] == "admin"
    assert datos["rol"] == "ADMINISTRADOR"
    assert "hash_contrasena" not in datos, "la respuesta no debe exponer el hash"
    assert "contrasena" not in datos


def test_endpoint_protegido_sin_token():
    """Sin sesión, un endpoint protegido responde 401 con la cabecera estándar."""
    with crear_cliente() as cliente:
        respuesta = cliente.get(f"{API}/diagnostico/colecciones")
    assert respuesta.status_code == 401
    assert respuesta.headers.get("WWW-Authenticate") == "Bearer"
    assert respuesta.json()["codigo_error"] == "CREDENCIALES_INVALIDAS"


def test_endpoint_protegido_con_token():
    with crear_cliente() as cliente:
        token = obtener_token(cliente)
        respuesta = cliente.get(f"{API}/diagnostico/colecciones",
                                headers=cabecera(token))
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["datos"]["total_documentos"] > 0


def test_endpoint_protegido_con_token_falso():
    with crear_cliente() as cliente:
        respuesta = cliente.get(f"{API}/diagnostico/colecciones",
                                headers=cabecera("esto.no.es-un-token"))
    assert respuesta.status_code == 401


def test_endpoints_publicos_siguen_abiertos():
    """
    Salud e información no exigen sesión.

    Un monitor externo debe poder comprobar que el servicio vive sin tener
    credenciales del sistema.
    """
    with crear_cliente() as cliente:
        for ruta in ("/salud", "/salud/mongodb", "/info", "/auth/estado"):
            respuesta = cliente.get(f"{API}{ruta}")
            assert respuesta.status_code == 200, f"{ruta} -> {respuesta.status_code}"


# ==========================================================================
# AUTORIZACIÓN POR ROL
# ==========================================================================
def test_los_tres_roles_pueden_iniciar_sesion():
    with crear_cliente() as cliente:
        for rol, (usuario, contrasena) in CUENTAS.items():
            respuesta = cliente.post(f"{API}/auth/login",
                                     data={"username": usuario, "password": contrasena})
            assert respuesta.status_code == 200, f"{usuario}: {respuesta.text}"
            assert respuesta.json()["datos"]["rol"] == rol


def test_exigir_rol_niega_al_no_autorizado():
    """
    La autorización distingue 401 de 403.

    Se prueba directamente sobre el servicio: los endpoints con restricción
    de rol llegarán con los módulos CRUD, pero el mecanismo debe estar
    verificado antes de que se apoye nada en él.
    """
    from backend.services.autenticacion import exigir_rol
    from backend.utils.seguridad import PermisoDenegado

    analista = {"usuario": "analista", "rol": settings.ROL_ANALISTA}

    exigir_rol(analista, (settings.ROL_ANALISTA,))          # autorizado: no lanza

    try:
        exigir_rol(analista, (settings.ROL_ADMINISTRADOR,))
        raise AssertionError("un ANALISTA no debe pasar un filtro de ADMINISTRADOR")
    except PermisoDenegado as exc:
        assert exc.estado_http == 403
        assert exc.codigo_error == "PERMISO_DENEGADO"


def test_administrador_no_tiene_paso_libre_automatico():
    """
    El ADMINISTRADOR no burla un filtro que no lo incluye.

    Es deliberado: las excepciones implícitas al control de acceso son las
    que después nadie sabe explicar ni auditar.
    """
    from backend.services.autenticacion import exigir_rol
    from backend.utils.seguridad import PermisoDenegado

    admin = {"usuario": "admin", "rol": settings.ROL_ADMINISTRADOR}
    try:
        exigir_rol(admin, (settings.ROL_DESPACHADOR,))
        raise AssertionError("el filtro debe aplicarse también al ADMINISTRADOR")
    except PermisoDenegado:
        pass


# ==========================================================================
# CONFIGURACIÓN Y ESTADO
# ==========================================================================
def test_estado_de_seguridad():
    with crear_cliente() as cliente:
        cuerpo = cliente.get(f"{API}/auth/estado").json()
    datos = cuerpo["datos"]
    assert datos["autenticacion"].startswith("JWT")
    assert set(datos["roles"]) == set(settings.CATALOGO_ROLES)
    assert datos["usuarios_registrados"] is True
    assert datos["clave_segura"] is True, (
        "JWT_CLAVE sigue siendo la de desarrollo; genera una propia en el .env")


def test_usuarios_fuera_del_alcance_del_etl():
    """
    La colección `usuarios` NO está entre las que recorre el ETL.

    Si estuviera, `etl/extraccion.py` volcaría credenciales y hashes a CSV
    en data/raw/. Es la razón de que se declarara en COLECCIONES_SISTEMA.
    """
    assert "usuarios" not in settings.COLECCIONES_OPERATIVAS
    assert "usuarios" not in settings.COLECCIONES_ANALITICAS
    assert "usuarios" in settings.COLECCIONES_SISTEMA
    assert "usuarios" in settings.TODAS_LAS_COLECCIONES


def test_login_documentado_en_openapi():
    with crear_cliente() as cliente:
        rutas = cliente.get("/openapi.json").json()["paths"]
    for endpoint in ("/auth/login", "/auth/yo", "/auth/estado",
                     "/auth/cambiar-contrasena"):
        assert f"{API}{endpoint}" in rutas, f"falta documentar {endpoint}"


# ==========================================================================
# Modo manual (sin pytest)
# ==========================================================================
if __name__ == "__main__":
    pruebas = [
        ("El hash no guarda la contraseña", test_hash_no_guarda_la_contrasena),
        ("El hash usa sal aleatoria", test_hash_usa_sal_aleatoria),
        ("El token lleva usuario y rol", test_token_lleva_usuario_y_rol),
        ("Un token manipulado se rechaza", test_token_manipulado_se_rechaza),
        ("Un token expirado se rechaza", test_token_expirado_se_rechaza),
        ("El token no lleva datos sensibles", test_token_no_lleva_datos_sensibles),
        ("Login correcto devuelve token", test_login_correcto_devuelve_token),
        ("Login con contraseña incorrecta → 401",
         test_login_con_contrasena_incorrecta),
        ("El login no revela si el usuario existe",
         test_login_no_revela_si_el_usuario_existe),
        ("El login registra el acceso", test_login_registra_el_acceso),
        ("GET /auth/yo no expone el hash",
         test_yo_devuelve_el_usuario_sin_el_hash),
        ("Endpoint protegido sin token → 401", test_endpoint_protegido_sin_token),
        ("Endpoint protegido con token → 200", test_endpoint_protegido_con_token),
        ("Endpoint protegido con token falso → 401",
         test_endpoint_protegido_con_token_falso),
        ("Los endpoints públicos siguen abiertos",
         test_endpoints_publicos_siguen_abiertos),
        ("Los tres roles pueden iniciar sesión",
         test_los_tres_roles_pueden_iniciar_sesion),
        ("exigir_rol niega al no autorizado (403)",
         test_exigir_rol_niega_al_no_autorizado),
        ("El ADMINISTRADOR no tiene paso libre",
         test_administrador_no_tiene_paso_libre_automatico),
        ("Estado del subsistema de seguridad", test_estado_de_seguridad),
        ("`usuarios` fuera del alcance del ETL",
         test_usuarios_fuera_del_alcance_del_etl),
        ("Endpoints de auth documentados en OpenAPI",
         test_login_documentado_en_openapi),
    ]

    print("=" * 70)
    print("  SIG-LOG — Pruebas de autenticación (RNP-11)")
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

    print("=" * 70)
    print(f"  Resultado: {len(pruebas) - fallos}/{len(pruebas)} pruebas correctas")
    print("=" * 70)
    sys.exit(1 if fallos else 0)
