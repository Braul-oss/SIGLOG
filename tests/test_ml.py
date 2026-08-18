"""
SIG-LOG — Sistema Integral de Gestión Logística
tests/test_ml.py

PRUEBAS DE LOS ENDPOINTS DE MACHINE LEARNING

El riesgo de este módulo no es que falle: es que **funcione mal en
silencio**. Un modelo al que se le pasa un vector distinto del que vio al
entrenar devuelve un número con toda la apariencia de una predicción. Por
eso la mitad de estas pruebas no miran el resultado, sino el vector:

    RN-ML1  no se predice sobre una entrega ya cerrada; su retraso está
            medido, no estimado
    RN-ML2  el escenario lo decide el estado del viaje, no quien llama:
            mientras el viaje no salga no existen ni el retraso de salida
            ni los incidentes (§15.1, prevención de fuga)
    RN-ML3  el vector se arma con las mismas variables y en el mismo orden
            con que se entrenó, y si falta una se falla en vez de
            rellenarla
    RN-ML4  la predicción se guarda en la entrega (§15.4) y nunca toca
            `hora_estimada_llegada` — la misma razón de RN-I5

El escenario (cliente, ruta, vehículo, operador, viaje) se monta con los
ayudantes de `tests/test_entregas.py` para no repetir su construcción, y se
borra al terminar junto con las predicciones que haya dejado.
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
from ml import evaluacion
from tests import test_entregas as escenarios

API = settings.API_PREFIJO


def cliente_http() -> TestClient:
    return TestClient(app)


def cab(c: TestClient, usuario: str = "admin") -> dict[str, str]:
    r = c.post(f"{API}/auth/login",
               data={"username": usuario, "password": "siglog2026"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['datos']['access_token']}"}


def limpiar() -> dict[str, int]:
    """
    Borra el escenario y, además, las predicciones que dejó.

    `test_entregas.limpiar()` no sabe de `predicciones`: esa colección
    todavía no existía cuando se escribió. Se limpia aquí, antes de borrar
    las entregas, mientras aún se pueden identificar por su folio.
    """
    bd = obtener_bd()
    # Las predicciones se identifican por la entrega a la que apuntan, así
    # que hay que localizarlas antes de que `test_entregas.limpiar()` borre
    # las entregas.
    rutas = [r["_id"] for r in bd["rutas"].find(
        {"nombre": {"$regex": f"^{escenarios.MARCA}"}}, {"_id": 1})]
    viajes = [v["_id"] for v in bd["viajes"].find(
        {"ruta_id": {"$in": rutas}}, {"_id": 1})] if rutas else []
    entregas = [e["_id"] for e in bd["entregas"].find(
        {"viaje_id": {"$in": viajes}}, {"_id": 1})] if viajes else []

    borradas = (bd["predicciones"].delete_many(
        {"entrega_id": {"$in": entregas}}).deleted_count if entregas else 0)
    resultado = escenarios.limpiar()
    resultado["predicciones"] = borradas
    return resultado


try:
    import pytest

    @pytest.fixture(scope="module", autouse=True)
    def _limpiar_al_terminar():
        yield
        limpiar()
except ImportError:                    # pragma: no cover
    pass


def entrega_pendiente(c, cabecera, *, iniciar: bool = False,
                      paradas: int = 1) -> tuple[dict, dict]:
    """Escenario completo con entregas generadas y sin llegada registrada."""
    esc = escenarios.escenario(c, cabecera, paradas)
    entregas = escenarios.generar(c, cabecera, esc)
    if iniciar:
        escenarios.iniciar_viaje(c, cabecera, esc)
    return esc, entregas[0]


# ==========================================================================
# CATÁLOGO DE MODELOS
# ==========================================================================
def test_modelos_publica_la_ficha_registrada():
    c = cliente_http()
    r = c.get(f"{API}/ml/modelos", headers=cab(c))
    assert r.status_code == 200, r.text
    datos = r.json()["datos"]

    nombres = {m["nombre"] for m in datos["modelos"]}
    assert nombres == {
        "clasificacion_retraso_planeacion", "clasificacion_retraso_en_ruta",
        "regresion_retraso_planeacion", "regresion_retraso_en_ruta"}, nombres

    for modelo in datos["modelos"]:
        assert modelo["escenario"] in ("PLANEACION", "EN_RUTA")
        assert modelo["semilla"] == 42, "la semilla de clase es 42"
        assert modelo["umbral_retraso_min"] == settings.UMBRAL_RETRASO_MIN
        assert modelo["metricas"], modelo["nombre"]
        assert modelo["binario_disponible"] is True, (
            f"{modelo['nombre']} está registrado pero no tiene .joblib")
        if modelo["tipo"] == "CLASIFICACION":
            assert 0 <= modelo["metricas"]["roc_auc"] <= 1
        else:
            assert modelo["metricas"]["rmse"] > 0


def test_el_escenario_en_ruta_predice_mejor_y_se_dice():
    """
    Es la comparación honesta que sostiene la decisión de diseño: EN_RUTA
    acierta más porque sabe más, no porque sea mejor modelo.
    """
    c = cliente_http()
    datos = c.get(f"{API}/ml/modelos", headers=cab(c)).json()["datos"]
    por_nombre = {m["nombre"]: m for m in datos["modelos"]}

    assert (por_nombre["clasificacion_retraso_en_ruta"]["metricas"]["roc_auc"]
            > por_nombre["clasificacion_retraso_planeacion"]["metricas"]["roc_auc"])
    assert (por_nombre["regresion_retraso_en_ruta"]["metricas"]["rmse"]
            < por_nombre["regresion_retraso_planeacion"]["metricas"]["rmse"])
    assert "avisa más tarde" in datos["lectura"]

    # Y EN_RUTA usa exactamente las tres variables de más que justifican eso
    extra = (set(datos["escenarios"]["EN_RUTA"])
             - set(datos["escenarios"]["PLANEACION"]))
    assert extra == {"retraso_salida_min", "n_incidentes_acumulados",
                     "incidentes_viaje"}, extra


# ==========================================================================
# CLUSTERS
# ==========================================================================
def test_clusters_rutas_con_su_perfil():
    c = cliente_http()
    r = c.get(f"{API}/ml/clusters-rutas", headers=cab(c))
    assert r.status_code == 200, r.text
    datos = r.json()["datos"]

    assert datos["total_rutas"] == 20, "las 20 rutas de la flotilla"
    assert datos["k"] == len(datos["grupos"])
    assert sum(g["total_rutas"] for g in datos["grupos"]) == 20
    for grupo in datos["grupos"]:
        assert grupo["nombre"], grupo["grupo"]
        assert grupo["recomendacion"], grupo["grupo"]
        assert grupo["total_rutas"] >= 2, (
            "ningún grupo de una sola ruta: fue la restricción de validez "
            "que se añadió al elegir k en PA-9")


def test_la_silueta_se_publica_y_se_matiza():
    """
    Publicar la silueta obliga a leer los grupos con reserva: 0.40 es una
    segmentación operativa útil, no categorías naturales separadas.
    """
    c = cliente_http()
    datos = c.get(f"{API}/ml/clusters-rutas", headers=cab(c)).json()["datos"]
    assert 0 < datos["silueta_global"] < 1
    assert "segmentación operativa" in datos["lectura"]
    assert "continuo" in datos["lectura"]


# ==========================================================================
# PREDICCIÓN — el vector  (RN-ML2, RN-ML3)
# ==========================================================================
def test_el_escenario_lo_decide_el_viaje_no_quien_llama():
    """RN-ML2."""
    c = cliente_http()
    cabecera = cab(c)
    try:
        # Viaje sin salir → PLANEACION
        _, entrega = entrega_pendiente(c, cabecera)
        r = c.post(f"{API}/ml/predecir-retraso", headers=cabecera,
                   json={"entrega_id": entrega["id"], "guardar": False})
        assert r.status_code == 200, r.text
        datos = r.json()["datos"]
        assert datos["escenario"] == "PLANEACION"
        assert "retraso_salida_min" not in datos["variables"], (
            "el viaje no ha salido: ese dato todavía no existe")
        assert "aún no sale" in datos["contexto"]["motivo_escenario"]

        # El mismo escenario, ya iniciado → EN_RUTA
        esc, otra = entrega_pendiente(c, cabecera, iniciar=True)
        r = c.post(f"{API}/ml/predecir-retraso", headers=cabecera,
                   json={"entrega_id": otra["id"], "guardar": False})
        assert r.status_code == 200, r.text
        datos = r.json()["datos"]
        assert datos["escenario"] == "EN_RUTA"
        assert "retraso_salida_min" in datos["variables"]
        assert "incidentes_viaje" in datos["variables"]
        assert datos["contexto"]["estatus_viaje"] == "EN_CURSO"
    finally:
        limpiar()


def test_el_vector_es_el_del_entrenamiento():
    """
    RN-ML3: mismas variables, mismo orden. Si el pipeline recibiera una
    columna de más, de menos o en otro sitio, el modelo respondería con una
    cifra sin sentido en vez de fallar.
    """
    c = cliente_http()
    cabecera = cab(c)
    try:
        _, entrega = entrega_pendiente(c, cabecera)
        r = c.post(f"{API}/ml/predecir-retraso", headers=cabecera,
                   json={"entrega_id": entrega["id"], "guardar": False})
        assert r.status_code == 200, r.text
        datos = r.json()["datos"]

        esperadas = evaluacion.columnas_del_escenario(datos["escenario"])
        assert list(datos["variables"]) == esperadas, (
            f"El vector no coincide con el del entrenamiento: "
            f"{set(datos['variables']) ^ set(esperadas)}")
        for columna in evaluacion.COLUMNAS_CON_FUGA:
            assert columna not in datos["variables"], (
                f"{columna} se conoce solo después del hecho que se predice")
        for nombre, valor in datos["variables"].items():
            assert valor is not None, nombre
    finally:
        limpiar()


def test_la_franja_horaria_es_la_del_etl():
    """
    Los cortes de las franjas se definen en un solo sitio. Si el API los
    recalculara por su cuenta, una entrega de las 7:00 podría caer en una
    franja distinta de la que vio el modelo.
    """
    from datetime import datetime, timezone

    from etl.transformacion import franja_de

    c = cliente_http()
    cabecera = cab(c)
    try:
        _, entrega = entrega_pendiente(c, cabecera)
        r = c.post(f"{API}/ml/predecir-retraso", headers=cabecera,
                   json={"entrega_id": entrega["id"], "guardar": False})
        datos = r.json()["datos"]

        estimada = datetime.fromisoformat(
            datos["contexto"]["hora_estimada_llegada"].replace("Z", "+00:00"))
        estimada = estimada.astimezone(timezone.utc)
        assert datos["variables"]["franja_horaria"] == franja_de(estimada.hour)
        assert datos["variables"]["dia_semana"] == estimada.weekday()
        assert datos["variables"]["mes"] == estimada.month
        assert datos["variables"]["es_fin_semana"] == int(
            estimada.weekday() >= 5)
    finally:
        limpiar()


# ==========================================================================
# PREDICCIÓN — el resultado y su persistencia  (RN-ML1, RN-ML4)
# ==========================================================================
def test_la_prediccion_se_guarda_en_la_entrega():
    """RN-ML4 / §15.4 punto 2."""
    from bson import ObjectId

    c = cliente_http()
    cabecera = cab(c)
    try:
        _, entrega = entrega_pendiente(c, cabecera)
        r = c.post(f"{API}/ml/predecir-retraso", headers=cabecera,
                   json={"entrega_id": entrega["id"]})
        assert r.status_code == 200, r.text
        datos = r.json()["datos"]
        assert datos["guardada"] is True
        assert 0 <= datos["probabilidad_retraso"] <= 1
        assert datos["riesgo"] in ("BAJO", "MEDIO", "ALTO")

        bd = obtener_bd()
        documento = bd["entregas"].find_one({"_id": ObjectId(entrega["id"])})
        assert documento["probabilidad_retraso"] == datos["probabilidad_retraso"]
        assert documento["retraso_estimado_min"] == datos["retraso_estimado_min"]
        assert documento["riesgo_retraso"] == datos["riesgo"]

        # La traza queda para poder confrontar después predicción y realidad
        traza = bd["predicciones"].find_one({"_id": {"$exists": True},
                                             "entrega_id": ObjectId(entrega["id"])})
        assert traza is not None
        assert traza["modelo_clasificacion"] == datos["modelo_clasificacion"]
        assert traza["variables"] == datos["variables"]
    finally:
        limpiar()


def test_la_prediccion_nunca_toca_la_hora_estimada():
    """
    Misma razón que RN-I5: el retraso se mide contra `hora_estimada_llegada`.
    Si una predicción la moviera, la entrega parecería puntual por obra del
    modelo que advirtió lo contrario.
    """
    from bson import ObjectId

    c = cliente_http()
    cabecera = cab(c)
    try:
        _, entrega = entrega_pendiente(c, cabecera)
        bd = obtener_bd()
        antes = bd["entregas"].find_one({"_id": ObjectId(entrega["id"])})

        r = c.post(f"{API}/ml/predecir-retraso", headers=cabecera,
                   json={"entrega_id": entrega["id"]})
        assert r.status_code == 200, r.text

        despues = bd["entregas"].find_one({"_id": ObjectId(entrega["id"])})
        assert despues["hora_estimada_llegada"] == antes["hora_estimada_llegada"]
        assert despues.get("hora_real_llegada") is None
        assert despues.get("retraso_min") is None, (
            "el retraso real sigue sin existir: lo estimado no lo sustituye")
        assert despues["retraso_estimado_min"] is not None
    finally:
        limpiar()


def test_guardar_falso_no_modifica_nada():
    from bson import ObjectId

    c = cliente_http()
    cabecera = cab(c)
    try:
        _, entrega = entrega_pendiente(c, cabecera)
        bd = obtener_bd()
        r = c.post(f"{API}/ml/predecir-retraso", headers=cabecera,
                   json={"entrega_id": entrega["id"], "guardar": False})
        assert r.status_code == 200, r.text
        assert r.json()["datos"]["guardada"] is False

        documento = bd["entregas"].find_one({"_id": ObjectId(entrega["id"])})
        assert "probabilidad_retraso" not in documento
        assert bd["predicciones"].count_documents(
            {"entrega_id": ObjectId(entrega["id"])}) == 0
    finally:
        limpiar()


def test_no_se_predice_sobre_una_entrega_cerrada():
    """RN-ML1: su retraso está medido, no estimado."""
    c = cliente_http()
    cabecera = cab(c)
    try:
        esc, entrega = entrega_pendiente(c, cabecera, iniciar=True)
        r = c.patch(f"{API}/entregas/{entrega['id']}/llegada",
                    headers=cabecera, json={})
        assert r.status_code == 200, r.text

        r = c.post(f"{API}/ml/predecir-retraso", headers=cabecera,
                   json={"entrega_id": entrega["id"]})
        assert r.status_code == 409, r.text
        cuerpo = r.json()
        assert cuerpo["codigo_error"] == "REGLA_ML1", cuerpo
        assert "se mide" in cuerpo["mensaje"]
    finally:
        limpiar()


def test_entrega_inexistente_da_404():
    c = cliente_http()
    r = c.post(f"{API}/ml/predecir-retraso", headers=cab(c),
               json={"entrega_id": "0" * 24})
    assert r.status_code == 404, r.text


# ==========================================================================
# ENTREGAS EN RIESGO
# ==========================================================================
def test_entregas_en_riesgo_ordena_por_probabilidad():
    """§15.4 punto 3: el conocimiento vuelve a la pantalla de operación."""
    c = cliente_http()
    cabecera = cab(c)
    try:
        _, primera = entrega_pendiente(c, cabecera, paradas=3)
        esc = escenarios.escenario(c, cabecera, 2)
        otras = escenarios.generar(c, cabecera, esc)
        for identificador in [primera["id"]] + [e["id"] for e in otras]:
            assert c.post(f"{API}/ml/predecir-retraso", headers=cabecera,
                          json={"entrega_id": identificador}).status_code == 200

        r = c.get(f"{API}/ml/entregas-en-riesgo", headers=cabecera,
                  params={"limite": 50})
        assert r.status_code == 200, r.text
        datos = r.json()["datos"]
        probabilidades = [e["probabilidad_retraso"] for e in datos["entregas"]]
        assert probabilidades == sorted(probabilidades, reverse=True)
        assert datos["total"] >= 3
        for fila in datos["entregas"]:
            assert fila["riesgo_retraso"] in ("BAJO", "MEDIO", "ALTO")
            assert fila["folio_entrega"]
    finally:
        limpiar()


# ==========================================================================
# PERMISOS
# ==========================================================================
def test_sin_sesion_no_hay_ml():
    c = cliente_http()
    for ruta in ("modelos", "clusters-rutas", "entregas-en-riesgo"):
        assert c.get(f"{API}/ml/{ruta}").status_code == 401, ruta
    assert c.post(f"{API}/ml/predecir-retraso",
                  json={"entrega_id": "0" * 24}).status_code == 401


def test_el_analista_consulta_pero_no_predice():
    """Predecir escribe en la entrega: no es una consulta disfrazada."""
    c = cliente_http()
    analista = cab(c, "analista")
    for ruta in ("modelos", "clusters-rutas", "entregas-en-riesgo"):
        assert c.get(f"{API}/ml/{ruta}", headers=analista).status_code == 200, ruta

    cabecera = cab(c)
    try:
        _, entrega = entrega_pendiente(c, cabecera)
        r = c.post(f"{API}/ml/predecir-retraso", headers=analista,
                   json={"entrega_id": entrega["id"]})
        assert r.status_code == 403, r.text

        # El despachador sí: es quien programa la jornada
        r = c.post(f"{API}/ml/predecir-retraso", headers=cab(c, "despachador"),
                   json={"entrega_id": entrega["id"]})
        assert r.status_code == 200, r.text
    finally:
        limpiar()


if __name__ == "__main__":
    pruebas = [
        ("Modelos publica la ficha registrada",
         test_modelos_publica_la_ficha_registrada),
        ("EN_RUTA predice mejor y se dice por qué",
         test_el_escenario_en_ruta_predice_mejor_y_se_dice),
        ("Clusters de rutas con su perfil", test_clusters_rutas_con_su_perfil),
        ("La silueta se publica y se matiza",
         test_la_silueta_se_publica_y_se_matiza),
        ("El escenario lo decide el viaje (RN-ML2)",
         test_el_escenario_lo_decide_el_viaje_no_quien_llama),
        ("El vector es el del entrenamiento (RN-ML3)",
         test_el_vector_es_el_del_entrenamiento),
        ("La franja horaria es la del ETL", test_la_franja_horaria_es_la_del_etl),
        ("La predicción se guarda en la entrega (RN-ML4)",
         test_la_prediccion_se_guarda_en_la_entrega),
        ("La predicción nunca toca la hora estimada",
         test_la_prediccion_nunca_toca_la_hora_estimada),
        ("guardar=false no modifica nada", test_guardar_falso_no_modifica_nada),
        ("No se predice sobre una entrega cerrada (RN-ML1)",
         test_no_se_predice_sobre_una_entrega_cerrada),
        ("Entrega inexistente da 404", test_entrega_inexistente_da_404),
        ("Entregas en riesgo ordena por probabilidad",
         test_entregas_en_riesgo_ordena_por_probabilidad),
        ("Sin sesión no hay ML", test_sin_sesion_no_hay_ml),
        ("El analista consulta pero no predice",
         test_el_analista_consulta_pero_no_predice),
    ]

    print("=" * 70)
    print("  SIG-LOG — Pruebas de los endpoints de Machine Learning")
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
