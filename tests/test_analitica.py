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
# DESEMPEÑO DE LA FLOTILLA
# ==========================================================================
def test_la_flotilla_cruza_costos_con_operacion():
    """
    Los costos vienen de `dim_vehiculo` y las entregas de `hecho_entrega`.
    Si el cruce se rompiera, la pantalla mostraría unidades caras sin trabajo
    o al revés, y nadie lo notaría a simple vista.
    """
    c = cliente_http()
    r = c.get(f"{API}/analitica/vehiculos?orden=costo&top=100",
              headers=cab(c))
    assert r.status_code == 200, r.text
    datos = r.json()["datos"]
    assert datos["flotilla"] == 20, "las 20 unidades de la flotilla"

    bd = obtener_bd()
    dimension = {d["_id"]: d for d in bd["dim_vehiculo"].find({})}
    for v in datos["vehiculos"]:
        origen = dimension[v["vehiculo_id"]]
        assert v["codigo_vehiculo"] == origen["codigo_vehiculo"]
        assert abs(v["costo_total"] - origen["costo_total_operacion"]) < 0.01
        assert abs(v["litros"] - origen["litros"]) < 0.1
        # El costo total es la suma de sus dos componentes, no un tercer dato
        assert abs(v["costo_total"] -
                   (v["costo_combustible"] + v["costo_mantenimiento"])) < 0.05

    # Las entregas del cruce deben coincidir con las del hecho
    esperadas = {f["_id"]: f["n"] for f in bd["hecho_entrega"].aggregate([
        {"$match": {"calidad_dato": "OK"}},
        {"$group": {"_id": "$vehiculo_id", "n": {"$sum": "$numero_entregas"}}},
    ])}
    for v in datos["vehiculos"]:
        assert v["entregas"] == esperadas.get(v["vehiculo_id"], 0), (
            v["codigo_vehiculo"])


def test_la_flotilla_se_identifica_por_su_codigo_no_por_su_id():
    """
    FASE de presentación: el identificador interno no puede ser lo que
    represente a una unidad. Cada fila trae código, marca, modelo y placa.
    """
    c = cliente_http()
    datos = c.get(f"{API}/analitica/vehiculos?top=5",
                  headers=cab(c)).json()["datos"]
    for v in datos["vehiculos"]:
        assert v["codigo_vehiculo"].startswith("VEH-"), v
        assert v["descripcion"].strip(), "falta marca y modelo"
        assert v["placa"], "falta la placa"
    # Y la lectura habla del código, no del identificador
    assert "VEH-" in datos["lectura"]
    assert datos["vehiculos"][0]["vehiculo_id"] not in datos["lectura"]


def test_cada_criterio_de_flotilla_ordena_por_lo_que_dice():
    c = cliente_http()
    cabecera = cab(c)
    campos = {"costo": "costo_total", "combustible": "litros",
              "entregas": "entregas", "uso": "km_recorridos"}
    for criterio, campo in campos.items():
        filas = c.get(f"{API}/analitica/vehiculos?orden={criterio}&top=10",
                      headers=cabecera).json()["datos"]["vehiculos"]
        valores = [f[campo] for f in filas]
        assert valores == sorted(valores, reverse=True), criterio

    # El rendimiento va al revés: primero el peor, que es el que interesa
    filas = c.get(f"{API}/analitica/vehiculos?orden=rendimiento&top=10",
                  headers=cabecera).json()["datos"]["vehiculos"]
    valores = [f["rendimiento_real_km_l"] for f in filas]
    assert valores == sorted(valores), "el peor rendimiento debe ir primero"

    assert c.get(f"{API}/analitica/vehiculos?orden=inventado",
                 headers=cabecera).status_code == 409


def test_los_totales_de_flotilla_cuadran_con_las_filas():
    c = cliente_http()
    datos = c.get(f"{API}/analitica/vehiculos?top=100",
                  headers=cab(c)).json()["datos"]
    filas, totales = datos["vehiculos"], datos["totales"]
    assert abs(totales["costo_total"] -
               sum(f["costo_total"] for f in filas)) < 0.5
    assert abs(totales["litros"] - sum(f["litros"] for f in filas)) < 0.5
    assert totales["entregas"] == sum(f["entregas"] for f in filas)
    assert totales["en_mantenimiento"] == sum(
        1 for f in filas if f["en_mantenimiento"])


# ==========================================================================
# DESEMPEÑO DE LOS OPERADORES
# ==========================================================================
def test_los_operadores_salen_de_su_dimension():
    c = cliente_http()
    r = c.get(f"{API}/analitica/operadores?orden=entregas&top=50",
              headers=cab(c))
    assert r.status_code == 200, r.text
    datos = r.json()["datos"]
    assert datos["plantilla"] == 24

    bd = obtener_bd()
    origen = {d["_id"]: d for d in bd["dim_operador"].find({})}
    for o in datos["operadores"]:
        d = origen[o["operador_id"]]
        assert o["nombre"] == d["nombre_completo"]
        assert o["entregas"] == int(d["entregas_medibles"])
        assert o["pct_a_tiempo"] == d["porcentaje_entregas_a_tiempo"]

    entregas = [o["entregas"] for o in datos["operadores"]]
    assert entregas == sorted(entregas, reverse=True)
    # La media de la plantilla sitúa a cada uno frente al resto
    assert 0 < datos["puntualidad_media_pct"] <= 100


def test_el_operador_se_identifica_por_su_nombre():
    """Un identificador no le dice nada a quien lee un informe."""
    c = cliente_http()
    datos = c.get(f"{API}/analitica/operadores?top=3",
                  headers=cab(c)).json()["datos"]
    for o in datos["operadores"]:
        assert o["nombre"].strip()
        assert o["codigo_operador"].startswith("OPE-")
    assert "OPE-" in datos["lectura"]


# ==========================================================================
# TENDENCIA
# ==========================================================================
def test_la_tendencia_cubre_todo_el_periodo():
    c = cliente_http()
    r = c.get(f"{API}/analitica/tendencia?agrupacion=semana", headers=cab(c))
    assert r.status_code == 200, r.text
    datos = r.json()["datos"]
    puntos = datos["puntos"]
    assert len(puntos) >= 20, "seis meses dan más de veinte semanas"

    # Ordenados y sin huecos de formato
    fechas = [p["inicio"] for p in puntos]
    assert fechas == sorted(fechas)
    for p in puntos:
        assert p["etiqueta"].strip()
        assert p["entregas"] > 0
        assert 0 <= p["pct_retrasadas"] <= 100

    # El total de la serie es el total del periodo: no se pierde ni se
    # duplica ninguna entrega al agrupar
    df = hechos()
    assert sum(p["entregas"] for p in puntos) == int(df["numero_entregas"].sum())

    assert c.get(f"{API}/analitica/tendencia?agrupacion=trimestre",
                 headers=cab(c)).status_code == 409


def test_la_tendencia_por_mes_agrupa_lo_mismo():
    c = cliente_http()
    cabecera = cab(c)
    semanas = c.get(f"{API}/analitica/tendencia?agrupacion=semana",
                    headers=cabecera).json()["datos"]
    meses = c.get(f"{API}/analitica/tendencia?agrupacion=mes",
                  headers=cabecera).json()["datos"]
    assert len(meses["puntos"]) < len(semanas["puntos"])
    assert (sum(p["entregas"] for p in meses["puntos"]) ==
            sum(p["entregas"] for p in semanas["puntos"]))


# ==========================================================================
# CRITERIOS DE ORDEN EN RUTAS
# ==========================================================================
def test_las_rutas_responden_tres_preguntas_distintas():
    """
    Volumen, retraso e incidencia no son la misma pregunta, y la respuesta
    tampoco tiene por qué ser la misma ruta.
    """
    c = cliente_http()
    cabecera = cab(c)
    resultados = {}
    for orden in ("volumen", "retraso", "incidencia"):
        r = c.get(f"{API}/analitica/rutas-mas-usadas?orden={orden}&top=10",
                  headers=cabecera)
        assert r.status_code == 200, f"{orden}: {r.text}"
        resultados[orden] = r.json()["datos"]

    assert [f["entregas"] for f in resultados["volumen"]["rutas"]] == sorted(
        (f["entregas"] for f in resultados["volumen"]["rutas"]), reverse=True)
    assert [f["retraso_medio_min"] for f in resultados["retraso"]["rutas"]] == \
        sorted((f["retraso_medio_min"] for f in resultados["retraso"]["rutas"]),
               reverse=True)
    assert [f["pct_retrasadas"] for f in resultados["incidencia"]["rutas"]] == \
        sorted((f["pct_retrasadas"] for f in resultados["incidencia"]["rutas"]),
               reverse=True)

    assert c.get(f"{API}/analitica/rutas-mas-usadas?orden=inventado",
                 headers=cabecera).status_code == 409


def test_los_promedios_excluyen_las_muestras_pequenas():
    """
    Una ruta con pocas entregas y un mal día encabezaría el ranking de
    retrasos sin que eso significara nada. Ordenar por volumen, en cambio,
    no necesita ese corte: ahí el tamaño ES la medida.
    """
    c = cliente_http()
    cabecera = cab(c)
    por_retraso = c.get(f"{API}/analitica/rutas-mas-usadas?orden=retraso&top=50",
                        headers=cabecera).json()["datos"]
    assert por_retraso["minimo_entregas"] > 0
    for fila in por_retraso["rutas"]:
        assert fila["entregas"] >= por_retraso["minimo_entregas"], fila

    por_volumen = c.get(f"{API}/analitica/rutas-mas-usadas?orden=volumen&top=50",
                        headers=cabecera).json()["datos"]
    assert por_volumen["minimo_entregas"] == 0


# ==========================================================================
# EL PERIODO SE PUBLICA
# ==========================================================================
def test_toda_consulta_dice_de_que_periodo_habla():
    """
    Una cifra sin periodo no se puede interpretar: «1,127 entregas» dice
    cosas distintas si son de una semana o de seis meses.
    """
    c = cliente_http()
    cabecera = cab(c)
    for ruta in ("/analitica/rutas-mas-usadas", "/analitica/vehiculos",
                 "/analitica/operadores", "/analitica/tendencia"):
        datos = c.get(API + ruta, headers=cabecera).json()["datos"]
        periodo = datos.get("periodo")
        assert periodo, ruta
        assert periodo["desde"] and periodo["hasta"], ruta
        assert periodo["desde"] <= periodo["hasta"], ruta
        assert periodo["etiqueta"].strip(), ruta


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
        ("La flotilla cruza costos con operación",
         test_la_flotilla_cruza_costos_con_operacion),
        ("La flotilla se identifica por su código",
         test_la_flotilla_se_identifica_por_su_codigo_no_por_su_id),
        ("Cada criterio de flotilla ordena por lo que dice",
         test_cada_criterio_de_flotilla_ordena_por_lo_que_dice),
        ("Los totales de flotilla cuadran con las filas",
         test_los_totales_de_flotilla_cuadran_con_las_filas),
        ("Los operadores salen de su dimensión",
         test_los_operadores_salen_de_su_dimension),
        ("El operador se identifica por su nombre",
         test_el_operador_se_identifica_por_su_nombre),
        ("La tendencia cubre todo el periodo",
         test_la_tendencia_cubre_todo_el_periodo),
        ("La tendencia por mes agrupa lo mismo",
         test_la_tendencia_por_mes_agrupa_lo_mismo),
        ("Las rutas responden tres preguntas distintas",
         test_las_rutas_responden_tres_preguntas_distintas),
        ("Los promedios excluyen las muestras pequeñas",
         test_los_promedios_excluyen_las_muestras_pequenas),
        ("Toda consulta dice de qué periodo habla",
         test_toda_consulta_dice_de_que_periodo_habla),
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
