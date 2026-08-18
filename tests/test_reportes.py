"""
SIG-LOG — Sistema Integral de Gestión Logística
tests/test_reportes.py

PRUEBAS DE LOS INFORMES EN PDF

Un PDF no se puede "leer" desde una prueba como se lee un JSON, pero sí se
puede comprobar lo que de verdad importa:

1. **Que se genere y sea un PDF válido**, con más de una página y con
   imágenes dentro. Un informe de dos kilobytes es un informe vacío.

2. **Que sus cifras sean las mismas del sistema.** Es la comprobación
   central: se extrae el texto del PDF y se busca en él la cifra que
   devuelve el servicio. Si el informe recalculara por su cuenta, aquí se
   vería.

3. **Que lleve la marca de datos simulados en cada página.** Un PDF se
   reenvía e imprime fuera del sistema, donde ya no hay pantalla que avise.

4. **Que el API y la consola construyan el mismo documento**, para que el
   que se descarga y el que se archiva no diverjan.

Ninguna prueba escribe en la base: un informe solo lee.
"""

from __future__ import annotations

import base64
import re
import sys
import zlib
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from fastapi.testclient import TestClient

from backend.main import app
from backend.services import analitica
from config import settings
from config.mongo_conexion import obtener_bd
from reportes import generar as generador

API = settings.API_PREFIJO
CLAVE = "siglog2026"


def cliente_http() -> TestClient:
    return TestClient(app, follow_redirects=False)


def cab(c: TestClient, usuario: str = "admin") -> None:
    respuesta = c.post("/entrar", data={"usuario": usuario,
                                        "contrasena": CLAVE})
    assert respuesta.status_code == 303, respuesta.text[:300]


def paginas(pdf: bytes) -> int:
    return len(re.findall(rb"/Type\s*/Page[^s]", pdf))


def texto(pdf: bytes) -> str:
    """
    Texto plano del PDF, para poder buscar cifras dentro.

    reportlab codifica los flujos en ASCII85 sobre zlib, así que hay que
    deshacer las dos capas antes de encontrar nada. Lo que se recoge son
    las cadenas entre paréntesis, que es lo que el documento dibuja.

    No es un extractor completo —no reconstruye el orden ni los espacios—
    pero basta para comprobar que un número está presente, que es lo único
    que hace falta aquí y no justifica añadir una dependencia al proyecto.
    """
    partes: list[str] = []
    for flujo in re.findall(rb"stream\r?\n(.*?)endstream", pdf, re.S):
        contenido = _descomprimir(flujo.rstrip(b"\r\n"))
        if contenido is None:
            continue
        for cadena in re.findall(rb"\((?:\\.|[^\\()])*\)", contenido):
            partes.append(_texto_pdf(cadena[1:-1]))
    return " ".join(partes)


def _descomprimir(flujo: bytes) -> bytes | None:
    """Deshace ASCII85 y zlib, en ese orden, tolerando que falte alguno."""
    datos = flujo
    if not datos.startswith(b"\x78"):          # no empieza por cabecera zlib
        try:
            datos = base64.a85decode(datos, adobe=False)
        except ValueError:
            try:
                datos = base64.a85decode(datos.rstrip(b"~>"), adobe=False)
            except ValueError:
                return None
    try:
        return zlib.decompress(datos)
    except zlib.error:
        return datos if b"(" in datos else None


def _texto_pdf(crudo: bytes) -> str:
    """
    Deshace los escapes del PDF, incluidos los octales de los acentos.

    Sin esto, «Análisis» aparecería como «An\\341lisis» y una búsqueda de
    texto con acentos no encontraría nada.
    """
    resultado = bytearray()
    i = 0
    while i < len(crudo):
        if crudo[i:i + 1] == b"\\" and i + 1 < len(crudo):
            # Un escape octal lleva de una a tres cifras, y solo de 0 a 7.
            # `\999` no es octal: es un `\9` —que el PDF define como el
            # propio carácter— seguido de dos nueves.
            octal = b""
            while (len(octal) < 3
                   and crudo[i + 1 + len(octal):i + 2 + len(octal)] in
                   (b"0", b"1", b"2", b"3", b"4", b"5", b"6", b"7")):
                octal += crudo[i + 1 + len(octal):i + 2 + len(octal)]
            if octal:
                resultado.append(int(octal, 8) & 0xFF)
                i += 1 + len(octal)
                continue
            resultado += crudo[i + 1:i + 2]
            i += 2
            continue
        resultado += crudo[i:i + 1]
        i += 1
    return resultado.decode("latin-1")


def contiene(contenido: str, frase: str) -> bool:
    """
    Si el documento dice esa frase, sin depender de cómo la partió.

    reportlab reparte un párrafo entre varios operadores de texto, así que
    una frase puede quedar troceada en el flujo. Y las tarjetas de
    indicador escriben el título en mayúsculas. Comparar sin espacios y sin
    distinguir mayúsculas evita perseguir esos dos detalles de formato, que
    no son lo que la prueba quiere comprobar.
    """
    limpiar = lambda s: "".join(s.split()).upper()
    return limpiar(frase) in limpiar(contenido)


def sin_marcas_de_tiempo(contenido: str) -> str:
    """Quita fechas y horas: cada documento lleva la suya de generación."""
    return re.sub(r"\d{2}/\d{2}/\d{4}|\d{2}:\d{2}", "", contenido)


_cache: dict[str, bytes] = {}


def informe(tipo: str) -> bytes:
    """Se genera una sola vez: cada uno tarda segundos por las gráficas."""
    if tipo not in _cache:
        _cache[tipo] = generador.generar(tipo, obtener_bd())
    return _cache[tipo]


# ==========================================================================
# EL DOCUMENTO
# ==========================================================================
def test_los_tres_informes_se_generan():
    for tipo in sorted(generador.INFORMES):
        pdf = informe(tipo)
        assert pdf[:5] == b"%PDF-", f"{tipo}: no es un PDF"
        assert pdf.rstrip()[-5:] == b"%%EOF", f"{tipo}: PDF truncado"
        assert paginas(pdf) >= 2, f"{tipo}: solo {paginas(pdf)} página"
        assert len(pdf) > 5_000, f"{tipo}: {len(pdf)} bytes, está vacío"


def test_los_informes_analiticos_llevan_graficas():
    """
    Un informe de análisis sin gráficas es una tabla larga.

    El operativo queda fuera a propósito: es una lista de lo que hay que
    atender, y una gráfica no ayuda a atender nada.
    """
    for tipo in ("ejecutivo", "flotilla"):
        pdf = informe(tipo)
        imagenes = len(re.findall(rb"/Subtype\s*/Image", pdf))
        assert imagenes >= 2, f"{tipo}: solo {imagenes} imagen"
        assert len(pdf) > 100_000, (
            f"{tipo}: {len(pdf)} bytes; las gráficas no se incrustaron")


def test_cada_informe_dice_de_que_periodo_habla():
    periodo = analitica.periodo(obtener_bd())
    etiqueta = periodo["etiqueta"]
    for tipo in ("ejecutivo", "flotilla"):
        contenido = texto(informe(tipo))
        assert contiene(contenido, etiqueta), (
            f"{tipo}: no dice que analiza «{etiqueta}»")


def test_cada_pagina_lleva_la_marca_de_datos_simulados():
    """
    Los datos del sistema son simulados y el documento tiene que decirlo.

    Va en el pie de **cada** página porque un PDF se imprime, se parte y se
    reenvía: la página que acabe suelta debe seguir diciendo de dónde
    salió.
    """
    for tipo in sorted(generador.INFORMES):
        pdf = informe(tipo)
        marcas = texto(pdf).count("SIMULADOS")
        assert marcas >= paginas(pdf), (
            f"{tipo}: {marcas} marcas para {paginas(pdf)} páginas")


# ==========================================================================
# LAS CIFRAS SON LAS DEL SISTEMA
# ==========================================================================
def test_el_ejecutivo_reproduce_los_indicadores():
    """
    La comprobación central: el informe no recalcula, transcribe.

    Se buscan dentro del PDF los títulos de los diez indicadores y el texto
    del resumen ejecutivo que produce `analytics.kpis`.
    """
    bd = obtener_bd()
    datos = analitica.kpis(bd)
    contenido = texto(informe("ejecutivo"))

    for indicador in datos["indicadores"]:
        assert contiene(contenido, indicador["titulo"]), indicador["clave"]

    # Un fragmento reconocible del resumen, sin depender de la puntuación
    fragmento = datos["resumen_ejecutivo"][:45]
    assert contiene(contenido, fragmento), "falta el resumen ejecutivo"


def test_el_informe_de_flotilla_reproduce_las_cifras_del_servicio():
    bd = obtener_bd()
    datos = analitica.desempeno_vehiculos(bd, "costo", 100)
    contenido = texto(informe("flotilla"))

    # Todas las unidades deben aparecer en el detalle
    for vehiculo in datos["vehiculos"]:
        assert contiene(contenido, vehiculo["codigo_vehiculo"]), (
            vehiculo["codigo_vehiculo"])

    # Y la más cara, con su importe
    peor = datos["vehiculos"][0]
    importe = f"${peor['costo_total']:,.0f}"
    assert contiene(contenido, importe), (
        f"no aparece el costo {importe} de {peor['codigo_vehiculo']}")

    # Los totales de referencia, también
    assert contiene(contenido, f"${datos['totales']['costo_total']:,.0f}")


def test_el_operativo_refleja_las_alertas_vigentes():
    from backend.services import mantenimientos as servicio_mtto
    from backend.services import operadores as servicio_operadores

    bd = obtener_bd()
    mantenimiento = servicio_mtto.pendientes(bd)
    licencias = servicio_operadores.licencias(bd)
    contenido = texto(informe("operativo"))

    for m in mantenimiento["vencidos"]:
        assert contiene(contenido, m["codigo_vehiculo"]), m["folio_mantenimiento"]
    for o in licencias.get("vencidas", []):
        assert contiene(contenido, o["codigo_operador"]), o["codigo_operador"]


def test_el_informe_identifica_los_vehiculos_por_su_codigo():
    """
    En un informe impreso, un identificador interno no le sirve a nadie.
    Cada unidad aparece por su código y su modelo.
    """
    bd = obtener_bd()
    datos = analitica.desempeno_vehiculos(bd, "costo", 5)
    contenido = texto(informe("flotilla"))
    for vehiculo in datos["vehiculos"]:
        assert contiene(contenido, vehiculo["codigo_vehiculo"])
        assert not contiene(contenido, vehiculo["vehiculo_id"]), (
            "el identificador interno no debe aparecer en el documento")


def test_los_grupos_de_rutas_se_explican_en_lenguaje_de_negocio():
    """Nada de «grupo 0»: cada grupo lleva su nombre y su recomendación."""
    from backend.services import ml as servicio_ml

    datos = servicio_ml.clusters_rutas(obtener_bd())
    contenido = texto(informe("ejecutivo"))
    for grupo in datos["grupos"]:
        assert contiene(contenido, grupo["nombre"]), grupo["grupo"]
    assert "no son categorías cerradas" in contenido.lower() or \
           "continuo" in contenido.lower(), (
        "falta la advertencia sobre cómo leer los grupos")


# ==========================================================================
# EL API
# ==========================================================================
def test_el_api_entrega_el_pdf():
    c = cliente_http()
    cab(c)
    for tipo in sorted(generador.INFORMES):
        respuesta = c.get(f"{API}/reportes/{tipo}")
        assert respuesta.status_code == 200, f"{tipo}: {respuesta.status_code}"
        assert respuesta.headers["content-type"] == "application/pdf", tipo
        assert respuesta.content[:5] == b"%PDF-", tipo
        assert tipo in respuesta.headers["content-disposition"], tipo


def test_el_catalogo_declara_que_responde_cada_informe():
    c = cliente_http()
    cab(c)
    respuesta = c.get(f"{API}/reportes")
    assert respuesta.status_code == 200
    datos = respuesta.json()["datos"]
    assert {i["tipo"] for i in datos["informes"]} == set(generador.INFORMES)
    for informe_ in datos["informes"]:
        assert informe_["responde"], informe_["tipo"]
        assert informe_["para"], informe_["tipo"]
        assert informe_["url"].endswith(informe_["tipo"])


def test_un_informe_inexistente_da_404():
    c = cliente_http()
    cab(c)
    respuesta = c.get(f"{API}/reportes/inventado")
    assert respuesta.status_code == 404
    assert "application/json" in respuesta.headers["content-type"]
    assert respuesta.json()["exito"] is False


def test_sin_sesion_no_hay_informes():
    c = cliente_http()
    assert c.get(f"{API}/reportes").status_code == 401
    assert c.get(f"{API}/reportes/ejecutivo").status_code == 401


def test_el_analista_descarga_los_informes():
    """Leer informes es exactamente su trabajo."""
    c = cliente_http()
    cab(c, "analista")
    for tipo in sorted(generador.INFORMES):
        respuesta = c.get(f"{API}/reportes/{tipo}")
        assert respuesta.status_code == 200, tipo


def test_el_api_y_la_consola_construyen_lo_mismo():
    """
    Los dos caminos llaman a `generador.generar()`.

    Si divergieran, el PDF que descarga un usuario dejaría de ser el mismo
    que el que se archiva, y nadie sabría cuál es el bueno. Se comparan por
    número de páginas y por contenido de texto, no byte a byte: cada
    documento lleva su hora de generación y esa sí cambia.
    """
    c = cliente_http()
    cab(c)
    por_api = c.get(f"{API}/reportes/flotilla").content
    por_consola = informe("flotilla")

    assert paginas(por_api) == paginas(por_consola)
    assert (sin_marcas_de_tiempo(texto(por_api))
            == sin_marcas_de_tiempo(texto(por_consola)))


def test_la_interfaz_ofrece_los_informes():
    c = cliente_http()
    cab(c)
    assert f"{API}/reportes/ejecutivo" in c.get("/panel").text
    assert f"{API}/reportes/operativo" in c.get("/panel").text
    assert f"{API}/reportes/flotilla" in c.get("/flotilla").text


if __name__ == "__main__":
    pruebas = [
        ("Los tres informes se generan", test_los_tres_informes_se_generan),
        ("Los informes analíticos llevan gráficas",
         test_los_informes_analiticos_llevan_graficas),
        ("Cada informe dice de qué periodo habla",
         test_cada_informe_dice_de_que_periodo_habla),
        ("Cada página lleva la marca de datos simulados",
         test_cada_pagina_lleva_la_marca_de_datos_simulados),
        ("El ejecutivo reproduce los indicadores",
         test_el_ejecutivo_reproduce_los_indicadores),
        ("El de flotilla reproduce las cifras del servicio",
         test_el_informe_de_flotilla_reproduce_las_cifras_del_servicio),
        ("El operativo refleja las alertas vigentes",
         test_el_operativo_refleja_las_alertas_vigentes),
        ("El informe identifica los vehículos por su código",
         test_el_informe_identifica_los_vehiculos_por_su_codigo),
        ("Los grupos de rutas se explican en lenguaje de negocio",
         test_los_grupos_de_rutas_se_explican_en_lenguaje_de_negocio),
        ("El API entrega el PDF", test_el_api_entrega_el_pdf),
        ("El catálogo declara qué responde cada informe",
         test_el_catalogo_declara_que_responde_cada_informe),
        ("Un informe inexistente da 404", test_un_informe_inexistente_da_404),
        ("Sin sesión no hay informes", test_sin_sesion_no_hay_informes),
        ("El analista descarga los informes",
         test_el_analista_descarga_los_informes),
        ("El API y la consola construyen lo mismo",
         test_el_api_y_la_consola_construyen_lo_mismo),
        ("La interfaz ofrece los informes",
         test_la_interfaz_ofrece_los_informes),
    ]

    print("=" * 70)
    print("  SIG-LOG — Pruebas de los informes en PDF")
    print("=" * 70)

    fallos = 0
    for descripcion, prueba in pruebas:
        try:
            prueba()
            print(f"  [OK]    {descripcion}")
        except AssertionError as exc:
            fallos += 1
            print(f"  [FALLA] {descripcion}\n          {exc}")
        except Exception as exc:                    # noqa: BLE001
            fallos += 1
            print(f"  [ERROR] {descripcion}\n          {type(exc).__name__}: {exc}")

    print("-" * 70)
    print("  Un informe solo lee: no hay escenario que limpiar.")
    print("=" * 70)
    print(f"  Resultado: {len(pruebas) - fallos}/{len(pruebas)} pruebas correctas")
    print("=" * 70)
    sys.exit(1 if fallos else 0)
