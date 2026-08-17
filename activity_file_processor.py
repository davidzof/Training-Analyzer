#!/usr/bin/env python3
"""
Parse one GPX, TCX or FIT activity file, compressed or uncompressed.

This module is intended to be imported by scan_strava_files.py.
It returns a compact summary including activity date/type, HR sample count,
raw HRmax and a 10-second maximum average.

FIT support requires:
    python3 -m pip install fitparse
"""

from __future__ import annotations

import gzip
import io
import xml.etree.ElementTree as ET
from collections import deque
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import BinaryIO, Iterable


@dataclass(frozen=True)
class HrSample:
    timestamp: datetime
    heart_rate: int


@dataclass
class ActivitySummary:
    filename: str
    file_format: str
    compressed: bool
    activity_date: str | None
    activity_type: str | None
    valid_hr_samples: int
    raw_hrmax: int | None
    hrmax_10s: float | None
    status: str
    error: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))


def detect_format(path: Path) -> tuple[str, bool]:
    name = path.name.lower()

    for fmt in ("gpx", "tcx", "fit"):
        if name.endswith(f".{fmt}.gz"):
            return fmt, True
        if name.endswith(f".{fmt}"):
            return fmt, False

    raise ValueError(f"Unsupported activity file: {path.name}")


def open_binary(path: Path, compressed: bool) -> BinaryIO:
    return gzip.open(path, "rb") if compressed else path.open("rb")




def sanitised_xml_stream(stream: BinaryIO) -> io.BytesIO:
    """Read XML bytes and remove leading BOM/whitespace before declaration."""
    data = stream.read()
    data = data.lstrip(b"\xef\xbb\xbf \t\r\n")
    return io.BytesIO(data)


def normalise_activity_type(value: str | None) -> str | None:
    if not value:
        return None

    text = value.strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "ride": "cycling",
        "biking": "cycling",
        "bike": "cycling",
        "cycling": "cycling",
        "road_biking": "cycling",
        "mountain_biking": "cycling",
        "virtual_ride": "cycling",
        "run": "running",
        "running": "running",
        "trail_running": "running",
        "walk": "walking",
        "walking": "walking",
        "hike": "hiking",
        "hiking": "hiking",
        "ski": "skiing",
        "skiing": "skiing",
        "cross_country_skiing": "skiing",
        "nordic_ski": "skiing",
    }
    return aliases.get(text, text)


def parse_gpx(stream: BinaryIO) -> tuple[str | None, list[HrSample]]:
    activity_type: str | None = None
    samples: list[HrSample] = []

    xml_stream = sanitised_xml_stream(stream)

    for _, element in ET.iterparse(xml_stream, events=("end",)):
        name = local_name(element.tag)

        if name == "type" and activity_type is None and element.text:
            activity_type = element.text.strip()

        elif name == "trkpt":
            timestamp: datetime | None = None
            heart_rate: int | None = None

            for child in element.iter():
                child_name = local_name(child.tag)
                if child_name == "time" and child.text:
                    timestamp = parse_timestamp(child.text)
                elif child_name in {"hr", "heartrate", "heart_rate"} and child.text:
                    try:
                        heart_rate = int(round(float(child.text.strip())))
                    except ValueError:
                        pass

            if timestamp is not None and heart_rate is not None:
                samples.append(HrSample(timestamp, heart_rate))

            element.clear()

    return normalise_activity_type(activity_type), sorted(
        samples, key=lambda item: item.timestamp
    )


def parse_tcx(stream: BinaryIO) -> tuple[str | None, list[HrSample]]:
    activity_type: str | None = None
    samples: list[HrSample] = []

    xml_stream = sanitised_xml_stream(stream)

    for _, element in ET.iterparse(xml_stream, events=("start", "end")):
        name = local_name(element.tag)

        if name == "activity" and activity_type is None:
            sport = element.attrib.get("Sport")
            if sport:
                activity_type = sport

        if name == "trackpoint":
            timestamp: datetime | None = None
            heart_rate: int | None = None

            for child in element.iter():
                child_name = local_name(child.tag)

                if child_name == "time" and child.text:
                    timestamp = parse_timestamp(child.text)

                elif child_name == "heartratebpm":
                    for descendant in child.iter():
                        if local_name(descendant.tag) == "value" and descendant.text:
                            try:
                                heart_rate = int(
                                    round(float(descendant.text.strip()))
                                )
                            except ValueError:
                                pass
                            break

            if timestamp is not None and heart_rate is not None:
                samples.append(HrSample(timestamp, heart_rate))

            element.clear()

    return normalise_activity_type(activity_type), sorted(
        samples, key=lambda item: item.timestamp
    )


def parse_fit(stream: BinaryIO) -> tuple[str | None, list[HrSample]]:
    try:
        from fitparse import FitFile
    except ImportError as exc:
        raise RuntimeError(
            "FIT support requires fitparse. Install it with: "
            "python3 -m pip install fitparse"
        ) from exc

    data = stream.read()
    fit_file = FitFile(io.BytesIO(data))

    activity_type: str | None = None
    samples: list[HrSample] = []

    for message in fit_file.get_messages("session"):
        sport = message.get_value("sport")
        if sport is not None:
            activity_type = str(sport)
            break

    for message in fit_file.get_messages("record"):
        timestamp = message.get_value("timestamp")
        heart_rate = message.get_value("heart_rate")

        if isinstance(timestamp, datetime) and heart_rate is not None:
            try:
                samples.append(
                    HrSample(timestamp, int(round(float(heart_rate))))
                )
            except (TypeError, ValueError):
                continue

    return normalise_activity_type(activity_type), sorted(
        samples, key=lambda item: item.timestamp
    )


def split_continuous_sections(
    samples: list[HrSample],
    max_gap_seconds: float = 3.0,
) -> list[list[HrSample]]:
    if not samples:
        return []

    sections: list[list[HrSample]] = [[samples[0]]]

    for previous, current in zip(samples, samples[1:]):
        gap = (current.timestamp - previous.timestamp).total_seconds()
        if gap <= 0 or gap > max_gap_seconds:
            sections.append([current])
        else:
            sections[-1].append(current)

    return sections


def max_rolling_average(
    sections: Iterable[list[HrSample]],
    window_seconds: int = 10,
) -> float | None:
    best: float | None = None
    required_span = max(0, window_seconds - 1)

    for section in sections:
        window: deque[HrSample] = deque()
        running_sum = 0

        for sample in section:
            window.append(sample)
            running_sum += sample.heart_rate

            while window and (
                sample.timestamp - window[0].timestamp
            ).total_seconds() > required_span:
                removed = window.popleft()
                running_sum -= removed.heart_rate

            if not window:
                continue

            span = (window[-1].timestamp - window[0].timestamp).total_seconds()
            if span >= required_span:
                average = running_sum / len(window)
                if best is None or average > best:
                    best = average

    return best


def process_activity_file(
    path: Path,
    min_hr: int = 50,
    max_hr: int = 220,
) -> ActivitySummary:
    fmt, compressed = detect_format(path)

    try:
        with open_binary(path, compressed) as stream:
            if fmt == "gpx":
                activity_type, samples = parse_gpx(stream)
            elif fmt == "tcx":
                activity_type, samples = parse_tcx(stream)
            elif fmt == "fit":
                activity_type, samples = parse_fit(stream)
            else:
                raise ValueError(f"Unsupported format: {fmt}")

        valid_samples = [
            sample
            for sample in samples
            if min_hr <= sample.heart_rate <= max_hr
        ]

        activity_date = (
            valid_samples[0].timestamp.isoformat()
            if valid_samples
            else (samples[0].timestamp.isoformat() if samples else None)
        )

        if not samples:
            return ActivitySummary(
                filename=path.name,
                file_format=fmt.upper(),
                compressed=compressed,
                activity_date=None,
                activity_type=activity_type,
                valid_hr_samples=0,
                raw_hrmax=None,
                hrmax_10s=None,
                status="no_samples",
            )

        if not valid_samples:
            return ActivitySummary(
                filename=path.name,
                file_format=fmt.upper(),
                compressed=compressed,
                activity_date=activity_date,
                activity_type=activity_type,
                valid_hr_samples=0,
                raw_hrmax=None,
                hrmax_10s=None,
                status="no_valid_hr",
            )

        sections = split_continuous_sections(valid_samples)
        raw_hrmax = max(sample.heart_rate for sample in valid_samples)
        hrmax_10s = max_rolling_average(sections, 10)

        return ActivitySummary(
            filename=path.name,
            file_format=fmt.upper(),
            compressed=compressed,
            activity_date=activity_date,
            activity_type=activity_type,
            valid_hr_samples=len(valid_samples),
            raw_hrmax=raw_hrmax,
            hrmax_10s=round(hrmax_10s, 1) if hrmax_10s is not None else None,
            status="ok",
        )

    except Exception as exc:
        return ActivitySummary(
            filename=path.name,
            file_format=fmt.upper(),
            compressed=compressed,
            activity_date=None,
            activity_type=None,
            valid_hr_samples=0,
            raw_hrmax=None,
            hrmax_10s=None,
            status="error",
            error=str(exc),
        )

# ---------------------------------------------------------------------------
# V8 seasonal / training analysis
# ---------------------------------------------------------------------------

@dataclass
class TrainingSummary:
    """
    Compact one-row representation of analyze_training.ActivityAnalysis.

    ActivitySummary remains the lightweight historical HR scan.
    TrainingSummary is the richer seasonal/trend record.
    """
    filename: str
    activity_date: str | None
    activity_type: str | None
    duration: str | None
    average_hr: float | None
    raw_max_hr: int | None
    analysed_max_hr: int | None
    hrmax_10s: float | None
    hrmax_30s: float | None
    hrmax_60s: float | None
    hrmax_candidate: float | None
    hrmax_confidence: str | None
    hrmax_reason: str | None
    best_30m_hr: float | None
    best_60m_hr: float | None
    best_90m_hr: float | None
    best_2h_hr: float | None
    best_2h_moving_fraction: float | None
    best_2h_hr_p10: float | None
    best_2h_hr_p90: float | None
    best_4h_hr: float | None
    best_4h_moving_fraction: float | None
    best_4h_hr_p10: float | None
    best_4h_hr_p90: float | None
    vam_15: float | None
    vam_30: float | None
    vam_60: float | None
    vam_retention_pct: float | None
    vam_comparison: str | None
    time_85pct_seconds: float | None
    time_90pct_seconds: float | None
    zone1_seconds: float | None
    zone2_seconds: float | None
    zone3_seconds: float | None
    zone_total_seconds: float | None
    active_zone1_seconds: float | None
    active_zone2_seconds: float | None
    active_zone3_seconds: float | None
    active_zone_total_seconds: float | None
    active_zone1_pct: float | None
    active_zone2_pct: float | None
    active_zone3_pct: float | None
    zone1_pct: float | None
    zone2_pct: float | None
    zone3_pct: float | None
    hard_block_threshold_bpm: float | None
    hard_block_count: int
    hard_blocks: list[dict]
    hard_block_gaps: list[dict]
    interval_count: int | None
    interval_work_total: str | None
    interval_work_median: str | None
    interval_work_avg_hr: float | None
    interval_work_max_hr: int | None
    interval_recovery_median: str | None
    interval_recovery_avg_hr: float | None
    interval_work_durations: str | None
    interval_work_avg_hrs: str | None
    interval_work_max_hrs: str | None
    interval_recovery_durations: str | None
    interval_recovery_avg_hrs: str | None
    interval_summary: str | None
    overall_ride: str | None
    key_effort: str | None
    classification: str | None
    confidence: str | None
    lt2_low: float | None
    lt2_high: float | None
    lt2_evidence: str | None
    lt2_reason: str | None
    lt2_clue: str | None
    hr_artefact: bool
    excluded_hr_samples: int
    distance_km: float | None
    elevation_gain_m: float | None
    has_hr: bool
    has_elevation: bool
    has_gps: bool
    has_power: bool
    status: str
    error: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _format_duration_hms(seconds: float | None) -> str | None:
    if seconds is None:
        return None
    total = int(round(seconds))
    h, rem = divmod(total, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}"


def _format_duration_list(values) -> str | None:
    if not values:
        return None
    return "|".join(_format_duration_hms(v) or "" for v in values)


def _format_number_list(values, digits=1) -> str | None:
    if not values:
        return None
    out = []
    for value in values:
        if value is None:
            out.append("")
        elif digits == 0:
            out.append(str(int(round(value))))
        else:
            out.append(f"{value:.{digits}f}")
    return "|".join(out)


def _format_interval_summary(i) -> str | None:
    if i is None:
        return None
    work = _format_duration_hms(i.work_median_s)
    rec = _format_duration_hms(i.recovery_median_s) if i.recovery_median_s is not None else "-"
    text = f"{i.count} detected hard-HR blocks; median {work} @ {i.work_avg_hr:.1f} bpm"
    if i.recovery_median_s is not None:
        text += f"; median recovery {rec}"
        if i.recovery_avg_hr is not None:
            text += f" @ {i.recovery_avg_hr:.1f} bpm"
    return text


def _format_activity_date(dt) -> str | None:
    if dt is None:
        return None
    return dt.strftime("%d %b %Y %H:%M")


def _serialize_hard_blocks(result) -> list[dict]:
    """Return all detected hard-HR blocks, independent of interval classification."""
    return [
        {
            "start": b.start.strftime("%H:%M:%S"),
            "end": b.end.strftime("%H:%M:%S"),
            "duration_seconds": round(b.duration_s, 1),
            "average_hr_bpm": round(b.avg_hr, 1),
            "max_hr_bpm": int(b.max_hr),
        }
        for b in result.blocks
    ]


def _serialize_hard_block_gaps(result) -> list[dict]:
    """Return terrain/recovery gaps between consecutive detected hard-HR blocks."""
    return [
        {
            "start": g.start.strftime("%H:%M:%S"),
            "end": g.end.strftime("%H:%M:%S"),
            "duration_seconds": round(g.duration_s, 1),
            "distance_km": round(g.distance_m / 1000.0, 3),
            "elevation_change_m": round(g.elev_gain_m, 1) if g.elev_gain_m is not None else None,
            "average_hr_bpm": round(g.avg_hr, 1) if g.avg_hr is not None else None,
            "stopped_fraction": round(g.stopped_fraction, 3),
            "kind": g.kind,
        }
        for g in result.gaps
    ]


def process_training_file(
    path: Path,
    hrmax: int,
    lt2: float | None = None,
    lt1: float | None = None,
    min_hr: int = 50,
    max_hr: int = 220,
) -> TrainingSummary:
    """
    Run V7's richer analysis on one activity.

    analyze_training.py must be in the same directory or on PYTHONPATH.
    """
    try:
        from analyze_training import analyze_activity
    except ImportError as exc:
        return TrainingSummary(
            filename=path.name, activity_date=None, activity_type=None,
            duration=None, average_hr=None, raw_max_hr=None,
            analysed_max_hr=None, hrmax_10s=None, hrmax_30s=None, hrmax_60s=None,
            hrmax_candidate=None, hrmax_confidence=None, hrmax_reason=None,
            best_30m_hr=None, best_60m_hr=None, best_90m_hr=None, best_2h_hr=None,
            best_2h_moving_fraction=None, best_2h_hr_p10=None, best_2h_hr_p90=None,
            best_4h_hr=None, best_4h_moving_fraction=None, best_4h_hr_p10=None,
            best_4h_hr_p90=None,
            vam_15=None, vam_30=None, vam_60=None, vam_retention_pct=None,
            vam_comparison=None, time_85pct_seconds=None,
            time_90pct_seconds=None, zone1_seconds=None, zone2_seconds=None, zone3_seconds=None, zone_total_seconds=None, active_zone1_seconds=None, active_zone2_seconds=None, active_zone3_seconds=None, active_zone_total_seconds=None, active_zone1_pct=None, active_zone2_pct=None, active_zone3_pct=None, zone1_pct=None, zone2_pct=None, zone3_pct=None, hard_block_threshold_bpm=None, hard_block_count=0,
            hard_blocks=[], hard_block_gaps=[], interval_count=None, interval_work_total=None,
            interval_work_median=None, interval_work_avg_hr=None, interval_work_max_hr=None,
            interval_recovery_median=None, interval_recovery_avg_hr=None,
            interval_work_durations=None, interval_work_avg_hrs=None, interval_work_max_hrs=None,
            interval_recovery_durations=None, interval_recovery_avg_hrs=None, interval_summary=None,
            overall_ride=None, key_effort=None,
            classification=None, confidence=None, lt2_low=None, lt2_high=None,
            lt2_evidence=None, lt2_reason=None, lt2_clue=None,
            hr_artefact=False, excluded_hr_samples=0, distance_km=None, elevation_gain_m=None,
            has_hr=False, has_elevation=False, has_gps=False, has_power=False, status="error",
            error=(
                "Could not import analyze_training.py. Put it in the same "
                "directory as activity_file_processor.py or on PYTHONPATH. "
                f"Original error: {exc}"
            ),
        )

    try:
        result = analyze_activity(
            path, hrmax=hrmax, lt2=lt2, lt1=lt1, min_hr=min_hr, max_hr=max_hr
        )
        sustained2h = result.sustained2h
        sustained4h = result.sustained4h

        return TrainingSummary(
            filename=path.name,
            activity_date=_format_activity_date(result.start_time),
            activity_type=normalise_activity_type(result.activity_type),
            duration=_format_duration_hms(result.duration_s),
            average_hr=round(result.average_hr, 1) if result.average_hr is not None else None,
            raw_max_hr=result.raw_max_hr,
            analysed_max_hr=result.analysed_max_hr,
            hrmax_10s=round(result.hrmax_10s, 1) if result.hrmax_10s is not None else None,
            hrmax_30s=round(result.hrmax_30s, 1) if result.hrmax_30s is not None else None,
            hrmax_60s=round(result.hrmax_60s, 1) if result.hrmax_60s is not None else None,
            hrmax_candidate=round(result.hrmax_candidate, 1) if result.hrmax_candidate is not None else None,
            hrmax_confidence=result.hrmax_confidence,
            hrmax_reason=result.hrmax_reason,
            best_30m_hr=round(result.best30_hr, 1) if result.best30_hr is not None else None,
            best_60m_hr=round(result.best60_hr, 1) if result.best60_hr is not None else None,
            best_90m_hr=round(result.best90_hr, 1) if result.best90_hr is not None else None,
            best_2h_hr=round(sustained2h.avg_hr, 1) if sustained2h is not None else None,
            best_2h_moving_fraction=round(sustained2h.moving_fraction, 4) if sustained2h is not None else None,
            best_2h_hr_p10=round(sustained2h.hr_p10, 1) if sustained2h is not None else None,
            best_2h_hr_p90=round(sustained2h.hr_p90, 1) if sustained2h is not None else None,
            best_4h_hr=round(sustained4h.avg_hr, 1) if sustained4h is not None else None,
            best_4h_moving_fraction=round(sustained4h.moving_fraction, 4) if sustained4h is not None else None,
            best_4h_hr_p10=round(sustained4h.hr_p10, 1) if sustained4h is not None else None,
            best_4h_hr_p90=round(sustained4h.hr_p90, 1) if sustained4h is not None else None,
            vam_15=round(result.vam15.vam, 1) if result.vam15 is not None else None,
            vam_30=round(result.vam30.vam, 1) if result.vam30 is not None else None,
            vam_60=round(result.vam60.vam, 1) if result.vam60 is not None else None,
            vam_retention_pct=round(result.vam_retention_pct, 1)
                if result.vam_retention_pct is not None else None,
            vam_comparison=result.vam_comparison_text,
            time_85pct_seconds=round(result.time85_s, 1) if result.time85_s is not None else None,
            time_90pct_seconds=round(result.time90_s, 1) if result.time90_s is not None else None,
            zone1_seconds=round(result.zone1_s, 1) if result.zone1_s is not None else None,
            zone2_seconds=round(result.zone2_s, 1) if result.zone2_s is not None else None,
            zone3_seconds=round(result.zone3_s, 1) if result.zone3_s is not None else None,
            zone_total_seconds=round(result.zone_total_s, 1) if result.zone_total_s is not None else None,
            active_zone1_seconds=round(result.active_zone1_s, 1) if result.active_zone1_s is not None else None,
            active_zone2_seconds=round(result.active_zone2_s, 1) if result.active_zone2_s is not None else None,
            active_zone3_seconds=round(result.active_zone3_s, 1) if result.active_zone3_s is not None else None,
            active_zone_total_seconds=round(result.active_zone_total_s, 1) if result.active_zone_total_s is not None else None,
            active_zone1_pct=round(100.0*result.active_zone1_s/result.active_zone_total_s, 1) if result.active_zone_total_s else None,
            active_zone2_pct=round(100.0*result.active_zone2_s/result.active_zone_total_s, 1) if result.active_zone_total_s else None,
            active_zone3_pct=round(100.0*result.active_zone3_s/result.active_zone_total_s, 1) if result.active_zone_total_s else None,
            zone1_pct=round(100.0*result.zone1_s/result.zone_total_s, 1) if result.zone_total_s else None,
            zone2_pct=round(100.0*result.zone2_s/result.zone_total_s, 1) if result.zone_total_s else None,
            zone3_pct=round(100.0*result.zone3_s/result.zone_total_s, 1) if result.zone_total_s else None,
            hard_block_threshold_bpm=round(result.detection_threshold, 1) if result.detection_threshold is not None else None,
            hard_block_count=len(result.blocks),
            hard_blocks=_serialize_hard_blocks(result),
            hard_block_gaps=_serialize_hard_block_gaps(result),
            interval_count=result.interval_summary.count if result.interval_summary is not None else None,
            interval_work_total=_format_duration_hms(result.interval_summary.work_total_s) if result.interval_summary is not None else None,
            interval_work_median=_format_duration_hms(result.interval_summary.work_median_s) if result.interval_summary is not None else None,
            interval_work_avg_hr=round(result.interval_summary.work_avg_hr, 1) if result.interval_summary is not None else None,
            interval_work_max_hr=result.interval_summary.work_max_hr if result.interval_summary is not None else None,
            interval_recovery_median=_format_duration_hms(result.interval_summary.recovery_median_s) if result.interval_summary is not None and result.interval_summary.recovery_median_s is not None else None,
            interval_recovery_avg_hr=round(result.interval_summary.recovery_avg_hr, 1) if result.interval_summary is not None and result.interval_summary.recovery_avg_hr is not None else None,
            interval_work_durations=_format_duration_list(result.interval_summary.work_durations_s) if result.interval_summary is not None else None,
            interval_work_avg_hrs=_format_number_list(result.interval_summary.work_avg_hrs, 1) if result.interval_summary is not None else None,
            interval_work_max_hrs=_format_number_list(result.interval_summary.work_max_hrs, 0) if result.interval_summary is not None else None,
            interval_recovery_durations=_format_duration_list(result.interval_summary.recovery_durations_s) if result.interval_summary is not None else None,
            interval_recovery_avg_hrs=_format_number_list(result.interval_summary.recovery_avg_hrs, 1) if result.interval_summary is not None else None,
            interval_summary=_format_interval_summary(result.interval_summary),
            overall_ride=result.overall,
            key_effort=result.key_effort,
            classification=result.classification,
            confidence=result.confidence,
            lt2_low=result.lt2_low,
            lt2_high=result.lt2_high,
            lt2_evidence=result.lt2_evidence,
            lt2_reason=result.lt2_reason,
            lt2_clue=result.lt2_clue,
            hr_artefact=bool(result.artefact_intervals),
            excluded_hr_samples=result.excluded_hr_samples,
            distance_km=round(result.distance_m/1000.0, 2),
            elevation_gain_m=round(result.elevation_gain_m, 0) if result.elevation_gain_m is not None else None,
            has_hr=result.has_hr,
            has_elevation=result.has_elevation,
            has_gps=result.has_gps,
            has_power=result.has_power,
            status="ok",
        )
    except Exception as exc:
        return TrainingSummary(
            filename=path.name, activity_date=None, activity_type=None,
            duration=None, average_hr=None, raw_max_hr=None,
            analysed_max_hr=None, hrmax_10s=None, hrmax_30s=None, hrmax_60s=None,
            hrmax_candidate=None, hrmax_confidence=None, hrmax_reason=None,
            best_30m_hr=None, best_60m_hr=None, best_90m_hr=None, best_2h_hr=None,
            best_2h_moving_fraction=None, best_2h_hr_p10=None, best_2h_hr_p90=None,
            best_4h_hr=None, best_4h_moving_fraction=None, best_4h_hr_p10=None,
            best_4h_hr_p90=None,
            vam_15=None, vam_30=None, vam_60=None, vam_retention_pct=None,
            vam_comparison=None, time_85pct_seconds=None,
            time_90pct_seconds=None, zone1_seconds=None, zone2_seconds=None, zone3_seconds=None, zone_total_seconds=None, active_zone1_seconds=None, active_zone2_seconds=None, active_zone3_seconds=None, active_zone_total_seconds=None, active_zone1_pct=None, active_zone2_pct=None, active_zone3_pct=None, zone1_pct=None, zone2_pct=None, zone3_pct=None, hard_block_threshold_bpm=None, hard_block_count=0,
            hard_blocks=[], hard_block_gaps=[], interval_count=None, interval_work_total=None,
            interval_work_median=None, interval_work_avg_hr=None, interval_work_max_hr=None,
            interval_recovery_median=None, interval_recovery_avg_hr=None,
            interval_work_durations=None, interval_work_avg_hrs=None, interval_work_max_hrs=None,
            interval_recovery_durations=None, interval_recovery_avg_hrs=None, interval_summary=None,
            overall_ride=None, key_effort=None,
            classification=None, confidence=None, lt2_low=None, lt2_high=None,
            lt2_evidence=None, lt2_reason=None, lt2_clue=None,
            hr_artefact=False, excluded_hr_samples=0, distance_km=None, elevation_gain_m=None,
            has_hr=False, has_elevation=False, has_gps=False, has_power=False,
            status="error", error=str(exc),
        )
