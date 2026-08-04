"""
Indicador LIQGLOB: Liquidez Global combinada de Estados Unidos y la
Eurozona, en miles de millones de dólares (billions), sin normalizar.

CANDADO: este módulo es 100% aditivo y NO modifica math_processor.py ni
advanced_liquidity.py. Reutiliza el DataFrame Maestro ya construido por
math_processor.py (columnas WALCL, WDTGAL, BTC_Close, SOL_Close - ya
descargadas de FRED, ya reindexadas a calendario diario continuo y ya
propagadas hacia adelante/ffill por el pipeline existente) y recibe,
además, varias series DIARIAS CRUDAS (sin forward-fill previo, con sus
huecos reales intactos) que este módulo SÍ necesita para poder aplicar
correctamente la alineación semanal: RRP (RRPONTSYD), EUR/USD (DEXUSEU) y
los componentes del BCE usados para LIQEUR. Ninguna se vuelve a descargar
aquí - todas llegan ya descargadas desde app.py (cacheadas con
@st.cache_data) vía data_ingestion.get_fred_data / get_ecb_liquidity_data.

Fórmulas (automáticas, ninguna cifra se introduce a mano):
    LIQEEUU = WALCL - TGA (WDTGAL) - RRP (RRPONTSYD)   [todo en miles de
              millones de USD]
    LIQEUR  = ver "METODOLOGÍA DE LIQEUR" más abajo
    LIQGLOB = LIQEEUU + LIQEUR

=====================================================================
METODOLOGÍA DE LIQEUR (migración desde EXLIQ a los 4 componentes)
=====================================================================
Tras una validación metodológica exhaustiva (ver liqeur_validation.py:
correlación prácticamente perfecta y diferencia porcentual media
prácticamente nula entre ambos cálculos, en la ventana donde coexisten),
LIQEUR se construye por defecto a partir de sus 4 componentes oficiales
del BCE (metodología "COMPONENTS"), en vez de depender directamente de la
serie consolidada ILM.D.U2.C.EXLIQ.U2.EUR (metodología "EXLIQ", legado),
cuyo historial retroactivo es más limitado. El flag
config.LIQEUR_METHODOLOGY controla cuál de las dos rutas de cálculo se
usa - AMBAS se conservan completas en el código (funciones
`_compute_liqeur_weekly_from_components` y
`_compute_liqeur_weekly_from_exliq_legacy` más abajo), así que revertir
la metodología no requiere tocar ningún archivo, solo ese flag.

  "COMPONENTS" (activa por defecto):
      LIQEUR = (Current Accounts - Minimum Reserve Requirements)
               + Deposit Facility - Marginal Lending Facility
      (fórmula oficial del BCE), convertido de millones de EUR a miles de
      millones de EUR y luego a USD con el EUR/USD de esa misma semana.

  "EXLIQ" (legado, conservado por reversibilidad):
      LIQEUR = (ILM.D.U2.C.EXLIQ.U2.EUR / 1000) x EURUSD

En ambos casos, ILM.D.U2.C.EXLIQ.U2.EUR se sigue descargando y se sigue
usando como serie de referencia en la sección "VALIDACIÓN METODOLÓGICA DE
LIQEUR" de la pestaña (ver app.py y liqeur_validation.py) - eso no cambia
con este flag; solo cambia cuál es la fuente que alimenta el CÁLCULO
activo de LIQGLOB.

=====================================================================
ALINEACIÓN TEMPORAL POR SEMANA ECONÓMICA (cambio significativo)
=====================================================================
CORRECCIÓN DE ERROR (salto de liquidez reportado en fin de trimestre,
ej. fin de septiembre / inicio de octubre): la versión anterior tomaba
`.resample("W-FRI").last()` sobre columnas ya continuas/ffilled, lo que
en la práctica combinaba el WALCL/TGA "congelado desde el miércoles" con
el RRP y el EUR/USD del VIERNES - dos momentos de mercado distintos
dentro de la misma observación. RRP puede moverse mucho de un día para
otro en fechas de fin de trimestre (efecto de "window dressing" de
fondos del mercado monetario, bien documentado), y esa mezcla era
exactamente lo que producía el salto visual reportado.

La corrección (y el cambio significativo pedido): cada observación de
LIQGLOB representa una única SEMANA ECONÓMICA, y todas las variables que
la componen deben venir de esa misma semana:
  - Series de frecuencia SEMANAL (WALCL, WDTGAL): ya llegan una sola vez
    por semana (vía el DataFrame Maestro) - se usa directamente su valor
    en el miércoles de esa semana.
  - Series de frecuencia DIARIA (RRP, EUR/USD, los 4 componentes del BCE
    y, en la metodología legado, EXLIQ): se busca el dato REAL publicado
    el miércoles de esa semana. Si no existe (feriado o ausencia de
    publicación), se busca el día hábil inmediatamente anterior DENTRO DE
    LA MISMA SEMANA: martes, y si tampoco existe, lunes. Si ninguno de
    los tres tiene dato real, esa semana no se construye (queda NaN) -
    nunca se toma un dato de una semana distinta (ver
    `_select_weekly_value_with_fallback` más abajo). Esta MISMA función,
    sin ninguna modificación, es la que se reutiliza para alinear
    semanalmente cada uno de los 4 componentes de LIQEUR.

Integridad semanal: una semana solo se incorpora al indicador cuando hay
información suficiente para calcular TODAS las variables de las regiones
activas (checkboxes). Para Eurozona con la metodología "COMPONENTS", esto
significa: los 4 componentes Y el tipo de cambio EUR/USD deben tener dato
real esa semana (miércoles/martes/lunes) - si falta cualquiera de los 5,
esa semana no se dibuja (propagación de NaN, sin inventar ni rellenar con
cero, sin forward-fill indiscriminado). Una región DESACTIVADA, en
cambio, simplemente no participa en la suma (exclusión deliberada, no un
hueco de datos).

Momento de ejecución: el indicador se recalcula automáticamente en cada
carga/actualización de caché de la app - no requiere intervención manual.
La hora en que se abre el programa nunca cambia la fecha económica de
cada observación (siempre el miércoles de su semana); solo determina si,
para la semana más reciente, ya hay o no datos oficiales publicados.
"""

import logging
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from config import (
    ECB_EUR_MILLIONS_TO_BILLIONS,
    LIQEUR_METHODOLOGY,
    LIQGLOB_HISTORY_WEEKS,
    LIQGLOB_REGIONS,
    US_MILLIONS_TO_BILLIONS,
    WEEKLY_FALLBACK_WEEKDAYS_PRIORITY,
    WEEKLY_REFERENCE_WEEKDAY,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

LOGGER = logging.getLogger(__name__)

# Columnas finales devueltas por build_liqglob_index, en este orden.
LIQGLOB_COLUMNS: List[str] = [
    "Date",
    "BTC_Close",
    "SOL_Close",
    "LIQEEUU_USD_B",
    "LIQEUR_USD_B",
    "LIQGLOB_USD_B",
]


def _week_start_monday(date_series: pd.Series) -> pd.Series:
    """
    Clave de semana (el lunes de esa semana calendario) usada para
    agrupar todas las series por "semana económica", sin usar
    `.resample()` - así se controla explícitamente qué día se toma de
    cada semana en vez de dejarlo a la convención de cierre de un
    resample de pandas.
    """
    return date_series - pd.to_timedelta(date_series.dt.weekday, unit="D")


def _select_weekly_value_with_fallback(
    raw_dataframe: pd.DataFrame,
    value_column: str,
) -> pd.DataFrame:
    """
    Selecciona, para una serie DIARIA CRUDA (con huecos reales, SIN
    forward-fill previo), un único valor por semana económica: el
    miércoles; si no existe, el martes; si tampoco existe, el lunes.

    Si ninguno de los tres días tiene una observación real, esa semana
    queda simplemente sin fila en el resultado (no se fabrica un valor,
    y nunca se usa un dato de martes/lunes de una semana DISTINTA - la
    búsqueda está estrictamente acotada a lunes-martes-miércoles de la
    misma semana calendario).

    Parameters
    ----------
    raw_dataframe : pd.DataFrame
        Columnas Date y `value_column`, SIN forward-fill previo (ej. el
        resultado crudo de data_ingestion.get_fred_data /
        get_ecb_liquidity_data).
    value_column : str
        Nombre de la columna de valor a seleccionar.

    Returns
    -------
    pd.DataFrame
        Columnas "Semana" (lunes de cada semana calendario) y
        `value_column`, una fila por semana con dato disponible.
    """
    try:
        if raw_dataframe is None or raw_dataframe.empty or value_column not in raw_dataframe.columns:
            return pd.DataFrame(columns=["Semana", value_column])

        working = raw_dataframe.loc[:, ["Date", value_column]].copy()
        working["Date"] = pd.to_datetime(working["Date"], errors="coerce")
        working[value_column] = pd.to_numeric(working[value_column], errors="coerce")
        working = working.dropna(subset=["Date", value_column])

        if working.empty:
            return pd.DataFrame(columns=["Semana", value_column])

        working = working.sort_values(by="Date").reset_index(drop=True)
        working["DiaSemana"] = working["Date"].dt.weekday
        working["Semana"] = _week_start_monday(working["Date"])

        # Solo se consideran candidatos lunes/martes/miércoles - nunca un
        # día de otra parte de la semana (jueves/viernes de la semana
        # ANTERIOR, por ejemplo, quedarían fuera de esta selección).
        candidates = working[working["DiaSemana"].isin(WEEKLY_FALLBACK_WEEKDAYS_PRIORITY)].copy()
        if candidates.empty:
            return pd.DataFrame(columns=["Semana", value_column])

        # Prioridad exacta pedida: miércoles primero, luego martes, luego
        # lunes - dentro de la MISMA semana únicamente.
        priority_rank = {
            weekday: rank for rank, weekday in enumerate(WEEKLY_FALLBACK_WEEKDAYS_PRIORITY)
        }
        candidates["Prioridad"] = candidates["DiaSemana"].map(priority_rank)
        candidates = candidates.sort_values(by=["Semana", "Prioridad"])

        selected = candidates.drop_duplicates(subset=["Semana"], keep="first")

        return selected.loc[:, ["Semana", value_column]].reset_index(drop=True)

    except Exception as error:
        LOGGER.exception(
            "Error al seleccionar el valor semanal con fallback para %s. "
            "Tipo: %s. Detalle: %s",
            value_column,
            type(error).__name__,
            error,
        )
        return pd.DataFrame(columns=["Semana", value_column])


def _select_master_weekday_rows(
    master_dataframe: pd.DataFrame,
    columns: List[str],
) -> pd.DataFrame:
    """
    Para columnas que YA llegan diarias/continuas y con forward-fill
    aplicado por math_processor.py (WALCL, WDTGAL - de frecuencia
    semanal real, ya son "la observación oficial de esa semana" en
    cualquier día que se lean - y BTC_Close/SOL_Close, que cotizan todos
    los días), se toma directamente la fila del día de referencia
    (miércoles, WEEKLY_REFERENCE_WEEKDAY) de cada semana calendario. Como
    el DataFrame Maestro cubre TODOS los días calendario sin huecos, el
    miércoles de cada semana siempre existe como fila.

    Returns
    -------
    pd.DataFrame
        Columnas "Semana" (lunes de esa semana) + `columns`.
    """
    try:
        working = master_dataframe.loc[:, ["Date"] + columns].copy()
        working["Date"] = pd.to_datetime(working["Date"], errors="coerce")
        working = working.dropna(subset=["Date"]).sort_values(by="Date").reset_index(drop=True)

        reference_rows = working.loc[working["Date"].dt.weekday == WEEKLY_REFERENCE_WEEKDAY].copy()
        reference_rows["Semana"] = _week_start_monday(reference_rows["Date"])

        return reference_rows.loc[:, ["Semana"] + columns].reset_index(drop=True)

    except Exception as error:
        LOGGER.exception(
            "Error al seleccionar filas del día de referencia semanal. "
            "Tipo: %s. Detalle: %s",
            type(error).__name__,
            error,
        )
        return pd.DataFrame(columns=["Semana"] + columns)


# =====================================================================
# METODOLOGÍA ACTIVA (por defecto): LIQEUR desde los 4 componentes
# =====================================================================
def _compute_liqeur_weekly_from_components(
    current_accounts_raw: Optional[pd.DataFrame],
    min_reserve_requirements_raw: Optional[pd.DataFrame],
    deposit_facility_raw: Optional[pd.DataFrame],
    marginal_lending_facility_raw: Optional[pd.DataFrame],
    eurusd_raw_dataframe: Optional[pd.DataFrame],
) -> pd.DataFrame:
    """
    METODOLOGÍA ACTIVA de LIQEUR (config.LIQEUR_METHODOLOGY ==
    "COMPONENTS"): reconstruye LIQEUR semana a semana a partir de sus 4
    componentes oficiales del BCE, aplicando la MISMA función de
    alineación semanal (miércoles, con fallback martes/lunes) ya usada
    para RRP y EUR/USD - `_select_weekly_value_with_fallback`, sin
    ninguna modificación.

    Fórmula oficial del BCE:
        LIQEUR = (Current Accounts - Minimum Reserve Requirements)
                 + Deposit Facility - Marginal Lending Facility
    (todo en millones de EUR) -> se divide entre 1000 para quedar en
    miles de millones (billions) de EUR, y se convierte a USD
    multiplicando por el tipo de cambio EUR/USD de esa MISMA semana.

    Integridad semanal: si CUALQUIERA de los 4 componentes o el tipo de
    cambio EUR/USD carece de observación real dentro de esa semana
    (miércoles/martes/lunes), el resultado de esa semana queda en NaN -
    nunca se inventa, aproxima, ni se usa forward-fill indiscriminado
    para rellenar el componente faltante.

    Parameters
    ----------
    current_accounts_raw : Optional[pd.DataFrame]
        Serie CRUDA (Date, Value) de ILM.D.U2.C.L020100.U2.EUR.
    min_reserve_requirements_raw : Optional[pd.DataFrame]
        Serie CRUDA (Date, Value) de ILM.D.U2.C.MRR.U2.EUR.
    deposit_facility_raw : Optional[pd.DataFrame]
        Serie CRUDA (Date, Value) de ILM.D.U2.C.L020200.U2.EUR.
    marginal_lending_facility_raw : Optional[pd.DataFrame]
        Serie CRUDA (Date, Value) de ILM.D.U2.C.A050500.U2.EUR.
    eurusd_raw_dataframe : Optional[pd.DataFrame]
        Serie CRUDA (Date, Value) de EUR/USD (DEXUSEU, FRED).

    Returns
    -------
    pd.DataFrame
        Columnas "Semana" y "LIQEUR_USD_B".
    """
    component_specs = [
        (current_accounts_raw, "CurrentAccounts"),
        (min_reserve_requirements_raw, "MinReserveReq"),
        (deposit_facility_raw, "DepositFacility"),
        (marginal_lending_facility_raw, "MarginalLendingFacility"),
    ]

    weekly_components: Dict[str, pd.DataFrame] = {}
    for raw_dataframe, column_name in component_specs:
        if raw_dataframe is not None and not raw_dataframe.empty:
            component_source = raw_dataframe.rename(columns={"Value": column_name})
            weekly_components[column_name] = _select_weekly_value_with_fallback(
                component_source, column_name
            )
        else:
            weekly_components[column_name] = pd.DataFrame(columns=["Semana", column_name])
            LOGGER.warning(
                "Sin historial crudo del componente %s (BCE); LIQEUR no "
                "participará en las semanas afectadas por esta ausencia.",
                column_name,
            )

    if eurusd_raw_dataframe is not None and not eurusd_raw_dataframe.empty:
        eurusd_source = eurusd_raw_dataframe.rename(columns={"Value": "EURUSD"})
        eurusd_weekly = _select_weekly_value_with_fallback(eurusd_source, "EURUSD")
    else:
        eurusd_weekly = pd.DataFrame(columns=["Semana", "EURUSD"])
        LOGGER.warning(
            "Sin historial crudo de EUR/USD (DEXUSEU) disponible; "
            "LIQEUR no participará en LIQGLOB."
        )

    merged = weekly_components["CurrentAccounts"]
    for column_name in ("MinReserveReq", "DepositFacility", "MarginalLendingFacility"):
        merged = pd.merge(merged, weekly_components[column_name], on="Semana", how="outer")
    merged = pd.merge(merged, eurusd_weekly, on="Semana", how="outer")

    if merged.empty:
        return pd.DataFrame(columns=["Semana", "LIQEUR_USD_B"])

    # Fórmula oficial del BCE, aplicada en millones de EUR primero, y
    # convertida a miles de millones (billions) recién después de
    # combinar los 4 componentes - matemáticamente equivalente a
    # convertir cada componente por separado (la fórmula es lineal), pero
    # más simple de leer y auditar.
    combined_millions_eur = (
        pd.to_numeric(merged.get("CurrentAccounts"), errors="coerce")
        - pd.to_numeric(merged.get("MinReserveReq"), errors="coerce")
        + pd.to_numeric(merged.get("DepositFacility"), errors="coerce")
        - pd.to_numeric(merged.get("MarginalLendingFacility"), errors="coerce")
    )
    combined_billions_eur = combined_millions_eur / ECB_EUR_MILLIONS_TO_BILLIONS
    eurusd_rate = pd.to_numeric(merged.get("EURUSD"), errors="coerce")

    merged["LIQEUR_USD_B"] = combined_billions_eur * eurusd_rate

    return merged.loc[:, ["Semana", "LIQEUR_USD_B"]]


# =====================================================================
# METODOLOGÍA LEGADO (conservada por reversibilidad, ver
# config.LIQEUR_METHODOLOGY): LIQEUR directamente desde EXLIQ
# =====================================================================
def _compute_liqeur_weekly_from_exliq_legacy(
    ecb_liquidity_dataframe: Optional[pd.DataFrame],
    eurusd_raw_dataframe: Optional[pd.DataFrame],
) -> pd.DataFrame:
    """
    METODOLOGÍA LEGADO de LIQEUR (config.LIQEUR_METHODOLOGY == "EXLIQ"):
    calcula LIQEUR directamente desde la serie consolidada oficial
    ILM.D.U2.C.EXLIQ.U2.EUR, sin pasar por sus 4 componentes. Esta era la
    metodología activa antes de la migración a
    `_compute_liqeur_weekly_from_components` - se conserva completa e
    intacta únicamente para permitir revertir la metodología cambiando
    config.LIQEUR_METHODOLOGY a "EXLIQ", sin modificar ningún archivo.

    Returns
    -------
    pd.DataFrame
        Columnas "Semana" y "LIQEUR_USD_B".
    """
    if eurusd_raw_dataframe is not None and not eurusd_raw_dataframe.empty:
        eurusd_source = eurusd_raw_dataframe.rename(columns={"Value": "EURUSD"})
        eurusd_weekly = _select_weekly_value_with_fallback(eurusd_source, "EURUSD")
    else:
        eurusd_weekly = pd.DataFrame(columns=["Semana", "EURUSD"])
        LOGGER.warning(
            "Sin historial crudo de EUR/USD (DEXUSEU) disponible; "
            "LIQEUR no participará en LIQGLOB."
        )

    if ecb_liquidity_dataframe is not None and not ecb_liquidity_dataframe.empty:
        ecb_source = ecb_liquidity_dataframe.rename(columns={"Value": "ECB_EXLIQ_EUR_M"})
        ecb_weekly = _select_weekly_value_with_fallback(ecb_source, "ECB_EXLIQ_EUR_M")
    else:
        ecb_weekly = pd.DataFrame(columns=["Semana", "ECB_EXLIQ_EUR_M"])
        LOGGER.warning(
            "Sin historial de Liquidez Excedentaria del BCE (EXLIQ) "
            "disponible; LIQEUR no participará en LIQGLOB."
        )

    merged = pd.merge(ecb_weekly, eurusd_weekly, on="Semana", how="outer")

    if merged.empty:
        return pd.DataFrame(columns=["Semana", "LIQEUR_USD_B"])

    eurusd_rate = pd.to_numeric(merged.get("EURUSD"), errors="coerce")
    ecb_billions_eur = (
        pd.to_numeric(merged.get("ECB_EXLIQ_EUR_M"), errors="coerce")
        / ECB_EUR_MILLIONS_TO_BILLIONS
    )
    merged["LIQEUR_USD_B"] = ecb_billions_eur * eurusd_rate

    return merged.loc[:, ["Semana", "LIQEUR_USD_B"]]


def build_liqglob_index(
    master_dataframe: pd.DataFrame,
    rrp_raw_dataframe: Optional[pd.DataFrame] = None,
    eurusd_raw_dataframe: Optional[pd.DataFrame] = None,
    current_accounts_raw_dataframe: Optional[pd.DataFrame] = None,
    min_reserve_requirements_raw_dataframe: Optional[pd.DataFrame] = None,
    deposit_facility_raw_dataframe: Optional[pd.DataFrame] = None,
    marginal_lending_facility_raw_dataframe: Optional[pd.DataFrame] = None,
    ecb_liquidity_dataframe: Optional[pd.DataFrame] = None,
    region_toggles: Optional[Dict[str, bool]] = None,
) -> pd.DataFrame:
    """
    Construye el indicador semanal LIQGLOB (Liquidez Global de Estados
    Unidos + Eurozona), listo para graficarse contra BTC/SOL, con
    alineación temporal por semana económica (miércoles, con fallback a
    martes/lunes dentro de la misma semana - ver docstring del módulo).

    Parameters
    ----------
    master_dataframe : pd.DataFrame
        DataFrame Maestro de math_processor.py (diario, con columnas
        WALCL, WDTGAL, BTC_Close, SOL_Close ya alineadas/ffilled). No se
        modifica ni se vuelve a descargar nada de este DataFrame.
    rrp_raw_dataframe : Optional[pd.DataFrame]
        Serie CRUDA (Date, Value) de RRP (RRPONTSYD), SIN forward-fill
        previo - resultado directo de data_ingestion.get_fred_data. Si es
        None o está vacía, LIQEEUU no participa (queda NaN).
    eurusd_raw_dataframe : Optional[pd.DataFrame]
        Serie CRUDA (Date, Value) de EUR/USD (DEXUSEU), SIN forward-fill
        previo. Necesaria en AMBAS metodologías de LIQEUR.
    current_accounts_raw_dataframe, min_reserve_requirements_raw_dataframe,
    deposit_facility_raw_dataframe, marginal_lending_facility_raw_dataframe : Optional[pd.DataFrame]
        Series CRUDAS (Date, Value) de los 4 componentes oficiales del
        BCE. Usadas por la metodología ACTIVA por defecto
        (config.LIQEUR_METHODOLOGY == "COMPONENTS") - ver
        `_compute_liqeur_weekly_from_components`.
    ecb_liquidity_dataframe : Optional[pd.DataFrame]
        Resultado de data_ingestion.get_ecb_liquidity_data() (columnas
        Date, Value - en millones de euros, SIN forward-fill previo).
        Usado solo si config.LIQEUR_METHODOLOGY == "EXLIQ" (metodología
        legado, ver `_compute_liqeur_weekly_from_exliq_legacy`) - con la
        metodología activa por defecto, este parámetro NO participa en
        el cálculo (aunque se siga aceptando por compatibilidad).
    region_toggles : Optional[Dict[str, bool]]
        Estado de cada checkbox (claves de config.LIQGLOB_REGIONS: "US",
        "EUROZONE"). Si es None, se usan los defaults (ambas activas).

    Returns
    -------
    pd.DataFrame
        DataFrame semanal (una fila por semana económica, ancladas al
        miércoles; últimas config.LIQGLOB_HISTORY_WEEKS semanas) con
        columnas LIQGLOB_COLUMNS. Las semanas sin información suficiente
        para alguna región ACTIVA quedan con LIQGLOB_USD_B en NaN (no se
        inventan ni se rellenan con cero) - Plotly simplemente no dibuja
        ese punto, dejando un hueco en la línea en vez de deformarla.
    """
    empty_result = pd.DataFrame(columns=LIQGLOB_COLUMNS)

    try:
        required_columns = ["Date", "WALCL", "WDTGAL", "BTC_Close", "SOL_Close"]
        missing_columns = [c for c in required_columns if c not in master_dataframe.columns]
        if master_dataframe.empty or missing_columns:
            if missing_columns:
                LOGGER.warning(
                    "Faltan columnas para el indicador LIQGLOB: %s.",
                    missing_columns,
                )
            return empty_result

        resolved_toggles = {
            key: region_config["default"] for key, region_config in LIQGLOB_REGIONS.items()
        }
        if region_toggles:
            resolved_toggles.update(region_toggles)

        # -----------------------------------------------------------
        # Paso 1: un valor por semana económica para cada serie, con la
        # alineación temporal correcta (ver docstrings de los helpers).
        # -----------------------------------------------------------
        us_weekly = _select_master_weekday_rows(
            master_dataframe, ["WALCL", "WDTGAL", "BTC_Close", "SOL_Close"]
        )

        if rrp_raw_dataframe is not None and not rrp_raw_dataframe.empty:
            rrp_source = rrp_raw_dataframe.rename(columns={"Value": "RRP"})
            rrp_weekly = _select_weekly_value_with_fallback(rrp_source, "RRP")
        else:
            rrp_weekly = pd.DataFrame(columns=["Semana", "RRP"])
            LOGGER.warning(
                "Sin historial crudo de RRP (RRPONTSYD) disponible; "
                "LIQEEUU no participará en LIQGLOB."
            )

        # -----------------------------------------------------------
        # LIQEUR: se calcula según config.LIQEUR_METHODOLOGY. Las dos
        # rutas de cálculo están completas e intactas en el módulo - este
        # es el ÚNICO punto de despacho entre ambas (ver docstring del
        # módulo, sección "MIGRACIÓN DE METODOLOGÍA DE LIQEUR").
        # -----------------------------------------------------------
        if LIQEUR_METHODOLOGY == "EXLIQ":
            liqeur_weekly = _compute_liqeur_weekly_from_exliq_legacy(
                ecb_liquidity_dataframe=ecb_liquidity_dataframe,
                eurusd_raw_dataframe=eurusd_raw_dataframe,
            )
        else:
            if LIQEUR_METHODOLOGY != "COMPONENTS":
                LOGGER.warning(
                    "config.LIQEUR_METHODOLOGY=%r no reconocido; se usa "
                    "'COMPONENTS' (metodología activa por defecto) como "
                    "resguardo.",
                    LIQEUR_METHODOLOGY,
                )
            liqeur_weekly = _compute_liqeur_weekly_from_components(
                current_accounts_raw=current_accounts_raw_dataframe,
                min_reserve_requirements_raw=min_reserve_requirements_raw_dataframe,
                deposit_facility_raw=deposit_facility_raw_dataframe,
                marginal_lending_facility_raw=marginal_lending_facility_raw_dataframe,
                eurusd_raw_dataframe=eurusd_raw_dataframe,
            )

        # -----------------------------------------------------------
        # Paso 2: unir todas las semanas en una sola tabla (outer merge
        # por "Semana"). Una semana sin dato en alguna serie queda con
        # NaN ahí (nunca con un valor inventado ni de otra semana). El
        # outer merge es precisamente lo que permite que el histórico se
        # extienda tan atrás como lo permita CUALQUIERA de las fuentes -
        # incluida ahora la Eurozona, ya no acotada al inicio de EXLIQ.
        # -----------------------------------------------------------
        weekly = us_weekly
        for extra_weekly in (rrp_weekly, liqeur_weekly):
            weekly = pd.merge(weekly, extra_weekly, on="Semana", how="outer")

        weekly = weekly.sort_values(by="Semana").reset_index(drop=True)

        if weekly.empty:
            return empty_result

        # -----------------------------------------------------------
        # Paso 3: fórmula de LIQEEUU (sin cambios). LIQEUR_USD_B ya llegó
        # calculada desde el Paso 1 (según la metodología activa) - aquí
        # solo se asegura que exista como columna.
        # -----------------------------------------------------------
        walcl_billions = pd.to_numeric(weekly.get("WALCL"), errors="coerce") / US_MILLIONS_TO_BILLIONS
        wdtgal_billions = pd.to_numeric(weekly.get("WDTGAL"), errors="coerce") / US_MILLIONS_TO_BILLIONS
        rrp_billions = pd.to_numeric(weekly.get("RRP"), errors="coerce")  # RRPONTSYD ya en billions

        weekly["LIQEEUU_USD_B"] = walcl_billions - wdtgal_billions - rrp_billions

        if "LIQEUR_USD_B" not in weekly.columns:
            weekly["LIQEUR_USD_B"] = np.nan

        # -----------------------------------------------------------
        # Paso 4: LIQGLOB = suma de las regiones ACTIVAS únicamente.
        # Una región DESACTIVADA no participa (exclusión deliberada). Una
        # región ACTIVA sin dato esa semana propaga NaN (integridad
        # semanal: "si no existe información válida para una semana
        # determinada, esa observación no deberá construirse").
        # ESCALABILIDAD: para una región futura, calcular su columna más
        # arriba y añadirla a `region_series` aquí abajo.
        # -----------------------------------------------------------
        region_series: Dict[str, pd.Series] = {
            "US": weekly["LIQEEUU_USD_B"],
            "EUROZONE": weekly["LIQEUR_USD_B"],
        }

        active_regions: List[str] = [
            region_key for region_key in LIQGLOB_REGIONS.keys()
            if resolved_toggles.get(region_key, True) and region_key in region_series
        ]

        if active_regions:
            total_liqglob = None
            for region_key in active_regions:
                series = pd.to_numeric(region_series[region_key], errors="coerce")
                total_liqglob = series if total_liqglob is None else total_liqglob + series
            weekly["LIQGLOB_USD_B"] = total_liqglob
        else:
            weekly["LIQGLOB_USD_B"] = np.nan

        # -----------------------------------------------------------
        # Paso 5: fecha final visible = miércoles de cada semana
        # económica (Semana + 2 días), y recorte a la ventana histórica
        # objetivo (últimas ~600 semanas).
        # -----------------------------------------------------------
        weekly["Date"] = weekly["Semana"] + pd.Timedelta(days=WEEKLY_REFERENCE_WEEKDAY)

        if LIQGLOB_HISTORY_WEEKS and len(weekly) > LIQGLOB_HISTORY_WEEKS:
            weekly = weekly.tail(LIQGLOB_HISTORY_WEEKS).reset_index(drop=True)

        for column in LIQGLOB_COLUMNS:
            if column not in weekly.columns:
                weekly[column] = np.nan

        weekly = weekly.loc[:, LIQGLOB_COLUMNS]
        weekly = weekly.sort_values(by="Date").reset_index(drop=True)

        LOGGER.info(
            "Indicador LIQGLOB construido. Regiones activas: %s. Semanas: %s. "
            "Semanas con LIQGLOB válido: %s.",
            active_regions,
            len(weekly),
            int(weekly["LIQGLOB_USD_B"].notna().sum()),
        )

        return weekly

    except Exception as error:
        LOGGER.exception(
            "Error al construir el indicador LIQGLOB. Tipo: %s. Detalle: %s",
            type(error).__name__,
            error,
        )
        return empty_result


# =====================================================================
# VERIFICACIÓN DE COBERTURA HISTÓRICA REAL POR FUENTE
# =====================================================================
# Requisito explícito del usuario: nunca asumir ni recortar por
# programación el histórico disponible - en vez de eso, esta función
# reporta la fecha REAL de la primera y la última observación cruda (tal
# cual llega de cada fuente, ANTES de cualquier alineación semanal,
# merge o recorte de ventana) para que se pueda verificar directamente,
# en la propia interfaz (Health Check de la pestaña LIQGLOB), si una
# fuente realmente carece de historia anterior o si el hueco aparece en
# algún paso posterior del pipeline.
def _describe_raw_source_coverage(
    dataframe: Optional[pd.DataFrame],
    date_column: str = "Date",
) -> Dict[str, object]:
    """
    Describe la cobertura histórica real (cruda) de un DataFrame Date/Value.

    Parameters
    ----------
    dataframe : Optional[pd.DataFrame]
        DataFrame crudo con al menos una columna de fecha.
    date_column : str
        Nombre de la columna de fecha a inspeccionar.

    Returns
    -------
    Dict[str, object]
        "primer_dato", "ultimo_dato" (pd.Timestamp o None) y
        "registros" (int) - exactamente lo que trae la fuente, sin
        ninguna transformación adicional.
    """
    try:
        if dataframe is None or dataframe.empty or date_column not in dataframe.columns:
            return {"primer_dato": None, "ultimo_dato": None, "registros": 0}

        parsed_dates = pd.to_datetime(dataframe[date_column], errors="coerce").dropna()

        if parsed_dates.empty:
            return {"primer_dato": None, "ultimo_dato": None, "registros": 0}

        return {
            "primer_dato": parsed_dates.min(),
            "ultimo_dato": parsed_dates.max(),
            "registros": int(len(parsed_dates)),
        }

    except Exception as error:
        LOGGER.exception(
            "Error al describir la cobertura histórica de una fuente. "
            "Tipo: %s. Detalle: %s",
            type(error).__name__,
            error,
        )
        return {"primer_dato": None, "ultimo_dato": None, "registros": 0}


def get_liqglob_source_coverage_report(
    master_dataframe: pd.DataFrame,
    rrp_raw_dataframe: Optional[pd.DataFrame] = None,
    eurusd_raw_dataframe: Optional[pd.DataFrame] = None,
    current_accounts_raw_dataframe: Optional[pd.DataFrame] = None,
    min_reserve_requirements_raw_dataframe: Optional[pd.DataFrame] = None,
    deposit_facility_raw_dataframe: Optional[pd.DataFrame] = None,
    marginal_lending_facility_raw_dataframe: Optional[pd.DataFrame] = None,
    ecb_liquidity_dataframe: Optional[pd.DataFrame] = None,
) -> Dict[str, Dict[str, object]]:
    """
    Reporte de auditoría: cobertura histórica REAL de cada fuente cruda
    usada por LIQGLOB, antes de cualquier alineación semanal o recorte.

    Este reporte existe para responder de forma verificable (no
    especulativa) si una región "empieza tarde" en el gráfico porque su
    fuente oficial realmente no tiene historia anterior, o porque algo en
    el procesamiento la está perdiendo - comparando el primer/último dato
    y la cantidad de registros crudos de cada fuente. Incluye los 4
    componentes del BCE (la fuente ACTIVA de LIQEUR desde la migración de
    metodología) y, además, EXLIQ (que ahora es solo la serie de
    referencia de la Validación Metodológica, ya no participa en el
    cálculo con la metodología activa por defecto).

    Parameters
    ----------
    master_dataframe : pd.DataFrame
        DataFrame Maestro de math_processor.py (para el rango de WALCL,
        como referencia de la fuente semanal de EE.UU.).
    rrp_raw_dataframe : Optional[pd.DataFrame]
        Serie cruda de RRP (RRPONTSYD).
    eurusd_raw_dataframe : Optional[pd.DataFrame]
        Serie cruda de EUR/USD (DEXUSEU).
    current_accounts_raw_dataframe, min_reserve_requirements_raw_dataframe,
    deposit_facility_raw_dataframe, marginal_lending_facility_raw_dataframe : Optional[pd.DataFrame]
        Series crudas de los 4 componentes oficiales del BCE.
    ecb_liquidity_dataframe : Optional[pd.DataFrame]
        Serie cruda de Liquidez Excedentaria del BCE
        (ILM.D.U2.C.EXLIQ.U2.EUR) - ahora solo referencia de validación.

    Returns
    -------
    Dict[str, Dict[str, object]]
        Mapa fuente -> {"primer_dato", "ultimo_dato", "registros"}.
    """
    try:
        walcl_source = (
            master_dataframe.loc[:, ["Date", "WALCL"]].dropna(subset=["WALCL"])
            if not master_dataframe.empty and "WALCL" in master_dataframe.columns
            else pd.DataFrame(columns=["Date", "WALCL"])
        )

        return {
            "WALCL (referencia EE.UU., FRED)": _describe_raw_source_coverage(walcl_source),
            "RRP - RRPONTSYD (FRED, crudo)": _describe_raw_source_coverage(rrp_raw_dataframe),
            "EUR/USD - DEXUSEU (FRED, crudo)": _describe_raw_source_coverage(eurusd_raw_dataframe),
            "Current Accounts - ILM.D.U2.C.L020100.U2.EUR (fuente activa LIQEUR)": _describe_raw_source_coverage(
                current_accounts_raw_dataframe
            ),
            "Minimum Reserve Req. - ILM.D.U2.C.MRR.U2.EUR (fuente activa LIQEUR)": _describe_raw_source_coverage(
                min_reserve_requirements_raw_dataframe
            ),
            "Deposit Facility - ILM.D.U2.C.L020200.U2.EUR (fuente activa LIQEUR)": _describe_raw_source_coverage(
                deposit_facility_raw_dataframe
            ),
            "Marginal Lending Facility - ILM.D.U2.C.A050500.U2.EUR (fuente activa LIQEUR)": _describe_raw_source_coverage(
                marginal_lending_facility_raw_dataframe
            ),
            "Liquidez Excedentaria BCE - ILM.D.U2.C.EXLIQ.U2.EUR (solo referencia de validación)": _describe_raw_source_coverage(
                ecb_liquidity_dataframe
            ),
        }

    except Exception as error:
        LOGGER.exception(
            "Error al generar el reporte de cobertura histórica de LIQGLOB. "
            "Tipo: %s. Detalle: %s",
            type(error).__name__,
            error,
        )
        return {}

