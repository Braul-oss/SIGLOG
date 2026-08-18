"""
SIG-LOG — Sistema Integral de Gestión Logística
tests/test_combustible.py

PRUEBAS DEL MÓDULO COMBUSTIBLE

    RN-F1  el folio CMB-AAAAMMDD-NNNN lo genera el sistema
    RN-F2  costo_total = litros × precio_por_litro
    RN-F3  el tramo sale del odómetro de la carga anterior; en la primera
           carga queda null, no cero
    RN-F4  rendimiento_km_l = km del tramo / litros
    RN-F5  el odómetro no baja respecto de la carga anterior
    RN-F6  los litros no superan la capacidad del tanque
    RN-F7  el combustible debe ser el de la unidad
    RN-F8  la carga actualiza el odómetro del vehículo

Las cargas de prueba se identifican por su estación y se borran junto con
los vehículos que las generaron.
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
PLACA = "ZZC"
ESTACION = "ZZ-PRUEBA Estación"


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
        "cargas": (bd["combustible"].delete_many(
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


def crear_vehiculo(c, cabecera, *, odometro: float = 100_000,
                   tanque: float = 120, combustible: str = "DIESEL") -> dict:
    r = c.post(f"{API}/vehiculos", headers=cabecera, json={
        "placa": f"{PLACA}-{random.randint(1000, 9999)}", "marca": "Prueba",
        "modelo": "Combustible", "anio": 2023, "tipo_vehiculo": "MEDIANO",
        "tipo_combustible": combustible, "capacidad_tanque_litros": tanque,
        "rendimiento_nominal_km_l": 7.0, "odometro_actual_km": odometro})
    assert r.status_code == 201, r.text
    return r.json()["datos"]


def cargar(c, cabecera, vehiculo, *, litros: float = 80.0,
           precio: float = 24.0, odometro: float = 100_500,
           fecha: datetime | None = None, **extra):
    cuerpo = {"vehiculo_id": vehiculo["id"], "litros": litros,
              "precio_por_litro": precio, "odometro_km": odometro,
              "estacion": ESTACION, **extra}
    if fecha:
        cuerpo["fecha"] = fecha.isoformat()
    return c.post(f"{API}/combustible", headers=cabecera, json=cuerpo)


# ==========================================================================
# PERMISOS
# ==========================================================================
def test_sin_sesion_no_se_consulta():
    with cliente_http() as c:
        assert c.get(f"{API}/combustible").status_code == 401


def test_el_analista_no_registra():
    with cliente_http() as c:
        cabecera = cab(c)
        v = crear_vehiculo(c, cabecera)
        r = cargar(c, cab(c, "analista"), v)
    assert r.status_code == 403


def test_el_despachador_si_registra():
    """El §3 le asigna al despachador las cargas de combustible."""
    with cliente_http() as c:
        cabecera = cab(c)
        v = crear_vehiculo(c, cabecera)
        r = cargar(c, cab(c, "despachador"), v)
    assert r.status_code == 201, r.text


# ==========================================================================
# REGISTRO Y CÁLCULOS  (RN-F1 a RN-F4)
# ==========================================================================
def test_la_primera_carga_no_tiene_rendimiento():
    """
    RN-F3: sin carga previa no hay tramo que medir. Poner cero fingiría un
    recorrido de cero kilómetros que hundiría el rendimiento promedio.
    """
    with cliente_http() as c:
        cabecera = cab(c)
        v = crear_vehiculo(c, cabecera, odometro=100_000)
        datos = cargar(c, cabecera, v, litros=80, precio=24.0,
                       odometro=100_050).json()["datos"]

    assert datos["folio_carga"].startswith("CMB-")
    assert datos["costo_total"] == 1920.0, "80 × 24.00 (RN-F2)"
    assert datos["km_recorridos_desde_carga_anterior"] is None
    assert datos["rendimiento_km_l"] is None, (
        "la primera carga no tiene tramo previo: debe ser null, no cero")


def test_la_segunda_carga_calcula_el_rendimiento():
    """RN-F3 y RN-F4."""
    with cliente_http() as c:
        cabecera = cab(c)
        v = crear_vehiculo(c, cabecera, odometro=100_000)
        ayer = datetime.now(timezone.utc) - timedelta(days=1)

        cargar(c, cabecera, v, litros=80, odometro=100_000, fecha=ayer)
        datos = cargar(c, cabecera, v, litros=50, precio=24.0,
                       odometro=100_350).json()["datos"]

    assert datos["km_recorridos_desde_carga_anterior"] == 350.0
    assert datos["rendimiento_km_l"] == 7.0, "350 km / 50 L (RN-F4)"
    assert datos["costo_total"] == 1200.0


def test_el_costo_se_calcula_no_se_captura():
    """RN-F2: el total sale de sus propias cifras."""
    with cliente_http() as c:
        cabecera = cab(c)
        v = crear_vehiculo(c, cabecera)
        datos = cargar(c, cabecera, v, litros=33.33,
                       precio=23.75).json()["datos"]
    assert datos["costo_total"] == round(33.33 * 23.75, 2)


def test_el_tipo_se_hereda_del_vehiculo():
    with cliente_http() as c:
        cabecera = cab(c)
        v = crear_vehiculo(c, cabecera, combustible="GASOLINA")
        datos = cargar(c, cabecera, v).json()["datos"]
    assert datos["tipo_combustible"] == "GASOLINA"


# ==========================================================================
# VALIDACIONES  (RN-F5 a RN-F7)
# ==========================================================================
def test_no_se_le_pone_gasolina_a_un_diesel():
    """RN-F7, la regla más concreta del módulo."""
    with cliente_http() as c:
        cabecera = cab(c)
        v = crear_vehiculo(c, cabecera, combustible="DIESEL")
        r = cargar(c, cabecera, v, tipo_combustible="GASOLINA")
    assert r.status_code == 409, r.text
    cuerpo = r.json()
    assert cuerpo["codigo_error"] == "REGLA_F7"
    assert cuerpo["detalles"][0]["combustible_del_vehiculo"] == "DIESEL"
    assert cuerpo["detalles"][0]["combustible_de_la_carga"] == "GASOLINA"


def test_no_caben_mas_litros_que_el_tanque():
    """RN-F6."""
    with cliente_http() as c:
        cabecera = cab(c)
        v = crear_vehiculo(c, cabecera, tanque=100)
        r = cargar(c, cabecera, v, litros=150)
    assert r.status_code == 409, r.text
    cuerpo = r.json()
    assert cuerpo["codigo_error"] == "REGLA_F6"
    assert cuerpo["detalles"][0]["capacidad_tanque_litros"] == 100


def test_el_odometro_no_baja():
    """RN-F5: una lectura mal tecleada daría un rendimiento absurdo."""
    with cliente_http() as c:
        cabecera = cab(c)
        v = crear_vehiculo(c, cabecera, odometro=100_000)
        ayer = datetime.now(timezone.utc) - timedelta(days=1)
        cargar(c, cabecera, v, odometro=100_400, fecha=ayer)

        r = cargar(c, cabecera, v, odometro=100_100)
    assert r.status_code == 409, r.text
    cuerpo = r.json()
    assert cuerpo["codigo_error"] == "REGLA_F5"
    assert cuerpo["detalles"][0]["odometro_carga_anterior"] == 100_400


def test_una_carga_intermedia_incoherente_se_rechaza():
    """
    Registrar una carga con fecha anterior pero odómetro mayor dejaría el
    tramo de la siguiente en negativo.
    """
    with cliente_http() as c:
        cabecera = cab(c)
        v = crear_vehiculo(c, cabecera, odometro=100_000)
        ahora = datetime.now(timezone.utc)
        cargar(c, cabecera, v, odometro=100_500, fecha=ahora)

        # Fecha anterior, pero odómetro mayor que la posterior
        r = cargar(c, cabecera, v, odometro=100_900,
                   fecha=ahora - timedelta(hours=5))
    assert r.status_code == 409, r.text
    assert r.json()["codigo_error"] == "REGLA_F5"
    assert "posterior" in r.json()["mensaje"]


def test_vehiculo_inexistente():
    with cliente_http() as c:
        r = c.post(f"{API}/combustible", headers=cab(c), json={
            "vehiculo_id": "6a83893489a0d3691e05ffff", "litros": 50,
            "precio_por_litro": 24.0, "odometro_km": 1000})
    assert r.status_code == 409
    assert "No existe el vehículo" in r.json()["mensaje"]


def test_litros_negativos_se_rechazan():
    with cliente_http() as c:
        cabecera = cab(c)
        v = crear_vehiculo(c, cabecera)
        r = cargar(c, cabecera, v, litros=-10)
    assert r.status_code == 422


# ==========================================================================
# EFECTO SOBRE EL VEHÍCULO  (RN-F8)
# ==========================================================================
def test_la_carga_actualiza_el_odometro_del_vehiculo():
    """
    RN-F8. El §11.2 dice que `odometro_actual_km` se actualiza con cada
    carga o viaje; el cierre del viaje ya cumplía la mitad y esta es la
    otra.
    """
    with cliente_http() as c:
        cabecera = cab(c)
        v = crear_vehiculo(c, cabecera, odometro=100_000)
        cargar(c, cabecera, v, odometro=100_780)

        actual = c.get(f"{API}/vehiculos/{v['id']}",
                       headers=cabecera).json()["datos"]
    assert actual["odometro_actual_km"] == 100_780


def test_una_carga_antigua_no_retrasa_el_odometro():
    """Registrar una carga vieja no debe hacer retroceder el kilometraje."""
    with cliente_http() as c:
        cabecera = cab(c)
        v = crear_vehiculo(c, cabecera, odometro=100_000)
        cargar(c, cabecera, v, odometro=100_900)

        # Carga anterior en el tiempo y con odómetro menor: es coherente
        antigua = datetime.now(timezone.utc) - timedelta(days=3)
        r = cargar(c, cabecera, v, odometro=100_200, fecha=antigua)
        assert r.status_code == 201, r.text

        actual = c.get(f"{API}/vehiculos/{v['id']}",
                       headers=cabecera).json()["datos"]
    assert actual["odometro_actual_km"] == 100_900, (
        "el odómetro del vehículo no debe retroceder")


# ==========================================================================
# INMUTABILIDAD  (§11.8)
# ==========================================================================
def test_no_hay_edicion_ni_borrado():
    """Cada carga es un hecho inmutable (§11.8)."""
    with cliente_http() as c:
        cabecera = cab(c)
        v = crear_vehiculo(c, cabecera)
        carga = cargar(c, cabecera, v).json()["datos"]
        assert c.put(f"{API}/combustible/{carga['id']}", headers=cabecera,
                     json={"litros": 1}).status_code == 405
        assert c.delete(f"{API}/combustible/{carga['id']}",
                        headers=cabecera).status_code == 405


# ==========================================================================
# CONSULTA Y RESUMEN  (§12.3)
# ==========================================================================
def test_listado_y_filtros():
    with cliente_http() as c:
        cabecera = cab(c)
        cuerpo = c.get(f"{API}/combustible?tamano=5", headers=cabecera).json()
        assert cuerpo["total"] >= 1_379, "deberían estar las del seed"

        v = crear_vehiculo(c, cabecera)
        cargar(c, cabecera, v)
        propio = c.get(f"{API}/combustible?vehiculo_id={v['id']}",
                       headers=cabecera).json()
    assert propio["total"] == 1


def test_resumen_responde_las_preguntas_del_caso():
    """
    §12.3: consumo y costo agregado. Responde qué vehículos generan
    mayores costos y cuáles consumen más.
    """
    with cliente_http() as c:
        cuerpo = c.get(f"{API}/combustible/resumen?top=5", headers=cab(c)).json()
    datos = cuerpo["datos"]
    assert datos["cargas"] >= 1_379
    assert datos["litros_totales"] > 0
    assert datos["costo_total"] > 0
    assert datos["rendimiento_flotilla_km_l"] > 0
    assert datos["costo_por_km"] > 0
    assert len(datos["por_vehiculo"]) == 5
    # Ordenado por costo descendente
    costos = [v["costo"] for v in datos["por_vehiculo"]]
    assert costos == sorted(costos, reverse=True)
    assert all(v["codigo_vehiculo"] for v in datos["por_vehiculo"])
    assert datos["por_estacion"]
    assert "km/l" in cuerpo["mensaje"]


def test_catalogos():
    with cliente_http() as c:
        datos = c.get(f"{API}/combustible/catalogos",
                      headers=cab(c)).json()["datos"]
    assert set(datos["tipos_combustible"]) == set(
        settings.CATALOGO_TIPO_COMBUSTIBLE)
    assert len(datos["estaciones"]) >= 1
    assert "no se capturan" in datos["nota_calculados"]


def test_inexistente_da_404():
    with cliente_http() as c:
        r = c.get(f"{API}/combustible/6a83893489a0d3691e05ffff",
                  headers=cab(c))
    assert r.status_code == 404


# ==========================================================================
# Modo manual (sin pytest)
# ==========================================================================
if __name__ == "__main__":
    pruebas = [
        ("Sin sesión no se consulta", test_sin_sesion_no_se_consulta),
        ("El analista no registra", test_el_analista_no_registra),
        ("El despachador sí registra", test_el_despachador_si_registra),
        ("La primera carga no tiene rendimiento (RN-F3)",
         test_la_primera_carga_no_tiene_rendimiento),
        ("La segunda carga calcula el rendimiento (RN-F4)",
         test_la_segunda_carga_calcula_el_rendimiento),
        ("El costo se calcula, no se captura (RN-F2)",
         test_el_costo_se_calcula_no_se_captura),
        ("El tipo se hereda del vehículo", test_el_tipo_se_hereda_del_vehiculo),
        ("No se le pone gasolina a un diésel (RN-F7)",
         test_no_se_le_pone_gasolina_a_un_diesel),
        ("No caben más litros que el tanque (RN-F6)",
         test_no_caben_mas_litros_que_el_tanque),
        ("El odómetro no baja (RN-F5)", test_el_odometro_no_baja),
        ("Una carga intermedia incoherente se rechaza",
         test_una_carga_intermedia_incoherente_se_rechaza),
        ("Vehículo inexistente", test_vehiculo_inexistente),
        ("Litros negativos se rechazan", test_litros_negativos_se_rechazan),
        ("La carga actualiza el odómetro del vehículo (RN-F8)",
         test_la_carga_actualiza_el_odometro_del_vehiculo),
        ("Una carga antigua no retrasa el odómetro",
         test_una_carga_antigua_no_retrasa_el_odometro),
        ("No hay edición ni borrado (§11.8)", test_no_hay_edicion_ni_borrado),
        ("Listado y filtros", test_listado_y_filtros),
        ("El resumen responde las preguntas del caso (§12.3)",
         test_resumen_responde_las_preguntas_del_caso),
        ("Catálogos", test_catalogos),
        ("Inexistente da 404", test_inexistente_da_404),
    ]

    print("=" * 70)
    print("  SIG-LOG — Pruebas del módulo Combustible")
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
