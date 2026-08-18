"""
SIG-LOG — Sistema Integral de Gestión Logística
backend/schemas/ml.py

ESQUEMAS DE LOS ENDPOINTS DE MACHINE LEARNING  (§12.3, §15.4)

La solicitud de predicción pide una entrega, no un vector de variables.

Es deliberado. Si el cliente enviara las dieciséis variables a mano podría
mandar cualquier combinación —una velocidad efectiva inventada, una
antigüedad que no corresponde al vehículo— y el modelo respondería con una
cifra que parecería una predicción sin serlo. Al pedir la entrega, el vector
lo arma el servicio a partir de datos reales y del enriquecimiento del ETL,
que es exactamente como se construyó al entrenar.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class PrediccionSolicitud(BaseModel):
    """Petición de predicción sobre una entrega existente."""

    entrega_id: str = Field(
        description="Entrega pendiente sobre la que se quiere predecir. El "
                    "escenario (PLANEACION o EN_RUTA) no se elige: lo "
                    "determina el estado del viaje.")
    guardar: bool = Field(
        default=True,
        description="Si es verdadero, escribe `probabilidad_retraso` y "
                    "`retraso_estimado_min` en la entrega (§15.4) y deja la "
                    "traza en `predicciones`. Ponerlo en falso permite "
                    "consultar sin modificar nada.")

    model_config = {
        "json_schema_extra": {
            "example": {
                "entrega_id": "6a83893489a0d3691e054f47",
                "guardar": True,
            }
        }
    }
