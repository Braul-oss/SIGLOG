"""
SIG-LOG — Sistema Integral de Gestión Logística
analytics/graficas.py

ACTIVIDAD PA-10 (parte 2) — CATÁLOGO DE GRÁFICAS
§18.1 del documento técnico base

Una función por gráfica, cada una respondiendo una pregunta concreta del
caso de estudio. Todas reciben un `Axes` de matplotlib y devuelven el
TEXTO DE INTERPRETACIÓN de lo que acaban de dibujar (RF-29, §18.3): la
gráfica y su lectura se generan juntas, porque una gráfica que hay que
explicar aparte termina sin explicación.

Reglas de presentación que cumplen todas
----------------------------------------
  · Título que enuncia el hallazgo, no la técnica.
  · Ejes rotulados CON UNIDADES.
  · Leyenda cuando hay más de una serie.
  · El color transmite significado (rojo = atención), nunca decora.
  · Ninguna gráfica recalcula métricas: consume lo que ya está en el DW
    (regla de la capa 8, §7.3).

Los datos son SIMULADOS (decisión C-02) y así se rotula en el dashboard.
"""

from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from config import settings
from config.mongo_conexion import obtener_bd

# Paleta con significado: el rojo señala lo que exige intervención.
COLOR_ALERTA = "#d62728"
COLOR_PRINCIPAL = "#1f77b4"
COLOR_SECUNDARIO = "#ff7f0e"
COLOR_BIEN = "#2ca02c"
COLOR_NEUTRO = "#7f7f7f"

NOMBRES_DIA = ("Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom")
ORDEN_FRANJAS = ("MADRUGADA", "PICO_MATUTINO", "VALLE",
                 "PICO_VESPERTINO", "NOCHE")


# ==========================================================================
# LECTURA DE DATOS  (una sola vez; las gráficas no consultan por su cuenta)
# ==========================================================================
def cargar_hechos(bd=None) -> pd.DataFrame:
    """Entregas de calidad OK con sus dimensiones ya desnormalizadas."""
    base = bd if bd is not None else obtener_bd()
    documentos = list(base["hecho_entrega"].find({"calidad_dato": "OK"}, {"_id": 0}))
    if not documentos:
        raise RuntimeError(
            "`hecho_entrega` está vacía. Ejecuta antes: python -m etl.run_etl")
    df = pd.DataFrame(documentos)
    df["fecha"] = pd.to_datetime(df["fecha"], utc=True)
    return df


def cargar_dimension(nombre: str, bd=None) -> pd.DataFrame:
    base = bd if bd is not None else obtener_bd()
    return pd.DataFrame(list(base[nombre].find({})))


# ==========================================================================
# 1 · HISTOGRAMA DEL RETRASO   (§18.1 #14)
# ==========================================================================
def histograma_retraso(ax, hechos: pd.DataFrame) -> str:
    serie = hechos["retraso_min"]
    media, mediana = serie.mean(), serie.median()
    umbral = settings.UMBRAL_RETRASO_MIN

    ax.hist(serie, bins=60, color=COLOR_PRINCIPAL, alpha=0.75,
            edgecolor="white", linewidth=0.3)
    ax.axvline(mediana, color=COLOR_BIEN, linestyle="-", linewidth=2,
               label=f"Mediana {mediana:.1f} min")
    ax.axvline(media, color=COLOR_SECUNDARIO, linestyle="--", linewidth=2,
               label=f"Media {media:.1f} min")
    ax.axvline(umbral, color=COLOR_ALERTA, linestyle=":", linewidth=2,
               label=f"Umbral de retraso ({umbral} min)")
    ax.set_title("Distribución del retraso: la mayoría cumple, "
                 "una cola larga no", fontsize=10, fontweight="bold")
    ax.set_xlabel("Retraso (minutos)")
    ax.set_ylabel("Número de entregas")
    ax.legend(fontsize=7)
    ax.grid(alpha=0.25, axis="y")

    asimetria = serie.skew()
    return (f"El retraso tiene media {media:.1f} min y mediana {mediana:.1f} min. "
            f"Que la media supere a la mediana (asimetría {asimetria:.2f}) indica "
            f"una cola de entregas muy retrasadas que arrastra el promedio: el "
            f"{100 * (serie > umbral).mean():.1f}% supera el umbral de {umbral} "
            "minutos, pero la entrega típica se retrasa mucho menos.")


# ==========================================================================
# 2 · BOXPLOT DEL RETRASO POR RUTA   (§18.1 #4)
# ==========================================================================
def boxplot_retraso_por_ruta(ax, hechos: pd.DataFrame,
                             dim_ruta: pd.DataFrame, top: int = 10) -> str:
    codigos = dict(zip(dim_ruta["_id"], dim_ruta["codigo_ruta"]))
    datos = hechos.assign(ruta=hechos["ruta_id"].map(codigos))
    orden = (datos.groupby("ruta")["retraso_min"].median()
             .sort_values(ascending=False).head(top).index.tolist())
    muestras = [datos.loc[datos["ruta"] == r, "retraso_min"].to_numpy() for r in orden]

    caja = ax.boxplot(muestras, tick_labels=orden, patch_artist=True,
                      showfliers=False,
                      medianprops={"color": "black", "linewidth": 1.5})
    for i, parche in enumerate(caja["boxes"]):
        parche.set_facecolor(COLOR_ALERTA if i < 3 else COLOR_PRINCIPAL)
        parche.set_alpha(0.75)
    ax.axhline(settings.UMBRAL_RETRASO_MIN, color=COLOR_ALERTA, linestyle=":",
               linewidth=1.5, label=f"Umbral ({settings.UMBRAL_RETRASO_MIN} min)")
    ax.set_title(f"Retraso por ruta: las {top} peores por mediana",
                 fontsize=10, fontweight="bold")
    ax.set_xlabel("Ruta")
    ax.set_ylabel("Retraso (minutos)")
    ax.tick_params(axis="x", rotation=45, labelsize=7)
    ax.legend(fontsize=7)
    ax.grid(alpha=0.25, axis="y")

    peor = orden[0]
    mediana_peor = datos.loc[datos["ruta"] == peor, "retraso_min"].median()
    mediana_global = hechos["retraso_min"].median()
    return (f"La ruta con mayor retraso mediano es {peor}, con "
            f"{mediana_peor:.1f} minutos, "
            f"{100 * (mediana_peor / mediana_global - 1):.0f}% por encima de la "
            f"mediana de la flotilla ({mediana_global:.1f} min). El boxplot "
            "muestra además la dispersión: una ruta con caja alta es "
            "sistemáticamente lenta, y una con bigotes largos es impredecible, "
            "que es un problema distinto.")


# ==========================================================================
# 3 · VIOLÍN POR FRANJA HORARIA   (§18.2, panel B [0,2])
# ==========================================================================
def violin_por_franja(ax, hechos: pd.DataFrame) -> str:
    presentes = [f for f in ORDEN_FRANJAS if f in set(hechos["franja_horaria"])]
    muestras = [hechos.loc[hechos["franja_horaria"] == f, "retraso_min"].to_numpy()
                for f in presentes]
    medias = [m.mean() for m in muestras]

    partes = ax.violinplot(muestras, showmedians=True, widths=0.8)
    peor = int(np.argmax(medias))
    for i, cuerpo in enumerate(partes["bodies"]):
        cuerpo.set_facecolor(COLOR_ALERTA if i == peor else COLOR_PRINCIPAL)
        cuerpo.set_alpha(0.7)
    ax.set_xticks(range(1, len(presentes) + 1))
    ax.set_xticklabels([f.replace("_", "\n") for f in presentes], fontsize=7)
    ax.axhline(settings.UMBRAL_RETRASO_MIN, color=COLOR_ALERTA, linestyle=":",
               linewidth=1.5)
    ax.set_title("El retraso depende de la franja horaria",
                 fontsize=10, fontweight="bold")
    ax.set_xlabel("Franja horaria")
    ax.set_ylabel("Retraso (minutos)")
    ax.grid(alpha=0.25, axis="y")

    return (f"La franja {presentes[peor].replace('_', ' ').lower()} concentra el "
            f"mayor retraso medio ({medias[peor]:.1f} min), frente a "
            f"{min(medias):.1f} min de la mejor franja. La forma del violín "
            "importa: donde el cuerpo es ancho y alto, el retraso no es un caso "
            "aislado sino el comportamiento habitual de esa franja.")


# ==========================================================================
# 4 · HEATMAP DE SATURACIÓN HORA × DÍA   (§18.1 #10)
# ==========================================================================
def heatmap_saturacion(ax, hechos: pd.DataFrame) -> str:
    datos = hechos
    # El DW guarda la franja horaria, no la hora exacta: el eje vertical es la
    # franja, que es el grano al que el diseño decidió analizar la saturación.
    tabla = (datos.pivot_table(index="franja_horaria", columns="dia_semana",
                               values="numero_entregas", aggfunc="sum")
             .reindex([f for f in ORDEN_FRANJAS
                       if f in set(datos["franja_horaria"])]))
    tabla = tabla.reindex(columns=sorted(datos["dia_semana"].unique()))

    imagen = ax.imshow(tabla.to_numpy(dtype=float), aspect="auto", cmap="YlOrRd")
    ax.set_xticks(range(len(tabla.columns)))
    ax.set_xticklabels([NOMBRES_DIA[int(d)] for d in tabla.columns], fontsize=8)
    ax.set_yticks(range(len(tabla.index)))
    ax.set_yticklabels([f.replace("_", " ").title() for f in tabla.index], fontsize=7)
    for i in range(len(tabla.index)):
        for j in range(len(tabla.columns)):
            valor = tabla.to_numpy(dtype=float)[i, j]
            if not np.isnan(valor):
                ax.text(j, i, f"{int(valor):,}", ha="center", va="center",
                        fontsize=6.5,
                        color="white" if valor > np.nanmax(tabla.to_numpy(dtype=float)) * 0.6
                        else "black")
    ax.set_title("Saturación: dónde se concentran las entregas",
                 fontsize=10, fontweight="bold")
    ax.set_xlabel("Día de la semana")
    ax.set_ylabel("Franja horaria")
    plt.colorbar(imagen, ax=ax, label="Entregas", fraction=0.045)

    matriz = tabla.to_numpy(dtype=float)
    i, j = np.unravel_index(np.nanargmax(matriz), matriz.shape)
    franja_pico = tabla.index[i]

    # El consejo depende de si la celda más cargada es además una franja
    # conflictiva: recomendar "mover carga al valle" cuando el pico YA está
    # en el valle sería contradictorio.
    retraso_franja = datos.groupby("franja_horaria")["retraso_min"].mean()
    mejor_franja = retraso_franja.idxmin()
    if franja_pico == mejor_franja:
        consejo = ("La buena noticia es que la mayor carga coincide con la "
                   "franja de menor retraso: la programación actual ya está "
                   "aprovechando la mejor ventana del día.")
    else:
        consejo = (f"Esa franja no es la de menor retraso: mover parte de la "
                   f"carga a {mejor_franja.replace('_', ' ').lower()}, que "
                   f"promedia {retraso_franja.min():.1f} min frente a "
                   f"{retraso_franja[franja_pico]:.1f}, es la palanca más "
                   "directa sobre el retraso.")
    return (f"La mayor saturación ocurre en {franja_pico.replace('_', ' ').lower()} "
            f"de {NOMBRES_DIA[int(tabla.columns[j])]}, con {int(matriz[i, j]):,} "
            f"entregas ({100 * matriz[i, j] / np.nansum(matriz):.1f}% del total). "
            + consejo)


# ==========================================================================
# 5 · SERIE TEMPORAL DE ENTREGAS Y RETRASO   (§18.1 #8)
# ==========================================================================
def serie_temporal(ax, hechos: pd.DataFrame, ventana: int = 7) -> str:
    diario = (hechos.groupby(hechos["fecha"].dt.date)
              .agg(entregas=("numero_entregas", "sum"),
                   retraso=("retraso_min", "mean")))
    diario.index = pd.to_datetime(diario.index)
    media_movil = diario["entregas"].rolling(ventana, min_periods=1).mean()

    ax.plot(diario.index, diario["entregas"], color=COLOR_NEUTRO, linewidth=0.8,
            alpha=0.6, label="Entregas por día")
    ax.plot(diario.index, media_movil, color=COLOR_PRINCIPAL, linewidth=2,
            label=f"Media móvil ({ventana} días)")
    ax.set_title("Demanda diaria y su tendencia", fontsize=10, fontweight="bold")
    ax.set_xlabel("Fecha")
    ax.set_ylabel("Entregas por día")
    ax.tick_params(axis="x", rotation=30, labelsize=7)
    ax.grid(alpha=0.25)

    eje_retraso = ax.twinx()
    eje_retraso.plot(diario.index,
                     diario["retraso"].rolling(ventana, min_periods=1).mean(),
                     color=COLOR_ALERTA, linewidth=1.6, linestyle="--",
                     label="Retraso medio (media móvil)")
    eje_retraso.set_ylabel("Retraso medio (minutos)", color=COLOR_ALERTA)
    eje_retraso.tick_params(axis="y", labelcolor=COLOR_ALERTA)

    lineas = ax.get_lines() + eje_retraso.get_lines()
    ax.legend(lineas, [l.get_label() for l in lineas], fontsize=7, loc="upper left")

    pico = diario["entregas"].idxmax()
    correlacion = diario["entregas"].corr(diario["retraso"])
    return (f"La operación promedia {diario['entregas'].mean():.0f} entregas "
            f"diarias, con un máximo de {int(diario['entregas'].max())} el "
            f"{pico.date()}. La correlación entre volumen diario y retraso medio "
            f"es {correlacion:.2f}: "
            + ("los días de más volumen sí tienden a retrasarse más, así que "
               "repartir la carga entre días alivia el retraso."
               if correlacion > 0.2 else
               "el retraso no se explica principalmente por el volumen del día, "
               "sino por cómo se programa cada ruta."))


# ==========================================================================
# 6 · PARETO DE CAUSAS DE RETRASO   (§18.1 #6)
# ==========================================================================
def pareto_causas(ax, hechos: pd.DataFrame) -> str:
    retrasadas = hechos[hechos["es_retraso"] == 1]
    conteo = (retrasadas["causa_retraso"].fillna("NO REGISTRADA")
              .value_counts().sort_values(ascending=False))
    acumulado = 100 * conteo.cumsum() / conteo.sum()

    posiciones = np.arange(len(conteo))
    # "Pocos vitales": las causas necesarias para llegar al 80% acumulado,
    # INCLUYENDO la que lo cruza. Marcar solo las que quedan por debajo del
    # 80% dejaría sin destacar a la causa dominante cuando una sola basta.
    n_vitales = int(np.searchsorted(acumulado.to_numpy(), 80) + 1)
    colores = [COLOR_ALERTA if i < n_vitales else COLOR_NEUTRO
               for i in posiciones]
    ax.bar(posiciones, conteo.to_numpy(), color=colores, alpha=0.85)
    ax.set_xticks(posiciones)
    ax.set_xticklabels([c.replace("_", " ").title() for c in conteo.index],
                       rotation=35, ha="right", fontsize=7)
    ax.set_title("Pareto: pocas causas explican casi todo el retraso",
                 fontsize=10, fontweight="bold")
    ax.set_xlabel("Causa del retraso")
    ax.set_ylabel("Entregas retrasadas")
    ax.grid(alpha=0.25, axis="y")

    eje_pct = ax.twinx()
    eje_pct.plot(posiciones, acumulado.to_numpy(), color="black", marker="o",
                 linewidth=1.5, markersize=4, label="% acumulado")
    eje_pct.axhline(80, color=COLOR_SECUNDARIO, linestyle="--", linewidth=1.2,
                    label="80% (regla de Pareto)")
    eje_pct.set_ylabel("Porcentaje acumulado")
    eje_pct.set_ylim(0, 105)
    eje_pct.legend(fontsize=7, loc="center right")

    vitales = min(n_vitales, len(conteo))
    principales = ", ".join(c.replace("_", " ").lower()
                            for c in conteo.index[:vitales])
    if vitales == 1:
        encabezado = (f"Una sola de las {len(conteo)} causas concentra el "
                      f"{acumulado.iloc[0]:.0f}% de las entregas retrasadas: "
                      f"{principales}")
        cierre = ("Concentrar el esfuerzo en esa única causa rinde más que "
                  "repartirlo entre todas.")
    else:
        encabezado = (f"{vitales} de {len(conteo)} causas concentran el "
                      f"{acumulado.iloc[vitales - 1]:.0f}% de las entregas "
                      f"retrasadas: {principales}")
        cierre = ("Atacar esas pocas causas rinde más que repartir el esfuerzo "
                  "entre todas.")
    return (f"{encabezado}, con {conteo.iloc[0]:,} entregas "
            f"({100 * conteo.iloc[0] / conteo.sum():.0f}%). {cierre}")


# ==========================================================================
# 7 · RUTAS MÁS UTILIZADAS   (§18.1 #1)
# ==========================================================================
def rutas_mas_utilizadas(ax, hechos: pd.DataFrame, dim_ruta: pd.DataFrame,
                         top: int = 10) -> str:
    codigos = dict(zip(dim_ruta["_id"], dim_ruta["codigo_ruta"]))
    resumen = (hechos.assign(ruta=hechos["ruta_id"].map(codigos))
               .groupby("ruta")
               .agg(entregas=("numero_entregas", "sum"),
                    viajes=("folio_viaje", "nunique"),
                    retraso=("retraso_min", "mean"))
               .sort_values("entregas", ascending=False).head(top)
               .sort_values("entregas"))

    colores = [COLOR_ALERTA if r > settings.UMBRAL_RETRASO_MIN else COLOR_PRINCIPAL
               for r in resumen["retraso"]]
    ax.barh(resumen.index, resumen["entregas"], color=colores, alpha=0.85)
    for i, (entregas, retraso) in enumerate(zip(resumen["entregas"],
                                                resumen["retraso"])):
        ax.text(entregas * 1.01, i, f"{retraso:.1f} min", va="center", fontsize=7)
    ax.set_title(f"Las {top} rutas más utilizadas "
                 f"(etiqueta = retraso medio; rojo si supera el umbral)",
                 fontsize=10, fontweight="bold")
    ax.set_xlabel("Entregas realizadas")
    ax.set_ylabel("Ruta")
    ax.grid(alpha=0.25, axis="x")

    lider = resumen.index[-1]
    criticas = int((resumen["retraso"] > settings.UMBRAL_RETRASO_MIN).sum())
    if criticas:
        cierre = (f"{criticas} de ellas superan en promedio el umbral de "
                  f"{settings.UMBRAL_RETRASO_MIN} minutos, y son prioritarias "
                  "porque su impacto se multiplica por el volumen que mueven.")
    else:
        cierre = (f"Ninguna supera en promedio el umbral de "
                  f"{settings.UMBRAL_RETRASO_MIN} minutos: el retraso de la "
                  "operación no proviene de las rutas de mayor volumen, sino "
                  "de rutas concretas con problemas propios.")
    return (f"La ruta más utilizada es {lider}, con "
            f"{int(resumen['entregas'].iloc[-1]):,} entregas. {cierre}")


# ==========================================================================
# 8 · COSTO Y RENDIMIENTO POR VEHÍCULO   (§18.1 #2 y #5)
# ==========================================================================
def costo_por_vehiculo(ax, dim_vehiculo: pd.DataFrame, top: int = 10) -> str:
    datos = (dim_vehiculo.dropna(subset=["costo_total_operacion"])
             .sort_values("costo_total_operacion", ascending=False).head(top))
    posiciones = np.arange(len(datos))

    ax.bar(posiciones, datos["costo_combustible"], color=COLOR_PRINCIPAL,
           alpha=0.85, label="Combustible")
    ax.bar(posiciones, datos["costo_mantenimiento"],
           bottom=datos["costo_combustible"], color=COLOR_SECUNDARIO,
           alpha=0.85, label="Mantenimiento")
    ax.set_xticks(posiciones)
    ax.set_xticklabels(datos["codigo_vehiculo"], rotation=45, fontsize=7)
    ax.set_title(f"Los {top} vehículos de mayor costo y su rendimiento",
                 fontsize=10, fontweight="bold")
    ax.set_xlabel("Vehículo")
    ax.set_ylabel("Costo del periodo (MXN)")
    ax.legend(fontsize=7, loc="upper right")
    ax.grid(alpha=0.25, axis="y")

    eje_rend = ax.twinx()
    eje_rend.plot(posiciones, datos["rendimiento_real_km_l"], color=COLOR_ALERTA,
                  marker="o", linewidth=1.5, markersize=5, label="Rendimiento real")
    eje_rend.plot(posiciones, datos["rendimiento_nominal_km_l"], color=COLOR_NEUTRO,
                  linestyle="--", linewidth=1.2, label="Rendimiento nominal")
    eje_rend.set_ylabel("Rendimiento (km/l)", color=COLOR_ALERTA)
    eje_rend.tick_params(axis="y", labelcolor=COLOR_ALERTA)
    eje_rend.legend(fontsize=7, loc="lower right")

    caro = datos.iloc[0]
    peor = datos.loc[datos["desviacion_rendimiento_pct"].idxmin()]
    return (f"{caro['codigo_vehiculo']} es el vehículo más costoso del periodo "
            f"(${caro['costo_total_operacion']:,.0f}, "
            f"${caro['costo_total_por_km']:.2f} por km). El de mayor desviación "
            f"de rendimiento es {peor['codigo_vehiculo']}: "
            f"{peor['rendimiento_real_km_l']:.2f} km/l reales frente a "
            f"{peor['rendimiento_nominal_km_l']:.2f} nominales "
            f"({peor['desviacion_rendimiento_pct']:.1f}%), señal de revisión "
            "mecánica antes que de reemplazo.")


# ==========================================================================
# 9 · DESEMPEÑO DE OPERADORES   (§18.1 #3)
# ==========================================================================
def desempeno_operadores(ax, dim_operador: pd.DataFrame) -> str:
    # Se grafica la plantilla COMPLETA, no un recorte: al mostrar solo los
    # mejores, el texto citaba a un operador ausente de la gráfica y el
    # rango real quedaba invisible, que es justo el hallazgo relevante.
    datos = (dim_operador.dropna(subset=["porcentaje_entregas_a_tiempo"])
             .sort_values("porcentaje_entregas_a_tiempo", ascending=False))
    posiciones = np.arange(len(datos))
    media = dim_operador["porcentaje_entregas_a_tiempo"].mean()

    colores = [COLOR_BIEN if p >= media else COLOR_ALERTA
               for p in datos["porcentaje_entregas_a_tiempo"]]
    ax.bar(posiciones, datos["porcentaje_entregas_a_tiempo"], color=colores,
           alpha=0.85)
    ax.axhline(media, color="black", linestyle="--", linewidth=1.2,
               label=f"Promedio de la flotilla ({media:.1f}%)")
    ax.set_xticks(posiciones)
    ax.set_xticklabels(datos["codigo_operador"], rotation=90, fontsize=6.5)
    ax.set_ylim(min(datos["porcentaje_entregas_a_tiempo"]) - 3,
                max(datos["porcentaje_entregas_a_tiempo"]) + 3)
    ax.set_title(f"Puntualidad de los {len(datos)} operadores",
                 fontsize=10, fontweight="bold")
    ax.set_xlabel("Operador")
    ax.set_ylabel("Entregas a tiempo (%)")
    ax.legend(fontsize=7)
    ax.grid(alpha=0.25, axis="y")

    mejor, peor = datos.iloc[0], datos.iloc[-1]
    rango = (mejor["porcentaje_entregas_a_tiempo"]
             - peor["porcentaje_entregas_a_tiempo"])
    return (f"El operador más puntual es {mejor['codigo_operador']} con "
            f"{mejor['porcentaje_entregas_a_tiempo']:.1f}% de entregas a tiempo; "
            f"el menor es {peor['codigo_operador']} con "
            f"{peor['porcentaje_entregas_a_tiempo']:.1f}%. El rango es de solo "
            f"{rango:.1f} puntos, así que el retraso NO se explica principalmente "
            "por quién conduce: buscarlo en la ruta y el horario es más "
            "productivo que en el desempeño individual.")


# ==========================================================================
# 10 · VEHÍCULOS QUE REQUIEREN MANTENIMIENTO   (§18.1 #7)
# ==========================================================================
def mantenimiento_pendiente(ax, hechos: pd.DataFrame,
                            dim_vehiculo: pd.DataFrame,
                            umbral_dias: int = 30) -> str:
    # El estado que interesa es el del CIERRE del periodo, no el peor momento
    # de la historia: se toma el valor de la última entrega de cada vehículo.
    # Usar max() daría la mayor brecha jamás alcanzada, que ya se resolvió.
    ultimos = (hechos.sort_values("fecha")
               .dropna(subset=["dias_desde_mantenimiento"])
               .groupby("vehiculo_id")["dias_desde_mantenimiento"]
               .last())
    datos = (dim_vehiculo.set_index("_id")
             .join(ultimos.rename("dias"), how="inner")
             .dropna(subset=["dias"])
             .sort_values("dias", ascending=False).head(12))

    colores = [COLOR_ALERTA if d >= umbral_dias else COLOR_PRINCIPAL
               for d in datos["dias"]]
    ax.bar(np.arange(len(datos)), datos["dias"], color=colores, alpha=0.85)
    ax.axhline(umbral_dias, color=COLOR_ALERTA, linestyle="--", linewidth=1.5,
               label=f"Umbral de servicio ({umbral_dias} días)")
    ax.set_xticks(np.arange(len(datos)))
    ax.set_xticklabels(datos["codigo_vehiculo"], rotation=45, fontsize=7)
    ax.set_title("Días desde el último mantenimiento",
                 fontsize=10, fontweight="bold")
    ax.set_xlabel("Vehículo")
    ax.set_ylabel("Días transcurridos")
    ax.legend(fontsize=7)
    ax.grid(alpha=0.25, axis="y")

    excedidos = int((datos["dias"] >= umbral_dias).sum())
    if excedidos:
        cierre = (f"{excedidos} de ellos ya rebasaron el umbral de "
                  f"{umbral_dias} días y deben programarse de inmediato: "
                  "dejarlos vencer los saca de operación de golpe, que es lo "
                  "que hoy deja rutas sin vehículo asignado.")
    else:
        cierre = (f"Ninguno rebasa el umbral de {umbral_dias} días, así que el "
                  "programa de mantenimiento está al corriente al cierre del "
                  "periodo.")
    return (f"Al cierre del periodo, el vehículo con más tiempo sin servicio es "
            f"{datos.iloc[0]['codigo_vehiculo']}, con "
            f"{int(datos.iloc[0]['dias'])} días. {cierre}")


# ==========================================================================
# 11 · CLUSTERS DE RUTAS EN EL PLANO PCA   (§18.1 #12)
# ==========================================================================
def clusters_rutas(ax, clusters: pd.DataFrame) -> str:
    # El color codifica severidad; los grupos que no la llevan reciben tonos
    # distintos entre sí, porque dos grupos del mismo color son un grupo a
    # los ojos de quien lee la gráfica.
    semanticos = {"CRÍTICAS": COLOR_ALERTA, "PROBLEMÁTICAS": COLOR_SECUNDARIO,
                  "LARGAS": COLOR_BIEN}
    reserva = iter((COLOR_PRINCIPAL, "#17becf", "#9467bd", "#8c564b"))

    asignados: dict[str, str] = {}
    for nombre in sorted(clusters["nombre_grupo"].unique()):
        color = next((c for clave, c in semanticos.items() if clave in nombre), None)
        asignados[nombre] = color or next(reserva, COLOR_NEUTRO)

    def color_de(nombre: str) -> str:
        return asignados[nombre]

    for nombre, grupo in clusters.groupby("nombre_grupo"):
        ax.scatter(grupo["componente_1"], grupo["componente_2"], s=110,
                   color=color_de(nombre), edgecolor="white", linewidth=1,
                   label=f"{nombre} ({len(grupo)})", zorder=3)
    for _, fila in clusters.iterrows():
        ax.annotate(fila["codigo_ruta"].replace("RUT-", ""),
                    (fila["componente_1"], fila["componente_2"]),
                    fontsize=6, ha="center", va="center", color="white",
                    fontweight="bold", zorder=4)
    ax.axhline(0, color="#cccccc", linewidth=0.8, zorder=1)
    ax.axvline(0, color="#cccccc", linewidth=0.8, zorder=1)
    ax.set_title("Grupos de rutas (K-Means sobre componentes principales)",
                 fontsize=10, fontweight="bold")
    ax.set_xlabel("Componente 1 — carga de trabajo de la ruta")
    ax.set_ylabel("Componente 2 — condiciones del recorrido")
    ax.legend(fontsize=6.5, loc="best")
    ax.grid(alpha=0.25, zorder=0)

    criticas = clusters[clusters["nombre_grupo"].str.contains("CRÍTICAS")]
    rutas = ", ".join(sorted(criticas["codigo_ruta"])) or "ninguna"
    return (f"El agrupamiento separa las {len(clusters)} rutas en "
            f"{clusters['nombre_grupo'].nunique()} perfiles operativos "
            f"(silueta {clusters['silueta_global'].iloc[0]:.3f}). El grupo "
            f"crítico reúne {len(criticas)} rutas: {rutas}. Son recorridos "
            "largos que además acumulan retraso, y por eso concentran la "
            "prioridad de rediseño.")


# ==========================================================================
# 12 · REAL VS PREDICHO DEL MODELO DE REGRESIÓN   (§18.1 #15)
# ==========================================================================
def real_vs_predicho(ax, hechos: pd.DataFrame, bd=None) -> str:
    import joblib

    from ml import evaluacion as ev

    ruta_modelo = RAIZ / "ml" / "modelos_guardados" / "regresion_retraso_en_ruta.joblib"
    if not ruta_modelo.exists():
        ax.text(0.5, 0.5, "Modelo no entrenado.\nEjecuta "
                          "ml.supervisado.regresion_retraso",
                ha="center", va="center", fontsize=9)
        ax.set_axis_off()
        return ("El modelo de regresión aún no está entrenado, así que esta "
                "gráfica no puede generarse.")

    modelo = joblib.load(ruta_modelo)
    X, y = ev.preparar(hechos, "EN_RUTA", "retraso_min")
    _, X_pru, _, y_pru = ev.dividir(X, y)
    prediccion = modelo.predict(X_pru)
    metricas = ev.metricas_regresion(y_pru, prediccion)

    ax.scatter(y_pru, prediccion, s=8, alpha=0.25, color=COLOR_PRINCIPAL,
               edgecolor="none")
    limites = [min(y_pru.min(), prediccion.min()), max(y_pru.max(), prediccion.max())]
    ax.plot(limites, limites, color=COLOR_ALERTA, linestyle="--", linewidth=1.8,
            label="Predicción perfecta")
    ax.set_title("Retraso real frente al predicho (conjunto de prueba)",
                 fontsize=10, fontweight="bold")
    ax.set_xlabel("Retraso real (minutos)")
    ax.set_ylabel("Retraso predicho (minutos)")
    ax.legend(fontsize=7)
    ax.grid(alpha=0.25)
    ax.text(0.03, 0.97,
            f"RMSE {metricas['rmse']:.2f} min\nMAE {metricas['mae']:.2f} min\n"
            f"R² {metricas['r2']:.3f}",
            transform=ax.transAxes, va="top", fontsize=7.5,
            bbox={"boxstyle": "round", "facecolor": "white", "alpha": 0.85})

    return (f"El modelo estima el retraso con un error típico de "
            f"{metricas['rmse']:.1f} minutos y explica el {metricas['r2']:.1%} de "
            "su variación. Los puntos por debajo de la diagonal en la zona alta "
            "muestran su límite conocido: subestima los retrasos extremos, así "
            "que la estimación debe acompañarse siempre de la alerta del "
            "clasificador.")
