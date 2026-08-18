"""
SIG-LOG — Sistema Integral de Gestión Logística
tests/test_vehiculos.py

PRUEBAS DEL MÓDULO VEHÍCULOS

Más allá del CRUD, comprueban:

    RN-V1  el código VEH-NNN lo genera el sistema y es inmutable
    RN-V2  la placa es única en la flotilla
    RN-V3  (RN-04) un vehículo, una ruta; una ruta, un vehículo
    RN-V4  no se da de baja un vehículo con ruta asignada
    RN-V5  el estado operativo es una máquina de estados
    RN-V6  el odómetro, el rendimiento real y las fechas de mantenimiento
           no se editan desde el API

Y que el endpoint de rendimiento **no recalcula**: devuelve la misma cifra
que el ETL dejó en `dim_vehiculo`.

Los vehículos de prueba se borran al terminar. Se distinguen por una placa
con prefijo ZZZ, que ninguna unidad real usa.

Ejecución:
    pytest tests/test_vehiculos.py -v
    python tests/test_vehiculos.py
"""

from __future__ import annotations

import random
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
PREFIJO_PLACA = "ZZZ"


def cliente_http() -> TestClient:
    return TestClient(app)


def token_de(c: TestClient, usuario: str) -> str:
    r = c.post(f"{API}/auth/login",
               data={"username": usuario, "password": "siglog2026"})
    assert r.status_code == 200, r.text
    return r.json()["datos"]["access_token"]


def cab(c: TestClient, usuario: str = "admin") -> dict[str, str]:
    return {"Authorization": f"Bearer {token_de(c, usuario)}"}


def limpiar() -> int:
    return obtener_bd()["vehiculos"].delete_many(
        {"placa": {"$regex": f"^{PREFIJO_PLACA}"}}).deleted_count


try:
    import pytest

    @pytest.fixture(scope="module", autouse=True)
    def _limpiar_al_terminar():
        yield
        limpiar()
except ImportError:                    # pragma: no cover
    pass


_usadas: set[str] = set()


def placa_libre() -> str:
    """Placa ZZZ-NNNN que no se haya usado antes en esta corrida."""
    while True:
        placa = f"{PREFIJO_PLACA}-{random.randint(1000, 9999)}"
        if placa not in _usadas:
            _usadas.add(placa)
            return placa


def alta(c, cabecera, **extra) -> dict:
    cuerpo = {"placa": placa_libre(), "marca": "Marca Prueba",
              "modelo": "Modelo Prueba", "anio": 2022,
              "tipo_vehiculo": "MEDIANO", "tipo_combustible": "DIESEL",
              "capacidad_tanque_litros": 120,
              "rendimiento_nominal_km_l": 7.0, **extra}
    r = c.post(f"{API}/vehiculos", headers=cabecera, json=cuerpo)
    assert r.status_code == 201, r.text
    return r.json()["datos"]


# ==========================================================================
# PERMISOS
# ==========================================================================
def test_sin_sesion_no_se_consulta():
    with cliente_http() as c:
        assert c.get(f"{API}/vehiculos").status_code == 401


def test_cualquier_sesion_consulta():
    with cliente_http() as c:
        for u in ("admin", "despachador", "analista"):
            assert c.get(f"{API}/vehiculos", headers=cab(c, u)).status_code == 200


def test_solo_admin_da_de_alta():
    with cliente_http() as c:
        cuerpo = {"placa": placa_libre(), "marca": "X", "modelo": "Y",
                  "anio": 2022, "tipo_vehiculo": "LIGERO",
                  "capacidad_tanque_litros": 60,
                  "rendimiento_nominal_km_l": 10}
        for u in ("despachador", "analista"):
            r = c.post(f"{API}/vehiculos", headers=cab(c, u), json=cuerpo)
            assert r.status_code == 403, f"{u}: {r.status_code}"


def test_el_despachador_si_cambia_el_estado():
    """
    Excepción razonada: el despachador opera el día a día y registra que
    una unidad salió a ruta o entró al taller (§3). Exigir un administrador
    para eso pararía la operación.
    """
    with cliente_http() as c:
        vehiculo = alta(c, cab(c))
        r = c.patch(f"{API}/vehiculos/{vehiculo['id']}/estado",
                    headers=cab(c, "despachador"),
                    json={"estado_operativo": "EN_RUTA"})
        assert r.status_code == 200, r.text
        # El analista no: solo consulta
        r2 = c.patch(f"{API}/vehiculos/{vehiculo['id']}/estado",
                     headers=cab(c, "analista"),
                     json={"estado_operativo": "DISPONIBLE"})
    assert r2.status_code == 403


# ==========================================================================
# CONSULTA
# ==========================================================================
def test_listado_y_filtros():
    with cliente_http() as c:
        cabecera = cab(c)
        cuerpo = c.get(f"{API}/vehiculos?tamano=5", headers=cabecera).json()
        assert cuerpo["total"] >= 20, "deberían estar los 20 del seed"
        codigos = [v["codigo_vehiculo"] for v in cuerpo["datos"]]
        assert codigos == sorted(codigos)

        por_estado = c.get(f"{API}/vehiculos?estado=DISPONIBLE",
                           headers=cabecera).json()
        assert all(v["estado_operativo"] == "DISPONIBLE"
                   for v in por_estado["datos"])

        por_tipo = c.get(f"{API}/vehiculos?tipo_vehiculo=PESADO",
                         headers=cabecera).json()
    assert all(v["tipo_vehiculo"] == "PESADO" for v in por_tipo["datos"])


def test_filtro_con_estado_invalido():
    with cliente_http() as c:
        r = c.get(f"{API}/vehiculos?estado=VOLANDO", headers=cab(c))
    assert r.status_code == 409
    assert r.json()["codigo_error"] == "REGLA_DE_NEGOCIO"


def test_catalogos_incluyen_las_transiciones():
    with cliente_http() as c:
        datos = c.get(f"{API}/vehiculos/catalogos", headers=cab(c)).json()["datos"]
    assert set(datos["estados"]) == set(settings.CATALOGO_ESTADO_VEHICULO)
    assert datos["transiciones"]["EN_MANTENIMIENTO"] == ["DISPONIBLE"]
    assert datos["transiciones"]["BAJA"] == []


def test_resumen():
    with cliente_http() as c:
        datos = c.get(f"{API}/vehiculos/resumen", headers=cab(c)).json()["datos"]
    assert datos["total"] == datos["activos"] + datos["inactivos"]
    assert datos["con_ruta_asignada"] >= 20, "los 20 del seed tienen ruta"


# ==========================================================================
# RENDIMIENTO  (§12.3) — no recalcula
# ==========================================================================
def test_rendimiento_lee_lo_que_ya_existe():
    """
    El endpoint devuelve el agregado que el ETL dejó en `dim_vehiculo` y
    las cargas con su km/l ya registrado, sin volver a calcular.
    """
    bd = obtener_bd()
    with cliente_http() as c:
        cabecera = cab(c)
        vehiculo = c.get(f"{API}/vehiculos?tamano=1",
                         headers=cabecera).json()["datos"][0]
        datos = c.get(f"{API}/vehiculos/{vehiculo['id']}/rendimiento",
                      headers=cabecera).json()["datos"]

    assert datos["cargas"], "el vehículo del seed tiene cargas de combustible"
    assert all("rendimiento_km_l" in x for x in datos["cargas"])
    assert datos["rendimiento_nominal_km_l"] > 0
    assert "dim_vehiculo" in datos["origen_agregado"]

    # La cifra debe COINCIDIR con la del DW, no parecerse
    dimension = obtener_bd()["dim_vehiculo"].find_one({"_id": vehiculo["id"]})
    assert dimension is not None, "el ETL debe haber cargado dim_vehiculo"
    assert datos["rendimiento_real_km_l"] == dimension["rendimiento_real_km_l"]


def test_rendimiento_trae_su_lectura():
    with cliente_http() as c:
        cabecera = cab(c)
        vehiculo = c.get(f"{API}/vehiculos?tamano=1",
                         headers=cabecera).json()["datos"][0]
        cuerpo = c.get(f"{API}/vehiculos/{vehiculo['id']}/rendimiento",
                       headers=cabecera).json()
    assert len(cuerpo["mensaje"]) > 40
    assert "km/l" in cuerpo["mensaje"]


def test_rendimiento_de_un_vehiculo_nuevo_lo_dice():
    """Sin cargas ni ETL, se dice explícitamente en vez de inventar un número."""
    with cliente_http() as c:
        cabecera = cab(c)
        nuevo = alta(c, cabecera)
        datos = c.get(f"{API}/vehiculos/{nuevo['id']}/rendimiento",
                      headers=cabecera).json()["datos"]
    assert datos["cargas"] == []
    assert datos["rendimiento_real_km_l"] is None
    assert "no disponible" in datos["origen_agregado"]
    assert "Todavía no hay" in datos["lectura"]


# ==========================================================================
# ALTA  (RN-V1, RN-V2)
# ==========================================================================
def test_alta_asigna_codigo_y_estado_inicial():
    with cliente_http() as c:
        v = alta(c, cab(c))
    assert v["codigo_vehiculo"].startswith("VEH-")
    assert v["estado_operativo"] == "DISPONIBLE"
    assert v["ruta_asignada_id"] is None
    assert v["rendimiento_real_km_l"] is None
    assert v["origen_dato"] == "REAL"


def test_placa_duplicada_se_rechaza():
    with cliente_http() as c:
        cabecera = cab(c)
        v = alta(c, cabecera)
        r = c.post(f"{API}/vehiculos", headers=cabecera,
                   json={"placa": v["placa"], "marca": "Otra", "modelo": "Otro",
                         "anio": 2020, "tipo_vehiculo": "LIGERO",
                         "capacidad_tanque_litros": 50,
                         "rendimiento_nominal_km_l": 12})
    assert r.status_code == 409, r.text
    assert r.json()["codigo_error"] == "RECURSO_DUPLICADO"


def test_placa_se_normaliza_con_guion():
    with cliente_http() as c:
        placa = placa_libre().replace("-", "")
        v = alta(c, cab(c), placa=placa)
    assert v["placa"] == f"{placa[:3]}-{placa[3:]}"


def test_placa_con_formato_invalido():
    with cliente_http() as c:
        r = c.post(f"{API}/vehiculos", headers=cab(c),
                   json={"placa": "12345678", "marca": "X", "modelo": "Y",
                         "anio": 2020, "tipo_vehiculo": "LIGERO",
                         "capacidad_tanque_litros": 50,
                         "rendimiento_nominal_km_l": 12})
    assert r.status_code == 422


def test_tipo_fuera_de_catalogo():
    with cliente_http() as c:
        r = c.post(f"{API}/vehiculos", headers=cab(c),
                   json={"placa": placa_libre(), "marca": "X", "modelo": "Y",
                         "anio": 2020, "tipo_vehiculo": "SUBMARINO",
                         "capacidad_tanque_litros": 50,
                         "rendimiento_nominal_km_l": 12})
    assert r.status_code == 422


# ==========================================================================
# EDICIÓN  (RN-V6)
# ==========================================================================
def test_actualizar_ficha():
    with cliente_http() as c:
        cabecera = cab(c)
        v = alta(c, cabecera)
        r = c.put(f"{API}/vehiculos/{v['id']}", headers=cabecera,
                  json={"marca": "Marca Corregida"})
    assert r.status_code == 200, r.text
    assert r.json()["datos"]["marca"] == "Marca Corregida"
    assert r.json()["datos"]["codigo_vehiculo"] == v["codigo_vehiculo"]


def test_no_se_editan_los_campos_calculados():
    """
    RN-V6: el esquema los ignora, así que la comprobación se hace sobre el
    servicio, que es la barrera real si se le llamara desde otro sitio.
    """
    from backend.services import vehiculos as servicio
    from backend.utils.errores import ReglaDeNegocio

    bd = obtener_bd()
    doc = bd["vehiculos"].find_one({})
    for campo, valor in (("odometro_actual_km", 1),
                         ("rendimiento_real_km_l", 99),
                         ("estado_operativo", "EN_RUTA"),
                         ("ruta_asignada_id", None)):
        try:
            servicio.actualizar(bd, str(doc["_id"]), {campo: valor})
            raise AssertionError(f"RN-V6 debió rechazar el campo {campo}")
        except ReglaDeNegocio as exc:
            assert exc.codigo_error == "REGLA_V6", campo


# ==========================================================================
# ESTADO  (RN-V5)
# ==========================================================================
def test_transicion_valida():
    with cliente_http() as c:
        cabecera = cab(c)
        v = alta(c, cabecera)
        r = c.patch(f"{API}/vehiculos/{v['id']}/estado", headers=cabecera,
                    json={"estado_operativo": "EN_MANTENIMIENTO",
                          "motivo": "Servicio programado"})
    assert r.status_code == 200, r.text
    assert r.json()["datos"]["estado_operativo"] == "EN_MANTENIMIENTO"


def test_transicion_invalida_se_rechaza():
    """De EN_MANTENIMIENTO no se sale a EN_RUTA sin pasar por DISPONIBLE."""
    with cliente_http() as c:
        cabecera = cab(c)
        v = alta(c, cabecera)
        c.patch(f"{API}/vehiculos/{v['id']}/estado", headers=cabecera,
                json={"estado_operativo": "EN_MANTENIMIENTO"})
        r = c.patch(f"{API}/vehiculos/{v['id']}/estado", headers=cabecera,
                    json={"estado_operativo": "EN_RUTA"})
    assert r.status_code == 409, r.text
    cuerpo = r.json()
    assert cuerpo["codigo_error"] == "REGLA_V5"
    assert cuerpo["detalles"][0]["transiciones_validas"] == ["DISPONIBLE"]


def test_no_se_pone_baja_por_el_endpoint_de_estado():
    """BAJA solo se alcanza dando de baja el vehículo, con sus comprobaciones."""
    with cliente_http() as c:
        cabecera = cab(c)
        v = alta(c, cabecera)
        r = c.patch(f"{API}/vehiculos/{v['id']}/estado", headers=cabecera,
                    json={"estado_operativo": "BAJA"})
    assert r.status_code == 409
    assert r.json()["codigo_error"] == "REGLA_V5"


def test_mismo_estado_se_rechaza():
    with cliente_http() as c:
        cabecera = cab(c)
        v = alta(c, cabecera)
        r = c.patch(f"{API}/vehiculos/{v['id']}/estado", headers=cabecera,
                    json={"estado_operativo": "DISPONIBLE"})
    assert r.status_code == 409
    assert "ya está" in r.json()["mensaje"]


# ==========================================================================
# RUTA  (RN-V3 / RN-04)
# ==========================================================================
def test_no_se_asigna_una_ruta_ya_tomada():
    """RN-04: las 20 rutas del seed ya tienen vehículo."""
    bd = obtener_bd()
    ruta = bd["rutas"].find_one({"vehiculo_asignado_id": {"$ne": None}})
    with cliente_http() as c:
        cabecera = cab(c)
        nuevo = alta(c, cabecera)
        r = c.patch(f"{API}/vehiculos/{nuevo['id']}/ruta", headers=cabecera,
                    json={"ruta_id": str(ruta["_id"])})
    assert r.status_code == 409, r.text
    cuerpo = r.json()
    assert cuerpo["codigo_error"] == "REGLA_V3"
    assert cuerpo["detalles"][0]["ruta"] == ruta["codigo_ruta"]


def test_asignar_y_desasignar_sincroniza_los_dos_extremos():
    """
    Al asignar, la ruta debe quedar apuntando al vehículo, y al
    desasignar debe quedar libre. Si solo se escribiera un lado, la ruta
    seguiría diciendo que la cubre un vehículo que ya no la tiene.
    """
    bd = obtener_bd()
    with cliente_http() as c:
        cabecera = cab(c)
        nuevo = alta(c, cabecera)

        # Se libera una ruta del seed para la prueba y se restaura al final
        ruta = bd["rutas"].find_one({"vehiculo_asignado_id": {"$ne": None}})
        titular_id = ruta["vehiculo_asignado_id"]
        try:
            c.patch(f"{API}/vehiculos/{titular_id}/ruta", headers=cabecera,
                    json={"ruta_id": None})

            r = c.patch(f"{API}/vehiculos/{nuevo['id']}/ruta", headers=cabecera,
                        json={"ruta_id": str(ruta["_id"])})
            assert r.status_code == 200, r.text
            assert r.json()["datos"]["ruta_asignada_id"] == str(ruta["_id"])

            actual = obtener_bd()["rutas"].find_one({"_id": ruta["_id"]})
            assert str(actual["vehiculo_asignado_id"]) == nuevo["id"], (
                "la ruta debe apuntar al vehículo recién asignado")

            r2 = c.patch(f"{API}/vehiculos/{nuevo['id']}/ruta", headers=cabecera,
                         json={"ruta_id": None})
            assert r2.status_code == 200
            libre = obtener_bd()["rutas"].find_one({"_id": ruta["_id"]})
            assert libre["vehiculo_asignado_id"] is None
        finally:
            # Se devuelve la ruta a su vehículo original, pase lo que pase
            c.patch(f"{API}/vehiculos/{titular_id}/ruta", headers=cabecera,
                    json={"ruta_id": str(ruta["_id"])})

    restaurada = obtener_bd()["rutas"].find_one({"_id": ruta["_id"]})
    assert str(restaurada["vehiculo_asignado_id"]) == str(titular_id)


def test_ruta_inexistente():
    with cliente_http() as c:
        cabecera = cab(c)
        v = alta(c, cabecera)
        r = c.patch(f"{API}/vehiculos/{v['id']}/ruta", headers=cabecera,
                    json={"ruta_id": "6a83893489a0d3691e05ffff"})
    assert r.status_code == 409
    assert "No existe la ruta" in r.json()["mensaje"]


# ==========================================================================
# BAJA  (RN-V4)
# ==========================================================================
def test_no_se_da_de_baja_con_ruta_asignada():
    """RN-V4: los 20 del seed tienen ruta, así que ninguno se puede dar de baja."""
    with cliente_http() as c:
        cabecera = cab(c)
        conRuta = next(v for v in c.get(f"{API}/vehiculos?tamano=20",
                                        headers=cabecera).json()["datos"]
                       if v["ruta_asignada_id"])
        r = c.delete(f"{API}/vehiculos/{conRuta['id']}", headers=cabecera)
    assert r.status_code == 409, r.text
    assert r.json()["codigo_error"] == "REGLA_V4"
    assert r.json()["detalles"][0]["ruta_asignada"]


def test_baja_sin_ruta_funciona_y_deja_estado_baja():
    with cliente_http() as c:
        cabecera = cab(c)
        v = alta(c, cabecera)
        r = c.delete(f"{API}/vehiculos/{v['id']}", headers=cabecera)
        assert r.status_code == 200, r.text
        datos = r.json()["datos"]
        assert datos["activo"] is False
        assert datos["estado_operativo"] == "BAJA", (
            "el registro y la flotilla deben contar lo mismo")
        # El documento se conserva
        assert c.get(f"{API}/vehiculos/{v['id']}",
                     headers=cabecera).status_code == 200


def test_reactivar_deja_disponible():
    with cliente_http() as c:
        cabecera = cab(c)
        v = alta(c, cabecera)
        c.delete(f"{API}/vehiculos/{v['id']}", headers=cabecera)
        r = c.patch(f"{API}/vehiculos/{v['id']}/reactivar", headers=cabecera)
    assert r.status_code == 200, r.text
    assert r.json()["datos"]["activo"] is True
    assert r.json()["datos"]["estado_operativo"] == "DISPONIBLE"


# ==========================================================================
# ERRORES
# ==========================================================================
def test_inexistente_da_404():
    with cliente_http() as c:
        r = c.get(f"{API}/vehiculos/6a83893489a0d3691e05ffff", headers=cab(c))
    assert r.status_code == 404


def test_identificador_invalido_da_400():
    with cliente_http() as c:
        r = c.get(f"{API}/vehiculos/no-es-id", headers=cab(c))
    assert r.status_code == 400


# ==========================================================================
# Modo manual (sin pytest)
# ==========================================================================
if __name__ == "__main__":
    pruebas = [
        ("Sin sesión no se consulta", test_sin_sesion_no_se_consulta),
        ("Cualquier sesión consulta", test_cualquier_sesion_consulta),
        ("Solo el admin da de alta", test_solo_admin_da_de_alta),
        ("El despachador sí cambia el estado",
         test_el_despachador_si_cambia_el_estado),
        ("Listado y filtros", test_listado_y_filtros),
        ("Filtro con estado inválido", test_filtro_con_estado_invalido),
        ("Los catálogos incluyen las transiciones",
         test_catalogos_incluyen_las_transiciones),
        ("Resumen", test_resumen),
        ("Rendimiento lee lo que ya existe (no recalcula)",
         test_rendimiento_lee_lo_que_ya_existe),
        ("Rendimiento trae su lectura", test_rendimiento_trae_su_lectura),
        ("Rendimiento de un vehículo nuevo lo dice",
         test_rendimiento_de_un_vehiculo_nuevo_lo_dice),
        ("El alta asigna código y estado inicial (RN-V1)",
         test_alta_asigna_codigo_y_estado_inicial),
        ("Placa duplicada se rechaza (RN-V2)", test_placa_duplicada_se_rechaza),
        ("La placa se normaliza con guion", test_placa_se_normaliza_con_guion),
        ("Placa con formato inválido", test_placa_con_formato_invalido),
        ("Tipo fuera de catálogo", test_tipo_fuera_de_catalogo),
        ("Actualizar ficha", test_actualizar_ficha),
        ("No se editan los campos calculados (RN-V6)",
         test_no_se_editan_los_campos_calculados),
        ("Transición válida (RN-V5)", test_transicion_valida),
        ("Transición inválida se rechaza (RN-V5)",
         test_transicion_invalida_se_rechaza),
        ("BAJA no se pone por el endpoint de estado",
         test_no_se_pone_baja_por_el_endpoint_de_estado),
        ("Mismo estado se rechaza", test_mismo_estado_se_rechaza),
        ("No se asigna una ruta ya tomada (RN-04)",
         test_no_se_asigna_una_ruta_ya_tomada),
        ("Asignar y desasignar sincroniza los dos extremos",
         test_asignar_y_desasignar_sincroniza_los_dos_extremos),
        ("Ruta inexistente", test_ruta_inexistente),
        ("No se da de baja con ruta asignada (RN-V4)",
         test_no_se_da_de_baja_con_ruta_asignada),
        ("Baja sin ruta deja estado BAJA",
         test_baja_sin_ruta_funciona_y_deja_estado_baja),
        ("Reactivar deja DISPONIBLE", test_reactivar_deja_disponible),
        ("Inexistente da 404", test_inexistente_da_404),
        ("Identificador inválido da 400", test_identificador_invalido_da_400),
    ]

    print("=" * 70)
    print("  SIG-LOG — Pruebas del módulo Vehículos")
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
    print(f"  Vehículos de prueba eliminados: {limpiar()}")
    print("=" * 70)
    print(f"  Resultado: {len(pruebas) - fallos}/{len(pruebas)} pruebas correctas")
    print("=" * 70)
    sys.exit(1 if fallos else 0)
