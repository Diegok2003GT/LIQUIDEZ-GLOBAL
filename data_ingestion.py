"""
Módulo de descarga, validación y limpieza de datos desde FRED y Yahoo Finance.
"""

import logging
from typing import Dict, List, Optional

import pandas as pd
import requests
import yfinance as yf

from config import (
    COINGECKO_API_KEY,
    DEFILLAMA_STABLECOIN_HISTORY_URL,  # NUEVO: LIQUIDEZ AVANZADA
    DEFILLAMA_STABLECOINS_LIST_URL,  # NUEVO: LIQUIDEZ AVANZADA
    FRED_API_BASE_URL,
    FRED_API_KEY,
    FRED_SERIES,
    STABLECOIN_SYMBOLS_TRACKED,  # NUEVO: LIQUIDEZ AVANZADA
    YAHOO_TICKERS,
    YFINANCE_INTERVAL,
    YFINANCE_PERIOD,
)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

LOGGER = logging.getLogger(__name__)

# ACTUALIZACIÓN PARCHE: Registro de salud de las fuentes de datos
# (Requerimiento 5). Cada descarga exitosa o fallida actualiza este
# diccionario en memoria, que luego math_processor/app.py exponen en el
# panel de auditoría. No reemplaza el manejo de errores existente, solo lo
# observa desde afuera.
DATA_HEALTH: Dict[str, str] = {}


def _mark_health(source_label: str, ok: bool, detail: str = "") -> None:
    """
    Registra el estatus de una fuente de datos en DATA_HEALTH.

    Parameters
    ----------
    source_label : str
        Nombre legible de la fuente (ej. 'WALCL', 'BTC-USD').
    ok : bool
        True si la descarga fue exitosa y con datos.
    detail : str
        Detalle adicional en caso de error.
    """
    try:
        if ok:
            DATA_HEALTH[source_label] = "OK"
        else:
            DATA_HEALTH[source_label] = f"ERROR{f' - {detail}' if detail else ''}"
    except Exception as error:
        LOGGER.exception(
            "Error al registrar salud de %s. Tipo: %s. Detalle: %s",
            source_label,
            type(error).__name__,
            error,
        )


def _empty_fred_dataframe() -> pd.DataFrame:
    """
    Crea un DataFrame vacío con la estructura estándar para datos FRED.
    """
    try:
        return pd.DataFrame(
            {
                "Date": pd.Series(dtype="datetime64[ns]"),
                "Value": pd.Series(dtype="float64"),
            }
        )
    except Exception as error:
        LOGGER.exception(
            "Error inesperado al crear el DataFrame vacío de FRED. "
            "Tipo de error: %s. Detalle: %s",
            type(error).__name__,
            error,
        )
        return pd.DataFrame(columns=["Date", "Value"])


def _empty_yfinance_dataframe() -> pd.DataFrame:
    """
    Crea un DataFrame vacío con una columna Date para resultados de Yahoo Finance.
    """
    try:
        return pd.DataFrame(
            {
                "Date": pd.Series(dtype="datetime64[ns]"),
            }
        )
    except Exception as error:
        LOGGER.exception(
            "Error inesperado al crear el DataFrame vacío de Yahoo Finance. "
            "Tipo de error: %s. Detalle: %s",
            type(error).__name__,
            error,
        )
        return pd.DataFrame(columns=["Date"])


def _clean_fred_dataframe(dataframe: pd.DataFrame) -> pd.DataFrame:
    """
    Limpia y estandariza un DataFrame descargado desde FRED.

    Parameters
    ----------
    dataframe : pd.DataFrame
        DataFrame con las columnas Date y Value.

    Returns
    -------
    pd.DataFrame
        Datos limpios, sin duplicados, ordenados por fecha y con Value numérico.
    """
    try:
        if dataframe.empty:
            LOGGER.warning("El DataFrame de FRED está vacío; no hay datos que limpiar.")
            return _empty_fred_dataframe()

        cleaned_dataframe = dataframe.copy()

        if "Date" not in cleaned_dataframe.columns or "Value" not in cleaned_dataframe.columns:
            raise ValueError(
                "El DataFrame de FRED debe contener obligatoriamente las columnas "
                "'Date' y 'Value'."
            )

        cleaned_dataframe["Date"] = pd.to_datetime(
            cleaned_dataframe["Date"],
            errors="coerce",
        )
        cleaned_dataframe["Value"] = pd.to_numeric(
            cleaned_dataframe["Value"],
            errors="coerce",
        )

        cleaned_dataframe = cleaned_dataframe.dropna(subset=["Date", "Value"])
        cleaned_dataframe = cleaned_dataframe.drop_duplicates(subset=["Date"], keep="last")
        cleaned_dataframe = cleaned_dataframe.sort_values(by="Date")
        cleaned_dataframe = cleaned_dataframe.reset_index(drop=True)

        LOGGER.info(
            "Limpieza FRED completada correctamente. Registros válidos: %s.",
            len(cleaned_dataframe),
        )

        return cleaned_dataframe

    except Exception as error:
        LOGGER.exception(
            "Error al limpiar datos de FRED. "
            "Tipo de error: %s. Detalle: %s",
            type(error).__name__,
            error,
        )
        return _empty_fred_dataframe()


def _clean_yfinance_dataframe(dataframe: pd.DataFrame) -> pd.DataFrame:
    """
    Limpia y estandariza un DataFrame descargado desde Yahoo Finance.

    Parameters
    ----------
    dataframe : pd.DataFrame
        DataFrame histórico descargado mediante yfinance.

    Returns
    -------
    pd.DataFrame
        Datos limpios, sin duplicados y ordenados cronológicamente.
    """
    try:
        if dataframe.empty:
            LOGGER.warning(
                "El DataFrame de Yahoo Finance está vacío; no hay datos que limpiar."
            )
            return _empty_yfinance_dataframe()

        cleaned_dataframe = dataframe.copy()

        if isinstance(cleaned_dataframe.columns, pd.MultiIndex):
            cleaned_dataframe.columns = [
                "_".join(
                    str(level)
                    for level in column
                    if level is not None and str(level).strip()
                ).strip("_")
                for column in cleaned_dataframe.columns.to_flat_index()
            ]

        cleaned_dataframe = cleaned_dataframe.reset_index()

        possible_date_columns = ["Date", "Datetime", "index"]
        date_column: Optional[str] = next(
            (
                column
                for column in possible_date_columns
                if column in cleaned_dataframe.columns
            ),
            None,
        )

        if date_column is None:
            raise ValueError(
                "No fue posible localizar una columna de fecha tras descargar "
                "los datos de Yahoo Finance."
            )

        if date_column != "Date":
            cleaned_dataframe = cleaned_dataframe.rename(columns={date_column: "Date"})

        cleaned_dataframe["Date"] = pd.to_datetime(
            cleaned_dataframe["Date"],
            errors="coerce",
        )

        if hasattr(cleaned_dataframe["Date"].dt, "tz") and cleaned_dataframe["Date"].dt.tz is not None:
            cleaned_dataframe["Date"] = cleaned_dataframe["Date"].dt.tz_localize(None)

        cleaned_dataframe = cleaned_dataframe.dropna(subset=["Date"])
        cleaned_dataframe = cleaned_dataframe.drop_duplicates(subset=["Date"], keep="last")
        cleaned_dataframe = cleaned_dataframe.sort_values(by="Date")
        cleaned_dataframe = cleaned_dataframe.reset_index(drop=True)

        LOGGER.info(
            "Limpieza Yahoo Finance completada correctamente. Registros válidos: %s.",
            len(cleaned_dataframe),
        )

        return cleaned_dataframe

    except Exception as error:
        LOGGER.exception(
            "Error al limpiar datos de Yahoo Finance. "
            "Tipo de error: %s. Detalle: %s",
            type(error).__name__,
            error,
        )
        return _empty_yfinance_dataframe()


def get_fred_data(series_id: str, api_key: str) -> pd.DataFrame:
    """
    Descarga observaciones históricas de una serie desde la API oficial de FRED.

    Parameters
    ----------
    series_id : str
        Identificador FRED de la serie a descargar, por ejemplo: WALCL.
    api_key : str
        API key válida de FRED.

    Returns
    -------
    pd.DataFrame
        DataFrame con las columnas Date y Value.
        Ante un error, devuelve un DataFrame vacío con dicha estructura.
    """
    try:
        if not isinstance(series_id, str) or not series_id.strip():
            raise ValueError("series_id debe ser un texto no vacío.")

        if not isinstance(api_key, str) or not api_key.strip() or api_key == "TU_API_KEY_AQUI":
            raise ValueError(
                "La FRED_API_KEY no está configurada. Reemplaza "
                "'TU_API_KEY_AQUI' en config.py por una API key válida de FRED."
            )

        request_parameters = {
            "series_id": series_id.strip(),
            "api_key": api_key.strip(),
            "file_type": "json",
        }

        LOGGER.info("Iniciando descarga FRED para la serie: %s.", series_id)

        response = requests.get(
            FRED_API_BASE_URL,
            params=request_parameters,
            timeout=30,
        )
        response.raise_for_status()

        response_data = response.json()

        if "error_message" in response_data:
            raise RuntimeError(
                f"FRED respondió con un error: {response_data['error_message']}"
            )

        observations = response_data.get("observations")

        if observations is None:
            raise ValueError(
                "La respuesta de FRED no contiene la clave 'observations'. "
                f"Respuesta recibida: {response_data}"
            )

        fred_dataframe = pd.DataFrame(observations)

        if fred_dataframe.empty:
            LOGGER.warning(
                "FRED no devolvió observaciones para la serie %s.",
                series_id,
            )
            _mark_health(series_id, ok=False, detail="sin observaciones")  # ACTUALIZACIÓN PARCHE
            return _empty_fred_dataframe()

        fred_dataframe = fred_dataframe.rename(
            columns={
                "date": "Date",
                "value": "Value",
            }
        )

        cleaned_dataframe = _clean_fred_dataframe(fred_dataframe)

        # ACTUALIZACIÓN PARCHE: registro de salud de la fuente.
        _mark_health(series_id, ok=not cleaned_dataframe.empty)

        LOGGER.info(
            "Descarga FRED finalizada para %s. Filas descargadas: %s.",
            series_id,
            len(cleaned_dataframe),
        )

        return cleaned_dataframe

    except requests.exceptions.Timeout as error:
        LOGGER.exception(
            "Tiempo de espera agotado al descargar FRED (%s). "
            "Verifica tu conexión a internet. Detalle: %s",
            series_id,
            error,
        )
        _mark_health(series_id, ok=False, detail="timeout")  # ACTUALIZACIÓN PARCHE
        return _empty_fred_dataframe()

    except requests.exceptions.HTTPError as error:
        response_text = ""
        try:
            response_text = error.response.text
        except Exception as response_error:
            LOGGER.exception(
                "No fue posible leer el contenido de la respuesta HTTP de FRED. "
                "Tipo de error: %s. Detalle: %s",
                type(response_error).__name__,
                response_error,
            )

        LOGGER.exception(
            "Error HTTP al descargar FRED (%s). "
            "Estado HTTP: %s. Respuesta: %s",
            series_id,
            getattr(error.response, "status_code", "desconocido"),
            response_text,
        )
        _mark_health(series_id, ok=False, detail="HTTP error")  # ACTUALIZACIÓN PARCHE
        return _empty_fred_dataframe()

    except requests.exceptions.RequestException as error:
        LOGGER.exception(
            "Error de red al descargar FRED (%s). "
            "Tipo de error: %s. Detalle: %s",
            series_id,
            type(error).__name__,
            error,
        )
        _mark_health(series_id, ok=False, detail="red")  # ACTUALIZACIÓN PARCHE
        return _empty_fred_dataframe()

    except ValueError as error:
        LOGGER.exception(
            "Error de validación o formato al procesar FRED (%s). Detalle: %s",
            series_id,
            error,
        )
        _mark_health(series_id, ok=False, detail="validación")  # ACTUALIZACIÓN PARCHE
        return _empty_fred_dataframe()

    except Exception as error:
        LOGGER.exception(
            "Error inesperado al descargar FRED (%s). "
            "Tipo de error: %s. Detalle: %s",
            series_id,
            type(error).__name__,
            error,
        )
        _mark_health(series_id, ok=False, detail="inesperado")  # ACTUALIZACIÓN PARCHE
        return _empty_fred_dataframe()


def get_yfinance_data(ticker: str) -> pd.DataFrame:
    """
    Descarga datos históricos diarios de los últimos tres años desde Yahoo Finance.

    Parameters
    ----------
    ticker : str
        Ticker de Yahoo Finance, por ejemplo: BTC-USD.

    Returns
    -------
    pd.DataFrame
        DataFrame histórico limpio con Date, Open, High, Low, Close,
        Adj Close y Volume cuando estén disponibles.
        Ante un error, devuelve un DataFrame vacío con columna Date.
    """
    try:
        if not isinstance(ticker, str) or not ticker.strip():
            raise ValueError("ticker debe ser un texto no vacío.")

        normalized_ticker = ticker.strip().upper()

        LOGGER.info(
            "Iniciando descarga Yahoo Finance para %s, periodo=%s, intervalo=%s.",
            normalized_ticker,
            YFINANCE_PERIOD,
            YFINANCE_INTERVAL,
        )

        yahoo_dataframe = yf.download(
            tickers=normalized_ticker,
            period=YFINANCE_PERIOD,
            interval=YFINANCE_INTERVAL,
            auto_adjust=False,
            progress=False,
            threads=False,
        )

        if yahoo_dataframe.empty:
            raise ValueError(
                f"Yahoo Finance no devolvió datos para el ticker '{normalized_ticker}'. "
                "Verifica que el símbolo exista y que Yahoo Finance esté disponible."
            )

        cleaned_dataframe = _clean_yfinance_dataframe(yahoo_dataframe)

        # ACTUALIZACIÓN PARCHE: registro de salud de la fuente.
        _mark_health(normalized_ticker, ok=not cleaned_dataframe.empty)

        LOGGER.info(
            "Descarga Yahoo Finance finalizada para %s. Filas descargadas: %s.",
            normalized_ticker,
            len(cleaned_dataframe),
        )

        return cleaned_dataframe

    except ValueError as error:
        LOGGER.exception(
            "Error de validación o disponibilidad al descargar Yahoo Finance (%s). "
            "Detalle: %s",
            ticker,
            error,
        )
        _mark_health(str(ticker).upper(), ok=False, detail="validación")  # ACTUALIZACIÓN PARCHE
        return _empty_yfinance_dataframe()

    except Exception as error:
        LOGGER.exception(
            "Error inesperado al descargar Yahoo Finance (%s). "
            "Tipo de error: %s. Detalle: %s",
            ticker,
            type(error).__name__,
            error,
        )
        _mark_health(str(ticker).upper(), ok=False, detail="inesperado")  # ACTUALIZACIÓN PARCHE
        return _empty_yfinance_dataframe()


# ACTUALIZACIÓN PARCHE: descarga opcional del historial de dominancia de
# USDT (Requerimiento 3). IMPORTANTE - lee esto antes de asumir que ya
# funciona:
#
# El endpoint gratuito de CoinGecko NO entrega historial de market cap
# global (solo el valor actual). El historial diario real de dominancia
# requiere el endpoint Pro "/global/market_cap_chart", que exige una
# COINGECKO_API_KEY de pago. Si no configuras esa variable de entorno,
# esta función devuelve un DataFrame vacío a propósito (no inventa datos) y
# USDT.D seguirá mostrando "N/D", igual que antes del parche.
#
# Si sí tienes una key de CoinGecko Pro, defínela como variable de entorno
# COINGECKO_API_KEY y esta función la usará automáticamente.
COINGECKO_GLOBAL_CHART_URL = "https://pro-api.coingecko.com/api/v3/global/market_cap_chart"
COINGECKO_TETHER_CHART_URL = "https://pro-api.coingecko.com/api/v3/coins/tether/market_chart"


def get_usdt_dominance_history(api_key: str = COINGECKO_API_KEY) -> pd.DataFrame:
    """
    Descarga el historial real de dominancia de mercado de USDT (USDT.D).

    Requiere una API key de CoinGecko Pro. Sin ella, devuelve un DataFrame
    vacío de forma explícita en lugar de aproximar el dato con el precio de
    USDT, que no representa su dominancia de mercado.

    Parameters
    ----------
    api_key : str
        API key de CoinGecko Pro. Por defecto usa COINGECKO_API_KEY de
        config.py.

    Returns
    -------
    pd.DataFrame
        Columnas Date y USDT_Dominance (en porcentaje). Vacío si no hay key
        configurada o si la descarga falla.
    """
    try:
        if not isinstance(api_key, str) or not api_key.strip():
            LOGGER.info(
                "COINGECKO_API_KEY no configurada; USDT.D permanecerá como N/D."
            )
            _mark_health("USDT.D", ok=False, detail="sin API key de CoinGecko")  # ACTUALIZACIÓN PARCHE
            return pd.DataFrame(columns=["Date", "USDT_Dominance"])

        headers = {"x-cg-pro-api-key": api_key.strip()}

        global_response = requests.get(
            COINGECKO_GLOBAL_CHART_URL,
            params={"days": "365"},
            headers=headers,
            timeout=30,
        )
        global_response.raise_for_status()
        global_market_cap = global_response.json().get("market_cap_chart", {}).get(
            "market_cap", []
        )

        tether_response = requests.get(
            COINGECKO_TETHER_CHART_URL,
            params={"vs_currency": "usd", "days": "365", "interval": "daily"},
            headers=headers,
            timeout=30,
        )
        tether_response.raise_for_status()
        tether_market_cap = tether_response.json().get("market_caps", [])

        if not global_market_cap or not tether_market_cap:
            raise ValueError("CoinGecko no devolvió datos suficientes para USDT.D.")

        global_dataframe = pd.DataFrame(
            global_market_cap, columns=["Timestamp", "Global_Market_Cap"]
        )
        tether_dataframe = pd.DataFrame(
            tether_market_cap, columns=["Timestamp", "USDT_Market_Cap"]
        )

        global_dataframe["Date"] = pd.to_datetime(
            global_dataframe["Timestamp"], unit="ms", errors="coerce"
        ).dt.normalize()
        tether_dataframe["Date"] = pd.to_datetime(
            tether_dataframe["Timestamp"], unit="ms", errors="coerce"
        ).dt.normalize()

        merged_dataframe = pd.merge(
            global_dataframe[["Date", "Global_Market_Cap"]],
            tether_dataframe[["Date", "USDT_Market_Cap"]],
            on="Date",
            how="inner",
        )

        merged_dataframe = merged_dataframe.dropna()
        merged_dataframe = merged_dataframe[merged_dataframe["Global_Market_Cap"] > 0]

        merged_dataframe["USDT_Dominance"] = (
            merged_dataframe["USDT_Market_Cap"] / merged_dataframe["Global_Market_Cap"]
        ) * 100.0

        result_dataframe = merged_dataframe[["Date", "USDT_Dominance"]].copy()
        result_dataframe = result_dataframe.drop_duplicates(subset=["Date"], keep="last")
        result_dataframe = result_dataframe.sort_values(by="Date").reset_index(drop=True)

        _mark_health("USDT.D", ok=not result_dataframe.empty)  # ACTUALIZACIÓN PARCHE

        LOGGER.info(
            "Historial de USDT.D descargado. Registros: %s.", len(result_dataframe)
        )

        return result_dataframe

    except Exception as error:
        LOGGER.exception(
            "Error al descargar historial de USDT.D. Tipo: %s. Detalle: %s",
            type(error).__name__,
            error,
        )
        _mark_health("USDT.D", ok=False, detail=type(error).__name__)  # ACTUALIZACIÓN PARCHE
        return pd.DataFrame(columns=["Date", "USDT_Dominance"])


# NUEVO: LIQUIDEZ AVANZADA - historial de capitalización de stablecoins
# (DefiLlama), usado en la fórmula de Liquidez de Corto Plazo, y también
# para calcular una dominancia real de USDT sobre stablecoins (ver
# get_usdt_stablecoin_dominance_history) que reemplaza el "N/D" permanente
# del semáforo cuando no hay COINGECKO_API_KEY.
def _resolve_stablecoin_ids(symbols: List[str]) -> Dict[str, str]:
    """
    Resuelve dinámicamente el ID interno de DefiLlama para cada símbolo de
    stablecoin solicitado (ej. 'USDT' -> '1'). No se hardcodean IDs: se
    consultan en tiempo real contra /stablecoins para evitar sumar la
    moneda equivocada si DefiLlama reordena o cambia sus IDs internos.

    Parameters
    ----------
    symbols : List[str]
        Símbolos a resolver, ej. ["USDT", "USDC", "DAI", "FDUSD"].

    Returns
    -------
    Dict[str, str]
        Mapa símbolo -> id de DefiLlama. Los símbolos no encontrados se omiten.
    """
    try:
        response = requests.get(DEFILLAMA_STABLECOINS_LIST_URL, timeout=30)
        response.raise_for_status()
        payload = response.json()

        pegged_assets = payload.get("peggedAssets", [])

        if not pegged_assets:
            raise ValueError("DefiLlama no devolvió la lista de stablecoins.")

        symbol_to_id: Dict[str, str] = {}
        wanted = {symbol.upper() for symbol in symbols}

        for asset in pegged_assets:
            asset_symbol = str(asset.get("symbol", "")).upper()
            asset_id = asset.get("id")
            if asset_symbol in wanted and asset_id is not None:
                symbol_to_id[asset_symbol] = str(asset_id)

        missing = wanted - set(symbol_to_id.keys())
        if missing:
            LOGGER.warning(
                "No se pudieron resolver los IDs de DefiLlama para: %s.",
                missing,
            )

        _mark_health("DefiLlama:stablecoins_list", ok=bool(symbol_to_id))

        return symbol_to_id

    except Exception as error:
        LOGGER.exception(
            "Error al resolver IDs de stablecoins en DefiLlama. "
            "Tipo: %s. Detalle: %s",
            type(error).__name__,
            error,
        )
        _mark_health("DefiLlama:stablecoins_list", ok=False, detail=type(error).__name__)
        return {}


def _get_single_stablecoin_history(stablecoin_id: str, symbol: str) -> pd.DataFrame:
    """
    Descarga el historial de capitalización circulante (en USD) de una
    stablecoin específica desde DefiLlama.

    Parameters
    ----------
    stablecoin_id : str
        ID interno de DefiLlama para la moneda (resuelto dinámicamente).
    symbol : str
        Símbolo, solo para logging/health check (ej. "USDT").

    Returns
    -------
    pd.DataFrame
        Columnas Date y <symbol>_MCap. Vacío si la descarga falla.
    """
    try:
        url = f"{DEFILLAMA_STABLECOIN_HISTORY_URL}/{stablecoin_id}"
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        payload = response.json()

        # NOTA DE ROBUSTEZ: la forma exacta del campo histórico en la
        # respuesta de DefiLlama puede variar (lo he visto documentado como
        # "tokens" a nivel raíz). Se prueban las variantes conocidas en
        # orden, y si ninguna aparece, se falla de forma controlada (nunca
        # se inventa un historial).
        history_records = (
            payload.get("tokens")
            or payload.get("chainBalances", {}).get("total", {}).get("tokens")
            or []
        )

        if not history_records:
            raise ValueError(
                f"La respuesta de DefiLlama para {symbol} (id={stablecoin_id}) "
                "no trae un historial reconocible."
            )

        rows = []
        for record in history_records:
            timestamp = record.get("date")
            circulating = record.get("circulating", {})
            mcap_usd = (
                circulating.get("peggedUSD")
                if isinstance(circulating, dict)
                else None
            )
            if timestamp is not None and mcap_usd is not None:
                rows.append({"Date": timestamp, f"{symbol}_MCap": mcap_usd})

        if not rows:
            raise ValueError(
                f"No se encontraron puntos válidos de circulating.peggedUSD para {symbol}."
            )

        history_dataframe = pd.DataFrame(rows)
        history_dataframe["Date"] = pd.to_datetime(
            history_dataframe["Date"], unit="s", errors="coerce"
        ).dt.normalize()
        history_dataframe = history_dataframe.dropna(subset=["Date"])
        history_dataframe = history_dataframe.drop_duplicates(subset=["Date"], keep="last")
        history_dataframe = history_dataframe.sort_values(by="Date").reset_index(drop=True)

        _mark_health(f"DefiLlama:{symbol}", ok=not history_dataframe.empty)

        return history_dataframe

    except Exception as error:
        LOGGER.exception(
            "Error al descargar historial de %s (DefiLlama). Tipo: %s. Detalle: %s",
            symbol,
            type(error).__name__,
            error,
        )
        _mark_health(f"DefiLlama:{symbol}", ok=False, detail=type(error).__name__)
        return pd.DataFrame(columns=["Date", f"{symbol}_MCap"])


def get_stablecoin_market_cap_history(
    symbols: Optional[List[str]] = None,
) -> pd.DataFrame:
    """
    Descarga y suma el historial de capitalización circulante (USD) de las
    stablecoins solicitadas (por defecto STABLECOIN_SYMBOLS_TRACKED: USDT,
    USDC, DAI, FDUSD), vía la API pública y gratuita de DefiLlama.

    Fault-tolerant: si una moneda individual falla, las demás se siguen
    sumando (igual que el resto del pipeline de FRED/Yahoo). Si todas
    fallan, devuelve un DataFrame vacío (nunca inventa una cifra).

    Parameters
    ----------
    symbols : Optional[List[str]]
        Lista de símbolos a sumar. Por defecto STABLECOIN_SYMBOLS_TRACKED.

    Returns
    -------
    pd.DataFrame
        Columnas: Date, Stablecoin_MCap_USD (suma de las monedas
        disponibles), y una columna por moneda individual (ej. USDT_MCap)
        para poder calcular dominancia de USDT sobre stablecoins.
    """
    try:
        target_symbols = symbols or STABLECOIN_SYMBOLS_TRACKED
        symbol_to_id = _resolve_stablecoin_ids(target_symbols)

        if not symbol_to_id:
            LOGGER.warning(
                "No se resolvió ningún ID de stablecoin; se devuelve historial vacío."
            )
            return pd.DataFrame(columns=["Date", "Stablecoin_MCap_USD"])

        per_coin_dataframes: List[pd.DataFrame] = []
        for symbol, stablecoin_id in symbol_to_id.items():
            coin_dataframe = _get_single_stablecoin_history(stablecoin_id, symbol)
            if not coin_dataframe.empty:
                per_coin_dataframes.append(coin_dataframe)

        if not per_coin_dataframes:
            LOGGER.warning(
                "Ninguna stablecoin individual devolvió historial; se "
                "devuelve DataFrame vacío (no se inventa un valor)."
            )
            return pd.DataFrame(columns=["Date", "Stablecoin_MCap_USD"])

        merged_dataframe: Optional[pd.DataFrame] = None
        for coin_dataframe in per_coin_dataframes:
            if merged_dataframe is None:
                merged_dataframe = coin_dataframe
            else:
                merged_dataframe = pd.merge(
                    merged_dataframe, coin_dataframe, on="Date", how="outer"
                )

        merged_dataframe = merged_dataframe.sort_values(by="Date").reset_index(drop=True)

        mcap_columns = [
            column for column in merged_dataframe.columns if column.endswith("_MCap")
        ]
        merged_dataframe[mcap_columns] = merged_dataframe[mcap_columns].ffill()
        merged_dataframe["Stablecoin_MCap_USD"] = merged_dataframe[mcap_columns].sum(
            axis=1, skipna=True
        )

        LOGGER.info(
            "Historial de stablecoins listo. Monedas incluidas: %s. Registros: %s.",
            list(symbol_to_id.keys()),
            len(merged_dataframe),
        )

        return merged_dataframe

    except Exception as error:
        LOGGER.exception(
            "Error al construir historial de capitalización de stablecoins. "
            "Tipo: %s. Detalle: %s",
            type(error).__name__,
            error,
        )
        return pd.DataFrame(columns=["Date", "Stablecoin_MCap_USD"])


def get_usdt_stablecoin_dominance_history(
    stablecoin_dataframe: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """
    NUEVO: LIQUIDEZ AVANZADA - reemplazo honesto del "N/D" permanente del
    semáforo de USDT.D cuando no hay COINGECKO_API_KEY.

    IMPORTANTE - esto NO es lo mismo que "USDT.D" en el sentido clásico
    (dominancia de USDT sobre TODO el mercado cripto, incluyendo BTC, ETH,
    etc.). Es la dominancia de USDT sobre el total de STABLECOINS
    rastreadas (USDT+USDC+DAI+FDUSD) - una métrica relacionada pero
    distinta, calculable 100% gratis con los mismos datos de DefiLlama que
    ya se descargan para la fórmula de Corto Plazo. Se etiqueta así de
    forma explícita en la interfaz para no confundirla con la definición
    clásica.

    Parameters
    ----------
    stablecoin_dataframe : Optional[pd.DataFrame]
        Resultado de get_stablecoin_market_cap_history(). Si es None, se
        descarga de nuevo.

    Returns
    -------
    pd.DataFrame
        Columnas Date y USDT_Stablecoin_Dominance (en porcentaje).
    """
    try:
        dataframe = (
            stablecoin_dataframe
            if stablecoin_dataframe is not None
            else get_stablecoin_market_cap_history()
        )

        if dataframe.empty or "USDT_MCap" not in dataframe.columns:
            return pd.DataFrame(columns=["Date", "USDT_Stablecoin_Dominance"])

        result_dataframe = dataframe.loc[:, ["Date"]].copy()
        result_dataframe["USDT_Stablecoin_Dominance"] = (
            dataframe["USDT_MCap"] / dataframe["Stablecoin_MCap_USD"]
        ) * 100.0
        result_dataframe = result_dataframe.dropna()

        return result_dataframe

    except Exception as error:
        LOGGER.exception(
            "Error al calcular dominancia de USDT sobre stablecoins. "
            "Tipo: %s. Detalle: %s",
            type(error).__name__,
            error,
        )
        return pd.DataFrame(columns=["Date", "USDT_Stablecoin_Dominance"])


if __name__ == "__main__":
    try:
        LOGGER.info("Ejecutando prueba de conexión con FRED: WALCL.")
        walcl_data = get_fred_data(
            series_id=FRED_SERIES["FED_BALANCE_SHEET"],
            api_key=FRED_API_KEY,
        )

        print("\nPrimeras 5 filas de WALCL:")
        print(walcl_data.head(5).to_string(index=False))

    except Exception as error:
        LOGGER.exception(
            "Error en la prueba principal de WALCL. "
            "Tipo de error: %s. Detalle: %s",
            type(error).__name__,
            error,
        )

    try:
        LOGGER.info("Ejecutando prueba de conexión con Yahoo Finance: BTC-USD.")
        btc_data = get_yfinance_data(
            ticker=YAHOO_TICKERS["BITCOIN"],
        )

        print("\nPrimeras 5 filas de BTC-USD:")
        print(btc_data.head(5).to_string(index=False))

    except Exception as error:
        LOGGER.exception(
            "Error en la prueba principal de BTC-USD. "
            "Tipo de error: %s. Detalle: %s",
            type(error).__name__,
            error,
        )