import json
import pandas as pd

DATE_FORMAT = "%d %b %Y %H:%M"


def load_training_json(file_or_path):
    if hasattr(file_or_path, "read"):
        return json.load(file_or_path)
    with open(file_or_path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _parse_duration_seconds(duration):
    if not duration:
        return None
    parts = str(duration).split(":")
    try:
        parts = [int(float(p)) for p in parts]
    except ValueError:
        return None
    if len(parts) == 3:
        hours, minutes, seconds = parts
    elif len(parts) == 2:
        hours = 0
        minutes, seconds = parts
    else:
        return None
    return hours * 3600 + minutes * 60 + seconds


def _parse_activity_date(value):
    if not value:
        return pd.NaT
    try:
        return pd.to_datetime(value, format=DATE_FORMAT)
    except (ValueError, TypeError):
        return pd.to_datetime(value, errors="coerce")


def _activity_key(activity):
    return f"{activity.get('filename', '')}|{activity.get('activity_date', '')}"


def build_activity_dataframe(training):
    rows = []
    for activity in training.get("activities", []):
        duration_seconds = _parse_duration_seconds(activity.get("duration"))
        rows.append({
            "activity_key": _activity_key(activity),
            "date": _parse_activity_date(activity.get("activity_date")),
            "name": activity.get("activity_name") or activity.get("filename") or "Unnamed activity",
            "sport": activity.get("activity_type"),
            "duration": activity.get("duration"),
            "duration_seconds": duration_seconds,
            "moving_hours": (duration_seconds / 3600.0) if duration_seconds is not None else None,
            "average_hr": activity.get("average_hr"),
            "max_hr": activity.get("analysed_max_hr"),
            "moving_time": activity.get("moving_time") or activity.get("moving_duration"),
            "average_cadence_rpm": activity.get("average_cadence_rpm"),
            "hr_intensity": activity.get("hr_intensity"),
            "hr_load": activity.get("hr_load"),
            "distance_km": activity.get("distance_km"),
            "elevation_gain_m": activity.get("elevation_gain_m"),
            "classification": activity.get("classification"),
            "bike": activity.get("activity_gear"),
            "gear": activity.get("activity_gear"),
            "location": activity.get("start_location"),
            "hard_blocks": activity.get("hard_block_count"),
            "tempo_blocks": activity.get("tempo_block_count"),
            "has_hr": activity.get("has_hr"),
        })
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("date").reset_index(drop=True)
    return df


def find_activity(training, activity_key):
    for activity in training.get("activities", []):
        if _activity_key(activity) == activity_key:
            return activity
    return None


def build_weekly_dataframe(training):
    rows = training.get("summary", {}).get("weekly_training", [])
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    if "week_start" in df.columns:
        df["week_start"] = pd.to_datetime(df["week_start"], errors="coerce")
        df = df.sort_values("week_start").reset_index(drop=True)
    return df


def build_summary_metrics(activity_df):
    return {
        "activities": int(len(activity_df)),
        "moving_hours": float(activity_df["moving_hours"].fillna(0).sum()),
        "hr_load": float(activity_df["hr_load"].fillna(0).sum()),
        "distance_km": float(activity_df["distance_km"].fillna(0).sum()),
        "elevation_gain_m": float(activity_df["elevation_gain_m"].fillna(0).sum()),
    }
