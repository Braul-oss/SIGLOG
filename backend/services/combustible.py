"""
SIG-LOG — Sistema Integral de Gestión Logística
backend/services/combustible.py

REGLAS DEL MÓDULO COMBUSTIBLE  (§11.8)

Cada carga es un hecho inmutable: se registra y no se edita ni se borra.
De estas cargas salen el rendimiento real de la flotilla, el KPI de costo
por kilómetro y las variables del clustering de vehículos.

Reglas de negocio (RN-F1 a RN-F8)
---------------------------------
RN-F1  El folio CMB-AAAAMMDD-NNNN lo genera el sistema y es inmutable.

RN-F2  `costo_total` = litros × precio_por_litro (§11.12). No se captura:
       un total tecleado podría no cuadrar con sus propias cifras.

RN-F3  `km_recorridos_desde_carga_anterior` sale de restar el odómetro de
       la carga anterior de esa unidad. En la PRIMERA carga de un vehículo
       queda en null, y eso es correcto: sin carga previa no hay tramo que
       medir, y poner cero fingiría un recorrido de cero kilómetros que
       hundiría el rendimiento promedio.

RN-F4  `rendimiento_km_l` = km del tramo / litros (§11.12). Es la cifra
       que compara el rendimiento real contra el nominal de fábrica.

RN-F5  El odómetro debe superar al de la carga anterior: el kilometraje no
       baja. Es la comprobación que evita que una lectura mal tecleada
       produzca un rendimiento absurdo.

RN-F6  Los litros no pueden superar la capacidad del tanque de la unidad.
       Cargar más de lo que cabe es un error de captura.

RN-F7  El combustible debe ser el de la unidad: no se le pone gasolina a
       un diésel. Si el registro dice lo contrario, o el vehículo está mal
       dado de alta o la carga se atribuyó a la unidad equivocada, y
       ambas cosas ensucian el análisis de consumo.

RN-F8  La carga actualiza el `odometro_actual_km` del vehículo. El §11.2
       dice que ese campo "se actualiza con cada carga/viaje": el cierre
       del viaje ya cumplía la mitad, y esta es la otra.

Sobre dónde se calcula el rendimiento
-------------------------------------
El §11.8 marca `km_recorridos_desde_carga_anterior` y `rendimiento_km_l`
como "calculado en el ETL". Aquí se calculan al registrar, y no es una
contradicción: el odómetro de la carga anterior ya se conoce en ese
momento, y dejarlos nulos hasta la próxima corrida del ETL dejaría la
colección operativa en un estado que ni el seed produce ni
`/vehiculos/{id}/rendimiento` puede leer. El ETL sigue haciendo lo suyo
—agregar por vehículo para el DW—; simplemente encuentra el trabajo por
carga ya hecho.
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from pymongo.database import Database

from backend.repositories.combustible import RepositorioCombustible
from backend.schemas.combustible import CargaSalida
from backend.utils.errores import ReglaDeNegocio
from config import settings


# ==========================================================================
# CONSULTA
# ==========================================================================
def listar(bd: Database, *, saltar: int = 0, limite: int = 50,
           vehiculo_id: str | None = None, viaje_id: str | None = None,
           estacion: str | None = None, fecha_desde: date | None = None,
           fecha_hasta: date | None = None
           ) -> tuple[list[dict[str, Any]], int]:
    repositorio = RepositorioCombustible(bd)
    filtro: dict[str, Any] = {}

    for campo, valor in (("vehiculo_id", vehiculo_id), ("viaje_id", viaje_id)):
        if valor:
            filtro[campo] = repositorio.a_object_id(valor)
    if estacion:
        filtro["estacion"] = {"$regex": f"^{estacion.strip()}$",
                              "$options": "i"}

    rango: dict[str, Any] = {}
    if fecha_desde:
        rango["$gte"] = _a_datetime(fecha_desde)
    if fecha_hasta:
        rango["$lte"] = _a_datetime(fecha_hasta).replace(hour=23, minute=59,
                                                         second=59)
    if rango:
        filtro["fecha"] = rango

    documentos = repositorio.listar(
        filtro, saltar=saltar, limite=limite,
        orden=[("fecha", -1)], incluir_inactivos=True)
    total = repositorio.contar(filtro, incluir_inactivos=True)
    return [_publico(d) for d in documentos], total


def obtener(bd: Database, identificador: str) -> dict[str, Any]:
    return _publico(
        RepositorioCombustible(bd).obtener(identificador, incluir_inactivos=True))


def resumen(bd: Database, top: int = 10) -> dict[str, Any]:
    """
    Consumo y costo agregado (§12.3).

    Es la vista que responde dos de las preguntas del caso de estudio:
    qué vehículos generan mayores costos y cuáles consumen más
    combustible.
    """
    repositorio = RepositorioCombustible(bd)
    totales = repositorio.totales()
    litros = totales.get("litros") or 0
    km = totales.get("km") or 0
    costo = totales.get("costo") or 0

    vehiculos = repositorio.por_vehiculo(top)
    peor = min((v for v in vehiculos if v.get("rendimiento_km_l")),
               key=lambda v: v["rendimiento_km_l"], default=None)

    return {
        "cargas": totales.get("cargas", 0),
        "litros_totales": round(litros, 1),
        "costo_total": round(costo, 2),
        "km_recorridos": round(km, 1),
        "precio_medio_por_litro": (round(totales["precio_medio"], 2)
                                   if totales.get("precio_medio") else None),
        "rendimiento_flotilla_km_l": (round(km / litros, 2) if litros else None),
        "costo_por_km": (round(costo / km, 2) if km else None),
        "por_vehiculo": vehiculos,
        "por_estacion": repositorio.por_estacion(),
        "lectura": _interpretar(costo, km, litros, peor),
    }


def catalogos(bd: Database) -> dict[str, Any]:
    return {
        "tipos_combustible": list(settings.CATALOGO_TIPO_COMBUSTIBLE),
        "estaciones": RepositorioCombustible(bd).estaciones(),
        "nota_calculados": (
            "costo_total, km_recorridos_desde_carga_anterior y "
            "rendimiento_km_l los calcula el sistema al registrar la carga; "
            "no se capturan."),
    }


# ==========================================================================
# REGISTRO
# ==========================================================================
def registrar(bd: Database, datos: dict[str, Any]) -> dict[str, Any]:
    """Registra la carga aplicando RN-F1 a RN-F8."""
    repositorio = RepositorioCombustible(bd)
    vehiculo = repositorio.vehiculo(
        repositorio.a_object_id(datos["vehiculo_id"]))
    if vehiculo is None:
        raise ReglaDeNegocio(f"No existe el vehículo '{datos['vehiculo_id']}'.")

    fecha = _fecha_o_ahora(datos.get("fecha"))
    litros = float(datos["litros"])
    odometro = float(datos["odometro_km"])

    tipo = _validar_tipo(vehiculo, datos.get("tipo_combustible"))      # RN-F7
    _validar_capacidad(vehiculo, litros)                               # RN-F6
    anterior = _validar_odometro(repositorio, vehiculo, odometro, fecha)  # RN-F5
    viaje_id = _validar_viaje(repositorio, vehiculo, datos.get("viaje_id"))

    # RN-F3 y RN-F4 — el tramo y su rendimiento
    km_tramo = (round(odometro - anterior["odometro_km"], 1)
                if anterior else None)
    rendimiento = (round(km_tramo / litros, 2)
                   if km_tramo is not None and litros else None)

    documento = {
        "folio_carga": repositorio.siguiente_folio(fecha),             # RN-F1
        "vehiculo_id": vehiculo["_id"],
        "viaje_id": viaje_id,
        "fecha": fecha,
        "litros": round(litros, 2),
        "precio_por_litro": round(float(datos["precio_por_litro"]), 2),
        "costo_total": round(litros * float(datos["precio_por_litro"]), 2),  # RN-F2
        "odometro_km": round(odometro, 1),
        "km_recorridos_desde_carga_anterior": km_tramo,
        "rendimiento_km_l": rendimiento,
        "tipo_combustible": tipo,
        "estacion": datos.get("estacion"),
    }
    creada = repositorio.crear(documento)

    # RN-F8 — el odómetro del vehículo queda al día
    if odometro > float(vehiculo.get("odometro_actual_km") or 0):
        repositorio.actualizar_odometro_vehiculo(vehiculo["_id"], odometro)

    return _publico(creada)


# ==========================================================================
# VALIDACIONES
# ==========================================================================
def _validar_tipo(vehiculo: dict[str, Any], solicitado: str | None) -> str:
    """RN-F7: el combustible debe ser el que usa la unidad."""
    del_vehiculo = vehiculo.get("tipo_combustible")
    if solicitado is None:
        return del_vehiculo
    if del_vehiculo and solicitado != del_vehiculo:
        raise ReglaDeNegocio(
            f"El vehículo {vehiculo['codigo_vehiculo']} usa {del_vehiculo} y "
            f"la carga dice {solicitado} (RN-F7). O la unidad está mal dada "
            "de alta o la carga se atribuyó al vehículo equivocado.",
            regla="F7",
            detalles=[{"combustible_del_vehiculo": del_vehiculo,
                       "combustible_de_la_carga": solicitado}])
    return solicitado


def _validar_capacidad(vehiculo: dict[str, Any], litros: float) -> None:
    """RN-F6: no caben más litros que la capacidad del tanque."""
    capacidad = vehiculo.get("capacidad_tanque_litros")
    if capacidad and litros > float(capacidad):
        raise ReglaDeNegocio(
            f"No se pueden cargar {litros:,.1f} litros en "
            f"{vehiculo['codigo_vehiculo']}: su tanque es de "
            f"{float(capacidad):,.0f} litros (RN-F6).",
            regla="F6",
            detalles=[{"capacidad_tanque_litros": float(capacidad),
                       "litros_solicitados": litros}])


def _validar_odometro(repositorio: RepositorioCombustible,
                      vehiculo: dict[str, Any], odometro: float,
                      fecha: datetime) -> dict[str, Any] | None:
    """RN-F5: el kilometraje no baja respecto de la carga anterior."""
    anterior = repositorio.carga_anterior(vehiculo["_id"], fecha)
    if anterior and odometro <= float(anterior["odometro_km"]):
        raise ReglaDeNegocio(
            f"El odómetro ({odometro:,.1f} km) no supera al de la carga "
            f"anterior {anterior['folio_carga']} "
            f"({float(anterior['odometro_km']):,.1f} km) (RN-F5). El "
            "kilometraje no baja: revisa la lectura.",
            regla="F5",
            detalles=[{"odometro_declarado": odometro,
                       "odometro_carga_anterior": float(anterior["odometro_km"]),
                       "folio_anterior": anterior["folio_carga"]}])

    # Una carga posterior con odómetro menor dejaría su tramo en negativo.
    posterior = repositorio.carga_posterior(vehiculo["_id"], fecha)
    if posterior and odometro >= float(posterior["odometro_km"]):
        raise ReglaDeNegocio(
            f"Ya existe una carga posterior ({posterior['folio_carga']}) con "
            f"odómetro {float(posterior['odometro_km']):,.1f} km. Registrar "
            f"esta con {odometro:,.1f} km dejaría su tramo en negativo "
            "(RN-F5).",
            regla="F5",
            detalles=[{"folio_posterior": posterior["folio_carga"]}])
    return anterior


def _validar_viaje(repositorio: RepositorioCombustible,
                   vehiculo: dict[str, Any], viaje_id: str | None):
    """Si la carga se atribuye a un viaje, debe ser un viaje de esa unidad."""
    if not viaje_id:
        return None
    viaje = repositorio.viaje(repositorio.a_object_id(viaje_id))
    if viaje is None:
        raise ReglaDeNegocio(f"No existe el viaje '{viaje_id}'.")
    if viaje.get("vehiculo_id") != vehiculo["_id"]:
        raise ReglaDeNegocio(
            f"El viaje {viaje['folio_viaje']} no es de la unidad "
            f"{vehiculo['codigo_vehiculo']}: la carga no puede atribuírsele.")
    return viaje["_id"]


# ==========================================================================
# INTERNO
# ==========================================================================
def _interpretar(costo: float, km: float, litros: float,
                 peor: dict[str, Any] | None) -> str:
    """Lectura en lenguaje natural del resumen (RF-29)."""
    if not costo:
        return "Todavía no hay cargas de combustible registradas."

    texto = (f"${costo:,.0f} en {litros:,.0f} litros para "
             f"{km:,.0f} km recorridos")
    if km:
        texto += (f", es decir ${costo / km:.2f} por kilómetro y "
                  f"{km / litros:.2f} km/l de rendimiento de flotilla")
    if peor:
        texto += (f". La unidad de menor rendimiento entre las de mayor "
                  f"consumo es {peor['codigo_vehiculo']} con "
                  f"{peor['rendimiento_km_l']:.2f} km/l")
    return texto + "."


def _a_datetime(valor: Any) -> datetime:
    if isinstance(valor, datetime):
        return valor if valor.tzinfo else valor.replace(tzinfo=timezone.utc)
    if isinstance(valor, date):
        return datetime(valor.year, valor.month, valor.day, tzinfo=timezone.utc)
    return datetime.fromisoformat(str(valor)).replace(tzinfo=timezone.utc)


def _fecha_o_ahora(valor: Any) -> datetime:
    return _a_datetime(valor) if valor else datetime.now(timezone.utc)


def _publico(documento: dict[str, Any]) -> dict[str, Any]:
    return CargaSalida.desde_documento(documento).model_dump()
