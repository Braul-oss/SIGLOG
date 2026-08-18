"""
SIG-LOG — Sistema Integral de Gestión Logística
etl/run_etl.py

ORQUESTADOR DEL ETL — encadena en una sola corrida las capas construidas
en PA-4 a PA-7, en el orden real de dependencia:

    1. EXTRACCIÓN        etl/extraccion.py       (Mongo → pandas + data/raw)
    2. LIMPIEZA          etl/limpieza.py         (D-L1..D-L5)
    3. TRANSFORMACIÓN    etl/transformacion.py   (dataset analítico)
    4. ENRIQUECIMIENTO   etl/enriquecimiento.py  (métricas y dataset de rutas)
    5. CARGA DW          etl/carga.py            (hecho_entrega + dimensiones)

Todo se ejecuta EN MEMORIA sobre una única extracción y al final se
escriben los mismos archivos que producen los scripts individuales
(data/raw, data/processed), de modo que correr el orquestador o correr
las actividades una a una deja el proyecto en el mismo estado.

La exploración (PA-4) no forma parte de la corrida: es un análisis, no
una capa productiva. Se ejecuta aparte con `python -m etl.exploracion`.

Uso
---
    python -m etl.run_etl              # pipeline completo
    python -m etl.run_etl --sin-dw     # todo menos la carga en MongoDB
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from config.mongo_conexion import cerrar_cliente, obtener_bd, verificar_conexion
from etl import carga, enriquecimiento, extraccion, limpieza, transformacion


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Orquestador del ETL de SIG-LOG (extracción → carga del DW).",
    )
    parser.add_argument("--sin-dw", action="store_true",
                        help="Ejecuta todo el pipeline pero no escribe en MongoDB.")
    args = parser.parse_args()

    if not verificar_conexion(verbose=True)["exito"]:
        return 1

    inicio_total = time.perf_counter()
    tiempos: list[tuple[str, float, str]] = []
    codigo = 0

    def paso(nombre: str, resumen: str, desde: float) -> None:
        tiempos.append((nombre, time.perf_counter() - desde, resumen))
        print(f"  [{len(tiempos)}] {nombre:<18} {resumen}")

    try:
        bd = obtener_bd()
        print("\n" + "=" * 70)
        print("  SIG-LOG · ORQUESTADOR ETL")
        print("=" * 70)

        # 1 · Extracción (una sola vez; alimenta todo lo demás)
        t = time.perf_counter()
        entregas_crudas = extraccion.extraer("entregas", bd=bd)
        paso("EXTRACCIÓN", f"{len(entregas_crudas):,} entregas crudas", t)

        # 2 · Limpieza
        t = time.perf_counter()
        limpio, bitacora = limpieza.limpiar_entregas(entregas_crudas)
        paso("LIMPIEZA", f"{len(limpio):,} filas "
             f"(-{bitacora['duplicados']['eliminados']} duplicados)", t)

        # 3 · Transformación (reutiliza la limpieza ya hecha vía transformar
        #     sería re-extraer; se encadena manualmente con sus funciones)
        t = time.perf_counter()
        df = transformacion.aplanar(limpio)
        df = transformacion.derivar_temporales(df)
        df = transformacion.unir_catalogos(df, bd=bd)
        columnas = (transformacion.COLUMNAS_ID + transformacion.COLUMNAS_FEATURES
                    + transformacion.COLUMNAS_OBJETIVO + transformacion.COLUMNAS_CONTROL)
        dataset = df[columnas].copy()
        paso("TRANSFORMACIÓN", f"dataset {dataset.shape[0]:,} × {dataset.shape[1]}", t)

        # 4 · Enriquecimiento
        t = time.perf_counter()
        hecho = carga.construir_hecho(dataset)      # ids en texto para las métricas
        veh = enriquecimiento.metricas_vehiculos(bd=bd)
        ope = enriquecimiento.metricas_operadores(hecho, bd=bd)
        rut = enriquecimiento.dataset_rutas(hecho, bd=bd)
        paso("ENRIQUECIMIENTO", f"{len(veh)} vehículos · {len(ope)} operadores "
             f"· {len(rut)} rutas", t)

        # 5 · Archivos procesados (mismo estado que los scripts individuales)
        t = time.perf_counter()
        transformacion.CARPETA_PROCESSED.mkdir(parents=True, exist_ok=True)
        for frame, ruta in (
            (limpio, limpieza.ARCHIVO_LIMPIO),
            (dataset, transformacion.ARCHIVO_DATASET),
            (veh, enriquecimiento.ARCHIVO_VEHICULOS),
            (ope, enriquecimiento.ARCHIVO_OPERADORES),
            (rut, enriquecimiento.ARCHIVO_RUTAS),
        ):
            extraccion.aplanar_para_csv(frame).to_csv(ruta, index=False,
                                                      encoding="utf-8")
        paso("ARCHIVOS", "data/processed actualizado (5 CSV)", t)

        # 6 · Carga del data warehouse
        t = time.perf_counter()
        codigo, hecho, dimensiones = carga.ejecutar_carga(
            bd, dataset, aplicar=not args.sin_dw)
        total_dw = len(hecho) + sum(len(d) for d in dimensiones.values())
        paso("CARGA DW", ("omitida (--sin-dw)" if args.sin_dw
                          else f"{total_dw:,} documentos en 6 colecciones"), t)

    except Exception as exc:                       # noqa: BLE001
        print(f"\n  ERROR en el pipeline: {type(exc).__name__}: {exc}")
        codigo = 1
    finally:
        cerrar_cliente()

    print("\n" + "=" * 70)
    print("  RESUMEN DE LA CORRIDA")
    print("=" * 70)
    for nombre, segundos, resumen in tiempos:
        print(f"  {nombre:<18}{segundos:>7.1f} s   {resumen}")
    print("-" * 70)
    print(f"  {'TOTAL':<18}{time.perf_counter() - inicio_total:>7.1f} s   "
          f"{'ETL COMPLETO SIN FALLAS' if codigo == 0 else 'CON FALLAS'}")
    print("=" * 70)
    return codigo


if __name__ == "__main__":
    sys.exit(main())
