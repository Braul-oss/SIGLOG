"""
SIG-LOG — Sistema Integral de Gestión Logística
tests/test_frontend.py

PRUEBAS DE LA INTERFAZ WEB

Una interfaz no se prueba mirando si "se ve bien". Lo que sí se puede
comprobar, y es lo que importa, son tres cosas:

1. **Que la sesión funcione y no se pueda saltar.** Sin cookie no hay
   página, la cookie es HttpOnly y SameSite, y salir la borra.

2. **Que lo que la pantalla ofrece exista de verdad en el API.** Es la
   prueba central del archivo. La pantalla de módulo se construye a partir
   de una descripción declarativa: si alguien renombra un parámetro del API
   o mueve un endpoint, la interfaz seguiría enseñando un filtro que no
   filtra o un botón que devuelve 404, y nadie se enteraría hasta usarlo.
   `test_el_catalogo_coincide_con_el_api` compara filtro por filtro y
   acción por acción contra el esquema OpenAPI real.

3. **Que los roles vean lo que les corresponde.** Ocultar un botón no es la
   protección —esa la hace `requiere_rol`, y se prueba aparte—, pero
   enseñar un botón que siempre va a responder 403 es una mentira de
   interfaz.

Ninguna prueba escribe en la base: la interfaz no tiene camino propio de
escritura, escribe llamando al API que ya está probado.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from fastapi.testclient import TestClient

from analytics import kpis as kpis_analytics
from backend.main import app
from backend.vistas import catalogo
from config import settings
from config.mongo_conexion import obtener_bd

API = settings.API_PREFIJO
CLAVE = "siglog2026"


def cliente_http() -> TestClient:
    """Sin seguir redirecciones: aquí el 303 y su destino son el resultado."""
    return TestClient(app, follow_redirects=False)


def entrar(c: TestClient, usuario: str = "admin"):
    respuesta = c.post("/entrar", data={"usuario": usuario, "contrasena": CLAVE})
    assert respuesta.status_code == 303, respuesta.text[:400]
    return respuesta


def json_del_modulo(html: str) -> dict:
    encontrado = re.search(
        r'<script id="datos-modulo" type="application/json">(.*?)</script>',
        html, re.S)
    assert encontrado, "la pantalla no incrustó la descripción del módulo"
    return json.loads(encontrado.group(1))


# ==========================================================================
# ACCESO
# ==========================================================================
def test_sin_sesion_no_hay_paginas():
    c = cliente_http()
    assert c.get("/").headers["location"] == "/entrar"
    for ruta in ("/panel", "/analitica", "/ml", "/modulos/clientes"):
        respuesta = c.get(ruta)
        assert respuesta.status_code == 303, ruta
        assert respuesta.headers["location"].startswith("/entrar"), ruta
        # Y se recuerda a dónde iba, para no dejarlo en el panel
        assert ruta in respuesta.headers["location"], ruta


def test_el_formulario_de_acceso_se_sirve_sin_sesion():
    c = cliente_http()
    respuesta = c.get("/entrar")
    assert respuesta.status_code == 200
    assert 'name="usuario"' in respuesta.text
    assert 'type="password"' in respuesta.text


def test_credenciales_malas_vuelven_al_formulario():
    """
    Un formulario que falla devuelve el formulario, no un JSON. Y el mensaje
    no dice cuál de los dos campos estaba mal: decirlo convertiría la
    pantalla en un verificador de cuentas existentes.
    """
    c = cliente_http()
    respuesta = c.post("/entrar",
                       data={"usuario": "admin", "contrasena": "no-es-esta"})
    assert respuesta.status_code == 401
    assert "text/html" in respuesta.headers["content-type"]
    assert "alert-danger" in respuesta.text
    assert 'name="usuario"' in respuesta.text, "debe poder reintentarse"
    assert settings.COOKIE_SESION not in respuesta.cookies
    texto = respuesta.text.lower()
    assert "no existe" not in texto and "no registrado" not in texto


def test_la_cookie_de_sesion_es_httponly_y_samesite():
    """
    HttpOnly impide que el JavaScript de la página lea el token: un XSS no
    podría llevarse la sesión. SameSite es lo que sostiene la defensa contra
    CSRF cuando se autentica por cookie.
    """
    c = cliente_http()
    respuesta = entrar(c)
    cabecera = respuesta.headers["set-cookie"].lower()
    assert settings.COOKIE_SESION in cabecera
    assert "httponly" in cabecera
    assert "samesite=strict" in cabecera
    assert respuesta.headers["location"] == "/panel"


def test_la_cookie_autentica_tambien_el_api():
    """
    Es el puente que hace funcionar toda la interfaz: el navegador no puede
    mandar la cabecera `Authorization` al pedir una página, pero sí manda la
    cookie, y con ella el JavaScript llama al mismo API de siempre.
    """
    c = cliente_http()
    entrar(c)
    respuesta = c.get(f"{API}/analitica/kpis")
    assert respuesta.status_code == 200, respuesta.text[:300]
    assert respuesta.json()["exito"] is True

    # Y sin cookie, el mismo endpoint sigue exigiendo sesión
    limpio = cliente_http()
    assert limpio.get(f"{API}/analitica/kpis").status_code == 401


def test_la_cabecera_manda_sobre_la_cookie():
    """
    Si alguien envía `Authorization` de forma explícita, esa es la identidad
    que quiere usar: una cookie abierta en otra pestaña no debe suplantarla.
    """
    c = cliente_http()
    entrar(c, "analista")                       # cookie de analista
    token = c.post(f"{API}/auth/login",
                   data={"username": "admin", "password": CLAVE}
                   ).json()["datos"]["access_token"]

    quien_soy = c.get(f"{API}/auth/yo",
                      headers={"Authorization": f"Bearer {token}"})
    assert quien_soy.json()["datos"]["usuario"] == "admin"
    assert c.get(f"{API}/auth/yo").json()["datos"]["usuario"] == "analista"


def test_salir_borra_la_cookie():
    c = cliente_http()
    entrar(c)
    assert c.get("/panel").status_code == 200

    respuesta = c.get("/salir")
    assert respuesta.status_code == 303
    assert respuesta.headers["location"] == "/entrar"
    cabecera = respuesta.headers["set-cookie"]
    assert "Max-Age=0" in cabecera or f'{settings.COOKIE_SESION}=""' in cabecera
    assert c.get("/panel").status_code == 303, "sin cookie, no hay panel"


def test_el_destino_no_puede_apuntar_fuera():
    """
    `destino` viaja en el formulario, así que lo controla quien lo envía. Un
    destino con dominio propio convertiría el acceso en un trampolín hacia
    otro sitio con la credibilidad de este.
    """
    c = cliente_http()
    for malicioso in ("https://ejemplo-falso.com", "//ejemplo-falso.com"):
        respuesta = c.post("/entrar", data={"usuario": "admin",
                                            "contrasena": CLAVE,
                                            "destino": malicioso})
        assert respuesta.headers["location"] == "/panel", malicioso

    # Un destino interno sí se respeta
    respuesta = c.post("/entrar", data={"usuario": "admin", "contrasena": CLAVE,
                                        "destino": "/modulos/viajes"})
    assert respuesta.headers["location"] == "/modulos/viajes"


# ==========================================================================
# PÁGINAS
# ==========================================================================
def test_todas_las_paginas_responden():
    c = cliente_http()
    entrar(c)
    rutas = ["/panel", "/analitica", "/ml"]
    rutas += [f"/modulos/{m.clave}" for m in catalogo.MODULOS]
    for ruta in rutas:
        respuesta = c.get(ruta)
        assert respuesta.status_code == 200, f"{ruta}: {respuesta.status_code}"
        assert "text/html" in respuesta.headers["content-type"], ruta
        assert "SIG-LOG" in respuesta.text, ruta
        # Ninguna página puede olvidar de dónde salen los datos
        assert "SIMULADOS" in respuesta.text, ruta


def test_un_modulo_inexistente_da_404_con_pagina():
    c = cliente_http()
    entrar(c)
    respuesta = c.get("/modulos/inventado")
    assert respuesta.status_code == 404
    assert "text/html" in respuesta.headers["content-type"], (
        "un 404 de navegación debe ser una página, no un JSON en crudo")
    assert "Volver al panel" in respuesta.text


def test_los_estaticos_se_sirven():
    c = cliente_http()
    for archivo in ("/static/css/siglog.css", "/static/js/siglog.js",
                    "/static/js/modulo.js", "/static/js/panel.js",
                    "/static/js/analitica.js", "/static/js/ml.js"):
        respuesta = c.get(archivo)
        assert respuesta.status_code == 200, archivo
        assert len(respuesta.text) > 500, archivo


def test_el_panel_muestra_los_kpis_de_analytics():
    """
    El panel se pinta en el servidor, así que los valores tienen que ser los
    mismos que calcula `analytics.kpis` — igual que en el endpoint.
    """
    c = cliente_http()
    entrar(c)
    html = c.get("/panel").text

    esperados = kpis_analytics.calcular(obtener_bd())
    titulos = re.findall(r'sl-kpi-titulo">([^<]+)</span>', html)
    assert len(titulos) == len(esperados) == 10
    for indicador in esperados:
        assert indicador["titulo"] in titulos, indicador["clave"]
        # La lectura de RF-29 viaja íntegra a la pantalla
        fragmento = indicador["lectura"][:40]
        assert fragmento in html or fragmento.replace("'", "&#39;") in html, (
            indicador["clave"])


# ==========================================================================
# LA PRUEBA CENTRAL: EL CATÁLOGO CONTRA EL API
# ==========================================================================
def test_el_catalogo_coincide_con_el_api():
    """
    Cada filtro y cada acción que la interfaz ofrece debe existir en el API.

    Sin esta prueba, renombrar un parámetro en un router dejaría en la
    pantalla un filtro que no filtra nada —o peor, que responde 422— y el
    fallo solo aparecería cuando alguien lo usara.
    """
    esquema = app.openapi()
    problemas: list[str] = []

    for modulo in catalogo.MODULOS:
        ruta_lista = API + modulo.recurso
        operacion = esquema["paths"].get(ruta_lista, {}).get("get")
        if operacion is None:
            problemas.append(f"{modulo.clave}: no existe GET {ruta_lista}")
            continue

        admitidos = {p["name"] for p in operacion.get("parameters", [])}
        for filtro in modulo.filtros:
            if filtro.nombre not in admitidos:
                problemas.append(
                    f"{modulo.clave}: el filtro '{filtro.nombre}' no es un "
                    f"parámetro de {ruta_lista} (admite {sorted(admitidos)})")

        if modulo.resumen:
            ruta = API + modulo.recurso + modulo.resumen
            if ruta not in esquema["paths"]:
                problemas.append(f"{modulo.clave}: no existe {ruta}")

        for accion in modulo.acciones:
            destino = (API + accion.ruta[3:] if accion.ruta.startswith("/../")
                       else API + modulo.recurso +
                            accion.ruta.replace("{id}", "{identificador}"))
            if destino not in esquema["paths"]:
                problemas.append(
                    f"{modulo.clave}/{accion.clave}: no existe {destino}")
            elif accion.metodo.lower() not in esquema["paths"][destino]:
                problemas.append(
                    f"{modulo.clave}/{accion.clave}: {destino} no admite "
                    f"{accion.metodo}")

    assert not problemas, "\n".join(problemas)


def test_cada_modulo_se_describe_completo():
    c = cliente_http()
    entrar(c)
    for modulo in catalogo.MODULOS:
        datos = json_del_modulo(c.get(f"/modulos/{modulo.clave}").text)
        assert datos["clave"] == modulo.clave
        assert datos["columnas"], modulo.clave
        assert datos["recurso"] == modulo.recurso
        assert datos["prefijo_api"] == API
        # Toda columna necesita un formato que el JavaScript sepa aplicar
        formatos = {"texto", "numero", "entero", "dinero", "fecha",
                    "fechahora", "hora", "booleano", "estado", "lista",
                    "minutos"}
        for columna in datos["columnas"]:
            assert columna["formato"] in formatos, (
                f"{modulo.clave}: formato '{columna['formato']}' desconocido")
        # Y todo campo, un tipo que el formulario sepa construir
        tipos = {"text", "password", "number", "select", "date", "datetime",
                 "time", "textarea", "checkbox", "ref", "objeto", "grupo"}
        for grupo in ("campos_alta", "campos_edicion"):
            for campo in datos[grupo]:
                assert campo["tipo"] in tipos, (
                    f"{modulo.clave}.{campo['nombre']}: tipo "
                    f"'{campo['tipo']}' desconocido")
                if campo["tipo"] == "ref":
                    assert campo["recurso"], f"{modulo.clave}.{campo['nombre']}"


def test_los_campos_calculados_no_aparecen_en_los_formularios():
    """
    Lo que el sistema deriva no se captura. Si un formulario ofreciera
    `retraso_min` o `costo_total`, la interfaz estaría invitando a escribir
    a mano justo las cifras que sostienen los modelos y los KPIs.
    """
    prohibidos = {
        "retraso_min", "es_retraso", "tiempo_real_min", "costo_total",
        "rendimiento_km_l", "rendimiento_real_km_l", "km_recorridos",
        "duracion_min", "distancia_total_km", "velocidad_efectiva_kmh",
        "proximo_mantenimiento_fecha", "fecha_ultimo_mantenimiento",
        "fecha_proximo_mantenimiento", "km_recorridos_desde_carga_anterior",
        "probabilidad_retraso", "retraso_estimado_min", "numero_paradas",
        "contrasena_hash", "folio_entrega", "folio_viaje", "codigo_cliente",
    }
    encontrados = []
    for modulo in catalogo.MODULOS:
        for grupo in (modulo.campos_alta, modulo.campos_edicion):
            for campo in grupo:
                if campo.nombre in prohibidos:
                    encontrados.append(f"{modulo.clave}.{campo.nombre}")
    assert not encontrados, (
        "campos calculados ofrecidos en un formulario: " +
        ", ".join(encontrados))


# ==========================================================================
# ROLES
# ==========================================================================
def test_el_analista_no_entra_a_usuarios():
    c = cliente_http()
    entrar(c, "analista")
    respuesta = c.get("/modulos/usuarios")
    assert respuesta.status_code == 403
    assert "text/html" in respuesta.headers["content-type"]
    # Y ni siquiera aparece en el menú: no se ofrece una puerta cerrada
    assert "/modulos/usuarios" not in c.get("/modulos/clientes").text


def test_el_analista_ve_las_pantallas_en_modo_consulta():
    c = cliente_http()
    entrar(c, "analista")
    for clave in ("clientes", "viajes", "entregas", "mantenimientos"):
        html = c.get(f"/modulos/{clave}").text
        assert 'id="btn-alta"' not in html, clave
        assert "Solo consulta" in html, clave
        assert "SIGLOG.puedeEscribir = false" in html, clave

    # Tampoco se le ofrece predecir, que escribe en la entrega
    assert 'id="form-prediccion"' not in c.get("/ml").text
    # Pero la analítica, que es su razón de ser, sí
    assert c.get("/analitica").status_code == 200


def test_el_despachador_escribe_donde_le_toca():
    """
    Los permisos no son uniformes: el despachador mueve la operación del día
    pero no da de alta clientes ni vehículos.
    """
    c = cliente_http()
    entrar(c, "despachador")
    for clave in ("viajes", "entregas", "incidentes", "combustible"):
        assert 'id="btn-alta"' in c.get(f"/modulos/{clave}").text, clave
    for clave in ("clientes", "vehiculos", "operadores", "rutas"):
        html = c.get(f"/modulos/{clave}").text
        assert 'id="btn-alta"' not in html, clave
        assert "Solo consulta" in html, clave


def test_lo_oculto_en_la_interfaz_sigue_prohibido_en_el_api():
    """
    Ocultar el botón no es la protección. Si alguien fabrica la petición a
    mano, quien la rechaza es `requiere_rol`, no la plantilla.
    """
    c = cliente_http()
    entrar(c, "analista")
    respuesta = c.post(f"{API}/clientes", json={
        "nombre": "ZZZ Intento del analista", "tipo_cliente": "MINORISTA",
        "direcciones": [{"alias": "Matriz", "calle": "X", "numero": "1",
                         "colonia": "Centro", "municipio": "Toluca",
                         "estado": "México", "cp": "50000", "principal": True}]})
    assert respuesta.status_code == 403, respuesta.text[:300]
    assert obtener_bd()["clientes"].count_documents(
        {"nombre": "ZZZ Intento del analista"}) == 0


if __name__ == "__main__":
    pruebas = [
        ("Sin sesión no hay páginas", test_sin_sesion_no_hay_paginas),
        ("El formulario de acceso se sirve",
         test_el_formulario_de_acceso_se_sirve_sin_sesion),
        ("Credenciales malas vuelven al formulario",
         test_credenciales_malas_vuelven_al_formulario),
        ("La cookie es HttpOnly y SameSite",
         test_la_cookie_de_sesion_es_httponly_y_samesite),
        ("La cookie autentica también el API",
         test_la_cookie_autentica_tambien_el_api),
        ("La cabecera manda sobre la cookie",
         test_la_cabecera_manda_sobre_la_cookie),
        ("Salir borra la cookie", test_salir_borra_la_cookie),
        ("El destino no puede apuntar fuera",
         test_el_destino_no_puede_apuntar_fuera),
        ("Todas las páginas responden", test_todas_las_paginas_responden),
        ("Un módulo inexistente da 404 con página",
         test_un_modulo_inexistente_da_404_con_pagina),
        ("Los estáticos se sirven", test_los_estaticos_se_sirven),
        ("El panel muestra los KPIs de analytics",
         test_el_panel_muestra_los_kpis_de_analytics),
        ("El catálogo coincide con el API",
         test_el_catalogo_coincide_con_el_api),
        ("Cada módulo se describe completo",
         test_cada_modulo_se_describe_completo),
        ("Los campos calculados no aparecen en los formularios",
         test_los_campos_calculados_no_aparecen_en_los_formularios),
        ("El analista no entra a usuarios", test_el_analista_no_entra_a_usuarios),
        ("El analista ve las pantallas en modo consulta",
         test_el_analista_ve_las_pantallas_en_modo_consulta),
        ("El despachador escribe donde le toca",
         test_el_despachador_escribe_donde_le_toca),
        ("Lo oculto sigue prohibido en el API",
         test_lo_oculto_en_la_interfaz_sigue_prohibido_en_el_api),
    ]

    print("=" * 70)
    print("  SIG-LOG — Pruebas de la interfaz web")
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
    print("  La interfaz no escribe por su cuenta: no hay escenario que limpiar.")
    print("=" * 70)
    print(f"  Resultado: {len(pruebas) - fallos}/{len(pruebas)} pruebas correctas")
    print("=" * 70)
    sys.exit(1 if fallos else 0)
