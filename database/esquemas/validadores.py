"""
SIG-LOG — Sistema Integral de Gestión Logística
database/esquemas/validadores.py

Propósito
---------
Validadores `$jsonSchema` de MongoDB para las colecciones operativas.
Corresponden literalmente a las tablas de campos de §11.1 a §11.10 del
documento técnico base. No se añade ningún campo que no esté en el diseño.

Criterios aplicados
-------------------
1. `required` incluye únicamente los campos marcados como **O (obligatorio)**
   en el documento, más los campos comunes `origen_dato` y `activo`.
2. Los campos numéricos se declaran como `number` (acepta int, long y double)
   para no romper la carga cuando un valor entero llega sin decimales.
3. **Solo se declara `enum` en los catálogos confirmados.**
   Confirmados el 16/08/2026 e importados de `config.settings`:
   `entregas.estatus` (RNP-08) e `incidentes.tipo` (RNP-12).
   Siguen SIN enum por estar pendientes: `incidentes.severidad`
   (escala pendiente), `mantenimientos.tipo` (RNP-05) y
   `entregas.causa_retraso`. Fijarlos ahora sería inventar reglas.
4. `additionalProperties` queda en su valor por defecto (permitido): los
   campos derivados que el ETL agregue más adelante no romperán la carga.

Estos validadores se aplican por defecto con `validationAction="warn"`:
registran la violación en el log del servidor pero **no** bloquean la
escritura. Se puede endurecer a "error" con SIGLOG_VALIDACION=error.
"""

from __future__ import annotations

from typing import Any

from config import settings

# --------------------------------------------------------------------------
# Campos comunes a todas las colecciones (§11, encabezado)
# --------------------------------------------------------------------------
CAMPOS_COMUNES_REQUERIDOS: list[str] = ["origen_dato", "activo"]

PROPIEDADES_COMUNES: dict[str, Any] = {
    "origen_dato": {
        "bsonType": "string",
        "enum": ["REAL", "SIMULADO"],
        "description": "Distingue datos reales de datos simulados. Obligatorio.",
    },
    "activo": {
        "bsonType": "bool",
        "description": "Baja lógica. El registro nunca se elimina físicamente.",
    },
    "fecha_creacion": {"bsonType": "date"},
    "fecha_modificacion": {"bsonType": "date"},
}

_NUM = {"bsonType": ["number", "null"]}
_STR = {"bsonType": ["string", "null"]}
_FECHA = {"bsonType": ["date", "null"]}
_REF = {"bsonType": ["objectId", "null"]}


def _esquema(titulo: str, requeridos: list[str], propiedades: dict[str, Any]) -> dict[str, Any]:
    """Construye un validador $jsonSchema agregando los campos comunes."""
    props: dict[str, Any] = dict(PROPIEDADES_COMUNES)
    props.update(propiedades)
    todos_requeridos = list(dict.fromkeys(requeridos + CAMPOS_COMUNES_REQUERIDOS))
    return {
        "$jsonSchema": {
            "bsonType": "object",
            "title": titulo,
            "required": todos_requeridos,
            "properties": props,
        }
    }


# --------------------------------------------------------------------------
# §11.1 clientes
# --------------------------------------------------------------------------
CLIENTES = _esquema(
    "clientes — catálogo de clientes y puntos de entrega (§11.1)",
    ["codigo_cliente", "nombre", "direcciones"],
    {
        "codigo_cliente": {"bsonType": "string", "description": "Clave de negocio, p. ej. CLI-001"},
        "nombre": {"bsonType": "string"},
        "razon_social": _STR,
        "tipo_cliente": _STR,  # catálogo pendiente (RNP-07)
        "telefono": _STR,
        "email": _STR,
        "direcciones": {
            "bsonType": "array",
            "minItems": 1,
            "items": {"bsonType": "object"},
            "description": "Documentos embebidos: alias, calle, colonia, municipio, cp, ubicacion...",
        },
        "ventana_horaria": {"bsonType": ["object", "null"]},  # depende de RNP-13
        "total_entregas": _NUM,
    },
)

# --------------------------------------------------------------------------
# §11.2 vehiculos
# --------------------------------------------------------------------------
VEHICULOS = _esquema(
    "vehiculos — flotilla y estado operativo (§11.2)",
    ["codigo_vehiculo", "placa", "marca", "modelo", "anio", "tipo_vehiculo", "estado_operativo"],
    {
        "codigo_vehiculo": {"bsonType": "string"},
        "placa": {"bsonType": "string"},
        "marca": {"bsonType": "string"},
        "modelo": {"bsonType": "string"},
        "anio": {"bsonType": "number"},
        "tipo_vehiculo": {"bsonType": "string"},
        "capacidad_carga_kg": _NUM,
        "capacidad_tanque_litros": _NUM,
        "rendimiento_nominal_km_l": _NUM,
        "odometro_actual_km": _NUM,
        "estado_operativo": {
            "bsonType": "string",
            "enum": ["DISPONIBLE", "EN_RUTA", "EN_MANTENIMIENTO", "BAJA"],
        },
        "ruta_asignada_id": _REF,
        "fecha_ultimo_mantenimiento": _FECHA,
        "fecha_proximo_mantenimiento": _FECHA,
        "rendimiento_real_km_l": _NUM,
        # ADICIÓN A §11.2 — pendiente de tu aprobación (ver PA-1).
        # El documento coloca `tipo_combustible` solo en la colección
        # `combustible`; aquí sirve como atributo del vehículo.
        "tipo_combustible": _STR,
    },
)

# --------------------------------------------------------------------------
# §11.3 operadores
# --------------------------------------------------------------------------
OPERADORES = _esquema(
    "operadores — personal de conducción (§11.3)",
    ["codigo_operador", "nombre_completo", "estado"],
    {
        "codigo_operador": {"bsonType": "string"},
        "nombre_completo": {"bsonType": "string"},
        "licencia": {"bsonType": ["object", "null"]},
        "fecha_ingreso": _FECHA,
        "estado": {"bsonType": "string", "enum": ["ACTIVO", "INACTIVO"]},
        "vehiculo_asignado_id": _REF,
        "total_entregas": _NUM,
        "porcentaje_entregas_a_tiempo": _NUM,
    },
)

# --------------------------------------------------------------------------
# §11.4 rutas
# --------------------------------------------------------------------------
RUTAS = _esquema(
    "rutas — definición planificada del recorrido (§11.4)",
    ["codigo_ruta", "nombre", "origen", "paradas", "hora_salida_programada"],
    {
        "codigo_ruta": {"bsonType": "string"},
        "nombre": {"bsonType": "string"},
        "zona": _STR,
        "origen": {"bsonType": "object", "description": "Centro de distribución"},
        "paradas": {
            "bsonType": "array",
            "minItems": 1,
            "items": {"bsonType": "object"},
            "description": "Array ordenado: orden, cliente_id, distancia_desde_anterior_km, tiempo_estimado_min",
        },
        "distancia_total_km": _NUM,
        "tiempo_estimado_total_min": _NUM,
        "numero_paradas": _NUM,
        "dias_operacion": {"bsonType": ["array", "null"]},  # depende de RNP-06
        "hora_salida_programada": {"bsonType": "string"},
        "vehiculo_asignado_id": _REF,
        # ADICIÓN A §11.4 — pendiente de tu aprobación (ver PA-1).
        # Velocidad efectiva de la ruta; PA-2 la necesita para calcular el
        # tiempo real de traslado de forma coherente con el tiempo estimado.
        "velocidad_efectiva_kmh": _NUM,
        # D-3 (16/08/2026): se elimina `activa`; se usa el campo común `activo`.
    },
)

# --------------------------------------------------------------------------
# §11.5 viajes
# --------------------------------------------------------------------------
VIAJES = _esquema(
    "viajes — ejecución de una ruta en una fecha (§11.5)",
    ["folio_viaje", "fecha", "ruta_id", "vehiculo_id", "operador_id",
     "hora_salida_programada", "estatus"],
    {
        "folio_viaje": {"bsonType": "string"},
        "fecha": {"bsonType": "date"},
        "ruta_id": {"bsonType": "objectId"},
        "vehiculo_id": {"bsonType": "objectId"},
        "operador_id": {"bsonType": "objectId"},
        "hora_salida_programada": {"bsonType": "date"},
        "hora_salida_real": _FECHA,
        "hora_regreso_real": _FECHA,
        "odometro_inicial_km": _NUM,
        "odometro_final_km": _NUM,
        "km_recorridos": _NUM,
        "estatus": {
            "bsonType": "string",
            "enum": ["PROGRAMADO", "EN_CURSO", "FINALIZADO", "CANCELADO"],
        },
        "total_entregas_programadas": _NUM,
        "total_entregas_completadas": _NUM,
        "total_incidentes": _NUM,
        "duracion_real_min": _NUM,
        "retraso_salida_min": _NUM,
    },
)

# --------------------------------------------------------------------------
# §11.6 entregas — colección crítica del proyecto
# --------------------------------------------------------------------------
ENTREGAS = _esquema(
    "entregas — hecho operativo central y fuente del dataset de ML (§11.6)",
    ["folio_entrega", "viaje_id", "ruta_id", "cliente_id", "nombre_cliente",
     "vehiculo_id", "placa", "operador_id", "nombre_operador", "orden_parada",
     "fecha", "hora_estimada_llegada", "tiempo_estimado_min", "distancia_km",
     "estatus"],
    {
        "folio_entrega": {"bsonType": "string"},
        "viaje_id": {"bsonType": "objectId"},
        "ruta_id": {"bsonType": "objectId"},
        "cliente_id": {"bsonType": "objectId"},
        "nombre_cliente": {"bsonType": "string"},
        "vehiculo_id": {"bsonType": "objectId"},
        "placa": {"bsonType": "string"},
        "operador_id": {"bsonType": "objectId"},
        "nombre_operador": {"bsonType": "string"},
        "orden_parada": {"bsonType": "number"},
        "fecha": {"bsonType": "date"},
        "hora_estimada_llegada": {"bsonType": "date"},
        "hora_real_llegada": _FECHA,
        "hora_estimada_recalculada": _FECHA,
        "tiempo_estimado_min": {"bsonType": "number"},
        "tiempo_real_min": _NUM,
        "retraso_min": _NUM,          # variable objetivo de regresión
        "es_retraso": _NUM,           # variable objetivo de clasificación
        "distancia_km": {"bsonType": "number"},
        "estatus": {
            "bsonType": "string",
            "enum": list(settings.CATALOGO_ESTATUS_ENTREGA),  # RNP-08 confirmada
        },
        "historial_estatus": {"bsonType": ["array", "null"]},
        "incidentes_ids": {"bsonType": ["array", "null"]},
        "causa_retraso": _STR,        # catálogo pendiente RNP-12: sin enum
        "observaciones": _STR,        # dato NO estructurado (evidencia U-II)
        "dia_semana": _NUM,
        "franja_horaria": _STR,
        "es_fin_semana": _NUM,
    },
)

# --------------------------------------------------------------------------
# §11.7 incidentes
# --------------------------------------------------------------------------
INCIDENTES = _esquema(
    "incidentes — eventos que afectan el tiempo de traslado (§11.7)",
    ["folio_incidente", "tipo", "severidad", "fecha_hora_inicio", "fuente"],
    {
        "folio_incidente": {"bsonType": "string"},
        "tipo": {
            "bsonType": "string",
            "enum": list(settings.CATALOGO_TIPOS_INCIDENTE),  # RNP-12 confirmada
        },
        "severidad": {"bsonType": "string"},  # escala pendiente: sin enum
        "fecha_hora_inicio": {"bsonType": "date"},
        "fecha_hora_fin": _FECHA,
        "duracion_min": _NUM,
        "viaje_id": _REF,
        "ruta_id": _REF,
        "entregas_afectadas": {"bsonType": ["array", "null"]},
        "ubicacion": {"bsonType": ["object", "null"]},
        "descripcion": _STR,          # dato NO estructurado
        "tiempo_perdido_estimado_min": _NUM,
        "fuente": {
            "bsonType": "string",
            "enum": ["MANUAL", "API_EXTERNA", "SIMULADO"],
        },
    },
)

# --------------------------------------------------------------------------
# §11.8 combustible
# --------------------------------------------------------------------------
COMBUSTIBLE = _esquema(
    "combustible — cargas para analizar consumo, rendimiento y costo (§11.8)",
    ["folio_carga", "vehiculo_id", "fecha", "litros", "precio_por_litro", "odometro_km"],
    {
        "folio_carga": {"bsonType": "string"},
        "vehiculo_id": {"bsonType": "objectId"},
        "viaje_id": _REF,
        "fecha": {"bsonType": "date"},
        "litros": {"bsonType": "number"},
        "precio_por_litro": {"bsonType": "number"},
        "costo_total": _NUM,
        "odometro_km": {"bsonType": "number"},
        "km_recorridos_desde_carga_anterior": _NUM,
        "rendimiento_km_l": _NUM,
        "tipo_combustible": _STR,
        "estacion": _STR,
    },
)

# --------------------------------------------------------------------------
# §11.9 mantenimientos
# --------------------------------------------------------------------------
MANTENIMIENTOS = _esquema(
    "mantenimientos — historial preventivo y correctivo (§11.9)",
    ["folio_mantenimiento", "vehiculo_id", "tipo", "fecha_programada", "estatus"],
    {
        "folio_mantenimiento": {"bsonType": "string"},
        "vehiculo_id": {"bsonType": "objectId"},
        "tipo": {"bsonType": "string"},  # PREVENTIVO/CORRECTIVO pendiente RNP-05: sin enum
        "fecha_programada": {"bsonType": "date"},
        "fecha_realizada": _FECHA,
        "odometro_km": _NUM,
        "descripcion": _STR,
        "costo": _NUM,
        "duracion_dias": _NUM,
        "estatus": {
            "bsonType": "string",
            "enum": ["PROGRAMADO", "REALIZADO", "VENCIDO"],
        },
        "proximo_mantenimiento_fecha": _FECHA,
    },
)

# --------------------------------------------------------------------------
# §11.10 seguimiento_eventos
# --------------------------------------------------------------------------
SEGUIMIENTO_EVENTOS = _esquema(
    "seguimiento_eventos — bitácora de la ruta en ejecución (§11.10)",
    ["viaje_id", "tipo_evento", "fecha_hora"],
    {
        "viaje_id": {"bsonType": "objectId"},
        "entrega_id": _REF,
        "tipo_evento": {
            "bsonType": "string",
            "enum": ["SALIDA", "LLEGADA_PARADA", "INCIDENTE", "DESVIO",
                     "RECALCULO_ETA", "REGRESO"],
        },
        "fecha_hora": {"bsonType": "date"},
        "ubicacion": {"bsonType": ["object", "null"]},
        "eta_anterior": _FECHA,
        "eta_nuevo": _FECHA,
        "motivo": _STR,
    },
)


# --------------------------------------------------------------------------
# Registro consultado por database/inicializar_bd.py
# --------------------------------------------------------------------------
VALIDADORES: dict[str, dict[str, Any]] = {
    "clientes": CLIENTES,
    "vehiculos": VEHICULOS,
    "operadores": OPERADORES,
    "rutas": RUTAS,
    "viajes": VIAJES,
    "entregas": ENTREGAS,
    "incidentes": INCIDENTES,
    "combustible": COMBUSTIBLE,
    "mantenimientos": MANTENIMIENTOS,
    "seguimiento_eventos": SEGUIMIENTO_EVENTOS,
}

# Las colecciones analíticas (hecho_entrega, dim_*, modelos_ml, predicciones,
# clusters_rutas) NO llevan validador todavía: su lista definitiva de columnas
# se fija en la actividad de ETL. Crear un validador ahora sería inventar el
# esquema antes de diseñarlo.
