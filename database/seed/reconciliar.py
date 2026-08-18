"""
SIG-LOG — Sistema Integral de Gestión Logística
database/seed/reconciliar.py

ACTIVIDAD PA-3 — Reconciliación de contadores y reporte de calidad

PA-1 y PA-2 dejaron los catálogos con sus contadores en cero y sin el estado
final de la flotilla. Esta actividad cierra el ciclo operativo:

  1. clientes.total_entregas          ← conteo real de entregas
  2. operadores.total_entregas        ← conteo real de entregas
  3. vehiculos.odometro_actual_km     ← odómetro del último viaje
  4. vehiculos.fecha_ultimo_mantenimiento / fecha_proximo_mantenimiento
  5. vehiculos.estado_operativo       ← DISPONIBLE o EN_MANTENIMIENTO

Y produce el REPORTE DE CALIDAD del dataset, que es el punto de partida
documentado de la Unidad II: dice exactamente qué hay que limpiar en PA-5.

Todo el trabajo se hace con **pipelines de agregación de MongoDB**
(`$group`, `$match`, `$sort`), siguiendo el patrón del ejercicio de clase
`processing_consulta_ventas.py`. Es evidencia directa del tema
"agregaciones" del diseño de base de datos.

Campos que esta actividad NO calcula
------------------------------------
`vehiculos.rendimiento_real_km_l` y `operadores.porcentaje_entregas_a_tiempo`
están marcados en §11.2 y §11.3 como "calculado en el ETL". Se dejan en null
a propósito: los deriva PA-6, y ahí es donde constituyen evidencia de
enriquecimiento de datos (Unidad II).

Uso
---
    python -m database.seed.reconciliar --dry-run   # muestra sin escribir
    python -m database.seed.reconciliar             # aplica y reporta
    python -m database.seed.reconciliar --solo-reporte
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from pymongo import UpdateOne

from config import settings
from config.mongo_conexion import cerrar_cliente, obtener_bd, verificar_conexion
from database.seed import comun as C
from database.seed import parametros as P


# ==========================================================================
# 1 · CONTADORES DE ENTREGAS  (clientes y operadores)
# ==========================================================================
def _conteo_entregas_por(bd, campo: str) -> dict:
    """
    Agregación: número de entregas efectivamente realizadas por entidad.

    Se cuentan las entregas con estatus ENTREGADA. Nota deliberada: las
    entregas duplicadas por doble captura SÍ se cuentan aquí, porque un
    sistema operativo no puede distinguirlas todavía. El reporte de calidad
    las expone para que PA-5 las depure.
    """
    pipeline = [
        {"$match": {"estatus": "ENTREGADA"}},
        {"$group": {"_id": f"${campo}", "total": {"$sum": 1}}},
    ]
    return {d["_id"]: d["total"] for d in bd["entregas"].aggregate(pipeline)}


def reconciliar_contadores(bd, coleccion: str, campo_entrega: str,
                           aplicar: bool) -> dict[str, Any]:
    conteos = _conteo_entregas_por(bd, campo_entrega)
    operaciones = [
        UpdateOne({"_id": _id},
                  {"$set": {"total_entregas": total,
                            "fecha_modificacion": C.ahora_utc()}})
        for _id, total in conteos.items()
    ]
    if aplicar and operaciones:
        bd[coleccion].bulk_write(operaciones, ordered=False)

    valores = sorted(conteos.values())
    total_docs = bd[coleccion].count_documents({})
    return {
        "coleccion": coleccion,
        "actualizados": len(operaciones),
        "sin_entregas": total_docs - len(operaciones),
        "min": valores[0] if valores else 0,
        "max": valores[-1] if valores else 0,
        "media": round(sum(valores) / len(valores), 1) if valores else 0,
        "suma": sum(valores),
    }


# ==========================================================================
# 2 · ESTADO FINAL DE LA FLOTILLA
# ==========================================================================
def reconciliar_vehiculos(bd, aplicar: bool) -> dict[str, Any]:
    # Odómetro final: el mayor registrado en los viajes del vehículo
    odometros = {
        d["_id"]: d["odometro"]
        for d in bd["viajes"].aggregate([
            {"$match": {"estatus": "FINALIZADO"}},
            {"$group": {"_id": "$vehiculo_id", "odometro": {"$max": "$odometro_final_km"},
                        "km": {"$sum": "$km_recorridos"}, "viajes": {"$sum": 1}}},
        ])
    }
    km_totales = {
        d["_id"]: {"km": round(d["km"], 1), "viajes": d["viajes"]}
        for d in bd["viajes"].aggregate([
            {"$match": {"estatus": "FINALIZADO"}},
            {"$group": {"_id": "$vehiculo_id", "km": {"$sum": "$km_recorridos"},
                        "viajes": {"$sum": 1}}},
        ])
    }

    # Último mantenimiento realizado y próximo programado
    ultimos = {
        d["_id"]: d for d in bd["mantenimientos"].aggregate([
            {"$match": {"estatus": "REALIZADO"}},
            {"$sort": {"fecha_realizada": 1}},
            {"$group": {"_id": "$vehiculo_id",
                        "ultimo": {"$last": "$fecha_realizada"},
                        "proximo": {"$last": "$proximo_mantenimiento_fecha"}}},
        ])
    }
    # Un mantenimiento VENCIDO deja al vehículo fuera de operación (RF-16)
    vencidos = {
        d["_id"] for d in bd["mantenimientos"].aggregate([
            {"$match": {"estatus": "VENCIDO"}},
            {"$group": {"_id": "$vehiculo_id"}},
        ])
    }

    operaciones = []
    resumen = {"DISPONIBLE": 0, "EN_MANTENIMIENTO": 0}
    for vehiculo in bd["vehiculos"].find({}, {"_id": 1}):
        vid = vehiculo["_id"]
        estado = "EN_MANTENIMIENTO" if vid in vencidos else "DISPONIBLE"
        resumen[estado] += 1
        cambios: dict[str, Any] = {
            "estado_operativo": estado,
            "fecha_modificacion": C.ahora_utc(),
        }
        if vid in odometros:
            cambios["odometro_actual_km"] = round(odometros[vid], 1)
        if vid in ultimos:
            cambios["fecha_ultimo_mantenimiento"] = ultimos[vid]["ultimo"]
            cambios["fecha_proximo_mantenimiento"] = ultimos[vid]["proximo"]
        operaciones.append(UpdateOne({"_id": vid}, {"$set": cambios}))

    if aplicar and operaciones:
        bd["vehiculos"].bulk_write(operaciones, ordered=False)

    kms = [v["km"] for v in km_totales.values()]
    return {
        "actualizados": len(operaciones),
        "estados": resumen,
        "con_mantenimiento": len(ultimos),
        "km_min": min(kms) if kms else 0,
        "km_max": max(kms) if kms else 0,
        "km_medio": round(sum(kms) / len(kms), 1) if kms else 0,
        "km_flotilla": round(sum(kms), 1),
    }


# ==========================================================================
# 3 · INTEGRIDAD REFERENCIAL EN LA BASE YA CARGADA
# ==========================================================================
def verificar_integridad(bd) -> list[tuple[str, bool, str]]:
    ids = {c: {d["_id"] for d in bd[c].find({}, {"_id": 1})}
           for c in ("clientes", "vehiculos", "operadores", "rutas", "viajes")}

    def huerfanos(coleccion: str, campo: str, destino: str) -> int:
        referidos = {d["_id"] for d in bd[coleccion].aggregate(
            [{"$group": {"_id": f"${campo}"}}]
        )}
        referidos.discard(None)
        return len(referidos - ids[destino])

    pruebas = [
        ("entregas → viajes", huerfanos("entregas", "viaje_id", "viajes")),
        ("entregas → rutas", huerfanos("entregas", "ruta_id", "rutas")),
        ("entregas → clientes", huerfanos("entregas", "cliente_id", "clientes")),
        ("entregas → vehiculos", huerfanos("entregas", "vehiculo_id", "vehiculos")),
        ("entregas → operadores", huerfanos("entregas", "operador_id", "operadores")),
        ("viajes → rutas", huerfanos("viajes", "ruta_id", "rutas")),
        ("incidentes → viajes", huerfanos("incidentes", "viaje_id", "viajes")),
        ("combustible → vehiculos", huerfanos("combustible", "vehiculo_id", "vehiculos")),
        ("mantenimientos → vehiculos", huerfanos("mantenimientos", "vehiculo_id", "vehiculos")),
    ]
    return [(nombre, n == 0, "sin huérfanos" if n == 0 else f"{n} referencias rotas")
            for nombre, n in pruebas]


# ==========================================================================
# 4 · REPORTE DE CALIDAD DEL DATASET  (insumo documentado de PA-5)
# ==========================================================================
CAMPOS_NULOS_VIGILADOS = (
    "hora_real_llegada", "tiempo_real_min", "retraso_min",
    "es_retraso", "causa_retraso", "observaciones",
)


def reporte_calidad(bd) -> None:
    total = bd["entregas"].count_documents({})

    C.encabezado("REPORTE DE CALIDAD DEL DATASET  ·  insumo de PA-5 (Unidad II)")

    print("  VALORES NULOS EN `entregas`")
    print(f"  {'CAMPO':<26}{'NULOS':>8}{'%':>9}   OBSERVACIÓN")
    print(C.SUBLINEA)
    for campo in CAMPOS_NULOS_VIGILADOS:
        nulos = bd["entregas"].count_documents(
            {"$or": [{campo: None}, {campo: {"$exists": False}}]}
        )
        nota = {
            "observaciones": "esperado: campo de texto libre opcional",
            "causa_retraso": "esperado: solo aplica a entregas retrasadas",
        }.get(campo, "a resolver en la limpieza")
        print(f"  {campo:<26}{nulos:>8}{nulos/total:>8.1%}   {nota}")

    # ---- Duplicados por clave de negocio ---------------------------------
    duplicados = list(bd["entregas"].aggregate([
        {"$group": {"_id": {"viaje": "$viaje_id", "cliente": "$cliente_id",
                            "orden": "$orden_parada"},
                    "n": {"$sum": 1}, "folios": {"$push": "$folio_entrega"}}},
        {"$match": {"n": {"$gt": 1}}},
    ]))
    print("\n  DUPLICADOS")
    print(f"      Grupos (viaje + cliente + parada) repetidos: {len(duplicados)}")
    print(f"      Documentos sobrantes a eliminar: {sum(d['n'] - 1 for d in duplicados)}")
    if duplicados:
        ejemplo = duplicados[0]["folios"]
        print(f"      Ejemplo: {' / '.join(ejemplo)}")

    # ---- Distribución de la variable objetivo -----------------------------
    est = list(bd["entregas"].aggregate([
        {"$match": {"retraso_min": {"$ne": None}}},
        {"$group": {"_id": None, "n": {"$sum": 1},
                    "media": {"$avg": "$retraso_min"},
                    "desv": {"$stdDevPop": "$retraso_min"},
                    "min": {"$min": "$retraso_min"},
                    "max": {"$max": "$retraso_min"},
                    "retrasadas": {"$sum": "$es_retraso"}}},
    ]))[0]
    print("\n  VARIABLE OBJETIVO `retraso_min`")
    print(f"      Registros utilizables .... {est['n']}")
    print(f"      Media / desv. estándar ... {est['media']:.1f} / {est['desv']:.1f} min")
    print(f"      Rango .................... {est['min']:.1f} a {est['max']:.1f} min")
    print(f"      es_retraso = 1 ........... {est['retrasadas']} "
          f"({est['retrasadas']/est['n']:.1%})")

    # ---- Outliers por regla IQR (la técnica que aplicará PA-5) -----------
    valores = sorted(d["retraso_min"] for d in bd["entregas"].find(
        {"retraso_min": {"$ne": None}}, {"retraso_min": 1}))
    q1 = valores[len(valores) // 4]
    q3 = valores[3 * len(valores) // 4]
    iqr = q3 - q1
    inf, sup = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    fuera = sum(1 for v in valores if v < inf or v > sup)
    print("\n  OUTLIERS POR REGLA IQR (vista previa de la técnica de PA-5)")
    print(f"      Q1 {q1:.1f}  ·  Q3 {q3:.1f}  ·  IQR {iqr:.1f}")
    print(f"      Límites: {inf:.1f} a {sup:.1f} min")
    print(f"      Fuera de límites: {fuera} ({fuera/len(valores):.1%})")
    print("      Nota: muchos son retrasos legítimos por incidentes graves.")
    print("      PA-5 debe decidir si se eliminan o se conservan.")

    # ---- Rango temporal y trazabilidad del origen -------------------------
    rango = list(bd["entregas"].aggregate([
        {"$group": {"_id": None, "desde": {"$min": "$fecha"}, "hasta": {"$max": "$fecha"}}},
    ]))[0]
    print("\n  COBERTURA Y TRAZABILIDAD")
    print(f"      Periodo cubierto ......... {rango['desde'].date()} a {rango['hasta'].date()}")
    for coleccion in settings.COLECCIONES_OPERATIVAS:
        n = bd[coleccion].count_documents({})
        if not n:
            continue
        simulados = bd[coleccion].count_documents({"origen_dato": "SIMULADO"})
        marca = "OK" if simulados == n else "REVISAR"
        print(f"      {coleccion:<22}{simulados}/{n} SIMULADO  [{marca}]")


# ==========================================================================
# IMPRESIÓN
# ==========================================================================
def imprimir_reconciliacion(clientes, operadores, vehiculos) -> None:
    C.encabezado("RECONCILIACIÓN DE CONTADORES")

    for res in (clientes, operadores):
        print(f"  {res['coleccion'].upper()}")
        print(f"      Documentos actualizados .. {res['actualizados']}")
        print(f"      Sin entregas registradas . {res['sin_entregas']}")
        print(f"      Entregas por entidad ..... min {res['min']} · "
              f"media {res['media']} · max {res['max']}")
        print(f"      Suma de contadores ....... {res['suma']}")

    print("  VEHICULOS")
    print(f"      Documentos actualizados .. {vehiculos['actualizados']}")
    print(f"      Con mantenimiento previo . {vehiculos['con_mantenimiento']}")
    print(f"      Kilómetros del periodo ... min {vehiculos['km_min']:,.1f} · "
          f"media {vehiculos['km_medio']:,.1f} · max {vehiculos['km_max']:,.1f}")
    print(f"      Kilometraje de flotilla .. {vehiculos['km_flotilla']:,.1f} km")
    for estado, n in vehiculos["estados"].items():
        print(f"      {estado:<24} {n}")
    print(f"      Criterio: estado evaluado al cierre del periodo simulado")
    print(f"      ({P.FECHA_FIN}). Un mantenimiento VENCIDO deja al vehículo")
    print(f"      fuera de operación (RF-16).")


def imprimir_integridad(resultados) -> bool:
    C.encabezado("INTEGRIDAD REFERENCIAL EN LA BASE CARGADA")
    for nombre, ok, detalle in resultados:
        print(f"  {'[OK]   ' if ok else '[FALLA]'} {nombre:<34}{detalle}")
    fallos = sum(1 for _, ok, _ in resultados if not ok)
    print(C.SUBLINEA)
    print(f"  {len(resultados) - fallos}/{len(resultados)} comprobaciones correctas")
    return fallos == 0


# ==========================================================================
# PUNTO DE ENTRADA
# ==========================================================================
def main() -> int:
    parser = argparse.ArgumentParser(
        description="PA-3 — Reconcilia contadores y reporta la calidad del dataset.",
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Calcula y muestra los cambios sin escribirlos.")
    parser.add_argument("--solo-reporte", action="store_true",
                        help="Omite la reconciliación; solo imprime el reporte de calidad.")
    args = parser.parse_args()

    C.aviso_datos_simulados()
    if not verificar_conexion(verbose=True)["exito"]:
        return 1

    try:
        bd = obtener_bd()
        if bd["entregas"].count_documents({}) == 0:
            print("\n  La colección `entregas` está vacía. Ejecuta primero PA-2:")
            print("  python -m database.seed.generar_operacion")
            return 1

        aplicar = not (args.dry_run or args.solo_reporte)

        if not args.solo_reporte:
            imprimir_reconciliacion(
                reconciliar_contadores(bd, "clientes", "cliente_id", aplicar),
                reconciliar_contadores(bd, "operadores", "operador_id", aplicar),
                reconciliar_vehiculos(bd, aplicar),
            )
            if not aplicar:
                print("\n  --dry-run activo: no se escribió ningún cambio.")

        integridad_ok = imprimir_integridad(verificar_integridad(bd))
        reporte_calidad(bd)

        print()
        print(C.LINEA)
        if integridad_ok:
            print("  PA-3 TERMINADA. Dataset operativo completo y verificado.")
            print("  Siguiente actividad: PA-4 (exploración de datos, Unidad I).")
        else:
            print("  PA-3 TERMINADA CON HALLAZGOS. Revisa la integridad referencial")
            print("  antes de continuar con el ETL.")
        print(C.LINEA)
        return 0 if integridad_ok else 1

    finally:
        cerrar_cliente()


if __name__ == "__main__":
    sys.exit(main())
