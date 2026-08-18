"""
SIG-LOG — Sistema Integral de Gestión Logística
reportes/

MÓDULO DE GENERACIÓN DE INFORMES  (RF-27, RF-28, RF-29)

Tres informes en PDF, uno por pregunta distinta:

    ejecutivo    cómo va la operación          → dirección
    operativo    qué hay que atender hoy       → coordinación y despacho
    aprendizaje  qué aprendió el sistema       → evidencia analítica

Ninguno calcula nada. Los KPIs salen de `analytics.kpis`, las gráficas de
`analytics.graficas` y los modelos de `modelos_ml`. Un informe que
recalculara sus cifras acabaría contradiciendo al dashboard, que es
justamente el problema que el proyecto vino a resolver.
"""
