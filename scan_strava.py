#!/usr/bin/env python3
"""
Scan Strava GPX/TCX/FIT activity files for training analysis (V13).

This version is training-analysis only: --hrmax is required. It writes per-ride
HRmax evidence, sustained HR observations (30m/60m/90m/2h/4h), VAM
(15m/30m/60m), LT2 evidence and HR artefact flags.

When Strava activities.csv is available it also supplies bike metadata and
annual/season volume totals (all matching activities, including rides without HR).

V13 adds rolling 12-month seasons via --month and optional appending of newly
analysed files to activities.csv via --add-missing-metadata.
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime
from collections import Counter
from pathlib import Path
from statistics import median
import re
import shutil

from activity_file_processor import detect_format, process_training_file


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
    "status",
    "error",
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Parse GPX, TCX and FIT files and run training analysis. "
            "--hrmax is required as the yearly analysis reference."
        )
    )
    parser.add_argument(
        "directory",
        type=Path,
        help="Directory containing activity files",
    )
    parser.add_argument(
        "--min-hr",
        type=int,
        default=50,
        help="Minimum accepted HR in bpm (default: 50)",
    )
    parser.add_argument(
        "--max-hr",
        type=int,
        default=220,
        help="Maximum accepted HR in bpm (default: 220)",
    )
    parser.add_argument(
        "--hrmax",
        type=int,
        required=True,
        help="Yearly HRmax reference used by the training analysis, e.g. --hrmax 184",
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
            "Optional normalized activity type filter, e.g. cycling, running, "
            "skiing, walking."
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
        "--output",
        type=Path,
        default=None,
        help=(
            "Output CSV. Defaults to training_<year>.csv or strava_training_summary.csv."
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

    if sport is not None:
        actual = (summary.activity_type or "").strip().lower()
        if actual != sport.strip().lower():
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
        "backcountryski": "skiing",
        "rollerski": "roller skiing",
    }
    return mapping.get(key, value.strip().lower())


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
    requested_sport = sport.strip().lower() if sport else None

    for filename, info in metadata.items():
        if not date_in_window(info.get("strava_activity_date"), year, month):
            continue

        if requested_sport is not None:
            actual = normalize_strava_sport(info.get("strava_activity_type"))
            if actual != requested_sport:
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


def default_output(args) -> Path:
    if args.output is not None:
        return args.output.expanduser()

    if args.year is not None:
        if args.month is not None:
            return Path(f"training_{args.year}-{args.month:02d}.csv")
        return Path(f"training_{args.year}.csv")

    return Path("strava_training_summary.csv")


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
    if sport is not None:
        actual = normalize_strava_sport(info.get("strava_activity_type"))
        if actual != sport.strip().lower():
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
    return {
        "activities": len(rows),
        "elapsed_hours": sum(elapsed)/3600 if elapsed else None,
        "moving_hours": sum(moving)/3600 if moving else None,
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


def print_training_summary(rows: list[dict], year: int | None, month: int | None, sport: str | None, volume: dict | None = None):
    ok = [r for r in rows if r["status"] == "ok"]

    print()
    if year is not None and month is not None:
        start, end = season_bounds(year, month)
        label = f"{start.strftime('%b %Y')} to {(end.replace(day=1) if end else end).strftime('%b %Y')}" if start and end else str(year)
        # End is exclusive, so display the final included month.
        final_month = 12 if month == 1 else month - 1
        final_year = year if month == 1 else year + 1
        label = f"{start.strftime('%b %Y')} to {datetime(final_year, final_month, 1).strftime('%b %Y')}"
        print(f"Season summary: {label}" + (f" / {sport}" if sport else ""))
    elif year is not None and sport:
        print(f"Season summary: {year} / {sport}")
    elif year is not None:
        print(f"Season summary: {year}")
    elif sport:
        print(f"Training summary: {sport}")
    else:
        print("Training summary")
    print("-" * 48)

    print(f"Activities analysed:              {len(ok)}")
    print(f"Errors:                           {sum(r['status'] == 'error' for r in rows)}")

    if volume is not None:
        print(f"Activities in Strava metadata:    {volume['activities']}")
        if volume.get("moving_hours") is not None:
            print(f"Total moving time:                {volume['moving_hours']:.1f} h")
        if volume.get("distance_km") is not None:
            print(f"Total distance:                   {volume['distance_km']:.0f} km")
        if volume.get("elevation_gain_m") is not None:
            print(f"Total elevation gain:             {volume['elevation_gain_m']:.0f} m")
        print(f"Long rides >=3h / >=4h / >=6h:   {volume['rides_3h']} / {volume['rides_4h']} / {volume['rides_6h']}")

    if not ok:
        return

    types = Counter((r["activity_type"] or "unknown") for r in ok)
    if len(types) > 1:
        print(
            "Activity types:                    "
            + ", ".join(f"{k}={v}" for k, v in types.most_common())
        )

    strong = [r for r in ok if r["lt2_evidence"] == "strong"]
    moderate = [r for r in ok if r["lt2_evidence"] == "moderate"]

    print(f"Strong LT2 observations:          {len(strong)}")
    print(f"Moderate LT2 observations:        {len(moderate)}")

    strong_lows = [r["lt2_low"] for r in strong if r["lt2_low"] is not None]
    strong_highs = [r["lt2_high"] for r in strong if r["lt2_high"] is not None]

    if strong_lows and strong_highs:
        print(
            f"Median strong LT2 range:           "
            f"{median(strong_lows):.1f}-{median(strong_highs):.1f} bpm"
        )
    else:
        print("Median strong LT2 range:           insufficient evidence")

    best30 = top_values(r["best_30m_hr"] for r in ok)
    best60 = top_values(r["best_60m_hr"] for r in ok)
    best90 = top_values(r.get("best_90m_hr") for r in ok)

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
        r for r in ok
        if r.get("hrmax_candidate") is not None
        and r.get("hrmax_confidence") in {"high", "medium"}
    ]
    if credible:
        credible_sorted = sorted(
            credible, key=lambda r: float(r["hrmax_candidate"]), reverse=True
        )[:5]
        print("Highest credible HRmax candidates:")
        for r in credible_sorted:
            print(
                f"  {float(r['hrmax_candidate']):.1f} bpm "
                f"({r['hrmax_confidence']})  {r['activity_date']}"
            )

    raw_top = top_values((r.get("raw_max_hr") for r in ok), n=5)
    if raw_top:
        print(
            "Highest raw HR observations:        "
            + ", ".join(f"{v:.0f}" for v in raw_top)
        )

    best2h = top_values((r.get("best_2h_hr") for r in ok))
    best4h = top_values((r.get("best_4h_hr") for r in ok))
    print(f"Qualifying 2h sustained windows:   {sum(r.get('best_2h_hr') is not None for r in ok)}")
    if best2h:
        print(
            "Top 2h sustained HR observations:   "
            + ", ".join(f"{v:.1f}" for v in best2h)
        )
    print(f"Qualifying 4h sustained windows:   {sum(r.get('best_4h_hr') is not None for r in ok)}")
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

    print(f"Comparable VAM activities:         {len(comparable)}")
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

    bikes = Counter((r.get("activity_gear") or "unknown") for r in ok)
    if any(name != "unknown" for name in bikes):
        print()
        print("VAM by bike (comparable activities)")
        print("-" * 48)
        for bike, activity_count in bikes.most_common():
            bike_rows = [r for r in comparable if (r.get("activity_gear") or "unknown") == bike]
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
            print(f"{bike} ({activity_count} rides{weight_text})")
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
    print(f"Detected interval sessions:        {len(interval_rows)}")
    if interval_rows:
        for r in interval_rows:
            date = r.get("activity_date") or "-"
            name = r.get("activity_name") or r.get("filename") or "-"
            detail = r.get("interval_summary") or "-"
            print(f"  {date:<18} {name}: {detail}")

    artefacts = [r for r in ok if r["hr_artefact"]]
    print()
    print(f"Activities with HR artefact flag:  {len(artefacts)}")


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

    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=TRAINING_CSV_FIELDS)
        writer.writeheader()

        for index, path in enumerate(files, start=1):
            summary = process_training_file(
                path,
                hrmax=args.hrmax,
                lt2=args.lt2,
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
                    f"ERROR: {summary.error}"
                )
                continue

            if not passes_filters(summary, args.year, args.month, args.sport):
                counts["filtered"] += 1
                continue

            row = enrich_training_row(summary.to_dict(), strava_metadata)
            rows.append(row)
            writer.writerow(row)
            counts["ok"] += 1

            label = summary.classification or summary.status
            gear = row.get("activity_gear")
            gear_text = f" | {gear}" if gear else ""
            print(
                f"[{index:>4}/{len(files)}] {summary.filename} | "
                f"{summary.status} | {label}{gear_text}"
            )

    print()
    print(f"Supported files found: {len(files)}")
    if args.year is not None or args.sport is not None:
        print(f"Filtered out:          {counts['filtered']}")
    print(f"Activities analysed:   {counts['ok']}")
    print(f"Errors:                {counts['error']}")
    print(f"CSV written to:        {output}")

    if args.add_missing_metadata:
        if activities_csv is None:
            print("Metadata update skipped: no activities.csv found", file=sys.stderr)
        else:
            try:
                added = append_missing_metadata_rows(activities_csv, rows, strava_metadata)
                print(f"Metadata rows appended: {added}")
                if added:
                    # Refresh annual/season volume so the current run immediately
                    # includes the newly appended activities.
                    refreshed_metadata = load_strava_metadata(activities_csv)
                    volume = metadata_volume_summary(refreshed_metadata, args.year, args.month, args.sport)
            except (OSError, ValueError) as exc:
                print(f"Error updating activities.csv: {exc}", file=sys.stderr)
                return 2

    print_training_summary(rows + error_rows, args.year, args.month, args.sport, volume)

    return 1 if counts["error"] else 0


def main() -> int:
    args = build_parser().parse_args()

    directory = args.directory.expanduser()
    output = default_output(args)

    if not directory.is_dir():
        print(f"Error: not a directory: {directory}", file=sys.stderr)
        return 2

    if args.month is not None and args.year is None:
        print("Error: --month requires --year.", file=sys.stderr)
        return 2

    if args.min_hr >= args.max_hr:
        print("Error: --min-hr must be lower than --max-hr.", file=sys.stderr)
        return 2

    if not (args.min_hr < args.hrmax < args.max_hr):
        print(
            "Error: --hrmax must lie between --min-hr and --max-hr.",
            file=sys.stderr,
        )
        return 2

    files = supported_files(directory)

    activities_csv = resolve_activities_csv(args, directory)
    try:
        strava_metadata = load_strava_metadata(activities_csv)
    except (OSError, ValueError) as exc:
        print(f"Error loading Strava activities.csv: {exc}", file=sys.stderr)
        return 2

    if activities_csv is not None:
        print(f"Strava metadata:       {activities_csv}")
        print(f"Metadata rows loaded:  {len(strava_metadata)}")
    else:
        print("Strava metadata:       not found (bike fields will be blank)")

    volume = metadata_volume_summary(strava_metadata, args.year, args.month, args.sport)

    # Major speed-up: when activities.csv is available and at least one
    # date/sport filter is requested, use the CSV as the index and open only
    # matching activity files. The activity files remain authoritative for
    # HR/VAM/LT2 analysis.
    if strava_metadata and not args.add_missing_metadata and (args.year is not None or args.sport is not None):
        files, matched_count, missing_count = preselect_files_from_metadata(
            directory, strava_metadata, args.year, args.month, args.sport
        )
        print(f"CSV rows matched:      {matched_count}")
        print(f"Matching files found:  {len(files)}")
        if missing_count:
            print(f"CSV rows missing file: {missing_count}")

    return run_training_scan(args, files, output, strava_metadata, volume, activities_csv)


if __name__ == "__main__":
    raise SystemExit(main())
