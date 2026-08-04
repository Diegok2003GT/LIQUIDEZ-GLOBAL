"""
Calendario oficial de Maintenance Periods del BCE (2004+): scraping
robusto, caché persistente y validación estructural obligatoria.

CANDADO: módulo 100% aditivo y aislado. No modifica math_processor.py,
advanced_liquidity.py, ni la lógica existente de liqglob.py más allá de
alimentar (de forma opcional) la reconstrucción histórica de MRR. Ningún
fallo de este módulo puede afectar LIQEEUU, la alineación semanal
(_select_weekly_value_with_fallback), ni la Validación Metodológica de
LIQEUR - si este módulo falla por completo, la reconstrucción histórica
de MRR simplemente no está disponible para los años afectados; el resto
del programa sigue funcionando exactamente igual.

POR QUÉ ESTE MÓDULO EXISTE (ver informes de investigación previos):
ILM.D.U2.C.MRR.U2.EUR (la fuente activa de MRR) solo tiene historial
desde 2024-09-27. El BCE no publica un calendario de Maintenance Periods
como dataset SDMX/API - solo como comunicados de prensa HTML/PDF. Este
módulo scrapea esa fuente oficial (una página índice estable,
`ecb.europa.eu/press/calendars/caleu/html/index.en.html`, verificada en
vivo durante el diseño de esta arquitectura), la valida estructuralmente
antes de confiar en ella, y la cachea de forma permanente.

FILOSOFÍA DE CONFIANZA: a diferencia de las series SDMX del resto del
programa (fuente oficial + API estable = confianza directa), el scraping
HTML/PDF NUNCA se trata como confiable por sí solo. Todo resultado nuevo
pasa por:
  1. Validación estructural (duración de cada período, continuidad entre
     períodos, cantidad de períodos por año) - ver `_validate_year_calendar`.
  2. Verificación contra una referencia dorada conocida (el calendario de
     2014, verificado dato-por-dato durante la investigación) - si el
     scraper alguna vez deja de reproducir correctamente ese año (un
     hecho histórico inmutable), se asume que el formato del sitio del
     BCE cambió, y se descarta CUALQUIER resultado nuevo del scraper
     (no solo el del año que falló) hasta revisión manual.
Un calendario que no pasa ambas verificaciones se descarta por completo -
nunca se usa parcialmente.

CACHÉ EN TRES CAPAS:
  1. Semilla (ECB_MP_CALENDAR_SEED_FILE): empaquetada con el código,
     contiene años ya validados manualmente - sobrevive aunque el sitio
     del BCE cambie o el entorno de despliegue sea efímero.
  2. Caché de ejecución (ECB_MP_CALENDAR_CACHE_FILE): años agregados en
     tiempo de ejecución mediante scraping exitoso y validado.
  3. Exportación permanente (ECB_MP_CALENDAR_EXPORT_FILE): copia de todo
     lo validado hasta ahora, pensada para respaldar/versionar fuera del
     programa (Requisito 4 del usuario).
Los años ya transcurridos, una vez validados, se consideran definitivos
y NUNCA se vuelven a descargar (Requisito 1/2). El año en curso (todavía
no transcurrido por completo) se revalida en cada actualización, porque
un calendario "indicativo" en curso podría ajustarse.
"""

import json
import logging
import os
import re
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple

import pandas as pd
import requests

from config import (
    ECB_MP_CALENDAR_CACHE_FILE,
    ECB_MP_CALENDAR_EXPORT_FILE,
    ECB_MP_CALENDAR_FIRST_YEAR,
    ECB_MP_CALENDAR_INDEX_URL,
    ECB_MP_CALENDAR_SEED_FILE,
    ECB_MP_GOLDEN_REFERENCE_CALENDAR,
    ECB_MP_GOLDEN_REFERENCE_YEAR,
    ECB_MP_MAX_DAYS,
    ECB_MP_MAX_PERIODS_PER_YEAR,
    ECB_MP_MIN_DAYS,
    ECB_MP_MIN_PERIODS_PER_YEAR,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

LOGGER = logging.getLogger(__name__)

CALENDAR_COLUMNS = ["Year", "MP", "GCMeetingDate", "StartDate", "EndDate"]

_MONTH_NAMES = (
    "january|february|march|april|may|june|july|august|september|october|"
    "november|december"
)
_DATE_PATTERN = re.compile(
    r"(\d{1,2})\s+(" + _MONTH_NAMES + r")\s+(\d{4})", re.IGNORECASE
)


# =====================================================================
# Parseo de fechas y tablas
# =====================================================================
def _parse_english_date(text: str) -> Optional[date]:
    """
    Parsea una fecha en formato "15 January 2014" (el formato usado en
    los comunicados del BCE). Devuelve None si no encuentra un patrón
    reconocible - nunca adivina ni aproxima una fecha.
    """
    if not isinstance(text, str):
        return None
    match = _DATE_PATTERN.search(text.strip())
    if not match:
        return None
    try:
        parsed = datetime.strptime(
            f"{match.group(1)} {match.group(2)} {match.group(3)}", "%d %B %Y"
        )
        return parsed.date()
    except ValueError:
        return None


def _row_looks_like_mp_row(cells: List[str]) -> bool:
    """
    Heurística estricta para reconocer una fila de tabla de Maintenance
    Period: primera celda es un entero pequeño (el número de MP), y hay
    al menos 3 fechas reconocibles en el resto de la fila (reunión del
    Consejo, inicio, fin).
    """
    if not cells:
        return False
    first_cell = cells[0].strip()
    if not first_cell.isdigit():
        return False
    mp_number = int(first_cell)
    if mp_number < 1 or mp_number > 13:
        return False
    dates_found = sum(1 for cell in cells if _parse_english_date(cell) is not None)
    return dates_found >= 3


def _extract_year_table_from_html(html_text: str, year: int) -> Optional[pd.DataFrame]:
    """
    Busca, dentro del HTML de un comunicado del BCE, la tabla del
    calendario de Maintenance Periods para `year`. Usa BeautifulSoup
    (parser tolerante) y una heurística estricta por fila (no por
    posición fija de columna, ya que el BCE ha cambiado ligeramente el
    layout entre años) - reconoce filas por patrón (número de MP seguido
    de al menos 3 fechas), no por índice de columna.

    Returns
    -------
    Optional[pd.DataFrame]
        Columnas CALENDAR_COLUMNS, o None si no se encontró una tabla
        reconocible para ese año.
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        LOGGER.error(
            "beautifulsoup4 no está instalado; no se puede parsear HTML "
            "del calendario del BCE."
        )
        return None

    try:
        soup = BeautifulSoup(html_text, "lxml")
    except Exception:
        soup = BeautifulSoup(html_text, "html.parser")

    candidate_rows: List[List[str]] = []
    for table in soup.find_all("table"):
        for row in table.find_all("tr"):
            cells = [cell.get_text(strip=True) for cell in row.find_all(["td", "th"])]
            if _row_looks_like_mp_row(cells):
                candidate_rows.append(cells)

    # Respaldo: si el BCE no usa <table> para este comunicado (a veces el
    # contenido llega como texto plano con saltos de línea), se intenta
    # reconocer filas también en el texto plano completo, línea por línea.
    if not candidate_rows:
        text_lines = soup.get_text("\n").split("\n")
        for line in text_lines:
            cells = [part.strip() for part in re.split(r"\t|  +", line) if part.strip()]
            if _row_looks_like_mp_row(cells):
                candidate_rows.append(cells)

    if not candidate_rows:
        return None

    parsed_rows = []
    for cells in candidate_rows:
        mp_number = int(cells[0].strip())
        found_dates = [d for d in (_parse_english_date(c) for c in cells) if d is not None]
        if len(found_dates) < 3:
            continue
        gc_meeting, start_date, end_date = found_dates[0], found_dates[1], found_dates[2]
        row_year = start_date.year
        parsed_rows.append(
            {
                "Year": row_year,
                "MP": mp_number,
                "GCMeetingDate": gc_meeting,
                "StartDate": start_date,
                "EndDate": end_date,
            }
        )

    if not parsed_rows:
        return None

    calendar_dataframe = pd.DataFrame(parsed_rows)
    calendar_dataframe = calendar_dataframe[calendar_dataframe["Year"] == year]
    calendar_dataframe = calendar_dataframe.drop_duplicates(subset=["MP"], keep="first")
    calendar_dataframe = calendar_dataframe.sort_values(by="MP").reset_index(drop=True)

    return calendar_dataframe if not calendar_dataframe.empty else None


def _extract_year_table_from_pdf(pdf_bytes: bytes, year: int) -> Optional[pd.DataFrame]:
    """
    Respaldo cuando el año no tiene tabla HTML reconocible: intenta
    extraer la tabla del PDF adjunto usando pdfplumber. Misma heurística
    estricta por fila que la extracción HTML.
    """
    try:
        import io as _io

        import pdfplumber
    except ImportError:
        LOGGER.error(
            "pdfplumber no está instalado; no se puede usar el respaldo "
            "en PDF para el calendario del BCE."
        )
        return None

    parsed_rows = []
    try:
        with pdfplumber.open(_io.BytesIO(pdf_bytes)) as pdf_document:
            for page in pdf_document.pages:
                for table in page.extract_tables() or []:
                    for row in table:
                        cells = [str(cell).strip() if cell else "" for cell in row]
                        if not _row_looks_like_mp_row(cells):
                            continue
                        mp_number = int(cells[0].strip())
                        found_dates = [
                            d for d in (_parse_english_date(c) for c in cells) if d is not None
                        ]
                        if len(found_dates) < 3:
                            continue
                        gc_meeting, start_date, end_date = found_dates[0], found_dates[1], found_dates[2]
                        parsed_rows.append(
                            {
                                "Year": start_date.year,
                                "MP": mp_number,
                                "GCMeetingDate": gc_meeting,
                                "StartDate": start_date,
                                "EndDate": end_date,
                            }
                        )
    except Exception as error:
        LOGGER.exception(
            "Error al extraer tabla del PDF del calendario BCE para %s. "
            "Tipo: %s. Detalle: %s",
            year,
            type(error).__name__,
            error,
        )
        return None

    if not parsed_rows:
        return None

    calendar_dataframe = pd.DataFrame(parsed_rows)
    calendar_dataframe = calendar_dataframe[calendar_dataframe["Year"] == year]
    calendar_dataframe = calendar_dataframe.drop_duplicates(subset=["MP"], keep="first")
    calendar_dataframe = calendar_dataframe.sort_values(by="MP").reset_index(drop=True)

    return calendar_dataframe if not calendar_dataframe.empty else None


# =====================================================================
# Descubrimiento de enlaces (página índice → comunicados/PDF por año)
# =====================================================================
def _discover_year_source_urls(index_html: str) -> Dict[int, List[str]]:
    """
    Parsea la página índice oficial y construye un mapa año -> lista de
    URLs candidatas (comunicado HTML y/o PDF) que podrían contener el
    calendario de ese año. No asume una fila fija por año - busca el
    patrón "Calendars for YYYY" o "reserve maintenance periods in YYYY"
    junto a cada enlace, de forma flexible.
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        LOGGER.error("beautifulsoup4 no está instalado; no se puede parsear el índice.")
        return {}

    try:
        soup = BeautifulSoup(index_html, "lxml")
    except Exception:
        soup = BeautifulSoup(index_html, "html.parser")

    year_to_urls: Dict[int, List[str]] = {}
    year_pattern = re.compile(r"(20\d{2})")

    for link in soup.find_all("a", href=True):
        link_text = link.get_text(" ", strip=True)
        href = link["href"]
        if not href.lower().endswith((".html", ".htm", ".pdf")):
            continue
        lower_text = link_text.lower()
        if "calendar" not in lower_text and "press release" not in lower_text:
            continue
        for year_match in year_pattern.findall(link_text):
            year_value = int(year_match)
            if year_value < ECB_MP_CALENDAR_FIRST_YEAR:
                continue
            resolved_url = href if href.startswith("http") else (
                "https://www.ecb.europa.eu" + href
            )
            year_to_urls.setdefault(year_value, [])
            if resolved_url not in year_to_urls[year_value]:
                year_to_urls[year_value].append(resolved_url)

    return year_to_urls


# =====================================================================
# Validación estructural obligatoria (Requisito 3)
# =====================================================================
def _validate_year_calendar(calendar_dataframe: pd.DataFrame, year: int) -> Tuple[bool, str]:
    """
    Aplica las invariantes estructurales conocidas del sistema de
    Maintenance Periods del BCE. Un calendario que falla CUALQUIERA de
    estas condiciones se rechaza por completo (nunca parcialmente).

    Returns
    -------
    Tuple[bool, str]
        (es_valido, motivo). Si es_valido es False, motivo explica cuál
        invariante falló.
    """
    if calendar_dataframe is None or calendar_dataframe.empty:
        return False, "Tabla vacía o no encontrada."

    working = calendar_dataframe.sort_values(by="MP").reset_index(drop=True)

    n_periods = len(working)
    if not (ECB_MP_MIN_PERIODS_PER_YEAR <= n_periods <= ECB_MP_MAX_PERIODS_PER_YEAR):
        return False, (
            f"Cantidad de períodos fuera de rango plausible: {n_periods} "
            f"(esperado entre {ECB_MP_MIN_PERIODS_PER_YEAR} y "
            f"{ECB_MP_MAX_PERIODS_PER_YEAR})."
        )

    for _, row in working.iterrows():
        if pd.isna(row["StartDate"]) or pd.isna(row["EndDate"]):
            return False, f"MP {row.get('MP')} tiene fechas faltantes."
        if row["EndDate"] <= row["StartDate"]:
            return False, f"MP {row['MP']}: fecha de fin no es posterior al inicio."
        duration_days = (row["EndDate"] - row["StartDate"]).days
        if not (ECB_MP_MIN_DAYS <= duration_days <= ECB_MP_MAX_DAYS):
            return False, (
                f"MP {row['MP']}: duración {duration_days} días fuera de rango "
                f"plausible ({ECB_MP_MIN_DAYS}-{ECB_MP_MAX_DAYS})."
            )

    for i in range(1, len(working)):
        previous_end = working.loc[i - 1, "EndDate"]
        current_start = working.loc[i, "StartDate"]
        if current_start != previous_end + pd.Timedelta(days=1):
            return False, (
                f"Discontinuidad entre MP {working.loc[i - 1, 'MP']} "
                f"(termina {previous_end}) y MP {working.loc[i, 'MP']} "
                f"(empieza {current_start}) - deben ser días consecutivos."
            )

    return True, "OK"


def _verify_golden_reference(calendar_dataframe: pd.DataFrame) -> Tuple[bool, str]:
    """
    Compara el calendario recién extraído para el año de referencia
    dorada (config.ECB_MP_GOLDEN_REFERENCE_YEAR) contra los valores
    conocidos y verificados manualmente. Si no coincide exactamente,
    asume que el formato del sitio del BCE cambió - nunca que "el
    calendario histórico cambió" (es un hecho inmutable).
    """
    golden_expected = pd.DataFrame(
        [
            {
                "MP": entry["mp"],
                "GCMeetingDate": pd.to_datetime(entry["gc_meeting"]).date(),
                "StartDate": pd.to_datetime(entry["start"]).date(),
                "EndDate": pd.to_datetime(entry["end"]).date(),
            }
            for entry in ECB_MP_GOLDEN_REFERENCE_CALENDAR
        ]
    ).sort_values(by="MP").reset_index(drop=True)

    working = calendar_dataframe.sort_values(by="MP").reset_index(drop=True)
    working_comparable = working.loc[:, ["MP", "GCMeetingDate", "StartDate", "EndDate"]].copy()

    if len(working_comparable) != len(golden_expected):
        return False, (
            f"Cantidad de períodos no coincide con la referencia dorada "
            f"({len(working_comparable)} vs {len(golden_expected)} esperados)."
        )

    for column in ["GCMeetingDate", "StartDate", "EndDate"]:
        working_comparable[column] = pd.to_datetime(working_comparable[column]).dt.date

    mismatches = working_comparable.compare(golden_expected)
    if not mismatches.empty:
        return False, f"Discrepancia contra la referencia dorada de {ECB_MP_GOLDEN_REFERENCE_YEAR}."

    return True, "OK"


# =====================================================================
# Descarga de un año específico (HTML primero, PDF como respaldo)
# =====================================================================
def _fetch_year_calendar(year: int, candidate_urls: List[str]) -> Tuple[Optional[pd.DataFrame], str]:
    """
    Intenta obtener y validar el calendario de un año específico,
    probando cada URL candidata: primero como HTML, luego (si falla)
    como PDF. Devuelve el primer resultado que pase la validación
    estructural obligatoria.
    """
    for url in candidate_urls:
        try:
            response = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
            response.raise_for_status()
        except requests.exceptions.RequestException as error:
            LOGGER.warning(
                "No se pudo descargar %s para el año %s. Detalle: %s", url, year, error
            )
            continue

        content_type = response.headers.get("Content-Type", "")
        extracted_dataframe = None

        if "pdf" in content_type.lower() or url.lower().endswith(".pdf"):
            extracted_dataframe = _extract_year_table_from_pdf(response.content, year)
        else:
            extracted_dataframe = _extract_year_table_from_html(response.text, year)

        if extracted_dataframe is None:
            continue

        is_valid, reason = _validate_year_calendar(extracted_dataframe, year)
        if not is_valid:
            LOGGER.warning(
                "Calendario %s extraído de %s no pasó la validación "
                "estructural: %s. Se descarta.",
                year, url, reason,
            )
            continue

        return extracted_dataframe, "OK"

    return None, "No se encontró una tabla válida en ninguna fuente candidata."


# =====================================================================
# Persistencia (semilla + caché + exportación)
# =====================================================================
def _calendar_dataframe_to_records(calendar_dataframe: pd.DataFrame) -> List[Dict[str, object]]:
    records = calendar_dataframe.copy()
    for column in ["GCMeetingDate", "StartDate", "EndDate"]:
        records[column] = pd.to_datetime(records[column]).dt.strftime("%Y-%m-%d")
    return records.loc[:, CALENDAR_COLUMNS].to_dict(orient="records")


def _records_to_calendar_dataframe(records: List[Dict[str, object]]) -> pd.DataFrame:
    if not records:
        return pd.DataFrame(columns=CALENDAR_COLUMNS)
    dataframe = pd.DataFrame(records)
    for column in ["GCMeetingDate", "StartDate", "EndDate"]:
        dataframe[column] = pd.to_datetime(dataframe[column], errors="coerce").dt.date
    return dataframe.loc[:, CALENDAR_COLUMNS]


def _load_json_calendar_file(file_path: str) -> pd.DataFrame:
    if not os.path.exists(file_path):
        return pd.DataFrame(columns=CALENDAR_COLUMNS)
    try:
        with open(file_path, "r", encoding="utf-8") as file_handle:
            payload = json.load(file_handle)
        return _records_to_calendar_dataframe(payload.get("periods", []))
    except Exception as error:
        LOGGER.exception(
            "Error al leer el archivo de calendario %s. Tipo: %s. Detalle: %s",
            file_path, type(error).__name__, error,
        )
        return pd.DataFrame(columns=CALENDAR_COLUMNS)


def _save_json_calendar_file(file_path: str, calendar_dataframe: pd.DataFrame) -> bool:
    try:
        directory_name = os.path.dirname(file_path) or "."
        os.makedirs(directory_name, exist_ok=True)
        payload = {
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "source": "ECB official press releases / PDFs (2004+), validated structurally",
            "periods": _calendar_dataframe_to_records(calendar_dataframe),
        }
        with open(file_path, "w", encoding="utf-8") as file_handle:
            json.dump(payload, file_handle, indent=2, ensure_ascii=False)
        return True
    except Exception as error:
        LOGGER.exception(
            "Error al guardar el archivo de calendario %s. Tipo: %s. Detalle: %s",
            file_path, type(error).__name__, error,
        )
        return False


# =====================================================================
# Orquestación pública
# =====================================================================
def update_maintenance_period_calendar() -> Tuple[pd.DataFrame, Dict[str, object]]:
    """
    Punto de entrada principal. Combina semilla + caché existentes,
    determina qué años faltan (Requisito 2 - descarga inteligente),
    intenta descargarlos y validarlos, y actualiza la caché y la
    exportación permanente si corresponde.

    Nunca lanza una excepción hacia el llamador: cualquier fallo se
    refleja en el diccionario de estado devuelto, y el calendario
    combinado devuelto es siempre, como mínimo, lo que ya había validado
    (semilla + caché previa) - nunca peor que antes de llamar a esta
    función.

    Returns
    -------
    Tuple[pd.DataFrame, Dict[str, object]]
        (calendario combinado, estado) - ver docstring del módulo para
        el detalle de las claves del diccionario de estado.
    """
    seed_calendar = _load_json_calendar_file(ECB_MP_CALENDAR_SEED_FILE)
    cached_calendar = _load_json_calendar_file(ECB_MP_CALENDAR_CACHE_FILE)

    combined_calendar = pd.concat([seed_calendar, cached_calendar], ignore_index=True)
    combined_calendar = combined_calendar.drop_duplicates(subset=["Year", "MP"], keep="last")

    current_year = datetime.utcnow().year
    validated_years = set(combined_calendar["Year"].unique()) if not combined_calendar.empty else set()

    # Requisito 1/2: los años YA TRANSCURRIDOS y ya validados nunca se
    # vuelven a descargar. El año en curso SÍ se revalida siempre.
    years_needed = [
        year for year in range(ECB_MP_CALENDAR_FIRST_YEAR, current_year + 1)
        if year == current_year or year not in validated_years
    ]

    status: Dict[str, object] = {
        "origen": "semilla+caché" if not years_needed else "semilla+caché+scraping",
        "años_ya_validados_reutilizados": sorted(validated_years - {current_year}),
        "años_intentados_esta_ejecución": years_needed,
        "años_agregados_exitosamente": [],
        "años_fallidos": {},
        "scraping_disponible": True,
        "última_actualización": datetime.utcnow().isoformat() + "Z",
    }

    if not years_needed:
        status["scraping_disponible"] = None
        return combined_calendar, status

    try:
        index_response = requests.get(
            ECB_MP_CALENDAR_INDEX_URL, timeout=30, headers={"User-Agent": "Mozilla/5.0"}
        )
        index_response.raise_for_status()
        year_to_urls = _discover_year_source_urls(index_response.text)
    except Exception as error:
        LOGGER.exception(
            "No se pudo descargar o parsear la página índice del "
            "calendario BCE. Tipo: %s. Detalle: %s",
            type(error).__name__, error,
        )
        status["scraping_disponible"] = False
        status["error_índice"] = str(error)
        return combined_calendar, status

    newly_validated_frames = []
    for year in years_needed:
        candidate_urls = year_to_urls.get(year, [])
        if not candidate_urls:
            status["años_fallidos"][year] = "No se encontró enlace para este año en el índice."
            continue

        year_dataframe, reason = _fetch_year_calendar(year, candidate_urls)
        if year_dataframe is None:
            status["años_fallidos"][year] = reason
            continue

        if year == ECB_MP_GOLDEN_REFERENCE_YEAR:
            golden_ok, golden_reason = _verify_golden_reference(year_dataframe)
            if not golden_ok:
                LOGGER.error(
                    "El scraper no reprodujo correctamente la referencia "
                    "dorada de %s: %s. Se descarta este resultado y se "
                    "detiene la actualización por esta ejecución (posible "
                    "cambio de formato del sitio del BCE).",
                    ECB_MP_GOLDEN_REFERENCE_YEAR, golden_reason,
                )
                status["años_fallidos"][year] = f"Referencia dorada no coincide: {golden_reason}"
                status["alerta_posible_cambio_de_formato"] = True
                break

        newly_validated_frames.append(year_dataframe)
        status["años_agregados_exitosamente"].append(year)

    if newly_validated_frames:
        updated_cache = pd.concat([cached_calendar] + newly_validated_frames, ignore_index=True)
        updated_cache = updated_cache.drop_duplicates(subset=["Year", "MP"], keep="last")
        _save_json_calendar_file(ECB_MP_CALENDAR_CACHE_FILE, updated_cache)

        combined_calendar = pd.concat([seed_calendar, updated_cache], ignore_index=True)
        combined_calendar = combined_calendar.drop_duplicates(subset=["Year", "MP"], keep="last")

        _save_json_calendar_file(ECB_MP_CALENDAR_EXPORT_FILE, combined_calendar)

    combined_calendar = combined_calendar.sort_values(by=["Year", "MP"]).reset_index(drop=True)
    return combined_calendar, status


def find_maintenance_period_for_date(
    calendar_dataframe: pd.DataFrame, target_date: date
) -> Optional[pd.Series]:
    """
    Devuelve la fila del Maintenance Period al que pertenece
    `target_date`, o None si no hay cobertura para esa fecha (nunca
    aproxima ni extrapola).
    """
    if calendar_dataframe is None or calendar_dataframe.empty:
        return None
    matches = calendar_dataframe[
        (calendar_dataframe["StartDate"] <= target_date)
        & (calendar_dataframe["EndDate"] >= target_date)
    ]
    if matches.empty:
        return None
    return matches.iloc[0]
