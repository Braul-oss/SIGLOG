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