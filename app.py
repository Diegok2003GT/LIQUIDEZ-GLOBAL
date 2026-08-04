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
    CHINA_DATA_DEPRECATED_WARNING,  # AUDITORÍA: Directriz 4 - Datos Obsoletos
    COMBINED_LIQUIDITY_COMPONENTS,  # NUEVO: LIQUIDEZ GLOBAL COMBINADA
    COMBINED_LIQUIDITY_DEFAULT_SMA_WEEKS,  # NUEVO: LIQUIDEZ GLOBAL COMBINADA
    COMBINED_LIQUIDITY_MAX_SMA_WEEKS,  # NUEVO: LIQUIDEZ GLOBAL COMBINADA
    COMBINED_LIQUIDITY_MIN_SMA_WEEKS,  # NUEVO: LIQUIDEZ GLOBAL COMBINADA
    COMBINED_LIQUIDITY_RESAMPLE_RULE,  # NUEVO: LIQUIDEZ GLOBAL COMBINADA
    ECB_BSI_FLOW_REF,  # RECONSTRUCCIÓN HISTÓRICA MRR
    ECB_BSI_MRR_SERIES_KEY,  # RECONSTRUCCIÓN HISTÓRICA MRR
    ECB_CURRENT_ACCOUNTS_SERIES_KEY,  # NUEVO: VALIDACIÓN LIQEUR
    ECB_DEPOSIT_FACILITY_SERIES_KEY,  # NUEVO: VALIDACIÓN LIQEUR
    ECB_MARGINAL_LENDING_FACILITY_SERIES_KEY,  # NUEVO: VALIDACIÓN LIQEUR
    ECB_MIN_RESERVE_REQUIREMENTS_SERIES_KEY,  # NUEVO: VALIDACIÓN LIQEUR
    FRED_API_KEY,  # NUEVO: INDICADOR LIQGLOB
    FRED_SERIES,  # NUEVO: INDICADOR LIQGLOB
    LAG_ACCELERATORS,
    LAG_DECELERATORS,
    LIQEUR_METHODOLOGY,  # MIGRACIÓN LIQEUR: COMPONENTS (activa) | EXLIQ (legado)
    LIQGLOB_REGIONS,  # NUEVO: INDICADOR LIQGLOB
    LIQGLOB_RESAMPLE_RULE,  # NUEVO: INDICADOR LIQGLOB
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
from liqglob import build_liqglob_index, get_liqglob_source_coverage_report  # NUEVO: INDICADOR LIQGLOB
from liqeur_validation import (  # VALIDACIÓN METODOLÓGICA DE LIQEUR (permanente)
    build_liqeur_reconstruction,
    compare_liqeur_reconstruction_vs_official,
    compute_validation_status,
)
from mp_calendar import update_maintenance_period_calendar  # RECONSTRUCCIÓN HISTÓRICA MRR
from mrr_historical_reconstruction import (  # RECONSTRUCCIÓN HISTÓRICA MRR
    build_mrr_historical_daily_series,
    combine_mrr_sources_with_priority,
    get_mrr_reconstruction_coverage_report,
)
from data_ingestion import (  # NUEVO: LIQUIDEZ AVANZADA
    get_ecb_liquidity_data,  # NUEVO: INDICADOR LIQGLOB
    get_fred_data,  # NUEVO: INDICADOR LIQGLOB
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

/* =====================================================================
   ADAPTABILIDAD MÓVIL (aislada por Media Queries)
   =====================================================================
   REGLA DE BLINDAJE: todo lo que sigue vive exclusivamente dentro de
   bloques @media (max-width: ...). Una media query, por definición, solo
   aplica cuando el ancho del viewport cumple la condición - fuera de ese
   rango (escritorio, >1024px) el navegador simplemente ignora estas
   reglas y el diseño institucional de arriba queda 100% intacto: mismas
   dimensiones, mismos anchos de contenedor, misma disposición de rejilla.
   No se sobreescribe ni se duplica ninguna regla de escritorio; esto es
   puramente aditivo y solo para pantallas angostas (tablets pequeñas y
   móviles). No toca lógica de datos, cálculos, caché ni colores de
   alerta del Health Check - solo tamaños, espaciados y apilamiento.
*/

/* Tablets pequeñas / móviles en horizontal */
@media (max-width: 1024px) {
    .ilt-section-header {
        flex-wrap: wrap;
        row-gap: 6px;
    }
}

/* Móviles y tablets pequeñas */
@media (max-width: 768px) {
    /* Menos aire lateral para aprovechar el ancho angosto de un teléfono */
    [data-testid="stAppViewContainer"] .block-container {
        padding-left: 0.8rem !important;
        padding-right: 0.8rem !important;
        padding-top: 1rem !important;
        max-width: 100% !important;
    }

    /* Tipografía técnica un poco más compacta, sin perder legibilidad */
    h1, h2, h3, h4,
    [data-testid="stMarkdownContainer"] h1,
    [data-testid="stMarkdownContainer"] h2,
    [data-testid="stMarkdownContainer"] h3 {
        letter-spacing: 0.05em !important;
        font-size: 1rem !important;
        white-space: normal;
    }

    /* Encabezado de sección: título arriba, rótulo de opciones debajo,
       en vez de forzados en una sola fila que se corta */
    .ilt-section-header {
        flex-direction: column;
        align-items: flex-start;
        gap: 8px;
    }
    .ilt-section-title {
        font-size: 0.85rem;
        letter-spacing: 0.07em;
        white-space: normal;
    }
    .ilt-section-options {
        font-size: 0.62rem;
        align-self: flex-start;
    }

    /* Streamlit ya apila columnas en pantallas angostas por defecto;
       esto solo refuerza el apilamiento vertical y quita márgenes
       laterales redundantes entre columnas apiladas en móvil. */
    [data-testid="stHorizontalBlock"] {
        flex-direction: column !important;
    }
    [data-testid="column"] {
        width: 100% !important;
        flex: 1 1 100% !important;
        min-width: 100% !important;
    }

    /* Botones a ancho completo: objetivo de toque más grande en móvil */
    .stButton > button, .stDownloadButton > button {
        width: 100%;
        font-size: 0.72rem;
        padding: 0.55rem 0.6rem;
    }

    /* Tabs: permiten scroll horizontal en vez de aplastarse ilegibles */
    .stTabs [data-baseweb="tab-list"] {
        overflow-x: auto;
        -webkit-overflow-scrolling: touch;
        flex-wrap: nowrap;
    }
    .stTabs [data-baseweb="tab"] {
        font-size: 0.68rem;
        padding: 8px 10px;
        white-space: nowrap;
    }

    /* Expanders: encabezado más compacto y con salto de línea permitido */
    [data-testid="stExpander"] summary {
        font-size: 0.72rem;
        white-space: normal;
    }

    /* Health Check y demás alertas: texto más chico, sin desbordar el
       contenedor angosto - los colores semánticos NO se tocan aquí. */
    [data-testid="stAlert"] {
        font-size: 0.72rem;
        padding: 0.6rem 0.7rem;
    }
    [data-testid="stAlert"] p {
        word-break: break-word;
    }

    /* Sliders y selects: ligera reducción de tamaño de texto */
    [data-testid="stSlider"], [data-testid="stSelectbox"] {
        font-size: 0.82rem;
    }

    /* Gráficos Plotly: si el ancho intrínseco excede la pantalla, se
       habilita scroll horizontal contenido en vez de recortar o
       deformar el gráfico (la altura configurada en Python no se toca,
       solo se asegura que no rompa el layout de la página). */
    [data-testid="stPlotlyChart"] {
        overflow-x: auto;
        -webkit-overflow-scrolling: touch;
    }

    /* ACTUALIZACIÓN PARCHE (UI/UX MÓVIL - Directriz 1): la modebar de
       Plotly (zoom, pan, cámara, herramientas de dibujo) se vuelve
       flotante y mínima en pantallas angostas, en vez de ocupar una
       franja fija sobre el gráfico. displayModeBar="hover" (config de
       Python) ya la mantiene oculta hasta que el usuario toca el
       gráfico; este CSS solo la encoge y la superpone con fondo
       semitransparente cuando sí aparece, para que nunca empuje ni tape
       contenido del gráfico. */
    .js-plotly-plot .plotly .modebar {
        position: absolute !important;
        top: 2px !important;
        right: 2px !important;
        background: rgba(13, 15, 18, 0.85) !important;
        border-radius: 4px !important;
        padding: 1px 2px !important;
        transform: scale(0.78);
        transform-origin: top right;
    }
    .js-plotly-plot .plotly .modebar-btn {
        padding: 2px !important;
    }

    /* Sidebar más angosta y con menos padding en móvil */
    [data-testid="stSidebar"] {
        min-width: 82vw !important;
        padding-right: 0.5rem;
    }
}

/* Teléfonos pequeños */
@media (max-width: 480px) {
    [data-testid="stAppViewContainer"] .block-container {
        padding-left: 0.5rem !important;
        padding-right: 0.5rem !important;
    }
    .ilt-section-title {
        font-size: 0.75rem;
    }
    .ilt-section-options {
        font-size: 0.58rem;
        padding: 2px 7px;
    }
    .stButton > button, .stDownloadButton > button {
        font-size: 0.68rem;
    }
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

# ACTUALIZACIÓN PARCHE (UI/UX MÓVIL - Directriz 1): configuración global de
# Plotly, compartida por TODAS las figuras (st.plotly_chart y el embed
# crudo de render_synced_dual_panel_chart).
#   - "scrollZoom": True ya cubre AMBOS mundos de forma nativa en
#     Plotly.js: rueda del ratón en escritorio Y pinch-to-zoom con dos
#     dedos en pantallas táctiles - no hace falta ninguna bandera aparte
#     para gestos táctiles.
#   - "responsive": True hace que Plotly reaccione a cambios de tamaño
#     del contenedor (rotar el teléfono, colapsar el sidebar, etc.), no
#     solo al evento resize de la ventana completa.
#   - "displayModeBar": "hover" hace que la barra de herramientas
#     (modebar) permanezca oculta hasta que el usuario interactúa con el
#     gráfico, en vez de ocupar espacio fijo todo el tiempo - en móvil,
#     donde el ancho es escaso, esto evita que estorbe sobre la esquina
#     superior del gráfico. El CSS de abajo (INSTITUTIONAL_TERMINAL_CSS,
#     bloque @media max-width:768px) además la encoge y la vuelve
#     flotante/semitransparente cuando sí aparece.
TRADINGVIEW_PLOTLY_CONFIG = {
    "scrollZoom": True,
    "responsive": True,
    "displaylogo": False,
    "displayModeBar": "hover",
    "doubleClick": "reset",
    "modeBarButtonsToAdd": ["drawline", "drawrect", "eraseshape"],
}

# ACTUALIZACIÓN PARCHE (RENDIMIENTO - Directriz 3): las trazas de línea/
# precio del Panel Principal y de Señales Macro Avanzadas usan go.Scattergl
# (WebGL) en vez de go.Scatter (SVG/Canvas del hilo principal). Con 10+
# años de historia diaria, cada traza puede tener miles de puntos;
# go.Scattergl delega el dibujo a la GPU vía WebGL, lo que evita que el
# navegador bloquee la interacción (arrastrar, hacer zoom, hover) al
# recibir figuras grandes. Es un reemplazo directo de la API - mismos
# parámetros (x, y, mode, line, marker, fill, hovertemplate, etc.) - así
# que ningún gráfico cambia visualmente, solo la forma en que se renderiza.
#
# EXCEPCIÓN DELIBERADA: build_advanced_index_synced_figure (pestaña
# "Liquidez Avanzada") usa go.Scatter clásico, no Scattergl - ver su
# docstring para el detalle del glitch de panning que motivó revertirlo
# ahí específicamente.

GUIDE_LINE_TARGETS = ("Panel de Liquidez", "Panel de Precio")

# MEJORA TRADINGVIEW (Requerimiento 1 y 2): configuración del panel único
# sincronizado. DEFAULT_VERTICAL_AMPLIFICATION = 1.0 significa "auto-ajuste
# normal, sin exagerar la escala". Los usuarios pueden subirlo si su serie
# es genuinamente plana y quieren verla más "dramática".
DEFAULT_VERTICAL_AMPLIFICATION = 1.0
MIN_VERTICAL_AMPLIFICATION = 0.5
MAX_VERTICAL_AMPLIFICATION = 6.0
Y_AUTOSCALE_PADDING_RATIO = 0.08  # 8% de aire arriba/abajo del rango visible

# =====================================================================
# ACTUALIZACIÓN PARCHE (RENDIMIENTO - Rango de Fechas / Directriz 1, 2 y 3)
# =====================================================================
# DIAGNÓSTICO: con el historial ahora extendido a 10+ años (Bitcoin desde
# ~2014, liquidez desde ~2000/2002), cada rerun de Streamlit - incluido
# cada clic en un checkbox - reconstruía las figuras de Plotly con miles
# de puntos por traza y, sobre todo, con cientos de rectángulos de
# sombreado de picos (_add_peak_shading llama a figure.add_vrect() una vez
# por cada episodio de pico detectado en TODO el historial). Eso es lo que
# se sentía como "se congela": no era la descarga de datos (ya estaba
# cacheada con @st.cache_data desde antes), sino la cantidad de objetos
# que Plotly tenía que serializar y que el navegador tenía que dibujar en
# cada rerun.
#
# SOLUCIÓN: un selector de rango de fechas por panel que recorta el
# DataFrame a la ventana visible SOLO para el paso de graficado. El
# recorte ocurre SIEMPRE después de calcular EMA/SMA/Z-Score/RoC sobre el
# historial completo (para que el primer punto visible no arranque con una
# media móvil a medio calentar), y es una operación de indexado booleano
# en memoria (`df[mask]`) - no vuelve a descargar ni a recalcular nada
# desde cero, así que es prácticamente instantánea incluso con miles de
# filas de por medio.
DEFAULT_HISTORY_YEARS = 4


def _resolve_default_date_range(dataframe: pd.DataFrame) -> Tuple[date, date]:
    """
    Calcula los límites [mínimo, máximo] disponibles para el selector de
    rango de fechas, a partir de los datos realmente cargados.

    Parameters
    ----------
    dataframe : pd.DataFrame
        DataFrame con una columna Date ya normalizada.

    Returns
    -------
    Tuple[date, date]
        (fecha_minima_disponible, fecha_maxima_disponible).
    """
    try:
        if dataframe.empty or "Date" not in dataframe.columns:
            today = date.today()
            return today - timedelta(days=365 * DEFAULT_HISTORY_YEARS), today

        min_date = pd.Timestamp(dataframe["Date"].min()).date()
        max_date = pd.Timestamp(dataframe["Date"].max()).date()

        return min_date, max_date

    except Exception as error:
        LOGGER.exception(
            "Error al calcular el rango de fechas disponible. "
            "Tipo: %s. Detalle: %s",
            type(error).__name__,
            error,
        )
        today = date.today()
        return today - timedelta(days=365 * DEFAULT_HISTORY_YEARS), today


def render_date_range_control(
    dataframe: pd.DataFrame,
    widget_key: str,
    label: str = "📅 Rango histórico visible en esta vista",
) -> Tuple[pd.Timestamp, pd.Timestamp]:
    """
    Renderiza, en el ÁREA PRINCIPAL (NO en el sidebar) de la pestaña que lo
    invoque, un selector de rango de fechas (Directriz 1 - Rendimiento),
    con valor inicial acotado a los últimos DEFAULT_HISTORY_YEARS años,
    sin importar cuánta historia real haya disponible en el DataFrame.

    UI/UX (corrección solicitada): este control vive fuera de
    `st.sidebar` a propósito - el sidebar de este programa está reservado
    para las herramientas exclusivas del Panel Principal (checkboxes del
    motor de liquidez, activo a comparar, etc.). Cada pestaña
    (render_main_dashboard, render_advanced_liquidity_tab,
    render_macro_signals_tab) llama a esta función UNA VEZ, cerca de la
    parte superior de su propia vista, con un `widget_key` distinto - así
    cada selector guarda su propio estado en `st.session_state` bajo una
    key única (`f"{widget_key}_date_range"`) y cambiar el rango en una
    pestaña nunca afecta a las demás.

    Esta sigue siendo la pieza central de la mejora de rendimiento: reduce
    de raíz la cantidad de puntos y de sombreados de picos que Plotly debe
    renderizar por defecto, sin descartar ni un solo dato del DataFrame
    Maestro cacheado - el usuario puede ampliar la ventana en cualquier
    momento con este mismo control.

    Parameters
    ----------
    dataframe : pd.DataFrame
        DataFrame ya cargado (o derivado), con columna Date, usado
        únicamente para acotar los límites min/max del selector.
    widget_key : str
        Prefijo único de session_state para este selector (un control por
        pestaña, para no compartir estado entre pestañas independientes).
    label : str
        Texto mostrado sobre el selector.

    Returns
    -------
    Tuple[pd.Timestamp, pd.Timestamp]
        (fecha_inicio, fecha_fin) elegidas, como pd.Timestamp normalizados
        listos para usarse en _filter_dataframe_by_date_range.
    """
    try:
        min_available_date, max_available_date = _resolve_default_date_range(dataframe)

        default_start_date = max(
            min_available_date,
            max_available_date - timedelta(days=365 * DEFAULT_HISTORY_YEARS),
        )

        selected_range = st.date_input(
            label,
            value=(default_start_date, max_available_date),
            min_value=min_available_date,
            max_value=max_available_date,
            key=f"{widget_key}_date_range",
            help=(
                f"Por defecto se muestran los últimos {DEFAULT_HISTORY_YEARS} "
                "años para mantener la interfaz ágil. Los indicadores "
                "(EMA, SMA, Z-Score) siempre se calculan sobre el "
                "historial COMPLETO antes de este recorte - ampliar el "
                "rango solo cambia cuánto se dibuja, nunca las cuentas."
            ),
        )

        if isinstance(selected_range, tuple) and len(selected_range) == 2:
            range_start_date, range_end_date = selected_range
        else:
            # El usuario todavía no cerró el rango (solo eligió un extremo);
            # se usa el default mientras tanto para no romper el gráfico.
            range_start_date, range_end_date = default_start_date, max_available_date

        if range_start_date > range_end_date:
            range_start_date, range_end_date = range_end_date, range_start_date

        return pd.Timestamp(range_start_date), pd.Timestamp(range_end_date)

    except Exception as error:
        LOGGER.exception(
            "Error al renderizar el selector de rango de fechas. "
            "Tipo: %s. Detalle: %s",
            type(error).__name__,
            error,
        )
        fallback_end_date = pd.Timestamp(date.today())
        fallback_start_date = fallback_end_date - pd.Timedelta(
            days=365 * DEFAULT_HISTORY_YEARS
        )
        return fallback_start_date, fallback_end_date


def _filter_dataframe_by_date_range(
    dataframe: pd.DataFrame,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
) -> pd.DataFrame:
    """
    Recorta el DataFrame a la ventana de fechas visible, DESPUÉS de que
    todos los indicadores (EMA, SMA, Z-Score, RoC) ya se calcularon sobre
    el historial completo. Es un filtrado puro en memoria (indexado
    booleano de Pandas) - nunca vuelve a descargar ni a recalcular nada,
    por lo que es prácticamente instantáneo sin importar cuántos años de
    historia tenga el DataFrame de entrada.

    Parameters
    ----------
    dataframe : pd.DataFrame
        DataFrame ya procesado (indicadores ya calculados sobre el
        historial completo).
    start_date : pd.Timestamp
        Fecha de inicio del rango visible (inclusive).
    end_date : pd.Timestamp
        Fecha de fin del rango visible (inclusive).

    Returns
    -------
    pd.DataFrame
        Copia recortada, con el índice reseteado, lista para graficar.
    """
    try:
        if dataframe.empty or "Date" not in dataframe.columns:
            return dataframe

        visibility_mask = (
            (dataframe["Date"] >= start_date) & (dataframe["Date"] <= end_date)
        )
        filtered_dataframe = dataframe.loc[visibility_mask].copy()
        filtered_dataframe = filtered_dataframe.reset_index(drop=True)

        return filtered_dataframe

    except Exception as error:
        LOGGER.exception(
            "Error al filtrar el DataFrame por rango de fechas. "
            "Tipo: %s. Detalle: %s",
            type(error).__name__,
            error,
        )
        return dataframe


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


# NUEVO: INDICADOR LIQGLOB - historial de la Liquidez Excedentaria de la
# Eurozona (ILM.D.U2.C.EXLIQ.U2.EUR, fuente oficial del BCE), cacheado por
# separado del DataFrame Maestro porque viene de una API distinta a
# FRED/Yahoo, con su propia cadencia de fallos - mismo criterio que
# load_stablecoin_history y load_mvrv_zscore_history.
#
# CORRECCIÓN DE ERROR (Health Check mostraba "ERROR - sin datos todavía"
# de forma permanente): ahora se cachea la TUPLA completa (DataFrame,
# estado real) que devuelve get_ecb_liquidity_data() - la pestaña lee el
# estado directamente de aquí, no del `health_report` de
# load_master_dataframe() (que se captura ANTES de que esta función se
# ejecute y por eso nunca lo reflejaba). Ver docstring de
# get_ecb_liquidity_data en data_ingestion.py para el detalle completo.
@st.cache_data(ttl=1800, show_spinner=False)
def load_ecb_liquidity_history() -> Tuple[pd.DataFrame, str]:
    """
    Descarga (con caché de 30 min) el historial de la serie de Liquidez
    Excedentaria de la Eurozona directamente desde la API oficial del
    BCE, junto con su estado real ("OK" o "ERROR - detalle").
    """
    try:
        return get_ecb_liquidity_data()
    except Exception as error:
        LOGGER.exception(
            "Error al cargar historial de Liquidez Excedentaria del BCE. "
            "Tipo: %s. Detalle: %s",
            type(error).__name__,
            error,
        )
        return pd.DataFrame(columns=["Date", "Value"]), f"ERROR - {type(error).__name__}"


# NUEVO: INDICADOR LIQGLOB - Alineación Temporal por Semana Económica.
# A diferencia de WALCL/WDTGAL/BTC_Close/SOL_Close (que se leen del
# DataFrame Maestro ya ffilled), RRP y EUR/USD necesitan llegar a
# liqglob.py CRUDOS (sin forward-fill previo, con sus huecos reales) para
# poder aplicar la búsqueda miércoles->martes->lunes dentro de la misma
# semana - ver liqglob._select_weekly_value_with_fallback. Por eso se
# descargan aquí de forma independiente (misma fuente/serie de FRED que
# ya usa math_processor.py, no se inventa nada nuevo), cacheadas por
# separado igual que el resto de fuentes de esta pestaña.
@st.cache_data(ttl=1800, show_spinner=False)
def load_liqglob_rrp_history() -> pd.DataFrame:
    """
    Descarga (con caché de 30 min) el historial CRUDO de RRP (RRPONTSYD)
    desde FRED, sin ningún forward-fill previo.
    """
    try:
        return get_fred_data(series_id=FRED_SERIES["REVERSE_REPO"], api_key=FRED_API_KEY)
    except Exception as error:
        LOGGER.exception(
            "Error al cargar historial crudo de RRP para LIQGLOB. "
            "Tipo: %s. Detalle: %s",
            type(error).__name__,
            error,
        )
        return pd.DataFrame(columns=["Date", "Value"])


@st.cache_data(ttl=1800, show_spinner=False)
def load_liqglob_eurusd_history() -> pd.DataFrame:
    """
    Descarga (con caché de 30 min) el historial CRUDO de EUR/USD
    (DEXUSEU) desde FRED, sin ningún forward-fill previo.
    """
    try:
        return get_fred_data(series_id=FRED_SERIES["EUR_USD_FRED"], api_key=FRED_API_KEY)
    except Exception as error:
        LOGGER.exception(
            "Error al cargar historial crudo de EUR/USD para LIQGLOB. "
            "Tipo: %s. Detalle: %s",
            type(error).__name__,
            error,
        )
        return pd.DataFrame(columns=["Date", "Value"])


# =====================================================================
# VALIDACIÓN METODOLÓGICA DE LIQEUR (Control de Calidad, permanente)
# =====================================================================
# CANDADO: estos 4 loaders son 100% aditivos y de SOLO LECTURA. Descargan
# (con caché de 30 min, igual criterio que el resto de fuentes de esta
# pestaña) los 4 componentes oficiales del BCE necesarios para
# liqeur_validation.py. Ninguno participa en el cálculo de LIQGLOB_USD_B
# ni en el gráfico principal - solo alimentan la sección de Validación
# Metodológica de LIQEUR (control de calidad permanente, ver más abajo).
@st.cache_data(ttl=1800, show_spinner=False)
def load_ecb_current_accounts_history() -> Tuple[pd.DataFrame, str]:
    """
    Descarga (con caché de 30 min) el historial crudo de
    ILM.D.U2.C.L020100.U2.EUR (Current Accounts) desde el ECB Data Portal.
    """
    try:
        return get_ecb_liquidity_data(series_key=ECB_CURRENT_ACCOUNTS_SERIES_KEY)
    except Exception as error:
        LOGGER.exception(
            "Error al cargar Current Accounts para la validación de LIQEUR. "
            "Tipo: %s. Detalle: %s",
            type(error).__name__,
            error,
        )
        return pd.DataFrame(columns=["Date", "Value"]), f"ERROR - {type(error).__name__}"


@st.cache_data(ttl=1800, show_spinner=False)
def load_ecb_min_reserve_requirements_history() -> Tuple[pd.DataFrame, str]:
    """
    Descarga (con caché de 30 min) el historial crudo de
    ILM.D.U2.C.MRR.U2.EUR (Minimum Reserve Requirements) desde el ECB
    Data Portal.
    """
    try:
        return get_ecb_liquidity_data(series_key=ECB_MIN_RESERVE_REQUIREMENTS_SERIES_KEY)
    except Exception as error:
        LOGGER.exception(
            "Error al cargar Minimum Reserve Requirements para la "
            "validación de LIQEUR. Tipo: %s. Detalle: %s",
            type(error).__name__,
            error,
        )
        return pd.DataFrame(columns=["Date", "Value"]), f"ERROR - {type(error).__name__}"


@st.cache_data(ttl=1800, show_spinner=False)
def load_ecb_deposit_facility_history() -> Tuple[pd.DataFrame, str]:
    """
    Descarga (con caché de 30 min) el historial crudo de
    ILM.D.U2.C.L020200.U2.EUR (Deposit Facility) desde el ECB Data Portal.
    """
    try:
        return get_ecb_liquidity_data(series_key=ECB_DEPOSIT_FACILITY_SERIES_KEY)
    except Exception as error:
        LOGGER.exception(
            "Error al cargar Deposit Facility para la validación de "
            "LIQEUR. Tipo: %s. Detalle: %s",
            type(error).__name__,
            error,
        )
        return pd.DataFrame(columns=["Date", "Value"]), f"ERROR - {type(error).__name__}"


@st.cache_data(ttl=1800, show_spinner=False)
def load_ecb_marginal_lending_facility_history() -> Tuple[pd.DataFrame, str]:
    """
    Descarga (con caché de 30 min) el historial crudo de
    ILM.D.U2.C.A050500.U2.EUR (Marginal Lending Facility) desde el ECB
    Data Portal.
    """
    try:
        return get_ecb_liquidity_data(series_key=ECB_MARGINAL_LENDING_FACILITY_SERIES_KEY)
    except Exception as error:
        LOGGER.exception(
            "Error al cargar Marginal Lending Facility para la "
            "validación de LIQEUR. Tipo: %s. Detalle: %s",
            type(error).__name__,
            error,
        )
        return pd.DataFrame(columns=["Date", "Value"]), f"ERROR - {type(error).__name__}"


# =====================================================================
# RECONSTRUCCIÓN HISTÓRICA DE MRR (BSI + Calendario oficial, 2004+)
# =====================================================================
# CANDADO: estos 2 loaders son 100% aditivos. Alimentan exclusivamente la
# combinación que se arma en render_liqglob_tab() antes de llamar a
# build_liqglob_index() - liqglob.py en sí NO CAMBIA (sigue recibiendo un
# DataFrame crudo Date/Value de MRR, exactamente como antes; solo cambia
# CÓMO se construye ese DataFrame en app.py, combinando la fuente
# oficial ILM.D con esta reconstrucción histórica).
@st.cache_data(ttl=1800, show_spinner=False)
def load_ecb_bsi_mrr_history() -> Tuple[pd.DataFrame, str]:
    """
    Descarga (con caché de 30 min) el historial crudo de
    BSI.M.U2.N.R.MRR.X.1.A1.3000.Z01.E (Minimum Reserve Requirements,
    dataset BSI, mensual) - fuente histórica para la reconstrucción de
    MRR antes de 2024-09-27.
    """
    try:
        return get_ecb_liquidity_data(flow_ref=ECB_BSI_FLOW_REF, series_key=ECB_BSI_MRR_SERIES_KEY)
    except Exception as error:
        LOGGER.exception(
            "Error al cargar BSI-MRR histórico. Tipo: %s. Detalle: %s",
            type(error).__name__,
            error,
        )
        return pd.DataFrame(columns=["Date", "Value"]), f"ERROR - {type(error).__name__}"


@st.cache_data(ttl=86400, show_spinner=False)
def load_ecb_mp_calendar() -> Tuple[pd.DataFrame, Dict[str, object]]:
    """
    Obtiene (con caché de 24h - el calendario de Maintenance Periods
    prácticamente nunca cambia, ver mp_calendar.py) el calendario oficial
    combinado (semilla + caché en disco + años faltantes vía scraping
    validado). Nunca lanza excepción: cualquier fallo queda reflejado en
    el diccionario de estado, y el calendario devuelto es, como mínimo,
    lo que ya había validado antes de esta llamada.
    """
    try:
        return update_maintenance_period_calendar()
    except Exception as error:
        LOGGER.exception(
            "Error crítico al actualizar el calendario de Maintenance "
            "Periods. Tipo: %s. Detalle: %s",
            type(error).__name__,
            error,
        )
        return pd.DataFrame(columns=["Year", "MP", "GCMeetingDate", "StartDate", "EndDate"]), {
            "origen": "error",
            "scraping_disponible": False,
            "error": str(error),
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
            go.Scattergl(
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
            go.Scattergl(
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
            go.Scattergl(
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
            # ACTUALIZACIÓN PARCHE (UI/UX MÓVIL - Directriz 2): leyenda
            # horizontal centrada DEBAJO del gráfico (y negativo = por
            # debajo del área de trazado), en vez de anclada arriba a la
            # derecha - en pantallas angostas, una leyenda horizontal
            # arriba-derecha con varios ítems se corta o se superpone al
            # título; abajo-centrada siempre tiene todo el ancho
            # disponible para envolver en varias líneas sin tapar nada.
            legend={
                "orientation": "h",
                "yanchor": "top",
                "y": -0.18,
                "xanchor": "center",
                "x": 0.5,
            },
            # Márgenes laterales al mínimo (aprovechar el ancho angosto de
            # un teléfono) y margen inferior ampliado para dejarle sitio a
            # la leyenda ahora reubicada debajo del eje X.
            margin={
                "l": 10,
                "r": 10,
                "t": 80,
                "b": 70,
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
            go.Scattergl(
                x=chart_dataframe["Date"],
                y=chart_dataframe["Liquidez_Cruda_Desfasada"],
                mode="lines",
                name="Liquidez Global Cruda",
                line={"color": "#3B82F6", "width": 1.5, "shape": "hv"},
                opacity=0.55,
            ),
        )

        figure.add_trace(
            go.Scattergl(
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
            # ACTUALIZACIÓN PARCHE (UI/UX MÓVIL - Directriz 2): leyenda
            # horizontal centrada debajo del gráfico, ver nota completa en
            # create_main_figure.
            legend={"orientation": "h", "yanchor": "top", "y": -0.25, "xanchor": "center", "x": 0.5},
            margin={"l": 10, "r": 10, "t": 60, "b": 55},
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
            go.Scattergl(
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
            # ACTUALIZACIÓN PARCHE (UI/UX MÓVIL - Directriz 2): leyenda
            # horizontal centrada debajo del gráfico, ver nota completa en
            # create_main_figure.
            legend={"orientation": "h", "yanchor": "top", "y": -0.25, "xanchor": "center", "x": 0.5},
            margin={"l": 10, "r": 10, "t": 60, "b": 55},
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
            go.Scattergl(
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
            go.Scattergl(
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
            go.Scattergl(
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
            # ACTUALIZACIÓN PARCHE (UI/UX MÓVIL - Directriz 2): leyenda
            # horizontal centrada debajo de TODA la figura (ambas filas),
            # no arriba - ver nota completa en create_main_figure.
            legend={"orientation": "h", "yanchor": "top", "y": -0.12, "xanchor": "center", "x": 0.5},
            margin={"l": 10, "r": 10, "t": 40, "b": 60},
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

        // ACTUALIZACIÓN PARCHE (UI/UX MÓVIL - Directriz 1 y 3): este
        // gráfico se embebe con Plotly.newPlot crudo (no vía
        // st.plotly_chart), así que use_container_width no aplica aquí -
        // el div ya tiene width:100%, pero Plotly necesita que se le
        // avise explícitamente cuándo su contenedor cambió de tamaño
        // (rotar el teléfono, colapsar/expandir el sidebar de Streamlit,
        // cambiar de pestaña) para recalcular el layout. config.responsive
        // ya ayuda con el resize de ventana completa; el ResizeObserver de
        // aquí cubre además los cambios de ancho que NO disparan un evento
        // 'resize' de la ventana (como el sidebar colapsándose dentro del
        // mismo viewport).
        function resizePlot() {{
            try {{
                Plotly.Plots.resize(gd);
            }} catch (resizeError) {{
                // Silencioso: un resize fallido no debe romper el gráfico.
            }}
        }}

        window.addEventListener('resize', resizePlot);

        if (typeof ResizeObserver !== 'undefined') {{
            const containerObserver = new ResizeObserver(function() {{
                resizePlot();
            }});
            containerObserver.observe(gd);
        }}
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

    CORRECCIÓN DE ERROR (UI/UX - glitch visual al arrastrar): las trazas de
    esta función usan `go.Scatter` (SVG clásico), NO `go.Scattergl`
    (WebGL). Es la única excepción deliberada en todo el programa: al
    hacer clic y arrastrar (panning) sobre esta figura con Scattergl, el
    navegador hacía desaparecer por completo el gráfico durante el
    arrastre y solo lo volvía a dibujar al soltar el clic - un problema
    documentado de Plotly.js/WebGL con esta figura de dos filas
    sincronizadas. Con el filtro de rango de fechas ya activo (4 años por
    defecto), el volumen de puntos aquí es lo bastante bajo como para que
    SVG clásico no vuelva a introducir el lag original; el resto de
    figuras del programa (Panel Principal, Señales Macro) sí se benefician
    de WebGL y lo conservan.

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
            # ACTUALIZACIÓN PARCHE (UI/UX MÓVIL - Directriz 2): leyenda
            # horizontal centrada debajo de TODA la figura - ver nota
            # completa en create_main_figure.
            legend={"orientation": "h", "yanchor": "top", "y": -0.12, "xanchor": "center", "x": 0.5},
            margin={"l": 10, "r": 10, "t": 40, "b": 60},
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

        # AUDITORÍA (Directriz 4 - Datos Obsoletos): advertencia visual
        # junto al checkbox de China. MYAGM2CNM189N está descontinuada en
        # FRED desde 2019 (ver nota completa en config.py); el checkbox
        # nace apagado por defecto, pero si el usuario lo activa igual
        # debe ver, sin necesidad de leer el código, que ese componente
        # sesgará los datos con un valor congelado desde esa fecha.
        if component_key == "CHINA":
            st.sidebar.caption(CHINA_DATA_DEPRECATED_WARNING)

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

        # ACTUALIZACIÓN PARCHE (UI/UX - selector de fechas fuera del
        # sidebar): la carga del DataFrame Maestro se adelanta aquí (ya
        # está cacheada con @st.cache_data, así que en reruns normales es
        # prácticamente instantánea) para poder renderizar el selector de
        # rango de fechas en la parte SUPERIOR del área principal de esta
        # pestaña, antes que cualquier otro control - el sidebar queda
        # reservado exclusivamente para las herramientas del Panel
        # Principal (activo a comparar, checkboxes del motor de liquidez,
        # desfase, etc.).
        with st.spinner("Descargando y procesando información macroeconómica..."):
            master_dataframe, health_report = load_master_dataframe()

        if master_dataframe.empty:
            st.error(
                "No fue posible construir el DataFrame Maestro. "
                "Verifica la API key de FRED, la conexión a internet y la consola."
            )
            st.stop()

        range_start_date, range_end_date = render_date_range_control(
            master_dataframe, widget_key="main_panel"
        )

        render_health_check_panel(health_report)  # ACTUALIZACIÓN PARCHE

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

        # ACTUALIZACIÓN PARCHE (RENDIMIENTO - Directriz 1): el recorte
        # ocurre DESPUÉS de recalculate_liquidity (EMA de 14 días y Media
        # Móvil de 50 ya están calculadas sobre el historial completo) y
        # ANTES de construir la figura. range_start_date/range_end_date ya
        # se obtuvieron arriba, del selector renderizado al inicio de esta
        # vista (ver UI/UX: selector fuera del sidebar).
        master_dataframe = _filter_dataframe_by_date_range(
            master_dataframe, range_start_date, range_end_date
        )

        if master_dataframe.empty:
            st.warning(
                "No hay datos en el rango de fechas seleccionado. Amplía "
                "el selector de rango histórico al inicio de esta pestaña."
            )
            st.stop()

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

        # ACTUALIZACIÓN PARCHE (UI/UX - selector de fechas fuera del
        # sidebar): se adelanta la carga (ya cacheada, prácticamente
        # instantánea en reruns normales) para poder mostrar el selector
        # de rango de fechas al inicio de ESTA pestaña, con su propia
        # `key` (widget_key="advanced_liquidity_panel") independiente del
        # Panel Principal y de Señales Macro. El rango elegido aquí se
        # aplica más abajo, después de calcular RoC/Z-Score sobre el
        # historial completo.
        with st.spinner("Descargando y procesando datos de Liquidez Avanzada..."):
            master_dataframe, health_report = load_master_dataframe()
            stablecoin_dataframe = load_stablecoin_history()

        if master_dataframe.empty:
            st.error(
                "No fue posible construir el DataFrame Maestro. Revisa el "
                "Panel Principal para más detalle."
            )
            return

        adv_range_start_date, adv_range_end_date = render_date_range_control(
            master_dataframe, widget_key="advanced_liquidity_panel"
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

        # ACTUALIZACIÓN PARCHE (RENDIMIENTO - Directriz 1): el recorte de
        # fechas ocurre DESPUÉS de construir advanced_dataframe (RoC de 90
        # días y Z-Score rodante de 52 semanas ya calculados sobre el
        # historial completo) y ANTES de construir la figura sincronizada.
        # adv_range_start_date/adv_range_end_date ya se obtuvieron arriba,
        # del selector renderizado al inicio de esta vista.
        advanced_dataframe = _filter_dataframe_by_date_range(
            advanced_dataframe, adv_range_start_date, adv_range_end_date
        )

        if advanced_dataframe.empty:
            st.warning(
                "No hay datos en el rango de fechas seleccionado. Amplía "
                "el selector de rango histórico al inicio de esta pestaña."
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
            go.Scattergl(
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
            go.Scattergl(
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
                go.Scattergl(
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
            go.Scattergl(
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
            go.Scattergl(
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
            go.Scattergl(
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
            go.Scattergl(
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
            # ACTUALIZACIÓN PARCHE (UI/UX MÓVIL - Directriz 2): leyenda
            # horizontal centrada debajo de las 4 filas - ver nota
            # completa en create_main_figure. Con varios ítems (US10Y,
            # SMA, STLFSI4, DXY invertido, MVRV, BTC), anclarla arriba a
            # la derecha (como antes) la cortaba en pantallas angostas;
            # centrada abajo, tiene todo el ancho disponible para
            # envolver en varias líneas.
            legend={
                "orientation": "h",
                "yanchor": "top",
                "y": -0.06,
                "xanchor": "center",
                "x": 0.5,
                "font": {"size": 10},
            },
            margin={"l": 10, "r": 10, "t": 90, "b": 50},
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

        # ACTUALIZACIÓN PARCHE (UI/UX - selector de fechas fuera del
        # sidebar): se adelanta la carga (ya cacheada) para poder mostrar
        # el selector de rango de fechas al inicio de ESTA pestaña, con su
        # propia `key` (widget_key="macro_signals_panel") independiente de
        # las otras dos. El rango elegido aquí se aplica más abajo, solo a
        # la copia que se envía a Plotly - después de que US10Y_SMA,
        # STLFSI4 y DXY_RoC90_Inv ya se calcularon sobre todo el historial.
        with st.spinner("Descargando y alineando datos macro (FRED) y on-chain (MVRV)..."):
            master_dataframe, health_report = load_master_dataframe()
            mvrv_dataframe, mvrv_metadata = load_mvrv_zscore_history()

        if master_dataframe.empty:
            st.error(
                "No fue posible construir el DataFrame Maestro. Revisa el "
                "Panel Principal para más detalle."
            )
            return

        macro_range_start_date, macro_range_end_date = render_date_range_control(
            master_dataframe, widget_key="macro_signals_panel"
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

        # ACTUALIZACIÓN PARCHE (RENDIMIENTO - Directriz 1): el conteo de
        # señales de arriba usa el historial COMPLETO a propósito (es un
        # resumen, no un gráfico). macro_range_start_date/
        # macro_range_end_date ya se obtuvieron arriba, del selector
        # renderizado al inicio de esta vista.
        chart_panel_dataframe = _filter_dataframe_by_date_range(
            panel_dataframe, macro_range_start_date, macro_range_end_date
        )

        if chart_panel_dataframe.empty:
            st.warning(
                "No hay datos en el rango de fechas seleccionado. Amplía "
                "el selector de rango histórico al inicio de esta pestaña."
            )
            return

        synced_figure = build_macro_signals_synced_figure(
            panel_dataframe=chart_panel_dataframe,
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


# =====================================================================
# NUEVO: INDICADOR LIQGLOB (LIQUIDEZ GLOBAL: ESTADOS UNIDOS + EUROZONA)
# =====================================================================
# CANDADO: esta sección es 100% aditiva y vive en su propia pestaña (la
# 4ta). No modifica render_main_dashboard, render_advanced_liquidity_tab,
# render_macro_signals_tab, ni ninguna de las figuras/controles que ya
# usan - build_advanced_index_synced_figure y render_synced_dual_panel_chart
# se REUTILIZAN tal cual (mismo crosshair sincronizado, mismo auto-ajuste
# de eje Y, mismo desfase sin recorte) porque ya son genéricas por
# columna/DataFrame de entrada.

LIQGLOB_INDEX_COLUMN = "LIQGLOB_USD_B"
LIQGLOB_INDEX_LABEL = "LIQGLOB (Estados Unidos + Eurozona)"
DEFAULT_LIQGLOB_ASSET_PANEL_HEIGHT = 420
DEFAULT_LIQGLOB_INDEX_PANEL_HEIGHT = 420


def render_liqglob_tab() -> None:
    """
    Renderiza la pestaña LIQGLOB: indicador semanal de liquidez conjunta
    de Estados Unidos y la Eurozona, en miles de millones de dólares
    (billions), sin normalizar (sin RoC ni Z-Score) - a diferencia de la
    Liquidez Global Combinada de la pestaña "Liquidez Avanzada", que sí
    se sigue calculando exactamente igual que antes y no se toca aquí.

    CORRECCIÓN DE ERROR (salto de liquidez en fin de trimestre) +
    CAMBIO SIGNIFICATIVO (alineación por semana económica): cada
    observación se ancla al miércoles de su semana (con fallback a
    martes/lunes dentro de la misma semana si el miércoles no tiene
    publicación) para todas sus variables, en vez de tomar el viernes de
    un resample genérico - ver liqglob.py para el detalle completo.

    MIGRACIÓN DE METODOLOGÍA DE LIQEUR (ver config.LIQEUR_METHODOLOGY y
    liqglob.py): desde esta actualización, LIQEUR se construye por
    defecto a partir de sus 4 componentes oficiales del BCE (Current
    Accounts, Minimum Reserve Requirements, Deposit Facility, Marginal
    Lending Facility) en vez de depender directamente de la serie
    consolidada ILM.D.U2.C.EXLIQ.U2.EUR - cuyo historial retroactivo es
    más limitado. EXLIQ se sigue descargando y se sigue usando, pero
    ahora únicamente como serie de referencia en la sección "Validación
    Metodológica de LIQEUR" más abajo, para vigilar de forma continua que
    la reconstrucción siga coincidiendo con la serie oficial. Revertir a
    la metodología anterior es tan simple como cambiar
    config.LIQEUR_METHODOLOGY a "EXLIQ" - ningún archivo más necesita
    modificarse.

    Checkboxes: Estados Unidos (LIQEEUU) y Eurozona (LIQEUR), cada uno
    con su propia fórmula independiente (config.LIQGLOB_REGIONS). Incluye
    su propio selector de "Rango histórico visible en esta vista" y su
    propio panel de Health Check (con estado real, no una foto obsoleta -
    ver load_ecb_liquidity_history), con el mismo criterio que el resto
    de pestañas del programa.
    """
    try:
        render_terminal_section_header("LIQGLOB: LIQUIDEZ GLOBAL (EE.UU. + EUROZONA)", options_label="OPCIONES · LIQGLOB")
        st.caption(
            "Suma directa, en miles de millones de USD, de la liquidez "
            "neta de la Reserva Federal y la Liquidez Excedentaria del "
            "BCE (convertida a dólares) - sin normalizar, para comparar "
            "la escala nominal real contra BTC/SOL."
        )

        with st.spinner("Descargando y procesando datos de LIQGLOB..."):
            master_dataframe, health_report = load_master_dataframe()
            rrp_raw_dataframe = load_liqglob_rrp_history()
            eurusd_raw_dataframe = load_liqglob_eurusd_history()
            # MIGRACIÓN LIQEUR: los 4 componentes oficiales del BCE son
            # ahora la fuente ACTIVA de LIQEUR (config.LIQEUR_METHODOLOGY
            # == "COMPONENTS") - se cargan aquí, antes de construir el
            # gráfico principal, y se reutilizan más abajo también en la
            # sección de Validación Metodológica (sin volver a
            # descargarlos - @st.cache_data ya los tiene en caché).
            current_accounts_raw, current_accounts_status = load_ecb_current_accounts_history()
            mrr_raw, mrr_status = load_ecb_min_reserve_requirements_history()
            deposit_facility_raw, deposit_facility_status = load_ecb_deposit_facility_history()
            mlf_raw, mlf_status = load_ecb_marginal_lending_facility_history()
            # EXLIQ: ya NO participa en el cálculo activo de LIQEUR (ver
            # liqglob._compute_liqeur_weekly_from_components) - se sigue
            # descargando únicamente como serie de referencia para la
            # Validación Metodológica, más abajo en esta misma pestaña.
            ecb_liquidity_dataframe, ecb_health_status = load_ecb_liquidity_history()

            # RECONSTRUCCIÓN HISTÓRICA DE MRR (BSI + calendario oficial,
            # 2004+): MRR es el único de los 4 componentes cuya versión
            # diaria (ILM.D) solo tiene historial desde 2024-09-27. Esta
            # combinación vive ENTERAMENTE aquí, en app.py - liqglob.py
            # no cambia en absoluto, sigue recibiendo un DataFrame crudo
            # Date/Value de MRR, exactamente como antes de esta
            # actualización. Un fallo de cualquiera de estas dos fuentes
            # (BSI o calendario) nunca degrada el resultado por debajo de
            # `mrr_raw` solo (combine_mrr_sources_with_priority siempre
            # prioriza el dato oficial ILM.D cuando existe).
            bsi_mrr_raw, bsi_mrr_status = load_ecb_bsi_mrr_history()
            mp_calendar_dataframe, mp_calendar_status = load_ecb_mp_calendar()
            mrr_historical_daily = build_mrr_historical_daily_series(
                bsi_mrr_raw, mp_calendar_dataframe
            )
            mrr_combined_raw = combine_mrr_sources_with_priority(
                ilm_daily_mrr_raw=mrr_raw,
                historical_mrr_daily=mrr_historical_daily,
            )

        if master_dataframe.empty:
            st.error(
                "No fue posible construir el DataFrame Maestro. Revisa el "
                "Panel Principal para más detalle."
            )
            return

        liqglob_range_start_date, liqglob_range_end_date = render_date_range_control(
            master_dataframe, widget_key="liqglob_panel"
        )

        with st.expander("¿CÓMO SE CALCULA LIQGLOB?"):
            st.markdown(
                """
**LIQGLOB = LIQEEUU + LIQEUR** (miles de millones de USD, una observación por semana económica)

- **LIQEEUU** (Estados Unidos) = `WALCL - TGA (WDTGAL) - RRP (RRPONTSYD)`,
  las tres series de la Reserva Federal vía FRED, ya convertidas a la
  misma unidad (miles de millones de USD).
- **LIQEUR** (Eurozona) = `(Current Accounts - Minimum Reserve
  Requirements) + Deposit Facility - Marginal Lending Facility`, la
  fórmula oficial del BCE aplicada a sus 4 componentes oficiales
  (ECB Data Portal, dataflow `ILM`), convertida de millones a miles de
  millones de EUR y luego a USD con el tipo de cambio EUR/USD oficial de
  FRED (DEXUSEU). **Metodología migrada:** hasta la actualización
  anterior, LIQEUR se tomaba directamente de la serie consolidada
  `ILM.D.U2.C.EXLIQ.U2.EUR`; tras una validación empírica (correlación
  prácticamente perfecta entre ambos cálculos - ver la sección
  "Validación Metodológica de LIQEUR" más abajo), se migró a calcularla
  desde sus 4 componentes, que tienen un historial mucho más profundo que
  la serie consolidada. `EXLIQ` se sigue descargando, pero ahora
  únicamente como serie de referencia de esa validación - ya no participa
  en este cálculo.
- Cada región es togglable de forma independiente con su propio
  checkbox: al desactivar una, su fórmula completa deja de sumar (no es
  un componente parcial, son dos fórmulas separadas).
- **Alineación por semana económica (miércoles):** cada observación
  representa una única semana, y todas sus variables provienen de esa
  misma semana. WALCL/TGA (semanales) usan la observación oficial de esa
  semana; RRP, EUR/USD y los 4 componentes de LIQEUR (diarios) usan el
  dato real del **miércoles** - si no existe por feriado, se busca el día
  hábil anterior **dentro de la misma semana** (martes, luego lunes).
  Nunca se mezcla un dato de una semana con el de otra.
- **Integridad semanal:** si a una región activa le falta información
  para calcular su fórmula completa esa semana (para Eurozona: cualquiera
  de los 4 componentes o el EUR/USD), esa observación simplemente **no se
  dibuja** (no se rellena con 0 ni se inventa un valor) - queda como un
  hueco en la línea, nunca como una caída vertical ni una escala
  aplastada.
- **Momento de ejecución:** el indicador se recalcula automáticamente en
  cada carga de la app. Abrir el programa no cambia la fecha económica de
  cada punto (siempre el miércoles de su semana) - solo determina si el
  dato oficial de la semana más reciente ya está publicado o todavía no.
- **Ventana histórica:** las últimas ~600 semanas (~11.5 años),
  reconstruida automáticamente en cada ejecución - ningún dato se
  introduce a mano.
                """
            )

        st.markdown("### COMPONENTES DE LIQGLOB")
        st.caption(
            "Desmarca cualquier región para excluir su fórmula completa "
            "de la suma - LIQGLOB se recalcula al instante."
        )

        region_toggles: Dict[str, bool] = {}
        checkbox_columns = st.columns(len(LIQGLOB_REGIONS))
        for checkbox_column, (region_key, region_config) in zip(
            checkbox_columns, LIQGLOB_REGIONS.items()
        ):
            session_key = f"liqglob_toggle_{region_key}"
            if session_key not in st.session_state:
                st.session_state[session_key] = region_config["default"]
            with checkbox_column:
                region_toggles[region_key] = st.checkbox(
                    region_config["label"],
                    key=session_key,
                )

        control_column, restore_column = st.columns([4, 1])
        with control_column:
            asset_col, offset_col = st.columns(2)
            with asset_col:
                liqglob_asset_label = st.radio(
                    "Activo a comparar",
                    options=list(ASSET_OPTIONS.keys()),
                    key="liqglob_asset_choice",
                    horizontal=True,
                )
                liqglob_asset_column = ASSET_OPTIONS[liqglob_asset_label]
            with offset_col:
                liqglob_offset_periods = st.slider(
                    "Desfase (semanas)",
                    min_value=0,
                    max_value=26,
                    value=0,
                    step=1,
                    key="liqglob_offset_slider",
                    help="Mismo mecanismo anti-recorte que el Panel Principal, en semanas.",
                )

            if "liqglob_asset_panel_height" not in st.session_state:
                st.session_state["liqglob_asset_panel_height"] = DEFAULT_LIQGLOB_ASSET_PANEL_HEIGHT
            if "liqglob_index_panel_height" not in st.session_state:
                st.session_state["liqglob_index_panel_height"] = DEFAULT_LIQGLOB_INDEX_PANEL_HEIGHT

            height_col1, height_col2 = st.columns(2)
            with height_col1:
                st.session_state["liqglob_asset_panel_height"] = st.slider(
                    f"Alto del panel de {liqglob_asset_label} (px)",
                    min_value=200,
                    max_value=700,
                    value=st.session_state["liqglob_asset_panel_height"],
                    key="liqglob_asset_height_slider",
                )
            with height_col2:
                st.session_state["liqglob_index_panel_height"] = st.slider(
                    "Alto del panel de LIQGLOB (px)",
                    min_value=200,
                    max_value=700,
                    value=st.session_state["liqglob_index_panel_height"],
                    key="liqglob_index_height_slider",
                )
        with restore_column:
            st.write("")
            st.write("")
            if st.button("RESTAURAR PROPORCIÓN ORIGINAL", key="liqglob_restore_button"):
                st.session_state["liqglob_asset_panel_height"] = DEFAULT_LIQGLOB_ASSET_PANEL_HEIGHT
                st.session_state["liqglob_index_panel_height"] = DEFAULT_LIQGLOB_INDEX_PANEL_HEIGHT
                st.rerun()

        st.caption(
            "Igual que en el Panel Principal: rueda del mouse = zoom "
            "horizontal, arrastrar el eje Y = comprimir/estirar la escala, "
            "cursor sincronizado entre ambos paneles."
        )

        # CORRECCIÓN DE ERROR (robustez ante fallos temporales de fuentes):
        # antes, si una región ACTIVA tenía su fuente cruda completamente
        # caída en esta carga (ej. HTTP 504 de la API del BCE), la regla de
        # integridad semanal de liqglob.py invalidaba el 100% de las
        # semanas del indicador - incluidas todas las semanas donde la
        # OTRA región (con datos íntegros) sí tenía información real. Esa
        # regla sigue siendo correcta para huecos puntuales dentro de una
        # fuente que funciona (ver liqglob._select_weekly_value_with_
        # fallback) - el problema aparecía solo cuando la fuente entera
        # fallaba en la descarga misma, no en una semana puntual.
        #
        # La corrección vive aquí, en la UI, y NO modifica liqglob.py. La
        # disponibilidad de Eurozona ahora depende de sus 4 componentes
        # oficiales del BCE + EUR/USD (metodología activa, "COMPONENTS") o
        # de EXLIQ + EUR/USD (metodología legado, "EXLIQ") - según
        # config.LIQEUR_METHODOLOGY, para que este chequeo de robustez
        # siga siendo válido sin importar cuál metodología esté activa. Si
        # la fuente cruda de una región activa llega vacía en esta carga,
        # esa región se excluye SOLO de este cálculo puntual (sin tocar el
        # checkbox del usuario, que conserva su estado), y se avisa con
        # claridad, indicando cuál de los componentes fue el que falló.
        #
        # NOTA: la disponibilidad de MRR se evalúa sobre `mrr_combined_raw`
        # (oficial ILM.D + reconstrucción histórica BSI+calendario), no
        # sobre `mrr_raw` a secas - así, si el ILM.D oficial falla mientras
        # la reconstrucción histórica sigue cubriendo las fechas
        # necesarias, Eurozona NO se degrada innecesariamente.
        if LIQEUR_METHODOLOGY == "EXLIQ":
            eurozone_source_available = (
                eurusd_raw_dataframe is not None and not eurusd_raw_dataframe.empty
                and ecb_liquidity_dataframe is not None and not ecb_liquidity_dataframe.empty
            )
        else:
            eurozone_components_status = {
                "Current Accounts": current_accounts_raw is not None and not current_accounts_raw.empty,
                "Minimum Reserve Requirements": mrr_combined_raw is not None and not mrr_combined_raw.empty,
                "Deposit Facility": deposit_facility_raw is not None and not deposit_facility_raw.empty,
                "Marginal Lending Facility": mlf_raw is not None and not mlf_raw.empty,
            }
            failed_components = [name for name, ok in eurozone_components_status.items() if not ok]
            eurozone_source_available = (
                eurusd_raw_dataframe is not None and not eurusd_raw_dataframe.empty
                and not failed_components
            )
            if failed_components:
                LOGGER.warning(
                    "Componente(s) del BCE no disponibles en esta carga: %s. "
                    "Eurozona se excluye temporalmente del gráfico principal.",
                    failed_components,
                )

        region_source_available = {
            "US": rrp_raw_dataframe is not None and not rrp_raw_dataframe.empty,
            "EUROZONE": eurozone_source_available,
        }

        effective_region_toggles = dict(region_toggles)
        degraded_region_labels = []
        for region_key, source_is_available in region_source_available.items():
            if effective_region_toggles.get(region_key, True) and not source_is_available:
                effective_region_toggles[region_key] = False
                degraded_region_labels.append(
                    LIQGLOB_REGIONS.get(region_key, {}).get("label", region_key)
                )

        if degraded_region_labels:
            st.warning(
                "⚠️ La fuente de datos de **" + "** y **".join(degraded_region_labels) + "** "
                "no respondió en esta carga (revisa el Health Check más "
                "abajo para el detalle de cuál fuente específica falló). "
                "LIQGLOB se muestra temporalmente solo con las regiones que "
                "sí tienen datos disponibles ahora mismo - tu selección de "
                "checkboxes no cambió. Vuelve a cargar la página cuando la "
                "fuente se recupere para ver el indicador completo de nuevo."
            )

        liqglob_dataframe = build_liqglob_index(
            master_dataframe,
            rrp_raw_dataframe=rrp_raw_dataframe,
            eurusd_raw_dataframe=eurusd_raw_dataframe,
            current_accounts_raw_dataframe=current_accounts_raw,
            min_reserve_requirements_raw_dataframe=mrr_combined_raw,
            deposit_facility_raw_dataframe=deposit_facility_raw,
            marginal_lending_facility_raw_dataframe=mlf_raw,
            ecb_liquidity_dataframe=ecb_liquidity_dataframe,
            region_toggles=effective_region_toggles,
        )

        if (
            liqglob_dataframe.empty
            or LIQGLOB_INDEX_COLUMN not in liqglob_dataframe.columns
            or liqglob_dataframe[LIQGLOB_INDEX_COLUMN].dropna().empty
        ):
            st.warning(
                "Todavía no hay suficiente historial para calcular "
                "LIQGLOB con la configuración actual. Prueba activando "
                "más regiones, o revisa el panel de Health Check más "
                "abajo si alguna fuente está fallando."
            )
            return

        liqglob_dataframe = _filter_dataframe_by_date_range(
            liqglob_dataframe, liqglob_range_start_date, liqglob_range_end_date
        )

        if liqglob_dataframe.empty:
            st.warning(
                "No hay datos en el rango de fechas seleccionado. Amplía "
                "el selector de rango histórico al inicio de esta pestaña."
            )
            return

        synced_figure, row1_indices, row2_indices = build_advanced_index_synced_figure(
            advanced_dataframe=liqglob_dataframe,
            asset_label=liqglob_asset_label,
            asset_column=liqglob_asset_column,
            index_label=LIQGLOB_INDEX_LABEL,
            index_column=LIQGLOB_INDEX_COLUMN,
            offset_periods=liqglob_offset_periods,
            asset_panel_height=st.session_state["liqglob_asset_panel_height"],
            index_panel_height=st.session_state["liqglob_index_panel_height"],
            offset_freq=LIQGLOB_RESAMPLE_RULE,
            value_unit_label="Miles de millones USD",
            value_axis_title="LIQGLOB (Miles de millones de USD)",
            reference_lines=[],
        )

        render_synced_dual_panel_chart(
            figure=synced_figure,
            row1_trace_indices=row1_indices,
            row2_trace_indices=row2_indices,
            component_height=(
                st.session_state["liqglob_asset_panel_height"]
                + st.session_state["liqglob_index_panel_height"]
            ),
            asset_amplification=1.0,
            liquidity_amplification=1.0,
        )

        with st.expander("ESTADO DE LAS FUENTES DE ESTA PESTAÑA (HEALTH CHECK)"):
            # El health check se indexa por ID real de fuente: las tres
            # series de la Fed + el tipo de cambio EUR/USD (health_report
            # ya las trae, math_processor.py las descarga siempre), los 4
            # componentes oficiales del BCE (fuente ACTIVA de LIQEUR desde
            # la migración de metodología - cada uno con su propio estado,
            # para identificar exactamente cuál falla si alguno falla) y
            # la serie EXLIQ (ahora solo referencia de validación), cuyo
            # estado se lee DIRECTO de load_ecb_liquidity_history() (ver
            # corrección de error en su docstring) - no de health_report,
            # que puede estar desfasado.
            relevant_sources = {
                key: value
                for key, value in health_report.items()
                if key in {"WALCL", "WDTGAL", "RRPONTSYD", "DEXUSEU"}
            }
            relevant_sources["Current Accounts (fuente activa LIQEUR)"] = current_accounts_status
            relevant_sources["Minimum Reserve Req. (fuente activa LIQEUR)"] = mrr_status
            relevant_sources["Deposit Facility (fuente activa LIQEUR)"] = deposit_facility_status
            relevant_sources["Marginal Lending Facility (fuente activa LIQEUR)"] = mlf_status
            relevant_sources["ILM.D.U2.C.EXLIQ.U2.EUR (solo referencia de validación)"] = ecb_health_status
            if not relevant_sources:
                st.write("Sin información de salud disponible todavía.")
            for source_name, status in sorted(relevant_sources.items()):
                if status == "OK":
                    st.success(f"{source_name}: OK")
                elif isinstance(status, str) and status.startswith("OK"):
                    st.warning(f"{source_name}: {status}")
                else:
                    st.error(f"{source_name}: {status}")

            # VERIFICACIÓN DE COBERTURA HISTÓRICA REAL (por región): antes
            # de asumir que una región "empieza tarde" por una fuente que
            # no tiene historia, se reporta aquí la fecha REAL de la
            # primera y última observación CRUDA de cada fuente (antes de
            # cualquier alineación semanal o recorte de ventana) - esto
            # permite confirmar directamente si el BCE realmente no tiene
            # datos anteriores a cierta fecha, o si el hueco aparece en
            # otro punto del procesamiento. Ahora incluye los 4 componentes
            # (la fuente que realmente determina cuánto se extiende hacia
            # atrás el histórico de Eurozona).
            st.markdown("---")
            st.markdown("**Cobertura histórica real de cada fuente (dato crudo, sin recortar):**")
            coverage_report = get_liqglob_source_coverage_report(
                master_dataframe,
                rrp_raw_dataframe=rrp_raw_dataframe,
                eurusd_raw_dataframe=eurusd_raw_dataframe,
                current_accounts_raw_dataframe=current_accounts_raw,
                min_reserve_requirements_raw_dataframe=mrr_raw,
                deposit_facility_raw_dataframe=deposit_facility_raw,
                marginal_lending_facility_raw_dataframe=mlf_raw,
                ecb_liquidity_dataframe=ecb_liquidity_dataframe,
            )
            for source_name, coverage in coverage_report.items():
                first_date = coverage.get("primer_dato")
                last_date = coverage.get("ultimo_dato")
                record_count = coverage.get("registros", 0)
                if first_date is None or last_date is None:
                    st.write(f"- **{source_name}**: sin datos crudos disponibles.")
                else:
                    st.write(
                        f"- **{source_name}**: primer dato real "
                        f"**{first_date.strftime('%Y-%m-%d')}**, último dato real "
                        f"**{last_date.strftime('%Y-%m-%d')}** "
                        f"({record_count} observaciones crudas)."
                    )
            st.caption(
                "Si la fecha del primer dato real de una fuente coincide "
                "con el arranque del tramo visible de esa región en el "
                "gráfico, la serie oficial correspondiente realmente no "
                "tiene historia anterior - no es un recorte del programa."
            )

        # =============================================================
        # RECONSTRUCCIÓN HISTÓRICA DE MRR (BSI + Calendario BCE, 2004+)
        # =============================================================
        # CANDADO: sección de solo lectura, informativa. No participa en
        # el cálculo - liqglob_dataframe ya se construyó más arriba con
        # `mrr_combined_raw`. Un fallo total de BSI o del calendario no
        # afecta esta sección más que en mostrar su propio estado "sin
        # datos" - el resto de la pestaña sigue funcionando igual (ver
        # combine_mrr_sources_with_priority: nunca degrada por debajo de
        # lo que ya ofrecía la serie oficial ILM.D sola).
        with st.expander("RECONSTRUCCIÓN HISTÓRICA DE MRR (BSI + CALENDARIO BCE, 2004+)"):
            st.caption(
                "MRR es el único de los 4 componentes de LIQEUR cuya serie "
                "diaria oficial (ILM.D.U2.C.MRR.U2.EUR) solo tiene "
                "historial desde 2024-09-27. Para extender el histórico de "
                "LIQGLOB antes de esa fecha, este bloque reconstruye MRR "
                "usando la serie mensual oficial BSI.M.U2.N.R.MRR.X.1.A1."
                "3000.Z01.E junto con el calendario oficial de Maintenance "
                "Periods del BCE (2004 en adelante) - nunca por "
                "aproximación de mes calendario."
            )

            # --- Estado de la fuente BSI ---
            if bsi_mrr_status == "OK":
                st.success(f"BSI.M.U2.N.R.MRR.X.1.A1.3000.Z01.E: {bsi_mrr_status}")
            elif isinstance(bsi_mrr_status, str) and bsi_mrr_status.startswith("OK"):
                st.warning(f"BSI.M.U2.N.R.MRR.X.1.A1.3000.Z01.E: {bsi_mrr_status}")
            else:
                st.error(f"BSI.M.U2.N.R.MRR.X.1.A1.3000.Z01.E: {bsi_mrr_status}")

            # --- Estado del calendario de Maintenance Periods ---
            calendar_years_used = mp_calendar_status.get("años_ya_validados_reutilizados", [])
            calendar_years_added = mp_calendar_status.get("años_agregados_exitosamente", [])
            calendar_years_failed = mp_calendar_status.get("años_fallidos", {})
            scraping_disponible = mp_calendar_status.get("scraping_disponible")

            if mp_calendar_dataframe is not None and not mp_calendar_dataframe.empty:
                calendar_coverage_start = int(mp_calendar_dataframe["Year"].min())
                calendar_coverage_end = int(mp_calendar_dataframe["Year"].max())
                calendar_periods_count = len(mp_calendar_dataframe)
            else:
                calendar_coverage_start = None
                calendar_coverage_end = None
                calendar_periods_count = 0

            if calendar_periods_count == 0:
                st.error(
                    "Calendario de Maintenance Periods: ERROR - sin datos "
                    "disponibles (ni semilla, ni caché, ni scraping exitoso)."
                )
            elif scraping_disponible is False:
                st.warning(
                    f"Calendario de Maintenance Periods: ADVERTENCIA - el "
                    f"scraping falló en esta carga, usando caché anterior "
                    f"(cobertura: {calendar_coverage_start}-{calendar_coverage_end}, "
                    f"{calendar_periods_count} períodos validados)."
                )
            elif calendar_years_failed:
                st.warning(
                    f"Calendario de Maintenance Periods: OK con advertencias "
                    f"- años que no se pudieron validar en esta carga: "
                    f"{list(calendar_years_failed.keys())}. Cobertura actual: "
                    f"{calendar_coverage_start}-{calendar_coverage_end} "
                    f"({calendar_periods_count} períodos validados)."
                )
            else:
                origen_texto = "caché (sin necesidad de scraping)" if not calendar_years_added else (
                    f"caché + scraping exitoso de: {calendar_years_added}"
                )
                st.success(
                    f"Calendario de Maintenance Periods: OK ({origen_texto}). "
                    f"Cobertura: {calendar_coverage_start}-{calendar_coverage_end} "
                    f"({calendar_periods_count} períodos validados)."
                )

            if mp_calendar_status.get("alerta_posible_cambio_de_formato"):
                st.error(
                    "⚠️ El scraper no reprodujo correctamente el calendario "
                    "de referencia dorada (2014) - posible cambio de "
                    "formato en el sitio del BCE. Se descartó el resultado "
                    "nuevo y se sigue usando la última caché válida "
                    "conocida. Revisar manualmente antes de confiar en "
                    "años nuevos agregados por scraping."
                )

            st.markdown(
                f"**Años ya validados y reutilizados desde caché "
                f"(nunca se vuelven a descargar):** "
                f"{calendar_years_used if calendar_years_used else 'ninguno todavía'}"
            )

            # --- Cobertura de la reconstrucción combinada y transición automática ---
            reconstruction_coverage = get_mrr_reconstruction_coverage_report(
                bsi_mrr_raw, mp_calendar_dataframe, mrr_raw
            )
            st.markdown("---")
            st.markdown("**Cobertura de la reconstrucción combinada:**")

            def _format_coverage_date(value):
                return value.strftime("%Y-%m-%d") if value is not None and pd.notna(value) else "N/D"

            st.write(
                f"- BSI (crudo, mensual): "
                f"{_format_coverage_date(reconstruction_coverage.get('bsi_primer_dato'))} a "
                f"{_format_coverage_date(reconstruction_coverage.get('bsi_ultimo_dato'))} "
                f"({reconstruction_coverage.get('bsi_registros', 0)} observaciones)."
            )
            st.write(
                f"- Reconstrucción histórica diaria (BSI + calendario): "
                f"{_format_coverage_date(reconstruction_coverage.get('reconstruccion_historica_primer_dia'))} a "
                f"{_format_coverage_date(reconstruction_coverage.get('reconstruccion_historica_ultimo_dia'))}."
            )
            transition_date = reconstruction_coverage.get("transicion_automatica_detectada_en")
            st.write(
                f"- **Punto de transición automática hacia la serie oficial "
                f"ILM.D.U2.C.MRR.U2.EUR:** {_format_coverage_date(transition_date)} "
                f"(a partir de esta fecha, la serie oficial siempre tiene "
                f"prioridad sobre la reconstrucción histórica, sin importar "
                f"que la reconstrucción también cubra esas fechas)."
            )
            st.caption(
                "Esta reconstrucción es de solo lectura: nunca interpola, "
                "nunca promedia, nunca inventa un valor donde no hay una "
                "observación real de BSI dentro del Maintenance Period "
                "correspondiente - esas semanas simplemente no se dibujan, "
                "igual criterio que el resto del programa."
            )

        # =============================================================
        # VALIDACIÓN METODOLÓGICA DE LIQEUR (Control de Calidad, permanente)
        # =============================================================
        # POR QUÉ EXISTE: esta sección nació como una validación puntual
        # (¿la fórmula oficial del BCE, aplicada a sus 4 componentes
        # públicos, reproduce la serie consolidada EXLIQ?), y tras
        # confirmarse empíricamente que sí (correlación prácticamente
        # perfecta), esa misma fórmula se convirtió en la metodología
        # ACTIVA de LIQEUR (ver liqglob._compute_liqeur_weekly_from_
        # components y config.LIQEUR_METHODOLOGY). Esta sección se
        # conserva de forma PERMANENTE como herramienta de control de
        # calidad: vigila en cada carga que la metodología activa siga
        # coincidiendo con la serie oficial EXLIQ, para detectar de
        # inmediato cualquier cambio futuro en la metodología de
        # publicación del BCE - sin que nadie tenga que acordarse de
        # revisarlo manualmente. Ver liqeur_validation.py para el detalle
        # completo de la metodología, las fórmulas y los umbrales.
        #
        # QUÉ COMPARA: LIQEUR_Reconstruida (a partir de los 4 componentes
        # oficiales del BCE - la misma fórmula que usa el cálculo activo
        # de LIQGLOB) contra EXLIQ_Oficial (la serie consolidada
        # ILM.D.U2.C.EXLIQ.U2.EUR, que ya NO participa en el cálculo,
        # solo en esta comparación), fecha por fecha.
        #
        # QUÉ NO ES: esta sección NO calcula ni modifica LIQGLOB. Es una
        # auditoría paralela e independiente sobre la metodología activa,
        # que ya se aplicó más arriba en build_liqglob_index().
        #
        # CANDADO - INDEPENDENCIA ABSOLUTA (auditado, ver informe de
        # auditoría entregado junto con esta actualización): este bloque
        # es de SOLO LECTURA. Desde la migración de metodología, los 4
        # componentes del BCE y EXLIQ se cargan UNA sola vez, arriba, al
        # inicio de la función (porque los 4 componentes ahora también
        # alimentan el gráfico principal) - esta sección los REUTILIZA tal
        # cual (misma referencia de los DataFrames ya cacheados por
        # @st.cache_data), sin volver a descargarlos y sin modificarlos.
        # La independencia funcional se mantiene intacta: `liqglob_dataframe`
        # ya se construyó más arriba, usando build_liqglob_index() sobre
        # los DataFrames CRUDOS únicamente - nunca sobre ningún resultado
        # de esta sección (`liqeur_reconstruction`, `validation_report`,
        # `validation_status`). Esta sección nunca escribe en
        # `liqglob_dataframe`, en `region_toggles`/`effective_region_
        # toggles`, ni en ninguna otra variable usada por el gráfico
        # principal. Un error aquí dentro (ver el propio try/except de
        # toda la función) nunca puede afectar el cálculo de LIQGLOB.
        st.markdown("---")
        st.markdown("## 🔍 VALIDACIÓN METODOLÓGICA DE LIQEUR")
        st.caption(
            "Control de calidad permanente: compara, día a día, la "
            "metodología ACTIVA de LIQEUR (reconstrucción por los 4 "
            "componentes oficiales del BCE) contra la serie oficial "
            "consolidada ILM.D.U2.C.EXLIQ.U2.EUR, que ahora funciona "
            "únicamente como referencia de validación. Esta sección es de "
            "solo lectura y no puede modificar el gráfico principal: "
            "`LIQEUR = (Current Accounts - Minimum Reserve Requirements) "
            "+ Deposit Facility - Marginal Lending Facility`."
        )

        with st.expander("ESTADO DE LOS 4 COMPONENTES (HEALTH CHECK)"):
            component_health = {
                "Current Accounts - ILM.D.U2.C.L020100.U2.EUR": current_accounts_status,
                "Minimum Reserve Requirements - ILM.D.U2.C.MRR.U2.EUR": mrr_status,
                "Deposit Facility - ILM.D.U2.C.L020200.U2.EUR": deposit_facility_status,
                "Marginal Lending Facility - ILM.D.U2.C.A050500.U2.EUR": mlf_status,
            }
            for source_name, status in component_health.items():
                if status == "OK":
                    st.success(f"{source_name}: OK")
                elif isinstance(status, str) and status.startswith("OK"):
                    st.warning(f"{source_name}: {status}")
                else:
                    st.error(f"{source_name}: {status}")

        # SOLO LECTURA: build_liqeur_reconstruction y
        # compare_liqeur_reconstruction_vs_official reciben DataFrames y
        # devuelven resultados - no modifican nada fuera de esta función,
        # y nada de lo que calculan se reutiliza en el gráfico principal.
        liqeur_reconstruction = build_liqeur_reconstruction(
            current_accounts_raw=current_accounts_raw,
            min_reserve_requirements_raw=mrr_raw,
            deposit_facility_raw=deposit_facility_raw,
            marginal_lending_facility_raw=mlf_raw,
        )

        validation_report = compare_liqeur_reconstruction_vs_official(
            reconstructed_dataframe=liqeur_reconstruction,
            exliq_official_raw=ecb_liquidity_dataframe,
        )

        # RESUMEN AUTOMÁTICO DE VALIDACIÓN: el estado (🟢/🟡/🔴/⚪) y el
        # mensaje se calculan en cada carga a partir de los números reales
        # del reporte - nunca es un texto fijo. Ver
        # config.LIQEUR_VALIDATION_STATUS_THRESHOLDS para los umbrales
        # documentados que definen cada estado.
        validation_status = compute_validation_status(validation_report)

        status_container = st.container()
        with status_container:
            st.markdown(f"### Estado de validación: {validation_status['emoji']} {validation_status['etiqueta']}")
            if validation_status["codigo"] == "VALIDADA":
                st.success(validation_status["mensaje"])
            elif validation_status["codigo"] == "REVISAR":
                st.warning(validation_status["mensaje"])
            elif validation_status["codigo"] == "NO_VALIDADA":
                st.error(validation_status["mensaje"])
            else:
                st.info(validation_status["mensaje"])

        if not validation_report.get("disponible"):
            st.caption(
                "El Health Check de arriba indica cuál de las 5 fuentes "
                "(4 componentes + EXLIQ oficial) no respondió en esta carga."
            )
        else:
            first_date = validation_report["primera_fecha"]
            last_date = validation_report["ultima_fecha"]
            n_observations = validation_report["n_observaciones"]
            max_abs_diff = validation_report["max_diferencia_abs"]
            mean_abs_diff = validation_report["media_diferencia_abs"]
            mean_pct_diff = validation_report["media_diferencia_pct"]
            correlation = validation_report["correlacion"]

            st.write(
                f"**Ventana comparada:** {first_date.strftime('%Y-%m-%d')} a "
                f"{last_date.strftime('%Y-%m-%d')} — **{n_observations}** "
                "observaciones donde ambas series (reconstruida y oficial) "
                "tienen dato real ese mismo día."
            )

            metric_col1, metric_col2, metric_col3, metric_col4 = st.columns(4)
            with metric_col1:
                st.metric("Diferencia máxima", f"{max_abs_diff:,.0f} M€")
            with metric_col2:
                st.metric("Diferencia media", f"{mean_abs_diff:,.0f} M€")
            with metric_col3:
                st.metric(
                    "Diferencia % media",
                    f"{mean_pct_diff:.4f}%" if pd.notna(mean_pct_diff) else "N/D",
                )
            with metric_col4:
                st.metric(
                    "Correlación",
                    f"{correlation:.6f}" if correlation is not None else "N/D",
                )

            st.markdown("**Fechas con mayor discrepancia absoluta:**")
            worst_discrepancies = validation_report["peores_discrepancias"].copy()
            worst_discrepancies["Date"] = worst_discrepancies["Date"].dt.strftime("%Y-%m-%d")
            worst_discrepancies = worst_discrepancies.rename(
                columns={
                    "Date": "Fecha",
                    "EXLIQ_Oficial": "EXLIQ Oficial (M€)",
                    "LIQEUR_Reconstruida": "LIQEUR Reconstruida (M€)",
                    "Diferencia": "Diferencia (M€)",
                    "Diferencia_Pct": "Diferencia (%)",
                }
            )
            st.dataframe(worst_discrepancies, use_container_width=True, hide_index=True)

            with st.expander("VER GRÁFICO COMPARATIVO (EXLIQ oficial vs LIQEUR reconstruida)"):
                comparison_series = validation_report["serie_comparada"]
                comparison_figure = go.Figure()
                comparison_figure.add_trace(
                    go.Scatter(
                        x=comparison_series["Date"],
                        y=comparison_series["EXLIQ_Oficial"],
                        mode="lines",
                        name="EXLIQ Oficial",
                        line={"color": "#38BDF8", "width": 2},
                    )
                )
                comparison_figure.add_trace(
                    go.Scatter(
                        x=comparison_series["Date"],
                        y=comparison_series["LIQEUR_Reconstruida"],
                        mode="lines",
                        name="LIQEUR Reconstruida",
                        line={"color": "#F59E0B", "width": 2, "dash": "dot"},
                    )
                )
                comparison_figure.update_layout(
                    template="plotly_dark",
                    paper_bgcolor="#0E1117",
                    plot_bgcolor="#0E1117",
                    height=400,
                    showlegend=True,
                    legend={"orientation": "h", "yanchor": "top", "y": -0.15, "xanchor": "center", "x": 0.5},
                    margin={"l": 10, "r": 10, "t": 30, "b": 40},
                    hovermode="x unified",
                )
                comparison_figure.update_yaxes(title_text="Millones de EUR")
                st.plotly_chart(comparison_figure, use_container_width=True)

            st.caption(
                "Esta validación se recalcula automáticamente en cada "
                "carga (con caché de 30 min por fuente) - es una "
                "herramienta de control de calidad permanente, no una "
                "foto fija. La metodología ACTIVA de LIQGLOB sigue siendo "
                "la serie oficial EXLIQ; sustituirla seguirá siendo "
                "siempre una decisión manual y explícita."
            )

    except Exception as error:
        LOGGER.exception(
            "Error crítico en la pestaña LIQGLOB. Tipo: %s. Detalle: %s",
            type(error).__name__,
            error,
        )
        st.error(
            "Ocurrió un error crítico al ejecutar la pestaña LIQGLOB. "
            "Consulta la consola para ver el detalle técnico."
        )


def main() -> None:
    """
    Punto de entrada de la aplicación: organiza el Panel Principal, la
    pestaña de Liquidez Avanzada, la pestaña de Señales Macro Avanzadas y
    la nueva pestaña LIQGLOB como pestañas independientes del mismo
    programa (NUEVO: LIQUIDEZ AVANZADA / NUEVO: PANEL MACRO-BITCOIN
    AVANZADO / NUEVO: INDICADOR LIQGLOB).
    """
    tab_main, tab_advanced, tab_macro_signals, tab_liqglob = st.tabs(
        ["PANEL PRINCIPAL", "LIQUIDEZ AVANZADA", "SEÑALES MACRO AVANZADAS", "LIQGLOB"]
    )

    with tab_main:
        render_main_dashboard()

    with tab_advanced:
        render_advanced_liquidity_tab()

    with tab_macro_signals:
        render_macro_signals_tab()

    with tab_liqglob:
        render_liqglob_tab()


if __name__ == "__main__":
    main()