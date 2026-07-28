"""
Procesamiento, alineación y cálculo de indicadores de liquidez global.

El módulo descarga las variables macroeconómicas y de mercado, las alinea
por fecha con outer joins, aplica forward fill únicamente a datos no cripto
y calcula la liquidez global sin invalidar la tabla si una fuente falla.
"""

import logging
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from config import (
    FRED_API_KEY,
    FRED_SERIES,
    LAG_ACCELERATORS,
    LAG_DECELERATORS,
    BASE_LAG_DAYS,
    LIQUIDITY_BASE_COMPONENTS,
    LIQUIDITY_REGION_COMPONENTS,
    MAX_NET_LAG_DAYS,
    MIN_NET_LAG_DAYS,
    USD_BILLIONS_TO_TRILLIONS,  # CORRECCIÓN DE ERROR
    YAHOO_TICKERS,
)
from data_ingestion import (
    DATA_HEALTH,
    get_fred_data,
    get_usdt_dominance_history,
    get_yfinance_data,
)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

LOGGER = logging.getLogger(__name__)


# ACTUALIZACIÓN PARCHE: nombres de columnas internos desacoplados del ID de
# serie de FRED (que puede cambiar). TREASURY_GENERAL_ACCOUNT y
# ECB_BALANCE_SHEET ya no exponen el ID crudo (WTGASSN/ECBASSET) como
# nombre de columna; se agrega JAPAN_BALANCE_SHEET.
FRED_COLUMN_MAPPING: Dict[str, str] = {
    "FED_BALANCE_SHEET": "WALCL",
    "TREASURY_GENERAL_ACCOUNT": "TGA",
    "REVERSE_REPO": "RRP",
    "ECB_BALANCE_SHEET": "ECBASSET",
    "PBOC_LIQUIDITY_OR_ASSETS": "PBoC_Assets",
    "JAPAN_BALANCE_SHEET": "JPNASSETS",  # ACTUALIZACIÓN PARCHE
    # NUEVO: LIQUIDEZ GLOBAL COMBINADA - series dedicadas para el nuevo
    # índice Fed+BCE (RoC). Se agregan como columnas nuevas, no reemplazan
    # nada existente: WDTGAL es distinta de TGA/WTREGEN, y DEXUSEU_FRED es
    # el tipo de cambio EUR/USD publicado por la propia FRED (no Yahoo),
    # tal como se pidió explícitamente para este cálculo.
    "US_TREASURY_ACCOUNT_WDTGAL": "WDTGAL",
    "EUR_USD_FRED": "DEXUSEU_FRED",
    # NUEVO: PANEL MACRO-BITCOIN AVANZADO - se registran aquí para que
    # _download_fred_dataframes() las descargue, alinee (ffill diario) y
    # fusione exactamente igual que el resto de series FRED, sin tocar
    # ninguna función existente.
    "US_10Y_TREASURY": "US10Y",
    "FINANCIAL_STRESS_INDEX": "STLFSI4",
}

YAHOO_COLUMN_MAPPING: Dict[str, str] = {
    "EUR_USD": "EURUSD",
    "CNY_USD": "CNYUSD",
    "JPY_USD": "JPYUSD",  # ACTUALIZACIÓN PARCHE
    "DOLLAR_INDEX": "DXY",
    "BITCOIN": "BTC_Close",
    "SOLANA": "SOL_Close",
    "TETHER": "USDT_Close",
}

CRYPTO_PRICE_COLUMNS: List[str] = [
    "BTC_Close",
    "SOL_Close",
    "USDT_Close",
]

MASTER_COLUMNS: List[str] = [
    "Date",
    "WALCL",
    "TGA",
    "RRP",
    "ECBASSET",
    "PBoC_Assets",
    "JPNASSETS",  # ACTUALIZACIÓN PARCHE
    "WDTGAL",  # NUEVO: LIQUIDEZ GLOBAL COMBINADA
    "DEXUSEU_FRED",  # NUEVO: LIQUIDEZ GLOBAL COMBINADA
    "US10Y",  # NUEVO: PANEL MACRO-BITCOIN AVANZADO
    "STLFSI4",  # NUEVO: PANEL MACRO-BITCOIN AVANZADO
    "EURUSD",
    "CNYUSD",
    "JPYUSD",  # ACTUALIZACIÓN PARCHE
    "DXY",
    "BTC_Close",
    "SOL_Close",
    "USDT_Close",
    "USDT_Dominance",  # ACTUALIZACIÓN PARCHE
    "WALCL_USD_T",
    "TGA_USD_T",
    "RRP_USD_T",
    "ECBASSET_EUR_T",
    "PBoC_Assets_CNY_T",
    "JPNASSETS_JPY_T",  # ACTUALIZACIÓN PARCHE
    "ECBASSET_USD_T",
    "PBoC_Assets_USD_T",
    "JPNASSETS_USD_T",  # ACTUALIZACIÓN PARCHE
    "Liquidez_Global",
    "Liquidez_Global_Cruda",  # ACTUALIZACIÓN PARCHE - antes de EMA, para graficar en escalones
    "Liquidez_Suavizada",
    "Media_Movil_50",
    "Es_Pico",
]

# WALCL, TGA y RRP se tratan como millones de USD.
# Al dividir entre 1,000,000, las series quedan expresadas
# en billones de dólares estadounidenses.
USD_MILLIONS_TO_TRILLIONS = 1_000_000.0

# ECBASSETSW se expresa como millones de euros.
EUR_MILLIONS_TO_TRILLIONS = 1_000_000.0

# PECOASSMMCNBDC se normaliza como millones de yuanes chinos.
CNY_MILLIONS_TO_TRILLIONS = 1_000_000.0

# ACTUALIZACIÓN PARCHE: JPNASSETS viene en "100 millones de yenes"
# (unidad oficial de FRED para esta serie). Para llevarlo a billones de
# yenes: valor * 100,000,000 / 1,000,000,000,000 = valor / 10,000.
JPY_HUNDRED_MILLIONS_TO_TRILLIONS = 10_000.0


def _create_empty_dataframe(columns: List[str]) -> pd.DataFrame:
    """
    Crea un DataFrame vacío con la estructura solicitada.

    Parameters
    ----------
    columns : List[str]
        Columnas requeridas en el DataFrame.

    Returns
    -------
    pd.DataFrame
        DataFrame vacío y estructurado.
    """
    try:
        dataframe = pd.DataFrame(columns=columns)

        if "Date" in dataframe.columns:
            dataframe["Date"] = pd.to_datetime(
                dataframe["Date"],
                errors="coerce",
            )

        return dataframe

    except Exception as error:
        LOGGER.exception(
            "Error al crear DataFrame vacío. Tipo: %s. Detalle: %s",
            type(error).__name__,
            error,
        )
        return pd.DataFrame()


def _create_empty_master_dataframe() -> pd.DataFrame:
    """
    Crea un DataFrame Maestro vacío con todas las columnas esperadas.

    Returns
    -------
    pd.DataFrame
        DataFrame Maestro vacío.
    """
    try:
        empty_master = _create_empty_dataframe(MASTER_COLUMNS)
        empty_master["Es_Pico"] = empty_master["Es_Pico"].astype(bool)
        return empty_master

    except Exception as error:
        LOGGER.exception(
            "Error al crear DataFrame Maestro vacío. Tipo: %s. Detalle: %s",
            type(error).__name__,
            error,
        )
        return pd.DataFrame(columns=MASTER_COLUMNS)


def _normalize_dates(dataframe: pd.DataFrame) -> pd.DataFrame:
    """
    Convierte Date a datetime, elimina duplicados y ordena cronológicamente.

    Parameters
    ----------
    dataframe : pd.DataFrame
        DataFrame que contiene una columna Date.

    Returns
    -------
    pd.DataFrame
        DataFrame con fechas normalizadas.
    """
    try:
        if dataframe.empty:
            return dataframe.copy()

        if "Date" not in dataframe.columns:
            raise ValueError(
                "El DataFrame no contiene la columna obligatoria 'Date'."
            )

        normalized_dataframe = dataframe.copy()
        normalized_dataframe["Date"] = pd.to_datetime(
            normalized_dataframe["Date"],
            errors="coerce",
        )

        if getattr(normalized_dataframe["Date"].dt, "tz", None) is not None:
            normalized_dataframe["Date"] = (
                normalized_dataframe["Date"].dt.tz_localize(None)
            )

        normalized_dataframe["Date"] = normalized_dataframe["Date"].dt.normalize()
        normalized_dataframe = normalized_dataframe.dropna(subset=["Date"])
        normalized_dataframe = normalized_dataframe.drop_duplicates(
            subset=["Date"],
            keep="last",
        )
        normalized_dataframe = normalized_dataframe.sort_values(by="Date")
        normalized_dataframe = normalized_dataframe.reset_index(drop=True)

        return normalized_dataframe

    except Exception as error:
        LOGGER.exception(
            "Error al normalizar fechas. Tipo: %s. Detalle: %s",
            type(error).__name__,
            error,
        )
        return _create_empty_dataframe(["Date"])


# =====================================================================
# ACTUALIZACIÓN (Directriz 1 - Alineación temporal estricta desde la raíz)
# =====================================================================
# Apertura PARCIAL y controlada del "Candado Estricto" del gráfico
# "Componentes de la Liquidez Global Combinada": esta función NO cambia
# colores, nombres ni disposición de ningún gráfico, y NO modifica
# build_combined_global_liquidity_index() ni ninguna fórmula existente en
# advanced_liquidity.py. Solo mejora la PUREZA del dato de entrada: cada
# serie individual (WALCL, ECBASSET, DEXUSEU, etc.) se reindexa a un
# calendario diario continuo y se propaga hacia adelante (ffill) de forma
# INDEPENDIENTE, en la raíz (este módulo de ingesta/procesamiento), antes
# de unirse con las demás. Así todas las variables del programa - tanto
# el gráfico original como los sub-paneles nuevos - se alimentan de datos
# continuos y sin huecos NaN desde el origen.
#
# No se inventa historia antes de la primera fecha real de cada serie: el
# reindexado solo cubre el rango [primera fecha, última fecha] que la
# propia fuente ya reportó.
def _reindex_daily_and_ffill(
    dataframe: pd.DataFrame,
    value_column: str,
) -> pd.DataFrame:
    """
    Reindexa una serie individual ya limpia a un calendario diario continuo
    (entre su propia primera y última fecha) y aplica ffill sobre los
    huecos internos.

    Parameters
    ----------
    dataframe : pd.DataFrame
        Serie ya preparada, con columnas Date y `value_column`.
    value_column : str
        Nombre de la columna de valor a reindexar/propagar.

    Returns
    -------
    pd.DataFrame
        Serie con columnas Date y `value_column`, diaria y continua. Si la
        entrada está vacía o inválida, se devuelve sin modificar.
    """
    try:
        if dataframe.empty or value_column not in dataframe.columns:
            return dataframe

        working = dataframe.dropna(subset=["Date", value_column]).copy()
        if working.empty:
            return dataframe

        working = working.sort_values(by="Date")
        working = working.drop_duplicates(subset=["Date"], keep="last")

        full_daily_index = pd.date_range(
            start=working["Date"].min(),
            end=working["Date"].max(),
            freq="D",
        )

        reindexed_dataframe = (
            working.set_index("Date")[[value_column]]
            .reindex(full_daily_index)
            .ffill()
            .rename_axis("Date")
            .reset_index()
        )

        LOGGER.info(
            "Directriz 1 - serie %s reindexada a calendario diario "
            "continuo + ffill en la raíz. Filas: %s -> %s.",
            value_column,
            len(working),
            len(reindexed_dataframe),
        )

        return reindexed_dataframe

    except Exception as error:
        LOGGER.exception(
            "Error al reindexar/ffillear en la raíz la serie %s. "
            "Tipo: %s. Detalle: %s",
            value_column,
            type(error).__name__,
            error,
        )
        return dataframe


def _prepare_fred_series(
    dataframe: pd.DataFrame,
    output_column: str,
) -> pd.DataFrame:
    """
    Convierte una descarga FRED al formato Date + variable macro.

    Parameters
    ----------
    dataframe : pd.DataFrame
        DataFrame entregado por get_fred_data.
    output_column : str
        Nombre final de la variable macroeconómica.

    Returns
    -------
    pd.DataFrame
        Serie macroeconómica limpia.
    """
    try:
        if dataframe.empty:
            LOGGER.warning(
                "La serie FRED %s está vacía; se utilizará como fuente no disponible.",
                output_column,
            )
            return _create_empty_dataframe(["Date", output_column])

        required_columns = {"Date", "Value"}

        if not required_columns.issubset(dataframe.columns):
            raise ValueError(
                f"La serie FRED {output_column} debe contener Date y Value."
            )

        prepared_dataframe = dataframe.loc[:, ["Date", "Value"]].copy()
        prepared_dataframe = prepared_dataframe.rename(
            columns={"Value": output_column}
        )
        prepared_dataframe[output_column] = pd.to_numeric(
            prepared_dataframe[output_column],
            errors="coerce",
        )

        prepared_dataframe = _normalize_dates(prepared_dataframe)
        prepared_dataframe = prepared_dataframe.dropna(subset=[output_column])
        prepared_dataframe = prepared_dataframe.reset_index(drop=True)

        # ACTUALIZACIÓN (Directriz 1): ffill + reindexado diario continuo
        # aplicado de forma independiente a ESTA serie individual, en la
        # raíz, antes de unirse con las demás en _outer_merge_and_align.
        prepared_dataframe = _reindex_daily_and_ffill(
            prepared_dataframe, output_column
        )

        LOGGER.info(
            "Serie FRED preparada: %s. Registros válidos: %s.",
            output_column,
            len(prepared_dataframe),
        )

        return prepared_dataframe

    except Exception as error:
        LOGGER.exception(
            "Error al preparar la serie FRED %s. Tipo: %s. Detalle: %s",
            output_column,
            type(error).__name__,
            error,
        )
        return _create_empty_dataframe(["Date", output_column])


def _prepare_yahoo_close_series(
    dataframe: pd.DataFrame,
    output_column: str,
) -> pd.DataFrame:
    """
    Extrae y normaliza la columna Close de Yahoo Finance.

    Parameters
    ----------
    dataframe : pd.DataFrame
        DataFrame entregado por get_yfinance_data.
    output_column : str
        Nombre final de la columna de cierre.

    Returns
    -------
    pd.DataFrame
        Serie de precios limpia.
    """
    try:
        if dataframe.empty:
            LOGGER.warning(
                "La serie Yahoo Finance %s está vacía; se utilizará como fuente no disponible.",
                output_column,
            )
            return _create_empty_dataframe(["Date", output_column])

        if "Date" not in dataframe.columns:
            raise ValueError(
                f"La serie Yahoo Finance {output_column} no contiene Date."
            )

        exact_close_columns = [
            column
            for column in dataframe.columns
            if str(column).strip().lower() == "close"
        ]

        prefixed_close_columns = [
            column
            for column in dataframe.columns
            if str(column).strip().lower().startswith("close_")
        ]

        generic_close_columns = [
            column
            for column in dataframe.columns
            if "close" in str(column).strip().lower()
            and "adj" not in str(column).strip().lower()
        ]

        close_candidates = (
            exact_close_columns
            or prefixed_close_columns
            or generic_close_columns
        )

        if not close_candidates:
            raise ValueError(
                f"No existe una columna Close válida para {output_column}. "
                f"Columnas detectadas: {list(dataframe.columns)}"
            )

        selected_close_column = close_candidates[0]

        prepared_dataframe = dataframe.loc[
            :,
            ["Date", selected_close_column],
        ].copy()

        prepared_dataframe = prepared_dataframe.rename(
            columns={selected_close_column: output_column}
        )

        prepared_dataframe[output_column] = pd.to_numeric(
            prepared_dataframe[output_column],
            errors="coerce",
        )

        prepared_dataframe = _normalize_dates(prepared_dataframe)
        prepared_dataframe = prepared_dataframe.dropna(subset=[output_column])
        prepared_dataframe = prepared_dataframe.reset_index(drop=True)

        # ACTUALIZACIÓN (Directriz 1): ffill + reindexado diario continuo
        # en la raíz, igual que las series FRED - EXCEPTO para los precios
        # cripto (BTC/SOL/USDT), que deben conservar únicamente fechas con
        # precio real (mismo criterio ya documentado en
        # _outer_merge_and_align: "sólo se mantienen fechas con precio
        # real de Bitcoin").
        if output_column not in CRYPTO_PRICE_COLUMNS:
            prepared_dataframe = _reindex_daily_and_ffill(
                prepared_dataframe, output_column
            )

        LOGGER.info(
            "Serie Yahoo Finance preparada: %s. Registros válidos: %s.",
            output_column,
            len(prepared_dataframe),
        )

        return prepared_dataframe

    except Exception as error:
        LOGGER.exception(
            "Error al preparar Yahoo Finance %s. Tipo: %s. Detalle: %s",
            output_column,
            type(error).__name__,
            error,
        )
        return _create_empty_dataframe(["Date", output_column])


def _download_fred_dataframes(api_key: str) -> List[pd.DataFrame]:
    """
    Descarga y prepara todas las series macroeconómicas de FRED.

    Parameters
    ----------
    api_key : str
        API key de FRED.

    Returns
    -------
    List[pd.DataFrame]
        Lista de DataFrames macroeconómicos preparados.
    """
    try:
        fred_dataframes: List[pd.DataFrame] = []

        for config_key, output_column in FRED_COLUMN_MAPPING.items():
            try:
                series_id = FRED_SERIES[config_key]

                LOGGER.info(
                    "Descargando FRED. Serie: %s | ID: %s.",
                    output_column,
                    series_id,
                )

                raw_dataframe = get_fred_data(
                    series_id=series_id,
                    api_key=api_key,
                )

                fred_dataframes.append(
                    _prepare_fred_series(
                        dataframe=raw_dataframe,
                        output_column=output_column,
                    )
                )

                # NUEVO: LIQUIDEZ AVANZADA - honestidad en el Health Check:
                # MYAGM2CNM189N responde OK pero está descontinuada desde
                # 2019. Sin esta nota, "OK" daría a entender que los datos
                # están al día, cuando en realidad no hay tramo reciente.
                if series_id == "MYAGM2CNM189N" and not raw_dataframe.empty:
                    last_available_date = raw_dataframe["Date"].max()
                    DATA_HEALTH[series_id] = (
                        f"OK (LIMITADO: sin datos después de {last_available_date.strftime('%Y-%m-%d')}, "
                        "serie descontinuada en FRED)"
                    )

            except KeyError as error:
                LOGGER.exception(
                    "No se encontró %s en FRED_SERIES. Tipo: %s. Detalle: %s",
                    config_key,
                    type(error).__name__,
                    error,
                )
                fred_dataframes.append(
                    _create_empty_dataframe(["Date", output_column])
                )

            except Exception as error:
                LOGGER.exception(
                    "Error descargando FRED %s. Tipo: %s. Detalle: %s",
                    output_column,
                    type(error).__name__,
                    error,
                )
                fred_dataframes.append(
                    _create_empty_dataframe(["Date", output_column])
                )

        return fred_dataframes

    except Exception as error:
        LOGGER.exception(
            "Error general en descarga de FRED. Tipo: %s. Detalle: %s",
            type(error).__name__,
            error,
        )
        return []


def _download_yahoo_dataframes() -> List[pd.DataFrame]:
    """
    Descarga y prepara todas las series de Yahoo Finance.

    Returns
    -------
    List[pd.DataFrame]
        Lista de DataFrames de mercado preparados.
    """
    try:
        yahoo_dataframes: List[pd.DataFrame] = []

        for config_key, output_column in YAHOO_COLUMN_MAPPING.items():
            try:
                ticker = YAHOO_TICKERS[config_key]

                LOGGER.info(
                    "Descargando Yahoo Finance. Variable: %s | Ticker: %s.",
                    output_column,
                    ticker,
                )

                raw_dataframe = get_yfinance_data(ticker=ticker)

                yahoo_dataframes.append(
                    _prepare_yahoo_close_series(
                        dataframe=raw_dataframe,
                        output_column=output_column,
                    )
                )

            except KeyError as error:
                LOGGER.exception(
                    "No se encontró %s en YAHOO_TICKERS. Tipo: %s. Detalle: %s",
                    config_key,
                    type(error).__name__,
                    error,
                )
                yahoo_dataframes.append(
                    _create_empty_dataframe(["Date", output_column])
                )

            except Exception as error:
                LOGGER.exception(
                    "Error descargando Yahoo Finance %s. Tipo: %s. Detalle: %s",
                    output_column,
                    type(error).__name__,
                    error,
                )
                yahoo_dataframes.append(
                    _create_empty_dataframe(["Date", output_column])
                )

        return yahoo_dataframes

    except Exception as error:
        LOGGER.exception(
            "Error general en descarga de Yahoo Finance. Tipo: %s. Detalle: %s",
            type(error).__name__,
            error,
        )
        return []


def _outer_merge_and_align(dataframes: List[pd.DataFrame]) -> pd.DataFrame:
    """
    Une todos los DataFrames usando outer joins por Date y aplica ffill.

    El forward fill se limita a datos macroeconómicos y de mercado tradicional.
    Los precios cripto se conservan sin propagación para que sólo se mantengan
    fechas con precio real de Bitcoin.

    NOTA (Directriz 1): cada serie individual ya llega aquí reindexada a
    calendario diario continuo y ffilleada de forma independiente desde
    _prepare_fred_series/_prepare_yahoo_close_series (la raíz). Este ffill
    posterior al merge se conserva como red de seguridad adicional para
    cubrir cualquier fecha que solo exista en OTRA serie del merge (ej. un
    feriado bancario de la Fed que sí sea día hábil para el BCE); no
    cambia el comportamiento previo, solo queda reforzado con datos de
    entrada más puros.

    Parameters
    ----------
    dataframes : List[pd.DataFrame]
        Series de datos que deben contener una columna Date.

    Returns
    -------
    pd.DataFrame
        DataFrame temporal unificado.
    """
    try:
        valid_dataframes = [
            dataframe.copy()
            for dataframe in dataframes
            if isinstance(dataframe, pd.DataFrame)
            and "Date" in dataframe.columns
        ]

        if not valid_dataframes:
            LOGGER.error("No se recibieron DataFrames válidos para unir.")
            return _create_empty_master_dataframe()

        merged_dataframe: Optional[pd.DataFrame] = None

        for dataframe in valid_dataframes:
            try:
                normalized_dataframe = _normalize_dates(dataframe)

                if merged_dataframe is None:
                    merged_dataframe = normalized_dataframe
                else:
                    merged_dataframe = pd.merge(
                        merged_dataframe,
                        normalized_dataframe,
                        on="Date",
                        how="outer",
                    )

            except Exception as error:
                LOGGER.exception(
                    "Error durante un outer join. Tipo: %s. Detalle: %s",
                    type(error).__name__,
                    error,
                )
                raise

        if merged_dataframe is None or merged_dataframe.empty:
            LOGGER.warning("El resultado de los outer joins está vacío.")
            return _create_empty_master_dataframe()

        merged_dataframe = _normalize_dates(merged_dataframe)

        # ACTUALIZACIÓN PARCHE: USDT_Dominance también se propaga hacia
        # adelante (no es un precio cripto intradía, es un indicador de
        # mercado que solo cambia con nuevas observaciones de CoinGecko).
        columns_to_forward_fill = [
            column
            for column in merged_dataframe.columns
            if column != "Date" and column not in CRYPTO_PRICE_COLUMNS
        ]

        if columns_to_forward_fill:
            merged_dataframe[columns_to_forward_fill] = (
                merged_dataframe[columns_to_forward_fill].ffill()
            )

        if "BTC_Close" not in merged_dataframe.columns:
            LOGGER.error(
                "BTC_Close no existe; no se puede establecer el calendario cripto."
            )
            return _create_empty_master_dataframe()

        merged_dataframe = merged_dataframe.dropna(subset=["BTC_Close"])
        merged_dataframe = merged_dataframe.sort_values(by="Date")
        merged_dataframe = merged_dataframe.reset_index(drop=True)

        LOGGER.info(
            "Alineación completada. Fechas con precio BTC válido: %s.",
            len(merged_dataframe),
        )

        return merged_dataframe

    except Exception as error:
        LOGGER.exception(
            "Error al unificar y alinear DataFrames. Tipo: %s. Detalle: %s",
            type(error).__name__,
            error,
        )
        return _create_empty_master_dataframe()


def _ensure_numeric_column(
    dataframe: pd.DataFrame,
    column: str,
) -> pd.DataFrame:
    """
    Garantiza que una columna numérica exista y sustituye faltantes por cero.

    Parameters
    ----------
    dataframe : pd.DataFrame
        DataFrame a modificar.
    column : str
        Columna que se convertirá a numérica.

    Returns
    -------
    pd.DataFrame
        DataFrame con la columna numérica garantizada.
    """
    try:
        processed_dataframe = dataframe.copy()

        if column not in processed_dataframe.columns:
            LOGGER.warning(
                "La columna %s no está disponible; se crea con valor 0.",
                column,
            )
            processed_dataframe[column] = 0.0

        processed_dataframe[column] = pd.to_numeric(
            processed_dataframe[column],
            errors="coerce",
        )

        processed_dataframe[column] = processed_dataframe[column].replace(
            [np.inf, -np.inf],
            np.nan,
        )

        processed_dataframe[column] = processed_dataframe[column].fillna(0.0)

        return processed_dataframe

    except Exception as error:
        LOGGER.exception(
            "Error al normalizar la columna %s. Tipo: %s. Detalle: %s",
            column,
            type(error).__name__,
            error,
        )
        return dataframe.copy()


def _calculate_component_scales(master_dataframe: pd.DataFrame) -> pd.DataFrame:
    """
    Convierte todas las series macro crudas a sus columnas *_USD_T.

    Esta función SOLO calcula los componentes individuales en dólares
    (billones). NO decide qué componentes se suman ni con qué signo -
    eso lo hace calculate_composite_liquidity, que es la función que los
    checkboxes de la interfaz controlan (Requerimiento 1).

    ACTUALIZACIÓN PARCHE - corrección de la conversión FX:
    EURUSD=X y CNYUSD=X en Yahoo Finance representan "dólares por unidad
    de moneda extranjera" (ej. 1 EUR = 1.08 USD). Para convertir un monto
    en euros o yuanes a dólares hay que MULTIPLICAR por ese tipo de
    cambio, no dividir. La versión anterior dividía, lo que inflaba
    artificialmente (o desinflaba) el componente según el nivel del tipo
    de cambio. JPY=X, en cambio, representa "yenes por dólar", así que
    para JPNASSETS sí corresponde DIVIDIR.

    Parameters
    ----------
    master_dataframe : pd.DataFrame
        DataFrame unificado y alineado por fecha.

    Returns
    -------
    pd.DataFrame
        DataFrame con todas las columnas *_USD_T calculadas.
    """
    try:
        if master_dataframe.empty:
            LOGGER.warning(
                "El DataFrame Maestro está vacío; no se calcularán escalas."
            )
            return _create_empty_master_dataframe()

        processed_dataframe = master_dataframe.copy()

        numeric_columns = [
            "WALCL",
            "TGA",
            "RRP",
            "ECBASSET",
            "PBoC_Assets",
            "JPNASSETS",  # ACTUALIZACIÓN PARCHE
            "EURUSD",
            "CNYUSD",
            "JPYUSD",  # ACTUALIZACIÓN PARCHE
        ]

        for column in numeric_columns:
            try:
                processed_dataframe = _ensure_numeric_column(
                    dataframe=processed_dataframe,
                    column=column,
                )
            except Exception as error:
                LOGGER.exception(
                    "Error procesando la columna %s. Tipo: %s. Detalle: %s",
                    column,
                    type(error).__name__,
                    error,
                )
                processed_dataframe[column] = 0.0

        processed_dataframe["WALCL_USD_T"] = (
            processed_dataframe["WALCL"] / USD_MILLIONS_TO_TRILLIONS
        )
        processed_dataframe["TGA_USD_T"] = (
            processed_dataframe["TGA"] / USD_MILLIONS_TO_TRILLIONS
        )
        # CORRECCIÓN DE ERROR: RRPONTSYD viene de FRED en "Billions of US
        # Dollars", NO en millones como WALCL/TGA. Dividir por el mismo
        # factor de un millón dejaba el componente RRP subvalorado por
        # 1000x, haciéndolo prácticamente invisible en la fórmula
        # (Liquidez_Global = WALCL - TGA - RRP). Se corrige usando el
        # divisor correcto de billones -> billones (miles de millones a
        # trillones = dividir entre 1000).
        processed_dataframe["RRP_USD_T"] = (
            processed_dataframe["RRP"] / USD_BILLIONS_TO_TRILLIONS
        )

        processed_dataframe["ECBASSET_EUR_T"] = (
            processed_dataframe["ECBASSET"] / EUR_MILLIONS_TO_TRILLIONS
        )
        processed_dataframe["PBoC_Assets_CNY_T"] = (
            processed_dataframe["PBoC_Assets"] / CNY_MILLIONS_TO_TRILLIONS
        )
        processed_dataframe["JPNASSETS_JPY_T"] = (  # ACTUALIZACIÓN PARCHE
            processed_dataframe["JPNASSETS"] / JPY_HUNDRED_MILLIONS_TO_TRILLIONS
        )

        valid_eurusd = processed_dataframe["EURUSD"] > 0
        valid_cnyusd = processed_dataframe["CNYUSD"] > 0
        valid_jpyusd = processed_dataframe["JPYUSD"] > 0  # ACTUALIZACIÓN PARCHE

        # ACTUALIZACIÓN PARCHE (CORRECCIÓN DE ERROR): se multiplica, no se
        # divide. EURUSD=X ya es "USD por EUR".
        processed_dataframe["ECBASSET_USD_T"] = np.where(
            valid_eurusd,
            processed_dataframe["ECBASSET_EUR_T"]
            * processed_dataframe["EURUSD"],
            0.0,
        )

        # ACTUALIZACIÓN PARCHE (CORRECCIÓN DE ERROR): se multiplica, no se
        # divide. CNYUSD=X ya es "USD por CNY".
        processed_dataframe["PBoC_Assets_USD_T"] = np.where(
            valid_cnyusd,
            processed_dataframe["PBoC_Assets_CNY_T"]
            * processed_dataframe["CNYUSD"],
            0.0,
        )

        # ACTUALIZACIÓN PARCHE: JPY=X es "yenes por USD", aquí sí se divide.
        processed_dataframe["JPNASSETS_USD_T"] = np.where(
            valid_jpyusd,
            processed_dataframe["JPNASSETS_JPY_T"]
            / processed_dataframe["JPYUSD"],
            0.0,
        )

        LOGGER.info(
            "Escalas de componentes calculadas. Registros procesados: %s.",
            len(processed_dataframe),
        )

        return processed_dataframe

    except Exception as error:
        LOGGER.exception(
            "Error al calcular escalas de componentes. Tipo: %s. Detalle: %s",
            type(error).__name__,
            error,
        )
        return _create_empty_master_dataframe()


# ACTUALIZACIÓN PARCHE: Motor de Cálculo de Liquidez Compuesta modular
# (Requerimiento 1). Esta función NO descarga nada; opera sobre el
# DataFrame ya cacheado, por lo que activar/desactivar un checkbox en la
# interfaz recalcula el gráfico al instante, sin volver a golpear las APIs.
def calculate_composite_liquidity(
    master_dataframe: pd.DataFrame,
    base_toggles: Optional[Dict[str, bool]] = None,
    region_toggles: Optional[Dict[str, bool]] = None,
) -> pd.DataFrame:
    """
    Calcula Liquidez_Global de forma dinámica según los checkboxes activos.

    Fórmula base (todos activos):
        Liquidez_Global = WALCL - (TGA + RRP) + Europa + China + Japón

    Si un checkbox se desactiva, ese componente se excluye por completo de
    la suma (no se reemplaza por cero disfrazado: simplemente no participa).

    Parameters
    ----------
    master_dataframe : pd.DataFrame
        DataFrame con las columnas *_USD_T ya calculadas.
    base_toggles : Optional[Dict[str, bool]]
        Diccionario con claves de LIQUIDITY_BASE_COMPONENTS (WALCL, TGA, RRP)
        y su estado (True = incluido). Si es None, se usan los defaults.
    region_toggles : Optional[Dict[str, bool]]
        Diccionario con claves de LIQUIDITY_REGION_COMPONENTS (EUROPA,
        CHINA, JAPON) y su estado. Si es None, se usan los defaults.

    Returns
    -------
    pd.DataFrame
        DataFrame con la columna Liquidez_Global_Cruda recalculada.
    """
    try:
        if master_dataframe.empty:
            LOGGER.warning(
                "El DataFrame Maestro está vacío; no se calculará liquidez."
            )
            return master_dataframe.copy()

        resolved_base_toggles = {
            key: config["default"] for key, config in LIQUIDITY_BASE_COMPONENTS.items()
        }
        if base_toggles:
            resolved_base_toggles.update(base_toggles)

        resolved_region_toggles = {
            key: config["default"] for key, config in LIQUIDITY_REGION_COMPONENTS.items()
        }
        if region_toggles:
            resolved_region_toggles.update(region_toggles)

        processed_dataframe = master_dataframe.copy()
        liquidity_accumulator = pd.Series(0.0, index=processed_dataframe.index)
        active_components: List[str] = []

        all_components = {**LIQUIDITY_BASE_COMPONENTS, **LIQUIDITY_REGION_COMPONENTS}
        all_toggles = {**resolved_base_toggles, **resolved_region_toggles}

        for component_key, component_config in all_components.items():
            try:
                is_active = bool(all_toggles.get(component_key, component_config["default"]))

                if not is_active:
                    continue

                column_name = component_config["column"]
                sign = component_config["sign"]

                if column_name not in processed_dataframe.columns:
                    LOGGER.warning(
                        "Componente %s solicitado pero la columna %s no existe; se omite.",
                        component_key,
                        column_name,
                    )
                    continue

                component_values = pd.to_numeric(
                    processed_dataframe[column_name], errors="coerce"
                ).fillna(0.0)

                liquidity_accumulator = liquidity_accumulator + (sign * component_values)
                active_components.append(component_key)

            except Exception as error:
                LOGGER.exception(
                    "Error al incorporar el componente %s. Tipo: %s. Detalle: %s",
                    component_key,
                    type(error).__name__,
                    error,
                )

        processed_dataframe["Liquidez_Global_Cruda"] = liquidity_accumulator

        LOGGER.info(
            "Liquidez_Global recalculada con componentes activos: %s.",
            active_components,
        )

        return processed_dataframe

    except Exception as error:
        LOGGER.exception(
            "Error al calcular liquidez compuesta. Tipo: %s. Detalle: %s",
            type(error).__name__,
            error,
        )
        return master_dataframe.copy()


def _apply_smoothing_and_peak_detection(
    master_dataframe: pd.DataFrame,
) -> pd.DataFrame:
    """
    Aplica EMA de 14 días y detecta picos sobre media móvil de 50 días.

    Parameters
    ----------
    master_dataframe : pd.DataFrame
        DataFrame que contiene Liquidez_Global_Cruda.

    Returns
    -------
    pd.DataFrame
        DataFrame con Liquidez_Suavizada, Media_Movil_50 y Es_Pico.
    """
    try:
        if master_dataframe.empty:
            LOGGER.warning(
                "El DataFrame Maestro está vacío; no se aplicará suavizado."
            )
            return _create_empty_master_dataframe()

        if "Liquidez_Global_Cruda" not in master_dataframe.columns:
            raise ValueError(
                "La columna Liquidez_Global_Cruda no existe en el DataFrame Maestro."
            )

        processed_dataframe = master_dataframe.copy()

        processed_dataframe["Liquidez_Global_Cruda"] = pd.to_numeric(
            processed_dataframe["Liquidez_Global_Cruda"],
            errors="coerce",
        ).fillna(0.0)

        # ACTUALIZACIÓN PARCHE: se mantiene también Liquidez_Global (alias)
        # por compatibilidad con cualquier código anterior que la referencie.
        processed_dataframe["Liquidez_Global"] = processed_dataframe["Liquidez_Global_Cruda"]

        processed_dataframe["Liquidez_Suavizada"] = (
            processed_dataframe["Liquidez_Global_Cruda"]
            .ewm(span=14, adjust=False, min_periods=1)
            .mean()
        )

        processed_dataframe["Media_Movil_50"] = (
            processed_dataframe["Liquidez_Suavizada"]
            .rolling(window=50, min_periods=50)
            .mean()
        )

        processed_dataframe["Es_Pico"] = (
            processed_dataframe["Liquidez_Suavizada"]
            > processed_dataframe["Media_Movil_50"]
        )

        processed_dataframe["Es_Pico"] = (
            processed_dataframe["Es_Pico"]
            .fillna(False)
            .astype(bool)
        )

        processed_dataframe = processed_dataframe.reset_index(drop=True)

        LOGGER.info(
            "EMA y detección de picos completadas. Picos identificados: %s.",
            int(processed_dataframe["Es_Pico"].sum()),
        )

        return processed_dataframe

    except Exception as error:
        LOGGER.exception(
            "Error al aplicar suavizado y picos. Tipo: %s. Detalle: %s",
            type(error).__name__,
            error,
        )
        return _create_empty_master_dataframe()


def recalculate_liquidity(
    master_dataframe: pd.DataFrame,
    base_toggles: Optional[Dict[str, bool]] = None,
    region_toggles: Optional[Dict[str, bool]] = None,
) -> pd.DataFrame:
    """
    Recalcula Liquidez_Global, su suavizado y los picos, sin re-descargar
    datos. Esta es la función que app.py debe llamar cada vez que el
    usuario cambia un checkbox (Requerimiento 1) - es instantánea porque
    trabaja sobre el DataFrame ya cacheado en memoria/sesión.

    Parameters
    ----------
    master_dataframe : pd.DataFrame
        DataFrame Maestro con las columnas *_USD_T ya calculadas.
    base_toggles : Optional[Dict[str, bool]]
        Estado de los checkboxes de la fórmula base (WALCL, TGA, RRP).
    region_toggles : Optional[Dict[str, bool]]
        Estado de los checkboxes regionales (EUROPA, CHINA, JAPON).

    Returns
    -------
    pd.DataFrame
        DataFrame con Liquidez_Global, Liquidez_Suavizada, Media_Movil_50 y
        Es_Pico actualizados.
    """
    try:
        composite_dataframe = calculate_composite_liquidity(
            master_dataframe=master_dataframe,
            base_toggles=base_toggles,
            region_toggles=region_toggles,
        )
        return _apply_smoothing_and_peak_detection(composite_dataframe)

    except Exception as error:
        LOGGER.exception(
            "Error al recalcular liquidez. Tipo: %s. Detalle: %s",
            type(error).__name__,
            error,
        )
        return master_dataframe.copy()


# ACTUALIZACIÓN PARCHE: Sistema de Catalizadores y Retraso Neto
# (Requerimiento 2). Es puramente informativo/visual - no toca
# Liquidez_Global ni ninguna columna del gráfico principal.
def calculate_net_lag_days(
    active_accelerators: Optional[List[str]] = None,
    active_decelerators: Optional[List[str]] = None,
    base_lag_days: int = BASE_LAG_DAYS,
) -> int:
    """
    Calcula el Retraso Neto Ajustado (en días) combinando el retraso base
    con los catalizadores de velocidad activos.

    Parameters
    ----------
    active_accelerators : Optional[List[str]]
        Nombres de aceleradores activos (claves de LAG_ACCELERATORS).
    active_decelerators : Optional[List[str]]
        Nombres de desaceleradores activos (claves de LAG_DECELERATORS).
    base_lag_days : int
        Retraso base de referencia, en días.

    Returns
    -------
    int
        Retraso neto ajustado, acotado entre MIN_NET_LAG_DAYS y
        MAX_NET_LAG_DAYS para evitar valores absurdos (negativos o
        extremos) si se activan muchos catalizadores a la vez.
    """
    try:
        net_lag = float(base_lag_days)

        for accelerator_name in (active_accelerators or []):
            adjustment = LAG_ACCELERATORS.get(accelerator_name, 0)
            net_lag += adjustment

        for decelerator_name in (active_decelerators or []):
            adjustment = LAG_DECELERATORS.get(decelerator_name, 0)
            net_lag += adjustment

        net_lag = max(MIN_NET_LAG_DAYS, min(MAX_NET_LAG_DAYS, net_lag))

        return int(round(net_lag))

    except Exception as error:
        LOGGER.exception(
            "Error al calcular el retraso neto ajustado. Tipo: %s. Detalle: %s",
            type(error).__name__,
            error,
        )
        return int(base_lag_days)


# ACTUALIZACIÓN PARCHE: Health Check agregado (Requerimiento 5).
def get_data_health_report() -> Dict[str, str]:
    """
    Devuelve una copia del estado de salud de cada fuente de datos
    recolectada en la última ejecución de build_master_dataframe.

    Returns
    -------
    Dict[str, str]
        Mapa fuente -> 'OK' o 'ERROR - detalle'.
    """
    try:
        return dict(DATA_HEALTH)
    except Exception as error:
        LOGGER.exception(
            "Error al obtener el reporte de salud de datos. Tipo: %s. Detalle: %s",
            type(error).__name__,
            error,
        )
        return {}


def build_master_dataframe(
    api_key: str = FRED_API_KEY,
) -> Tuple[pd.DataFrame, Dict[str, str]]:
    """
    Descarga, alinea y procesa los datos de la aplicación macroeconómica.

    Si una fuente secundaria falla, se preservan los datos disponibles y la
    Liquidez_Global se calcula con los componentes que sí pudieron descargarse.

    ACTUALIZACIÓN PARCHE: ahora devuelve una tupla (DataFrame, health_report)
    en lugar de solo el DataFrame, para alimentar el panel de auditoría de
    app.py (Requerimiento 5). Cualquier código que llame a esta función debe
    desempaquetar la tupla.

    ACTUALIZACIÓN (Directriz 1): cada serie FRED/Yahoo (no cripto) ya llega
    aquí reindexada a calendario diario continuo y ffilleada de forma
    independiente desde la raíz (_prepare_fred_series /
    _prepare_yahoo_close_series), antes del outer merge - ver comentarios
    en ese módulo para el detalle exacto.

    Parameters
    ----------
    api_key : str, optional
        API key de FRED. Por defecto usa FRED_API_KEY de config.py.

    Returns
    -------
    Tuple[pd.DataFrame, Dict[str, str]]
        DataFrame Maestro listo para graficarse en Streamlit, y el reporte
        de salud de cada fuente de datos.
    """
    try:
        LOGGER.info("Iniciando construcción del DataFrame Maestro.")

        DATA_HEALTH.clear()  # ACTUALIZACIÓN PARCHE - reporte fresco por corrida

        fred_dataframes = _download_fred_dataframes(api_key=api_key)
        yahoo_dataframes = _download_yahoo_dataframes()

        # ACTUALIZACIÓN PARCHE: intento de traer historial real de USDT.D.
        # Si no hay COINGECKO_API_KEY configurada, esto devuelve un
        # DataFrame vacío y USDT.D queda como N/D (comportamiento honesto).
        usdt_dominance_dataframe = get_usdt_dominance_history()
        if not usdt_dominance_dataframe.empty:
            usdt_dominance_dataframe = _normalize_dates(usdt_dominance_dataframe)

        all_dataframes = fred_dataframes + yahoo_dataframes + [usdt_dominance_dataframe]

        if not all_dataframes:
            LOGGER.error(
                "No se generaron DataFrames desde FRED ni Yahoo Finance."
            )
            return _create_empty_master_dataframe(), get_data_health_report()

        master_dataframe = _outer_merge_and_align(all_dataframes)

        if master_dataframe.empty:
            LOGGER.warning(
                "No hay datos BTC válidos; se devuelve DataFrame Maestro vacío."
            )
            return _create_empty_master_dataframe(), get_data_health_report()

        master_dataframe = _calculate_component_scales(master_dataframe)
        master_dataframe = recalculate_liquidity(master_dataframe)

        for column in MASTER_COLUMNS:
            if column not in master_dataframe.columns:
                try:
                    if column == "Es_Pico":
                        master_dataframe[column] = False
                    elif column == "Date":
                        master_dataframe[column] = pd.NaT
                    else:
                        master_dataframe[column] = 0.0
                except Exception as error:
                    LOGGER.exception(
                        "Error creando columna faltante %s. Tipo: %s. Detalle: %s",
                        column,
                        type(error).__name__,
                        error,
                    )

        master_dataframe = master_dataframe.loc[:, MASTER_COLUMNS]
        master_dataframe = master_dataframe.sort_values(by="Date")
        master_dataframe = master_dataframe.reset_index(drop=True)

        LOGGER.info(
            "DataFrame Maestro finalizado correctamente. Filas: %s.",
            len(master_dataframe),
        )

        return master_dataframe, get_data_health_report()

    except Exception as error:
        LOGGER.exception(
            "Error crítico al construir el DataFrame Maestro. "
            "Tipo: %s. Detalle: %s",
            type(error).__name__,
            error,
        )
        return _create_empty_master_dataframe(), get_data_health_report()


if __name__ == "__main__":
    try:
        master_data, health_report = build_master_dataframe()

        print("\nPrimeras 5 filas del DataFrame Maestro:")
        print(master_data.head(5).to_string(index=False))

        print("\nÚltimas 5 filas del DataFrame Maestro:")
        print(master_data.tail(5).to_string(index=False))

        print(f"\nRegistros finales: {len(master_data)}")

        print("\nReporte de salud de fuentes de datos:")
        for source_name, status in health_report.items():
            print(f"  {source_name}: {status}")

        if "Es_Pico" in master_data.columns:
            print(
                "Picos de liquidez detectados: "
                f"{int(master_data['Es_Pico'].sum())}"
            )

    except Exception as error:
        LOGGER.exception(
            "Error en ejecución principal. Tipo: %s. Detalle: %s",
            type(error).__name__,
            error,
        )