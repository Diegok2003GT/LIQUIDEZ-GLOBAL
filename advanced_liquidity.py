"""
Índices de Liquidez Avanzada: Liquidez Global Combinada (Fed + BCE, vía
Rate of Change) y Corto Plazo (Índice de Liquidez Inmediata de Mercado).

Este módulo NO vuelve a descargar nada por su cuenta: recibe el DataFrame
Maestro ya construido por math_processor.py (con todas las columnas *_USD_T
ya convertidas a la misma unidad y con el bug de escala de RRP corregido) y
el historial de stablecoins de data_ingestion.py, y sobre eso arma las
canastas y las normaliza.

Filosofía: normalización matemática pura. No se recorta (clip), no se
suaviza de más, no se rellena con inventos - donde falta un componente,
simplemente no participa en la suma (igual que el motor de liquidez base),
y donde la ventana de cálculo todavía no tiene suficiente historia, el
resultado es NaN en vez de un número inventado.
"""

import logging
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from config import (
    COMBINED_LIQUIDITY_COMPONENTS,
    COMBINED_LIQUIDITY_MAX_SMA_WEEKS,
    COMBINED_LIQUIDITY_MIN_SMA_WEEKS,
    COMBINED_LIQUIDITY_RESAMPLE_RULE,
    COMBINED_LIQUIDITY_ROC_WINDOW_DAYS,
    COMBINED_LIQUIDITY_ZSCORE_WINDOW_WEEKS,  # CORRECCIÓN INSTITUCIONAL
    DXY_ROC_WINDOW_DAYS,  # NUEVO: PANEL MACRO-BITCOIN AVANZADO
    LIQUIDITY_SIGNAL_ZSCORE_THRESHOLD,  # NUEVO: PANEL MACRO-BITCOIN AVANZADO
    MACRO_PANEL_RESAMPLE_RULE,  # NUEVO: PANEL MACRO-BITCOIN AVANZADO
    MVRV_CAPITULATION_THRESHOLD,  # NUEVO: PANEL MACRO-BITCOIN AVANZADO
    RRP_BILLIONS_TO_MILLIONS,
    SHORT_TERM_LIQUIDITY_COMPONENTS,
    SHORT_TERM_ZSCORE_WINDOW_DAYS,
    US10Y_SMA_MAX_WEEKS,  # NUEVO: PANEL MACRO-BITCOIN AVANZADO
    US10Y_SMA_MIN_WEEKS,  # NUEVO: PANEL MACRO-BITCOIN AVANZADO
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

LOGGER = logging.getLogger(__name__)

STABLECOIN_TRILLIONS_DIVISOR = 1_000_000_000_000.0  # USD -> billones (trillions)


def calculate_zscore(
    series: pd.Series,
    window_days: int,
    min_periods_ratio: float = 0.5,
) -> pd.Series:
    """
    Calcula el Z-Score de una serie usando una media móvil y desviación
    estándar de ventana `window_days`.

    No se recorta (clip) el resultado a ningún rango: si un valor real da
    Z=+7 porque el evento fue genuinamente extremo, se muestra tal cual.
    Recortarlo sería "maquillar" el dato, justo lo que se pidió evitar.

    Parameters
    ----------
    series : pd.Series
        Serie cruda (ya en la misma unidad para todos sus componentes).
    window_days : int
        Tamaño de la ventana en días calendario (ej. 700 para 100 semanas).
    min_periods_ratio : float
        Fracción mínima de la ventana que debe tener datos válidos antes de
        calcular un Z-Score. Con menos historia que eso, el resultado es
        NaN (no se inventa una media/desviación con pocos datos).

    Returns
    -------
    pd.Series
        Serie de Z-Scores (misma longitud que `series`, con NaN al inicio).
    """
    try:
        numeric_series = pd.to_numeric(series, errors="coerce")
        min_periods = max(2, int(window_days * min_periods_ratio))

        rolling_mean = numeric_series.rolling(
            window=window_days, min_periods=min_periods
        ).mean()
        rolling_std = numeric_series.rolling(
            window=window_days, min_periods=min_periods
        ).std()

        with np.errstate(divide="ignore", invalid="ignore"):
            zscore = (numeric_series - rolling_mean) / rolling_std

        # Si la desviación estándar es 0 (serie perfectamente plana en la
        # ventana), el Z-Score matemáticamente no está definido - se deja
        # como NaN en vez de un infinito o un cero falso.
        zscore = zscore.replace([np.inf, -np.inf], np.nan)

        return zscore

    except Exception as error:
        LOGGER.exception(
            "Error al calcular Z-Score. Tipo: %s. Detalle: %s",
            type(error).__name__,
            error,
        )
        return pd.Series(np.nan, index=series.index)


def _sum_components(
    dataframe: pd.DataFrame,
    components: Dict[str, Dict],
    overrides: Optional[Dict[str, pd.Series]] = None,
) -> pd.Series:
    """
    Suma (con signo) las columnas de una canasta de componentes, igual de
    explícito que el motor de liquidez base (config.LIQUIDITY_BASE_COMPONENTS).

    Parameters
    ----------
    dataframe : pd.DataFrame
        DataFrame que contiene las columnas referenciadas en `components`.
    components : Dict[str, Dict]
        Ej. SHORT_TERM_LIQUIDITY_COMPONENTS (el índice combinado Fed+BCE
        usa su propia lógica de suma directa, ver build_combined_global_liquidity_index).
        Cada entrada trae "column" (opcional, si viene de `overrides`) y "sign".
    overrides : Optional[Dict[str, pd.Series]]
        Series ya calculadas fuera del DataFrame (ej. WALCL fijo, o la
        capitalización de stablecoins ya en trillones), indexadas por la
        misma clave que en `components`.

    Returns
    -------
    pd.Series
        Suma con signo de los componentes disponibles.
    """
    overrides = overrides or {}
    total = pd.Series(0.0, index=dataframe.index)

    for component_key, component_config in components.items():
        sign = component_config.get("sign", 1)

        if component_key in overrides:
            values = pd.to_numeric(overrides[component_key], errors="coerce").fillna(0.0)
        else:
            column_name = component_config.get("column")
            if column_name is None or column_name not in dataframe.columns:
                LOGGER.warning(
                    "Componente %s omitido: columna %s no disponible.",
                    component_key,
                    column_name,
                )
                continue
            values = pd.to_numeric(dataframe[column_name], errors="coerce").fillna(0.0)

        total = total + (sign * values)

    return total


def build_combined_global_liquidity_index(
    master_dataframe: pd.DataFrame,
    component_toggles: Optional[Dict[str, bool]] = None,
    apply_sma: bool = False,
    sma_window_weeks: int = 4,
) -> pd.DataFrame:
    """
    NUEVO: Índice de Liquidez Global Combinada (Fed + BCE), reemplaza el
    enfoque anterior de Largo Plazo (Z-Score multi-región con Japón/China).
    Metodología exacta de 5 pasos:

    Paso 1 (ingesta): usa las columnas ya descargadas de FRED por
    math_processor.py: WALCL, WDTGAL, RRP (RRPONTSYD), ECBASSET
    (ECBASSETSW), DEXUSEU_FRED. Ninguna viene de Yahoo Finance para este
    cálculo, tal como se pidió ("exclusivamente FRED").

    Paso 2 (alineación): ya resuelto de forma genérica por
    math_processor.py - todas las columnas FRED se reindexan a calendario
    diario continuo y se propagan hacia adelante (forward-fill) antes de
    llegar aquí.

    Paso 3 (conversión y escala):
        BCE_USD = ECBASSET (millones EUR) * DEXUSEU_FRED (USD por EUR)
        Fed_Neta = WALCL - WDTGAL - RRP_en_millones
    donde RRP_en_millones corrige que RRPONTSYD viene en miles de millones,
    no en millones (ver RRP_BILLIONS_TO_MILLIONS en config.py).

    Paso 4 (normalización - RoC): Rate of Change porcentual sobre una
    ventana móvil de 90 días de la liquidez combinada nominal. Esto evita
    que el tamaño de la Fed eclipse al BCE, y evita una tendencia alcista
    infinita en el gráfico (a diferencia de una suma nominal directa).

    Paso 5 (re-agrupación semanal): el RoC diario se re-muestrea a cierre
    de viernes (W-FRI) con `.last()` (el valor real de cierre, nunca un
    promedio) para quedar en cadencia semanal.

    CORRECCIÓN INSTITUCIONAL (post-entrega): el RoC de 90 días puede
    "explotar" a porcentajes absurdos cuando la Liquidez_Combinada_Nominal
    pasa cerca de cero (el denominador de pct_change se acerca a 0). Por
    eso se agrega un paso adicional, en este orden exacto:

        suma de componentes -> RoC (90 días) -> Z-Score RODANTE (52 semanas)

    El Z-Score usa `calculate_zscore()`, que YA es rodante por
    construcción (media y desviación estándar con `.rolling()`, nunca
    `.mean()`/`.std()` globales/histórico completo) - expresa el RoC en
    desviaciones estándar recientes en vez de un porcentaje que puede
    dispararse. Si `apply_sma` es True, la Media Móvil Simple de
    `sma_window_weeks` semanas se aplica DESPUÉS del Z-Score (suavizado
    visual final, no reemplaza ningún cálculo anterior - todas las
    columnas intermedias se devuelven).

    Cada uno de los 4 componentes (WALCL, TGA, RRP, ECB) es togglable de
    forma independiente vía `component_toggles`; uno desactivado se excluye
    por completo de la suma, no participa ni como cero disfrazado.

    Parameters
    ----------
    master_dataframe : pd.DataFrame
        DataFrame Maestro de math_processor.py (diario, con columnas
        WALCL, WDTGAL, RRP, ECBASSET, DEXUSEU_FRED ya alineadas/ffilled).
    component_toggles : Optional[Dict[str, bool]]
        Estado de cada checkbox (claves de config.COMBINED_LIQUIDITY_COMPONENTS:
        WALCL, TGA, RRP, ECB). Si es None, se usan los defaults (todos activos).
    apply_sma : bool
        Si True, agrega la columna Indice_Global_Final ya suavizada con SMA
        (aplicada sobre el Z-Score, no sobre el RoC crudo).
    sma_window_weeks : int
        Ventana de la SMA en semanas (se acota entre
        COMBINED_LIQUIDITY_MIN_SMA_WEEKS y COMBINED_LIQUIDITY_MAX_SMA_WEEKS).

    Returns
    -------
    pd.DataFrame
        DataFrame semanal (cierre viernes) con Date, BTC_Close, SOL_Close,
        Indice_Global_RoC (RoC crudo, % sobre 90 días), Indice_Global_Zscore
        (Z-Score rodante de 52 semanas sobre ese RoC) e Indice_Global_Final
        (= Z-Score, o Z-Score + SMA si apply_sma=True).
    """
    empty_result = pd.DataFrame(
        columns=[
            "Date", "BTC_Close", "SOL_Close",
            "Indice_Global_RoC", "Indice_Global_Zscore", "Indice_Global_Final",
        ]
    )

    try:
        required_columns = [
            "Date", "WALCL", "WDTGAL", "RRP", "ECBASSET", "DEXUSEU_FRED",
            "BTC_Close", "SOL_Close",
        ]
        missing_columns = [c for c in required_columns if c not in master_dataframe.columns]
        if master_dataframe.empty or missing_columns:
            if missing_columns:
                LOGGER.warning(
                    "Faltan columnas para el Índice Global Combinado: %s.",
                    missing_columns,
                )
            return empty_result

        resolved_toggles = {
            key: config["default"] for key, config in COMBINED_LIQUIDITY_COMPONENTS.items()
        }
        if component_toggles:
            resolved_toggles.update(component_toggles)

        working = master_dataframe.loc[:, required_columns].copy()
        working = working.sort_values(by="Date").reset_index(drop=True)

        walcl = pd.to_numeric(working["WALCL"], errors="coerce").fillna(0.0)
        wdtgal = pd.to_numeric(working["WDTGAL"], errors="coerce").fillna(0.0)
        rrp_millones = (
            pd.to_numeric(working["RRP"], errors="coerce").fillna(0.0) * RRP_BILLIONS_TO_MILLIONS
        )
        ecb_usd = (
            pd.to_numeric(working["ECBASSET"], errors="coerce").fillna(0.0)
            * pd.to_numeric(working["DEXUSEU_FRED"], errors="coerce").fillna(0.0)
        )

        # Paso 3 + checkboxes: cada componente se incluye solo si su
        # checkbox está activo (ninguno se fuerza a participar).
        zero_series = pd.Series(0.0, index=working.index)
        combined_nominal = (
            (walcl if resolved_toggles.get("WALCL", True) else zero_series)
            - (wdtgal if resolved_toggles.get("TGA", True) else zero_series)
            - (rrp_millones if resolved_toggles.get("RRP", True) else zero_series)
            + (ecb_usd if resolved_toggles.get("ECB", True) else zero_series)
        )

        working["Liquidez_Combinada_Nominal"] = combined_nominal

        # Paso 4: Rate of Change de 90 días. NaN para los primeros 90 días
        # (no hay suficiente historia) - no se inventa un valor.
        working["Indice_Global_RoC"] = (
            working["Liquidez_Combinada_Nominal"].pct_change(
                periods=COMBINED_LIQUIDITY_ROC_WINDOW_DAYS
            )
            * 100.0
        )
        working["Indice_Global_RoC"] = working["Indice_Global_RoC"].replace(
            [np.inf, -np.inf], np.nan
        )

        # Paso 5: re-agrupación semanal (cierre viernes), último valor de
        # cada semana (no un promedio - consistente con el resto del
        # programa: no se inventa un valor intermedio).
        weekly = (
            working.set_index("Date")[["BTC_Close", "SOL_Close", "Indice_Global_RoC"]]
            .resample(COMBINED_LIQUIDITY_RESAMPLE_RULE)
            .last()
            .reset_index()
        )

        # CORRECCIÓN INSTITUCIONAL: el RoC de 90 días puede "explotar" a
        # porcentajes absurdos (ej. -379%) cuando Liquidez_Combinada_Nominal
        # pasa cerca de cero (el denominador de pct_change se acerca a 0).
        # Se normaliza con un Z-Score RODANTE de 52 semanas (media y
        # desviación estándar móviles, NUNCA histórico completo/global) -
        # el orden exacto queda: suma de componentes -> RoC de 90 días ->
        # Z-Score sobre ese RoC ya semanal. calculate_zscore ya es rodante
        # por construcción (usa .rolling(), no .mean()/.std() globales).
        weekly["Indice_Global_Zscore"] = calculate_zscore(
            weekly["Indice_Global_RoC"], COMBINED_LIQUIDITY_ZSCORE_WINDOW_WEEKS
        )

        if apply_sma:
            bounded_window = max(
                COMBINED_LIQUIDITY_MIN_SMA_WEEKS,
                min(COMBINED_LIQUIDITY_MAX_SMA_WEEKS, sma_window_weeks),
            )
            weekly["Indice_Global_Final"] = (
                weekly["Indice_Global_Zscore"]
                .rolling(window=bounded_window, min_periods=max(2, bounded_window // 2))
                .mean()
            )
        else:
            weekly["Indice_Global_Final"] = weekly["Indice_Global_Zscore"]

        LOGGER.info(
            "Índice de Liquidez Global Combinada construido. Componentes activos: %s. "
            "SMA aplicada: %s. Semanas: %s.",
            [k for k, v in resolved_toggles.items() if v],
            apply_sma,
            len(weekly),
        )

        return weekly

    except Exception as error:
        LOGGER.exception(
            "Error al construir el Índice de Liquidez Global Combinada. "
            "Tipo: %s. Detalle: %s",
            type(error).__name__,
            error,
        )
        return empty_result



def build_short_term_liquidity_index(
    master_dataframe: pd.DataFrame,
    stablecoin_dataframe: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """
    Índice de Liquidez Inmediata de Mercado (Corto Plazo):

        WALCL (fijo al último miércoles) - TGA diario - RRP diario
        + Capitalización de Stablecoins (USDT+USDC+DAI+FDUSD)

    Nota técnica: WALCL ya llega desde FRED como un nivel semanal "As of
    Wednesday" y math_processor.py ya lo propaga hacia adelante (ffill)
    hasta la siguiente actualización - es decir, "mantenerlo fijo hasta el
    próximo miércoles" es exactamente el comportamiento que ya tiene la
    columna WALCL_USD_T. No hace falta lógica adicional para eso.

    Normalizado con Z-Score de 30 días.

    Parameters
    ----------
    master_dataframe : pd.DataFrame
        DataFrame Maestro de math_processor.py.
    stablecoin_dataframe : Optional[pd.DataFrame]
        Resultado de data_ingestion.get_stablecoin_market_cap_history().
        Si es None o está vacío, el componente de stablecoins simplemente
        no participa (no se inventa un valor).

    Returns
    -------
    pd.DataFrame
        DataFrame con Date, Indice_Corto_Plazo_Crudo e
        Indice_Corto_Plazo_Zscore.
    """
    try:
        if master_dataframe.empty:
            return pd.DataFrame(
                columns=["Date", "Indice_Corto_Plazo_Crudo", "Indice_Corto_Plazo_Zscore"]
            )

        result = master_dataframe.loc[:, ["Date"]].copy()

        overrides: Dict[str, pd.Series] = {
            "WALCL_FIJO": master_dataframe.get(
                "WALCL_USD_T", pd.Series(0.0, index=master_dataframe.index)
            )
        }

        if stablecoin_dataframe is not None and not stablecoin_dataframe.empty:
            stablecoin_aligned = pd.merge(
                master_dataframe.loc[:, ["Date"]],
                stablecoin_dataframe.loc[:, ["Date", "Stablecoin_MCap_USD"]],
                on="Date",
                how="left",
            )
            stablecoin_aligned["Stablecoin_MCap_USD"] = stablecoin_aligned[
                "Stablecoin_MCap_USD"
            ].ffill()
            overrides["STABLECOINS"] = (
                stablecoin_aligned["Stablecoin_MCap_USD"] / STABLECOIN_TRILLIONS_DIVISOR
            )
        else:
            LOGGER.warning(
                "Sin historial de stablecoins disponible; el componente "
                "STABLECOINS no participará en el Índice de Corto Plazo."
            )

        result["Indice_Corto_Plazo_Crudo"] = _sum_components(
            master_dataframe, SHORT_TERM_LIQUIDITY_COMPONENTS, overrides=overrides
        )

        result["Indice_Corto_Plazo_Zscore"] = calculate_zscore(
            result["Indice_Corto_Plazo_Crudo"], SHORT_TERM_ZSCORE_WINDOW_DAYS
        )

        return result

    except Exception as error:
        LOGGER.exception(
            "Error al construir el Índice de Liquidez de Corto Plazo. "
            "Tipo: %s. Detalle: %s",
            type(error).__name__,
            error,
        )
        return pd.DataFrame(
            columns=["Date", "Indice_Corto_Plazo_Crudo", "Indice_Corto_Plazo_Zscore"]
        )


def build_short_term_liquidity_view(
    master_dataframe: pd.DataFrame,
    stablecoin_dataframe: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """
    Punto de entrada para la vista de Corto Plazo: sigue siendo diaria, sin
    checkboxes ni cambio de temporalidad (por decisión explícita del
    usuario - el Largo Plazo es el único que cambió a semanal/mensual).

    Parameters
    ----------
    master_dataframe : pd.DataFrame
        DataFrame Maestro de math_processor.py.
    stablecoin_dataframe : Optional[pd.DataFrame]
        Resultado de data_ingestion.get_stablecoin_market_cap_history().

    Returns
    -------
    pd.DataFrame
        Date, BTC_Close, SOL_Close, Indice_Corto_Plazo_Crudo,
        Indice_Corto_Plazo_Zscore (cadencia diaria).
    """
    try:
        if master_dataframe.empty:
            return pd.DataFrame()

        short_term = build_short_term_liquidity_index(master_dataframe, stablecoin_dataframe)

        combined = master_dataframe.loc[:, ["Date", "BTC_Close", "SOL_Close"]].copy()
        combined = pd.merge(combined, short_term, on="Date", how="left")
        combined = combined.sort_values(by="Date").reset_index(drop=True)

        return combined

    except Exception as error:
        LOGGER.exception(
            "Error al construir la vista de Liquidez de Corto Plazo. "
            "Tipo: %s. Detalle: %s",
            type(error).__name__,
            error,
        )
        return pd.DataFrame()


# =====================================================================
# NUEVO: PANEL MACRO-BITCOIN AVANZADO (US10Y, STLFSI4, DXY, MVRV Z-Score)
# =====================================================================
# CANDADO: esta sección es 100% aditiva. No modifica, llama de forma
# distinta, ni reutiliza el estado interno de build_combined_global_
# liquidity_index() más allá de invocarla de la misma manera en que ya lo
# hace app.py - es decir, se lee su resultado, nunca se altera su código.

MACRO_PANEL_COLUMNS: List[str] = [
    "Date",
    "BTC_Close",
    "Liquidez_Global_Zscore",
    "US10Y",
    "US10Y_SMA",
    "STLFSI4",
    "DXY_RoC90_Inv",
    "MVRV_Zscore",
    "Senal_Compra_Macro",
]


def _resample_weekly_last(
    dataframe: pd.DataFrame,
    date_column: str,
    value_columns: List[str],
) -> pd.DataFrame:
    """
    Reagrupa una serie diaria a cadencia semanal (cierre viernes),
    tomando el último valor real de cada semana (`.last()`), exactamente
    la misma convención ya usada por el índice de Liquidez Global
    Combinada. Nunca promedia ni interpola un valor sintético.
    """
    try:
        if dataframe.empty:
            return pd.DataFrame(columns=[date_column] + value_columns)

        working = dataframe.loc[:, [date_column] + value_columns].copy()
        working = working.sort_values(by=date_column).reset_index(drop=True)

        weekly = (
            working.set_index(date_column)[value_columns]
            .resample(MACRO_PANEL_RESAMPLE_RULE)
            .last()
            .reset_index()
        )

        return weekly

    except Exception as error:
        LOGGER.exception(
            "Error al reagrupar semanalmente. Tipo: %s. Detalle: %s",
            type(error).__name__,
            error,
        )
        return pd.DataFrame(columns=[date_column] + value_columns)


def build_macro_bitcoin_signals_view(
    master_dataframe: pd.DataFrame,
    mvrv_dataframe: Optional[pd.DataFrame] = None,
    us10y_sma_weeks: int = 20,
) -> pd.DataFrame:
    """
    Construye la vista semanal sincronizada del Panel Macro-Bitcoin
    Avanzado: US10Y (+ SMA), STLFSI4 (para sombreado de fondo), DXY con
    Rate of Change de 90 días invertido, MVRV Z-Score de Bitcoin, y la
    Señal de Compra Macro (Requerimiento 6).

    Metodología (igual criterio que Liquidez Global Combinada):
      - US10Y y STLFSI4: ya llegan diarios y con ffill aplicado desde
        math_processor.py (misma alineación genérica que WALCL/WDTGAL).
        Aquí solo se reagrupan a cierre de viernes con `.last()`.
      - DXY: Rate of Change porcentual de 90 días calculado en la serie
        DIARIA (para no perder resolución en la ventana móvil), invertido
        (x -1), y luego reagrupado semanalmente con `.last()`.
      - MVRV Z-Score: se reindexa a calendario diario continuo + ffill
        (mismo criterio que el resto del programa) antes de reagruparse
        semanalmente, para alinearlo con las demás series.
      - Liquidez Global: se reutiliza Indice_Global_Final, calculado por
        build_combined_global_liquidity_index() con los componentes por
        defecto (WALCL, TGA, RRP, ECB activos) - esa función NO se
        modifica, solo se invoca y se lee su resultado.
      - Señal de Compra Macro: True cuando, en la misma semana,
        Liquidez_Global_Zscore < LIQUIDITY_SIGNAL_ZSCORE_THRESHOLD Y
        MVRV_Zscore < MVRV_CAPITULATION_THRESHOLD simultáneamente.

    Parameters
    ----------
    master_dataframe : pd.DataFrame
        DataFrame Maestro de math_processor.py (con US10Y, STLFSI4, DXY y
        BTC_Close ya alineados).
    mvrv_dataframe : Optional[pd.DataFrame]
        Resultado de data_ingestion.get_mvrv_zscore_history(). Si es None
        o está vacío, la columna MVRV_Zscore y la Señal de Compra Macro
        quedan en NaN/False (no se inventa un valor).
    us10y_sma_weeks : int
        Ventana en semanas de la SMA aplicada sobre US10Y, acotada entre
        US10Y_SMA_MIN_WEEKS y US10Y_SMA_MAX_WEEKS.

    Returns
    -------
    pd.DataFrame
        Columnas: MACRO_PANEL_COLUMNS, cadencia semanal (cierre viernes).
    """
    empty_result = pd.DataFrame(columns=MACRO_PANEL_COLUMNS)

    try:
        required_columns = ["Date", "US10Y", "STLFSI4", "DXY", "BTC_Close"]
        missing_columns = [c for c in required_columns if c not in master_dataframe.columns]
        if master_dataframe.empty or missing_columns:
            if missing_columns:
                LOGGER.warning(
                    "Faltan columnas para el Panel Macro-Bitcoin Avanzado: %s.",
                    missing_columns,
                )
            return empty_result

        working = master_dataframe.loc[:, required_columns].copy()
        working = working.sort_values(by="Date").reset_index(drop=True)

        # DXY: RoC de 90 días calculado en la serie diaria, luego invertido.
        working["DXY_RoC90_Inv"] = (
            pd.to_numeric(working["DXY"], errors="coerce").pct_change(
                periods=DXY_ROC_WINDOW_DAYS
            )
            * 100.0
            * -1.0
        )
        working["DXY_RoC90_Inv"] = working["DXY_RoC90_Inv"].replace(
            [np.inf, -np.inf], np.nan
        )

        weekly = _resample_weekly_last(
            working,
            date_column="Date",
            value_columns=["US10Y", "STLFSI4", "DXY_RoC90_Inv", "BTC_Close"],
        )

        if weekly.empty:
            return empty_result

        # Requerimiento 2: SMA de mediano/largo plazo sobre US10Y, ya en
        # cadencia semanal (bounded_window semanas ~ mediano/largo plazo).
        bounded_window = max(
            US10Y_SMA_MIN_WEEKS, min(US10Y_SMA_MAX_WEEKS, int(us10y_sma_weeks))
        )
        weekly["US10Y_SMA"] = (
            weekly["US10Y"]
            .rolling(window=bounded_window, min_periods=max(2, bounded_window // 2))
            .mean()
        )

        # Liquidez Global: se REUTILIZA (solo lectura) el índice ya
        # existente y sin modificar. Componentes por defecto (todos ON).
        combined_liquidity = build_combined_global_liquidity_index(master_dataframe)
        if not combined_liquidity.empty and "Indice_Global_Final" in combined_liquidity.columns:
            liquidity_slice = combined_liquidity.loc[
                :, ["Date", "Indice_Global_Final"]
            ].rename(columns={"Indice_Global_Final": "Liquidez_Global_Zscore"})
            weekly = pd.merge(weekly, liquidity_slice, on="Date", how="left")
        else:
            weekly["Liquidez_Global_Zscore"] = np.nan

        # MVRV Z-Score: reindexado a calendario diario continuo + ffill,
        # igual criterio que el resto del programa, antes de reagrupar.
        if mvrv_dataframe is not None and not mvrv_dataframe.empty:
            mvrv_clean = mvrv_dataframe.loc[:, ["Date", "MVRV_Zscore"]].copy()
            mvrv_clean["Date"] = pd.to_datetime(mvrv_clean["Date"], errors="coerce")
            mvrv_clean = mvrv_clean.dropna(subset=["Date"]).sort_values(by="Date")

            full_daily_index = pd.date_range(
                start=mvrv_clean["Date"].min(),
                end=max(mvrv_clean["Date"].max(), weekly["Date"].max()),
                freq="D",
            )
            mvrv_daily = (
                mvrv_clean.set_index("Date")
                .reindex(full_daily_index)
                .ffill()
                .rename_axis("Date")
                .reset_index()
            )

            mvrv_weekly = _resample_weekly_last(
                mvrv_daily, date_column="Date", value_columns=["MVRV_Zscore"]
            )
            weekly = pd.merge(weekly, mvrv_weekly, on="Date", how="left")
        else:
            LOGGER.warning(
                "Sin historial de MVRV Z-Score disponible; la columna "
                "MVRV_Zscore y la Señal de Compra Macro quedarán vacías."
            )
            weekly["MVRV_Zscore"] = np.nan

        # Requerimiento 6: Señal de Compra Macro (ambas condiciones a la
        # vez, en la misma semana). Con NaN en cualquiera de los dos
        # lados, la comparación da False de forma natural (no se activa
        # una señal con datos incompletos).
        weekly["Senal_Compra_Macro"] = (
            (weekly["Liquidez_Global_Zscore"] < LIQUIDITY_SIGNAL_ZSCORE_THRESHOLD)
            & (weekly["MVRV_Zscore"] < MVRV_CAPITULATION_THRESHOLD)
        ).fillna(False)

        for column in MACRO_PANEL_COLUMNS:
            if column not in weekly.columns:
                weekly[column] = np.nan

        weekly = weekly.loc[:, MACRO_PANEL_COLUMNS]
        weekly = weekly.sort_values(by="Date").reset_index(drop=True)

        LOGGER.info(
            "Panel Macro-Bitcoin Avanzado construido. Semanas: %s. "
            "Señales de compra detectadas: %s.",
            len(weekly),
            int(weekly["Senal_Compra_Macro"].sum()),
        )

        return weekly

    except Exception as error:
        LOGGER.exception(
            "Error al construir el Panel Macro-Bitcoin Avanzado. "
            "Tipo: %s. Detalle: %s",
            type(error).__name__,
            error,
        )
        return empty_result
