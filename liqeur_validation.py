"""
Validación Metodológica de LIQEUR (Control de Calidad): compara, día a
día, la reconstrucción por los 4 componentes oficiales del BCE contra la
serie consolidada ILM.D.U2.C.EXLIQ.U2.EUR.

QUÉ ES ESTO Y POR QUÉ EXISTE:
Este módulo nació como una validación puntual (¿la fórmula oficial del
BCE, aplicada a sus 4 componentes públicos, reproduce la serie
consolidada EXLIQ?) y, tras confirmarse empíricamente que sí (correlación
≈ 1.000000, diferencia porcentual media ≈ 0 en la validación realizada),
se convierte en una herramienta PERMANENTE de control de calidad. Su
propósito ya no es decidir si sustituir la metodología una única vez,
sino vigilar de forma continua que ambas series sigan coincidiendo cada
vez que se carga el programa - si en el futuro el BCE cambiara algo en su
metodología de publicación (de EXLIQ o de cualquiera de los 4
componentes), esta sección lo mostraría de inmediato como una
discrepancia nueva, sin que nadie tenga que acordarse de revisarlo
manualmente.

QUÉ COMPARA: LIQEUR_Reconstruida (calculada aquí, a partir de los 4
componentes crudos) contra EXLIQ_Oficial (la serie consolidada tal cual
la publica el BCE), fecha por fecha, únicamente donde ambas tienen dato
real ese mismo día.

CANDADO - INDEPENDENCIA ABSOLUTA (auditado y confirmado, ver informe de
auditoría entregado junto con esta actualización):
  - Este módulo NO modifica liqglob.py.
  - NO participa en el cálculo de LIQGLOB_USD_B.
  - NO afecta el gráfico principal de la pestaña LIQGLOB en absoluto.
  - Es un módulo de solo LECTURA: recibe DataFrames ya descargados por
    otras funciones, calcula y devuelve resultados - nunca escribe,
    muta, ni comparte estado con el cálculo principal de LIQGLOB.
  - La metodología ACTIVA de LIQEUR sigue usando ILM.D.U2.C.EXLIQ.U2.EUR
    directamente, sin ningún cambio. Esta sección NO es el cálculo
    oficial de LIQGLOB - es una auditoría paralela e independiente sobre
    él. Sustituir EXLIQ por la reconstrucción seguirá siendo, en todo
    momento, una decisión manual y explícita, nunca automática.

Fórmula oficial del BCE (confirmada textualmente en múltiples ediciones
del ECB Economic Bulletin, 2023-2026 - ver informe de investigación
previo a este módulo):

    LIQEUR_Reconstruida = (Current Accounts - Minimum Reserve Requirements)
                           + Deposit Facility - Marginal Lending Facility

Filosofía de la reconstrucción: rigor máximo, cero relleno. La
reconstrucción se calcula únicamente sobre fechas donde los 4
componentes tienen dato REAL simultáneamente (inner join estricto, sin
forward-fill) - nunca mezcla información de días distintos ni inventa un
valor donde falta uno de los 4. La comparación contra EXLIQ oficial usa,
a su vez, únicamente las fechas donde AMBAS series (reconstruida y
oficial) tienen dato real.

ESTADO AUTOMÁTICO (🟢 VALIDADA / 🟡 REVISAR / 🔴 NO VALIDADA): se calcula
en `compute_validation_status()` a partir de umbrales documentados en
config.LIQEUR_VALIDATION_STATUS_THRESHOLDS - nunca es un texto fijo ni
una decisión manual; se recalcula con los datos reales de cada carga.
"""

import logging
from typing import Dict, Optional

import numpy as np
import pandas as pd

from config import LIQEUR_VALIDATION_STATUS_THRESHOLDS, LIQEUR_VALIDATION_TOP_N_DISCREPANCIES

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

LOGGER = logging.getLogger(__name__)

RECONSTRUCTION_COLUMNS = [
    "Date",
    "CurrentAccounts",
    "MinReserveReq",
    "DepositFacility",
    "MarginalLendingFacility",
    "LIQEUR_Reconstruida",
]

COMPARISON_COLUMNS = [
    "Date",
    "EXLIQ_Oficial",
    "LIQEUR_Reconstruida",
    "Diferencia",
    "Diferencia_Abs",
    "Diferencia_Pct",
]


def _clean_raw_component(raw_dataframe: Optional[pd.DataFrame], output_column: str) -> Optional[pd.DataFrame]:
    """
    Estandariza un DataFrame crudo (Date, Value) de un componente del BCE:
    parsea fechas/valores, descarta filas inválidas y renombra Value a
    `output_column`. No aplica ningún forward-fill ni relleno.

    Returns
    -------
    Optional[pd.DataFrame]
        Columnas Date y `output_column`, o None si no hay datos
        aprovechables.
    """
    try:
        if raw_dataframe is None or raw_dataframe.empty:
            return None
        if "Date" not in raw_dataframe.columns or "Value" not in raw_dataframe.columns:
            return None

        working = raw_dataframe.loc[:, ["Date", "Value"]].copy()
        working["Date"] = pd.to_datetime(working["Date"], errors="coerce")
        working["Value"] = pd.to_numeric(working["Value"], errors="coerce")
        working = working.dropna(subset=["Date", "Value"])
        working = working.drop_duplicates(subset=["Date"], keep="last")
        working = working.sort_values(by="Date").reset_index(drop=True)

        if working.empty:
            return None

        return working.rename(columns={"Value": output_column})

    except Exception as error:
        LOGGER.exception(
            "Error al limpiar el componente crudo %s. Tipo: %s. Detalle: %s",
            output_column,
            type(error).__name__,
            error,
        )
        return None


def build_liqeur_reconstruction(
    current_accounts_raw: Optional[pd.DataFrame],
    min_reserve_requirements_raw: Optional[pd.DataFrame],
    deposit_facility_raw: Optional[pd.DataFrame],
    marginal_lending_facility_raw: Optional[pd.DataFrame],
) -> pd.DataFrame:
    """
    Reconstruye LIQEUR día a día a partir de los 4 componentes CRUDOS del
    BCE (Current Accounts, Minimum Reserve Requirements, Deposit
    Facility, Marginal Lending Facility), aplicando la fórmula oficial:

        LIQEUR_Reconstruida = (Current Accounts - Minimum Reserve
                                Requirements) + Deposit Facility -
                                Marginal Lending Facility

    El merge entre los 4 componentes es un INNER JOIN estricto sobre
    Date - solo se calcula un valor reconstruido para fechas donde los
    CUATRO componentes tienen una observación real ese mismo día. No hay
    forward-fill ni relleno de ningún tipo.

    Parameters
    ----------
    current_accounts_raw : Optional[pd.DataFrame]
        Serie cruda (Date, Value) de ILM.D.U2.C.L020100.U2.EUR.
    min_reserve_requirements_raw : Optional[pd.DataFrame]
        Serie cruda (Date, Value) de ILM.D.U2.C.MRR.U2.EUR.
    deposit_facility_raw : Optional[pd.DataFrame]
        Serie cruda (Date, Value) de ILM.D.U2.C.L020200.U2.EUR.
    marginal_lending_facility_raw : Optional[pd.DataFrame]
        Serie cruda (Date, Value) de ILM.D.U2.C.A050500.U2.EUR.

    Returns
    -------
    pd.DataFrame
        Columnas RECONSTRUCTION_COLUMNS. Vacío si falta cualquiera de
        los 4 componentes o no hay fechas en común entre los cuatro.
    """
    empty_result = pd.DataFrame(columns=RECONSTRUCTION_COLUMNS)

    try:
        current_accounts = _clean_raw_component(current_accounts_raw, "CurrentAccounts")
        min_reserve_req = _clean_raw_component(min_reserve_requirements_raw, "MinReserveReq")
        deposit_facility = _clean_raw_component(deposit_facility_raw, "DepositFacility")
        marginal_lending_facility = _clean_raw_component(
            marginal_lending_facility_raw, "MarginalLendingFacility"
        )

        missing_components = [
            name
            for name, dataframe in (
                ("Current Accounts", current_accounts),
                ("Minimum Reserve Requirements", min_reserve_req),
                ("Deposit Facility", deposit_facility),
                ("Marginal Lending Facility", marginal_lending_facility),
            )
            if dataframe is None
        ]
        if missing_components:
            LOGGER.warning(
                "No se puede reconstruir LIQEUR: faltan componentes: %s.",
                missing_components,
            )
            return empty_result

        merged = current_accounts
        for component_dataframe in (min_reserve_req, deposit_facility, marginal_lending_facility):
            merged = pd.merge(merged, component_dataframe, on="Date", how="inner")

        merged = merged.sort_values(by="Date").reset_index(drop=True)

        if merged.empty:
            LOGGER.warning(
                "Los 4 componentes de LIQEUR no comparten ninguna fecha en común."
            )
            return empty_result

        merged["LIQEUR_Reconstruida"] = (
            merged["CurrentAccounts"]
            - merged["MinReserveReq"]
            + merged["DepositFacility"]
            - merged["MarginalLendingFacility"]
        )

        LOGGER.info(
            "Reconstrucción de LIQEUR completada. Fechas con los 4 "
            "componentes disponibles: %s (de %s a %s).",
            len(merged),
            merged["Date"].min().strftime("%Y-%m-%d"),
            merged["Date"].max().strftime("%Y-%m-%d"),
        )

        return merged.loc[:, RECONSTRUCTION_COLUMNS]

    except Exception as error:
        LOGGER.exception(
            "Error al reconstruir LIQEUR por componentes. Tipo: %s. Detalle: %s",
            type(error).__name__,
            error,
        )
        return empty_result


def compare_liqeur_reconstruction_vs_official(
    reconstructed_dataframe: pd.DataFrame,
    exliq_official_raw: Optional[pd.DataFrame],
) -> Dict[str, object]:
    """
    Compara, observación por observación, LIQEUR_Reconstruida contra la
    serie oficial EXLIQ, únicamente en las fechas donde AMBAS series
    tienen un dato real (inner join estricto - nunca se compara un
    reconstruido de un día contra un oficial de otro día).

    Parameters
    ----------
    reconstructed_dataframe : pd.DataFrame
        Resultado de build_liqeur_reconstruction().
    exliq_official_raw : Optional[pd.DataFrame]
        Serie cruda (Date, Value) de ILM.D.U2.C.EXLIQ.U2.EUR (resultado
        directo de data_ingestion.get_ecb_liquidity_data(), sin ffill).

    Returns
    -------
    Dict[str, object]
        "disponible": bool - False si no hay suficientes datos para
            comparar (en cuyo caso "motivo" explica por qué).
        Si "disponible" es True, además incluye:
        "max_diferencia_abs", "media_diferencia_abs",
        "media_diferencia_pct", "correlacion" (Pearson),
        "primera_fecha", "ultima_fecha", "n_observaciones",
        "peores_discrepancias" (DataFrame, las
        LIQEUR_VALIDATION_TOP_N_DISCREPANCIES fechas con mayor diferencia
        absoluta) y "serie_comparada" (DataFrame completo, por si se
        quiere graficar).
    """
    empty_result: Dict[str, object] = {
        "disponible": False,
        "motivo": "Todavía no hay suficientes datos reales en común entre la "
        "reconstrucción y la serie oficial para comparar.",
    }

    try:
        if reconstructed_dataframe is None or reconstructed_dataframe.empty:
            return empty_result

        official = _clean_raw_component(exliq_official_raw, "EXLIQ_Oficial")
        if official is None:
            return empty_result

        merged = pd.merge(
            reconstructed_dataframe.loc[:, ["Date", "LIQEUR_Reconstruida"]],
            official,
            on="Date",
            how="inner",
        )
        merged = merged.sort_values(by="Date").reset_index(drop=True)

        if merged.empty:
            return empty_result

        merged["Diferencia"] = merged["LIQEUR_Reconstruida"] - merged["EXLIQ_Oficial"]
        merged["Diferencia_Abs"] = merged["Diferencia"].abs()

        with np.errstate(divide="ignore", invalid="ignore"):
            percent_difference = np.where(
                merged["EXLIQ_Oficial"] != 0,
                (merged["Diferencia"] / merged["EXLIQ_Oficial"]) * 100.0,
                np.nan,
            )
        merged["Diferencia_Pct"] = percent_difference
        merged["Diferencia_Pct"] = merged["Diferencia_Pct"].replace([np.inf, -np.inf], np.nan)

        max_abs_diff = float(merged["Diferencia_Abs"].max())
        mean_abs_diff = float(merged["Diferencia_Abs"].mean())
        mean_pct_diff = float(merged["Diferencia_Pct"].abs().mean(skipna=True))
        # Correlación de Pearson entre ambas series - NaN si alguna de
        # las dos es constante (desviación estándar cero) en la ventana
        # comparada.
        correlation_value = merged["LIQEUR_Reconstruida"].corr(merged["EXLIQ_Oficial"])
        correlation = float(correlation_value) if pd.notna(correlation_value) else None

        worst_discrepancies = (
            merged.reindex(merged["Diferencia_Abs"].sort_values(ascending=False).index)
            .head(LIQEUR_VALIDATION_TOP_N_DISCREPANCIES)
            .loc[:, COMPARISON_COLUMNS]
            .reset_index(drop=True)
        )

        LOGGER.info(
            "Validación LIQEUR completada. Observaciones comparadas: %s. "
            "Diferencia máxima: %.2f. Diferencia media: %.2f. "
            "Correlación: %s.",
            len(merged),
            max_abs_diff,
            mean_abs_diff,
            correlation,
        )

        return {
            "disponible": True,
            "max_diferencia_abs": max_abs_diff,
            "media_diferencia_abs": mean_abs_diff,
            "media_diferencia_pct": mean_pct_diff,
            "correlacion": correlation,
            "primera_fecha": merged["Date"].min(),
            "ultima_fecha": merged["Date"].max(),
            "n_observaciones": int(len(merged)),
            "peores_discrepancias": worst_discrepancies,
            "serie_comparada": merged.loc[:, COMPARISON_COLUMNS],
        }

    except Exception as error:
        LOGGER.exception(
            "Error al comparar LIQEUR reconstruida vs EXLIQ oficial. "
            "Tipo: %s. Detalle: %s",
            type(error).__name__,
            error,
        )
        return empty_result


# =====================================================================
# ESTADO AUTOMÁTICO DE LA VALIDACIÓN (semáforo dinámico)
# =====================================================================
# Esta función es de SOLO LECTURA: recibe el resultado ya calculado por
# compare_liqeur_reconstruction_vs_official() y únicamente lo clasifica
# contra los umbrales documentados en config.py. No vuelve a calcular
# nada, no descarga nada, no toca ningún estado compartido - es
# deliberadamente la función más simple de este módulo, precisamente
# porque es la que decide qué "semáforo" ve el usuario y no debe tener
# ninguna lógica oculta ni umbrales improvisados.
def compute_validation_status(validation_report: Dict[str, object]) -> Dict[str, str]:
    """
    Calcula el estado automático (🟢 VALIDADA / 🟡 REVISAR /
    🔴 NO VALIDADA / ⚪ SIN DATOS) de la validación metodológica de LIQEUR,
    a partir de los umbrales documentados en
    config.LIQEUR_VALIDATION_STATUS_THRESHOLDS. El estado NUNCA es texto
    fijo: se recalcula en cada carga con los números reales del reporte
    de comparación.

    Parameters
    ----------
    validation_report : Dict[str, object]
        Resultado de compare_liqeur_reconstruction_vs_official().

    Returns
    -------
    Dict[str, str]
        "codigo": "VALIDADA" | "REVISAR" | "NO_VALIDADA" | "SIN_DATOS"
        "emoji": "🟢" | "🟡" | "🔴" | "⚪"
        "etiqueta": texto corto para mostrar junto al emoji
        "mensaje": frase explicativa generada a partir de los números
            reales del reporte (nunca un texto genérico fijo)
    """
    if not validation_report.get("disponible"):
        return {
            "codigo": "SIN_DATOS",
            "emoji": "⚪",
            "etiqueta": "SIN DATOS SUFICIENTES",
            "mensaje": validation_report.get(
                "motivo",
                "Todavía no hay suficientes datos reales en común para "
                "evaluar el estado de la validación.",
            ),
        }

    correlation = validation_report.get("correlacion")
    mean_pct_diff = validation_report.get("media_diferencia_pct")
    mean_abs_diff = validation_report.get("media_diferencia_abs")
    n_observations = validation_report.get("n_observaciones", 0)

    correlation_for_check = correlation if correlation is not None else -1.0
    pct_for_check = mean_pct_diff if (mean_pct_diff is not None and pd.notna(mean_pct_diff)) else float("inf")

    thresholds = LIQEUR_VALIDATION_STATUS_THRESHOLDS

    is_validated = (
        correlation_for_check >= thresholds["correlacion_validada"]
        and pct_for_check <= thresholds["diferencia_pct_validada"]
    )
    is_review = (
        not is_validated
        and correlation_for_check >= thresholds["correlacion_revisar"]
        and pct_for_check <= thresholds["diferencia_pct_revisar"]
    )

    correlation_text = f"{correlation:.6f}" if correlation is not None else "N/D"
    mean_abs_diff_text = f"{mean_abs_diff:,.1f} M€" if mean_abs_diff is not None else "N/D"
    mean_pct_diff_text = (
        f"{mean_pct_diff:.4f}%" if (mean_pct_diff is not None and pd.notna(mean_pct_diff)) else "N/D"
    )

    if is_validated:
        return {
            "codigo": "VALIDADA",
            "emoji": "🟢",
            "etiqueta": "VALIDADA",
            "mensaje": (
                f"La reconstrucción reproduce correctamente la serie oficial "
                f"del BCE en las {n_observations} observaciones comparadas "
                f"(correlación {correlation_text}, diferencia porcentual "
                f"media {mean_pct_diff_text}, diferencia media "
                f"{mean_abs_diff_text})."
            ),
        }

    if is_review:
        return {
            "codigo": "REVISAR",
            "etiqueta": "REVISAR",
            "emoji": "🟡",
            "mensaje": (
                f"La reconstrucción se parece a la serie oficial pero no "
                f"alcanza el umbral de validación estricta (correlación "
                f"{correlation_text}, diferencia porcentual media "
                f"{mean_pct_diff_text}). Revisa la tabla de peores "
                f"discrepancias antes de sacar conclusiones."
            ),
        }

    return {
        "codigo": "NO_VALIDADA",
        "emoji": "🔴",
        "etiqueta": "NO VALIDADA",
        "mensaje": (
            f"La reconstrucción se aleja de la serie oficial más allá de "
            f"los umbrales esperados (correlación {correlation_text}, "
            f"diferencia porcentual media {mean_pct_diff_text}). No se "
            f"recomienda considerar la sustitución de la metodología "
            f"activa hasta entender esta discrepancia."
        ),
    }

