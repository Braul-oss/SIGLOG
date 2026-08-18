"""
SIG-LOG — Sistema Integral de Gestión Logística
reportes/operativo.py

INFORME OPERATIVO — QUÉ HAY QUE ATENDER HOY

A diferencia de los otros dos, este no describe el periodo: describe el
**momento**. Es la lista de lo que exige una decisión ahora mismo, ordenada
por urgencia:

    1. Unidades paradas por mantenimiento vencido
    2. Servicios atrasados que aún no han parado la unidad
    3. Operadores que no pueden conducir
    4. Incidentes abiertos
    5. Entregas con riesgo de llegar tarde

Por eso lleva la hora en la cabecera y no solo la fecha: a las tres de la
tarde la lista ya no es la misma que a las nueve.

Todo sale de los servicios que ya atienden esas mismas alertas en la
pantalla. El informe no consulta la base por su cuenta.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from pymongo.database import Database

from backend.services import incidentes as servicio_incidentes
from backend.services import mantenimientos as servicio_mtto
from backend.services import ml as servicio_ml
from backend.services import operadores as servicio_operadores
from backend.utils.errores import ErrorSIGLOG
from config import settings
from reportes import comun

TITULO = "Informe operativo"
SUBTITULO = ("Lo que exige una decisión ahora mismo, ordenado por urgencia. "
             "Refleja el estado del sistema en el momento de generarlo.")


def construir(bd: Database) -> bytes:
    elementos: list = comun.portada(TITULO, SUBTITULO)

    momento = datetime.now(timezone.utc).astimezone()
    elementos.append(comun.aviso(
        f"<b>Generado el {momento:%d/%m/%Y} a las {momento:%H:%M}.</b> "
        "Este informe es una foto del momento, no un resumen del periodo: "
        "una unidad que hoy está parada puede volver a operación mañana, y "
        "una entrega en riesgo puede llegar a tiempo. Consúltalo el mismo "
        "día en que se genera."))
    elementos.append(comun.espacio(0.4))

    bloques = [
        _mantenimiento(bd),
        _licencias(bd),
        _incidentes(bd),
        _riesgo(bd),
    ]
    for bloque in bloques:
        elementos += bloque

    return comun.documento(TITULO, SUBTITULO, elementos)


# ==========================================================================
# BLOQUES
# ==========================================================================
def _mantenimiento(bd: Database) -> list:
    try:
        datos = servicio_mtto.pendientes(bd)
    except ErrorSIGLOG as error:
        return _no_disponible("1. Mantenimiento", error)

    partes = comun.seccion(
        "1. Unidades que requieren mantenimiento",
        "Un servicio vencido saca la unidad de operación: deja de poder "
        "programarse en una jornada hasta que se atienda. Los atrasados "
        "todavía no la han parado, pero lo harán.")

    resumen = [
        ["Unidades paradas por servicio vencido",
         comun.entero(datos["total_vencidos"]),
         "No pueden salir a ruta. Atenderlas las devuelve a operación."],
        ["Servicios atrasados sin declarar vencidos",
         comun.entero(datos["total_atrasados"]),
         "La fecha ya pasó. Es donde conviene actuar antes de que paren la "
         "unidad."],
        [f"Servicios próximos ({datos['dias_anticipacion']} días)",
         comun.entero(datos["total_proximos"]),
         "Todavía se pueden planificar sin parar nada."],
    ]
    partes.append(comun.tabla(
        ["Situación", "Unidades", "Qué implica"], resumen,
        anchos=[comun.ANCHO_UTIL * p for p in (.34, .12, .54)],
        alinear_derecha=(1,),
        destacar=lambda i: i == 0 and datos["total_vencidos"] > 0))
    partes.append(comun.lectura(datos["alerta"]))

    filas = []
    etiquetas = {"vencidos": "Vencido", "atrasados": "Atrasado",
                 "proximos": "Próximo"}
    for grupo, etiqueta in etiquetas.items():
        for m in datos[grupo]:
            filas.append([
                f"<b>{m['codigo_vehiculo']}</b> "
                f"<font size=6 color='#667589'>{m.get('placa') or ''}</font>",
                etiqueta, m["folio_mantenimiento"], m["tipo"] or "—",
                comun.fecha(m["fecha_programada"]),
                comun.entero(m["dias"]),
                (m["estado_operativo"] or "—").replace("_", " ").title(),
            ])

    if filas:
        partes.append(comun.espacio(0.2))
        partes.append(comun.tabla(
            ["Vehículo", "Situación", "Folio", "Tipo",
             "Fecha programada", "Días", "Estado de la unidad"],
            filas,
            anchos=[comun.ANCHO_UTIL * p for p in
                    (.15, .11, .19, .12, .15, .08, .20)],
            alinear_derecha=(5,),
            destacar=lambda i: i < datos["total_vencidos"]))
    return partes


def _licencias(bd: Database) -> list:
    try:
        datos = servicio_operadores.licencias(bd)
    except ErrorSIGLOG as error:
        return _no_disponible("2. Licencias", error)

    partes = comun.seccion(
        "2. Operadores que no pueden conducir",
        "Una licencia vencida impide salir a ruta, y el sistema lo "
        "comprueba al programar el viaje. Conviene resolverlo antes de "
        "armar la jornada, no cuando el viaje se rechaza.")

    vencidas = datos.get("vencidas") or []
    por_vencer = datos.get("por_vencer") or []

    if not vencidas and not por_vencer:
        partes.append(comun.lectura(datos.get("alerta", "Sin incidencias.")))
        return partes

    filas = []
    for o in vencidas:
        filas.append([f"<b>{o['codigo_operador']}</b>", o["nombre_completo"],
                      "Vencida", comun.fecha(o.get("vigencia")),
                      comun.entero(o.get("dias"))])
    for o in por_vencer:
        filas.append([f"<b>{o['codigo_operador']}</b>", o["nombre_completo"],
                      "Por vencer", comun.fecha(o.get("vigencia")),
                      comun.entero(o.get("dias"))])

    partes.append(comun.tabla(
        ["Código", "Operador", "Licencia", "Vigencia hasta", "Días"],
        filas,
        anchos=[comun.ANCHO_UTIL * p for p in (.13, .40, .15, .18, .14)],
        alinear_derecha=(4,),
        destacar=lambda i: i < len(vencidas)))
    partes.append(comun.lectura(datos.get("alerta", "")))
    return partes


def _incidentes(bd: Database) -> list:
    try:
        datos = servicio_incidentes.resumen(bd)
    except ErrorSIGLOG as error:
        return _no_disponible("3. Incidentes", error)

    partes = comun.seccion(
        "3. Incidentes abiertos",
        "Un incidente sin cerrar es un problema del que aún no se conoce la "
        "duración real. Cerrarlo es lo que permite medir cuánto costó.")

    abiertos, _ = servicio_incidentes.listar(bd, limite=25, solo_abiertos=True)
    if not abiertos:
        partes.append(comun.lectura(
            "No hay incidentes abiertos: todos los registrados tienen su "
            "hora de cierre y su duración medida."))
        return partes

    partes.append(comun.tabla(
        ["Folio", "Tipo", "Severidad", "Inicio",
         "Minutos perdidos<br/>estimados", "Entregas afectadas"],
        [[i["folio_incidente"], (i["tipo"] or "—").replace("_", " ").title(),
          i["severidad"] or "—", comun.fecha(i["fecha_hora_inicio"]),
          comun.numero(i["tiempo_perdido_estimado_min"], 0),
          comun.entero(len(i.get("entregas_afectadas") or []))]
         for i in abiertos],
        anchos=[comun.ANCHO_UTIL * p for p in (.22, .16, .13, .15, .18, .16)],
        alinear_derecha=(4, 5),
        destacar=lambda i: abiertos[i]["severidad"] == "ALTA"))
    partes.append(comun.lectura(datos.get("alerta", "")))
    return partes


def _riesgo(bd: Database) -> list:
    try:
        datos = servicio_ml.entregas_en_riesgo(bd, 25)
    except ErrorSIGLOG as error:
        return _no_disponible("4. Entregas en riesgo", error)

    umbral = settings.UMBRAL_RETRASO_MIN
    partes = comun.seccion(
        "4. Entregas con riesgo de llegar tarde",
        "Predicción de los modelos entrenados con el histórico, sobre las "
        "entregas que aún no han llegado. La probabilidad indica cuánto se "
        f"parece esta entrega a las que superaron los {umbral} minutos de "
        "retraso; los minutos estimados sirven para reprogramar una ventana "
        "concreta.")

    entregas = datos["entregas"]
    if not entregas:
        partes.append(comun.lectura(datos["lectura"]))
        return partes

    partes.append(comun.tabla(
        ["Entrega", "Cliente", "Estatus", "Hora estimada",
         "Probabilidad<br/>de retraso", "Retraso estimado<br/>(minutos)",
         "Riesgo"],
        [[e["folio_entrega"], e.get("nombre_cliente") or "—",
          (e.get("estatus") or "—").replace("_", " ").title(),
          _hora(e.get("hora_estimada_llegada")),
          comun.porcentaje(e["probabilidad_retraso"] * 100),
          comun.numero(e["retraso_estimado_min"], 1),
          e.get("riesgo_retraso") or "—"]
         for e in entregas],
        anchos=[comun.ANCHO_UTIL * p for p in
                (.20, .22, .12, .12, .12, .12, .10)],
        alinear_derecha=(4, 5),
        destacar=lambda i: entregas[i].get("riesgo_retraso") == "ALTO"))
    partes.append(comun.lectura(datos["lectura"]))
    return partes


# ==========================================================================
# INTERNO
# ==========================================================================
def _no_disponible(titulo: str, error: ErrorSIGLOG) -> list:
    """
    Un bloque que no se puede construir se dice, no se omite.

    Omitirlo dejaría un informe que parece completo y no lo está, y quien
    lo lea concluiría que no hay nada que atender.
    """
    return comun.seccion(titulo) + [
        comun.aviso(f"<b>No disponible.</b> {error.mensaje}")]


def _hora(valor: Any) -> str:
    if not valor:
        return "—"
    if isinstance(valor, str):
        try:
            valor = datetime.fromisoformat(valor.replace("Z", "+00:00"))
        except ValueError:
            return valor
    return valor.strftime("%d/%m %H:%M")
