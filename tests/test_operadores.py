"""
SIG-LOG — Sistema Integral de Gestión Logística
tests/test_operadores.py

PRUEBAS DEL MÓDULO OPERADORES

Además del CRUD:

    RN-O1  el código OPE-NNN lo genera el sistema y es inmutable
    RN-O2  el número de licencia es único
    RN-O3  un operador con licencia vencida no puede quedar ACTIVO
    RN-O4  el sistema avisa de las licencias por vencer
    RN-O5  no se da de baja a quien tiene viajes sin cerrar
    RN-O6  entregas y puntualidad no se editan desde el API

Y que el desempeño **lee** lo que calculó el ETL, con la advertencia ética
que pide el §11.3.

Los operadores de prueba se distinguen por un nombre con prefijo ZZ-PRUEBA
y se borran al terminar.
"""

from __future__ import annotations

import random
import sys
from datetime import date, timedelta
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from fastapi.testclient import TestClient

from backend.main import app
from config import settings
from config.mongo_conexion import obtener_bd

API = settings.API_PREFIJO
MARCA = "ZZ-PRUEBA"


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
    return obtener_bd()["operadores"].delete_many(
        {"nombre_completo": {"$regex": f"^{MARCA}"}}).deleted_count


try:
    import pytest

    @pytest.fixture(scope="module", autouse=True)
    def _limpiar_al_terminar():
        yield
        limpiar()
except ImportError:                    # pragma: no cover
    pass


_licencias: set[str] = set()


def licencia_libre() -> str:
    while True:
        numero = f"ZZ{random.randint(1000000, 9999999)}"
        if numero not in _licencias:
            _licencias.add(numero)
            return numero


def alta(c, cabecera, sufijo: str = "", *, vigencia: date | None = None,
         **extra) -> dict:
    cuerpo = {
        "nombre_completo": f"{MARCA} Operador {sufijo or random.randint(1, 999)}",
        "licencia": {"numero": licencia_libre(), "tipo": "C",
                     "vigencia": str(vigencia or (date.today()
                                                  + timedelta(days=365)))},
        "fecha_ingreso": str(date.today() - timedelta(days=400)),
        **extra,
    }
    r = c.post(f"{API}/operadores", headers=cabecera, json=cuerpo)
    assert r.status_code == 201, r.text
    return r.json()["datos"]


# ==========================================================================
# PERMISOS
# ==========================================================================
def test_sin_sesion_no_se_consulta():
    with cliente_http() as c:
        assert c.get(f"{API}/operadores").status_code == 401


def test_cualquier_sesion_consulta():
    with cliente_http() as c:
        for u in ("admin", "despachador", "analista"):
            assert c.get(f"{API}/operadores", headers=cab(c, u)).status_code == 200


def test_solo_admin_da_de_alta():
    with cliente_http() as c:
        cuerpo = {"nombre_completo": f"{MARCA} Intruso Prueba",
                  "licencia": {"numero": licencia_libre(), "tipo": "B",
                               "vigencia": str(date.today() + timedelta(days=200))},
                  "fecha_ingreso": str(date.today() - timedelta(days=100))}
        for u in ("despachador", "analista"):
            r = c.post(f"{API}/operadores", headers=cab(c, u), json=cuerpo)
            assert r.status_code == 403, f"{u}: {r.status_code}"


def test_el_despachador_cambia_el_estado():
    with cliente_http() as c:
        o = alta(c, cab(c))
        r = c.patch(f"{API}/operadores/{o['id']}/estado",
                    headers=cab(c, "despachador"), json={"estado": "INACTIVO"})
        assert r.status_code == 200, r.text
        r2 = c.patch(f"{API}/operadores/{o['id']}/estado",
                     headers=cab(c, "analista"), json={"estado": "ACTIVO"})
    assert r2.status_code == 403


# ==========================================================================
# CONSULTA
# ==========================================================================
def test_listado_y_filtros():
    with cliente_http() as c:
        cabecera = cab(c)
        cuerpo = c.get(f"{API}/operadores?tamano=5", headers=cabecera).json()
        assert cuerpo["total"] >= 24, "deberían estar los 24 del seed"
        codigos = [o["codigo_operador"] for o in cuerpo["datos"]]
        assert codigos == sorted(codigos)

        activos = c.get(f"{API}/operadores?estado=ACTIVO", headers=cabecera).json()
    assert all(o["estado"] == "ACTIVO" for o in activos["datos"])


def test_filtro_por_licencia_vencida():
    """Los 8 operadores del seed con licencia vencida deben poder aislarse."""
    with cliente_http() as c:
        cabecera = cab(c)
        vencidas = c.get(f"{API}/operadores?licencia_vencida=true",
                         headers=cabecera).json()
        vigentes = c.get(f"{API}/operadores?licencia_vencida=false",
                         headers=cabecera).json()
    assert vencidas["total"] >= 1
    assert all(o["licencia_vigente"] is False for o in vencidas["datos"])
    assert all(o["licencia_vigente"] is True for o in vigentes["datos"])


def test_la_salida_calcula_vigencia_y_antiguedad():
    with cliente_http() as c:
        o = c.get(f"{API}/operadores?tamano=1", headers=cab(c)).json()["datos"][0]
    assert o["licencia_vigente"] in (True, False)
    assert isinstance(o["dias_para_vencer_licencia"], int)
    assert o["antiguedad_meses"] is not None and o["antiguedad_meses"] >= 0


def test_licencias_vencidas_y_por_vencer():
    """RN-O4: la consulta que permite actuar antes de que sea un problema."""
    with cliente_http() as c:
        cuerpo = c.get(f"{API}/operadores/licencias?dias=60",
                       headers=cab(c)).json()
    datos = cuerpo["datos"]
    assert datos["dias_anticipacion"] == 60
    assert datos["total_vencidas"] >= 1, "el seed tiene licencias vencidas"
    for ficha in datos["vencidas"]:
        assert ficha["dias"] < 0, "una licencia vencida tiene días negativos"
    for ficha in datos["por_vencer"]:
        assert 0 <= ficha["dias"] <= 60
    assert "VENCIDA" in cuerpo["mensaje"] or "vigentes" in cuerpo["mensaje"]


def test_resumen_alerta_de_licencias():
    with cliente_http() as c:
        datos = c.get(f"{API}/operadores/resumen", headers=cab(c)).json()["datos"]
    assert datos["total"] == datos["activos"] + datos["inactivos"]
    assert datos["licencias_vencidas"] >= 1
    assert datos["dias_aviso_licencia"] == settings.DIAS_AVISO_LICENCIA


def test_catalogos_declaran_la_rotacion():
    """RNP-03: se dice explícitamente que el operador rota de vehículo."""
    with cliente_http() as c:
        datos = c.get(f"{API}/operadores/catalogos", headers=cab(c)).json()["datos"]
    assert set(datos["estados"]) == set(settings.CATALOGO_ESTADO_OPERADOR)
    assert "ROTAN" in datos["asignacion_vehiculo"]


# ==========================================================================
# DESEMPEÑO  (§12.3) — lee, no recalcula
# ==========================================================================
def test_desempenio_lee_del_dw():
    with cliente_http() as c:
        cabecera = cab(c)
        o = c.get(f"{API}/operadores?tamano=1", headers=cabecera).json()["datos"][0]
        datos = c.get(f"{API}/operadores/{o['id']}/desempenio",
                      headers=cabecera).json()["datos"]

    dimension = obtener_bd()["dim_operador"].find_one({"_id": o["id"]})
    assert dimension is not None, "el ETL debe haber cargado dim_operador"
    assert (datos["porcentaje_entregas_a_tiempo"]
            == dimension["porcentaje_entregas_a_tiempo"]), (
        "la cifra debe COINCIDIR con la del DW, no parecerse")
    assert "dim_operador" in datos["origen"]


def test_desempenio_situa_frente_a_la_flotilla():
    """Un porcentaje aislado no dice si es bueno; el promedio sí."""
    with cliente_http() as c:
        cabecera = cab(c)
        o = c.get(f"{API}/operadores?tamano=1", headers=cabecera).json()["datos"][0]
        datos = c.get(f"{API}/operadores/{o['id']}/desempenio",
                      headers=cabecera).json()["datos"]
    assert datos["promedio_flotilla"] is not None
    assert datos["diferencia_vs_flotilla"] is not None
    assert len(datos["lectura"]) > 60


def test_desempenio_incluye_la_advertencia_etica():
    """El §11.3 pide declarar el riesgo de evaluar personas; se declara."""
    with cliente_http() as c:
        cabecera = cab(c)
        o = c.get(f"{API}/operadores?tamano=1", headers=cabecera).json()["datos"][0]
        datos = c.get(f"{API}/operadores/{o['id']}/desempenio",
                      headers=cabecera).json()["datos"]
    assert "no para evaluar a personas" in datos["aviso"]
    assert "§11.3" in datos["aviso"]


def test_desempenio_de_un_operador_nuevo():
    with cliente_http() as c:
        cabecera = cab(c)
        nuevo = alta(c, cabecera)
        datos = c.get(f"{API}/operadores/{nuevo['id']}/desempenio",
                      headers=cabecera).json()["datos"]
    assert datos["porcentaje_entregas_a_tiempo"] is None
    assert "no disponible" in datos["origen"]
    assert "Todavía no hay" in datos["lectura"]


# ==========================================================================
# ALTA  (RN-O1, RN-O2, RN-O3)
# ==========================================================================
def test_alta_asigna_codigo():
    with cliente_http() as c:
        o = alta(c, cab(c))
    assert o["codigo_operador"].startswith("OPE-")
    assert o["estado"] == "ACTIVO"
    assert o["total_entregas"] == 0
    assert o["porcentaje_entregas_a_tiempo"] is None
    assert o["origen_dato"] == "REAL"


def test_licencia_duplicada_se_rechaza():
    with cliente_http() as c:
        cabecera = cab(c)
        o = alta(c, cabecera)
        r = c.post(f"{API}/operadores", headers=cabecera,
                   json={"nombre_completo": f"{MARCA} Otro Distinto",
                         "licencia": {"numero": o["licencia"]["numero"],
                                      "tipo": "B",
                                      "vigencia": str(date.today()
                                                      + timedelta(days=100))},
                         "fecha_ingreso": str(date.today() - timedelta(days=50))})
    assert r.status_code == 409, r.text
    assert r.json()["codigo_error"] == "RECURSO_DUPLICADO"


def test_alta_con_licencia_vencida_nace_inactivo():
    """RN-O3 desde el alta: no se registra como ACTIVO a quien no puede conducir."""
    with cliente_http() as c:
        o = alta(c, cab(c), vigencia=date.today() - timedelta(days=10))
    assert o["estado"] == "INACTIVO"
    assert o["licencia_vigente"] is False


def test_fecha_de_ingreso_futura_se_rechaza():
    with cliente_http() as c:
        r = c.post(f"{API}/operadores", headers=cab(c),
                   json={"nombre_completo": f"{MARCA} Del Futuro",
                         "licencia": {"numero": licencia_libre(), "tipo": "C",
                                      "vigencia": str(date.today()
                                                      + timedelta(days=300))},
                         "fecha_ingreso": str(date.today() + timedelta(days=30))})
    assert r.status_code == 422


def test_tipo_de_licencia_invalido():
    with cliente_http() as c:
        r = c.post(f"{API}/operadores", headers=cab(c),
                   json={"nombre_completo": f"{MARCA} Tipo Malo",
                         "licencia": {"numero": licencia_libre(), "tipo": "Z",
                                      "vigencia": str(date.today()
                                                      + timedelta(days=300))},
                         "fecha_ingreso": str(date.today() - timedelta(days=30))})
    assert r.status_code == 422


# ==========================================================================
# EDICIÓN Y RENOVACIÓN
# ==========================================================================
def test_actualizar_y_renovar_licencia():
    """Enviar `licencia` es la vía para registrar una renovación."""
    with cliente_http() as c:
        cabecera = cab(c)
        o = alta(c, cabecera, vigencia=date.today() - timedelta(days=5))
        assert o["licencia_vigente"] is False

        nueva = str(date.today() + timedelta(days=730))
        r = c.put(f"{API}/operadores/{o['id']}", headers=cabecera,
                  json={"licencia": {"numero": o["licencia"]["numero"],
                                     "tipo": "C", "vigencia": nueva}})
        assert r.status_code == 200, r.text
        assert r.json()["datos"]["licencia_vigente"] is True

        # Y ahora sí se puede activar
        activacion = c.patch(f"{API}/operadores/{o['id']}/estado",
                             headers=cabecera, json={"estado": "ACTIVO"})
    assert activacion.status_code == 200, activacion.text


def test_no_se_editan_los_campos_calculados():
    from backend.services import operadores as servicio
    from backend.utils.errores import ReglaDeNegocio

    bd = obtener_bd()
    doc = bd["operadores"].find_one({})
    for campo, valor in (("total_entregas", 5),
                         ("porcentaje_entregas_a_tiempo", 99.9),
                         ("estado", "INACTIVO")):
        try:
            servicio.actualizar(bd, str(doc["_id"]), {campo: valor})
            raise AssertionError(f"RN-O6 debió rechazar {campo}")
        except ReglaDeNegocio as exc:
            assert exc.codigo_error == "REGLA_O6", campo


# ==========================================================================
# ESTADO  (RN-O3)
# ==========================================================================
def test_no_se_activa_con_licencia_vencida():
    """
    RN-O3, la regla central del módulo: el sistema no facilita que alguien
    conduzca sin licencia vigente.
    """
    with cliente_http() as c:
        cabecera = cab(c)
        o = alta(c, cabecera, vigencia=date.today() - timedelta(days=30))
        r = c.patch(f"{API}/operadores/{o['id']}/estado", headers=cabecera,
                    json={"estado": "ACTIVO"})
    assert r.status_code == 409, r.text
    cuerpo = r.json()
    assert cuerpo["codigo_error"] == "REGLA_O3"
    assert "venció" in cuerpo["mensaje"]
    assert cuerpo["detalles"][0]["vigencia"]


def test_desactivar_siempre_se_puede():
    """
    Poner INACTIVO a alguien nunca se bloquea: es la medida prudente y el
    sistema no debe ponerle trabas.

    El operador se crea con licencia VIGENTE —así nace ACTIVO— porque uno
    con la licencia vencida ya nace INACTIVO por RN-O3 y no habría cambio
    de estado que probar.
    """
    with cliente_http() as c:
        cabecera = cab(c)
        o = alta(c, cabecera)
        assert o["estado"] == "ACTIVO"
        r = c.patch(f"{API}/operadores/{o['id']}/estado", headers=cabecera,
                    json={"estado": "INACTIVO", "motivo": "Baja temporal"})
    assert r.status_code == 200, r.text
    assert r.json()["datos"]["estado"] == "INACTIVO"


def test_mismo_estado_se_rechaza():
    with cliente_http() as c:
        cabecera = cab(c)
        o = alta(c, cabecera)
        r = c.patch(f"{API}/operadores/{o['id']}/estado", headers=cabecera,
                    json={"estado": "ACTIVO"})
    assert r.status_code == 409
    assert "ya está" in r.json()["mensaje"]


# ==========================================================================
# BAJA  (RN-O5)
# ==========================================================================
def test_baja_logica_conserva_el_documento():
    with cliente_http() as c:
        cabecera = cab(c)
        o = alta(c, cabecera)
        r = c.delete(f"{API}/operadores/{o['id']}", headers=cabecera)
        assert r.status_code == 200, r.text
        assert r.json()["datos"]["activo"] is False
        assert r.json()["datos"]["estado"] == "INACTIVO"
        assert c.get(f"{API}/operadores/{o['id']}",
                     headers=cabecera).status_code == 200


def test_reactivar_no_habilita_para_conducir():
    """
    Reactivar la ficha y autorizar a conducir son decisiones distintas: la
    primera devuelve el registro, la segunda pasa por la comprobación de
    la licencia.
    """
    with cliente_http() as c:
        cabecera = cab(c)
        o = alta(c, cabecera)
        c.delete(f"{API}/operadores/{o['id']}", headers=cabecera)
        r = c.patch(f"{API}/operadores/{o['id']}/reactivar", headers=cabecera)
    assert r.status_code == 200, r.text
    datos = r.json()["datos"]
    assert datos["activo"] is True
    assert datos["estado"] == "INACTIVO", (
        "reactivar la ficha no debe habilitar automáticamente para conducir")


def test_rn_o5_bloquea_la_baja_con_viajes_en_curso():
    """
    RN-O5 en la capa de servicio.

    Se prueba aquí porque el periodo simulado ya cerró: todos los viajes
    están FINALIZADOS o CANCELADOS, así que por la API no hay forma de
    provocar la situación. La regla protege el día en que el sistema
    registre viajes en curso.
    """
    from bson import ObjectId

    from backend.services import operadores as servicio
    from backend.utils.errores import ReglaDeNegocio

    bd = obtener_bd()
    operador = bd["operadores"].find_one({"activo": {"$ne": False}})
    viaje = bd["viajes"].find_one({"operador_id": operador["_id"]})
    assert viaje is not None, "el operador del seed debe tener viajes"

    original = viaje["estatus"]
    try:
        bd["viajes"].update_one({"_id": viaje["_id"]},
                                {"$set": {"estatus": "EN_RUTA"}})
        try:
            servicio.desactivar(bd, str(operador["_id"]))
            raise AssertionError("RN-O5 debió impedir la baja")
        except ReglaDeNegocio as exc:
            assert exc.codigo_error == "REGLA_O5"
            assert exc.detalles[0]["viajes_en_curso"] >= 1
    finally:
        # Se restaura SIEMPRE el estatus original del viaje
        obtener_bd()["viajes"].update_one(
            {"_id": ObjectId(str(viaje["_id"]))},
            {"$set": {"estatus": original}})

    assert obtener_bd()["viajes"].find_one(
        {"_id": viaje["_id"]})["estatus"] == original


# ==========================================================================
# ERRORES
# ==========================================================================
def test_inexistente_da_404():
    with cliente_http() as c:
        r = c.get(f"{API}/operadores/6a83893489a0d3691e05ffff", headers=cab(c))
    assert r.status_code == 404


def test_identificador_invalido_da_400():
    with cliente_http() as c:
        r = c.get(f"{API}/operadores/no-es-id", headers=cab(c))
    assert r.status_code == 400


# ==========================================================================
# Modo manual (sin pytest)
# ==========================================================================
if __name__ == "__main__":
    pruebas = [
        ("Sin sesión no se consulta", test_sin_sesion_no_se_consulta),
        ("Cualquier sesión consulta", test_cualquier_sesion_consulta),
        ("Solo el admin da de alta", test_solo_admin_da_de_alta),
        ("El despachador cambia el estado", test_el_despachador_cambia_el_estado),
        ("Listado y filtros", test_listado_y_filtros),
        ("Filtro por licencia vencida", test_filtro_por_licencia_vencida),
        ("La salida calcula vigencia y antigüedad",
         test_la_salida_calcula_vigencia_y_antiguedad),
        ("Licencias vencidas y por vencer (RN-O4)",
         test_licencias_vencidas_y_por_vencer),
        ("El resumen alerta de licencias", test_resumen_alerta_de_licencias),
        ("Los catálogos declaran la rotación (RNP-03)",
         test_catalogos_declaran_la_rotacion),
        ("Desempeño lee del DW (no recalcula)", test_desempenio_lee_del_dw),
        ("Desempeño sitúa frente a la flotilla",
         test_desempenio_situa_frente_a_la_flotilla),
        ("Desempeño incluye la advertencia ética (§11.3)",
         test_desempenio_incluye_la_advertencia_etica),
        ("Desempeño de un operador nuevo", test_desempenio_de_un_operador_nuevo),
        ("El alta asigna código (RN-O1)", test_alta_asigna_codigo),
        ("Licencia duplicada se rechaza (RN-O2)",
         test_licencia_duplicada_se_rechaza),
        ("Alta con licencia vencida nace INACTIVO (RN-O3)",
         test_alta_con_licencia_vencida_nace_inactivo),
        ("Fecha de ingreso futura se rechaza",
         test_fecha_de_ingreso_futura_se_rechaza),
        ("Tipo de licencia inválido", test_tipo_de_licencia_invalido),
        ("Actualizar y renovar licencia", test_actualizar_y_renovar_licencia),
        ("No se editan los campos calculados (RN-O6)",
         test_no_se_editan_los_campos_calculados),
        ("No se activa con licencia vencida (RN-O3)",
         test_no_se_activa_con_licencia_vencida),
        ("Desactivar siempre se puede", test_desactivar_siempre_se_puede),
        ("Mismo estado se rechaza", test_mismo_estado_se_rechaza),
        ("La baja lógica conserva el documento",
         test_baja_logica_conserva_el_documento),
        ("Reactivar no habilita para conducir",
         test_reactivar_no_habilita_para_conducir),
        ("RN-O5 bloquea la baja con viajes en curso",
         test_rn_o5_bloquea_la_baja_con_viajes_en_curso),
        ("Inexistente da 404", test_inexistente_da_404),
        ("Identificador inválido da 400", test_identificador_invalido_da_400),
    ]

    print("=" * 70)
    print("  SIG-LOG — Pruebas del módulo Operadores")
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
    print(f"  Operadores de prueba eliminados: {limpiar()}")
    print("=" * 70)
    print(f"  Resultado: {len(pruebas) - fallos}/{len(pruebas)} pruebas correctas")
    print("=" * 70)
    sys.exit(1 if fallos else 0)
