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
    rutas = [s.ruta for s in catalogo.SECCIONES]
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
                    "minutos", "referencia"}
        for columna in datos["columnas"]:
            assert columna["formato"] in formatos, (
                f"{modulo.clave}: formato '{columna['formato']}' desconocido")
            # Una columna "referencia" sin recurso enseñaría el identificador
            # crudo, que es justo lo que ese formato existe para evitar
            if columna["formato"] == "referencia":
                assert columna["recurso"], (
                    f"{modulo.clave}.{columna['campo']}: referencia sin recurso")
                assert columna["etiqueta_opcion"], (
                    f"{modulo.clave}.{columna['campo']}: sin campo legible")
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


def test_los_formularios_coinciden_con_los_esquemas_del_api():
    """
    Cada campo de cada formulario debe existir en el esquema que el API
    espera para esa operación.

    Es la contraparte de `test_el_catalogo_coincide_con_el_api`, que
    comprueba las *rutas*. Aquí se comprueban los *campos*: un nombre mal
    escrito en el catálogo produciría un formulario que parece funcionar
    —el usuario lo rellena y pulsa guardar— pero cuyo dato el API descarta
    en silencio, porque Pydantic ignora lo que no conoce. El registro
    quedaría sin ese cambio y nadie vería un error.
    """
    esquema = app.openapi()
    componentes = esquema.get("components", {}).get("schemas", {})

    def propiedades(ruta: str, metodo: str) -> set[str] | None:
        """Campos que admite el cuerpo de esa operación, o None si no lleva."""
        operacion = esquema["paths"].get(ruta, {}).get(metodo)
        if operacion is None:
            return None
        cuerpo = operacion.get("requestBody")
        if not cuerpo:
            return set()
        contenido = cuerpo["content"].get("application/json")
        if contenido is None:
            return set()
        referencia = contenido["schema"].get("$ref", "")
        if not referencia:
            return set()
        modelo = componentes.get(referencia.rsplit("/", 1)[-1], {})
        return set(modelo.get("properties", {}))

    problemas: list[str] = []

    for modulo in catalogo.MODULOS:
        # --- alta ---------------------------------------------------------
        if modulo.campos_alta:
            admitidos = propiedades(API + modulo.recurso, "post")
            for campo in modulo.campos_alta:
                if admitidos and campo.nombre not in admitidos:
                    problemas.append(
                        f"{modulo.clave}: el alta ofrece '{campo.nombre}', que "
                        f"POST {modulo.recurso} no admite "
                        f"({sorted(admitidos)})")

        # --- edición ------------------------------------------------------
        if modulo.campos_edicion:
            ruta = API + modulo.recurso + "/{identificador}"
            admitidos = propiedades(ruta, "put")
            assert admitidos is not None, (
                f"{modulo.clave} declara edición pero no existe PUT {ruta}")
            for campo in modulo.campos_edicion:
                if campo.nombre not in admitidos:
                    problemas.append(
                        f"{modulo.clave}: la edición ofrece '{campo.nombre}', "
                        f"que PUT no admite ({sorted(admitidos)})")

        # --- acciones -----------------------------------------------------
        for accion in modulo.acciones:
            if not accion.campos:
                continue
            destino = (API + accion.ruta[3:] if accion.ruta.startswith("/../")
                       else API + modulo.recurso +
                            accion.ruta.replace("{id}", "{identificador}"))
            admitidos = propiedades(destino, accion.metodo.lower())
            if not admitidos:
                continue
            for campo in accion.campos:
                if campo.nombre not in admitidos:
                    problemas.append(
                        f"{modulo.clave}/{accion.clave}: ofrece "
                        f"'{campo.nombre}', que {accion.metodo} {destino} "
                        f"no admite ({sorted(admitidos)})")

    assert not problemas, "\n".join(problemas)


def test_cada_accion_de_una_fila_tiene_su_propio_icono():
    """
    Con cinco o seis botones en la misma fila, repetir icono obliga a pasar
    el ratón por todos para saber cuál es cuál.
    """
    repetidos = []
    for modulo in catalogo.MODULOS:
        iconos = [a.icono for a in modulo.acciones if a.por_fila]
        # "Ver", "Editar" y "Baja" son fijos y ya tienen los suyos
        iconos += ["bi-eye", "bi-pencil", "bi-trash"]
        vistos = set()
        for icono in iconos:
            if icono in vistos:
                repetidos.append(f"{modulo.clave}: {icono} aparece dos veces")
            vistos.add(icono)
    assert not repetidos, "\n".join(repetidos)


def test_los_catalogos_se_pueden_editar_desde_la_interfaz():
    """
    Los cuatro catálogos del caso de estudio necesitan la «U» de CRUD.

    Sin formulario de edición, corregir el teléfono de un cliente o renovar
    la licencia de un operador solo se podría hacer desde la documentación
    del API, que no es una interfaz de trabajo.
    """
    faltan = []
    for clave in ("clientes", "vehiculos", "operadores", "rutas"):
        modulo = catalogo.POR_CLAVE[clave]
        if not modulo.campos_edicion:
            faltan.append(f"{clave}: sin formulario de edición")
        # Y una baja que no se puede deshacer no es una baja lógica
        if not any(a.clave == "reactivar" for a in modulo.acciones):
            faltan.append(f"{clave}: sin acción de reactivación")
    assert not faltan, "\n".join(faltan)

    # Las paradas de una ruta se editan como lista completa
    rutas = catalogo.POR_CLAVE["rutas"]
    paradas = next((a for a in rutas.acciones if a.clave == "paradas"), None)
    assert paradas is not None, "rutas: no se pueden editar las paradas"
    assert paradas.precargar, (
        "la edición de paradas debe llegar con las actuales: presentarla "
        "vacía donde el API espera la lista completa invitaría a borrarlas")


def test_la_edicion_no_ofrece_lo_que_el_sistema_calcula():
    """
    Un formulario de edición que ofreciera el odómetro o el rendimiento real
    estaría invitando a escribir a mano justo las cifras que sostienen los
    KPIs y los modelos.
    """
    derivados = {
        "vehiculos": {"odometro_actual_km", "rendimiento_real_km_l",
                      "fecha_ultimo_mantenimiento", "fecha_proximo_mantenimiento",
                      "estado_operativo", "ruta_asignada_id"},
        "rutas": {"numero_paradas", "distancia_total_km",
                  "tiempo_estimado_total_min", "velocidad_efectiva_kmh",
                  "vehiculo_asignado_id"},
        "operadores": {"antiguedad_meses", "licencia_vigente",
                       "porcentaje_entregas_a_tiempo", "total_entregas",
                       "estado"},
        "clientes": {"codigo_cliente", "total_entregas"},
    }
    encontrados = []
    for clave, prohibidos in derivados.items():
        for campo in catalogo.POR_CLAVE[clave].campos_edicion:
            if campo.nombre in prohibidos:
                encontrados.append(f"{clave}.{campo.nombre}")
    assert not encontrados, (
        "la edición ofrece campos que el sistema calcula: " +
        ", ".join(encontrados))


def test_la_interfaz_ofrece_exactamente_lo_que_el_api_permite():
    """
    Cada acción, contra el API real, con cada rol.

    Se comprueban las dos direcciones, y las dos importan:

    - **Más laxa** sería enseñar un botón que siempre responde 403. El
      usuario lo pulsa, recibe un error y deja de fiarse de la pantalla.
    - **Más estricta** sería esconder algo que el rol sí puede hacer. Es
      peor, porque no deja rastro: nadie reporta un botón que nunca vio.
      Justo eso pasaba con el despachador y los servicios de mantenimiento.

    Las peticiones van contra identificadores inexistentes y con el cuerpo
    vacío: la comprobación de rol ocurre antes que la de esquema, así que
    el 403 llega igual y no se escribe nada en la base.
    """
    INEXISTENTE = "0" * 24
    desajustes: list[str] = []

    for usuario, rol in (("admin", settings.ROL_ADMINISTRADOR),
                         ("despachador", settings.ROL_DESPACHADOR),
                         ("analista", settings.ROL_ANALISTA)):
        cliente = cliente_http()
        entrar(cliente, usuario)

        for modulo in catalogo.MODULOS:
            if not catalogo.puede_leer(modulo, rol):
                continue                 # ya lo cubre la matriz de acceso
            ofrecidas = {a.clave for a in catalogo.acciones_permitidas(modulo, rol)}

            for accion in modulo.acciones:
                if accion.metodo == "GET":
                    continue             # consultar no cambia nada
                destino = (API + accion.ruta[3:]
                           if accion.ruta.startswith("/../")
                           else API + modulo.recurso +
                                accion.ruta.replace("{id}", INEXISTENTE))
                respuesta = cliente.request(accion.metodo, destino, json={})
                prohibida = respuesta.status_code == 403
                ofrecida = accion.clave in ofrecidas

                if ofrecida and prohibida:
                    desajustes.append(
                        f"{rol}: la interfaz ofrece «{accion.etiqueta}» en "
                        f"{modulo.clave}, pero el API responde 403")
                if not ofrecida and not prohibida:
                    desajustes.append(
                        f"{rol}: la interfaz esconde «{accion.etiqueta}» en "
                        f"{modulo.clave}, pero el API sí lo permite "
                        f"(respondió {respuesta.status_code})")

    assert not desajustes, "\n".join(desajustes)


def test_el_despachador_atiende_el_taller():
    """
    El caso concreto que motivó los permisos por acción.

    Programar un servicio es planificación y la decide el administrador.
    Registrar que se hizo, o constatar que venció, lo hace quien ve pasar
    la unidad por el taller.
    """
    c = cliente_http()
    entrar(c, "despachador")
    html = c.get("/modulos/mantenimientos").text

    assert 'id="btn-alta"' not in html, "programar es del administrador"
    assert "Realizar" in html and "Declarar vencido" in html
    # Y no se le dice que está en solo consulta, porque no lo está
    assert "Solo consulta" not in html

    # El API coincide: le deja pasar la comprobación de rol
    for accion in ("realizar", "vencer"):
        respuesta = c.patch(f"{API}/mantenimientos/{'0' * 24}/{accion}", json={})
        assert respuesta.status_code != 403, accion


def test_lo_que_no_se_puede_usar_no_se_manda_a_la_pagina():
    """
    El recorte se hace en el servidor.

    Si la página recibiera la lista completa y ocultara con JavaScript,
    bastaría con mirar el código fuente para inventariar lo que existe, y
    cualquier fallo en esa lógica dejaría botones que responden 403.
    """
    c = cliente_http()
    entrar(c, "despachador")
    datos = json_del_modulo(c.get("/modulos/clientes").text)

    # El despachador solo consulta clientes: no debe llegarle ni el
    # formulario de alta ni el de edición
    assert datos["campos_alta"] == []
    assert datos["campos_edicion"] == []
    assert datos["permite_baja"] is False
    assert datos["acciones"] == []

    # Y al administrador sí
    admin = cliente_http()
    entrar(admin, "admin")
    datos = json_del_modulo(admin.get("/modulos/clientes").text)
    assert datos["campos_alta"], "el administrador sí da de alta clientes"
    assert datos["campos_edicion"]
    assert datos["permite_baja"] is True


# ==========================================================================
# GRÁFICAS
# ==========================================================================
def _scripts_de_pantalla() -> dict[str, list[Path]]:
    """Qué archivo de JavaScript carga cada plantilla."""
    plantillas = RAIZ / "frontend" / "templates"
    pares: dict[str, list[Path]] = {}
    for html in plantillas.glob("*.html"):
        for script in re.findall(r"/static/js/([a-z]+)\.js",
                                 html.read_text(encoding="utf-8")):
            pares.setdefault(script, []).append(html)
    return pares


def test_toda_grafica_declara_su_tipo():
    """
    Chart.js exige un `type` en la raíz de la configuración.

    Sin él lanza «"undefined" is not a registered controller» y el lienzo
    queda en blanco. Es especialmente fácil de olvidar en las gráficas
    mixtas, donde cada serie ya declara el suyo y parece que basta: no
    basta, y el fallo no deja rastro salvo en la consola del navegador.
    """
    estaticos = RAIZ / "frontend" / "static" / "js"
    problemas = []
    for archivo in sorted(estaticos.glob("*.js")):
        texto = archivo.read_text(encoding="utf-8")
        for encontrado in re.finditer(r"new Chart\(", texto):
            linea = texto[:encontrado.start()].count("\n") + 1
            # La configuración empieza en la llave que sigue a la coma
            resto = texto[encontrado.end():]
            apertura = resto.find("{")
            if apertura < 0:
                problemas.append(f"{archivo.name}:{linea}: sin configuración")
                continue
            # Primera clave de primer nivel, saltando comentarios
            cabeza = resto[apertura + 1:apertura + 700]
            cabeza = re.sub(r"//[^\n]*", "", cabeza)
            primera = re.search(r"\s*(\w+)\s*:", cabeza)
            if primera is None or primera.group(1) not in ("type", "data",
                                                           "options"):
                problemas.append(
                    f"{archivo.name}:{linea}: configuración inesperada")
                continue
            # `type` debe estar antes de `data` en el primer nivel
            hasta_data = cabeza.split("data:")[0]
            if "type:" not in hasta_data:
                problemas.append(
                    f"{archivo.name}:{linea}: la gráfica no declara `type` en "
                    "la raíz; Chart.js no la dibujará")
    assert not problemas, "\n".join(problemas)


def test_cada_script_encuentra_los_elementos_que_busca():
    """
    Un `getElementById` que devuelve null rompe la pantalla en silencio.

    Se comprueba contra la plantilla que carga cada script, más la base,
    que aporta los elementos comunes.
    """
    estaticos = RAIZ / "frontend" / "static" / "js"
    base = (RAIZ / "frontend" / "templates" / "base.html").read_text(
        encoding="utf-8")

    problemas = []
    for script, plantillas in _scripts_de_pantalla().items():
        js = (estaticos / f"{script}.js").read_text(encoding="utf-8")
        buscados = sorted(set(re.findall(r'getElementById\("([^"]+)"\)', js)))
        for plantilla in plantillas:
            html = plantilla.read_text(encoding="utf-8") + base
            for elemento in buscados:
                if f'id="{elemento}"' not in html:
                    problemas.append(
                        f"{script}.js busca «{elemento}», que no existe en "
                        f"{plantilla.name}")
    assert not problemas, "\n".join(problemas)


def test_los_identificadores_del_dom_son_ascii():
    """
    Un identificador con acento depende de que la página y el script se
    interpreten con la misma codificación. Con doce lienzos en el sistema
    no compensa el riesgo por un carácter.
    """
    malos = []
    for carpeta, patron in ((RAIZ / "frontend" / "templates", "*.html"),
                            (RAIZ / "frontend" / "static" / "js", "*.js")):
        for archivo in sorted(carpeta.glob(patron)):
            texto = archivo.read_text(encoding="utf-8")
            for elemento in re.findall(r'id="([^"]+)"', texto):
                if not elemento.isascii():
                    malos.append(f"{archivo.name}: id=\"{elemento}\"")
            for elemento in re.findall(r'getElementById\("([^"]+)"\)', texto):
                if not elemento.isascii():
                    malos.append(f"{archivo.name}: getElementById(\"{elemento}\")")
    assert not malos, "\n".join(malos)


def test_los_ejes_de_las_graficas_llevan_su_unidad():
    """
    Un eje sin unidad obliga a adivinar, y quien adivina se equivoca.

    Se exige que cada gráfica con escalas rotule sus ejes. Las unidades
    concretas —MXN, minutos, km, litros— se comprueban buscando que
    aparezcan en los rótulos del sistema.
    """
    estaticos = RAIZ / "frontend" / "static" / "js"
    unidades = ("(MXN)", "(minutos)", "(km)", "(litros)", "(%)")
    sin_rotular = []
    encontradas = set()

    for archivo in sorted(estaticos.glob("*.js")):
        texto = archivo.read_text(encoding="utf-8")
        if "new Chart(" not in texto:
            continue
        for unidad in unidades:
            if unidad in texto:
                encontradas.add(unidad)
        # Toda gráfica con `scales` debe rotular al menos un eje
        for bloque in re.findall(r"scales:\s*\{(.{0,900}?)\n\s{8,}\}",
                                 texto, re.S):
            if "title:" not in bloque:
                linea = texto[:texto.find(bloque)].count("\n") + 1
                sin_rotular.append(f"{archivo.name}:{linea}: ejes sin rótulo")

    assert not sin_rotular, "\n".join(sin_rotular)
    assert len(encontradas) >= 4, (
        f"solo se rotulan {sorted(encontradas)}; faltan unidades por declarar")


def test_el_panel_lleva_a_las_demas_pantallas():
    """
    Un panel del que no se puede salir es un callejón sin salida.

    Cada tarjeta resume algo que tiene su pantalla completa: las rutas
    llevan a la analítica, los vehículos a la flotilla, la predicción a ML
    y el mantenimiento a su módulo. Y la cabecera ofrece la navegación
    entre las pantallas de análisis, tomada de `secciones`, que ya viene
    filtrada por rol.
    """
    c = cliente_http()
    entrar(c)
    html = c.get("/panel").text

    for destino in ("/flotilla", "/analitica", "/ml"):
        assert f'href="{destino}"' in html, destino

    # Los enlaces al detalle de cada tarjeta
    assert html.count("sl-ver-mas") >= 4, (
        "las tarjetas del panel no dicen dónde está el detalle")

    # Y ninguno lleva a una pantalla que este rol no pueda abrir
    for destino in set(re.findall(r'href="(/[a-z]+(?:/[a-z]+)?)"', html)):
        if destino.startswith(("/static", "/salir", "/api")):
            continue
        assert c.get(destino).status_code == 200, (
            f"el panel enlaza a {destino}, que responde "
            f"{c.get(destino).status_code}")


def test_el_panel_ofrece_los_tres_informes():
    """
    Los tres, con su descripción: «ejecutivo» y «operativo» no dicen por sí
    solos cuál hace falta.
    """
    c = cliente_http()
    entrar(c)
    html = c.get("/panel").text
    for tipo in ("ejecutivo", "operativo", "flotilla"):
        assert f"{API}/reportes/{tipo}" in html, tipo
    assert "Qué atender hoy" in html
    # Y cada enlace responde de verdad, no da 404
    for tipo in ("ejecutivo", "operativo", "flotilla"):
        respuesta = c.get(f"{API}/reportes/{tipo}")
        assert respuesta.status_code == 200, f"{tipo}: {respuesta.status_code}"


# ==========================================================================
# ROLES
# ==========================================================================
def test_el_analista_no_entra_a_usuarios():
    c = cliente_http()
    entrar(c, "analista")
    respuesta = c.get("/modulos/usuarios")
    assert respuesta.status_code == 403
    assert "text/html" in respuesta.headers["content-type"]
    assert "no corresponde a tu perfil" in respuesta.text
    # Y ni siquiera aparece en el menú: no se ofrece una puerta cerrada
    assert "/modulos/usuarios" not in c.get("/modulos/clientes").text


def test_el_analista_ve_los_catalogos_en_modo_consulta():
    """
    Lo que el analista sí abre, lo abre en solo lectura.

    Los catálogos le dan contexto a los informes —qué ruta es RUT-004, qué
    vehículo es VEH-014—, así que los ve; pero no puede tocarlos.
    """
    c = cliente_http()
    entrar(c, "analista")
    for clave in ("clientes", "vehiculos", "operadores", "rutas"):
        respuesta = c.get(f"/modulos/{clave}")
        assert respuesta.status_code == 200, clave
        html = respuesta.text
        assert 'id="btn-alta"' not in html, clave
        assert "Solo consulta" in html, clave
        assert "SIGLOG.puedeEscribir = false" in html, clave

    # Tampoco se le ofrece predecir, que escribe en la entrega
    assert 'id="form-prediccion"' not in c.get("/ml").text
    # Pero el análisis, que es su razón de ser, sí
    for ruta in ("/panel", "/analitica", "/flotilla", "/ml"):
        assert c.get(ruta).status_code == 200, ruta


def test_la_matriz_de_acceso_se_aplica_de_verdad():
    """
    La prueba que da sentido a todo el control de acceso.

    Ocultar una entrada del menú no protege nada: quien teclee la dirección
    llega igual. Aquí se comprueba, pantalla por pantalla y rol por rol,
    que el servidor responde 403 a lo que ese rol no debería abrir — y 200
    a lo que sí.
    """
    from backend.vistas import catalogo

    sesiones = {}
    for usuario, rol in (("admin", settings.ROL_ADMINISTRADOR),
                         ("despachador", settings.ROL_DESPACHADOR),
                         ("analista", settings.ROL_ANALISTA)):
        c = cliente_http()
        entrar(c, usuario)
        sesiones[rol] = c

    problemas = []
    for fila in catalogo.matriz_de_acceso():
        for rol, cliente in sesiones.items():
            permitido = rol in fila["lectura"]
            codigo = cliente.get(fila["ruta"]).status_code
            esperado = 200 if permitido else 403
            if codigo != esperado:
                problemas.append(
                    f"{rol} → {fila['ruta']}: respondió {codigo}, "
                    f"se esperaba {esperado}")
    assert not problemas, "\n".join(problemas)


def test_el_menu_solo_ofrece_lo_que_se_puede_abrir():
    """
    Ninguna entrada del menú puede llevar a un 403.

    Enseñar una puerta cerrada es una mentira de interfaz, y además hace
    que el usuario dude de si el sistema funciona.
    """
    for usuario in ("admin", "despachador", "analista"):
        c = cliente_http()
        entrar(c, usuario)
        html = c.get("/panel").text
        enlaces = set(re.findall(r'href="(/modulos/[a-z]+|/panel|/flotilla'
                                 r'|/analitica|/ml)"', html))
        for enlace in enlaces:
            assert c.get(enlace).status_code == 200, (
                f"{usuario}: el menú ofrece {enlace} pero responde "
                f"{c.get(enlace).status_code}")


def test_el_despachador_escribe_donde_le_toca():
    """
    Los permisos no son uniformes, y tampoco son de todo o nada.

    El despachador mueve la operación del día: da de alta viajes, entregas,
    incidentes y cargas. En los catálogos no da de alta ni edita —eso es
    del administrador—, pero sí ejecuta los actos operativos que viven
    dentro de ellos: marcar que un camión entró al taller o que un operador
    causó baja temporal es despacho, no administración del catálogo.

    Por eso «Solo consulta» solo aparece donde de verdad no puede hacer
    nada: clientes y rutas.
    """
    c = cliente_http()
    entrar(c, "despachador")

    for clave in ("viajes", "entregas", "incidentes", "combustible"):
        assert 'id="btn-alta"' in c.get(f"/modulos/{clave}").text, clave

    # En los catálogos no da de alta, en ninguno
    for clave in ("clientes", "vehiculos", "operadores", "rutas"):
        assert 'id="btn-alta"' not in c.get(f"/modulos/{clave}").text, clave

    # Pero sí cambia el estado operativo de unidades y conductores
    for clave in ("vehiculos", "operadores"):
        html = c.get(f"/modulos/{clave}").text
        assert "Cambiar estado" in html, clave
        assert "Solo consulta" not in html, (
            f"{clave}: no está en solo consulta, puede cambiar el estado")

    # Y donde no puede hacer nada, se le dice
    for clave in ("clientes", "rutas"):
        assert "Solo consulta" in c.get(f"/modulos/{clave}").text, clave


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
        ("Toda gráfica declara su tipo", test_toda_grafica_declara_su_tipo),
        ("Cada script encuentra los elementos que busca",
         test_cada_script_encuentra_los_elementos_que_busca),
        ("Los identificadores del DOM son ASCII",
         test_los_identificadores_del_dom_son_ascii),
        ("Los ejes de las gráficas llevan su unidad",
         test_los_ejes_de_las_graficas_llevan_su_unidad),
        ("El panel lleva a las demás pantallas",
         test_el_panel_lleva_a_las_demas_pantallas),
        ("El panel ofrece los tres informes",
         test_el_panel_ofrece_los_tres_informes),
        ("El panel muestra los KPIs de analytics",
         test_el_panel_muestra_los_kpis_de_analytics),
        ("El catálogo coincide con el API",
         test_el_catalogo_coincide_con_el_api),
        ("Cada módulo se describe completo",
         test_cada_modulo_se_describe_completo),
        ("Los campos calculados no aparecen en los formularios",
         test_los_campos_calculados_no_aparecen_en_los_formularios),
        ("Los formularios coinciden con los esquemas del API",
         test_los_formularios_coinciden_con_los_esquemas_del_api),
        ("Cada acción de una fila tiene su propio icono",
         test_cada_accion_de_una_fila_tiene_su_propio_icono),
        ("Los catálogos se pueden editar desde la interfaz",
         test_los_catalogos_se_pueden_editar_desde_la_interfaz),
        ("La edición no ofrece lo que el sistema calcula",
         test_la_edicion_no_ofrece_lo_que_el_sistema_calcula),
        ("El analista no entra a usuarios", test_el_analista_no_entra_a_usuarios),
        ("El analista ve los catálogos en modo consulta",
         test_el_analista_ve_los_catalogos_en_modo_consulta),
        ("La matriz de acceso se aplica de verdad",
         test_la_matriz_de_acceso_se_aplica_de_verdad),
        ("El menú solo ofrece lo que se puede abrir",
         test_el_menu_solo_ofrece_lo_que_se_puede_abrir),
        ("El despachador escribe donde le toca",
         test_el_despachador_escribe_donde_le_toca),
        ("Lo oculto sigue prohibido en el API",
         test_lo_oculto_en_la_interfaz_sigue_prohibido_en_el_api),
        ("La interfaz ofrece exactamente lo que el API permite",
         test_la_interfaz_ofrece_exactamente_lo_que_el_api_permite),
        ("El despachador atiende el taller",
         test_el_despachador_atiende_el_taller),
        ("Lo que no se puede usar no se manda a la página",
         test_lo_que_no_se_puede_usar_no_se_manda_a_la_pagina),
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
