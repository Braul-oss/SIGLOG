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
```

Verifica que la conexión y la estructura estén correctas:

```bash
python tests/test_conexion.py
```

---

## Ejecutar SIG-LOG (aplicación web)

**Comando oficial**, desde la raíz del proyecto:

```bash
python -m backend.main
```

| Recurso | URL |
|---|---|
| API | http://127.0.0.1:8000/api/v1 |
| Documentación interactiva (Swagger) | http://127.0.0.1:8000/docs |
| Documentación alternativa (ReDoc) | http://127.0.0.1:8000/redoc |
| Esquema OpenAPI | http://127.0.0.1:8000/openapi.json |

El punto de entrada es **`backend/main.py`**. Expone `app` (la aplicación
FastAPI) e `iniciar()` (el arranque con uvicorn), de modo que esta forma
alternativa es equivalente:

```bash
uvicorn backend.main:app --reload
```

> **Ejecuta siempre desde la raíz del proyecto.** El paquete `backend` se
> importa como `backend.main`, así que la raíz debe estar en el `PYTHONPATH`.
> Desde otro directorio el arranque falla con `ModuleNotFoundError: No module
> named 'backend'`; si lo necesitas, exporta `PYTHONPATH=/ruta/a/SIGLOG`.

El host, el puerto y la recarga automática se configuran en el `.env`
(`API_HOST`, `API_PUERTO`, `API_RECARGA`).

### Endpoints disponibles

Todos bajo el prefijo `/api/v1` (§12.2 del documento técnico).

| Método | Endpoint | Propósito |
|---|---|---|
| GET | `/salud` | Verifica que la API responde (no consulta MongoDB) |
| GET | `/salud/mongodb` | Ping real contra MongoDB Atlas |
| GET | `/info` | Versión, entorno y módulos disponibles |
| GET | `/diagnostico/colecciones` | Conteo de documentos por colección |
| GET | `/diagnostico/muestra/{coleccion}` | Documentos de muestra de una colección |

Prueba rápida con el servidor levantado:

```bash
curl http://127.0.0.1:8000/api/v1/salud
curl http://127.0.0.1:8000/api/v1/salud/mongodb
curl http://127.0.0.1:8000/api/v1/diagnostico/colecciones
```

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

## Pruebas

```bash
python tests/test_conexion.py     # conexión, colecciones e índices
python tests/test_api.py          # backend base (13 pruebas)

# o con pytest
pytest tests/ -v
```

Cada módulo del ETL, ML y analytics imprime además sus propias verificaciones
automáticas al final de su ejecución.

---

## Estructura del proyecto

```
SIGLOG/
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
| Autenticación, usuarios y roles | Pendiente |
| Módulos CRUD | Pendiente |
| Endpoints de analítica y ML | Pendiente |
| Frontend | Pendiente |
| Reportes PDF | Pendiente |

La documentación de diseño está en `docs/SIG-LOG_Documento_Tecnico_Base.md`.
