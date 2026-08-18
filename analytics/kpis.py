"""
SIG-LOG — Sistema Integral de Gestión Logística
analytics/kpis.py

ACTIVIDAD PA-10 (parte 1) — INDICADORES DEL DASHBOARD EJECUTIVO
PANEL A del §18.2 del documento técnico base

Calcula los diez indicadores que resumen la operación en una pantalla, con
**agregaciones de MongoDB** (`$group`, `$match`, `$percentile`), no
trayendo las colecciones completas a pandas. Es una decisión deliberada:
el motor de base de datos hace el trabajo pesado y el resultado son unas
pocas cifras, que es como debe consultarlas un dashboard web.

Regla de la capa 8 (§7.3): la visualización **comunica e interpreta, no
recalcula métricas por su cuenta**. Por eso todos los números del
dashboard salen de aquí y de ningún otro lado.

Interpretación automática (RF-29, §18.3)
----------------------------------------
Cada indicador viaja con su lectura en lenguaje natural y un semáforo. Un
número sin contexto no ayuda a decidir: "72.4% a tiempo" no dice si eso
es bueno. El texto lo sitúa frente a la meta y frente al resto de la
operación, que es lo que convierte el dato en conocimiento.

Uso
---
    python -m analytics.kpis
    python -m analytics.kpis --json     # salida para el API/frontend
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from config import settings
from config.mongo_conexion import cerrar_cliente, obtener_bd, verificar_conexion

ARCHIVO_REPORTE = RAIZ / "data" / "outputs" / "reporte_kpis.txt"
ARCHIVO_JSON = RAIZ / "data" / "outputs" / "kpis.json"

# Metas de la operación. No son datos observados: son el criterio contra el
# que se juzga cada indicador, y por eso viven declaradas y no escondidas
# dentro de un `if`.
META_PUNTUALIDAD_PCT: float = 85.0
META_RETRASO_MEDIO_MIN: float = 10.0
LIMITE_VEHICULOS_MANTENIMIENTO: int = 4


# ==========================================================================
# AGREGACIONES
# ==========================================================================
def _una(bd, coleccion: str, pipeline: list[dict]) -> dict[str, Any]:
    """Ejecuta un pipeline que devuelve un solo documento."""
    resultado = list(bd[coleccion].aggregate(pipeline))
    return resultado[0] if resultado else {}


def kpis_de_entregas(bd) -> dict[str, Any]:
    """Indicadores derivados de la tabla de hechos."""
    base = _una(bd, "hecho_entrega", [
        {"$match": {"calidad_dato": "OK"}},
        {"$group": {
            "_id": None,
            "entregas": {"$sum": 1},
            "retrasadas": {"$sum": "$es_retraso"},
            "retraso_medio": {"$avg": "$retraso_min"},
            "completadas": {"$sum": "$entrega_completada"},
            "minutos_perdidos": {"$sum": "$minutos_perdidos_incidentes"},
            "costo_asignado": {"$sum": "$costo_combustible_asignado"},
        }},
    ])
    if not base:
        return {}

    # La mediana no tiene operador de acumulación clásico en MongoDB: se
    # obtiene con $percentile sobre el conjunto ya filtrado.
    mediana = _una(bd, "hecho_entrega", [
        {"$match": {"calidad_dato": "OK"}},
        {"$group": {"_id": None,
                    "p50": {"$percentile": {"input": "$retraso_min",
                                            "p": [0.5],
                                            "method": "approximate"}}}},
    ])
    base["retraso_mediano"] = (mediana.get("p50") or [0.0])[0]

    # Cobertura temporal: el dashboard debe decir de qué periodo habla.
    periodo = _una(bd, "hecho_entrega", [
        {"$group": {"_id": None,
                    "desde": {"$min": "$fecha_id"},
                    "hasta": {"$max": "$fecha_id"},
                    "dias": {"$addToSet": "$fecha_id"},
                    "todas": {"$sum": 1}}},
    ])
    base["periodo_desde"] = periodo.get("desde")
    base["periodo_hasta"] = periodo.get("hasta")
    base["dias_operados"] = len(periodo.get("dias", []))
    base["entregas_totales"] = periodo.get("todas", 0)
    return base


def kpis_de_flotilla(bd) -> dict[str, Any]:
    """Kilómetros, combustible, rendimiento y estado de la flotilla."""
    viajes = _una(bd, "viajes", [
        {"$match": {"estatus": "FINALIZADO"}},
        {"$group": {"_id": None, "km": {"$sum": "$km_recorridos"},
                    "viajes": {"$sum": 1}}},
    ])
    combustible = _una(bd, "combustible", [
        {"$group": {"_id": None, "costo": {"$sum": "$costo_total"},
                    "litros": {"$sum": "$litros"}, "cargas": {"$sum": 1}}},
    ])
    rendimiento = _una(bd, "dim_vehiculo", [
        {"$group": {"_id": None,
                    "rendimiento": {"$avg": "$rendimiento_real_km_l"},
                    "nominal": {"$avg": "$rendimiento_nominal_km_l"}}},
    ])
    en_mantenimiento = bd["dim_vehiculo"].count_documents(
        {"estado_operativo": "EN_MANTENIMIENTO"})

    km = viajes.get("km", 0.0)
    costo = combustible.get("costo", 0.0)
    return {
        "km_totales": km,
        "viajes_finalizados": viajes.get("viajes", 0),
        "costo_combustible": costo,
        "litros": combustible.get("litros", 0.0),
        "costo_por_km": costo / km if km else 0.0,
        "rendimiento_flotilla": rendimiento.get("rendimiento", 0.0),
        "rendimiento_nominal": rendimiento.get("nominal", 0.0),
        "vehiculos_mantenimiento": en_mantenimiento,
        "vehiculos_totales": bd["dim_vehiculo"].count_documents({}),
        "incidentes": bd["incidentes"].count_documents({}),
    }


# ==========================================================================
# CONSTRUCCIÓN DE LOS INDICADORES  (§18.2, Panel A)
# ==========================================================================
def _semaforo(valor: float, meta: float, mayor_es_mejor: bool,
              margen: float = 0.10) -> str:
    """VERDE cumple la meta · AMARILLO cerca · ROJO lejos."""
    if mayor_es_mejor:
        if valor >= meta:
            return "VERDE"
        return "AMARILLO" if valor >= meta * (1 - margen) else "ROJO"
    if valor <= meta:
        return "VERDE"
    return "AMARILLO" if valor <= meta * (1 + margen) else "ROJO"


def calcular(bd=None) -> list[dict[str, Any]]:
    """
    Devuelve los diez KPIs del Panel A, cada uno con valor, unidad,
    semáforo y lectura en lenguaje natural (RF-29).
    """
    base = bd if bd is not None else obtener_bd()
    entregas = kpis_de_entregas(base)
    if not entregas:
        raise RuntimeError(
            "`hecho_entrega` está vacía. Ejecuta antes: python -m etl.run_etl")
    flotilla = kpis_de_flotilla(base)

    n = entregas["entregas"]
    puntualidad = 100 * (1 - entregas["retrasadas"] / n)
    entregas_por_dia = n / max(entregas["dias_operados"], 1)
    km_por_viaje = flotilla["km_totales"] / max(flotilla["viajes_finalizados"], 1)
    pct_mantenimiento = (100 * flotilla["vehiculos_mantenimiento"]
                         / max(flotilla["vehiculos_totales"], 1))
    desviacion = (100 * (flotilla["rendimiento_flotilla"]
                         - flotilla["rendimiento_nominal"])
                  / flotilla["rendimiento_nominal"]
                  if flotilla["rendimiento_nominal"] else 0.0)
    posicion_mediana = ("menor" if entregas["retraso_mediano"] < entregas["retraso_medio"]
                        else "mayor")
    lado_meta = "por encima" if puntualidad >= META_PUNTUALIDAD_PCT else "por debajo"
    lado_nominal = "por debajo" if desviacion < 0 else "por encima"

    return [
        {
            "clave": "entregas_totales",
            "titulo": "Entregas del periodo",
            "valor": int(entregas["entregas_totales"]), "unidad": "entregas",
            "semaforo": "NEUTRO",
            "lectura": (
                f"{entregas['entregas_totales']:,} entregas registradas en "
                f"{entregas['dias_operados']} días de operación "
                f"({entregas_por_dia:.0f} al día). De ellas, {n:,} tienen "
                "datos completos y sostienen todos los indicadores "
                "siguientes."),
        },
        {
            "clave": "puntualidad",
            "titulo": "Entregas a tiempo",
            "valor": round(puntualidad, 1), "unidad": "%",
            "semaforo": _semaforo(puntualidad, META_PUNTUALIDAD_PCT, True),
            "lectura": (
                f"{puntualidad:.1f}% de las entregas llegaron dentro del "
                f"umbral de {settings.UMBRAL_RETRASO_MIN} minutos, "
                f"{lado_meta} de la meta del {META_PUNTUALIDAD_PCT:.0f}%. Son "
                f"{entregas['retrasadas']:,} entregas retrasadas "
                f"({100 - puntualidad:.1f}%) sobre las que actuar."),
        },
        {
            "clave": "retraso_medio",
            "titulo": "Retraso promedio",
            "valor": round(entregas["retraso_medio"], 1), "unidad": "min",
            "semaforo": _semaforo(entregas["retraso_medio"],
                                  META_RETRASO_MEDIO_MIN, False),
            "lectura": (
                f"El retraso promedio es de {entregas['retraso_medio']:.1f} "
                f"minutos, contra una meta de "
                f"{META_RETRASO_MEDIO_MIN:.0f}. El promedio se ve arrastrado "
                "por los casos extremos; la mediana describe mejor a la "
                "entrega típica."),
        },
        {
            "clave": "retraso_mediano",
            "titulo": "Retraso mediano",
            "valor": round(entregas["retraso_mediano"], 1), "unidad": "min",
            "semaforo": _semaforo(entregas["retraso_mediano"],
                                  META_RETRASO_MEDIO_MIN, False),
            "lectura": (
                f"La mitad de las entregas se retrasa menos de "
                f"{entregas['retraso_mediano']:.1f} minutos. Al ser "
                f"{posicion_mediana} que el promedio, confirma que unas pocas "
                "entregas muy retrasadas distorsionan la media."),
        },
        {
            "clave": "km_totales",
            "titulo": "Kilómetros recorridos",
            "valor": round(flotilla["km_totales"], 1), "unidad": "km",
            "semaforo": "NEUTRO",
            "lectura": (
                f"La flotilla recorrió {flotilla['km_totales']:,.0f} km en "
                f"{flotilla['viajes_finalizados']:,} viajes finalizados, un "
                f"promedio de {km_por_viaje:.0f} km por viaje."),
        },
        {
            "clave": "costo_combustible",
            "titulo": "Costo de combustible",
            "valor": round(flotilla["costo_combustible"], 2), "unidad": "MXN",
            "semaforo": "NEUTRO",
            "lectura": (
                f"${flotilla['costo_combustible']:,.0f} en "
                f"{flotilla['litros']:,.0f} litros. Es el costo variable "
                "principal de la operación y el que más rápido responde a "
                "cambios en el diseño de las rutas."),
        },
        {
            "clave": "costo_por_km",
            "titulo": "Costo por kilómetro",
            "valor": round(flotilla["costo_por_km"], 2), "unidad": "MXN/km",
            "semaforo": "NEUTRO",
            "lectura": (
                f"Cada kilómetro cuesta ${flotilla['costo_por_km']:.2f} en "
                "combustible. Es el indicador que permite comparar vehículos "
                "de distinto tamaño y antigüedad en igualdad de condiciones."),
        },
        {
            "clave": "rendimiento_flotilla",
            "titulo": "Rendimiento de la flotilla",
            "valor": round(flotilla["rendimiento_flotilla"], 2), "unidad": "km/l",
            "semaforo": _semaforo(flotilla["rendimiento_flotilla"],
                                  flotilla["rendimiento_nominal"], True),
            "lectura": (
                f"El rendimiento real promedio es de "
                f"{flotilla['rendimiento_flotilla']:.2f} km/l, "
                f"{abs(desviacion):.1f}% {lado_nominal} del nominal de fábrica "
                f"({flotilla['rendimiento_nominal']:.2f} km/l). Una brecha "
                "creciente suele anticipar necesidad de mantenimiento."),
        },
        {
            "clave": "vehiculos_mantenimiento",
            "titulo": "Vehículos en mantenimiento",
            "valor": int(flotilla["vehiculos_mantenimiento"]),
            "unidad": "vehículos",
            "semaforo": _semaforo(flotilla["vehiculos_mantenimiento"],
                                  LIMITE_VEHICULOS_MANTENIMIENTO, False),
            "lectura": (
                f"{flotilla['vehiculos_mantenimiento']} de "
                f"{flotilla['vehiculos_totales']} vehículos "
                f"({pct_mantenimiento:.0f}%) están fuera de operación por "
                "mantenimiento vencido, y su carga debe redistribuirse entre "
                "el resto."),
        },
        {
            "clave": "incidentes",
            "titulo": "Incidentes del periodo",
            "valor": int(flotilla["incidentes"]), "unidad": "incidentes",
            "semaforo": "NEUTRO",
            "lectura": (
                f"{flotilla['incidentes']:,} incidentes registrados, que "
                f"acumulan {entregas['minutos_perdidos']:,.0f} minutos "
                f"perdidos ({entregas['minutos_perdidos'] / 60:,.0f} horas) "
                "en las entregas afectadas."),
        },
    ]


def resumen_ejecutivo(indicadores: list[dict[str, Any]]) -> str:
    """
    Párrafo que sintetiza el tablero: qué está bien, qué no y qué atender.
    Es el texto que encabezará el reporte en PDF.
    """
    por_clave = {k["clave"]: k for k in indicadores}
    alertas = [k for k in indicadores if k["semaforo"] == "ROJO"]
    punt = por_clave["puntualidad"]
    lado = "por encima" if punt["valor"] >= META_PUNTUALIDAD_PCT else "por debajo"

    partes = [
        f"En el periodo analizado se registraron "
        f"{por_clave['entregas_totales']['valor']:,} entregas con una "
        f"puntualidad del {punt['valor']}%, {lado} de la meta del "
        f"{META_PUNTUALIDAD_PCT:.0f}%."
    ]
    if alertas:
        nombres = ", ".join(a["titulo"].lower() for a in alertas)
        verbo, sustantivo = (("Requiere", "indicador") if len(alertas) == 1
                             else ("Requieren", "indicadores"))
        partes.append(f"{verbo} atención {len(alertas)} {sustantivo} en rojo: "
                      f"{nombres}.")
    else:
        partes.append("Ningún indicador está en rojo.")
    partes.append(
        f"El costo de combustible asciende a "
        f"${por_clave['costo_combustible']['valor']:,.0f} "
        f"(${por_clave['costo_por_km']['valor']:.2f} por km) y "
        f"{por_clave['vehiculos_mantenimiento']['valor']} vehículos están "
        "fuera de operación.")
    return " ".join(partes)


# ==========================================================================
# PRESENTACIÓN
# ==========================================================================
SIMBOLO = {"VERDE": "[ OK ]", "AMARILLO": "[ !! ]", "ROJO": "[ XX ]",
           "NEUTRO": "[ -- ]"}


def _envolver(texto: str, ancho: int) -> list[str]:
    return textwrap.wrap(texto, ancho)


def imprimir(indicadores: list[dict[str, Any]]) -> None:
    print("=" * 78)
    print("  SIG-LOG · TABLERO EJECUTIVO (Panel A)  —  datos SIMULADOS")
    print("=" * 78)
    print(f"  {'INDICADOR':<30}{'VALOR':>16}  {'ESTADO':<10}UNIDAD")
    print("-" * 78)
    for kpi in indicadores:
        valor = (f"{kpi['valor']:,.2f}" if isinstance(kpi["valor"], float)
                 else f"{kpi['valor']:,}")
        print(f"  {kpi['titulo']:<30}{valor:>16}  "
              f"{SIMBOLO[kpi['semaforo']]:<10}{kpi['unidad']}")

    print()
    print("=" * 78)
    print("  INTERPRETACIÓN AUTOMÁTICA (RF-29)")
    print("=" * 78)
    for kpi in indicadores:
        print(f"\n  {kpi['titulo'].upper()}  {SIMBOLO[kpi['semaforo']]}")
        for linea in _envolver(kpi["lectura"], 70):
            print(f"      {linea}")

    print()
    print("=" * 78)
    print("  RESUMEN EJECUTIVO")
    print("=" * 78)
    for linea in _envolver(resumen_ejecutivo(indicadores), 74):
        print(f"  {linea}")


def verificar(indicadores: list[dict[str, Any]]) -> list[tuple[str, bool, str]]:
    por_clave = {k["clave"]: k for k in indicadores}
    return [
        ("Los 10 KPIs del Panel A calculados", len(indicadores) == 10,
         f"{len(indicadores)} indicadores"),
        ("Ningún indicador sin valor",
         all(k["valor"] is not None for k in indicadores), "todos con valor"),
        ("Puntualidad en el rango 0-100%",
         0 <= por_clave["puntualidad"]["valor"] <= 100,
         f"{por_clave['puntualidad']['valor']}%"),
        ("Mediana menor que la media (distribución sesgada)",
         por_clave["retraso_mediano"]["valor"] < por_clave["retraso_medio"]["valor"],
         f"{por_clave['retraso_mediano']['valor']} < "
         f"{por_clave['retraso_medio']['valor']} min"),
        ("Costo por km positivo y consistente",
         por_clave["costo_por_km"]["valor"] > 0,
         f"${por_clave['costo_por_km']['valor']}/km"),
        ("Cada KPI trae su interpretación (RF-29)",
         all(len(k["lectura"]) > 40 for k in indicadores),
         f"{len(indicadores)} lecturas generadas"),
    ]


def imprimir_verificaciones(resultados: list[tuple[str, bool, str]]) -> bool:
    print()
    print("=" * 78)
    print("  VERIFICACIONES AUTOMÁTICAS")
    print("=" * 78)
    for nombre, ok, detalle in resultados:
        print(f"  {'[OK]   ' if ok else '[FALLA]'} {nombre:<48}{detalle}")
    fallos = sum(1 for _, ok, _ in resultados if not ok)
    print("-" * 78)
    print(f"  {len(resultados) - fallos}/{len(resultados)} verificaciones correctas")
    return fallos == 0


# ==========================================================================
# PUNTO DE ENTRADA
# ==========================================================================
def main() -> int:
    parser = argparse.ArgumentParser(
        description="PA-10 — KPIs del dashboard ejecutivo (Panel A, §18.2).")
    parser.add_argument("--json", action="store_true",
                        help="Imprime los KPIs en JSON (formato para el API).")
    parser.add_argument("--sin-archivos", action="store_true",
                        help="No escribe el reporte ni el JSON.")
    args = parser.parse_args()

    if not verificar_conexion(verbose=not args.json)["exito"]:
        return 1

    codigo = 0
    try:
        bd = obtener_bd()
        indicadores = calcular(bd)

        if args.json:
            print(json.dumps(indicadores, ensure_ascii=False, indent=2))
            return 0

        memoria = io.StringIO()
        with contextlib.redirect_stdout(memoria):
            imprimir(indicadores)
            if not imprimir_verificaciones(verificar(indicadores)):
                codigo = 1
        reporte = memoria.getvalue()
        print(reporte)

        if not args.sin_archivos:
            ARCHIVO_REPORTE.parent.mkdir(parents=True, exist_ok=True)
            ARCHIVO_REPORTE.write_text(reporte, encoding="utf-8")
            ARCHIVO_JSON.write_text(
                json.dumps({"generado": datetime.now(timezone.utc).isoformat(),
                            "origen_dato": "SIMULADO",
                            "indicadores": indicadores},
                           ensure_ascii=False, indent=2),
                encoding="utf-8")
            print(f"  Reporte: {ARCHIVO_REPORTE.relative_to(RAIZ)}")
            print(f"  JSON:    {ARCHIVO_JSON.relative_to(RAIZ)}")
    finally:
        cerrar_cliente()
    return codigo


if __name__ == "__main__":
    sys.exit(main())
