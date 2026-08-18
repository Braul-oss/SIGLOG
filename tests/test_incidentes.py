"""
SIG-LOG — Sistema Integral de Gestión Logística
tests/test_incidentes.py

PRUEBAS DEL MÓDULO INCIDENTES Y DEL RECÁLCULO DE ETA (RF-33)

    RN-I1  el folio INC-AAAAMMDD-NNN lo genera el sistema
    RN-I2  no se registran incidentes sobre viajes cerrados
    RN-I3  la duración se calcula al cerrar, del inicio y el fin
    RN-I4  el recálculo solo alcanza a las entregas pendientes del viaje
    RN-I5  el recálculo escribe `hora_estimada_recalculada` y NUNCA pisa
           `hora_estimada_llegada`
    RN-I6  cada recálculo deja constancia en `seguimiento_eventos`

La prueba más importante del módulo es la de RN-I5, y conviene explicar
por qué: el retraso se mide como `real − hora_estimada_llegada`. Si un
incidente sobrescribiera esa hora, la entrega parecería puntual
justamente por el incidente que la retrasó, y los modelos perderían la
señal que este módulo existe para darles.
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
MARCA = "ZZ-INCIDENTE"
PLACA = "ZZI"

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
        "seguimiento": (bd["seguimiento_eventos"].delete_many(
            {"viaje_id": {"$in": viajes}}).deleted_count if viajes else 0),
        "incidentes": (bd["incidentes"].delete_many(
            {"viaje_id": {"$in": viajes}}).deleted_count if viajes else 0),
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


def escenario(c, cabecera, n_paradas: int = 3, *, iniciar: bool = True) -> dict:
    """Viaje EN_CURSO con sus entregas generadas, listo para incidentes."""
    clientes = []
    for _ in range(n_paradas):
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
        "modelo": "Incidente", "anio": 2023, "tipo_vehiculo": "MEDIANO",
        "capacidad_tanque_litros": 120, "rendimiento_nominal_km_l": 7.0,
        "odometro_actual_km": 40_000})
    assert r.status_code == 201, r.text
    vehiculo = r.json()["datos"]

    r = c.post(f"{API}/operadores", headers=cabecera, json={
        "nombre_completo": f"{MARCA} Operador {_unico()}",
        "licencia": {"numero": _unico("ZI"), "tipo": "C",
                     "vigencia": str(date.today() + timedelta(days=400))},
        "fecha_ingreso": str(date.today() - timedelta(days=300))})
    assert r.status_code == 201, r.text
    operador = r.json()["datos"]

    r = c.post(f"{API}/viajes", headers=cabecera, json={
        "ruta_id": ruta["id"], "vehiculo_id": vehiculo["id"],
        "operador_id": operador["id"], "fecha": str(date.today())})
    assert r.status_code == 201, r.text
    viaje = r.json()["datos"]

    r = c.post(f"{API}/entregas/generar", headers=cabecera,
               json={"viaje_id": viaje["id"]})
    assert r.status_code == 201, r.text
    entregas = r.json()["datos"]["entregas"]

    if iniciar:
        r = c.patch(f"{API}/viajes/{viaje['id']}/iniciar", headers=cabecera,
                    json={"odometro_inicial_km": 40_000})
        assert r.status_code == 200, r.text

    return {"ruta": ruta, "vehiculo": vehiculo, "operador": operador,
            "viaje": viaje, "entregas": entregas}


def registrar(c, cabecera, esc, minutos: float = 25, tipo: str = "TRAFICO"):
    return c.post(f"{API}/incidentes", headers=cabecera, json={
        "viaje_id": esc["viaje"]["id"], "tipo": tipo, "severidad": "MEDIA",
        "tiempo_perdido_estimado_min": minutos,
        "descripcion": "Incidente de prueba"})


# ==========================================================================
# PERMISOS
# ==========================================================================
def test_sin_sesion_no_se_consulta():
    with cliente_http() as c:
        assert c.get(f"{API}/incidentes").status_code == 401


def test_el_analista_no_registra():
    with cliente_http() as c:
        cabecera = cab(c)
        esc = escenario(c, cabecera, 1)
        r = c.post(f"{API}/incidentes", headers=cab(c, "analista"), json={
            "viaje_id": esc["viaje"]["id"], "tipo": "TRAFICO",
            "severidad": "BAJA", "tiempo_perdido_estimado_min": 10})
    assert r.status_code == 403


# ==========================================================================
# REGISTRO  (RN-I1, RN-I2, RN-I3)
# ==========================================================================
def test_registrar_asigna_folio_y_actualiza_el_viaje():
    with cliente_http() as c:
        cabecera = cab(c)
        esc = escenario(c, cabecera, 1)
        r = registrar(c, cabecera, esc)
        assert r.status_code == 201, r.text
        datos = r.json()["datos"]

        viaje = c.get(f"{API}/viajes/{esc['viaje']['id']}",
                      headers=cabecera).json()["datos"]

    assert datos["folio_incidente"].startswith(f"INC-{date.today():%Y%m%d}-")
    assert datos["abierto"] is True
    assert datos["duracion_min"] is None, "la duración se calcula al cerrar"
    assert datos["ruta_id"] == esc["ruta"]["id"], "hereda la ruta del viaje"
    assert viaje["total_incidentes"] == 1, "el viaje debe contar su incidente"


def test_no_se_registra_sobre_un_viaje_cerrado():
    """RN-I2: el cierre del viaje ya declaró cuántos incidentes hubo."""
    with cliente_http() as c:
        cabecera = cab(c)
        esc = escenario(c, cabecera, 1)
        c.patch(f"{API}/viajes/{esc['viaje']['id']}/finalizar", headers=cabecera,
                json={"odometro_final_km": 40_100})
        r = registrar(c, cabecera, esc)
    assert r.status_code == 409, r.text
    cuerpo = r.json()
    assert cuerpo["codigo_error"] == "REGLA_I2"
    assert cuerpo["detalles"][0]["estatus_viaje"] == "FINALIZADO"


def test_cerrar_calcula_la_duracion():
    """RN-I3."""
    with cliente_http() as c:
        cabecera = cab(c)
        esc = escenario(c, cabecera, 1)
        inicio = datetime.now(timezone.utc) - timedelta(minutes=40)
        r = c.post(f"{API}/incidentes", headers=cabecera, json={
            "viaje_id": esc["viaje"]["id"], "tipo": "ACCIDENTE",
            "severidad": "ALTA", "tiempo_perdido_estimado_min": 30,
            "fecha_hora_inicio": inicio.isoformat()})
        incidente = r.json()["datos"]

        fin = inicio + timedelta(minutes=37)
        r = c.patch(f"{API}/incidentes/{incidente['id']}/cerrar",
                    headers=cabecera, json={"fecha_hora_fin": fin.isoformat()})
    assert r.status_code == 200, r.text
    datos = r.json()["datos"]
    assert datos["duracion_min"] == 37.0
    assert datos["abierto"] is False


def test_no_se_cierra_dos_veces():
    with cliente_http() as c:
        cabecera = cab(c)
        esc = escenario(c, cabecera, 1)
        incidente = registrar(c, cabecera, esc).json()["datos"]
        c.patch(f"{API}/incidentes/{incidente['id']}/cerrar", headers=cabecera,
                json={})
        r = c.patch(f"{API}/incidentes/{incidente['id']}/cerrar",
                    headers=cabecera, json={})
    assert r.status_code == 409
    assert "ya estaba cerrado" in r.json()["mensaje"]


def test_tipo_fuera_del_catalogo_rnp12():
    with cliente_http() as c:
        cabecera = cab(c)
        esc = escenario(c, cabecera, 1)
        r = c.post(f"{API}/incidentes", headers=cabecera, json={
            "viaje_id": esc["viaje"]["id"], "tipo": "METEORITO",
            "severidad": "ALTA", "tiempo_perdido_estimado_min": 10})
    assert r.status_code == 422


# ==========================================================================
# RECÁLCULO DE ETA  (RF-33) — el corazón del módulo
# ==========================================================================
def test_el_recalculo_suma_los_minutos_a_las_pendientes():
    """§17.3, pasos 2 y 3: entregas pendientes, ETA + minutos perdidos."""
    with cliente_http() as c:
        cabecera = cab(c)
        esc = escenario(c, cabecera, 3)
        etas_antes = {e["folio_entrega"]: e["hora_estimada_llegada"]
                      for e in esc["entregas"]}

        incidente = registrar(c, cabecera, esc, minutos=25).json()["datos"]
        r = c.post(f"{API}/incidentes/{incidente['id']}/afectar-entregas",
                   headers=cabecera, json={})
    assert r.status_code == 200, r.text
    datos = r.json()["datos"]
    assert datos["entregas_afectadas"] == 3
    assert datos["minutos_perdidos"] == 25.0

    for detalle in datos["detalle"]:
        anterior = datetime.fromisoformat(detalle["eta_anterior"])
        nuevo = datetime.fromisoformat(detalle["eta_nuevo"])
        assert (nuevo - anterior).total_seconds() / 60 == 25.0
        assert detalle["eta_anterior"].startswith(
            etas_antes[detalle["entrega"]][:16])


def test_el_recalculo_no_pisa_el_plan_original():
    """
    RN-I5, la prueba más importante del módulo.

    El retraso se mide como `real − hora_estimada_llegada`. Si el
    incidente sobrescribiera esa hora, la entrega parecería puntual
    justamente por el incidente que la retrasó.
    """
    with cliente_http() as c:
        cabecera = cab(c)
        esc = escenario(c, cabecera, 2)
        entrega = esc["entregas"][0]
        plan_original = entrega["hora_estimada_llegada"]

        incidente = registrar(c, cabecera, esc, minutos=40).json()["datos"]
        c.post(f"{API}/incidentes/{incidente['id']}/afectar-entregas",
               headers=cabecera, json={})

        actual = c.get(f"{API}/entregas/{entrega['id']}",
                       headers=cabecera).json()["datos"]

    # Se comparan INSTANTES y no cadenas: dos representaciones distintas
    # del mismo momento son el mismo momento.
    assert (datetime.fromisoformat(actual["hora_estimada_llegada"])
            == datetime.fromisoformat(plan_original)), (
        "el plan original NO debe modificarse (RN-I5)")
    assert actual["hora_estimada_recalculada"] is not None
    recalculado = datetime.fromisoformat(actual["hora_estimada_recalculada"])
    original = datetime.fromisoformat(plan_original)
    assert (recalculado - original).total_seconds() / 60 == 40.0
    assert incidente["id"] in actual["incidentes_ids"]


def test_el_retraso_se_sigue_midiendo_contra_el_plan_original():
    """
    La consecuencia práctica de RN-I5: tras un incidente, el retraso de la
    entrega sigue reflejando lo que se perdió. Si el ETA recalculado fuera
    la referencia, el retraso saldría casi cero y el incidente dejaría de
    explicar nada.
    """
    with cliente_http() as c:
        cabecera = cab(c)
        esc = escenario(c, cabecera, 1)
        entrega = esc["entregas"][0]
        estimada = datetime.fromisoformat(entrega["hora_estimada_llegada"])

        incidente = registrar(c, cabecera, esc, minutos=30).json()["datos"]
        c.post(f"{API}/incidentes/{incidente['id']}/afectar-entregas",
               headers=cabecera, json={})

        # Llega justo cuando predijo el ETA recalculado: 30 min tarde
        r = c.patch(f"{API}/entregas/{entrega['id']}/llegada", headers=cabecera,
                    json={"hora_real_llegada":
                          (estimada + timedelta(minutes=30)).isoformat(),
                          "causa_retraso": "TRAFICO"})
    assert r.status_code == 200, r.text
    datos = r.json()["datos"]
    assert datos["retraso_min"] == 30.0, (
        "el retraso debe medirse contra el plan original, no contra el "
        "ETA recalculado")
    assert datos["es_retraso"] == 1


def test_dos_incidentes_se_acumulan():
    """El segundo recálculo parte del ETA ya ajustado, no del original."""
    with cliente_http() as c:
        cabecera = cab(c)
        esc = escenario(c, cabecera, 1)
        entrega = esc["entregas"][0]
        original = datetime.fromisoformat(entrega["hora_estimada_llegada"])

        for minutos in (15, 20):
            incidente = registrar(c, cabecera, esc,
                                  minutos=minutos).json()["datos"]
            r = c.post(f"{API}/incidentes/{incidente['id']}/afectar-entregas",
                       headers=cabecera, json={})
            assert r.status_code == 200, r.text

        actual = c.get(f"{API}/entregas/{entrega['id']}",
                       headers=cabecera).json()["datos"]
    recalculado = datetime.fromisoformat(actual["hora_estimada_recalculada"])
    assert (recalculado - original).total_seconds() / 60 == 35.0
    assert len(actual["incidentes_ids"]) == 2


def test_las_entregas_ya_cerradas_no_se_recalculan():
    """RN-I4, paso 2 del §17.3."""
    with cliente_http() as c:
        cabecera = cab(c)
        esc = escenario(c, cabecera, 2)
        # Se registra la llegada de la primera: queda ENTREGADA
        c.patch(f"{API}/entregas/{esc['entregas'][0]['id']}/llegada",
                headers=cabecera, json={})

        incidente = registrar(c, cabecera, esc).json()["datos"]
        r = c.post(f"{API}/incidentes/{incidente['id']}/afectar-entregas",
                   headers=cabecera, json={})
    assert r.status_code == 200, r.text
    datos = r.json()["datos"]
    assert datos["entregas_afectadas"] == 1, "solo la que sigue pendiente"
    assert datos["detalle"][0]["entrega"] == esc["entregas"][1]["folio_entrega"]


def test_no_se_recalculan_entregas_de_otro_viaje():
    with cliente_http() as c:
        cabecera = cab(c)
        esc_a = escenario(c, cabecera, 1)
        esc_b = escenario(c, cabecera, 1)
        incidente = registrar(c, cabecera, esc_a).json()["datos"]
        r = c.post(f"{API}/incidentes/{incidente['id']}/afectar-entregas",
                   headers=cabecera,
                   json={"entregas_ids": [esc_b["entregas"][0]["id"]]})
    assert r.status_code == 409, r.text
    assert r.json()["codigo_error"] == "REGLA_I4"
    assert "no pertenecen al viaje" in r.json()["mensaje"]


def test_sin_entregas_pendientes_avisa():
    with cliente_http() as c:
        cabecera = cab(c)
        esc = escenario(c, cabecera, 1)
        c.patch(f"{API}/entregas/{esc['entregas'][0]['id']}/llegada",
                headers=cabecera, json={})
        incidente = registrar(c, cabecera, esc).json()["datos"]
        r = c.post(f"{API}/incidentes/{incidente['id']}/afectar-entregas",
                   headers=cabecera, json={})
    assert r.status_code == 409
    assert r.json()["codigo_error"] == "REGLA_I4"


def test_el_recalculo_usa_la_duracion_real_si_ya_cerro():
    with cliente_http() as c:
        cabecera = cab(c)
        esc = escenario(c, cabecera, 1)
        inicio = datetime.now(timezone.utc) - timedelta(minutes=50)
        incidente = c.post(f"{API}/incidentes", headers=cabecera, json={
            "viaje_id": esc["viaje"]["id"], "tipo": "CLIMA", "severidad": "ALTA",
            "tiempo_perdido_estimado_min": 10,
            "fecha_hora_inicio": inicio.isoformat()}).json()["datos"]

        c.patch(f"{API}/incidentes/{incidente['id']}/cerrar", headers=cabecera,
                json={"fecha_hora_fin":
                      (inicio + timedelta(minutes=45)).isoformat()})

        r = c.post(f"{API}/incidentes/{incidente['id']}/afectar-entregas",
                   headers=cabecera, json={})
    assert r.json()["datos"]["minutos_perdidos"] == 45.0, (
        "cerrado, debe usar la duración real y no el estimado inicial")


def test_la_respuesta_declara_el_supuesto_del_recalculo():
    """
    El §17.3 advierte que el recálculo lineal es un supuesto no
    confirmado. La respuesta lo dice, para que la cifra no se tome por
    una certeza.
    """
    with cliente_http() as c:
        cabecera = cab(c)
        esc = escenario(c, cabecera, 1)
        incidente = registrar(c, cabecera, esc).json()["datos"]
        datos = c.post(f"{API}/incidentes/{incidente['id']}/afectar-entregas",
                       headers=cabecera, json={}).json()["datos"]
    assert "supuesto" in datos["advertencia"]
    assert "§17.3" in datos["advertencia"]
    assert "lineal" in datos["metodo"]
    assert "NO se modifica" in datos["nota_plan_original"]


# ==========================================================================
# BITÁCORA  (RN-I6, §11.10)
# ==========================================================================
def test_el_recalculo_deja_rastro_en_la_bitacora():
    """
    RN-I6 y §17.3 paso 4. `seguimiento_eventos` llevaba vacía desde que se
    creó la base; este es el módulo que la llena.
    """
    with cliente_http() as c:
        cabecera = cab(c)
        esc = escenario(c, cabecera, 2)
        incidente = registrar(c, cabecera, esc, minutos=20).json()["datos"]
        c.post(f"{API}/incidentes/{incidente['id']}/afectar-entregas",
               headers=cabecera, json={})

        datos = c.get(f"{API}/incidentes/bitacora/{esc['viaje']['id']}",
                      headers=cabecera).json()["datos"]

    tipos = [e["tipo_evento"] for e in datos["eventos"]]
    assert "INCIDENTE" in tipos
    assert tipos.count("RECALCULO_ETA") == 2, "un evento por entrega afectada"

    recalculo = next(e for e in datos["eventos"]
                     if e["tipo_evento"] == "RECALCULO_ETA")
    assert recalculo["eta_anterior"] and recalculo["eta_nuevo"]
    anterior = datetime.fromisoformat(recalculo["eta_anterior"])
    nuevo = datetime.fromisoformat(recalculo["eta_nuevo"])
    assert (nuevo - anterior).total_seconds() / 60 == 20.0
    assert incidente["folio_incidente"] in recalculo["motivo"]


# ==========================================================================
# CONSULTA
# ==========================================================================
def test_listado_y_filtros():
    with cliente_http() as c:
        cabecera = cab(c)
        cuerpo = c.get(f"{API}/incidentes?tamano=5", headers=cabecera).json()
        assert cuerpo["total"] >= 350, "deberían estar los del seed"

        trafico = c.get(f"{API}/incidentes?tipo=TRAFICO&tamano=5",
                        headers=cabecera).json()
    assert all(i["tipo"] == "TRAFICO" for i in trafico["datos"])


def test_filtro_por_severidad_invalida():
    with cliente_http() as c:
        r = c.get(f"{API}/incidentes?severidad=CATASTROFICA", headers=cab(c))
    assert r.status_code == 409


def test_resumen_identifica_la_causa_dominante():
    with cliente_http() as c:
        cuerpo = c.get(f"{API}/incidentes/resumen", headers=cab(c)).json()
    datos = cuerpo["datos"]
    assert datos["total"] == sum(datos["por_tipo"].values())
    assert datos["tipo_dominante"] in settings.CATALOGO_TIPOS_INCIDENTE
    assert datos["total"] == datos["abiertos"] + datos["cerrados"]


def test_catalogos_declaran_la_advertencia():
    with cliente_http() as c:
        datos = c.get(f"{API}/incidentes/catalogos", headers=cab(c)).json()["datos"]
    assert set(datos["tipos"]) == set(settings.CATALOGO_TIPOS_INCIDENTE)
    assert set(datos["severidades"]) == set(settings.CATALOGO_SEVERIDAD_INCIDENTE)
    assert "supuesto" in datos["recalculo_eta"]["advertencia"]


def test_inexistente_da_404():
    with cliente_http() as c:
        r = c.get(f"{API}/incidentes/6a83893489a0d3691e05ffff", headers=cab(c))
    assert r.status_code == 404


# ==========================================================================
# Modo manual (sin pytest)
# ==========================================================================
if __name__ == "__main__":
    pruebas = [
        ("Sin sesión no se consulta", test_sin_sesion_no_se_consulta),
        ("El analista no registra", test_el_analista_no_registra),
        ("Registrar asigna folio y actualiza el viaje (RN-I1)",
         test_registrar_asigna_folio_y_actualiza_el_viaje),
        ("No se registra sobre un viaje cerrado (RN-I2)",
         test_no_se_registra_sobre_un_viaje_cerrado),
        ("Cerrar calcula la duración (RN-I3)", test_cerrar_calcula_la_duracion),
        ("No se cierra dos veces", test_no_se_cierra_dos_veces),
        ("Tipo fuera del catálogo RNP-12", test_tipo_fuera_del_catalogo_rnp12),
        ("El recálculo suma los minutos a las pendientes (RF-33)",
         test_el_recalculo_suma_los_minutos_a_las_pendientes),
        ("El recálculo NO pisa el plan original (RN-I5)",
         test_el_recalculo_no_pisa_el_plan_original),
        ("El retraso se sigue midiendo contra el plan original",
         test_el_retraso_se_sigue_midiendo_contra_el_plan_original),
        ("Dos incidentes se acumulan", test_dos_incidentes_se_acumulan),
        ("Las entregas ya cerradas no se recalculan (RN-I4)",
         test_las_entregas_ya_cerradas_no_se_recalculan),
        ("No se recalculan entregas de otro viaje (RN-I4)",
         test_no_se_recalculan_entregas_de_otro_viaje),
        ("Sin entregas pendientes avisa", test_sin_entregas_pendientes_avisa),
        ("El recálculo usa la duración real si ya cerró",
         test_el_recalculo_usa_la_duracion_real_si_ya_cerro),
        ("La respuesta declara el supuesto del recálculo (§17.3)",
         test_la_respuesta_declara_el_supuesto_del_recalculo),
        ("El recálculo deja rastro en la bitácora (RN-I6)",
         test_el_recalculo_deja_rastro_en_la_bitacora),
        ("Listado y filtros", test_listado_y_filtros),
        ("Filtro por severidad inválida", test_filtro_por_severidad_invalida),
        ("El resumen identifica la causa dominante",
         test_resumen_identifica_la_causa_dominante),
        ("Los catálogos declaran la advertencia",
         test_catalogos_declaran_la_advertencia),
        ("Inexistente da 404", test_inexistente_da_404),
    ]

    print("=" * 70)
    print("  SIG-LOG — Pruebas del módulo Incidentes (RF-33)")
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
