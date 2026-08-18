# SIG-LOG — Sistema Integral de Gestión Logística

Sistema de información para una empresa de transporte y distribución: administra
la operación logística (clientes, vehículos, operadores, rutas, viajes, entregas,
incidentes, combustible y mantenimiento) y extrae conocimiento de ella mediante
un proceso ETL, un data warehouse, modelos de Machine Learning y un dashboard
con interpretación automática.

> **Todos los datos del proyecto son SIMULADOS**, generados con fines académicos.
> Ninguna cifra describe una empresa real. Cada documento lleva la marca
> `origen_dato: "SIMULADO"`.

---

## Requisitos

- Python 3.13 (probado en 3.13.11)
- Una base de datos MongoDB Atlas llamada `siglog`
- Acceso de red al cluster (tu IP debe estar en la *Network Access List* de Atlas)

## Instalación

```bash
git clone <repositorio>
cd SIGLOG

pip install -r requirements.txt

# Configura las credenciales
cp .env.example .env
# Edita .env con tu usuario, contraseña y cluster de MongoDB Atlas

# Genera la clave de firma de los tokens y colócala en JWT_CLAVE
python -c "import secrets; print(secrets.token_hex(32))"
```

Verifica que la conexión y la estructura estén correctas:

```bash
python tests/test_conexion.py
```

---

## Ejecutar SIG-LOG (aplicación web)

**Comando oficial**, desde la raíz del proyecto:

```bash
uvicorn app:app --reload
```

| Recurso | URL |
|---|---|
| API | http://127.0.0.1:8000/api/v1 |
| Documentación interactiva (Swagger) | http://127.0.0.1:8000/docs |
| Documentación alternativa (ReDoc) | http://127.0.0.1:8000/redoc |
| Esquema OpenAPI | http://127.0.0.1:8000/openapi.json |

`app.py` (en la raíz) solo **reexporta** la aplicación; quien la construye
—con su ciclo de vida, manejadores de error, CORS y routers— es
**`backend/main.py`**. No hay dos configuraciones que mantener, solo dos
nombres para la misma aplicación.

Formas equivalentes, todas válidas:

```bash
uvicorn app:app --reload            # la de arriba
uvicorn backend.main:app --reload   # apunta al módulo que la construye
python -m backend.main              # usa host/puerto/recarga del .env
python app.py                       # equivalente a la anterior
```

> **Ejecuta siempre desde la raíz del proyecto.** Tanto `app` como el
> paquete `backend` se importan desde ahí, así que la raíz debe estar en el
> `PYTHONPATH`.
> Desde otro directorio el arranque falla con `ModuleNotFoundError: No module
> named 'backend'`; si lo necesitas, exporta `PYTHONPATH=/ruta/a/SIGLOG`.

El host, el puerto y la recarga automática se configuran en el `.env`
(`API_HOST`, `API_PUERTO`, `API_RECARGA`).

### Primer usuario

La API exige sesión para las operaciones protegidas, así que hay que crear
una cuenta antes de poder usarla:

```bash
python -m database.crear_usuario --usuario admin --rol ADMINISTRADOR
python -m database.crear_usuario --listar          # ver las cuentas existentes
python -m database.crear_usuario --usuario admin --restablecer
```

La contraseña se pide por consola y nunca se pasa como argumento: quedaría
registrada en el historial del shell.

**Roles disponibles** (RNP-11, actores del §3):

| Rol | Quién es | Qué hace |
|---|---|---|
| `ADMINISTRADOR` | Coordinador logístico | Catálogos, configuración y usuarios |
| `DESPACHADOR` | Capturista | Registra la operación del día a día |
| `ANALISTA` | Directivo | Consulta dashboard, reportes y resultados de ML |

### Endpoints disponibles

Todos bajo el prefijo `/api/v1` (§12.2 del documento técnico).

| Método | Endpoint | Acceso | Propósito |
|---|---|---|---|
| GET | `/salud` | público | Verifica que la API responde (no consulta MongoDB) |
| GET | `/salud/mongodb` | público | Ping real contra MongoDB Atlas |
| GET | `/info` | público | Versión, entorno y módulos disponibles |
| POST | `/auth/login` | público | Inicia sesión y devuelve el token JWT |
| GET | `/auth/estado` | público | Estado del subsistema de seguridad |
| GET | `/auth/yo` | sesión | Datos del usuario autenticado |
| POST | `/auth/cambiar-contrasena` | sesión | Cambia la contraseña propia |
| GET | `/diagnostico/colecciones` | sesión | Conteo de documentos por colección |
| GET | `/diagnostico/muestra/{coleccion}` | sesión | Documentos de muestra |
| GET | `/usuarios` | admin | Listar cuentas (paginado, filtrable por rol) |
| GET | `/usuarios/roles` | admin | Catálogo de roles |
| GET | `/usuarios/resumen` | admin | Conteo por rol y estado |
| GET | `/usuarios/{id}` | admin | Detalle de una cuenta |
| POST | `/usuarios` | admin | Alta de una cuenta |
| PUT | `/usuarios/{id}` | admin | Editar nombre y correo |
| PATCH | `/usuarios/{id}/rol` | admin | Cambiar el rol |
| PATCH | `/usuarios/{id}/contrasena` | admin | Restablecer la contraseña |
| DELETE | `/usuarios/{id}` | admin | Baja lógica |
| PATCH | `/usuarios/{id}/reactivar` | admin | Reactivar una cuenta |
| GET | `/clientes` | sesión | Listar (paginado, con búsqueda y filtros) |
| GET | `/clientes/catalogos` | sesión | Tipos y municipios para los formularios |
| GET | `/clientes/resumen` | sesión | Conteo por tipo y estado |
| GET | `/clientes/{id}` | sesión | Detalle |
| POST | `/clientes` | admin | Crear |
| PUT | `/clientes/{id}` | admin | Actualizar |
| DELETE | `/clientes/{id}` | admin | Baja lógica |
| PATCH | `/clientes/{id}/reactivar` | admin | Reactivar |
| GET | `/vehiculos` | sesión | Listar (búsqueda y filtros por estado y tipo) |
| GET | `/vehiculos/catalogos` | sesión | Estados, tipos y transiciones válidas |
| GET | `/vehiculos/resumen` | sesión | Conteo por estado y tipo |
| GET | `/vehiculos/{id}` | sesión | Detalle |
| GET | `/vehiculos/{id}/rendimiento` | sesión | Rendimiento histórico km/l |
| POST | `/vehiculos` | admin | Dar de alta |
| PUT | `/vehiculos/{id}` | admin | Actualizar la ficha |
| PATCH | `/vehiculos/{id}/estado` | admin o despachador | Cambiar el estado operativo |
| PATCH | `/vehiculos/{id}/ruta` | admin | Asignar o quitar la ruta |
| DELETE | `/vehiculos/{id}` | admin | Baja lógica |
| PATCH | `/vehiculos/{id}/reactivar` | admin | Reactivar |
| GET | `/operadores` | sesión | Listar (filtros por estado y licencia vencida) |
| GET | `/operadores/catalogos` | sesión | Estados y tipos de licencia |
| GET | `/operadores/resumen` | sesión | Plantilla y alerta de licencias |
| GET | `/operadores/licencias` | sesión | Vencidas y por vencer |
| GET | `/operadores/{id}` | sesión | Detalle |
| GET | `/operadores/{id}/desempenio` | sesión | Entregas y puntualidad |
| POST | `/operadores` | admin | Dar de alta |
| PUT | `/operadores/{id}` | admin | Actualizar ficha o renovar licencia |
| PATCH | `/operadores/{id}/estado` | admin o despachador | Activar o desactivar |
| DELETE | `/operadores/{id}` | admin | Baja lógica |
| PATCH | `/operadores/{id}/reactivar` | admin | Reactivar la ficha |
| GET | `/rutas` | sesión | Listar (filtros por zona y sin vehículo) |
| GET | `/rutas/catalogos` · `/resumen` | sesión | Catálogos y cobertura |
| GET | `/rutas/{id}` | sesión | Detalle con sus paradas |
| GET | `/rutas/{id}/analisis` | sesión | Perfil del ETL y grupo del clustering |
| POST | `/rutas` | admin | Crear |
| PUT | `/rutas/{id}` | admin | Actualizar la cabecera |
| POST | `/rutas/{id}/paradas` | admin | Agregar una parada |
| PUT | `/rutas/{id}/paradas` | admin | Reemplazar el itinerario |
| DELETE | `/rutas/{id}/paradas/{orden}` | admin | Quitar una parada |
| PUT | `/rutas/{id}/asignar-vehiculo` | admin | Asignar o quitar el vehículo |
| DELETE | `/rutas/{id}` | admin | Baja lógica |
| PATCH | `/rutas/{id}/reactivar` | admin | Reactivar |
| GET | `/viajes` · `/catalogos` · `/resumen` · `/{id}` | sesión | Consultar jornadas |
| POST | `/viajes` | admin o despachador | Programar la jornada |
| PATCH | `/viajes/{id}/iniciar` | admin o despachador | Registrar la salida real |
| PATCH | `/viajes/{id}/finalizar` | admin o despachador | Registrar el regreso |
| PATCH | `/viajes/{id}/cancelar` | admin o despachador | Cancelar con motivo |
| GET | `/entregas` · `/catalogos` · `/resumen` · `/{id}` | sesión | Consultar entregas |
| POST | `/entregas` | admin o despachador | Crear una entrega |
| POST | `/entregas/generar` | admin o despachador | Generarlas todas desde la ruta |
| PATCH | `/entregas/{id}/llegada` | admin o despachador | Registrar la llegada → calcula el retraso |
| PATCH | `/entregas/{id}/estatus` | admin o despachador | Cambiar estatus + historial |
| GET | `/incidentes` · `/catalogos` · `/resumen` · `/{id}` | sesión | Consultar incidentes |
| GET | `/incidentes/bitacora/{viaje_id}` | sesión | Bitácora de seguimiento del viaje |
| POST | `/incidentes` | admin o despachador | Registrar un incidente |
| POST | `/incidentes/{id}/afectar-entregas` | admin o despachador | Recalcular ETA (RF-33) |
| PATCH | `/incidentes/{id}/cerrar` | admin o despachador | Cerrar y calcular la duración |
| GET | `/combustible` · `/catalogos` · `/{id}` | sesión | Consultar cargas |
| GET | `/combustible/resumen` | sesión | Consumo y costo agregado |
| POST | `/combustible` | admin o despachador | Registrar una carga |
| GET | `/mantenimientos` · `/catalogos` · `/resumen` · `/{id}` | sesión | Consultar mantenimientos |
| GET | `/mantenimientos/pendientes` | sesión | Vehículos por atender (RF-16) |
| POST | `/mantenimientos` | administrador | Programar un servicio |
| PUT | `/mantenimientos/{id}` | administrador | Editar mientras no se realice |
| PATCH | `/mantenimientos/{id}/realizar` | admin o despachador | Registrar el servicio efectuado |
| PATCH | `/mantenimientos/{id}/vencer` | admin o despachador | Declararlo vencido |
| GET | `/analitica/kpis` | sesión | Los diez indicadores del dashboard |
| GET | `/analitica/rutas-mas-usadas` | sesión | Volumen y retraso medio por ruta |
| GET | `/analitica/causas-retraso` | sesión | Pareto de causas |
| GET | `/analitica/saturacion-horaria` | sesión | Entregas por franja y día |
| GET | `/ml/modelos` | sesión | Modelos entrenados y sus métricas |
| GET | `/ml/clusters-rutas` | sesión | Grupos de rutas (K-Means sobre PCA) |
| GET | `/ml/entregas-en-riesgo` | sesión | Pendientes ordenadas por riesgo |
| POST | `/ml/predecir-retraso` | admin o despachador | Predicción para una entrega |

En el módulo de clientes el permiso **no es uniforme**: consultar lo puede
hacer cualquier sesión —el despachador necesita ver clientes para registrar
entregas y el analista para leer los reportes—, mientras que modificar está
reservado al administrador (§3).

**Reglas de negocio de la gestión de cuentas.** Existen para que un
administrador no pueda dejar el sistema sin quien lo administre:

| Regla | Qué impide |
|---|---|
| RN-U1 | Nadie puede desactivar su propia cuenta |
| RN-U2 | Nadie puede cambiar su propio rol |
| RN-U3 | No se puede desactivar ni degradar al último administrador activo |
| RN-U4 | El identificador de acceso no se puede cambiar |
| RN-U5 | El hash de la contraseña nunca sale en una respuesta |

**Reglas del módulo de clientes:**

| Regla | Qué impide |
|---|---|
| RN-C1 | El código de cliente lo genera el sistema (CLI-NNN) y es inmutable |
| RN-C2 | Al menos una dirección y exactamente una marcada como principal |
| RN-C3 | No se puede dar de baja un cliente que es parada de una ruta activa |
| RN-C4 | La baja es lógica: el histórico de entregas se conserva |

**Reglas del módulo de vehículos:**

| Regla | Qué impide |
|---|---|
| RN-V1 | El código VEH-NNN lo genera el sistema y es inmutable |
| RN-V2 | La placa es única en la flotilla |
| RN-V3 | RN-04: un vehículo, una ruta; una ruta, un vehículo |
| RN-V4 | No se da de baja un vehículo con ruta asignada |
| RN-V5 | El estado operativo es una máquina de estados, no un campo libre |
| RN-V6 | El odómetro, el rendimiento real y las fechas de mantenimiento no se editan desde el API: los mantienen la operación y el ETL |

**Reglas del módulo de operadores:**

| Regla | Qué impide |
|---|---|
| RN-O1 | El código OPE-NNN lo genera el sistema y es inmutable |
| RN-O2 | El número de licencia es único |
| RN-O3 | Un operador con la licencia vencida no puede quedar ACTIVO |
| RN-O4 | El sistema avisa de las licencias por vencer con antelación |
| RN-O5 | No se da de baja a quien tiene viajes sin cerrar |
| RN-O6 | Las entregas y la puntualidad no se editan desde el API |

**Reglas del módulo de rutas:**

| Regla | Qué impide |
|---|---|
| RN-R1 | El código RUT-NNN lo genera el sistema y es inmutable |
| RN-R2 | Los totales se recalculan a partir de las paradas, nunca se capturan |
| RN-R3 | Paradas numeradas 1..N sin huecos, y al menos una |
| RN-R4 | El cliente de la parada existe, está activo y tiene esa dirección |
| RN-R5 | Un cliente no se repite dentro de la misma ruta |
| RN-R6 | No se da de baja una ruta con vehículo o con viajes sin cerrar |

**Reglas del módulo de viajes:**

| Regla | Qué impide |
|---|---|
| RN-J1 | El folio VJE-AAAAMMDD-NNNN lo genera el sistema |
| RN-J2 | El viaje avanza y nunca retrocede; un viaje cerrado no se reabre |
| RN-J3 | Ruta activa, vehículo disponible, operador con licencia vigente, y nadie en dos jornadas a la vez |
| RN-J4 | Una ruta se ejecuta una vez al día |
| RN-J5 | El odómetro no baja al salir |
| RN-J6 | El odómetro final supera al inicial y el regreso a la salida |
| RN-J7 | No hay borrado ni baja lógica: solo cancelación con motivo |

**Reglas del módulo de entregas:**

| Regla | Qué impide |
|---|---|
| RN-E1 | El folio ENT-AAAAMMDD-NNNNN lo genera el sistema |
| RN-E2 | `tiempo_real_min`, `retraso_min` y `es_retraso` se calculan al registrar la llegada; nunca se capturan |
| RN-E3 | El estatus sigue RNP-08 y cada cambio queda en el historial con quién lo hizo |
| RN-E4 | No se registra llegada si el viaje no está EN_CURSO |
| RN-E5 | Los campos denormalizados preservan el dato histórico (§10.4) |
| RN-E6 | La causa de retraso solo se acepta si la entrega llegó retrasada |
| RN-E7 | La entrega hereda del viaje su ruta, vehículo, operador y fecha |

**Reglas del módulo de incidentes:**

| Regla | Qué impide |
|---|---|
| RN-I1 | El folio INC-AAAAMMDD-NNN lo genera el sistema |
| RN-I2 | No se registran incidentes sobre viajes cerrados |
| RN-I3 | La duración se calcula al cerrar, del inicio y el fin |
| RN-I4 | El recálculo de ETA solo alcanza a las entregas pendientes del viaje |
| RN-I5 | El recálculo escribe `hora_estimada_recalculada` y **nunca** pisa `hora_estimada_llegada` |
| RN-I6 | Cada recálculo deja constancia en `seguimiento_eventos` |

**Reglas del módulo de combustible:**

| Regla | Qué impide |
|---|---|
| RN-F1 | El folio CMB-AAAAMMDD-NNNN lo genera el sistema |
| RN-F2 | `costo_total` = litros × precio_por_litro; no se captura |
| RN-F3 | El tramo sale del odómetro de la carga anterior; en la primera carga queda null, no cero |
| RN-F4 | `rendimiento_km_l` = km del tramo / litros |
| RN-F5 | El odómetro no baja respecto de la carga anterior |
| RN-F6 | Los litros no superan la capacidad del tanque |
| RN-F7 | El combustible debe ser el de la unidad: no se le pone gasolina a un diésel |
| RN-F8 | La carga actualiza el odómetro del vehículo |

**Reglas del módulo de mantenimiento:**

| Regla | Qué impide |
|---|---|
| RN-M1 | El folio MTO-AAAAMMDD-NNNN lo genera el sistema |
| RN-M2 | PROGRAMADO → REALIZADO o VENCIDO, y VENCIDO → REALIZADO; de REALIZADO no se sale |
| RN-M3 | Una unidad no tiene dos servicios abiertos a la vez |
| RN-M4 | `duracion_dias` y `proximo_mantenimiento_fecha` se calculan, no se capturan |
| RN-M5 | Realizar el servicio escribe las fechas de mantenimiento del vehículo |
| RN-M6 | Un servicio vencido saca la unidad de operación; realizarlo la devuelve solo si no le quedan otros vencidos |
| RN-M7 | No se da por vencido un servicio antes de su fecha programada |

> **RN-M5 cierra la promesa de RN-V6.** La ficha del vehículo prohíbe capturar
> `fecha_ultimo_mantenimiento` y `fecha_proximo_mantenimiento` porque "se derivan
> de la colección `mantenimientos`". Este módulo es donde se derivan.
>
> La periodicidad de RNP-04 se aplica **por calendario** (30 días): es lo que la
> simulación implementó y sobre lo que se construyeron el DW y la variable
> `dias_desde_mantenimiento`. El documento recomendaba la opción (c) —lo primero
> entre calendario y kilometraje—; pasar a ella sería un cambio de regla que hay
> que acordar, no un ajuste de constante.

> **RN-I5 es la regla que protege a los modelos.** El retraso se mide como
> `real − hora_estimada_llegada`. Si un incidente sobrescribiera esa hora, la
> entrega parecería puntual justamente por el incidente que la retrasó, y los
> modelos perderían la señal que este módulo existe para darles.

> **El recálculo lineal es un supuesto declarado.** El §17.3 advierte que un
> incidente de 25 minutos podría no retrasar 25 minutos a la última parada del
> día. Se implementa como dice el documento y la respuesta del API lleva esa
> advertencia, para que la cifra no se tome por una certeza.

> **`PATCH /entregas/{id}/llegada` es el endpoint más importante del sistema.**
> Ahí nacen `retraso_min` y `es_retraso`, las dos variables que los modelos
> aprenden a predecir. Se derivan de las horas y nunca se capturan: los modelos
> deben aprender de lo que ocurrió, no de lo que alguien tecleó.

> **Viajes y entregas son las colecciones sin baja lógica.** El §11.5 establece que
> cada documento *es* el histórico y no se sobrescribe, así que un viaje no se
> borra: se cancela dejando constancia del motivo.

> **Cerrar un viaje actualiza el odómetro del vehículo.** Es donde se cumple la
> promesa de RN-V6, que prohíbe capturarlo desde la ficha del vehículo
> precisamente porque lo escribe este cierre. Y programar exige licencia
> vigente, con lo que RN-O3 deja de ser una restricción solo de pantalla.

**RN-04 (vehículo ↔ ruta) vale en los dos sentidos:** una ruta no puede tener
dos vehículos, y un vehículo no puede saltar de una ruta a otra sin liberarse
antes. Se implementa una sola vez, en el servicio de vehículos, y el endpoint
`/rutas/{id}/asignar-vehiculo` delega en él.

> **Nota ética (§11.3).** El endpoint `/operadores/{id}/desempenio` incluye en
> su respuesta la advertencia que pide el documento técnico: estas cifras
> describen el resultado de las rutas asignadas, no la capacidad personal del
> operador. El retraso depende sobre todo de la ruta, la franja horaria y los
> incidentes. Úsense para rediseñar rutas y turnos, no para evaluar personas.

Los endpoints de salud quedan abiertos a propósito: un monitor externo debe
poder comprobar que el servicio vive sin tener credenciales.

Prueba rápida con el servidor levantado:

```bash
# Endpoints públicos
curl http://127.0.0.1:8000/api/v1/salud
curl http://127.0.0.1:8000/api/v1/salud/mongodb

# Iniciar sesión: copia el valor de "access_token" de la respuesta
curl -X POST http://127.0.0.1:8000/api/v1/auth/login -d "username=admin&password=TU_CONTRASENA"

# Usarlo en los endpoints protegidos
TOKEN="pega-aqui-el-access_token"
curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8000/api/v1/auth/yo
curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8000/api/v1/diagnostico/colecciones
```

Desde **http://127.0.0.1:8000/docs** es más cómodo: el botón *Authorize* pide
usuario y contraseña, y adjunta el token en las peticiones siguientes.

---

## Capa analítica

Se ejecuta por línea de comandos y es independiente del servidor web. El orden
importa: cada etapa consume la salida de la anterior.

```bash
# 1 · Poblar la base con datos simulados (solo la primera vez)
python -m database.inicializar_bd
python -m database.seed.generar_catalogos
python -m database.seed.generar_operacion
python -m database.seed.reconciliar

# 2 · ETL completo: extracción → limpieza → transformación → carga del DW
python -m etl.run_etl

# 3 · Machine Learning
python -m ml.supervisado.clasificacion_retraso    # riesgo de retraso
python -m ml.supervisado.regresion_retraso        # minutos de retraso
python -m ml.no_supervisado.seleccion_k           # elección de k
python -m ml.no_supervisado.kmeans_rutas          # agrupamiento de rutas
python -m ml.no_supervisado.pca_rutas             # componentes y visualización

# 4 · Indicadores y dashboard
python -m analytics.kpis
python -m analytics.dashboard
```

Los reportes y las gráficas quedan en `data/outputs/`.

Análisis exploratorio, que se ejecuta aparte porque no forma parte del pipeline
productivo:

```bash
python -m etl.exploracion
```

---

## La capa analítica expuesta

Estos ocho endpoints **no reimplementan nada**. `/analitica/kpis` llama a
`analytics.kpis.calcular()`, que sigue siendo el único lugar donde los diez
indicadores están definidos; `/ml/*` carga los modelos ya entrenados desde
`ml/modelos_guardados/` y lee sus fichas de `modelos_ml`. Es la regla de la capa
8 (§7.3): quien muestra los datos **comunica e interpreta, no recalcula**.

Las tres consultas agregadas del §12.3 sí se resuelven en el servicio, con
agregaciones de MongoDB, porque no existían como función que devolviera cifras:
en `analytics/graficas.py` viven dentro de las funciones que dibujan. Para que
las dos vías no se separen, `tests/test_analitica.py` compara cifra por cifra la
salida de cada endpoint con lo que la gráfica correspondiente calcula en pandas
sobre los mismos datos.

**Reglas de la predicción:**

| Regla | Qué impide |
|---|---|
| RN-ML1 | No se predice sobre una entrega ya cerrada: su retraso está medido, no estimado |
| RN-ML2 | El escenario lo decide el estado del viaje, no quien llama |
| RN-ML3 | El vector se arma con las mismas variables y en el mismo orden con que se entrenó; si falta una, se falla en vez de rellenarla |
| RN-ML4 | La predicción se guarda en la entrega, y **nunca** toca `hora_estimada_llegada` |

> **RN-ML2 es la continuación de la prevención de fuga de §15.1.** Al entrenar se
> separaron dos escenarios: PLANEACION usa solo lo conocido al programar el
> viaje; EN_RUTA añade el retraso de salida y los incidentes. Mientras el viaje
> no haya salido esos datos no existen, así que pedir EN_RUTA sería inventarlos.
> Por eso el escenario no es un parámetro de la petición: lo determina el estado
> del viaje.
>
> EN_RUTA predice bastante mejor (ROC-AUC 0.92 contra 0.78, RMSE 9.3 contra
> 15.0), pero avisa más tarde. PLANEACION es el que deja margen para decidir, y
> ese margen es justamente lo que hace útil la predicción.

> **RN-ML4 es RN-I5 otra vez.** El retraso se mide contra
> `hora_estimada_llegada`. Si una predicción la moviera, la entrega parecería
> puntual por obra del modelo que advirtió lo contrario, y la variable objetivo
> de los modelos quedaría contaminada por sus propias salidas.

---

## Pruebas

```bash
python tests/test_conexion.py       # conexión, colecciones e índices
python tests/test_api.py            # backend base (14 pruebas)
python tests/test_autenticacion.py  # seguridad y roles (21 pruebas)
python tests/test_usuarios.py       # gestión de usuarios (28 pruebas)
python tests/test_clientes.py       # módulo clientes (27 pruebas)
python tests/test_vehiculos.py      # módulo vehículos (30 pruebas)
python tests/test_operadores.py     # módulo operadores (29 pruebas)
python tests/test_rutas.py          # módulo rutas (34 pruebas)
python tests/test_viajes.py         # módulo viajes (26 pruebas)
python tests/test_entregas.py       # módulo entregas (26 pruebas)
python tests/test_incidentes.py     # módulo incidentes (22 pruebas)
python tests/test_combustible.py    # módulo combustible (20 pruebas)
python tests/test_mantenimientos.py # módulo mantenimiento (21 pruebas)
python tests/test_analitica.py      # endpoints de analítica (11 pruebas)
python tests/test_ml.py             # endpoints de ML (15 pruebas)

# o con pytest
pytest tests/ -v
```

Cada módulo del ETL, ML y analytics imprime además sus propias verificaciones
automáticas al final de su ejecución.

---

## Estructura del proyecto

```
SIGLOG/
├── app.py           Punto de entrada (reexporta backend/main.py)
├── config/          Configuración y conexión única a MongoDB
├── backend/         API FastAPI (routers, services, repositories, schemas)
├── frontend/        Plantillas Jinja2 y estáticos (pendiente)
├── database/        Esquemas, índices y generador de datos simulados
├── etl/             Extracción, limpieza, transformación, enriquecimiento y carga
├── ml/              Modelos supervisados y no supervisados
├── analytics/       KPIs, gráficas y dashboard
├── data/            raw · processed · outputs (reportes y gráficas)
├── docs/            Documento técnico base
└── tests/           Pruebas y evidencias
```

La arquitectura del backend sigue el flujo en capas del documento técnico:

```
Frontend → FastAPI → Router → Service → Repository → MongoDB
```

y, para las funciones analíticas, reutiliza los módulos ya existentes en lugar
de duplicar su lógica:

```
Frontend → FastAPI → Service → analytics/ · ml/ → MongoDB → respuesta
```

---

## Estado del proyecto

| Componente | Estado |
|---|---|
| Base de datos, esquemas e índices | Completo |
| Datos simulados | Completo |
| ETL y data warehouse | Completo |
| Machine Learning supervisado y no supervisado | Completo |
| KPIs y dashboard | Completo |
| Backend base (API) | Completo |
| Autenticación y roles (JWT) | Completo |
| Gestión de usuarios y roles | Completo |
| Módulos del dominio: clientes, vehículos, operadores, rutas, viajes, entregas, incidentes, combustible, mantenimiento | Completo |
| Endpoints de analítica y ML | Completo |
| Frontend | Pendiente |
| Reportes PDF | Pendiente |

La documentación de diseño está en `docs/SIG-LOG_Documento_Tecnico_Base.md`.
