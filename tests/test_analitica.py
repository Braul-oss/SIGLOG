"""
SIG-LOG — Sistema Integral de Gestión Logística
tests/test_analitica.py

PRUEBAS DE LOS ENDPOINTS DE ANALÍTICA

Lo que estas pruebas vigilan no es que los endpoints respondan 200 —eso es
lo fácil— sino que **no se hayan convertido en una segunda fuente de la
verdad**.

    /analitica/kpis              debe devolver exactamente lo que calcula
                                 `analytics.kpis.calcular()`, sin retocar
                                 un solo número

    /analitica/rutas-mas-usadas  agregación en MongoDB que debe coincidir
    /analitica/causas-retraso    cifra por cifra con lo que
    /analitica/saturacion-horaria `analytics/graficas.py` calcula en pandas
                                 sobre los mismos datos

Esa última comparación es el corazón del archivo. Las gráficas agrupan con
pandas dentro de funciones que dibujan; el API agrega en el motor de base de
datos. Son dos caminos distintos hacia la misma cifra, y si alguien cambia
una definición y olvida la otra, el dashboard y el API empezarían a contar
historias diferentes. Aquí es donde eso se detecta.

Ninguna prueba escribe en la base: la analítica solo lee.
"""

from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from fastapi.testclient import TestClient

from analytics import graficas, kpis as kpis_analytics
from backend.main import app
from config import settings
from config.mongo_conexion import obtener_bd

API = settings.API_PREFIJO


def cliente_http() -> TestClient:
    return TestClient(app)


def cab(c: TestClient, usuario: str = "admin") -> dict[str, str]:
    r = c.post(f"{API}/auth/login",
               data={"username": usuario, "password": "siglog2026"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['datos']['access_token']}"}


_hechos_cache = {}


def hechos():
    """Los mismos datos que ven las gráficas, cargados una sola vez."""
    if "df" not in _hechos_cache:
        _hechos_cache["df"] = graficas.cargar_hechos(obtener_bd())
    return _hechos_cache["df"]


# ==========================================================================
# KPIs — delegación sin retoques
# ==========================================================================
def test_los_kpis_son_los_de_analytics_sin_retocar():
    """
    El API no recalcula métricas (§7.3, regla de la capa 8).

    Se compara indicador por indicador contra `analytics.kpis.calcular()`.
    Si alguien "ajustara" un valor al pasarlo por el API, aquí se ve.
    """
    c = cliente_http()
    r = c.get(f"{API}/analitica/kpis", headers=cab(c))
    assert r.status_code == 200, r.text
    datos = r.json()["datos"]

    esperados = kpis_analytics.calcular(obtener_bd())
    assert datos["total_indicadores"] == len(esperados) == 10

    for entregado, esperado in zip(datos["indicadores"], esperados):
        assert entregado["clave"] == esperado["clave"]
        assert entregado["valor"] == esperado["valor"], entregado["clave"]
        assert entregado["semaforo"] == esperado["semaforo"], entregado["clave"]
        assert entregado["lectura"] == esperado["lectura"], entregado["clave"]

    # El resumen ejecutivo de RF-29 viaja como mensaje de la respuesta
    assert r.json()["mensaje"] == datos["resumen_ejecutivo"]
    assert sum(datos["semaforos"].values()) == 10
    assert datos["umbral_retraso_min"] == settings.UMBRAL_RETRASO_MIN


def test_cada_kpi_trae_su_lectura():
    """RF-29: un número sin contexto no ayuda a decidir."""
    c = cliente_http()
    datos = c.get(f"{API}/analitica/kpis", headers=cab(c)).json()["datos"]
    for indicador in datos["indicadores"]:
        assert indicador["lectura"].strip(), indicador["clave"]
        assert indicador["semaforo"] in ("VERDE", "AMARILLO", "ROJO", "NEUTRO")
        assert indicador["titulo"].strip()
    assert len(datos["resumen_ejecutivo"]) > 100


# ==========================================================================
# RUTAS MÁS USADAS — contra la definición de la gráfica
# ==========================================================================
def test_rutas_mas_usadas_coincide_con_la_grafica():
    """
    Misma cifra por dos caminos: agregación de MongoDB contra el groupby de
    pandas que usa `graficas.rutas_mas_utilizadas`.
    """
    c = cliente_http()
    r = c.get(f"{API}/analitica/rutas-mas-usadas", headers=cab(c),
              params={"top": 10})
    assert r.status_code == 200, r.text
    entregado = {f["codigo_ruta"]: f for f in r.json()["datos"]["rutas"]}
    assert len(entregado) == 10

    df = hechos()
    dim_ruta = graficas.cargar_dimension("dim_ruta", obtener_bd())
    codigos = dict(zip(dim_ruta["_id"], dim_ruta["codigo_ruta"]))
    esperado = (df.assign(ruta=df["ruta_id"].map(codigos))
                .groupby("ruta")
                .agg(entregas=("numero_entregas", "sum"),
                     viajes=("folio_viaje", "nunique"),
                     retraso=("retraso_min", "mean"))
                .sort_values("entregas", ascending=False).head(10))

    assert set(entregado) == set(esperado.index), (
        f"El API y la gráfica eligen rutas distintas: "
        f"{set(entregado) ^ set(esperado.index)}")
    for codigo, fila in esperado.iterrows():
        obtenido = entregado[codigo]
        assert obtenido["entregas"] == int(fila["entregas"]), codigo
        assert obtenido["viajes"] == int(fila["viajes"]), codigo
        assert abs(obtenido["retraso_medio_min"] - fila["retraso"]) < 0.01, codigo


def test_rutas_mas_usadas_ordena_y_marca_el_umbral():
    c = cliente_http()
    datos = c.get(f"{API}/analitica/rutas-mas-usadas", headers=cab(c),
                  params={"top": 5}).json()["datos"]
    rutas = datos["rutas"]
    assert len(rutas) == 5
    assert [f["entregas"] for f in rutas] == sorted(
        (f["entregas"] for f in rutas), reverse=True)
    for fila in rutas:
        assert fila["sobre_umbral"] == (
            fila["retraso_medio_min"] > settings.UMBRAL_RETRASO_MIN)
        assert 0 <= fila["pct_retrasadas"] <= 100
        assert fila["codigo_ruta"], "la ruta debe venir identificada"
    assert datos["lectura"].strip()


# ==========================================================================
# CAUSAS DE RETRASO — Pareto
# ==========================================================================
def test_causas_retraso_coincide_con_el_pareto():
    c = cliente_http()
    r = c.get(f"{API}/analitica/causas-retraso", headers=cab(c))
    assert r.status_code == 200, r.text
    datos = r.json()["datos"]

    df = hechos()
    retrasadas = df[df["es_retraso"] == 1]
    conteo = (retrasadas["causa_retraso"].fillna("NO REGISTRADA")
              .value_counts())

    assert datos["total_retrasadas"] == int(conteo.sum())
    entregado = {f["causa"]: f["entregas"] for f in datos["causas"]}
    assert entregado == {c: int(v) for c, v in conteo.items()}


def test_los_pocos_vitales_incluyen_la_causa_que_cruza_el_80():
    """
    El criterio que se corrigió en PA-10: marcar solo las causas por debajo
    del 80% dejaba fuera a la dominante cuando una sola ya lo superaba.
    """
    c = cliente_http()
    datos = c.get(f"{API}/analitica/causas-retraso",
                  headers=cab(c)).json()["datos"]
    causas = datos["causas"]
    vitales = [f for f in causas if f["es_vital"]]

    assert len(vitales) == datos["pocos_vitales"] >= 1
    # Los vitales son un prefijo de la lista, no una selección dispersa
    assert causas[:len(vitales)] == vitales
    # Y el último de ellos es el que alcanza o cruza el 80%
    assert vitales[-1]["porcentaje_acumulado"] >= 80
    if len(vitales) > 1:
        assert vitales[-2]["porcentaje_acumulado"] < 80

    acumulado = 0.0
    for fila in causas:
        acumulado += fila["porcentaje"]
        assert abs(fila["porcentaje_acumulado"] - acumulado) < 0.5, fila["causa"]
    assert abs(causas[-1]["porcentaje_acumulado"] - 100) < 0.5


# ==========================================================================
# SATURACIÓN HORARIA
# ==========================================================================
def test_saturacion_coincide_con_el_heatmap():
    c = cliente_http()
    r = c.get(f"{API}/analitica/saturacion-horaria", headers=cab(c))
    assert r.status_code == 200, r.text
    datos = r.json()["datos"]

    df = hechos()
    tabla = df.pivot_table(index="franja_horaria", columns="dia_semana",
                           values="numero_entregas", aggfunc="sum")

    entregado = {(c_["franja_horaria"], c_["dia_semana"]): c_["entregas"]
                 for c_ in datos["celdas"]}
    for franja in tabla.index:
        for dia in tabla.columns:
            valor = tabla.loc[franja, dia]
            if valor == valor:                      # descarta NaN
                assert entregado[(franja, int(dia))] == int(valor), (franja, dia)

    assert datos["total_entregas"] == int(df["numero_entregas"].sum())
    pico = max(datos["celdas"], key=lambda c_: c_["entregas"])
    assert datos["franja_pico"] == pico["franja_horaria"]
    assert datos["dia_pico"] == pico["dia_semana"]


def test_la_saturacion_no_se_contradice():
    """
    Si la franja más cargada es ya la de menor retraso, la lectura no puede
    recomendar mover carga hacia ella. Fue un error real en PA-10.
    """
    c = cliente_http()
    datos = c.get(f"{API}/analitica/saturacion-horaria",
                  headers=cab(c)).json()["datos"]
    lectura = datos["lectura"]

    if datos["franja_pico"] == datos["franja_menor_retraso"]:
        assert "ya está aprovechando" in lectura, lectura
        assert "mover parte de la carga" not in lectura, lectura
    else:
        assert "mover parte de la carga" in lectura, lectura
        # Y el destino sugerido es de verdad la franja de menor retraso
        assert (datos["franja_menor_retraso"].replace("_", " ").lower()
                in lectura), lectura

    menor = min(datos["por_franja"], key=lambda f: f["retraso_medio_min"])
    assert menor["franja_horaria"] == datos["franja_menor_retraso"]


# ==========================================================================
# PERMISOS Y CONTRATO
# ==========================================================================
def test_sin_sesion_no_hay_analitica():
    c = cliente_http()
    for ruta in ("kpis", "rutas-mas-usadas", "causas-retraso",
                 "saturacion-horaria"):
        assert c.get(f"{API}/analitica/{ruta}").status_code == 401, ruta


def test_el_analista_consulta_todo():
    """El rol que no toca la operación existe justamente para leer esto."""
    c = cliente_http()
    cabecera = cab(c, "analista")
    for ruta in ("kpis", "rutas-mas-usadas", "causas-retraso",
                 "saturacion-horaria"):
        r = c.get(f"{API}/analitica/{ruta}", headers=cabecera)
        assert r.status_code == 200, f"{ruta}: {r.text}"
        cuerpo = r.json()
        assert cuerpo["exito"] is True
        assert cuerpo["mensaje"].strip(), ruta


def test_el_top_se_valida():
    c = cliente_http()
    cabecera = cab(c)
    assert c.get(f"{API}/analitica/rutas-mas-usadas", headers=cabecera,
                 params={"top": 0}).status_code == 422
    assert c.get(f"{API}/analitica/rutas-mas-usadas", headers=cabecera,
                 params={"top": 500}).status_code == 422


if __name__ == "__main__":
    pruebas = [
        ("Los KPIs son los de analytics, sin retocar",
         test_los_kpis_son_los_de_analytics_sin_retocar),
        ("Cada KPI trae su lectura (RF-29)", test_cada_kpi_trae_su_lectura),
        ("Rutas más usadas coincide con la gráfica",
         test_rutas_mas_usadas_coincide_con_la_grafica),
        ("Rutas más usadas ordena y marca el umbral",
         test_rutas_mas_usadas_ordena_y_marca_el_umbral),
        ("Causas de retraso coincide con el Pareto",
         test_causas_retraso_coincide_con_el_pareto),
        ("Los pocos vitales incluyen la causa que cruza el 80%",
         test_los_pocos_vitales_incluyen_la_causa_que_cruza_el_80),
        ("Saturación coincide con el heatmap",
         test_saturacion_coincide_con_el_heatmap),
        ("La saturación no se contradice", test_la_saturacion_no_se_contradice),
        ("Sin sesión no hay analítica", test_sin_sesion_no_hay_analitica),
        ("El analista consulta todo", test_el_analista_consulta_todo),
        ("El parámetro top se valida", test_el_top_se_valida),
    ]

    print("=" * 70)
    print("  SIG-LOG — Pruebas de los endpoints de Analítica")
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
    print("  La analítica solo lee: no hay escenario que limpiar.")
    print("=" * 70)
    print(f"  Resultado: {len(pruebas) - fallos}/{len(pruebas)} pruebas correctas")
    print("=" * 70)
    sys.exit(1 if fallos else 0)
