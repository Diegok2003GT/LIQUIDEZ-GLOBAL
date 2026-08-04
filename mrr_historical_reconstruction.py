"""
Reconstrucción histórica de MRR (Minimum Reserve Requirements) para el
tramo anterior a 2024-09-27, usando la serie oficial mensual
BSI.M.U2.N.R.MRR.X.1.A1.3000.Z01.E y el calendario oficial de
Maintenance Periods del BCE (ver mp_calendar.py).

CANDADO: módulo 100% aditivo y aislado. No modifica math_processor.py,
advanced_liquidity.py, ni la lógica de alineación semanal de liqglob.py
(_select_weekly_value_with_fallback, sin ninguna modificación). Este
módulo únicamente produce una serie CRUDA (Date, Value) de MRR histórico,
con exactamente el mismo formato que ya produce
data_ingestion.get_ecb_liquidity_data() para el resto de fuentes - se
integra al pipeline existente sin que liqglob.py necesite tratarla de
forma especial más allá de combinarla con la serie oficial ILM.D (ver
`combine_mrr_sources_with_priority`).

POR QUÉ NO ES UNA APROXIMACIÓN MENSUAL (ver diseño previo, sección
"Candidatas A/B/C" descartada): con el calendario REAL de Maintenance
Periods disponible (mp_calendar.py, 2004+), ya no hace falta aproximar
por mes calendario. La asociación es exacta: cada observación mensual de
BSI se asigna al Maintenance Period que contiene su fecha (fin de mes),
y ese valor se propaga ÚNICAMENTE dentro de los días reales de ese
Maintenance Period - nunca por mes calendario, nunca interpolado, nunca
promediado.

INTEGRIDAD: un Maintenance Period sin ninguna observación mensual de BSI
dentro de su rango de fechas queda SIN valor asignado (no se rellena con
el mes más cercano) - esa porción del histórico simplemente no participa,
igual filosofía que el resto del programa.
"""

import logging
from datetime import date, timedelta
from typing import Dict, Optional

import numpy as np
import pandas as pd

LOGGER = logging.getLogger(__name__)


def assign_bsi_observations_to_maintenance_periods(
    bsi_mrr_raw: pd.DataFrame,
    calendar_dataframe: pd.DataFrame,
) -> pd.DataFrame:
    """
    Asigna cada observación mensual de BSI-MRR al Maintenance Period
    real que contiene su fecha. Solo se asigna un valor a un MP si
    existe al menos una observación BSI cuya fecha caiga dentro de
    [StartDate, EndDate] de ese MP - nunca se usa la observación "más
    cercana" de otro período.

    Parameters
    ----------
    bsi_mrr_raw : pd.DataFrame
        Serie cruda (Date, Value) de BSI.M.U2.N.R.MRR.X.1.A1.3000.Z01.E,
        resultado directo de data_ingestion.get_ecb_liquidity_data().
    calendar_dataframe : pd.DataFrame
        Resultado de mp_calendar.update_maintenance_period_calendar()
        (columnas Year, MP, GCMeetingDate, StartDate, EndDate).

    Returns
    -------
    pd.DataFrame
        Columnas Year, MP, StartDate, EndDate, MRR_Value - solo para los
        Maintenance Periods que sí tienen una observación BSI real dentro
        de su rango.
    """
    empty_result = pd.DataFrame(columns=["Year", "MP", "StartDate", "EndDate", "MRR_Value"])

    if bsi_mrr_raw is None or bsi_mrr_raw.empty:
        LOGGER.warning("Sin observaciones crudas de BSI-MRR; no se puede asociar a Maintenance Periods.")
        return empty_result
    if calendar_dataframe is None or calendar_dataframe.empty:
        LOGGER.warning("Sin calendario de Maintenance Periods disponible; no se puede asociar BSI-MRR.")
        return empty_result

    working_bsi = bsi_mrr_raw.loc[:, ["Date", "Value"]].copy()
    working_bsi["Date"] = pd.to_datetime(working_bsi["Date"], errors="coerce")
    working_bsi["Value"] = pd.to_numeric(working_bsi["Value"], errors="coerce")
    working_bsi = working_bsi.dropna(subset=["Date", "Value"])
    working_bsi = working_bsi.sort_values(by="Date")

    if working_bsi.empty:
        return empty_result

    assigned_rows = []
    for _, mp_row in calendar_dataframe.iterrows():
        period_start = mp_row["StartDate"]
        period_end = mp_row["EndDate"]

        observations_in_period = working_bsi[
            (working_bsi["Date"].dt.date >= period_start)
            & (working_bsi["Date"].dt.date <= period_end)
        ]
        if observations_in_period.empty:
            continue

        # Si un Maintenance Period contiene más de un fin de mes de BSI
        # (posible en períodos largos), se usa la observación MÁS
        # RECIENTE dentro del período - el requerimiento no cambia
        # durante el MP, así que cualquier observación real dentro de él
        # es válida, pero la más reciente es la más representativa del
        # dato ya consolidado por el BCE para ese período.
        selected_observation = observations_in_period.sort_values(by="Date").iloc[-1]

        assigned_rows.append(
            {
                "Year": mp_row["Year"],
                "MP": mp_row["MP"],
                "StartDate": period_start,
                "EndDate": period_end,
                "MRR_Value": selected_observation["Value"],
            }
        )

    if not assigned_rows:
        return empty_result

    return pd.DataFrame(assigned_rows)


def build_mrr_historical_daily_series(
    bsi_mrr_raw: pd.DataFrame,
    calendar_dataframe: pd.DataFrame,
) -> pd.DataFrame:
    """
    Construye una serie DIARIA cruda de MRR histórico (mismo formato
    Date/Value que el resto de fuentes del programa), propagando el
    valor asignado a cada Maintenance Period ÚNICAMENTE dentro de sus
    días reales (StartDate a EndDate, inclusive) - nunca por mes
    calendario, nunca más allá del rango real del período.

    Returns
    -------
    pd.DataFrame
        Columnas Date, Value - una fila por cada día cubierto por algún
        Maintenance Period con observación BSI asignada. Los días fuera
        de cobertura simplemente no aparecen (no se inventan).
    """
    empty_result = pd.DataFrame(columns=["Date", "Value"])

    assigned_periods = assign_bsi_observations_to_maintenance_periods(
        bsi_mrr_raw, calendar_dataframe
    )
    if assigned_periods.empty:
        return empty_result

    daily_rows = []
    for _, period_row in assigned_periods.iterrows():
        period_dates = pd.date_range(start=period_row["StartDate"], end=period_row["EndDate"], freq="D")
        for day in period_dates:
            daily_rows.append({"Date": day, "Value": period_row["MRR_Value"]})

    if not daily_rows:
        return empty_result

    daily_dataframe = pd.DataFrame(daily_rows)
    daily_dataframe = daily_dataframe.drop_duplicates(subset=["Date"], keep="last")
    daily_dataframe = daily_dataframe.sort_values(by="Date").reset_index(drop=True)

    return daily_dataframe


def combine_mrr_sources_with_priority(
    ilm_daily_mrr_raw: Optional[pd.DataFrame],
    historical_mrr_daily: Optional[pd.DataFrame],
) -> pd.DataFrame:
    """
    Combina la serie oficial diaria (ILM.D.U2.C.MRR.U2.EUR, prioritaria
    siempre que tenga dato real) con la reconstrucción histórica
    (BSI + calendario) - la reconstrucción histórica SOLO se usa para
    fechas donde la serie oficial ILM.D no tiene un dato real. Este es
    exactamente el mecanismo de "detección automática de la transición"
    diseñado previamente: no depende de ninguna fecha fija, solo de cuál
    fuente tiene dato real ese día.

    Returns
    -------
    pd.DataFrame
        Columnas Date, Value - lista para pasar tal cual a
        liqglob._select_weekly_value_with_fallback, sin ningún cambio en
        esa función.
    """
    official_dataframe = pd.DataFrame(columns=["Date", "Value"])
    if ilm_daily_mrr_raw is not None and not ilm_daily_mrr_raw.empty:
        official_dataframe = ilm_daily_mrr_raw.loc[:, ["Date", "Value"]].copy()
        official_dataframe["Date"] = pd.to_datetime(official_dataframe["Date"], errors="coerce")
        official_dataframe = official_dataframe.dropna(subset=["Date"])

    historical_dataframe = pd.DataFrame(columns=["Date", "Value"])
    if historical_mrr_daily is not None and not historical_mrr_daily.empty:
        historical_dataframe = historical_mrr_daily.loc[:, ["Date", "Value"]].copy()
        historical_dataframe["Date"] = pd.to_datetime(historical_dataframe["Date"], errors="coerce")
        historical_dataframe = historical_dataframe.dropna(subset=["Date"])

    if official_dataframe.empty and historical_dataframe.empty:
        return pd.DataFrame(columns=["Date", "Value"])

    official_dates = set(official_dataframe["Date"])
    historical_only = historical_dataframe[~historical_dataframe["Date"].isin(official_dates)]

    combined = pd.concat([historical_only, official_dataframe], ignore_index=True)
    combined = combined.drop_duplicates(subset=["Date"], keep="last")
    combined = combined.sort_values(by="Date").reset_index(drop=True)

    return combined


def get_mrr_reconstruction_coverage_report(
    bsi_mrr_raw: Optional[pd.DataFrame],
    calendar_dataframe: Optional[pd.DataFrame],
    ilm_daily_mrr_raw: Optional[pd.DataFrame],
) -> Dict[str, object]:
    """
    Reporte de auditoría para el Health Check: cobertura real de cada
    pieza de la reconstrucción histórica de MRR, y en qué fecha ocurre
    la transición automática hacia la serie oficial ILM.D.

    Returns
    -------
    Dict[str, object]
        "bsi_primer_dato", "bsi_ultimo_dato", "bsi_registros",
        "calendario_primer_año", "calendario_ultimo_año",
        "calendario_periodos_validados",
        "reconstruccion_historica_primer_dia",
        "reconstruccion_historica_ultimo_dia",
        "ilm_primer_dato", "transicion_automatica_detectada_en".
    """
    report: Dict[str, object] = {}

    if bsi_mrr_raw is not None and not bsi_mrr_raw.empty:
        bsi_dates = pd.to_datetime(bsi_mrr_raw["Date"], errors="coerce").dropna()
        report["bsi_primer_dato"] = bsi_dates.min() if not bsi_dates.empty else None
        report["bsi_ultimo_dato"] = bsi_dates.max() if not bsi_dates.empty else None
        report["bsi_registros"] = int(len(bsi_dates))
    else:
        report["bsi_primer_dato"] = None
        report["bsi_ultimo_dato"] = None
        report["bsi_registros"] = 0

    if calendar_dataframe is not None and not calendar_dataframe.empty:
        report["calendario_primer_año"] = int(calendar_dataframe["Year"].min())
        report["calendario_ultimo_año"] = int(calendar_dataframe["Year"].max())
        report["calendario_periodos_validados"] = int(len(calendar_dataframe))
    else:
        report["calendario_primer_año"] = None
        report["calendario_ultimo_año"] = None
        report["calendario_periodos_validados"] = 0

    historical_daily = build_mrr_historical_daily_series(bsi_mrr_raw, calendar_dataframe)
    if not historical_daily.empty:
        report["reconstruccion_historica_primer_dia"] = historical_daily["Date"].min()
        report["reconstruccion_historica_ultimo_dia"] = historical_daily["Date"].max()
    else:
        report["reconstruccion_historica_primer_dia"] = None
        report["reconstruccion_historica_ultimo_dia"] = None

    if ilm_daily_mrr_raw is not None and not ilm_daily_mrr_raw.empty:
        ilm_dates = pd.to_datetime(ilm_daily_mrr_raw["Date"], errors="coerce").dropna()
        report["ilm_primer_dato"] = ilm_dates.min() if not ilm_dates.empty else None
        report["transicion_automatica_detectada_en"] = ilm_dates.min() if not ilm_dates.empty else None
    else:
        report["ilm_primer_dato"] = None
        report["transicion_automatica_detectada_en"] = None

    return report
