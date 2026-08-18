"""
SIG-LOG — Sistema Integral de Gestión Logística
backend/vistas/plantillas.py

MOTOR DE PLANTILLAS Y FILTROS DE PRESENTACIÓN

Un único `Jinja2Templates` compartido: crear uno por vista recargaría el
entorno de plantillas en cada petición.

Los filtros de aquí solo dan formato. Ninguno calcula: si una cifra hay que
derivarla, se deriva en el servicio y llega ya derivada. Es la misma regla
de la capa 8 (§7.3) aplicada a la plantilla — la vista comunica, no computa.
"""

from __future__ import annotations

import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from fastapi.templating import Jinja2Templates
from markupsafe import Markup

from config import settings

plantillas = Jinja2Templates(directory=str(settings.FRONTEND_PLANTILLAS))


# ==========================================================================
# FILTROS
# ==========================================================================
def numero(valor: Any, decimales: int = 1) -> str:
    """1234.5 → '1,234.5'. Un guion si no hay dato: cero y vacío no son lo
    mismo, y confundirlos falsea cualquier lectura."""
    if valor is None or valor == "":
        return "—"
    try:
        return f"{float(valor):,.{decimales}f}"
    except (TypeError, ValueError):
        return str(valor)


def entero(valor: Any) -> str:
    if valor is None or valor == "":
        return "—"
    try:
        return f"{int(valor):,}"
    except (TypeError, ValueError):
        return str(valor)


def dinero(valor: Any) -> str:
    if valor is None or valor == "":
        return "—"
    try:
        return f"${float(valor):,.2f}"
    except (TypeError, ValueError):
        return str(valor)


def fecha(valor: Any) -> str:
    if not valor:
        return "—"
    if isinstance(valor, str):
        try:
            valor = datetime.fromisoformat(valor.replace("Z", "+00:00"))
        except ValueError:
            return valor
    if isinstance(valor, (datetime, date)):
        return valor.strftime("%d/%m/%Y")
    return str(valor)


def color_semaforo(valor: str) -> str:
    """
    Vocabulario de `analytics.kpis`: VERDE cumple la meta, AMARILLO se queda
    cerca, ROJO lejos, NEUTRO no se juzga contra ninguna meta.
    """
    return {"VERDE": "success", "AMARILLO": "warning",
            "ROJO": "danger", "NEUTRO": "secondary"}.get(valor, "secondary")


def a_json(valor: Any) -> Markup:
    """
    Serializa para incrustarlo en un `<script type="application/json">`.

    Devuelve `Markup` porque el autoescape de Jinja convertiría cada comilla
    en `&#34;` y el JSON dejaría de ser analizable. Saltarse el autoescape
    obliga a neutralizar a mano lo único que el navegador interpreta dentro
    de un `<script>`:

    - `</`   cerraría la etiqueta antes de tiempo y volcaría el resto del
      JSON como texto de la página;
    - `<!--` abre un comentario que se traga lo que venga detrás.

    Nada más hace falta: en un bloque `application/json` el navegador no
    ejecuta código, y `json.dumps` ya escapa comillas y saltos de línea.
    """
    texto = json.dumps(valor, ensure_ascii=False, default=str)
    return Markup(texto.replace("</", "<\\/").replace("<!--", "<\\u0021--"))


plantillas.env.filters["numero"] = numero
plantillas.env.filters["entero"] = entero
plantillas.env.filters["dinero"] = dinero
plantillas.env.filters["fecha"] = fecha
plantillas.env.filters["color_semaforo"] = color_semaforo
plantillas.env.filters["a_json"] = a_json
