"""
SIG-LOG — Sistema Integral de Gestión Logística
reportes/comun.py

ARMAZÓN COMÚN DE LOS INFORMES EN PDF

Aquí vive lo que comparten los tres informes: la plantilla de página con su
cabecera y su pie, la paleta, los estilos de texto y los constructores de
tabla, indicador y gráfica.

Dos decisiones que conviene explicar
------------------------------------
**Las gráficas se dibujan en memoria llamando a `analytics/graficas.py`.**
No se leen los PNG de `data/outputs/`: esos archivos son de la última vez
que alguien ejecutó el dashboard, y un informe que mezclara cifras frescas
con gráficas viejas mentiría sin que nadie lo notara. Se paga una décima de
segundo por gráfica a cambio de que el PDF sea siempre coherente consigo
mismo.

**Cada página lleva la marca de datos simulados.** Un PDF se descarga, se
reenvía y se imprime fuera del sistema, donde ya no hay una pantalla que
avise. La marca viaja con el documento porque es el documento el que puede
acabar en manos de alguien que no sabe de dónde salió.
"""

from __future__ import annotations

import io
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (
    Image,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from config import settings

# --------------------------------------------------------------------------
# PALETA
# --------------------------------------------------------------------------
# Los mismos colores que la interfaz: quien ve el panel y luego imprime el
# informe debe reconocer que son el mismo sistema.
TINTA = colors.HexColor("#16202e")
TINTA_SUAVE = colors.HexColor("#667589")
ACENTO = colors.HexColor("#1f4e79")
ACENTO_CLARO = colors.HexColor("#eaf1f8")
BORDE = colors.HexColor("#dfe5ee")
VERDE = colors.HexColor("#2ca02c")
AMBAR = colors.HexColor("#f0a500")
ROJO = colors.HexColor("#d62728")

COLOR_SEMAFORO = {"VERDE": VERDE, "AMARILLO": AMBAR, "ROJO": ROJO,
                  "NEUTRO": TINTA_SUAVE}

MARGEN = 1.6 * cm
ANCHO_UTIL = A4[0] - 2 * MARGEN


# --------------------------------------------------------------------------
# ESTILOS
# --------------------------------------------------------------------------
def _estilos() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "titulo": ParagraphStyle(
            "sl_titulo", parent=base["Title"], fontSize=20, leading=24,
            textColor=TINTA, spaceAfter=2, alignment=0),
        "subtitulo": ParagraphStyle(
            "sl_subtitulo", parent=base["Normal"], fontSize=10, leading=14,
            textColor=TINTA_SUAVE, spaceAfter=14),
        "seccion": ParagraphStyle(
            "sl_seccion", parent=base["Heading2"], fontSize=13, leading=16,
            textColor=ACENTO, spaceBefore=16, spaceAfter=4),
        "subseccion": ParagraphStyle(
            "sl_subseccion", parent=base["Heading3"], fontSize=10.5,
            leading=13, textColor=TINTA, spaceBefore=10, spaceAfter=3),
        "cuerpo": ParagraphStyle(
            "sl_cuerpo", parent=base["Normal"], fontSize=9, leading=13,
            textColor=TINTA, alignment=TA_JUSTIFY, spaceAfter=5),
        "lectura": ParagraphStyle(
            "sl_lectura", parent=base["Normal"], fontSize=8.5, leading=12.5,
            textColor=TINTA_SUAVE, alignment=TA_JUSTIFY,
            leftIndent=8, borderPadding=0, spaceBefore=3, spaceAfter=9),
        "nota": ParagraphStyle(
            "sl_nota", parent=base["Normal"], fontSize=8, leading=11,
            textColor=TINTA_SUAVE, spaceAfter=6),
        "celda": ParagraphStyle(
            "sl_celda", parent=base["Normal"], fontSize=7.5, leading=9.5,
            textColor=TINTA),
        "celda_cabecera": ParagraphStyle(
            "sl_celda_cabecera", parent=base["Normal"], fontSize=7,
            leading=9, textColor=colors.white, alignment=TA_CENTER),
    }


ESTILOS = _estilos()


# --------------------------------------------------------------------------
# PLANTILLA DE PÁGINA
# --------------------------------------------------------------------------
class _Plantilla(SimpleDocTemplate):
    """Documento con cabecera, pie numerado y marca de origen de los datos."""

    def __init__(self, destino, titulo: str, subtitulo: str, **kwargs):
        super().__init__(
            destino, pagesize=A4,
            leftMargin=MARGEN, rightMargin=MARGEN,
            topMargin=MARGEN + 0.9 * cm, bottomMargin=MARGEN + 0.4 * cm,
            title=f"SIG-LOG · {titulo}", author=settings.APP_NOMBRE,
            subject=subtitulo, **kwargs)
        self._titulo = titulo
        self._generado = datetime.now(timezone.utc).astimezone()

    def _adornos(self, lienzo, documento) -> None:
        lienzo.saveState()

        # Cabecera
        lienzo.setFillColor(ACENTO)
        lienzo.rect(0, A4[1] - 0.85 * cm, A4[0], 0.85 * cm, stroke=0, fill=1)
        lienzo.setFillColor(colors.white)
        lienzo.setFont("Helvetica-Bold", 8.5)
        lienzo.drawString(MARGEN, A4[1] - 0.58 * cm, "SIG-LOG")
        lienzo.setFont("Helvetica", 8.5)
        lienzo.drawString(MARGEN + 1.7 * cm, A4[1] - 0.58 * cm,
                          f"· {self._titulo}")
        lienzo.drawRightString(A4[0] - MARGEN, A4[1] - 0.58 * cm,
                               self._generado.strftime("%d/%m/%Y %H:%M"))

        # Pie: la marca de origen viaja con el documento, no con la pantalla
        lienzo.setFillColor(TINTA_SUAVE)
        lienzo.setFont("Helvetica", 6.8)
        lienzo.drawString(
            MARGEN, 1.05 * cm,
            "Datos SIMULADOS con fines académicos. Ninguna cifra describe "
            "una empresa real.")
        lienzo.setFont("Helvetica", 7.5)
        lienzo.drawRightString(A4[0] - MARGEN, 1.05 * cm,
                               f"Página {documento.page}")
        lienzo.setStrokeColor(BORDE)
        lienzo.setLineWidth(0.5)
        lienzo.line(MARGEN, 1.45 * cm, A4[0] - MARGEN, 1.45 * cm)

        lienzo.restoreState()

    def construir(self, elementos: list) -> None:
        self.build(elementos, onFirstPage=self._adornos,
                   onLaterPages=self._adornos)


def documento(titulo: str, subtitulo: str, elementos: list) -> bytes:
    """Arma el PDF completo y lo devuelve en memoria."""
    memoria = io.BytesIO()
    _Plantilla(memoria, titulo, subtitulo).construir(elementos)
    return memoria.getvalue()


def portada(titulo: str, subtitulo: str, periodo: dict[str, Any] | None = None
            ) -> list:
    """Encabezado del informe: qué es, de qué habla y de cuándo."""
    partes = [Paragraph(titulo, ESTILOS["titulo"])]
    texto = subtitulo
    if periodo and periodo.get("etiqueta"):
        texto += f"<br/>Periodo analizado: <b>{periodo['etiqueta']}</b>"
        if periodo.get("desde"):
            texto += (f" ({_fecha(periodo['desde'])} a "
                      f"{_fecha(periodo['hasta'])})")
    partes.append(Paragraph(texto, ESTILOS["subtitulo"]))
    return partes


def _fecha(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%d/%m/%Y")
    except (TypeError, ValueError):
        return str(iso)


# --------------------------------------------------------------------------
# PIEZAS
# --------------------------------------------------------------------------
def seccion(titulo: str, explicacion: str = "") -> list:
    """
    Un apartado con su explicación.

    La explicación no es decorativa: el informe lo lee alguien que no
    conoce el modelo de datos, y un apartado sin decir qué responde obliga
    a deducirlo de los números.
    """
    partes = [Paragraph(titulo, ESTILOS["seccion"])]
    if explicacion:
        partes.append(Paragraph(explicacion, ESTILOS["cuerpo"]))
    return partes


def lectura(texto: str) -> Paragraph:
    """La interpretación automática que acompaña a cada cifra (RF-29)."""
    return Paragraph(f"<b>Lectura:</b> {texto}", ESTILOS["lectura"])


def indicadores(kpis: list[dict[str, Any]], por_fila: int = 5) -> Table:
    """
    Rejilla de indicadores con su valor, su unidad y su semáforo.

    El color del borde superior repite el criterio de la pantalla: verde
    cumple la meta, ámbar se queda cerca, rojo se aleja, gris no se juzga
    contra ninguna.
    """
    tarjetas = []
    for kpi in kpis:
        tarjetas.append([
            Paragraph(f"<font size=6.5 color='#667589'>"
                      f"{kpi['titulo'].upper()}</font>", ESTILOS["celda"]),
            Paragraph(f"<font size=13><b>{_valor(kpi)}</b></font>",
                      ESTILOS["celda"]),
            Paragraph(f"<font size=6 color='#667589'>{kpi['unidad']}</font>",
                      ESTILOS["celda"]),
        ])

    filas, estilo = [], []
    ancho = ANCHO_UTIL / por_fila
    for inicio in range(0, len(tarjetas), por_fila):
        bloque = tarjetas[inicio:inicio + por_fila]
        columna = len(filas)
        filas.append([Table([[p] for p in t], colWidths=[ancho - 6],
                            style=TableStyle([
                                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                                ("TOPPADDING", (0, 0), (-1, -1), 1),
                                ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
                            ]))
                      for t in bloque]
                     + [""] * (por_fila - len(bloque)))
        for i, kpi in enumerate(kpis[inicio:inicio + por_fila]):
            estilo.append(("LINEABOVE", (i, columna), (i, columna), 2,
                           COLOR_SEMAFORO.get(kpi["semaforo"], TINTA_SUAVE)))

    tabla = Table(filas, colWidths=[ancho] * por_fila)
    tabla.setStyle(TableStyle(estilo + [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
    ]))
    return tabla


def _valor(kpi: dict[str, Any]) -> str:
    valor = kpi["valor"]
    if kpi.get("unidad") in ("MXN", "MXN/km"):
        return f"${valor:,.0f}" if abs(valor) >= 100 else f"${valor:,.2f}"
    if isinstance(valor, float) and valor != int(valor):
        return f"{valor:,.1f}"
    return f"{int(valor):,}"


def tabla(cabeceras: list[str], filas: list[list[Any]],
          anchos: list[float] | None = None,
          alinear_derecha: tuple[int, ...] = (),
          destacar: Callable[[int], bool] | None = None) -> Table:
    """
    Tabla con cabecera de color y filas alternas.

    `destacar` recibe el índice de la fila y decide si va marcada en rojo:
    sirve para señalar lo que exige atención sin depender de que el lector
    compare columna a columna.
    """
    datos = [[Paragraph(c, ESTILOS["celda_cabecera"]) for c in cabeceras]]
    for fila in filas:
        datos.append([Paragraph(str(v), ESTILOS["celda"]) for v in fila])

    if anchos is None:
        anchos = [ANCHO_UTIL / len(cabeceras)] * len(cabeceras)

    estilo = [
        ("BACKGROUND", (0, 0), (-1, 0), ACENTO),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.4, BORDE),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]
    for columna in alinear_derecha:
        estilo.append(("ALIGN", (columna, 1), (columna, -1), "RIGHT"))
    for i in range(1, len(datos)):
        if i % 2 == 0:
            estilo.append(("BACKGROUND", (0, i), (-1, i),
                           colors.HexColor("#f7f9fc")))
        if destacar and destacar(i - 1):
            estilo.append(("TEXTCOLOR", (0, i), (-1, i), ROJO))

    resultado = Table(datos, colWidths=anchos, repeatRows=1)
    resultado.setStyle(TableStyle(estilo))
    return resultado


def grafica(dibujar: Callable[[Any], Any], ancho_cm: float = 17.0,
            alto_cm: float = 7.0) -> Image:
    """
    Ejecuta `dibujar(ax)` y devuelve la figura como imagen embebida.

    Recibe una función en vez de un archivo porque así se pueden pasar
    directamente las de `analytics/graficas.py`, que es justo lo que evita
    duplicar el código de las gráficas — y lo que garantiza que el informe
    y el dashboard dibujen exactamente lo mismo.
    """
    figura, ejes = plt.subplots(figsize=(ancho_cm / 2.54, alto_cm / 2.54))
    try:
        dibujar(ejes)
        figura.tight_layout()
        memoria = io.BytesIO()
        # 150 ppp: legible al imprimir sin inflar el PDF a decenas de megas
        figura.savefig(memoria, format="png", dpi=150,
                       bbox_inches="tight", facecolor="white")
    finally:
        plt.close(figura)

    memoria.seek(0)
    # La proporción se toma del PNG ya generado, no de la que se pidió:
    # `bbox_inches="tight"` recorta los márgenes sobrantes y cambia el alto
    # real. Escalar con la proporción pedida deformaría la gráfica.
    ancho_px, alto_px = ImageReader(memoria).getSize()
    memoria.seek(0)
    ancho = ancho_cm * cm
    return Image(memoria, width=ancho, height=ancho * alto_px / ancho_px)


def espacio(alto: float = 0.35) -> Spacer:
    return Spacer(1, alto * cm)


def salto() -> PageBreak:
    return PageBreak()


def juntos(elementos: list) -> KeepTogether:
    """Evita que un título quede solo al final de una página."""
    return KeepTogether(elementos)


def aviso(texto: str) -> Table:
    """Recuadro para lo que el lector no debe pasar por alto."""
    caja = Table([[Paragraph(texto, ESTILOS["nota"])]],
                 colWidths=[ANCHO_UTIL])
    caja.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), ACENTO_CLARO),
        ("LINEBEFORE", (0, 0), (0, -1), 2.5, ACENTO),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    return caja


# --------------------------------------------------------------------------
# FORMATO
# --------------------------------------------------------------------------
def dinero(valor: Any, decimales: int = 0) -> str:
    if valor is None:
        return "—"
    return f"${float(valor):,.{decimales}f}"


def numero(valor: Any, decimales: int = 1) -> str:
    if valor is None:
        return "—"
    return f"{float(valor):,.{decimales}f}"


def entero(valor: Any) -> str:
    if valor is None:
        return "—"
    return f"{int(valor):,}"


def porcentaje(valor: Any, decimales: int = 0) -> str:
    if valor is None:
        return "—"
    return f"{float(valor):,.{decimales}f}%"


def fecha(valor: Any) -> str:
    if not valor:
        return "—"
    if isinstance(valor, str):
        try:
            valor = datetime.fromisoformat(valor.replace("Z", "+00:00"))
        except ValueError:
            return valor
    return valor.strftime("%d/%m/%Y")
