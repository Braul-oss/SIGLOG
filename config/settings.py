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


# §11.3 — Operadores.
ESTADO_OPERADOR_ACTIVO: str = "ACTIVO"
ESTADO_OPERADOR_INACTIVO: str = "INACTIVO"
CATALOGO_ESTADO_OPERADOR: tuple[str, ...] = (
    ESTADO_OPERADOR_ACTIVO,
    ESTADO_OPERADOR_INACTIVO,
)

# Tipos de licencia federal de carga. La simulación usa B, C y E; se
# admite el catálogo completo porque es un documento oficial con tipos
# fijos, no una clasificación propia del proyecto.
CATALOGO_TIPO_LICENCIA: tuple[str, ...] = ("A", "B", "C", "D", "E")

# Días de anticipación con que el sistema avisa de una licencia por vencer.
# Un operador cuya licencia caduca la semana próxima sigue siendo legal
# hoy, pero programarle rutas del mes que viene es un problema seguro.
DIAS_AVISO_LICENCIA: int = 30

# RNP-03 resuelta con la opción (b): el operador ROTA de vehículo por
# jornada, no tiene uno fijo. Por eso `operadores.vehiculo_asignado_id`
# permanece nulo y el API no ofrece asignarlo: la pareja operador-vehículo
# se decide en cada viaje, que es donde queda registrada.
OPERADOR_ROTA_VEHICULO: bool = True


# §11.4 — Rutas.
# Las zonas son la dimensión geográfica del DW y una variable del
# clustering; el catálogo es el que la operación ya usa.
CATALOGO_ZONA: tuple[str, ...] = ("NORTE", "SUR", "ORIENTE", "PONIENTE")

# RNP-06 (días de operación) se resuelve con la opción (b): días fijos de
# la semana. Es lo que la simulación implementó —cada ruta declara sus
# días— y lo que permite analizar la saturación por día.
CATALOGO_DIAS_OPERACION: tuple[str, ...] = (
    "LUNES", "MARTES", "MIERCOLES", "JUEVES", "VIERNES", "SABADO", "DOMINGO",
)


# §11.5 — Viajes: la ejecución de una ruta en una fecha.
ESTATUS_VIAJE_PROGRAMADO: str = "PROGRAMADO"
ESTATUS_VIAJE_EN_CURSO: str = "EN_CURSO"
ESTATUS_VIAJE_FINALIZADO: str = "FINALIZADO"
ESTATUS_VIAJE_CANCELADO: str = "CANCELADO"

CATALOGO_ESTATUS_VIAJE: tuple[str, ...] = (
    ESTATUS_VIAJE_PROGRAMADO,
    ESTATUS_VIAJE_EN_CURSO,
    ESTATUS_VIAJE_FINALIZADO,
    ESTATUS_VIAJE_CANCELADO,
)

# Un viaje avanza; nunca retrocede. El §11.5 dice que cada documento ES el
# histórico y no se sobrescribe: por eso de FINALIZADO y CANCELADO no sale
# ninguna transición. Corregir un viaje cerrado sería reescribir lo que ya
# ocurrió, y sobre esos documentos se construyen el DW y los modelos.
TRANSICIONES_ESTATUS_VIAJE: dict[str, tuple[str, ...]] = {
    ESTATUS_VIAJE_PROGRAMADO: (ESTATUS_VIAJE_EN_CURSO, ESTATUS_VIAJE_CANCELADO),
    ESTATUS_VIAJE_EN_CURSO: (ESTATUS_VIAJE_FINALIZADO, ESTATUS_VIAJE_CANCELADO),
    ESTATUS_VIAJE_FINALIZADO: (),
    ESTATUS_VIAJE_CANCELADO: (),
}

# Estatus en los que un viaje sigue "abierto" y ocupa a su vehículo y a su
# operador. Los usan las comprobaciones de disponibilidad.
ESTATUS_VIAJE_ABIERTOS: tuple[str, ...] = (
    ESTATUS_VIAJE_PROGRAMADO,
    ESTATUS_VIAJE_EN_CURSO,
)


# §11.7 — Incidentes.
# La escala de severidad estaba marcada como "regla pendiente" en el §11.7.
# Se fija con los tres valores que la simulación ya usa; son los que
# alimentan a los modelos como predictor de los retrasos anómalos.
CATALOGO_SEVERIDAD_INCIDENTE: tuple[str, ...] = ("BAJA", "MEDIA", "ALTA")

CATALOGO_FUENTE_INCIDENTE: tuple[str, ...] = ("MANUAL", "API_EXTERNA", "SIMULADO")

# §11.10 — Bitácora de seguimiento. El recálculo de ETA (RF-33) escribe
# aquí su rastro, que es el paso 4 del procedimiento del §17.3.
CATALOGO_TIPO_EVENTO_SEGUIMIENTO: tuple[str, ...] = (
    "SALIDA", "LLEGADA_PARADA", "INCIDENTE", "DESVIO",
    "RECALCULO_ETA", "REGRESO",
)

# RF-33 — El §17.3 propone sumar los minutos perdidos al ETA de las
# entregas pendientes, y ADVIERTE que ese recálculo lineal es un supuesto,
# no una regla confirmada: un incidente de 25 minutos podría no retrasar
# 25 minutos a la última parada del día. Se implementa como dice el
# documento y la respuesta del API lo declara, para que nadie lo tome por
# una certeza.
RECALCULO_ETA_ES_LINEAL: bool = True
ADVERTENCIA_RECALCULO_ETA: str = (
    "El recálculo suma linealmente los minutos perdidos al ETA de cada "
    "entrega pendiente. El §17.3 del documento técnico advierte que ese "
    "supuesto no está confirmado: un incidente de 25 minutos podría no "
    "retrasar 25 minutos a la última parada del día."
)


# §11.9 — Mantenimientos.
# RNP-05 se resuelve con la opción (b): preventivo y correctivo, que es lo
# que la simulación implementó y lo que distingue el servicio planificado
# de la reparación por falla.
TIPO_MANTENIMIENTO_PREVENTIVO: str = "PREVENTIVO"
TIPO_MANTENIMIENTO_CORRECTIVO: str = "CORRECTIVO"
CATALOGO_TIPO_MANTENIMIENTO: tuple[str, ...] = (
    TIPO_MANTENIMIENTO_PREVENTIVO,
    TIPO_MANTENIMIENTO_CORRECTIVO,
)

ESTATUS_MTTO_PROGRAMADO: str = "PROGRAMADO"
ESTATUS_MTTO_REALIZADO: str = "REALIZADO"
ESTATUS_MTTO_VENCIDO: str = "VENCIDO"
CATALOGO_ESTATUS_MANTENIMIENTO: tuple[str, ...] = (
    ESTATUS_MTTO_PROGRAMADO,
    ESTATUS_MTTO_REALIZADO,
    ESTATUS_MTTO_VENCIDO,
)

# Un mantenimiento vencido SÍ se puede realizar: es precisamente lo que
# devuelve el vehículo a operación. Lo que no existe es el camino de
# vuelta desde REALIZADO.
TRANSICIONES_ESTATUS_MANTENIMIENTO: dict[str, tuple[str, ...]] = {
    ESTATUS_MTTO_PROGRAMADO: (ESTATUS_MTTO_REALIZADO, ESTATUS_MTTO_VENCIDO),
    ESTATUS_MTTO_VENCIDO: (ESTATUS_MTTO_REALIZADO,),
    ESTATUS_MTTO_REALIZADO: (),
}

# RNP-04 — periodicidad. El documento recomendaba la opción (c), "lo
# primero que ocurra entre calendario y kilometraje", pero la simulación
# implementó la (a): cada 30 días de calendario, y sobre esos datos se
# construyeron el DW y `dias_desde_mantenimiento`. Se fija por calendario
# para no contradecir lo que el proyecto ya opera; pasar a la (c) sería un
# cambio de regla, no un ajuste de constante.
DIAS_PERIODICIDAD_MANTENIMIENTO: int = 30

# Días de anticipación con que RF-16 alerta de un mantenimiento próximo.
DIAS_AVISO_MANTENIMIENTO: int = 7


# --------------------------------------------------------------------------
# REGLAS AÚN PENDIENTES (no se convierten en enum hasta ser aprobadas)
#   RNP-13  ventanas horarias comprometidas con el cliente
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
# Interfaz web  (§8.2 — Jinja2 + Bootstrap servidos por el mismo FastAPI)
# --------------------------------------------------------------------------
FRONTEND_RAIZ = RAIZ_PROYECTO / "frontend"
FRONTEND_PLANTILLAS = FRONTEND_RAIZ / "templates"
FRONTEND_ESTATICOS = FRONTEND_RAIZ / "static"

# El navegador no puede mandar la cabecera `Authorization` al pedir una
# página: solo manda cookies. El mismo token JWT que usa el API viaja en
# esta cookie para las peticiones del navegador.
#
# HttpOnly: el JavaScript de la página NO puede leerla. Es lo que impide
# que un XSS se lleve la sesión, y por eso el token no se guarda en
# localStorage aunque sea más cómodo.
#
# SameSite=strict: el navegador no la adjunta en peticiones originadas
# desde otro sitio. Con autenticación por cookie eso es lo que sostiene la
# defensa contra CSRF, porque cualquier página externa que provocara un
# POST a esta API lo haría sin sesión.
COOKIE_SESION: str = "siglog_sesion"
COOKIE_SAMESITE: str = "strict"
# Solo por HTTPS. En desarrollo se sirve por http://127.0.0.1 y activarlo
# impediría entrar, así que sigue al entorno en vez de estar fijo.
COOKIE_SEGURA: bool = APP_ENTORNO.lower() in ("produccion", "production")


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
