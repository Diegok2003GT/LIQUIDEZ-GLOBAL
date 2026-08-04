"""
Módulo de descarga, validación y limpieza de datos desde FRED y Yahoo Finance.

AUDITORÍA (Directriz 1 - Eliminación de Yahoo Finance para FX): los tipos de
cambio EUR/USD, CNY/USD y JPY/USD ya NO se descargan desde Yahoo Finance
(antes "EURUSD=X", "CNYUSD=X", "JPY=X" en config.YAHOO_TICKERS). Las tres
series ahora se obtienen exclusivamente vía get_fred_data() (más abajo, sin
cambios funcionales) usando los tickers oficiales de FRED (DEXUSEU, DEXCHUS,
DEXJPUS, ver config.FRED_SERIES). get_yfinance_data() se conserva sin
cambios funcionales: sigue siendo la única fuente para DXY, BTC-USD,
SOL-USD y USDT-USD, que no tienen un equivalente EXACTO gratuito en FRED.

AUDITORÍA QUANT (historial de 10+ años, núcleo activo: EE. UU., Europa/BCE,
DXY, US10Y, MVRV):
  1. Joins: get_stablecoin_market_cap_history() ya usaba how="outer" (sin
     cambios). get_usdt_dominance_history() SÍ tenía un how="inner" al
     cruzar el market cap global con el de USDT (ambos de CoinGecko) -
     corregido aquí a how="outer" + ffill, para que un desalineamiento
     puntual entre las dos llamadas a CoinGecko no elimine la fecha
     completa del historial de USDT.D. NOTA DE ALCANCE: USDT.D no forma
     parte del núcleo activo (US/Europa/DXY/US10Y/MVRV) y su propia
     ventana de descarga sigue acotada a 365 días por el parámetro `days`
     de la API de CoinGecko - esta corrección solo evita una pérdida de
     datos adicional e innecesaria dentro de esa ventana, no la amplía.
  2. Filtros ocultos de fecha en FRED: se revisó get_fred_data() y el
     diccionario `request_parameters` que arma - NO se envía
     `observation_start`, `observation_end` ni ningún parámetro de
     fecha o `limit` a la API de FRED (ver la función más abajo). Por
     defecto, FRED devuelve el historial COMPLETO de la serie (para
     WALCL, TGA/WTREGEN, RRP/RRPONTSYD y DEXUSEU eso significa décadas de
     historia real). No se encontró ningún `start_date` ni límite de
     fecha hardcodeado en este archivo ni en config.py para estas cuatro
     series.

CORRECCIÓN DE ERROR (recorte visual del gráfico al año ~2023 en Plotly):
  1. YFINANCE_PERIOD ya NO es "3y": ahora es "max" (ver config.py). Con
     esto, get_yfinance_data() descarga toda la historia real disponible
     de BTC-USD, SOL-USD, USDT-USD y DXY (DX-Y.NYB) sin inventar ni
     recortar ningún dato - cada serie trae exactamente lo que Yahoo
     Finance tiene registrado desde su propio primer día de cotización.
  2. DXY (Yahoo, "DX-Y.NYB") sigue siendo la única fuente para el índice
     ICE DXY exacto - no existe un sustituto gratuito idéntico en FRED
     (DTWEXBGS es una canasta y metodología distinta, no un reemplazo).
     En vez de sustituirlo en silencio, se agregó DTWEXBGS como una
     SEGUNDA columna independiente (DXY_FRED, ver math_processor.py) que
     convive con DXY sin recortarlo ni reemplazarlo - así el análisis del
     dólar tiene tanto el ticker de mercado de corto plazo (DXY) como
     20+ años de historia gratuita (DXY_FRED).
"""

import io  # NUEVO: INDICADOR LIQGLOB - parseo de CSV devuelto por la API del BCE
import logging
import os
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import requests
import yfinance as yf

from config import (
    BGEOMETRICS_API_KEY,  # NUEVO: PANEL MACRO-BITCOIN AVANZADO
    COINGECKO_API_KEY,
    DEFILLAMA_STABLECOIN_HISTORY_URL,  # NUEVO: LIQUIDEZ AVANZADA
    DEFILLAMA_STABLECOINS_LIST_URL,  # NUEVO: LIQUIDEZ AVANZADA
    ECB_LIQUIDITY_FLOW_REF,  # NUEVO: INDICADOR LIQGLOB
    ECB_LIQUIDITY_SERIES_KEY,  # NUEVO: INDICADOR LIQGLOB
    ECB_SDW_BASE_URL,  # NUEVO: INDICADOR LIQGLOB
    FRED_API_BASE_URL,
    FRED_API_KEY,
    FRED_SERIES,
    MVRV_CACHE_DIR,  # ACTUALIZACIÓN: Directriz 3 - cache local MVRV
    MVRV_CACHE_FILE_PATH,  # ACTUALIZACIÓN: Directriz 3 - cache local MVRV
    MVRV_CACHE_TTL_SECONDS,  # ACTUALIZACIÓN: Directriz 3 - cache local MVRV
    MVRV_ZSCORE_API_URL,  # NUEVO: PANEL MACRO-BITCOIN AVANZADO
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

    AUDITORÍA (Directriz 1): esta función es genérica por `series_id` y no
    necesitó ningún cambio para soportar la migración de FX de Yahoo Finance
    a FRED - simplemente ahora también se le pasan los tickers DEXUSEU,
    DEXCHUS y DEXJPUS desde math_processor.py, igual que cualquier otra
    serie FRED (WALCL, ECBASSETSW, etc.).

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


# NUEVO: INDICADOR LIQGLOB - descarga de la serie oficial de Liquidez
# Excedentaria de la Eurozona directamente desde la API pública del BCE
# (ECB Data Portal / SDW API), sin API key. Esta serie (ILM.D.U2.C.EXLIQ.
# U2.EUR) es distinta de ECBASSETSW (la que ya usa la Liquidez Global
# Combinada, vía FRED) - se pidió explícitamente esta otra serie, tomada
# de la fuente oficial del BCE, no de FRED.
#
# CORRECCIÓN DE ERROR (Health Check mostraba "ERROR - sin datos todavía"
# incluso cuando la descarga sí funcionaba): esta función se invoca desde
# app.py en una llamada cacheada SEPARADA de load_master_dataframe()
# (build_master_dataframe(), que es la que arma `health_report`). Como
# `health_report` es una FOTO tomada ANTES de que esta función se
# ejecute, nunca llegaba a reflejar su resultado real - exactamente el
# mismo problema ya documentado y corregido para el MVRV Z-Score (ver
# get_mvrv_zscore_history). La corrección es la misma: en vez de que la
# interfaz dependa de DATA_HEALTH/health_report para esta fuente, la
# función devuelve su propio estado real en el segundo elemento de la
# tupla - la UI lo lee directo de aquí, sin importar el orden de llamadas
# entre pestañas/cachés. DATA_HEALTH se sigue actualizando igual (por si
# algún otro consumidor lo necesita), pero ya no es la fuente de verdad
# para el Health Check de esta serie.
def get_ecb_liquidity_data(
    flow_ref: str = ECB_LIQUIDITY_FLOW_REF,
    series_key: str = ECB_LIQUIDITY_SERIES_KEY,
) -> Tuple[pd.DataFrame, str]:
    """
    Descarga observaciones históricas de una serie del BCE (ECB Data
    Portal / SDW API), en formato CSV, y las estandariza a la misma
    estructura Date/Value que get_fred_data() (reutiliza los mismos
    helpers de limpieza, sin duplicar esa lógica).

    Parameters
    ----------
    flow_ref : str
        Flujo (dataflow) del BCE, por ejemplo "ILM". Por defecto
        ECB_LIQUIDITY_FLOW_REF de config.py.
    series_key : str
        Clave de la serie dentro de ese flujo, por ejemplo
        "D.U2.C.EXLIQ.U2.EUR". Por defecto ECB_LIQUIDITY_SERIES_KEY.

    Returns
    -------
    Tuple[pd.DataFrame, str]
        DataFrame con las columnas Date y Value (mismo formato que
        get_fred_data; vacío ante cualquier error - nunca se inventa un
        valor), y el estado REAL de esta descarga ("OK" o
        "ERROR - detalle"), listo para mostrarse tal cual en el Health
        Check sin depender de ningún diccionario global.
    """
    health_label = f"{flow_ref}.{series_key}"

    try:
        if not isinstance(flow_ref, str) or not flow_ref.strip():
            raise ValueError("flow_ref debe ser un texto no vacío.")
        if not isinstance(series_key, str) or not series_key.strip():
            raise ValueError("series_key debe ser un texto no vacío.")

        request_url = f"{ECB_SDW_BASE_URL}/{flow_ref.strip()}/{series_key.strip()}"
        request_parameters = {"format": "csvdata"}

        LOGGER.info(
            "Iniciando descarga ECB SDW para la serie: %s.", health_label
        )

        response = requests.get(
            request_url,
            params=request_parameters,
            headers={"Accept": "text/csv"},
            timeout=30,
        )
        response.raise_for_status()

        raw_text = response.text

        if not raw_text or not raw_text.strip():
            raise ValueError(
                "La API del BCE devolvió una respuesta vacía para "
                f"{health_label}."
            )

        csv_dataframe = pd.read_csv(io.StringIO(raw_text))

        if csv_dataframe.empty:
            LOGGER.warning(
                "El BCE no devolvió observaciones para la serie %s.",
                health_label,
            )
            _mark_health(health_label, ok=False, detail="sin observaciones")
            return _empty_fred_dataframe(), "ERROR - sin observaciones"

        # La API del BCE puede devolver las columnas en distinto orden o
        # con mayúsculas/minúsculas distintas según el dataflow - se
        # busca TIME_PERIOD/OBS_VALUE de forma flexible, sin asumir un
        # orden fijo de columnas.
        column_lookup = {
            str(column).strip().upper(): column for column in csv_dataframe.columns
        }
        time_column = column_lookup.get("TIME_PERIOD")
        value_column = column_lookup.get("OBS_VALUE")

        if time_column is None or value_column is None:
            raise ValueError(
                "La respuesta CSV del BCE no contiene las columnas "
                "esperadas TIME_PERIOD/OBS_VALUE para "
                f"{health_label}. Columnas recibidas: "
                f"{list(csv_dataframe.columns)}"
            )

        renamed_dataframe = csv_dataframe.rename(
            columns={time_column: "Date", value_column: "Value"}
        )[["Date", "Value"]]

        cleaned_dataframe = _clean_fred_dataframe(renamed_dataframe)

        download_ok = not cleaned_dataframe.empty
        _mark_health(health_label, ok=download_ok)

        LOGGER.info(
            "Descarga ECB SDW finalizada para %s. Filas descargadas: %s.",
            health_label,
            len(cleaned_dataframe),
        )

        status = "OK" if download_ok else "ERROR - datos no aprovechables tras la limpieza"
        return cleaned_dataframe, status

    except requests.exceptions.Timeout as error:
        LOGGER.exception(
            "Tiempo de espera agotado al descargar del BCE (%s). "
            "Verifica tu conexión a internet. Detalle: %s",
            health_label,
            error,
        )
        _mark_health(health_label, ok=False, detail="timeout")
        return _empty_fred_dataframe(), "ERROR - timeout"

    except requests.exceptions.HTTPError as error:
        status_code = getattr(error.response, "status_code", "desconocido")
        LOGGER.exception(
            "Error HTTP al descargar del BCE (%s). Estado HTTP: %s.",
            health_label,
            status_code,
        )
        _mark_health(health_label, ok=False, detail="HTTP error")
        return _empty_fred_dataframe(), f"ERROR - HTTP {status_code}"

    except requests.exceptions.RequestException as error:
        LOGGER.exception(
            "Error de red al descargar del BCE (%s). Tipo de error: %s. "
            "Detalle: %s",
            health_label,
            type(error).__name__,
            error,
        )
        _mark_health(health_label, ok=False, detail="red")
        return _empty_fred_dataframe(), "ERROR - red"

    except ValueError as error:
        LOGGER.exception(
            "Error de validación o formato al procesar datos del BCE "
            "(%s). Detalle: %s",
            health_label,
            error,
        )
        _mark_health(health_label, ok=False, detail="validación")
        return _empty_fred_dataframe(), f"ERROR - {error}"

    except Exception as error:
        LOGGER.exception(
            "Error inesperado al descargar del BCE (%s). Tipo de error: "
            "%s. Detalle: %s",
            health_label,
            type(error).__name__,
            error,
        )
        _mark_health(health_label, ok=False, detail="inesperado")
        return _empty_fred_dataframe(), f"ERROR - {type(error).__name__}"


def get_yfinance_data(ticker: str) -> pd.DataFrame:
    """
    Descarga el historial diario completo disponible desde Yahoo Finance.

    AUDITORÍA (Directriz 1): tras la migración de FX a FRED, esta función ya
    solo se invoca para DX-Y.NYB (DXY), BTC-USD, SOL-USD y USDT-USD - ninguno
    tiene un equivalente EXACTO gratuito en FRED.

    CORRECCIÓN DE ERROR (recorte visual del gráfico al año ~2023):
    YFINANCE_PERIOD ya no es "3y" - ahora es "max" (config.py), así que
    esta función descarga toda la historia real de cada ticker desde su
    propio primer día de cotización en Yahoo Finance, sin ningún recorte
    de ventana fijo.

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
            LOGGER.warning(
                "Yahoo Finance no devolvió datos para el ticker %s.",
                normalized_ticker,
            )
            _mark_health(normalized_ticker, ok=False, detail="sin datos")  # ACTUALIZACIÓN PARCHE
            return _empty_yfinance_dataframe()

        cleaned_dataframe = _clean_yfinance_dataframe(yahoo_dataframe)

        # ACTUALIZACIÓN PARCHE: registro de salud de la fuente.
        _mark_health(normalized_ticker, ok=not cleaned_dataframe.empty)

        LOGGER.info(
            "Descarga Yahoo Finance finalizada para %s. Filas descargadas: %s.",
            normalized_ticker,
            len(cleaned_dataframe),
        )

        return cleaned_dataframe

    except Exception as error:
        LOGGER.exception(
            "Error al descargar datos de Yahoo Finance (%s). "
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

        # AUDITORÍA (Directriz 1 - Joins para el Historial): antes se usaba
        # how="inner", que descarta silenciosamente cualquier fecha en la
        # que una de las dos series (market cap global o de USDT) no
        # tuviera un registro exacto ese día - un desalineamiento de
        # apenas unas horas entre ambas llamadas a CoinGecko podía
        # recortar días completos sin ninguna advertencia. Se cambia a
        # how="outer" + ffill (igual criterio que el resto del pipeline
        # no-cripto) para que un hueco puntual en una de las dos series se
        # rellene con su último valor conocido en vez de eliminar la fecha
        # entera del historial de USDT.D.
        merged_dataframe = pd.merge(
            global_dataframe[["Date", "Global_Market_Cap"]],
            tether_dataframe[["Date", "USDT_Market_Cap"]],
            on="Date",
            how="outer",
        )
        merged_dataframe = merged_dataframe.sort_values(by="Date")
        merged_dataframe[["Global_Market_Cap", "USDT_Market_Cap"]] = (
            merged_dataframe[["Global_Market_Cap", "USDT_Market_Cap"]].ffill()
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


# NUEVO: PANEL MACRO-BITCOIN AVANZADO - historial del MVRV Z-Score de
# Bitcoin, vía la API de BGeometrics (bitcoin-data.com).
#
# La respuesta de BGeometrics puede llegar en más de un formato según el
# endpoint/versión (lista de objetos {"d": fecha, "mvrvZscore": valor} o
# variantes de nombre de clave). Este parser es deliberadamente defensivo:
# prueba varias claves de fecha/valor conocidas y, si ninguna calza, no
# inventa un número - devuelve un DataFrame vacío y lo refleja como ERROR
# en el Health Check, igual que el resto del pipeline.
_MVRV_DATE_KEYS = ("d", "date", "Date", "timestamp")
_MVRV_VALUE_KEYS = (
    "mvrvZscore",
    "mvrv_zscore",
    "mvrv_z_score",
    "value",
    "Value",
    "zscore",
)


def _parse_mvrv_response(payload) -> pd.DataFrame:
    """
    Convierte la respuesta cruda (JSON ya deserializado) de la API de MVRV
    Z-Score a un DataFrame Date/MVRV_Zscore, sin importar cuál de los
    formatos conocidos haya devuelto el servidor.

    Parameters
    ----------
    payload : Any
        Contenido ya parseado (response.json()) del endpoint de MVRV.

    Returns
    -------
    pd.DataFrame
        Columnas Date y MVRV_Zscore. Vacío si el formato no es reconocido.
    """
    try:
        records = payload
        if isinstance(payload, dict):
            # Variante estilo {"data": [...]}.
            records = payload.get("data", payload.get("results", payload))

        rows = []

        if isinstance(records, list) and records and isinstance(records[0], (list, tuple)):
            # Variante [[fecha, valor], [fecha, valor], ...]
            for entry in records:
                if len(entry) < 2:
                    continue
                rows.append({"Date": entry[0], "MVRV_Zscore": entry[1]})

        elif isinstance(records, list):
            # Variante lista de diccionarios.
            for entry in records:
                if not isinstance(entry, dict):
                    continue
                date_value = next(
                    (entry[key] for key in _MVRV_DATE_KEYS if key in entry),
                    None,
                )
                score_value = next(
                    (entry[key] for key in _MVRV_VALUE_KEYS if key in entry),
                    None,
                )
                if date_value is None or score_value is None:
                    continue
                rows.append({"Date": date_value, "MVRV_Zscore": score_value})

        if not rows:
            return pd.DataFrame(columns=["Date", "MVRV_Zscore"])

        parsed_dataframe = pd.DataFrame(rows)
        parsed_dataframe["Date"] = pd.to_datetime(
            parsed_dataframe["Date"], errors="coerce"
        )
        parsed_dataframe["MVRV_Zscore"] = pd.to_numeric(
            parsed_dataframe["MVRV_Zscore"], errors="coerce"
        )
        parsed_dataframe = parsed_dataframe.dropna(subset=["Date", "MVRV_Zscore"])
        parsed_dataframe = parsed_dataframe.drop_duplicates(subset=["Date"], keep="last")
        parsed_dataframe = parsed_dataframe.sort_values(by="Date").reset_index(drop=True)

        return parsed_dataframe

    except Exception as error:
        LOGGER.exception(
            "Error al interpretar la respuesta del MVRV Z-Score. "
            "Tipo: %s. Detalle: %s",
            type(error).__name__,
            error,
        )
        return pd.DataFrame(columns=["Date", "MVRV_Zscore"])


# =====================================================================
# Directriz 3 (turno anterior): cache local en disco para el MVRV Z-Score.
# =====================================================================
def _load_mvrv_cache_from_disk() -> Optional[pd.DataFrame]:
    """
    Lee el cache local en disco del MVRV Z-Score, si existe y es válido.

    Returns
    -------
    Optional[pd.DataFrame]
        DataFrame con columnas Date/MVRV_Zscore, o None si el archivo no
        existe, está corrupto o no tiene registros aprovechables.
    """
    try:
        if not os.path.isfile(MVRV_CACHE_FILE_PATH):
            return None

        cached_dataframe = pd.read_csv(MVRV_CACHE_FILE_PATH)

        if "Date" not in cached_dataframe.columns or "MVRV_Zscore" not in cached_dataframe.columns:
            LOGGER.warning(
                "El archivo de cache de MVRV Z-Score no tiene el formato esperado; se ignora."
            )
            return None

        cached_dataframe["Date"] = pd.to_datetime(cached_dataframe["Date"], errors="coerce")
        cached_dataframe["MVRV_Zscore"] = pd.to_numeric(
            cached_dataframe["MVRV_Zscore"], errors="coerce"
        )
        cached_dataframe = cached_dataframe.dropna(subset=["Date", "MVRV_Zscore"])

        if cached_dataframe.empty:
            return None

        cached_dataframe = cached_dataframe.sort_values(by="Date").reset_index(drop=True)

        return cached_dataframe

    except Exception as error:
        LOGGER.exception(
            "Error al leer el cache local del MVRV Z-Score. Tipo: %s. Detalle: %s",
            type(error).__name__,
            error,
        )
        return None


def _save_mvrv_cache_to_disk(dataframe: pd.DataFrame) -> None:
    """
    Guarda en disco (CSV) el último DataFrame exitoso del MVRV Z-Score, para
    que las próximas cargas puedan leer desde ahí sin golpear la API.
    """
    try:
        if dataframe is None or dataframe.empty:
            return

        os.makedirs(MVRV_CACHE_DIR, exist_ok=True)
        dataframe.to_csv(MVRV_CACHE_FILE_PATH, index=False)

        LOGGER.info(
            "Cache local del MVRV Z-Score actualizado en %s. Registros: %s.",
            MVRV_CACHE_FILE_PATH,
            len(dataframe),
        )

    except Exception as error:
        LOGGER.exception(
            "Error al guardar el cache local del MVRV Z-Score. Tipo: %s. Detalle: %s",
            type(error).__name__,
            error,
        )


def _mvrv_cache_is_fresh() -> bool:
    """
    True si el archivo de cache existe y su antigüedad es menor a
    MVRV_CACHE_TTL_SECONDS - en ese caso no hace falta golpear la API.
    """
    try:
        if not os.path.isfile(MVRV_CACHE_FILE_PATH):
            return False
        file_age_seconds = time.time() - os.path.getmtime(MVRV_CACHE_FILE_PATH)
        return file_age_seconds < MVRV_CACHE_TTL_SECONDS
    except Exception as error:
        LOGGER.exception(
            "Error al verificar la antigüedad del cache del MVRV Z-Score. "
            "Tipo: %s. Detalle: %s",
            type(error).__name__,
            error,
        )
        return False


def _get_mvrv_cache_timestamp() -> Optional[datetime]:
    """
    Devuelve la fecha/hora real en que se escribió el archivo de cache del
    MVRV Z-Score en disco (su mtime), o None si el archivo no existe.

    ACTUALIZACIÓN (Trazabilidad de Datos Total - Directriz 1): este
    timestamp es el que se expone como `fecha_actualizacion` cuando el
    dato proviene del Caché Local, para que la UI pueda mostrar
    exactamente cuándo se guardó por última vez (no un valor inventado).
    """
    try:
        if not os.path.isfile(MVRV_CACHE_FILE_PATH):
            return None
        return datetime.fromtimestamp(os.path.getmtime(MVRV_CACHE_FILE_PATH))
    except Exception as error:
        LOGGER.exception(
            "Error al leer la fecha de modificación del cache del MVRV "
            "Z-Score. Tipo: %s. Detalle: %s",
            type(error).__name__,
            error,
        )
        return None


def _mvrv_metadata(fuente_datos: str, fecha_actualizacion: Optional[datetime]) -> Dict[str, Any]:
    """
    Construye el diccionario de metadatos de trazabilidad devuelto junto
    al DataFrame por get_mvrv_zscore_history().

    Parameters
    ----------
    fuente_datos : str
        "API Directa", "Caché Local" o "Sin Datos".
    fecha_actualizacion : Optional[datetime]
        Momento real en que se obtuvo/guardó el dato. None si no hay dato.
    """
    return {
        "fuente_datos": fuente_datos,
        "fecha_actualizacion": fecha_actualizacion,
    }


def get_mvrv_zscore_history(
    api_key: str = BGEOMETRICS_API_KEY,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    Descarga el historial del MVRV Z-Score de Bitcoin desde la API de
    BGeometrics (bitcoin-data.com), usando el token del usuario.

    El token se inyecta de dos formas válidas a la vez (documentación de
    BGeometrics): como parámetro "token" en la URL y como encabezado
    "Authorization: Bearer <token>".

    Antes de golpear la API, se revisa si hay un cache local "fresco"
    (menos de MVRV_CACHE_TTL_SECONDS de antigüedad) - si lo hay, se sirve
    directo desde disco y NO se hace una petición HTTP nueva. Si la
    petición HTTP falla por cualquier motivo, se intenta servir el cache
    local como resguardo antes de devolver un DataFrame vacío.

    ACTUALIZACIÓN (Trazabilidad de Datos Total): esta función YA NO
    devuelve solo el DataFrame. Devuelve una tupla (DataFrame, metadata),
    donde metadata trae SIEMPRE el origen real del dato:
        - "fuente_datos": "API Directa" | "Caché Local" | "Sin Datos"
        - "fecha_actualizacion": datetime real de cuándo se obtuvo/guardó
          el dato (None si no hay dato disponible).
    Esto es lo que consume app.py para pintar el Health Check de forma
    honesta, sin depender del diccionario global DATA_HEALTH (que podía
    quedar desactualizado por el orden de llamadas entre
    load_master_dataframe() y load_mvrv_zscore_history(), produciendo el
    falso negativo "ERROR" reportado). DATA_HEALTH se sigue actualizando
    igual que antes, solo que ya no es la fuente de verdad para la UI.

    Parameters
    ----------
    api_key : str
        Token de BGeometrics (BGEOMETRICS_API_KEY en config.py).

    Returns
    -------
    Tuple[pd.DataFrame, Dict[str, Any]]
        DataFrame con columnas Date y MVRV_Zscore (vacío únicamente si
        tanto la API como el cache local fallan - nunca se inventa un
        valor), y el diccionario de metadatos descrito arriba.
    """
    try:
        if _mvrv_cache_is_fresh():
            cached_dataframe = _load_mvrv_cache_from_disk()
            if cached_dataframe is not None and not cached_dataframe.empty:
                DATA_HEALTH["MVRV_Zscore"] = "OK (cache local)"
                cache_timestamp = _get_mvrv_cache_timestamp()
                LOGGER.info(
                    "MVRV Z-Score servido desde cache local (fresco). Registros: %s.",
                    len(cached_dataframe),
                )
                return cached_dataframe, _mvrv_metadata("Caché Local", cache_timestamp)

        headers: Dict[str, str] = {}
        params: Dict[str, str] = {}
        if isinstance(api_key, str) and api_key.strip():
            clean_key = api_key.strip()
            headers["Authorization"] = f"Bearer {clean_key}"
            params["token"] = clean_key

        LOGGER.info("Iniciando descarga del MVRV Z-Score (BGeometrics).")

        response = requests.get(
            MVRV_ZSCORE_API_URL,
            headers=headers,
            params=params,
            timeout=30,
        )
        response.raise_for_status()

        payload = response.json()
        result_dataframe = _parse_mvrv_response(payload)

        if result_dataframe.empty:
            raise ValueError(
                "La respuesta del MVRV Z-Score no contenía registros "
                "reconocibles."
            )

        _mark_health("MVRV_Zscore", ok=True)
        _save_mvrv_cache_to_disk(result_dataframe)

        fetched_at = datetime.now()

        LOGGER.info(
            "Historial de MVRV Z-Score descargado. Registros: %s.",
            len(result_dataframe),
        )

        return result_dataframe, _mvrv_metadata("API Directa", fetched_at)

    except requests.exceptions.HTTPError as error:
        status_code = getattr(error.response, "status_code", "desconocido")
        detail = (
            "token inválido o no autorizado (revisa BGEOMETRICS_API_KEY)"
            if status_code in (401, 403)
            else f"HTTP {status_code}"
        )
        LOGGER.exception(
            "Error HTTP al descargar MVRV Z-Score. Detalle: %s", error
        )
        return _fallback_to_mvrv_cache(detail)

    except Exception as error:
        LOGGER.exception(
            "Error al descargar el MVRV Z-Score. Tipo: %s. Detalle: %s",
            type(error).__name__,
            error,
        )
        return _fallback_to_mvrv_cache(type(error).__name__)


def _fallback_to_mvrv_cache(error_detail: str) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    Si la petición HTTP del MVRV Z-Score falla, se intenta servir el
    último DataFrame exitoso guardado en el cache local (aunque esté
    vencido) antes de devolver un DataFrame vacío.

    Parameters
    ----------
    error_detail : str
        Motivo del fallo de la API, solo para fines de Health Check/log.

    Returns
    -------
    Tuple[pd.DataFrame, Dict[str, Any]]
        El cache local (fuente_datos="Caché Local") si existe, o un
        DataFrame vacío con fuente_datos="Sin Datos" si tanto la API como
        el cache fallan.
    """
    try:
        cached_dataframe = _load_mvrv_cache_from_disk()
        if cached_dataframe is not None and not cached_dataframe.empty:
            DATA_HEALTH["MVRV_Zscore"] = (
                f"OK (cache local - la API falló: {error_detail})"
            )
            cache_timestamp = _get_mvrv_cache_timestamp()
            LOGGER.warning(
                "La API de MVRV Z-Score falló (%s); se sirvió el cache "
                "local con %s registros en su lugar.",
                error_detail,
                len(cached_dataframe),
            )
            return cached_dataframe, _mvrv_metadata("Caché Local", cache_timestamp)

        _mark_health("MVRV_Zscore", ok=False, detail=error_detail)
        return pd.DataFrame(columns=["Date", "MVRV_Zscore"]), _mvrv_metadata("Sin Datos", None)

    except Exception as error:
        LOGGER.exception(
            "Error inesperado en el fallback de cache del MVRV Z-Score. "
            "Tipo: %s. Detalle: %s",
            type(error).__name__,
            error,
        )
        _mark_health("MVRV_Zscore", ok=False, detail="fallback de cache falló")
        return pd.DataFrame(columns=["Date", "MVRV_Zscore"]), _mvrv_metadata("Sin Datos", None)


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