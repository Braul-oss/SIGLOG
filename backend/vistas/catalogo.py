"""
SIG-LOG — Sistema Integral de Gestión Logística
backend/vistas/catalogo.py

DESCRIPCIÓN DECLARATIVA DE LAS PANTALLAS DE MÓDULO

Los nueve módulos del dominio comparten la misma pantalla: una tabla con
filtros, un botón de alta y unas cuantas acciones. Lo único que cambia
entre ellos son las columnas, los campos del formulario y las acciones
disponibles.

Escribir nueve plantillas casi idénticas habría multiplicado por nueve
cualquier corrección de la tabla o del formulario. En vez de eso hay **una**
plantilla y **una** descripción por módulo. Añadir un módulo es añadir un
`Modulo` aquí.

Lo que este archivo NO hace
---------------------------
No valida nada. Que un campo esté marcado como requerido sirve para que el
navegador avise antes de enviar; la validación de verdad la hace Pydantic en
el API y las reglas de negocio, el servicio. Si las dos discrepan, manda el
API: la interfaz es un cliente más.

Sobre los permisos hay dos niveles, y conviene no confundirlos:

`roles_lectura`   quién puede ABRIR la pantalla. Lo comprueba el router en
                  `backend/routers/vistas.py` y responde 403 aunque se
                  escriba la URL a mano. Es una puerta de verdad.

`roles_escritura` quién puede dar de alta o modificar dentro de ella. Aquí
                  solo sirve para **ocultar** botones —enseñar uno que
                  siempre va a responder 403 es una mentira de interfaz—,
                  porque quien autoriza de verdad la escritura es
                  `requiere_rol` en el router del API, y sigue haciéndolo
                  aunque alguien fabrique la petición con curl.
"""

from __future__ import annotations

import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from config import settings


# ==========================================================================
# PIEZAS
# ==========================================================================
@dataclass(frozen=True)
class Columna:
    """Una columna de la tabla."""

    campo: str
    etiqueta: str
    # texto · numero · entero · dinero · fecha · fechahora · hora ·
    # booleano · estado (píldora de color) · lista · minutos ·
    # referencia (resuelve un identificador a su nombre legible)
    formato: str = "texto"
    ancho: str = ""
    # Solo para formato "referencia": de dónde sacar el nombre legible y qué
    # campos mostrar. Un identificador interno como
    # `6a83893489a0d3691e054f47` no le dice nada a nadie; quien mira una
    # tabla necesita ver «VEH-001 · Hino Serie 300».
    recurso: str = ""
    etiqueta_opcion: str = ""
    detalle_opcion: str = ""


@dataclass(frozen=True)
class Campo:
    """Un campo de formulario."""

    nombre: str
    etiqueta: str
    # text · password · number · select · date · datetime · time ·
    # textarea · checkbox · ref (select alimentado por otro recurso) ·
    # objeto (subformulario fijo) · grupo (lista repetible)
    tipo: str = "text"
    requerido: bool = False
    opciones: tuple[str, ...] = ()
    ayuda: str = ""
    paso: str = "any"
    multiple: bool = False
    # Para tipo "ref": recurso del API y campo que se muestra
    recurso: str = ""
    etiqueta_opcion: str = ""
    # Para "objeto" y "grupo"
    subcampos: tuple["Campo", ...] = ()


@dataclass(frozen=True)
class Filtro:
    """Un control de la barra de filtros. Va como parámetro de consulta."""

    nombre: str
    etiqueta: str
    tipo: str = "text"
    opciones: tuple[str, ...] = ()
    recurso: str = ""
    etiqueta_opcion: str = ""


@dataclass(frozen=True)
class Accion:
    """
    Una operación distinta del alta y la edición.

    Son los cambios de estado del dominio —iniciar un viaje, registrar una
    llegada, cerrar un incidente— que tienen endpoint propio precisamente
    porque cada uno dispara reglas distintas.
    """

    clave: str
    etiqueta: str
    metodo: str                       # POST · PUT · PATCH · DELETE
    ruta: str                         # sufijo tras el recurso; {id} si aplica
    campos: tuple[Campo, ...] = ()
    estilo: str = "outline-secondary"
    # Un icono propio por acción. Con cinco o seis botones en la misma fila,
    # repetir el mismo símbolo obliga a pasar el ratón por todos para saber
    # cuál es cuál.
    icono: str = "bi-lightning"
    # Roles que pueden ejecutarla. Vacío = los de escritura del módulo.
    #
    # Existe porque los permisos del dominio no siempre coinciden con el
    # módulo entero: en mantenimiento, programar un servicio es cosa del
    # administrador, pero registrarlo como hecho lo hace quien ve pasar la
    # unidad por el taller. Sin esto la interfaz sería más restrictiva que
    # el API, y le escondería al despachador algo que sí puede hacer.
    roles: tuple[str, ...] = ()
    por_fila: bool = True             # botón en cada fila, o en la barra
    confirmar: str = ""
    descripcion: str = ""
    # Si es cierto, el formulario llega con los valores actuales del
    # registro. Lo necesitan las acciones que REEMPLAZAN algo —las paradas
    # de una ruta— y no las que solo añaden un dato nuevo: presentar una
    # lista vacía donde el sistema espera la lista completa invitaría a
    # borrar sin querer todo lo que había.
    precargar: bool = False


@dataclass(frozen=True)
class Modulo:
    """Una pantalla de módulo completa."""

    clave: str
    titulo: str
    icono: str
    recurso: str
    descripcion: str
    columnas: tuple[Columna, ...]
    # Quién puede ABRIR la pantalla. Es la puerta, no la decoración: el
    # router la comprueba y responde 403 aunque se escriba la URL a mano.
    roles_lectura: tuple[str, ...] = settings.CATALOGO_ROLES
    # Quién puede dar de alta o modificar dentro de ella.
    roles_escritura: tuple[str, ...] = (settings.ROL_ADMINISTRADOR,)
    filtros: tuple[Filtro, ...] = ()
    campos_alta: tuple[Campo, ...] = ()
    campos_edicion: tuple[Campo, ...] = ()
    acciones: tuple[Accion, ...] = ()
    etiqueta_alta: str = "Nuevo"
    permite_baja: bool = True
    resumen: str = ""                 # sufijo del endpoint de resumen
    nota: str = ""                    # advertencia visible en la pantalla

    def a_json(self) -> dict[str, Any]:
        """Diccionario serializable que consume el JavaScript de la página."""
        datos = asdict(self)
        datos["prefijo_api"] = settings.API_PREFIJO
        return datos


# ==========================================================================
# PIEZAS REUTILIZADAS
# ==========================================================================
_DIRECCION = (
    Campo("alias", "Alias", requerido=True, ayuda="Matriz, Sucursal Norte…"),
    Campo("calle", "Calle", requerido=True),
    Campo("numero", "Número", requerido=True),
    Campo("colonia", "Colonia", requerido=True),
    Campo("municipio", "Municipio", requerido=True),
    Campo("estado", "Estado"),
    Campo("cp", "C.P.", requerido=True, ayuda="5 dígitos"),
    Campo("referencias", "Referencias"),
    Campo("principal", "Principal", tipo="checkbox"),
)

_ORIGEN = (
    Campo("nombre", "Nombre del origen", requerido=True),
    Campo("calle", "Calle", requerido=True),
    Campo("numero", "Número", requerido=True),
    Campo("colonia", "Colonia", requerido=True),
    Campo("municipio", "Municipio", requerido=True),
    Campo("estado", "Estado"),
    Campo("cp", "C.P.", requerido=True),
)

_LICENCIA = (
    Campo("numero", "Número de licencia", requerido=True),
    Campo("tipo", "Tipo", tipo="select", requerido=True,
          opciones=settings.CATALOGO_TIPO_LICENCIA),
    Campo("vigencia", "Vigencia", tipo="date", requerido=True),
)

# --------------------------------------------------------------------------
# GRUPOS DE ROLES
# --------------------------------------------------------------------------
# La navegación de cada rol sale de aquí. Cambiar quién ve qué es cambiar
# una de estas tuplas, no tocar plantillas ni menús.
#
# El criterio: cada quien ve lo que necesita para su trabajo.
#
#   ADMINISTRADOR  coordina: lo ve todo.
#   DESPACHADOR    mueve la operación del día. Necesita además consultar los
#                  catálogos —clientes, vehículos, operadores, rutas— porque
#                  sin ellos no puede programar una jornada.
#   ANALISTA       lee para decidir. Ve el análisis y los catálogos que le
#                  dan contexto, pero no la captura transaccional del día:
#                  el detalle de cada entrega o cada carga no le aporta
#                  nada que el análisis no le dé ya agregado.
TODOS = settings.CATALOGO_ROLES
OPERACION = (settings.ROL_ADMINISTRADOR, settings.ROL_DESPACHADOR)
SOLO_ADMIN = (settings.ROL_ADMINISTRADOR,)

_REF_VEHICULO = dict(tipo="ref", recurso="/vehiculos",
                     etiqueta_opcion="codigo_vehiculo")
_REF_VIAJE = dict(tipo="ref", recurso="/viajes", etiqueta_opcion="folio_viaje")
_REF_RUTA = dict(tipo="ref", recurso="/rutas", etiqueta_opcion="codigo_ruta")
_REF_CLIENTE = dict(tipo="ref", recurso="/clientes",
                    etiqueta_opcion="codigo_cliente")
_REF_OPERADOR = dict(tipo="ref", recurso="/operadores",
                     etiqueta_opcion="codigo_operador")


# ==========================================================================
# MÓDULOS
# ==========================================================================
CLIENTES = Modulo(
    clave="clientes", titulo="Clientes", icono="bi-people", recurso="/clientes",
    roles_lectura=TODOS,
    descripcion="A quién se entrega. Cada cliente guarda sus direcciones; la "
                "marcada como principal es la que toma una ruta si no se "
                "indica otra.",
    columnas=(
        Columna("codigo_cliente", "Código", ancho="110px"),
        Columna("nombre", "Nombre"),
        Columna("tipo_cliente", "Tipo", "estado", ancho="130px"),
        Columna("telefono", "Teléfono", ancho="130px"),
        Columna("email", "Correo"),
        Columna("total_entregas", "Entregas", "entero", ancho="90px"),
        Columna("activo", "Activo", "booleano", ancho="80px"),
    ),
    filtros=(
        Filtro("busqueda", "Buscar por nombre o código"),
        Filtro("tipo_cliente", "Tipo", "select",
               opciones=settings.CATALOGO_TIPO_CLIENTE),
    ),
    campos_alta=(
        Campo("nombre", "Nombre", requerido=True),
        Campo("razon_social", "Razón social"),
        Campo("tipo_cliente", "Tipo de cliente", tipo="select", requerido=True,
              opciones=settings.CATALOGO_TIPO_CLIENTE),
        Campo("telefono", "Teléfono"),
        Campo("email", "Correo electrónico"),
        Campo("direcciones", "Direcciones", tipo="grupo", subcampos=_DIRECCION,
              ayuda="Al menos una. Exactamente una debe ser la principal."),
    ),
    campos_edicion=(
        Campo("nombre", "Nombre"),
        Campo("razon_social", "Razón social"),
        Campo("tipo_cliente", "Tipo de cliente", tipo="select",
              opciones=settings.CATALOGO_TIPO_CLIENTE),
        Campo("telefono", "Teléfono"),
        Campo("email", "Correo electrónico"),
        Campo("direcciones", "Direcciones", tipo="grupo", subcampos=_DIRECCION,
              ayuda="Se envían todas juntas: lo que quede aquí sustituye a "
                    "las direcciones actuales. Sigue haciendo falta "
                    "exactamente una principal."),
    ),
    acciones=(
        Accion("reactivar", "Reactivar", "PATCH", "/{id}/reactivar",
               estilo="outline-success", icono="bi-arrow-counterclockwise",
               descripcion="Devuelve al catálogo un registro dado de baja. "
                           "Las bajas son lógicas: el histórico nunca pierde "
                           "filas hacia atrás, así que reactivar recupera el "
                           "registro tal como estaba."),
    ),
    resumen="/resumen",
)

VEHICULOS = Modulo(
    clave="vehiculos", titulo="Vehículos", icono="bi-truck", recurso="/vehiculos",
    roles_lectura=TODOS,
    descripcion="La flotilla. El odómetro, el rendimiento real y las fechas "
                "de mantenimiento no se capturan aquí (RN-V6): los mantienen "
                "la operación, el módulo de mantenimiento y el ETL.",
    columnas=(
        Columna("codigo_vehiculo", "Código", ancho="110px"),
        Columna("placa", "Placa", ancho="100px"),
        Columna("marca", "Marca"),
        Columna("modelo", "Modelo"),
        Columna("anio", "Año", "entero", ancho="70px"),
        Columna("tipo_vehiculo", "Tipo", "estado", ancho="100px"),
        Columna("estado_operativo", "Estado", "estado", ancho="150px"),
        Columna("odometro_actual_km", "Odómetro", "numero", ancho="110px"),
        Columna("rendimiento_real_km_l", "km/l real", "numero", ancho="100px"),
    ),
    filtros=(
        Filtro("busqueda", "Buscar por placa o código"),
        Filtro("estado", "Estado", "select",
               opciones=settings.CATALOGO_ESTADO_VEHICULO),
        Filtro("tipo_vehiculo", "Tipo", "select",
               opciones=settings.CATALOGO_TIPO_VEHICULO),
    ),
    campos_alta=(
        Campo("placa", "Placa", requerido=True),
        Campo("marca", "Marca", requerido=True),
        Campo("modelo", "Modelo", requerido=True),
        Campo("anio", "Año", tipo="number", requerido=True, paso="1"),
        Campo("tipo_vehiculo", "Tipo", tipo="select", requerido=True,
              opciones=settings.CATALOGO_TIPO_VEHICULO),
        Campo("tipo_combustible", "Combustible", tipo="select", requerido=True,
              opciones=settings.CATALOGO_TIPO_COMBUSTIBLE),
        Campo("capacidad_tanque_litros", "Tanque (litros)", tipo="number",
              requerido=True),
        Campo("rendimiento_nominal_km_l", "Rendimiento nominal (km/l)",
              tipo="number", requerido=True,
              ayuda="El de ficha. El real lo calcula el módulo de combustible."),
        Campo("odometro_actual_km", "Odómetro inicial (km)", tipo="number",
              requerido=True,
              ayuda="Solo al dar de alta: después lo mueven las cargas y los "
                    "viajes."),
    ),
    campos_edicion=(
        Campo("placa", "Placa"),
        Campo("marca", "Marca"),
        Campo("modelo", "Modelo"),
        Campo("anio", "Año", tipo="number", paso="1"),
        Campo("tipo_vehiculo", "Tipo", tipo="select",
              opciones=settings.CATALOGO_TIPO_VEHICULO),
        Campo("tipo_combustible", "Combustible", tipo="select",
              opciones=settings.CATALOGO_TIPO_COMBUSTIBLE),
        Campo("capacidad_tanque_litros", "Tanque (litros)", tipo="number"),
        Campo("rendimiento_nominal_km_l", "Rendimiento nominal (km/l)",
              tipo="number",
              ayuda="El de ficha. El rendimiento real y el odómetro no se "
                    "editan: los mueven las cargas de combustible y los "
                    "viajes, y corregirlos a mano falsearía el consumo de "
                    "dos tramos."),
    ),
    acciones=(
        Accion("estado", "Cambiar estado", "PATCH", "/{id}/estado",
               icono="bi-toggle-on", roles=OPERACION, campos=(
                   Campo("estado_operativo", "Nuevo estado", tipo="select",
                         requerido=True,
                         opciones=settings.CATALOGO_ESTADO_VEHICULO),
                   Campo("motivo", "Motivo", tipo="textarea"),
               ),
               descripcion="Las transiciones válidas las decide el servicio; "
                           "un salto no permitido responde 409."),
        Accion("ruta", "Asignar ruta", "PATCH", "/{id}/ruta",
               icono="bi-signpost-split",
               campos=(Campo("ruta_id", "Ruta", **_REF_RUTA),),
               descripcion="RN-04: un vehículo cubre una sola ruta y una "
                           "ruta la cubre un solo vehículo. Dejarlo vacío "
                           "libera la unidad, y entonces la ruta queda sin "
                           "cubrir."),
        Accion("reactivar", "Reactivar", "PATCH", "/{id}/reactivar",
               estilo="outline-success", icono="bi-arrow-counterclockwise",
               descripcion="Devuelve al catálogo un registro dado de baja. "
                           "Las bajas son lógicas: el histórico nunca pierde "
                           "filas hacia atrás, así que reactivar recupera el "
                           "registro tal como estaba."),
    ),
    resumen="/resumen",
)

OPERADORES = Modulo(
    clave="operadores", titulo="Operadores", icono="bi-person-badge",
    recurso="/operadores",
    roles_lectura=TODOS,
    descripcion="Quién conduce. Un operador con la licencia vencida no puede "
                "salir a ruta, y el sistema lo comprueba al programar el viaje.",
    columnas=(
        Columna("codigo_operador", "Código", ancho="110px"),
        Columna("nombre_completo", "Nombre"),
        Columna("estado", "Estado", "estado", ancho="110px"),
        Columna("licencia_vigente", "Licencia", "booleano", ancho="90px"),
        Columna("dias_para_vencer_licencia", "Días", "entero", ancho="80px"),
        Columna("antiguedad_meses", "Antigüedad", "entero", ancho="100px"),
        Columna("total_entregas", "Entregas", "entero", ancho="90px"),
        Columna("porcentaje_entregas_a_tiempo", "A tiempo", "numero",
                ancho="90px"),
    ),
    filtros=(
        Filtro("busqueda", "Buscar por nombre o código"),
        Filtro("estado", "Estado", "select",
               opciones=settings.CATALOGO_ESTADO_OPERADOR),
    ),
    campos_alta=(
        Campo("nombre_completo", "Nombre completo", requerido=True),
        Campo("licencia", "Licencia", tipo="objeto", subcampos=_LICENCIA),
        Campo("fecha_ingreso", "Fecha de ingreso", tipo="date", requerido=True,
              ayuda="De aquí sale la experiencia que usan los modelos."),
    ),
    campos_edicion=(
        Campo("nombre_completo", "Nombre completo"),
        Campo("licencia", "Licencia", tipo="objeto", subcampos=_LICENCIA),
        Campo("fecha_ingreso", "Fecha de ingreso", tipo="date",
              ayuda="Renovar la licencia se hace aquí: basta con actualizar "
                    "su vigencia. Un operador con la licencia vencida no "
                    "puede salir a ruta."),
    ),
    acciones=(
        Accion("estado", "Cambiar estado", "PATCH", "/{id}/estado",
               icono="bi-toggle-on", roles=OPERACION, campos=(
                   Campo("estado", "Nuevo estado", tipo="select",
                         requerido=True,
                         opciones=settings.CATALOGO_ESTADO_OPERADOR),
                   Campo("motivo", "Motivo", tipo="textarea"),
               )),
        Accion("reactivar", "Reactivar", "PATCH", "/{id}/reactivar",
               estilo="outline-success", icono="bi-arrow-counterclockwise",
               descripcion="Devuelve al catálogo un registro dado de baja. "
                           "Las bajas son lógicas: el histórico nunca pierde "
                           "filas hacia atrás, así que reactivar recupera el "
                           "registro tal como estaba."),

        Accion("desempenio", "Desempeño", "GET", "/{id}/desempenio",
               estilo="outline-info", icono="bi-graph-up",
               descripcion="Entregas, puntualidad y retraso medio del operador."),
    ),
    resumen="/resumen",
)

RUTAS = Modulo(
    clave="rutas", titulo="Rutas", icono="bi-signpost-split", recurso="/rutas",
    roles_lectura=TODOS,
    descripcion="El recorrido y sus paradas. La distancia total, el tiempo "
                "estimado y la velocidad efectiva se calculan de las paradas: "
                "no se capturan.",
    columnas=(
        Columna("codigo_ruta", "Código", ancho="110px"),
        Columna("nombre", "Nombre"),
        Columna("zona", "Zona", "estado", ancho="110px"),
        Columna("numero_paradas", "Paradas", "entero", ancho="90px"),
        Columna("distancia_total_km", "Km", "numero", ancho="90px"),
        Columna("tiempo_estimado_total_min", "Minutos", "numero", ancho="90px"),
        Columna("velocidad_efectiva_kmh", "km/h", "numero", ancho="80px"),
        Columna("hora_salida_programada", "Salida", ancho="80px"),
        Columna("vehiculo_asignado_id", "Vehículo", "referencia",
                ancho="190px", recurso="/vehiculos",
                etiqueta_opcion="codigo_vehiculo", detalle_opcion="placa"),
    ),
    filtros=(
        Filtro("busqueda", "Buscar por nombre o código"),
        Filtro("zona", "Zona", "select", opciones=settings.CATALOGO_ZONA),
    ),
    campos_alta=(
        Campo("nombre", "Nombre", requerido=True),
        Campo("zona", "Zona", tipo="select", requerido=True,
              opciones=settings.CATALOGO_ZONA),
        Campo("hora_salida_programada", "Hora de salida", tipo="time",
              requerido=True),
        Campo("dias_operacion", "Días de operación", tipo="select",
              requerido=True, multiple=True,
              opciones=settings.CATALOGO_DIAS_OPERACION),
        Campo("origen", "Origen", tipo="objeto", subcampos=_ORIGEN),
        Campo("paradas", "Paradas", tipo="grupo", subcampos=(
            Campo("cliente_id", "Cliente", requerido=True, **_REF_CLIENTE),
            Campo("direccion_alias", "Dirección", requerido=True,
                  ayuda="Alias de una dirección registrada del cliente."),
            Campo("distancia_desde_anterior_km", "Km desde la anterior",
                  tipo="number", requerido=True),
            Campo("tiempo_estimado_min", "Minutos estimados", tipo="number",
                  requerido=True),
        ), ayuda="El orden en que se capturan es el orden de la ruta."),
    ),
    campos_edicion=(
        Campo("nombre", "Nombre"),
        Campo("zona", "Zona", tipo="select", opciones=settings.CATALOGO_ZONA),
        Campo("hora_salida_programada", "Hora de salida", tipo="time"),
        Campo("dias_operacion", "Días de operación", tipo="select",
              multiple=True, opciones=settings.CATALOGO_DIAS_OPERACION),
        Campo("origen", "Origen", tipo="objeto", subcampos=_ORIGEN),
    ),
    acciones=(
        Accion("asignar", "Asignar vehículo", "PUT", "/{id}/asignar-vehiculo",
               icono="bi-truck",
               campos=(Campo("vehiculo_id", "Vehículo", **_REF_VEHICULO),),
               descripcion="RN-04: un vehículo cubre una sola ruta. Dejarlo "
                           "vacío libera la ruta."),
        Accion("paradas", "Editar paradas", "PUT", "/{id}/paradas",
               estilo="outline-primary", precargar=True,
               icono="bi-geo-alt",
               campos=(Campo("paradas", "Paradas", tipo="grupo", subcampos=(
                   Campo("cliente_id", "Cliente", requerido=True, **_REF_CLIENTE),
                   Campo("direccion_alias", "Dirección", requerido=True,
                         ayuda="Alias de una dirección registrada del cliente."),
                   Campo("distancia_desde_anterior_km", "Km desde la anterior",
                         tipo="number", requerido=True),
                   Campo("tiempo_estimado_min", "Minutos estimados",
                         tipo="number", requerido=True),
               )),),
               descripcion="La lista completa sustituye a la actual, y el "
                           "orden en que quedan aquí es el orden del "
                           "recorrido. La distancia total, el tiempo "
                           "estimado y la velocidad efectiva se recalculan "
                           "solos: no se capturan."),
        Accion("reactivar", "Reactivar", "PATCH", "/{id}/reactivar",
               estilo="outline-success", icono="bi-arrow-counterclockwise",
               descripcion="Devuelve al catálogo un registro dado de baja. "
                           "Las bajas son lógicas: el histórico nunca pierde "
                           "filas hacia atrás, así que reactivar recupera el "
                           "registro tal como estaba."),
    ),
    resumen="/resumen",
)

VIAJES = Modulo(
    clave="viajes", titulo="Viajes", icono="bi-calendar-check", recurso="/viajes",
    roles_escritura=(settings.ROL_ADMINISTRADOR, settings.ROL_DESPACHADOR),
    roles_lectura=OPERACION,
    descripcion="La jornada: una ruta, un vehículo y un operador en un día. "
                "Es el contenedor de las entregas y de los incidentes.",
    etiqueta_alta="Programar jornada",
    columnas=(
        Columna("folio_viaje", "Folio", ancho="150px"),
        Columna("fecha", "Fecha", "fecha", ancho="110px"),
        Columna("estatus", "Estatus", "estado", ancho="120px"),
        Columna("hora_salida_programada", "Salida prog.", "hora", ancho="100px"),
        Columna("hora_salida_real", "Salida real", "hora", ancho="100px"),
        Columna("retraso_salida_min", "Retraso", "minutos", ancho="90px"),
        Columna("km_recorridos", "Km", "numero", ancho="90px"),
        Columna("total_entregas_programadas", "Entregas", "entero", ancho="90px"),
        Columna("total_incidentes", "Incid.", "entero", ancho="80px"),
    ),
    filtros=(
        Filtro("estatus", "Estatus", "select",
               opciones=settings.CATALOGO_ESTATUS_VIAJE),
        Filtro("fecha_desde", "Desde", "date"),
        Filtro("fecha_hasta", "Hasta", "date"),
        Filtro("ruta_id", "Ruta", "ref", recurso="/rutas",
               etiqueta_opcion="codigo_ruta"),
    ),
    campos_alta=(
        Campo("ruta_id", "Ruta", requerido=True, **_REF_RUTA),
        Campo("vehiculo_id", "Vehículo", requerido=True, **_REF_VEHICULO),
        Campo("operador_id", "Operador", requerido=True, **_REF_OPERADOR),
        Campo("fecha", "Fecha", tipo="date", requerido=True),
    ),
    acciones=(
        Accion("iniciar", "Iniciar", "PATCH", "/{id}/iniciar",
               estilo="outline-success", icono="bi-play-circle",
               campos=(
                   Campo("odometro_inicial_km", "Odómetro de salida (km)",
                         tipo="number", requerido=True),
                   Campo("hora_salida_real", "Hora real de salida",
                         tipo="datetime",
                         ayuda="Si se deja vacía, se toma el momento actual."),
               ),
               descripcion="Calcula el retraso de salida, que es una de las "
                           "variables del escenario EN_RUTA."),
        Accion("finalizar", "Finalizar", "PATCH", "/{id}/finalizar",
               estilo="outline-primary", icono="bi-flag",
               campos=(
                   Campo("odometro_final_km", "Odómetro de regreso (km)",
                         tipo="number", requerido=True),
                   Campo("hora_regreso_real", "Hora de regreso", tipo="datetime"),
                   Campo("total_entregas_completadas", "Entregas completadas",
                         tipo="number", paso="1"),
               ),
               descripcion="Los km recorridos salen de la diferencia de "
                           "odómetros; no se capturan."),
        Accion("cancelar", "Cancelar", "PATCH", "/{id}/cancelar",
               estilo="outline-danger", icono="bi-x-octagon",
               campos=(Campo("motivo", "Motivo", tipo="textarea", requerido=True),),
               confirmar="¿Cancelar la jornada? No se puede deshacer."),
    ),
    permite_baja=False,
    resumen="/resumen",
)

ENTREGAS = Modulo(
    clave="entregas", titulo="Entregas", icono="bi-box-seam", recurso="/entregas",
    roles_escritura=(settings.ROL_ADMINISTRADOR, settings.ROL_DESPACHADOR),
    roles_lectura=OPERACION,
    descripcion="La colección crítica del proyecto: de aquí salen la variable "
                "objetivo y la mayoría de los predictores.",
    nota="El retraso NO se captura. Se calcula al registrar la llegada, "
         f"comparándola con la hora estimada, y supera el umbral de "
         f"{settings.UMBRAL_RETRASO_MIN} minutos o no lo supera.",
    etiqueta_alta="Nueva entrega",
    columnas=(
        Columna("folio_entrega", "Folio", ancho="160px"),
        Columna("orden_parada", "#", "entero", ancho="50px"),
        Columna("nombre_cliente", "Cliente"),
        Columna("estatus", "Estatus", "estado", ancho="120px"),
        Columna("hora_estimada_llegada", "ETA", "hora", ancho="80px"),
        Columna("hora_real_llegada", "Llegada", "hora", ancho="80px"),
        Columna("retraso_min", "Retraso", "minutos", ancho="90px"),
        Columna("es_retraso", "¿Tarde?", "booleano", ancho="80px"),
        Columna("probabilidad_retraso", "Riesgo", "numero", ancho="80px"),
    ),
    filtros=(
        Filtro("viaje_id", "Viaje", "ref", recurso="/viajes",
               etiqueta_opcion="folio_viaje"),
        Filtro("estatus", "Estatus", "select",
               opciones=settings.CATALOGO_ESTATUS_ENTREGA),
        Filtro("solo_retrasadas", "Solo retrasadas", "checkbox"),
        Filtro("fecha_desde", "Desde", "date"),
        Filtro("fecha_hasta", "Hasta", "date"),
    ),
    campos_alta=(
        Campo("viaje_id", "Viaje", requerido=True, **_REF_VIAJE),
        Campo("cliente_id", "Cliente", requerido=True, **_REF_CLIENTE),
        Campo("orden_parada", "Orden de parada", tipo="number", requerido=True,
              paso="1"),
        Campo("tiempo_estimado_min", "Minutos estimados", tipo="number",
              requerido=True),
        Campo("distancia_km", "Distancia (km)", tipo="number", requerido=True),
        Campo("hora_estimada_llegada", "Hora estimada de llegada",
              tipo="datetime",
              ayuda="Si se omite, se calcula acumulando los tiempos de la ruta."),
        Campo("observaciones", "Observaciones", tipo="textarea"),
    ),
    acciones=(
        Accion("generar", "Generar desde la ruta", "POST", "/generar",
               por_fila=False, estilo="primary", icono="bi-magic",
               campos=(Campo("viaje_id", "Viaje", requerido=True, **_REF_VIAJE),),
               descripcion="La operación normal: la ruta ya sabe a quién se "
                           "entrega y en qué orden."),
        Accion("llegada", "Registrar llegada", "PATCH", "/{id}/llegada",
               estilo="outline-success", icono="bi-check2-circle",
               campos=(
                   Campo("hora_real_llegada", "Hora real de llegada",
                         tipo="datetime",
                         ayuda="Vacía = ahora."),
                   Campo("entregada", "Se entregó", tipo="checkbox"),
                   Campo("causa_retraso", "Causa del retraso", tipo="select",
                         opciones=settings.CATALOGO_TIPOS_INCIDENTE,
                         ayuda="Solo se acepta si hubo retraso (RN-E6)."),
                   Campo("observaciones", "Observaciones", tipo="textarea"),
               ),
               descripcion="Aquí nace el retraso: se calcula, no se escribe."),
        Accion("estatus", "Cambiar estatus", "PATCH", "/{id}/estatus",
               icono="bi-toggle-on", campos=(
                   Campo("estatus", "Nuevo estatus", tipo="select",
                         requerido=True,
                         opciones=settings.CATALOGO_ESTATUS_ENTREGA),
                   Campo("motivo", "Motivo", tipo="textarea"),
               )),
        Accion("predecir", "Predecir retraso", "POST",
               "/../ml/predecir-retraso", estilo="outline-warning",
               icono="bi-magic",
               campos=(Campo("guardar", "Guardar en la entrega",
                             tipo="checkbox"),),
               descripcion="Aplica los modelos entrenados. El escenario lo "
                           "decide el estado del viaje, no esta pantalla."),
    ),
    permite_baja=False,
    resumen="/resumen",
)

INCIDENTES = Modulo(
    clave="incidentes", titulo="Incidentes", icono="bi-exclamation-triangle",
    recurso="/incidentes",
    roles_escritura=(settings.ROL_ADMINISTRADOR, settings.ROL_DESPACHADOR),
    roles_lectura=OPERACION,
    descripcion="Lo que sale mal durante la jornada. Un incidente puede "
                "recalcular el ETA de las entregas pendientes del viaje (RF-33).",
    nota="El recálculo escribe `hora_estimada_recalculada` y nunca pisa "
         "`hora_estimada_llegada` (RN-I5): si la pisara, la entrega parecería "
         "puntual justo por el incidente que la retrasó.",
    etiqueta_alta="Registrar incidente",
    columnas=(
        Columna("folio_incidente", "Folio", ancho="160px"),
        Columna("tipo", "Tipo", "estado", ancho="130px"),
        Columna("severidad", "Severidad", "estado", ancho="110px"),
        Columna("fecha_hora_inicio", "Inicio", "fechahora", ancho="150px"),
        Columna("duracion_min", "Duración", "minutos", ancho="90px"),
        Columna("tiempo_perdido_estimado_min", "Perdido", "minutos", ancho="90px"),
        Columna("abierto", "Abierto", "booleano", ancho="80px"),
        Columna("fuente", "Fuente", ancho="110px"),
    ),
    filtros=(
        Filtro("viaje_id", "Viaje", "ref", recurso="/viajes",
               etiqueta_opcion="folio_viaje"),
        Filtro("tipo", "Tipo", "select", opciones=settings.CATALOGO_TIPOS_INCIDENTE),
        Filtro("severidad", "Severidad", "select",
               opciones=settings.CATALOGO_SEVERIDAD_INCIDENTE),
        Filtro("solo_abiertos", "Solo abiertos", "checkbox"),
    ),
    campos_alta=(
        Campo("viaje_id", "Viaje", requerido=True, **_REF_VIAJE),
        Campo("tipo", "Tipo", tipo="select", requerido=True,
              opciones=settings.CATALOGO_TIPOS_INCIDENTE),
        Campo("severidad", "Severidad", tipo="select", requerido=True,
              opciones=settings.CATALOGO_SEVERIDAD_INCIDENTE),
        Campo("fecha_hora_inicio", "Inicio", tipo="datetime"),
        Campo("tiempo_perdido_estimado_min", "Minutos perdidos estimados",
              tipo="number", requerido=True),
        Campo("descripcion", "Descripción", tipo="textarea",
              ayuda="Texto libre: es el dato no estructurado del proyecto."),
        Campo("fuente", "Fuente", tipo="select",
              opciones=settings.CATALOGO_FUENTE_INCIDENTE),
    ),
    acciones=(
        Accion("afectar", "Recalcular ETA", "POST", "/{id}/afectar-entregas",
               estilo="outline-warning", icono="bi-clock-history",
               campos=(Campo("minutos_perdidos", "Minutos a propagar",
                             tipo="number",
                             ayuda="Vacío = los estimados del incidente."),),
               descripcion="RF-33. Solo alcanza a las entregas pendientes del "
                           "viaje y deja constancia en `seguimiento_eventos`."),
        Accion("cerrar", "Cerrar", "PATCH", "/{id}/cerrar",
               estilo="outline-success", icono="bi-check2-circle",
               campos=(Campo("fecha_hora_fin", "Fin", tipo="datetime"),),
               descripcion="Calcula la duración real del incidente."),
    ),
    permite_baja=False,
    resumen="/resumen",
)

COMBUSTIBLE = Modulo(
    clave="combustible", titulo="Combustible", icono="bi-fuel-pump",
    recurso="/combustible",
    roles_escritura=(settings.ROL_ADMINISTRADOR, settings.ROL_DESPACHADOR),
    roles_lectura=OPERACION,
    descripcion="Las cargas de la flotilla. El costo total, el tramo recorrido "
                "y el rendimiento se calculan de los litros y del odómetro.",
    nota="Una carga no se edita ni se borra: es un hecho ocurrido. "
         "Corregirla retroactivamente cambiaría el rendimiento de dos tramos.",
    etiqueta_alta="Registrar carga",
    columnas=(
        Columna("folio_carga", "Folio", ancho="160px"),
        Columna("fecha", "Fecha", "fecha", ancho="110px"),
        Columna("litros", "Litros", "numero", ancho="90px"),
        Columna("precio_por_litro", "$/litro", "dinero", ancho="90px"),
        Columna("costo_total", "Costo", "dinero", ancho="110px"),
        Columna("odometro_km", "Odómetro", "numero", ancho="110px"),
        Columna("km_recorridos_desde_carga_anterior", "Tramo", "numero",
                ancho="90px"),
        Columna("rendimiento_km_l", "km/l", "numero", ancho="80px"),
        Columna("estacion", "Estación"),
    ),
    filtros=(
        Filtro("vehiculo_id", "Vehículo", "ref", recurso="/vehiculos",
               etiqueta_opcion="codigo_vehiculo"),
        Filtro("fecha_desde", "Desde", "date"),
        Filtro("fecha_hasta", "Hasta", "date"),
    ),
    campos_alta=(
        Campo("vehiculo_id", "Vehículo", requerido=True, **_REF_VEHICULO),
        Campo("litros", "Litros", tipo="number", requerido=True),
        Campo("precio_por_litro", "Precio por litro", tipo="number",
              requerido=True),
        Campo("odometro_km", "Odómetro al cargar (km)", tipo="number",
              requerido=True,
              ayuda="No puede ser menor que el de la carga anterior (RN-F5)."),
        Campo("fecha", "Fecha y hora", tipo="datetime"),
        Campo("viaje_id", "Viaje", **_REF_VIAJE),
        Campo("estacion", "Estación"),
    ),
    permite_baja=False,
    resumen="/resumen",
)

MANTENIMIENTOS = Modulo(
    clave="mantenimientos", titulo="Mantenimiento", icono="bi-tools",
    recurso="/mantenimientos",
    roles_lectura=OPERACION,
    descripcion="Los servicios de la flotilla. Realizar uno actualiza las "
                "fechas de mantenimiento del vehículo, que su ficha no deja "
                "capturar.",
    nota=f"Un servicio vencido deja la unidad fuera de operación. Vuelve a "
         f"estar disponible al realizarlo, pero solo si no le quedan otros "
         f"vencidos. La periodicidad es de "
         f"{settings.DIAS_PERIODICIDAD_MANTENIMIENTO} días de calendario.",
    etiqueta_alta="Programar servicio",
    columnas=(
        Columna("folio_mantenimiento", "Folio", ancho="160px"),
        Columna("tipo", "Tipo", "estado", ancho="120px"),
        Columna("estatus", "Estatus", "estado", ancho="120px"),
        Columna("fecha_programada", "Programado", "fecha", ancho="110px"),
        Columna("fecha_realizada", "Realizado", "fecha", ancho="110px"),
        Columna("proximo_mantenimiento_fecha", "Próximo", "fecha", ancho="110px"),
        Columna("dias_de_atraso", "Atraso", "entero", ancho="80px"),
        Columna("costo", "Costo", "dinero", ancho="110px"),
    ),
    filtros=(
        Filtro("vehiculo_id", "Vehículo", "ref", recurso="/vehiculos",
               etiqueta_opcion="codigo_vehiculo"),
        Filtro("tipo", "Tipo", "select",
               opciones=settings.CATALOGO_TIPO_MANTENIMIENTO),
        Filtro("estatus", "Estatus", "select",
               opciones=settings.CATALOGO_ESTATUS_MANTENIMIENTO),
    ),
    campos_alta=(
        Campo("vehiculo_id", "Vehículo", requerido=True, **_REF_VEHICULO),
        Campo("tipo", "Tipo", tipo="select", requerido=True,
              opciones=settings.CATALOGO_TIPO_MANTENIMIENTO),
        Campo("fecha_programada", "Fecha programada", tipo="date",
              requerido=True),
        Campo("descripcion", "Descripción", tipo="textarea"),
        Campo("costo_estimado", "Costo estimado", tipo="number"),
    ),
    campos_edicion=(
        Campo("fecha_programada", "Fecha programada", tipo="date"),
        Campo("tipo", "Tipo", tipo="select",
              opciones=settings.CATALOGO_TIPO_MANTENIMIENTO),
        Campo("descripcion", "Descripción", tipo="textarea"),
        Campo("costo_estimado", "Costo estimado", tipo="number"),
    ),
    acciones=(
        Accion("realizar", "Realizar", "PATCH", "/{id}/realizar",
               estilo="outline-success", icono="bi-wrench-adjustable",
               roles=OPERACION,
               campos=(
                   Campo("odometro_km", "Odómetro (km)", tipo="number",
                         requerido=True),
                   Campo("costo", "Costo real", tipo="number", requerido=True),
                   Campo("fecha_realizada", "Fecha realizada", tipo="date"),
                   Campo("duracion_dias", "Días fuera de operación",
                         tipo="number",
                         ayuda="Vacío = de la fecha programada a la realizada."),
                   Campo("descripcion", "Descripción", tipo="textarea"),
               )),
        Accion("vencer", "Declarar vencido", "PATCH", "/{id}/vencer",
               estilo="outline-danger", icono="bi-exclamation-octagon",
               roles=OPERACION,
               campos=(Campo("motivo", "Motivo", tipo="textarea"),),
               confirmar="La unidad quedará fuera de operación. ¿Continuar?"),
    ),
    permite_baja=False,
    resumen="/resumen",
)

USUARIOS = Modulo(
    clave="usuarios", titulo="Usuarios", icono="bi-shield-lock",
    recurso="/usuarios",
    roles_lectura=SOLO_ADMIN,
    descripcion="Las cuentas del sistema y su rol. Ningún endpoint devuelve "
                "jamás el hash de la contraseña.",
    nota="El sistema no se puede quedar sin administradores activos: "
         "desactivar o degradar al último está prohibido, y quien lo intente "
         "recibe un 409, no un error genérico.",
    etiqueta_alta="Nueva cuenta",
    columnas=(
        Columna("usuario", "Usuario", ancho="140px"),
        Columna("nombre_completo", "Nombre"),
        Columna("rol", "Rol", "estado", ancho="140px"),
        Columna("activo", "Activo", "booleano", ancho="80px"),
        Columna("ultimo_acceso", "Último acceso", "fechahora", ancho="160px"),
    ),
    filtros=(
        Filtro("rol", "Rol", "select", opciones=settings.CATALOGO_ROLES),
        Filtro("incluir_inactivos", "Incluir dados de baja", "checkbox"),
    ),
    campos_alta=(
        Campo("usuario", "Usuario", requerido=True),
        Campo("contrasena", "Contraseña", tipo="password", requerido=True,
              ayuda="Mínimo 8 caracteres. Se guarda con bcrypt, nunca en claro."),
        Campo("nombre_completo", "Nombre completo", requerido=True),
        Campo("rol", "Rol", tipo="select", requerido=True,
              opciones=settings.CATALOGO_ROLES),
    ),
    campos_edicion=(
        Campo("nombre_completo", "Nombre completo"),
        Campo("correo", "Correo electrónico"),
    ),
    acciones=(
        # El rol NO se edita junto con el resto de los datos: tiene endpoint
        # propio porque arrastra dos reglas —nadie cambia su propio rol
        # (RN-U2) y no se degrada al último administrador activo (RN-U3)—
        # que no tendrían dónde aplicarse en una edición genérica.
        Accion("rol", "Cambiar rol", "PATCH", "/{id}/rol",
               estilo="outline-primary", icono="bi-person-gear",
               campos=(Campo("rol", "Nuevo rol", tipo="select", requerido=True,
                             opciones=settings.CATALOGO_ROLES),),
               descripcion="Nadie puede cambiar su propio rol, y el último "
                           "administrador activo no se puede degradar."),
        Accion("reiniciar", "Reiniciar contraseña", "PATCH",
               "/{id}/contrasena", estilo="outline-warning", icono="bi-key",
               campos=(Campo("contrasena_nueva", "Nueva contraseña",
                             tipo="password", requerido=True),)),
        Accion("reactivar", "Reactivar", "PATCH", "/{id}/reactivar",
               estilo="outline-success", icono="bi-arrow-counterclockwise",
               descripcion="Devuelve al sistema una cuenta dada de baja."),
    ),
)


MODULOS: tuple[Modulo, ...] = (
    CLIENTES, VEHICULOS, OPERADORES, RUTAS, VIAJES, ENTREGAS, INCIDENTES,
    COMBUSTIBLE, MANTENIMIENTOS, USUARIOS,
)

POR_CLAVE: dict[str, Modulo] = {modulo.clave: modulo for modulo in MODULOS}


# ==========================================================================
# PANTALLAS DE ANÁLISIS
# ==========================================================================
# No son módulos del dominio —no tienen tabla ni formulario— pero sí forman
# parte de la navegación y también se reparten por rol.
@dataclass(frozen=True)
class Seccion:
    """Una entrada de navegación que no es un módulo CRUD."""

    clave: str
    titulo: str
    icono: str
    ruta: str
    roles: tuple[str, ...] = settings.CATALOGO_ROLES
    descripcion: str = ""


SECCIONES: tuple[Seccion, ...] = (
    Seccion("panel", "Panel ejecutivo", "bi-speedometer2", "/panel",
            descripcion="Qué está pasando en la operación, en una pantalla."),
    Seccion("flotilla", "Flotilla", "bi-truck-front", "/flotilla",
            descripcion="Qué unidades cuestan más, consumen más, trabajan "
                        "más y llegan tarde con más frecuencia."),
    Seccion("analitica", "Rutas y retrasos", "bi-bar-chart-line", "/analitica",
            descripcion="Dónde se concentra el retraso y por qué."),
    Seccion("ml", "Predicción", "bi-cpu", "/ml",
            descripcion="Qué entregas van a llegar tarde, y qué rutas se "
                        "parecen entre sí."),
)

SECCIONES_POR_CLAVE: dict[str, Seccion] = {s.clave: s for s in SECCIONES}


# ==========================================================================
# NAVEGACIÓN Y PERMISOS
# ==========================================================================
def secciones_visibles(rol: str | None) -> list[dict[str, Any]]:
    """Pantallas de análisis que ese rol puede abrir."""
    return [{"clave": s.clave, "titulo": s.titulo, "icono": s.icono,
             "ruta": s.ruta, "descripcion": s.descripcion}
            for s in SECCIONES if rol in s.roles]


def menu(rol: str | None = None) -> list[dict[str, Any]]:
    """
    Módulos del dominio visibles para ese rol.

    Ocultar una entrada **no** es la protección: el router comprueba
    `puede_leer` y responde 403 aunque se escriba la URL a mano. Esto es lo
    otro, que también importa — no ofrecer una puerta que va a estar
    cerrada.
    """
    return [{"clave": m.clave, "titulo": m.titulo, "icono": m.icono}
            for m in MODULOS if puede_leer(m, rol)]


def puede_leer(modulo: Modulo, rol: str | None) -> bool:
    """Si ese rol puede abrir la pantalla del módulo."""
    return rol in modulo.roles_lectura


def puede_escribir(modulo: Modulo, rol: str | None) -> bool:
    """Si ese rol puede dar de alta, modificar o dar de baja en el módulo."""
    return rol in modulo.roles_escritura


def puede_ejecutar(modulo: Modulo, accion: Accion, rol: str | None) -> bool:
    """
    Si ese rol puede ejecutar esa acción concreta.

    Una acción sin roles propios hereda los de escritura del módulo. Los
    tiene propios cuando el permiso del dominio no coincide con el del
    módulo entero.
    """
    return rol in (accion.roles or modulo.roles_escritura)


def acciones_permitidas(modulo: Modulo, rol: str | None) -> tuple[Accion, ...]:
    """Las acciones que ese rol puede ejecutar, en el orden declarado."""
    return tuple(a for a in modulo.acciones if puede_ejecutar(modulo, a, rol))


def vista_para(modulo: Modulo, rol: str | None) -> dict[str, Any]:
    """
    La descripción del módulo **recortada a lo que este rol puede hacer**.

    El recorte se hace en el servidor a propósito. Si la página recibiera
    la lista completa y ocultara con JavaScript, bastaría con mirar el
    código fuente para ver qué acciones existen; y peor, cualquier fallo en
    esa lógica dejaría botones que responden 403. Lo que no se puede usar,
    no se manda.
    """
    datos = modulo.a_json()
    datos["acciones"] = [asdict(a) for a in acciones_permitidas(modulo, rol)]
    if not puede_escribir(modulo, rol):
        # Alta, edición y baja son del módulo, no de una acción suelta
        datos["campos_alta"] = []
        datos["campos_edicion"] = []
        datos["permite_baja"] = False
    return datos


def puede_ver_seccion(clave: str, rol: str | None) -> bool:
    """Si ese rol puede abrir una pantalla de análisis."""
    seccion = SECCIONES_POR_CLAVE.get(clave)
    return seccion is not None and rol in seccion.roles


def matriz_de_acceso() -> list[dict[str, Any]]:
    """
    La matriz completa de quién ve y quién escribe qué.

    Existe para que la política se pueda auditar de un vistazo —y para que
    una prueba compruebe que la interfaz y el API dicen lo mismo— sin tener
    que leer diez declaraciones de módulo.
    """
    filas = []
    for seccion in SECCIONES:
        filas.append({"pantalla": seccion.titulo, "tipo": "análisis",
                      "ruta": seccion.ruta,
                      "lectura": list(seccion.roles), "escritura": []})
    for modulo in MODULOS:
        filas.append({"pantalla": modulo.titulo, "tipo": "módulo",
                      "ruta": f"/modulos/{modulo.clave}",
                      "lectura": list(modulo.roles_lectura),
                      "escritura": list(modulo.roles_escritura)})
    return filas
