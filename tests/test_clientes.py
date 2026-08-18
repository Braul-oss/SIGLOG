"""
SIG-LOG — Sistema Integral de Gestión Logística
tests/test_clientes.py

PRUEBAS DEL MÓDULO CLIENTES

Además del CRUD, comprueban las reglas que impiden dejar la operación en
un estado imposible:

    RN-C1  el código de cliente lo genera el sistema y es inmutable
    RN-C2  al menos una dirección y exactamente una principal
    RN-C3  no se puede dar de baja un cliente que es parada de una ruta activa
    RN-C4  la baja es lógica: el histórico de entregas se conserva

Y el reparto de permisos, que aquí NO es uniforme: consultar lo puede
hacer cualquier sesión, modificar solo el ADMINISTRADOR.

Los clientes que crean estas pruebas se borran al terminar.

Ejecución:
    pytest tests/test_clientes.py -v
    python tests/test_clientes.py
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
MARCA = "ZZ-PRUEBA"          # va en el nombre, para poder limpiarlos después


def crear_cliente_http() -> TestClient:
    return TestClient(app)


def token_de(cliente: TestClient, usuario: str) -> str:
    respuesta = cliente.post(f"{API}/auth/login",
                             data={"username": usuario, "password": "siglog2026"})
    assert respuesta.status_code == 200, respuesta.text
    return respuesta.json()["datos"]["access_token"]


def cabecera(cliente: TestClient, usuario: str = "admin") -> dict[str, str]:
    return {"Authorization": f"Bearer {token_de(cliente, usuario)}"}


def limpiar() -> int:
    return obtener_bd()["clientes"].delete_many(
        {"nombre": {"$regex": f"^{MARCA}"}}).deleted_count


try:
    import pytest

    @pytest.fixture(scope="module", autouse=True)
    def _limpiar_al_terminar():
        yield
        limpiar()
except ImportError:                    # pragma: no cover
    pass


def direccion(alias: str = "Matriz", principal: bool = True,
              municipio: str = "Toluca") -> dict:
    return {"alias": alias, "calle": "Avenida Siempre Viva", "numero": "742",
            "colonia": "Centro", "municipio": municipio, "estado": "México",
            "cp": "50000", "principal": principal}


def alta(cliente, cab, sufijo: str, **extra) -> dict:
    cuerpo = {"nombre": f"{MARCA} {sufijo}", "tipo_cliente": "MAYORISTA",
              "direcciones": [direccion()], **extra}
    respuesta = cliente.post(f"{API}/clientes", headers=cab, json=cuerpo)
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()["datos"]


# ==========================================================================
# PERMISOS  (no uniformes en el módulo)
# ==========================================================================
def test_sin_sesion_no_se_consulta():
    with crear_cliente_http() as c:
        assert c.get(f"{API}/clientes").status_code == 401


def test_cualquier_sesion_puede_consultar():
    """
    El DESPACHADOR necesita ver clientes para registrar entregas y el
    ANALISTA para leer los reportes. Negárselo obligaría a darles rol de
    administrador, que sería peor.
    """
    with crear_cliente_http() as c:
        for usuario in ("admin", "despachador", "analista"):
            respuesta = c.get(f"{API}/clientes", headers=cabecera(c, usuario))
            assert respuesta.status_code == 200, f"{usuario}: {respuesta.text}"


def test_solo_el_administrador_modifica():
    """Escribir sí está restringido: el §3 lo asigna al Administrador."""
    with crear_cliente_http() as c:
        cuerpo = {"nombre": f"{MARCA} intruso", "tipo_cliente": "MINORISTA",
                  "direcciones": [direccion()]}
        for usuario in ("despachador", "analista"):
            respuesta = c.post(f"{API}/clientes", headers=cabecera(c, usuario),
                               json=cuerpo)
            assert respuesta.status_code == 403, f"{usuario}: {respuesta.status_code}"
            assert respuesta.json()["codigo_error"] == "PERMISO_DENEGADO"


# ==========================================================================
# CONSULTA
# ==========================================================================
def test_listado_pagina_y_ordena():
    with crear_cliente_http() as c:
        cuerpo = c.get(f"{API}/clientes?pagina=1&tamano=5",
                       headers=cabecera(c)).json()
    assert len(cuerpo["datos"]) <= 5
    assert cuerpo["total"] >= 100, "deberían estar los 100 clientes del seed"
    codigos = [x["codigo_cliente"] for x in cuerpo["datos"]]
    assert codigos == sorted(codigos), "el listado debe venir ordenado por código"


def test_busqueda_por_texto():
    """La búsqueda encuentra coincidencias parciales, no solo palabras exactas."""
    with crear_cliente_http() as c:
        cab = cabecera(c)
        primero = c.get(f"{API}/clientes?tamano=1", headers=cab).json()["datos"][0]
        fragmento = primero["nombre"].split()[0][:5]
        cuerpo = c.get(f"{API}/clientes?busqueda={fragmento}", headers=cab).json()
    assert cuerpo["total"] >= 1
    assert all(fragmento.lower() in x["nombre"].lower()
               or fragmento.lower() in x["codigo_cliente"].lower()
               for x in cuerpo["datos"])


def test_filtro_por_tipo():
    with crear_cliente_http() as c:
        cuerpo = c.get(f"{API}/clientes?tipo_cliente=INDUSTRIAL",
                       headers=cabecera(c)).json()
    assert cuerpo["datos"]
    assert all(x["tipo_cliente"] == "INDUSTRIAL" for x in cuerpo["datos"])


def test_filtro_por_tipo_invalido():
    with crear_cliente_http() as c:
        respuesta = c.get(f"{API}/clientes?tipo_cliente=INVENTADO",
                          headers=cabecera(c))
    assert respuesta.status_code == 409
    assert respuesta.json()["codigo_error"] == "REGLA_DE_NEGOCIO"


def test_catalogos_y_resumen():
    with crear_cliente_http() as c:
        cab = cabecera(c)
        catalogos = c.get(f"{API}/clientes/catalogos", headers=cab).json()["datos"]
        resumen = c.get(f"{API}/clientes/resumen", headers=cab).json()["datos"]
    assert set(catalogos["tipos_cliente"]) == set(settings.CATALOGO_TIPO_CLIENTE)
    assert len(catalogos["municipios"]) >= 1
    assert resumen["total"] == resumen["activos"] + resumen["inactivos"]
    assert sum(resumen["por_tipo"].values()) >= 100


def test_rutas_fijas_no_se_confunden_con_un_id():
    with crear_cliente_http() as c:
        cab = cabecera(c)
        assert c.get(f"{API}/clientes/catalogos", headers=cab).status_code == 200
        assert c.get(f"{API}/clientes/resumen", headers=cab).status_code == 200


# ==========================================================================
# ALTA  (RN-C1 y RN-C2)
# ==========================================================================
def test_el_sistema_asigna_el_codigo():
    """RN-C1: el código lo genera el sistema, con el formato CLI-NNN."""
    with crear_cliente_http() as c:
        creado = alta(c, cabecera(c), "codigo")
    assert creado["codigo_cliente"].startswith("CLI-")
    assert len(creado["codigo_cliente"]) >= 7
    assert creado["total_entregas"] == 0
    assert creado["activo"] is True


def test_el_codigo_no_se_repite():
    with crear_cliente_http() as c:
        cab = cabecera(c)
        uno = alta(c, cab, "consec1")
        dos = alta(c, cab, "consec2")
    assert uno["codigo_cliente"] != dos["codigo_cliente"]


def test_una_sola_direccion_sin_marcar_se_marca_sola():
    """RN-C2: con una única dirección, exigir la marca sería burocracia."""
    with crear_cliente_http() as c:
        creado = alta(c, cabecera(c), "unica",
                      direcciones=[direccion(principal=False)])
    assert creado["direcciones"][0]["principal"] is True


def test_varias_direcciones_sin_principal_se_rechazan():
    """RN-C2: con varias, la intención es ambigua y hay que declararla."""
    with crear_cliente_http() as c:
        respuesta = c.post(
            f"{API}/clientes", headers=cabecera(c),
            json={"nombre": f"{MARCA} ambigua", "tipo_cliente": "MINORISTA",
                  "direcciones": [direccion("Matriz", False),
                                  direccion("Bodega", False)]})
    assert respuesta.status_code == 409, respuesta.text
    assert respuesta.json()["codigo_error"] == "REGLA_C2"


def test_dos_direcciones_principales_se_rechazan():
    with crear_cliente_http() as c:
        respuesta = c.post(
            f"{API}/clientes", headers=cabecera(c),
            json={"nombre": f"{MARCA} doble", "tipo_cliente": "MINORISTA",
                  "direcciones": [direccion("Matriz", True),
                                  direccion("Bodega", True)]})
    assert respuesta.status_code == 409, respuesta.text
    assert respuesta.json()["codigo_error"] == "REGLA_C2"


def test_sin_direcciones_se_rechaza():
    with crear_cliente_http() as c:
        respuesta = c.post(
            f"{API}/clientes", headers=cabecera(c),
            json={"nombre": f"{MARCA} sin dir", "tipo_cliente": "MINORISTA",
                  "direcciones": []})
    assert respuesta.status_code == 422


def test_tipo_fuera_de_catalogo_se_rechaza():
    with crear_cliente_http() as c:
        respuesta = c.post(
            f"{API}/clientes", headers=cabecera(c),
            json={"nombre": f"{MARCA} tipo", "tipo_cliente": "PARTICULAR",
                  "direcciones": [direccion()]})
    assert respuesta.status_code == 422
    assert respuesta.json()["codigo_error"] == "ESQUEMA_INVALIDO"


def test_codigo_postal_invalido_se_rechaza():
    with crear_cliente_http() as c:
        mala = direccion()
        mala["cp"] = "123"
        respuesta = c.post(
            f"{API}/clientes", headers=cabecera(c),
            json={"nombre": f"{MARCA} cp", "tipo_cliente": "MINORISTA",
                  "direcciones": [mala]})
    assert respuesta.status_code == 422


# ==========================================================================
# EDICIÓN
# ==========================================================================
def test_actualizar_parcialmente():
    """Los campos no enviados no se borran."""
    with crear_cliente_http() as c:
        cab = cabecera(c)
        creado = alta(c, cab, "editar", telefono="7221112233")
        respuesta = c.put(f"{API}/clientes/{creado['id']}", headers=cab,
                          json={"nombre": f"{MARCA} editado"})
    assert respuesta.status_code == 200, respuesta.text
    datos = respuesta.json()["datos"]
    assert datos["nombre"] == f"{MARCA} editado"
    assert datos["telefono"] == "7221112233", "el teléfono no debía borrarse"
    assert datos["codigo_cliente"] == creado["codigo_cliente"]


def test_reemplazar_direcciones_revalida_rn_c2():
    with crear_cliente_http() as c:
        cab = cabecera(c)
        creado = alta(c, cab, "dirs")
        respuesta = c.put(
            f"{API}/clientes/{creado['id']}", headers=cab,
            json={"direcciones": [direccion("Matriz", True),
                                  direccion("Bodega", True)]})
    assert respuesta.status_code == 409
    assert respuesta.json()["codigo_error"] == "REGLA_C2"


def test_actualizar_sin_campos_se_rechaza():
    with crear_cliente_http() as c:
        cab = cabecera(c)
        creado = alta(c, cab, "vacio")
        respuesta = c.put(f"{API}/clientes/{creado['id']}", headers=cab, json={})
    assert respuesta.status_code == 409
    assert "ningún campo" in respuesta.json()["mensaje"]


# ==========================================================================
# BAJA  (RN-C3 y RN-C4)
# ==========================================================================
def test_no_se_da_de_baja_un_cliente_que_es_parada_de_ruta():
    """
    RN-C3, la regla que protege la operación.

    Se usa un cliente del seed: los 100 son parada de alguna ruta, así que
    cualquiera sirve para provocar la situación real.
    """
    with crear_cliente_http() as c:
        cab = cabecera(c)
        existente = c.get(f"{API}/clientes?tamano=1", headers=cab).json()["datos"][0]
        respuesta = c.delete(f"{API}/clientes/{existente['id']}", headers=cab)
    assert respuesta.status_code == 409, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["codigo_error"] == "REGLA_C3"
    assert "ruta" in cuerpo["mensaje"].lower()
    assert cuerpo["detalles"][0]["rutas_afectadas"]


def test_baja_de_un_cliente_sin_rutas_si_funciona():
    """La regla impide lo peligroso, no lo legítimo."""
    with crear_cliente_http() as c:
        cab = cabecera(c)
        creado = alta(c, cab, "baja")
        respuesta = c.delete(f"{API}/clientes/{creado['id']}", headers=cab)
        assert respuesta.status_code == 200, respuesta.text
        assert respuesta.json()["datos"]["activo"] is False

        # RN-C4: el documento se conserva
        detalle = c.get(f"{API}/clientes/{creado['id']}", headers=cab)
        assert detalle.status_code == 200
        # y desaparece del listado por omisión
        activos = c.get(f"{API}/clientes?busqueda={MARCA}", headers=cab).json()
        assert creado["id"] not in [x["id"] for x in activos["datos"]]
        # pero se ve al pedir los inactivos
        todos = c.get(f"{API}/clientes?busqueda={MARCA}&incluir_inactivos=true",
                      headers=cab).json()
    assert creado["id"] in [x["id"] for x in todos["datos"]]


def test_reactivar():
    with crear_cliente_http() as c:
        cab = cabecera(c)
        creado = alta(c, cab, "reactiva")
        c.delete(f"{API}/clientes/{creado['id']}", headers=cab)
        respuesta = c.patch(f"{API}/clientes/{creado['id']}/reactivar", headers=cab)
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["datos"]["activo"] is True


def test_doble_baja_se_rechaza():
    with crear_cliente_http() as c:
        cab = cabecera(c)
        creado = alta(c, cab, "doble")
        c.delete(f"{API}/clientes/{creado['id']}", headers=cab)
        respuesta = c.delete(f"{API}/clientes/{creado['id']}", headers=cab)
    assert respuesta.status_code == 409
    assert "ya estaba" in respuesta.json()["mensaje"]


# ==========================================================================
# ERRORES
# ==========================================================================
def test_cliente_inexistente_da_404():
    with crear_cliente_http() as c:
        respuesta = c.get(f"{API}/clientes/6a83893489a0d3691e05ffff",
                          headers=cabecera(c))
    assert respuesta.status_code == 404
    assert respuesta.json()["codigo_error"] == "NO_ENCONTRADO"


def test_identificador_invalido_da_400():
    with crear_cliente_http() as c:
        respuesta = c.get(f"{API}/clientes/no-es-un-id", headers=cabecera(c))
    assert respuesta.status_code == 400
    assert respuesta.json()["codigo_error"] == "VALIDACION_FALLIDA"


def test_el_etl_no_se_ve_afectado():
    """
    Los clientes creados por la API llevan `origen_dato: REAL`, que los
    distingue de los SIMULADOS del seed sin sacarlos del alcance del ETL:
    un cliente capturado por el sistema web SÍ es dato del dominio.
    """
    with crear_cliente_http() as c:
        creado = alta(c, cabecera(c), "origen")
    assert creado["origen_dato"] == "REAL"
    assert "clientes" in settings.COLECCIONES_OPERATIVAS


# ==========================================================================
# Modo manual (sin pytest)
# ==========================================================================
if __name__ == "__main__":
    pruebas = [
        ("Sin sesión no se consulta", test_sin_sesion_no_se_consulta),
        ("Cualquier sesión puede consultar", test_cualquier_sesion_puede_consultar),
        ("Solo el administrador modifica", test_solo_el_administrador_modifica),
        ("El listado pagina y ordena", test_listado_pagina_y_ordena),
        ("Búsqueda por texto", test_busqueda_por_texto),
        ("Filtro por tipo", test_filtro_por_tipo),
        ("Filtro por tipo inválido", test_filtro_por_tipo_invalido),
        ("Catálogos y resumen", test_catalogos_y_resumen),
        ("Rutas fijas no se confunden con un id",
         test_rutas_fijas_no_se_confunden_con_un_id),
        ("El sistema asigna el código (RN-C1)", test_el_sistema_asigna_el_codigo),
        ("El código no se repite", test_el_codigo_no_se_repite),
        ("Una sola dirección se marca sola (RN-C2)",
         test_una_sola_direccion_sin_marcar_se_marca_sola),
        ("Varias sin principal se rechazan (RN-C2)",
         test_varias_direcciones_sin_principal_se_rechazan),
        ("Dos principales se rechazan (RN-C2)",
         test_dos_direcciones_principales_se_rechazan),
        ("Sin direcciones se rechaza", test_sin_direcciones_se_rechaza),
        ("Tipo fuera de catálogo se rechaza",
         test_tipo_fuera_de_catalogo_se_rechaza),
        ("Código postal inválido se rechaza",
         test_codigo_postal_invalido_se_rechaza),
        ("Actualizar parcialmente", test_actualizar_parcialmente),
        ("Reemplazar direcciones revalida RN-C2",
         test_reemplazar_direcciones_revalida_rn_c2),
        ("Actualizar sin campos se rechaza", test_actualizar_sin_campos_se_rechaza),
        ("No se da de baja un cliente con rutas (RN-C3)",
         test_no_se_da_de_baja_un_cliente_que_es_parada_de_ruta),
        ("Baja de un cliente sin rutas (RN-C4)",
         test_baja_de_un_cliente_sin_rutas_si_funciona),
        ("Reactivar", test_reactivar),
        ("Doble baja se rechaza", test_doble_baja_se_rechaza),
        ("Cliente inexistente da 404", test_cliente_inexistente_da_404),
        ("Identificador inválido da 400", test_identificador_invalido_da_400),
        ("Los clientes de la API llevan origen REAL",
         test_el_etl_no_se_ve_afectado),
    ]

    print("=" * 70)
    print("  SIG-LOG — Pruebas del módulo Clientes")
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

    print("-" * 70)
    print(f"  Clientes de prueba eliminados: {limpiar()}")
    print("=" * 70)
    print(f"  Resultado: {len(pruebas) - fallos}/{len(pruebas)} pruebas correctas")
    print("=" * 70)
    sys.exit(1 if fallos else 0)
