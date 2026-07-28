"""
Configuración centralizada de fuentes de datos macroeconómicos y de mercado.
"""

import os

# ACTUALIZACIÓN PARCHE: la API key ahora se lee primero desde la variable de
# entorno FRED_API_KEY. Si no existe, se usa el valor hardcodeado como
# respaldo para no romper la ejecución actual. Antes de compartir o subir
# este proyecto a un repositorio público, se recomienda eliminar el valor
# hardcodeado y definir la variable de entorno (o usar st.secrets en
# Streamlit Cloud).
FRED_API_KEY = os.environ.get("FRED_API_KEY", "421fb189b5e3c356d022deb289bef205")

# ACTUALIZACIÓN PARCHE: key opcional de CoinGecko Pro, necesaria únicamente
# para obtener la serie histórica real de dominancia de USDT (USDT.D).
# El endpoint gratuito de CoinGecko NO expone historial de market cap
# global, solo el valor actual. Sin esta key, USDT.D seguirá mostrando
# "N/D" de forma honesta, tal como ya lo hacía el programa.
COINGECKO_API_KEY = os.environ.get("COINGECKO_API_KEY", "")

FRED_API_BASE_URL = "https://api.stlouisfed.org/fred/series/observations"

# CORRECCIÓN DE ERROR (ronda de Liquidez Avanzada): "PECOASSMMCNBDC" no es un
# ID válido de FRED - por eso la consola mostraba "PECOASSMMCNBDC: ERROR -
# HTTP error", y por eso el checkbox de China nunca cambiaba el gráfico (el
# componente siempre valía 0). Se reemplaza por MYAGM2CNM189N (M2 de China,
# FMI/FRED), que sí es válido y coincide con la nueva fórmula del usuario
# ("Banco de China M2").
#
# LIMITACIÓN HONESTA QUE HAY QUE CONOCER: no existe ninguna serie gratuita y
# VIGENTE de M2 de China en FRED. MYAGM2CNM189N está descontinuada desde
# agosto de 2019 - justo antes del período que más interesa (ciclos post-2019
# de Bitcoin). Con esto el error HTTP desaparece y el checkbox sí afecta el
# gráfico para el tramo histórico disponible (hasta 2019), pero el componente
# no tendrá datos recientes hasta que se conecte una fuente de pago (Trading
# Economics, CEIC, Wind) o se cargue un CSV manual. No se inventan cifras
# para rellenar ese hueco.
FRED_SERIES = {
    "FED_BALANCE_SHEET": "WALCL",
    "TREASURY_GENERAL_ACCOUNT": "WTREGEN",
    "REVERSE_REPO": "RRPONTSYD",
    "ECB_BALANCE_SHEET": "ECBASSETSW",
    "PBOC_LIQUIDITY_OR_ASSETS": "MYAGM2CNM189N",  # CORRECCIÓN DE ERROR
    "JAPAN_BALANCE_SHEET": "JPNASSETS",  # ACTUALIZACIÓN PARCHE
    # NUEVO: LIQUIDEZ GLOBAL COMBINADA (Fed + BCE, RoC) - series verificadas
    # una por una en FRED antes de usarlas:
    # - WDTGAL: TGA semanal "as of Wednesday", vigente (confirmado con datos
    #   hasta 2026), en Millones de USD. Distinta de WTREGEN (que ya usa el
    #   resto del programa); se pidió específicamente para este índice.
    # - DEXUSEU: tipo de cambio USD por EUR, publicado por la propia FRED
    #   (no Yahoo), diario. "ECBASSETW" que se propuso NO existe en FRED - la
    #   serie real (y la que ya usa el resto del programa) es ECBASSETSW.
    "US_TREASURY_ACCOUNT_WDTGAL": "WDTGAL",
    "EUR_USD_FRED": "DEXUSEU",
    # NUEVO: PANEL MACRO-BITCOIN AVANZADO (US10Y, STLFSI4) - series FRED
    # verificadas: DGS10 (rendimiento diario del Tesoro a 10 años, % anual)
    # y STLFSI4 (Índice de Estrés Financiero de San Luis, actualización
    # semanal, se propaga con ffill como el resto de series FRED).
    "US_10Y_TREASURY": "DGS10",
    "FINANCIAL_STRESS_INDEX": "STLFSI4",
}

# ACTUALIZACIÓN PARCHE: se agrega el par JPY_USD para poder convertir
# JPNASSETS (yenes) a dólares.
YAHOO_TICKERS = {
    "EUR_USD": "EURUSD=X",
    "CNY_USD": "CNYUSD=X",
    "JPY_USD": "JPY=X",  # ACTUALIZACIÓN PARCHE - yenes por dólar (USD/JPY)
    "DOLLAR_INDEX": "DX-Y.NYB",
    "BITCOIN": "BTC-USD",
    "SOLANA": "SOL-USD",
    "TETHER": "USDT-USD",
}

YFINANCE_PERIOD = "3y"
YFINANCE_INTERVAL = "1d"

# ACTUALIZACIÓN PARCHE: configuración del Motor de Cálculo de Liquidez
# Compuesta (Requerimiento 1). Cada componente define:
#   - column: la columna en dólares/billones ya calculada por math_processor.
#   - sign: +1 si suma a la liquidez, -1 si resta (WALCL - TGA - RRP).
#   - default: si el checkbox nace activado o no.
# Todo es operable desde checkboxes en app.py; nada de esto está hardcodeado
# en la fórmula final, que se recalcula dinámicamente.
LIQUIDITY_BASE_COMPONENTS = {
    "WALCL": {
        "label": "WALCL (Balance Fed)",
        "column": "WALCL_USD_T",
        "sign": 1,
        "default": True,
    },
    "TGA": {
        "label": "TGA (Cuenta del Tesoro)",
        "column": "TGA_USD_T",
        "sign": -1,
        "default": True,
    },
    "RRP": {
        "label": "RRP (Reverse Repo)",
        "column": "RRP_USD_T",
        "sign": -1,
        "default": True,
    },
}

LIQUIDITY_REGION_COMPONENTS = {
    "EUROPA": {
        "label": "Europa (BCE)",
        "column": "ECBASSET_USD_T",
        "sign": 1,
        "default": True,
    },
    "CHINA": {
        "label": "China (M2, datos hasta 2019)",
        "column": "PBoC_Assets_USD_T",
        "sign": 1,
        "default": True,
    },
    "JAPON": {
        "label": "Japón (BoJ)",
        "column": "JPNASSETS_USD_T",
        "sign": 1,
        "default": False,  # apagado por defecto: serie mensual, más lenta
    },
}

# ACTUALIZACIÓN PARCHE: configuración del Sistema de Catalizadores y Retraso
# (Requerimiento 2). Estos valores son supuestos de trabajo razonables, no
# datos descargados de ninguna fuente: el usuario puede ajustarlos.
BASE_LAG_DAYS = 60  # retraso base histórico usado como referencia de partida

# Aceleradores: reducen el retraso neto (el efecto de liquidez llega más rápido).
LAG_ACCELERATORS = {
    "Reunión FOMC activa": -7,
    "Reporte CPI alto": -5,
    "Pico de volumen en Stablecoins": -4,
}

# Desaceleradores: aumentan el retraso neto (el efecto tarda más en sentirse).
LAG_DECELERATORS = {
    "Baja velocidad M2": 6,
    "Vacaciones bancarias / Crypto Winter": 10,
}

MIN_NET_LAG_DAYS = 0
MAX_NET_LAG_DAYS = 180

# NUEVO: LIQUIDEZ AVANZADA - conversión de unidades de RRP.
#
# CORRECCIÓN DE ERROR IMPORTANTE: RRPONTSYD se publica en FRED en "Billions
# of US Dollars" (miles de millones), mientras que WALCL y WTREGEN se
# publican en "Millions of U.S. Dollars" (millones). El motor original
# dividía las tres series por el mismo factor (1,000,000), lo cual dejaba a
# RRP subvalorado por un factor de 1000. Esta es la corrección que el
# usuario pidió como "RepoInverso * 1000": aquí se implementa como una
# conversión directa de billions -> trillions (dividir entre 1000), que es
# matemáticamente equivalente y más clara.
USD_BILLIONS_TO_TRILLIONS = 1_000.0

# NUEVO: LIQUIDEZ AVANZADA - endpoints de DefiLlama para stablecoins.
# Se usa stablecoins.llama.fi (dominio específico de stablecoins de
# DefiLlama, sin necesidad de API key). Los IDs de cada moneda (USDT, USDC,
# DAI, FDUSD) NO se hardcodean: se resuelven en tiempo real contra
# /stablecoins, porque adivinar esos IDs podría sumar la moneda equivocada.
DEFILLAMA_STABLECOINS_LIST_URL = "https://stablecoins.llama.fi/stablecoins"
DEFILLAMA_STABLECOIN_HISTORY_URL = "https://stablecoins.llama.fi/stablecoin"
STABLECOIN_SYMBOLS_TRACKED = ["USDT", "USDC", "DAI", "FDUSD"]

# NUEVO: LIQUIDEZ GLOBAL COMBINADA (reemplaza el enfoque anterior de
# Largo Plazo) - solo Fed + BCE, sin Japón/China (el usuario los quitó por
# dar señales incompatibles/raras al mezclarlos). Metodología de 5 pasos
# exacta pedida por el usuario:
#   1. Ingesta: WALCL, WDTGAL, RRPONTSYD, ECBASSETSW, DEXUSEU (solo FRED).
#   2. Alineación: calendario diario continuo + forward-fill (ya lo hace
#      math_processor.py de forma genérica para todas las columnas FRED).
#   3. Conversión: BCE en EUR * DEXUSEU = BCE en USD; Fed Neta =
#      WALCL - WDTGAL - RRP (RRP ya corregido de billones a millones).
#   4. Normalización: Rate of Change (RoC) porcentual en ventana móvil de
#      90 días - así ninguna economía "eclipsa" a la otra por tamaño
#      nominal, y no hay tendencia alcista infinita en el gráfico.
#   5. Re-agrupación semanal (cierre viernes) + SMA opcional de suavizado.
COMBINED_LIQUIDITY_ROC_WINDOW_DAYS = 90
COMBINED_LIQUIDITY_RESAMPLE_RULE = "W-FRI"  # cierre viernes
COMBINED_LIQUIDITY_DEFAULT_SMA_WEEKS = 4
COMBINED_LIQUIDITY_MIN_SMA_WEEKS = 2
COMBINED_LIQUIDITY_MAX_SMA_WEEKS = 12

# CORRECCIÓN INSTITUCIONAL (post-entrega): el RoC de 90 días, al aplicarse
# sobre una Liquidez Neta que puede pasar cerca de cero (Fed Neta + BCE),
# puede "explotar" a porcentajes absurdos (ej. -379%) cuando el
# denominador se acerca a cero - eso fue lo que se vio como "-3.79".
# La corrección: normalizar ese RoC con un Z-Score RODANTE (ventana móvil
# de 52 semanas, no histórico completo) - así el número queda expresado en
# desviaciones estándar recientes, no en un porcentaje que puede dispararse.
COMBINED_LIQUIDITY_ZSCORE_WINDOW_WEEKS = 52

# Billones (RRPONTSYD) -> Millones, para que quede en la misma escala que
# WALCL/WDTGAL (que sí vienen en millones). Ver nota de corrección de RRP
# más arriba: RRPONTSYD se publica en miles de millones, no en millones.
RRP_BILLIONS_TO_MILLIONS = 1_000.0

# "default" controla el estado inicial de cada checkbox en la pestaña.
# Los 4 siguen siendo togglables de forma independiente, tal como se pidió.
COMBINED_LIQUIDITY_COMPONENTS = {
    "WALCL": {"label": "Fed - WALCL", "sign": 1, "default": True},
    "TGA": {"label": "Fed - TGA (WDTGAL)", "sign": -1, "default": True},
    "RRP": {"label": "Fed - Reverse Repo", "sign": -1, "default": True},
    "ECB": {"label": "Europa (BCE, USD vía DEXUSEU)", "sign": 1, "default": True},
}

# NUEVO: LIQUIDEZ AVANZADA - ventana de normalización Z-Score.
# El Corto Plazo sigue trabajando en datos diarios (30 días calendario).
SHORT_TERM_ZSCORE_WINDOW_DAYS = 30

SHORT_TERM_LIQUIDITY_COMPONENTS = {
    "WALCL_FIJO": {"label": "Fed - WALCL (fijo al último miércoles)", "sign": 1},
    "TGA": {"label": "Fed - TGA diario", "column": "TGA_USD_T", "sign": -1},
    "RRP": {"label": "Fed - Reverse Repo diario", "column": "RRP_USD_T", "sign": -1},
    "STABLECOINS": {"label": "Capitalización de Stablecoins", "sign": 1},
}

# =====================================================================
# NUEVO: PANEL MACRO-BITCOIN AVANZADO (US10Y, STLFSI4, DXY, MVRV Z-Score)
# =====================================================================
# Este bloque NO modifica ni interfiere con la Liquidez Global Combinada
# (arriba). Es un panel aparte, con sus propias 4 filas sincronizadas en
# el eje X, agregado como una pestaña nueva e independiente.

# Cadencia semanal (mismo criterio que Liquidez Global Combinada: cierre
# de viernes, último valor real de la semana, nunca un promedio).
MACRO_PANEL_RESAMPLE_RULE = "W-FRI"

# Requerimiento 2 (US10Y): SMA de mediano/largo plazo sobre la serie ya
# semanal, para suavizar el ruido de los rendimientos diarios.
US10Y_SMA_DEFAULT_WEEKS = 20
US10Y_SMA_MIN_WEEKS = 4
US10Y_SMA_MAX_WEEKS = 52

# Requerimiento 3 (STLFSI4): umbrales de sombreado de fondo. > 0 significa
# condiciones financieras más estrictas que el promedio histórico; > 2 es
# la zona de pánico/crisis bancaria genuina (ej. SVB, marzo 2023).
STLFSI_STRESS_THRESHOLD = 0.0
STLFSI_PANIC_THRESHOLD = 2.0
STLFSI_SHADE_OPACITY_LOW = 0.08
STLFSI_SHADE_OPACITY_HIGH = 0.28
STLFSI_SHADE_COLOR_RGB = "220, 38, 38"  # rojo

# Requerimiento 4 (DXY): Rate of Change de 90 días, invertido (x -1) para
# que "dólar debilitándose" apunte en la misma dirección visual que
# "liquidez aumentando" (ambos favorecen a Bitcoin).
DXY_ROC_WINDOW_DAYS = 90

# Requerimiento 5 (MVRV Z-Score): endpoint público de BGeometrics
# (bitcoin-data.com) para métricas on-chain de Bitcoin.
#
# ACTUALIZACIÓN (Directriz 2 - Integración del Token de BGeometrics): el
# usuario ya cuenta con su propia API key. Se sigue leyendo primero desde
# la variable de entorno BGEOMETRICS_API_KEY (mismo criterio que
# FRED_API_KEY arriba); si no existe, se usa el valor entregado por el
# usuario como respaldo para que la app funcione sin configuración
# adicional. Antes de compartir o subir este proyecto a un repositorio
# público, se recomienda eliminar el valor hardcodeado y definir solo la
# variable de entorno.
MVRV_ZSCORE_API_URL = "https://bitcoin-data.com/v1/mvrv-zscore"
BGEOMETRICS_API_KEY = os.environ.get("BGEOMETRICS_API_KEY", "UUST4LgdZI")

# ACTUALIZACIÓN (Directriz 3 - Cache local del MVRV Z-Score): se guarda el
# último DataFrame exitoso en un CSV local, en una carpeta "cache" junto al
# resto del proyecto, para no agotar el límite de peticiones de la API key
# cada vez que el usuario mueve el gráfico o recarga la interfaz.
MVRV_CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")
MVRV_CACHE_FILE_PATH = os.path.join(MVRV_CACHE_DIR, "mvrv_zscore_cache.csv")
# Mientras el cache tenga menos de esta antigüedad (segundos), la app lo lee
# directo desde disco y NO dispara una petición HTTP nueva. Mismo criterio
# que el TTL de 30 min ya usado por @st.cache_data en app.py.
MVRV_CACHE_TTL_SECONDS = 1800

# Requerimiento 6 (Alerta de Compra Macro): umbrales de la señal compuesta.
#   a) Z-Score de Liquidez Global (Indice_Global_Final, ya calculado por
#      build_combined_global_liquidity_index) en su cuartil inferior.
#      Un Z-Score < -1.0 deja aproximadamente el 16% de las observaciones
#      más bajas bajo una distribución normal estándar - un proxy robusto
#      y ampliamente usado en la práctica institucional para "cuartil
#      inferior" cuando no se dispone de suficiente historia para
#      calcular percentiles empíricos exactos.
#   b) MVRV Z-Score < 0.1 (zona de capitulación histórica, umbral
#      estándar de la métrica original de Mahmudov/Puell).
LIQUIDITY_SIGNAL_ZSCORE_THRESHOLD = -1.0
MVRV_CAPITULATION_THRESHOLD = 0.1