"""
SIG-LOG — Sistema Integral de Gestión Logística
tests/test_api.py

PRUEBAS DEL BACKEND BASE

Usan `TestClient`, que ejecuta la aplicación en el mismo proceso: no hay
que levantar uvicorn ni abrir un puerto. Son pruebas de integración —
consultan MongoDB Atlas de verdad — porque lo que se quiere comprobar es
justamente que la cadena Router → Service → Repository → MongoDB funciona
completa.

Ejecución con pytest:
    pytest tests/test_api.py -v

Ejecución sin pytest (salida legible, útil como evidencia):
    python tests/test_api.py
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

API = settings.API_PREFIJO


def crear_cliente() -> TestClient:
    return TestClient(app)


# ==========================================================================
# CONTRATO DE RESPUESTA  (§12.2)
# ==========================================================================
def _validar_formato_exito(cuerpo: dict) -> None:
    """Toda respuesta correcta cumple el contrato del §12.2."""
    assert cuerpo["exito"] is True, "el campo `exito` debe ser true"
    assert isinstance(cuerpo["mensaje"], str) and cuerpo["mensaje"], \
        "el campo `mensaje` no puede ir vacío"
    assert "datos" in cuerpo, "falta el campo `datos`"


def test_salud_responde():
    """GET /salud devuelve 200 sin depender de MongoDB."""
    with crear_cliente() as cliente:
        respuesta = cliente.get(f"{API}/salud")
    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()
    _validar_formato_exito(cuerpo)
    assert cuerpo["datos"]["estado"] == "OPERATIVO"
    assert cuerpo["datos"]["origen_datos"] == "SIMULADO"


def test_info_declara_capacidades():
    """GET /info expone versión, prefijo y módulos pendientes."""
    with crear_cliente() as cliente:
        cuerpo = cliente.get(f"{API}/info").json()
    _validar_formato_exito(cuerpo)
    capacidades = cuerpo["datos"]["capacidades"]
    assert capacidades["prefijo"] == API
    assert "sistema" in capacidades["modulos_disponibles"]
    assert "autenticacion" in capacidades["modulos_pendientes"]


def test_salud_mongodb():
    """GET /salud/mongodb confirma la conexión con Atlas."""
    with crear_cliente() as cliente:
        respuesta = cliente.get(f"{API}/salud/mongodb")
    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()
    _validar_formato_exito(cuerpo)
    assert cuerpo["datos"]["base_datos"] == settings.MONGO_DB
    assert cuerpo["datos"]["total_colecciones"] > 0


def test_diagnostico_colecciones():
    """GET /diagnostico/colecciones cuenta documentos reales de la base."""
    with crear_cliente() as cliente:
        respuesta = cliente.get(f"{API}/diagnostico/colecciones")
    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()
    _validar_formato_exito(cuerpo)
    datos = cuerpo["datos"]
    assert datos["operativas"]["entregas"] > 0, "la colección `entregas` está vacía"
    assert cuerpo["total"] == datos["total_documentos"]


def test_diagnostico_muestra_serializa():
    """La muestra devuelve documentos con `_id` y fechas ya serializados."""
    with crear_cliente() as cliente:
        respuesta = cliente.get(f"{API}/diagnostico/muestra/vehiculos?limite=3")
    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()
    _validar_formato_exito(cuerpo)
    assert cuerpo["total"] == len(cuerpo["datos"]) <= 3
    documento = cuerpo["datos"][0]
    assert isinstance(documento["_id"], str), "ObjectId debe serializarse a texto"
    assert isinstance(documento["fecha_creacion"], str), "la fecha debe ser ISO"


# ==========================================================================
# MANEJO DE ERRORES  (§12.2)
# ==========================================================================
def test_error_404_con_formato_uniforme():
    """Una colección fuera del catálogo responde 404 con el formato del §12.2."""
    with crear_cliente() as cliente:
        respuesta = cliente.get(f"{API}/diagnostico/muestra/inventada")
    assert respuesta.status_code == 404
    cuerpo = respuesta.json()
    assert cuerpo["exito"] is False
    assert cuerpo["codigo_error"] == "NO_ENCONTRADO"
    assert "detalles" in cuerpo


def test_error_422_con_formato_uniforme():
    """Un parámetro fuera de rango responde 422 traducido al formato propio."""
    with crear_cliente() as cliente:
        respuesta = cliente.get(f"{API}/diagnostico/muestra/vehiculos?limite=999")
    assert respuesta.status_code == 422
    cuerpo = respuesta.json()
    assert cuerpo["exito"] is False
    assert cuerpo["codigo_error"] == "ESQUEMA_INVALIDO"
    assert cuerpo["detalles"], "el error de esquema debe detallar el campo"
    assert cuerpo["detalles"][0]["campo"] == "query.limite"


# ==========================================================================
# INFRAESTRUCTURA
# ==========================================================================
def test_documentacion_openapi():
    """La documentación automática del §12.1 se genera y describe los endpoints."""
    with crear_cliente() as cliente:
        respuesta = cliente.get("/openapi.json")
    assert respuesta.status_code == 200
    rutas = respuesta.json()["paths"]
    for endpoint in ("/salud", "/salud/mongodb", "/info",
                     "/diagnostico/colecciones"):
        assert f"{API}{endpoint}" in rutas, f"falta documentar {endpoint}"


def test_raiz_redirige_a_documentacion():
    with crear_cliente() as cliente:
        respuesta = cliente.get("/", follow_redirects=False)
    assert respuesta.status_code in (302, 307)
    assert respuesta.headers["location"] == "/docs"


def test_cors_no_es_comodin():
    """
    CORS debe declarar orígenes explícitos.

    Un `*` junto a credenciales permitidas es un error de seguridad clásico,
    y aquí además sería innecesario: el frontend corre en el mismo proceso.
    """
    assert "*" not in settings.CORS_ORIGENES
    assert all(o.startswith("http") for o in settings.CORS_ORIGENES)


def test_no_se_duplica_la_capa_analitica():
    """
    El backend no reimplementa ETL, KPIs ni ML.

    Se comprueba que ningún archivo de `backend/` contenga los cálculos que
    ya viven en `analytics/`, `etl/` o `ml/`. Es la regla que el usuario
    fijó para esta etapa, así que se prueba como cualquier otro requisito.
    """
    prohibidos = ("KMeans", "RandomForest", "train_test_split",
                  "silhouette_score", "read_csv")
    encontrados = []
    for archivo in (RAIZ / "backend").rglob("*.py"):
        texto = archivo.read_text(encoding="utf-8")
        for termino in prohibidos:
            if termino in texto:
                encontrados.append(f"{archivo.name}: {termino}")
    assert not encontrados, (
        "El backend no debe reimplementar la capa analítica: " + ", ".join(encontrados))


# ==========================================================================
# Modo manual (sin pytest)
# ==========================================================================
if __name__ == "__main__":
    pruebas = [
        ("GET /salud responde", test_salud_responde),
        ("GET /info declara capacidades", test_info_declara_capacidades),
        ("GET /salud/mongodb conecta con Atlas", test_salud_mongodb),
        ("GET /diagnostico/colecciones cuenta documentos",
         test_diagnostico_colecciones),
        ("GET /diagnostico/muestra serializa correctamente",
         test_diagnostico_muestra_serializa),
        ("Error 404 con formato uniforme", test_error_404_con_formato_uniforme),
        ("Error 422 con formato uniforme", test_error_422_con_formato_uniforme),
        ("Documentación OpenAPI generada", test_documentacion_openapi),
        ("La raíz redirige a /docs", test_raiz_redirige_a_documentacion),
        ("CORS con orígenes explícitos", test_cors_no_es_comodin),
        ("El backend no duplica la capa analítica",
         test_no_se_duplica_la_capa_analitica),
    ]

    print("=" * 70)
    print("  SIG-LOG — Pruebas del backend base")
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

    print("=" * 70)
    print(f"  Resultado: {len(pruebas) - fallos}/{len(pruebas)} pruebas correctas")
    print("=" * 70)
    sys.exit(1 if fallos else 0)
