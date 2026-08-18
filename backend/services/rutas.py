"""
SIG-LOG — Sistema Integral de Gestión Logística
backend/services/rutas.py

REGLAS DEL MÓDULO RUTAS  (§11.4)

Reglas de negocio (RN-R1 a RN-R6)
---------------------------------
RN-R1  `codigo_ruta` lo genera el sistema (RUT-NNN) y es inmutable.

RN-R2  Los totales de la ruta —distancia, tiempo, número de paradas y
       velocidad efectiva— se RECALCULAN a partir de las paradas cada vez
       que estas cambian. Nunca se capturan. Si el total pudiera
       contradecir a sus partes, el clustering agruparía rutas por una
       cifra que no describe el recorrido.

RN-R3  Una ruta tiene al menos una parada, y sus paradas van numeradas
       1..N sin huecos ni repeticiones. El orden define el recorrido y es
       lo que produce el efecto de acumulación del retraso, así que lo
       asigna el sistema por la posición en la lista.

RN-R4  El cliente de cada parada debe existir, estar activo y tener
       registrada la dirección que se indica. Una parada que apunta a una
       dirección inexistente es un viaje que no se puede hacer.

RN-R5  Un cliente no se repite dentro de la misma ruta. Visitarlo dos
       veces en un mismo recorrido es casi siempre un error de captura; si
       alguna vez fuera legítimo, esta es la regla a relajar.

RN-R6  No se da de baja una ruta con vehículo asignado o con viajes sin
       cerrar: el vehículo quedaría apuntando a una ruta inactiva y los
       viajes sin plan que ejecutar.

Sobre la asignación de vehículo
-------------------------------
`PUT /rutas/{id}/asignar-vehiculo` es el mismo RN-04 que ya resuelve el
módulo de vehículos, visto desde el otro extremo. Por eso este servicio
DELEGA en `services.vehiculos.asignar_ruta` en lugar de reimplementarlo:
dos implementaciones de la misma regla acabarían discrepando, y es
precisamente la regla que mantiene coherentes los dos lados de la
relación.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from bson import ObjectId
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from backend.repositories.rutas import RepositorioRutas
from backend.schemas.rutas import RutaSalida
from backend.utils.errores import RecursoDuplicado, ReglaDeNegocio
from config import settings

CAMPOS_CALCULADOS = ("distancia_total_km", "tiempo_estimado_total_min",
                     "numero_paradas", "velocidad_efectiva_kmh",
                     "paradas", "vehiculo_asignado_id")


# ==========================================================================
# CONSULTA
# ==========================================================================
def listar(bd: Database, *, saltar: int = 0, limite: int = 50,
           busqueda: str | None = None, zona: str | None = None,
           sin_vehiculo: bool | None = None, incluir_inactivos: bool = False
           ) -> tuple[list[dict[str, Any]], int]:
    repositorio = RepositorioRutas(bd)
    filtro: dict[str, Any] = {}

    if busqueda:
        texto = busqueda.strip()
        filtro["$or"] = [
            {"nombre": {"$regex": texto, "$options": "i"}},
            {"codigo_ruta": {"$regex": texto, "$options": "i"}},
        ]
    if zona:
        zona = zona.strip().upper()
        if zona not in settings.CATALOGO_ZONA:
            raise ReglaDeNegocio(
                f"Zona '{zona}' no pertenece al catálogo "
                f"{list(settings.CATALOGO_ZONA)}.")
        filtro["zona"] = zona
    if sin_vehiculo is not None:
        filtro["vehiculo_asignado_id"] = None if sin_vehiculo else {"$ne": None}

    documentos = repositorio.listar(
        filtro, saltar=saltar, limite=limite,
        orden=[("codigo_ruta", 1)], incluir_inactivos=incluir_inactivos)
    total = repositorio.contar(filtro, incluir_inactivos=incluir_inactivos)
    return [_publico(d) for d in documentos], total


def obtener(bd: Database, identificador: str) -> dict[str, Any]:
    return _publico(
        RepositorioRutas(bd).obtener(identificador, incluir_inactivos=True))


def resumen(bd: Database) -> dict[str, Any]:
    repositorio = RepositorioRutas(bd)
    total = repositorio.contar(incluir_inactivos=True)
    activas = repositorio.contar()
    sin_vehiculo = repositorio.contar({"vehiculo_asignado_id": None})
    return {
        "total": total,
        "activas": activas,
        "inactivas": total - activas,
        "por_zona": {zona: repositorio.contar({"zona": zona})
                     for zona in settings.CATALOGO_ZONA},
        "sin_vehiculo_asignado": sin_vehiculo,
        "alerta": (f"{sin_vehiculo} ruta(s) activa(s) no tienen vehículo "
                   "asignado y no podrían ejecutarse."
                   if sin_vehiculo else
                   "Todas las rutas activas tienen vehículo asignado."),
    }


def analisis(bd: Database, identificador: str) -> dict[str, Any]:
    """
    Análisis de la ruta: perfil operativo del ETL y grupo del clustering.

    Conecta el catálogo con lo que el proyecto extrajo de los datos. No
    recalcula: lee `dim_ruta` y `clusters_rutas`, que son las mismas
    cifras del dashboard y del reporte de K-Means.
    """
    repositorio = RepositorioRutas(bd)
    ruta = repositorio.obtener(identificador, incluir_inactivos=True)

    perfil = repositorio.perfil_del_dw(ruta["_id"]) or {}
    perfil.pop("_id", None)
    grupo = repositorio.cluster(ruta["_id"]) or {}
    grupo.pop("_id", None)
    promedio = repositorio.promedio_retraso_flotilla()

    return {
        "ruta": {
            "id": str(ruta["_id"]),
            "codigo_ruta": ruta.get("codigo_ruta"),
            "nombre": ruta.get("nombre"),
            "zona": ruta.get("zona"),
            "numero_paradas": ruta.get("numero_paradas"),
            "distancia_total_km": ruta.get("distancia_total_km"),
        },
        "perfil_operativo": perfil,
        "promedio_retraso_flotilla": promedio,
        "grupo": grupo,
        "origen": ("dim_ruta y clusters_rutas" if perfil or grupo
                   else "no disponible: ejecuta el ETL y el clustering"),
        "lectura": _interpretar_analisis(ruta, perfil, grupo, promedio),
        "recomendacion": grupo.get("recomendacion"),
    }


# ==========================================================================
# ALTA
# ==========================================================================
def crear(bd: Database, datos: dict[str, Any]) -> dict[str, Any]:
    repositorio = RepositorioRutas(bd)
    paradas = _preparar_paradas(repositorio, datos["paradas"])

    documento = {
        **datos,
        "paradas": paradas,
        **_totales(paradas),                                # RN-R2
        "codigo_ruta": repositorio.siguiente_codigo(),      # RN-R1
        "vehiculo_asignado_id": None,
    }
    try:
        creada = repositorio.crear(documento)
    except DuplicateKeyError as exc:
        raise RecursoDuplicado(
            "El código de ruta ya existe. Vuelve a intentarlo.") from exc
    return _publico(creada)


# ==========================================================================
# EDICIÓN DE LA CABECERA
# ==========================================================================
def actualizar(bd: Database, identificador: str,
               cambios: dict[str, Any]) -> dict[str, Any]:
    if "codigo_ruta" in cambios:
        raise ReglaDeNegocio(
            "El código de ruta no se puede cambiar (RN-R1): aparece en los "
            "viajes y en el análisis histórico.", regla="R1")
    prohibidos = [c for c in cambios if c in CAMPOS_CALCULADOS]
    if prohibidos:
        raise ReglaDeNegocio(
            f"Estos campos no se editan desde aquí (RN-R2): "
            f"{', '.join(prohibidos)}. Las paradas tienen sus propios "
            "endpoints y los totales se recalculan a partir de ellas; el "
            "vehículo se asigna con /asignar-vehiculo.",
            regla="R2")
    if not cambios:
        raise ReglaDeNegocio("No se envió ningún campo que actualizar.")

    return _publico(RepositorioRutas(bd).actualizar(identificador, cambios,
                                                    incluir_inactivos=True))


# ==========================================================================
# PARADAS  (§12.3)
# ==========================================================================
def agregar_parada(bd: Database, identificador: str,
                   parada: dict[str, Any]) -> dict[str, Any]:
    """Añade una parada al final del itinerario y recalcula los totales."""
    repositorio = RepositorioRutas(bd)
    ruta = repositorio.obtener(identificador, incluir_inactivos=True)

    actuales = [_parada_entrada(p) for p in ruta.get("paradas", [])]
    return _guardar_paradas(repositorio, identificador, actuales + [parada])


def reemplazar_paradas(bd: Database, identificador: str,
                       paradas: list[dict[str, Any]]) -> dict[str, Any]:
    """Sustituye el itinerario completo y recalcula los totales."""
    repositorio = RepositorioRutas(bd)
    repositorio.obtener(identificador, incluir_inactivos=True)
    return _guardar_paradas(repositorio, identificador, paradas)


def quitar_parada(bd: Database, identificador: str, orden: int) -> dict[str, Any]:
    """
    Elimina una parada y RENUMERA el resto (RN-R3).

    Sin renumerar quedaría un hueco en el orden, y el orden es lo que
    describe el recorrido y sostiene el análisis de acumulación de retraso.
    """
    repositorio = RepositorioRutas(bd)
    ruta = repositorio.obtener(identificador, incluir_inactivos=True)
    actuales = ruta.get("paradas", [])

    if not any(p["orden"] == orden for p in actuales):
        raise ReglaDeNegocio(
            f"La ruta no tiene ninguna parada con orden {orden}. "
            f"Tiene {len(actuales)} parada(s).")
    if len(actuales) == 1:
        raise ReglaDeNegocio(
            "Una ruta necesita al menos una parada (RN-R3). Si ya no se "
            "opera, da de baja la ruta.", regla="R3")

    restantes = [_parada_entrada(p) for p in actuales if p["orden"] != orden]
    return _guardar_paradas(repositorio, identificador, restantes)


def _guardar_paradas(repositorio: RepositorioRutas, identificador: str,
                     paradas: list[dict[str, Any]]) -> dict[str, Any]:
    preparadas = _preparar_paradas(repositorio, paradas)
    cambios = {"paradas": preparadas, **_totales(preparadas)}
    return _publico(repositorio.actualizar(identificador, cambios,
                                           incluir_inactivos=True))


# ==========================================================================
# VEHÍCULO  (§12.3, RN-04)
# ==========================================================================
def asignar_vehiculo(bd: Database, identificador: str,
                     vehiculo_id: str | None) -> dict[str, Any]:
    """
    Asigna o quita el vehículo de la ruta.

    DELEGA en el servicio de vehículos, que ya implementa RN-04 y
    sincroniza los dos extremos de la relación. Reimplementarlo aquí daría
    dos versiones de la misma regla, y bastaría que una cambiara para que
    la ruta y el vehículo dejaran de coincidir.
    """
    from backend.services import vehiculos as servicio_vehiculos

    repositorio = RepositorioRutas(bd)
    ruta = repositorio.obtener(identificador, incluir_inactivos=True)
    asignado = ruta.get("vehiculo_asignado_id")

    if vehiculo_id is None:
        if asignado is None:
            raise ReglaDeNegocio("La ruta no tiene ningún vehículo asignado.")
        servicio_vehiculos.asignar_ruta(bd, str(asignado), None)
        return _publico(repositorio.obtener(identificador, incluir_inactivos=True))

    objeto_vehiculo = repositorio.a_object_id(vehiculo_id)
    if repositorio.vehiculo(objeto_vehiculo) is None:
        raise ReglaDeNegocio(
            f"No existe el vehículo con identificador '{vehiculo_id}'.")

    # El servicio de vehículos aplica RN-04 y escribe ambos extremos.
    servicio_vehiculos.asignar_ruta(bd, vehiculo_id, identificador)
    return _publico(repositorio.obtener(identificador, incluir_inactivos=True))


# ==========================================================================
# BAJA Y REACTIVACIÓN
# ==========================================================================
def desactivar(bd: Database, identificador: str) -> dict[str, Any]:
    """Baja lógica, con las dos comprobaciones de RN-R6."""
    repositorio = RepositorioRutas(bd)
    ruta = repositorio.obtener(identificador, incluir_inactivos=True)

    if not ruta.get("activo", True):
        raise ReglaDeNegocio(
            f"La ruta '{ruta['codigo_ruta']}' ya estaba dada de baja.")

    if ruta.get("vehiculo_asignado_id"):
        vehiculo = repositorio.vehiculo(ruta["vehiculo_asignado_id"])
        codigo = vehiculo.get("codigo_vehiculo") if vehiculo else "?"
        raise ReglaDeNegocio(
            f"No se puede dar de baja la ruta '{ruta['codigo_ruta']}' "
            f"(RN-R6): la cubre el vehículo {codigo}, que quedaría "
            "apuntando a una ruta inactiva. Desasígnalo primero.",
            regla="R6",
            detalles=[{"vehiculo_asignado": codigo}])

    en_curso = repositorio.viajes_en_curso(ruta["_id"])
    if en_curso:
        raise ReglaDeNegocio(
            f"No se puede dar de baja la ruta '{ruta['codigo_ruta']}' "
            f"(RN-R6): tiene {en_curso} viaje(s) sin cerrar.",
            regla="R6",
            detalles=[{"viajes_en_curso": en_curso}])

    return _publico(repositorio.baja_logica(identificador))


def reactivar(bd: Database, identificador: str) -> dict[str, Any]:
    repositorio = RepositorioRutas(bd)
    ruta = repositorio.obtener(identificador, incluir_inactivos=True)
    if ruta.get("activo", True):
        raise ReglaDeNegocio(f"La ruta '{ruta['codigo_ruta']}' ya está activa.")
    return _publico(repositorio.actualizar(identificador, {"activo": True},
                                           incluir_inactivos=True))


# ==========================================================================
# INTERNO
# ==========================================================================
def _parada_entrada(parada: dict[str, Any]) -> dict[str, Any]:
    """Convierte una parada almacenada al formato de entrada."""
    return {
        "cliente_id": str(parada["cliente_id"]),
        "direccion_alias": parada.get("direccion_alias", ""),
        "distancia_desde_anterior_km": parada["distancia_desde_anterior_km"],
        "tiempo_estimado_min": parada["tiempo_estimado_min"],
    }


def _preparar_paradas(repositorio: RepositorioRutas,
                      paradas: list[Any]) -> list[dict[str, Any]]:
    """
    Valida y numera las paradas (RN-R3, RN-R4 y RN-R5).

    Devuelve la lista lista para guardar, con `orden` asignado por posición
    y el `cliente_id` como ObjectId.
    """
    lista = [p.model_dump() if hasattr(p, "model_dump") else dict(p)
             for p in paradas]
    if not lista:
        raise ReglaDeNegocio(
            "Una ruta necesita al menos una parada (RN-R3).", regla="R3")

    identificadores = [repositorio.a_object_id(p["cliente_id"]) for p in lista]

    # RN-R5 — sin clientes repetidos en la misma ruta
    if len(set(identificadores)) != len(identificadores):
        raise ReglaDeNegocio(
            "Hay un cliente repetido en las paradas de la ruta (RN-R5). "
            "Visitar dos veces al mismo cliente en un recorrido suele ser un "
            "error de captura.",
            regla="R5")

    # RN-R4 — el cliente existe, está activo y tiene esa dirección
    clientes = repositorio.clientes_por_id(identificadores)
    preparadas: list[dict[str, Any]] = []

    for posicion, (parada, cliente_id) in enumerate(zip(lista, identificadores),
                                                    start=1):
        cliente = clientes.get(cliente_id)
        if cliente is None:
            raise ReglaDeNegocio(
                f"La parada {posicion} apunta a un cliente que no existe "
                f"('{parada['cliente_id']}') (RN-R4).", regla="R4")
        if not cliente.get("activo", True):
            raise ReglaDeNegocio(
                f"La parada {posicion} apunta al cliente "
                f"{cliente.get('codigo_cliente')}, que está dado de baja "
                "(RN-R4).", regla="R4")

        alias_disponibles = [d.get("alias")
                             for d in cliente.get("direcciones", [])]
        if parada["direccion_alias"] not in alias_disponibles:
            raise ReglaDeNegocio(
                f"El cliente {cliente.get('codigo_cliente')} no tiene una "
                f"dirección con alias '{parada['direccion_alias']}' (RN-R4). "
                f"Tiene: {alias_disponibles}.",
                regla="R4",
                detalles=[{"alias_disponibles": alias_disponibles}])

        preparadas.append({
            "orden": posicion,                       # RN-R3: lo pone el sistema
            "cliente_id": cliente_id,
            "direccion_alias": parada["direccion_alias"],
            "distancia_desde_anterior_km": round(
                float(parada["distancia_desde_anterior_km"]), 2),
            "tiempo_estimado_min": round(float(parada["tiempo_estimado_min"]), 1),
        })
    return preparadas


def _totales(paradas: list[dict[str, Any]]) -> dict[str, Any]:
    """
    RN-R2: los totales se derivan de las paradas, siempre.

    `velocidad_efectiva_kmh` incluye el tiempo de entrega además del
    traslado, así que es menor que la velocidad de circulación. Es la cifra
    que usa el clustering, y describe el ritmo real de la ruta.
    """
    distancia = round(sum(p["distancia_desde_anterior_km"] for p in paradas), 1)
    tiempo = round(sum(p["tiempo_estimado_min"] for p in paradas), 1)
    return {
        "numero_paradas": len(paradas),
        "distancia_total_km": distancia,
        "tiempo_estimado_total_min": tiempo,
        "velocidad_efectiva_kmh": (round(distancia / (tiempo / 60), 1)
                                   if tiempo else None),
    }


def _publico(documento: dict[str, Any]) -> dict[str, Any]:
    return RutaSalida.desde_documento(documento).model_dump()


def _interpretar_analisis(ruta: dict[str, Any], perfil: dict[str, Any],
                          grupo: dict[str, Any],
                          promedio: float | None) -> str:
    """Lectura en lenguaje natural del análisis de la ruta (RF-29)."""
    codigo = ruta.get("codigo_ruta")
    if not perfil:
        return (f"Todavía no hay análisis para {codigo}. Se obtiene al "
                "ejecutar el ETL y el clustering sobre sus entregas.")

    retraso = perfil.get("retraso_medio_min")
    pct = perfil.get("pct_entregas_retrasadas")
    texto = (f"{codigo} promedia {retraso:.1f} minutos de retraso en "
             f"{int(perfil.get('entregas', 0)):,} entregas")
    if pct is not None:
        texto += f", con un {pct:.1f}% de entregas retrasadas"

    if promedio is not None and retraso is not None:
        diferencia = retraso - promedio
        if abs(diferencia) < 1:
            texto += f". Está en la media de la flotilla ({promedio:.1f} min)"
        elif diferencia > 0:
            texto += (f", {diferencia:.1f} minutos por encima de la media de "
                      f"la flotilla ({promedio:.1f} min)")
        else:
            texto += (f", {abs(diferencia):.1f} minutos por debajo de la "
                      f"media ({promedio:.1f} min)")

    if grupo.get("nombre_grupo"):
        texto += (f". El clustering la clasifica como "
                  f"{grupo['nombre_grupo']}")
    return texto + "."
