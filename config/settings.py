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

# --------------------------------------------------------------------------
# Colecciones del SISTEMA (no del dominio logístico)
# --------------------------------------------------------------------------
# `usuarios` no aparece en el §11 porque el documento dejó la autenticación
# como regla pendiente (RNP-11). Al resolverse con la opción (b) —roles
# Admin/Despachador/Consulta— hace falta almacenarlos.
#
# Se declara en un grupo APARTE y no dentro de las operativas por una razón
# concreta: `etl/extraccion.py` recorre COLECCIONES_OPERATIVAS para volcarlo
# todo a pandas y a CSV en data/raw/. Incluir aquí a los usuarios haría que
# el ETL exportara credenciales y hashes de contraseña. Separarlas lo impide
# por diseño, no por disciplina.
COLECCIONES_SISTEMA: tuple[str, ...] = (
    "usuarios",            # autenticación y control de acceso (RNP-11 opción b)
)

TODAS_LAS_COLECCIONES: tuple[str, ...] = (
    COLECCIONES_OPERATIVAS + COLECCIONES_ANALITICAS + COLECCIONES_SISTEMA
)

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

# RNP-07 — Catálogo de tipo de cliente.
# El documento lo dejó pendiente, pero la simulación ya opera con estos
# cuatro valores y sobre ellos se construyeron el DW, las gráficas y la
# variable categórica `tipo_cliente` de los modelos. Declararlos aquí no
# inventa nada: fija como catálogo lo que el proyecto ya usa, y da al API
# con qué validar el alta de un cliente.
CATALOGO_TIPO_CLIENTE: tuple[str, ...] = (
    "MINORISTA",
    "MAYORISTA",
    "INDUSTRIAL",
    "INSTITUCIONAL",
)


# §11.2 — Estado operativo del vehículo.
# El catálogo está escrito en el propio documento técnico, así que aquí no
# se decide nada nuevo: se materializa para que el API pueda validarlo.
ESTADO_DISPONIBLE: str = "DISPONIBLE"
ESTADO_EN_RUTA: str = "EN_RUTA"
ESTADO_EN_MANTENIMIENTO: str = "EN_MANTENIMIENTO"
ESTADO_BAJA: str = "BAJA"

CATALOGO_ESTADO_VEHICULO: tuple[str, ...] = (
    ESTADO_DISPONIBLE,
    ESTADO_EN_RUTA,
    ESTADO_EN_MANTENIMIENTO,
    ESTADO_BAJA,
)

# Transiciones permitidas entre estados (RN-V5). Un vehículo no pasa de
# EN_MANTENIMIENTO a EN_RUTA sin volver antes a DISPONIBLE: el taller lo
# libera y solo entonces puede salir.
#
# BAJA no es destino de ninguna transición a propósito: se alcanza dando de
# baja el vehículo (DELETE), para que ese camino pase siempre por sus
# comprobaciones y no se pueda retirar una unidad por la puerta de atrás.
TRANSICIONES_ESTADO_VEHICULO: dict[str, tuple[str, ...]] = {
    ESTADO_DISPONIBLE: (ESTADO_EN_RUTA, ESTADO_EN_MANTENIMIENTO),
    ESTADO_EN_RUTA: (ESTADO_DISPONIBLE, ESTADO_EN_MANTENIMIENTO),
    ESTADO_EN_MANTENIMIENTO: (ESTADO_DISPONIBLE,),
    ESTADO_BAJA: (),          # solo se sale reactivando el vehículo
}

# Supuesto S-03 del documento: tipos de unidad de la flotilla.
CATALOGO_TIPO_VEHICULO: tuple[str, ...] = ("LIGERO", "MEDIANO", "PESADO")

CATALOGO_TIPO_COMBUSTIBLE: tuple[str, ...] = ("DIESEL", "GASOLINA")


# --------------------------------------------------------------------------
# REGLAS AÚN PENDIENTES (no se convierten en enum hasta ser aprobadas)
#   RNP-05  tipo de mantenimiento (PREVENTIVO / CORRECTIVO)
#   RNP-13  ventanas horarias comprometidas con el cliente
#   severidad de incidente: escala pendiente de definir
# --------------------------------------------------------------------------


# ==========================================================================
# API / BACKEND  (§12 del documento técnico)
# --------------------------------------------------------------------------
# Se declara aquí y no en backend/ por la regla del §9.1: `config/` guarda
# la configuración y `backend/` no debe leer variables de entorno por su
# cuenta. Así el API, el ETL y el ML comparten una única fuente de verdad.
# ==========================================================================

API_PREFIJO: str = "/api/v1"                    # §12.2: base de la API
API_TITULO: str = "SIG-LOG API"
API_DESCRIPCION: str = (
    "API del Sistema Integral de Gestión de Transporte y Logística. "
    "Expone la operación logística y los resultados de la capa analítica "
    "(ETL, KPIs y modelos de Machine Learning). "
    "Todos los datos son SIMULADOS con fines académicos."
)

API_HOST: str = os.getenv("API_HOST", "127.0.0.1")
API_PUERTO: int = int(os.getenv("API_PUERTO", "8000"))
# Recarga automática al guardar: cómoda en desarrollo, prohibida en producción.
API_RECARGA: bool = _leer_bool("API_RECARGA", APP_ENTORNO == "desarrollo")

# Orígenes permitidos por CORS. El frontend previsto es Jinja2 servido por
# el mismo proceso de FastAPI (§8.2), de modo que en condiciones normales no
# hace falta CORS. Se deja configurable para poder abrir un frontend en otro
# puerto durante el desarrollo, con una lista explícita y nunca "*".
CORS_ORIGENES: tuple[str, ...] = tuple(
    origen.strip()
    for origen in os.getenv(
        "API_CORS_ORIGENES",
        "http://localhost:8000,http://127.0.0.1:8000",
    ).split(",")
    if origen.strip()
)


# ==========================================================================
# SEGURIDAD Y CONTROL DE ACCESO  (RNP-11 resuelta: opción b)
# ==========================================================================
# Los roles salen de los actores del §3 y del §12.3. La equivalencia:
#     ADMINISTRADOR  →  "Administrador / Coordinador logístico" (§3)
#     DESPACHADOR    →  "Despachador / Capturista" (§3)
#     ANALISTA       →  "Analista / Directivo" (§3); es el rol que §12.3
#                       llama "Consulta". Se usa el nombre del actor porque
#                       describe lo que hace, no solo lo que se le niega.
ROL_ADMINISTRADOR: str = "ADMINISTRADOR"
ROL_DESPACHADOR: str = "DESPACHADOR"
ROL_ANALISTA: str = "ANALISTA"

CATALOGO_ROLES: tuple[str, ...] = (
    ROL_ADMINISTRADOR,
    ROL_DESPACHADOR,
    ROL_ANALISTA,
)

# Clave de firma de los JWT. NUNCA debe quedarse en el valor por defecto
# fuera de desarrollo: quien la conozca puede fabricar tokens válidos.
# Generar una con:  python -c "import secrets; print(secrets.token_hex(32))"
JWT_CLAVE_POR_DEFECTO: str = "clave-de-desarrollo-NO-USAR-FUERA-DE-DESARROLLO"
JWT_CLAVE: str = os.getenv("JWT_CLAVE", JWT_CLAVE_POR_DEFECTO)
JWT_ALGORITMO: str = os.getenv("JWT_ALGORITMO", "HS256")
JWT_MINUTOS_EXPIRACION: int = int(os.getenv("JWT_MINUTOS_EXPIRACION", "480"))


def jwt_clave_es_insegura() -> bool:
    """True si la clave de firma sigue siendo la de desarrollo."""
    return JWT_CLAVE == JWT_CLAVE_POR_DEFECTO


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
        "api_prefijo": API_PREFIJO,
        "api_direccion": f"http://{API_HOST}:{API_PUERTO}",
    }
