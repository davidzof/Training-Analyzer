#!/usr/bin/env python3
"""
Scan GPX/TCX/FIT activity files for training analysis.

This version is training-analysis only: --hrmax is required. It writes per-activity
HRmax evidence, sustained HR observations (30m/60m/90m/2h/4h), VAM
(15m/30m/60m), LT2 evidence and HR artefact flags.

When Strava activities.csv is available it also supplies bike metadata and
annual/season volume totals (all matching activities, including activities without HR).

Structured JSON output is available via --json. Activities without usable HR
are still retained for distance, elevation and VAM analysis.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timedelta
from collections import Counter
from pathlib import Path
from statistics import median
import re
import shutil

from activity_file_processor import detect_format, process_training_file


MESSAGES = {
    "en": {
        "description": "Parse GPX, TCX and FIT files and run training analysis. --hrmax is required as the yearly analysis reference.",
        "directory_help": "Directory containing activity files",
        "lang_help": "Language for console/help text (default: English)",
        "min_hr_help": "Minimum accepted HR in bpm (default: 50)",
        "max_hr_help": "Maximum accepted HR in bpm (default: 220)",
        "hrmax_help": "Yearly HRmax reference used by the training analysis, e.g. --hrmax 184",
        "season_summary": "Season summary",
        "training_summary": "Training summary",
        "activities_processed": "Activities processed:             {value}",
        "activities_with_hr": "Activities with usable HR:        {value}",
        "activities_without_hr": "Activities without usable HR:     {value}",
        "errors": "Errors:                           {value}",
        "activities_metadata": "Activities in Strava metadata:    {value}",
        "total_moving": "Total moving time:                {value:.1f} h",
        "total_distance": "Total distance:                   {value:.0f} km",
        "total_elevation": "Total elevation gain:             {value:.0f} m",
        "long_activities": "Long activities >=3h / >=4h / >=6h: {a3} / {a4} / {a6}",
        "activity_types": "Activity types:                    {value}",
        "strong_lt2": "Strong LT2 observations:          {value}",
        "moderate_lt2": "Moderate LT2 observations:        {value}",
        "median_lt2": "Median strong LT2 range:           {value}",
        "insufficient": "insufficient evidence",
        "highest_hrmax": "Highest credible HRmax candidates:",
        "highest_raw_hr": "Highest raw HR observations:        {value}",
        "qualifying_2h": "Qualifying 2h sustained windows:   {value}",
        "qualifying_4h": "Qualifying 4h sustained windows:   {value}",
        "comparable_vam": "Comparable VAM activities:         {value}",
        "vam_by_bike": "VAM by bike (comparable activities)",
        "bike_activities": "{bike} ({count} activities{weight})",
        "detected_intervals": "Detected interval sessions:        {value}",
        "hr_artefacts": "Activities with HR artefact flag:  {value}",
        "metadata_skipped": "Metadata update skipped: no activities.csv found",
        "metadata_appended": "Metadata rows appended: {value}",
        "metadata_update_error": "Error updating activities.csv: {value}",
        "supported_files": "Supported files found: {value}",
        "filtered_out": "Filtered out:          {value}",
        "processed_short": "Activities processed:  {value}",
        "with_hr_short": "With usable HR:        {value}",
        "without_hr_short": "Without usable HR:     {value}",
        "errors_short": "Errors:                {value}",
        "written_to": "{kind} written to:        {value}",
        "err_not_dir": "Error: not a directory: {value}",
        "err_month_year": "Error: --month requires --year.",
        "err_minmax": "Error: --min-hr must be lower than --max-hr.",
        "err_hrmax": "Error: --hrmax must lie between --min-hr and --max-hr.",
        "err_zones": "Error: 3-zone reporting requires both --lt1 and --lt2 (or neither).",
        "err_threshold_order": "Error: require --min-hr < --lt1 < --lt2 < --max-hr.",
        "err_load_metadata": "Error loading Strava activities.csv: {value}",
        "strava_metadata": "Strava metadata:       {value}",
        "metadata_rows": "Metadata rows loaded:  {value}",
        "metadata_missing": "Strava metadata:       not found (bike fields will be blank)",
        "csv_rows_matched": "CSV rows matched:      {value}",
        "matching_files": "Matching files found:  {value}",
        "csv_missing_file": "CSV rows missing file: {value}",
        "error_prefix": "ERROR",
    },
    "fr": {
        "description": "Analyse les fichiers GPX, TCX et FIT pour l'entraînement. --hrmax est requis comme référence annuelle.",
        "directory_help": "Dossier contenant les fichiers d'activité",
        "lang_help": "Langue des messages et de l'aide (par défaut : anglais)",
        "min_hr_help": "FC minimale acceptée en bpm (défaut : 50)",
        "max_hr_help": "FC maximale acceptée en bpm (défaut : 220)",
        "hrmax_help": "Référence annuelle de FC max utilisée pour l'analyse, par ex. --hrmax 184",
        "season_summary": "Résumé de la saison",
        "training_summary": "Résumé d'entraînement",
        "activities_processed": "Activités traitées :              {value}",
        "activities_with_hr": "Activités avec FC exploitable :    {value}",
        "activities_without_hr": "Activités sans FC exploitable :   {value}",
        "errors": "Erreurs :                          {value}",
        "activities_metadata": "Activités dans les métadonnées :   {value}",
        "total_moving": "Temps total en mouvement :          {value:.1f} h",
        "total_distance": "Distance totale :                   {value:.0f} km",
        "total_elevation": "Dénivelé positif total :            {value:.0f} m",
        "long_activities": "Activités longues >=3h / >=4h / >=6h : {a3} / {a4} / {a6}",
        "activity_types": "Types d'activité :                  {value}",
        "strong_lt2": "Observations LT2 fortes :           {value}",
        "moderate_lt2": "Observations LT2 modérées :        {value}",
        "median_lt2": "Plage LT2 médiane (forte) :        {value}",
        "insufficient": "preuves insuffisantes",
        "highest_hrmax": "Meilleurs candidats crédibles de FC max :",
        "highest_raw_hr": "FC brutes les plus élevées :        {value}",
        "qualifying_2h": "Fenêtres soutenues de 2 h valides : {value}",
        "qualifying_4h": "Fenêtres soutenues de 4 h valides : {value}",
        "comparable_vam": "Activités VAM comparables :         {value}",
        "vam_by_bike": "VAM par vélo (activités comparables)",
        "bike_activities": "{bike} ({count} activités{weight})",
        "detected_intervals": "Séances d'intervalles détectées :   {value}",
        "hr_artefacts": "Activités avec artefact FC signalé : {value}",
        "metadata_skipped": "Mise à jour des métadonnées ignorée : activities.csv introuvable",
        "metadata_appended": "Lignes de métadonnées ajoutées : {value}",
        "metadata_update_error": "Erreur lors de la mise à jour de activities.csv : {value}",
        "supported_files": "Fichiers pris en charge trouvés : {value}",
        "filtered_out": "Filtrés :                    {value}",
        "processed_short": "Activités traitées :        {value}",
        "with_hr_short": "Avec FC exploitable :        {value}",
        "without_hr_short": "Sans FC exploitable :       {value}",
        "errors_short": "Erreurs :                    {value}",
        "written_to": "{kind} écrit dans :           {value}",
        "err_not_dir": "Erreur : ce n'est pas un dossier : {value}",
        "err_month_year": "Erreur : --month nécessite --year.",
        "err_minmax": "Erreur : --min-hr doit être inférieur à --max-hr.",
        "err_hrmax": "Erreur : --hrmax doit être compris entre --min-hr et --max-hr.",
        "err_zones": "Erreur : le rapport en 3 zones nécessite --lt1 et --lt2 ensemble (ou aucun).",
        "err_threshold_order": "Erreur : il faut --min-hr < --lt1 < --lt2 < --max-hr.",
        "err_load_metadata": "Erreur lors du chargement de Strava activities.csv : {value}",
        "strava_metadata": "Métadonnées Strava :      {value}",
        "metadata_rows": "Lignes de métadonnées :   {value}",
        "metadata_missing": "Métadonnées Strava :      introuvables (champs vélo laissés vides)",
        "csv_rows_matched": "Lignes CSV correspondantes : {value}",
        "matching_files": "Fichiers correspondants :    {value}",
        "csv_missing_file": "Lignes CSV sans fichier :    {value}",
        "error_prefix": "ERREUR",
    },
}


def detect_language(argv: list[str] | None = None) -> str:
    """Return the explicitly requested language, defaulting to English."""
    argv = sys.argv[1:] if argv is None else argv
    for i, arg in enumerate(argv):
        if arg == "--lang" and i + 1 < len(argv):
            return argv[i + 1] if argv[i + 1] in MESSAGES else "en"
        if arg.startswith("--lang="):
            value = arg.split("=", 1)[1]
            return value if value in MESSAGES else "en"
    return "en"


def t(key: str, lang: str, **kwargs) -> str:
    template = MESSAGES.get(lang, MESSAGES["en"]).get(key, MESSAGES["en"].get(key, key))
    return template.format(**kwargs)


TRAINING_CSV_FIELDS = [
    "filename",
    "activity_date",
    "activity_type",
    "strava_activity_id",
    "activity_name",
    "activity_gear",
    "bike_weight",
    "bike_id",
    "athlete_weight",
    "duration",
    "average_hr",
    "raw_max_hr",
    "analysed_max_hr",
    "hrmax_10s",
    "hrmax_30s",
    "hrmax_60s",
    "hrmax_candidate",
    "hrmax_confidence",
    "hrmax_reason",
    "best_30m_hr",
    "best_60m_hr",
    "best_90m_hr",
    "best_2h_hr",
    "best_2h_moving_fraction",
    "best_2h_hr_p10",
    "best_2h_hr_p90",
    "best_4h_hr",
    "best_4h_moving_fraction",
    "best_4h_hr_p10",
    "best_4h_hr_p90",
    "vam_15",
    "vam_30",
    "vam_60",
    "vam_retention_pct",
    "vam_comparison",
    "time_85pct_seconds",
    "time_90pct_seconds",
    "zone1_seconds",
    "zone2_seconds",
    "zone3_seconds",
    "zone_total_seconds",
    "active_zone1_seconds",
    "active_zone2_seconds",
    "active_zone3_seconds",
    "active_zone_total_seconds",
    "active_zone1_pct",
    "active_zone2_pct",
    "active_zone3_pct",
    "zone1_pct",
    "zone2_pct",
    "zone3_pct",
    "hard_block_threshold_bpm",
    "hard_block_count",
    "hard_blocks",
    "hard_block_gaps",
    "interval_count",
    "interval_work_total",
    "interval_work_median",
    "interval_work_avg_hr",
    "interval_work_max_hr",
    "interval_recovery_median",
    "interval_recovery_avg_hr",
    "interval_work_durations",
    "interval_work_avg_hrs",
    "interval_work_max_hrs",
    "interval_recovery_durations",
    "interval_recovery_avg_hrs",
    "interval_summary",
    "overall_ride",
    "key_effort",
    "classification",
    "confidence",
    "lt2_low",
    "lt2_high",
    "lt2_evidence",
    "lt2_reason",
    "lt2_clue",
    "hr_artefact",
    "excluded_hr_samples",
    "distance_km",
    "elevation_gain_m",
    "has_hr",
    "has_elevation",
    "has_gps",
    "has_power",
    "status",
    "error",
]


def build_parser(lang: str = "en") -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=t("description", lang))
    parser.add_argument(
        "directory",
        type=Path,
        help=t("directory_help", lang),
    )
    parser.add_argument(
        "--lang",
        choices=("en", "fr"),
        default=lang,
        help=t("lang_help", lang),
    )
    parser.add_argument(
        "--min-hr",
        type=int,
        default=50,
        help=t("min_hr_help", lang),
    )
    parser.add_argument(
        "--max-hr",
        type=int,
        default=220,
        help=t("max_hr_help", lang),
    )
    parser.add_argument(
        "--hrmax",
        type=int,
        required=True,
        help=t("hrmax_help", lang),
    )
    parser.add_argument(
        "--lt1",
        type=float,
        default=None,
        help=(
            "Optional known LT1 HR for per-activity and weekly 3-zone time-in-zone "
            "reporting. Zone reporting requires both --lt1 and --lt2."
        ),
    )
    parser.add_argument(
        "--lt2",
        type=float,
        default=None,
        help=(
            "Optional known LT2 HR supplied to the analysis. Usually omit this when "
            "historically estimating LT2."
        ),
    )
    parser.add_argument(
        "--year",
        type=int,
        default=None,
        help=(
            "Calendar year to analyse, or season start year when --month is supplied. "
            "When activities.csv is available, the date window is normally applied "
            "before opening activity files."
        ),
    )
    parser.add_argument(
        "--month",
        type=int,
        choices=range(1, 13),
        metavar="1-12",
        default=None,
        help=(
            "Optional season start month. Requires --year. For example "
            "--year 2025 --month 5 scans 1 May 2025 through 30 Apr 2026. "
            "Without --month, --year means the normal calendar year."
        ),
    )
    parser.add_argument(
        "--sport",
        type=str,
        default=None,
        help=(
            "Optional comma-separated normalized activity type filter, e.g. "
            "cycling,skiing,walking. The skiing alias includes Nordic and "
            "backcountry skiing, but not alpine skiing."
        ),
    )
    parser.add_argument(
        "--activities-csv",
        type=Path,
        default=None,
        help=(
            "Path to Strava activities.csv. If omitted, training mode looks "
            "for activities.csv in the parent directory of the activities "
            "folder. Used to attach bike/gear metadata."
        ),
    )
    parser.add_argument(
        "--add-missing-metadata",
        action="store_true",
        help=(
            "Append successfully parsed activity files that are missing from "
            "activities.csv. Useful when adding new GPX/TCX/FIT files during a season. "
            "When enabled, the scanner does not rely solely on metadata preselection."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help=(
            "Write structured JSON instead of CSV. The JSON contains the period, "
            "analysis parameters, season summary and the same per-activity fields "
            "normally written to CSV."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help=(
            "Optional output path. If omitted, a descriptive filename is generated "
            "from the year/season and sport."
        ),
    )
    return parser


def supported_files(directory: Path) -> list[Path]:
    files: list[Path] = []
    for path in directory.iterdir():
        if not path.is_file():
            continue
        try:
            detect_format(path)
            files.append(path)
        except ValueError:
            pass

    files.sort(key=lambda p: p.name.lower())
    return files


def _english_month_number(name: str) -> int | None:
    months = {
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
        "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    }
    return months.get(name.strip().lower()[:3]) if name else None


def parse_activity_datetime(value: str | None) -> datetime | None:
    """Parse scanner or Strava activity dates without depending on OS locale."""
    if not value:
        return None
    text = value.strip()

    # Scanner output: 17 Jul 2015 14:32
    m = re.match(r"^(\d{1,2})\s+([A-Za-z]{3,9})\s+((?:19|20)\d{2})\s+(\d{1,2}):(\d{2})(?::(\d{2}))?$", text)
    if m:
        day, mon, year, hour, minute, second = m.groups()
        month = _english_month_number(mon)
        if month:
            return datetime(int(year), month, int(day), int(hour), int(minute), int(second or 0))

    # Strava export: Dec 28, 2025, 2:34:18 PM
    m = re.match(
        r"^([A-Za-z]{3,9})\s+(\d{1,2}),\s*((?:19|20)\d{2}),\s*"
        r"(\d{1,2}):(\d{2})(?::(\d{2}))?\s*([APap][Mm])?$",
        text,
    )
    if m:
        mon, day, year, hour, minute, second, ampm = m.groups()
        month = _english_month_number(mon)
        if month:
            h = int(hour)
            if ampm:
                ap = ampm.lower()
                if ap == "pm" and h != 12:
                    h += 12
                elif ap == "am" and h == 12:
                    h = 0
            return datetime(int(year), month, int(day), h, int(minute), int(second or 0))

    # ISO-style fallback.
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def season_bounds(year: int | None, month: int | None) -> tuple[datetime | None, datetime | None]:
    if year is None:
        return None, None
    start_month = month or 1
    start = datetime(year, start_month, 1)
    end_year = year + 1
    end = datetime(end_year, start_month, 1)
    return start, end


def date_in_window(value: str | None, year: int | None, month: int | None) -> bool:
    if year is None:
        return True
    dt = parse_activity_datetime(value)
    if dt is None:
        return False
    start, end = season_bounds(year, month)
    assert start is not None and end is not None
    return start <= dt < end


def passes_filters(summary, year: int | None, month: int | None, sport: str | None) -> bool:
    if not date_in_window(summary.activity_date, year, month):
        return False

    if not sport_matches(summary.activity_type, sport):
        return False

    return True


def normalize_export_filename(value: str | None) -> str | None:
    """Return the basename used to join Strava activities.csv to export files."""
    if not value:
        return None
    value = value.strip().replace("\\", "/")
    if not value:
        return None
    return value.rsplit("/", 1)[-1]


def resolve_activities_csv(args, directory: Path) -> Path | None:
    """Resolve an explicit or conventional Strava activities.csv path."""
    if args.activities_csv is not None:
        candidate = args.activities_csv.expanduser()
        return candidate

    candidate = directory.parent / "activities.csv"
    if candidate.is_file():
        return candidate

    return None


def load_strava_metadata(path: Path | None) -> dict[str, dict]:
    """Load selected Strava metadata keyed by exported activity filename."""
    if path is None:
        return {}

    if not path.is_file():
        raise FileNotFoundError(f"activities.csv not found: {path}")

    result: dict[str, dict] = {}
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        required = {"Filename", "Activity ID", "Activity Gear", "Bike Weight"}
        missing = sorted(required - set(reader.fieldnames or []))
        if missing:
            raise ValueError(
                "activities.csv is missing expected columns: " + ", ".join(missing)
            )

        for row in reader:
            key = normalize_export_filename(row.get("Filename"))
            if not key:
                continue

            def clean(name: str):
                value = row.get(name)
                if value is None:
                    return None
                value = value.strip()
                return value if value else None

            def as_float(name: str):
                value = clean(name)
                if value is None:
                    return None
                try:
                    return float(value)
                except ValueError:
                    return None

            result[key] = {
                "strava_activity_id": clean("Activity ID"),
                "activity_name": clean("Activity Name"),
                "activity_gear": clean("Activity Gear"),
                "bike_weight": as_float("Bike Weight"),
                "bike_id": clean("Bike"),
                "athlete_weight": as_float("Athlete Weight"),
                "strava_activity_date": clean("Activity Date"),
                "strava_activity_type": clean("Activity Type"),
                "elapsed_time_s": as_float("Elapsed Time"),
                "moving_time_s": as_float("Moving Time"),
                "distance_m_meta": as_float("Distance"),
                "elevation_gain_m_meta": as_float("Elevation Gain"),
            }

    return result



def parse_strava_year(value: str | None) -> int | None:
    dt = parse_activity_datetime(value)
    return dt.year if dt is not None else None


def normalize_strava_sport(value: str | None) -> str | None:
    if not value:
        return None
    key = value.strip().lower().replace("_", "").replace(" ", "")
    mapping = {
        "ride": "cycling",
        "virtualride": "cycling",
        "ebikeride": "cycling",
        "mountainbikeride": "cycling",
        "gravelride": "cycling",
        "run": "running",
        "virtualrun": "running",
        "trailrun": "running",
        "walk": "walking",
        "hike": "walking",
        "nordicski": "skiing",
        "nordicskiing": "skiing",
        "crosscountryski": "skiing",
        "crosscountryskiing": "skiing",
        "backcountryski": "skiing",
        "rollerski": "roller skiing",
        "rollerskiing": "roller skiing",
    }
    return mapping.get(key, value.strip().lower())


def parse_sport_filter(value: str | None) -> set[str] | None:
    """Return normalized sports requested by a comma-separated --sport value."""
    if not value:
        return None
    sports = {
        normalized
        for part in value.split(",")
        if part.strip()
        for normalized in [normalize_strava_sport(part)]
        if normalized is not None
    }
    return sports or None


def sport_matches(actual_value: str | None, requested_value: str | None) -> bool:
    requested = parse_sport_filter(requested_value)
    if requested is None:
        return True
    return normalize_strava_sport(actual_value) in requested


def preselect_files_from_metadata(
    directory: Path,
    metadata: dict[str, dict],
    year: int | None,
    month: int | None,
    sport: str | None,
) -> tuple[list[Path], int, int]:
    """Select candidate files from activities.csv before opening activity files.

    Returns (files, metadata_rows_selected, missing_files).
    """
    selected: list[Path] = []
    missing = 0
    matched_rows = 0
    requested_sports = parse_sport_filter(sport)

    for filename, info in metadata.items():
        if not date_in_window(info.get("strava_activity_date"), year, month):
            continue

        if requested_sports is not None:
            actual = normalize_strava_sport(info.get("strava_activity_type"))
            if actual not in requested_sports:
                continue

        matched_rows += 1
        path = directory / filename
        if not path.is_file():
            missing += 1
            continue
        try:
            detect_format(path)
        except ValueError:
            continue
        selected.append(path)

    selected.sort(key=lambda p: p.name.lower())
    return selected, matched_rows, missing

def enrich_training_row(row: dict, metadata: dict[str, dict]) -> dict:
    """Add Strava gear metadata to one training-analysis row."""
    enriched = dict(row)
    info = metadata.get(normalize_export_filename(row.get("filename")) or "", {})
    for field in (
        "strava_activity_id",
        "activity_name",
        "activity_gear",
        "bike_weight",
        "bike_id",
        "athlete_weight",
    ):
        enriched[field] = info.get(field)

    # Strava's Activity Gear field is generic: it can be a bicycle, running
    # shoe, ski equipment, etc. Keep activity_gear for every sport, but only
    # expose bike-specific metadata for cycling activities.
    if normalize_strava_sport(enriched.get("activity_type")) != "cycling":
        enriched["bike_weight"] = None
        enriched["bike_id"] = None

    return enriched


def _strava_activity_type_from_normalized(value: str | None) -> str | None:
    mapping = {
        "cycling": "Ride",
        "running": "Run",
        "walking": "Walk",
        "hiking": "Hike",
        "skiing": "NordicSki",
        "roller skiing": "RollerSki",
    }
    if not value:
        return None
    return mapping.get(value.strip().lower(), value)


def _strava_date_string(value: str | None) -> str | None:
    dt = parse_activity_datetime(value)
    if dt is None:
        return None
    hour = dt.hour % 12 or 12
    ampm = "AM" if dt.hour < 12 else "PM"
    return f"{dt.strftime('%b')} {dt.day}, {dt.year}, {hour}:{dt.minute:02d}:{dt.second:02d} {ampm}"


def append_missing_metadata_rows(path: Path, rows: list[dict], existing: dict[str, dict]) -> int:
    """Append minimal Strava-compatible metadata rows for newly analysed files.

    Existing rows and the original column order are preserved. Fields that
    cannot be reconstructed locally (Activity ID, gear, calories, etc.) stay blank.
    """
    if not rows:
        return 0
    if not path.is_file():
        raise FileNotFoundError(f"activities.csv not found: {path}")

    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
    required = {"Filename", "Activity Date", "Activity Type", "Elapsed Time", "Moving Time", "Distance", "Elevation Gain"}
    missing = sorted(required - set(fieldnames))
    if missing:
        raise ValueError("activities.csv cannot be updated; missing columns: " + ", ".join(missing))

    additions = []
    seen = set(existing.keys())
    for row in rows:
        filename = normalize_export_filename(row.get("filename"))
        if not filename or filename in seen or row.get("status") != "ok":
            continue
        record = {name: "" for name in fieldnames}
        record["Filename"] = f"activities/{filename}"
        record["Activity Date"] = _strava_date_string(row.get("activity_date")) or ""
        record["Activity Type"] = _strava_activity_type_from_normalized(row.get("activity_type")) or ""
        duration_s = _duration_seconds_hms(row.get("duration"))
        if duration_s is not None:
            record["Elapsed Time"] = str(int(round(duration_s)))
            record["Moving Time"] = str(int(round(duration_s)))
        if row.get("distance_km") is not None:
            record["Distance"] = f"{float(row['distance_km']) * 1000.0:.1f}"
        if row.get("elevation_gain_m") is not None:
            record["Elevation Gain"] = f"{float(row['elevation_gain_m']):.1f}"
        if "Activity Name" in record:
            record["Activity Name"] = Path(filename).stem
        additions.append(record)
        seen.add(filename)

    if not additions:
        return 0

    backup = path.with_suffix(path.suffix + ".bak")
    if not backup.exists():
        shutil.copy2(path, backup)

    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writerows(additions)
    return len(additions)


def _filename_slug(value: str | None) -> str:
    if not value:
        return "training"
    key = value.strip().lower()
    aliases = {
        "skiing": "cross-country-skiing",
        "nordic skiing": "cross-country-skiing",
        "roller skiing": "roller-skiing",
    }
    if key in aliases:
        return aliases[key]
    slug = re.sub(r"[^a-z0-9]+", "-", key).strip("-")
    return slug or "training"


def default_output(args) -> Path:
    if args.output is not None:
        return args.output.expanduser()

    ext = "json" if args.json else "csv"
    sport = _filename_slug(args.sport)

    if args.year is not None and args.month is not None:
        month_name = datetime(args.year, args.month, 1).strftime("%B").lower()
        return Path(f"{month_name}-{args.year}-{sport}.{ext}")

    if args.year is not None:
        return Path(f"{args.year}-{sport}.{ext}")

    return Path(f"{sport}.{ext}")


def top_values(values, n=3):
    vals = sorted(
        [float(v) for v in values if v is not None],
        reverse=True,
    )
    return vals[:n]


def fmt_number(value, digits=1):
    if value is None:
        return "-"
    return f"{value:.{digits}f}"


def _metadata_matches(info: dict, year: int | None, month: int | None, sport: str | None) -> bool:
    if not date_in_window(info.get("strava_activity_date"), year, month):
        return False
    if not sport_matches(info.get("strava_activity_type"), sport):
        return False
    return True


def metadata_volume_summary(metadata: dict[str, dict], year: int | None, month: int | None, sport: str | None) -> dict | None:
    if not metadata:
        return None
    rows = [info for info in metadata.values() if _metadata_matches(info, year, month, sport)]
    if not rows:
        return None
    elapsed = [float(r["elapsed_time_s"]) for r in rows if r.get("elapsed_time_s") is not None]
    moving = [float(r["moving_time_s"]) for r in rows if r.get("moving_time_s") is not None]
    distance = [float(r["distance_m_meta"]) for r in rows if r.get("distance_m_meta") is not None]
    elev = [float(r["elevation_gain_m_meta"]) for r in rows if r.get("elevation_gain_m_meta") is not None]
    durations = [float(r.get("moving_time_s") or r.get("elapsed_time_s")) for r in rows if (r.get("moving_time_s") is not None or r.get("elapsed_time_s") is not None)]
    moving_by_sport = Counter()
    for r in rows:
        if r.get("moving_time_s") is None:
            continue
        sport_name = normalize_strava_sport(r.get("strava_activity_type")) or "unknown"
        moving_by_sport[sport_name] += float(r["moving_time_s"])
    return {
        "activities": len(rows),
        "elapsed_hours": sum(elapsed)/3600 if elapsed else None,
        "moving_hours": sum(moving)/3600 if moving else None,
        "hours_by_sport": {
            name: round(seconds/3600.0, 2)
            for name, seconds in sorted(moving_by_sport.items())
        },
        "distance_km": sum(distance)/1000 if distance else None,
        "elevation_gain_m": sum(elev) if elev else None,
        "rides_3h": sum(v >= 3*3600 for v in durations),
        "rides_4h": sum(v >= 4*3600 for v in durations),
        "rides_6h": sum(v >= 6*3600 for v in durations),
    }


def _duration_seconds_hms(value: str | None) -> float | None:
    if not value:
        return None
    try:
        h, m, sec = value.split(":")
        return int(h)*3600 + int(m)*60 + int(sec)
    except Exception:
        return None


def build_weekly_summary(
    rows: list[dict],
    metadata: dict[str, dict],
    year: int | None,
    month: int | None,
    sport: str | None,
) -> list[dict]:
    """Aggregate transparent weekly training volume and 3-zone HR time.

    Volume comes from Strava metadata where available, so activities without HR
    still count. Zone and hard-effort data are joined from analysed activities.
    Empty weeks between the first and last activity are retained so training
    gaps are visible. The 4-week figure is the sum of the current and previous
    three calendar weeks.
    """
    row_by_file = {
        normalize_export_filename(r.get("filename")): r
        for r in rows
        if r.get("status") == "ok" and normalize_export_filename(r.get("filename"))
    }
    entries = []
    seen = set()
    if metadata:
        for filename, info in metadata.items():
            if not _metadata_matches(info, year, month, sport):
                continue
            dt = parse_activity_datetime(info.get("strava_activity_date"))
            if dt is None:
                continue
            key = normalize_export_filename(filename) or filename
            seen.add(key)
            entries.append((key, dt, info, row_by_file.get(key)))

    # Fall back to analysed rows for activities absent from activities.csv.
    for key, row in row_by_file.items():
        if key in seen:
            continue
        if not date_in_window(row.get("activity_date"), year, month):
            continue
        if not sport_matches(row.get("activity_type"), sport):
            continue
        dt = parse_activity_datetime(row.get("activity_date"))
        if dt is None:
            continue
        entries.append((key, dt, {}, row))

    if not entries:
        return []

    buckets: dict[datetime, dict] = {}
    for key, dt, info, row in entries:
        week = (dt - timedelta(days=dt.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        b = buckets.setdefault(week, {
            "activities": 0,
            "moving_seconds": 0.0,
            "distance_m": 0.0,
            "elevation_gain_m": 0.0,
            "rides_3h": 0,
            "zone1_seconds": 0.0,
            "zone2_seconds": 0.0,
            "zone3_seconds": 0.0,
            "zone_total_seconds": 0.0,
            "active_zone1_seconds": 0.0,
            "active_zone2_seconds": 0.0,
            "active_zone3_seconds": 0.0,
            "active_zone_total_seconds": 0.0,
            "activities_with_zone_data": 0,
            "activities_with_active_zone_data": 0,
            "hard_blocks": 0,
            "activities_with_hard_blocks": 0,
            "moving_seconds_by_sport": Counter(),
        })
        b["activities"] += 1
        moving = info.get("moving_time_s")
        elapsed = info.get("elapsed_time_s")
        if moving is None and row is not None:
            moving = _duration_seconds_hms(row.get("duration"))
        duration_s = float(moving if moving is not None else (elapsed or 0.0))
        duration_s = max(0.0, duration_s)
        b["moving_seconds"] += duration_s
        actual_sport = normalize_strava_sport(
            info.get("strava_activity_type") or (row.get("activity_type") if row is not None else None)
        ) or "unknown"
        b["moving_seconds_by_sport"][actual_sport] += duration_s
        if duration_s >= 3*3600:
            b["rides_3h"] += 1
        if info.get("distance_m_meta") is not None:
            b["distance_m"] += float(info["distance_m_meta"])
        elif row is not None and row.get("distance_km") is not None:
            b["distance_m"] += float(row["distance_km"])*1000.0
        if info.get("elevation_gain_m_meta") is not None:
            b["elevation_gain_m"] += float(info["elevation_gain_m_meta"])
        elif row is not None and row.get("elevation_gain_m") is not None:
            b["elevation_gain_m"] += float(row["elevation_gain_m"])

        if row is not None and row.get("zone_total_seconds") is not None:
            b["activities_with_zone_data"] += 1
            for field in ("zone1_seconds", "zone2_seconds", "zone3_seconds", "zone_total_seconds"):
                b[field] += float(row.get(field) or 0.0)
        if row is not None and row.get("active_zone_total_seconds") is not None:
            b["activities_with_active_zone_data"] += 1
            for field in ("active_zone1_seconds", "active_zone2_seconds", "active_zone3_seconds", "active_zone_total_seconds"):
                b[field] += float(row.get(field) or 0.0)
        if row is not None:
            blocks = int(row.get("hard_block_count") or 0)
            b["hard_blocks"] += blocks
            if blocks:
                b["activities_with_hard_blocks"] += 1

    first_week = min(buckets)
    last_week = max(buckets)
    weeks = []
    cursor = first_week
    while cursor <= last_week:
        b = buckets.get(cursor, {
            "activities": 0, "moving_seconds": 0.0, "distance_m": 0.0,
            "elevation_gain_m": 0.0, "rides_3h": 0, "zone1_seconds": 0.0,
            "zone2_seconds": 0.0, "zone3_seconds": 0.0, "zone_total_seconds": 0.0,
            "active_zone1_seconds": 0.0, "active_zone2_seconds": 0.0,
            "active_zone3_seconds": 0.0, "active_zone_total_seconds": 0.0,
            "activities_with_zone_data": 0, "activities_with_active_zone_data": 0, "hard_blocks": 0,
            "activities_with_hard_blocks": 0, "moving_seconds_by_sport": Counter(),
        })
        recorded_ztotal = b["zone_total_seconds"]
        active_ztotal = b["active_zone_total_seconds"]
        iso = cursor.isocalendar()
        weeks.append({
            "week_start": cursor.date().isoformat(),
            "iso_year": iso.year,
            "iso_week": iso.week,
            "activities": b["activities"],
            "moving_hours": round(b["moving_seconds"]/3600.0, 2),
            "hours_by_sport": {
                name: round(seconds/3600.0, 2)
                for name, seconds in sorted(b["moving_seconds_by_sport"].items())
            },
            "distance_km": round(b["distance_m"]/1000.0, 1),
            "elevation_gain_m": round(b["elevation_gain_m"], 0),
            "rides_3h": b["rides_3h"],
            "activities_with_zone_data": b["activities_with_zone_data"],
            "activities_with_active_zone_data": b["activities_with_active_zone_data"],
            "zone1_hours": round(b["active_zone1_seconds"]/3600.0, 2) if active_ztotal else None,
            "zone2_hours": round(b["active_zone2_seconds"]/3600.0, 2) if active_ztotal else None,
            "zone3_hours": round(b["active_zone3_seconds"]/3600.0, 2) if active_ztotal else None,
            "hr_zone_hours": round(active_ztotal/3600.0, 2) if active_ztotal else None,
            "zone1_pct": round(100*b["active_zone1_seconds"]/active_ztotal, 1) if active_ztotal else None,
            "zone2_pct": round(100*b["active_zone2_seconds"]/active_ztotal, 1) if active_ztotal else None,
            "zone3_pct": round(100*b["active_zone3_seconds"]/active_ztotal, 1) if active_ztotal else None,
            "recorded_zone1_hours": round(b["zone1_seconds"]/3600.0, 2) if recorded_ztotal else None,
            "recorded_zone2_hours": round(b["zone2_seconds"]/3600.0, 2) if recorded_ztotal else None,
            "recorded_zone3_hours": round(b["zone3_seconds"]/3600.0, 2) if recorded_ztotal else None,
            "recorded_hr_zone_hours": round(recorded_ztotal/3600.0, 2) if recorded_ztotal else None,
            "hard_blocks": b["hard_blocks"],
            "activities_with_hard_blocks": b["activities_with_hard_blocks"],
        })
        cursor += timedelta(days=7)

    for i, week in enumerate(weeks):
        week["moving_hours_4wk"] = round(sum(w["moving_hours"] for w in weeks[max(0, i-3):i+1]), 2)
    return weeks


def build_training_summary(rows: list[dict], year: int | None, month: int | None, sport: str | None, volume: dict | None = None, weekly: list[dict] | None = None) -> dict:
    """Return the season summary as structured, JSON-friendly data."""
    ok = [r for r in rows if r["status"] == "ok"]
    errors = [r for r in rows if r["status"] == "error"]
    with_hr = [r for r in ok if bool(r.get("has_hr"))]
    without_hr = [r for r in ok if not bool(r.get("has_hr"))]

    if year is not None:
        start, end = season_bounds(year, month)
        period = {
            "start": start.date().isoformat() if start else None,
            "end_exclusive": end.date().isoformat() if end else None,
            "calendar_year": year if month is None else None,
            "season_start_year": year if month is not None else None,
            "season_start_month": month,
        }
    else:
        period = {
            "start": None,
            "end_exclusive": None,
            "calendar_year": None,
            "season_start_year": None,
            "season_start_month": None,
        }

    strong = [r for r in ok if r.get("lt2_evidence") == "strong"]
    moderate = [r for r in ok if r.get("lt2_evidence") == "moderate"]
    strong_lows = [float(r["lt2_low"]) for r in strong if r.get("lt2_low") is not None]
    strong_highs = [float(r["lt2_high"]) for r in strong if r.get("lt2_high") is not None]

    credible = [
        r for r in with_hr
        if r.get("hrmax_candidate") is not None
        and r.get("hrmax_confidence") in {"high", "medium"}
    ]
    credible_sorted = sorted(
        credible, key=lambda r: float(r["hrmax_candidate"]), reverse=True
    )[:5]

    comparable = [
        r for r in ok
        if r.get("vam_15") is not None
        and r.get("vam_30") is not None
        and r.get("vam_comparison")
        and str(r["vam_comparison"]).startswith("comparable:")
    ]

    cycling_rows = [r for r in ok if normalize_strava_sport(r.get("activity_type")) == "cycling"]
    comparable_cycling = [r for r in comparable if normalize_strava_sport(r.get("activity_type")) == "cycling"]
    bike_names = []
    for r in cycling_rows:
        name = r.get("activity_gear") or "unknown"
        if name not in bike_names:
            bike_names.append(name)
    bikes = []
    for bike in bike_names:
        all_bike_rows = [r for r in cycling_rows if (r.get("activity_gear") or "unknown") == bike]
        bike_rows = [r for r in comparable_cycling if (r.get("activity_gear") or "unknown") == bike]
        if not bike_rows:
            continue
        weights = [float(r["bike_weight"]) for r in bike_rows if r.get("bike_weight") is not None]
        vam15 = [float(r["vam_15"]) for r in bike_rows if r.get("vam_15") is not None]
        vam30 = [float(r["vam_30"]) for r in bike_rows if r.get("vam_30") is not None]
        vam60 = [float(r["vam_60"]) for r in bike_rows if r.get("vam_60") is not None]
        retention = [float(r["vam_retention_pct"]) for r in bike_rows if r.get("vam_retention_pct") is not None]
        bikes.append({
            "bike": bike,
            "activities": len(all_bike_rows),
            "median_bike_weight_kg": median(weights) if weights else None,
            "comparable_vam_activities": len(bike_rows),
            "vam_15_median": median(vam15) if vam15 else None,
            "vam_15_best": max(vam15) if vam15 else None,
            "vam_30_median": median(vam30) if vam30 else None,
            "vam_30_best": max(vam30) if vam30 else None,
            "vam_60_median": median(vam60) if vam60 else None,
            "vam_60_best": max(vam60) if vam60 else None,
            "median_retention_pct": median(retention) if retention else None,
        })

    interval_rows = [r for r in ok if r.get("interval_count")]
    interval_sessions = [
        {
            "activity_date": r.get("activity_date"),
            "activity_name": r.get("activity_name") or r.get("filename"),
            "filename": r.get("filename"),
            "interval_count": r.get("interval_count"),
            "summary": r.get("interval_summary"),
        }
        for r in interval_rows
    ]

    retention = [
        float(r["vam_retention_pct"])
        for r in comparable if r.get("vam_retention_pct") is not None
    ]

    return {
        "period": period,
        "sport": sport,
        "activities_processed": len(ok),
        "activities_with_usable_hr": len(with_hr),
        "activities_without_usable_hr": len(without_hr),
        "activities_analysed": len(ok),
        "errors": len(errors),
        "activity_types": dict(Counter((r.get("activity_type") or "unknown") for r in ok)),
        "volume": volume,
        "weekly_training": weekly or [],
        "lt2": {
            "strong_observations": len(strong),
            "moderate_observations": len(moderate),
            "median_strong_low_bpm": median(strong_lows) if strong_lows else None,
            "median_strong_high_bpm": median(strong_highs) if strong_highs else None,
        },
        "heart_rate": {
            "top_30m_bpm": top_values(r.get("best_30m_hr") for r in with_hr),
            "top_60m_bpm": top_values(r.get("best_60m_hr") for r in with_hr),
            "top_90m_bpm": top_values(r.get("best_90m_hr") for r in with_hr),
            "qualifying_2h_windows": sum(r.get("best_2h_hr") is not None for r in with_hr),
            "top_2h_bpm": top_values(r.get("best_2h_hr") for r in with_hr),
            "qualifying_4h_windows": sum(r.get("best_4h_hr") is not None for r in with_hr),
            "top_4h_bpm": top_values(r.get("best_4h_hr") for r in with_hr),
            "highest_raw_hr_bpm": top_values((r.get("raw_max_hr") for r in with_hr), n=5),
            "credible_hrmax_candidates": [
                {
                    "bpm": float(r["hrmax_candidate"]),
                    "confidence": r.get("hrmax_confidence"),
                    "activity_date": r.get("activity_date"),
                    "activity_name": r.get("activity_name") or r.get("filename"),
                    "filename": r.get("filename"),
                }
                for r in credible_sorted
            ],
            "artefact_flagged_activities": sum(bool(r.get("hr_artefact")) for r in with_hr),
        },
        "vam": {
            "comparable_activities": len(comparable),
            "top_15m_m_per_h": top_values(r.get("vam_15") for r in comparable),
            "top_30m_m_per_h": top_values(r.get("vam_30") for r in comparable),
            "top_60m_m_per_h": top_values(r.get("vam_60") for r in comparable),
            "median_retention_pct": median(retention) if retention else None,
            "by_bike": bikes,
        },
        "hard_efforts": {
            "activities_with_hard_blocks": sum((r.get("hard_block_count") or 0) > 0 for r in with_hr),
            "total_hard_blocks": sum(int(r.get("hard_block_count") or 0) for r in with_hr),
        },
        "intervals": {
            "detected_sessions": len(interval_rows),
            "sessions": interval_sessions,
        },
    }


def write_json_output(
    output: Path,
    rows: list[dict],
    summary: dict,
    args,
) -> None:
    payload = {
        "schema_version": 1,
        "generated_by": "training-analyser",
        "analysis_parameters": {
            "hrmax_bpm": args.hrmax,
            "lt1_bpm": args.lt1,
            "lt2_bpm": args.lt2,
            "min_hr_bpm": args.min_hr,
            "max_hr_bpm": args.max_hr,
        },
        "summary": summary,
        "activities": rows,
    }
    with output.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def print_training_summary(rows: list[dict], year: int | None, month: int | None, sport: str | None, volume: dict | None = None, lang: str = "en"):
    ok = [r for r in rows if r["status"] == "ok"]
    with_hr = [r for r in ok if bool(r.get("has_hr"))]
    without_hr = [r for r in ok if not bool(r.get("has_hr"))]

    print()
    if year is not None and month is not None:
        start, end = season_bounds(year, month)
        label = f"{start.strftime('%b %Y')} to {(end.replace(day=1) if end else end).strftime('%b %Y')}" if start and end else str(year)
        # End is exclusive, so display the final included month.
        final_month = 12 if month == 1 else month - 1
        final_year = year if month == 1 else year + 1
        label = f"{start.strftime('%b %Y')} to {datetime(final_year, final_month, 1).strftime('%b %Y')}"
        print(f"{t("season_summary", lang)}: {label}" + (f" / {sport}" if sport else ""))
    elif year is not None and sport:
        print(f"{t("season_summary", lang)}: {year} / {sport}")
    elif year is not None:
        print(f"{t("season_summary", lang)}: {year}")
    elif sport:
        print(f"{t("training_summary", lang)}: {sport}")
    else:
        print(t("training_summary", lang))
    print("-" * 48)

    print(t("activities_processed", lang, value=len(ok)))
    print(t("activities_with_hr", lang, value=len(with_hr)))
    print(t("activities_without_hr", lang, value=len(without_hr)))
    print(t("errors", lang, value=sum(r["status"] == "error" for r in rows)))

    if volume is not None:
        print(t("activities_metadata", lang, value=volume["activities"]))
        if volume.get("moving_hours") is not None:
            print(t("total_moving", lang, value=volume["moving_hours"]))
        if volume.get("distance_km") is not None:
            print(t("total_distance", lang, value=volume["distance_km"]))
        if volume.get("elevation_gain_m") is not None:
            print(t("total_elevation", lang, value=volume["elevation_gain_m"]))
        print(t("long_activities", lang, a3=volume["rides_3h"], a4=volume["rides_4h"], a6=volume["rides_6h"]))

    if not ok:
        return

    types = Counter((r["activity_type"] or "unknown") for r in ok)
    if len(types) > 1:
        print(
            t("activity_types", lang, value=", ".join(f"{k}={v}" for k, v in types.most_common()))
        )

    strong = [r for r in with_hr if r["lt2_evidence"] == "strong"]
    moderate = [r for r in with_hr if r["lt2_evidence"] == "moderate"]

    print(t("strong_lt2", lang, value=len(strong)))
    print(t("moderate_lt2", lang, value=len(moderate)))

    strong_lows = [r["lt2_low"] for r in strong if r["lt2_low"] is not None]
    strong_highs = [r["lt2_high"] for r in strong if r["lt2_high"] is not None]

    if strong_lows and strong_highs:
        print(
            t("median_lt2", lang, value=f"{median(strong_lows):.1f}-{median(strong_highs):.1f} bpm")
        )
    else:
        print(t("median_lt2", lang, value=t("insufficient", lang)))

    best30 = top_values(r["best_30m_hr"] for r in with_hr)
    best60 = top_values(r["best_60m_hr"] for r in with_hr)
    best90 = top_values(r.get("best_90m_hr") for r in with_hr)

    if best30:
        print(
            "Top 30m HR observations:           "
            + ", ".join(f"{v:.1f}" for v in best30)
        )
    if best60:
        print(
            "Top 60m HR observations:           "
            + ", ".join(f"{v:.1f}" for v in best60)
        )
    if best90:
        print(
            "Top 90m HR observations:           "
            + ", ".join(f"{v:.1f}" for v in best90)
        )

    # HRmax evidence is descriptive. The supplied --hrmax remains the analysis
    # reference; users can inspect candidates and rerun with a revised value.
    credible = [
        r for r in with_hr
        if r.get("hrmax_candidate") is not None
        and r.get("hrmax_confidence") in {"high", "medium"}
    ]
    if credible:
        credible_sorted = sorted(
            credible, key=lambda r: float(r["hrmax_candidate"]), reverse=True
        )[:5]
        print(t("highest_hrmax", lang))
        for r in credible_sorted:
            print(
                f"  {float(r['hrmax_candidate']):.1f} bpm "
                f"({r['hrmax_confidence']})  {r['activity_date']}"
            )

    raw_top = top_values((r.get("raw_max_hr") for r in with_hr), n=5)
    if raw_top:
        print(
            t("highest_raw_hr", lang, value=", ".join(f"{v:.0f}" for v in raw_top))
        )

    best2h = top_values((r.get("best_2h_hr") for r in with_hr))
    best4h = top_values((r.get("best_4h_hr") for r in with_hr))
    print(t("qualifying_2h", lang, value=sum(r.get("best_2h_hr") is not None for r in ok)))
    if best2h:
        print(
            "Top 2h sustained HR observations:   "
            + ", ".join(f"{v:.1f}" for v in best2h)
        )
    print(t("qualifying_4h", lang, value=sum(r.get("best_4h_hr") is not None for r in ok)))
    if best4h:
        print(
            "Top 4h sustained HR observations:   "
            + ", ".join(f"{v:.1f}" for v in best4h)
        )

    comparable = [
        r for r in ok
        if r["vam_15"] is not None
        and r["vam_30"] is not None
        and r["vam_comparison"]
        and r["vam_comparison"].startswith("comparable:")
    ]

    print(t("comparable_vam", lang, value=len(comparable)))
    if comparable:
        best_vam15 = top_values(r["vam_15"] for r in comparable)
        best_vam30 = top_values(r["vam_30"] for r in comparable)
        best_vam60 = top_values(r.get("vam_60") for r in comparable)
        retention = [
            float(r["vam_retention_pct"])
            for r in comparable
            if r["vam_retention_pct"] is not None
        ]

        print(
            "Top comparable 15m VAM:            "
            + ", ".join(f"{v:.0f}" for v in best_vam15)
            + " m/h"
        )
        print(
            "Top comparable 30m VAM:            "
            + ", ".join(f"{v:.0f}" for v in best_vam30)
            + " m/h"
        )
        if best_vam60:
            print(
                "Top comparable 60m VAM:            "
                + ", ".join(f"{v:.0f}" for v in best_vam60)
                + " m/h"
            )
        if retention:
            print(
                f"Median comparable VAM retention:   "
                f"{median(retention):.1f}%"
            )

    cycling_rows = [r for r in ok if normalize_strava_sport(r.get("activity_type")) == "cycling"]
    comparable_cycling = [r for r in comparable if normalize_strava_sport(r.get("activity_type")) == "cycling"]
    bikes = Counter((r.get("activity_gear") or "unknown") for r in cycling_rows)
    if any(name != "unknown" for name in bikes):
        print()
        print(t("vam_by_bike", lang))
        print("-" * 48)
        for bike, activity_count in bikes.most_common():
            bike_rows = [r for r in comparable_cycling if (r.get("activity_gear") or "unknown") == bike]
            if not bike_rows:
                continue

            weights = [
                float(r["bike_weight"])
                for r in bike_rows
                if r.get("bike_weight") is not None
            ]
            vam15 = [float(r["vam_15"]) for r in bike_rows if r.get("vam_15") is not None]
            vam30 = [float(r["vam_30"]) for r in bike_rows if r.get("vam_30") is not None]
            vam60 = [float(r["vam_60"]) for r in bike_rows if r.get("vam_60") is not None]
            retention = [
                float(r["vam_retention_pct"])
                for r in bike_rows
                if r.get("vam_retention_pct") is not None
            ]

            weight_text = f", {median(weights):.1f} kg" if weights else ""
            print(t("bike_activities", lang, bike=bike, count=activity_count, weight=weight_text))
            print(f"  comparable VAM: {len(bike_rows)}")
            if vam15:
                print(f"  15m VAM median/best: {median(vam15):.0f} / {max(vam15):.0f} m/h")
            if vam30:
                print(f"  30m VAM median/best: {median(vam30):.0f} / {max(vam30):.0f} m/h")
            if vam60:
                print(f"  60m VAM median/best: {median(vam60):.0f} / {max(vam60):.0f} m/h")
            if retention:
                print(f"  median retention: {median(retention):.1f}%")

    interval_rows = [r for r in ok if r.get("interval_count")]
    print()
    print(t("detected_intervals", lang, value=len(interval_rows)))
    if interval_rows:
        for r in interval_rows:
            date = r.get("activity_date") or "-"
            name = r.get("activity_name") or r.get("filename") or "-"
            detail = r.get("interval_summary") or "-"
            print(f"  {date:<18} {name}: {detail}")

    artefacts = [r for r in with_hr if r["hr_artefact"]]
    print()
    print(t("hr_artefacts", lang, value=len(artefacts)))


def _csv_safe_training_row(row: dict) -> dict:
    """Encode nested hard-effort evidence as JSON text in the flat CSV format."""
    out = dict(row)
    for key in ("hard_blocks", "hard_block_gaps"):
        value = out.get(key)
        out[key] = json.dumps(value, ensure_ascii=False, separators=(",", ":")) if value else ""
    return out


def run_training_scan(
    args,
    files: list[Path],
    output: Path,
    strava_metadata: dict[str, dict],
    volume: dict | None = None,
    activities_csv: Path | None = None,
) -> int:
    rows: list[dict] = []
    error_rows: list[dict] = []
    counts = {"ok": 0, "error": 0, "filtered": 0}

    csv_handle = None
    writer = None
    if not args.json:
        csv_handle = output.open("w", newline="", encoding="utf-8")
        writer = csv.DictWriter(csv_handle, fieldnames=TRAINING_CSV_FIELDS)
        writer.writeheader()

    try:
        for index, path in enumerate(files, start=1):
            summary = process_training_file(
                path,
                hrmax=args.hrmax,
                lt2=args.lt2,
                lt1=args.lt1,
                min_hr=args.min_hr,
                max_hr=args.max_hr,
            )

            # Errors often have no parsed date/type. Count and display them
            # before applying year/sport filters so they cannot masquerade as
            # "filtered out" activities.
            if summary.status == "error":
                counts["error"] += 1
                row = enrich_training_row(summary.to_dict(), strava_metadata)
                error_rows.append(row)
                print(
                    f"[{index:>4}/{len(files)}] {summary.filename} | "
                    f"{t("error_prefix", args.lang)}: {summary.error}"
                )
                continue

            if not passes_filters(summary, args.year, args.month, args.sport):
                counts["filtered"] += 1
                continue

            row = enrich_training_row(summary.to_dict(), strava_metadata)
            rows.append(row)
            if writer is not None:
                writer.writerow(_csv_safe_training_row(row))
            counts["ok"] += 1

            label = summary.classification or summary.status
            gear = row.get("activity_gear")
            gear_text = f" | {gear}" if gear else ""
            print(
                f"[{index:>4}/{len(files)}] {summary.filename} | "
                f"{summary.status} | {label}{gear_text}"
            )
    finally:
        if csv_handle is not None:
            csv_handle.close()

    if args.add_missing_metadata:
        if activities_csv is None:
            print(t("metadata_skipped", args.lang), file=sys.stderr)
        else:
            try:
                added = append_missing_metadata_rows(activities_csv, rows, strava_metadata)
                print(t("metadata_appended", args.lang, value=added))
                if added:
                    # Refresh annual/season volume so the current run immediately
                    # includes the newly appended activities.
                    refreshed_metadata = load_strava_metadata(activities_csv)
                    volume = metadata_volume_summary(refreshed_metadata, args.year, args.month, args.sport)
            except (OSError, ValueError) as exc:
                print(t("metadata_update_error", args.lang, value=exc), file=sys.stderr)
                return 2

    # Volume metrics come from Strava metadata, but the activity count should
    # describe the files actually selected by this scan. Keep selected files
    # that later failed processing in the count.
    if volume is not None:
        volume = dict(volume)
        volume["activities"] = len(files) - counts["filtered"]

    weekly = build_weekly_summary(rows, strava_metadata, args.year, args.month, args.sport)
    structured_summary = build_training_summary(
        rows + error_rows, args.year, args.month, args.sport, volume, weekly
    )

    if args.json:
        write_json_output(output, rows, structured_summary, args)

    print()
    print(t("supported_files", args.lang, value=len(files)))
    if args.year is not None or args.sport is not None:
        print(t("filtered_out", args.lang, value=counts["filtered"]))
    print(t("processed_short", args.lang, value=counts["ok"]))
    print(t("with_hr_short", args.lang, value=sum(bool(r.get("has_hr")) for r in rows)))
    print(t("without_hr_short", args.lang, value=sum(not bool(r.get("has_hr")) for r in rows)))
    print(t("errors_short", args.lang, value=counts["error"]))
    print(t("written_to", args.lang, kind="JSON" if args.json else "CSV", value=output))

    print_training_summary(rows + error_rows, args.year, args.month, args.sport, volume, lang=args.lang)

    return 1 if counts["error"] else 0


def main() -> int:
    lang = detect_language()
    args = build_parser(lang).parse_args()
    lang = args.lang

    directory = args.directory.expanduser()
    output = default_output(args)

    if not directory.is_dir():
        print(t("err_not_dir", lang, value=directory), file=sys.stderr)
        return 2

    if args.month is not None and args.year is None:
        print(t("err_month_year", lang), file=sys.stderr)
        return 2

    if args.min_hr >= args.max_hr:
        print(t("err_minmax", lang), file=sys.stderr)
        return 2

    if not (args.min_hr < args.hrmax < args.max_hr):
        print(t("err_hrmax", lang), file=sys.stderr)
        return 2

    if (args.lt1 is None) != (args.lt2 is None):
        print(t("err_zones", lang), file=sys.stderr)
        return 2
    if args.lt1 is not None and not (args.min_hr < args.lt1 < args.lt2 < args.max_hr):
        print(t("err_threshold_order", lang), file=sys.stderr)
        return 2

    files = supported_files(directory)

    activities_csv = resolve_activities_csv(args, directory)
    try:
        strava_metadata = load_strava_metadata(activities_csv)
    except (OSError, ValueError) as exc:
        print(t("err_load_metadata", lang, value=exc), file=sys.stderr)
        return 2

    if activities_csv is not None:
        print(t("strava_metadata", lang, value=activities_csv))
        print(t("metadata_rows", lang, value=len(strava_metadata)))
    else:
        print(t("metadata_missing", lang))

    volume = metadata_volume_summary(strava_metadata, args.year, args.month, args.sport)

    # Major speed-up: when activities.csv is available and at least one
    # date/sport filter is requested, use the CSV as the index and open only
    # matching activity files. The activity files remain authoritative for
    # HR/VAM/LT2 analysis.
    if strava_metadata and not args.add_missing_metadata and (args.year is not None or args.sport is not None):
        files, matched_count, missing_count = preselect_files_from_metadata(
            directory, strava_metadata, args.year, args.month, args.sport
        )
        print(t("csv_rows_matched", lang, value=matched_count))
        print(t("matching_files", lang, value=len(files)))
        if missing_count:
            print(t("csv_missing_file", lang, value=missing_count))

    return run_training_scan(args, files, output, strava_metadata, volume, activities_csv)


if __name__ == "__main__":
    raise SystemExit(main())
