#!/usr/bin/env python3
"""
Training-session analyser.


Main ideas
----------
V7 changes:
* The V6 analysis is exposed through analyze_activity(), so batch processing
  can import exactly the same logic instead of duplicating it.
* Single-file command-line output remains compatible with V6.
* Numerical LT2 still requires credible hard 60-minute evidence.
* VAM same-climb logic and descent-HR artefact filtering are unchanged.

1. Physiological effort and terrain are separate.
2. Repeated HR blocks are not automatically "intervals":
   gaps are examined using movement, stopping, gradient and HR recovery.
3. Stops/easing inside one climb can be merged into an interrupted sustained effort.
4. Interval sessions never generate a direct LT2 estimate.
5. LT2 evidence is graded:
      strong   -> sustained hard effort with useful 30m + 60m HR
      moderate -> sustained ~25-40m hard effort with useful 30m HR
6. 15m/30m VAM is reported, but the durability comparison is only interpreted
   when the windows plausibly belong to the same sustained climb.
7. High HR occurring during fast descending can be flagged as suspicious.
8. A 2-hour HR value is reported only as an aerobic/LT1 clue when the window is
   highly continuous; it is never called LT1 directly.

This remains a heuristic analyser. HR-only files cannot directly measure LT1/LT2.

Examples
--------
python3 analyze_training.py ride.gpx --hrmax 184
python3 analyze_training.py ride.gpx --hrmax 184 --lt2 162
"""

from __future__ import annotations

import argparse
import csv
import gzip
import io
import math
import shutil
import sys
import xml.etree.ElementTree as ET
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from statistics import mean, median



# ---------------------------------------------------------------------------
# Optional single-file Strava metadata update
# ---------------------------------------------------------------------------

def _normalise_export_filename(value: str | None) -> str | None:
    """Return the basename used to match a Strava activities.csv row."""
    if not value:
        return None
    text = str(value).strip().replace("\\", "/")
    return Path(text).name or None


def _strava_activity_type(activity_type: str | None) -> str:
    """Map the analyser's normalised sport names to common Strava labels."""
    mapping = {
        "cycling": "Ride",
        "running": "Run",
        "walking": "Walk",
        "hiking": "Hike",
        "skiing": "NordicSki",
        "roller skiing": "RollerSki",
    }
    if not activity_type:
        return ""
    return mapping.get(activity_type.strip().lower(), activity_type)


def _strava_date_string(dt: datetime) -> str:
    """Format a timestamp like Strava's export metadata."""
    hour = dt.hour % 12 or 12
    ampm = "AM" if dt.hour < 12 else "PM"
    return f"{dt.strftime('%b')} {dt.day}, {dt.year}, {hour}:{dt.minute:02d}:{dt.second:02d} {ampm}"


def resolve_single_activity_csv(activity_path: Path, explicit: Path | None) -> Path | None:
    """Find activities.csv for a single activity.

    With the normal Strava layout ``Strava/activities/file.fit``, the metadata
    file is ``Strava/activities.csv``. An explicit path always wins.
    """
    if explicit is not None:
        return explicit.expanduser()

    activity_path = activity_path.expanduser().resolve()
    candidates = [
        activity_path.parent.parent / "activities.csv",
        activity_path.parent / "activities.csv",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def append_single_activity_metadata(path: Path, analysis: "ActivityAnalysis") -> bool:
    """Append one minimal row to a Strava activities.csv if it is absent.

    The original column order and existing rows are preserved. Only values that
    can be reconstructed reliably from the local activity file are populated;
    Strava-only fields such as activity ID, gear and calories remain blank.
    A one-time ``activities.csv.bak`` backup is created before the first append.

    Returns True when a new row was appended, False when it was already present.
    """
    if not path.is_file():
        raise FileNotFoundError(f"activities.csv not found: {path}")

    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        existing = {
            _normalise_export_filename(row.get("Filename"))
            for row in reader
            if row.get("Filename")
        }

    required = {
        "Filename", "Activity Date", "Activity Type", "Elapsed Time",
        "Moving Time", "Distance", "Elevation Gain",
    }
    missing = sorted(required - set(fieldnames))
    if missing:
        raise ValueError(
            "activities.csv cannot be updated; missing columns: " + ", ".join(missing)
        )

    filename = analysis.path.name
    if filename in existing:
        return False

    record = {name: "" for name in fieldnames}
    record["Filename"] = f"activities/{filename}"
    record["Activity Date"] = _strava_date_string(analysis.start_time)
    record["Activity Type"] = _strava_activity_type(analysis.activity_type)
    duration_s = int(round(analysis.duration_s))
    record["Elapsed Time"] = str(duration_s)
    record["Moving Time"] = str(duration_s)
    record["Distance"] = f"{analysis.distance_m:.1f}"
    if analysis.elevation_gain_m is not None:
        record["Elevation Gain"] = f"{analysis.elevation_gain_m:.1f}"
    if "Activity Name" in record:
        # Remove both compression and activity-format suffixes where possible.
        name = filename
        if name.lower().endswith(".gz"):
            name = name[:-3]
        for suffix in (".gpx", ".tcx", ".fit"):
            if name.lower().endswith(suffix):
                name = name[:-len(suffix)]
                break
        record["Activity Name"] = name

    backup = path.with_suffix(path.suffix + ".bak")
    if not backup.exists():
        shutil.copy2(path, backup)

    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writerow(record)
    return True

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Sample:
    timestamp: datetime
    heart_rate: int | None = None
    elevation: float | None = None
    lat: float | None = None
    lon: float | None = None
    distance_m: float | None = None


@dataclass
class Block:
    start: datetime
    end: datetime
    avg_hr: float
    max_hr: int

    @property
    def duration_s(self) -> float:
        return (self.end - self.start).total_seconds()


@dataclass
class GapInfo:
    start: datetime
    end: datetime
    duration_s: float
    distance_m: float
    elev_gain_m: float | None
    avg_hr: float | None
    min_hr: int | None
    stopped_fraction: float
    moving_speed_kmh: float | None
    gradient_pct: float | None
    kind: str


@dataclass
class EffortGroup:
    blocks: list[Block]
    gaps: list[GapInfo]
    start: datetime
    end: datetime
    duration_s: float
    work_duration_s: float
    avg_work_hr: float
    max_hr: int
    interrupted: bool


@dataclass
class IntervalSummary:
    count: int
    work_durations_s: list[float]
    work_avg_hrs: list[float]
    work_max_hrs: list[int]
    recovery_durations_s: list[float]
    recovery_avg_hrs: list[float | None]
    work_total_s: float
    work_median_s: float
    work_avg_hr: float
    work_max_hr: int
    recovery_median_s: float | None
    recovery_avg_hr: float | None


@dataclass
class VamResult:
    vam: float
    gain_m: float
    start: datetime
    end: datetime


@dataclass
class AerobicWindow:
    avg_hr: float
    start: datetime
    end: datetime
    moving_fraction: float
    stopped_fraction: float
    descending_fraction: float
    hr_p10: float
    hr_p90: float


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def fmt_time(seconds: float | None) -> str:
    if seconds is None:
        return "-"
    seconds = int(round(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def fmt_clock(ts: datetime | None) -> str:
    return ts.strftime("%H:%M:%S") if ts is not None else "-"


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def parse_timestamp(text: str) -> datetime:
    return datetime.fromisoformat(text.strip().replace("Z", "+00:00"))


def detect_format(path: Path) -> tuple[str, bool]:
    name = path.name.lower()
    for fmt in ("gpx", "tcx", "fit"):
        if name.endswith(f".{fmt}.gz"):
            return fmt, True
        if name.endswith(f".{fmt}"):
            return fmt, False
    raise ValueError(f"Unsupported file: {path.name}")


def open_binary(path: Path, compressed: bool):
    return gzip.open(path, "rb") if compressed else path.open("rb")


def clean_xml_bytes(data: bytes) -> bytes:
    return data.lstrip(b"\xef\xbb\xbf \t\r\n")


def percentile(values, p):
    if not values:
        return None
    values = sorted(values)
    if len(values) == 1:
        return float(values[0])
    pos = (len(values) - 1) * p
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return float(values[lo])
    frac = pos - lo
    return values[lo] * (1-frac) + values[hi] * frac


def haversine_m(a: Sample, b: Sample) -> float:
    if None in (a.lat, a.lon, b.lat, b.lon):
        return 0.0
    r = 6371000.0
    lat1 = math.radians(a.lat)
    lat2 = math.radians(b.lat)
    dlat = lat2 - lat1
    dlon = math.radians(b.lon - a.lon)
    x = math.sin(dlat/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
    return 2*r*math.asin(min(1.0, math.sqrt(x)))


def segment_distance_m(a: Sample, b: Sample) -> float:
    if (
        a.distance_m is not None and b.distance_m is not None
        and b.distance_m >= a.distance_m
    ):
        return b.distance_m - a.distance_m
    return haversine_m(a, b)


def samples_between(samples, start, end):
    return [s for s in samples if start <= s.timestamp <= end]


# ---------------------------------------------------------------------------
# Readers
# ---------------------------------------------------------------------------

def parse_gpx(path: Path, compressed: bool):
    with open_binary(path, compressed) as f:
        root = ET.fromstring(clean_xml_bytes(f.read()))

    activity_type = None
    samples = []

    for element in root.iter():
        name = local_name(element.tag)

        if name == "type" and activity_type is None and element.text:
            activity_type = element.text.strip()

        if name != "trkpt":
            continue

        try:
            lat = float(element.attrib["lat"])
            lon = float(element.attrib["lon"])
        except (KeyError, ValueError):
            lat = lon = None

        timestamp = None
        elevation = None
        heart_rate = None

        for child in element.iter():
            cname = local_name(child.tag)

            if cname == "time" and child.text:
                try:
                    timestamp = parse_timestamp(child.text)
                except ValueError:
                    pass
            elif cname == "ele" and child.text:
                try:
                    elevation = float(child.text.strip())
                except ValueError:
                    pass
            elif cname in {"hr", "heartrate", "heart_rate"} and child.text:
                try:
                    heart_rate = int(round(float(child.text.strip())))
                except ValueError:
                    pass

        if timestamp is not None:
            samples.append(Sample(timestamp, heart_rate, elevation, lat, lon, None))

    return activity_type, sorted(samples, key=lambda s: s.timestamp)


def parse_tcx(path: Path, compressed: bool):
    with open_binary(path, compressed) as f:
        root = ET.fromstring(clean_xml_bytes(f.read()))

    activity_type = None
    samples = []

    for element in root.iter():
        name = local_name(element.tag)

        if name == "activity" and activity_type is None:
            activity_type = element.attrib.get("Sport")

        if name != "trackpoint":
            continue

        timestamp = elevation = distance_m = lat = lon = heart_rate = None

        for child in element.iter():
            cname = local_name(child.tag)

            if cname == "time" and child.text:
                try:
                    timestamp = parse_timestamp(child.text)
                except ValueError:
                    pass
            elif cname == "altitudemeters" and child.text:
                try:
                    elevation = float(child.text.strip())
                except ValueError:
                    pass
            elif cname == "distancemeters" and child.text:
                try:
                    distance_m = float(child.text.strip())
                except ValueError:
                    pass
            elif cname == "latitudedegrees" and child.text:
                try:
                    lat = float(child.text.strip())
                except ValueError:
                    pass
            elif cname == "longitudedegrees" and child.text:
                try:
                    lon = float(child.text.strip())
                except ValueError:
                    pass
            elif cname == "heartratebpm":
                for desc in child.iter():
                    if local_name(desc.tag) == "value" and desc.text:
                        try:
                            heart_rate = int(round(float(desc.text.strip())))
                        except ValueError:
                            pass
                        break

        if timestamp is not None:
            samples.append(Sample(
                timestamp, heart_rate, elevation, lat, lon, distance_m
            ))

    return activity_type, sorted(samples, key=lambda s: s.timestamp)


def semicircles_to_degrees(v):
    return float(v) * (180.0 / 2**31)


def parse_fit(path: Path, compressed: bool):
    try:
        from fitparse import FitFile
    except ImportError as exc:
        raise RuntimeError(
            "FIT support requires fitparse: python3 -m pip install fitparse"
        ) from exc

    with open_binary(path, compressed) as f:
        fit = FitFile(io.BytesIO(f.read()))

    activity_type = None
    for msg in fit.get_messages("session"):
        sport = msg.get_value("sport")
        if sport is not None:
            activity_type = str(sport)
            break

    samples = []
    for msg in fit.get_messages("record"):
        ts = msg.get_value("timestamp")
        if not isinstance(ts, datetime):
            continue

        hr = msg.get_value("heart_rate")
        elev = msg.get_value("enhanced_altitude")
        if elev is None:
            elev = msg.get_value("altitude")
        dist = msg.get_value("distance")

        lat_raw = msg.get_value("position_lat")
        lon_raw = msg.get_value("position_long")

        try:
            hr = int(round(float(hr))) if hr is not None else None
        except (TypeError, ValueError):
            hr = None
        try:
            elev = float(elev) if elev is not None else None
        except (TypeError, ValueError):
            elev = None
        try:
            dist = float(dist) if dist is not None else None
        except (TypeError, ValueError):
            dist = None
        try:
            lat = semicircles_to_degrees(lat_raw) if lat_raw is not None else None
            lon = semicircles_to_degrees(lon_raw) if lon_raw is not None else None
        except (TypeError, ValueError):
            lat = lon = None

        samples.append(Sample(ts, hr, elev, lat, lon, dist))

    return activity_type, sorted(samples, key=lambda s: s.timestamp)


def read_samples(path: Path):
    fmt, compressed = detect_format(path)
    if fmt == "gpx":
        return parse_gpx(path, compressed)
    if fmt == "tcx":
        return parse_tcx(path, compressed)
    if fmt == "fit":
        return parse_fit(path, compressed)
    raise ValueError(fmt)


# ---------------------------------------------------------------------------
# Basic HR analysis
# ---------------------------------------------------------------------------

def hr_samples(samples, min_hr, max_hr):
    return [
        s for s in samples
        if s.heart_rate is not None and min_hr <= s.heart_rate <= max_hr
    ]


def split_sections(samples, max_gap_s=5.0):
    if not samples:
        return []
    sections = [[samples[0]]]
    for a, b in zip(samples, samples[1:]):
        dt = (b.timestamp-a.timestamp).total_seconds()
        if dt <= 0 or dt > max_gap_s:
            sections.append([b])
        else:
            sections[-1].append(b)
    return sections


def best_hr_average(samples, window_s, max_gap_s=5.0):
    best = None
    for section in split_sections(samples, max_gap_s):
        q = deque()
        total = 0.0
        for s in section:
            q.append(s)
            total += s.heart_rate
            while q and (s.timestamp-q[0].timestamp).total_seconds() > window_s:
                old = q.popleft()
                total -= old.heart_rate
            if len(q) < 2:
                continue
            span = (q[-1].timestamp-q[0].timestamp).total_seconds()
            if span >= 0.95*window_s:
                avg = total/len(q)
                if best is None or avg > best:
                    best = avg
    return best


def rolling_hr(samples, window_s=30):
    out = []
    q = deque()
    total = 0.0
    for s in samples:
        q.append(s)
        total += s.heart_rate
        while q and (s.timestamp-q[0].timestamp).total_seconds() > window_s:
            old = q.popleft()
            total -= old.heart_rate
        out.append((s.timestamp, total/len(q)))
    return out


def detect_hard_blocks(samples, threshold, min_block_s=240, bridge_gap_s=90):
    smooth = rolling_hr(samples, 30)
    raw_blocks = []
    start = last_above = None

    for i, (ts, hr) in enumerate(smooth):
        if hr >= threshold:
            if start is None:
                start = i
            last_above = i
        elif start is not None and last_above is not None:
            gap = (ts-smooth[last_above][0]).total_seconds()
            if gap > bridge_gap_s:
                raw_blocks.append((start, last_above))
                start = last_above = None

    if start is not None and last_above is not None:
        raw_blocks.append((start, last_above))

    blocks = []
    for a, b in raw_blocks:
        st = smooth[a][0]
        en = smooth[b][0]
        if (en-st).total_seconds() < min_block_s:
            continue
        raw = samples_between(samples, st, en)
        if raw:
            blocks.append(Block(
                st, en,
                mean(s.heart_rate for s in raw),
                max(s.heart_rate for s in raw),
            ))
    return blocks


def time_above(samples, threshold):
    total = 0.0
    for a, b in zip(samples, samples[1:]):
        dt = (b.timestamp-a.timestamp).total_seconds()
        if 0 < dt <= 10 and a.heart_rate >= threshold:
            total += dt
    return total


# ---------------------------------------------------------------------------
# Movement / gap analysis
# ---------------------------------------------------------------------------

def analyse_gap(all_samples, hr_samples_, prev_block, next_block, threshold):
    raw = samples_between(all_samples, prev_block.end, next_block.start)
    hrs = samples_between(hr_samples_, prev_block.end, next_block.start)

    duration = (next_block.start-prev_block.end).total_seconds()
    if len(raw) < 2 or duration <= 0:
        return GapInfo(
            prev_block.end, next_block.start, duration, 0, None,
            mean(s.heart_rate for s in hrs) if hrs else None,
            min((s.heart_rate for s in hrs), default=None),
            1.0, None, None, "stop / data gap"
        )

    distance = 0.0
    moving_time = 0.0
    stopped_time = 0.0

    for a, b in zip(raw, raw[1:]):
        dt = (b.timestamp-a.timestamp).total_seconds()
        if dt <= 0 or dt > 30:
            continue
        d = segment_distance_m(a, b)
        distance += d
        speed = (d/dt)*3.6
        if speed < 2.0:
            stopped_time += dt
        else:
            moving_time += dt

    observed = moving_time + stopped_time
    stopped_fraction = stopped_time/observed if observed > 0 else 1.0
    moving_speed = (distance/moving_time)*3.6 if moving_time > 0 else None

    elev = [s.elevation for s in raw if s.elevation is not None]
    elev_gain = elev[-1]-elev[0] if len(elev) >= 2 else None
    gradient = (
        100.0*elev_gain/distance
        if elev_gain is not None and distance >= 50
        else None
    )

    avg_hr = mean(s.heart_rate for s in hrs) if hrs else None
    min_hr = min((s.heart_rate for s in hrs), default=None)

    # Classification order matters.
    if stopped_fraction >= 0.30 or (duration >= 45 and distance < 100):
        kind = "stop"
    elif elev_gain is not None and elev_gain < -15:
        kind = "descent / terrain recovery"
    elif gradient is not None and gradient >= 2.0:
        if avg_hr is not None and avg_hr >= threshold-8:
            kind = "easing on climb"
        else:
            kind = "active recovery on climb"
    elif avg_hr is not None and avg_hr <= threshold-10 and stopped_fraction < 0.15:
        kind = "active recovery"
    else:
        kind = "terrain/easing"

    return GapInfo(
        prev_block.end, next_block.start, duration, distance, elev_gain,
        avg_hr, min_hr, stopped_fraction, moving_speed, gradient, kind
    )


def build_effort_groups(blocks, all_samples, hrs, threshold):
    if not blocks:
        return [], []

    gaps = [
        analyse_gap(all_samples, hrs, a, b, threshold)
        for a, b in zip(blocks, blocks[1:])
    ]

    groups = []
    cur_blocks = [blocks[0]]
    cur_gaps = []

    for gap, next_block in zip(gaps, blocks[1:]):
        # Merge when interruption looks like a stop or brief easing rather than
        # a deliberately ridden recovery.
        current_work_s = sum(b.duration_s for b in cur_blocks)

        merge = (
            gap.duration_s <= 8*60
            and gap.kind in {"stop", "easing on climb", "terrain/easing"}
        )

        # Once a genuinely long hard climbing effort is already established,
        # a short active-recovery-looking patch on the same climb is more
        # likely to be easing/feeding/photo terrain than a new interval set.
        # This does NOT merge classic 4x8 recoveries because no single current
        # group has yet accumulated ~20 minutes of hard work.
        if (
            not merge
            and gap.duration_s <= 5*60
            and gap.kind == "active recovery on climb"
            and current_work_s >= 20*60
        ):
            merge = True

        if merge:
            cur_gaps.append(gap)
            cur_blocks.append(next_block)
        else:
            groups.append(make_effort_group(cur_blocks, cur_gaps))
            cur_blocks = [next_block]
            cur_gaps = []

    groups.append(make_effort_group(cur_blocks, cur_gaps))
    return groups, gaps


def make_effort_group(blocks, gaps):
    start = blocks[0].start
    end = blocks[-1].end
    work_s = sum(b.duration_s for b in blocks)
    weighted_hr = (
        sum(b.avg_hr*b.duration_s for b in blocks)/work_s
        if work_s > 0 else blocks[0].avg_hr
    )
    return EffortGroup(
        blocks=blocks,
        gaps=gaps,
        start=start,
        end=end,
        duration_s=(end-start).total_seconds(),
        work_duration_s=work_s,
        avg_work_hr=weighted_hr,
        max_hr=max(b.max_hr for b in blocks),
        interrupted=bool(gaps),
    )


# ---------------------------------------------------------------------------
# Descending HR artefact detection
# ---------------------------------------------------------------------------

def suspicious_descent_hr(all_samples, hrs, hrmax):
    """
    Flag high-HR samples during obvious fast descending.

    V5 subsequently clusters sustained flags into artefact intervals. Isolated
    points remain warnings only and are not removed automatically.
    """
    flags = []
    threshold = max(0.92*hrmax, hrmax-15)

    for i in range(1, len(all_samples)):
        a = all_samples[i-1]
        b = all_samples[i]
        if b.heart_rate is None or b.heart_rate < threshold:
            continue

        dt = (b.timestamp-a.timestamp).total_seconds()
        if dt <= 0 or dt > 10:
            continue

        d = segment_distance_m(a, b)
        speed = d/dt*3.6

        if (
            speed >= 30
            and a.elevation is not None and b.elevation is not None
            and b.elevation < a.elevation-0.5
        ):
            flags.append(b)

    return flags


def descent_artefact_intervals(flags, cluster_gap_s=12, pad_s=150):
    """
    Convert repeated suspicious descending HR samples into exclusion intervals.

    A cluster is considered strong enough for exclusion when it contains at
    least five flagged samples or lasts at least 20 seconds. This avoids
    deleting a genuine isolated high-HR point merely because the rider happened
    to be descending at that instant.
    """
    if not flags:
        return []

    flags = sorted(flags, key=lambda s: s.timestamp)
    clusters = [[flags[0]]]

    for s in flags[1:]:
        if (s.timestamp-clusters[-1][-1].timestamp).total_seconds() <= cluster_gap_s:
            clusters[-1].append(s)
        else:
            clusters.append([s])

    from datetime import timedelta

    intervals = []
    for cluster in clusters:
        span = (cluster[-1].timestamp-cluster[0].timestamp).total_seconds()

        if len(cluster) < 5 and span < 20:
            continue

        intervals.append((
            cluster[0].timestamp-timedelta(seconds=pad_s),
            cluster[-1].timestamp+timedelta(seconds=pad_s),
        ))

    return intervals


def timestamp_in_intervals(ts, intervals):
    return any(start <= ts <= end for start, end in intervals)


def exclude_artefact_hr_samples(hrs, intervals):
    if not intervals:
        return list(hrs)

    return [
        s for s in hrs
        if not timestamp_in_intervals(s.timestamp, intervals)
    ]


# ---------------------------------------------------------------------------
# VAM
# ---------------------------------------------------------------------------

def median_filter_elevation(samples, radius=2):
    elev = [s.elevation for s in samples]
    out = []
    for i, s in enumerate(samples):
        if s.elevation is None:
            out.append(s)
            continue
        vals = [
            elev[j]
            for j in range(max(0, i-radius), min(len(samples), i+radius+1))
            if elev[j] is not None
        ]
        vals.sort()
        med = vals[len(vals)//2]
        out.append(Sample(
            s.timestamp, s.heart_rate, med, s.lat, s.lon, s.distance_m
        ))
    return out


def best_vam(samples, window_s, minimum_gain_m, max_gap_s=10.0):
    elev = [s for s in samples if s.elevation is not None]
    if len(elev) < 2:
        return None

    elev = median_filter_elevation(elev, 2)
    best = None

    for section in split_sections(elev, max_gap_s):
        left = 0
        for right in range(1, len(section)):
            while (
                left < right
                and (section[right].timestamp-section[left].timestamp).total_seconds()
                > window_s
            ):
                left += 1

            candidates = [left] + ([left-1] if left > 0 else [])
            for start_idx in candidates:
                a = section[start_idx]
                b = section[right]
                elapsed = (b.timestamp-a.timestamp).total_seconds()

                if elapsed < 0.95*window_s or elapsed > 1.05*window_s:
                    continue

                gain = b.elevation-a.elevation
                if gain < minimum_gain_m:
                    continue

                vam = gain*3600/elapsed
                if best is None or vam > best.vam:
                    best = VamResult(vam, gain, a.timestamp, b.timestamp)

    return best


def _elevation_series(samples):
    """Return elevation samples with a modest median filter applied."""
    elev = [s for s in samples if s.elevation is not None]
    if not elev:
        return []
    return median_filter_elevation(elev, radius=3)


def _segment_distance_between(samples):
    total = 0.0
    for a, b in zip(samples, samples[1:]):
        dt = (b.timestamp-a.timestamp).total_seconds()
        if 0 < dt <= 30:
            total += segment_distance_m(a, b)
    return total


def find_broad_climb_segment(all_samples, target_start, target_end):
    """
    Find the broader net-ascent segment containing a VAM window.

    Real climbs need not rise monotonically: flatter ramps, tiny downhill
    sections and GPS altitude noise are tolerated.
    """
    series = _elevation_series(all_samples)
    if len(series) < 3:
        return None

    inside = [
        i for i, s in enumerate(series)
        if target_start <= s.timestamp <= target_end
    ]
    if not inside:
        return None

    left = inside[0]
    right = inside[-1]

    CHUNK_S = 180
    MAX_DROP_M = 45.0
    FLAT_NET_M = 8.0
    MAX_FLAT_CHUNKS = 2

    flat_chunks = 0
    while left > 0:
        anchor = series[left].timestamp
        j = left - 1
        while j > 0 and (anchor-series[j].timestamp).total_seconds() < CHUNK_S:
            j -= 1

        chunk = series[j:left+1]
        if len(chunk) < 2:
            break

        net = chunk[-1].elevation-chunk[0].elevation
        peak = max(s.elevation for s in chunk)
        drop = peak-chunk[-1].elevation

        if net < -20 or drop > MAX_DROP_M:
            break

        if net < FLAT_NET_M:
            flat_chunks += 1
            if flat_chunks > MAX_FLAT_CHUNKS:
                break
        else:
            flat_chunks = 0

        left = j

    flat_chunks = 0
    while right < len(series)-1:
        anchor = series[right].timestamp
        j = right + 1
        while j < len(series)-1 and (series[j].timestamp-anchor).total_seconds() < CHUNK_S:
            j += 1

        chunk = series[right:j+1]
        if len(chunk) < 2:
            break

        net = chunk[-1].elevation-chunk[0].elevation
        peak = max(s.elevation for s in chunk)
        drop_from_peak = peak-chunk[-1].elevation

        if net < -20 or drop_from_peak > MAX_DROP_M:
            break

        if net < FLAT_NET_M:
            flat_chunks += 1
            if flat_chunks > MAX_FLAT_CHUNKS:
                break
        else:
            flat_chunks = 0

        right = j

    segment = series[left:right+1]
    if len(segment) < 2:
        return None

    net_gain = segment[-1].elevation-segment[0].elevation
    distance = _segment_distance_between(segment)

    return segment[0].timestamp, segment[-1].timestamp, net_gain, distance


def same_continuous_climb(v15, v30, all_samples):
    """
    Determine whether the best 15m and 30m VAM windows belong to the same
    broader climb, even if the optimum windows only partly overlap.
    """
    if v15 is None or v30 is None:
        return False, None

    seg15 = find_broad_climb_segment(all_samples, v15.start, v15.end)
    seg30 = find_broad_climb_segment(all_samples, v30.start, v30.end)

    if seg15 is None or seg30 is None:
        return False, None

    s15, e15, gain15, dist15 = seg15
    s30, e30, gain30, dist30 = seg30

    overlap_s = max(
        0.0,
        (min(e15, e30)-max(s15, s30)).total_seconds()
    )

    same = overlap_s >= 10*60

    if not same:
        early_end = min(v15.end, v30.end)
        late_start = max(v15.start, v30.start)

        if early_end <= late_start:
            bridge = _elevation_series(
                samples_between(all_samples, early_end, late_start)
            )
            if len(bridge) >= 2:
                bridge_net = bridge[-1].elevation-bridge[0].elevation
                bridge_peak = max(s.elevation for s in bridge)
                bridge_drop = bridge_peak-bridge[-1].elevation

                if bridge_net >= -10 and bridge_drop <= 35:
                    same = True

    detail = {
        "segment15": seg15,
        "segment30": seg30,
        "overlap_s": overlap_s,
    }

    return same, detail


def vam_comparison(v15, v30, primary_classification, all_samples):
    if v15 is None or v30 is None:
        return "not available"

    retention = v30.vam/v15.vam if v15.vam > 0 else 0

    if "interval" in primary_classification.lower():
        return "not interpreted: interval session"

    same_climb, detail = same_continuous_climb(v15, v30, all_samples)

    if same_climb:
        if retention >= 0.80:
            return "comparable: same sustained climb / climbing segment"
        return "same sustained climb, but 30m includes substantial easier terrain"

    overlap = max(
        0.0,
        (min(v15.end, v30.end)-max(v15.start, v30.start)).total_seconds()
    )
    overlap15 = overlap/(15*60)

    if overlap15 >= 0.75 and retention >= 0.80:
        return "comparable: likely same sustained climb"

    if overlap15 >= 0.75:
        return "same area, but 30m window includes substantial easier terrain"

    return "not directly comparable: different terrain/climbing sections likely"


def terrain_context(samples):
    elev = [s.elevation for s in samples if s.elevation is not None]
    if len(elev) < 2:
        return "unknown"
    rng = max(elev)-min(elev)
    if rng < 50:
        return "mostly flat / gently rolling"
    if rng < 200:
        return "rolling / hilly"
    return "hilly / climbing"


# ---------------------------------------------------------------------------
# 2-hour aerobic / LT1 clue
# ---------------------------------------------------------------------------

def window_quality(samples):
    if len(samples) < 2:
        return None

    moving = stopped = descending = observed = 0.0
    current_stop = 0.0
    max_stop = 0.0

    for a, b in zip(samples, samples[1:]):
        dt = (b.timestamp-a.timestamp).total_seconds()
        if dt <= 0:
            continue

        # A recording/autopause gap can hide a real rest. Treat the whole gap
        # as a stopped episode for the purpose of the longest-stop test.
        if dt > 30:
            max_stop = max(max_stop, dt)
            current_stop = 0.0
            continue

        observed += dt
        d = segment_distance_m(a, b)
        speed = d/dt*3.6

        if speed < 2:
            stopped += dt
            current_stop += dt
            max_stop = max(max_stop, current_stop)
        else:
            moving += dt
            current_stop = 0.0

        if (
            a.elevation is not None and b.elevation is not None
            and b.elevation-a.elevation < -1.0
        ):
            descending += dt

    if observed <= 0:
        return None

    return moving/observed, stopped/observed, descending/observed, max_stop


def best_sustained_hr_window(all_samples, window_s, min_hr, max_hr):
    """Return the highest reasonably continuous long-duration HR window.

    This is intentionally descriptive rather than physiological: it does not
    estimate LT1 or label the effort as aerobic. A window must cover almost
    the requested elapsed time and must not contain a single rest/recording
    gap longer than five minutes. Short photo, water, junction and summit stops
    are allowed, even when several occur within the window. HR spread is
    reported descriptively but is not used as a qualification gate. Descending
    is allowed because long rides naturally include descents and recoveries.
    """
    if not all_samples:
        return None
    q = deque()
    best = None
    last_eval = None

    for s in all_samples:
        q.append(s)
        while q and (s.timestamp-q[0].timestamp).total_seconds() > window_s:
            q.popleft()

        if len(q) < 20:
            continue

        span = (q[-1].timestamp-q[0].timestamp).total_seconds()
        if span < 0.97*window_s:
            continue

        # One candidate per minute is enough for a long-duration observation.
        if last_eval is not None and (s.timestamp-last_eval).total_seconds() < 60:
            continue
        last_eval = s.timestamp

        window = list(q)
        quality = window_quality(window)
        if quality is None:
            continue

        moving_fraction, stopped_fraction, descending_fraction, max_stop_s = quality

        hs = [
            x.heart_rate for x in window
            if x.heart_rate is not None and min_hr <= x.heart_rate <= max_hr
        ]
        if len(hs) < 20:
            continue

        p10 = percentile(hs, 0.10)
        p90 = percentile(hs, 0.90)
        avg = mean(hs)

        if max_stop_s <= 5*60:
            candidate = AerobicWindow(
                avg, window[0].timestamp, window[-1].timestamp,
                moving_fraction, stopped_fraction, descending_fraction,
                p10, p90
            )
            if best is None or candidate.avg_hr > best.avg_hr:
                best = candidate

    return best


# ---------------------------------------------------------------------------
# Classification / LT2
# ---------------------------------------------------------------------------

def overall_ride_character(duration_s, avg_hr, hrmax):
    pct = avg_hr/hrmax
    if pct < 0.68:
        return "easy endurance / recovery"
    if pct < 0.78:
        return "endurance"
    if pct < 0.85:
        return "tempo / moderately hard endurance"
    return "hard / mixed"


def classify_key_effort(groups, gaps, hrmax, lt2):
    """
    Decide whether repeated hard work looks like intervals or one interrupted
    sustained effort.
    """
    if not groups:
        return "none", "high"

    threshold = lt2 if lt2 is not None else 0.87*hrmax

    # A merged group spanning >=25 min is a sustained effort, even if stops
    # briefly interrupted it.
    sustained = [g for g in groups if g.duration_s >= 25*60 and g.work_duration_s >= 18*60]
    if sustained:
        best = max(sustained, key=lambda g: g.work_duration_s)
        if best.avg_work_hr >= threshold:
            return (
                "interrupted sustained threshold effort"
                if best.interrupted else
                "sustained threshold effort",
                "high",
            )
        return "long tempo / sub-threshold effort", "medium"

    # If there are >=3 separate groups and the separating gaps look like active
    # recoveries, classify as intervals.
    hard_groups = [g for g in groups if g.work_duration_s >= 4*60]
    active_recovery_gaps = [
        g for g in gaps
        if g.kind in {"active recovery", "active recovery on climb"}
    ]

    if len(hard_groups) >= 3 and len(active_recovery_gaps) >= 2:
        avg_work = mean(g.avg_work_hr for g in hard_groups)

        if lt2 is not None:
            delta = avg_work-lt2
            if delta >= 7:
                return "very hard intervals", "high"
            if delta >= 3:
                return "supra-threshold intervals", "high"
            return "threshold intervals", "high"

        pct = avg_work/hrmax
        if pct >= 0.91:
            return "very hard intervals", "medium"
        if pct >= 0.88:
            return "supra-threshold intervals", "medium"
        return "threshold intervals", "high"

    # Single shorter hard effort.
    best = max(groups, key=lambda g: g.work_duration_s)
    if best.work_duration_s >= 15*60:
        return "sustained high-tempo / threshold-region effort", "medium"

    return "short hard efforts within ride", "medium"


def summarize_intervals(groups, all_samples, hrs, threshold, classification):
    """
    Preserve the actual HR-detected work/recovery structure for sessions that
    the classifier already regards as intervals.

    Durations are deliberately described as *detected hard-HR blocks*. HR lags
    workload, so these should not be mistaken for exact prescribed/lap times.
    """
    if "interval" not in classification.lower():
        return None

    hard = [g for g in groups if g.work_duration_s >= 4*60]
    if len(hard) < 3:
        return None

    recoveries = [
        analyse_gap(all_samples, hrs, a, b, threshold)
        for a, b in zip(hard, hard[1:])
    ]

    work_durations = [g.work_duration_s for g in hard]
    work_avg_hrs = [g.avg_work_hr for g in hard]
    work_max_hrs = [g.max_hr for g in hard]
    recovery_durations = [g.duration_s for g in recoveries]
    recovery_avg_hrs = [g.avg_hr for g in recoveries]

    work_total = sum(work_durations)
    weighted_work_hr = (
        sum(g.avg_work_hr * g.work_duration_s for g in hard) / work_total
        if work_total > 0 else mean(work_avg_hrs)
    )

    valid_recovery_hr = [
        (g.avg_hr, g.duration_s) for g in recoveries
        if g.avg_hr is not None and g.duration_s > 0
    ]
    recovery_total = sum(d for _, d in valid_recovery_hr)
    weighted_recovery_hr = (
        sum(hr*d for hr, d in valid_recovery_hr) / recovery_total
        if recovery_total > 0 else None
    )

    return IntervalSummary(
        count=len(hard),
        work_durations_s=work_durations,
        work_avg_hrs=work_avg_hrs,
        work_max_hrs=work_max_hrs,
        recovery_durations_s=recovery_durations,
        recovery_avg_hrs=recovery_avg_hrs,
        work_total_s=work_total,
        work_median_s=median(work_durations),
        work_avg_hr=weighted_work_hr,
        work_max_hr=max(work_max_hrs),
        recovery_median_s=median(recovery_durations) if recovery_durations else None,
        recovery_avg_hr=weighted_recovery_hr,
    )


def combined_classification(overall, key_effort):
    if key_effort == "none":
        return overall
    if "interval" in key_effort:
        return key_effort
    if overall in {"easy endurance / recovery", "endurance"}:
        return f"{overall} ride with {key_effort}"
    return key_effort


def estimate_lt2(primary, groups, hrmax, best30, best60, time85):
    """
    V5 rule: a numerical LT2 range requires credible 60-minute evidence.

    A strong 30-minute effort is still useful, but it produces only supporting
    evidence / an upper-side clue rather than a numerical LT2 estimate.
    """
    if "interval" in primary.lower():
        return (
            None, None, "none",
            "interval session - no direct LT2 estimate",
            None,
        )

    floor = 0.82*hrmax
    ceiling = 0.93*hrmax

    hard30 = best30 is not None and floor <= best30 <= ceiling
    hard60 = best60 is not None and floor <= best60 <= ceiling

    sustained = [
        g for g in groups
        if g.duration_s >= 25*60 and g.work_duration_s >= 18*60
    ]

    if not sustained:
        return (
            None, None, "none",
            "no suitable sustained hard effort",
            None,
        )

    bestg = max(sustained, key=lambda g: g.work_duration_s)

    # Strong numerical estimate: useful 30m + 60m values and substantial
    # threshold-region time. The 60m value is the crucial extra evidence.
    if hard30 and hard60 and time85 >= 25*60:
        low = max(floor, min(best60, best30-3))
        high = min(ceiling, min(best30, best60+4))

        if high >= low:
            return (
                round(low,1), round(high,1), "strong",
                "30m + 60m sustained hard effort",
                None,
            )

    # 30m-only evidence: useful clue, never a numerical estimate.
    if hard30 and bestg.work_duration_s >= 20*60:
        if bestg.interrupted:
            return (
                None, None, "moderate",
                "interrupted sustained hard effort; 30m HR is useful evidence "
                "but is not sufficient for a numerical LT2 estimate",
                f"30m HR {best30:.1f} bpm provides supporting threshold evidence",
            )

        return (
            None, None, "moderate",
            "strong 30m sustained effort; no supporting 60m threshold window",
            f"30m HR {best30:.1f} bpm suggests LT2 is probably at or below "
            f"about {round(best30):.0f} bpm",
        )

    return (
        None, None, "low",
        "sustained effort present but insufficient for LT2 estimate",
        None,
    )


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def print_vam(label, v):
    if v is None:
        print(f"{label:<17}-")
    else:
        print(
            f"{label:<17}{v.vam:.0f} m/h  "
            f"(+{v.gain_m:.0f} m net, {fmt_clock(v.start)}-{fmt_clock(v.end)})"
        )



@dataclass
class ActivityAnalysis:
    path: Path
    activity_type: str | None
    start_time: datetime
    end_time: datetime
    duration_s: float
    terrain: str
    raw_average_hr: float | None
    average_hr: float | None
    raw_max_hr: int | None
    analysed_max_hr: int | None
    hrmax_10s: float | None
    hrmax_30s: float | None
    hrmax_60s: float | None
    hrmax_candidate: float | None
    hrmax_confidence: str | None
    hrmax_reason: str | None
    best30_hr: float | None
    best60_hr: float | None
    best90_hr: float | None
    sustained2h: AerobicWindow | None
    sustained4h: AerobicWindow | None
    vam15: VamResult | None
    vam30: VamResult | None
    vam60: VamResult | None
    vam_retention_pct: float | None
    vam_comparison_text: str | None
    time85_s: float | None
    time90_s: float | None
    detection_threshold: float | None
    blocks: list[Block]
    gaps: list[GapInfo]
    groups: list[EffortGroup]
    interval_summary: IntervalSummary | None
    overall: str | None
    key_effort: str | None
    classification: str | None
    confidence: str | None
    lt2_low: float | None
    lt2_high: float | None
    lt2_evidence: str | None
    lt2_reason: str | None
    lt2_clue: str | None
    suspicious_descent_samples: list[Sample]
    artefact_intervals: list[tuple[datetime, datetime]]
    excluded_hr_samples: int
    distance_m: float
    elevation_gain_m: float | None
    has_hr: bool
    has_elevation: bool
    has_gps: bool
    has_power: bool


def analyze_activity(path: str | Path, hrmax: int, lt2: float | None = None,
                     min_hr: int = 50, max_hr: int = 220) -> ActivityAnalysis:
    """
    Analyse one activity and return structured results.

    Heart rate is optional. Distance, elevation and VAM are extracted whenever
    the source file supports them. HR-derived metrics are populated only when
    at least two usable HR samples remain after validity/artefact filtering.
    """
    path = Path(path).expanduser()
    activity_type, all_samples = read_samples(path)
    if len(all_samples) < 2:
        raise ValueError("Not enough timestamped activity samples")

    start_time = all_samples[0].timestamp
    end_time = all_samples[-1].timestamp
    duration = (end_time-start_time).total_seconds()
    if duration <= 0:
        raise ValueError("Activity has no positive duration")

    has_elevation = sum(s.elevation is not None for s in all_samples) >= 2
    has_gps = sum(s.lat is not None and s.lon is not None for s in all_samples) >= 2
    # Placeholder for future recorded-power support.
    has_power = False

    # Non-HR metrics are deliberately calculated before deciding whether the
    # activity contains usable HR. A ride without HR can still contribute VAM,
    # distance, elevation and historical training context.
    vam15 = best_vam(all_samples, 15*60, 40)
    vam30 = best_vam(all_samples, 30*60, 75)
    vam60 = best_vam(all_samples, 60*60, 150)

    distance_m = 0.0
    for a, b in zip(all_samples, all_samples[1:]):
        dt = (b.timestamp-a.timestamp).total_seconds()
        if 0 < dt <= 60:
            distance_m += max(0.0, segment_distance_m(a, b))

    elev_series = _elevation_series(all_samples)
    elevation_gain_m = None
    if len(elev_series) >= 2:
        gain = 0.0
        for a, b in zip(elev_series, elev_series[1:]):
            dt = (b.timestamp-a.timestamp).total_seconds()
            if 0 < dt <= 60 and a.elevation is not None and b.elevation is not None:
                delta = b.elevation-a.elevation
                if delta > 0:
                    gain += delta
        elevation_gain_m = gain

    raw_hrs = hr_samples(all_samples, min_hr, max_hr)
    suspicious = []
    artefact_intervals = []
    hrs = []
    raw_avg_hr = None
    raw_max = None

    if len(raw_hrs) >= 2:
        raw_avg_hr = mean(s.heart_rate for s in raw_hrs)
        raw_max = max(s.heart_rate for s in raw_hrs)
        suspicious = suspicious_descent_hr(all_samples, raw_hrs, hrmax)
        artefact_intervals = descent_artefact_intervals(suspicious)
        hrs = exclude_artefact_hr_samples(raw_hrs, artefact_intervals)

    has_hr = len(hrs) >= 2

    if not has_hr:
        retention = None
        comparison = None
        if vam15 is not None and vam30 is not None and vam15.vam > 0:
            retention = 100*vam30.vam/vam15.vam
            comparison = vam_comparison(vam15, vam30, "unclassified (no usable HR)", all_samples)

        return ActivityAnalysis(
            path=path,
            activity_type=activity_type,
            start_time=start_time,
            end_time=end_time,
            duration_s=duration,
            terrain=terrain_context(all_samples),
            raw_average_hr=raw_avg_hr,
            average_hr=None,
            raw_max_hr=raw_max,
            analysed_max_hr=None,
            hrmax_10s=None,
            hrmax_30s=None,
            hrmax_60s=None,
            hrmax_candidate=None,
            hrmax_confidence=None,
            hrmax_reason=None,
            best30_hr=None,
            best60_hr=None,
            best90_hr=None,
            sustained2h=None,
            sustained4h=None,
            vam15=vam15,
            vam30=vam30,
            vam60=vam60,
            vam_retention_pct=retention,
            vam_comparison_text=comparison,
            time85_s=None,
            time90_s=None,
            detection_threshold=None,
            blocks=[],
            gaps=[],
            groups=[],
            interval_summary=None,
            overall=None,
            key_effort=None,
            classification="unclassified (no usable HR)",
            confidence=None,
            lt2_low=None,
            lt2_high=None,
            lt2_evidence=None,
            lt2_reason=None,
            lt2_clue=None,
            suspicious_descent_samples=suspicious,
            artefact_intervals=artefact_intervals,
            excluded_hr_samples=max(0, len(raw_hrs)-len(hrs)),
            distance_m=distance_m,
            elevation_gain_m=elevation_gain_m,
            has_hr=False,
            has_elevation=has_elevation,
            has_gps=has_gps,
            has_power=has_power,
        )

    avg_hr = mean(s.heart_rate for s in hrs)
    analysed_max = max(s.heart_rate for s in hrs)

    hrmax10 = best_hr_average(hrs, 10, max_gap_s=15.0)
    hrmax30 = best_hr_average(hrs, 30, max_gap_s=15.0)
    hrmax60 = best_hr_average(hrs, 60, max_gap_s=15.0)

    hrmax_candidate = hrmax10
    hrmax_confidence = "low"
    hrmax_reason = "insufficient sustained high-HR evidence"
    if hrmax10 is not None:
        if hrmax10 > hrmax + 10:
            hrmax_reason = "candidate far above supplied HRmax; possible sensor artefact"
        elif (
            hrmax30 is not None and hrmax60 is not None
            and hrmax10 >= 0.95*hrmax
            and hrmax30 >= hrmax10 - 3
            and hrmax60 >= hrmax10 - 6
        ):
            hrmax_confidence = "high"
            hrmax_reason = "high HR sustained for 10s/30s/60s"
        elif (
            hrmax30 is not None
            and hrmax10 >= 0.92*hrmax
            and hrmax30 >= hrmax10 - 5
        ):
            hrmax_confidence = "medium"
            hrmax_reason = "high HR sustained for at least 30s"
        else:
            hrmax_reason = "short or submaximal high-HR observation"

    best30 = best_hr_average(hrs, 30*60)
    best60 = best_hr_average(hrs, 60*60)
    best90 = best_hr_average(hrs, 90*60)

    detection_threshold = lt2 if lt2 is not None else 0.85*hrmax
    blocks = detect_hard_blocks(hrs, detection_threshold)
    groups, gaps = build_effort_groups(blocks, all_samples, hrs, detection_threshold)

    t85 = time_above(hrs, 0.85*hrmax)
    t90 = time_above(hrs, 0.90*hrmax)

    overall = overall_ride_character(duration, avg_hr, hrmax)
    key_effort, key_conf = classify_key_effort(groups, gaps, hrmax, lt2)
    primary = combined_classification(overall, key_effort)
    interval_summary = summarize_intervals(
        groups, all_samples, hrs, detection_threshold, primary
    )

    lt2_low, lt2_high, lt2_conf, lt2_reason, lt2_clue = estimate_lt2(
        primary, groups, hrmax, best30, best60, t85
    )

    sustained2h = None
    sustained4h = None
    if duration >= 2*3600:
        sustained2h = best_sustained_hr_window(all_samples, 2*3600, min_hr, max_hr)
    if duration >= 4*3600:
        sustained4h = best_sustained_hr_window(all_samples, 4*3600, min_hr, max_hr)

    retention = None
    comparison = None
    if vam15 is not None and vam30 is not None and vam15.vam > 0:
        retention = 100*vam30.vam/vam15.vam
        comparison = vam_comparison(vam15, vam30, primary, all_samples)

    return ActivityAnalysis(
        path=path,
        activity_type=activity_type,
        start_time=start_time,
        end_time=end_time,
        duration_s=duration,
        terrain=terrain_context(all_samples),
        raw_average_hr=raw_avg_hr,
        average_hr=avg_hr,
        raw_max_hr=raw_max,
        analysed_max_hr=analysed_max,
        hrmax_10s=hrmax10,
        hrmax_30s=hrmax30,
        hrmax_60s=hrmax60,
        hrmax_candidate=hrmax_candidate,
        hrmax_confidence=hrmax_confidence,
        hrmax_reason=hrmax_reason,
        best30_hr=best30,
        best60_hr=best60,
        best90_hr=best90,
        sustained2h=sustained2h,
        sustained4h=sustained4h,
        vam15=vam15,
        vam30=vam30,
        vam60=vam60,
        vam_retention_pct=retention,
        vam_comparison_text=comparison,
        time85_s=t85,
        time90_s=t90,
        detection_threshold=detection_threshold,
        blocks=blocks,
        gaps=gaps,
        groups=groups,
        interval_summary=interval_summary,
        overall=overall,
        key_effort=key_effort,
        classification=primary,
        confidence=key_conf,
        lt2_low=lt2_low,
        lt2_high=lt2_high,
        lt2_evidence=lt2_conf,
        lt2_reason=lt2_reason,
        lt2_clue=lt2_clue,
        suspicious_descent_samples=suspicious,
        artefact_intervals=artefact_intervals,
        excluded_hr_samples=len(raw_hrs)-len(hrs),
        distance_m=distance_m,
        elevation_gain_m=elevation_gain_m,
        has_hr=True,
        has_elevation=has_elevation,
        has_gps=has_gps,
        has_power=has_power,
    )


def print_analysis(a: ActivityAnalysis):
    print(f"File:            {a.path.name}")
    print(f"Activity type:   {a.activity_type or '-'}")
    print(f"Terrain:         {a.terrain}")
    print(f"Duration:        {fmt_time(a.duration_s)}")
    print(f"Average HR:      {a.average_hr:.1f}" if a.average_hr is not None else "Average HR:      -")
    print(f"Maximum HR:      {a.analysed_max_hr}" if a.analysed_max_hr is not None else "Maximum HR:      -")

    if a.artefact_intervals:
        suspicious_max = max(s.heart_rate for s in a.suspicious_descent_samples)
        print(f"Raw maximum HR:  {a.raw_max_hr}")
        print(
            f"HR artefact flag: {len(a.suspicious_descent_samples)} "
            f"high-HR descending samples (up to {suspicious_max} bpm)"
        )
        print(
            f"HR excluded:      {a.excluded_hr_samples} samples in "
            f"{len(a.artefact_intervals)} sustained descent-artefact interval(s)"
        )
    elif a.suspicious_descent_samples:
        suspicious_max = max(s.heart_rate for s in a.suspicious_descent_samples)
        print(
            f"HR artefact flag: {len(a.suspicious_descent_samples)} isolated "
            f"descending sample(s) (up to {suspicious_max} bpm; not excluded)"
        )

    print(
        f"HRmax evidence:  10s {a.hrmax_10s:.1f} / 30s {a.hrmax_30s:.1f} / 60s {a.hrmax_60s:.1f} bpm"
        if None not in (a.hrmax_10s, a.hrmax_30s, a.hrmax_60s)
        else "HRmax evidence:  insufficient sustained data"
    )
    if a.hrmax_candidate is not None:
        print(
            f"HRmax candidate: {a.hrmax_candidate:.1f} bpm "
            f"({a.hrmax_confidence}: {a.hrmax_reason})"
        )

    print(
        f"Best 30 min HR:  {a.best30_hr:.1f}"
        if a.best30_hr is not None else "Best 30 min HR:  -"
    )
    print(
        f"Best 60 min HR:  {a.best60_hr:.1f}"
        if a.best60_hr is not None else "Best 60 min HR:  -"
    )

    if a.best90_hr is not None:
        print(f"Best 90m HR:      {a.best90_hr:.1f}")

    if a.sustained2h is not None:
        w = a.sustained2h
        print(
            f"Best 2h HR:       {w.avg_hr:.1f} bpm  "
            f"({fmt_clock(w.start)}-{fmt_clock(w.end)}, "
            f"moving {100*w.moving_fraction:.1f}%)"
        )
        print(f"2h HR spread:    P10 {w.hr_p10:.0f} / P90 {w.hr_p90:.0f} bpm")
    elif a.duration_s >= 2*3600:
        print("Best 2h HR:       none - no sufficiently continuous 2h window")

    if a.sustained4h is not None:
        w = a.sustained4h
        print(
            f"Best 4h HR:       {w.avg_hr:.1f} bpm  "
            f"({fmt_clock(w.start)}-{fmt_clock(w.end)}, "
            f"moving {100*w.moving_fraction:.1f}%)"
        )
        print(f"4h HR spread:    P10 {w.hr_p10:.0f} / P90 {w.hr_p90:.0f} bpm")
    elif a.duration_s >= 4*3600:
        print("Best 4h HR:       none - no sufficiently continuous 4h window")

    print_vam("Best 15 min VAM:", a.vam15)
    print_vam("Best 30 min VAM:", a.vam30)

    if a.vam15 is not None and a.vam30 is not None:
        gap = a.vam15.vam-a.vam30.vam
        print(
            f"VAM 15-30 gap:   {gap:.0f} m/h  "
            f"(30m = {a.vam_retention_pct:.1f}% of 15m)"
        )
        print(f"VAM comparison:  {a.vam_comparison_text}")

    print(f"Time >=85% max:  {fmt_time(a.time85_s)}")
    print(f"Time >=90% max:  {fmt_time(a.time90_s)}")
    print()

    if not a.has_hr:
        print("Heart-rate analysis: no usable HR data")
        print(f"Classification:      {a.classification}")
        return

    print(f"Detected HR blocks using {a.detection_threshold:.0f} bpm:")
    if a.blocks:
        for i, b in enumerate(a.blocks, 1):
            print(
                f"{i:>2}. {fmt_time(b.duration_s):>7}  "
                f"avg {b.avg_hr:5.1f}  max {b.max_hr}"
            )
    else:
        print("none")

    if a.gaps:
        print()
        print("Gaps between HR blocks:")
        for i, g in enumerate(a.gaps, 1):
            elev = "-" if g.elev_gain_m is None else f"{g.elev_gain_m:+.0f}m"
            hr = "-" if g.avg_hr is None else f"{g.avg_hr:.0f}"
            print(
                f"{i:>2}. {fmt_time(g.duration_s):>7}  "
                f"{g.distance_m/1000:4.2f} km  elev {elev:>6}  "
                f"HR {hr:>3}  stop {100*g.stopped_fraction:4.0f}%  {g.kind}"
            )

    if a.groups:
        print()
        print("Interpreted effort groups:")
        for i, g in enumerate(a.groups, 1):
            marker = "interrupted" if g.interrupted else "continuous"
            print(
                f"{i:>2}. {fmt_time(g.duration_s):>7} span / "
                f"{fmt_time(g.work_duration_s):>7} hard  "
                f"avg work HR {g.avg_work_hr:5.1f}  {marker}"
            )

    print()
    print(f"Overall ride:     {a.overall}")
    print(f"Key effort:       {a.key_effort}")
    print(f"Classification:   {a.classification}")
    print(f"Confidence:       {a.confidence}")

    if a.lt2_low is not None:
        print(f"LT2 candidate:    {a.lt2_low:.1f}-{a.lt2_high:.1f} bpm")
    else:
        print("LT2 candidate:    none")

    print(f"LT2 evidence:     {a.lt2_evidence}")
    print(f"LT2 reason:       {a.lt2_reason}")
    if a.lt2_clue is not None:
        print(f"LT2 clue:         {a.lt2_clue}")


def main():
    p = argparse.ArgumentParser(
        description="Analyse one endurance activity for HR, LT2, VAM and aerobic clues."
    )
    p.add_argument("file", type=Path)
    p.add_argument("--hrmax", type=int, required=True)
    p.add_argument("--lt2", type=float, default=None)
    p.add_argument("--min-hr", type=int, default=50)
    p.add_argument("--max-hr", type=int, default=220)
    p.add_argument(
        "--activities-csv",
        type=Path,
        default=None,
        help=(
            "Path to Strava activities.csv. If omitted, the analyser looks for "
            "activities.csv in the parent of the activity directory."
        ),
    )
    p.add_argument(
        "--no-update-metadata",
        action="store_true",
        help="Analyse the activity without appending it to activities.csv.",
    )
    args = p.parse_args()

    try:
        result = analyze_activity(
            args.file, args.hrmax, args.lt2, args.min_hr, args.max_hr
        )
    except Exception as exc:
        print(f"Error reading/analyzing file: {exc}", file=sys.stderr)
        return 1

    print_analysis(result)

    if not args.no_update_metadata:
        activities_csv = resolve_single_activity_csv(args.file, args.activities_csv)
        if activities_csv is not None:
            try:
                added = append_single_activity_metadata(activities_csv, result)
                if added:
                    print(f"Metadata appended:  {activities_csv}")
                else:
                    print(f"Metadata already present: {activities_csv}")
            except Exception as exc:
                print(f"Warning: could not update activities.csv: {exc}", file=sys.stderr)
        elif args.activities_csv is not None:
            # Normally unreachable because an explicit path is returned even if
            # missing, but retained for clear command-line behaviour.
            print(
                f"Warning: activities.csv not found: {args.activities_csv.expanduser()}",
                file=sys.stderr,
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
