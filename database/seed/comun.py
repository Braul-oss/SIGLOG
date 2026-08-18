"""
SIG-LOG — Sistema Integral de Gestión Logística
database/seed/comun.py

Utilidades compartidas por todos los generadores de DATOS SIMULADOS
(PA-1 catálogos, PA-2 operación, PA-3 eventos).

Regla invariable: toda función que construya un documento debe pasar por
`campos_comunes()`, que estampa `origen_dato: "SIMULADO"`. Ese campo es lo
que impide confundir datos simulados con datos reales (§16.3, regla 1).
"""

from __future__ import annotations

import random
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Iterable, Sequence, TypeVar

from database.seed import parametros as P

T = TypeVar("T")


# --------------------------------------------------------------------------
# Aleatoriedad reproducible
# --------------------------------------------------------------------------
def crear_rng(semilla: int | None = None) -> random.Random:
    """Generador con semilla fija (42 por defecto, como en clase)."""
    return random.Random(P.SEMILLA if semilla is None else semilla)


def elegir_ponderado(rng: random.Random, pesos: dict[str, float]) -> str:
    """Elige una clave según su peso relativo."""
    claves = list(pesos.keys())
    return rng.choices(claves, weights=[pesos[k] for k in claves], k=1)[0]


def repartir(rng: random.Random, total: int, partes: int,
             minimo: int, maximo: int) -> list[int]:
    """
    Reparte `total` unidades entre `partes` grupos, cada uno en [minimo, maximo].

    Se usa para decidir cuántas paradas tendrá cada ruta garantizando que la
    suma cubra exactamente a todos los clientes de la zona.
    """
    if not partes * minimo <= total <= partes * maximo:
        raise ValueError(
            f"No se puede repartir {total} entre {partes} grupos de "
            f"[{minimo}, {maximo}]."
        )
    tamanos = [minimo] * partes
    restante = total - sum(tamanos)
    while restante > 0:
        i = rng.randrange(partes)
        if tamanos[i] < maximo:
            tamanos[i] += 1
            restante -= 1
    rng.shuffle(tamanos)
    return tamanos


def muestra_sin_repeticion(rng: random.Random, poblacion: Sequence[T], k: int) -> list[T]:
    """Muestra de k elementos distintos."""
    return rng.sample(list(poblacion), k)


# --------------------------------------------------------------------------
# Fechas y horas
# --------------------------------------------------------------------------
def ahora_utc() -> datetime:
    """Marca temporal con zona horaria, coherente con tz_aware=True del cliente."""
    return datetime.now(timezone.utc)


def a_datetime(dia: date, hora_texto: str) -> datetime:
    """Combina una fecha con una hora en formato 'HH:MM'."""
    horas, minutos = (int(x) for x in hora_texto.split(":"))
    return datetime.combine(dia, time(horas, minutos), tzinfo=timezone.utc)


def dias_de_operacion(inicio: date, fin: date,
                      dias_semana: Iterable[int] = P.DIAS_OPERACION_SEMANA) -> list[date]:
    """Lista de días hábiles del periodo simulado (lunes a sábado)."""
    permitidos = set(dias_semana)
    dias: list[date] = []
    actual = inicio
    while actual <= fin:
        if actual.weekday() in permitidos:
            dias.append(actual)
        actual += timedelta(days=1)
    return dias


def hora_aleatoria(rng: random.Random, desde: str, hasta: str, paso_min: int) -> str:
    """Hora 'HH:MM' aleatoria dentro del rango, en múltiplos de `paso_min`."""
    h1, m1 = (int(x) for x in desde.split(":"))
    h2, m2 = (int(x) for x in hasta.split(":"))
    inicio, fin = h1 * 60 + m1, h2 * 60 + m2
    minutos = rng.randrange(inicio, fin + 1, paso_min)
    return f"{minutos // 60:02d}:{minutos % 60:02d}"


def fecha_aleatoria(rng: random.Random, anio_min: int, anio_max: int) -> datetime:
    """Fecha aleatoria (a medianoche UTC) entre el 1-ene de dos años dados."""
    inicio = date(anio_min, 1, 1)
    fin = date(anio_max, 12, 31)
    dia = inicio + timedelta(days=rng.randrange((fin - inicio).days + 1))
    return datetime.combine(dia, time(0, 0), tzinfo=timezone.utc)


# --------------------------------------------------------------------------
# Campos comunes y folios
# --------------------------------------------------------------------------
def campos_comunes(activo: bool = True) -> dict[str, Any]:
    """
    Campos presentes en TODAS las colecciones (§11, encabezado).

    `origen_dato: "SIMULADO"` es obligatorio y no admite excepción.
    """
    momento = ahora_utc()
    return {
        "origen_dato": P.ORIGEN_DATO,
        "activo": activo,
        "fecha_creacion": momento,
        "fecha_modificacion": momento,
    }


def codigo(prefijo: str, numero: int, ancho: int = 3) -> str:
    """Clave de negocio con ceros a la izquierda: CLI-001, VEH-020, RUT-007."""
    return f"{prefijo}-{numero:0{ancho}d}"


def folio_fechado(prefijo: str, dia: date, consecutivo: int, ancho: int = 4) -> str:
    """Folio con fecha embebida: VJE-20260216-0001 (usado por PA-2 y PA-3)."""
    return f"{prefijo}-{dia.strftime('%Y%m%d')}-{consecutivo:0{ancho}d}"


# --------------------------------------------------------------------------
# Salida por consola
# --------------------------------------------------------------------------
LINEA = "=" * 72
SUBLINEA = "-" * 72


def encabezado(titulo: str) -> None:
    print()
    print(LINEA)
    print(f"  {titulo}")
    print(LINEA)


def aviso_datos_simulados() -> None:
    """Se imprime siempre. Debe quedar en la evidencia entregada al profesor."""
    print(LINEA)
    print("  ⚠  DATOS SIMULADOS")
    print("  Ninguna cifra generada describe una empresa real (decisión C-02).")
    print(f"  Todo documento se marca con origen_dato: \"{P.ORIGEN_DATO}\".")
    print(f"  Parámetros: Anexo B  ·  semilla = {P.SEMILLA}")
    print(LINEA)
