"""
SIG-LOG — Sistema Integral de Gestión Logística
config/settings.py

Propósito
---------
Punto único de lectura de la configuración del proyecto. Ningún otro módulo
debe leer variables de entorno directamente ni contener credenciales
literales (§9.1 del documento técnico: `config/` no contiene lógica de
negocio ni credenciales literales).

Patrón de carga del .env: el mismo utilizado en los ejercicios de clase
(`generar_datos2_insertmany.py`, `spark_processing_cargadatos.py`):
    load_dotenv(RAIZ / ".env")  +  quote_plus()  para escapar credenciales.
"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import quote_plus

from dotenv import load_dotenv

# --------------------------------------------------------------------------
# Rutas base del proyecto
# --------------------------------------------------------------------------
RAIZ_PROYECTO: Path = Path(__file__).resolve().parent.parent
RUTA_ENV: Path = RAIZ_PROYECTO / ".env"

load_dotenv(dotenv_path=RUTA_ENV)


def _leer_bool(nombre: str, por_defecto: bool = False) -> bool:
    """Lee una variable de entorno booleana de forma tolerante."""
    valor = os.getenv(nombre)
    if valor is None or valor.strip() == "":
        return por_defecto
    return valor.strip().lower() in {"1", "true", "si", "sí", "yes", "y", "on"}


# --------------------------------------------------------------------------
# Identidad de la aplicación
# --------------------------------------------------------------------------
APP_NOMBRE: str = "SIG-LOG"
APP_VERSION: str = "0.1.0"
APP_ENTORNO: str = os.getenv("APP_ENTORNO", "desarrollo")

# --------------------------------------------------------------------------
# Conexión a MongoDB Atlas
# --------------------------------------------------------------------------
MONGO_USER: str | None = os.getenv("MONGO_USER")
MONGO_PASSWORD: str | None = os.getenv("MONGO_PASSWORD")
MONGO_CLUSTER: str | None = os.getenv("MONGO_CLUSTER")
MONGO_DB: str = os.getenv("MONGO_DB", "siglog")

# Alternativa: cadena completa entregada por Atlas. Si existe, tiene prioridad.
MONGO_URI_DIRECTA: str | None = os.getenv("MONGO_URI")

MONGO_TIMEOUT_MS: int = int(os.getenv("MONGO_TIMEOUT_MS", "10000"))

# --------------------------------------------------------------------------
# Parámetros de inicialización de la base de datos
# --------------------------------------------------------------------------
# warn | error | off   (ver .env.example)
NIVEL_VALIDACION: str = os.getenv("SIGLOG_VALIDACION", "warn").strip().lower()

# Decisión D-4 (16/08/2026): el proyecto NO usa coordenadas GPS.
# El índice 2dsphere de §11.1 permanece desactivado.
CREAR_INDICE_GEOESPACIAL: bool = _leer_bool("SIGLOG_INDICE_GEO", False)

# --------------------------------------------------------------------------
# Catálogo de colecciones (§11 del documento técnico)
# El orden es intencional: refleja la dependencia lógica entre entidades.
# --------------------------------------------------------------------------
COLECCIONES_OPERATIVAS: tuple[str, ...] = (
    "clientes",            # §11.1
    "vehiculos",           # §11.2
    "operadores",          # §11.3
    "rutas",               # §11.4
    "viajes",              # §11.5
    "entregas",            # §11.6
    "incidentes",          # §11.7
    "combustible",         # §11.8
    "mantenimientos",      # §11.9
    "seguimiento_eventos", # §11.10
)

COLECCIONES_ANALITICAS: tuple[str, ...] = (
    "hecho_entrega",   # tabla de hechos del DW / dataset de entrenamiento
    "dim_tiempo",
    "dim_cliente",
    "dim_vehiculo",
    "dim_operador",
    "dim_ruta",
    "modelos_ml",
    "predicciones",
    "clusters_rutas",
)

TODAS_LAS_COLECCIONES: tuple[str, ...] = COLECCIONES_OPERATIVAS + COLECCIONES_ANALITICAS

# Colecciones que produce la actividad PA-1 (catálogos maestros)
COLECCIONES_CATALOGO: tuple[str, ...] = ("clientes", "vehiculos", "operadores", "rutas")

# Valores admitidos para el campo común `origen_dato` (regla académica:
# nunca confundir datos simulados con datos reales).
ORIGENES_DATO: tuple[str, ...] = ("REAL", "SIMULADO")


# ==========================================================================
# REGLAS DE NEGOCIO CONFIRMADAS — 16/08/2026
# --------------------------------------------------------------------------
# Estos catálogos dejaron de ser "reglas pendientes" al ser aprobados.
# Fuente única de verdad: los validadores de esquema, el generador de datos
# simulados y el ETL deben importarlos de aquí, nunca redefinirlos.
# ==========================================================================

# RNP-01 — Umbral a partir del cual una entrega se considera retrasada.
# Define la variable objetivo de clasificación `es_retraso`.
UMBRAL_RETRASO_MIN: int = 15

# RNP-08 — Catálogo de estatus de una entrega.
CATALOGO_ESTATUS_ENTREGA: tuple[str, ...] = (
    "PROGRAMADA",
    "EN_RUTA",
    "ENTREGADA",
    "NO_ENTREGADA",
    "CANCELADA",
)

# RNP-12 — Catálogo de tipos de incidente.
CATALOGO_TIPOS_INCIDENTE: tuple[str, ...] = (
    "TRAFICO",
    "ACCIDENTE",
    "PROTESTA",
    "CLIMA",
    "FALLA_VEHICULO",
    "CLIENTE_AUSENTE",
    "OTRO",
)

# --------------------------------------------------------------------------
# REGLAS AÚN PENDIENTES (no se convierten en enum hasta ser aprobadas)
#   RNP-05  tipo de mantenimiento (PREVENTIVO / CORRECTIVO)
#   RNP-07  catálogo de tipo de cliente / servicio  → ver database/seed/parametros.py
#   RNP-13  ventanas horarias comprometidas con el cliente
#   severidad de incidente: escala pendiente de definir
# --------------------------------------------------------------------------


# --------------------------------------------------------------------------
# Construcción de la URI de conexión
# --------------------------------------------------------------------------
def construir_uri() -> str:
    """
    Devuelve la cadena de conexión a MongoDB Atlas.

    Prioridad:
      1. MONGO_URI (cadena completa) si está definida.
      2. Composición segura a partir de usuario/contraseña/cluster.

    Lanza ValueError si falta información, sin exponer la contraseña.
    """
    if MONGO_URI_DIRECTA:
        return MONGO_URI_DIRECTA

    faltantes = [
        nombre
        for nombre, valor in (
            ("MONGO_USER", MONGO_USER),
            ("MONGO_PASSWORD", MONGO_PASSWORD),
            ("MONGO_CLUSTER", MONGO_CLUSTER),
        )
        if not valor
    ]
    if faltantes:
        raise ValueError(
            "Faltan variables en el archivo .env: "
            + ", ".join(faltantes)
            + f". Archivo esperado: {RUTA_ENV}"
        )

    usuario = quote_plus(str(MONGO_USER))
    contrasena = quote_plus(str(MONGO_PASSWORD))
    return (
        f"mongodb+srv://{usuario}:{contrasena}@{MONGO_CLUSTER}/"
        f"?retryWrites=true&w=majority&appName={APP_NOMBRE}"
    )


def uri_enmascarada() -> str:
    """URI apta para imprimir en consola o en logs: oculta la contraseña."""
    try:
        uri = construir_uri()
    except ValueError as exc:
        return f"<no disponible: {exc}>"

    if "@" not in uri:
        return uri
    esquema, resto = uri.split("://", 1)
    credenciales, host = resto.split("@", 1)
    usuario = credenciales.split(":", 1)[0]
    return f"{esquema}://{usuario}:****@{host}"


def resumen_configuracion() -> dict[str, object]:
    """Diccionario legible con el estado de la configuración (sin secretos)."""
    return {
        "app": f"{APP_NOMBRE} v{APP_VERSION}",
        "entorno": APP_ENTORNO,
        "raiz_proyecto": str(RAIZ_PROYECTO),
        "archivo_env": str(RUTA_ENV),
        "env_encontrado": RUTA_ENV.exists(),
        "base_datos": MONGO_DB,
        "uri": uri_enmascarada(),
        "timeout_ms": MONGO_TIMEOUT_MS,
        "nivel_validacion": NIVEL_VALIDACION,
        "indice_geoespacial": CREAR_INDICE_GEOESPACIAL,
        "umbral_retraso_min": UMBRAL_RETRASO_MIN,
        "colecciones_operativas": len(COLECCIONES_OPERATIVAS),
        "colecciones_analiticas": len(COLECCIONES_ANALITICAS),
    }
