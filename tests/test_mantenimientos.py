"""
SIG-LOG — Sistema Integral de Gestión Logística
tests/test_mantenimientos.py

PRUEBAS DEL MÓDULO MANTENIMIENTOS Y DE LA ALERTA RF-16

    RN-M1  el folio MTO-AAAAMMDD-NNNN lo genera el sistema
    RN-M2  PROGRAMADO → REALIZADO | VENCIDO, VENCIDO → REALIZADO,
           REALIZADO → nada
    RN-M3  una unidad no tiene dos servicios abiertos a la vez
    RN-M4  duración y próxima fecha se calculan, no se capturan
    RN-M5  realizar el servicio escribe las fechas del vehículo (cierra
           la promesa de RN-V6)
    RN-M6  vencido saca la unidad de operación; realizarlo la devuelve,
           pero solo si no le quedan otros vencidos
    RN-M7  no se vence por anticipado

Los vehículos de prueba llevan placa ZZM y se borran con sus servicios.
"""

from __future__ import annotations

import random
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from fastapi.testclient import TestClient

from backend.main import app
from config import settings
from config.mongo_conexion import obtener_bd

API = settings.API_PREFIJO
PLACA = "ZZM"
HOY = datetime.now(timezone.utc).date()


def cliente_http() -> TestClient:
    return TestClient(app)


def cab(c: TestClient, usuario: str = "admin") -> dict[str, str]:
    r = c.post(f"{API}/auth/login",
               data={"username": usuario, "password": "siglog2026"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['datos']['access_token']}"}


def limpiar() -> dict[str, int]:
    bd = obtener_bd()
    vehiculos = [v["_id"] for v in bd["vehiculos"].find(
        {"placa": {"$regex": f"^{PLACA}"}}, {"_id": 1})]
    return {
        "mantenimientos": (bd["mantenimientos"].delete_many(
            {"vehiculo_id": {"$in": vehiculos}}).deleted_count
            if vehiculos else 0),
        "vehiculos": bd["vehiculos"].delete_many(
            {"placa": {"$regex": f"^{PLACA}"}}).deleted_count,
    }


try:
    import pytest

    @pytest.fixture(scope="module", autouse=True)
    def _limpiar_al_terminar():
        yield
        limpiar()
except ImportError:                    # pragma: no cover
    pass


# --------------------------------------------------------------------------
# Escenario
# --------------------------------------------------------------------------
def crear_vehiculo(c, cabecera) -> dict:
    r = c.post(f"{API}/vehiculos", headers=cabecera, json={
        "placa": f"{PLACA}-{random.randint(1000, 9999)}", "marca": "Prueba",
        "modelo": "Mantenimiento", "anio": 2023, "tipo_vehiculo": "MEDIANO",
        "tipo_combustible": "DIESEL", "capacidad_tanque_litros": 120,
        "rendimiento_nominal_km_l": 7.0, "odometro_actual_km": 90_000})
    assert r.status_code == 201, r.text
    return r.json()["datos"]


def programar(c, cabecera, vehiculo, *, dias: int = 5,
              tipo: str = "PREVENTIVO", **extra):
    cuerpo = {"vehiculo_id": vehiculo["id"], "tipo": tipo,
              "fecha_programada": str(HOY + timedelta(days=dias)),
              "descripcion": "Servicio de prueba", "costo_estimado": 5000}
    cuerpo.update(extra)
    return c.post(f"{API}/mantenimientos", headers=cabecera, json=cuerpo)


def realizar(c, cabecera, identificador, **extra):
    cuerpo = {"odometro_km": 91_000, "costo": 5400.0}
    cuerpo.update(extra)
    return c.patch(f"{API}/mantenimientos/{identificador}/realizar",
                   headers=cabecera, json=cuerpo)


# ==========================================================================
# PROGRAMACIÓN
# ==========================================================================
def test_programar_genera_folio_del_sistema():
    """RN-M1: el folio es MTO-AAAAMMDD-NNNN y nace PROGRAMADO."""
    c = cliente_http()
    cabecera = cab(c)
    vehiculo = crear_vehiculo(c, cabecera)

    r = programar(c, cabecera, vehiculo, dias=5)
    assert r.status_code == 201, r.text
    datos = r.json()["datos"]

    folio = datos["folio_mantenimiento"]
    esperado = f"MTO-{(HOY + timedelta(days=5)):%Y%m%d}-"
    assert folio.startswith(esperado), folio
    assert len(folio.rsplit("-", 1)[1]) == 4, folio
    assert datos["estatus"] == "PROGRAMADO"
    # Capturado desde el sistema web, no simulado
    assert datos["origen_dato"] == "REAL"
    # RN-M4: los campos derivados nacen vacíos, no en cero
    assert datos["duracion_dias"] is None
    assert datos["proximo_mantenimiento_fecha"] is None
    assert datos["fecha_realizada"] is None
    # Aún falta para la fecha: el atraso es negativo
    assert datos["dias_de_atraso"] < 0, datos["dias_de_atraso"]


def test_una_unidad_no_tiene_dos_servicios_abiertos():
    """RN-M3."""
    c = cliente_http()
    cabecera = cab(c)
    vehiculo = crear_vehiculo(c, cabecera)

    assert programar(c, cabecera, vehiculo, dias=-5).status_code == 201

    r = programar(c, cabecera, vehiculo, dias=20, tipo="CORRECTIVO")
    assert r.status_code == 409, r.text
    cuerpo = r.json()
    assert cuerpo["codigo_error"] == "REGLA_M3", cuerpo
    assert "sin realizar" in cuerpo["mensaje"]

    # Realizado el primero, la unidad vuelve a admitir programación
    primero = c.get(f"{API}/mantenimientos", headers=cabecera,
                    params={"vehiculo_id": vehiculo["id"]}).json()["datos"][0]
    assert realizar(c, cabecera, primero["id"]).status_code == 200
    assert programar(c, cabecera, vehiculo, dias=40).status_code == 201


def test_vehiculo_inexistente_se_rechaza():
    c = cliente_http()
    cabecera = cab(c)
    r = c.post(f"{API}/mantenimientos", headers=cabecera, json={
        "vehiculo_id": "0" * 24, "tipo": "PREVENTIVO",
        "fecha_programada": str(HOY + timedelta(days=3))})
    assert r.status_code == 409, r.text
    assert "No existe el vehículo" in r.json()["mensaje"]


def test_tipo_fuera_del_catalogo_se_rechaza():
    """RNP-05: solo PREVENTIVO y CORRECTIVO."""
    c = cliente_http()
    cabecera = cab(c)
    vehiculo = crear_vehiculo(c, cabecera)
    r = programar(c, cabecera, vehiculo, tipo="URGENTE")
    assert r.status_code == 422, r.text


# ==========================================================================
# EDICIÓN
# ==========================================================================
def test_los_campos_calculados_no_se_editan():
    """RN-M4: duración, próxima fecha y estatus no se capturan."""
    c = cliente_http()
    cabecera = cab(c)
    vehiculo = crear_vehiculo(c, cabecera)
    mantenimiento = programar(c, cabecera, vehiculo).json()["datos"]

    for campo, valor in (("estatus", "REALIZADO"), ("duracion_dias", 3),
                         ("costo", 100)):
        r = c.put(f"{API}/mantenimientos/{mantenimiento['id']}",
                  headers=cabecera, json={campo: valor})
        # El esquema no declara esos campos: Pydantic los ignora y el
        # servicio ve una edición vacía. En cualquiera de los dos caminos
        # el valor calculado queda intacto, que es lo que se protege.
        assert r.status_code == 409, f"{campo}: {r.text}"

    actual = c.get(f"{API}/mantenimientos/{mantenimiento['id']}",
                   headers=cabecera).json()["datos"]
    assert actual["estatus"] == "PROGRAMADO"
    assert actual["duracion_dias"] is None
    assert actual["costo"] is None


def test_un_servicio_realizado_no_se_edita():
    """RN-M2: es el registro de lo que se hizo."""
    c = cliente_http()
    cabecera = cab(c)
    vehiculo = crear_vehiculo(c, cabecera)
    mantenimiento = programar(c, cabecera, vehiculo, dias=-2).json()["datos"]
    assert realizar(c, cabecera, mantenimiento["id"]).status_code == 200

    r = c.put(f"{API}/mantenimientos/{mantenimiento['id']}", headers=cabecera,
              json={"descripcion": "Corrección posterior"})
    assert r.status_code == 409, r.text
    assert r.json()["codigo_error"] == "REGLA_M2"


def test_editar_la_fecha_programada_funciona():
    c = cliente_http()
    cabecera = cab(c)
    vehiculo = crear_vehiculo(c, cabecera)
    mantenimiento = programar(c, cabecera, vehiculo, dias=5).json()["datos"]

    nueva = HOY + timedelta(days=12)
    r = c.put(f"{API}/mantenimientos/{mantenimiento['id']}", headers=cabecera,
              json={"fecha_programada": str(nueva), "costo_estimado": 9000})
    assert r.status_code == 200, r.text
    datos = r.json()["datos"]
    assert datos["fecha_programada"].startswith(str(nueva))
    assert datos["costo_estimado"] == 9000


# ==========================================================================
# REALIZAR  (RN-M4, RN-M5)
# ==========================================================================
def test_realizar_calcula_duracion_y_proxima_fecha():
    """RN-M4."""
    c = cliente_http()
    cabecera = cab(c)
    vehiculo = crear_vehiculo(c, cabecera)
    mantenimiento = programar(c, cabecera, vehiculo, dias=-4).json()["datos"]

    realizada = HOY - timedelta(days=1)
    r = realizar(c, cabecera, mantenimiento["id"],
                 fecha_realizada=str(realizada))
    assert r.status_code == 200, r.text
    datos = r.json()["datos"]

    assert datos["estatus"] == "REALIZADO"
    # De la programada (hoy-4) a la realizada (hoy-1) van 3 días
    assert datos["duracion_dias"] == 3.0, datos["duracion_dias"]
    esperada = realizada + timedelta(
        days=settings.DIAS_PERIODICIDAD_MANTENIMIENTO)
    assert datos["proximo_mantenimiento_fecha"].startswith(str(esperada)), datos
    # Ya realizado, deja de acumular atraso
    assert datos["dias_de_atraso"] is None


def test_realizar_actualiza_las_fechas_del_vehiculo():
    """
    RN-M5 — y con ella se cierra RN-V6.

    La ficha del vehículo prohíbe capturar estas dos fechas porque "se
    derivan de la colección mantenimientos". Esta prueba es la que
    comprueba que efectivamente se derivan.
    """
    c = cliente_http()
    cabecera = cab(c)
    vehiculo = crear_vehiculo(c, cabecera)

    antes = c.get(f"{API}/vehiculos/{vehiculo['id']}",
                  headers=cabecera).json()["datos"]
    assert not antes.get("fecha_ultimo_mantenimiento")

    # La ficha no deja capturarlas (RN-V6)
    r = c.put(f"{API}/vehiculos/{vehiculo['id']}", headers=cabecera,
              json={"fecha_ultimo_mantenimiento": str(HOY)})
    assert r.status_code in (409, 422), r.text

    mantenimiento = programar(c, cabecera, vehiculo, dias=-2).json()["datos"]
    realizada = HOY
    assert realizar(c, cabecera, mantenimiento["id"],
                    fecha_realizada=str(realizada)).status_code == 200

    bd = obtener_bd()
    from bson import ObjectId
    despues = bd["vehiculos"].find_one({"_id": ObjectId(vehiculo["id"])})
    assert despues["fecha_ultimo_mantenimiento"].date() == realizada
    assert despues["fecha_proximo_mantenimiento"].date() == (
        realizada + timedelta(days=settings.DIAS_PERIODICIDAD_MANTENIMIENTO))


def test_no_se_realiza_antes_de_la_fecha_programada():
    c = cliente_http()
    cabecera = cab(c)
    vehiculo = crear_vehiculo(c, cabecera)
    mantenimiento = programar(c, cabecera, vehiculo, dias=20).json()["datos"]

    r = realizar(c, cabecera, mantenimiento["id"],
                 fecha_realizada=str(HOY))
    assert r.status_code == 409, r.text
    assert "anterior a la" in r.json()["mensaje"]


def test_un_servicio_realizado_no_se_realiza_dos_veces():
    """RN-M2: de REALIZADO no se sale."""
    c = cliente_http()
    cabecera = cab(c)
    vehiculo = crear_vehiculo(c, cabecera)
    mantenimiento = programar(c, cabecera, vehiculo, dias=-2).json()["datos"]
    assert realizar(c, cabecera, mantenimiento["id"]).status_code == 200

    r = realizar(c, cabecera, mantenimiento["id"])
    assert r.status_code == 409, r.text
    assert r.json()["codigo_error"] == "REGLA_M2"
    r = c.patch(f"{API}/mantenimientos/{mantenimiento['id']}/vencer",
                headers=cabecera, json={})
    assert r.status_code == 409, r.text


# ==========================================================================
# VENCER Y RF-16  (RN-M6, RN-M7)
# ==========================================================================
def test_no_se_vence_por_anticipado():
    """RN-M7."""
    c = cliente_http()
    cabecera = cab(c)
    vehiculo = crear_vehiculo(c, cabecera)
    mantenimiento = programar(c, cabecera, vehiculo, dias=15).json()["datos"]

    r = c.patch(f"{API}/mantenimientos/{mantenimiento['id']}/vencer",
                headers=cabecera, json={"motivo": "adelanto indebido"})
    assert r.status_code == 409, r.text
    assert r.json()["codigo_error"] == "REGLA_M7"


def test_vencer_saca_la_unidad_de_operacion():
    """RN-M6, primera mitad de RF-16."""
    c = cliente_http()
    cabecera = cab(c)
    vehiculo = crear_vehiculo(c, cabecera)
    mantenimiento = programar(c, cabecera, vehiculo, dias=-3).json()["datos"]

    r = c.patch(f"{API}/mantenimientos/{mantenimiento['id']}/vencer",
                headers=cabecera, json={"motivo": "taller saturado"})
    assert r.status_code == 200, r.text
    assert r.json()["datos"]["estatus"] == "VENCIDO"

    estado = c.get(f"{API}/vehiculos/{vehiculo['id']}",
                   headers=cabecera).json()["datos"]["estado_operativo"]
    assert estado == settings.ESTADO_EN_MANTENIMIENTO, estado


def test_realizar_un_vencido_devuelve_la_unidad_a_operacion():
    """RN-M6, segunda mitad."""
    c = cliente_http()
    cabecera = cab(c)
    vehiculo = crear_vehiculo(c, cabecera)
    mantenimiento = programar(c, cabecera, vehiculo, dias=-3).json()["datos"]
    assert c.patch(f"{API}/mantenimientos/{mantenimiento['id']}/vencer",
                   headers=cabecera, json={}).status_code == 200

    r = realizar(c, cabecera, mantenimiento["id"])
    assert r.status_code == 200, r.text
    datos = r.json()["datos"]
    assert datos["estatus"] == "REALIZADO"
    assert datos["vehiculo_liberado"] is True
    assert datos["vencidos_restantes"] == 0

    estado = c.get(f"{API}/vehiculos/{vehiculo['id']}",
                   headers=cabecera).json()["datos"]["estado_operativo"]
    assert estado == settings.ESTADO_DISPONIBLE, estado


def test_con_otro_vencido_la_unidad_no_vuelve_a_la_calle():
    """
    RN-M6: atender uno de dos vencidos no basta.

    RN-M3 impide programar dos servicios abiertos por la API, así que el
    segundo vencido se inserta directamente en la colección: es el estado
    que puede llegar del histórico o de la simulación, y la regla tiene
    que sostenerse igual.
    """
    from bson import ObjectId

    c = cliente_http()
    cabecera = cab(c)
    vehiculo = crear_vehiculo(c, cabecera)
    mantenimiento = programar(c, cabecera, vehiculo, dias=-3).json()["datos"]
    assert c.patch(f"{API}/mantenimientos/{mantenimiento['id']}/vencer",
                   headers=cabecera, json={}).status_code == 200

    bd = obtener_bd()
    otro = bd["mantenimientos"].insert_one({
        "folio_mantenimiento": f"MTO-{HOY:%Y%m%d}-9999",
        "vehiculo_id": ObjectId(vehiculo["id"]),
        "tipo": "CORRECTIVO", "estatus": settings.ESTATUS_MTTO_VENCIDO,
        "fecha_programada": datetime.now(timezone.utc) - timedelta(days=10),
        "activo": True, "origen_dato": "SIMULADO",
    }).inserted_id

    try:
        r = realizar(c, cabecera, mantenimiento["id"])
        assert r.status_code == 200, r.text
        datos = r.json()["datos"]
        assert datos["vehiculo_liberado"] is False, datos
        assert datos["vencidos_restantes"] == 1, datos

        estado = c.get(f"{API}/vehiculos/{vehiculo['id']}",
                       headers=cabecera).json()["datos"]["estado_operativo"]
        assert estado == settings.ESTADO_EN_MANTENIMIENTO, estado
        # Pero las fechas del vehículo sí se actualizaron: el servicio se hizo
        ficha = bd["vehiculos"].find_one({"_id": ObjectId(vehiculo["id"])})
        assert ficha["fecha_ultimo_mantenimiento"] is not None
    finally:
        bd["mantenimientos"].delete_one({"_id": otro})


def test_pendientes_separa_vencidos_atrasados_y_proximos():
    """RF-16."""
    c = cliente_http()
    cabecera = cab(c)

    vencido_v = crear_vehiculo(c, cabecera)
    atrasado_v = crear_vehiculo(c, cabecera)
    proximo_v = crear_vehiculo(c, cabecera)
    lejano_v = crear_vehiculo(c, cabecera)

    vencido = programar(c, cabecera, vencido_v, dias=-9).json()["datos"]
    assert c.patch(f"{API}/mantenimientos/{vencido['id']}/vencer",
                   headers=cabecera, json={}).status_code == 200
    atrasado = programar(c, cabecera, atrasado_v, dias=-2).json()["datos"]
    proximo = programar(c, cabecera, proximo_v, dias=3).json()["datos"]
    lejano = programar(c, cabecera, lejano_v, dias=200).json()["datos"]

    r = c.get(f"{API}/mantenimientos/pendientes", headers=cabecera,
              params={"dias": 7})
    assert r.status_code == 200, r.text
    datos = r.json()["datos"]

    folios = {g: {m["folio_mantenimiento"] for m in datos[g]}
              for g in ("vencidos", "atrasados", "proximos")}
    assert vencido["folio_mantenimiento"] in folios["vencidos"]
    assert atrasado["folio_mantenimiento"] in folios["atrasados"]
    assert proximo["folio_mantenimiento"] in folios["proximos"]
    # A 200 días no entra en el aviso de 7
    for grupo in folios.values():
        assert lejano["folio_mantenimiento"] not in grupo

    # Cada fila trae el vehículo identificado, no solo su id
    fila = next(m for m in datos["vencidos"]
                if m["folio_mantenimiento"] == vencido["folio_mantenimiento"])
    assert fila["codigo_vehiculo"] == vencido_v["codigo_vehiculo"]
    assert fila["estado_operativo"] == settings.ESTADO_EN_MANTENIMIENTO
    assert fila["dias"] >= 9, fila
    assert "vencido" in r.json()["mensaje"].lower()


# ==========================================================================
# CONSULTA, PERMISOS Y CONTRATO
# ==========================================================================
def test_listado_y_filtros():
    c = cliente_http()
    cabecera = cab(c)
    vehiculo = crear_vehiculo(c, cabecera)
    programar(c, cabecera, vehiculo, dias=-6, tipo="CORRECTIVO")

    r = c.get(f"{API}/mantenimientos", headers=cabecera,
              params={"vehiculo_id": vehiculo["id"], "tipo": "CORRECTIVO"})
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["total"] == 1, cuerpo
    assert cuerpo["datos"][0]["tipo"] == "CORRECTIVO"

    # Filtro que no corresponde
    r = c.get(f"{API}/mantenimientos", headers=cabecera,
              params={"vehiculo_id": vehiculo["id"], "tipo": "PREVENTIVO"})
    assert r.json()["total"] == 0

    # Rango de fechas
    r = c.get(f"{API}/mantenimientos", headers=cabecera, params={
        "vehiculo_id": vehiculo["id"],
        "fecha_desde": str(HOY - timedelta(days=7)),
        "fecha_hasta": str(HOY)})
    assert r.json()["total"] == 1

    # Catálogo inválido
    r = c.get(f"{API}/mantenimientos", headers=cabecera,
              params={"estatus": "INVENTADO"})
    assert r.status_code == 409, r.text


def test_resumen_y_catalogos():
    c = cliente_http()
    cabecera = cab(c)

    r = c.get(f"{API}/mantenimientos/catalogos", headers=cabecera)
    assert r.status_code == 200, r.text
    datos = r.json()["datos"]
    assert set(datos["tipos"]) == set(settings.CATALOGO_TIPO_MANTENIMIENTO)
    assert datos["transiciones"]["REALIZADO"] == []
    assert "REALIZADO" in datos["transiciones"]["VENCIDO"]
    assert datos["periodicidad_dias"] == settings.DIAS_PERIODICIDAD_MANTENIMIENTO

    r = c.get(f"{API}/mantenimientos/resumen", headers=cabecera)
    assert r.status_code == 200, r.text
    datos = r.json()["datos"]
    assert datos["total"] >= 120, datos["total"]
    assert set(datos["por_tipo"]) == set(settings.CATALOGO_TIPO_MANTENIMIENTO)
    assert sum(datos["por_estatus"].values()) <= datos["total"]
    if datos["costo_por_vehiculo"]:
        primero = datos["costo_por_vehiculo"][0]
        assert {"codigo_vehiculo", "servicios", "costo"} <= set(primero)


def test_permisos_por_rol():
    """Consultar, cualquiera; programar, solo ADMINISTRADOR."""
    c = cliente_http()
    cabecera = cab(c)
    vehiculo = crear_vehiculo(c, cabecera)

    analista = cab(c, "analista")
    assert c.get(f"{API}/mantenimientos/pendientes",
                 headers=analista).status_code == 200
    r = programar(c, analista, vehiculo)
    assert r.status_code == 403, r.text

    # El despachador no programa, pero sí registra lo que pasa por el taller
    despachador = cab(c, "despachador")
    assert programar(c, despachador, vehiculo).status_code == 403
    mantenimiento = programar(c, cabecera, vehiculo, dias=-2).json()["datos"]
    assert realizar(c, despachador, mantenimiento["id"]).status_code == 200


def test_sin_sesion_no_se_consulta():
    c = cliente_http()
    assert c.get(f"{API}/mantenimientos").status_code == 401


def test_inexistente_da_404():
    c = cliente_http()
    cabecera = cab(c)
    r = c.get(f"{API}/mantenimientos/{'0' * 24}", headers=cabecera)
    assert r.status_code == 404, r.text
    assert r.json()["exito"] is False


if __name__ == "__main__":
    pruebas = [
        ("El folio lo genera el sistema (RN-M1)",
         test_programar_genera_folio_del_sistema),
        ("Una unidad, un servicio abierto (RN-M3)",
         test_una_unidad_no_tiene_dos_servicios_abiertos),
        ("Vehículo inexistente", test_vehiculo_inexistente_se_rechaza),
        ("Tipo fuera del catálogo (RNP-05)",
         test_tipo_fuera_del_catalogo_se_rechaza),
        ("Los campos calculados no se editan (RN-M4)",
         test_los_campos_calculados_no_se_editan),
        ("Un servicio realizado no se edita (RN-M2)",
         test_un_servicio_realizado_no_se_edita),
        ("Editar la fecha programada", test_editar_la_fecha_programada_funciona),
        ("Realizar calcula duración y próxima fecha (RN-M4)",
         test_realizar_calcula_duracion_y_proxima_fecha),
        ("Realizar actualiza las fechas del vehículo (RN-M5 / RN-V6)",
         test_realizar_actualiza_las_fechas_del_vehiculo),
        ("No se realiza antes de la fecha programada",
         test_no_se_realiza_antes_de_la_fecha_programada),
        ("De REALIZADO no se sale (RN-M2)",
         test_un_servicio_realizado_no_se_realiza_dos_veces),
        ("No se vence por anticipado (RN-M7)", test_no_se_vence_por_anticipado),
        ("Vencer saca la unidad de operación (RN-M6)",
         test_vencer_saca_la_unidad_de_operacion),
        ("Realizar un vencido devuelve la unidad (RN-M6)",
         test_realizar_un_vencido_devuelve_la_unidad_a_operacion),
        ("Con otro vencido la unidad no vuelve (RN-M6)",
         test_con_otro_vencido_la_unidad_no_vuelve_a_la_calle),
        ("Pendientes separa vencidos, atrasados y próximos (RF-16)",
         test_pendientes_separa_vencidos_atrasados_y_proximos),
        ("Listado y filtros", test_listado_y_filtros),
        ("Resumen y catálogos", test_resumen_y_catalogos),
        ("Permisos por rol", test_permisos_por_rol),
        ("Sin sesión no se consulta", test_sin_sesion_no_se_consulta),
        ("Inexistente da 404", test_inexistente_da_404),
    ]

    print("=" * 70)
    print("  SIG-LOG — Pruebas del módulo Mantenimientos")
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
    print(f"  Escenario eliminado: {limpiar()}")
    print("=" * 70)
    print(f"  Resultado: {len(pruebas) - fallos}/{len(pruebas)} pruebas correctas")
    print("=" * 70)
    sys.exit(1 if fallos else 0)
