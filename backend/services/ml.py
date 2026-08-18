"""
SIG-LOG — Sistema Integral de Gestión Logística
backend/services/ml.py

MODELOS DE MACHINE LEARNING EXPUESTOS POR EL API  (§12.3, §15.4)

Este módulo **no entrena nada**. Los modelos se entrenan en
`ml/supervisado/` y `ml/no_supervisado/`, se serializan en
`ml/modelos_guardados/` y su ficha queda en la colección `modelos_ml`. Aquí
solo se cargan y se usan.

Es el paso que el §15.4 llama "integración posterior en la aplicación", y
es lo que separa un proyecto de extracción de conocimiento de un ejercicio
de laboratorio: el modelo entrenado con el histórico vuelve a la operación
y dice, antes de que salga el camión, qué entregas van a llegar tarde.

Las tres piezas
---------------
`modelos()`            la ficha de los cuatro modelos vigentes: algoritmo,
                       escenario, métricas y variables con las que se
                       aprobaron. Se lee de `modelos_ml`, no se recalcula.

`predecir_retraso()`   arma el vector de variables de una entrega real y
                       aplica el clasificador y el regresor del escenario
                       que corresponda.

`clusters_rutas()`     los grupos de rutas de PA-9, leídos de
                       `clusters_rutas` con su perfil y su recomendación.

Los dos escenarios (§15.2)
--------------------------
PLANEACION  usa solo lo que se sabe al programar el viaje. Es el escenario
            útil para decidir, porque todavía se puede cambiar algo.

EN_RUTA     añade lo ya ocurrido —retraso de salida e incidentes—. Predice
            mucho mejor (ROC-AUC 0.92 contra 0.78) pero avisa más tarde.

El escenario no lo elige quien llama: lo determina el estado del viaje. Si
el viaje aún no ha salido no existen `retraso_salida_min` ni incidentes, y
pedir EN_RUTA sería inventar datos. Esa comprobación es la que evita que la
fuga de información que se cuidó al entrenar (§15.1) se cuele al predecir.

Origen de las variables
-----------------------
El vector tiene que ser **el mismo** que vio el modelo al entrenar. Si una
variable se calcula aquí con otra fórmula, la predicción deja de valer,
aunque el número salga con buena cara. Por eso cada variable se toma de
donde la tomó el ETL:

- las de la ruta (velocidad efectiva, paradas, distancia total) de la
  colección `rutas`, que es de donde las lee `enriquecimiento.dataset_rutas`
  sin recalcularlas;
- `franja_horaria` con `etl.transformacion.franja_de`, la misma función,
  para que los cortes de las franjas se definan en un solo sitio;
- `experiencia_operador_meses` con la fórmula del ETL —días desde el
  ingreso entre 30.44—, evaluada a la fecha de la entrega.

Y si alguna falta, se falla en vez de rellenarla: un valor inventado
produce una cifra que parece una predicción sin serlo.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from bson import ObjectId
from pymongo.database import Database

from backend.utils.errores import (
    NoEncontrado,
    ReglaDeNegocio,
    ServicioNoDisponible,
)
from config import settings
from etl.transformacion import franja_de
from ml import evaluacion

ESCENARIO_PLANEACION = "PLANEACION"
ESCENARIO_EN_RUTA = "EN_RUTA"

# Estatus de viaje en los que ya ocurrió la salida: solo entonces existen
# `retraso_salida_min` e incidentes acumulados (RNP del catálogo de viajes).
ESTATUS_VIAJE_INICIADO = (settings.ESTATUS_VIAJE_EN_CURSO,
                          settings.ESTATUS_VIAJE_FINALIZADO)

# Entregas sobre las que tiene sentido predecir (RNP-08). Una entrega ya
# cerrada no se predice: se mide.
ESTATUS_PREDECIBLES = ("PROGRAMADA", "EN_RUTA")

_MODELOS_EN_MEMORIA: dict[str, Any] = {}


# ==========================================================================
# CATÁLOGO DE MODELOS
# ==========================================================================
def modelos(bd: Database) -> dict[str, Any]:
    """
    Ficha de los modelos entrenados, tal como la dejó `registrar_modelo()`.

    Se devuelve también si el binario existe en disco: un modelo registrado
    cuyo `.joblib` se borró aparecería como disponible y fallaría al primer
    intento de predecir. Es mejor decirlo aquí.
    """
    fichas = list(bd["modelos_ml"].find({}, {"_id": 0}).sort("nombre", 1))
    if not fichas:
        raise ServicioNoDisponible(
            "No hay modelos registrados en `modelos_ml`. Ejecuta antes: "
            "python -m ml.supervisado.clasificacion_retraso y "
            "python -m ml.supervisado.regresion_retraso.")

    for ficha in fichas:
        archivo = evaluacion.CARPETA_MODELOS / f"{ficha['nombre']}.joblib"
        ficha["binario_disponible"] = archivo.exists()
        if isinstance(ficha.get("fecha_entrenamiento"), datetime):
            ficha["fecha_entrenamiento"] = ficha["fecha_entrenamiento"]

    clasificacion = [f for f in fichas if f["tipo"] == "CLASIFICACION"]
    regresion = [f for f in fichas if f["tipo"] == "REGRESION"]
    faltantes = [f["nombre"] for f in fichas if not f["binario_disponible"]]

    partes = []
    for ficha in sorted(clasificacion, key=lambda f: f["escenario"]):
        partes.append(f"{ficha['escenario'].lower()} ROC-AUC "
                      f"{ficha['metricas'].get('roc_auc', 0):.2f}")
    lectura = (
        f"{len(fichas)} modelos vigentes: {len(clasificacion)} de "
        f"clasificación y {len(regresion)} de regresión, entrenados con "
        f"semilla {fichas[0].get('semilla')} sobre el umbral de "
        f"{settings.UMBRAL_RETRASO_MIN} minutos. "
        + (f"Clasificación: {'; '.join(partes)}. " if partes else "")
        + "El escenario EN_RUTA predice mejor porque incorpora lo ya "
          "ocurrido, pero avisa más tarde: PLANEACION es el que deja "
          "margen para decidir.")
    if faltantes:
        lectura += (f" Atención: {len(faltantes)} modelo(s) sin binario en "
                    f"disco ({', '.join(faltantes)}); no se puede predecir "
                    "con ellos hasta reentrenarlos.")

    return {
        "modelos": fichas,
        "total": len(fichas),
        "escenarios": {
            ESCENARIO_PLANEACION: evaluacion.columnas_del_escenario(
                ESCENARIO_PLANEACION),
            ESCENARIO_EN_RUTA: evaluacion.columnas_del_escenario(
                ESCENARIO_EN_RUTA),
        },
        "umbral_retraso_min": settings.UMBRAL_RETRASO_MIN,
        "lectura": lectura,
    }


def _cargar(nombre: str):
    """Carga perezosa y cacheada del pipeline serializado."""
    if nombre in _MODELOS_EN_MEMORIA:
        return _MODELOS_EN_MEMORIA[nombre]

    archivo = evaluacion.CARPETA_MODELOS / f"{nombre}.joblib"
    if not archivo.exists():
        raise ServicioNoDisponible(
            f"El modelo '{nombre}' no está en disco ({archivo.name}). "
            "Vuelve a entrenarlo con los módulos de ml/supervisado/.")

    import joblib

    _MODELOS_EN_MEMORIA[nombre] = joblib.load(archivo)
    return _MODELOS_EN_MEMORIA[nombre]


# ==========================================================================
# PREDICCIÓN
# ==========================================================================
def predecir_retraso(bd: Database, entrega_id: str, *,
                     guardar: bool = True) -> dict[str, Any]:
    """
    Predice si una entrega va a llegar tarde y cuántos minutos (§15.4).

    Devuelve las dos cosas porque responden preguntas distintas: la
    probabilidad sirve para ordenar por riesgo y decidir a quién llamar; los
    minutos, para reprogramar una ventana concreta.
    """
    entrega = _entrega(bd, entrega_id)

    if entrega.get("hora_real_llegada") is not None:
        raise ReglaDeNegocio(
            f"La entrega {entrega['folio_entrega']} ya tiene llegada "
            f"registrada: su retraso real es {entrega.get('retraso_min')} "
            "minutos. Una entrega cerrada no se predice, se mide.",
            regla="ML1")
    if entrega.get("estatus") not in ESTATUS_PREDECIBLES:
        raise ReglaDeNegocio(
            f"La entrega {entrega['folio_entrega']} está "
            f"{entrega.get('estatus')}. Solo se predice sobre entregas "
            f"{' o '.join(ESTATUS_PREDECIBLES)}.",
            regla="ML1")

    variables, escenario, contexto = _variables_de_entrega(bd, entrega)

    clasificador = _cargar(f"clasificacion_retraso_{escenario.lower()}")
    regresor = _cargar(f"regresion_retraso_{escenario.lower()}")

    import pandas as pd

    fila = pd.DataFrame([variables],
                        columns=evaluacion.columnas_del_escenario(escenario))
    probabilidad = float(clasificador.predict_proba(fila)[0][1])
    minutos = float(regresor.predict(fila)[0])

    umbral = settings.UMBRAL_RETRASO_MIN
    if probabilidad >= 0.70:
        riesgo = "ALTO"
    elif probabilidad >= 0.40:
        riesgo = "MEDIO"
    else:
        riesgo = "BAJO"

    resultado = {
        "entrega_id": str(entrega["_id"]),
        "folio_entrega": entrega.get("folio_entrega"),
        "escenario": escenario,
        "probabilidad_retraso": round(probabilidad, 4),
        "retraso_estimado_min": round(minutos, 1),
        "riesgo": riesgo,
        "umbral_retraso_min": umbral,
        "modelo_clasificacion": f"clasificacion_retraso_{escenario.lower()}",
        "modelo_regresion": f"regresion_retraso_{escenario.lower()}",
        "variables": variables,
        "contexto": contexto,
        "lectura": _lectura_prediccion(entrega, escenario, probabilidad,
                                       minutos, riesgo),
    }

    if guardar:
        _guardar_prediccion(bd, entrega, resultado)
        resultado["guardada"] = True
    else:
        resultado["guardada"] = False
    return resultado


def _lectura_prediccion(entrega: dict[str, Any], escenario: str,
                        probabilidad: float, minutos: float,
                        riesgo: str) -> str:
    umbral = settings.UMBRAL_RETRASO_MIN
    base = (f"Riesgo {riesgo}: {100 * probabilidad:.0f}% de probabilidad de "
            f"superar los {umbral} minutos, con un retraso estimado de "
            f"{minutos:.0f} min.")

    if escenario == ESCENARIO_PLANEACION:
        origen = ("Predicción hecha solo con lo que se sabe al programar el "
                  "viaje, así que todavía hay margen para actuar sobre ella.")
    else:
        origen = ("El viaje ya salió: la predicción incorpora el retraso de "
                  "salida y los incidentes ocurridos, y por eso es más "
                  "confiable, pero deja menos margen de maniobra.")

    if riesgo == "ALTO":
        accion = (f"Conviene avisar al cliente y revisar la ventana de "
                  f"entrega de {entrega.get('folio_entrega')} antes de que el "
                  "retraso se confirme.")
    elif riesgo == "MEDIO":
        accion = ("Vale la pena vigilarla: no es una alerta, pero tampoco una "
                  "entrega tranquila.")
    else:
        accion = "No requiere intervención."
    return f"{base} {origen} {accion}"


def _guardar_prediccion(bd: Database, entrega: dict[str, Any],
                        resultado: dict[str, Any]) -> None:
    """
    Escribe la predicción en la entrega y deja la traza en `predicciones`.

    Los dos campos de la entrega son los que pide el §15.4 punto 2. La
    colección `predicciones` guarda además el vector usado y el modelo, para
    poder comparar después predicción contra realidad: sin esa traza no hay
    forma de saber si el modelo sigue sirviendo.

    Nunca se toca `hora_estimada_llegada`. Es la misma razón por la que
    RN-I5 se lo prohíbe al recálculo de ETA: el retraso se mide contra ella,
    y si una predicción la moviera, la entrega parecería puntual por obra
    del modelo que la advirtió.
    """
    ahora = datetime.now(timezone.utc)
    bd["entregas"].update_one(
        {"_id": entrega["_id"]},
        {"$set": {
            "probabilidad_retraso": resultado["probabilidad_retraso"],
            "retraso_estimado_min": resultado["retraso_estimado_min"],
            "riesgo_retraso": resultado["riesgo"],
            "fecha_prediccion": ahora,
            "fecha_modificacion": ahora,
        }},
    )
    bd["predicciones"].insert_one({
        "entrega_id": entrega["_id"],
        "folio_entrega": entrega.get("folio_entrega"),
        "viaje_id": entrega.get("viaje_id"),
        "escenario": resultado["escenario"],
        "probabilidad_retraso": resultado["probabilidad_retraso"],
        "retraso_estimado_min": resultado["retraso_estimado_min"],
        "riesgo": resultado["riesgo"],
        "modelo_clasificacion": resultado["modelo_clasificacion"],
        "modelo_regresion": resultado["modelo_regresion"],
        "variables": resultado["variables"],
        "umbral_retraso_min": settings.UMBRAL_RETRASO_MIN,
        "origen_dato": "REAL",
        "fecha_prediccion": ahora,
    })


def entregas_en_riesgo(bd: Database, limite: int = 20) -> dict[str, Any]:
    """
    Entregas pendientes ordenadas por riesgo (§15.4, punto 3).

    Solo lista lo ya predicho; no predice en masa. Predecir cientos de
    entregas dentro de una petición HTTP convertiría una consulta en un
    trabajo por lotes, y ese trabajo pertenece a un proceso programado, no
    a un endpoint de lectura.
    """
    filas = list(bd["entregas"].find(
        {"probabilidad_retraso": {"$exists": True},
         "hora_real_llegada": None,
         "activo": True},
        {"folio_entrega": 1, "viaje_id": 1, "orden_parada": 1,
         "nombre_cliente": 1, "estatus": 1, "hora_estimada_llegada": 1,
         "probabilidad_retraso": 1, "retraso_estimado_min": 1,
         "riesgo_retraso": 1, "fecha_prediccion": 1},
    ).sort("probabilidad_retraso", -1).limit(max(limite, 1)))

    for fila in filas:
        fila["id"] = str(fila.pop("_id"))
        if fila.get("viaje_id") is not None:
            fila["viaje_id"] = str(fila["viaje_id"])

    altos = sum(1 for f in filas if f.get("riesgo_retraso") == "ALTO")
    if not filas:
        lectura = ("Ninguna entrega pendiente tiene predicción todavía. "
                   "Llama a POST /ml/predecir-retraso al programarlas.")
    elif altos:
        lectura = (f"{altos} de las {len(filas)} entregas pendientes con "
                   "predicción están en riesgo ALTO. Son las que conviene "
                   "atender primero: el aviso llega antes que el retraso.")
    else:
        lectura = (f"Las {len(filas)} entregas pendientes con predicción "
                   "están en riesgo medio o bajo; ninguna exige intervención "
                   "inmediata.")
    return {"entregas": filas, "total": len(filas), "en_riesgo_alto": altos,
            "lectura": lectura}


# ==========================================================================
# CLUSTERS DE RUTAS
# ==========================================================================
def clusters_rutas(bd: Database) -> dict[str, Any]:
    """
    Los grupos de rutas de PA-9, con su perfil y su recomendación.

    Se acompañan de la silueta global por honestidad: 0.40 en el espacio PCA
    indica una **segmentación operativa útil**, no categorías naturales
    separadas. Las rutas forman un continuo, y el agrupamiento es una forma
    de ordenarlo, no un descubrimiento de tipos. Publicar el número obliga a
    leer los grupos con esa reserva.
    """
    filas = list(bd["clusters_rutas"].find({}, {"_id": 0}).sort("grupo", 1))
    if not filas:
        raise ServicioNoDisponible(
            "No hay agrupamiento cargado en `clusters_rutas`. Ejecuta antes: "
            "python -m ml.no_supervisado.kmeans_rutas.")

    grupos: dict[int, dict[str, Any]] = {}
    for fila in filas:
        grupo = grupos.setdefault(fila["grupo"], {
            "grupo": fila["grupo"],
            "nombre": fila.get("nombre_grupo"),
            "descripcion": fila.get("descripcion_grupo"),
            "recomendacion": fila.get("recomendacion"),
            "rutas": [],
        })
        grupo["rutas"].append(fila.get("codigo_ruta"))
        if isinstance(fila.get("fecha_agrupamiento"), datetime):
            fila["fecha_agrupamiento"] = fila["fecha_agrupamiento"]

    for grupo in grupos.values():
        grupo["total_rutas"] = len(grupo["rutas"])

    silueta = filas[0].get("silueta_global")
    k = filas[0].get("k")
    reparto = ", ".join(f"{g['nombre']}: {g['total_rutas']}"
                        for g in grupos.values())
    lectura = (
        f"{len(filas)} rutas repartidas en {k} grupos ({reparto}). "
        f"La silueta global es {silueta}: eso indica una segmentación "
        "operativa útil, no categorías naturales bien separadas. Las rutas "
        "forman un continuo y el agrupamiento sirve para ordenarlo y "
        "priorizar, no para afirmar que existen tipos de ruta.")

    return {
        "rutas": filas,
        "grupos": sorted(grupos.values(), key=lambda g: g["grupo"]),
        "total_rutas": len(filas),
        "k": k,
        "silueta_global": silueta,
        "algoritmo": filas[0].get("algoritmo"),
        "espacio": filas[0].get("espacio"),
        "lectura": lectura,
    }


# ==========================================================================
# ARMADO DEL VECTOR DE VARIABLES
# ==========================================================================
def _entrega(bd: Database, entrega_id: str) -> dict[str, Any]:
    try:
        objeto = ObjectId(entrega_id)
    except Exception as error:                          # noqa: BLE001
        raise NoEncontrado("la entrega", entrega_id) from error
    entrega = bd["entregas"].find_one({"_id": objeto})
    if entrega is None:
        raise NoEncontrado("la entrega", entrega_id)
    return entrega


def _variables_de_entrega(bd: Database, entrega: dict[str, Any]
                          ) -> tuple[dict[str, Any], str, dict[str, Any]]:
    """
    Reconstruye el vector con el que se entrenó, para esta entrega concreta.

    El escenario lo decide el estado del viaje, no quien llama: mientras el
    viaje no haya salido, `retraso_salida_min` y los incidentes no existen.
    """
    viaje = bd["viajes"].find_one({"_id": entrega.get("viaje_id")})
    if viaje is None:
        raise ReglaDeNegocio(
            f"La entrega {entrega['folio_entrega']} no tiene viaje asociado; "
            "sin él no se puede construir el contexto de la predicción.")

    ruta = bd["rutas"].find_one({"_id": entrega.get("ruta_id")})
    vehiculo = bd["vehiculos"].find_one({"_id": entrega.get("vehiculo_id")})
    operador = bd["operadores"].find_one({"_id": entrega.get("operador_id")})
    cliente = bd["clientes"].find_one({"_id": entrega.get("cliente_id")})
    if not all((ruta, vehiculo, operador, cliente)):
        faltan = [nombre for nombre, doc in (
            ("ruta", ruta), ("vehículo", vehiculo),
            ("operador", operador), ("cliente", cliente)) if doc is None]
        raise ReglaDeNegocio(
            f"Faltan datos de contexto para predecir: {', '.join(faltan)}.")

    # Las variables de la ruta se leen de la propia colección `rutas`, que es
    # de donde las tomó el ETL (`enriquecimiento.dataset_rutas` las extrae de
    # ahí sin recalcularlas). Así el vector coincide con el del
    # entrenamiento y una ruta recién creada puede predecirse sin esperar a
    # la siguiente corrida del data warehouse.

    estimada = entrega.get("hora_estimada_llegada")
    if estimada is None:
        raise ReglaDeNegocio(
            f"La entrega {entrega['folio_entrega']} no tiene hora estimada de "
            "llegada; sin ella no existen ni la franja horaria ni el "
            "concepto de retraso.")
    if estimada.tzinfo is None:
        estimada = estimada.replace(tzinfo=timezone.utc)

    fecha = entrega.get("fecha") or viaje.get("fecha") or estimada
    if fecha.tzinfo is None:
        fecha = fecha.replace(tzinfo=timezone.utc)

    variables: dict[str, Any] = {
        "orden_parada": entrega.get("orden_parada"),
        "tiempo_estimado_min": entrega.get("tiempo_estimado_min"),
        "distancia_km": entrega.get("distancia_km"),
        "dia_semana": estimada.weekday(),
        "es_fin_semana": int(estimada.weekday() >= 5),
        "mes": estimada.month,
        "numero_paradas_ruta": (ruta.get("numero_paradas")
                                or len(ruta.get("paradas", [])) or None),
        "distancia_total_ruta_km": ruta.get("distancia_total_km"),
        "velocidad_efectiva_kmh": ruta.get("velocidad_efectiva_kmh"),
        "antiguedad_vehiculo_anios": max(
            fecha.year - int(vehiculo.get("anio", fecha.year)), 0),
        "rendimiento_nominal_km_l": vehiculo.get("rendimiento_nominal_km_l"),
        "experiencia_operador_meses": _experiencia_meses(operador, fecha),
        "franja_horaria": franja_de(estimada.hour),
        "zona": ruta.get("zona"),
        "tipo_vehiculo": vehiculo.get("tipo_vehiculo"),
        "tipo_cliente": cliente.get("tipo_cliente"),
    }

    salio = viaje.get("estatus") in ESTATUS_VIAJE_INICIADO
    escenario = ESCENARIO_EN_RUTA if salio else ESCENARIO_PLANEACION
    if salio:
        variables["retraso_salida_min"] = viaje.get("retraso_salida_min") or 0.0
        variables["n_incidentes_acumulados"] = len(
            entrega.get("incidentes_ids") or [])
        variables["incidentes_viaje"] = viaje.get("total_incidentes") or 0

    faltantes = [k for k, v in variables.items() if v is None]
    if faltantes:
        raise ReglaDeNegocio(
            f"No se puede predecir: faltan las variables "
            f"{', '.join(faltantes)}. El modelo fue entrenado con todas "
            "ellas, y sustituirlas por un valor inventado daría una cifra "
            "que parecería una predicción sin serlo.")

    contexto = {
        "viaje": viaje.get("folio_viaje"),
        "estatus_viaje": viaje.get("estatus"),
        "ruta": ruta.get("codigo_ruta"),
        "vehiculo": vehiculo.get("codigo_vehiculo"),
        "operador": operador.get("codigo_operador"),
        "cliente": cliente.get("nombre_empresa") or cliente.get("nombre"),
        "hora_estimada_llegada": estimada,
        "motivo_escenario": (
            "El viaje ya salió: se conocen el retraso de salida y los "
            "incidentes." if salio else
            "El viaje aún no sale: solo se usa lo conocido al programarlo."),
    }
    return variables, escenario, contexto


def _experiencia_meses(operador: dict[str, Any], fecha: datetime) -> float:
    """Misma fórmula que el ETL: días desde el ingreso entre 30.44."""
    ingreso = operador.get("fecha_ingreso")
    if ingreso is None:
        return 0.0
    if ingreso.tzinfo is None:
        ingreso = ingreso.replace(tzinfo=timezone.utc)
    return round(max((fecha - ingreso).days, 0) / 30.44, 1)
