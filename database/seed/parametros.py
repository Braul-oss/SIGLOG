"""
SIG-LOG — Sistema Integral de Gestión Logística
database/seed/parametros.py

╔══════════════════════════════════════════════════════════════════════════╗
║  ⚠  DATOS SIMULADOS                                                       ║
║                                                                          ║
║  Ninguna cifra de este archivo describe una empresa real.                ║
║  Decisión C-02: no existen datos reales de vehículos, clientes,          ║
║  operadores, rutas, entregas, tiempos, combustible, mantenimiento ni      ║
║  incidentes. Todos los valores son PARÁMETROS DE DISEÑO de una           ║
║  simulación académica, elegidos por suficiencia estadística y            ║
║  consistencia interna, no por verosimilitud comercial.                    ║
║                                                                          ║
║  Todo documento generado lleva  origen_dato: "SIMULADO".                 ║
╚══════════════════════════════════════════════════════════════════════════╝

Fuente: ANEXO B del documento técnico base, aprobado el 16/08/2026.
Cambiar cualquier valor de aquí NO requiere tocar el código del generador
(§16.4 del documento técnico).
"""

from __future__ import annotations

from datetime import date

# ==========================================================================
# SEMILLA
# La misma semilla 42 usada en todos los ejercicios de clase
# (train_test_split, KMeans, randomSplit). Garantiza reproducibilidad.
# ==========================================================================
SEMILLA: int = 42

ORIGEN_DATO: str = "SIMULADO"


# ==========================================================================
# B.1 — DIMENSIONAMIENTO DE LA FLOTILLA Y LA OPERACIÓN
# ==========================================================================
NUM_VEHICULOS: int = 20
NUM_RUTAS: int = 20          # RN-04: 1 ruta por vehículo ⇒ debe igualar a NUM_VEHICULOS
NUM_CLIENTES: int = 100
NUM_OPERADORES: int = 24     # 20 titulares + 4 de relevo (habilita rotación, RNP-03 b)

PARADAS_POR_RUTA_MIN: int = 3
PARADAS_POR_RUTA_MAX: int = 8

# Tipos de vehículo (habilita dim_tipo_vehiculo del modelo copo de nieve §14.3)
TIPOS_VEHICULO: tuple[str, ...] = ("LIGERO", "MEDIANO", "PESADO")
DISTRIBUCION_TIPOS_VEHICULO: dict[str, int] = {"LIGERO": 8, "MEDIANO": 7, "PESADO": 5}

# Zonas geográficas (habilita dim_zona; da estructura al clustering de rutas)
ZONAS: tuple[str, ...] = ("NORTE", "SUR", "ORIENTE", "PONIENTE")

# Municipios por zona. Supuesto S-01: operación local del Valle de Toluca.
MUNICIPIOS_POR_ZONA: dict[str, tuple[str, ...]] = {
    "NORTE":    ("Almoloya de Juárez", "Otzolotepec", "Xonacatlán", "Temoaya"),
    "SUR":      ("Metepec", "Calimaya", "Mexicaltzingo", "Chapultepec"),
    "ORIENTE":  ("Lerma", "San Mateo Atenco", "Ocoyoacac"),
    "PONIENTE": ("Toluca", "Zinacantepec", "Almoloya del Río"),
}
ESTADO: str = "México"


# ==========================================================================
# B.2 — HORIZONTE TEMPORAL
# ==========================================================================
FECHA_INICIO: date = date(2026, 2, 1)
FECHA_FIN: date = date(2026, 7, 31)
# Días de operación: lunes(0) a sábado(5). Domingo excluido.
DIAS_OPERACION_SEMANA: tuple[int, ...] = (0, 1, 2, 3, 4, 5)
DIAS_OPERACION_NOMBRES: tuple[str, ...] = (
    "LUNES", "MARTES", "MIERCOLES", "JUEVES", "VIERNES", "SABADO",
)


# ==========================================================================
# B.3 — DISTANCIA Y TIEMPO
# ==========================================================================
DISTANCIA_ENTRE_PARADAS_KM: tuple[float, float] = (3.0, 25.0)
DISTANCIA_TOTAL_RUTA_KM: tuple[float, float] = (25.0, 120.0)
VELOCIDAD_EFECTIVA_KMH: tuple[float, float] = (18.0, 35.0)
TIEMPO_SERVICIO_PARADA_MIN: tuple[int, int] = (10, 20)
HORA_SALIDA_PROGRAMADA: tuple[str, str] = ("06:00", "09:00")
PASO_MINUTOS_SALIDA: int = 15


# ==========================================================================
# B.4 — PARÁMETROS DEL FENÓMENO A PREDECIR  (los usa PA-2)
# ==========================================================================
UMBRAL_RETRASO_MIN: int = 15                       # RNP-01 confirmada
FRANJAS_PICO: tuple[tuple[int, int], ...] = ((7, 10), (17, 20))
FACTOR_HORA_PICO: tuple[float, float] = (1.15, 1.35)
FACTOR_DIA_SEMANA: dict[int, float] = {           # lunes=0 … sábado=5
    0: 1.06, 1: 1.00, 2: 1.00, 3: 1.02, 4: 1.08, 5: 0.95,
}
RUIDO_RELATIVO: float = 0.12                       # ±12%

# --- Línea base de planificación (necesaria para calibrar el fenómeno) -----
# El `tiempo_estimado_min` de una ruta NO se calcula suponiendo calles vacías
# y vehículo nuevo: el planificador lo ajusta con el desempeño histórico de
# esa ruta con ese vehículo. Por eso el tiempo real se compara contra las
# condiciones TÍPICAS de la ruta, no contra un escenario ideal.
#
# Sin este término, cada viaje que toca la hora pico saldría retrasado por
# construcción (>90% de retrasos), incompatible con el 25-30% que fija este
# mismo anexo. La línea base se calcula por ruta con estos supuestos:
DIAS_DESDE_MTTO_TIPICO: int = 15          # punto medio del ciclo de 30 días
FACTOR_PICO_TIPICO: float = 1.25          # punto medio del rango 1.15–1.35

# Ajuste fino residual. 1.00 = el planificador acierta en promedio.
# Por encima de 1.00 el planificador es conservador (estima de más).
FACTOR_CONDICIONES_TIPICAS: float = 1.035
PROPORCION_RETRASOS_OBJETIVO: tuple[float, float] = (0.25, 0.30)
R2_ESPERADO: tuple[float, float] = (0.55, 0.80)


# ==========================================================================
# B.5 — COMBUSTIBLE Y MANTENIMIENTO  (los usa PA-3)
# ==========================================================================
RENDIMIENTO_NOMINAL_KM_L: dict[str, tuple[float, float]] = {
    "LIGERO":  (8.0, 11.0),
    "MEDIANO": (5.0, 7.0),
    "PESADO":  (3.0, 5.0),
}
CAPACIDAD_TANQUE_L: dict[str, int] = {"LIGERO": 60, "MEDIANO": 120, "PESADO": 200}
VARIACION_RENDIMIENTO_REAL: float = 0.15
PRECIO_POR_LITRO: tuple[float, float] = (24.00, 26.50)

# RNP-04, opción (c): cada 30 días o 8,000 km, lo primero que ocurra.
MANTENIMIENTO_DIAS: int = 30
MANTENIMIENTO_KM: int = 8000
PROPORCION_PREVENTIVO: float = 0.80
COSTO_MANTENIMIENTO_PREVENTIVO: tuple[float, float] = (2500.0, 5000.0)
COSTO_MANTENIMIENTO_CORRECTIVO: tuple[float, float] = (6000.0, 20000.0)


# ==========================================================================
# B.6 — INCIDENTES  (los usa PA-3)
# ==========================================================================
INCIDENTES_FRECUENCIA: dict[str, float] = {
    "TRAFICO": 0.55, "CLIMA": 0.15, "ACCIDENTE": 0.12,
    "FALLA_VEHICULO": 0.08, "CLIENTE_AUSENTE": 0.06, "PROTESTA": 0.04,
}
INCIDENTES_DURACION_MIN: dict[str, tuple[int, int]] = {
    "TRAFICO": (10, 45), "CLIMA": (15, 40), "ACCIDENTE": (30, 90),
    "FALLA_VEHICULO": (40, 180), "CLIENTE_AUSENTE": (10, 25), "PROTESTA": (45, 150),
}
PROPORCION_VIAJES_CON_INCIDENTE: float = 0.12


# ==========================================================================
# B.7 — PARÁMETROS ADICIONALES AL ANEXO B
# --------------------------------------------------------------------------
# ⚠ Estos valores NO están en el Anexo B aprobado. Fueron necesarios para
#   completar PA-1 y quedan marcados para tu revisión. Cambiarlos es trivial.
# ==========================================================================

# Odómetro inicial: se deriva de la antigüedad del vehículo.
ANIO_MIN_VEHICULO: int = 2014
ANIO_MAX_VEHICULO: int = 2024
KM_POR_ANIO: tuple[int, int] = (25_000, 45_000)

# RNP-07 — catálogo de tipo de cliente. SIGUE PENDIENTE DE TU APROBACIÓN.
# Se necesita para responder la pregunta 9 del dashboard
# ("¿qué servicio tiene mayor demanda?"). Propuesta base:
CATALOGO_TIPO_CLIENTE: dict[str, float] = {
    "MINORISTA": 0.45,
    "MAYORISTA": 0.25,
    "INDUSTRIAL": 0.20,
    "INSTITUCIONAL": 0.10,
}

# Centro de distribución (origen común de todas las rutas)
CENTRO_DISTRIBUCION: dict[str, str] = {
    "nombre": "Centro de Distribución SIG-LOG",
    "calle": "Vialidad Adolfo López Mateos",
    "numero": "1200",
    "colonia": "Parque Industrial Toluca",
    "municipio": "Toluca",
    "estado": ESTADO,
    "cp": "50200",
}

# Probabilidad de que un cliente tenga una segunda dirección (supuesto S-05)
PROBABILIDAD_SEGUNDA_DIRECCION: float = 0.15

# ---- Añadidos en PA-2 -----------------------------------------------------
# Retraso en la salida del viaje. Distribución gamma: la mayoría sale casi a
# tiempo, unos pocos con retraso grande. Se propaga íntegro a todas las
# entregas del día (Anexo B.4).
RETRASO_SALIDA_FORMA: float = 1.6
RETRASO_SALIDA_ESCALA: float = 4.0
RETRASO_SALIDA_MAX_MIN: int = 45

# Efecto de la antigüedad del vehículo sobre el tiempo real (Anexo B.4:
# "vehículos más antiguos, ligeramente más lentos").
FACTOR_ANTIGUEDAD_POR_ANIO: float = 0.010

# Efecto de los días transcurridos desde el último mantenimiento
# (Anexo B.4: "efecto leve y creciente"). Se satura a los 60 días.
FACTOR_MANTENIMIENTO_POR_DIA: float = 0.0018
DIAS_MANTENIMIENTO_SATURACION: int = 60

# Kilómetros reales del viaje respecto de la distancia planificada de la
# ruta: incluye el retorno al centro de distribución y desvíos menores.
FACTOR_RETORNO_KM: float = 1.25
VARIACION_KM_VIAJE: float = 0.05

# Viajes cancelados (vehículo no disponible, cliente cancela la jornada).
PROPORCION_VIAJES_CANCELADOS: float = 0.01

# Recarga de combustible: se llena cuando el consumo acumulado alcanza esta
# fracción del tanque. Calibrado para aproximar las ≈1,500 cargas del B.2.
FRACCION_TANQUE_RECARGA: float = 0.23

# Mantenimiento vencido: proporción de servicios programados que no se
# realizaron en fecha. Alimenta la alerta de mantenimiento (RF-16).
PROPORCION_MANTENIMIENTO_VENCIDO: float = 0.05
DURACION_MANTENIMIENTO_DIAS: tuple[int, int] = (1, 2)

# ---- Defectos de calidad deliberados (evidencia de la Unidad II) ----------
# Sin nulos, duplicados ni outliers, la actividad de limpieza (PA-5) no
# tendría nada que limpiar y la Unidad II quedaría sin evidencia real.
PROPORCION_SIN_HORA_REAL: float = 0.02      # captura omitida en campo
PROPORCION_ENTREGAS_DUPLICADAS: float = 0.005  # doble captura del mismo evento
PROPORCION_CON_OBSERVACIONES: float = 0.18  # texto libre (dato NO estructurado)

OBSERVACIONES_LIBRES: tuple[str, ...] = (
    "Cliente recibió sin novedad.",
    "se entrego en anden trasero",
    "Firma de recibido ilegible",
    "El cliente pidió reprogramar la siguiente visita",
    "TRAFICO PESADO EN LA AVENIDA",
    "Acceso bloqueado por obra, se dejó en recepción",
    "faltaba personal en el almacen del cliente",
    "Entrega parcial, se acordó completar mañana",
    "Lluvia intensa durante la descarga",
    "sin observaciones",
)
ESTACIONES_SERVICIO: tuple[str, ...] = (
    "Estación Tollocan", "Estación Las Torres", "Estación Aeropuerto",
    "Estación Metepec Centro", "Estación Lerma Industrial", "Estación Zinacantepec",
)
DESCRIPCIONES_INCIDENTE: dict[str, tuple[str, ...]] = {
    "TRAFICO": ("Congestión vehicular en vialidad principal",
                "trafico lento por hora pico", "Embotellamiento en el entronque"),
    "CLIMA": ("Lluvia intensa reduce la velocidad de circulación",
              "granizada", "Neblina densa en la carretera"),
    "ACCIDENTE": ("Choque entre particulares bloquea un carril",
                  "accidente vial adelante", "Volcadura, circulación desviada"),
    "FALLA_VEHICULO": ("Falla mecánica, se requirió asistencia",
                       "llanta ponchada", "Sobrecalentamiento del motor"),
    "CLIENTE_AUSENTE": ("Nadie en el domicilio al momento de la entrega",
                        "cliente cerrado", "Almacén del cliente sin personal"),
    "PROTESTA": ("Manifestación bloquea la vialidad",
                 "bloqueo carretero", "Marcha sobre avenida principal"),
}

# Antigüedad de los operadores
ANIO_INGRESO_OPERADOR: tuple[int, int] = (2018, 2025)
TIPOS_LICENCIA: tuple[str, ...] = ("B", "C", "E")
VIGENCIA_LICENCIA_ANIOS: tuple[int, int] = (2026, 2029)


# ==========================================================================
# VOCABULARIO PARA NOMBRES SIMULADOS
# Combinaciones sintéticas. No corresponden a ninguna empresa ni persona real.
# ==========================================================================
GIROS_COMERCIALES: tuple[str, ...] = (
    "Abarrotes", "Ferretería", "Papelería", "Farmacia", "Refaccionaria",
    "Materiales", "Distribuidora", "Comercializadora", "Almacenes",
    "Autoservicio", "Bodega", "Insumos", "Suministros", "Depósito",
    "Mercería", "Panificadora", "Lácteos", "Textiles", "Plásticos", "Vidrios",
)
APELATIVOS_COMERCIALES: tuple[str, ...] = (
    "del Valle", "San Miguel", "La Providencia", "El Roble", "Santa Fe",
    "Los Pinos", "La Merced", "El Progreso", "San Bernardino", "La Aurora",
    "Cinco Estrellas", "Las Torres", "El Águila", "La Esperanza", "Colón",
    "San Buenaventura", "Reforma", "La Purísima", "El Cerrito", "Nueva Era",
    "Independencia", "La Joya", "Tollocan", "Matlazincas", "Xinantécatl",
)
SUFIJOS_SOCIETARIOS: tuple[str, ...] = ("S.A. de C.V.", "S. de R.L.", "")

NOMBRES_PILA: tuple[str, ...] = (
    "Juan", "Miguel", "José", "Luis", "Carlos", "Jorge", "Ricardo", "Fernando",
    "Roberto", "Alejandro", "Ernesto", "Guadalupe", "Martha", "Verónica",
    "Patricia", "Rosa", "Alberto", "Gerardo", "Salvador", "Rubén",
    "Hugo", "Ismael", "Efraín", "Noé", "Abel", "Raúl", "Octavio", "Sergio",
)
APELLIDOS: tuple[str, ...] = (
    "Hernández", "García", "Martínez", "López", "González", "Pérez", "Sánchez",
    "Ramírez", "Cruz", "Flores", "Gómez", "Díaz", "Reyes", "Morales", "Jiménez",
    "Vargas", "Castillo", "Mendoza", "Romero", "Álvarez", "Ortega", "Guerrero",
    "Medina", "Aguilar", "Rojas", "Cabrera", "Estrada", "Peralta",
)

CALLES: tuple[str, ...] = (
    "Av. Independencia", "Calle Hidalgo", "Av. Morelos", "Calle Juárez",
    "Av. Las Torres", "Calle Allende", "Blvd. Aeropuerto", "Av. Tollocan",
    "Calle Zaragoza", "Av. Solidaridad", "Calle Guerrero", "Av. Constituyentes",
    "Calle Aldama", "Av. Miguel Alemán", "Calle Nicolás Bravo",
)
COLONIAS: tuple[str, ...] = (
    "Centro", "San Sebastián", "Santa Clara", "La Merced", "Universidad",
    "Industrial", "Reforma", "Del Parque", "Santa Ana", "Las Américas",
    "San Lorenzo", "El Seminario", "Vértice", "Izcalli", "La Providencia",
)

MARCAS_POR_TIPO: dict[str, tuple[tuple[str, str], ...]] = {
    "LIGERO": (
        ("Nissan", "NP300"), ("Chevrolet", "Tornado"), ("Ford", "Transit"),
        ("Volkswagen", "Crafter"), ("Renault", "Kangoo"),
    ),
    "MEDIANO": (
        ("Isuzu", "ELF 600"), ("Hino", "Serie 300"), ("Ford", "F-350"),
        ("Chevrolet", "NPR"), ("Mercedes-Benz", "Accelo"),
    ),
    "PESADO": (
        ("Kenworth", "T370"), ("Freightliner", "M2 106"),
        ("International", "DuraStar"), ("Volvo", "VM 270"),
    ),
}
TIPOS_COMBUSTIBLE: tuple[str, ...] = ("DIESEL", "GASOLINA")
