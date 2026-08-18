"""
SIG-LOG — Sistema Integral de Gestión Logística
tests/test_viajes.py

PRUEBAS DEL MÓDULO VIAJES

Este módulo es donde convergen los anteriores, así que las pruebas
comprueban tanto sus reglas propias como que las promesas de los otros se
cumplan de verdad:

    RN-J1  el folio VJE-AAAAMMDD-NNNN lo genera el sistema
    RN-J2  el viaje avanza y nunca retrocede
    RN-J3  ruta activa, vehículo disponible, operador con licencia vigente,
           y nadie en dos jornadas a la vez
    RN-J4  una ruta se ejecuta una vez al día
    RN-J5  el odómetro no baja al salir
    RN-J6  el odómetro final supera al inicial y el regreso a la salida
    RN-J7  no hay borrado ni baja lógica: solo cancelación con motivo

Y sobre todo:
  · que programar exija licencia vigente, cobrando RN-O3;
  · que finalizar ACTUALICE el odómetro del vehículo, cumpliendo lo que
    RN-V6 prometió al prohibir capturarlo a mano.

Las pruebas crean su propio escenario —ruta, vehículo y operador nuevos—
para no tocar los datos del seed, y lo borran al terminar.
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
MARCA = "ZZ-VIAJE"
PLACA = "ZZV"

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


def limpiar() -> dict[str, int]:
    """Borra todo el escenario de prueba, en orden inverso a su creación."""
    bd = obtener_bd()
    rutas = [r["_id"] for r in bd["rutas"].find(
        {"nombre": {"$regex": f"^{MARCA}"}}, {"_id": 1})]
    borrados = {
        "viajes": bd["viajes"].delete_many(
            {"ruta_id": {"$in": rutas}}).deleted_count if rutas else 0,
        "rutas": bd["rutas"].delete_many(
            {"nombre": {"$regex": f"^{MARCA}"}}).deleted_count,
        "vehiculos": bd["vehiculos"].delete_many(
            {"placa": {"$regex": f"^{PLACA}"}}).deleted_count,
        "operadores": bd["operadores"].delete_many(
            {"nombre_completo": {"$regex": f"^{MARCA}"}}).deleted_count,
    }
    return borrados


try:
    import pytest

    @pytest.fixture(scope="module", autouse=True)
    def _limpiar_al_terminar():
        yield
        limpiar()
except ImportError:                    # pragma: no cover
    pass


_usados: set[str] = set()


def _unico(prefijo: str) -> str:
    while True:
        valor = f"{prefijo}{random.randint(1000, 9999)}"
        if valor not in _usados:
            _usados.add(valor)
            return valor


def crear_ruta(c, cabecera) -> dict:
    bd = obtener_bd()
    cliente = bd["clientes"].find_one({"activo": {"$ne": False}})
    principal = next((d for d in cliente["direcciones"] if d.get("principal")),
                     cliente["direcciones"][0])
    r = c.post(f"{API}/rutas", headers=cabecera, json={
        "nombre": f"{MARCA} Ruta {_unico('')}", "zona": "NORTE",
        "origen": ORIGEN,
        "paradas": [{"cliente_id": str(cliente["_id"]),
                     "direccion_alias": principal["alias"],
                     "distancia_desde_anterior_km": 12.0,
                     "tiempo_estimado_min": 35.0}],
        "dias_operacion": ["LUNES", "MARTES", "MIERCOLES", "JUEVES", "VIERNES"],
        "hora_salida_programada": "06:30"})
    assert r.status_code == 201, r.text
    return r.json()["datos"]


def crear_vehiculo(c, cabecera, odometro: float = 50_000) -> dict:
    r = c.post(f"{API}/vehiculos", headers=cabecera, json={
        "placa": f"{PLACA}-{random.randint(1000, 9999)}",
        "marca": "Prueba", "modelo": "Viaje", "anio": 2023,
        "tipo_vehiculo": "MEDIANO", "capacidad_tanque_litros": 120,
        "rendimiento_nominal_km_l": 7.0, "odometro_actual_km": odometro})
    assert r.status_code == 201, r.text
    return r.json()["datos"]


def crear_operador(c, cabecera, *, vigencia: date | None = None) -> dict:
    r = c.post(f"{API}/operadores", headers=cabecera, json={
        "nombre_completo": f"{MARCA} Operador {_unico('')}",
        "licencia": {"numero": _unico("ZV"), "tipo": "C",
                     "vigencia": str(vigencia or date.today()
                                     + timedelta(days=400))},
        "fecha_ingreso": str(date.today() - timedelta(days=300))})
    assert r.status_code == 201, r.text
    return r.json()["datos"]


def escenario(c, cabecera, *, odometro: float = 50_000,
              vigencia: date | None = None) -> dict:
    """Ruta, vehículo y operador nuevos, listos para programar un viaje."""
    return {"ruta": crear_ruta(c, cabecera),
            "vehiculo": crear_vehiculo(c, cabecera, odometro),
            "operador": crear_operador(c, cabecera, vigencia=vigencia)}


def programar(c, cabecera, esc: dict, dia: date | None = None):
    return c.post(f"{API}/viajes", headers=cabecera, json={
        "ruta_id": esc["ruta"]["id"], "vehiculo_id": esc["vehiculo"]["id"],
        "operador_id": esc["operador"]["id"],
        "fecha": str(dia or date.today())})


# ==========================================================================
# PERMISOS
# ==========================================================================
def test_sin_sesion_no_se_consulta():
    with cliente_http() as c:
        assert c.get(f"{API}/viajes").status_code == 401


def test_cualquier_sesion_consulta():
    with cliente_http() as c:
        for u in ("admin", "despachador", "analista"):
            assert c.get(f"{API}/viajes", headers=cab(c, u)).status_code == 200


def test_el_despachador_opera_y_el_analista_no():
    """
    Este es el módulo del despachador: el §3 le asigna registrar jornadas,
    horas reales e incidentes.
    """
    with cliente_http() as c:
        cabecera = cab(c)
        esc = escenario(c, cabecera)
        r = programar(c, cab(c, "despachador"), esc)
        assert r.status_code == 201, r.text

        esc2 = escenario(c, cabecera)
        r2 = programar(c, cab(c, "analista"), esc2)
    assert r2.status_code == 403


# ==========================================================================
# PROGRAMAR  (RN-J1, RN-J3, RN-J4)
# ==========================================================================
def test_programar_asigna_folio_fechado():
    with cliente_http() as c:
        cabecera = cab(c)
        esc = escenario(c, cabecera)
        v = programar(c, cabecera, esc).json()["datos"]
    assert v["folio_viaje"].startswith(f"VJE-{date.today():%Y%m%d}-")
    assert v["estatus"] == "PROGRAMADO"
    assert v["total_entregas_programadas"] == 1
    assert v["hora_salida_programada"].endswith("06:30:00Z") or \
        "06:30" in v["hora_salida_programada"]
    assert v["km_recorridos"] is None


def test_no_se_programa_con_operador_inactivo():
    """
    Un operador dado de alta con la licencia ya vencida nace INACTIVO
    (RN-O3), y esa condición lo excluye de cualquier jornada.
    """
    with cliente_http() as c:
        cabecera = cab(c)
        esc = escenario(c, cabecera, vigencia=date.today() - timedelta(days=5))
        assert esc["operador"]["estado"] == "INACTIVO"
        r = programar(c, cabecera, esc)
    assert r.status_code == 409, r.text
    assert r.json()["codigo_error"] == "REGLA_J3"


def test_no_se_programa_con_licencia_vencida():
    """
    RN-J3 cobrando RN-O3 en el caso que de verdad importa: un operador que
    sigue ACTIVO pero cuya licencia caducó mientras tanto.

    Es la situación real —las licencias vencen solas, sin que nadie toque
    el estado— y demuestra que la comprobación de licencia no es
    redundante con la de estado: sin ella, el sistema programaría a alguien
    que no puede conducir legalmente.
    """
    with cliente_http() as c:
        cabecera = cab(c)
        esc = escenario(c, cabecera)
        assert esc["operador"]["estado"] == "ACTIVO"

        # La licencia caduca sin que el estado cambie
        r = c.put(f"{API}/operadores/{esc['operador']['id']}", headers=cabecera,
                  json={"licencia": {
                      "numero": esc["operador"]["licencia"]["numero"],
                      "tipo": "C",
                      "vigencia": str(date.today() - timedelta(days=1))}})
        assert r.status_code == 200, r.text
        assert r.json()["datos"]["estado"] == "ACTIVO", (
            "el operador sigue activo; solo venció su licencia")
        assert r.json()["datos"]["licencia_vigente"] is False

        respuesta = programar(c, cabecera, esc)
    assert respuesta.status_code == 409, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["codigo_error"] == "REGLA_J3"
    assert "licencia" in cuerpo["mensaje"].lower()
    assert cuerpo["detalles"][0]["vigencia"]


def test_no_se_programa_con_vehiculo_en_mantenimiento():
    with cliente_http() as c:
        cabecera = cab(c)
        esc = escenario(c, cabecera)
        c.patch(f"{API}/vehiculos/{esc['vehiculo']['id']}/estado",
                headers=cabecera, json={"estado_operativo": "EN_MANTENIMIENTO"})
        r = programar(c, cabecera, esc)
    assert r.status_code == 409, r.text
    assert r.json()["codigo_error"] == "REGLA_J3"
    assert r.json()["detalles"][0]["estado_operativo"] == "EN_MANTENIMIENTO"


def test_no_se_programa_dos_veces_la_misma_ruta_el_mismo_dia():
    """RN-J4."""
    with cliente_http() as c:
        cabecera = cab(c)
        esc = escenario(c, cabecera)
        assert programar(c, cabecera, esc).status_code == 201

        otro = {**esc, "vehiculo": crear_vehiculo(c, cabecera),
                "operador": crear_operador(c, cabecera)}
        r = programar(c, cabecera, otro)
    assert r.status_code == 409, r.text
    assert r.json()["codigo_error"] == "REGLA_J4"
    assert r.json()["detalles"][0]["folio_existente"]


def test_un_vehiculo_no_esta_en_dos_jornadas():
    """RN-J3: nadie puede estar en dos sitios a la vez."""
    with cliente_http() as c:
        cabecera = cab(c)
        esc = escenario(c, cabecera)
        assert programar(c, cabecera, esc).status_code == 201

        # Otra ruta y otro operador, pero el MISMO vehículo
        otro = {"ruta": crear_ruta(c, cabecera),
                "vehiculo": esc["vehiculo"],
                "operador": crear_operador(c, cabecera)}
        r = programar(c, cabecera, otro)
    assert r.status_code == 409, r.text
    assert r.json()["codigo_error"] == "REGLA_J3"
    assert r.json()["detalles"][0]["folio_abierto"]


def test_un_operador_no_esta_en_dos_jornadas():
    with cliente_http() as c:
        cabecera = cab(c)
        esc = escenario(c, cabecera)
        assert programar(c, cabecera, esc).status_code == 201

        otro = {"ruta": crear_ruta(c, cabecera),
                "vehiculo": crear_vehiculo(c, cabecera),
                "operador": esc["operador"]}
        r = programar(c, cabecera, otro)
    assert r.status_code == 409, r.text
    assert r.json()["codigo_error"] == "REGLA_J3"


def test_no_se_programa_con_ruta_dada_de_baja():
    with cliente_http() as c:
        cabecera = cab(c)
        esc = escenario(c, cabecera)
        c.delete(f"{API}/rutas/{esc['ruta']['id']}", headers=cabecera)
        r = programar(c, cabecera, esc)
    assert r.status_code == 409, r.text
    assert r.json()["codigo_error"] == "REGLA_J3"


# ==========================================================================
# INICIAR  (RN-J5)
# ==========================================================================
def test_iniciar_calcula_el_retraso_y_pone_el_vehiculo_en_ruta():
    with cliente_http() as c:
        cabecera = cab(c)
        esc = escenario(c, cabecera, odometro=50_000)
        viaje = programar(c, cabecera, esc).json()["datos"]

        # Sale dos horas después de las 06:30 programadas
        salida = datetime.combine(date.today(),
                                  datetime.min.time()).replace(
            hour=8, minute=30, tzinfo=timezone.utc)
        r = c.patch(f"{API}/viajes/{viaje['id']}/iniciar", headers=cabecera,
                    json={"hora_salida_real": salida.isoformat(),
                          "odometro_inicial_km": 50_000})
        assert r.status_code == 200, r.text
        datos = r.json()["datos"]
        assert datos["estatus"] == "EN_CURSO"
        assert datos["retraso_salida_min"] == 120.0

        vehiculo = c.get(f"{API}/vehiculos/{esc['vehiculo']['id']}",
                         headers=cabecera).json()["datos"]
    assert vehiculo["estado_operativo"] == "EN_RUTA"


def test_el_odometro_no_baja_al_salir():
    """RN-J5."""
    with cliente_http() as c:
        cabecera = cab(c)
        esc = escenario(c, cabecera, odometro=80_000)
        viaje = programar(c, cabecera, esc).json()["datos"]
        r = c.patch(f"{API}/viajes/{viaje['id']}/iniciar", headers=cabecera,
                    json={"odometro_inicial_km": 79_000})
    assert r.status_code == 409, r.text
    cuerpo = r.json()
    assert cuerpo["codigo_error"] == "REGLA_J5"
    assert cuerpo["detalles"][0]["odometro_registrado"] == 80_000


def test_no_se_inicia_dos_veces():
    with cliente_http() as c:
        cabecera = cab(c)
        esc = escenario(c, cabecera)
        viaje = programar(c, cabecera, esc).json()["datos"]
        c.patch(f"{API}/viajes/{viaje['id']}/iniciar", headers=cabecera,
                json={"odometro_inicial_km": 50_000})
        r = c.patch(f"{API}/viajes/{viaje['id']}/iniciar", headers=cabecera,
                    json={"odometro_inicial_km": 50_100})
    assert r.status_code == 409
    assert r.json()["codigo_error"] == "REGLA_J2"


# ==========================================================================
# FINALIZAR  (RN-J6) — cumple la promesa de RN-V6
# ==========================================================================
def test_finalizar_calcula_y_actualiza_el_odometro_del_vehiculo():
    """
    La prueba central del módulo: cerrar el viaje ESCRIBE el odómetro del
    vehículo. Es lo que RN-V6 prometió al prohibir capturarlo a mano.
    """
    with cliente_http() as c:
        cabecera = cab(c)
        esc = escenario(c, cabecera, odometro=50_000)
        viaje = programar(c, cabecera, esc).json()["datos"]

        salida = datetime.now(timezone.utc) - timedelta(hours=4)
        c.patch(f"{API}/viajes/{viaje['id']}/iniciar", headers=cabecera,
                json={"hora_salida_real": salida.isoformat(),
                      "odometro_inicial_km": 50_000})

        regreso = salida + timedelta(hours=3, minutes=30)
        r = c.patch(f"{API}/viajes/{viaje['id']}/finalizar", headers=cabecera,
                    json={"hora_regreso_real": regreso.isoformat(),
                          "odometro_final_km": 50_120,
                          "total_entregas_completadas": 1})
        assert r.status_code == 200, r.text
        datos = r.json()["datos"]
        assert datos["estatus"] == "FINALIZADO"
        assert datos["km_recorridos"] == 120.0
        assert datos["duracion_real_min"] == 210.0
        assert datos["total_entregas_completadas"] == 1

        vehiculo = c.get(f"{API}/vehiculos/{esc['vehiculo']['id']}",
                         headers=cabecera).json()["datos"]
    assert vehiculo["estado_operativo"] == "DISPONIBLE"
    assert vehiculo["odometro_actual_km"] == 50_120, (
        "el cierre del viaje debe actualizar el odómetro del vehículo (RN-V6)")


def test_odometro_final_debe_superar_al_inicial():
    """RN-J6."""
    with cliente_http() as c:
        cabecera = cab(c)
        esc = escenario(c, cabecera, odometro=50_000)
        viaje = programar(c, cabecera, esc).json()["datos"]
        c.patch(f"{API}/viajes/{viaje['id']}/iniciar", headers=cabecera,
                json={"odometro_inicial_km": 50_000})
        r = c.patch(f"{API}/viajes/{viaje['id']}/finalizar", headers=cabecera,
                    json={"odometro_final_km": 49_900})
    assert r.status_code == 409, r.text
    assert r.json()["codigo_error"] == "REGLA_J6"


def test_no_se_finaliza_sin_haber_salido():
    with cliente_http() as c:
        cabecera = cab(c)
        esc = escenario(c, cabecera)
        viaje = programar(c, cabecera, esc).json()["datos"]
        r = c.patch(f"{API}/viajes/{viaje['id']}/finalizar", headers=cabecera,
                    json={"odometro_final_km": 50_100})
    assert r.status_code == 409, r.text
    assert r.json()["codigo_error"] == "REGLA_J2"


def test_las_entregas_completadas_se_cuentan_solas():
    """Si no se declaran, se cuentan de las entregas registradas del viaje."""
    with cliente_http() as c:
        cabecera = cab(c)
        esc = escenario(c, cabecera, odometro=10_000)
        viaje = programar(c, cabecera, esc).json()["datos"]
        c.patch(f"{API}/viajes/{viaje['id']}/iniciar", headers=cabecera,
                json={"odometro_inicial_km": 10_000})
        r = c.patch(f"{API}/viajes/{viaje['id']}/finalizar", headers=cabecera,
                    json={"odometro_final_km": 10_050})
    assert r.status_code == 200, r.text
    assert r.json()["datos"]["total_entregas_completadas"] == 0


# ==========================================================================
# CANCELAR Y RN-J2 / RN-J7
# ==========================================================================
def test_cancelar_exige_motivo_y_libera_la_unidad():
    with cliente_http() as c:
        cabecera = cab(c)
        esc = escenario(c, cabecera)
        viaje = programar(c, cabecera, esc).json()["datos"]
        c.patch(f"{API}/viajes/{viaje['id']}/iniciar", headers=cabecera,
                json={"odometro_inicial_km": 50_000})

        sin_motivo = c.patch(f"{API}/viajes/{viaje['id']}/cancelar",
                             headers=cabecera, json={"motivo": "x"})
        assert sin_motivo.status_code == 422, "el motivo tiene mínimo de longitud"

        r = c.patch(f"{API}/viajes/{viaje['id']}/cancelar", headers=cabecera,
                    json={"motivo": "Bloqueo de la vialidad principal"})
        assert r.status_code == 200, r.text
        assert r.json()["datos"]["estatus"] == "CANCELADO"
        assert r.json()["datos"]["motivo_cancelacion"]

        vehiculo = c.get(f"{API}/vehiculos/{esc['vehiculo']['id']}",
                         headers=cabecera).json()["datos"]
    assert vehiculo["estado_operativo"] == "DISPONIBLE", (
        "cancelar un viaje en curso debe liberar la unidad")


def test_un_viaje_cerrado_no_se_reabre():
    """RN-J2: cada documento es el histórico y no se reescribe."""
    with cliente_http() as c:
        cabecera = cab(c)
        esc = escenario(c, cabecera, odometro=20_000)
        viaje = programar(c, cabecera, esc).json()["datos"]
        c.patch(f"{API}/viajes/{viaje['id']}/iniciar", headers=cabecera,
                json={"odometro_inicial_km": 20_000})
        c.patch(f"{API}/viajes/{viaje['id']}/finalizar", headers=cabecera,
                json={"odometro_final_km": 20_080})

        for accion, cuerpo in (("iniciar", {"odometro_inicial_km": 20_000}),
                               ("finalizar", {"odometro_final_km": 20_200}),
                               ("cancelar", {"motivo": "Ya no aplica el viaje"})):
            r = c.patch(f"{API}/viajes/{viaje['id']}/{accion}",
                        headers=cabecera, json=cuerpo)
            assert r.status_code == 409, f"{accion}: {r.status_code}"
            assert r.json()["codigo_error"] == "REGLA_J2"
            assert r.json()["detalles"][0]["transiciones_validas"] == []


def test_no_existe_borrado_de_viajes():
    """RN-J7: es la única colección sin baja lógica."""
    with cliente_http() as c:
        cabecera = cab(c)
        esc = escenario(c, cabecera)
        viaje = programar(c, cabecera, esc).json()["datos"]
        r = c.delete(f"{API}/viajes/{viaje['id']}", headers=cabecera)
    assert r.status_code == 405, "no debe existir DELETE en viajes"


# ==========================================================================
# CONSULTA
# ==========================================================================
def test_listado_y_filtros():
    with cliente_http() as c:
        cabecera = cab(c)
        cuerpo = c.get(f"{API}/viajes?tamano=5", headers=cabecera).json()
        assert cuerpo["total"] >= 2900, "deberían estar los del seed"

        finalizados = c.get(f"{API}/viajes?estatus=FINALIZADO&tamano=3",
                            headers=cabecera).json()
    assert all(v["estatus"] == "FINALIZADO" for v in finalizados["datos"])


def test_filtro_por_fechas():
    with cliente_http() as c:
        cabecera = cab(c)
        cuerpo = c.get(f"{API}/viajes?fecha_desde=2026-02-01"
                       f"&fecha_hasta=2026-02-28&tamano=5",
                       headers=cabecera).json()
    assert cuerpo["total"] >= 1
    for v in cuerpo["datos"]:
        assert v["fecha"].startswith("2026-02")


def test_estatus_invalido():
    with cliente_http() as c:
        r = c.get(f"{API}/viajes?estatus=VOLANDO", headers=cab(c))
    assert r.status_code == 409


def test_catalogos_y_resumen():
    with cliente_http() as c:
        cabecera = cab(c)
        catalogos = c.get(f"{API}/viajes/catalogos",
                          headers=cabecera).json()["datos"]
        resumen = c.get(f"{API}/viajes/resumen", headers=cabecera).json()["datos"]
    assert catalogos["transiciones"]["FINALIZADO"] == []
    assert "no se borra" in catalogos["nota"]
    assert resumen["total"] == sum(resumen["por_estatus"].values())


def test_inexistente_da_404():
    with cliente_http() as c:
        r = c.get(f"{API}/viajes/6a83893489a0d3691e05ffff", headers=cab(c))
    assert r.status_code == 404


# ==========================================================================
# Modo manual (sin pytest)
# ==========================================================================
if __name__ == "__main__":
    pruebas = [
        ("Sin sesión no se consulta", test_sin_sesion_no_se_consulta),
        ("Cualquier sesión consulta", test_cualquier_sesion_consulta),
        ("El despachador opera y el analista no",
         test_el_despachador_opera_y_el_analista_no),
        ("Programar asigna folio fechado (RN-J1)",
         test_programar_asigna_folio_fechado),
        ("No se programa con operador inactivo",
         test_no_se_programa_con_operador_inactivo),
        ("No se programa con licencia vencida (RN-J3 / RN-O3)",
         test_no_se_programa_con_licencia_vencida),
        ("No se programa con vehículo en mantenimiento",
         test_no_se_programa_con_vehiculo_en_mantenimiento),
        ("No se programa dos veces la misma ruta el mismo día (RN-J4)",
         test_no_se_programa_dos_veces_la_misma_ruta_el_mismo_dia),
        ("Un vehículo no está en dos jornadas (RN-J3)",
         test_un_vehiculo_no_esta_en_dos_jornadas),
        ("Un operador no está en dos jornadas (RN-J3)",
         test_un_operador_no_esta_en_dos_jornadas),
        ("No se programa con ruta dada de baja",
         test_no_se_programa_con_ruta_dada_de_baja),
        ("Iniciar calcula el retraso y pone el vehículo EN_RUTA",
         test_iniciar_calcula_el_retraso_y_pone_el_vehiculo_en_ruta),
        ("El odómetro no baja al salir (RN-J5)",
         test_el_odometro_no_baja_al_salir),
        ("No se inicia dos veces (RN-J2)", test_no_se_inicia_dos_veces),
        ("Finalizar calcula y actualiza el odómetro del vehículo (RN-V6)",
         test_finalizar_calcula_y_actualiza_el_odometro_del_vehiculo),
        ("El odómetro final debe superar al inicial (RN-J6)",
         test_odometro_final_debe_superar_al_inicial),
        ("No se finaliza sin haber salido", test_no_se_finaliza_sin_haber_salido),
        ("Las entregas completadas se cuentan solas",
         test_las_entregas_completadas_se_cuentan_solas),
        ("Cancelar exige motivo y libera la unidad",
         test_cancelar_exige_motivo_y_libera_la_unidad),
        ("Un viaje cerrado no se reabre (RN-J2)",
         test_un_viaje_cerrado_no_se_reabre),
        ("No existe borrado de viajes (RN-J7)", test_no_existe_borrado_de_viajes),
        ("Listado y filtros", test_listado_y_filtros),
        ("Filtro por fechas", test_filtro_por_fechas),
        ("Estatus inválido", test_estatus_invalido),
        ("Catálogos y resumen", test_catalogos_y_resumen),
        ("Inexistente da 404", test_inexistente_da_404),
    ]

    print("=" * 70)
    print("  SIG-LOG — Pruebas del módulo Viajes")
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
    print(f"  Escenario de prueba eliminado: {limpiar()}")
    print("=" * 70)
    print(f"  Resultado: {len(pruebas) - fallos}/{len(pruebas)} pruebas correctas")
    print("=" * 70)
    sys.exit(1 if fallos else 0)
