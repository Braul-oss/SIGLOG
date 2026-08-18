"""
SIG-LOG — Sistema Integral de Gestión Logística
app.py

PUNTO DE ENTRADA EN LA RAÍZ DEL PROYECTO

    uvicorn app:app --reload

Este archivo **no construye ni configura nada**: la aplicación FastAPI se
arma en `backend/main.py` —con su ciclo de vida, sus manejadores de error,
CORS y los routers— y aquí solo se reexporta.

Que sea un simple reexport es la única forma de tener dos rutas de arranque
sin arriesgar que se desincronicen: no hay una segunda configuración que
mantener, solo un segundo nombre para la misma aplicación. Si mañana cambia
el arranque, se cambia en `backend/main.py` y las dos formas lo heredan.

Formas equivalentes de levantar el servidor, todas desde la raíz:

    uvicorn app:app --reload            # esta, la usada en clase
    uvicorn backend.main:app --reload   # apunta al módulo que la construye
    python -m backend.main              # usa la configuración del .env
    python app.py                       # equivalente a la anterior

La raíz del proyecto debe ser el directorio de trabajo: el paquete
`backend` se importa desde ahí.

Documentación interactiva: http://127.0.0.1:8000/docs
"""

from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

# `app` es la instancia de FastAPI que construye backend/main.py.
# `iniciar` levanta uvicorn con host, puerto y recarga tomados del .env.
from backend.main import app, iniciar

# Lo que este módulo expone públicamente. Deja explícito que `app` no es un
# objeto nuevo, sino el mismo de backend.main.
__all__ = ["app", "iniciar"]


if __name__ == "__main__":
    iniciar()
