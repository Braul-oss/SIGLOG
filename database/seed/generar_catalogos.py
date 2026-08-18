"""
SIG-LOG — Sistema Integral de Gestión Logística
database/seed/generar_catalogos.py

ACTIVIDAD PA-1 — Generador de catálogos maestros (DATOS SIMULADOS)

Genera y carga en MongoDB Atlas las cuatro colecciones de catálogo:
    clientes · vehiculos · operadores · rutas

Y establece la relación 1:1 vehículo ↔ ruta exigida por RN-04.

NO genera viajes, entregas, incidentes, combustible ni mantenimientos:
eso corresponde a PA-2 y PA-3.

Uso
---
    python -m database.seed.generar_catalogos --dry-run   # genera y valida, sin escribir
    python -m database.seed.generar_catalogos             # genera e inserta
    python -m database.seed.generar_catalogos --limpiar   # borra los catálogos y regenera
    python -m database.seed.generar_catalogos --semilla 7 # otra semilla
"""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from bson import ObjectId

from config import settings
from config.mongo_conexion import cerrar_cliente, obtener_bd, verificar_conexion
from database.seed import comun as C
from database.seed import parametros as P

# Índice inverso municipio → zona, para saber a qué zona pertenece un cliente
ZONA_DE_MUNICIPIO: dict[str, str] = {
    municipio: zona
    for zona, municipios in P.MUNICIPIOS_POR_ZONA.items()
    for municipio in municipios
}


# ==========================================================================
# CLIENTES
# ==========================================================================
def _nombres_comerciales(rng: random.Random, cantidad: int) -> list[str]:
    """Nombres comerciales sintéticos y distintos entre sí."""
    combinaciones = [
        f"{giro} {apelativo}"
        for giro in P.GIROS_COMERCIALES
        for apelativo in P.APELATIVOS_COMERCIALES
    ]
    rng.shuffle(combinaciones)
    if cantidad > len(combinaciones):
        raise ValueError("Vocabulario insuficiente para generar nombres únicos.")
    return [
        f"{base} {rng.choice(P.SUFIJOS_SOCIETARIOS)}".strip()
        for base in combinaciones[:cantidad]
    ]


def _direccion(rng: random.Random, municipio: str, alias: str, principal: bool) -> dict[str, Any]:
    """
    Dirección embebida (§11.1). Sin `ubicacion` GeoJSON: decisión D-4,
    el proyecto no utiliza coordenadas GPS.
    """
    return {
        "alias": alias,
        "calle": rng.choice(P.CALLES),
        "numero": str(rng.randint(1, 480)),
        "colonia": rng.choice(P.COLONIAS),
        "municipio": municipio,
        "estado": P.ESTADO,
        "cp": f"5{rng.randint(0, 2)}{rng.randint(100, 999)}",
        "referencias": rng.choice(
            ["Portón azul", "Frente a la plaza", "Junto a la gasolinera",
             "Local en esquina", "Bodega al fondo", ""]
        ),
        "principal": principal,
    }


def generar_clientes(rng: random.Random) -> list[dict[str, Any]]:
    """100 clientes distribuidos equitativamente entre las 4 zonas."""
    nombres = _nombres_comerciales(rng, P.NUM_CLIENTES)
    por_zona = P.NUM_CLIENTES // len(P.ZONAS)
    clientes: list[dict[str, Any]] = []

    consecutivo = 0
    for zona in P.ZONAS:
        municipios = P.MUNICIPIOS_POR_ZONA[zona]
        for _ in range(por_zona):
            consecutivo += 1
            municipio = rng.choice(municipios)
            direcciones = [_direccion(rng, municipio, "Matriz", True)]
            if rng.random() < P.PROBABILIDAD_SEGUNDA_DIRECCION:
                direcciones.append(
                    _direccion(rng, rng.choice(municipios), "Sucursal", False)
                )

            clientes.append({
                "_id": ObjectId(),
                "codigo_cliente": C.codigo("CLI", consecutivo),
                "nombre": nombres[consecutivo - 1],
                # RNP-07 pendiente de aprobación (ver parametros.py, B.7)
                "tipo_cliente": C.elegir_ponderado(rng, P.CATALOGO_TIPO_CLIENTE),
                "telefono": f"722{rng.randint(1000000, 9999999)}",
                "email": f"contacto{consecutivo:03d}@ejemplo-simulado.mx",
                "direcciones": direcciones,
                # `ventana_horaria` se omite: depende de RNP-13, aún pendiente.
                "total_entregas": 0,
                **C.campos_comunes(),
            })
    return clientes


# ==========================================================================
# VEHÍCULOS
# ==========================================================================
def _placa(rng: random.Random, usadas: set[str]) -> str:
    letras = "ABCDEFGHJKLMNPRSTUVWXYZ"
    while True:
        placa = (
            "".join(rng.choice(letras) for _ in range(3))
            + "-"
            + f"{rng.randint(100, 999)}"
        )
        if placa not in usadas:
            usadas.add(placa)
            return placa


def generar_vehiculos(rng: random.Random) -> list[dict[str, Any]]:
    """20 vehículos repartidos en 3 tipos (8 ligeros, 7 medianos, 5 pesados)."""
    tipos: list[str] = []
    for tipo, cantidad in P.DISTRIBUCION_TIPOS_VEHICULO.items():
        tipos.extend([tipo] * cantidad)
    if len(tipos) != P.NUM_VEHICULOS:
        raise ValueError("DISTRIBUCION_TIPOS_VEHICULO no suma NUM_VEHICULOS.")
    rng.shuffle(tipos)

    usadas: set[str] = set()
    vehiculos: list[dict[str, Any]] = []

    for i, tipo in enumerate(tipos, start=1):
        marca, modelo = rng.choice(P.MARCAS_POR_TIPO[tipo])
        anio = rng.randint(P.ANIO_MIN_VEHICULO, P.ANIO_MAX_VEHICULO)
        antiguedad = max(P.FECHA_INICIO.year - anio, 0)
        odometro = round(antiguedad * rng.uniform(*P.KM_POR_ANIO), 0)
        rend_min, rend_max = P.RENDIMIENTO_NOMINAL_KM_L[tipo]

        vehiculos.append({
            "_id": ObjectId(),
            "codigo_vehiculo": C.codigo("VEH", i),
            "placa": _placa(rng, usadas),
            "marca": marca,
            "modelo": modelo,
            "anio": anio,
            "tipo_vehiculo": tipo,
            # `capacidad_carga_kg` se omite: DATO PENDIENTE DE DEFINICIÓN (§11.2).
            # No está en el Anexo B y ningún modelo ni gráfica lo utiliza.
            "capacidad_tanque_litros": P.CAPACIDAD_TANQUE_L[tipo],
            "rendimiento_nominal_km_l": round(rng.uniform(rend_min, rend_max), 2),
            "odometro_actual_km": odometro,
            "estado_operativo": "DISPONIBLE",
            "ruta_asignada_id": None,          # se asigna al crear las rutas (RN-04)
            "fecha_ultimo_mantenimiento": None,  # derivado: lo llena PA-3
            "fecha_proximo_mantenimiento": None,
            "rendimiento_real_km_l": None,       # derivado: lo calcula el ETL
            "tipo_combustible": "DIESEL" if tipo != "LIGERO" else "GASOLINA",
            **C.campos_comunes(),
        })
    return vehiculos


# ==========================================================================
# OPERADORES
# ==========================================================================
def generar_operadores(rng: random.Random) -> list[dict[str, Any]]:
    """24 operadores: 20 titulares + 4 de relevo. Rotan (RNP-03 opción b)."""
    usados: set[str] = set()
    operadores: list[dict[str, Any]] = []

    for i in range(1, P.NUM_OPERADORES + 1):
        while True:
            nombre = (
                f"{rng.choice(P.NOMBRES_PILA)} "
                f"{rng.choice(P.APELLIDOS)} {rng.choice(P.APELLIDOS)}"
            )
            if nombre not in usados:
                usados.add(nombre)
                break

        operadores.append({
            "_id": ObjectId(),
            "codigo_operador": C.codigo("OPE", i),
            "nombre_completo": nombre,
            "licencia": {
                "numero": f"LF{rng.randint(1000000, 9999999)}",
                "tipo": rng.choice(P.TIPOS_LICENCIA),
                "vigencia": C.fecha_aleatoria(rng, *P.VIGENCIA_LICENCIA_ANIOS),
            },
            "fecha_ingreso": C.fecha_aleatoria(rng, *P.ANIO_INGRESO_OPERADOR),
            "estado": "ACTIVO",
            # RNP-03 opción (b): los operadores rotan ⇒ sin asignación fija.
            "vehiculo_asignado_id": None,
            "total_entregas": 0,
            "porcentaje_entregas_a_tiempo": None,  # derivado: lo calcula el ETL
            **C.campos_comunes(),
        })
    return operadores


# ==========================================================================
# RUTAS
# ==========================================================================
def _distancias_de_ruta(rng: random.Random, n_paradas: int) -> list[float]:
    """
    Distancias por tramo que respetan a la vez los dos rangos del Anexo B:
    cada tramo en [3, 25] km y el total de la ruta en [25, 120] km.
    """
    d_min, d_max = P.DISTANCIA_ENTRE_PARADAS_KM
    t_min, t_max = P.DISTANCIA_TOTAL_RUTA_KM

    for _ in range(300):
        tramos = [round(rng.uniform(d_min, d_max), 1) for _ in range(n_paradas)]
        if t_min <= sum(tramos) <= t_max:
            return tramos

    # Respaldo determinista: escalar al centro del rango permitido y recortar
    objetivo = min(max(t_min, n_paradas * (d_min + d_max) / 2), t_max)
    tramos = [rng.uniform(d_min, d_max) for _ in range(n_paradas)]
    factor = objetivo / sum(tramos)
    return [round(min(max(t * factor, d_min), d_max), 1) for t in tramos]


def generar_rutas(
    rng: random.Random,
    clientes: list[dict[str, Any]],
    vehiculos: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    20 rutas (5 por zona). Cada cliente aparece como parada de exactamente
    una ruta, y cada ruta recibe exactamente un vehículo (RN-04).
    """
    rutas_por_zona = P.NUM_RUTAS // len(P.ZONAS)
    rutas: list[dict[str, Any]] = []
    consecutivo = 0

    for zona in P.ZONAS:
        de_la_zona = [
            c for c in clientes
            if ZONA_DE_MUNICIPIO[c["direcciones"][0]["municipio"]] == zona
        ]
        rng.shuffle(de_la_zona)
        tamanos = C.repartir(
            rng, len(de_la_zona), rutas_por_zona,
            P.PARADAS_POR_RUTA_MIN, P.PARADAS_POR_RUTA_MAX,
        )

        cursor = 0
        for n_paradas in tamanos:
            consecutivo += 1
            seleccion = de_la_zona[cursor:cursor + n_paradas]
            cursor += n_paradas

            velocidad = rng.uniform(*P.VELOCIDAD_EFECTIVA_KMH)
            distancias = _distancias_de_ruta(rng, n_paradas)

            paradas: list[dict[str, Any]] = []
            for orden, (cliente, distancia) in enumerate(zip(seleccion, distancias), start=1):
                servicio = rng.randint(*P.TIEMPO_SERVICIO_PARADA_MIN)
                traslado = distancia / velocidad * 60
                paradas.append({
                    "orden": orden,
                    "cliente_id": cliente["_id"],
                    "direccion_alias": cliente["direcciones"][0]["alias"],
                    "distancia_desde_anterior_km": distancia,
                    "tiempo_estimado_min": round(traslado + servicio, 1),
                    # `ventana_horaria` se omite: depende de RNP-13, pendiente.
                })

            rutas.append({
                "_id": ObjectId(),
                "codigo_ruta": C.codigo("RUT", consecutivo),
                "nombre": f"Zona {zona.title()} {consecutivo:02d}",
                "zona": zona,
                "origen": dict(P.CENTRO_DISTRIBUCION),
                "paradas": paradas,
                "distancia_total_km": round(sum(distancias), 1),
                "tiempo_estimado_total_min": round(
                    sum(p["tiempo_estimado_min"] for p in paradas), 1
                ),
                "numero_paradas": n_paradas,
                "velocidad_efectiva_kmh": round(velocidad, 1),
                "dias_operacion": list(P.DIAS_OPERACION_NOMBRES),
                "hora_salida_programada": C.hora_aleatoria(
                    rng, *P.HORA_SALIDA_PROGRAMADA, P.PASO_MINUTOS_SALIDA
                ),
                "vehiculo_asignado_id": None,   # se resuelve en asignar_vehiculos()
                **C.campos_comunes(),
            })

    asignar_vehiculos(rutas, vehiculos)
    return rutas


def asignar_vehiculos(
    rutas: list[dict[str, Any]],
    vehiculos: list[dict[str, Any]],
) -> None:
    """
    Aplica RN-04: relación 1:1 entre vehículo y ruta.

    El emparejamiento no es aleatorio: las rutas más largas reciben los
    vehículos pesados y las más cortas los ligeros. Es una decisión de
    simulación deliberada (§16.3, regla 5: la simulación debe incorporar
    relaciones realistas). Sin ella, `consumo` y `costo` serían ruido puro
    y el clustering de rutas del Caso 3 no encontraría estructura.
    """
    prioridad = {"PESADO": 0, "MEDIANO": 1, "LIGERO": 2}
    rutas_ordenadas = sorted(rutas, key=lambda r: -r["distancia_total_km"])
    vehiculos_ordenados = sorted(vehiculos, key=lambda v: prioridad[v["tipo_vehiculo"]])

    for ruta, vehiculo in zip(rutas_ordenadas, vehiculos_ordenados):
        ruta["vehiculo_asignado_id"] = vehiculo["_id"]
        vehiculo["ruta_asignada_id"] = ruta["_id"]


# ==========================================================================
# VALIDACIONES DE COHERENCIA
# ==========================================================================
def validar(clientes, vehiculos, operadores, rutas) -> list[tuple[str, bool, str]]:
    """Comprobaciones que deben pasar antes de escribir en Atlas."""
    ids_clientes = {c["_id"] for c in clientes}
    en_rutas = [p["cliente_id"] for r in rutas for p in r["paradas"]]

    todas = clientes + vehiculos + operadores + rutas
    veh_de_ruta = [r["vehiculo_asignado_id"] for r in rutas]
    ruta_de_veh = [v["ruta_asignada_id"] for v in vehiculos]

    pruebas: list[tuple[str, bool, str]] = [
        ("Conteo de clientes", len(clientes) == P.NUM_CLIENTES, f"{len(clientes)}/{P.NUM_CLIENTES}"),
        ("Conteo de vehículos", len(vehiculos) == P.NUM_VEHICULOS, f"{len(vehiculos)}/{P.NUM_VEHICULOS}"),
        ("Conteo de operadores", len(operadores) == P.NUM_OPERADORES, f"{len(operadores)}/{P.NUM_OPERADORES}"),
        ("Conteo de rutas", len(rutas) == P.NUM_RUTAS, f"{len(rutas)}/{P.NUM_RUTAS}"),
        ("Códigos de cliente únicos",
         len({c["codigo_cliente"] for c in clientes}) == len(clientes), ""),
        ("Placas únicas",
         len({v["placa"] for v in vehiculos}) == len(vehiculos), ""),
        ("Códigos de operador únicos",
         len({o["codigo_operador"] for o in operadores}) == len(operadores), ""),
        ("Códigos de ruta únicos",
         len({r["codigo_ruta"] for r in rutas}) == len(rutas), ""),
        ("RN-04: cada ruta tiene un vehículo distinto",
         len(set(veh_de_ruta)) == len(rutas) and None not in veh_de_ruta, ""),
        ("RN-04: cada vehículo tiene una ruta distinta",
         len(set(ruta_de_veh)) == len(vehiculos) and None not in ruta_de_veh, ""),
        ("Todo cliente es parada de alguna ruta",
         set(en_rutas) == ids_clientes, f"{len(set(en_rutas))}/{len(ids_clientes)}"),
        ("Ningún cliente se repite entre rutas",
         len(en_rutas) == len(set(en_rutas)), f"{len(en_rutas)} paradas"),
        ("Paradas por ruta dentro de [3, 8]",
         all(P.PARADAS_POR_RUTA_MIN <= r["numero_paradas"] <= P.PARADAS_POR_RUTA_MAX for r in rutas), ""),
        ("Distancia total de ruta dentro de [25, 120] km",
         all(P.DISTANCIA_TOTAL_RUTA_KM[0] <= r["distancia_total_km"] <= P.DISTANCIA_TOTAL_RUTA_KM[1]
             for r in rutas), ""),
        ("Distancia por tramo dentro de [3, 25] km",
         all(P.DISTANCIA_ENTRE_PARADAS_KM[0] <= p["distancia_desde_anterior_km"] <= P.DISTANCIA_ENTRE_PARADAS_KM[1]
             for r in rutas for p in r["paradas"]), ""),
        ("100% de documentos marcados como SIMULADO",
         all(d["origen_dato"] == "SIMULADO" for d in todas), f"{len(todas)} documentos"),
    ]
    return [(nombre, bool(ok), detalle) for nombre, ok, detalle in pruebas]


# ==========================================================================
# RESUMEN
# ==========================================================================
def imprimir_resumen(clientes, vehiculos, operadores, rutas) -> None:
    C.encabezado("RESUMEN DE LOS CATÁLOGOS GENERADOS")

    print(f"  Clientes ....... {len(clientes)}")
    for tipo in P.CATALOGO_TIPO_CLIENTE:
        n = sum(1 for c in clientes if c["tipo_cliente"] == tipo)
        print(f"      {tipo:<16}{n}")

    print(f"\n  Vehículos ...... {len(vehiculos)}")
    for tipo in P.TIPOS_VEHICULO:
        del_tipo = [v for v in vehiculos if v["tipo_vehiculo"] == tipo]
        rend = sum(v["rendimiento_nominal_km_l"] for v in del_tipo) / len(del_tipo)
        print(f"      {tipo:<16}{len(del_tipo):<4} rendimiento nominal medio: {rend:.2f} km/l")

    print(f"\n  Operadores ..... {len(operadores)}")
    print(f"\n  Rutas .......... {len(rutas)}")
    distancias = [r["distancia_total_km"] for r in rutas]
    tiempos = [r["tiempo_estimado_total_min"] for r in rutas]
    paradas = [r["numero_paradas"] for r in rutas]
    print(f"      Distancia total  min {min(distancias):.1f} · "
          f"media {sum(distancias)/len(distancias):.1f} · max {max(distancias):.1f} km")
    print(f"      Tiempo estimado  min {min(tiempos):.1f} · "
          f"media {sum(tiempos)/len(tiempos):.1f} · max {max(tiempos):.1f} min")
    print(f"      Paradas          min {min(paradas)} · "
          f"media {sum(paradas)/len(paradas):.1f} · max {max(paradas)}")
    print(f"      Paradas totales  {sum(paradas)}")
    for zona in P.ZONAS:
        n = sum(1 for r in rutas if r["zona"] == zona)
        print(f"      Zona {zona:<10}{n} rutas")


def imprimir_validaciones(resultados) -> bool:
    C.encabezado("VALIDACIONES DE COHERENCIA")
    for nombre, ok, detalle in resultados:
        marca = "[OK]   " if ok else "[FALLA]"
        print(f"  {marca} {nombre:<48}{detalle}")
    fallos = sum(1 for _, ok, _ in resultados if not ok)
    print(C.SUBLINEA)
    print(f"  {len(resultados) - fallos}/{len(resultados)} validaciones correctas")
    return fallos == 0


# ==========================================================================
# CARGA A MONGODB
# ==========================================================================
def cargar(bd, clientes, vehiculos, operadores, rutas, limpiar: bool) -> None:
    conjuntos = {
        "clientes": clientes,
        "vehiculos": vehiculos,
        "operadores": operadores,
        "rutas": rutas,
    }

    if limpiar:
        C.encabezado("LIMPIEZA PREVIA DE CATÁLOGOS")
        for nombre in settings.COLECCIONES_CATALOGO:
            borrados = bd[nombre].delete_many({}).deleted_count
            print(f"  {nombre:<16}{borrados} documentos eliminados")

    C.encabezado("CARGA EN MONGODB ATLAS")
    for nombre, documentos in conjuntos.items():
        existentes = bd[nombre].count_documents({})
        if existentes and not limpiar:
            print(f"  {nombre:<16}OMITIDA — ya contiene {existentes} documentos. "
                  f"Usa --limpiar para regenerar.")
            continue
        resultado = bd[nombre].insert_many(documentos)
        print(f"  {nombre:<16}{len(resultado.inserted_ids)} documentos insertados")


# ==========================================================================
# PUNTO DE ENTRADA
# ==========================================================================
def main() -> int:
    parser = argparse.ArgumentParser(
        description="PA-1 — Genera los catálogos maestros simulados de SIG-LOG.",
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Genera y valida en memoria, sin escribir en Atlas.")
    parser.add_argument("--limpiar", action="store_true",
                        help="Borra clientes, vehiculos, operadores y rutas antes de insertar.")
    parser.add_argument("--semilla", type=int, default=P.SEMILLA,
                        help=f"Semilla de aleatoriedad (por defecto {P.SEMILLA}).")
    args = parser.parse_args()

    C.aviso_datos_simulados()

    rng = C.crear_rng(args.semilla)
    C.encabezado("GENERACIÓN EN MEMORIA")
    clientes = generar_clientes(rng)
    print(f"  clientes ....... {len(clientes)}")
    vehiculos = generar_vehiculos(rng)
    print(f"  vehiculos ...... {len(vehiculos)}")
    operadores = generar_operadores(rng)
    print(f"  operadores ..... {len(operadores)}")
    rutas = generar_rutas(rng, clientes, vehiculos)
    print(f"  rutas .......... {len(rutas)}")

    imprimir_resumen(clientes, vehiculos, operadores, rutas)
    if not imprimir_validaciones(validar(clientes, vehiculos, operadores, rutas)):
        print("\n  Se detectaron fallas de coherencia. No se escribe nada en Atlas.")
        return 1

    if args.dry_run:
        print("\n  --dry-run activo: no se escribió nada en MongoDB.")
        return 0

    if not verificar_conexion(verbose=True)["exito"]:
        return 1

    try:
        cargar(obtener_bd(), clientes, vehiculos, operadores, rutas, args.limpiar)
        print()
        print(C.LINEA)
        print("  PA-1 TERMINADA. Siguiente actividad: PA-2 (viajes y entregas).")
        print(C.LINEA)
        return 0
    finally:
        cerrar_cliente()


if __name__ == "__main__":
    sys.exit(main())
