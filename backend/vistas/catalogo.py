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

Tampoco decide permisos. `roles_escritura` solo sirve para **ocultar** los
botones que ese rol no podría usar — enseñar un botón que siempre va a
responder 403 es una mentira de interfaz. Quien autoriza de verdad es
`requiere_rol` en el router, y sigue haciéndolo aunque alguien fabrique la
petición a mano.
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
    # booleano · estado (píldora de color) · lista · minutos
    formato: str = "texto"
    ancho: str = ""


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
    por_fila: bool = True             # botón en cada fila, o en la barra
    confirmar: str = ""
    descripcion: str = ""


@dataclass(frozen=True)
class Modulo:
    """Una pantalla de módulo completa."""

    clave: str
    titulo: str
    icono: str
    recurso: str
    descripcion: str
    columnas: tuple[Columna, ...]
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
    resumen="/resumen",
)

VEHICULOS = Modulo(
    clave="vehiculos", titulo="Vehículos", icono="bi-truck", recurso="/vehiculos",
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
    acciones=(
        Accion("estado", "Cambiar estado", "PATCH", "/{id}/estado",
               campos=(
                   Campo("estado_operativo", "Nuevo estado", tipo="select",
                         requerido=True,
                         opciones=settings.CATALOGO_ESTADO_VEHICULO),
                   Campo("motivo", "Motivo", tipo="textarea"),
               ),
               descripcion="Las transiciones válidas las decide el servicio; "
                           "un salto no permitido responde 409."),
    ),
    resumen="/resumen",
)

OPERADORES = Modulo(
    clave="operadores", titulo="Operadores", icono="bi-person-badge",
    recurso="/operadores",
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
    acciones=(
        Accion("estado", "Cambiar estado", "PATCH", "/{id}/estado",
               campos=(
                   Campo("estado", "Nuevo estado", tipo="select",
                         requerido=True,
                         opciones=settings.CATALOGO_ESTADO_OPERADOR),
                   Campo("motivo", "Motivo", tipo="textarea"),
               )),
        Accion("desempenio", "Desempeño", "GET", "/{id}/desempenio",
               estilo="outline-info",
               descripcion="Entregas, puntualidad y retraso medio del operador."),
    ),
    resumen="/resumen",
)

RUTAS = Modulo(
    clave="rutas", titulo="Rutas", icono="bi-signpost-split", recurso="/rutas",
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
        Columna("vehiculo_asignado_id", "Vehículo", ancho="110px"),
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
    acciones=(
        Accion("asignar", "Asignar vehículo", "PUT", "/{id}/asignar-vehiculo",
               campos=(Campo("vehiculo_id", "Vehículo", **_REF_VEHICULO),),
               descripcion="RN-04: un vehículo cubre una sola ruta. Dejarlo "
                           "vacío libera la ruta."),
    ),
    resumen="/resumen",
)

VIAJES = Modulo(
    clave="viajes", titulo="Viajes", icono="bi-calendar-check", recurso="/viajes",
    roles_escritura=(settings.ROL_ADMINISTRADOR, settings.ROL_DESPACHADOR),
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
        Accion("iniciar", "Iniciar", "PATCH", "/{id}/iniciar", estilo="outline-success",
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
               estilo="outline-primary",
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
               estilo="outline-danger",
               campos=(Campo("motivo", "Motivo", tipo="textarea", requerido=True),),
               confirmar="¿Cancelar la jornada? No se puede deshacer."),
    ),
    permite_baja=False,
    resumen="/resumen",
)

ENTREGAS = Modulo(
    clave="entregas", titulo="Entregas", icono="bi-box-seam", recurso="/entregas",
    roles_escritura=(settings.ROL_ADMINISTRADOR, settings.ROL_DESPACHADOR),
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
               por_fila=False, estilo="primary",
               campos=(Campo("viaje_id", "Viaje", requerido=True, **_REF_VIAJE),),
               descripcion="La operación normal: la ruta ya sabe a quién se "
                           "entrega y en qué orden."),
        Accion("llegada", "Registrar llegada", "PATCH", "/{id}/llegada",
               estilo="outline-success",
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
               campos=(
                   Campo("estatus", "Nuevo estatus", tipo="select",
                         requerido=True,
                         opciones=settings.CATALOGO_ESTATUS_ENTREGA),
                   Campo("motivo", "Motivo", tipo="textarea"),
               )),
        Accion("predecir", "Predecir retraso", "POST",
               "/../ml/predecir-retraso", estilo="outline-warning",
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
               estilo="outline-warning",
               campos=(Campo("minutos_perdidos", "Minutos a propagar",
                             tipo="number",
                             ayuda="Vacío = los estimados del incidente."),),
               descripcion="RF-33. Solo alcanza a las entregas pendientes del "
                           "viaje y deja constancia en `seguimiento_eventos`."),
        Accion("cerrar", "Cerrar", "PATCH", "/{id}/cerrar",
               estilo="outline-success",
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
               estilo="outline-success",
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
               estilo="outline-danger",
               campos=(Campo("motivo", "Motivo", tipo="textarea"),),
               confirmar="La unidad quedará fuera de operación. ¿Continuar?"),
    ),
    permite_baja=False,
    resumen="/resumen",
)

USUARIOS = Modulo(
    clave="usuarios", titulo="Usuarios", icono="bi-shield-lock",
    recurso="/usuarios",
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
               estilo="outline-primary",
               campos=(Campo("rol", "Nuevo rol", tipo="select", requerido=True,
                             opciones=settings.CATALOGO_ROLES),),
               descripcion="Nadie puede cambiar su propio rol, y el último "
                           "administrador activo no se puede degradar."),
        Accion("reiniciar", "Reiniciar contraseña", "PATCH",
               "/{id}/contrasena", estilo="outline-warning",
               campos=(Campo("contrasena_nueva", "Nueva contraseña",
                             tipo="password", requerido=True),)),
        Accion("reactivar", "Reactivar", "PATCH", "/{id}/reactivar",
               estilo="outline-success",
               descripcion="Devuelve al sistema una cuenta dada de baja."),
    ),
)


MODULOS: tuple[Modulo, ...] = (
    CLIENTES, VEHICULOS, OPERADORES, RUTAS, VIAJES, ENTREGAS, INCIDENTES,
    COMBUSTIBLE, MANTENIMIENTOS, USUARIOS,
)

POR_CLAVE: dict[str, Modulo] = {modulo.clave: modulo for modulo in MODULOS}


def menu(rol: str | None = None) -> list[dict[str, Any]]:
    """
    Entradas de navegación visibles para ese rol.

    `usuarios` solo aparece para el administrador. No es la protección —esa
    la hace el router— sino una cuestión de no ofrecer una puerta cerrada.
    """
    visibles = []
    for modulo in MODULOS:
        if modulo.clave == "usuarios" and rol != settings.ROL_ADMINISTRADOR:
            continue
        visibles.append({"clave": modulo.clave, "titulo": modulo.titulo,
                         "icono": modulo.icono})
    return visibles


def puede_escribir(modulo: Modulo, rol: str | None) -> bool:
    """Si ese rol puede dar de alta o modificar en el módulo."""
    return rol in modulo.roles_escritura
