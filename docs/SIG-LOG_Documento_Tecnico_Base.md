# SIG-LOG — Sistema Integral de Gestión Logística
## DOCUMENTO TÉCNICO BASE (v1.0 — Fase 1: Análisis y Arquitectura)

**Materia:** Extracción del conocimiento en bases de datos
**Programa:** Ingeniería en Desarrollo y Gestión de Software — 9° cuatrimestre
**Institución:** Universidad Tecnológica del Valle de Toluca
**Periodo:** Mayo – Agosto 2026
**Fecha del documento:** 16 de agosto de 2026
**Versión:** 1.1
**Estado:** APROBADO EN LO ESENCIAL — decisiones D-01 a D-15 vigentes con los ajustes de la v1.1
**Regla de uso:** toda decisión posterior del proyecto debe compararse contra este documento. Si una decisión lo contradice, se actualiza este documento y se registra el cambio en el historial de versiones.

---

## AVISO CRÍTICO ANTES DE LEER

Al analizar la secuencia didáctica encontré fechas que cambian por completo la planeación:

| Evento | Fecha según secuencia didáctica |
|---|---|
| Examen Unidad IV | 31 de julio de 2026 |
| Examen Unidad V | 17 de agosto de 2026 |
| **Examen final (Unidades I–V)** | **18 de agosto de 2026** |
| Fecha de hoy | **16 de agosto de 2026** |

Si la entrega del proyecto coincide con el examen final, **quedan aproximadamente 2 días**, no semanas. Un plan de 19 fases no es ejecutable en ese plazo.

### DECISIONES CONFIRMADAS (v1.1 — 16/08/2026)

| # | Decisión | Consecuencia |
|---|---|---|
| **C-01** | **Fecha límite: 18 de agosto de 2026** | Se ejecuta el **Plan A** (§20.1). El Plan B queda archivado como referencia de evolución futura |
| **C-02** | **No existen datos reales de ninguna entidad.** El proyecto es 100% académico | El supuesto S-04 queda **confirmado como hecho**. Todo el contenido de la base será `origen_dato: "SIMULADO"`. Los parámetros de simulación se definen en el **Anexo B** |
| **C-03** | **Opción B del stack: pandas + NumPy + scikit-learn + Matplotlib** | **PySpark queda fuera del proyecto.** Las equivalencias que preservan la trazabilidad académica están en el **Anexo A** |

Estas tres decisiones modifican las secciones §5.3, §7.2, §8, §9, §13, §15, §16 y §20 de la v1.0. El texto ya está actualizado.

---

## 1. COMPRENSIÓN DEL PROBLEMA

### 1.1 Qué entiendo del negocio

Una empresa de transporte y distribución de mercancías opera una flotilla que realiza entregas diarias a clientes en distintos destinos. Hoy la información está dispersa en archivos y sistemas separados, lo que impide responder preguntas básicas de operación: qué rutas fallan, qué vehículos cuestan más, por qué se retrasan las entregas.

El problema real no es "no tener un CRUD". Es que **no existe una base de datos unificada que permita convertir la operación diaria en conocimiento para decidir**. Ese es exactamente el objeto de la materia: extraer conocimiento a partir de bases de datos.

### 1.2 Qué entiendo del sistema

SIG-LOG tiene dos naturalezas que conviven y que conviene no mezclar:

**a) Sistema transaccional (OLTP).** Registra la operación: clientes, vehículos, operadores, rutas, entregas, combustible, mantenimiento, incidentes. Escrituras frecuentes, documentos pequeños, consultas por identificador y por fecha. Vive en MongoDB Atlas.

**b) Sistema analítico (OLAP + ML).** Consume lo anterior, lo limpia, lo denormaliza, lo enriquece y produce: un dataset analítico, modelos de aprendizaje supervisado y no supervisado, y un dashboard. Vive en un proceso ETL separado y en colecciones/archivos analíticos.

La frontera entre ambos es el proceso ETL. Mantenerla explícita es lo que hace demostrable la Unidad II y lo que evita que el proyecto se convierta en "un CRUD con dos gráficas".

### 1.3 Cuál es la pregunta central del proyecto

Todo el sistema puede resumirse en una pregunta operativa:

> **¿Esta entrega va a llegar tarde, cuánto, y por qué?**

Y en una pregunta estratégica:

> **¿Qué rutas, vehículos y operadores se comportan igual entre sí, y cuáles son la excepción costosa?**

La primera es aprendizaje supervisado (Unidad III). La segunda es aprendizaje no supervisado (Unidad IV). Las dos requieren datos limpios (Unidad II) y se comunican mediante visualización (Unidad V). El encuadre metodológico completo es Unidad I.

Esta es la coherencia interna que hace que el proyecto no parezca cinco tareas pegadas con cinta.

### 1.4 Alcance académico (lo que SÍ y lo que NO)

**Dentro de alcance:**
- Modelado de datos operativos en MongoDB Atlas
- API y módulos CRUD para las 8 entidades obligatorias
- Proceso ETL documentado y ejecutable
- Modelo conceptual de Data Warehouse (estrella / copo de nieve)
- Modelos supervisado y no supervisado con evaluación y optimización
- Dashboard con interpretación de resultados
- Documentación y evidencias

**Fuera de alcance (salvo indicación contraria):**
- Rastreo GPS en tiempo real con hardware
- Optimización de rutas (VRP / vehicle routing problem)
- Integración con APIs de tráfico de pago
- Aplicación móvil para operadores
- Facturación, nómina, inventario de almacén

---

## 2. REQUERIMIENTOS CONSOLIDADOS

### 2.1 Requerimientos funcionales

| ID | Requerimiento | Módulo | Prioridad |
|---|---|---|---|
| RF-01 | Registrar, consultar, modificar y dar de baja clientes | Clientes | Alta |
| RF-02 | Registrar una o más direcciones de entrega por cliente | Clientes | Alta |
| RF-03 | Registrar, consultar, modificar y dar de baja vehículos | Vehículos | Alta |
| RF-04 | Consultar el estado operativo de un vehículo (disponible / en ruta / en mantenimiento) | Vehículos | Alta |
| RF-05 | Registrar, consultar, modificar y dar de baja operadores | Operadores | Alta |
| RF-06 | Registrar rutas con su secuencia ordenada de paradas | Rutas | Alta |
| RF-07 | Registrar distancia y tiempo estimado de traslado por tramo de ruta | Rutas | Alta |
| RF-08 | Asignar una ruta a un vehículo (relación 1 a 1) | Rutas / Vehículos | Alta |
| RF-09 | Registrar la ejecución diaria de una ruta (viaje/jornada) | Entregas | Alta |
| RF-10 | Registrar entregas con hora estimada y hora real de llegada | Entregas | Alta |
| RF-11 | Registrar el estatus de una entrega y su historial de cambios | Entregas | Alta |
| RF-12 | Registrar incidentes (tráfico, accidente, protesta, otros) asociados a una entrega o viaje | Incidentes | Alta |
| RF-13 | Registrar cargas de combustible con litros, costo y odómetro | Combustible | Alta |
| RF-14 | Calcular rendimiento (km/l) y costo por kilómetro por vehículo | Combustible | Alta |
| RF-15 | Registrar mantenimientos realizados y programados | Mantenimiento | Alta |
| RF-16 | Alertar qué vehículos requieren mantenimiento según periodicidad | Mantenimiento | Media |
| RF-17 | Ejecutar un proceso ETL que genere el dataset analítico | ETL | Alta |
| RF-18 | Detectar y tratar valores nulos, duplicados y atípicos | ETL | Alta |
| RF-19 | Generar variables derivadas (retraso, duración real, franja horaria, día de semana) | ETL | Alta |
| RF-20 | Entrenar y evaluar un modelo de regresión sobre el tiempo/retraso de entrega | ML supervisado | Alta |
| RF-21 | Entrenar y evaluar un modelo de clasificación de riesgo de retraso | ML supervisado | Alta |
| RF-22 | Reportar MSE, RMSE, MAE y R² del modelo de regresión | ML supervisado | Alta |
| RF-23 | Agrupar rutas similares mediante K-Means | ML no supervisado | Alta |
| RF-24 | Determinar el número óptimo de grupos (método del codo e índice de silueta) | ML no supervisado | Alta |
| RF-25 | Aplicar PCA para visualización y diagnóstico de correlación entre variables | ML no supervisado | Media |
| RF-26 | Persistir los resultados de los modelos (predicciones, clusters, métricas) | ML | Media |
| RF-27 | Generar el conjunto de gráficas del dashboard | Reportes | Alta |
| RF-28 | Mostrar indicadores (KPI) de operación en el dashboard | Reportes | Alta |
| RF-29 | Emitir una interpretación textual automática de cada resultado analítico | Reportes | Media |
| RF-30 | Exportar datasets y resultados a CSV/JSON | ETL / Reportes | Media |
| RF-31 | Generar un conjunto de datos históricos simulados, claramente etiquetados como tales | Datos | Alta |
| RF-32 | Registrar cambios e incidencias sobre una ruta en ejecución | Seguimiento | Media |
| RF-33 | Recalcular el tiempo estimado de llegada (ETA) al registrarse un incidente | Seguimiento | Media |

### 2.2 Requerimientos no funcionales

| ID | Requerimiento | Justificación |
|---|---|---|
| RNF-01 | El backend se implementa en Python | Requisito del proyecto y coherencia con la materia |
| RNF-02 | La base de datos operativa es MongoDB Atlas | Requisito del proyecto; ya usado en clase |
| RNF-03 | Las credenciales se manejan mediante archivo `.env`, nunca en código | Práctica ya establecida en los ejercicios de clase |
| RNF-04 | El código debe ser legible y comentado con fines didácticos | El profesor evalúa comprensión, no solo funcionamiento |
| RNF-05 | Cada resultado analítico debe ser interpretable, no solo numérico | La secuencia didáctica exige "interpretación de resultados" en U-III, U-IV y U-V |
| RNF-06 | Los datos simulados deben ser distinguibles de los datos reales a nivel de dato | Regla explícita del proyecto |
| RNF-07 | El proyecto debe entregarse en un repositorio | Exigido en el resultado de aprendizaje de U-II, U-III, U-IV y U-V |
| RNF-08 | La ejecución debe ser reproducible en otra máquina siguiendo el manual técnico | Evidencia de funcionamiento |
| RNF-09 | El sistema debe funcionar sin conexión a servicios externos de pago | Restricción académica y de costo |
| RNF-10 | Los procesos ETL y ML deben poder ejecutarse de forma independiente del API | Separación de responsabilidades |

### 2.3 Reglas de negocio CONFIRMADAS

| ID | Regla | Fuente |
|---|---|---|
| RN-01 | Existe una cantidad determinada de vehículos en la flotilla | Requerimiento del usuario |
| RN-02 | Existe una cantidad determinada de clientes | Requerimiento del usuario |
| RN-03 | Un vehículo puede entregar mercancía a diferentes clientes | Requerimiento del usuario |
| RN-04 | Cada vehículo tiene asignada **una sola ruta** | Requerimiento del usuario |
| RN-05 | Una ruta puede tener múltiples entregas | Requerimiento del usuario |
| RN-06 | Las entregas dependen del tiempo de traslado | Requerimiento del usuario |
| RN-07 | El tiempo real de entrega puede verse afectado por tráfico, accidentes, protestas u otros incidentes | Requerimiento del usuario |
| RN-08 | Debe existir información suficiente para analizar el rendimiento de los vehículos | Requerimiento del usuario |
| RN-09 | El consumo de combustible debe registrarse y poder analizarse posteriormente | Requerimiento del usuario |
| RN-10 | El modelado prioritario inicial es: vehículos, clientes, rutas y tiempo de traslado | Requerimiento del usuario |

### 2.4 Reglas de negocio PENDIENTES DE DEFINICIÓN

Cada una incluye opciones para que decidas. Ninguna se aplicará hasta que la confirmes.

| ID | Regla pendiente | Opciones propuestas |
|---|---|---|
| RNP-01 | ¿A partir de cuántos minutos una entrega se considera "retrasada"? | (a) >0 min; (b) >15 min; (c) >30 min; (d) >10% del tiempo estimado |
| RNP-02 | ¿Un vehículo cambia de ruta alguna vez? Si la asignación es fija, ¿cómo se registra un cambio histórico? | (a) asignación fija e inmutable; (b) asignación con vigencia (fecha_inicio/fecha_fin) — **recomendada** |
| RNP-03 | ¿Un operador está asignado a un vehículo fijo, o rota? | (a) fijo; (b) rota por jornada — **recomendada, más realista y genera más datos para ML** |
| RNP-04 | Periodicidad de mantenimiento: ¿mensual por calendario o por kilometraje? | (a) cada 30 días; (b) cada N km; (c) lo primero que ocurra — **recomendada** |
| RNP-05 | ¿Qué tipos de mantenimiento existen (preventivo, correctivo, ambos)? | (a) solo preventivo; (b) preventivo + correctivo — **recomendada** |
| RNP-06 | ¿Una ruta se ejecuta todos los días, ciertos días, o bajo demanda? | (a) diaria; (b) días fijos de la semana; (c) bajo demanda |
| RNP-07 | ¿Qué "servicios" ofrece la empresa? (el dashboard pide "servicio con mayor demanda") | Pendiente: se requiere el catálogo de servicios o eliminar el indicador |
| RNP-08 | ¿Una entrega puede fallar/no entregarse? ¿Qué estatus existen? | Propuesta: PROGRAMADA → EN_RUTA → ENTREGADA / NO_ENTREGADA / CANCELADA |
| RNP-09 | ¿El combustible se carga por vehículo o por jornada? | (a) evento independiente por carga — **recomendada**; (b) atado a la jornada |
| RNP-10 | ¿Se registra el odómetro en cada carga de combustible? | Necesario para calcular km/l. Si no se registra, el rendimiento no es calculable |
| RNP-11 | ¿El sistema requiere usuarios y autenticación? | (a) sin autenticación (académico); (b) con roles Admin/Despachador/Consulta — **recomendada solo si hay tiempo** |
| RNP-12 | ¿Qué causas de retraso son válidas como catálogo cerrado? | Propuesta base: TRAFICO, ACCIDENTE, PROTESTA, CLIMA, FALLA_VEHICULO, CLIENTE_AUSENTE, OTRO |
| RNP-13 | ¿Se manejan ventanas horarias de entrega comprometidas con el cliente? | (a) no; (b) sí (afecta directamente la definición de "retraso") |
| RNP-14 | ¿Un incidente afecta a una entrega, a todo un viaje, o a una ruta completa? | Propuesta: se registra a nivel viaje y se propaga a las entregas posteriores del viaje |

### 2.5 SUPUESTOS (no son reglas de negocio)

Marcados explícitamente. Se convertirán en reglas **solo** si los confirmas.

| ID | Supuesto | Impacto si es falso |
|---|---|---|
| S-01 | La operación es local/regional (Valle de Toluca y alrededores), no nacional | Cambia rangos de distancia y tiempos; no cambia el modelo |
| S-02 | Cada ruta se ejecuta una vez por día como máximo | Si hay varias vueltas, se requiere numerar la jornada |
| S-03 | Todos los vehículos son de carga terrestre similares entre sí | Si hay tipos muy distintos (camioneta vs tráiler), se requiere `tipo_vehiculo` como dimensión |
| S-04 | Los datos históricos no existen aún y deberán simularse para entrenar | Si existen datos reales, cambia toda la estrategia de datos (§16) |
| S-05 | Un cliente tiene una dirección de entrega principal | Si tiene varias sucursales, ya está previsto: direcciones embebidas |
| S-06 | El costo de combustible es el principal costo variable modelado | Si hay casetas/peajes, se requiere agregarlos como campo |
| S-07 | No hay integración con un sistema de facturación existente | Si la hay, aparece una fuente de datos externa en el ETL |

---

## 3. ACTORES DEL SISTEMA

Propongo **cuatro actores**, no más. Añadir actores que no ejecutan acciones distintas solo infla el documento.

| Actor | Descripción | Acciones principales | ¿Necesario? |
|---|---|---|---|
| **Administrador / Coordinador logístico** | Gestiona catálogos y configuración | Alta/baja de clientes, vehículos, operadores y rutas; asignación vehículo↔ruta | Sí — actor principal |
| **Despachador / Capturista** | Opera el día a día | Registra jornadas, entregas, horas reales, incidentes, cargas de combustible | Sí |
| **Analista / Directivo** | Consume conocimiento | Ejecuta ETL, entrena modelos, consulta dashboard e interpreta resultados | Sí — es el actor que justifica la materia |
| **Sistema (proceso automatizado)** | Actor no humano | Ejecuta ETL, calcula campos derivados, recalcula ETA, genera predicciones | Sí — modelarlo explícitamente aclara qué es automático |

**Actor descartado:** *Operador/Conductor* como usuario del sistema. Requeriría app móvil, que está fuera de alcance. El operador es una **entidad de datos**, no un usuario. Si más adelante quieres que capture entregas desde su teléfono, eso es la mejora futura MF-03 (§17.4).

---

## 4. MÓDULOS DEL SISTEMA

### 4.1 Los ocho módulos obligatorios

| # | Módulo | Propósito | Depende de |
|---|---|---|---|
| M1 | Clientes | Catálogo de clientes y direcciones de entrega | — |
| M2 | Vehículos | Catálogo de flotilla y su estado operativo | — |
| M3 | Operadores | Catálogo de conductores | — |
| M4 | Rutas | Definición de rutas, paradas, distancias y tiempos estimados | M1, M2 |
| M5 | Entregas | Ejecución diaria: jornadas y entregas con tiempos reales | M1–M4 |
| M6 | Combustible | Cargas, litros, costos, odómetro, rendimiento | M2 |
| M7 | Mantenimiento | Programación e historial de servicios | M2 |
| M8 | Reportes y Análisis | Dashboard, KPIs, gráficas, resultados de ML | Todos |

### 4.2 Módulos adicionales que el análisis determina necesarios

| # | Módulo | Por qué es necesario | ¿Podría omitirse? |
|---|---|---|---|
| M9 | **Incidentes** | RN-07 es una regla confirmada: tráfico, accidentes y protestas afectan el tiempo. Sin esta entidad no existe la variable predictora más importante del modelo de retraso. Es la diferencia entre un modelo que predice y uno que adivina | **No.** Es requisito funcional de ML |
| M10 | **ETL / Preparación de datos** | Es un módulo ejecutable, no documentación. Es la evidencia central de la Unidad II | **No.** Sin él no hay Unidad II |
| M11 | **Machine Learning** | Entrenamiento, evaluación y persistencia de modelos. Evidencia de U-III y U-IV | **No** |
| M12 | **Seguimiento dinámico de rutas** | Solicitado explícitamente. Modelado conceptual en §17 | Parcialmente: núcleo sí, GPS no |
| M13 | **Generación de datos (semillas)** | Sin datos históricos no hay ML entrenable. Debe ser un módulo separado y explícito para no contaminar datos reales | **No**, dado el supuesto S-04 |

**Decisión de diseño:** *Incidentes* es módulo propio, no un subcampo de *Entregas*. Justificación: un incidente (una protesta en una avenida) afecta a **varias** entregas simultáneamente. Si lo embebo en la entrega, duplico el hecho y pierdo la capacidad de contarlo una sola vez.

---

## 5. ANÁLISIS DE LOS EJERCICIOS DE CLASE

Analicé los 54 archivos del profesor. Este análisis es la base de todas las decisiones técnicas que siguen: **si el profesor lo enseñó, se usa; si no lo enseñó, se justifica o se descarta.**

### 5.1 Matriz de análisis de archivos

| Archivo | Unidad | Tema | Técnica utilizada | Biblioteca | Ejemplo realizado | Aplicación posible en SIG-LOG |
|---|---|---|---|---|---|---|
| `unidad1_basico.py` | I | Exploración de datos | DataFrame, `info()`, nulos, estadísticos | pandas, numpy | Inventario Eco Mart | Exploración inicial del dataset de entregas |
| `unidad1_estructura.py` | I | Código estructurado | Funciones (`cargar_datos()`), separación de responsabilidades | pandas, numpy | Inventario estructurado | Patrón de organización de los scripts de ETL y ML |
| `unidad1_spark.py` | I | Análisis de columnas y valores | Esquema explícito, `printSchema`, `describe`, nulos, `approxQuantile` (mediana), `fillna`, filtro de riesgo, export CSV | PySpark | Riesgo de desabasto Eco Mart | **Base directa del ETL:** análisis de columnas, imputación por mediana y exportación |
| `01_practica_seguridad_III.py` | I/II | Agregación y filtrado | `groupBy`, `agg`, `count`, `filter` | PySpark | Intentos de login fallidos | Conteo de retrasos por ruta / vehículo |
| `02_practica_seguridad_frecuencia_III.py` | I/II | Frecuencias | `filter` + `groupBy` + `count` | PySpark | Fuerza bruta por IP | Frecuencia de incidentes por ruta |
| `03_practica_seguridad_usuarios_III.py` | I/II | Clasificación por reglas | `when().otherwise()` para nivel de riesgo | PySpark | Riesgo de usuarios | **Etiquetado de riesgo de retraso** por reglas antes de ML |
| `01_practica_IOT_IV.py` | I/II | Métricas por grupo | `avg`, `max`, `min` | PySpark | Sensores IoT | Métricas de tiempo por ruta |
| `02_practica_IOT_estadisticas_IV.py` | I/II | Estadística descriptiva | `avg`, `max`, `min`, `stddev` | PySpark | Temperatura por sensor | Variabilidad del tiempo de traslado por ruta |
| `03_practica_IOT_consumo_IV.py` | I/II | Suma y alertas por umbral | `sum` + `filter` | PySpark | Consumo kWh | **Consumo de combustible por vehículo + alertas** |
| `generar_datos_insertone.py` | II | Carga de datos | `.env`, `quote_plus`, `insert_one` | pymongo, dotenv | Ventas aleatorias | Patrón de conexión segura a Atlas (reutilizable tal cual) |
| `generar_datos2_insertmany.py` | II | Carga masiva | `insert_many` | pymongo | Ventas en lote | **Generador de datos históricos simulados** |
| `generar_datos_fechas.py` | II | Datos temporales | `datetime`, `timedelta`, fechas aleatorias | pymongo | Ventas con fecha | **Generación de la serie histórica de entregas** |
| `spark_test_mongoconexion.py` | II | Prueba de conexión | `list_database_names()` | pymongo | Verificación | Script de verificación de entorno |
| `spark_test_array.py` | II | Prueba de Spark | `spark.range()` | PySpark | Verificación | Script de verificación de entorno |
| `spark_processing_cargadatos.py` | II | Lectura Spark↔Mongo | Conector `mongo-spark-connector` | PySpark | Carga de ventas | **Extracción del ETL** |
| `spark_processingconsulta2.py` | II | Agregación distribuida | `groupBy` + `sum`/`avg` | PySpark | Ventas agregadas | Agregaciones del dataset analítico |
| `processing_consulta_ventas.py` | II | Agregación nativa Mongo | Pipeline `$group` | pymongo | Ventas por producto | **Agregaciones del API** (KPIs sin Spark) |
| `processing_consulta_ventas_valida.py` | II | Agregación validada | Pipeline con validaciones | pymongo | Ventas validadas | Consultas del dashboard con manejo de errores |
| `mongo_spark_conexion_sinnulos.py` | II | **ETL completo** | Conexión + `select`/`cast` + `dropna` + variable derivada (`ingreso = cantidad × precio`) + `VectorAssembler(handleInvalid="skip")` | PySpark | Pipeline de ventas | **Plantilla exacta del ETL de SIG-LOG.** Es el archivo más importante del conjunto |
| `01_mapreduce.py` | II | MapReduce | `groupBy` + `sum` distribuido | PySpark | Ventas por producto | Agregación de entregas por ruta |
| `01_mapreduce_analytics_connulos.py` | II | MapReduce con datos sucios | Igual, pero sin limpieza previa | PySpark, matplotlib | Demostración del problema | **Evidencia comparativa de limpieza (antes)** |
| `01_mapreduce_analytics_sinnulos.py` | II | MapReduce con datos limpios | Igual + `interpretar_mapreduce()` | PySpark, matplotlib, pandas | Demostración de la solución | **Evidencia comparativa de limpieza (después)** + patrón de interpretación automática |
| `03_regresion_analytics.py` | III | **Comparación de regresiones** | `randomSplit([0.8,0.2], seed=42)`, LinearRegression simple/múltiple, Ridge (`regParam`), Lasso (`elasticNetParam`), `PolynomialExpansion`, `CrossValidator` + `ParamGridBuilder`, `RegressionEvaluator` (rmse, mae, r2), selección del mejor modelo | PySpark ML | 6 modelos sobre ventas | **Plantilla exacta del modelo supervisado de regresión de SIG-LOG** |
| `03_regresion_analytics_graficos.py` | III/V | Regresión + visualización | Igual + `matplotlib.use("Agg")` + gráficas real vs predicho | PySpark ML, matplotlib | Modelos graficados | Gráfica real vs predicho del retraso |
| `regresion_analytics_graficos_dash.py` | V | Dashboard interactivo | `px.scatter`, `px.histogram` | plotly | Dashboard de ventas | Alternativa interactiva del dashboard (opcional) |
| `04_decision_tree.py` | III | Clasificación | `DecisionTreeClassifier`, `MulticlassClassificationEvaluator` | PySpark ML | Venta alta/baja | **Clasificación de riesgo de retraso** |
| `04_arboldedecision.py` | III | Clasificación con etiqueta derivada | `when(col > umbral, 1).otherwise(0)` + árbol | PySpark ML | Etiqueta por umbral | **Creación de la etiqueta `es_retraso` a partir del umbral RNP-01** |
| `05_bosque_aleatorio.py` | III | Ensamble | `Pipeline`, `RandomForestClassifier`, `BinaryClassificationEvaluator`, `fillna` | PySpark ML | Categoría de venta | Modelo de clasificación mejorado + importancia de variables |
| `07_red_neural.py` | III | Deep learning | Red neuronal | PySpark + PyTorch | Predicción | **No se usará.** Fuera de la secuencia didáctica; agrega dependencia pesada sin aportar a la evaluación |
| `u4distanciaeuclidiana1.py` | IV | Fundamento de K-Means | Distancia euclidiana paso a paso, sin sklearn | numpy | Clientes (edad, gasto) | Explicación de la métrica de similitud entre rutas |
| `u4kmeanscalculos2.py` | IV | K-Means manual | Implementación desde cero, iteraciones y centroides | numpy, matplotlib | Clientes | Demostración de comprensión del algoritmo |
| `u4comparacionkmeans3.py` | IV | K-Means con librería | `KMeans(n_clusters, random_state=42, n_init=10)` | scikit-learn | Comparación manual vs sklearn | **Agrupación de rutas de SIG-LOG** |
| `unidad4.py` / `u4inerciametodocodo4.py` | IV | Método del codo | WCSS/inercia para k = 1..n | scikit-learn, matplotlib | Selección de k | **Selección del número de grupos de rutas** |
| `u4indicesilueta5.py` | IV | Evaluación de clustering | `silhouette_score` + cálculo manual | scikit-learn | Validación de k | **Evaluación del modelo no supervisado** (exigido por la U-IV) |
| `u4pcavarianzaexplicada6.py` | IV | PCA | `StandardScaler` + `PCA` + varianza explicada + KMeans sobre componentes | scikit-learn, matplotlib | Reducción a 2D | **PCA sobre variables de rutas/vehículos + visualización de clusters** |
| `02_kmeans.py` | IV | K-Means distribuido | `pyspark.ml.clustering.KMeans` + `ClusteringEvaluator` | PySpark ML | Clustering de ventas | Alternativa distribuida del clustering |
| `02_kmeans_analytics.py` | IV/V | Clustering + interpretación | KMeans + `groupBy(prediction).agg(avg)` + gráfica 3D + `interpretar_clusters()` | PySpark ML, matplotlib | Perfilado de clusters | **Perfilado e interpretación de los grupos de rutas** |
| `06_pca.py` | IV | PCA distribuido | `StandardScaler` + `PCA(k=2)` + `explainedVariance` + KMeans | PySpark ML | PCA + clusters | Variante distribuida de PCA |
| `graficas1.py` | V | Gráfica de líneas | `plt.plot` | matplotlib | Serie mensual | Evolución de entregas / retrasos por mes |
| `graficas2.py` | V | Personalización | Estilos, ejes, leyendas, anotaciones | matplotlib | Línea personalizada | Estándar visual del dashboard |
| `graficas3.py` | V | Teoría del color | Paletas profesionales | matplotlib, seaborn | Comparación de paletas | Paleta institucional del dashboard |
| `graficas4.py` | V | Barras | `plt.bar` | matplotlib | Ventas por sucursal | Entregas por operador / ruta |
| `graficas5.py` | V | Barras agrupadas | Barras múltiples por categoría | matplotlib | Sucursales del Valle de Toluca | Comparación estimado vs real por ruta |
| `graficas6.py` | V | Histograma | `sns.histplot` | seaborn | Distribución EDA | **Distribución del retraso en minutos** |
| `graficas7.py` | V | Histograma avanzado | Media, mediana, moda (`scipy.stats.mode`) | seaborn, scipy | EDA avanzado | Distribución con tendencia central del tiempo de traslado |
| `graficas8.py` | V | BoxPlot | `sns.boxplot` | seaborn | Comparación de grupos | **Retraso por ruta / por vehículo (detección de outliers)** |
| `graficas9.py` | V | Violin + Box + Strip | Composición de gráficas | seaborn | Distribución detallada | Distribución de tiempos por franja horaria |
| `graficas10db.py` | V | Dashboard estadístico | `plt.subplots` multipanel | matplotlib, seaborn | Dashboard básico | Estructura del dashboard |
| `graficas11db.py` | V | **Dashboard analítico 2×3** | 6 paneles: histograma, boxplot, violín, KDE, ECDF | matplotlib, seaborn | EDA completo | **Plantilla directa del dashboard de SIG-LOG** |
| `graficas12db.py` | V | Dashboard ejecutivo | Asimetría (`skew`) y curtosis (`kurtosis`) | seaborn, scipy | Dashboard directivo | Panel ejecutivo de KPIs logísticos |
| `graficas13cuartiles.py` | V / II | Outliers por IQR | Q1, Q3, IQR, límites 1.5·IQR, filtrado | pandas, seaborn | Salarios con outliers | **Limpieza avanzada: eliminación de tiempos atípicos en el ETL** |

### 5.2 Matriz de reutilización

| Ejercicio de clase | Concepto aprendido | Aplicación en SIG-LOG | Módulo | ¿Se reutiliza / adapta? | Motivo |
|---|---|---|---|---|---|
| `mongo_spark_conexion_sinnulos.py` | Conexión + limpieza + features | Núcleo del pipeline de extracción y transformación | ETL | **Se adapta** | Cambian las columnas (entregas en lugar de ventas); la estructura se conserva íntegra |
| `generar_datos_fechas.py` + `generar_datos2_insertmany.py` | Generación e inserción masiva con fechas | Generador de histórico simulado de entregas | Datos | **Se adapta** | Es exactamente el mecanismo que necesitamos para tener datos entrenables |
| `unidad1_spark.py` | Análisis de columnas, mediana con `approxQuantile`, `fillna`, export CSV | Limpieza básica del ETL y exploración inicial | ETL | **Se reutiliza** | Cubre literalmente los temas "análisis de columnas" y "valores de análisis" de U-I |
| `graficas13cuartiles.py` | Detección de outliers por IQR | Limpieza avanzada de tiempos de traslado atípicos | ETL | **Se reutiliza** | Es la técnica de limpieza avanzada exigida por U-II |
| `01_mapreduce_analytics_connulos/sinnulos.py` | Efecto de los nulos en el resultado | Evidencia comparativa de calidad de datos | ETL / Reportes | **Se adapta** | Genera una evidencia muy valiosa: mismo análisis, con y sin limpieza |
| `03_regresion_analytics.py` | Comparación de 6 modelos y selección del mejor | Predicción del retraso en minutos | ML supervisado | **Se adapta** | El profesor evalúa "justificación del algoritmo": comparar modelos ES la justificación |
| `04_arboldedecision.py` | Etiqueta binaria por umbral con `when()` | Creación de `es_retraso` | ML supervisado | **Se reutiliza** | Método idéntico, cambia el umbral (RNP-01) |
| `05_bosque_aleatorio.py` | Pipeline + ensamble + evaluador binario | Clasificación de riesgo de retraso | ML supervisado | **Se adapta** | Aporta importancia de variables → responde "¿cuáles son las causas de retraso?" |
| `u4comparacionkmeans3.py` | K-Means con sklearn | Agrupación de rutas similares | ML no supervisado | **Se adapta** | Cambian las variables (distancia, tiempo, entregas, retrasos) |
| `u4inerciametodocodo4.py` | Método del codo | Selección del número de grupos de rutas | ML no supervisado | **Se reutiliza** | Justificación obligatoria del valor de k |
| `u4indicesilueta5.py` | Índice de silueta | Evaluación del clustering | ML no supervisado | **Se reutiliza** | U-IV exige "reporte de evaluación" del modelo |
| `u4pcavarianzaexplicada6.py` | PCA + varianza explicada | Reducción y visualización de clusters | ML no supervisado | **Se adapta** | Con >2 variables, es la única forma de graficar los grupos |
| `u4distanciaeuclidiana1.py` + `u4kmeanscalculos2.py` | Fundamento matemático | Sección explicativa del manual técnico | Documentación | **Se reutiliza como explicación** | Demuestra comprensión, no solo uso de librería |
| `02_kmeans_analytics.py` | Perfilado e interpretación de clusters | Descripción de cada grupo de rutas | ML / Reportes | **Se adapta** | Convierte números en conocimiento accionable |
| `graficas11db.py` | Dashboard 2×3 | Estructura del dashboard analítico | Reportes | **Se adapta** | Plantilla lista; solo cambian los datos |
| `graficas12db.py` | Dashboard ejecutivo con skew/kurtosis | Panel de KPIs directivos | Reportes | **Se adapta** | Aporta el nivel "toma de decisiones" |
| `graficas4/5/6/8/9.py` | Barras, agrupadas, histograma, box, violín | Gráficas específicas del dashboard | Reportes | **Se reutiliza** | Cada pregunta del dashboard mapea a uno de estos tipos |
| `processing_consulta_ventas.py` | Pipeline `$group` de MongoDB | KPIs del API sin levantar Spark | API / Reportes | **Se adapta** | Los KPIs simples no justifican arrancar Spark |
| `03_practica_seguridad_usuarios_III.py` | Clasificación por reglas con `when()` | Nivel de riesgo de ruta antes del ML | ETL | **Se adapta** | Línea base contra la cual comparar el modelo |
| `03_practica_IOT_consumo_IV.py` | Suma + alerta por umbral | Alerta de consumo anómalo de combustible | Combustible | **Se adapta** | Patrón idéntico, cambia la magnitud |
| `07_red_neural.py` | Red neuronal con PyTorch | — | — | **NO se usa** | No está en la secuencia didáctica; agrega una dependencia pesada sin aportar a la evaluación |
| `regresion_analytics_graficos_dash.py` | Plotly/Dash | Dashboard interactivo | Reportes | **Opcional** | Solo si sobra tiempo; matplotlib ya cubre el requisito |

### 5.3 Conclusiones del análisis de ejercicios

Cinco hallazgos que condicionan todo el diseño:

1. **La clase trabajó con PySpark de forma dominante en las Unidades II y III.** Por decisión C-03 el proyecto usará pandas + scikit-learn. Esto **no rompe la trazabilidad** siempre que cada técnica de clase tenga su equivalente explícito y documentado: `groupBy/agg` → `groupby/agg`; `approxQuantile` → `quantile`; `VectorAssembler` → matriz de features; `randomSplit` → `train_test_split`; `RegressionEvaluator` → `sklearn.metrics`. La tabla completa está en el **Anexo A** y debe incluirse en el manual técnico.

2. **Ya existe una plantilla de ETL probada contra MongoDB Atlas.** `mongo_spark_conexion_sinnulos.py` hace exactamente el flujo que necesitamos: leer de Atlas → castear tipos → eliminar nulos → crear variable derivada → vectorizar. No hay que inventar el ETL; hay que adaptarlo.

3. **La Unidad IV se enseñó íntegramente con scikit-learn** (`u4comparacionkmeans3.py`, `u4inerciametodocodo4.py`, `u4indicesilueta5.py`, `u4pcavarianzaexplicada6.py`). Por lo tanto la Unidad IV se implementa **exactamente como en clase, sin adaptación alguna**. La Unidad III se enseñó con Spark ML y se traduce a scikit-learn conservando la misma estructura de comparación de modelos (Anexo A).

4. **El profesor valora la interpretación automática.** Varios ejercicios incluyen funciones (`interpretar_mapreduce`, `interpretar_clusters`) que traducen números a frases. La secuencia didáctica lo confirma: U-III, U-IV y U-V piden "descripción de resultados" e "interpretación". SIG-LOG debe incluir esta capa (RF-29). Es barata de implementar y muy visible en la evaluación.

5. **seaborn y scipy sí son bibliotecas de clase.** Aparecen en `graficas3`, `graficas6`–`graficas13`. No violan la regla de "no agregar bibliotecas innecesarias": son parte del material del curso.

---

## 6. MATRIZ DE LAS CINCO UNIDADES

| Unidad | Tema visto en clase | Aplicación posible en SIG-LOG | Aplicación propuesta | Evidencia requerida |
|---|---|---|---|---|
| **I** | Conceptos de IA | Encuadre del proyecto | Sección del manual técnico: qué es y qué no es IA en SIG-LOG | Documento comparativo IA/ML/DM/Big Data |
| **I** | Big Data | Naturaleza de los datos logísticos | Justificación del uso de PySpark y de por qué el volumen actual no es Big Data (honestidad técnica) | Sección del manual técnico |
| **I** | Aplicaciones de IA y Big Data | Casos del sector transporte | Tabla de casos de aplicación logística | Documento de U-I |
| **I** | Procesamiento de datos | Flujo completo del sistema | Diagrama de arquitectura de datos (§7) | Diagrama + descripción |
| **I** | Entrada de datos | Captura operativa | Módulos CRUD + generador de datos simulados | API funcionando + colecciones pobladas |
| **I** | Preparación de datos | Antesala del ETL | Casting, tipado y esquema de validación en MongoDB | `docs/modelo_datos.md` + validadores |
| **I** | Exploración de datos | EDA del dataset de entregas | Script de exploración con `printSchema`, `describe`, conteo de nulos (patrón de `unidad1_spark.py`) | `notebooks/` o `etl/exploracion.py` + salida |
| **I** | Enriquecimiento de datos | Variables derivadas | `retraso_min`, `duracion_real_min`, `dia_semana`, `franja_horaria`, `km_por_litro` | Dataset analítico con columnas nuevas |
| **I** | Data Science / Business Intelligence | Capa analítica | Separación explícita OLTP vs OLAP; dashboard como capa BI | Arquitectura + dashboard |
| **I** | Generación de informes | Reportes del sistema | Módulo de reportes + interpretación automática (RF-29) | Reportes generados |
| **I** | Optimización | Mejora de procesos y modelos | Índices de MongoDB; CrossValidator en regresión; selección de k en K-Means | Reporte de optimización |
| **I** | Metodologías para el análisis | Método de trabajo | Adopción de **CRISP-DM** mapeado a las 5 unidades (§7.4) | Documento de planificación |
| **I** | Planificación del análisis | Plan del proyecto | Plan de desarrollo incremental (§20) | Este documento |
| **I** | Visión general de los datos de origen | Inventario de fuentes | Tabla de fuentes de datos (§13.1) | Documento de U-II |
| **I** | Análisis de columnas | Perfilado de columnas | Tabla por colección: tipo, nulos, rango, cardinalidad, valores únicos | Reporte de perfilado |
| **I** | Valores de análisis | Estadísticos por variable | `describe()` + media/mediana/moda/desviación por variable clave | Salida del script de exploración |
| **II** | Tipos y fuentes de datos | Clasificación de los datos del sistema | Estructurados (colecciones), semiestructurados (JSON de incidentes, arrays anidados), no estructurados (observaciones de texto libre del operador) | Tabla de clasificación (§13.1) |
| **II** | Datos estructurados | Colecciones con esquema | `vehiculos`, `clientes`, `operadores` | Modelo de datos |
| **II** | Datos semiestructurados | Documentos anidados | `rutas.paradas[]`, `entregas.historial_estatus[]` | Modelo de datos |
| **II** | Datos no estructurados | Texto libre | `incidentes.descripcion`, `entregas.observaciones` | Modelo de datos + tratamiento en ETL |
| **II** | Modelo estrella | Diseño del DW | `hecho_entrega` + 5 dimensiones (§14.2) | Diagrama estrella |
| **II** | Modelo copo de nieve | Normalización de dimensiones | `dim_ruta → dim_zona`; `dim_vehiculo → dim_tipo_vehiculo → dim_marca` (§14.3) | Diagrama copo de nieve + comparación |
| **II** | Limpieza básica | Nulos, tipos, duplicados | `dropna` / `fillna` con mediana vía `approxQuantile`; casting; eliminación de duplicados | Script ETL + reporte antes/después |
| **II** | Limpieza avanzada | Outliers y consistencia | IQR (patrón `graficas13cuartiles.py`) sobre `tiempo_real_min`; validación de rangos; coherencia de fechas | Script ETL + gráfica de outliers |
| **II** | Minería de datos | Diagrama del proceso | Diagrama del proceso de minería aplicado a SIG-LOG | Documento de U-II |
| **II** | Conjuntos de datos | Datasets del proyecto | `dataset_entregas`, `dataset_rutas`, `dataset_vehiculos` | Archivos en `data/processed/` |
| **II** | ETL — Extracción | Lectura de fuentes | Spark-Mongo connector + pymongo + CSV | `etl/extraccion.py` |
| **II** | ETL — Transformación | Denormalización y derivadas | Joins entrega↔ruta↔vehículo↔operador↔incidente; variables derivadas | `etl/transformacion.py` |
| **II** | ETL — Carga | Escritura del resultado | Colección `analytics_entregas` + CSV/Parquet | `etl/carga.py` |
| **III** | ML supervisado | Predicción con etiqueta conocida | Dos modelos sobre el mismo dataset | Modelos entrenados |
| **III** | Regresión lineal | Predecir cuánto se retrasa | Regresión múltiple → `retraso_min`; comparación de 6 variantes (patrón `03_regresion_analytics.py`) | Reporte de comparación de modelos |
| **III** | Clasificación | Predecir si se retrasa | Árbol de decisión y Random Forest → `es_retraso` | Reporte de clasificación + importancia de variables |
| **III** | Evaluación de modelos | Medición del desempeño | `RegressionEvaluator` y evaluadores de clasificación | Tabla de métricas |
| **III** | MSE | Métrica de regresión | Reportado junto con RMSE | Salida del evaluador |
| **III** | MAE | Métrica de regresión | Reportado y comparado con MSE (sensibilidad a outliers) | Salida + interpretación |
| **III** | Entrenamiento y evaluación | Partición de datos | `randomSplit([0.8, 0.2], seed=42)` — idéntico a clase | Script + reporte |
| **III** | Optimización | Mejora del modelo | `CrossValidator` + `ParamGridBuilder` (regParam, elasticNetParam) | Reporte de optimización |
| **IV** | ML no supervisado | Descubrir estructura sin etiquetas | Agrupación de rutas | Modelo de clustering |
| **IV** | K-Means | Agrupar entidades similares | Rutas por distancia, tiempo, entregas, retraso, consumo, costo | Modelo + perfilado de grupos |
| **IV** | PCA | Reducción de dimensionalidad | Reducir 6–8 variables a 2 componentes para visualizar clusters + diagnóstico de colinealidad | Gráfica 2D + varianza explicada |
| **IV** | Entrenamiento/prueba y evaluación | Validación del clustering | Método del codo (WCSS) + índice de silueta | Gráfica del codo + score de silueta |
| **IV** | Optimización de la implementación | Ajuste del modelo | Estandarización previa, `n_init=10`, comparación de k, justificación del k elegido | Reporte de optimización |
| **V** | Representación de datos en gráficas | Visualización de resultados | 12+ gráficas mapeadas a preguntas de negocio (§18) | Dashboard |
| **V** | Tipos de gráficas | Selección adecuada | Barras, líneas, histograma, boxplot, violín, dispersión, pastel, heatmap | Dashboard + justificación de cada tipo |
| **V** | Interpretación de resultados | Conocimiento, no números | Función de interpretación automática (patrón `interpretar_clusters`) | Texto generado junto a cada gráfica |
| **V** | Herramientas: Excel | Exportación | CSV del dataset analítico abrible en Excel con tabla dinámica | Archivo CSV + captura |
| **V** | Herramientas: Power BI | Exportación | Mismo CSV como fuente de un reporte Power BI (opcional) | Archivo `.pbix` (opcional) |
| **V** | Bibliotecas / API's: Matplotlib | Visualización programática | Todas las gráficas del dashboard | Código fuente en repositorio |
| **V** | Dashboards | Vista integrada | Dashboard 2×3 analítico + panel ejecutivo de KPIs (patrón `graficas11db`/`graficas12db`) | Dashboard funcional |

---

## 7. ARQUITECTURA PROPUESTA

### 7.1 Cambios respecto al esquema que propusiste

Tu esquema lineal (Frontend → API → MongoDB → ETL → Dataset → ML → Resultados → Dashboard) es correcto, pero corrijo tres cosas:

1. **El flujo no es lineal, es cíclico.** Los resultados de ML (predicciones, clusters) vuelven a MongoDB y son consumidos por el API. Un ETA recalculado con el modelo es dato operativo, no solo un reporte.
2. **ETL y ML no están "debajo" del API.** Son procesos batch independientes, ejecutables por línea de comandos, sin pasar por el API. Esto cumple RNF-10 y es como se trabajó en clase.
3. **Falta la capa de datos simulados.** Con el supuesto S-04, el generador de semillas es un componente de primera clase, no un script suelto.

### 7.2 Arquitectura en capas

```
┌──────────────────────────────────────────────────────────────────────┐
│  CAPA 1 — PRESENTACIÓN                                               │
│  Interfaz web (formularios CRUD + dashboard)                         │
│  Gráficas PNG generadas por Matplotlib/Seaborn                       │
└───────────────────────────────┬──────────────────────────────────────┘
                                │ HTTP / JSON
┌───────────────────────────────▼──────────────────────────────────────┐
│  CAPA 2 — API / BACKEND  (FastAPI)                                   │
│  ┌────────────┬─────────────┬──────────────┬───────────────────────┐ │
│  │  Routers   │  Servicios  │  Repositorios│  Esquemas (Pydantic)  │ │
│  │ (endpoints)│(reglas neg.)│(acceso Mongo)│  (validación)         │ │
│  └────────────┴─────────────┴──────────────┴───────────────────────┘ │
└───────────────────────────────┬──────────────────────────────────────┘
                                │ pymongo
┌───────────────────────────────▼──────────────────────────────────────┐
│  CAPA 3 — PERSISTENCIA OPERATIVA  (MongoDB Atlas)                    │
│  clientes · vehiculos · operadores · rutas · viajes · entregas        │
│  incidentes · combustible · mantenimientos                           │
│                                                                      │
│  ◄── alimentada también por el GENERADOR DE DATOS SIMULADOS          │
│      (campo origen_dato = "SIMULADO" en cada documento)              │
└───────────────────────────────┬──────────────────────────────────────┘
                                │ pymongo (driver oficial)       
┌───────────────────────────────▼──────────────────────────────────────┐
│  CAPA 4 — ETL (pandas)                                               │
│  Extracción → Limpieza básica → Limpieza avanzada (IQR) →            │
│  Transformación (joins, denormalización) → Enriquecimiento           │
│  (variables derivadas) → Carga                                       │
│  Genera: reporte de calidad de datos (antes/después)                 │
└───────────────────────────────┬──────────────────────────────────────┘
                                │
┌───────────────────────────────▼──────────────────────────────────────┐
│  CAPA 5 — ALMACÉN ANALÍTICO  (modelo estrella en MongoDB + archivos) │
│  hecho_entrega · dim_tiempo · dim_cliente · dim_vehiculo             │
│  dim_operador · dim_ruta                                             │
│  data/processed/*.csv  (para Excel / Power BI)                       │
└──────────────┬─────────────────────────────────┬─────────────────────┘
               │                                 │
┌──────────────▼──────────────┐   ┌──────────────▼─────────────────────┐
│ CAPA 6a — ML SUPERVISADO    │   │ CAPA 6b — ML NO SUPERVISADO        │
│ (scikit-learn)              │   │ (scikit-learn)                     │
│ Regresión → retraso_min     │   │ K-Means → grupos de rutas          │
│ Clasificación → es_retraso  │   │ Codo + Silueta → k óptimo          │
│ MSE · RMSE · MAE · R²       │   │ PCA → visualización 2D             │
└──────────────┬──────────────┘   └──────────────┬─────────────────────┘
               │                                 │
               └────────────────┬────────────────┘
                                │
┌───────────────────────────────▼──────────────────────────────────────┐
│  CAPA 7 — RESULTADOS                                                 │
│  modelos_ml (métricas, parámetros, fecha)  ·  predicciones           │
│  clusters asignados  ·  archivos de modelo serializados              │
│         │                                                            │
│         └──────► RETROALIMENTA la Capa 3 (ETA predicho por entrega)  │
└───────────────────────────────┬──────────────────────────────────────┘
                                │
┌───────────────────────────────▼──────────────────────────────────────┐
│  CAPA 8 — VISUALIZACIÓN E INTERPRETACIÓN                             │
│  Dashboard analítico 2×3 · Panel ejecutivo de KPIs                   │
│  Interpretación automática en lenguaje natural                       │
│  Exportación CSV → Excel / Power BI                                  │
└──────────────────────────────────────────────────────────────────────┘
```

### 7.3 Descripción de cada capa

| Capa | Responsabilidad | NO debe hacer |
|---|---|---|
| 1. Presentación | Mostrar datos y capturar entradas | Contener reglas de negocio ni consultar Mongo directamente |
| 2. API/Backend | Validar, aplicar reglas, orquestar acceso a datos | Entrenar modelos ni ejecutar Spark |
| 3. Persistencia operativa | Guardar el hecho operativo tal como ocurrió | Guardar agregados ni resultados analíticos |
| 4. ETL | Limpiar, transformar, enriquecer y cargar | Modificar datos operativos originales |
| 5. Almacén analítico | Servir datos listos para analizar | Ser fuente de escritura para el API |
| 6. ML | Entrenar, evaluar y predecir | Leer datos crudos sin pasar por ETL |
| 7. Resultados | Persistir métricas y predicciones con trazabilidad | Sobrescribir históricos de modelos anteriores |
| 8. Visualización | Comunicar e interpretar | Recalcular métricas por su cuenta |

**Regla arquitectónica clave:** el ETL **nunca escribe** en las colecciones operativas. Solo lee. Si esta regla se rompe, se pierde la distinción OLTP/OLAP que sostiene la Unidad II.

### 7.4 Metodología: CRISP-DM mapeada a las unidades

La Unidad I exige justificar una metodología. Propongo **CRISP-DM** por su ajuste natural:

| Fase CRISP-DM | En SIG-LOG | Unidad |
|---|---|---|
| Comprensión del negocio | §1 de este documento; reglas de negocio | I |
| Comprensión de los datos | Exploración, análisis de columnas, valores de análisis | I |
| Preparación de los datos | ETL, limpieza básica y avanzada, DW | II |
| Modelado | Regresión, clasificación, K-Means, PCA | III y IV |
| Evaluación | MSE, MAE, R², silueta, método del codo | III y IV |
| Despliegue | API, dashboard, predicciones en producción | V |

Alternativa considerada y descartada: **KDD**. Es válida y más "clásica", pero CRISP-DM mapea 1 a 1 con las cinco unidades, lo que fortalece la trazabilidad académica.

---

## 8. STACK TECNOLÓGICO

| Tecnología | Uso | Motivo | Alternativa | ¿Necesaria? |
|---|---|---|---|---|
| **Python 3.10+** | Lenguaje base | Requisito del proyecto; lenguaje de todos los ejercicios | — | **Sí, obligatoria** |
| **MongoDB Atlas** | BD operativa | Requisito del proyecto; ya usada y probada en clase | — | **Sí, obligatoria** |
| **FastAPI** | API REST | Genera documentación OpenAPI automática (cubre el entregable "documentación de APIs" sin escribirla a mano); validación integrada con Pydantic (cubre el requisito de validaciones); menos código que Flask | Flask (más simple pero exige Marshmallow + Swagger manual) | **Sí** |
| **Pydantic** | Validación de esquemas | Viene con FastAPI; define contratos de datos explícitos | Marshmallow | **Sí** |
| **PyMongo** | Acceso a MongoDB desde el API | Es el driver usado en todos los ejercicios de clase; síncrono y suficiente para este volumen | Motor (async), Beanie (ODM) | **Sí** |
| **python-dotenv** | Credenciales | Patrón exacto de los ejercicios (`.env` + `quote_plus`) | Variables de entorno del SO | **Sí** |
| **pandas** | ETL completo, manipulación tabular, exploración | Decisión C-03. Usado en U-I (`unidad1_basico.py`, `unidad1_estructura.py`) y en `graficas8/12/13`. Cero costo de instalación y arranque inmediato | PySpark (descartado por C-03) | **Sí, núcleo del proyecto** |
| **scikit-learn** | ML supervisado **y** no supervisado | Es la herramienta exacta de la Unidad IV en clase. Para la Unidad III sustituye a Spark ML con equivalencia 1:1 (Anexo A) | Spark ML (descartado) | **Sí, núcleo del proyecto** |
| ~~PySpark~~ | — | **Descartado por decisión C-03.** Se documenta la equivalencia técnica en el Anexo A y se justifica en el manual técnico que el volumen de datos no requiere procesamiento distribuido | — | **No** |
| ~~mongo-spark-connector~~ | — | Descartado junto con PySpark | — | **No** |
| **NumPy** | Cálculo numérico | Base de sklearn; usado en todos los ejercicios de U-IV | — | **Sí** |
| **Matplotlib** | Visualización | Exigido explícitamente por la secuencia didáctica de U-V | — | **Sí, obligatoria** |
| **Seaborn** | Visualización estadística | Usado en `graficas3` y `graficas6`–`graficas13`; es material de clase | Solo Matplotlib | **Sí** |
| **SciPy** | `skew`, `kurtosis`, `mode` | Usado en `graficas7` y `graficas12` | Cálculo manual | Sí, para el panel ejecutivo |
| **Jinja2 + Bootstrap 5** | Frontend | Servido por el mismo FastAPI; sin build, sin npm, sin framework JS. Es la opción que **menos complica** el proyecto | React/Vue (SPA) | **Sí** (ver §8.2) |
| **Chart.js** | Gráficas interactivas del frontend | CDN, sin instalación. Complementa (no sustituye) a Matplotlib | Solo PNGs de Matplotlib | Opcional |
| **pytest** | Pruebas | Evidencia de la fase de pruebas | unittest | Sí, en Plan B |
| PyTorch | — | — | — | **No.** Fuera de la secuencia didáctica |
| Airflow / Prefect | — | — | — | **No.** Orquestación innecesaria para ETL manual |
| Docker | — | — | — | **No** en Plan A. Opcional en Plan B |
| Power BI | Reporte opcional | Mencionado en U-V; se cubre exportando CSV | Excel | Opcional |

### 8.1 Decisión C-03 resuelta: Opción B (pandas + scikit-learn)

PySpark queda fuera. Justificación que debe aparecer en el manual técnico, redactada como argumento técnico y no como limitación:

> El volumen de datos de SIG-LOG (miles de registros, no millones) no justifica un motor de procesamiento distribuido. Introducir Spark añadiría dependencia de JVM, tiempo de arranque y complejidad operativa sin ganancia de rendimiento. La decisión de **no** distribuir es tan técnica como la de distribuir: se documenta el umbral a partir del cual convendría migrar (aproximadamente, cuando el dataset supere la memoria disponible de un solo equipo).

Beneficio colateral relevante dado el plazo: se eliminan por completo los riesgos RT-01 (Spark no arranca) y la instalación de Java, liberando aproximadamente 2 horas del cronograma.

**Cómo se preserva la trazabilidad académica:** el Anexo A mapea cada técnica de los ejercicios de clase a su equivalente exacto en pandas/scikit-learn. Ese anexo debe incluirse en el manual técnico como evidencia de que se dominan ambos enfoques.

### 8.2 Nota sobre el frontend

Descarto React/Vue. Razones: obligan a un segundo entorno (Node, npm, build), duplican la validación, y no aportan nada evaluable en esta materia — el profesor evalúa extracción de conocimiento, no SPA. Jinja2 + Bootstrap permite tener CRUD y dashboard funcionando dentro del mismo proceso de FastAPI.

---

## 9. ESTRUCTURA INICIAL DE CARPETAS

```
SIG-LOG/
├── .env                          # credenciales (NUNCA se sube al repositorio)
├── .env.example                  # plantilla sin credenciales
├── .gitignore
├── requirements.txt
├── README.md
│
├── config/
│   ├── settings.py               # lectura de .env, constantes del sistema
│   └── mongo_conexion.py         # cliente PyMongo (patrón exacto de clase: .env + quote_plus)
│
├── backend/
│   ├── main.py                   # arranque de FastAPI
│   ├── routers/                  # endpoints por recurso
│   ├── schemas/                  # modelos Pydantic (validación)
│   ├── services/                 # reglas de negocio
│   ├── repositories/             # acceso a MongoDB
│   └── utils/                    # helpers compartidos
│
├── frontend/
│   ├── templates/                # HTML Jinja2
│   └── static/                   # CSS, JS, imágenes, gráficas generadas
│
├── database/
│   ├── esquemas/                 # validadores JSON Schema de MongoDB
│   ├── indices.py                # creación de índices
│   └── seed/                     # generador de DATOS SIMULADOS
│
├── etl/
│   ├── extraccion.py
│   ├── limpieza.py
│   ├── transformacion.py
│   ├── enriquecimiento.py
│   ├── carga.py
│   ├── exploracion.py            # EDA / análisis de columnas (Unidad I)
│   └── run_etl.py                # orquestador ejecutable
│
├── ml/
│   ├── supervisado/
│   │   ├── regresion_retraso.py
│   │   └── clasificacion_retraso.py
│   ├── no_supervisado/
│   │   ├── kmeans_rutas.py
│   │   ├── seleccion_k.py        # codo + silueta
│   │   └── pca_rutas.py
│   ├── evaluacion.py             # métricas centralizadas
│   └── interpretacion.py         # traducción de resultados a lenguaje natural
│
├── analytics/
│   ├── kpis.py                   # agregaciones MongoDB para indicadores
│   ├── graficas/                 # una función por gráfica del dashboard
│   └── dashboard.py              # composición de paneles
│
├── data/
│   ├── raw/                      # extracciones sin tocar
│   ├── processed/                # datasets limpios (CSV/Parquet)
│   ├── external/                 # fuentes externas si las hubiera
│   └── outputs/                  # gráficas PNG y reportes generados
│
├── docs/
│   ├── 00_documento_tecnico_base.md   # este documento
│   ├── 01_arquitectura.md
│   ├── 02_modelo_datos.md
│   ├── 03_api.md
│   ├── 04_etl.md
│   ├── 05_data_warehouse.md
│   ├── 06_machine_learning.md
│   ├── 07_visualizaciones.md
│   ├── 08_matriz_trazabilidad.md
│   ├── manual_tecnico.md
│   └── manual_usuario.md
│
└── tests/
    ├── test_api/
    ├── test_etl/
    └── evidencias/               # capturas y salidas de ejecución
```

### 9.1 Propósito y límites de cada carpeta

| Carpeta | Contendrá | NO debe contener |
|---|---|---|
| `config/` | Conexiones y configuración | Lógica de negocio, credenciales literales |
| `backend/` | API, validación, reglas de negocio | Código de ML, código de ETL, gráficas |
| `frontend/` | Plantillas y estáticos | Consultas a MongoDB, lógica de negocio |
| `database/` | Esquemas, índices, semillas | Datos reales de producción |
| `database/seed/` | Generador de DATOS SIMULADOS | Nada que se confunda con datos reales |
| `etl/` | Extracción, limpieza, transformación, carga | Entrenamiento de modelos, endpoints |
| `ml/` | Entrenamiento, evaluación, predicción | Limpieza (eso pertenece al ETL) |
| `analytics/` | KPIs, gráficas, dashboard | Entrenamiento de modelos |
| `data/raw/` | Extracciones crudas | Archivos editados a mano |
| `data/processed/` | Datasets listos para modelar | Datos sin limpiar |
| `data/outputs/` | PNG, CSV de resultados | Código |
| `docs/` | Documentación viva | Código ejecutable |
| `tests/` | Pruebas y evidencias | Código de producción |

---

## 10. MODELO CONCEPTUAL DE DATOS

### 10.1 Entidades y cardinalidades

```
   CLIENTE ─────────< ENTREGA >───────── VIAJE >──────── RUTA
      │                  │                 │              │
      │                  │                 ├── VEHICULO ──┘ (1:1 vehículo↔ruta, RN-04)
      │                  │                 └── OPERADOR
      │                  │
      │                  └───────< INCIDENTE
      │
      └── direcciones[] (embebido)

   VEHICULO ─────< CARGA_COMBUSTIBLE
   VEHICULO ─────< MANTENIMIENTO
   VIAJE    ─────< EVENTO_SEGUIMIENTO   (Fase de seguimiento dinámico)
```

| Relación | Cardinalidad | Regla |
|---|---|---|
| Vehículo ↔ Ruta | 1 : 1 | RN-04 |
| Ruta → Paradas (clientes) | 1 : N | RN-05 |
| Vehículo → Clientes | N : M (a través de entregas) | RN-03 |
| Ruta → Viaje | 1 : N | Una ruta se ejecuta muchos días |
| Viaje → Entregas | 1 : N | Un viaje realiza varias entregas |
| Cliente → Entregas | 1 : N | Un cliente recibe muchas entregas |
| Viaje → Incidentes | 1 : N | Varios incidentes en un mismo viaje |
| Incidente → Entregas | 1 : N | Un incidente afecta varias entregas |
| Vehículo → Cargas de combustible | 1 : N | Evento recurrente |
| Vehículo → Mantenimientos | 1 : N | Historial |

### 10.2 La entidad que faltaba: VIAJE

Tu lista de entidades no incluye **Viaje** (o Jornada). Propongo agregarla y explico por qué:

Si un vehículo tiene una sola ruta (RN-04) y esa ruta se ejecuta todos los días, entonces "vehículo A, ruta 3, 12 de agosto" y "vehículo A, ruta 3, 13 de agosto" son **ejecuciones distintas** del mismo plan. Sin una entidad que represente la ejecución:

- No puedo saber cuántos km recorrió el vehículo ese día → no puedo calcular km/l
- No puedo asociar un incidente a "el viaje del martes" → tendría que repetirlo en cada entrega
- No puedo saber qué operador manejó ese día si los operadores rotan (RNP-03)
- No tengo el grano correcto para la tabla de hechos del DW

**Viaje es la bisagra entre el plan (Ruta) y la realidad (Entregas).** Sin ella, el modelo de datos no soporta el análisis que exige la materia. Es la decisión de diseño más importante de este documento.

### 10.3 Decisiones: colección, embebido o referencia

| Dato | Decisión | Justificación |
|---|---|---|
| Direcciones del cliente | **Embebido** (array en `clientes`) | Cardinalidad baja y acotada; siempre se leen con el cliente; nunca se consultan solas |
| Paradas de una ruta | **Embebido** (array ordenado en `rutas`) | El orden es parte de la definición de la ruta; se leen siempre juntas; cardinalidad acotada |
| Entregas | **Colección independiente** | Crecimiento ilimitado; se consultan por fecha, cliente y estatus; son la base del dataset de ML |
| Historial de estatus de una entrega | **Embebido** (array en `entregas`) | Máximo ~5 elementos; solo tiene sentido dentro de su entrega |
| Viajes | **Colección independiente** | Crecimiento ilimitado (uno por ruta por día); tiene sus propios agregados |
| Incidentes | **Colección independiente + referencia** | Un incidente afecta varias entregas; embeberlo duplicaría el hecho e impediría contarlo una vez |
| Cargas de combustible | **Colección independiente** | Evento con fecha propia; volumen creciente; base del análisis de rendimiento |
| Mantenimientos | **Colección independiente** | Historial creciente; se consulta por vehículo y por fecha |
| Datos del vehículo dentro de una entrega | **Referencia + campos denormalizados mínimos** | Se guarda `vehiculo_id` y también `placa` para no hacer lookup en cada listado |
| Puntos GPS / eventos de seguimiento | **Colección independiente** | Crecimiento potencialmente ilimitado; embeberlos rompería el límite de 16 MB por documento |
| Dataset analítico | **Colección independiente** (`hecho_entrega`) | Es salida del ETL, grano distinto, ciclo de vida distinto |
| Resultados de modelos | **Colección independiente** (`modelos_ml`) | Trazabilidad de versiones de modelo |

**Criterio general aplicado:** *embeber cuando la relación es de contención y la cardinalidad está acotada; referenciar cuando la entidad tiene vida propia o crecimiento ilimitado.*

### 10.4 Denormalización controlada

MongoDB no tiene JOIN barato. Denormalizo deliberadamente en `entregas`: se guardan `vehiculo_id` + `placa`, `operador_id` + `nombre_operador`, `cliente_id` + `nombre_cliente`. Esto duplica datos, pero:

- Los listados y el dashboard no requieren `$lookup`
- Los nombres históricos se preservan aunque el catálogo cambie (si un cliente se renombra, la entrega de marzo conserva el nombre de marzo)

Es una decisión consciente, no un descuido de normalización.

---

## 11. COLECCIONES DE MONGODB PROPUESTAS

Notación: **O** = obligatorio · **P** = opcional · **C** = calculado por el sistema · **D** = derivado en el ETL

Todas las colecciones incluyen estos campos comunes:
- `origen_dato` (O): `"REAL"` | `"SIMULADO"` — **cumple la regla de no confundir datos simulados con reales**
- `fecha_creacion` (C), `fecha_modificacion` (C), `activo` (O, booleano para baja lógica)

---

### 11.1 `clientes`

**Propósito:** catálogo de clientes y sus puntos de entrega.

| Campo | Tipo | Tipo de campo | Descripción |
|---|---|---|---|
| `_id` | ObjectId | O | Identificador |
| `codigo_cliente` | String | O | Clave de negocio (ej. CLI-001) |
| `nombre` / `razon_social` | String | O | Nombre |
| `tipo_cliente` | String | P | Regla pendiente RNP-07 |
| `telefono`, `email` | String | P | Contacto |
| `direcciones[]` | Array de objetos | O | Embebido: `{alias, calle, numero, colonia, municipio, estado, cp, referencias, ubicacion: {type:"Point", coordinates:[lng,lat]}, principal:bool}` |
| `ventana_horaria` | Objeto | P | `{hora_inicio, hora_fin}` — depende de RNP-13 |
| `total_entregas` | Int | C | Contador acumulado |

**Índices:** `codigo_cliente` (único) · `nombre` (texto) · `direcciones.municipio` · `direcciones.ubicacion` (2dsphere, si se usa GPS)
**Histórico:** no requiere versionado; el nombre se conserva denormalizado en las entregas.
**Para ML:** `municipio` y `tipo_cliente` como variables categóricas; `ubicacion` para distancias reales.

---

### 11.2 `vehiculos`

**Propósito:** flotilla y su estado operativo.

| Campo | Tipo | Tipo | Descripción |
|---|---|---|---|
| `_id` | ObjectId | O | |
| `codigo_vehiculo` | String | O | VEH-001 |
| `placa` | String | O | Única |
| `marca`, `modelo`, `anio` | String/Int | O | Dimensiones para el DW |
| `tipo_vehiculo` | String | O | Supuesto S-03; ej. camioneta, torton, tráiler |
| `capacidad_carga_kg` | Double | P | Dato pendiente de definición |
| `capacidad_tanque_litros` | Double | P | **Dato pendiente de definición** — necesario para análisis de combustible |
| `rendimiento_nominal_km_l` | Double | P | **Dato pendiente de definición** — línea base contra la cual comparar el real |
| `odometro_actual_km` | Double | C | Se actualiza con cada carga/viaje |
| `estado_operativo` | String | O | DISPONIBLE / EN_RUTA / EN_MANTENIMIENTO / BAJA |
| `ruta_asignada_id` | ObjectId | P | Referencia (RN-04). Si RNP-02 = vigencia, se mueve a un historial |
| `fecha_ultimo_mantenimiento` | Date | D | Del último documento de `mantenimientos` |
| `fecha_proximo_mantenimiento` | Date | D | Según RNP-04 |
| `rendimiento_real_km_l` | Double | D | Calculado en el ETL a partir de `combustible` |

**Índices:** `placa` (único) · `codigo_vehiculo` (único) · `estado_operativo` · `ruta_asignada_id` · `fecha_proximo_mantenimiento`
**Histórico:** el historial de asignación de ruta depende de RNP-02.
**Para ML:** `tipo_vehiculo`, `anio` (→ antigüedad), `rendimiento_real_km_l`, `odometro_actual_km` son predictores del retraso y variables del clustering de vehículos.

---

### 11.3 `operadores`

| Campo | Tipo | Tipo | Descripción |
|---|---|---|---|
| `_id` | ObjectId | O | |
| `codigo_operador` | String | O | OPE-001 |
| `nombre_completo` | String | O | |
| `licencia` | Objeto | P | `{numero, tipo, vigencia}` |
| `fecha_ingreso` | Date | P | Permite derivar antigüedad |
| `estado` | String | O | ACTIVO / INACTIVO |
| `vehiculo_asignado_id` | ObjectId | P | Solo si RNP-03 = asignación fija |
| `total_entregas` | Int | C | Contador |
| `porcentaje_entregas_a_tiempo` | Double | D | Calculado en el ETL |

**Índices:** `codigo_operador` (único) · `estado` · `licencia.vigencia`
**Para ML:** antigüedad y `porcentaje_entregas_a_tiempo` histórico son predictores razonables del retraso. **Advertencia ética:** este uso puede derivar en evaluación del desempeño de personas; conviene declararlo en la documentación.

---

### 11.4 `rutas`

**Propósito:** definición planificada del recorrido. Es el "plan", no la ejecución.

| Campo | Tipo | Tipo | Descripción |
|---|---|---|---|
| `_id` | ObjectId | O | |
| `codigo_ruta` | String | O | RUT-001 |
| `nombre` | String | O | Ej. "Zona Norte Toluca" |
| `zona` | String | P | Dimensión del DW (copo de nieve) |
| `origen` | Objeto | O | Punto de partida (centro de distribución) |
| `paradas[]` | Array ordenado | O | Embebido: `{orden, cliente_id, direccion_alias, distancia_desde_anterior_km, tiempo_estimado_min, ventana_horaria}` |
| `distancia_total_km` | Double | C | Suma de las paradas |
| `tiempo_estimado_total_min` | Double | C | Suma de las paradas |
| `numero_paradas` | Int | C | Longitud del array |
| `dias_operacion[]` | Array | P | Depende de RNP-06 |
| `hora_salida_programada` | String | O | Necesaria para el análisis de saturación horaria |
| `vehiculo_asignado_id` | ObjectId | P | Contraparte de RN-04 |
| `activa` | Boolean | O | |

**Índices:** `codigo_ruta` (único) · `zona` · `vehiculo_asignado_id` · `paradas.cliente_id`
**Histórico:** si una ruta cambia de trazado, se recomienda versionarla (`version`, `vigente_desde`) para no invalidar el análisis histórico. **Regla pendiente.**
**Para ML:** `distancia_total_km`, `tiempo_estimado_total_min`, `numero_paradas`, `zona` son las variables centrales del clustering de rutas (Caso 3).

---

### 11.5 `viajes` — **colección nueva propuesta**

**Propósito:** ejecución de una ruta en una fecha por un vehículo y un operador. Es la unidad de operación diaria.

| Campo | Tipo | Tipo | Descripción |
|---|---|---|---|
| `_id` | ObjectId | O | |
| `folio_viaje` | String | O | VJE-20260816-001 |
| `fecha` | Date | O | Fecha de operación |
| `ruta_id` | ObjectId | O | Referencia |
| `vehiculo_id` | ObjectId | O | Referencia |
| `operador_id` | ObjectId | O | Referencia |
| `hora_salida_programada` | DateTime | O | Del plan |
| `hora_salida_real` | DateTime | P | Capturada |
| `hora_regreso_real` | DateTime | P | Capturada |
| `odometro_inicial_km` | Double | P | Para calcular km recorridos |
| `odometro_final_km` | Double | P | Idem |
| `km_recorridos` | Double | C | `final - inicial` |
| `estatus` | String | O | PROGRAMADO / EN_CURSO / FINALIZADO / CANCELADO |
| `total_entregas_programadas` | Int | C | |
| `total_entregas_completadas` | Int | C | |
| `total_incidentes` | Int | D | |
| `duracion_real_min` | Double | C | |
| `retraso_salida_min` | Double | C | `salida_real - salida_programada` |

**Índices:** `fecha` · `{ruta_id, fecha}` (compuesto) · `vehiculo_id` · `operador_id` · `estatus`
**Histórico:** cada documento **es** el histórico; nunca se sobrescribe.
**Para ML:** `retraso_salida_min` es probablemente el predictor más fuerte del retraso de las entregas del día (si sales tarde, llegas tarde). `km_recorridos` alimenta el cálculo de rendimiento.

---

### 11.6 `entregas`

**Propósito:** hecho operativo central. Es la fuente principal del dataset de Machine Learning.

| Campo | Tipo | Tipo | Descripción |
|---|---|---|---|
| `_id` | ObjectId | O | |
| `folio_entrega` | String | O | ENT-20260816-0001 |
| `viaje_id` | ObjectId | O | Referencia |
| `ruta_id` | ObjectId | O | Denormalizado para consultas directas |
| `cliente_id` | ObjectId | O | Referencia |
| `nombre_cliente` | String | O (denorm.) | Preserva el nombre histórico |
| `vehiculo_id`, `placa` | ObjectId/String | O (denorm.) | |
| `operador_id`, `nombre_operador` | ObjectId/String | O (denorm.) | |
| `orden_parada` | Int | O | Posición en la ruta |
| `fecha` | Date | O | |
| `hora_estimada_llegada` | DateTime | O | ETA planificado |
| `hora_real_llegada` | DateTime | P | Capturada al entregar |
| `hora_estimada_recalculada` | DateTime | C | Recalculada al registrarse un incidente (RF-33) |
| `tiempo_estimado_min` | Double | O | Del plan de ruta |
| `tiempo_real_min` | Double | C | Real de traslado |
| `retraso_min` | Double | C | `real − estimado` — **variable objetivo de regresión** |
| `es_retraso` | Int (0/1) | D | Según umbral RNP-01 — **variable objetivo de clasificación** |
| `distancia_km` | Double | O | Del plan de ruta |
| `estatus` | String | O | Según RNP-08 |
| `historial_estatus[]` | Array | C | Embebido: `{estatus, fecha_hora, usuario}` |
| `incidentes_ids[]` | Array de ObjectId | P | Referencias |
| `causa_retraso` | String | P | Catálogo RNP-12 |
| `observaciones` | String | P | **Dato no estructurado** (evidencia U-II) |
| `dia_semana` | Int | D | Derivado en ETL |
| `franja_horaria` | String | D | Derivado en ETL (MAÑANA/MEDIODIA/TARDE) |
| `es_fin_semana` | Int | D | Derivado en ETL |

**Índices:** `folio_entrega` (único) · `fecha` · `{cliente_id, fecha}` · `{ruta_id, fecha}` · `vehiculo_id` · `estatus` · `es_retraso`
**Histórico:** `historial_estatus[]` embebido.
**Para ML:** esta colección aporta la variable objetivo y la mayoría de los predictores. **Es la colección crítica del proyecto.**

---

### 11.7 `incidentes`

**Propósito:** registrar eventos que afectan el tiempo de traslado (RN-07).

| Campo | Tipo | Tipo | Descripción |
|---|---|---|---|
| `_id` | ObjectId | O | |
| `folio_incidente` | String | O | INC-20260816-001 |
| `tipo` | String | O | Catálogo RNP-12 |
| `severidad` | String | O | BAJA / MEDIA / ALTA — **regla pendiente de escala** |
| `fecha_hora_inicio` | DateTime | O | |
| `fecha_hora_fin` | DateTime | P | |
| `duracion_min` | Double | C | |
| `viaje_id` | ObjectId | P | Referencia |
| `ruta_id` | ObjectId | P | Referencia |
| `entregas_afectadas[]` | Array de ObjectId | P | Referencias |
| `ubicacion` | Objeto | P | GeoJSON Point (si hay GPS) |
| `descripcion` | String | P | **Dato no estructurado** |
| `tiempo_perdido_estimado_min` | Double | P | Capturado o estimado |
| `fuente` | String | O | MANUAL / API_EXTERNA / SIMULADO |

**Índices:** `fecha_hora_inicio` · `tipo` · `viaje_id` · `ruta_id` · `severidad`
**Para ML:** `tipo`, `severidad` y `duracion_min` son los predictores que explican los retrasos anómalos. Sin esta colección, el modelo solo aprende la variación normal.

---

### 11.8 `combustible`

**Propósito:** registrar cargas para analizar consumo, rendimiento y costo (RN-09).

| Campo | Tipo | Tipo | Descripción |
|---|---|---|---|
| `_id` | ObjectId | O | |
| `folio_carga` | String | O | |
| `vehiculo_id` | ObjectId | O | Referencia |
| `viaje_id` | ObjectId | P | Solo si RNP-09 = atado a jornada |
| `fecha` | Date | O | |
| `litros` | Double | O | **Dato pendiente de definición** en cuanto a rangos típicos |
| `precio_por_litro` | Double | O | **Dato pendiente de definición** |
| `costo_total` | Double | C | `litros × precio_por_litro` |
| `odometro_km` | Double | O | Crítico (RNP-10): sin él no hay km/l |
| `km_recorridos_desde_carga_anterior` | Double | D | Calculado en el ETL |
| `rendimiento_km_l` | Double | D | `km_recorridos / litros` |
| `tipo_combustible` | String | P | |
| `estacion` | String | P | |

**Índices:** `{vehiculo_id, fecha}` (compuesto) · `fecha` · `viaje_id`
**Histórico:** cada carga es un hecho inmutable.
**Para ML:** alimenta el clustering de vehículos (Caso 4) y el KPI de costo por kilómetro.

---

### 11.9 `mantenimientos`

| Campo | Tipo | Tipo | Descripción |
|---|---|---|---|
| `_id` | ObjectId | O | |
| `folio_mantenimiento` | String | O | |
| `vehiculo_id` | ObjectId | O | Referencia |
| `tipo` | String | O | PREVENTIVO / CORRECTIVO (RNP-05) |
| `fecha_programada` | Date | O | Según RNP-04 |
| `fecha_realizada` | Date | P | |
| `odometro_km` | Double | P | |
| `descripcion` | String | P | No estructurado |
| `costo` | Double | P | **Dato pendiente de definición** |
| `duracion_dias` | Double | C | Días fuera de operación |
| `estatus` | String | O | PROGRAMADO / REALIZADO / VENCIDO |
| `proximo_mantenimiento_fecha` | Date | D | Según RNP-04 |

**Índices:** `{vehiculo_id, fecha_programada}` · `estatus` · `tipo`
**Para ML:** días desde el último mantenimiento es un predictor plausible del retraso (vehículo mal mantenido → más lento / más fallas) y variable del clustering de vehículos.

---

### 11.10 `seguimiento_eventos` — Fase de seguimiento dinámico

**Propósito:** registrar cambios y checkpoints de una ruta en ejecución. Detalle conceptual en §17.

| Campo | Tipo | Tipo | Descripción |
|---|---|---|---|
| `_id` | ObjectId | O | |
| `viaje_id` | ObjectId | O | Referencia |
| `entrega_id` | ObjectId | P | Referencia |
| `tipo_evento` | String | O | SALIDA / LLEGADA_PARADA / INCIDENTE / DESVIO / RECALCULO_ETA / REGRESO |
| `fecha_hora` | DateTime | O | |
| `ubicacion` | Objeto | P | GeoJSON — solo si hay GPS |
| `eta_anterior` | DateTime | P | |
| `eta_nuevo` | DateTime | P | |
| `motivo` | String | P | |

**Índices:** `{viaje_id, fecha_hora}` · `tipo_evento`
**Nota:** colección independiente por crecimiento ilimitado. Si más adelante se registran coordenadas por minuto, es candidata a colección de series de tiempo de MongoDB.

---

### 11.11 Colecciones analíticas (salida del ETL)

| Colección | Grano | Propósito |
|---|---|---|
| `hecho_entrega` | Una entrega ejecutada | Tabla de hechos del DW; dataset de entrenamiento |
| `dim_tiempo` | Un día | Dimensión temporal |
| `dim_cliente` | Un cliente | Dimensión |
| `dim_vehiculo` | Un vehículo | Dimensión |
| `dim_operador` | Un operador | Dimensión |
| `dim_ruta` | Una ruta | Dimensión |
| `modelos_ml` | Un entrenamiento | Métricas, parámetros, fecha, versión, algoritmo |
| `predicciones` | Una predicción | Resultado del modelo aplicado a una entrega |
| `clusters_rutas` | Una ruta | Grupo asignado + perfil del grupo |

---

### 11.12 Resumen: campos calculados y derivados

| Campo | Tipo | Dónde se calcula | Fórmula |
|---|---|---|---|
| `costo_total` (combustible) | Calculado | API, al guardar | `litros × precio_por_litro` |
| `km_recorridos` (viaje) | Calculado | API, al cerrar viaje | `odometro_final − odometro_inicial` |
| `tiempo_real_min` | Calculado | API, al registrar llegada | `hora_real_llegada − hora_salida_tramo` |
| `retraso_min` | Calculado | API, al registrar llegada | `hora_real − hora_estimada` |
| `es_retraso` | Derivado | ETL | `1 si retraso_min > umbral (RNP-01)` |
| `rendimiento_km_l` | Derivado | ETL | `km_entre_cargas / litros` |
| `dia_semana`, `franja_horaria`, `es_fin_semana` | Derivados | ETL | Funciones de fecha |
| `porcentaje_entregas_a_tiempo` | Derivado | ETL | `entregas_a_tiempo / total × 100` |
| `costo_por_km` | Derivado | ETL | `costo_combustible / km_recorridos` |
| `dias_desde_mantenimiento` | Derivado | ETL | `fecha_entrega − fecha_ultimo_mantenimiento` |

---

## 12. DISEÑO CONCEPTUAL DE LA API

### 12.1 ¿El proyecto necesita API?

Sí, por tres razones: (1) separa presentación de lógica, cumpliendo la arquitectura en capas; (2) FastAPI genera la documentación OpenAPI automáticamente, cubriendo un entregable sin trabajo extra; (3) permite que ETL y ML consuman datos sin duplicar la lógica de acceso.

### 12.2 Convenciones

- Base: `/api/v1`
- Recursos en plural y en español (coherente con el dominio)
- Respuesta uniforme:
```json
{ "exito": true, "mensaje": "...", "datos": {...}, "total": 0 }
```
- Errores:
```json
{ "exito": false, "mensaje": "...", "codigo_error": "VALIDACION_FALLIDA", "detalles": [...] }
```
- Códigos: `200` OK · `201` creado · `400` validación · `404` no encontrado · `409` conflicto de regla de negocio · `422` error de esquema · `500` error interno

### 12.3 Endpoints principales (solo el diseño)

| Recurso | Método | Endpoint | Propósito |
|---|---|---|---|
| Clientes | GET | `/clientes` | Listar con filtros y paginación |
| | GET | `/clientes/{id}` | Detalle |
| | POST | `/clientes` | Crear |
| | PUT | `/clientes/{id}` | Actualizar |
| | DELETE | `/clientes/{id}` | Baja lógica |
| Vehículos | GET/POST/PUT/DELETE | `/vehiculos` | CRUD |
| | GET | `/vehiculos/{id}/rendimiento` | Rendimiento histórico km/l |
| | PATCH | `/vehiculos/{id}/estado` | Cambiar estado operativo |
| Operadores | GET/POST/PUT/DELETE | `/operadores` | CRUD |
| | GET | `/operadores/{id}/desempenio` | Entregas y puntualidad |
| Rutas | GET/POST/PUT/DELETE | `/rutas` | CRUD |
| | POST | `/rutas/{id}/paradas` | Agregar parada |
| | PUT | `/rutas/{id}/asignar-vehiculo` | Aplicar RN-04 (valida 1:1) |
| Viajes | GET/POST | `/viajes` | Listar / iniciar jornada |
| | PATCH | `/viajes/{id}/iniciar` | Registrar salida real |
| | PATCH | `/viajes/{id}/finalizar` | Registrar regreso y odómetro |
| Entregas | GET/POST | `/entregas` | Listar / crear |
| | PATCH | `/entregas/{id}/llegada` | Registrar hora real → dispara cálculo de retraso |
| | PATCH | `/entregas/{id}/estatus` | Cambiar estatus + historial |
| Incidentes | GET/POST | `/incidentes` | Listar / registrar |
| | POST | `/incidentes/{id}/afectar-entregas` | Asociar y **recalcular ETA** (RF-33) |
| Combustible | GET/POST | `/combustible` | Listar / registrar carga |
| | GET | `/combustible/resumen` | Consumo y costo agregado |
| Mantenimiento | GET/POST/PUT | `/mantenimientos` | CRUD |
| | GET | `/mantenimientos/pendientes` | Vehículos por atender (RF-16) |
| Analítica | GET | `/analitica/kpis` | Indicadores del dashboard |
| | GET | `/analitica/rutas-mas-usadas` | Consulta agregada |
| | GET | `/analitica/causas-retraso` | Consulta agregada |
| | GET | `/analitica/saturacion-horaria` | Consulta agregada |
| ML | GET | `/ml/modelos` | Modelos entrenados y métricas |
| | POST | `/ml/predecir-retraso` | Predicción para una entrega |
| | GET | `/ml/clusters-rutas` | Grupos de rutas |
| Sistema | GET | `/salud` | Verificación de conexión |

**Autenticación:** pendiente de RNP-11. Si se implementa, JWT con roles Admin / Despachador / Consulta. Mi recomendación: **omitirla en Plan A** — no aporta puntos en esta materia.

---

## 13. ESTRATEGIA ETL

### 13.1 Inventario de fuentes (Unidad I: "visión general de los datos de origen")

| Fuente | Tipo de dato | Formato | Frecuencia | Método de extracción |
|---|---|---|---|---|
| Colecciones operativas de MongoDB | Estructurado | BSON/JSON | Diaria | `pymongo` → `pd.DataFrame` |
| `rutas.paradas[]`, `entregas.historial_estatus[]` | **Semiestructurado** | Arrays anidados | Diaria | `pd.json_normalize()` / `DataFrame.explode()` |
| `incidentes.descripcion`, `entregas.observaciones` | **No estructurado** | Texto libre | Eventual | Conteo de palabras clave / categorización manual |
| Archivos CSV de carga inicial | Estructurado | CSV | Única | `pd.read_csv()` |
| Generador de datos simulados | Estructurado | JSON | Única | Inserción directa |
| API de tráfico externa | Estructurado | JSON | — | **Fuera de alcance actual** (§17.4) |

Esto cubre literalmente el tema "Tipos y fuentes de datos: estructurados, semiestructurados y no estructurados" de la Unidad II. Es importante que las tres categorías existan de verdad en el sistema, no solo en el documento.

### 13.2 Flujo del ETL

**1. EXTRACCIÓN (`etl/extraccion.py`)**
- Lectura de `entregas`, `viajes`, `rutas`, `vehiculos`, `operadores`, `clientes`, `incidentes`, `combustible`, `mantenimientos`
- Snapshot a `data/raw/` con marca de tiempo (trazabilidad y reproducibilidad)
- Tipos de extracción a documentar: completa (inicial) vs incremental (por fecha) — la secuencia didáctica pide "tipos de extracción"

**2. LIMPIEZA BÁSICA (`etl/limpieza.py`)**
- Casting explícito de tipos con `astype()` / `pd.to_datetime()` (equivale al `cast()` de `mongo_spark_conexion_sinnulos.py`)
- Conteo de nulos con `df.isnull().sum()` (patrón exacto de `unidad1_basico.py`) → **reporte de calidad antes de limpiar**
- Estrategia por columna: eliminar filas sin variable objetivo (`dropna(subset=[...])`); imputar numéricas con la **mediana vía `df[col].median()`** (equivale a `approxQuantile(0.5)` de `unidad1_spark.py`); imputar categóricas con `"NO_ESPECIFICADO"`
- Eliminación de duplicados con `drop_duplicates(subset=["folio_entrega"])`
- Normalización de texto (mayúsculas/minúsculas, espacios)

**3. LIMPIEZA AVANZADA (`etl/limpieza.py`)**
- **Outliers por IQR** sobre `tiempo_real_min` y `retraso_min` (patrón exacto de `graficas13cuartiles.py`): Q1, Q3, IQR, límites Q1−1.5·IQR y Q3+1.5·IQR
- Decisión documentada: ¿se eliminan o se marcan? **Recomiendo marcarlos** (`es_outlier = 1`) en lugar de eliminarlos — un retraso de 3 horas por una protesta no es un error de captura, es el fenómeno que queremos estudiar
- Validación de rangos: `litros > 0`, `distancia_km > 0`, `hora_real >= hora_salida`
- Coherencia referencial: entregas cuyo `viaje_id` no exista

**4. TRANSFORMACIÓN (`etl/transformacion.py`)**
- Joins: `entregas` ⋈ `viajes` ⋈ `rutas` ⋈ `vehiculos` ⋈ `operadores` ⋈ `clientes`
- Agregación de incidentes por viaje: `total_incidentes`, `tipo_incidente_principal`, `minutos_perdidos`
- Aplanado de arrays anidados
- Codificación de categóricas con `pd.get_dummies()` o `sklearn.preprocessing.OneHotEncoder` (equivale a `StringIndexer` + `OneHotEncoder` de Spark ML)

**5. ENRIQUECIMIENTO (`etl/enriquecimiento.py`)**
- Temporales: `dia_semana`, `es_fin_semana`, `mes`, `franja_horaria`, `hora_del_dia`
- Operativas: `retraso_min`, `es_retraso`, `porcentaje_desviacion_tiempo`
- Vehículo: `antiguedad_anios`, `dias_desde_mantenimiento`, `rendimiento_km_l`
- Históricas: `retraso_promedio_historico_ruta`, `retraso_promedio_historico_operador` — **cuidado con la fuga de información**: deben calcularse solo con datos anteriores a la fecha de cada entrega
- Ruta: `densidad_paradas = numero_paradas / distancia_total_km`

**6. CARGA (`etl/carga.py`)**
- Escritura de `hecho_entrega` y dimensiones en MongoDB con `insert_many()` por lotes (patrón de `generar_datos2_insertmany.py`)
- Exportación a `data/processed/dataset_entregas.csv` (para Excel/Power BI y para sklearn)
- Tipos de carga a documentar: completa (recarga total) vs incremental (append) — exigido por la secuencia didáctica
- Reporte final: registros de entrada, descartados, imputados, marcados como outlier, registros de salida

### 13.3 Evidencia diferenciadora

Recomiendo replicar el patrón de `01_mapreduce_analytics_connulos.py` vs `_sinnulos.py`: ejecutar la **misma** agregación con datos sucios y con datos limpios, y mostrar ambas gráficas lado a lado. Es la evidencia más contundente posible de la Unidad II, y es prácticamente gratis porque el ETL ya produce ambos estados.

### 13.4 Sobre archivos CSV/JSON de prueba

Sí conviene, por tres razones: (1) permiten desarrollar el ETL sin depender de la conexión a Atlas; (2) son un entregable exigido ("repositorio con el conjunto de datos preprocesados"); (3) son la fuente para Excel y Power BI. Deben residir en `data/` y estar etiquetados como simulados.

---

## 14. PROPUESTA DE DATA WAREHOUSE

### 14.1 Cómo evitar que sea una base duplicada sin propósito

El DW no será una segunda base de datos paralela. Será **la materialización del dataset analítico siguiendo un esquema estrella**, dentro de MongoDB, generado por el ETL. Es decir: el modelo estrella *es* el dataset de Machine Learning y *es* la fuente del dashboard. Un solo artefacto, tres usos. Así se demuestra el conocimiento de DW sin duplicar datos sin razón.

### 14.2 Modelo estrella

**Tabla de hechos: `hecho_entrega`**
Grano: **una entrega ejecutada**. Es el grano correcto porque es el nivel al que ocurren los fenómenos que queremos analizar (el retraso).

| Tipo | Campo |
|---|---|
| Claves | `id_tiempo`, `id_cliente`, `id_vehiculo`, `id_operador`, `id_ruta` |
| Métricas aditivas | `distancia_km`, `costo_combustible_asignado`, `total_incidentes`, `numero_entregas` (=1) |
| Métricas semiaditivas | `tiempo_estimado_min`, `tiempo_real_min`, `retraso_min`, `minutos_perdidos_incidentes` |
| Métricas no aditivas | `porcentaje_desviacion`, `rendimiento_km_l` |
| Banderas | `es_retraso`, `es_fin_semana`, `es_outlier`, `entrega_completada` |
| Degeneradas | `folio_entrega`, `folio_viaje` |

**Dimensiones:**

| Dimensión | Atributos |
|---|---|
| `dim_tiempo` | fecha, día, mes, año, trimestre, día de la semana, nombre del día, es_fin_semana, franja_horaria, hora |
| `dim_cliente` | código, nombre, tipo, municipio, zona |
| `dim_vehiculo` | código, placa, marca, modelo, año, tipo, antigüedad, capacidad |
| `dim_operador` | código, nombre, antigüedad, estado |
| `dim_ruta` | código, nombre, zona, distancia total, número de paradas, tiempo estimado |

```
                       dim_tiempo
                            │
     dim_cliente ─── hecho_entrega ─── dim_vehiculo
                     │           │
              dim_operador   dim_ruta
```

### 14.3 Modelo copo de nieve

Normalizando las dimensiones:

```
dim_cliente ──► dim_zona ──► dim_municipio ──► dim_estado
dim_vehiculo ──► dim_tipo_vehiculo ──► dim_marca
dim_ruta ──► dim_zona
dim_tiempo ──► dim_mes ──► dim_trimestre ──► dim_anio
```

### 14.4 Comparación y recomendación

| Criterio | Estrella | Copo de nieve |
|---|---|---|
| Complejidad de consulta | Baja | Alta (más joins) |
| Redundancia | Alta | Baja |
| Velocidad | Mayor | Menor |
| Ajuste a MongoDB | Muy bueno (documentos denormalizados) | Pobre (Mongo no favorece joins) |
| Facilidad para ML | Alta (una tabla plana) | Baja |
| Valor didáctico | Alto | Alto |

**Recomendación: implementar el modelo estrella y documentar el copo de nieve.** El estrella se materializa y se usa; el copo de nieve se diagrama, se explica y se justifica por qué no se implementó. Esto demuestra dominio de ambos conceptos sin construir dos almacenes.

### 14.5 Hechos adicionales (opcionales)

| Tabla de hechos | Grano | Uso |
|---|---|---|
| `hecho_consumo_combustible` | Una carga | Análisis de costo y rendimiento |
| `hecho_mantenimiento` | Un servicio | Análisis de disponibilidad de flotilla |

Comparten `dim_tiempo` y `dim_vehiculo` — esto constituye una **constelación de hechos** (fact constellation), concepto que vale la pena mencionar en la documentación.

---

## 15. PROPUESTA DE MACHINE LEARNING

### 15.1 Comparación de los cuatro casos

#### CASO 1 — Clasificación: ¿esta entrega llegará tarde?

| Aspecto | Detalle |
|---|---|
| Objetivo | Anticipar riesgo de retraso para actuar antes (avisar al cliente, reordenar paradas) |
| Variable objetivo | `es_retraso` (0/1), derivada de `retraso_min` y el umbral RNP-01 |
| Variables predictoras | `distancia_km`, `tiempo_estimado_min`, `orden_parada`, `numero_paradas_ruta`, `dia_semana`, `franja_horaria`, `es_fin_semana`, `retraso_salida_min`, `total_incidentes`, `tipo_incidente`, `antiguedad_vehiculo`, `dias_desde_mantenimiento`, `rendimiento_km_l`, `zona`, `retraso_historico_ruta` |
| Colecciones origen | `entregas`, `viajes`, `rutas`, `vehiculos`, `incidentes`, `mantenimientos` |
| Algoritmo | `sklearn.tree.DecisionTreeClassifier` (base, interpretable) y `sklearn.ensemble.RandomForestClassifier` (mejorado). Mismos algoritmos vistos en clase, misma nomenclatura de clase, distinta biblioteca |
| Métricas | Accuracy, Precisión, Recall, F1, AUC, matriz de confusión |
| Cantidad mínima | ≈300 entregas por clase; ≈1,000 en total como objetivo razonable |
| Problemas previsibles | **Desbalance de clases** (si el 90% llega a tiempo, un modelo que siempre diga "a tiempo" acierta 90% y no sirve). Se mitiga reportando recall y F1, no solo accuracy |
| Valor para la empresa | Alto: permite intervención preventiva |
| Valor académico | Cubre "Clasificación" (U-III) y aporta importancia de variables → responde "¿causas de retraso?" |

#### CASO 2 — Regresión: ¿cuánto se retrasará / cuánto tardará?

| Aspecto | Detalle |
|---|---|
| Objetivo | Estimar el tiempo real de traslado y el retraso en minutos |
| Variable objetivo | `retraso_min` (recomendada) o `tiempo_real_min` |
| Variables predictoras | Las mismas del Caso 1 |
| Algoritmo | `LinearRegression` simple y múltiple, `Ridge`, `Lasso`, `PolynomialFeatures` + `LinearRegression`, y `GridSearchCV` — replica exacta de los 6 modelos de `03_regresion_analytics.py` en scikit-learn |
| Métricas | **MSE, RMSE, MAE, R²** vía `mean_squared_error`, `mean_absolute_error`, `r2_score` — cubre literalmente los temas de U-III |
| Partición | `train_test_split(X, y, test_size=0.2, random_state=42)` — equivale a `randomSplit([0.8, 0.2], seed=42)` de clase, conservando la semilla 42 |
| Cantidad mínima | ≈10–20 registros por variable predictora; con 15 predictores ⇒ **≥300 registros mínimo, ≥1,000 recomendado** |
| Problemas previsibles | Colinealidad entre `distancia_km` y `tiempo_estimado_min` (miden casi lo mismo) → aquí PCA aporta valor real como diagnóstico |
| Valor para la empresa | Alto: mejora la promesa de entrega al cliente |
| Valor académico | Cubre regresión, MSE, MAE, entrenamiento/prueba y optimización |

**Recomendación sobre Casos 1 y 2: implementar AMBOS.** La Unidad III exige regresión *y* clasificación. Ambos comparten el mismo dataset y las mismas variables predictoras; solo cambia la variable objetivo (`retraso_min` continua vs `es_retraso` binaria). El costo marginal del segundo modelo es bajo y la cobertura académica se duplica. Es la decisión más eficiente del proyecto.

#### CASO 3 — Clustering: agrupación de rutas similares

| Aspecto | Detalle |
|---|---|
| Objetivo | Descubrir tipos de ruta para diseñar políticas diferenciadas |
| Variables | `distancia_total_km`, `tiempo_estimado_total_min`, `numero_paradas`, `frecuencia_mensual`, `porcentaje_retrasos`, `retraso_promedio_min`, `consumo_promedio_litros`, `costo_promedio` |
| Origen | `dim_ruta` + agregados de `hecho_entrega` |
| Algoritmo | `KMeans(n_clusters=k, random_state=42, n_init=10)` con `StandardScaler` previo — **parámetros idénticos a `u4comparacionkmeans3.py`** |
| Selección de k | Método del codo (WCSS) + índice de silueta — ambos vistos en clase |
| Métricas | Inercia, silhouette score |
| Cantidad mínima | **Al menos 15–20 rutas.** Con 5 rutas, K-Means no aporta nada — es la limitación crítica de este caso |
| Problemas previsibles | Pocas rutas; variables correlacionadas; sensibilidad a la escala |
| Valor para la empresa | Medio-alto: permite políticas por tipo de ruta |
| Valor académico | Cubre K-Means, codo, silueta y optimización (U-IV completa) |

#### CASO 4 — Clustering: perfilado de rendimiento de vehículos

| Aspecto | Detalle |
|---|---|
| Objetivo | Identificar vehículos eficientes, promedio y problemáticos |
| Variables | `rendimiento_km_l`, `costo_por_km`, `km_recorridos_mes`, `porcentaje_entregas_retrasadas`, `numero_mantenimientos`, `antiguedad_anios`, `dias_fuera_operacion` |
| Origen | `dim_vehiculo` + agregados de `hecho_entrega`, `combustible`, `mantenimientos` |
| Algoritmo | `KMeans` + `PCA(n_components=2)` para visualización — patrón exacto de `u4pcavarianzaexplicada6.py` |
| Cantidad mínima | **Al menos 15–20 vehículos** |
| Problemas previsibles | Si la flotilla es pequeña (<10), el clustering no es defendible estadísticamente |
| Valor para la empresa | Alto: decisiones de renovación de flotilla |
| Valor académico | Igual que el Caso 3 |

**Recomendación sobre Casos 3 y 4:** implementar el **Caso 3 (rutas)** como principal, porque conecta directamente con la pregunta del dashboard "¿qué grupos de rutas son similares?" y con el eje del proyecto (el retraso). El Caso 4 queda como secundario si hay tiempo, o **sustituye** al Caso 3 si resulta que hay más vehículos que rutas. **La decisión final depende de P-02 y P-03 de §23** — no puedo cerrarla sin saber cuántas rutas y cuántos vehículos existen.

### 15.2 ¿PCA aporta valor real?

Sí, en tres usos concretos. No lo incluiría solo por cumplir:

| Uso | Justificación | ¿Aporta? |
|---|---|---|
| **Visualización de clusters** | Con 8 variables de ruta es imposible graficar los grupos. PCA a 2 componentes permite el scatter que hace comprensible el resultado | **Sí, alto** |
| **Diagnóstico de colinealidad** | `distancia_km`, `tiempo_estimado_min` y `costo` están fuertemente correlacionadas. La varianza explicada lo revela cuantitativamente y justifica decisiones sobre las variables de la regresión | **Sí, alto** |
| **Reducción previa a K-Means** | Con 8 variables y pocas observaciones, reducir a 2–3 componentes puede mejorar la estabilidad del clustering | **Sí, medio** |
| Reducción previa a la regresión | Perdería interpretabilidad de los coeficientes, que es justo lo que queremos explicar | **No lo recomiendo** |

Conclusión: PCA se aplica en el flujo no supervisado (Casos 3 y 4), reportando la varianza explicada como hace `u4pcavarianzaexplicada6.py`. No se aplica a la regresión.

### 15.3 Estrategia de entrenamiento y evaluación

| Aspecto | Decisión |
|---|---|
| Partición | `train_test_split(test_size=0.2, random_state=42)` — 80/20 con la misma semilla de clase |
| Partición temporal | **Alternativa recomendada si hay tiempo:** entrenar con meses 1–5 y probar con el mes 6. Es más honesto para un problema de predicción (no puedes usar el futuro para predecir el pasado) |
| Validación cruzada | `GridSearchCV(cv=5)` sobre `alpha` (Ridge/Lasso) y `l1_ratio` (ElasticNet) — equivale a `CrossValidator` + `ParamGridBuilder` con `regParam`/`elasticNetParam` |
| Prevención de fuga de datos | Las variables históricas (`retraso_promedio_ruta`) deben calcularse solo con registros anteriores a cada entrega |
| Línea base | Comparar cada modelo contra una regla simple (ej. "predecir siempre el retraso promedio"). Si el modelo no supera la línea base, no sirve — y decirlo es evidencia de criterio |
| Persistencia | Métricas, parámetros, fecha y versión en `modelos_ml`; modelo serializado con `joblib.dump()` en `ml/modelos_guardados/` |

### 15.4 Integración posterior en la aplicación

1. El modelo entrenado se guarda en disco y sus metadatos en `modelos_ml`
2. Al crear una entrega, el API llama a `/ml/predecir-retraso` y guarda `probabilidad_retraso` y `retraso_estimado_min` en el documento de la entrega
3. El dashboard muestra las entregas del día ordenadas por riesgo
4. Al registrarse un incidente, se recalcula el ETA y se vuelve a predecir (conecta con RF-33)

Esto cierra el ciclo: el conocimiento extraído regresa a la operación. Es lo que distingue un proyecto de extracción de conocimiento de un ejercicio de laboratorio.

---

## 16. ESTRATEGIA DE DATOS

Esta sección responde a la preocupación central: *no llegar al final y descubrir que no hay datos para entrenar.*

### 16.1 Datos que deben capturarse desde el primer día

Si un campo no se captura desde el inicio, no existirá históricamente y no podrá reconstruirse. Estos son los **innegociables**:

| Prioridad | Dato | Colección | Por qué es crítico |
|---|---|---|---|
| **1** | `hora_estimada_llegada` | entregas | Sin ella no existe el concepto de retraso |
| **1** | `hora_real_llegada` | entregas | Es la mitad de la variable objetivo |
| **1** | `tiempo_estimado_min` por tramo | rutas.paradas | RN-10 lo señala como prioritario |
| **1** | `distancia_km` por tramo | rutas.paradas | Predictor principal |
| **1** | `fecha` y `hora` de cada evento | todas | Sin marca temporal no hay análisis de patrones ni partición temporal |
| **1** | `odometro_km` en cada carga | combustible | Sin él, km/l es incalculable (RNP-10) |
| **2** | `hora_salida_real` del viaje | viajes | Predictor probablemente muy fuerte |
| **2** | `tipo` y `duracion_min` del incidente | incidentes | Explica los retrasos anómalos |
| **2** | `litros` y `precio_por_litro` | combustible | Costo y rendimiento |
| **2** | `orden_parada` | entregas | El retraso se acumula a lo largo de la ruta |
| **3** | `fecha_realizada` del mantenimiento | mantenimientos | Predictor secundario |
| **3** | `causa_retraso` | entregas | Etiqueta interpretable para el dashboard |
| **3** | `observaciones` | entregas | Único dato no estructurado real del sistema |

**Consecuencia de diseño:** los formularios de captura del módulo de Entregas deben exigir hora estimada y hora real desde la Fase 5. No es un "extra para después".

### 16.2 Cantidad mínima de datos

No puedo darte cifras absolutas sin conocer el tamaño de la operación (P-02, P-03, P-05). Te doy la fórmula:

```
Registros de entrega ≈ N_rutas × entregas_por_ruta × días_operados
```

| Modelo | Mínimo defendible | Recomendado |
|---|---|---|
| Regresión múltiple (≈15 predictores) | 300 registros | 1,000–2,000 |
| Clasificación binaria | 300 por clase | 500+ por clase |
| K-Means de rutas | 15 rutas | 25+ rutas |
| K-Means de vehículos | 15 vehículos | 25+ vehículos |

**Riesgo identificado:** si la empresa tiene, por ejemplo, 5 vehículos y 5 rutas, el clustering de rutas será estadísticamente indefendible. En ese escenario, la solución honesta es simular un histórico de más rutas o cambiar el Caso 3 por el agrupamiento de **entregas** (que sí tendrán volumen), no fingir que 5 puntos forman 3 grupos.

### 16.3 Generación de DATOS SIMULADOS

Bajo el supuesto S-04 (no existe histórico real), necesitamos simular. Reglas estrictas:

1. **Todo documento simulado lleva `origen_dato: "SIMULADO"`.** Sin excepción. Esto permite filtrar, contar y separar en cualquier momento.
2. **El generador vive en `database/seed/`**, nunca mezclado con la lógica del API.
3. **La documentación declara explícitamente** qué proporción del dataset es simulada y cómo se generó.
4. **Los parámetros de simulación los defines tú, no yo.** No inventaré cantidades de vehículos, distancias, tiempos, consumos ni costos. El generador recibirá esos valores como configuración.
5. **La simulación debe incorporar relaciones realistas**, no ruido puro: más distancia ⇒ más tiempo; incidente ⇒ más retraso; hora pico ⇒ más retraso. Si los datos son aleatorios puros, ningún modelo aprenderá nada y el R² será cercano a cero — lo cual arruinaría la evidencia de la Unidad III.
6. **Debe existir ruido controlado.** Si la relación es perfecta, el R² será 1.0 y resultará evidentemente artificial ante el profesor.

Punto delicado que conviene reconocer en la documentación: cuando entrenas un modelo sobre datos que tú mismo generaste con una fórmula, el modelo está redescubriendo tu fórmula. La honestidad académica consiste en decirlo, no en ocultarlo. El valor demostrado es el dominio del método, no el descubrimiento empírico.

### 16.4 Parámetros del generador

Confirmada la decisión C-02 (no existen datos reales), estos valores dejan de ser "datos de negocio pendientes de descubrir" y pasan a ser **parámetros de diseño de la simulación**. No describen ninguna empresa real y no deben presentarse como tales.

Los valores propuestos están en el **Anexo B**. Fueron elegidos por dos criterios, no por verosimilitud comercial:
1. **Suficiencia estadística:** que cada modelo supere sus mínimos de §16.2.
2. **Consistencia interna:** que las relaciones entre variables permitan que los modelos aprendan algo real (más distancia ⇒ más tiempo; incidente ⇒ más retraso; hora pico ⇒ más retraso).

Todos son ajustables en un archivo de configuración; cambiarlos no requiere tocar el código del generador.

---

## 17. SEGUIMIENTO DINÁMICO DE RUTAS (nivel conceptual)

Mencionaste que me proporcionarás un análisis adicional sobre este componente. **No lo he recibido**, así que esta sección es preliminar y deberá compararse con ese documento cuando lo entregues. No diseño la implementación definitiva aún.

### 17.1 Qué información requiere el sistema

| Necesidad | Cómo se resuelve | Requiere GPS |
|---|---|---|
| Saber en qué parada va el viaje | Registrar llegada por parada (`orden_parada` + hora real) | **No** |
| Saber si se desvió del plan | Comparar secuencia real vs `paradas[]` planificadas | **No** |
| Saber por qué se retrasó | Registro de incidente asociado al viaje | **No** |
| Recalcular el ETA de las paradas pendientes | Propagar el retraso acumulado a las paradas siguientes | **No** |
| Ver el vehículo en un mapa en tiempo real | Coordenadas periódicas | **Sí** |
| Calcular distancia real recorrida | Odómetro (sí) o traza GPS (mejor) | Parcial |
| Conocer el tráfico actual | API externa | **Sí + servicio externo** |

**Conclusión clave: el 80% del valor del seguimiento dinámico NO requiere GPS.** Requiere registrar eventos con marca de tiempo. Esto es una buena noticia para el alcance académico.

### 17.2 Cómo representar una ruta

Tres niveles posibles:

| Nivel | Representación | Complejidad | Recomendación |
|---|---|---|---|
| **1. Secuencia de paradas** | Array ordenado de clientes con distancia y tiempo entre ellas | Baja | **Recomendado para el proyecto** |
| 2. Secuencia + coordenadas | Cada parada con GeoJSON Point | Media | Opcional; permite mapa estático |
| 3. Polilínea completa | Trazado real calle por calle | Alta | Fuera de alcance |

El nivel 1 es suficiente para todo el análisis de retrasos, el clustering y el DW. El nivel 2 agrega valor visual con costo bajo si ya tienes las coordenadas de los clientes.

### 17.3 Cómo funcionaría el recálculo del ETA (propuesta)

```
1. Se registra un incidente en el viaje V, a las 10:30, con duración estimada de 25 min
2. El sistema identifica las entregas de V con estatus ≠ ENTREGADA
3. Para cada una: eta_nuevo = eta_anterior + minutos_perdidos
4. Se escribe un evento en `seguimiento_eventos` (tipo RECALCULO_ETA, con eta_anterior y eta_nuevo)
5. Opcional (integración ML): en lugar de sumar linealmente, se invoca el modelo de regresión
   con la variable `total_incidentes` actualizada para estimar el retraso
```

El paso 5 es lo que convierte el módulo de seguimiento en el punto donde el Machine Learning entra en producción. Es un argumento fuerte de cara a la evaluación.

**Advertencia:** el recálculo lineal (paso 3) es un supuesto, no una regla confirmada. Podría ser que un incidente de 25 minutos no retrase 25 minutos a la última parada del día. **Regla pendiente de definición.**

### 17.4 Separación de funcionalidades

| Funcionalidad | Clasificación | Requiere servicio externo |
|---|---|---|
| Registro de salida y llegada por parada | **Actual** — necesaria para el proyecto | No |
| Registro de incidentes con duración | **Actual** | No |
| Recálculo de ETA por propagación | **Actual** | No |
| Bitácora de eventos del viaje | **Actual** | No |
| Comparación plan vs ejecución | **Actual** | No |
| Predicción de ETA con el modelo de ML | **Actual** (integración de U-III) | No |
| Coordenadas de clientes y mapa estático | **Futura cercana** | No (coordenadas manuales) |
| Ubicación del vehículo en tiempo real | **Futura** | Sí (GPS/telemetría) |
| Tráfico en tiempo real | **Futura** | Sí (API de mapas, generalmente de pago) |
| Recálculo de ruta óptima (VRP) | **Futura** | Sí |
| App móvil del operador | **Futura** | No, pero es otro proyecto |

**Mi recomendación de alcance:** implementar solo la columna "Actual". Es defendible, completo, y no depende de servicios externos ni de hardware (RNF-09).

Cuando me entregues tu análisis adicional, compararé punto por punto contra esta propuesta y ajustaré: qué datos necesita, qué cambios en MongoDB, qué endpoints, si requiere GPS, cómo detectar cambios y cómo afectan al ETA.

---

## 18. DASHBOARD: INDICADORES Y VISUALIZACIONES

### 18.1 Mapeo pregunta → dataset → métrica → gráfica → módulo

| # | Pregunta de negocio | Dataset / origen | Métrica | Gráfica propuesta | Módulo | Ejercicio base |
|---|---|---|---|---|---|---|
| 1 | ¿Qué rutas son más utilizadas? | `hecho_entrega` agrupado por ruta | Conteo de viajes y de entregas | Barras horizontales ordenadas | Reportes | `graficas4.py` |
| 2 | ¿Qué vehículos generan mayores costos? | `combustible` + `mantenimientos` por vehículo | Costo total y costo por km | Barras + línea de costo/km (eje secundario) | Combustible | `graficas5.py` |
| 3 | ¿Qué operadores realizan más entregas? | `hecho_entrega` por operador | Conteo y % a tiempo | Barras agrupadas (entregas vs puntualidad) | Operadores | `graficas5.py` |
| 4 | ¿Qué rutas presentan mayores retrasos? | `hecho_entrega` por ruta | Retraso promedio y % de retrasos | **BoxPlot por ruta** (muestra mediana y dispersión, no solo promedio) | Reportes | `graficas8.py` |
| 5 | ¿Qué vehículos consumen más combustible? | `combustible` por vehículo | Litros totales y km/l | Barras + línea de rendimiento | Combustible | `graficas5.py` |
| 6 | ¿Cuáles son las principales causas de retraso? | `incidentes` + `entregas.causa_retraso` | Frecuencia y minutos perdidos por causa | **Pareto** (barras ordenadas + % acumulado) | Incidentes | `graficas4.py` |
| 7 | ¿Qué vehículos requieren mantenimiento? | `mantenimientos` + `vehiculos` | Días/km desde el último servicio | Barras con línea de umbral | Mantenimiento | `graficas4.py` |
| 8 | ¿Cuál es la demanda de servicios? | `hecho_entrega` por fecha | Entregas por día/semana/mes | Línea temporal con media móvil | Reportes | `graficas1.py`, `graficas2.py` |
| 9 | ¿Qué servicio tiene mayor demanda? | Depende de RNP-07 | Conteo por tipo de servicio | Pastel o barras | Reportes | `graficas4.py` |
| 10 | ¿Qué horarios presentan mayor saturación? | `hecho_entrega` por hora | Entregas por hora y por día de la semana | **Heatmap hora × día de semana** | Reportes | `graficas3.py` (paletas) |
| 11 | ¿Qué rutas tienen mayor frecuencia de envíos? | `viajes` por ruta | Viajes por mes | Barras | Rutas | `graficas4.py` |
| 12 | ¿Qué patrones se encuentran en los datos? | Salida de K-Means + PCA | Grupos y perfil de cada grupo | **Dispersión PCA 2D coloreada por cluster** | ML | `u4pcavarianzaexplicada6.py` |
| 13 | ¿Qué entregas presentan mayor riesgo de retraso? | Salida del clasificador | Probabilidad de retraso | Tabla ordenada + histograma de probabilidades | ML | `graficas6.py` |
| 14 | ¿Cómo se distribuye el retraso? | `hecho_entrega` | Media, mediana, desviación, asimetría | Histograma + KDE con líneas de tendencia central | Reportes | `graficas7.py` |
| 15 | ¿El modelo predice bien? | Predicciones vs reales | MSE, RMSE, MAE, R² | Dispersión real vs predicho + línea ideal | ML | `03_regresion_analytics_graficos.py` |

### 18.2 Composición del dashboard

**Panel A — Dashboard ejecutivo (KPIs)** — patrón de `graficas12db.py`

| KPI | Fórmula |
|---|---|
| Entregas totales del periodo | `count(hecho_entrega)` |
| % de entregas a tiempo | `(1 − es_retraso.mean()) × 100` |
| Retraso promedio (min) | `retraso_min.mean()` |
| Retraso mediano (min) | `retraso_min.median()` — más robusto que la media |
| Km totales recorridos | `sum(km_recorridos)` |
| Costo total de combustible | `sum(costo_total)` |
| Costo promedio por km | `costo_total / km_recorridos` |
| Rendimiento promedio de flotilla | `mean(rendimiento_km_l)` |
| Vehículos en mantenimiento | `count(estado = EN_MANTENIMIENTO)` |
| Incidentes del periodo | `count(incidentes)` |

**Panel B — Dashboard analítico 2×3** — patrón exacto de `graficas11db.py`

| Posición | Gráfica |
|---|---|
| [0,0] | Histograma del retraso |
| [0,1] | BoxPlot del retraso por ruta |
| [0,2] | Violin plot por franja horaria |
| [1,0] | Heatmap de saturación hora × día |
| [1,1] | Serie temporal de entregas y retrasos |
| [1,2] | Pareto de causas de retraso |

**Panel C — Resultados de Machine Learning**

| Posición | Gráfica |
|---|---|
| [0,0] | Método del codo (WCSS vs k) |
| [0,1] | Índice de silueta por k |
| [1,0] | Clusters de rutas en el plano PCA |
| [1,1] | Real vs predicho + métricas de regresión |

### 18.3 Interpretación automática (RF-29)

Cada gráfica se acompaña de un texto generado, siguiendo el patrón de `interpretar_mapreduce()` e `interpretar_clusters()`. Ejemplo de la forma esperada:

> "La ruta con mayor retraso promedio es {ruta} con {X} minutos, {Y}% por encima del promedio de la flotilla. El {Z}% de sus entregas se registran como retrasadas. La causa más frecuente asociada es {causa}."

Esto es lo que convierte gráficas en conocimiento, que es literalmente el nombre de la materia.

---

## 19. MATRIZ DE TRAZABILIDAD DEL PROYECTO

Matriz viva: se actualiza con cada funcionalidad agregada.

| ID | Requerimiento | Módulo | Datos necesarios | Proceso | Unidad | Evidencia |
|---|---|---|---|---|---|---|
| RF-01 | CRUD de clientes | Clientes | `clientes` | Captura | I | API + capturas |
| RF-02 | Direcciones por cliente | Clientes | `clientes.direcciones[]` | Captura | II (semiestructurado) | Documento con array |
| RF-03 | CRUD de vehículos | Vehículos | `vehiculos` | Captura | I | API + capturas |
| RF-04 | Estado operativo del vehículo | Vehículos | `vehiculos.estado_operativo` | Consulta | I | Endpoint |
| RF-05 | CRUD de operadores | Operadores | `operadores` | Captura | I | API + capturas |
| RF-06 | Rutas con paradas ordenadas | Rutas | `rutas.paradas[]` | Captura | II | Documento anidado |
| RF-07 | Distancia y tiempo por tramo | Rutas | `rutas.paradas[]` | Captura | I | Documento |
| RF-08 | Asignación vehículo↔ruta 1:1 | Rutas | referencia cruzada | Validación (RN-04) | I | Prueba de validación |
| RF-09 | Registro de jornada | Entregas | `viajes` | Captura | I | Colección poblada |
| RF-10 | Horas estimada y real | Entregas | `entregas` | Captura | I | Colección poblada |
| RF-11 | Historial de estatus | Entregas | `entregas.historial_estatus[]` | Captura | II | Documento anidado |
| RF-12 | Registro de incidentes | Incidentes | `incidentes` | Captura | I | Colección poblada |
| RF-13 | Cargas de combustible | Combustible | `combustible` | Captura | I | Colección poblada |
| RF-14 | Rendimiento km/l | Combustible | `combustible` + `viajes` | Cálculo derivado | I (enriquecimiento) | Campo calculado |
| RF-15 | Mantenimientos | Mantenimiento | `mantenimientos` | Captura | I | Colección poblada |
| RF-16 | Alerta de mantenimiento | Mantenimiento | `mantenimientos` | Consulta con umbral | I | Endpoint + gráfica |
| RF-17 | Proceso ETL | ETL | Todas las operativas | ETL completo | **II** | Script + logs + dataset |
| RF-18 | Nulos, duplicados, outliers | ETL | Todas | Limpieza básica y avanzada | **II** | Reporte antes/después |
| RF-19 | Variables derivadas | ETL | `hecho_entrega` | Enriquecimiento | **I y II** | Columnas nuevas |
| RF-20 | Regresión del retraso | ML | `hecho_entrega` | Entrenamiento | **III** | Modelo + reporte |
| RF-21 | Clasificación de riesgo | ML | `hecho_entrega` | Entrenamiento | **III** | Modelo + matriz de confusión |
| RF-22 | MSE, RMSE, MAE, R² | ML | Predicciones | Evaluación | **III** | Tabla de métricas |
| RF-23 | K-Means de rutas | ML | `dim_ruta` agregada | Clustering | **IV** | Modelo + perfilado |
| RF-24 | Codo + silueta | ML | Mismo dataset | Optimización | **IV** | Dos gráficas |
| RF-25 | PCA | ML | Mismo dataset | Reducción | **IV** | Varianza explicada + scatter |
| RF-26 | Persistir resultados | ML | `modelos_ml`, `predicciones` | Carga | III y IV | Colecciones |
| RF-27 | Gráficas del dashboard | Reportes | `hecho_entrega` | Visualización | **V** | PNG + código |
| RF-28 | KPIs | Reportes | Agregaciones | Consulta | **V** | Panel ejecutivo |
| RF-29 | Interpretación automática | Reportes | Resultados | Generación de texto | **V** | Salida textual |
| RF-30 | Exportar CSV/JSON | ETL | Datasets | Carga | **II y V** | Archivos en `data/` |
| RF-31 | Datos simulados etiquetados | Datos | Todas | Generación | II | Colecciones con `origen_dato` |
| RF-32 | Cambios/incidencias en ruta | Seguimiento | `seguimiento_eventos` | Captura | I | Bitácora |
| RF-33 | Recálculo de ETA | Seguimiento | `entregas`, `incidentes` | Cálculo | I y III | Antes/después del ETA |

---

## 20. PLAN DE DESARROLLO

### 20.1 PLAN A — EJECUCIÓN CONFIRMADA (16–18 de agosto)

Plan activo por decisión C-01. Prioridad absoluta: **evidencia de las cinco unidades**, no completitud del CRUD.

**Principio rector:** un proyecto con ETL, dos modelos supervisados, uno no supervisado y dashboard, pero con CRUD parcial, **aprueba las cinco unidades**. Un CRUD impecable sin análisis **reprueba cuatro de cinco**.

| Bloque | Objetivo | Depende de | Archivos | Resultado | Evidencia | Tiempo |
|---|---|---|---|---|---|---|
| **B1** | Entorno, `.env`, estructura de carpetas, conexión a Atlas verificada | Credenciales | `config/`, `requirements.txt` | Conexión OK | Salida de la prueba de conexión | 45 min |
| **B2** | **Generador de datos simulados** y carga a Atlas | B1 + Anexo B aprobado | `database/seed/` | 9 colecciones pobladas, ≈15,000 entregas | Capturas de Atlas + conteos por colección | 3 h |
| **B3** | Exploración de datos (EDA): esquema, análisis de columnas, nulos, estadísticos | B2 | `etl/exploracion.py` | Perfilado completo | Salida en consola + tabla de perfilado | 1 h |
| **B4** | **ETL con pandas**: limpieza básica, IQR, derivadas, carga, export CSV | B3 | `etl/` | `hecho_entrega` + dimensiones + CSV | Reporte antes/después de limpieza | 2.5 h |
| **B5** | **ML supervisado**: regresión comparada (6 modelos) + clasificación | B4 | `ml/supervisado/` | Modelos con MSE, RMSE, MAE, R², matriz de confusión | Tabla comparativa + gráfica real vs predicho | 2.5 h |
| **B6** | **ML no supervisado**: codo, silueta, K-Means, PCA | B4 | `ml/no_supervisado/` | Clusters de rutas perfilados | Gráfica del codo, score de silueta, scatter PCA | 2 h |
| **B7** | **Dashboard**: paneles A, B y C + interpretación automática | B4–B6 | `analytics/` | Dashboard completo | PNG + texto interpretativo | 2.5 h |
| **B8** | **API + interfaz mínima**: router genérico CRUD + endpoints analíticos | B2 | `backend/`, `frontend/` | API documentada y navegable | `/docs` de OpenAPI + capturas | 3 h |
| **B9** | Documentación, matrices de trazabilidad y evidencias | Todos | `docs/` | Manuales + matrices | Documentos entregables | 2.5 h |

**Total estimado: ≈19.75 h** distribuidas entre la tarde del 16, el día completo del 17 y la mañana del 18.

### 20.1.1 Reglas de corte

Con este plazo, la disciplina de ejecución importa más que la ambición técnica:

1. **Si un bloque excede su tiempo asignado en más de 30 min, se congela y se avanza.** Un bloque incompleto pero funcional vale más que un bloque perfecto que impide llegar al siguiente.
2. **B2 es el cuello de botella crítico.** Todo lo analítico depende de él. Si falla, no hay proyecto. Se ejecuta primero y se verifica con conteos antes de continuar.
3. **B8 (API/interfaz) es sacrificable antes que B4–B7.** Si el tiempo aprieta, se entrega la API sin interfaz web y se documentan las pruebas con la interfaz automática de OpenAPI.
4. **B9 no se deja para el final del final.** La documentación se va escribiendo al cerrar cada bloque, aprovechando que el contexto está fresco.

### 20.1.2 Atajo estructural para el CRUD

Los ocho módulos obligatorios no requieren ocho conjuntos de código artesanal. Un **router genérico parametrizado por colección** (repositorio genérico + esquema Pydantic por entidad) entrega el CRUD de las nueve colecciones con aproximadamente un tercio del código. Las reglas específicas (validación de RN-04 en la asignación vehículo↔ruta, cálculo de retraso al registrar llegada) se implementan como excepciones sobre ese router genérico, no como módulos separados.

Es una decisión de ingeniería defendible por sí misma, no solo un atajo de plazo: reduce duplicación y concentra el mantenimiento.

### 20.2 PLAN B — Desarrollo incremental completo (4–6 semanas)

| Fase | Objetivo | Dependencias | Resultado | Evidencia |
|---|---|---|---|---|
| B1 | Análisis y arquitectura | — | Este documento aprobado | `docs/00_...md` |
| B2 | Configuración del proyecto | B1 | Entorno, `.env`, estructura, conexión | `/salud` OK |
| B3 | Modelo de datos y colecciones | B2 | Esquemas, validadores, índices | Capturas de Atlas |
| B4 | Generador de datos simulados | B3 | Base poblada | Conteos por colección |
| B5 | API base | B3 | Estructura, manejo de errores, respuesta uniforme | `/docs` |
| B6 | Módulo Clientes | B5 | CRUD + direcciones | Pruebas |
| B7 | Módulo Vehículos | B5 | CRUD + estado | Pruebas |
| B8 | Módulo Operadores | B5 | CRUD | Pruebas |
| B9 | Módulo Rutas | B6–B8 | CRUD + paradas + asignación 1:1 | Prueba de RN-04 |
| B10 | Módulo Viajes y Entregas | B9 | Captura de tiempos reales | Pruebas |
| B11 | Módulo Incidentes | B10 | Registro y asociación | Pruebas |
| B12 | Módulo Combustible | B7 | Cargas y rendimiento | Pruebas |
| B13 | Módulo Mantenimiento | B7 | Programación y alertas | Pruebas |
| B14 | Seguimiento dinámico | B10, B11 | Bitácora + recálculo de ETA | Antes/después |
| B15 | ETL | B10–B13 | Dataset analítico + DW estrella | Reporte de calidad |
| B16 | ML supervisado | B15 | Regresión + clasificación | Métricas |
| B17 | ML no supervisado | B15 | K-Means + PCA | Codo, silueta, scatter |
| B18 | Dashboard | B15–B17 | Paneles + interpretación | PNG |
| B19 | Frontend | B6–B13, B18 | Interfaz completa | Capturas |
| B20 | Pruebas | Todas | Suite de pruebas | Reporte de pytest |
| B21 | Manual técnico | Todas | Documento | PDF/MD |
| B22 | Manual de usuario | B19 | Documento | PDF/MD |

**Diferencia clave respecto a tu lista original:** moví el generador de datos a la posición 4 (era implícito) y agregué el módulo de Viajes. Ambos son bloqueantes para todo lo analítico.

---

## 21. RIESGOS

### 21.1 Riesgos académicos

| ID | Riesgo | Probabilidad | Impacto | Mitigación |
|---|---|---|---|---|
| RA-01 | ~~Plazo desconocido~~ **CONFIRMADO: 2 días.** El riesgo ahora es no terminar | **Alta** | **Crítico** | Plan A activo (§20.1). Regla de corte: si un bloque excede su tiempo, se entrega incompleto y se avanza al siguiente. El orden del plan garantiza que lo evaluable esté listo primero |
| RA-02 | Datos insuficientes para que los modelos sean defendibles | **Mitigado** | Alto | Parámetros del Anexo B: ≈15,000 entregas, 20 rutas, 20 vehículos. Supera todos los mínimos estadísticos de §16.2 |
| RA-03 | Clustering sin sentido por pocas rutas/vehículos | Media | Alto | Confirmar P-02/P-05; si son pocos, agrupar entregas en lugar de rutas |
| RA-04 | Confusión entre datos simulados y reales | **Eliminado** | — | Decisión C-02: **no existen datos reales**. El 100% del contenido lleva `origen_dato: "SIMULADO"` y así se declara en la portada del manual técnico. No hay ambigüedad posible |
| RA-05 | Modelo con métricas irreales (R² ≈ 1.0) por simulación demasiado limpia | Media | Medio | Ruido controlado en el generador; reportar honestamente |
| RA-06 | Desbalance de clases que infla el accuracy | Alta | Medio | Reportar precisión, recall, F1 y matriz de confusión, no solo accuracy |
| RA-07 | El profesor espera las herramientas exactas de clase y se usaron otras | Media | Alto | Matriz de reutilización de §5.2; priorizar PySpark, sklearn y Matplotlib |
| RA-08 | Documentación dejada al final y sin terminar | Alta | Medio | Documentación viva desde la etapa 1 (§22) |
| RA-09 | Fuga de datos por variables históricas mal construidas | Media | Medio | Calcular agregados históricos solo con registros previos a cada entrega |

### 21.2 Riesgos técnicos

| ID | Riesgo | Probabilidad | Impacto | Mitigación |
|---|---|---|---|---|
| RT-01 | ~~PySpark no arranca~~ | **Eliminado** | — | Decisión C-03: no se usa PySpark. Se liberan ~2 h del cronograma |
| RT-02 | Límites del cluster gratuito de MongoDB Atlas (512 MB) | Baja | Medio | Volumen estimado muy inferior; monitorear |
| RT-03 | Latencia de Atlas en operaciones masivas | Media | Bajo | Usar `insert_many` por lotes (patrón de clase) |
| RT-04 | Credenciales expuestas en el repositorio | Media | **Alto** | `.env` en `.gitignore` desde el primer commit; `.env.example` sin valores |
| RT-05 | Inconsistencia entre datos denormalizados | Media | Medio | La denormalización es de instantánea histórica: es intencional, se documenta |
| RT-06 | Modelo entrenado y luego irreproducible | Media | Medio | `seed=42` fijo + registro de parámetros en `modelos_ml` |
| RT-07 | Documentos que exceden 16 MB por embebido excesivo | Baja | Alto | Ya mitigado: eventos GPS y entregas en colecciones independientes |
| RT-08 | Alcance descontrolado en el seguimiento dinámico | **Alta** | Alto | Tabla de separación actual/futuro de §17.4 como contrato |

### 21.3 El riesgo que más me preocupa

**RA-01, ahora confirmado.** Con 2 días, cada hora dedicada a un CRUD pulido es una hora que no se dedica a la evidencia de las cinco unidades. La contramedida está incorporada al Plan A: el generador de datos, el ETL y los modelos van **antes** que la interfaz, y el CRUD se resuelve con un router genérico en lugar de ocho módulos artesanales (§20.1, Bloque 8).

Riesgo secundario que vale la pena vigilar: **RA-05** (métricas irrealmente buenas). Con datos simulados por fórmula, un R² de 0.98 delata la simulación. El generador debe incluir ruido suficiente para que R² caiga en un rango creíble (aproximadamente 0.55–0.80) y el modelo siga siendo útil sin parecer artificial.

---

## 22. DOCUMENTACIÓN VIVA

No dejar la documentación para el final. Estos documentos nacen con el proyecto y se actualizan en cada etapa:

| Documento | Nace en | Se actualiza | Responsable de mantenerlo |
|---|---|---|---|
| `00_documento_tecnico_base.md` | Etapa 1 | Ante cualquier cambio de decisión | Este documento |
| `08_matriz_trazabilidad.md` | Etapa 1 | Cada funcionalidad nueva | Obligatorio |
| `02_modelo_datos.md` | Etapa 2 | Cada colección o campo nuevo | Obligatorio |
| `04_etl.md` | Etapa 3 | Cada transformación nueva | Obligatorio |
| `06_machine_learning.md` | Etapa 4 | Cada entrenamiento | Obligatorio |
| `07_visualizaciones.md` | Etapa 6 | Cada gráfica | Obligatorio |
| `03_api.md` | Etapa 7 | Automático vía OpenAPI | FastAPI lo genera |
| `01_arquitectura.md` | Etapa 1 | Ante cambios estructurales | Obligatorio |
| `05_data_warehouse.md` | Etapa 3 | Al definir hechos y dimensiones | Obligatorio |
| `manual_tecnico.md` | Etapa 8 | Al cierre | Entregable |
| `manual_usuario.md` | Etapa 8 | Al cierre | Entregable |
| `bitacora_decisiones.md` | Etapa 1 | Cada decisión relevante | **Recomendado**: registra qué se decidió, cuándo y por qué. Es lo que permite defender el proyecto oralmente |

### 22.1 Entregables y su relación con las unidades

| Entregable | Unidad que evidencia |
|---|---|
| Documento comparativo IA/ML/DM/Big Data | I |
| Documento de caso de estudio con objetivo, alcance y metodología | I |
| Esquema de Data Warehouse | II |
| Documento de tipos y fuentes de datos | II |
| Documento de técnicas de limpieza | II |
| Repositorio con datos preprocesados | II |
| Documento de justificación del algoritmo supervisado + evaluación | III |
| Repositorio con el modelo de regresión y clasificación | III |
| Documento de justificación del algoritmo no supervisado + evaluación | IV |
| Repositorio con el modelo de agrupación y reducción de dimensionalidad | IV |
| Dashboard con gráficas personalizadas e interpretación | V |
| Repositorio con el código de las gráficas | V |
| Manual técnico y manual de usuario | Transversal |
| Matriz de trazabilidad | Transversal |

Nota: estos entregables no los inventé. Están tomados directamente de los "Resultados del aprendizaje por unidad temática" de la secuencia didáctica.

---

## 23. INFORMACIÓN QUE NECESITO DE TI

Ordenadas por urgencia. Las tres primeras bloquean el inicio.

### Bloqueantes — RESUELTAS (16/08/2026)

| ID | Pregunta | Respuesta | Efecto |
|---|---|---|---|
| **P-01** | Fecha real de entrega | **18 de agosto de 2026** | Plan A activo (§20.1) |
| **P-02** | Número de vehículos | No existen datos reales | Se define por simulación: **20** (Anexo B) |
| **P-03** | Número de clientes | No existen datos reales | Se define por simulación: **100** (Anexo B) |
| **P-04** | ¿PySpark disponible? | Se elige **Opción B: pandas + scikit-learn** | PySpark descartado (§8.1, Anexo A) |

### Única pregunta abierta bloqueante

| ID | Pregunta |
|---|---|
| **P-27** | **¿Apruebas los parámetros de simulación del Anexo B?** Basta con confirmarlos o indicar qué números cambias. Sin esta confirmación no puede ejecutarse el Bloque B2, del cual depende todo lo demás |

### Alta prioridad

| ID | Pregunta |
|---|---|
| ~~P-05 a P-08~~ | Resueltas por simulación (Anexo B) — solo requieren tu visto bueno |
| **P-09** | ¿Confirmas el umbral de retraso en **>15 minutos**? (RNP-01) Está propuesto en el Anexo B |
| ~~P-10~~ | Resuelta: **no existen datos históricos reales**. Todo será simulado |
| **P-11** | ¿Me compartes el análisis adicional del seguimiento dinámico de rutas? Si no llega antes del Bloque B2, se implementa la versión sin GPS de §17.4 y se documenta como decisión de alcance |

### Media prioridad

| ID | Pregunta |
|---|---|
| P-12 | ¿Los operadores rotan entre vehículos o cada uno maneja siempre el mismo? (RNP-03) |
| P-13 | Mantenimiento: ¿por calendario, por kilometraje, o lo primero que ocurra? (RNP-04) |
| P-14 | ¿Qué "servicios" ofrece la empresa? El dashboard pide "servicio con mayor demanda" y no tengo el catálogo (RNP-07) |
| P-15 | ¿El sistema requiere login y roles de usuario? (RNP-11) |
| P-16 | ¿Las rutas operan todos los días o en días específicos? (RNP-06) |
| P-17 | ¿Manejan ventanas horarias comprometidas con el cliente? (RNP-13) |
| P-18 | ¿Cuántos meses de histórico quieres simular? |
| P-19 | ¿Tienes preferencia por Flask sobre FastAPI, o te parece bien FastAPI? |
| P-20 | ¿El proyecto es individual o en equipo? Si es en equipo, ¿cuántos integrantes y hay reparto de módulos? |

### Baja prioridad (pueden resolverse durante el desarrollo)

| ID | Pregunta |
|---|---|
| P-21 | ¿Precio por litro de combustible y consumo aproximado por vehículo? |
| P-22 | ¿Costo típico de un mantenimiento preventivo? |
| P-23 | ¿Con qué frecuencia ocurren incidentes (tráfico, accidentes, protestas)? |
| P-24 | ¿Quieres coordenadas GPS de los clientes para mostrar un mapa estático? |
| P-25 | ¿Requieres exportación a Power BI o basta con CSV para Excel? |
| P-26 | ¿En qué zona geográfica opera la empresa? (Confirma o refuta el supuesto S-01) |

---

## 24. RESUMEN DE DECISIONES QUE REQUIEREN TU APROBACIÓN

| # | Decisión propuesta | Sección |
|---|---|---|
| D-01 | Agregar la entidad **Viaje** (jornada) al modelo de datos | §10.2 |
| D-02 | **Incidentes** como colección independiente, no embebida | §4.2, §10.3 |
| D-03 | Stack: **FastAPI + PyMongo + pandas + NumPy + scikit-learn + Matplotlib/Seaborn** *(modificada en v1.1: sin PySpark)* | §8 |
| D-04 | Frontend: **Jinja2 + Bootstrap** servido por FastAPI (sin React) | §8.2 |
| D-05 | ML supervisado **y** no supervisado en **scikit-learn**, con tabla de equivalencias Spark→sklearn en el manual técnico *(modificada en v1.1)* | §5.3, Anexo A |
| D-06 | Implementar **regresión Y clasificación** sobre el mismo dataset | §15.1 |
| D-07 | Clustering principal: **rutas** (Caso 3); vehículos como secundario | §15.1 |
| D-08 | **PCA sí se usa**, para visualización y diagnóstico de colinealidad; no para la regresión | §15.2 |
| D-09 | Data Warehouse: **implementar estrella, documentar copo de nieve** | §14.4 |
| D-10 | Outliers se **marcan**, no se eliminan | §13.2 |
| D-11 | Campo **`origen_dato: "SIMULADO"`** en todos los documentos; se declara en la portada del manual técnico | §16.3 |
| D-12 | Seguimiento dinámico: solo funcionalidades **sin GPS ni servicios externos** | §17.4 |
| D-13 | Metodología: **CRISP-DM** mapeada a las cinco unidades | §7.4 |
| D-14 | **No usar PyTorch** (fuera de la secuencia didáctica) ni **PySpark** (decisión C-03) | §5.2, §8.1 |
| D-15 | Autenticación **opcional**, no prioritaria | §12.3 |

---

## HISTORIAL DE VERSIONES

| Versión | Fecha | Cambios | Estado |
|---|---|---|---|
| 1.0 | 16/08/2026 | Documento inicial: análisis completo, arquitectura, modelo de datos, ETL, DW, ML, dashboard y planes de desarrollo | Superada |
| **1.1** | 16/08/2026 | Confirmadas C-01 (entrega 18/08), C-02 (sin datos reales) y C-03 (stack pandas + scikit-learn). Eliminado PySpark de §7.2, §8, §9, §13 y §15. Plan A convertido en cronograma ejecutable de 9 bloques. Añadidos **Anexo A** (equivalencias Spark→scikit-learn) y **Anexo B** (parámetros de simulación) | **Vigente** |

---

**Fin del cuerpo principal — v1.1**

*Ningún dato de este documento describe una empresa real. Confirmada la decisión C-02, todas las cantidades del Anexo B son **parámetros de diseño de una simulación académica**, elegidos por criterios estadísticos y de consistencia interna, y así deben presentarse en la documentación entregable.*

---

# ANEXO A — EQUIVALENCIAS PySpark → pandas / scikit-learn

**Propósito:** demostrar que la decisión C-03 es una elección de ingeniería, no un desconocimiento de las herramientas de clase. Este anexo debe incluirse íntegro en el manual técnico.

## A.1 Preparación y limpieza de datos (Unidades I y II)

| Ejercicio de clase | Técnica en PySpark | Equivalente en pandas | Nota |
|---|---|---|---|
| `unidad1_spark.py` | `df.printSchema()` | `df.dtypes` / `df.info()` | Análisis de columnas (U-I) |
| `unidad1_spark.py` | `df.describe().show()` | `df.describe()` | Valores de análisis (U-I) |
| `unidad1_spark.py` | `df.count()`, `len(df.columns)` | `df.shape` | Dimensiones del dataset |
| `unidad1_spark.py` | `df.filter(col("x").isNull())` | `df[df["x"].isnull()]` | Detección de nulos |
| `unidad1_spark.py` | `approxQuantile("x", [0.5], 0.01)` | `df["x"].median()` | **La mediana en pandas es exacta, no aproximada.** Spark aproxima porque distribuye; pandas no necesita hacerlo |
| `unidad1_spark.py` | `df.fillna({"x": mediana})` | `df["x"].fillna(mediana)` | Imputación |
| `unidad1_spark.py` | `df.write.csv(...)` | `df.to_csv(...)` | Exportación |
| `mongo_spark_conexion_sinnulos.py` | `col("x").cast("double")` | `df["x"].astype(float)` | Tipado explícito |
| `mongo_spark_conexion_sinnulos.py` | `df.dropna(subset=[...])` | `df.dropna(subset=[...])` | **Sintaxis idéntica** |
| `mongo_spark_conexion_sinnulos.py` | `df.withColumn("ingreso", col("a")*col("b"))` | `df["ingreso"] = df["a"] * df["b"]` | Variable derivada |
| `mongo_spark_conexion_sinnulos.py` | `VectorAssembler(inputCols=[...])` | `X = df[[...]].values` | Spark exige vectorizar; scikit-learn acepta la matriz directamente. **Un paso menos** |
| `01_mapreduce.py` | `df.groupBy("x").agg(sum("y"))` | `df.groupby("x")["y"].sum()` | **MapReduce conceptual idéntico:** agrupar (map) y reducir (agg) |
| `spark_processingconsulta2.py` | `groupBy().agg(sum, avg)` | `df.groupby(...).agg(["sum","mean"])` | Agregación múltiple |
| `03_practica_seguridad_usuarios_III.py` | `when(col("x")>n, "ALTO").otherwise("BAJO")` | `np.where(df["x"]>n, "ALTO", "BAJO")` | Clasificación por reglas |
| `01_practica_IOT_IV.py` | `agg(avg, max, min)` | `df.groupby(...).agg(["mean","max","min"])` | Estadística por grupo |
| `02_practica_IOT_estadisticas_IV.py` | `stddev("x")` | `df["x"].std()` | Desviación estándar |
| `processing_consulta_ventas.py` | Pipeline `$group` de MongoDB | **Se conserva sin cambios** | Los pipelines de agregación de MongoDB son independientes de Spark y se usan tal cual para los KPIs del API |
| `graficas13cuartiles.py` | (ya estaba en pandas) | `quantile(0.25)`, `quantile(0.75)`, IQR | **Se reutiliza sin modificación** |

**Sobre el concepto de MapReduce (tema de Big Data, U-I/U-II):** se conserva y se demuestra de dos formas — con `groupby().agg()` de pandas y con los pipelines `$aggregate` de MongoDB, que ejecutan la agregación **del lado del servidor**, no en el cliente. Esta segunda vía es un argumento sólido: es procesamiento delegado al motor de datos, exactamente el principio que Spark implementa de forma distribuida.

## A.2 Aprendizaje supervisado (Unidad III)

| Ejercicio de clase | PySpark ML | scikit-learn | Nota |
|---|---|---|---|
| `03_regresion_analytics.py` | `randomSplit([0.8,0.2], seed=42)` | `train_test_split(test_size=0.2, random_state=42)` | Misma partición, misma semilla |
| `03_regresion_analytics.py` | `LinearRegression()` | `LinearRegression()` | **Nombre de clase idéntico** |
| `03_regresion_analytics.py` | `LinearRegression(regParam=0.5, elasticNetParam=0.0)` | `Ridge(alpha=0.5)` | Regularización L2 |
| `03_regresion_analytics.py` | `LinearRegression(regParam=0.5, elasticNetParam=1.0)` | `Lasso(alpha=0.5)` | Regularización L1 |
| `03_regresion_analytics.py` | `PolynomialExpansion(degree=2)` | `PolynomialFeatures(degree=2)` | Regresión polinómica |
| `03_regresion_analytics.py` | `CrossValidator` + `ParamGridBuilder` | `GridSearchCV(cv=5)` | Validación cruzada y búsqueda de hiperparámetros |
| `03_regresion_analytics.py` | `RegressionEvaluator(metricName="rmse")` | `mean_squared_error(y, p, squared=False)` | RMSE |
| `03_regresion_analytics.py` | `RegressionEvaluator(metricName="mae")` | `mean_absolute_error(y, p)` | **MAE — tema explícito de U-III** |
| `03_regresion_analytics.py` | `RegressionEvaluator(metricName="mse")` | `mean_squared_error(y, p)` | **MSE — tema explícito de U-III** |
| `03_regresion_analytics.py` | `RegressionEvaluator(metricName="r2")` | `r2_score(y, p)` | Coeficiente de determinación |
| `04_decision_tree.py` | `DecisionTreeClassifier()` | `DecisionTreeClassifier()` | **Nombre idéntico** |
| `04_arboldedecision.py` | `when(col("x")>n,1).otherwise(0)` | `(df["x"] > n).astype(int)` | Creación de la etiqueta binaria |
| `05_bosque_aleatorio.py` | `RandomForestClassifier()` | `RandomForestClassifier()` | **Nombre idéntico** |
| `05_bosque_aleatorio.py` | `Pipeline(stages=[...])` | `sklearn.pipeline.Pipeline([...])` | **Concepto idéntico** |
| `05_bosque_aleatorio.py` | `BinaryClassificationEvaluator()` | `roc_auc_score()`, `classification_report()` | Evaluación binaria |
| `04_decision_tree.py` | `MulticlassClassificationEvaluator()` | `accuracy_score`, `f1_score`, `confusion_matrix` | Evaluación multiclase |
| `05_bosque_aleatorio.py` | `model.featureImportances` | `model.feature_importances_` | **Responde "¿causas de retraso?"** |

## A.3 Aprendizaje no supervisado (Unidad IV)

**No requiere traducción: la Unidad IV se impartió íntegramente en scikit-learn.**

| Ejercicio | Técnica | Estado |
|---|---|---|
| `u4distanciaeuclidiana1.py` | Distancia euclidiana manual con NumPy | Se reutiliza sin cambios (explicación del manual técnico) |
| `u4kmeanscalculos2.py` | K-Means implementado desde cero | Se reutiliza sin cambios |
| `u4comparacionkmeans3.py` | `KMeans(n_clusters, random_state=42, n_init=10)` | Se reutiliza; solo cambian las variables |
| `u4inerciametodocodo4.py` | WCSS / método del codo | Se reutiliza |
| `u4indicesilueta5.py` | `silhouette_score` | Se reutiliza |
| `u4pcavarianzaexplicada6.py` | `StandardScaler` + `PCA` + `explained_variance_ratio_` | Se reutiliza |

Esta es una **ventaja** de la Opción B: la Unidad IV se implementa con fidelidad total, sin adaptación alguna.

## A.4 Visualización (Unidad V)

Sin cambios. Los 13 archivos `graficas*.py` usan matplotlib, seaborn, pandas, numpy y scipy — ninguno depende de Spark. Se reutilizan como plantillas directas.

## A.5 Justificación técnica de no usar Spark

Redacción sugerida para el manual técnico:

> Los ejercicios del curso emplearon Apache Spark para demostrar el procesamiento distribuido de datos. SIG-LOG genera un volumen aproximado de 15,000 registros de entrega, que ocupan menos de 20 MB en memoria. Ese volumen es tres órdenes de magnitud inferior al umbral en que un motor distribuido aporta ventaja: por debajo de la memoria disponible de un solo equipo, la sobrecarga de coordinación de Spark supera el beneficio del paralelismo. Se optó por pandas y scikit-learn, documentando la equivalencia técnica de cada operación (Anexo A) y el criterio de migración: si el dataset creciera hasta exceder la memoria del equipo, o si se incorporaran fuentes de telemetría en tiempo real, la arquitectura de la capa 4 permitiría sustituir pandas por PySpark sin modificar las capas adyacentes, ya que la interfaz de entrada (colecciones de MongoDB) y de salida (dataset analítico) permanecen iguales.

Este párrafo demuestra criterio de arquitectura, que es un nivel de comprensión superior a saber usar la herramienta.

---

# ANEXO B — PARÁMETROS DE SIMULACIÓN

> ### ⚠ DATOS SIMULADOS
> **Ninguna cifra de este anexo describe una empresa real.** Confirmada la decisión C-02, no existen datos reales de vehículos, clientes, operadores, rutas, entregas, tiempos, combustible, mantenimiento ni incidentes.
> Todos los valores siguientes son **parámetros de diseño de una simulación académica**, elegidos por dos criterios: suficiencia estadística para los modelos y consistencia interna entre variables.
> Todo documento generado llevará el campo `origen_dato: "SIMULADO"`.

## B.1 Dimensionamiento de la flotilla y la operación

| Parámetro | Valor propuesto | Criterio de elección |
|---|---|---|
| Vehículos | **20** | K-Means sobre vehículos requiere ≥15 observaciones para ser defendible (§16.2) |
| Rutas | **20** | RN-04 impone 1 ruta por vehículo ⇒ el número coincide necesariamente |
| Clientes | **100** | 20 rutas × 5 paradas promedio |
| Operadores | **24** | 20 titulares + 4 de relevo, lo que habilita la rotación (RNP-03 opción b) y genera variabilidad analizable |
| Paradas por ruta | **3 a 8** (media ≈5) | Genera dispersión suficiente para que `numero_paradas` discrimine entre clusters |
| Tipos de vehículo | **3** (ligero, mediano, pesado) | Habilita `dim_tipo_vehiculo` del modelo copo de nieve (§14.3) |
| Zonas geográficas | **4** | Habilita `dim_zona`; da estructura al clustering de rutas |

## B.2 Horizonte temporal

| Parámetro | Valor propuesto | Criterio |
|---|---|---|
| Periodo simulado | **1 de febrero – 31 de julio de 2026** (6 meses) | Permite análisis de tendencia mensual y estacionalidad para la Unidad V |
| Días de operación | Lunes a sábado | Genera contraste entre día hábil y fin de semana (`es_fin_semana` como predictor) |
| Días operados | ≈155 | |
| Viajes generados | 20 rutas × 155 días ≈ **3,100** | |
| **Entregas generadas** | ≈**15,500** | Supera con holgura el mínimo de 1,000 para regresión con 15 predictores (§16.2) |
| Cargas de combustible | ≈**1,500** | Aproximadamente 1 carga cada 2 días por vehículo |
| Mantenimientos | ≈**120** | 20 vehículos × 6 meses |
| Incidentes | ≈**370** | ≈12% de los viejes registra al menos un incidente |

## B.3 Parámetros de distancia y tiempo

| Parámetro | Valor propuesto | Criterio |
|---|---|---|
| Distancia entre paradas | **3 – 25 km** | Rango amplio para que la variable tenga poder predictivo |
| Distancia total por ruta | **25 – 120 km** | Derivada de lo anterior |
| Velocidad efectiva promedio | **18 – 35 km/h** | Refleja operación urbana con paradas; genera la relación distancia⇒tiempo que el modelo debe aprender |
| Tiempo de servicio por parada | **10 – 20 min** | Tiempo de descarga; añade componente no proporcional a la distancia |
| Hora de salida programada | **06:00 – 09:00** | Permite el análisis de saturación horaria (pregunta 10 del dashboard) |

## B.4 Parámetros que generan el fenómeno a predecir

Esta es la parte crítica: **si el retraso fuera puramente aleatorio, ningún modelo aprendería nada y el R² sería cercano a cero**, invalidando la evidencia de la Unidad III. Las relaciones siguientes son las que el modelo debe descubrir.

| Factor | Efecto propuesto sobre el tiempo real |
|---|---|
| Distancia | Efecto base proporcional |
| Franja horaria pico (07:00–10:00 y 17:00–20:00) | +15% a +35% sobre el tiempo estimado |
| Día de la semana | Lunes y viernes ligeramente más lentos |
| Orden de parada | El retraso se **acumula** a lo largo de la ruta: la parada 6 hereda el retraso de las anteriores |
| Retraso en la salida del viaje | Se propaga íntegro a todas las entregas del día |
| Incidente | Añade su `duracion_min` a las entregas posteriores del mismo viaje |
| Antigüedad del vehículo | Vehículos más antiguos, ligeramente más lentos |
| Días desde el último mantenimiento | Efecto leve y creciente |
| **Ruido aleatorio** | **±12%** — indispensable para que R² no resulte artificialmente perfecto |

| Parámetro objetivo | Valor buscado | Criterio |
|---|---|---|
| Umbral de retraso (RNP-01) | **> 15 minutos** | Propuesto; a confirmar (P-09) |
| Proporción de entregas retrasadas | **25% – 30%** | Evita el desbalance extremo que haría inútil la clasificación (riesgo RA-06) |
| R² esperado del modelo de regresión | **0.55 – 0.80** | Creíble. Un R² > 0.95 delataría la simulación |

## B.5 Combustible y mantenimiento

| Parámetro | Valor propuesto | Criterio |
|---|---|---|
| Rendimiento nominal por tipo | Ligero **8–11 km/l** · Mediano **5–7 km/l** · Pesado **3–5 km/l** | Diferencia entre tipos para que el clustering de vehículos encuentre estructura |
| Variación del rendimiento real | ±15% sobre el nominal, degradado por antigüedad | Genera dispersión analizable |
| Capacidad de tanque | Ligero **60 L** · Mediano **120 L** · Pesado **200 L** | |
| Precio por litro | **24.00 – 26.50** (unidad monetaria) | Con ligera variación temporal creciente, para que el análisis de costos muestre tendencia |
| Periodicidad de mantenimiento (RNP-04) | **Cada 30 días o 8,000 km, lo primero que ocurra** | Opción (c), la más realista |
| Proporción preventivo / correctivo | **80% / 20%** | Permite distinguir tipos en el análisis |
| Costo de mantenimiento | Preventivo **2,500 – 5,000** · Correctivo **6,000 – 20,000** | Genera outliers legítimos para la limpieza avanzada por IQR |

## B.6 Incidentes

| Tipo | Frecuencia relativa | Duración propuesta |
|---|---|---|
| TRAFICO | 55% | 10 – 45 min |
| CLIMA | 15% | 15 – 40 min |
| ACCIDENTE | 12% | 30 – 90 min |
| FALLA_VEHICULO | 8% | 40 – 180 min |
| CLIENTE_AUSENTE | 6% | 10 – 25 min |
| PROTESTA | 4% | 45 – 150 min |

Distribución elegida para que el análisis de Pareto (pregunta 6 del dashboard) muestre una estructura interpretable: pocas causas concentran la mayoría de los eventos, pero las de baja frecuencia concentran el mayor tiempo perdido por evento. Ese contraste es exactamente lo que hace interesante la interpretación.

## B.7 Declaración obligatoria en los entregables

Debe aparecer, con este contenido, en la portada del manual técnico y del manual de usuario:

> **Naturaleza de los datos.** El presente sistema opera con un conjunto de datos íntegramente simulado, generado mediante el módulo `database/seed/`. No corresponde a ninguna organización real. Cada documento almacenado incluye el campo `origen_dato` con valor `"SIMULADO"`, lo que permite verificar esta condición mediante consulta directa a la base de datos. Los parámetros de generación se documentan en el Anexo B del documento técnico base y fueron seleccionados con criterios de suficiencia estadística, no de representatividad comercial. Los resultados de los modelos de aprendizaje automático deben interpretarse, por tanto, como demostración del dominio metodológico y no como hallazgos empíricos sobre una operación logística real.

Esta declaración protege la honestidad académica del trabajo y, lejos de restarle valor, evidencia criterio metodológico.

---

**Fin del documento técnico base v1.1**
