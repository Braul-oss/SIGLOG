"""
SIG-LOG — Sistema Integral de Gestión Logística
tests/test_entregas.py

PRUEBAS DEL MÓDULO ENTREGAS

`entregas` es la colección crítica del proyecto: de aquí salen la variable
objetivo y la mayoría de los predictores. Lo que estas pruebas comprueban,
por encima del CRUD, es que esa cifra sea **calculada y no capturada**:

    RN-E1  el folio ENT-AAAAMMDD-NNNNN lo genera el sistema
    RN-E2  tiempo_real_min, retraso_min y es_retraso se calculan al
           registrar la llegada; el umbral RNP-01 decide es_retraso
    RN-E3  el estatus sigue RNP-08 y cada cambio queda en el historial
           con quién lo hizo
    RN-E4  no se registra llegada si el viaje no está EN_CURSO
    RN-E5  los campos denormalizados preservan el dato histórico (§10.4)
    RN-E6  la causa de retraso solo se acepta si hubo retraso
    RN-E7  la entrega hereda del viaje ruta, vehículo, operador y fecha

Cada prueba monta su propio escenario completo —cliente, ruta, vehículo,
operador y viaje— y lo borra al terminar, para no tocar el seed.
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
MARCA = "ZZ-ENTREGA"
PLACA = "ZZE"
UMBRAL = settings.UMBRAL_RETRASO_MIN

ORIGEN = {"nombre": "Centro de Distribución SIG-LOG",
          "calle": "Vialidad Adolfo López Mateos", "numero": "1200",
          "colonia": "Parque Industrial", "municipio": "Toluca",
          "estado": "México", "cp": "50200"}


def cliente_http() -> TestClient:
    return TestClient(app)


def cab(c: TestClient, usuario: str = "admin") -> dict[str, str]:
    r = c.post(f"{API}/auth/login",
               data={"username": usuario, "password": "siglog2026"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['datos']['access_token']}"}


def limpiar() -> dict[str, int]:
    bd = obtener_bd()
    rutas = [r["_id"] for r in bd["rutas"].find(
        {"nombre": {"$regex": f"^{MARCA}"}}, {"_id": 1})]
    viajes = [v["_id"] for v in bd["viajes"].find(
        {"ruta_id": {"$in": rutas}}, {"_id": 1})] if rutas else []
    return {
        "entregas": (bd["entregas"].delete_many(
            {"viaje_id": {"$in": viajes}}).deleted_count if viajes else 0),
        "viajes": (bd["viajes"].delete_many(
            {"_id": {"$in": viajes}}).deleted_count if viajes else 0),
        "rutas": bd["rutas"].delete_many(
            {"nombre": {"$regex": f"^{MARCA}"}}).deleted_count,
        "vehiculos": bd["vehiculos"].delete_many(
            {"placa": {"$regex": f"^{PLACA}"}}).deleted_count,
        "operadores": bd["operadores"].delete_many(
            {"nombre_completo": {"$regex": f"^{MARCA}"}}).deleted_count,
        "clientes": bd["clientes"].delete_many(
            {"nombre": {"$regex": f"^{MARCA}"}}).deleted_count,
    }


try:
    import pytest

    @pytest.fixture(scope="module", autouse=True)
    def _limpiar_al_terminar():
        yield
        limpiar()
except ImportError:                    # pragma: no cover
    pass


_usados: set[str] = set()


def _unico(prefijo: str = "") -> str:
    while True:
        valor = f"{prefijo}{random.randint(10000, 99999)}"
        if valor not in _usados:
            _usados.add(valor)
            return valor


def escenario(c, cabecera, n_paradas: int = 2) -> dict:
    """Cliente(s), ruta, vehículo, operador y viaje, listos para entregas."""
    clientes = []
    for i in range(n_paradas):
        r = c.post(f"{API}/clientes", headers=cabecera, json={
            "nombre": f"{MARCA} Cliente {_unico()}", "tipo_cliente": "MINORISTA",
            "direcciones": [{"alias": "Matriz", "calle": "Calle Prueba",
                             "numero": "1", "colonia": "Centro",
                             "municipio": "Toluca", "estado": "México",
                             "cp": "50000", "principal": True}]})
        assert r.status_code == 201, r.text
        clientes.append(r.json()["datos"])

    r = c.post(f"{API}/rutas", headers=cabecera, json={
        "nombre": f"{MARCA} Ruta {_unico()}", "zona": "NORTE", "origen": ORIGEN,
        "paradas": [{"cliente_id": cl["id"], "direccion_alias": "Matriz",
                     "distancia_desde_anterior_km": 10.0,
                     "tiempo_estimado_min": 30.0} for cl in clientes],
        "dias_operacion": ["LUNES", "MARTES", "MIERCOLES", "JUEVES", "VIERNES"],
        "hora_salida_programada": "06:30"})
    assert r.status_code == 201, r.text
    ruta = r.json()["datos"]

    r = c.post(f"{API}/vehiculos", headers=cabecera, json={
        "placa": f"{PLACA}-{random.randint(1000, 9999)}", "marca": "Prueba",
        "modelo": "Entrega", "anio": 2023, "tipo_vehiculo": "MEDIANO",
        "capacidad_tanque_litros": 120, "rendimiento_nominal_km_l": 7.0,
        "odometro_actual_km": 30_000})
    assert r.status_code == 201, r.text
    vehiculo = r.json()["datos"]

    r = c.post(f"{API}/operadores", headers=cabecera, json={
        "nombre_completo": f"{MARCA} Operador {_unico()}",
        "licencia": {"numero": _unico("ZE"), "tipo": "C",
                     "vigencia": str(date.today() + timedelta(days=400))},
        "fecha_ingreso": str(date.today() - timedelta(days=300))})
    assert r.status_code == 201, r.text
    operador = r.json()["datos"]

    r = c.post(f"{API}/viajes", headers=cabecera, json={
        "ruta_id": ruta["id"], "vehiculo_id": vehiculo["id"],
        "operador_id": operador["id"], "fecha": str(date.today())})
    assert r.status_code == 201, r.text

    return {"clientes": clientes, "ruta": ruta, "vehiculo": vehiculo,
            "operador": operador, "viaje": r.json()["datos"]}


def generar(c, cabecera, esc) -> list[dict]:
    r = c.post(f"{API}/entregas/generar", headers=cabecera,
               json={"viaje_id": esc["viaje"]["id"]})
    assert r.status_code == 201, r.text
    return r.json()["datos"]["entregas"]


def iniciar_viaje(c, cabecera, esc) -> None:
    r = c.patch(f"{API}/viajes/{esc['viaje']['id']}/iniciar", headers=cabecera,
                json={"odometro_inicial_km": 30_000})
    assert r.status_code == 200, r.text


# ==========================================================================
# PERMISOS
# ==========================================================================
def test_sin_sesion_no_se_consulta():
    with cliente_http() as c:
        assert c.get(f"{API}/entregas").status_code == 401


def test_el_analista_no_registra():
    with cliente_http() as c:
        cabecera = cab(c)
        esc = escenario(c, cabecera, 1)
        r = c.post(f"{API}/entregas/generar", headers=cab(c, "analista"),
                   json={"viaje_id": esc["viaje"]["id"]})
    assert r.status_code == 403


# ==========================================================================
# ALTA  (RN-E1, RN-E5, RN-E7)
# ==========================================================================
def test_generar_desde_la_ruta():
    """La operación normal: la ruta ya sabe a quién se entrega y en qué orden."""
    with cliente_http() as c:
        cabecera = cab(c)
        esc = escenario(c, cabecera, 3)
        entregas = generar(c, cabecera, esc)

    assert len(entregas) == 3
    assert [e["orden_parada"] for e in entregas] == [1, 2, 3]
    for e in entregas:
        assert e["folio_entrega"].startswith(f"ENT-{date.today():%Y%m%d}-")
        assert e["estatus"] == "PROGRAMADA"
        assert e["retraso_min"] is None, "aún no ha llegado"
        assert e["es_retraso"] is None

    # El ETA se acumula: la parada 2 se estima 30 min después de la 1
    primera = datetime.fromisoformat(entregas[0]["hora_estimada_llegada"])
    segunda = datetime.fromisoformat(entregas[1]["hora_estimada_llegada"])
    assert (segunda - primera).total_seconds() / 60 == 30.0


def test_la_entrega_hereda_del_viaje_y_denormaliza():
    """RN-E7 y §10.4: hereda del viaje y copia los nombres del momento."""
    with cliente_http() as c:
        cabecera = cab(c)
        esc = escenario(c, cabecera, 1)
        entrega = generar(c, cabecera, esc)[0]

    assert entrega["viaje_id"] == esc["viaje"]["id"]
    assert entrega["ruta_id"] == esc["ruta"]["id"]
    assert entrega["vehiculo_id"] == esc["vehiculo"]["id"]
    assert entrega["operador_id"] == esc["operador"]["id"]
    # Denormalización de §10.4
    assert entrega["nombre_cliente"] == esc["clientes"][0]["nombre"]
    assert entrega["placa"] == esc["vehiculo"]["placa"]
    assert entrega["nombre_operador"] == esc["operador"]["nombre_completo"]


def test_el_nombre_denormalizado_preserva_el_historico():
    """
    §10.4: si el cliente se renombra, la entrega conserva el nombre que
    tenía cuando se operó. Es la razón de ser de la denormalización.
    """
    with cliente_http() as c:
        cabecera = cab(c)
        esc = escenario(c, cabecera, 1)
        entrega = generar(c, cabecera, esc)[0]
        nombre_original = entrega["nombre_cliente"]

        r = c.put(f"{API}/clientes/{esc['clientes'][0]['id']}", headers=cabecera,
                  json={"nombre": f"{MARCA} Cliente Renombrado"})
        assert r.status_code == 200, r.text

        actual = c.get(f"{API}/entregas/{entrega['id']}",
                       headers=cabecera).json()["datos"]
    assert actual["nombre_cliente"] == nombre_original, (
        "la entrega debe conservar el nombre histórico del cliente (§10.4)")


def test_no_se_generan_dos_veces():
    with cliente_http() as c:
        cabecera = cab(c)
        esc = escenario(c, cabecera, 1)
        generar(c, cabecera, esc)
        r = c.post(f"{API}/entregas/generar", headers=cabecera,
                   json={"viaje_id": esc["viaje"]["id"]})
    assert r.status_code == 409
    assert "ya tiene entregas" in r.json()["mensaje"]


def test_crear_una_entrega_suelta():
    with cliente_http() as c:
        cabecera = cab(c)
        esc = escenario(c, cabecera, 1)
        r = c.post(f"{API}/entregas", headers=cabecera, json={
            "viaje_id": esc["viaje"]["id"],
            "cliente_id": esc["clientes"][0]["id"],
            "orden_parada": 5, "tiempo_estimado_min": 20.0,
            "distancia_km": 8.0})
    assert r.status_code == 201, r.text
    assert r.json()["datos"]["orden_parada"] == 5


def test_no_se_repite_el_orden_de_parada():
    with cliente_http() as c:
        cabecera = cab(c)
        esc = escenario(c, cabecera, 1)
        generar(c, cabecera, esc)
        r = c.post(f"{API}/entregas", headers=cabecera, json={
            "viaje_id": esc["viaje"]["id"],
            "cliente_id": esc["clientes"][0]["id"],
            "orden_parada": 1, "tiempo_estimado_min": 20.0,
            "distancia_km": 8.0})
    assert r.status_code == 409
    assert "orden de parada 1" in r.json()["mensaje"]


# ==========================================================================
# LLEGADA — donde nace la variable objetivo  (RN-E2)
# ==========================================================================
def test_la_llegada_calcula_la_variable_objetivo():
    """
    La prueba central del proyecto: `retraso_min` y `es_retraso` se
    DERIVAN de las horas, no se capturan.
    """
    with cliente_http() as c:
        cabecera = cab(c)
        esc = escenario(c, cabecera, 1)
        entrega = generar(c, cabecera, esc)[0]
        iniciar_viaje(c, cabecera, esc)

        estimada = datetime.fromisoformat(entrega["hora_estimada_llegada"])
        llegada = estimada + timedelta(minutes=25)     # 25 > umbral de 15

        r = c.patch(f"{API}/entregas/{entrega['id']}/llegada", headers=cabecera,
                    json={"hora_real_llegada": llegada.isoformat(),
                          "causa_retraso": "TRAFICO"})
    assert r.status_code == 200, r.text
    datos = r.json()["datos"]
    assert datos["retraso_min"] == 25.0
    assert datos["es_retraso"] == 1, f"25 min supera el umbral de {UMBRAL}"
    assert datos["tiempo_real_min"] == 55.0          # 30 estimados + 25
    assert datos["causa_retraso"] == "TRAFICO"
    assert datos["estatus"] == "ENTREGADA"


def test_una_entrega_puntual_no_es_retraso():
    with cliente_http() as c:
        cabecera = cab(c)
        esc = escenario(c, cabecera, 1)
        entrega = generar(c, cabecera, esc)[0]
        iniciar_viaje(c, cabecera, esc)

        estimada = datetime.fromisoformat(entrega["hora_estimada_llegada"])
        r = c.patch(f"{API}/entregas/{entrega['id']}/llegada", headers=cabecera,
                    json={"hora_real_llegada":
                          (estimada + timedelta(minutes=5)).isoformat()})
    datos = r.json()["datos"]
    assert datos["retraso_min"] == 5.0
    assert datos["es_retraso"] == 0


def test_una_entrega_adelantada_da_retraso_negativo():
    """El retraso puede ser negativo: llegar antes también es información."""
    with cliente_http() as c:
        cabecera = cab(c)
        esc = escenario(c, cabecera, 1)
        entrega = generar(c, cabecera, esc)[0]
        iniciar_viaje(c, cabecera, esc)

        estimada = datetime.fromisoformat(entrega["hora_estimada_llegada"])
        r = c.patch(f"{API}/entregas/{entrega['id']}/llegada", headers=cabecera,
                    json={"hora_real_llegada":
                          (estimada - timedelta(minutes=8)).isoformat()})
    datos = r.json()["datos"]
    assert datos["retraso_min"] == -8.0
    assert datos["es_retraso"] == 0


def test_el_umbral_rnp01_es_estricto():
    """Exactamente el umbral NO es retraso; se exige superarlo."""
    with cliente_http() as c:
        cabecera = cab(c)
        esc = escenario(c, cabecera, 1)
        entrega = generar(c, cabecera, esc)[0]
        iniciar_viaje(c, cabecera, esc)

        estimada = datetime.fromisoformat(entrega["hora_estimada_llegada"])
        r = c.patch(f"{API}/entregas/{entrega['id']}/llegada", headers=cabecera,
                    json={"hora_real_llegada":
                          (estimada + timedelta(minutes=UMBRAL)).isoformat()})
    datos = r.json()["datos"]
    assert datos["retraso_min"] == float(UMBRAL)
    assert datos["es_retraso"] == 0, "el umbral es 'mayor que', no 'mayor o igual'"


def test_no_se_registra_llegada_sin_viaje_en_curso():
    """RN-E4: no se entrega antes de salir."""
    with cliente_http() as c:
        cabecera = cab(c)
        esc = escenario(c, cabecera, 1)
        entrega = generar(c, cabecera, esc)[0]
        # El viaje sigue PROGRAMADO
        r = c.patch(f"{API}/entregas/{entrega['id']}/llegada", headers=cabecera,
                    json={})
    assert r.status_code == 409, r.text
    cuerpo = r.json()
    assert cuerpo["codigo_error"] == "REGLA_E4"
    assert cuerpo["detalles"][0]["estatus_viaje"] == "PROGRAMADO"


def test_no_se_registra_la_llegada_dos_veces():
    """Corregirla reescribiría la variable objetivo de los modelos."""
    with cliente_http() as c:
        cabecera = cab(c)
        esc = escenario(c, cabecera, 1)
        entrega = generar(c, cabecera, esc)[0]
        iniciar_viaje(c, cabecera, esc)

        c.patch(f"{API}/entregas/{entrega['id']}/llegada", headers=cabecera,
                json={})
        r = c.patch(f"{API}/entregas/{entrega['id']}/llegada", headers=cabecera,
                    json={})
    assert r.status_code == 409
    assert "ya tiene registrada su llegada" in r.json()["mensaje"]


def test_la_causa_solo_se_acepta_si_hubo_retraso():
    """RN-E6: atribuir causas a entregas puntuales ensuciaría el Pareto."""
    with cliente_http() as c:
        cabecera = cab(c)
        esc = escenario(c, cabecera, 1)
        entrega = generar(c, cabecera, esc)[0]
        iniciar_viaje(c, cabecera, esc)

        estimada = datetime.fromisoformat(entrega["hora_estimada_llegada"])
        r = c.patch(f"{API}/entregas/{entrega['id']}/llegada", headers=cabecera,
                    json={"hora_real_llegada":
                          (estimada + timedelta(minutes=2)).isoformat(),
                          "causa_retraso": "TRAFICO"})
    assert r.status_code == 409, r.text
    assert r.json()["codigo_error"] == "REGLA_E6"


def test_causa_fuera_de_catalogo():
    with cliente_http() as c:
        cabecera = cab(c)
        esc = escenario(c, cabecera, 1)
        entrega = generar(c, cabecera, esc)[0]
        iniciar_viaje(c, cabecera, esc)
        r = c.patch(f"{API}/entregas/{entrega['id']}/llegada", headers=cabecera,
                    json={"causa_retraso": "PEREZA"})
    assert r.status_code == 422


def test_llegada_sin_entregar_deja_no_entregada():
    with cliente_http() as c:
        cabecera = cab(c)
        esc = escenario(c, cabecera, 1)
        entrega = generar(c, cabecera, esc)[0]
        iniciar_viaje(c, cabecera, esc)
        r = c.patch(f"{API}/entregas/{entrega['id']}/llegada", headers=cabecera,
                    json={"entregada": False,
                          "observaciones": "Cliente ausente en el domicilio"})
    assert r.status_code == 200, r.text
    datos = r.json()["datos"]
    assert datos["estatus"] == "NO_ENTREGADA"
    assert datos["retraso_min"] is not None, "el retraso se calcula igual"


# ==========================================================================
# ESTATUS E HISTORIAL  (RN-E3)
# ==========================================================================
def test_el_historial_registra_quien_y_cuando():
    with cliente_http() as c:
        cabecera = cab(c)
        esc = escenario(c, cabecera, 1)
        entrega = generar(c, cabecera, esc)[0]
        assert len(entrega["historial_estatus"]) == 1
        assert entrega["historial_estatus"][0]["usuario"] == "admin"

        r = c.patch(f"{API}/entregas/{entrega['id']}/estatus",
                    headers=cab(c, "despachador"),
                    json={"estatus": "EN_RUTA", "motivo": "Salió a ruta"})
    assert r.status_code == 200, r.text
    historial = r.json()["datos"]["historial_estatus"]
    assert len(historial) == 2
    assert historial[-1]["estatus"] == "EN_RUTA"
    assert historial[-1]["usuario"] == "despachador"
    assert historial[-1]["motivo"] == "Salió a ruta"
    assert historial[-1]["fecha_hora"]


def test_transicion_de_estatus_invalida():
    with cliente_http() as c:
        cabecera = cab(c)
        esc = escenario(c, cabecera, 1)
        entrega = generar(c, cabecera, esc)[0]
        # PROGRAMADA no salta directo a ENTREGADA
        r = c.patch(f"{API}/entregas/{entrega['id']}/estatus", headers=cabecera,
                    json={"estatus": "ENTREGADA"})
    assert r.status_code == 409, r.text
    cuerpo = r.json()
    assert cuerpo["codigo_error"] == "REGLA_E3"
    assert set(cuerpo["detalles"][0]["transiciones_validas"]) == {"EN_RUTA",
                                                                  "CANCELADA"}


def test_una_entrega_cerrada_no_cambia():
    with cliente_http() as c:
        cabecera = cab(c)
        esc = escenario(c, cabecera, 1)
        entrega = generar(c, cabecera, esc)[0]
        iniciar_viaje(c, cabecera, esc)
        c.patch(f"{API}/entregas/{entrega['id']}/llegada", headers=cabecera,
                json={})
        r = c.patch(f"{API}/entregas/{entrega['id']}/estatus", headers=cabecera,
                    json={"estatus": "CANCELADA"})
    assert r.status_code == 409
    assert r.json()["detalles"][0]["transiciones_validas"] == []


def test_no_existe_borrado():
    with cliente_http() as c:
        cabecera = cab(c)
        esc = escenario(c, cabecera, 1)
        entrega = generar(c, cabecera, esc)[0]
        r = c.delete(f"{API}/entregas/{entrega['id']}", headers=cabecera)
    assert r.status_code == 405


# ==========================================================================
# CONSULTA
# ==========================================================================
def test_listado_y_filtros():
    with cliente_http() as c:
        cabecera = cab(c)
        cuerpo = c.get(f"{API}/entregas?tamano=5", headers=cabecera).json()
        assert cuerpo["total"] >= 14_000, "deberían estar las del seed"

        retrasadas = c.get(f"{API}/entregas?solo_retrasadas=true&tamano=5",
                           headers=cabecera).json()
    assert all(e["es_retraso"] == 1 for e in retrasadas["datos"])


def test_filtro_por_viaje():
    with cliente_http() as c:
        cabecera = cab(c)
        esc = escenario(c, cabecera, 2)
        generar(c, cabecera, esc)
        cuerpo = c.get(f"{API}/entregas?viaje_id={esc['viaje']['id']}",
                       headers=cabecera).json()
    assert cuerpo["total"] == 2


def test_resumen_reporta_la_variable_objetivo():
    with cliente_http() as c:
        datos = c.get(f"{API}/entregas/resumen", headers=cab(c)).json()["datos"]
    objetivo = datos["variable_objetivo"]
    assert objetivo["umbral_min"] == UMBRAL
    assert objetivo["entregas_medibles"] > 0
    assert 0 <= objetivo["puntualidad_pct"] <= 100
    assert objetivo["retraso_medio_min"] is not None


def test_catalogos():
    with cliente_http() as c:
        datos = c.get(f"{API}/entregas/catalogos", headers=cab(c)).json()["datos"]
    assert set(datos["estatus"]) == set(settings.CATALOGO_ESTATUS_ENTREGA)
    assert datos["transiciones"]["ENTREGADA"] == []
    assert datos["umbral_retraso_min"] == UMBRAL
    assert "no se capturan" in datos["nota_variable_objetivo"]


def test_inexistente_da_404():
    with cliente_http() as c:
        r = c.get(f"{API}/entregas/6a83893489a0d3691e05ffff", headers=cab(c))
    assert r.status_code == 404


# ==========================================================================
# Modo manual (sin pytest)
# ==========================================================================
if __name__ == "__main__":
    pruebas = [
        ("Sin sesión no se consulta", test_sin_sesion_no_se_consulta),
        ("El analista no registra", test_el_analista_no_registra),
        ("Generar desde la ruta", test_generar_desde_la_ruta),
        ("La entrega hereda del viaje y denormaliza (RN-E7, §10.4)",
         test_la_entrega_hereda_del_viaje_y_denormaliza),
        ("El nombre denormalizado preserva el histórico (§10.4)",
         test_el_nombre_denormalizado_preserva_el_historico),
        ("No se generan dos veces", test_no_se_generan_dos_veces),
        ("Crear una entrega suelta", test_crear_una_entrega_suelta),
        ("No se repite el orden de parada", test_no_se_repite_el_orden_de_parada),
        ("La llegada calcula la variable objetivo (RN-E2)",
         test_la_llegada_calcula_la_variable_objetivo),
        ("Una entrega puntual no es retraso", test_una_entrega_puntual_no_es_retraso),
        ("Una entrega adelantada da retraso negativo",
         test_una_entrega_adelantada_da_retraso_negativo),
        ("El umbral RNP-01 es estricto", test_el_umbral_rnp01_es_estricto),
        ("No se registra llegada sin viaje EN_CURSO (RN-E4)",
         test_no_se_registra_llegada_sin_viaje_en_curso),
        ("No se registra la llegada dos veces",
         test_no_se_registra_la_llegada_dos_veces),
        ("La causa solo se acepta si hubo retraso (RN-E6)",
         test_la_causa_solo_se_acepta_si_hubo_retraso),
        ("Causa fuera de catálogo", test_causa_fuera_de_catalogo),
        ("Llegada sin entregar deja NO_ENTREGADA",
         test_llegada_sin_entregar_deja_no_entregada),
        ("El historial registra quién y cuándo (RN-E3)",
         test_el_historial_registra_quien_y_cuando),
        ("Transición de estatus inválida", test_transicion_de_estatus_invalida),
        ("Una entrega cerrada no cambia", test_una_entrega_cerrada_no_cambia),
        ("No existe borrado", test_no_existe_borrado),
        ("Listado y filtros", test_listado_y_filtros),
        ("Filtro por viaje", test_filtro_por_viaje),
        ("El resumen reporta la variable objetivo",
         test_resumen_reporta_la_variable_objetivo),
        ("Catálogos", test_catalogos),
        ("Inexistente da 404", test_inexistente_da_404),
    ]

    print("=" * 70)
    print("  SIG-LOG — Pruebas del módulo Entregas")
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
