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
#
# AUDITORÍA (Directriz 4 - Datos Obsoletos): por esta misma razón, el
# checkbox de China ahora nace APAGADO por defecto (ver
# LIQUIDITY_REGION_COMPONENTS más abajo) y la interfaz muestra una
# advertencia explícita junto al checkbox si el usuario decide activarlo.
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
    # AUDITORÍA (Directriz 1 - Eliminación de Yahoo Finance para FX): antes,
    # el tipo de cambio CNY/USD y JPY/USD se descargaba de Yahoo Finance
    # (CNYUSD=X, JPY=X), lo cual limitaba la profundidad histórica a
    # YFINANCE_PERIOD="3y" (ver más abajo). DEXCHUS y DEXJPUS son las series
    # oficiales de FRED para estos mismos tipos de cambio, con décadas de
    # historia real (igual que DEXUSEU ya usado para el euro), y permiten
    # calcular ciclos macroeconómicos completos (10+ años) sin depender de
    # Yahoo Finance para ningún tipo de cambio. Ambas son gratuitas.
    #   - DEXCHUS: Yuanes Chinos por 1 Dólar (unidad: CNY por USD, igual
    #     convención que JPY=X - se DIVIDE para convertir a USD).
    #   - DEXJPUS: Yenes Japoneses por 1 Dólar (unidad: JPY por USD, misma
    #     convención que antes con JPY=X - se DIVIDE para convertir a USD).
    "CHINA_USD_EXCHANGE": "DEXCHUS",
    "JAPAN_USD_EXCHANGE": "DEXJPUS",
    # NUEVO: PANEL MACRO-BITCOIN AVANZADO (US10Y, STLFSI4) - series FRED
    # verificadas: DGS10 (rendimiento diario del Tesoro a 10 años, % anual)
    # y STLFSI4 (Índice de Estrés Financiero de San Luis, actualización
    # semanal, se propaga con ffill como el resto de series FRED).
    "US_10Y_TREASURY": "DGS10",
    "FINANCIAL_STRESS_INDEX": "STLFSI4",
    # AUDITORÍA (Directriz 3 - Doble ingesta del Dólar): DTWEXBGS es el
    # "Trade Weighted U.S. Dollar Index: Broad, Goods and Services" de la
    # Reserva Federal (FRED, gratuito, historia diaria desde 2006 - 20+
    # años). NO es el mismo índice que DXY de Yahoo Finance (metodología y
    # canasta de monedas distintas: DXY pesa fuertemente el EUR y es de
    # ICE; DTWEXBGS es una canasta más amplia y diversificada calculada
    # por la Fed) - por eso conviven como DOS columnas independientes
    # (DXY y DXY_FRED en math_processor.py), ninguna reemplaza a la otra.
    # DXY (Yahoo) sirve para el corto plazo con el ticker de mercado que
    # el usuario ya conoce; DTWEXBGS aporta una historia mucho más larga
    # y gratuita para el análisis del dólar a 10+ años.
    "US_DOLLAR_INDEX_FRED": "DTWEXBGS",
}

# AUDITORÍA (Directriz 1 - Eliminación de Yahoo Finance para FX): ya NO se
# descargan EUR_USD, CNY_USD ni JPY_USD desde Yahoo Finance (antes
# "EURUSD=X", "CNYUSD=X", "JPY=X"). Los tres tipos de cambio ahora vienen
# exclusivamente de FRED (DEXUSEU, DEXCHUS, DEXJPUS en FRED_SERIES, arriba),
# lo que elimina el límite fijo de 3 años de Yahoo Finance para estas series.
# Yahoo Finance se conserva únicamente para lo que no existe en FRED de
# forma gratuita (con la misma metodología exacta): el índice DXY y los
# precios de mercado de BTC/SOL/USDT.
YAHOO_TICKERS = {
    "DOLLAR_INDEX": "DX-Y.NYB",
    "BITCOIN": "BTC-USD",
    "SOLANA": "SOL-USD",
    "TETHER": "USDT-USD",
}

# CORRECCIÓN DE ERROR (recorte visual del gráfico al año ~2023 - Directriz
# 1): antes YFINANCE_PERIOD="3y" limitaba BTC-USD, SOL-USD, USDT-USD y DXY
# a solo los últimos 3 años de historia. Como _outer_merge_and_align (en
# math_processor.py) definía el calendario maestro únicamente a partir de
# las fechas con BTC_Close válido, ese límite de 3 años en Yahoo Finance
# terminaba recortando TODO el gráfico - incluida la Liquidez de la Fed,
# que en realidad tiene décadas de historia en FRED - a la misma ventana
# corta de Bitcoin. Con period="max", yfinance descarga toda la historia
# real disponible de cada ticker (BTC-USD y SOL-USD desde su primer día
# de cotización; DXY desde el inicio de su serie en Yahoo Finance), sin
# inventar ni un solo dato.
YFINANCE_PERIOD = "max"
YFINANCE_INTERVAL = "1d"

# AUDITORÍA (Directriz 3 - Point-in-Time Mapping / Publication Lag): WALCL y
# WDTGAL son series semanales "as of Wednesday" - el valor "del miércoles"
# no se publica ni se conoce realmente ese mismo día, sino con retraso
# (típicamente el jueves por la tarde, hora de EE.UU.). Antes de reindexar
# estas series a un calendario diario continuo (ver
# math_processor._prepare_fred_series), sus fechas se desplazan
# PUBLICATION_LAG_DAYS días hacia adelante, de modo que el ffill posterior
# no le atribuya al miércoles un dato que en la realidad todavía no existía
# ese día (corrección de Look-Ahead Bias). El resto de las series FRED
# (ECBASSETSW, DGS10, STLFSI4, DEXUSEU, DEXCHUS, DEXJPUS, etc.) no se
# desplaza: no se documentó un rezago de publicación equivalente para ellas
# y desplazarlas sin evidencia sería introducir un supuesto no verificado.
PUBLICATION_LAG_DAYS = 1
PUBLICATION_LAG_COLUMNS = {"WALCL", "WDTGAL"}

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

# AUDITORÍA (Directriz 4 - Datos Obsoletos): el checkbox de China nace
# APAGADO por defecto ("default": False) porque MYAGM2CNM189N (su única
# fuente gratuita en FRED) está descontinuada desde agosto de 2019 - ver
# nota completa junto a FRED_SERIES arriba. CHINA_DATA_DEPRECATED_WARNING,
# más abajo, es el texto que app.py muestra junto al checkbox si el usuario
# decide activarlo de todos modos.
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
        "default": False,  # AUDITORÍA: apagado por defecto - serie descontinuada
    },
    "JAPON": {
        "label": "Japón (BoJ)",
        "column": "JPNASSETS_USD_T",
        "sign": 1,
        "default": False,  # apagado por defecto: serie mensual, más lenta
    },
}

# AUDITORÍA (Directriz 4 - Datos Obsoletos): mensaje de advertencia mostrado
# en app.py junto al checkbox de China, para que el usuario entienda que
# activarlo introduce un componente "congelado" desde 2019 (no una serie
# viva) y puede sesgar la Liquidez Global de forma silenciosa si no se lee
# esta nota.
CHINA_DATA_DEPRECATED_WARNING = (
    "⚠️ MYAGM2CNM189N (M2 de China) está descontinuada en FRED desde "
    "agosto de 2019. Si activas este componente, sumará un valor "
    "estancado desde esa fecha en todo el tramo posterior (no una serie "
    "en vivo) y puede sesgar la Liquidez Global."
)

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

# =====================================================================
# NUEVO: INDICADOR LIQGLOB (LIQUIDEZ GLOBAL: ESTADOS UNIDOS + EUROZONA)
# =====================================================================
# CANDADO: esta sección es 100% aditiva. Vive en su propia pestaña
# (la 4ta), con su propio módulo de cálculo (liqglob.py) y sus propios
# checkboxes. NO modifica COMBINED_LIQUIDITY_COMPONENTS ni la Liquidez
# Global Combinada (RoC + Z-Score) de la pestaña "Liquidez Avanzada" -
# esa sigue intacta y se sigue calculando exactamente igual que antes.
#
# Diferencia clave con la Liquidez Global Combinada existente: LIQGLOB es
# una suma DIRECTA en miles de millones de dólares (billions), SIN
# normalizar (sin RoC ni Z-Score) - pensada para comparar la escala
# nominal real de la liquidez conjunta contra BTC/SOL, tal como se pidió.
#
# Fórmulas (automáticas, sin ningún dato introducido a mano):
#   LIQEEUU = WALCL - TGA (WDTGAL) - RRP (RRPONTSYD)   [FRED, ya en el
#             DataFrame Maestro de math_processor.py - no se vuelve a
#             descargar nada de FRED para esto]
#   LIQEUR  = (ILM.D.U2.C.EXLIQ.U2.EUR / 1000) x EURUSD (DEXUSEU, FRED)
#   LIQGLOB = LIQEEUU + LIQEUR

# Fuente oficial del BCE (ECB Data Portal / SDW API), serie diaria de
# Liquidez Excedentaria: ILM.D.U2.C.EXLIQ.U2.EUR. "ILM" es el flujo
# (dataflow); el resto es la clave de la serie dentro de ese flujo. Esta
# serie NO es ECBASSETSW (la que ya usa la Liquidez Global Combinada) -
# es una serie distinta, pedida explícitamente por el usuario para este
# nuevo indicador.
ECB_SDW_BASE_URL = "https://data-api.ecb.europa.eu/service/data"
ECB_LIQUIDITY_FLOW_REF = "ILM"
ECB_LIQUIDITY_SERIES_KEY = "D.U2.C.EXLIQ.U2.EUR"

# =====================================================================
# NUEVO: VALIDACIÓN EXPERIMENTAL DE LIQEUR (reconstrucción por componentes)
# =====================================================================
# CANDADO: esta sección es 100% aditiva y EXPERIMENTAL. Los códigos de
# abajo alimentan liqeur_validation.py, un módulo aparte que NO participa
# en el cálculo de LIQGLOB_USD_B ni en el gráfico principal de la pestaña
# LIQGLOB - su único propósito es comparar, día a día, una reconstrucción
# de la Liquidez Excedentaria hecha a partir de sus 4 componentes
# oficiales contra la serie consolidada ILM.D.U2.C.EXLIQ.U2.EUR, para
# decidir en un paso POSTERIOR y manual si se sustituye la metodología
# actual (que sigue usando EXLIQ directamente, sin cambios).
#
# Los 4 códigos siguientes viven en el MISMO dataflow "ILM" que EXLIQ
# (ECB_LIQUIDITY_FLOW_REF de arriba, ya definido) - verificados uno por
# uno contra el ECB Data Portal antes de usarlos:
#   - D.U2.C.L020100.U2.EUR: "Current accounts (covering the minimum
#     reserves system)".
#   - D.U2.C.MRR.U2.EUR: "Minimum reserve requirements".
#   - D.U2.C.L020200.U2.EUR: "Deposit facility".
#   - D.U2.C.A050500.U2.EUR: "Marginal lending facility".
#
# Fórmula oficial del BCE (confirmada textualmente en múltiples ediciones
# del ECB Economic Bulletin, 2023-2026):
#   Excess Liquidity = (Current Accounts - Minimum Reserve Requirements)
#                       + Deposit Facility - Marginal Lending Facility
ECB_CURRENT_ACCOUNTS_SERIES_KEY = "D.U2.C.L020100.U2.EUR"
ECB_MIN_RESERVE_REQUIREMENTS_SERIES_KEY = "D.U2.C.MRR.U2.EUR"
ECB_DEPOSIT_FACILITY_SERIES_KEY = "D.U2.C.L020200.U2.EUR"
ECB_MARGINAL_LENDING_FACILITY_SERIES_KEY = "D.U2.C.A050500.U2.EUR"

# Cantidad de fechas (las de mayor discrepancia absoluta) que se muestran
# en la tabla de "peores discrepancias" del panel de validación.
LIQEUR_VALIDATION_TOP_N_DISCREPANCIES = 15

# =====================================================================
# RECONSTRUCCIÓN HISTÓRICA DE MRR (BSI + Calendario oficial de
# Maintenance Periods del BCE, 2004+)
# =====================================================================
# CANDADO: esta sección alimenta un módulo 100% aislado
# (mp_calendar.py + mrr_historical_reconstruction.py). Ningún fallo aquí
# puede afectar LIQEEUU, la alineación semanal, ni la Validación
# Metodológica - ver docstrings de esos módulos para el detalle completo
# de la arquitectura de aislamiento y fallback.
#
# MRR es el ÚNICO de los 4 componentes de LIQEUR cuya versión diaria
# (ILM.D.U2.C.MRR.U2.EUR) solo tiene historial desde 2024-09-27 (los
# otros 3 - Current Accounts, Deposit Facility, Marginal Lending
# Facility - ya tienen historial completo desde 1998-12-31, confirmado
# en el propio Health Check del programa). Este módulo reconstruye MRR
# hacia atrás, desde 2004 en adelante, usando:
#   1. La serie mensual oficial BSI.M.U2.N.R.MRR.X.1.A1.3000.Z01.E
#      ("Minimum reserve requirements", BSI, agregado eurozona).
#   2. El calendario oficial de Maintenance Periods del BCE, para saber
#      a qué período pertenece cada observación mensual de BSI, y
#      propagar ese valor exclusivamente dentro de los días reales de
#      ese Maintenance Period (nunca por mes calendario aproximado).

# --- Fuente BSI (dataset distinto de ILM, mismo API/endpoint del BCE) ---
ECB_BSI_FLOW_REF = "BSI"
ECB_BSI_MRR_SERIES_KEY = "M.U2.N.R.MRR.X.1.A1.3000.Z01.E"

# --- Calendario oficial de Maintenance Periods ---
# Página índice oficial y estable del BCE que enlaza, año por año, a los
# comunicados/PDF con los calendarios de maintenance periods. Verificada
# en vivo durante el diseño de esta arquitectura (cobertura real: 2004 en
# adelante). NO es una API SDMX - es HTML/PDF oficial, por eso este
# módulo trata cualquier resultado como "no confiable hasta que pase
# validación estructural", nunca como una fuente de la misma categoría
# que las series SDMX del resto del programa.
ECB_MP_CALENDAR_INDEX_URL = "https://www.ecb.europa.eu/press/calendars/caleu/html/index.en.html"

# Primer año con cobertura automática fiable (antes de 2004 cambia la
# propia definición operativa del Maintenance Period - fuera de alcance
# por decisión explícita, ver informe de investigación previo).
ECB_MP_CALENDAR_FIRST_YEAR = 2004

# Archivo semilla: calendario ya validado y verificado manualmente
# durante esta investigación (empaquetado con el propio código - sigue
# funcionando aunque el sitio del BCE cambie de formato en el futuro).
# Archivo de caché: años adicionales agregados en tiempo de ejecución.
# Archivo de exportación: copia permanente de todo lo ya validado (ver
# Requisito 4 del usuario) - mismo formato que la caché, pensado para
# poder versionarse/respaldarse fuera del programa.
ECB_MP_CALENDAR_SEED_FILE = "data/ecb_mp_calendar_seed.json"
ECB_MP_CALENDAR_CACHE_FILE = "data/ecb_mp_calendar_cache.json"
ECB_MP_CALENDAR_EXPORT_FILE = "data/ecb_mp_calendar_validated_export.json"

# --- Umbrales de validación estructural (obligatoria, ver Requisito 3) ---
# Rango de duración plausible de un Maintenance Period, con margen sobre
# los valores reales observados (28-56 días) durante la investigación.
ECB_MP_MIN_DAYS = 20
ECB_MP_MAX_DAYS = 60
# Cantidad de períodos por año calendario, según la cadencia real
# ligada a las reuniones del Consejo de Gobierno (~8 desde 2015, hasta
# 13 en años con calendario distinto) - con margen.
ECB_MP_MIN_PERIODS_PER_YEAR = 7
ECB_MP_MAX_PERIODS_PER_YEAR = 13

# --- Referencia dorada (autoverificación, ver Requisito 3 / diseño previo) ---
# Calendario de 2014 COMPLETO, extraído y verificado dato-por-dato contra
# el comunicado oficial del BCE (pr130610) durante esta investigación -
# nunca aproximado ni completado por inferencia. Se usa exclusivamente
# para detectar si el scraper dejó de funcionar correctamente (si un
# nuevo scraping de 2014 alguna vez no coincide con esto, es una señal
# inequívoca de que cambió el formato del sitio del BCE, no que "2014
# cambió" - es un hecho histórico inmutable).
ECB_MP_GOLDEN_REFERENCE_YEAR = 2014
ECB_MP_GOLDEN_REFERENCE_CALENDAR = [
    {"mp": 1, "gc_meeting": "2014-01-09", "start": "2014-01-15", "end": "2014-02-11"},
    {"mp": 2, "gc_meeting": "2014-02-06", "start": "2014-02-12", "end": "2014-03-11"},
    {"mp": 3, "gc_meeting": "2014-03-06", "start": "2014-03-12", "end": "2014-04-08"},
    {"mp": 4, "gc_meeting": "2014-04-03", "start": "2014-04-09", "end": "2014-05-13"},
    {"mp": 5, "gc_meeting": "2014-05-08", "start": "2014-05-14", "end": "2014-06-10"},
    {"mp": 6, "gc_meeting": "2014-06-05", "start": "2014-06-11", "end": "2014-07-08"},
    {"mp": 7, "gc_meeting": "2014-07-03", "start": "2014-07-09", "end": "2014-08-12"},
    {"mp": 8, "gc_meeting": "2014-08-07", "start": "2014-08-13", "end": "2014-09-09"},
    {"mp": 9, "gc_meeting": "2014-09-04", "start": "2014-09-10", "end": "2014-10-07"},
    {"mp": 10, "gc_meeting": "2014-10-02", "start": "2014-10-08", "end": "2014-11-11"},
    {"mp": 11, "gc_meeting": "2014-11-06", "start": "2014-11-12", "end": "2014-12-09"},
    {"mp": 12, "gc_meeting": "2014-12-04", "start": "2014-12-10", "end": "2015-01-13"},
]

# =====================================================================
# UMBRALES DEL ESTADO AUTOMÁTICO DE LA VALIDACIÓN METODOLÓGICA DE LIQEUR
# =====================================================================
# Estos umbrales determinan el semáforo automático (🟢 VALIDADA /
# 🟡 REVISAR / 🔴 NO VALIDADA) que se muestra en la sección permanente de
# "Validación Metodológica de LIQEUR" (ver liqeur_validation.py). Son
# deliberadamente conservadores: en observaciones normales, la
# reconstrucción por componentes y la serie oficial EXLIQ deberían
# coincidir casi exactamente (misma fórmula oficial del BCE aplicada a
# los mismos datos oficiales), así que una diferencia porcentual media
# por encima de estos umbrales es una señal genuina de que algo cambió
# (metodología del BCE, calidad del dato, etc.) y merece revisión humana
# antes de tomar cualquier decisión sobre la metodología activa.
#
# Se evalúan dos condiciones en conjunto (correlación Y diferencia
# porcentual media) porque una sola métrica puede ser engañosa por sí
# sola: una correlación alta con un sesgo sistemático constante seguiría
# pareciendo "casi perfecta" en correlación, pero fallaría el umbral de
# diferencia porcentual, y viceversa.
LIQEUR_VALIDATION_STATUS_THRESHOLDS = {
    # 🟢 VALIDADA: correlación >= 0.999 Y diferencia % media <= 1.0%
    "correlacion_validada": 0.999,
    "diferencia_pct_validada": 1.0,
    # 🟡 REVISAR: correlación >= 0.99 Y diferencia % media <= 5.0%
    # (no cumple el umbral de VALIDADA, pero tampoco es un fallo claro)
    "correlacion_revisar": 0.99,
    "diferencia_pct_revisar": 5.0,
    # Por debajo de "revisar" en cualquiera de las dos métricas -> 🔴 NO VALIDADA
}

# La serie del BCE viene en MILLONES de euros; se divide entre 1000 para
# dejarla en miles de millones (billions) de euros, antes de convertirse
# a dólares con el tipo de cambio EUR/USD (DEXUSEU, FRED).
ECB_EUR_MILLIONS_TO_BILLIONS = 1_000.0

# WALCL y WDTGAL (TGA) llegan de FRED en MILLONES de USD; se dividen entre
# 1000 para quedar en miles de millones (billions) - misma unidad final
# que RRP (RRPONTSYD ya viene nativamente en billions en FRED, ver nota
# histórica junto a RRP_BILLIONS_TO_MILLIONS más arriba - aquí NO se le
# aplica ninguna conversión adicional).
US_MILLIONS_TO_BILLIONS = 1_000.0

# =====================================================================
# MIGRACIÓN DE METODOLOGÍA DE LIQEUR (de EXLIQ consolidada a los 4
# componentes oficiales del BCE)
# =====================================================================
# Tras la validación metodológica (ver liqeur_validation.py: correlación
# prácticamente perfecta, diferencia porcentual media prácticamente nula
# entre la reconstrucción por componentes y la serie oficial EXLIQ en su
# ventana de coexistencia), LIQEUR pasa a construirse por defecto a
# partir de sus 4 componentes oficiales, en vez de depender de la serie
# consolidada ILM.D.U2.C.EXLIQ.U2.EUR (que según lo investigado solo
# tiene historial retroactivo limitado, aprox. desde septiembre de 2024).
#
# REVERSIBILIDAD: este único flag controla qué metodología usa
# build_liqglob_index() (liqglob.py) para calcular LIQEUR_USD_B. Revertir
# a la metodología anterior NO requiere tocar ningún archivo de código -
# basta con cambiar el valor de esta constante a "EXLIQ". Ambas rutas de
# cálculo (_compute_liqeur_weekly_from_components y
# _compute_liqeur_weekly_from_exliq_legacy, en liqglob.py) se conservan
# completas e intactas en el código - la migración NO elimina la lógica
# anterior, solo deja de ser la que se usa por defecto.
#
#   "COMPONENTS" (nueva, activa por defecto desde esta migración):
#       LIQEUR = (Current Accounts - Minimum Reserve Requirements)
#                + Deposit Facility - Marginal Lending Facility
#       Historial: el que permitan los 4 componentes oficiales del BCE
#       (más profundo que EXLIQ, según lo investigado).
#
#   "EXLIQ" (legado, conservada por si hace falta revertir):
#       LIQEUR = ILM.D.U2.C.EXLIQ.U2.EUR directamente.
#       Historial: limitado al de esa serie consolidada.
#
# En AMBOS casos, ILM.D.U2.C.EXLIQ.U2.EUR se sigue descargando y se sigue
# usando en la sección "VALIDACIÓN METODOLÓGICA DE LIQEUR" como serie de
# referencia - eso no cambia con este flag.
LIQEUR_METHODOLOGY = "COMPONENTS"  # "COMPONENTS" (activa) | "EXLIQ" (legado)

# =====================================================================
# CORRECCIÓN DE ERROR (salto de liquidez en fin de trimestre, ej. fin de
# septiembre / inicio de octubre): la versión anterior re-agrupaba con
# `.resample("W-FRI").last()`, tomando el valor del VIERNES de cada
# semana para TODAS las series. WALCL y TGA (WDTGAL) solo se actualizan
# los MIÉRCOLES (y quedan fijos el resto de la semana vía forward-fill),
# pero RRP (RRPONTSYD) y el tipo de cambio EUR/USD cotizan TODOS los días
# hábiles - en fechas de fin de trimestre, RRP puede tener movimientos
# muy grandes de un día para otro (efecto bien documentado de "window
# dressing" de fondos del mercado monetario). El resultado: el viernes
# terminaba combinando el WALCL/TGA "congelado" del miércoles con un RRP
# de un día distinto (a veces varios días después), mezclando información
# de dos momentos distintos del mercado dentro de la misma observación -
# eso es lo que producía el salto visual reportado.
#
# CAMBIO SIGNIFICATIVO (alineación temporal por semana económica): ahora
# cada observación de LIQGLOB usa el MIÉRCOLES como día de referencia
# único para TODAS las series de esa semana:
#   - Series de frecuencia SEMANAL (WALCL, WDTGAL): se usa la observación
#     oficial de esa semana (ya llegan una sola vez por semana).
#   - Series de frecuencia DIARIA (RRP, EUR/USD, BCE): se usa el dato
#     REAL publicado el miércoles de esa semana; si no existe (feriado o
#     ausencia de publicación), se busca el día hábil inmediatamente
#     anterior DENTRO DE LA MISMA SEMANA (martes, luego lunes). Si
#     ninguno de los tres existe, esa semana NO se construye (queda como
#     NaN y no se dibuja) - nunca se usa un dato de una semana distinta.
# Ver liqglob.py (_select_weekly_value_with_fallback) para la
# implementación exacta de esta búsqueda.
WEEKLY_REFERENCE_WEEKDAY = 2  # 0=lunes, 1=martes, 2=miércoles (pandas .dt.weekday)
WEEKLY_FALLBACK_WEEKDAYS_PRIORITY = [2, 1, 0]  # miércoles -> martes -> lunes, misma semana

# Frecuencia semanal usada para extender el eje X al aplicar desfase
# (mismo mecanismo anti-recorte que el resto del programa, ver
# app._extend_dataframe_for_offset) - anclada al miércoles, consistente
# con WEEKLY_REFERENCE_WEEKDAY de arriba.
LIQGLOB_RESAMPLE_RULE = "W-WED"

# Ventana histórica objetivo (~600 semanas ~ 11.5 años). No es un recorte
# de la descarga (siempre se pide el historial completo a cada fuente,
# FRED y BCE); es solo el tramo final que se conserva en el resultado ya
# semanal, antes de graficarse.
LIQGLOB_HISTORY_WEEKS = 600

# Regiones activables de forma independiente vía checkbox, cada una con
# su propia fórmula completa (no hay "sign" por componente, como en
# COMBINED_LIQUIDITY_COMPONENTS - aquí cada región es una fórmula
# separada que participa entera o no participa en absoluto).
# ESCALABILIDAD: agregar una región futura (Japón, China, Reino Unido,
# Suiza, etc.) solo requiere una nueva entrada aquí + su propia serie
# calculada en liqglob.py (agregada al diccionario `region_series` de
# build_liqglob_index) - no hace falta rediseñar la suma final ni la
# alineación semanal, que ya son genéricas por región.
LIQGLOB_REGIONS = {
    "US": {
        "label": "Estados Unidos (LIQEEUU = WALCL - TGA - RRP)",
        "column": "LIQEEUU_USD_B",
        "default": True,
    },
    "EUROZONE": {
        "label": "Eurozona (LIQEUR = BCE Liquidez Excedentaria x EUR/USD)",
        "column": "LIQEUR_USD_B",
        "default": True,
    },

}

# NOTA OPERATIVA (Momento de ejecución): esta app recalcula LIQGLOB en
# cada carga/actualización de caché (no requiere un cron externo). Abrir
# el programa un viernes despues de las 7:00 AM hora de Nueva York es el
# momento en que, típicamente, los datos oficiales de la semana de
# referencia (miércoles) ya están publicados por la Fed y el BCE - pero
# la HORA en que se abre el programa nunca cambia la FECHA ECONÓMICA de
# cada observación (siempre el miércoles de su semana, ver
# WEEKLY_REFERENCE_WEEKDAY arriba): si se abre antes de que el dato esté
# disponible, esa semana simplemente no se dibuja todavía (ver Integridad
# Semanal en liqglob.py), nunca se muestra con datos incompletos.