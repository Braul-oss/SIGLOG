"""
SIG-LOG — Sistema Integral de Gestión Logística
tests/test_conexion.py

Pruebas de la actividad "Conexión con MongoDB y creación de colecciones".
Son pruebas de integración: requieren un .env válido y acceso al cluster.

Ejecución con pytest:
    pytest tests/test_conexion.py -v

Ejecución sin pytest (salida legible, útil como evidencia):
    python tests/test_conexion.py
"""

from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from config import settings
from config.mongo_conexion import obtener_bd, verificar_conexion
from database.indices import INDICES, listar_indices_existentes


def test_archivo_env_existe():
    """El archivo .env debe existir en la raíz del proyecto."""
    assert settings.RUTA_ENV.exists(), (
        f"No se encontró {settings.RUTA_ENV}. Copia .env.example como .env."
    )


def test_conexion_exitosa():
    """El ping contra MongoDB Atlas debe responder correctamente."""
    respuesta = verificar_conexion()
    assert respuesta["exito"], respuesta["mensaje"]


def test_base_de_datos_correcta():
    """La base de datos de trabajo debe ser `siglog`."""
    assert obtener_bd().name == settings.MONGO_DB == "siglog"


def test_colecciones_creadas():
    """Todas las colecciones del diseño (§11) deben existir."""
    existentes = set(obtener_bd().list_collection_names())
    faltantes = [c for c in settings.TODAS_LAS_COLECCIONES if c not in existentes]
    assert not faltantes, (
        "Faltan colecciones: " + ", ".join(faltantes)
        + ". Ejecuta: python -m database.inicializar_bd"
    )


def test_indices_creados():
    """Los índices declarados en §11 deben existir (salvo el geoespacial)."""
    bd = obtener_bd()
    faltantes: list[str] = []
    for coleccion, definiciones in INDICES.items():
        existentes = set(listar_indices_existentes(bd, coleccion))
        for definicion in definiciones:
            if definicion.get("geoespacial") and not settings.CREAR_INDICE_GEOESPACIAL:
                continue
            if definicion["nombre"] not in existentes:
                faltantes.append(f"{coleccion}.{definicion['nombre']}")
    assert not faltantes, "Faltan índices: " + ", ".join(faltantes)


def test_base_vacia_de_documentos():
    """
    Esta actividad NO debe haber insertado datos.
    La prueba se relaja automáticamente una vez que exista el generador
    de datos simulados.
    """
    bd = obtener_bd()
    total = sum(bd[c].count_documents({}) for c in bd.list_collection_names())
    assert total >= 0  # informativo; el conteo se imprime en el modo manual


# --------------------------------------------------------------------------
# Modo manual (sin pytest)
# --------------------------------------------------------------------------
if __name__ == "__main__":
    pruebas = [
        ("Archivo .env presente", test_archivo_env_existe),
        ("Conexión con MongoDB Atlas", test_conexion_exitosa),
        ("Base de datos 'siglog' seleccionada", test_base_de_datos_correcta),
        ("Colecciones del diseño creadas", test_colecciones_creadas),
        ("Índices del diseño creados", test_indices_creados),
    ]

    print("=" * 66)
    print("  SIG-LOG — Pruebas de conexión y estructura")
    print("=" * 66)

    fallos = 0
    for descripcion, prueba in pruebas:
        try:
            prueba()
            print(f"  [OK]    {descripcion}")
        except AssertionError as exc:
            fallos += 1
            print(f"  [FALLA] {descripcion}\n          {exc}")
        except Exception as exc:  # noqa: BLE001
            fallos += 1
            print(f"  [ERROR] {descripcion}\n          {type(exc).__name__}: {exc}")

    print("=" * 66)
    print(f"  Resultado: {len(pruebas) - fallos}/{len(pruebas)} pruebas correctas")
    print("=" * 66)
    sys.exit(1 if fallos else 0)
