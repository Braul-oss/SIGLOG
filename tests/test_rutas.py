"""
SIG-LOG — Sistema Integral de Gestión Logística
tests/test_rutas.py

PRUEBAS DEL MÓDULO RUTAS

Además del CRUD:

    RN-R1  el código RUT-NNN lo genera el sistema y es inmutable
    RN-R2  los totales se recalculan a partir de las paradas, no se capturan
    RN-R3  paradas numeradas 1..N sin huecos, y al menos una
    RN-R4  el cliente de la parada existe, está activo y tiene esa dirección
    RN-R5  un cliente no se repite dentro de la misma ruta
    RN-R6  no se da de baja una ruta con vehículo o con viajes sin cerrar

Y lo que más importa de este módulo: que `PUT /rutas/{id}/asignar-vehiculo`
y `PATCH /vehiculos/{id}/ruta` sean **la misma regla**, no dos que puedan
discrepar.

Las rutas de prueba se distinguen por un nombre con prefijo ZZ-PRUEBA.
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
MARCA = "ZZ-PRUEBA"

ORIGEN = {"nombre": "Centro de Distribución SIG-LOG",
          "calle": "Vialidad Adolfo López Mateos", "numero": "1200",
          "colonia": "Parque Industrial", "municipio": "Toluca",
          "estado": "México", "cp": "50200"}


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
    return obtener_bd()["rutas"].delete_many(
        {"nombre": {"$regex": f"^{MARCA}"}}).deleted_count


try:
    import pytest

    @pytest.fixture(scope="module", autouse=True)
    def _limpiar_al_terminar():
        yield
        limpiar()
except ImportError:                    # pragma: no cover
    pass


def clientes_de_prueba(n: int = 3) -> list[dict]:
    """Clientes reales del seed, con el alias de su dirección principal."""
    bd = obtener_bd()
    salida = []
    for doc in bd["clientes"].find({"activo": {"$ne": False}}).limit(n):
        principal = next((d for d in doc["direcciones"] if d.get("principal")),
                         doc["direcciones"][0])
        salida.append({"id": str(doc["_id"]), "alias": principal["alias"],
                       "codigo": doc["codigo_cliente"]})
    return salida


def parada(cliente: dict, km: float = 10.0, minutos: float = 30.0) -> dict:
    return {"cliente_id": cliente["id"], "direccion_alias": cliente["alias"],
            "distancia_desde_anterior_km": km, "tiempo_estimado_min": minutos}


def alta(c, cabecera, sufijo: str = "", n_paradas: int = 2, **extra) -> dict:
    clientes = clientes_de_prueba(n_paradas)
    cuerpo = {
        "nombre": f"{MARCA} Ruta {sufijo or 'X'}",
        "zona": "NORTE", "origen": ORIGEN,
        "paradas": [parada(cl, 10.0 * (i + 1), 30.0)
                    for i, cl in enumerate(clientes)],
        "dias_operacion": ["LUNES", "MIERCOLES"],
        "hora_salida_programada": "06:30",
        **extra,
    }
    r = c.post(f"{API}/rutas", headers=cabecera, json=cuerpo)
    assert r.status_code == 201, r.text
    return r.json()["datos"]


# ==========================================================================
# PERMISOS
# ==========================================================================
def test_sin_sesion_no_se_consulta():
    with cliente_http() as c:
        assert c.get(f"{API}/rutas").status_code == 401


def test_cualquier_sesion_consulta():
    with cliente_http() as c:
        for u in ("admin", "despachador", "analista"):
            assert c.get(f"{API}/rutas", headers=cab(c, u)).status_code == 200


def test_solo_admin_modifica():
    """Cambiar el trazado de una ruta es rediseño, no operación diaria."""
    with cliente_http() as c:
        clientes = clientes_de_prueba(1)
        cuerpo = {"nombre": f"{MARCA} Intrusa", "zona": "SUR",
                  "origen": ORIGEN, "paradas": [parada(clientes[0])],
                  "dias_operacion": ["LUNES"],
                  "hora_salida_programada": "07:00"}
        for u in ("despachador", "analista"):
            r = c.post(f"{API}/rutas", headers=cab(c, u), json=cuerpo)
            assert r.status_code == 403, f"{u}: {r.status_code}"


# ==========================================================================
# CONSULTA
# ==========================================================================
def test_listado_y_filtros():
    with cliente_http() as c:
        cabecera = cab(c)
        cuerpo = c.get(f"{API}/rutas?tamano=5", headers=cabecera).json()
        assert cuerpo["total"] >= 20, "deberían estar las 20 del seed"
        codigos = [r["codigo_ruta"] for r in cuerpo["datos"]]
        assert codigos == sorted(codigos)

        norte = c.get(f"{API}/rutas?zona=NORTE", headers=cabecera).json()
    assert all(r["zona"] == "NORTE" for r in norte["datos"])


def test_filtro_sin_vehiculo():
    with cliente_http() as c:
        cabecera = cab(c)
        alta(c, cabecera, "sinveh")           # nace sin vehículo
        sin = c.get(f"{API}/rutas?sin_vehiculo=true", headers=cabecera).json()
        con = c.get(f"{API}/rutas?sin_vehiculo=false", headers=cabecera).json()
    assert all(r["vehiculo_asignado_id"] is None for r in sin["datos"])
    assert all(r["vehiculo_asignado_id"] is not None for r in con["datos"])
    assert con["total"] >= 20, "las 20 del seed tienen vehículo"


def test_zona_invalida():
    with cliente_http() as c:
        r = c.get(f"{API}/rutas?zona=CENTRO", headers=cab(c))
    assert r.status_code == 409
    assert r.json()["codigo_error"] == "REGLA_DE_NEGOCIO"


def test_resumen_y_catalogos():
    with cliente_http() as c:
        cabecera = cab(c)
        resumen = c.get(f"{API}/rutas/resumen", headers=cabecera).json()["datos"]
        catalogos = c.get(f"{API}/rutas/catalogos",
                          headers=cabecera).json()["datos"]
    assert resumen["total"] == resumen["activas"] + resumen["inactivas"]
    assert sum(resumen["por_zona"].values()) >= 20
    assert set(catalogos["zonas"]) == set(settings.CATALOGO_ZONA)
    assert "RN-R2" in catalogos["nota_totales"]


# ==========================================================================
# ANÁLISIS — lee del ETL y del clustering
# ==========================================================================
def test_analisis_lee_del_dw_y_del_clustering():
    with cliente_http() as c:
        cabecera = cab(c)
        ruta = c.get(f"{API}/rutas?tamano=1", headers=cabecera).json()["datos"][0]
        datos = c.get(f"{API}/rutas/{ruta['id']}/analisis",
                      headers=cabecera).json()["datos"]

    bd = obtener_bd()
    dimension = bd["dim_ruta"].find_one({"_id": ruta["id"]})
    cluster = bd["clusters_rutas"].find_one({"_id": ruta["id"]})
    assert dimension is not None and cluster is not None

    assert (datos["perfil_operativo"]["retraso_medio_min"]
            == dimension["retraso_medio_min"]), (
        "la cifra debe COINCIDIR con la del DW")
    assert datos["grupo"]["nombre_grupo"] == cluster["nombre_grupo"]
    assert datos["recomendacion"] == cluster["recomendacion"]
    assert len(datos["lectura"]) > 60


def test_analisis_de_una_ruta_nueva():
    with cliente_http() as c:
        cabecera = cab(c)
        nueva = alta(c, cabecera, "analisis")
        datos = c.get(f"{API}/rutas/{nueva['id']}/analisis",
                      headers=cabecera).json()["datos"]
    assert datos["perfil_operativo"] == {}
    assert "no disponible" in datos["origen"]
    assert "Todavía no hay" in datos["lectura"]


# ==========================================================================
# ALTA  (RN-R1, RN-R2, RN-R3)
# ==========================================================================
def test_alta_calcula_los_totales():
    """RN-R2: los totales salen de las paradas, no se envían."""
    with cliente_http() as c:
        r = alta(c, cab(c), "totales", n_paradas=3)
    assert r["codigo_ruta"].startswith("RUT-")
    assert r["numero_paradas"] == 3
    assert r["distancia_total_km"] == 60.0        # 10 + 20 + 30
    assert r["tiempo_estimado_total_min"] == 90.0  # 30 × 3
    assert r["velocidad_efectiva_kmh"] == 40.0     # 60 km / 1.5 h
    assert r["vehiculo_asignado_id"] is None
    assert r["origen_dato"] == "REAL"


def test_las_paradas_se_numeran_solas():
    """RN-R3: el orden lo pone el sistema por la posición en la lista."""
    with cliente_http() as c:
        r = alta(c, cab(c), "orden", n_paradas=3)
    assert [p["orden"] for p in r["paradas"]] == [1, 2, 3]


def test_dias_de_operacion_se_ordenan():
    with cliente_http() as c:
        r = alta(c, cab(c), "dias",
                 dias_operacion=["VIERNES", "LUNES", "MIERCOLES"])
    assert r["dias_operacion"] == ["LUNES", "MIERCOLES", "VIERNES"]


def test_dia_invalido_se_rechaza():
    with cliente_http() as c:
        clientes = clientes_de_prueba(1)
        r = c.post(f"{API}/rutas", headers=cab(c),
                   json={"nombre": f"{MARCA} DiaMalo", "zona": "SUR",
                         "origen": ORIGEN, "paradas": [parada(clientes[0])],
                         "dias_operacion": ["LUNEZ"],
                         "hora_salida_programada": "06:00"})
    assert r.status_code == 422


def test_hora_invalida_se_rechaza():
    with cliente_http() as c:
        clientes = clientes_de_prueba(1)
        r = c.post(f"{API}/rutas", headers=cab(c),
                   json={"nombre": f"{MARCA} HoraMala", "zona": "SUR",
                         "origen": ORIGEN, "paradas": [parada(clientes[0])],
                         "dias_operacion": ["LUNES"],
                         "hora_salida_programada": "25:99"})
    assert r.status_code == 422


def test_sin_paradas_se_rechaza():
    with cliente_http() as c:
        r = c.post(f"{API}/rutas", headers=cab(c),
                   json={"nombre": f"{MARCA} Vacia", "zona": "SUR",
                         "origen": ORIGEN, "paradas": [],
                         "dias_operacion": ["LUNES"],
                         "hora_salida_programada": "06:00"})
    assert r.status_code == 422


# ==========================================================================
# VALIDACIÓN DE PARADAS  (RN-R4, RN-R5)
# ==========================================================================
def test_cliente_inexistente_en_la_parada():
    with cliente_http() as c:
        clientes = clientes_de_prueba(1)
        mala = parada(clientes[0])
        mala["cliente_id"] = "6a83893489a0d3691e05ffff"
        r = c.post(f"{API}/rutas", headers=cab(c),
                   json={"nombre": f"{MARCA} ClienteMalo", "zona": "SUR",
                         "origen": ORIGEN, "paradas": [mala],
                         "dias_operacion": ["LUNES"],
                         "hora_salida_programada": "06:00"})
    assert r.status_code == 409, r.text
    assert r.json()["codigo_error"] == "REGLA_R4"


def test_alias_de_direccion_inexistente():
    """RN-R4: una parada a una dirección que el cliente no tiene."""
    with cliente_http() as c:
        clientes = clientes_de_prueba(1)
        mala = parada(clientes[0])
        mala["direccion_alias"] = "Bodega Que No Existe"
        r = c.post(f"{API}/rutas", headers=cab(c),
                   json={"nombre": f"{MARCA} AliasMalo", "zona": "SUR",
                         "origen": ORIGEN, "paradas": [mala],
                         "dias_operacion": ["LUNES"],
                         "hora_salida_programada": "06:00"})
    assert r.status_code == 409, r.text
    cuerpo = r.json()
    assert cuerpo["codigo_error"] == "REGLA_R4"
    assert cuerpo["detalles"][0]["alias_disponibles"]


def test_cliente_repetido_en_la_ruta():
    """RN-R5."""
    with cliente_http() as c:
        clientes = clientes_de_prueba(1)
        r = c.post(f"{API}/rutas", headers=cab(c),
                   json={"nombre": f"{MARCA} Repetido", "zona": "SUR",
                         "origen": ORIGEN,
                         "paradas": [parada(clientes[0]), parada(clientes[0])],
                         "dias_operacion": ["LUNES"],
                         "hora_salida_programada": "06:00"})
    assert r.status_code == 409, r.text
    assert r.json()["codigo_error"] == "REGLA_R5"


# ==========================================================================
# EDICIÓN DE PARADAS
# ==========================================================================
def test_agregar_parada_recalcula():
    with cliente_http() as c:
        cabecera = cab(c)
        ruta = alta(c, cabecera, "agregar", n_paradas=2)
        antes = ruta["distancia_total_km"]

        tercero = clientes_de_prueba(3)[2]
        r = c.post(f"{API}/rutas/{ruta['id']}/paradas", headers=cabecera,
                   json=parada(tercero, 15.0, 20.0))
    assert r.status_code == 200, r.text
    datos = r.json()["datos"]
    assert datos["numero_paradas"] == 3
    assert datos["distancia_total_km"] == round(antes + 15.0, 1)
    assert [p["orden"] for p in datos["paradas"]] == [1, 2, 3]


def test_quitar_parada_renumera():
    """RN-R3: al quitar la primera, la segunda pasa a ser la 1."""
    with cliente_http() as c:
        cabecera = cab(c)
        ruta = alta(c, cabecera, "quitar", n_paradas=3)
        segundo_cliente = ruta["paradas"][1]["cliente_id"]

        r = c.delete(f"{API}/rutas/{ruta['id']}/paradas/1", headers=cabecera)
    assert r.status_code == 200, r.text
    datos = r.json()["datos"]
    assert datos["numero_paradas"] == 2
    assert [p["orden"] for p in datos["paradas"]] == [1, 2]
    assert datos["paradas"][0]["cliente_id"] == segundo_cliente


def test_no_se_quita_la_ultima_parada():
    with cliente_http() as c:
        cabecera = cab(c)
        ruta = alta(c, cabecera, "ultima", n_paradas=1)
        r = c.delete(f"{API}/rutas/{ruta['id']}/paradas/1", headers=cabecera)
    assert r.status_code == 409
    assert r.json()["codigo_error"] == "REGLA_R3"


def test_quitar_parada_inexistente():
    with cliente_http() as c:
        cabecera = cab(c)
        ruta = alta(c, cabecera, "noexiste", n_paradas=2)
        r = c.delete(f"{API}/rutas/{ruta['id']}/paradas/9", headers=cabecera)
    assert r.status_code == 409
    assert "orden 9" in r.json()["mensaje"]


def test_reemplazar_itinerario():
    with cliente_http() as c:
        cabecera = cab(c)
        ruta = alta(c, cabecera, "reemplazo", n_paradas=3)
        clientes = clientes_de_prueba(2)
        r = c.put(f"{API}/rutas/{ruta['id']}/paradas", headers=cabecera,
                  json={"paradas": [parada(clientes[1], 5.0, 15.0),
                                    parada(clientes[0], 7.0, 21.0)]})
    assert r.status_code == 200, r.text
    datos = r.json()["datos"]
    assert datos["numero_paradas"] == 2
    assert datos["distancia_total_km"] == 12.0
    assert datos["tiempo_estimado_total_min"] == 36.0
    assert datos["paradas"][0]["cliente_id"] == clientes[1]["id"]


def test_no_se_editan_los_totales_ni_las_paradas_por_el_put():
    """RN-R2: el PUT de cabecera no toca paradas ni totales."""
    from backend.services import rutas as servicio
    from backend.utils.errores import ReglaDeNegocio

    bd = obtener_bd()
    doc = bd["rutas"].find_one({})
    for campo, valor in (("distancia_total_km", 1),
                         ("numero_paradas", 99),
                         ("paradas", []),
                         ("vehiculo_asignado_id", None)):
        try:
            servicio.actualizar(bd, str(doc["_id"]), {campo: valor})
            raise AssertionError(f"RN-R2 debió rechazar {campo}")
        except ReglaDeNegocio as exc:
            assert exc.codigo_error == "REGLA_R2", campo


def test_actualizar_cabecera():
    with cliente_http() as c:
        cabecera = cab(c)
        ruta = alta(c, cabecera, "cabecera")
        r = c.put(f"{API}/rutas/{ruta['id']}", headers=cabecera,
                  json={"nombre": f"{MARCA} Renombrada", "zona": "SUR"})
    assert r.status_code == 200, r.text
    datos = r.json()["datos"]
    assert datos["zona"] == "SUR"
    assert datos["codigo_ruta"] == ruta["codigo_ruta"]
    assert datos["numero_paradas"] == ruta["numero_paradas"]


# ==========================================================================
# VEHÍCULO  (RN-04) — la misma regla desde los dos lados
# ==========================================================================
def test_no_se_asigna_un_vehiculo_ya_ocupado():
    """
    RN-04 en su segundo sentido: un vehículo que ya cubre una ruta no puede
    saltar a otra sin liberarse antes.

    Permitirlo dejaba la ruta anterior sin unidad en silencio, que es
    exactamente el estado que RN-R6 impide al dar de baja una ruta.
    """
    with cliente_http() as c:
        cabecera = cab(c)
        nueva = alta(c, cabecera, "vehocupado")
        ocupado = obtener_bd()["vehiculos"].find_one(
            {"ruta_asignada_id": {"$ne": None}})
        r = c.put(f"{API}/rutas/{nueva['id']}/asignar-vehiculo",
                  headers=cabecera, json={"vehiculo_id": str(ocupado["_id"])})
    assert r.status_code == 409, r.text
    cuerpo = r.json()
    assert cuerpo["codigo_error"] == "REGLA_V3", (
        "debe ser la MISMA regla que aplica el módulo de vehículos")
    assert cuerpo["detalles"][0]["ruta_actual"], (
        "el error debe decir qué ruta cubre ya ese vehículo")


def test_un_vehiculo_no_salta_de_ruta_desde_vehiculos():
    """La misma protección desde el módulo de vehículos: simétrica."""
    bd = obtener_bd()
    with cliente_http() as c:
        cabecera = cab(c)
        nueva = alta(c, cabecera, "nosalta")
        ocupado = bd["vehiculos"].find_one({"ruta_asignada_id": {"$ne": None}})
        r = c.patch(f"{API}/vehiculos/{ocupado['_id']}/ruta", headers=cabecera,
                    json={"ruta_id": nueva["id"]})
    assert r.status_code == 409, r.text
    assert r.json()["codigo_error"] == "REGLA_V3"


def test_asignar_desde_rutas_sincroniza_los_dos_extremos():
    """
    Asignar desde `/rutas` debe dejar el mismo estado que asignar desde
    `/vehiculos`: es la misma regla delegada, no una segunda versión.
    """
    bd = obtener_bd()
    with cliente_http() as c:
        cabecera = cab(c)
        nueva = alta(c, cabecera, "sincro")
        vehiculo = bd["vehiculos"].find_one({"ruta_asignada_id": {"$ne": None}})
        ruta_original = vehiculo["ruta_asignada_id"]
        try:
            # Se libera el vehículo de su ruta y se asigna a la nueva
            c.patch(f"{API}/vehiculos/{vehiculo['_id']}/ruta", headers=cabecera,
                    json={"ruta_id": None})
            r = c.put(f"{API}/rutas/{nueva['id']}/asignar-vehiculo",
                      headers=cabecera,
                      json={"vehiculo_id": str(vehiculo["_id"])})
            assert r.status_code == 200, r.text
            assert r.json()["datos"]["vehiculo_asignado_id"] == str(vehiculo["_id"])

            # El otro extremo también quedó escrito
            actual = obtener_bd()["vehiculos"].find_one({"_id": vehiculo["_id"]})
            assert str(actual["ruta_asignada_id"]) == nueva["id"]

            # Y desasignar desde rutas libera ambos lados
            r2 = c.put(f"{API}/rutas/{nueva['id']}/asignar-vehiculo",
                       headers=cabecera, json={"vehiculo_id": None})
            assert r2.status_code == 200, r2.text
            libre = obtener_bd()["vehiculos"].find_one({"_id": vehiculo["_id"]})
            assert libre["ruta_asignada_id"] is None
        finally:
            # Se devuelve el vehículo a su ruta original, pase lo que pase
            c.patch(f"{API}/vehiculos/{vehiculo['_id']}/ruta", headers=cabecera,
                    json={"ruta_id": str(ruta_original)})

    restaurado = obtener_bd()["vehiculos"].find_one({"_id": vehiculo["_id"]})
    assert str(restaurado["ruta_asignada_id"]) == str(ruta_original)


def test_vehiculo_inexistente():
    with cliente_http() as c:
        cabecera = cab(c)
        ruta = alta(c, cabecera, "vehnoexiste")
        r = c.put(f"{API}/rutas/{ruta['id']}/asignar-vehiculo", headers=cabecera,
                  json={"vehiculo_id": "6a83893489a0d3691e05ffff"})
    assert r.status_code == 409
    assert "No existe el vehículo" in r.json()["mensaje"]


# ==========================================================================
# BAJA  (RN-R6)
# ==========================================================================
def test_no_se_da_de_baja_con_vehiculo_asignado():
    """RN-R6: las 20 del seed tienen vehículo."""
    with cliente_http() as c:
        cabecera = cab(c)
        conVehiculo = next(r for r in c.get(f"{API}/rutas?tamano=20",
                                            headers=cabecera).json()["datos"]
                           if r["vehiculo_asignado_id"])
        r = c.delete(f"{API}/rutas/{conVehiculo['id']}", headers=cabecera)
    assert r.status_code == 409, r.text
    assert r.json()["codigo_error"] == "REGLA_R6"
    assert r.json()["detalles"][0]["vehiculo_asignado"]


def test_baja_sin_vehiculo_funciona():
    with cliente_http() as c:
        cabecera = cab(c)
        ruta = alta(c, cabecera, "baja")
        r = c.delete(f"{API}/rutas/{ruta['id']}", headers=cabecera)
        assert r.status_code == 200, r.text
        assert r.json()["datos"]["activo"] is False
        assert c.get(f"{API}/rutas/{ruta['id']}",
                     headers=cabecera).status_code == 200


def test_reactivar():
    with cliente_http() as c:
        cabecera = cab(c)
        ruta = alta(c, cabecera, "reactiva")
        c.delete(f"{API}/rutas/{ruta['id']}", headers=cabecera)
        r = c.patch(f"{API}/rutas/{ruta['id']}/reactivar", headers=cabecera)
    assert r.status_code == 200, r.text
    assert r.json()["datos"]["activo"] is True


# ==========================================================================
# ERRORES
# ==========================================================================
def test_inexistente_da_404():
    with cliente_http() as c:
        r = c.get(f"{API}/rutas/6a83893489a0d3691e05ffff", headers=cab(c))
    assert r.status_code == 404


def test_identificador_invalido_da_400():
    with cliente_http() as c:
        r = c.get(f"{API}/rutas/no-es-id", headers=cab(c))
    assert r.status_code == 400


# ==========================================================================
# Modo manual (sin pytest)
# ==========================================================================
if __name__ == "__main__":
    pruebas = [
        ("Sin sesión no se consulta", test_sin_sesion_no_se_consulta),
        ("Cualquier sesión consulta", test_cualquier_sesion_consulta),
        ("Solo el admin modifica", test_solo_admin_modifica),
        ("Listado y filtros", test_listado_y_filtros),
        ("Filtro sin vehículo", test_filtro_sin_vehiculo),
        ("Zona inválida", test_zona_invalida),
        ("Resumen y catálogos", test_resumen_y_catalogos),
        ("El análisis lee del DW y del clustering",
         test_analisis_lee_del_dw_y_del_clustering),
        ("Análisis de una ruta nueva", test_analisis_de_una_ruta_nueva),
        ("El alta calcula los totales (RN-R2)", test_alta_calcula_los_totales),
        ("Las paradas se numeran solas (RN-R3)",
         test_las_paradas_se_numeran_solas),
        ("Los días de operación se ordenan", test_dias_de_operacion_se_ordenan),
        ("Día inválido se rechaza", test_dia_invalido_se_rechaza),
        ("Hora inválida se rechaza", test_hora_invalida_se_rechaza),
        ("Sin paradas se rechaza", test_sin_paradas_se_rechaza),
        ("Cliente inexistente en la parada (RN-R4)",
         test_cliente_inexistente_en_la_parada),
        ("Alias de dirección inexistente (RN-R4)",
         test_alias_de_direccion_inexistente),
        ("Cliente repetido en la ruta (RN-R5)", test_cliente_repetido_en_la_ruta),
        ("Agregar parada recalcula", test_agregar_parada_recalcula),
        ("Quitar parada renumera (RN-R3)", test_quitar_parada_renumera),
        ("No se quita la última parada", test_no_se_quita_la_ultima_parada),
        ("Quitar parada inexistente", test_quitar_parada_inexistente),
        ("Reemplazar itinerario", test_reemplazar_itinerario),
        ("El PUT no toca paradas ni totales (RN-R2)",
         test_no_se_editan_los_totales_ni_las_paradas_por_el_put),
        ("Actualizar cabecera", test_actualizar_cabecera),
        ("No se asigna un vehículo ya ocupado (RN-04)",
         test_no_se_asigna_un_vehiculo_ya_ocupado),
        ("Un vehículo no salta de ruta desde /vehiculos",
         test_un_vehiculo_no_salta_de_ruta_desde_vehiculos),
        ("Asignar desde rutas sincroniza los dos extremos",
         test_asignar_desde_rutas_sincroniza_los_dos_extremos),
        ("Vehículo inexistente", test_vehiculo_inexistente),
        ("No se da de baja con vehículo asignado (RN-R6)",
         test_no_se_da_de_baja_con_vehiculo_asignado),
        ("Baja sin vehículo funciona", test_baja_sin_vehiculo_funciona),
        ("Reactivar", test_reactivar),
        ("Inexistente da 404", test_inexistente_da_404),
        ("Identificador inválido da 400", test_identificador_invalido_da_400),
    ]

    print("=" * 70)
    print("  SIG-LOG — Pruebas del módulo Rutas")
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
    print(f"  Rutas de prueba eliminadas: {limpiar()}")
    print("=" * 70)
    print(f"  Resultado: {len(pruebas) - fallos}/{len(pruebas)} pruebas correctas")
    print("=" * 70)
    sys.exit(1 if fallos else 0)
