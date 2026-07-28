"""
Dashboard macroeconómico interactivo para análisis de liquidez global,
Bitcoin y Solana.

Ejecución:
    streamlit run app.py
"""

import json
import logging
from datetime import timedelta, date
from typing import Any, Dict, Iterable, List, Optional, Tuple

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components
from plotly.subplots import make_subplots

from config import (
    COMBINED_LIQUIDITY_COMPONENTS,  # NUEVO: LIQUIDEZ GLOBAL COMBINADA
    COMBINED_LIQUIDITY_DEFAULT_SMA_WEEKS,  # NUEVO: LIQUIDEZ GLOBAL COMBINADA
    COMBINED_LIQUIDITY_MAX_SMA_WEEKS,  # NUEVO: LIQUIDEZ GLOBAL COMBINADA
    COMBINED_LIQUIDITY_MIN_SMA_WEEKS,  # NUEVO: LIQUIDEZ GLOBAL COMBINADA
    COMBINED_LIQUIDITY_RESAMPLE_RULE,  # NUEVO: LIQUIDEZ GLOBAL COMBINADA
    LAG_ACCELERATORS,
    LAG_DECELERATORS,
    LIQUIDITY_BASE_COMPONENTS,
    LIQUIDITY_REGION_COMPONENTS,
    LIQUIDITY_SIGNAL_ZSCORE_THRESHOLD,  # NUEVO: PANEL MACRO-BITCOIN AVANZADO
    MVRV_CAPITULATION_THRESHOLD,  # NUEVO: PANEL MACRO-BITCOIN AVANZADO
    STLFSI_PANIC_THRESHOLD,  # NUEVO: PANEL MACRO-BITCOIN AVANZADO
    STLFSI_SHADE_COLOR_RGB,  # NUEVO: PANEL MACRO-BITCOIN AVANZADO
    STLFSI_SHADE_OPACITY_HIGH,  # NUEVO: PANEL MACRO-BITCOIN AVANZADO
    STLFSI_SHADE_OPACITY_LOW,  # NUEVO: PANEL MACRO-BITCOIN AVANZADO
    STLFSI_STRESS_THRESHOLD,  # NUEVO: PANEL MACRO-BITCOIN AVANZADO
    US10Y_SMA_DEFAULT_WEEKS,  # NUEVO: PANEL MACRO-BITCOIN AVANZADO
    US10Y_SMA_MAX_WEEKS,  # NUEVO: PANEL MACRO-BITCOIN AVANZADO
    US10Y_SMA_MIN_WEEKS,  # NUEVO: PANEL MACRO-BITCOIN AVANZADO
)
from math_processor import build_master_dataframe, calculate_net_lag_days, recalculate_liquidity
from advanced_liquidity import (  # NUEVO: LIQUIDEZ GLOBAL COMBINADA
    build_combined_global_liquidity_index,
    build_macro_bitcoin_signals_view,  # NUEVO: PANEL MACRO-BITCOIN AVANZADO
    build_short_term_liquidity_view,
)
from data_ingestion import (  # NUEVO: LIQUIDEZ AVANZADA
    get_mvrv_zscore_history,  # NUEVO: PANEL MACRO-BITCOIN AVANZADO
    get_stablecoin_market_cap_history,
    get_usdt_stablecoin_dominance_history,
)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

LOGGER = logging.getLogger(__name__)


st.set_page_config(
    page_title="Macro Liquidity Terminal",
    page_icon="▪",
    layout="wide",
    initial_sidebar_state="expanded",
)


# =====================================================================
# REDISEÑO VISUAL (Dark Institutional Terminal) - SOLO CSS/HTML.
# =====================================================================
# IMPORTANTE: este bloque es puramente de presentación (CSS inyectado vía
# st.markdown). NO declara, redefine ni toca ninguna variable, función o
# columna usada por el motor de datos, el caché o los gráficos - solo
# cambia cómo se ven los contenedores nativos de Streamlit (fondo,
# bordes, tipografía, tabs, alertas, botones, inputs). Los colores
# semánticos de st.success/st.warning/st.error/st.info (verde/ámbar/
# rojo/azul) se conservan intactos; solo se aplanan sus bordes y sombras
# para que luzcan como una barra de estado técnica, no como un "toast" de
# prototipo.
INSTITUTIONAL_TERMINAL_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600;700&family=IBM+Plex+Sans:wght@400;500;600&display=swap');

:root {
    --ilt-bg: #08090b;
    --ilt-panel-bg: #0d0f12;
    --ilt-border: #232629;
    --ilt-border-soft: #1a1c1f;
    --ilt-text: #d8dadd;
    --ilt-text-muted: #7c8288;
    --ilt-accent: #c9a24b;
    --ilt-green: #2e9e5b;
    --ilt-amber: #c9862f;
    --ilt-red: #b3413a;
}

html, body, [data-testid="stAppViewContainer"], [data-testid="stHeader"] {
    background-color: var(--ilt-bg) !important;
    color: var(--ilt-text) !important;
    font-family: 'IBM Plex Sans', 'Segoe UI', sans-serif;
}

[data-testid="stHeader"] { background-color: transparent !important; border-bottom: 1px solid var(--ilt-border-soft); }

[data-testid="stSidebar"] {
    background-color: var(--ilt-panel-bg) !important;
    border-right: 1px solid var(--ilt-border);
}

/* Tipografía técnica en mayúsculas para todos los encabezados nativos */
h1, h2, h3, h4,
[data-testid="stMarkdownContainer"] h1,
[data-testid="stMarkdownContainer"] h2,
[data-testid="stMarkdownContainer"] h3 {
    font-family: 'IBM Plex Mono', monospace !important;
    text-transform: uppercase;
    letter-spacing: 0.09em;
    color: var(--ilt-text) !important;
    font-weight: 600 !important;
    border-bottom: 1px solid var(--ilt-border-soft);
    padding-bottom: 6px;
}

p, span, label, .stCaption, [data-testid="stCaptionContainer"] {
    font-family: 'IBM Plex Sans', 'Segoe UI', sans-serif;
    color: var(--ilt-text-muted);
}

/* Contenedores planos, sin sombras plásticas */
[data-testid="stExpander"] {
    background-color: var(--ilt-panel-bg) !important;
    border: 1px solid var(--ilt-border) !important;
    border-radius: 2px !important;
    box-shadow: none !important;
}
[data-testid="stExpander"] summary {
    font-family: 'IBM Plex Mono', monospace !important;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    font-size: 0.82rem;
}

/* Botones planos, sin bordes redondeados exagerados */
.stButton > button, .stDownloadButton > button {
    background-color: var(--ilt-panel-bg) !important;
    color: var(--ilt-text) !important;
    border: 1px solid var(--ilt-border) !important;
    border-radius: 2px !important;
    font-family: 'IBM Plex Mono', monospace !important;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    font-size: 0.78rem;
    box-shadow: none !important;
    transition: border-color 0.15s ease-in-out;
}
.stButton > button:hover, .stDownloadButton > button:hover {
    border-color: var(--ilt-accent) !important;
    color: var(--ilt-accent) !important;
}

/* Tabs estilo terminal: indicador de línea inferior, sin píldoras */
.stTabs [data-baseweb="tab-list"] {
    gap: 4px;
    border-bottom: 1px solid var(--ilt-border);
}
.stTabs [data-baseweb="tab"] {
    background-color: transparent !important;
    font-family: 'IBM Plex Mono', monospace !important;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    font-size: 0.8rem;
    color: var(--ilt-text-muted) !important;
    border-radius: 0 !important;
}
.stTabs [aria-selected="true"] {
    color: var(--ilt-text) !important;
    border-bottom: 2px solid var(--ilt-accent) !important;
}

/* Alertas (Health Check) aplanadas, colores semánticos intactos */
[data-testid="stAlert"] {
    border-radius: 2px !important;
    border: 1px solid var(--ilt-border) !important;
    box-shadow: none !important;
    font-family: 'IBM Plex Mono', monospace !important;
    font-size: 0.82rem;
}
div[data-baseweb="notification"] { border-radius: 2px !important; }

/* Inputs, selects, sliders: look minimalista */
[data-testid="stSelectbox"] div[data-baseweb="select"] > div,
[data-testid="stTextInput"] input,
[data-testid="stNumberInput"] input {
    background-color: var(--ilt-panel-bg) !important;
    border: 1px solid var(--ilt-border) !important;
    border-radius: 2px !important;
    color: var(--ilt-text) !important;
}
[data-testid="stSlider"] [data-baseweb="slider"] > div > div {
    background: var(--ilt-accent) !important;
}

/* Encabezado de sección con rótulo de opciones en la esquina */
.ilt-section-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    border-bottom: 1px solid var(--ilt-border);
    padding-bottom: 8px;
    margin-bottom: 14px;
}
.ilt-section-title {
    font-family: 'IBM Plex Mono', monospace;
    text-transform: uppercase;
    letter-spacing: 0.12em;
    font-size: 1.05rem;
    font-weight: 600;
    color: var(--ilt-text);
}
.ilt-section-options {
    font-family: 'IBM Plex Mono', monospace;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    font-size: 0.68rem;
    color: var(--ilt-text-muted);
    border: 1px solid var(--ilt-border);
    padding: 3px 10px;
    border-radius: 2px;
    white-space: nowrap;
}
</style>
"""

st.markdown(INSTITUTIONAL_TERMINAL_CSS, unsafe_allow_html=True)


def render_terminal_section_header(title: str, options_label: str = "OPCIONES") -> None:
    """
    Encabezado de sección estilo terminal institucional: título técnico en
    mayúsculas a la izquierda y un rótulo minimalista de opciones a la
    derecha (puramente visual, no agrega ni quita ninguna funcionalidad).

    Esta función SOLO renderiza HTML/CSS vía st.markdown - no descarga ni
    procesa ningún dato, y no reemplaza ninguna llamada existente al
    motor de liquidez, al caché o a los constructores de figuras.

    Parameters
    ----------
    title : str
        Título de la sección (se muestra tal cual, en mayúsculas por CSS).
    options_label : str
        Texto minimalista de la esquina superior derecha del panel.
    """
    try:
        st.markdown(
            f"""
            <div class="ilt-section-header">
                <span class="ilt-section-title">{title}</span>
                <span class="ilt-section-options">{options_label}</span>
            </div>
            """,
            unsafe_allow_html=True,
        )
    except Exception as error:
        LOGGER.exception(
            "Error al renderizar encabezado de sección. Tipo: %s. Detalle: %s",
            type(error).__name__,
            error,
        )
        st.subheader(title)


ASSET_OPTIONS = {
    "Bitcoin (BTC-USD)": "BTC_Close",
    "Solana (SOL-USD)": "SOL_Close",
}

# ACTUALIZACIÓN PARCHE: ya no se busca en varias columnas candidatas; la
# columna canónica de dominancia es USDT_Dominance (viene de CoinGecko en
# data_ingestion.py cuando hay COINGECKO_API_KEY configurada).
USDT_DOMINANCE_COLUMN = "USDT_Dominance"

# ACTUALIZACIÓN PARCHE: proporciones por defecto de los paneles divididos,
# usadas también por el botón "Restaurar Proporción Original".
DEFAULT_SPLIT_WIDTH_RATIO = 60  # % de ancho para el panel de liquidez
DEFAULT_PANEL_HEIGHT = 500

# MEJORA TRADINGVIEW: alturas por defecto del layout vertical (activo arriba,
# liquidez abajo) y config nativa de Plotly para que el gráfico se comporte
# como TradingView:
#   - scrollZoom: la rueda del mouse hace zoom horizontal sobre el tiempo.
#   - fixedrange=False en los ejes (ver más abajo, en cada figura): permite
#     arrastrar el eje Y para comprimir/estirar la escala de valores; Plotly
#     cambia el cursor automáticamente al pasar sobre el eje (comportamiento
#     nativo, no hace falta JS adicional).
#   - dragmode="pan": arrastrar DENTRO del gráfico desplaza el tiempo en vez
#     de dibujar un rectángulo de zoom, igual que en TradingView.
DEFAULT_ASSET_PANEL_HEIGHT = 420
DEFAULT_LIQUIDITY_PANEL_HEIGHT = 420

TRADINGVIEW_PLOTLY_CONFIG = {
    "scrollZoom": True,
    "displaylogo": False,
    "displayModeBar": True,
    "doubleClick": "reset",
    "modeBarButtonsToAdd": ["drawline", "drawrect", "eraseshape"],
}

GUIDE_LINE_TARGETS = ("Panel de Liquidez", "Panel de Precio")

# MEJORA TRADINGVIEW (Requerimiento 1 y 2): configuración del panel único
# sincronizado. DEFAULT_VERTICAL_AMPLIFICATION = 1.0 significa "auto-ajuste
# normal, sin exagerar la escala". Los usuarios pueden subirlo si su serie
# es genuinamente plana y quieren verla más "dramática".
DEFAULT_VERTICAL_AMPLIFICATION = 1.0
MIN_VERTICAL_AMPLIFICATION = 0.5
MAX_VERTICAL_AMPLIFICATION = 6.0
Y_AUTOSCALE_PADDING_RATIO = 0.08  # 8% de aire arriba/abajo del rango visible


@st.cache_data(ttl=900, show_spinner=False)
def load_master_dataframe() -> Tuple[pd.DataFrame, Dict[str, str]]:
    """
    Construye y almacena temporalmente el DataFrame Maestro.

    ACTUALIZACIÓN PARCHE: ahora devuelve también el reporte de salud de
    cada fuente de datos (health check), usado en el panel de auditoría.

    Returns
    -------
    Tuple[pd.DataFrame, Dict[str, str]]
        DataFrame Maestro procesado por math_processor.py, y el reporte
        de salud por fuente.
    """
    try:
        LOGGER.info("Solicitando DataFrame Maestro al procesador matemático.")

        dataframe, health_report = build_master_dataframe()

        if not isinstance(dataframe, pd.DataFrame):
            raise TypeError(
                "build_master_dataframe() no devolvió un DataFrame de Pandas."
            )

        if dataframe.empty:
            LOGGER.warning("El DataFrame Maestro recibido está vacío.")
            return pd.DataFrame(), health_report

        if "Date" not in dataframe.columns:
            raise ValueError(
                "El DataFrame Maestro no contiene la columna Date."
            )

        dataframe = dataframe.copy()
        dataframe["Date"] = pd.to_datetime(
            dataframe["Date"],
            errors="coerce",
        )

        dataframe = dataframe.dropna(subset=["Date"])
        dataframe = dataframe.drop_duplicates(subset=["Date"], keep="last")
        dataframe = dataframe.sort_values(by="Date")
        dataframe = dataframe.reset_index(drop=True)

        LOGGER.info(
            "DataFrame Maestro cargado correctamente. Filas: %s.",
            len(dataframe),
        )

        return dataframe, health_report

    except Exception as error:
        LOGGER.exception(
            "Error al cargar el DataFrame Maestro. Tipo: %s. Detalle: %s",
            type(error).__name__,
            error,
        )
        return pd.DataFrame(), {}


# NUEVO: LIQUIDEZ AVANZADA - historial de stablecoins (DefiLlama), cacheado
# por separado del DataFrame Maestro porque viene de una API distinta y con
# su propia cadencia de fallos.
@st.cache_data(ttl=1800, show_spinner=False)
def load_stablecoin_history() -> pd.DataFrame:
    """
    Descarga (con caché de 30 min) el historial sumado de capitalización de
    stablecoins vía DefiLlama.
    """
    try:
        return get_stablecoin_market_cap_history()
    except Exception as error:
        LOGGER.exception(
            "Error al cargar historial de stablecoins. Tipo: %s. Detalle: %s",
            type(error).__name__,
            error,
        )
        return pd.DataFrame(columns=["Date", "Stablecoin_MCap_USD"])


# NUEVO: PANEL MACRO-BITCOIN AVANZADO - historial del MVRV Z-Score,
# cacheado por separado (fuente distinta a FRED/Yahoo, con su propia
# cadencia de fallos, igual criterio que load_stablecoin_history).
#
# ACTUALIZACIÓN (Trazabilidad de Datos Total): ahora devuelve también los
# metadatos de origen (fuente_datos, fecha_actualizacion) que entrega
# get_mvrv_zscore_history(), para que el Health Check de la pestaña pueda
# mostrar el estado REAL del dato (API Directa / Caché Local / Sin Datos)
# en vez de depender del diccionario global DATA_HEALTH.
@st.cache_data(ttl=1800, show_spinner=False)
def load_mvrv_zscore_history() -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    Descarga (con caché de 30 min) el historial del MVRV Z-Score de
    Bitcoin vía la API de BGeometrics, junto con sus metadatos de
    trazabilidad (fuente_datos y fecha_actualizacion).
    """
    try:
        return get_mvrv_zscore_history()
    except Exception as error:
        LOGGER.exception(
            "Error al cargar historial de MVRV Z-Score. Tipo: %s. Detalle: %s",
            type(error).__name__,
            error,
        )
        return pd.DataFrame(columns=["Date", "MVRV_Zscore"]), {
            "fuente_datos": "Sin Datos",
            "fecha_actualizacion": None,
        }


def get_peak_ranges(dataframe: pd.DataFrame) -> Iterable[Tuple[pd.Timestamp, pd.Timestamp]]:
    """
    Agrupa días consecutivos con Es_Pico=True para crear zonas sombreadas.

    Parameters
    ----------
    dataframe : pd.DataFrame
        DataFrame con Date y Es_Pico.

    Returns
    -------
    Iterable[Tuple[pd.Timestamp, pd.Timestamp]]
        Rangos de inicio y finalización de cada pico de liquidez.
    """
    try:
        if dataframe.empty or "Es_Pico" not in dataframe.columns:
            return []

        peak_dataframe = dataframe.loc[:, ["Date", "Es_Pico"]].copy()
        peak_dataframe["Es_Pico"] = peak_dataframe["Es_Pico"].fillna(False).astype(bool)
        peak_dataframe = peak_dataframe.sort_values(by="Date")

        peak_dates = peak_dataframe.loc[
            peak_dataframe["Es_Pico"],
            "Date",
        ].tolist()

        if not peak_dates:
            return []

        peak_ranges = []
        start_date = peak_dates[0]
        previous_date = peak_dates[0]

        for current_date in peak_dates[1:]:
            if (current_date - previous_date).days > 1:
                peak_ranges.append((start_date, previous_date))
                start_date = current_date

            previous_date = current_date

        peak_ranges.append((start_date, previous_date))

        return peak_ranges

    except Exception as error:
        LOGGER.exception(
            "Error al identificar rangos de picos. Tipo: %s. Detalle: %s",
            type(error).__name__,
            error,
        )
        return []


def add_projection_line(
    figure: go.Figure,
    projection_date: pd.Timestamp,
    label: str,
    color: str,
) -> go.Figure:
    """
    Añade una línea vertical discontinua de proyección al gráfico.

    Parameters
    ----------
    figure : go.Figure
        Figura Plotly a modificar.
    projection_date : pd.Timestamp
        Fecha de la proyección.
    label : str
        Texto visible sobre la línea.
    color : str
        Color CSS o hexadecimal para la línea.

    Returns
    -------
    go.Figure
        Figura con la línea vertical incorporada.
    """
    try:
        figure.add_shape(
            type="line",
            x0=projection_date,
            x1=projection_date,
            y0=0,
            y1=1,
            xref="x",
            yref="paper",
            line={
                "color": color,
                "width": 2,
                "dash": "dash",
            },
        )

        figure.add_annotation(
            x=projection_date,
            y=1,
            xref="x",
            yref="paper",
            text=label,
            showarrow=False,
            yshift=12,
            font={
                "color": color,
                "size": 11,
            },
            bgcolor="rgba(15, 23, 42, 0.75)",
            bordercolor=color,
            borderwidth=1,
        )

        return figure

    except Exception as error:
        LOGGER.exception(
            "Error al añadir línea de proyección %s. Tipo: %s. Detalle: %s",
            label,
            type(error).__name__,
            error,
        )
        return figure


def _extend_dataframe_for_offset(
    dataframe: pd.DataFrame,
    offset_periods: int,
    freq: str = "D",
) -> pd.DataFrame:
    """
    MEJORA TRADINGVIEW (Requerimiento 3 - corrección de recorte): agrega
    filas de fechas futuras al final del DataFrame antes de desplazar la
    liquidez.

    El bug original: pandas .shift(periods=N) empuja los últimos N valores
    de la serie "fuera" del arreglo porque no hay filas nuevas donde
    colocarlos, y esos valores simplemente se pierden. Visualmente se veía
    como si la línea se cortara de golpe en el borde derecho.

    La corrección: se extiende el DataFrame con N fechas futuras (vacías en
    todo lo demás) ANTES de desplazar, para que el shift tenga espacio real
    donde colocar esos valores desplazados. El eje X del gráfico también se
    ajusta dinámicamente para mostrar ese tramo extendido.

    NUEVO: LIQUIDEZ AVANZADA (cambio de temporalidad) - ahora acepta
    `freq` para poder extender también series semanales ("W-WED") o
    mensuales ("ME"), no solo diarias. El Panel Principal y el Corto Plazo
    siguen usando el valor por defecto "D" sin ningún cambio de comportamiento.

    Parameters
    ----------
    dataframe : pd.DataFrame
        DataFrame ya ordenado por Date.
    offset_periods : int
        Cantidad de períodos de desfase solicitados (días, semanas o meses
        según `freq`).
    freq : str
        Frecuencia de pandas para las fechas futuras a agregar: "D"
        (diario, default), "W-WED" (semanal, cierre miércoles) o "ME"
        (mensual, fin de mes).

    Returns
    -------
    pd.DataFrame
        DataFrame extendido (o el original si offset_periods <= 0).
    """
    try:
        if offset_periods <= 0 or dataframe.empty:
            return dataframe.copy()

        last_date = dataframe["Date"].max()

        # date_range con periods=N+1 y freq dado, descartando el primer
        # punto (que es la propia last_date), garantiza el espaciado
        # correcto sin tener que calcular manualmente el "+1 día/semana/mes"
        # para cada tipo de frecuencia.
        future_dates = pd.date_range(start=last_date, periods=offset_periods + 1, freq=freq)[1:]

        extension_dataframe = pd.DataFrame({"Date": future_dates})

        extended_dataframe = pd.concat(
            [dataframe, extension_dataframe],
            ignore_index=True,
            sort=False,
        )

        return extended_dataframe

    except Exception as error:
        LOGGER.exception(
            "Error al extender el DataFrame para el desfase. "
            "Tipo: %s. Detalle: %s",
            type(error).__name__,
            error,
        )
        return dataframe.copy()


def _prepare_chart_dataframe(dataframe: pd.DataFrame, offset_days: int) -> pd.DataFrame:
    """
    Prepara una copia del DataFrame Maestro con las columnas listas para
    graficar (liquidez cruda, suavizada y desfasada).

    MEJORA TRADINGVIEW: ahora extiende el eje de fechas hacia el futuro
    antes de aplicar el shift, para que el desfase no recorte el tramo
    final de la serie (ver _extend_dataframe_for_offset).

    Parameters
    ----------
    dataframe : pd.DataFrame
        DataFrame Maestro.
    offset_days : int
        Días para desplazar Liquidez_Suavizada hacia el futuro.

    Returns
    -------
    pd.DataFrame
        Copia lista para graficar, con margen dinámico si offset_days > 0.
    """
    chart_dataframe = dataframe.copy()
    chart_dataframe = chart_dataframe.sort_values(by="Date")
    chart_dataframe = chart_dataframe.reset_index(drop=True)

    # MEJORA TRADINGVIEW: margen dinámico para que el desfase no corte la serie.
    chart_dataframe = _extend_dataframe_for_offset(chart_dataframe, offset_days)
    chart_dataframe = chart_dataframe.sort_values(by="Date").reset_index(drop=True)

    chart_dataframe["Liquidez_Desfasada"] = (
        pd.to_numeric(chart_dataframe["Liquidez_Suavizada"], errors="coerce")
        .shift(periods=offset_days)
    )

    if "Liquidez_Global_Cruda" in chart_dataframe.columns:
        chart_dataframe["Liquidez_Cruda_Desfasada"] = (
            pd.to_numeric(chart_dataframe["Liquidez_Global_Cruda"], errors="coerce")
            .shift(periods=offset_days)
        )
    else:
        chart_dataframe["Liquidez_Cruda_Desfasada"] = chart_dataframe["Liquidez_Desfasada"]

    return chart_dataframe


def _add_peak_shading(
    figure: go.Figure,
    chart_dataframe: pd.DataFrame,
    row: Optional[int] = None,
) -> go.Figure:
    """
    Sombrea en verde tenue los rangos identificados como picos de liquidez.

    MEJORA TRADINGVIEW: acepta un `row` opcional para poder usarse también
    dentro de un subplot de varias filas (panel único dividido). Si `row`
    es None, se comporta exactamente igual que antes (figura de un solo panel).
    """
    peak_ranges = get_peak_ranges(chart_dataframe)

    for start_date, end_date in peak_ranges:
        try:
            vrect_kwargs = dict(
                x0=start_date,
                x1=end_date + timedelta(days=1),
                fillcolor="rgba(0, 255, 0, 0.1)",
                line_width=0,
                layer="below",
            )
            if row is not None:
                vrect_kwargs["row"] = row
                vrect_kwargs["col"] = 1
            figure.add_vrect(**vrect_kwargs)
        except Exception as error:
            LOGGER.exception(
                "Error al sombrear pico desde %s hasta %s. "
                "Tipo: %s. Detalle: %s",
                start_date,
                end_date,
                type(error).__name__,
                error,
            )

    return figure


# MEJORA TRADINGVIEW (Requerimiento 4): líneas guía horizontales/verticales.
# Se guardan en session_state como una lista de diccionarios y se vuelven a
# dibujar en cada rerun. No modifican ningún dato, solo son anotaciones
# visuales (igual que las líneas de soporte/resistencia en TradingView).
def _init_guide_lines_state() -> None:
    """Inicializa la lista de líneas guía en session_state si no existe."""
    if "guide_lines" not in st.session_state:
        st.session_state["guide_lines"] = []


def _apply_guide_lines(
    figure: go.Figure,
    target_panel: str,
    row: Optional[int] = None,
) -> go.Figure:
    """
    Dibuja sobre la figura las líneas guía cuyo panel objetivo coincide.

    MEJORA TRADINGVIEW: acepta un `row` opcional para poder usarse también
    dentro de un subplot de varias filas.

    Parameters
    ----------
    figure : go.Figure
        Figura a la que se le agregarán las líneas.
    target_panel : str
        Uno de GUIDE_LINE_TARGETS ("Panel de Liquidez" o "Panel de Precio").
    row : Optional[int]
        Fila del subplot donde dibujar (1-indexado). None si la figura no
        es un subplot de varias filas.

    Returns
    -------
    go.Figure
        Figura con las líneas guía correspondientes agregadas.
    """
    try:
        _init_guide_lines_state()

        for guide_line in st.session_state["guide_lines"]:
            if guide_line.get("target") != target_panel:
                continue

            try:
                if guide_line["orientation"] == "horizontal":
                    hline_kwargs = dict(
                        y=guide_line["value"],
                        line_color=guide_line["color"],
                        line_width=1.5,
                        line_dash="dot",
                        annotation_text=guide_line.get("label", ""),
                        annotation_position="top left",
                    )
                    if row is not None:
                        hline_kwargs["row"] = row
                        hline_kwargs["col"] = 1
                    figure.add_hline(**hline_kwargs)
                else:
                    vline_kwargs = dict(
                        x=guide_line["value"],
                        line_color=guide_line["color"],
                        line_width=1.5,
                        line_dash="dot",
                        annotation_text=guide_line.get("label", ""),
                        annotation_position="top",
                    )
                    if row is not None:
                        vline_kwargs["row"] = row
                        vline_kwargs["col"] = 1
                    figure.add_vline(**vline_kwargs)
            except Exception as error:
                LOGGER.exception(
                    "Error al dibujar línea guía %s. Tipo: %s. Detalle: %s",
                    guide_line,
                    type(error).__name__,
                    error,
                )

        return figure

    except Exception as error:
        LOGGER.exception(
            "Error al aplicar líneas guía. Tipo: %s. Detalle: %s",
            type(error).__name__,
            error,
        )
        return figure


def _apply_guide_lines_combined(figure: go.Figure) -> go.Figure:
    """
    Variante de _apply_guide_lines para el gráfico Combinado, que tiene dos
    ejes Y (liquidez a la izquierda, precio a la derecha). Las líneas
    verticales se dibujan una sola vez (el eje X es compartido); las
    horizontales se dirigen al eje primario o secundario según el panel
    objetivo que el usuario haya elegido al crearlas.

    Parameters
    ----------
    figure : go.Figure
        Figura combinada (dual-axis) a la que se le agregarán las líneas.

    Returns
    -------
    go.Figure
        Figura con las líneas guía agregadas.
    """
    try:
        _init_guide_lines_state()

        for guide_line in st.session_state["guide_lines"]:
            try:
                if guide_line["orientation"] == "vertical":
                    figure.add_vline(
                        x=guide_line["value"],
                        line_color=guide_line["color"],
                        line_width=1.5,
                        line_dash="dot",
                        annotation_text=guide_line.get("label", ""),
                        annotation_position="top",
                    )
                else:
                    figure.add_hline(
                        y=guide_line["value"],
                        line_color=guide_line["color"],
                        line_width=1.5,
                        line_dash="dot",
                        annotation_text=guide_line.get("label", ""),
                        annotation_position="top left",
                        secondary_y=(guide_line.get("target") == "Panel de Precio"),
                    )
            except Exception as error:
                LOGGER.exception(
                    "Error al dibujar línea guía combinada %s. Tipo: %s. Detalle: %s",
                    guide_line,
                    type(error).__name__,
                    error,
                )

        return figure

    except Exception as error:
        LOGGER.exception(
            "Error al aplicar líneas guía combinadas. Tipo: %s. Detalle: %s",
            type(error).__name__,
            error,
        )
        return figure


def render_guide_lines_panel() -> None:
    """
    Renderiza el panel de control para añadir líneas guía horizontales y
    verticales, con selector de color, en reemplazo de atajos de teclado
    (Alt+H / Alt+V no son viables de forma confiable en Streamlit sin un
    componente JS/React aparte; estos controles hacen exactamente lo mismo
    con un clic).
    """
    st.markdown("---")
    st.subheader("LÍNEAS GUÍA (SOPORTES / RESISTENCIAS)")
    st.caption(
        "Marca niveles o fechas clave sobre cualquiera de los dos paneles. "
        "También puedes usar las herramientas de dibujo nativas de la "
        "barra de Plotly (ícono de línea/rectángulo, arriba a la derecha "
        "de cada gráfico) para trazar líneas libres del color elegido."
    )

    _init_guide_lines_state()

    color_column, target_column, clear_column = st.columns([1, 1, 1])

    with color_column:
        selected_color = st.color_picker(
            "Color de la línea guía",
            value="#FFFFFF",
            key="guide_line_color",
        )

    with target_column:
        selected_target = st.selectbox(
            "Panel objetivo",
            options=GUIDE_LINE_TARGETS,
            key="guide_line_target",
        )

    with clear_column:
        st.write("")
        st.write("")
        if st.button("BORRAR TODAS LAS LÍNEAS GUÍA"):
            st.session_state["guide_lines"] = []
            st.rerun()

    horizontal_column, vertical_column = st.columns(2)

    with horizontal_column:
        h_label = (
            "Valor Y (Billones USD)"
            if selected_target == "Panel de Liquidez"
            else "Valor Y (Precio en USD)"
        )
        h_value = st.number_input(
            f"LÍNEA HORIZONTAL — {h_label}",
            value=0.0,
            step=0.1,
            key="guide_h_value",
        )
        if st.button("Añadir línea horizontal"):
            st.session_state["guide_lines"].append(
                {
                    "orientation": "horizontal",
                    "value": h_value,
                    "color": selected_color,
                    "target": selected_target,
                    "label": f"{h_value:,.2f}",
                }
            )
            st.rerun()

    with vertical_column:
        v_date = st.date_input(
            "LÍNEA VERTICAL — FECHA",
            value=date.today(),
            key="guide_v_value",
        )
        if st.button("Añadir línea vertical"):
            st.session_state["guide_lines"].append(
                {
                    "orientation": "vertical",
                    "value": pd.Timestamp(v_date),
                    "color": selected_color,
                    "target": selected_target,
                    "label": v_date.strftime("%d-%m-%Y"),
                }
            )
            st.rerun()

    if st.session_state["guide_lines"]:
        st.caption(f"Líneas activas: {len(st.session_state['guide_lines'])}")


def create_main_figure(
    dataframe: pd.DataFrame,
    asset_label: str,
    asset_column: str,
    offset_days: int,
    selected_date: Optional[pd.Timestamp],
) -> go.Figure:
    """
    Construye el gráfico multi-eje principal de liquidez y precio (vista
    combinada, la misma que ya funcionaba, con una traza adicional).

    ACTUALIZACIÓN PARCHE (Requerimiento 3): se agrega la traza de
    Liquidez_Global cruda (antes del EMA) con line_shape='hv' para
    representarla como escalones, ya que refleja actualizaciones
    discretas de balances (semanales/mensuales), no una interpolación
    continua. La traza de Liquidez_Suavizada (verde, EMA de 14 días) se
    deja completamente intacta.

    Parameters
    ----------
    dataframe : pd.DataFrame
        DataFrame Maestro.
    asset_label : str
        Nombre de activo seleccionado en la interfaz.
    asset_column : str
        Columna de precio asociada al activo.
    offset_days : int
        Días para desplazar Liquidez_Suavizada hacia el futuro.
    selected_date : Optional[pd.Timestamp]
        Fecha seleccionada en el gráfico.

    Returns
    -------
    go.Figure
        Figura Plotly lista para renderizarse.
    """
    try:
        if dataframe.empty:
            raise ValueError(
                "No hay datos disponibles para construir el gráfico."
            )

        if asset_column not in dataframe.columns:
            raise ValueError(
                f"La columna de precio {asset_column} no existe."
            )

        if "Liquidez_Suavizada" not in dataframe.columns:
            raise ValueError(
                "La columna Liquidez_Suavizada no existe."
            )

        chart_dataframe = _prepare_chart_dataframe(dataframe, offset_days)

        chart_dataframe[asset_column] = pd.to_numeric(
            chart_dataframe[asset_column],
            errors="coerce",
        )

        figure = make_subplots(
            specs=[[{"secondary_y": True}]],
        )

        # ACTUALIZACIÓN PARCHE: línea de Liquidez Global cruda en escalones.
        figure.add_trace(
            go.Scatter(
                x=chart_dataframe["Date"],
                y=chart_dataframe["Liquidez_Cruda_Desfasada"],
                mode="lines",
                name=f"Liquidez Global Cruda ({offset_days}d)",
                line={
                    "color": "#3B82F6",
                    "width": 1.5,
                    "shape": "hv",
                },
                opacity=0.55,
                hovertemplate=(
                    "<b>Liquidez Global (Cruda)</b><br>"
                    "Fecha: %{x|%d-%m-%Y}<br>"
                    "Liquidez: %{y:,.2f} T USD"
                    "<extra></extra>"
                ),
            ),
            secondary_y=False,
        )

        # Traza sin modificar respecto al original: Liquidez Suavizada (EMA).
        figure.add_trace(
            go.Scatter(
                x=chart_dataframe["Date"],
                y=chart_dataframe["Liquidez_Desfasada"],
                mode="lines",
                name=f"Liquidez Suavizada ({offset_days}d)",
                line={
                    "color": "#00CC96",
                    "width": 3,
                },
                hovertemplate=(
                    "<b>Liquidez Suavizada</b><br>"
                    "Fecha: %{x|%d-%m-%Y}<br>"
                    "Liquidez: %{y:,.2f} T USD"
                    "<extra></extra>"
                ),
            ),
            secondary_y=False,
        )

        figure.add_trace(
            go.Scatter(
                x=chart_dataframe["Date"],
                y=chart_dataframe[asset_column],
                mode="lines",
                name=asset_label,
                line={
                    "color": "#F59E0B",
                    "width": 2,
                },
                hovertemplate=(
                    f"<b>{asset_label}</b><br>"
                    "Fecha: %{x|%d-%m-%Y}<br>"
                    "Precio: $%{y:,.2f}"
                    "<extra></extra>"
                ),
            ),
            secondary_y=True,
        )

        figure = _add_peak_shading(figure, chart_dataframe)

        if selected_date is not None:
            try:
                selected_timestamp = pd.Timestamp(selected_date).normalize()

                btc_projection_date = selected_timestamp + timedelta(days=7)
                sol_projection_date = selected_timestamp + timedelta(days=40)

                figure = add_projection_line(
                    figure=figure,
                    projection_date=btc_projection_date,
                    label="Impacto BTC +7 días",
                    color="#F59E0B",
                )

                figure = add_projection_line(
                    figure=figure,
                    projection_date=sol_projection_date,
                    label="Impacto SOL +40 días",
                    color="#A855F7",
                )

            except Exception as error:
                LOGGER.exception(
                    "Error al añadir proyecciones temporales. "
                    "Tipo: %s. Detalle: %s",
                    type(error).__name__,
                    error,
                )

        # MEJORA TRADINGVIEW: líneas guía horizontales/verticales dibujadas
        # por el usuario (Requerimiento 4).
        figure = _apply_guide_lines_combined(figure)

        figure.update_layout(
            title={
                "text": (
                    f"Liquidez Global vs. {asset_label} "
                    f"| Desfase: {offset_days} días"
                ),
                "x": 0.01,
                "xanchor": "left",
            },
            template="plotly_dark",
            paper_bgcolor="#0E1117",
            plot_bgcolor="#0E1117",
            height=650,
            hovermode="x unified",
            dragmode="pan",  # MEJORA TRADINGVIEW: arrastrar = desplazar tiempo, no dibujar zoom-box
            legend={
                "orientation": "h",
                "yanchor": "bottom",
                "y": 1.02,
                "xanchor": "right",
                "x": 1,
            },
            margin={
                "l": 10,
                "r": 10,
                "t": 80,
                "b": 10,
            },
            # MEJORA TRADINGVIEW: color de las formas dibujadas con las
            # herramientas nativas de la barra de Plotly (drawline/drawrect).
            newshape={"line": {"color": st.session_state.get("guide_line_color", "#FFFFFF")}},
        )

        # MEJORA TRADINGVIEW: rango de fechas explícito para que el margen
        # dinámico del desfase (offset) siempre sea visible, y fixedrange
        # desactivado para permitir arrastrar/zoom nativo sobre el eje.
        figure.update_xaxes(
            title_text="Fecha",
            showgrid=False,
            fixedrange=False,
            range=[chart_dataframe["Date"].min(), chart_dataframe["Date"].max()],
        )

        figure.update_yaxes(
            title_text="Liquidez Global (Billones USD)",
            secondary_y=False,
            showgrid=True,
            gridcolor="rgba(255, 255, 255, 0.08)",
            tickformat=",.2f",
            fixedrange=False,  # MEJORA TRADINGVIEW: arrastrar el eje Y estira/comprime la escala
        )

        figure.update_yaxes(
            title_text=f"Precio {asset_label} (USD)",
            secondary_y=True,
            showgrid=False,
            tickprefix="$",
            tickformat=",.2f",
            fixedrange=False,  # MEJORA TRADINGVIEW
        )

        return figure

    except Exception as error:
        LOGGER.exception(
            "Error al construir gráfico principal. Tipo: %s. Detalle: %s",
            type(error).__name__,
            error,
        )

        fallback_figure = go.Figure()
        fallback_figure.update_layout(
            template="plotly_dark",
            title="No fue posible construir el gráfico",
            height=500,
        )
        return fallback_figure


# ACTUALIZACIÓN PARCHE (Requerimiento 4): figuras independientes para el
# modo de "Paneles Divididos". Reutilizan los mismos datos que la vista
# combinada; no descargan ni recalculan nada por su cuenta.
def create_liquidity_only_figure(
    dataframe: pd.DataFrame,
    offset_days: int,
    panel_height: int,
) -> go.Figure:
    """
    Construye un panel independiente solo con las líneas de liquidez.
    """
    try:
        chart_dataframe = _prepare_chart_dataframe(dataframe, offset_days)

        figure = go.Figure()

        figure.add_trace(
            go.Scatter(
                x=chart_dataframe["Date"],
                y=chart_dataframe["Liquidez_Cruda_Desfasada"],
                mode="lines",
                name="Liquidez Global Cruda",
                line={"color": "#3B82F6", "width": 1.5, "shape": "hv"},
                opacity=0.55,
            ),
        )

        figure.add_trace(
            go.Scatter(
                x=chart_dataframe["Date"],
                y=chart_dataframe["Liquidez_Desfasada"],
                mode="lines",
                name="Liquidez Suavizada (EMA 14d)",
                line={"color": "#00CC96", "width": 3},
            ),
        )

        figure = _add_peak_shading(figure, chart_dataframe)

        # MEJORA TRADINGVIEW: líneas guía asignadas a este panel.
        figure = _apply_guide_lines(figure, target_panel="Panel de Liquidez")

        figure.update_layout(
            title="Panel de Liquidez Global",
            template="plotly_dark",
            paper_bgcolor="#0E1117",
            plot_bgcolor="#0E1117",
            height=panel_height,
            hovermode="x unified",
            dragmode="pan",  # MEJORA TRADINGVIEW
            legend={"orientation": "h", "yanchor": "bottom", "y": 1.02},
            margin={"l": 10, "r": 10, "t": 60, "b": 10},
            newshape={"line": {"color": st.session_state.get("guide_line_color", "#FFFFFF")}},
        )
        # MEJORA TRADINGVIEW: rango dinámico (no corta el desfase) + drag/zoom nativo.
        figure.update_xaxes(
            fixedrange=False,
            range=[chart_dataframe["Date"].min(), chart_dataframe["Date"].max()],
        )
        figure.update_yaxes(
            title_text="Liquidez (Billones USD)",
            gridcolor="rgba(255, 255, 255, 0.08)",
            fixedrange=False,
        )

        return figure

    except Exception as error:
        LOGGER.exception(
            "Error al construir panel de liquidez. Tipo: %s. Detalle: %s",
            type(error).__name__,
            error,
        )
        fallback_figure = go.Figure()
        fallback_figure.update_layout(template="plotly_dark", height=panel_height)
        return fallback_figure


def create_asset_only_figure(
    dataframe: pd.DataFrame,
    asset_label: str,
    asset_column: str,
    panel_height: int,
    offset_days: int = 0,
) -> go.Figure:
    """
    Construye un panel independiente solo con el precio del activo.

    MEJORA TRADINGVIEW: recibe offset_days únicamente para igualar el rango
    del eje X con el panel de liquidez (que sí se extiende hacia el futuro
    por el desfase). El precio del activo no se desplaza ni se inventa
    dato futuro alguno; solo se alinea visualmente el eje.
    """
    try:
        chart_dataframe = dataframe.copy().sort_values(by="Date")
        chart_dataframe[asset_column] = pd.to_numeric(
            chart_dataframe[asset_column], errors="coerce"
        )
        chart_dataframe = chart_dataframe.reset_index(drop=True)
        aligned_dataframe = _extend_dataframe_for_offset(chart_dataframe, offset_days)

        figure = go.Figure()
        figure.add_trace(
            go.Scatter(
                x=chart_dataframe["Date"],
                y=chart_dataframe[asset_column],
                mode="lines",
                name=asset_label,
                line={"color": "#F59E0B", "width": 2},
            ),
        )

        # MEJORA TRADINGVIEW: líneas guía asignadas a este panel.
        figure = _apply_guide_lines(figure, target_panel="Panel de Precio")

        figure.update_layout(
            title=f"Panel de Precio | {asset_label}",
            template="plotly_dark",
            paper_bgcolor="#0E1117",
            plot_bgcolor="#0E1117",
            height=panel_height,
            hovermode="x unified",
            dragmode="pan",  # MEJORA TRADINGVIEW
            legend={"orientation": "h", "yanchor": "bottom", "y": 1.02},
            margin={"l": 10, "r": 10, "t": 60, "b": 10},
            newshape={"line": {"color": st.session_state.get("guide_line_color", "#FFFFFF")}},
        )
        # MEJORA TRADINGVIEW: mismo rango de fechas que el panel de liquidez
        # (incluye el margen del desfase) + drag/zoom nativo.
        figure.update_xaxes(
            fixedrange=False,
            range=[aligned_dataframe["Date"].min(), aligned_dataframe["Date"].max()],
        )
        figure.update_yaxes(title_text="Precio (USD)", tickprefix="$", fixedrange=False)

        return figure

    except Exception as error:
        LOGGER.exception(
            "Error al construir panel de activo. Tipo: %s. Detalle: %s",
            type(error).__name__,
            error,
        )
        fallback_figure = go.Figure()
        fallback_figure.update_layout(template="plotly_dark", height=panel_height)
        return fallback_figure


# MEJORA TRADINGVIEW (Requerimientos 1 y 2): panel único dividido en dos
# filas (subplots verticales) con eje X compartido, crosshair sincronizado
# y auto-ajuste dinámico del eje Y por fila al hacer zoom.
def build_synced_dual_panel_figure(
    dataframe: pd.DataFrame,
    asset_label: str,
    asset_column: str,
    offset_days: int,
    asset_panel_height: int,
    liquidity_panel_height: int,
) -> Tuple[go.Figure, List[int], List[int]]:
    """
    Construye UN solo go.Figure con dos filas (activo arriba, liquidez
    abajo), eje X compartido y crosshair sincronizado. Reutiliza la misma
    preparación de datos (_prepare_chart_dataframe) que ya corrige el
    recorte por desfase, y las mismas líneas guía / sombreado de picos.

    También calcula, para cada trazo de liquidez, la "fecha real del dato"
    (Date - offset_days) y la expone vía customdata en el hover, para que
    el tooltip del panel inferior muestre la fecha original del dato de
    liquidez que quedó desplazado, no la fecha física en pantalla.

    Parameters
    ----------
    dataframe : pd.DataFrame
        DataFrame Maestro.
    asset_label : str
        Nombre del activo seleccionado.
    asset_column : str
        Columna de precio del activo.
    offset_days : int
        Días de desfase de liquidez.
    asset_panel_height : int
        Alto en píxeles del panel superior (activo).
    liquidity_panel_height : int
        Alto en píxeles del panel inferior (liquidez).

    Returns
    -------
    Tuple[go.Figure, List[int], List[int]]
        La figura, y los índices de traza (dentro de figure.data) que
        pertenecen a la fila 1 (activo) y a la fila 2 (liquidez),
        respectivamente. Estos índices los necesita el JS del componente
        para saber sobre qué trazos calcular el auto-ajuste de cada panel.
    """
    try:
        chart_dataframe = _prepare_chart_dataframe(dataframe, offset_days)
        chart_dataframe[asset_column] = pd.to_numeric(
            chart_dataframe[asset_column], errors="coerce"
        )

        # Fecha real del dato de liquidez (antes de ser desplazado). Ver
        # docstring: value(D_i) = Liquidez_Suavizada(D_i - offset_days), así
        # que la fecha real de origen es D_i - offset_days.
        source_dates = chart_dataframe["Date"] - pd.Timedelta(days=offset_days)

        total_height = max(asset_panel_height + liquidity_panel_height, 1)
        asset_ratio = asset_panel_height / total_height

        figure = make_subplots(
            rows=2,
            cols=1,
            shared_xaxes=True,
            vertical_spacing=0.05,
            row_heights=[asset_ratio, 1 - asset_ratio],
            subplot_titles=(asset_label, "Liquidez Global Compuesta"),
        )

        trace_index = 0
        row1_trace_indices: List[int] = []
        row2_trace_indices: List[int] = []

        figure.add_trace(
            go.Scatter(
                x=chart_dataframe["Date"],
                y=chart_dataframe[asset_column],
                mode="lines",
                name=asset_label,
                line={"color": "#F59E0B", "width": 2},
                hovertemplate=(
                    f"<b>{asset_label}</b><br>Fecha: %{{x|%d-%m-%Y}}<br>"
                    "Precio: $%{y:,.2f}<extra></extra>"
                ),
            ),
            row=1,
            col=1,
        )
        row1_trace_indices.append(trace_index)
        trace_index += 1

        figure.add_trace(
            go.Scatter(
                x=chart_dataframe["Date"],
                y=chart_dataframe["Liquidez_Cruda_Desfasada"],
                mode="lines",
                name="Liquidez Global Cruda",
                line={"color": "#3B82F6", "width": 1.5, "shape": "hv"},
                opacity=0.55,
                customdata=source_dates,
                hovertemplate=(
                    "<b>Liquidez Global (Cruda)</b><br>"
                    "Fecha en pantalla: %{x|%d-%m-%Y}<br>"
                    "Fecha real del dato: %{customdata|%d-%m-%Y}<br>"
                    "Liquidez: %{y:,.2f} T USD<extra></extra>"
                ),
            ),
            row=2,
            col=1,
        )
        row2_trace_indices.append(trace_index)
        trace_index += 1

        figure.add_trace(
            go.Scatter(
                x=chart_dataframe["Date"],
                y=chart_dataframe["Liquidez_Desfasada"],
                mode="lines",
                name="Liquidez Suavizada (EMA 14d)",
                line={"color": "#00CC96", "width": 3},
                customdata=source_dates,
                hovertemplate=(
                    "<b>Liquidez Suavizada</b><br>"
                    "Fecha en pantalla: %{x|%d-%m-%Y}<br>"
                    "Fecha real del dato: %{customdata|%d-%m-%Y}<br>"
                    "Liquidez: %{y:,.2f} T USD<extra></extra>"
                ),
            ),
            row=2,
            col=1,
        )
        row2_trace_indices.append(trace_index)
        trace_index += 1

        figure = _add_peak_shading(figure, chart_dataframe, row=2)
        figure = _apply_guide_lines(figure, target_panel="Panel de Precio", row=1)
        figure = _apply_guide_lines(figure, target_panel="Panel de Liquidez", row=2)

        figure.update_layout(
            template="plotly_dark",
            paper_bgcolor="#0E1117",
            plot_bgcolor="#0E1117",
            height=total_height,
            showlegend=True,
            legend={"orientation": "h", "yanchor": "bottom", "y": 1.0},
            margin={"l": 10, "r": 10, "t": 40, "b": 10},
            hovermode="x",  # una caja de hover por panel, sincronizadas por X
            dragmode="pan",
            newshape={"line": {"color": st.session_state.get("guide_line_color", "#FFFFFF")}},
        )

        # Crosshair sincronizado entre ambas filas + eje X realmente
        # compartido (matches="x") para que el zoom/pan se mueva junto.
        figure.update_xaxes(
            showspikes=True,
            spikemode="across",
            spikesnap="cursor",
            spikethickness=1,
            spikecolor="#94A3B8",
            spikedash="dot",
            fixedrange=False,
            matches="x",
            range=[chart_dataframe["Date"].min(), chart_dataframe["Date"].max()],
        )
        figure.update_yaxes(fixedrange=False)

        figure.update_xaxes(title_text="Fecha", row=2, col=1)
        figure.update_yaxes(
            title_text=f"Precio {asset_label} (USD)", tickprefix="$", row=1, col=1
        )
        figure.update_yaxes(title_text="Liquidez (Billones USD)", row=2, col=1)

        return figure, row1_trace_indices, row2_trace_indices

    except Exception as error:
        LOGGER.exception(
            "Error al construir el panel único sincronizado. Tipo: %s. Detalle: %s",
            type(error).__name__,
            error,
        )
        fallback_figure = go.Figure()
        fallback_figure.update_layout(template="plotly_dark", height=600)
        return fallback_figure, [], []


def render_synced_dual_panel_chart(
    figure: go.Figure,
    row1_trace_indices: List[int],
    row2_trace_indices: List[int],
    component_height: int,
    asset_amplification: float,
    liquidity_amplification: float,
) -> None:
    """
    Renderiza la figura de dos filas como un componente HTML con Plotly.js
    embebido directamente (en vez de st.plotly_chart), porque necesitamos
    escuchar el evento 'plotly_relayout' del navegador para recalcular el
    rango del eje Y de cada fila cuando el usuario hace zoom/pan en X -
    Plotly no hace esto automáticamente (limitación conocida de la
    librería). Esto es 100% del lado del navegador: no dispara reruns de
    Streamlit ni manda nada de vuelta a Python.

    Parameters
    ----------
    figure : go.Figure
        Figura construida por build_synced_dual_panel_figure.
    row1_trace_indices : List[int]
        Índices de traza que pertenecen al panel superior (activo).
    row2_trace_indices : List[int]
        Índices de traza que pertenecen al panel inferior (liquidez).
    component_height : int
        Alto total en píxeles del componente.
    asset_amplification : float
        Factor de estiramiento vertical manual del panel de activo.
    liquidity_amplification : float
        Factor de estiramiento vertical manual del panel de liquidez.
    """
    try:
        figure_json = figure.to_json()
        config_json = json.dumps(TRADINGVIEW_PLOTLY_CONFIG)
        row1_json = json.dumps(row1_trace_indices)
        row2_json = json.dumps(row2_trace_indices)

        html_code = f"""
<div id="tv-synced-chart" style="width:100%;"></div>
<script src="https://cdn.plot.ly/plotly-2.32.0.min.js"></script>
<script>
(function() {{
    const figSpec = {figure_json};
    const gd = document.getElementById('tv-synced-chart');
    const config = {config_json};
    const row1Traces = {row1_json};
    const row2Traces = {row2_json};
    const paddingRatio = {Y_AUTOSCALE_PADDING_RATIO};
    const ampRow1 = {asset_amplification};
    const ampRow2 = {liquidity_amplification};
    let adjusting = false;

    function visibleRange(traceIndices, xMin, xMax, amplification) {{
        let values = [];
        for (let t = 0; t < traceIndices.length; t++) {{
            const trace = gd.data[traceIndices[t]];
            if (!trace || !trace.x || !trace.y) {{ continue; }}
            for (let i = 0; i < trace.x.length; i++) {{
                const xv = new Date(trace.x[i]).getTime();
                const yv = trace.y[i];
                if (xv >= xMin && xv <= xMax && yv !== null && yv !== undefined && !isNaN(yv)) {{
                    values.push(yv);
                }}
            }}
        }}
        if (values.length === 0) {{ return null; }}

        let minV = Math.min.apply(null, values);
        let maxV = Math.max.apply(null, values);
        const center = (minV + maxV) / 2;
        let halfSpan = (maxV - minV) / 2;
        if (halfSpan === 0) {{
            // Serie realmente plana en este rango: usar un margen base
            // para que igual se pueda ver algo, y que el slider de
            // amplificación tenga efecto real.
            halfSpan = (Math.abs(center) > 0 ? Math.abs(center) * 0.02 : 1);
        }}
        const safeAmplification = amplification > 0 ? amplification : 1;
        const adjustedHalfSpan = halfSpan / safeAmplification;
        const pad = adjustedHalfSpan * paddingRatio;

        return [center - adjustedHalfSpan - pad, center + adjustedHalfSpan + pad];
    }}

    function applyAutoscale() {{
        if (adjusting) {{ return; }}

        let xMin, xMax;
        const xaxis = gd.layout.xaxis;
        if (xaxis && xaxis.range && xaxis.range.length === 2) {{
            xMin = new Date(xaxis.range[0]).getTime();
            xMax = new Date(xaxis.range[1]).getTime();
        }} else {{
            return;
        }}

        const range1 = visibleRange(row1Traces, xMin, xMax, ampRow1);
        const range2 = visibleRange(row2Traces, xMin, xMax, ampRow2);

        const updates = {{}};
        if (range1) {{
            updates['yaxis.range'] = range1;
            updates['yaxis.autorange'] = false;
        }}
        if (range2) {{
            updates['yaxis2.range'] = range2;
            updates['yaxis2.autorange'] = false;
        }}

        if (Object.keys(updates).length > 0) {{
            adjusting = true;
            Plotly.relayout(gd, updates).then(function() {{ adjusting = false; }})
                .catch(function() {{ adjusting = false; }});
        }}
    }}

    Plotly.newPlot(gd, figSpec.data, figSpec.layout, config).then(function() {{
        // Auto-ajuste inicial, para que la amplificación manual también
        // aplique antes de que el usuario haga zoom por primera vez.
        applyAutoscale();

        gd.on('plotly_relayout', function(eventData) {{
            if (adjusting) {{ return; }}
            applyAutoscale();
        }});
    }});
}})();
</script>
"""

        components.html(html_code, height=component_height + 40, scrolling=False)

    except Exception as error:
        LOGGER.exception(
            "Error al renderizar el panel único sincronizado. Tipo: %s. Detalle: %s",
            type(error).__name__,
            error,
        )
        st.error("No fue posible renderizar el panel único sincronizado.")


# NUEVO: LIQUIDEZ AVANZADA - figura de dos filas para la nueva pestaña,
# reutilizando exactamente el mismo componente de renderizado
# (render_synced_dual_panel_chart) que ya probamos para el panel principal:
# crosshair sincronizado, auto-ajuste de eje Y por zoom, scrollZoom,
# herramientas de dibujo y desfase sin recorte, todo gratis por reutilización.
INDEX_CHOICES = {
    "Liquidez Global Combinada (Fed + BCE, RoC 90d + Z-Score 52 semanas)": "Indice_Global_Final",
    "Corto Plazo (Índice de Liquidez Inmediata de Mercado, Z-Score 30 días)": "Indice_Corto_Plazo_Zscore",
}


def build_advanced_index_synced_figure(
    advanced_dataframe: pd.DataFrame,
    asset_label: str,
    asset_column: str,
    index_label: str,
    index_column: str,
    offset_periods: int,
    asset_panel_height: int,
    index_panel_height: int,
    offset_freq: str = "D",
    value_unit_label: str = "Z-Score",
    value_axis_title: str = "Z-Score (desviaciones estándar)",
    reference_lines: Optional[List[float]] = None,
) -> Tuple[go.Figure, List[int], List[int]]:
    """
    Construye la figura de dos filas (activo arriba, índice normalizado
    abajo) para la pestaña de Liquidez Avanzada.

    NUEVO: LIQUIDEZ GLOBAL COMBINADA - generalizado para soportar tanto el
    Z-Score (Corto Plazo) como el Rate of Change % (Liquidez Global
    Combinada), vía `value_unit_label`/`value_axis_title`/`reference_lines`,
    en vez de asumir siempre Z-Score.

    Parameters
    ----------
    advanced_dataframe : pd.DataFrame
        Resultado de build_combined_global_liquidity_index o
        build_short_term_liquidity_view, en la cadencia que corresponda.
    asset_label : str
        Nombre del activo (BTC o SOL).
    asset_column : str
        Columna de precio del activo.
    index_label : str
        Nombre visible del índice elegido.
    index_column : str
        Columna a graficar en el panel inferior.
    offset_periods : int
        Desfase en la unidad de `offset_freq`, con el mismo mecanismo
        anti-recorte que el panel principal.
    asset_panel_height : int
        Alto en píxeles del panel superior.
    index_panel_height : int
        Alto en píxeles del panel inferior.
    offset_freq : str
        "D" (días), "W-WED"/"W-FRI" (semanas) o "ME" (meses).
    value_unit_label : str
        Etiqueta corta de la unidad, usada en el hover (ej. "Z-Score" o "RoC 90d").
    value_axis_title : str
        Título completo del eje Y del panel inferior.
    reference_lines : Optional[List[float]]
        Valores en los que dibujar líneas de referencia punteadas (ej.
        [3, -3, 0] para Z-Score, o [0] para RoC). Por defecto [3, -3, 0].

    Returns
    -------
    Tuple[go.Figure, List[int], List[int]]
        Figura, índices de traza de la fila 1 y de la fila 2.
    """
    try:
        working_dataframe = advanced_dataframe.copy().sort_values(by="Date").reset_index(drop=True)
        working_dataframe[asset_column] = pd.to_numeric(
            working_dataframe[asset_column], errors="coerce"
        )

        # MEJORA TRADINGVIEW (reutilizado): margen dinámico para que el
        # desfase no corte la serie, igual que en el panel principal.
        chart_dataframe = _extend_dataframe_for_offset(
            working_dataframe, offset_periods, freq=offset_freq
        )
        chart_dataframe = chart_dataframe.sort_values(by="Date").reset_index(drop=True)

        chart_dataframe["Indice_Desfasado"] = pd.to_numeric(
            chart_dataframe[index_column], errors="coerce"
        ).shift(periods=offset_periods)

        # La "fecha real del dato" debe restarse en la misma unidad que el
        # desfase (días, semanas o meses); los meses no tienen una duración
        # fija en días, así que se usa pd.DateOffset en vez de Timedelta.
        if offset_periods > 0:
            if offset_freq.startswith("W"):
                source_dates = chart_dataframe["Date"] - pd.Timedelta(weeks=offset_periods)
            elif offset_freq.startswith("M"):
                source_dates = chart_dataframe["Date"] - pd.DateOffset(months=offset_periods)
            else:
                source_dates = chart_dataframe["Date"] - pd.Timedelta(days=offset_periods)
        else:
            source_dates = chart_dataframe["Date"]

        total_height = max(asset_panel_height + index_panel_height, 1)
        asset_ratio = asset_panel_height / total_height

        figure = make_subplots(
            rows=2,
            cols=1,
            shared_xaxes=True,
            vertical_spacing=0.05,
            row_heights=[asset_ratio, 1 - asset_ratio],
            subplot_titles=(asset_label, index_label),
        )

        row1_trace_indices: List[int] = [0]
        row2_trace_indices: List[int] = [1]

        figure.add_trace(
            go.Scatter(
                x=chart_dataframe["Date"],
                y=chart_dataframe[asset_column],
                mode="lines",
                name=asset_label,
                line={"color": "#F59E0B", "width": 2},
                hovertemplate=(
                    f"<b>{asset_label}</b><br>Fecha: %{{x|%d-%m-%Y}}<br>"
                    "Precio: $%{y:,.2f}<extra></extra>"
                ),
            ),
            row=1,
            col=1,
        )

        figure.add_trace(
            go.Scatter(
                x=chart_dataframe["Date"],
                y=chart_dataframe["Indice_Desfasado"],
                mode="lines",
                name=index_label,
                line={"color": "#38BDF8", "width": 2.5},
                customdata=source_dates,
                hovertemplate=(
                    f"<b>{index_label}</b><br>"
                    "Fecha en pantalla: %{x|%d-%m-%Y}<br>"
                    "Fecha real del dato: %{customdata|%d-%m-%Y}<br>"
                    f"{value_unit_label}: " + "%{y:.2f}<extra></extra>"
                ),
            ),
            row=2,
            col=1,
        )

        # Líneas de referencia configurables (+3/-3/0 para Z-Score, o solo
        # 0 para RoC%, que no tiene un umbral "extremo" universal).
        resolved_reference_lines = [3, -3, 0] if reference_lines is None else reference_lines
        for reference_value in resolved_reference_lines:
            line_style = (
                {"line_color": "rgba(255,255,255,0.4)", "line_dash": "dash"}
                if reference_value == 0
                else {"line_color": "rgba(255,255,255,0.25)", "line_dash": "dot"}
            )
            figure.add_hline(y=reference_value, row=2, col=1, **line_style)

        figure = _apply_guide_lines(figure, target_panel="Panel de Precio", row=1)
        figure = _apply_guide_lines(figure, target_panel="Panel de Liquidez", row=2)

        figure.update_layout(
            template="plotly_dark",
            paper_bgcolor="#0E1117",
            plot_bgcolor="#0E1117",
            height=total_height,
            showlegend=True,
            legend={"orientation": "h", "yanchor": "bottom", "y": 1.0},
            margin={"l": 10, "r": 10, "t": 40, "b": 10},
            hovermode="x",
            dragmode="pan",
            newshape={"line": {"color": st.session_state.get("guide_line_color", "#FFFFFF")}},
        )

        figure.update_xaxes(
            showspikes=True,
            spikemode="across",
            spikesnap="cursor",
            spikethickness=1,
            spikecolor="#94A3B8",
            spikedash="dot",
            fixedrange=False,
            matches="x",
            range=[chart_dataframe["Date"].min(), chart_dataframe["Date"].max()],
        )
        figure.update_yaxes(fixedrange=False)

        figure.update_xaxes(title_text="Fecha", row=2, col=1)
        figure.update_yaxes(title_text=f"Precio {asset_label} (USD)", tickprefix="$", row=1, col=1)
        figure.update_yaxes(title_text=value_axis_title, row=2, col=1)

        return figure, row1_trace_indices, row2_trace_indices

    except Exception as error:
        LOGGER.exception(
            "Error al construir la figura de Liquidez Avanzada. Tipo: %s. Detalle: %s",
            type(error).__name__,
            error,
        )
        fallback_figure = go.Figure()
        fallback_figure.update_layout(template="plotly_dark", height=600)
        return fallback_figure, [], []


def extract_selected_date(selection_event: Any) -> Optional[pd.Timestamp]:
    """
    Extrae la fecha de un punto seleccionado desde st.plotly_chart.

    Parameters
    ----------
    selection_event : Any
        Evento retornado por st.plotly_chart.

    Returns
    -------
    Optional[pd.Timestamp]
        Fecha seleccionada o None si no existe una selección válida.
    """
    try:
        if selection_event is None:
            return None

        if hasattr(selection_event, "get"):
            selection = selection_event.get("selection", {})
        else:
            selection = getattr(selection_event, "selection", {})

        if hasattr(selection, "get"):
            selected_points = selection.get("points", [])
        else:
            selected_points = getattr(selection, "points", [])

        if not selected_points:
            return None

        first_point = selected_points[0]

        if hasattr(first_point, "get"):
            raw_date = first_point.get("x")
        else:
            raw_date = getattr(first_point, "x", None)

        if raw_date is None:
            return None

        selected_date = pd.to_datetime(raw_date, errors="coerce")

        if pd.isna(selected_date):
            return None

        return pd.Timestamp(selected_date).normalize()

    except Exception as error:
        LOGGER.exception(
            "Error al extraer fecha seleccionada. Tipo: %s. Detalle: %s",
            type(error).__name__,
            error,
        )
        return None


def get_seven_day_trend(
    dataframe: pd.DataFrame,
    column: str,
) -> Tuple[Optional[float], Optional[float]]:
    """
    Calcula el último valor y la variación porcentual de siete observaciones.

    Parameters
    ----------
    dataframe : pd.DataFrame
        DataFrame Maestro.
    column : str
        Columna a analizar.

    Returns
    -------
    Tuple[Optional[float], Optional[float]]
        Último valor y cambio porcentual de siete días.
    """
    try:
        if column not in dataframe.columns:
            return None, None

        series = pd.to_numeric(
            dataframe[column],
            errors="coerce",
        ).dropna()

        last_seven_values = series.tail(7)

        if len(last_seven_values) < 2:
            return None, None

        first_value = float(last_seven_values.iloc[0])
        last_value = float(last_seven_values.iloc[-1])

        if first_value == 0:
            return last_value, None

        percentage_change = (
            (last_value - first_value) / abs(first_value)
        ) * 100

        return last_value, percentage_change

    except Exception as error:
        LOGGER.exception(
            "Error al calcular tendencia de %s. Tipo: %s. Detalle: %s",
            column,
            type(error).__name__,
            error,
        )
        return None, None


def render_risk_panel(
    dataframe: pd.DataFrame,
    usdt_stablecoin_dominance_df: Optional[pd.DataFrame] = None,
) -> None:
    """
    Renderiza las tarjetas de semáforo para DXY y USDT.D.

    NUEVO: LIQUIDEZ AVANZADA - cuando no hay COINGECKO_API_KEY (dominancia
    clásica de USDT sobre TODO el mercado cripto no disponible), en vez de
    dejar "N/D" para siempre, se usa la dominancia de USDT sobre el total
    de stablecoins rastreadas (dato 100% gratuito de DefiLlama, ya
    descargado para la fórmula de Corto Plazo). Se etiqueta de forma
    explícita como una métrica DISTINTA a la clásica, para no confundir.

    Parameters
    ----------
    dataframe : pd.DataFrame
        DataFrame Maestro.
    usdt_stablecoin_dominance_df : Optional[pd.DataFrame]
        Resultado de data_ingestion.get_usdt_stablecoin_dominance_history().
    """
    try:
        st.markdown("---")
        st.subheader("Semáforo de Riesgo: Falsos Rallies")

        dxy_column, usdt_column = st.columns(2)

        with dxy_column:
            try:
                dxy_value, dxy_change = get_seven_day_trend(
                    dataframe=dataframe,
                    column="DXY",
                )

                if dxy_value is None or dxy_change is None:
                    st.metric(
                        label="DXY — Tendencia 7 días",
                        value="N/D",
                        delta="Datos insuficientes",
                    )
                    st.warning("No hay datos suficientes del DXY.")
                else:
                    st.metric(
                        label="DXY — Tendencia 7 días",
                        value=f"{dxy_value:,.2f}",
                        delta=f"{dxy_change:+.2f}%",
                        delta_color="inverse",
                    )

                    if dxy_change > 0:
                        st.error("ALERTA: DXY AL ALZA (PRESIÓN BAJISTA)")
                    elif dxy_change < 0:
                        st.success("DXY A LA BAJA (FAVORABLE)")
                    else:
                        st.info("DXY SIN VARIACIÓN RELEVANTE.")

            except Exception as error:
                LOGGER.exception(
                    "Error al renderizar tarjeta DXY. Tipo: %s. Detalle: %s",
                    type(error).__name__,
                    error,
                )
                st.error("No fue posible calcular la señal del DXY.")

        with usdt_column:
            try:
                has_classic_dominance = (
                    USDT_DOMINANCE_COLUMN in dataframe.columns
                    and pd.to_numeric(
                        dataframe[USDT_DOMINANCE_COLUMN], errors="coerce"
                    ).notna().any()
                )

                has_stablecoin_dominance = (
                    usdt_stablecoin_dominance_df is not None
                    and not usdt_stablecoin_dominance_df.empty
                    and "USDT_Stablecoin_Dominance" in usdt_stablecoin_dominance_df.columns
                )

                if has_classic_dominance:
                    usdt_value, usdt_change = get_seven_day_trend(
                        dataframe=dataframe,
                        column=USDT_DOMINANCE_COLUMN,
                    )

                    if usdt_value is None or usdt_change is None:
                        st.metric(
                            label="USDT.D — Tendencia 7 días",
                            value="N/D",
                            delta="Datos insuficientes",
                        )
                        st.warning("No hay datos suficientes de USDT.D.")
                    else:
                        st.metric(
                            label="USDT.D — Tendencia 7 días",
                            value=f"{usdt_value:,.2f}%",
                            delta=f"{usdt_change:+.2f}%",
                            delta_color="inverse",
                        )

                        if usdt_change > 0:
                            st.error("CAPITAL REFUGIÁNDOSE EN CASH")
                        elif usdt_change < 0:
                            st.success("CAPITAL ROTANDO A RIESGO")
                        else:
                            st.info("DOMINANCIA USDT SIN VARIACIÓN RELEVANTE.")

                elif has_stablecoin_dominance:
                    # NUEVO: LIQUIDEZ AVANZADA - fallback gratuito, honesto y
                    # explícitamente etiquetado como una métrica distinta.
                    usdt_value, usdt_change = get_seven_day_trend(
                        dataframe=usdt_stablecoin_dominance_df,
                        column="USDT_Stablecoin_Dominance",
                    )

                    if usdt_value is None or usdt_change is None:
                        st.metric(
                            label="USDT vs. Stablecoins — Tendencia 7 días",
                            value="N/D",
                            delta="Datos insuficientes",
                        )
                        st.warning("No hay datos suficientes todavía.")
                    else:
                        st.metric(
                            label="USDT vs. Stablecoins — Tendencia 7 días",
                            value=f"{usdt_value:,.2f}%",
                            delta=f"{usdt_change:+.2f}%",
                            delta_color="inverse",
                        )

                        if usdt_change > 0:
                            st.error("USDT GANANDO TERRENO FRENTE A OTRAS STABLECOINS")
                        elif usdt_change < 0:
                            st.success("USDT PERDIENDO TERRENO FRENTE A OTRAS STABLECOINS")
                        else:
                            st.info("SIN VARIACIÓN RELEVANTE.")

                    st.caption(
                        "ℹ️ Esta NO es la dominancia clásica de USDT sobre todo "
                        "el mercado cripto (esa requiere COINGECKO_API_KEY de "
                        "pago). Es la dominancia de USDT sobre el total de "
                        "stablecoins rastreadas (USDT+USDC+DAI+FDUSD, vía "
                        "DefiLlama, gratis) - una señal relacionada pero distinta."
                    )

                else:
                    st.metric(
                        label="USDT.D — Tendencia 7 días",
                        value="N/D",
                        delta="Sin fuente disponible",
                    )
                    st.info(
                        "ℹ️ USDT.D clásico requiere COINGECKO_API_KEY (de pago). "
                        "El precio USDT-USD nunca se usa como sustituto."
                    )

            except Exception as error:
                LOGGER.exception(
                    "Error al renderizar tarjeta USDT.D. Tipo: %s. Detalle: %s",
                    type(error).__name__,
                    error,
                )
                st.error("No fue posible calcular la señal de USDT.D.")

    except Exception as error:
        LOGGER.exception(
            "Error al renderizar panel de riesgo. Tipo: %s. Detalle: %s",
            type(error).__name__,
            error,
        )
        st.error("No fue posible renderizar el panel de riesgo.")


# ACTUALIZACIÓN PARCHE (Requerimiento 1): checkboxes del motor de liquidez.
def render_liquidity_engine_controls() -> Tuple[Dict[str, bool], Dict[str, bool]]:
    """
    Renderiza los checkboxes de la fórmula base y de las regiones, e
    inicializa sus valores por defecto en session_state la primera vez.

    Returns
    -------
    Tuple[Dict[str, bool], Dict[str, bool]]
        (base_toggles, region_toggles) con el estado actual de cada checkbox.
    """
    st.sidebar.markdown("### MOTOR DE LIQUIDEZ COMPUESTA")
    st.sidebar.caption(
        "Fórmula base: WALCL − (TGA + RRP). Actívalo o desactívalo por "
        "componente; el gráfico se recalcula al instante."
    )

    base_toggles: Dict[str, bool] = {}
    for component_key, component_config in LIQUIDITY_BASE_COMPONENTS.items():
        session_key = f"toggle_base_{component_key}"
        if session_key not in st.session_state:
            st.session_state[session_key] = component_config["default"]
        base_toggles[component_key] = st.sidebar.checkbox(
            component_config["label"],
            key=session_key,
        )

    st.sidebar.markdown("**Regiones adicionales:**")
    region_toggles: Dict[str, bool] = {}
    for component_key, component_config in LIQUIDITY_REGION_COMPONENTS.items():
        session_key = f"toggle_region_{component_key}"
        if session_key not in st.session_state:
            st.session_state[session_key] = component_config["default"]
        region_toggles[component_key] = st.sidebar.checkbox(
            component_config["label"],
            key=session_key,
        )

    return base_toggles, region_toggles


# ACTUALIZACIÓN PARCHE (Requerimiento 2): panel de catalizadores y retraso.
def render_catalyst_panel() -> None:
    """
    Renderiza el panel de Catalizadores Dinámicos y calcula el Retraso Neto
    Ajustado. Es puramente informativo: no modifica los datos del gráfico
    de liquidez.
    """
    st.markdown("---")
    st.subheader("⏱️ Catalizadores de Velocidad y Retraso (LAG)")
    st.caption(
        "Herramienta de apoyo visual. No modifica el gráfico de liquidez; "
        "solo estima cuánto podría tardar el efecto de la liquidez en "
        "sentirse en el mercado, según el contexto que selecciones."
    )

    date_column, accel_column, decel_column = st.columns([1, 1, 1])

    with date_column:
        selected_range = st.date_input(
            "Rango de fechas de análisis",
            value=(date.today() - timedelta(days=30), date.today()),
            key="catalyst_date_range",
        )

    with accel_column:
        st.markdown("**ACELERADORES**")
        active_accelerators = [
            name
            for name in LAG_ACCELERATORS
            if st.checkbox(name, key=f"accel_{name}")
        ]

    with decel_column:
        st.markdown("**DESACELERADORES**")
        active_decelerators = [
            name
            for name in LAG_DECELERATORS
            if st.checkbox(name, key=f"decel_{name}")
        ]

    net_lag_days = calculate_net_lag_days(
        active_accelerators=active_accelerators,
        active_decelerators=active_decelerators,
    )

    if isinstance(selected_range, tuple) and len(selected_range) == 2:
        range_label = f"{selected_range[0].strftime('%d-%m-%Y')} → {selected_range[1].strftime('%d-%m-%Y')}"
    else:
        range_label = "Rango incompleto"

    st.info(
        f"**Retraso Neto Ajustado: {net_lag_days} días** "
        f"(rango analizado: {range_label}). "
        f"Aceleradores activos: {', '.join(active_accelerators) or 'ninguno'}. "
        f"Desaceleradores activos: {', '.join(active_decelerators) or 'ninguno'}."
    )


# ACTUALIZACIÓN PARCHE (Requerimiento 5): panel de salud de datos.
def render_health_check_panel(health_report: Dict[str, str]) -> None:
    """
    Muestra el estatus (OK / ERROR) de cada fuente de datos recolectada.
    """
    with st.sidebar.expander("ESTADO DE LAS FUENTES (HEALTH CHECK)", expanded=False):
        if not health_report:
            st.write("Sin información de salud disponible todavía.")
            return

        for source_name, status in sorted(health_report.items()):
            if status == "OK":
                st.success(f"{source_name}: OK")
            else:
                st.error(f"{source_name}: {status}")


# ACTUALIZACIÓN PARCHE (Requerimiento 5): documentación del programa.
def render_documentation_panel() -> None:
    """
    Explica de forma clara qué hace el programa y para qué sirve cada
    control, en una sección plegable.
    """
    with st.expander("¿CÓMO FUNCIONA ESTE PROGRAMA?"):
        st.markdown(
            """
**¿Qué datos usa?**
- **FRED** (Reserva Federal de EE.UU.): balance de la Fed (WALCL), Cuenta
  General del Tesoro (TGA), Reverse Repo (RRP), balance del BCE
  (ECBASSETSW) y del Banco de Japón (JPNASSETS).
- **Yahoo Finance**: precios de BTC, SOL, USDT, el índice del dólar (DXY) y
  los tipos de cambio EUR/USD, CNY/USD, JPY/USD usados para convertir cada
  balance a dólares.
- **CoinGecko** (opcional, requiere key paga): dominancia histórica real de
  USDT en el mercado cripto (USDT.D).

**¿Qué hace con ellos?**
1. Descarga cada serie por separado y las alinea por fecha.
2. Convierte cada balance a billones de dólares usando el tipo de cambio
   correspondiente.
3. Calcula la Liquidez Global sumando y restando solo los componentes que
   tengas activados en los checkboxes de la izquierda.
4. Suaviza esa liquidez con una media móvil exponencial (EMA) de 14 días
   para quitarle ruido, y detecta "picos" cuando esa línea suavizada supera
   su propia media de 50 días.

**¿Para qué sirve cada control?**
- **Checkboxes de Motor de Liquidez**: incluyen o excluyen un componente de
  la fórmula al instante, sin volver a descargar nada.
- **Desfase de Liquidez**: adelanta la liquidez X días hacia el futuro para
  compararla visualmente con el precio (hipótesis de que la liquidez
  antecede al precio).
- **Catalizadores y Retraso (LAG)**: panel informativo aparte que estima
  cuántos días podría tardar ese efecto según el contexto de mercado que
  marques. No cambia el gráfico de liquidez.
- **Health Check**: te dice si cada fuente de datos respondió bien (OK) o
  falló (ERROR), para que sepas si lo que ves es un dato real o un hueco
  tapado con cero.
            """
        )


def render_main_dashboard() -> None:
    """
    Ejecuta la aplicación Streamlit.
    """
    try:
        render_terminal_section_header("MACRO LIQUIDITY TERMINAL", options_label="OPCIONES · PANEL PRINCIPAL")
        st.caption(
            "Monitor institucional de liquidez global, criptoactivos "
            "y señales de riesgo."
        )

        render_documentation_panel()  # ACTUALIZACIÓN PARCHE

        st.sidebar.header("Controles")

        selected_asset_label = st.sidebar.radio(
            label="Activo a comparar",
            options=list(ASSET_OPTIONS.keys()),
            index=0,
        )

        selected_asset_column = ASSET_OPTIONS[selected_asset_label]

        offset_days = st.sidebar.slider(
            label="Desfase de Liquidez (días)",
            min_value=0,
            max_value=90,
            value=0,
            step=1,
            help=(
                "Desplaza Liquidez_Suavizada hacia el futuro mediante "
                "Pandas .shift(periods=días)."
            ),
        )

        # ACTUALIZACIÓN PARCHE: checkboxes del motor de liquidez modular.
        base_toggles, region_toggles = render_liquidity_engine_controls()

        # ACTUALIZACIÓN PARCHE: modo de visualización (combinado vs paneles).
        # MEJORA TRADINGVIEW: el modo de paneles ahora es vertical (activo
        # arriba, liquidez abajo a todo el ancho), no lado a lado.
        st.sidebar.markdown("### VISUALIZACIÓN")
        display_mode = st.sidebar.radio(
            "Modo de visualización",
            options=["Combinado (recomendado)", "Estilo TradingView (Vertical)"],
            index=0,
            key="display_mode",
        )

        if st.sidebar.button("Actualizar datos"):
            try:
                load_master_dataframe.clear()
                st.session_state.pop("selected_chart_date", None)
                st.rerun()
            except Exception as error:
                LOGGER.exception(
                    "Error al actualizar datos. Tipo: %s. Detalle: %s",
                    type(error).__name__,
                    error,
                )
                st.sidebar.error("No fue posible actualizar los datos.")

        if st.sidebar.button("Limpiar proyección"):
            try:
                st.session_state.pop("selected_chart_date", None)
                st.rerun()
            except Exception as error:
                LOGGER.exception(
                    "Error al limpiar proyección. Tipo: %s. Detalle: %s",
                    type(error).__name__,
                    error,
                )
                st.sidebar.error("No fue posible limpiar la proyección.")

        with st.spinner("Descargando y procesando información macroeconómica..."):
            master_dataframe, health_report = load_master_dataframe()

        render_health_check_panel(health_report)  # ACTUALIZACIÓN PARCHE

        if master_dataframe.empty:
            st.error(
                "No fue posible construir el DataFrame Maestro. "
                "Verifica la API key de FRED, la conexión a internet y la consola."
            )
            st.stop()

        if selected_asset_column not in master_dataframe.columns:
            st.error(
                f"No existe la serie de precio requerida: {selected_asset_column}."
            )
            st.stop()

        valid_asset_data = pd.to_numeric(
            master_dataframe[selected_asset_column],
            errors="coerce",
        ).dropna()

        if valid_asset_data.empty:
            st.error(
                f"No existen precios válidos para {selected_asset_label}."
            )
            st.stop()

        # ACTUALIZACIÓN PARCHE: recálculo instantáneo de liquidez según los
        # checkboxes activos (Requerimiento 1). No vuelve a descargar nada.
        master_dataframe = recalculate_liquidity(
            master_dataframe=master_dataframe,
            base_toggles=base_toggles,
            region_toggles=region_toggles,
        )

        selected_chart_date = st.session_state.get("selected_chart_date")

        if selected_chart_date is not None:
            try:
                selected_chart_date = pd.Timestamp(selected_chart_date).normalize()
            except Exception as error:
                LOGGER.exception(
                    "Error al recuperar fecha seleccionada. "
                    "Tipo: %s. Detalle: %s",
                    type(error).__name__,
                    error,
                )
                selected_chart_date = None
                st.session_state.pop("selected_chart_date", None)

        # MEJORA TRADINGVIEW: el panel de líneas guía se renderiza antes de
        # construir las figuras, para que cualquier línea añadida aparezca
        # de inmediato en el mismo rerun.
        render_guide_lines_panel()

        if display_mode == "Combinado (recomendado)":
            main_figure = create_main_figure(
                dataframe=master_dataframe,
                asset_label=selected_asset_label,
                asset_column=selected_asset_column,
                offset_days=offset_days,
                selected_date=selected_chart_date,
            )

            try:
                selection_event = st.plotly_chart(
                    main_figure,
                    use_container_width=True,
                    on_select="rerun",
                    selection_mode="points",
                    key="macro_liquidity_chart",
                    config=TRADINGVIEW_PLOTLY_CONFIG,  # MEJORA TRADINGVIEW
                )

                new_selected_date = extract_selected_date(selection_event)

                if (
                    new_selected_date is not None
                    and new_selected_date != selected_chart_date
                ):
                    st.session_state["selected_chart_date"] = new_selected_date
                    st.rerun()

            except TypeError as error:
                LOGGER.exception(
                    "La versión instalada de Streamlit no admite on_select. "
                    "Tipo: %s. Detalle: %s",
                    type(error).__name__,
                    error,
                )
                st.plotly_chart(
                    main_figure,
                    use_container_width=True,
                    key="macro_liquidity_chart_fallback",
                    config=TRADINGVIEW_PLOTLY_CONFIG,  # MEJORA TRADINGVIEW
                )
                st.warning(
                    "Actualiza Streamlit para habilitar las proyecciones "
                    "al seleccionar puntos del gráfico."
                )

            except Exception as error:
                LOGGER.exception(
                    "Error al renderizar gráfico interactivo. "
                    "Tipo: %s. Detalle: %s",
                    type(error).__name__,
                    error,
                )
                st.error("No fue posible renderizar el gráfico interactivo.")

        else:
            # MEJORA TRADINGVIEW (Requerimientos 1 y 2 de esta ronda): ahora
            # es UN SOLO lienzo (un solo go.Figure, un solo componente en
            # pantalla) dividido en dos filas con eje X compartido: activo
            # arriba, Liquidez Compuesta abajo. El cursor sobre cualquiera
            # de los dos paneles dibuja una línea vertical sincronizada en
            # ambos (crosshair nativo de Plotly vía spikes + eje X
            # compartido). Cada fila tiene su propia escala Y, y esa escala
            # se recalcula automáticamente al hacer zoom/pan (ver
            # build_synced_dual_panel_figure / render_synced_dual_panel_chart
            # para el detalle técnico de por qué esto necesita un pequeño
            # bloque de JavaScript).
            if "asset_panel_height" not in st.session_state:
                st.session_state["asset_panel_height"] = DEFAULT_ASSET_PANEL_HEIGHT
            if "liquidity_panel_height" not in st.session_state:
                st.session_state["liquidity_panel_height"] = DEFAULT_LIQUIDITY_PANEL_HEIGHT
            if "asset_amplification" not in st.session_state:
                st.session_state["asset_amplification"] = DEFAULT_VERTICAL_AMPLIFICATION
            if "liquidity_amplification" not in st.session_state:
                st.session_state["liquidity_amplification"] = DEFAULT_VERTICAL_AMPLIFICATION

            control_column, restore_column = st.columns([4, 1])
            with control_column:
                height_col, amp_col = st.columns(2)
                with height_col:
                    st.session_state["asset_panel_height"] = st.slider(
                        f"Alto del panel de {selected_asset_label} (px)",
                        min_value=200,
                        max_value=700,
                        value=st.session_state["asset_panel_height"],
                        key="asset_height_slider",
                    )
                    st.session_state["liquidity_panel_height"] = st.slider(
                        "Alto del panel de Liquidez (px)",
                        min_value=200,
                        max_value=700,
                        value=st.session_state["liquidity_panel_height"],
                        key="liquidity_height_slider",
                    )
                with amp_col:
                    # MEJORA TRADINGVIEW (Requerimiento 1): estiramiento
                    # vertical manual, para cuando una serie es genuinamente
                    # plana y el auto-ajuste por sí solo no basta.
                    st.session_state["asset_amplification"] = st.slider(
                        f"Amplificación visual — {selected_asset_label}",
                        min_value=MIN_VERTICAL_AMPLIFICATION,
                        max_value=MAX_VERTICAL_AMPLIFICATION,
                        value=st.session_state["asset_amplification"],
                        step=0.25,
                        key="asset_amplification_slider",
                        help="Sube esto si la línea se ve demasiado plana incluso después de hacer zoom.",
                    )
                    st.session_state["liquidity_amplification"] = st.slider(
                        "Amplificación visual — Liquidez",
                        min_value=MIN_VERTICAL_AMPLIFICATION,
                        max_value=MAX_VERTICAL_AMPLIFICATION,
                        value=st.session_state["liquidity_amplification"],
                        step=0.25,
                        key="liquidity_amplification_slider",
                        help="Sube esto si la línea se ve demasiado plana incluso después de hacer zoom.",
                    )
            with restore_column:
                st.write("")
                st.write("")
                if st.button("RESTAURAR PROPORCIÓN ORIGINAL"):
                    st.session_state["asset_panel_height"] = DEFAULT_ASSET_PANEL_HEIGHT
                    st.session_state["liquidity_panel_height"] = DEFAULT_LIQUIDITY_PANEL_HEIGHT
                    st.session_state["asset_amplification"] = DEFAULT_VERTICAL_AMPLIFICATION
                    st.session_state["liquidity_amplification"] = DEFAULT_VERTICAL_AMPLIFICATION
                    st.rerun()

            st.caption(
                "Mueve el cursor sobre cualquiera de los dos paneles: la "
                "línea vertical se sincroniza en ambos. La rueda del mouse "
                "hace zoom horizontal, y cada panel reajusta su propia "
                "escala vertical automáticamente. Si el desfase está "
                "activo, la caja de información del panel de liquidez "
                "muestra la fecha real del dato además de la fecha en "
                "pantalla."
            )

            synced_figure, row1_indices, row2_indices = build_synced_dual_panel_figure(
                dataframe=master_dataframe,
                asset_label=selected_asset_label,
                asset_column=selected_asset_column,
                offset_days=offset_days,
                asset_panel_height=st.session_state["asset_panel_height"],
                liquidity_panel_height=st.session_state["liquidity_panel_height"],
            )

            render_synced_dual_panel_chart(
                figure=synced_figure,
                row1_trace_indices=row1_indices,
                row2_trace_indices=row2_indices,
                component_height=(
                    st.session_state["asset_panel_height"]
                    + st.session_state["liquidity_panel_height"]
                ),
                asset_amplification=st.session_state["asset_amplification"],
                liquidity_amplification=st.session_state["liquidity_amplification"],
            )

        if selected_chart_date is not None:
            st.caption(
                "Fecha seleccionada: "
                f"{selected_chart_date.strftime('%d-%m-%Y')} | "
                "Proyección BTC: +7 días | Proyección SOL: +40 días"
            )

        render_catalyst_panel()  # ACTUALIZACIÓN PARCHE

        # NUEVO: LIQUIDEZ AVANZADA - fallback gratuito para USDT.D.
        with st.spinner("Consultando stablecoins (DefiLlama)..."):
            stablecoin_dataframe_for_risk = load_stablecoin_history()
            usdt_stablecoin_dominance_df = get_usdt_stablecoin_dominance_history(
                stablecoin_dataframe_for_risk
            )

        render_risk_panel(master_dataframe, usdt_stablecoin_dominance_df)

    except Exception as error:
        LOGGER.exception(
            "Error crítico en app.py. Tipo: %s. Detalle: %s",
            type(error).__name__,
            error,
        )
        st.error(
            "Ocurrió un error crítico al ejecutar el tablero. "
            "Consulta la consola para ver el detalle técnico."
        )


# NUEVO: LIQUIDEZ AVANZADA - segunda pestaña del programa, con los índices
# de Largo y Corto Plazo, comparados contra BTC/SOL, con toda la
# interacción TradingView ya construida (crosshair, auto-ajuste de Y,
# desfase sin recorte, líneas guía).
def render_advanced_liquidity_tab() -> None:
    """
    Renderiza la pestaña de Liquidez Avanzada: selector de índice
    (Liquidez Global Combinada / Corto Plazo), selector de activo, desfase,
    y el panel único sincronizado con el mismo motor de interacción que el
    Panel Principal.

    NUEVO: Liquidez Global Combinada (reemplaza el enfoque anterior de
    Largo Plazo con Z-Score y Japón/China):
      - Solo Fed + BCE, exclusivamente vía FRED (WALCL, WDTGAL, RRPONTSYD,
        ECBASSETSW, DEXUSEU). Japón y China se quitaron por decisión
        explícita del usuario (daban señales incompatibles al mezclarlos).
      - Checkboxes por componente (WALCL, TGA, RRP, ECB).
      - Normalización en dos etapas: primero Rate of Change (RoC) de 90
        días (evita que el tamaño de la Fed eclipse al BCE y evita una
        tendencia alcista infinita), y luego Z-Score RODANTE de 52 semanas
        sobre ese RoC (evita lecturas absurdas cuando el RoC "explota" por
        pasar cerca de cero - corrección institucional post-entrega).
      - Siempre semanal (cierre viernes) - no hay selector de temporalidad
        porque ya no hace falta reconciliar con series mensuales.
      - SMA opcional de suavizado sobre el resultado final.
    El Índice de Corto Plazo NO cambió: sigue diario, sin checkboxes,
    exactamente como antes.
    """
    try:
        render_terminal_section_header("LIQUIDEZ AVANZADA: ÍNDICES NORMALIZADOS", options_label="OPCIONES · LIQUIDEZ AVANZADA")
        st.caption(
            "Dos canastas independientes, cada una con su propia "
            "normalización, para compararse con Bitcoin/Solana sin "
            "aplanarse ni exagerarse."
        )

        with st.expander("¿CÓMO SE CALCULAN ESTOS ÍNDICES?"):
            st.markdown(
                """
**Liquidez Global Combinada (Fed + BCE)**
- Canasta configurable con checkboxes: `WALCL - TGA (WDTGAL) - RRP`
  (Fed Neta) `+ BCE (ECBASSETSW convertido a USD con DEXUSEU, el tipo de
  cambio oficial de la propia FRED - no Yahoo)`.
- **Solo Fed + BCE.** Japón y China se sacaron de este índice porque
  mezclarlos con Fed/BCE daba señales incompatibles.
- **Alineación de calendarios:** todas las series se reindexan a
  calendario diario continuo y se propagan hacia adelante (forward-fill)
  antes de operar con ellas, porque la Fed cierra en miércoles y el BCE
  en viernes.
- **Normalización en dos etapas:**
  1. **Rate of Change (RoC) de 90 días** sobre la liquidez combinada
     nominal - evita que el tamaño nominal de la Fed eclipse al BCE, y
     evita una tendencia alcista infinita (una suma nominal directa
     siempre sube porque los balances de los bancos centrales crecen con
     el tiempo).
  2. **Z-Score rodante de 52 semanas** sobre ese RoC (media y desviación
     estándar MÓVILES, nunca histórico completo) - el RoC puede "explotar"
     a porcentajes absurdos cuando la liquidez neta pasa cerca de cero; el
     Z-Score lo re-expresa en desviaciones estándar recientes, mucho más
     interpretable y estable.
- **Re-agrupación semanal** (cierre viernes) con `.last()` - el valor real
  de cada semana, nunca un promedio inventado - aplicada ANTES del
  Z-Score (el orden exacto es: suma de componentes → RoC → Z-Score).
- **SMA opcional**: si la activas, suaviza el Z-Score final con una Media
  Móvil Simple - es una capa visual, no reemplaza el cálculo.

**Índice de Liquidez Inmediata de Mercado (Corto Plazo)**
- Canasta fija: `WALCL` (fijo al último miércoles - así es como FRED
  publica el dato, ya viene así) `- TGA diario - RRP diario +
  Capitalización de Stablecoins` (USDT+USDC+DAI+FDUSD, vía DefiLlama).
- Sigue siendo **diario**, con Z-Score de **30 días**. Sin checkboxes.

**Sobre la normalización:** no se recorta (clip) ningún valor en ninguno
de los dos índices. Si un movimiento es genuinamente extremo, se muestra
como tal.
                """
            )

        index_label = st.selectbox(
            "Índice a graficar",
            options=list(INDEX_CHOICES.keys()),
            key="advanced_index_choice",
        )
        index_column = INDEX_CHOICES[index_label]
        is_combined_global = index_label.startswith("Liquidez Global Combinada")

        # NUEVO: Liquidez Global Combinada - checkboxes (WALCL/TGA/RRP/ECB,
        # SIN Japón/China) y SMA opcional. Sin selector de temporalidad:
        # el resultado siempre es semanal (Paso 5, cierre viernes).
        combined_toggles: Dict[str, bool] = {}
        apply_sma = False
        sma_window_weeks = COMBINED_LIQUIDITY_DEFAULT_SMA_WEEKS

        if is_combined_global:
            st.markdown("### COMPONENTES DE LA LIQUIDEZ GLOBAL COMBINADA")
            st.caption(
                "Desmarca cualquier componente para excluirlo por completo "
                "de la canasta - el índice se recalcula al instante. "
                "Solo Fed + BCE (exclusivamente FRED)."
            )

            checkbox_columns = st.columns(len(COMBINED_LIQUIDITY_COMPONENTS))
            for checkbox_column, (component_key, component_config) in zip(
                checkbox_columns, COMBINED_LIQUIDITY_COMPONENTS.items()
            ):
                session_key = f"combined_toggle_{component_key}"
                if session_key not in st.session_state:
                    st.session_state[session_key] = component_config["default"]
                with checkbox_column:
                    combined_toggles[component_key] = st.checkbox(
                        component_config["label"],
                        key=session_key,
                    )

            sma_col1, sma_col2 = st.columns([1, 2])
            with sma_col1:
                apply_sma = st.checkbox(
                    "Aplicar SMA de suavizado",
                    value=False,
                    key="combined_apply_sma",
                    help="Elimina ruido residual de alta frecuencia sobre la curva semanal final.",
                )
            with sma_col2:
                if apply_sma:
                    sma_window_weeks = st.slider(
                        "Ventana de la SMA (semanas)",
                        min_value=COMBINED_LIQUIDITY_MIN_SMA_WEEKS,
                        max_value=COMBINED_LIQUIDITY_MAX_SMA_WEEKS,
                        value=COMBINED_LIQUIDITY_DEFAULT_SMA_WEEKS,
                        step=1,
                        key="combined_sma_window",
                    )

        control_column, restore_column = st.columns([4, 1])
        with control_column:
            asset_col, offset_col = st.columns(2)
            with asset_col:
                adv_asset_label = st.radio(
                    "Activo a comparar",
                    options=list(ASSET_OPTIONS.keys()),
                    key="advanced_asset_choice",
                    horizontal=True,
                )
                adv_asset_column = ASSET_OPTIONS[adv_asset_label]
            with offset_col:
                if is_combined_global:
                    adv_offset_periods = st.slider(
                        "Desfase (semanas)",
                        min_value=0,
                        max_value=26,
                        value=0,
                        step=1,
                        key="advanced_offset_slider_combined",
                        help="Mismo mecanismo anti-recorte que el Panel Principal, en semanas.",
                    )
                else:
                    adv_offset_periods = st.slider(
                        "Desfase (días)",
                        min_value=0,
                        max_value=90,
                        value=0,
                        step=1,
                        key="advanced_offset_slider_short_term",
                        help="Mismo mecanismo anti-recorte que el Panel Principal.",
                    )

            if "adv_asset_panel_height" not in st.session_state:
                st.session_state["adv_asset_panel_height"] = DEFAULT_ASSET_PANEL_HEIGHT
            if "adv_index_panel_height" not in st.session_state:
                st.session_state["adv_index_panel_height"] = DEFAULT_LIQUIDITY_PANEL_HEIGHT

            height_col1, height_col2 = st.columns(2)
            with height_col1:
                st.session_state["adv_asset_panel_height"] = st.slider(
                    f"Alto del panel de {adv_asset_label} (px)",
                    min_value=200,
                    max_value=700,
                    value=st.session_state["adv_asset_panel_height"],
                    key="adv_asset_height_slider",
                )
            with height_col2:
                st.session_state["adv_index_panel_height"] = st.slider(
                    "Alto del panel del índice (px)",
                    min_value=200,
                    max_value=700,
                    value=st.session_state["adv_index_panel_height"],
                    key="adv_index_height_slider",
                )
        with restore_column:
            st.write("")
            st.write("")
            if st.button("RESTAURAR PROPORCIÓN ORIGINAL", key="adv_restore_button"):
                st.session_state["adv_asset_panel_height"] = DEFAULT_ASSET_PANEL_HEIGHT
                st.session_state["adv_index_panel_height"] = DEFAULT_LIQUIDITY_PANEL_HEIGHT
                st.rerun()

        st.caption(
            "Igual que en el Panel Principal: rueda del mouse = zoom "
            "horizontal, arrastrar el eje Y = comprimir/estirar la escala, "
            "cursor sincronizado entre ambos paneles."
        )

        with st.spinner("Descargando y procesando datos de Liquidez Avanzada..."):
            master_dataframe, health_report = load_master_dataframe()
            stablecoin_dataframe = load_stablecoin_history()

        if master_dataframe.empty:
            st.error(
                "No fue posible construir el DataFrame Maestro. Revisa el "
                "Panel Principal para más detalle."
            )
            return

        # NUEVO: Liquidez Global Combinada arma su propia vista semanal
        # (Fed + BCE, RoC); Corto Plazo sigue diario, sin cambios.
        if is_combined_global:
            advanced_dataframe = build_combined_global_liquidity_index(
                master_dataframe,
                component_toggles=combined_toggles,
                apply_sma=apply_sma,
                sma_window_weeks=sma_window_weeks,
            )
            offset_freq = COMBINED_LIQUIDITY_RESAMPLE_RULE
        else:
            advanced_dataframe = build_short_term_liquidity_view(
                master_dataframe, stablecoin_dataframe
            )
            offset_freq = "D"

        if (
            advanced_dataframe.empty
            or index_column not in advanced_dataframe.columns
            or advanced_dataframe[index_column].dropna().empty
        ):
            st.warning(
                "Todavía no hay suficiente historial para calcular "
                f"'{index_label}' con la configuración actual. Prueba "
                "activando más componentes, o espera a que se acumule "
                "más historia (el RoC de 90 días necesita al menos 90 "
                "días de datos previos)."
            )
            return

        synced_figure, row1_indices, row2_indices = build_advanced_index_synced_figure(
            advanced_dataframe=advanced_dataframe,
            asset_label=adv_asset_label,
            asset_column=adv_asset_column,
            index_label=index_label,
            index_column=index_column,
            offset_periods=adv_offset_periods,
            asset_panel_height=st.session_state["adv_asset_panel_height"],
            index_panel_height=st.session_state["adv_index_panel_height"],
            offset_freq=offset_freq,
        )

        render_synced_dual_panel_chart(
            figure=synced_figure,
            row1_trace_indices=row1_indices,
            row2_trace_indices=row2_indices,
            component_height=(
                st.session_state["adv_asset_panel_height"]
                + st.session_state["adv_index_panel_height"]
            ),
            asset_amplification=1.0,
            liquidity_amplification=1.0,
        )

        with st.expander("ESTADO DE LAS FUENTES DE ESTA PESTAÑA (HEALTH CHECK)"):
            # NUEVO: Liquidez Global Combinada - el health check se indexa
            # por ID de serie de FRED (no por nombre interno de columna),
            # así que se filtra por los IDs reales: WALCL, WDTGAL,
            # RRPONTSYD, ECBASSETSW, DEXUSEU (+ DefiLlama para Corto Plazo).
            relevant_sources = {
                key: value
                for key, value in health_report.items()
                if key in {"WALCL", "WDTGAL", "RRPONTSYD", "ECBASSETSW", "DEXUSEU"}
                or "DefiLlama" in key
            }
            if not relevant_sources:
                st.write("Sin información de salud disponible todavía.")
            for source_name, status in sorted(relevant_sources.items()):
                if status == "OK":
                    st.success(f"{source_name}: OK")
                elif status.startswith("OK"):
                    st.warning(f"{source_name}: {status}")
                else:
                    st.error(f"{source_name}: {status}")

    except Exception as error:
        LOGGER.exception(
            "Error crítico en la pestaña de Liquidez Avanzada. Tipo: %s. Detalle: %s",
            type(error).__name__,
            error,
        )
        st.error(
            "Ocurrió un error crítico al ejecutar la pestaña de Liquidez "
            "Avanzada. Consulta la consola para ver el detalle técnico."
        )


# =====================================================================
# NUEVO: PANEL MACRO-BITCOIN AVANZADO (US10Y, STLFSI4, DXY, MVRV Z-Score)
# =====================================================================
# CANDADO: esta sección completa es aditiva y vive en su propia pestaña.
# No modifica create_main_figure, create_liquidity_only_figure,
# create_asset_only_figure, build_synced_dual_panel_figure,
# render_synced_dual_panel_chart, build_advanced_index_synced_figure, ni
# el bloque "Componentes de la Liquidez Global Combinada" dentro de
# render_advanced_liquidity_tab(), que permanecen intactos.

MACRO_PANEL_ROW_HEIGHT = 230  # alto por fila (px), 4 filas sincronizadas
DATA_HEALTH_KEY_MISSING_LABEL = "ERROR - sin datos todavía"


def _add_stlfsi_background_shading(
    figure: go.Figure,
    panel_dataframe: pd.DataFrame,
    row: int,
) -> go.Figure:
    """
    Requerimiento 3: sombreado de fondo (no una línea) del STLFSI4 sobre
    el panel de Liquidez (fila `row`). Por cada semana con STLFSI4 > 0 se
    dibuja una franja roja sutil; si además STLFSI4 > STLFSI_PANIC_THRESHOLD
    (pánico/crisis bancaria genuina), la opacidad aumenta para destacarla.
    Semanas con STLFSI4 <= 0 (condiciones financieras normales o laxas) no
    se sombrean.
    """
    try:
        shading_dataframe = panel_dataframe.loc[:, ["Date", "STLFSI4"]].dropna()
        if shading_dataframe.empty:
            return figure

        shading_dataframe = shading_dataframe.sort_values(by="Date").reset_index(drop=True)
        half_week = timedelta(days=3.5)

        for _, week_row in shading_dataframe.iterrows():
            stress_value = week_row["STLFSI4"]
            if stress_value <= STLFSI_STRESS_THRESHOLD:
                continue

            opacity = (
                STLFSI_SHADE_OPACITY_HIGH
                if stress_value > STLFSI_PANIC_THRESHOLD
                else STLFSI_SHADE_OPACITY_LOW
            )

            figure.add_vrect(
                x0=week_row["Date"] - half_week,
                x1=week_row["Date"] + half_week,
                fillcolor=f"rgba({STLFSI_SHADE_COLOR_RGB}, {opacity})",
                line_width=0,
                layer="below",
                row=row,
                col=1,
            )

        return figure

    except Exception as error:
        LOGGER.exception(
            "Error al aplicar sombreado de STLFSI4. Tipo: %s. Detalle: %s",
            type(error).__name__,
            error,
        )
        return figure


def build_macro_signals_synced_figure(
    panel_dataframe: pd.DataFrame,
    asset_label: str,
    us10y_sma_weeks: int,
) -> go.Figure:
    """
    Requerimiento 1: gráfico principal del Panel Macro-Bitcoin Avanzado,
    dividido en 4 sub-paneles verticales que comparten el mismo eje X
    (Date), con zoom/pan perfectamente sincronizado entre filas gracias a
    `shared_xaxes=True` de Plotly (las filas quedan enlazadas mediante
    ejes "matches", comportamiento nativo - no requiere JavaScript
    adicional).

    Fila 1: Liquidez Global (Z-Score) vs. Precio del activo, con el
            sombreado de fondo del STLFSI4 (Requerimiento 3) y los
            marcadores de la Señal de Compra Macro (Requerimiento 6).
    Fila 2: US10Y + SMA (Requerimiento 2).
    Fila 3: DXY - RoC 90 días invertido (Requerimiento 4).
    Fila 4: MVRV Z-Score de Bitcoin (Requerimiento 5).
    """
    try:
        if panel_dataframe.empty:
            raise ValueError(
                "No hay datos suficientes para construir el Panel "
                "Macro-Bitcoin Avanzado."
            )

        figure = make_subplots(
            rows=4,
            cols=1,
            shared_xaxes=True,
            vertical_spacing=0.035,
            row_heights=[0.32, 0.22, 0.22, 0.24],
            specs=[
                [{"secondary_y": True}],
                [{"secondary_y": False}],
                [{"secondary_y": False}],
                [{"secondary_y": False}],
            ],
            subplot_titles=(
                "Liquidez Global (Z-Score) vs. Precio  |  fondo rojo = estrés financiero (STLFSI4)",
                "US10Y — Rendimiento del Tesoro a 10 años (%)",
                "DXY — Fortaleza del Dólar (RoC 90d invertido)",
                "MVRV Z-Score de Bitcoin (on-chain)",
            ),
        )

        # --- Fila 1: Liquidez Global (Z-Score) + Precio del activo ---
        figure.add_trace(
            go.Scatter(
                x=panel_dataframe["Date"],
                y=panel_dataframe["Liquidez_Global_Zscore"],
                mode="lines",
                name="Liquidez Global (Z-Score)",
                line={"color": "#00CC96", "width": 2.5},
                hovertemplate=(
                    "<b>Liquidez Global (Z-Score)</b><br>"
                    "Semana: %{x|%d-%m-%Y}<br>Z-Score: %{y:.2f}<extra></extra>"
                ),
            ),
            row=1, col=1, secondary_y=False,
        )
        figure.add_trace(
            go.Scatter(
                x=panel_dataframe["Date"],
                y=panel_dataframe["BTC_Close"],
                mode="lines",
                name=asset_label,
                line={"color": "#F59E0B", "width": 1.8},
                opacity=0.85,
                hovertemplate=(
                    f"<b>{asset_label}</b><br>"
                    "Semana: %{x|%d-%m-%Y}<br>Precio: $%{y:,.0f}<extra></extra>"
                ),
            ),
            row=1, col=1, secondary_y=True,
        )

        figure = _add_stlfsi_background_shading(figure, panel_dataframe, row=1)

        # Requerimiento 6: marcador verde en la base del gráfico cuando la
        # Señal de Compra Macro está activa esa semana.
        signal_dataframe = panel_dataframe.loc[panel_dataframe["Senal_Compra_Macro"] == True]  # noqa: E712
        if not signal_dataframe.empty:
            liquidity_min = pd.to_numeric(
                panel_dataframe["Liquidez_Global_Zscore"], errors="coerce"
            ).min()
            marker_y_base = (liquidity_min if pd.notna(liquidity_min) else 0.0) - 0.3
            figure.add_trace(
                go.Scatter(
                    x=signal_dataframe["Date"],
                    y=[marker_y_base] * len(signal_dataframe),
                    mode="markers",
                    name="Señal de Compra Macro",
                    marker={
                        "symbol": "triangle-up",
                        "size": 14,
                        "color": "#39FF14",
                        "line": {"color": "#0E1117", "width": 1},
                    },
                    hovertemplate=(
                        "<b>SEÑAL DE COMPRA MACRO</b><br>"
                        "Semana: %{x|%d-%m-%Y}<br>"
                        "Liquidez en cuartil inferior + MVRV en capitulación"
                        "<extra></extra>"
                    ),
                ),
                row=1, col=1, secondary_y=False,
            )

        # --- Fila 2: US10Y + SMA ---
        figure.add_trace(
            go.Scatter(
                x=panel_dataframe["Date"],
                y=panel_dataframe["US10Y"],
                mode="lines",
                name="US10Y (10Y Treasury)",
                line={"color": "#38BDF8", "width": 1.5},
                opacity=0.6,
                hovertemplate="US10Y: %{y:.2f}%<extra></extra>",
            ),
            row=2, col=1,
        )
        figure.add_trace(
            go.Scatter(
                x=panel_dataframe["Date"],
                y=panel_dataframe["US10Y_SMA"],
                mode="lines",
                name=f"US10Y SMA ({us10y_sma_weeks}sem)",
                line={"color": "#0EA5E9", "width": 2.5},
                hovertemplate="US10Y SMA: %{y:.2f}%<extra></extra>",
            ),
            row=2, col=1,
        )

        # --- Fila 3: DXY RoC 90d invertido ---
        figure.add_trace(
            go.Scatter(
                x=panel_dataframe["Date"],
                y=panel_dataframe["DXY_RoC90_Inv"],
                mode="lines",
                name="DXY RoC 90d (invertido)",
                line={"color": "#A855F7", "width": 2},
                fill="tozeroy",
                fillcolor="rgba(168, 85, 247, 0.12)",
                hovertemplate="DXY RoC 90d Inv: %{y:.2f}%<extra></extra>",
            ),
            row=3, col=1,
        )
        figure.add_hline(y=0, line_color="rgba(255,255,255,0.25)", line_width=1, row=3, col=1)

        # --- Fila 4: MVRV Z-Score ---
        figure.add_trace(
            go.Scatter(
                x=panel_dataframe["Date"],
                y=panel_dataframe["MVRV_Zscore"],
                mode="lines",
                name="MVRV Z-Score (BTC)",
                line={"color": "#FB7185", "width": 2.2},
                hovertemplate="MVRV Z-Score: %{y:.2f}<extra></extra>",
            ),
            row=4, col=1,
        )
        figure.add_hline(
            y=MVRV_CAPITULATION_THRESHOLD,
            line_color="#39FF14",
            line_dash="dot",
            line_width=1.5,
            annotation_text="Capitulación (<0.1)",
            annotation_position="bottom right",
            row=4, col=1,
        )

        figure.update_layout(
            template="plotly_dark",
            paper_bgcolor="#0E1117",
            plot_bgcolor="#0E1117",
            height=MACRO_PANEL_ROW_HEIGHT * 4,
            hovermode="x unified",
            dragmode="pan",
            showlegend=True,
            legend={
                "orientation": "h",
                "yanchor": "bottom",
                "y": 1.03,
                "xanchor": "right",
                "x": 1,
                "font": {"size": 10},
            },
            margin={"l": 10, "r": 10, "t": 90, "b": 10},
        )

        figure.update_xaxes(showgrid=False, fixedrange=False)
        figure.update_xaxes(title_text="Fecha (semanal, cierre viernes)", row=4, col=1)

        figure.update_yaxes(
            title_text="Liquidez (Z-Score)", row=1, col=1, secondary_y=False,
            gridcolor="rgba(255, 255, 255, 0.08)", fixedrange=False,
        )
        figure.update_yaxes(
            title_text=f"Precio {asset_label} (USD)", row=1, col=1, secondary_y=True,
            showgrid=False, tickprefix="$", fixedrange=False,
        )
        figure.update_yaxes(title_text="%", row=2, col=1, fixedrange=False,
                             gridcolor="rgba(255, 255, 255, 0.08)")
        figure.update_yaxes(title_text="% (invertido)", row=3, col=1, fixedrange=False,
                             gridcolor="rgba(255, 255, 255, 0.08)")
        figure.update_yaxes(title_text="Z-Score", row=4, col=1, fixedrange=False,
                             gridcolor="rgba(255, 255, 255, 0.08)")

        return figure

    except Exception as error:
        LOGGER.exception(
            "Error al construir el Panel Macro-Bitcoin Avanzado. "
            "Tipo: %s. Detalle: %s",
            type(error).__name__,
            error,
        )
        fallback_figure = go.Figure()
        fallback_figure.update_layout(
            template="plotly_dark",
            title="No fue posible construir el Panel Macro-Bitcoin Avanzado",
            height=500,
        )
        return fallback_figure


def render_macro_signals_tab() -> None:
    """
    Renderiza la nueva pestaña "Señales Macro Avanzadas": US10Y, STLFSI4,
    DXY (RoC 90d invertido) y MVRV Z-Score de Bitcoin, en 4 sub-paneles
    verticales sincronizados en el eje X (Requerimiento 1), más la Señal
    de Compra Macro (Requerimiento 6).
    """
    try:
        render_terminal_section_header(
            "SEÑALES MACRO AVANZADAS (US10Y · STLFSI4 · DXY · MVRV)",
            options_label="OPCIONES · SEÑALES MACRO",
        )
        st.caption(
            "Panel independiente y sincronizado: arrastra o haz zoom en "
            "cualquiera de las 4 filas y las demás se mueven exactamente "
            "igual (mismo eje de tiempo). No reemplaza ni modifica los "
            "gráficos del Panel Principal ni de Liquidez Avanzada."
        )

        asset_label = "Bitcoin (BTC-USD)"

        sma_col, _ = st.columns([1, 3])
        with sma_col:
            us10y_sma_weeks = st.slider(
                "SMA de US10Y (semanas)",
                min_value=US10Y_SMA_MIN_WEEKS,
                max_value=US10Y_SMA_MAX_WEEKS,
                value=US10Y_SMA_DEFAULT_WEEKS,
                step=1,
                key="macro_us10y_sma_weeks",
                help="Media móvil de mediano/largo plazo para suavizar el ruido diario del US10Y.",
            )

        with st.spinner("Descargando y alineando datos macro (FRED) y on-chain (MVRV)..."):
            master_dataframe, health_report = load_master_dataframe()
            mvrv_dataframe, mvrv_metadata = load_mvrv_zscore_history()

        if master_dataframe.empty:
            st.error(
                "No fue posible construir el DataFrame Maestro. Revisa el "
                "Panel Principal para más detalle."
            )
            return

        panel_dataframe = build_macro_bitcoin_signals_view(
            master_dataframe=master_dataframe,
            mvrv_dataframe=mvrv_dataframe,
            us10y_sma_weeks=us10y_sma_weeks,
        )

        if panel_dataframe.empty:
            st.warning(
                "Todavía no hay suficiente historial para calcular el "
                "Panel Macro-Bitcoin Avanzado (US10Y, STLFSI4 y DXY "
                "necesitan al menos 90 días de datos previos)."
            )
            return

        signals_count = int(panel_dataframe["Senal_Compra_Macro"].sum())
        if signals_count > 0:
            last_signal_date = panel_dataframe.loc[
                panel_dataframe["Senal_Compra_Macro"] == True, "Date"  # noqa: E712
            ].max()
            st.success(
                f"{signals_count} SEÑAL(ES) DE COMPRA MACRO DETECTADAS EN "
                f"el historial. Última: {last_signal_date.strftime('%d-%m-%Y')}."
            )
        else:
            st.info(
                "Sin señales de Compra Macro activas en el historial "
                "disponible con los umbrales actuales."
            )

        synced_figure = build_macro_signals_synced_figure(
            panel_dataframe=panel_dataframe,
            asset_label=asset_label,
            us10y_sma_weeks=us10y_sma_weeks,
        )

        st.plotly_chart(
            synced_figure,
            use_container_width=True,
            config=TRADINGVIEW_PLOTLY_CONFIG,
        )

        with st.expander("ESTADO DE LAS FUENTES DE ESTA PESTAÑA (HEALTH CHECK)"):
            relevant_sources = {
                key: value
                for key, value in health_report.items()
                if key in {"DGS10", "STLFSI4", "DX-Y.NYB"}
            }

            if not relevant_sources:
                st.write("Sin información de salud disponible todavía.")
            for source_name, status in sorted(relevant_sources.items()):
                if status == "OK":
                    st.success(f"{source_name}: OK")
                elif isinstance(status, str) and status.startswith("OK"):
                    st.warning(f"{source_name}: {status}")
                else:
                    st.error(f"{source_name}: {status}")

            # ACTUALIZACIÓN (Trazabilidad de Datos Total): el estado del
            # MVRV Z-Score YA NO se lee del diccionario global
            # health_report/DATA_HEALTH - ese diccionario podía quedar
            # desactualizado según el orden de llamadas entre
            # load_master_dataframe() (que limpia DATA_HEALTH al iniciar)
            # y load_mvrv_zscore_history() (que se llama después), lo cual
            # producía el falso negativo "ERROR" reportado aunque el dato
            # sí se hubiera cargado bien vía caché. Ahora se lee siempre
            # de los metadatos reales que devuelve get_mvrv_zscore_history:
            # fuente_datos + fecha_actualizacion. Nunca se fuerza "OK" si
            # no hay datos.
            mvrv_source = mvrv_metadata.get("fuente_datos", "Sin Datos")
            mvrv_updated_at = mvrv_metadata.get("fecha_actualizacion")
            mvrv_has_data = mvrv_dataframe is not None and not mvrv_dataframe.empty
            timestamp_label = (
                mvrv_updated_at.strftime("%d-%m-%Y %H:%M:%S")
                if mvrv_updated_at is not None
                else "desconocida"
            )

            if mvrv_has_data and mvrv_source == "API Directa":
                st.success(
                    "MVRV_Zscore (BGeometrics): OK - Datos extraídos de la "
                    f"API (Última actualización: {timestamp_label})"
                )
            elif mvrv_has_data and mvrv_source == "Caché Local":
                st.warning(
                    "MVRV_Zscore (BGeometrics): OK - Usando Caché Local "
                    f"(Última actualización: {timestamp_label})"
                )
            else:
                st.error(
                    "MVRV_Zscore (BGeometrics): ERROR - Sin datos (Fallo "
                    "en API y Caché)"
                )

    except Exception as error:
        LOGGER.exception(
            "Error crítico en la pestaña de Señales Macro Avanzadas. "
            "Tipo: %s. Detalle: %s",
            type(error).__name__,
            error,
        )
        st.error(
            "Ocurrió un error crítico al ejecutar la pestaña de Señales "
            "Macro Avanzadas. Consulta la consola para ver el detalle técnico."
        )


def main() -> None:
    """
    Punto de entrada de la aplicación: organiza el Panel Principal, la
    pestaña de Liquidez Avanzada y la nueva pestaña de Señales Macro
    Avanzadas como pestañas independientes del mismo programa (NUEVO:
    LIQUIDEZ AVANZADA / NUEVO: PANEL MACRO-BITCOIN AVANZADO).
    """
    tab_main, tab_advanced, tab_macro_signals = st.tabs(
        ["PANEL PRINCIPAL", "LIQUIDEZ AVANZADA", "SEÑALES MACRO AVANZADAS"]
    )

    with tab_main:
        render_main_dashboard()

    with tab_advanced:
        render_advanced_liquidity_tab()

    with tab_macro_signals:
        render_macro_signals_tab()


if __name__ == "__main__":
    main()