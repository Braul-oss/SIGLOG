"""
SIG-LOG — Sistema Integral de Gestión Logística
reportes/generar.py

GENERACIÓN DE INFORMES DESDE LA CONSOLA

    python -m reportes.generar                    los tres, a data/outputs/
    python -m reportes.generar --tipo ejecutivo   solo uno
    python -m reportes.generar --destino /ruta    a otra carpeta

Existe además del endpoint del API porque un informe se puede querer sin
levantar el servidor: para adjuntarlo a una entrega, para archivarlo o para
comprobar que sigue generándose después de tocar la capa analítica.

Los dos caminos llaman a la MISMA función `construir(bd)` de cada informe.
Si divergieran, el PDF que descarga un usuario dejaría de ser el mismo que
el que se archiva.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from config.mongo_conexion import cerrar_cliente, obtener_bd, verificar_conexion
from reportes import ejecutivo, flotilla, operativo

CARPETA_SALIDA = RAIZ / "data" / "outputs"

INFORMES = {
    "ejecutivo": (ejecutivo, "Estado de la operación, para dirección"),
    "flotilla": (flotilla, "Desempeño de los vehículos"),
    "operativo": (operativo, "Qué hay que atender hoy"),
}


def generar(tipo: str, bd) -> bytes:
    """Construye un informe. Es el punto único: el API llama a lo mismo."""
    if tipo not in INFORMES:
        raise ValueError(f"Informe '{tipo}' no existe. Hay: {list(INFORMES)}")
    modulo, _ = INFORMES[tipo]
    return modulo.construir(bd)


def nombre_archivo(tipo: str) -> str:
    """`informe_flotilla_20260818.pdf` — la fecha va en el nombre porque un
    informe describe un momento y acaba conviviendo con sus versiones."""
    return f"informe_{tipo}_{datetime.now():%Y%m%d}.pdf"


def main() -> int:
    analizador = argparse.ArgumentParser(
        description="Genera los informes en PDF de SIG-LOG.")
    analizador.add_argument(
        "--tipo", choices=sorted(INFORMES), default=None,
        help="Informe a generar. Si se omite, se generan los tres.")
    analizador.add_argument(
        "--destino", default=str(CARPETA_SALIDA),
        help=f"Carpeta de salida (por omisión {CARPETA_SALIDA}).")
    argumentos = analizador.parse_args()

    print("=" * 70)
    print("  SIG-LOG — Generación de informes en PDF")
    print("=" * 70)

    respuesta = verificar_conexion()
    if not respuesta["exito"]:
        print(f"  MongoDB no disponible: {respuesta['mensaje']}")
        return 1

    destino = Path(argumentos.destino)
    destino.mkdir(parents=True, exist_ok=True)
    tipos = [argumentos.tipo] if argumentos.tipo else sorted(INFORMES)

    bd = obtener_bd()
    fallos = 0
    try:
        for tipo in tipos:
            _, descripcion = INFORMES[tipo]
            try:
                contenido = generar(tipo, bd)
            except Exception as error:              # noqa: BLE001
                fallos += 1
                print(f"  [FALLA] {tipo:11} {type(error).__name__}: {error}")
                continue

            archivo = destino / nombre_archivo(tipo)
            archivo.write_bytes(contenido)
            print(f"  [OK]    {tipo:11} {len(contenido):>9,} bytes  "
                  f"{archivo.name}")
            print(f"          {descripcion}")
    finally:
        cerrar_cliente()

    print("-" * 70)
    print(f"  {len(tipos) - fallos}/{len(tipos)} informes generados en "
          f"{destino}")
    print("=" * 70)
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
