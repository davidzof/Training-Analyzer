# Training Analysis

A toolkit for data mining historical fitness activity written in
Python. Basically you can export all of your Strava activities
and let this script analyze them. The output can be loaded into an AI to
get insights and advice about training or can be used by
actual humans like coaches.

It offers the following features

- heart-rate analysis across multiple durations;
- per-ride and per-season HRmax evidence;
- cautious LT2 estimation;
- long-duration sustained heart-rate observations;
- hard-effort block detection, including recovery gaps;
- climbing performance using VAM;
- analysis of activities even when no usable HR trace is present;
- capability flags for HR, elevation, GPS and future power data;
- annual cycling volume, distance and elevation;
- bike/gear context from Strava's `activities.csv`;
- structured CSV or JSON output for longitudinal analysis by humans or LLMs;
- historical comparison across many years.

The current versions are:

- `scan_strava.py` — batch scanner and yearly summary;
- `activity_file_processor.py` — per-file wrapper used by the scanner;
- `analyze_training.py` — underlying activity analysis engine.

---

## 1. Requirements

### Python

Python 3.10+ is recommended.

The GPX and TCX readers use only the Python standard library.

FIT support requires `fitparse`:

```bash
python3 -m pip install fitparse
```

### Files

Put these three Python files in the same directory:

```text
scan_strava.py
activity_file_processor.py
analyze_training.py
```

## 2. Supported activity files

The scanner understands:

```text
.gpx
.gpx.gz
.tcx
.tcx.gz
.fit
.fit.gz
```

Files are scanned from the **single directory supplied on the command line**. The scanner is not recursive. It can
work directly with Strava batch exports.

Example:

```text
Strava/
├── activities.csv
└── activities/
    ├── 12345678901.fit.gz
    ├── 12345678902.gpx
    ├── 12345678903.tcx.gz
    └── ...
```

---

## 3. Strava `activities.csv`

The scanner can run without `activities.csv`, but it is strongly recommended.

When available, `activities.csv` is used for:

- fast preselection by year and sport;
- Strava activity ID;
- activity name;
- bike/gear name;
- bike weight;
- bike ID;
- athlete weight, if present;
- annual activity count;
- annual moving time;
- annual distance;
- annual elevation gain;
- counts of long rides.

It also allows annual volume to include rides where no usable HR trace exists.

### Capability-based activity processing

Heart rate is **not** a prerequisite for an activity to be analysed. The scanner keeps an activity whenever the source file contains enough timestamped samples to reconstruct useful evidence.

Each activity reports availability flags:

```text
has_hr
has_elevation
has_gps
has_power
```

The current analyser uses HR, GPS and elevation where available. `has_power` is currently a placeholder for future recorded-power support.

A ride without usable HR can still contribute:

- distance;
- elevation gain;
- VAM, when elevation data is suitable;
- bike/gear statistics;
- yearly/seasonal volume.

HR-dependent fields remain `null` in JSON or empty in CSV. This avoids the historical selection bias of analysing climbing performance only on rides where a heart-rate monitor happened to be worn.

### Automatic lookup

If the activity directory is:

```text
/path/to/Strava/activities
```

the scanner automatically looks for:

```text
/path/to/Strava/activities.csv
```

You can also specify it explicitly:

```bash
--activities-csv /path/to/Strava/activities.csv
```

### File matching

The Strava CSV normally contains filenames such as:

```text
activities/12345678901.fit.gz
```

The scanner joins these to the exported files by basename:

```text
12345678901.fit.gz
```

### Meaning of `CSV rows missing file`

For example:

```text
CSV rows matched:      174
Matching files found:  168
CSV rows missing file: 6
```

means that 174 metadata rows matched the year/sport filter, but six referenced activity files were not present in the supplied activity directory.

---

## 4. Basic usage

The main command is:

```bash
python3 scan_strava.py DIRECTORY --hrmax HRMAX
```

`--hrmax` is mandatory.

Example:

```bash
python3 scan_strava.py /home/user/Strava/activities --hrmax 184
```

A typical yearly cycling scan is:

```bash
python3 scan_strava.py /home/user/Strava/activities --hrmax 184 --year 2025 --sport cycling --output cycling_2025.csv
```

A multi-sport endurance scan can use a comma-separated sport list:

```bash
python3 scan_strava.py /home/user/Strava/activities --hrmax 183 --lt1 142 --lt2 160 --year 2026 --sport cycling,skiing,walking --json
```

Here `skiing` includes Nordic/cross-country and backcountry skiing, but not alpine/downhill skiing.

With an explicit metadata file:

```bash
python3 scan_strava.py /home/user/Strava/activities --hrmax 184 --year 2025 --sport cycling --output cycling_2025.csv --activities-csv /home/user/Strava/activities.csv
```

---

## 5. Command-line options

### Positional argument

#### `directory`

Directory containing GPX, TCX or FIT activity files.

Example:

```bash
python3 scan_strava.py ../../Documents/Strava/activities ...
```

---

### `--hrmax`

Required yearly HRmax reference.

Example:

```bash
--hrmax 192
```

This is the HRmax value used by the analysis rules for that run.

The program also reports **per-ride HRmax candidates**, so a useful workflow is:

1. make a reasonable yearly HRmax estimate;
2. run the analysis;
3. inspect credible HRmax candidates;
4. revise the yearly HRmax if appropriate;
5. rerun the year.

The software does **not** silently replace the supplied HRmax.

---

### `--year`

Restrict analysis to one calendar year.

Example:

```bash
--year 2015
```

When `activities.csv` is available, year filtering is performed before opening the activity files, which greatly speeds up large Strava archives.

Year extraction is locale-independent, so English Strava dates such as:

```text
Dec 28, 2025, 2:34:18 PM
```

also work on systems using a French locale.

---

### `--month`

Optional season-start month (1–12). It requires `--year`. For example `--year 2025 --month 5` analyses May 2025 through April 2026.

---

### `--add-missing-metadata`

Append successfully analysed files missing from `activities.csv`. A one-time `activities.csv.bak` backup is created before the first append.

---

### `--sport`

Restrict analysis to one or more normalized sports. Multiple sports are supplied as a comma-separated list with no special weighting between them.

Examples:

```bash
--sport cycling
--sport cycling,skiing,walking
```

If `--sport` is omitted, all activity types are eligible for the scan.

The main normalized sport names currently understood are:

| `--sport` value | Strava activity types included | Notes |
|---|---|---|
| `cycling` | Ride, VirtualRide, EBikeRide, MountainBikeRide, GravelRide | All are grouped as cycling. |
| `running` | Run, VirtualRun, TrailRun | All are grouped as running. |
| `walking` | Walk, Hike | Hiking is currently grouped with walking. |
| `skiing` | Skiing, NordicSki, NordicSkiing, CrossCountrySki, CrossCountrySkiing, BackcountrySki | Intended for self-propelled skiing. It does **not** include alpine/downhill skiing. |
| `roller skiing` | RollerSki, RollerSkiing | Kept separate from snow skiing. |

Other Strava activity types are retained using a lower-case version of their original name, so they can still be selected explicitly when needed.

In particular, alpine skiing is **not** an alias of `skiing`. Strava values such as `AlpineSki` or `alpine_skiing` remain separate activity types and therefore are excluded by:

```bash
--sport cycling,skiing,walking
```

This makes the above a useful multi-sport endurance scan when walking is deliberate base exercise and lift-served alpine skiing should not contribute to the default training-volume summary.

---

### `--lt1` and `--lt2`

Optional known lactate-threshold heart rates. When both are supplied, the analyser reports time in a simple three-zone model:

```text
Zone 1: HR < LT1
Zone 2: LT1 <= HR < LT2
Zone 3: HR >= LT2
```

Example:

```bash
--lt1 140 --lt2 160
```

Zone time is calculated from the same cleaned HR samples used by the rest of the analyser. Recording gaps and HR samples rejected as artefacts are not counted. The output includes seconds and percentages for each zone.

Zone reporting requires both thresholds. If they are omitted, zone fields remain `null`/empty. The scanner does not infer LT1 from a percentage of HRmax.

`--lt2` also continues to help the existing effort-classification logic when supplied.

---

### `--min-hr`

Minimum accepted HR sample.

Default:

```text
50 bpm
```

Example:

```bash
--min-hr 45
```

---

### `--max-hr`

Maximum accepted HR sample.

Default:

```text
220 bpm
```

Example:

```bash
--max-hr 210
```

This is a hard sample-validity limit, not the physiological HRmax estimate.

The supplied `--hrmax` must lie between `--min-hr` and `--max-hr`.

---

### `--activities-csv`

Explicit path to Strava's `activities.csv`.

Example:

```bash
--activities-csv ../Strava/activities.csv
```

If omitted, the scanner looks in the parent directory of the activity folder.

---

### `--json`

Write structured JSON instead of CSV. The JSON contains the season/year summary together with the per-activity records, making it suitable for LLM or agent analysis.

Example:

```bash
python3 scan_strava.py /home/user/Strava/activities --hrmax 184 --year 2025 --sport cycling --json
```

This produces:

```text
2025-cycling.json
```

The JSON is designed for longitudinal analysis. It contains a compact top-level season summary plus the individual activity records used to support it. Missing observations use JSON `null`; unavailable capabilities are represented explicitly by the `has_*` flags. Hard-effort blocks and their gaps remain nested arrays rather than being flattened into strings.

When `--lt1` and `--lt2` are supplied, each HR-equipped activity includes two complementary three-zone views. The existing `zone1_seconds`, `zone2_seconds`, `zone3_seconds` and `zone_total_seconds` fields preserve all continuously recorded HR time. The `active_zone1_seconds`, `active_zone2_seconds`, `active_zone3_seconds` and `active_zone_total_seconds` fields count only intervals with credible movement, currently **at least 2 km/h**. The lower threshold is deliberately sport-neutral: it is low enough to retain slow uphill skiing and walking while still removing stationary periods and most GPS drift. This also prevents a device left recording at work from becoming several hours of apparent training while preserving the original HR record. The season summary additionally contains `weekly_training`, which aggregates weekly moving hours, distance, climbing, long rides, active zone time and hard-effort counts.

For a May-start cross-country skiing season:

```text
may-2025-cross-country-skiing.json
```

---

### `--output`

Optional output path. Normally the scanner generates the filename automatically.

Example:

```bash
--output cycling_2015.csv
```

Default names are generated from the period and sport. Examples:

```text
2025-cycling.csv
may-2025-cross-country-skiing.csv
```

Use `--output` only when you want to override the generated name.

---

## 5A. Rolling 12-month seasons with `--month`

By default, `--year 2025` means the calendar year 1 January through 31 December 2025.

If `--month` is supplied, `--year` becomes the **season start year** and the scanner analyses exactly 12 months beginning on the first day of that month.

For example:

```bash
--year 2025 --month 5
```

means:

```text
1 May 2025 <= activity < 1 May 2026
```

or, in ordinary terms, **May 2025 through April 2026**.

This is particularly useful for sports such as cross-country skiing whose training year may begin after the winter season.

Example:

```bash
python3 scan_strava.py /home/user/Strava/activities --hrmax 184 --year 2025 --month 5 --sport skiing --output skiing_2025-26.csv
```

If `--output` is omitted, a skiing season beginning in May 2025 defaults to:

```text
may-2025-cross-country-skiing.csv
```

`--month` requires `--year`.

---

## 5B. Updating `activities.csv` as new files arrive

A Strava export is normally static, but the activity directory can also be used as a growing local archive during a season.

If new GPX, TCX or FIT files are copied into the directory, they may not yet have rows in the original Strava `activities.csv`.

Use:

```bash
--add-missing-metadata
```

to append successfully analysed missing files to `activities.csv`.

Example:

```bash
python3 scan_strava.py /home/user/Strava/activities --hrmax 184 --year 2026 --sport cycling --activities-csv /home/user/Strava/activities.csv --add-missing-metadata --output cycling_2026.csv
```

When this option is enabled, the scanner does **not** rely solely on `activities.csv` for preselection. It scans the activity directory so newly added files can be discovered.

Before the first append, the scanner creates a one-time backup:

```text
activities.csv.bak
```

Existing rows are never replaced.

For a newly discovered activity, only metadata that can be reconstructed locally is written:

```text
Filename
Activity Date
Activity Type
Elapsed Time
Moving Time
Distance
Elevation Gain
```

Fields that cannot be reconstructed reliably remain blank, including Strava activity ID, gear, bike weight and calories.

For locally reconstructed rows, `Moving Time` and `Elapsed Time` are initially set to the analysed activity duration. The scanner deliberately does not invent Strava-specific pause semantics that are not available from the local source file.

After appending rows, the scanner reloads `activities.csv`, so the current run's annual/season volume summary immediately includes the new activities.


---

## 6. Full yearly example

```bash
python3 scan_strava.py ../../Documents/Strava/activities --hrmax 192 --year 2015 --sport cycling --output cycling_2015.csv --activities-csv ../../Documents/Strava/activities.csv
```

Typical output begins with:

```text
Strava metadata:       ../../Documents/Strava/activities.csv
Metadata rows loaded:  3746
CSV rows matched:      93
Matching files found:  93
```

The scanner then processes each matching activity and writes one CSV row per successfully analysed activity.

At the end it prints the yearly summary.

---

## 7. Exit status

The scanner returns:

```text
0
```

when the run completes with no activity-file analysis errors.

It returns:

```text
1
```

if one or more activity files caused analysis/parsing errors.

It returns:

```text
2
```

for command/configuration errors such as an invalid directory, invalid HR limits, or a missing/bad `activities.csv`.

Important: a return code of `1` does **not** mean the whole scan failed. The output CSV and successfully analysed activities are still written.

---

# Analysis metrics

## 8. Activity date and duration

Dates are written in human-readable form:

```text
17 Jul 2015 14:32
```

Duration is written as:

```text
h:mm:ss
```

for example:

```text
4:07:35
```

The calculations internally still use seconds.

---

## 9. Basic heart-rate fields

### `average_hr`

Average HR after the analysis artefact exclusion logic.

### `raw_max_hr`

Highest accepted raw HR sample before artefact exclusion.

This should **not** automatically be interpreted as physiological HRmax.

### `analysed_max_hr`

Highest HR remaining after the analyser excludes recognised artefact intervals.

---

# HRmax evidence

## 10. Rolling HRmax observations

Each ride reports:

```text
hrmax_10s
hrmax_30s
hrmax_60s
```

These are the best rolling HR averages over 10, 30 and 60 seconds.

They are more useful than an isolated one-second maximum because they show whether a high HR was sustained.

---

## 11. `hrmax_candidate`

The current per-ride candidate is based on the best 10-second HR.

The program then assesses how well that high HR was sustained.

### High confidence

A candidate can be labelled `high` when:

- the 10-second value is at least 95% of supplied HRmax;
- the 30-second value is within 3 bpm of the 10-second value;
- the 60-second value is within 6 bpm of the 10-second value.

### Medium confidence

A candidate can be labelled `medium` when:

- the 10-second value is at least 92% of supplied HRmax;
- the 30-second value is within 5 bpm of the 10-second value.

### Low confidence

Used when the high-HR evidence is too short, too low, or otherwise weak.

If the candidate is more than 10 bpm above the supplied yearly HRmax, the reason explicitly warns that it may be a sensor artefact.

### Recommended use

Do not simply take the highest candidate in a year.

Look for:

- repeated candidates;
- physiological consistency;
- sustained 30s/60s support;
- a ride context where a maximal effort is plausible;
- agreement with neighbouring years.

Old HR straps can create sustained-looking errors, so historical HRmax should be treated as an evidence-based estimate.

---

# Sustained heart-rate observations

## 12. 30-minute HR

```text
best_30m_hr
```

Highest rolling 30-minute average HR.

This can be useful threshold evidence, but a high 30-minute HR alone is **not sufficient for a numerical LT2 estimate**.

---

## 13. 60-minute HR

```text
best_60m_hr
```

Highest rolling 60-minute average HR.

This is an important part of the LT2 evidence rules.

---

## 14. 90-minute HR

```text
best_90m_hr
```

Highest rolling 90-minute HR observation.

This is especially useful for long sustained climbs that naturally fall between the existing 60-minute and 2-hour durations.

It is descriptive and is not automatically labelled as a physiological threshold.

---

## 15. 2-hour sustained HR

Fields:

```text
best_2h_hr
best_2h_moving_fraction
best_2h_hr_p10
best_2h_hr_p90
```

The program intentionally does **not** label this LT1.

It answers a simpler question:

> What was the highest observed average HR over a reasonably continuous two-hour period?

P10 and P90 are reported as descriptive information about the HR distribution but are **not** used to accept/reject the window.

---

## 16. 4-hour sustained HR

Fields:

```text
best_4h_hr
best_4h_moving_fraction
best_4h_hr_p10
best_4h_hr_p90
```

Again, this is **not automatically called LT1**.

The purpose is to provide a long-duration aerobic reference:

> What was the highest average HR actually sustained over a real four-hour period without a substantial recovery break?

These observations can be useful when thinking about the likely LT1 region, but interpretation is left to the user.

---

## 17. Five-minute stop rule for 2h/4h windows

Long-duration windows allow normal riding interruptions such as:

- summit photographs;
- bottle filling;
- short traffic stops;
- junctions;
- short mechanical interruptions.

A window is rejected when it contains a **single stopped episode longer than 5 minutes**.

A recording/autopause gap longer than 5 minutes is also treated as excessive rest.

This prevents a lunch stop or other substantial recovery from making a 2h/4h average appear more sustainable than it really was.

### What counts as stopped?

Movement is currently classified as stopped when estimated speed is below:

```text
2 km/h
```

Short stopped periods can accumulate; cumulative stopped percentage alone does not reject the window.

### HR spread

Older versions used a P10–P90 spread restriction.

That restriction has been removed.

Mountain rides naturally contain climbs, descents and easier sections, so a wide HR distribution is not itself a reason to discard a long-duration observation.

---


## Hard-effort blocks and interval session detail

The analyser keeps two related but deliberately separate concepts:

1. **hard HR blocks** — sustained hard efforts detected in the HR trace;
2. **structured interval sessions** — a stricter interpretation requiring a convincing repeated work/recovery pattern.

This distinction matters for outdoor training. A hilly ride may contain several genuine hard climbs without resembling a conventional `4 x 8 min` interval workout. The hard efforts are still useful evidence and are therefore exported even when the activity does not qualify as an interval session.

Every HR-enabled activity now includes:

```text
hard_block_threshold_bpm
hard_block_count
hard_blocks
hard_block_gaps
```

Each hard block records:

```text
start
end
duration_seconds
average_hr_bpm
max_hr_bpm
```

When two hard blocks are separated, the gap can record:

```text
start
end
duration_seconds
distance_km
elevation_change_m
average_hr_bpm
stopped_fraction
kind
```

Possible gap descriptions include terrain-aware labels such as `descent / terrain recovery`, `easing on climb` and `active recovery on climb`.

In JSON, `hard_blocks` and `hard_block_gaps` are proper nested arrays. In CSV they are stored as compact JSON text in the corresponding cells.

A ride can therefore legitimately contain:

```text
hard_block_count: 4
interval_count:    null
```

This means four sustained hard efforts were detected, but the ride did not meet the stricter definition of a structured interval session.

When a genuine interval session is detected, the existing interval summary fields are also populated:

```text
interval_count
interval_work_total
interval_work_median
interval_work_avg_hr
interval_work_max_hr
interval_recovery_median
interval_recovery_avg_hr
interval_work_durations
interval_work_avg_hrs
interval_work_max_hrs
interval_recovery_durations
interval_recovery_avg_hrs
interval_summary
```

These remain **HR-detected** work/recovery periods rather than exact prescribed or lap durations. Heart rate rises and falls with a delay after workload changes, so a real 8-minute interval may appear as somewhat less than eight minutes above the detection threshold. The software reports what the HR trace supports rather than inventing exact workout timing.

---

# LT2 analysis

## 18. LT2 philosophy

The program treats LT2 estimation cautiously.

HR alone cannot identify LT2 with laboratory precision.

The output is therefore evidence, not a diagnosis.

Key fields are:

```text
lt2_low
lt2_high
lt2_evidence
lt2_reason
lt2_clue
```

Possible evidence labels include:

```text
strong
moderate
low
none
```

---

## 19. Strong LT2 evidence

A numerical LT2 range requires credible 60-minute evidence.

The current logic looks for:

- sustained hard effort rather than an interval session;
- 30-minute HR in a plausible threshold region;
- 60-minute HR in a plausible threshold region;
- substantial time around the high-intensity region.

The threshold search region is approximately:

```text
82% to 93% of supplied HRmax
```

A strong result can then produce:

```text
lt2_low
lt2_high
```

---

## 20. Thirty-minute-only evidence

A strong 30-minute effort without supporting 60-minute evidence does **not** produce a numerical LT2 range.

Instead it produces a moderate clue such as:

```text
30m HR 164.0 bpm suggests LT2 is probably at or below about 164 bpm
```

This prevents a hard 30-minute effort from being mistaken for a one-hour threshold.

---

## 21. Interval sessions

If the ride is classified as an interval session, the program does not make a direct numerical LT2 estimate from it.

Intervals are useful training evidence, but recovery periods make them unsuitable for direct LT2 inference.

---

# HR artefact handling

## 22. Artefact flags

Fields:

```text
hr_artefact
excluded_hr_samples
```

The analyser includes logic for suspicious high HR during descending, where static/electrical interference or bad chest-strap contact can sometimes create false values.

The raw and analysed maxima are therefore both retained.

### Important limitation

Artefact detection is not perfect.

Older sensors can generate sustained-looking false HR that survives automated filtering.

For historical data, give more weight to:

- repeated observations;
- long sustained patterns;
- plausible ride context;
- consistency across neighbouring years;

and less weight to isolated extreme values.

---

# VAM / climbing analysis

## 23. VAM fields

Per ride:

```text
vam_15
vam_30
vam_60
vam_retention_pct
vam_comparison
```

VAM is vertical ascent speed in metres per hour.

---

## 24. Minimum ascent requirements

A VAM window must include approximately the requested duration and enough net climbing.

Current minimum net ascent is:

| Window | Minimum gain |
|---|---:|
| 15 min | 40 m |
| 30 min | 75 m |
| 60 min | 150 m |

The elevation trace is median-filtered to reduce GPS/barometric noise.

---

## 25. Comparable VAM

The scanner distinguishes VAM observations judged suitable for comparison.

The seasonal summary only uses rides whose `vam_comparison` starts with:

```text
comparable:
```

for its main comparable-VAM statistics.

This helps avoid comparing a clean sustained climb with a window dominated by rolling terrain or unrelated activity structure.

---

## 26. VAM retention

```text
vam_retention_pct
```

is approximately:

```text
100 × 30-minute VAM / 15-minute VAM
```

It indicates how well climbing rate is maintained as duration increases.

A high percentage means the 30-minute climbing rate was close to the best 15-minute rate.

---

## 27. 60-minute VAM

```text
vam_60
```

adds a longer-duration climbing-performance observation.

It can be especially useful in archives containing long Alpine climbs.

The seasonal summary reports top comparable 60-minute VAM values when available.

---

## 28. Bike context

When `activities.csv` is available, the output includes:

```text
activity_gear
bike_weight
bike_id
```

The summary also reports comparable VAM by bike.

This is important because VAM depends not only on fitness but also on:

- bike weight;
- tyres;
- road vs MTB use;
- surface;
- gradient;
- conditions;
- system weight.

The program deliberately does **not** invent a weight-normalized pseudo-power score.

Raw VAM is retained, and bike/gear is supplied as context.

---

# Distance and elevation

## 29. Per-ride distance

```text
distance_km
```

Device distance is preferred when available.

GPS/haversine distance is used as a fallback.

Very large recording gaps are not blindly bridged when calculating the per-ride total.

---

## 30. Per-ride elevation gain

```text
elevation_gain_m
```

Positive elevation changes are summed from a median-filtered elevation trace.

This reduces sensitivity to GPS/barometric noise.

---

# Annual volume

## 31. Why annual volume uses `activities.csv`

Physiological analysis can only use files with sufficient HR data.

That would make a year where the HR strap was rarely used look artificially inactive.

Therefore, when `activities.csv` is present, annual volume is calculated from **all Strava metadata rows matching the requested year and sport**, including activities without usable HR.

The summary reports:

```text
Activities in Strava metadata
Total moving time
Total distance
Total elevation gain
Long rides >=3h / >=4h / >=6h
```

This makes historical interpretation much more robust.

For example, a year with only 14 HR-analyzed rides can still correctly show high total cycling volume if many rides were recorded without HR.

---

# CSV columns

## 32. Identification and Strava metadata

```text
filename
activity_date
activity_type
strava_activity_id
activity_name
activity_gear
bike_weight
bike_id
athlete_weight
```

---

## 33. Basic activity metrics

```text
duration
average_hr
raw_max_hr
analysed_max_hr
distance_km
elevation_gain_m
```

---

## 34. HRmax evidence

```text
hrmax_10s
hrmax_30s
hrmax_60s
hrmax_candidate
hrmax_confidence
hrmax_reason
```

---

## 35. Sustained HR

```text
best_30m_hr
best_60m_hr
best_90m_hr

best_2h_hr
best_2h_moving_fraction
best_2h_hr_p10
best_2h_hr_p90

best_4h_hr
best_4h_moving_fraction
best_4h_hr_p10
best_4h_hr_p90
```

---

## 36. VAM

```text
vam_15
vam_30
vam_60
vam_retention_pct
vam_comparison
```

---

## 37. Intensity, hard efforts and classification

```text
time_85pct_seconds
time_90pct_seconds
hard_block_threshold_bpm
hard_block_count
hard_blocks
hard_block_gaps
overall_ride
key_effort
classification
confidence
```

`time_85pct_seconds` and `time_90pct_seconds` are based on the supplied yearly `--hrmax`.

---

## 38. LT2

```text
lt2_low
lt2_high
lt2_evidence
lt2_reason
lt2_clue
```

---

## 39. Availability, artefact and status

```text
hr_artefact
excluded_hr_samples
has_hr
has_elevation
has_gps
has_power
status
error
```

`status: ok` does not imply that HR is present. A valid no-HR ride can have `has_hr: false` while retaining GPS/elevation/VAM evidence.

---

# Seasonal summary

## 40. Annual volume section

When metadata is available:

```text
Activities in Strava metadata
Total moving time
Total distance
Total elevation gain
Long rides >=3h / >=4h / >=6h
```

---

## 41. LT2 section

The scanner reports:

```text
Strong LT2 observations
Moderate LT2 observations
Median strong LT2 range
```

The median strong range is much more useful historically than blindly selecting the single highest ride.

---

## 42. Sustained HR section

The scanner reports the top observations for:

```text
30m
60m
90m
2h
4h
```

For long-duration values it also reports how many qualifying windows were found.

---

## 43. HRmax section

The summary prints the five highest candidates labelled:

```text
high
medium
```

followed by the highest raw HR observations.

This makes it easy to see the difference between:

```text
credible sustained HRmax evidence
```

and:

```text
raw sensor maxima
```

---

## 44. Hard-effort section

The JSON season summary contains:

```text
activities_with_hard_blocks
total_hard_blocks
```

This prevents a year containing hard climbing or other embedded quality work from looking like an entirely easy/endurance year merely because none of the rides met the stricter interval-session definition.

The separate interval summary still reports only structured sessions.

---

## 45. Weekly training and three-zone distribution

The JSON season summary contains a `weekly_training` array. Weekly volume is based on Strava moving-time metadata where available, so rides without HR still count toward training hours. Empty calendar weeks between the first and last recorded activity are retained so genuine breaks in training remain visible. Weekly `zone1_hours`, `zone2_hours`, `zone3_hours`, `hr_zone_hours` and zone percentages are based on the active-cycling zone stream, while all continuously recorded HR time remains available as `recorded_zone1_hours`, `recorded_zone2_hours`, `recorded_zone3_hours` and `recorded_hr_zone_hours`.

Each week can contain:

```text
week_start
iso_year / iso_week
activities
moving_hours
distance_km
elevation_gain_m
rides_3h
activities_with_zone_data
zone1_hours / zone2_hours / zone3_hours
hr_zone_hours
zone1_pct / zone2_pct / zone3_pct
hard_blocks
activities_with_hard_blocks
moving_hours_4wk
```

`hr_zone_hours` is deliberately separate from total moving hours. This shows how much of the week actually had usable HR data and prevents missing HR from being silently treated as Zone 1.

`moving_hours_4wk` is the sum of the current week and previous three calendar weeks. It gives an easy-to-read measure of recent training exposure without introducing an opaque training-load score.

---

## 46. VAM section

The scanner reports:

```text
Comparable VAM activities
Top comparable 15m VAM
Top comparable 30m VAM
Top comparable 60m VAM
Median comparable VAM retention
```

When gear data exists it also shows comparable VAM grouped by bike.

---

# One-off activity analysis

## 46. Running the analyser directly

For detailed analysis of one activity:

```bash
python3 analyze_training.py ride.gpx --hrmax 184
```

FIT example:

```bash
python3 analyze_training.py ride.fit.gz --hrmax 184
```

With a known LT2:

```bash
python3 analyze_training.py ride.gpx --hrmax 184 --lt2 162
```

After a successful one-off analysis, the analyser looks for `activities.csv` in the parent of the activity directory and appends a minimal reconstructed metadata row when the file is missing from the CSV. It does not overwrite an existing row and creates a one-time `.bak` backup before the first append.

Use an explicit metadata file with:

```bash
python3 analyze_training.py ride.gpx --hrmax 184 --activities-csv /path/to/activities.csv
```

Or analyse without changing metadata:

```bash
python3 analyze_training.py ride.gpx --hrmax 184 --no-update-metadata
```

The one-off analyser prints more detail than the batch scanner, including:

- terrain context;
- average and maximum HR;
- HRmax evidence;
- best sustained HR observations;
- VAM;
- hard blocks;
- effort grouping;
- classification;
- LT2 evidence;
- artefact information.

---

# Suggested historical workflow

## 47. Analyse one year at a time

Example:

```bash
python3 scan_strava.py /data/Strava/activities --hrmax 192 --year 2015 --sport cycling --output cycling_2015.csv --activities-csv /data/Strava/activities.csv
```

Repeat for each year.

---

## 48. Choose HRmax sensibly

Start with a reasonable annual estimate.

Then inspect:

```text
hrmax_candidate
hrmax_confidence
hrmax_reason
hrmax_30s
hrmax_60s
```

and the seasonal `Highest credible HRmax candidates`.

If the evidence suggests the estimate is wrong, rerun the year with a revised `--hrmax`.

---

## 49. Interpret LT2 across several rides

Prefer:

- repeated strong observations;
- sustained climbs;
- sustained flat hard efforts;
- agreement between 30m and 60m;
- consistency across a season.

Avoid using:

- interval sessions as direct LT2 estimates;
- isolated raw HR maxima;
- one unusually high 30-minute effort.

---

## 50. Use 4h HR as a long-duration clue, not an automatic LT1 label

The program deliberately reports:

```text
best_4h_hr
```

rather than:

```text
LT1
```

A clean four-hour observation with very high moving fraction and no long rest can be useful evidence about sustainable aerobic intensity.

However, terrain, heat, fatigue, descending and pacing all influence the result.

---

## 51. Use annual volume to explain performance

When comparing years, do not interpret VAM or threshold changes without considering:

- total riding hours;
- total distance;
- total elevation;
- number of long rides;
- bike type;
- changes in available training time;
- injury;
- illness;
- exceptional events such as lockdown.

Short-term changes in training opportunity can be much larger than normal age-related decline.

---

# Troubleshooting

## 52. `FIT support requires fitparse`

Install:

```bash
python3 -m pip install fitparse
```

---

## 53. `activities.csv not found`

Either specify it explicitly:

```bash
--activities-csv /path/to/activities.csv
```

or place it in the parent directory of the activity folder.

The analysis still works without metadata if you simply omit `--activities-csv`, but annual volume and gear enrichment will be unavailable.

---

## 54. `CSV rows missing file`

The metadata row exists, but the corresponding GPX/FIT/TCX file is not present in the supplied activity directory.

Check the directory you passed as the positional argument.

---

## 55. No usable heart rate

Missing or unusable HR is no longer a file-level error.

If the activity still has enough timestamped samples, it is retained with:

```text
has_hr: false
```

HR-dependent metrics remain empty/`null`, while GPS/elevation/VAM, distance and metadata can still be analysed where available. A true processing error is reserved for a file that cannot provide enough usable activity data at all.

---

## 56. XML `unbound prefix`

Some old GPX files contain malformed XML namespace prefixes.

Example:

```text
unbound prefix: line 1395, column 127
```

This is a problem in the source GPX, not in the physiological analysis.

The file may need to be repaired or converted before it can be read.

---

## 57. Lots of raw HR values over plausible HRmax

Do not raise `--hrmax` merely because old files contain values such as:

```text
206
215
220
```

Inspect the sustained HRmax candidates and the surrounding ride context.

Old chest straps can produce convincing but false high-HR episodes.

---

## 58. A 4-hour ride has no `best_4h_hr`

Possible reasons include:

- the actual HR-recorded duration is less than four hours;
- insufficient valid HR samples;
- a stopped episode longer than five minutes;
- a recording/autopause gap longer than five minutes.

P10–P90 spread is **not** a rejection criterion.

---

## 59. VAM looks unexpectedly low

Check:

- bike;
- MTB vs road;
- tyre type;
- surface;
- gradient;
- whether the VAM window is marked comparable;
- whether the route is rolling rather than one sustained climb.

Do not compare all bikes as if they were equivalent.

---

# Design principles

The analysis deliberately follows a few conservative rules:

1. **Observed data before labels.**  
   Report 2h/4h sustained HR rather than automatically declaring LT1.

2. **Capabilities rather than prerequisites.**  
   Missing HR does not discard GPS, elevation, VAM or volume evidence.

3. **Hard efforts are not automatically interval sessions.**  
   Preserve detected hard blocks even when the ride fails the stricter structured-interval test.

4. **Sustained evidence before maxima.**  
   HRmax confidence uses 10s/30s/60s support rather than a one-second spike.

5. **60-minute evidence before numerical LT2.**  
   A hard 30-minute effort alone only provides a clue.

6. **Intervals are not direct LT2 tests.**

7. **Raw VAM stays raw.**  
   Bike metadata provides context instead of creating an artificial normalization formula.

8. **Historical sensor data is noisy.**  
   Repeated patterns matter more than isolated extremes.

9. **Training context matters.**  
   Annual volume, injury, lifestyle and bike use can explain large performance changes independently of ageing.

---

# Example project layout

```text
analysis/
├── scan_strava.py
├── activity_file_processor.py
├── analyze_training.py
├── cycling_2015.csv
├── cycling_2016.csv
└── ...

Strava/
├── activities.csv
└── activities/
    ├── 318152282.fit.gz
    ├── 341398533.fit.gz
    ├── ...
```

Example command from `analysis/`:

```bash
python3 scan_strava.py ../Strava/activities --hrmax 192 --year 2015 --sport cycling --output cycling_2015.csv --activities-csv ../Strava/activities.csv
```

---

# Important caveat

This project analyses historical exercise data and provides heuristic physiological evidence.

It is not a laboratory lactate test, metabolic cart, ECG or medical diagnostic tool.

Values such as HRmax, LT2 and long-duration HR should be interpreted as estimates and observations, especially when using old sensor data.

# Appendix
## Example output

```text
Supported files found: 212
Filtered out:          0
Activities processed: 210
With usable HR:       55
Without usable HR:    155
Errors:                1
CSV written to:        cycling_2022.csv

Season summary: 2022 / cycling
------------------------------------------------
Activities processed:             210
With usable HR:                   55
Without usable HR:                155
Errors:                           1
Activities in Strava metadata:    212
Total moving time:                170.6 h
Total distance:                   3404 km
Total elevation gain:             51664 m
Long rides >=3h / >=4h / >=6h:   6 / 4 / 1
Strong LT2 observations:          2
Moderate LT2 observations:        3
Median strong LT2 range:           156.8-160.8 bpm
Top 30m HR observations:           175.8, 169.3, 169.2
Top 60m HR observations:           172.8, 160.6, 157.7
Top 90m HR observations:           171.4, 149.6, 148.0
Highest credible HRmax candidates:
  183.0 bpm (high)  11 Mar 2022 11:26
  181.7 bpm (high)  12 Nov 2022 12:41
  180.0 bpm (high)  16 Oct 2022 14:21
  179.8 bpm (high)  08 Dec 2022 14:01
  179.5 bpm (high)  02 Oct 2022 12:25
Highest raw HR observations:        198, 197, 195, 192, 188
Qualifying 2h sustained windows:   12
Top 2h sustained HR observations:   164.2, 160.3, 157.4
Qualifying 4h sustained windows:   2
Top 4h sustained HR observations:   144.8, 143.6
Comparable VAM activities:         12
Top comparable 15m VAM:            946, 909, 888 m/h
Top comparable 30m VAM:            872, 846, 843 m/h
Top comparable 60m VAM:            801, 738, 725 m/h
Median comparable VAM retention:   93.2%
Activities with hard blocks:        (depends on selected period)
Total hard blocks:                  (depends on selected period)

VAM by bike (comparable activities)
------------------------------------------------
Commuter (23 rides, 10.2 kg)
  comparable VAM: 1
  15m VAM median/best: 842 / 842 m/h
  30m VAM median/best: 681 / 681 m/h
  60m VAM median/best: 434 / 434 m/h
  median retention: 80.9%
Spitfeur (13 rides, 8.2 kg)
  comparable VAM: 5
  15m VAM median/best: 846 / 875 m/h
  30m VAM median/best: 795 / 843 m/h
  60m VAM median/best: 711 / 738 m/h
  median retention: 93.3%
F60 (5 rides, 8.0 kg)
  comparable VAM: 3
  15m VAM median/best: 888 / 909 m/h
  30m VAM median/best: 846 / 872 m/h
  60m VAM median/best: 687 / 801 m/h
  median retention: 98.2%
unknown (4 rides)
  comparable VAM: 1
  15m VAM median/best: 760 / 760 m/h
  30m VAM median/best: 722 / 722 m/h
  60m VAM median/best: 508 / 508 m/h
  median retention: 95.0%
Winter Bike (1 rides)
  comparable VAM: 1
  15m VAM median/best: 858 / 858 m/h
  30m VAM median/best: 741 / 741 m/h
  60m VAM median/best: 710 / 710 m/h
  median retention: 86.4%

```

The analysis detected 6 interval sessions - I was trying to work on my climbing speed:
```text
  22 Aug 2022 16:05  Evening Ride: 4 detected hard-HR blocks; median 0:08:08 @ 166.8 bpm; median recovery 0:07:11 @ 139.1 bpm
  26 Aug 2022 10:16  Lunch Ride: 4 detected hard-HR blocks; median 0:08:04 @ 166.0 bpm; median recovery 0:03:03 @ 136.5 bpm
  31 Aug 2022 15:52  4x8s: 4 detected hard-HR blocks; median 0:08:02 @ 169.1 bpm; median recovery 0:02:39 @ 142.7 bpm
  05 Sep 2022 16:01  Evening Ride: 3 detected hard-HR blocks; median 0:08:35 @ 171.8 bpm; median recovery 0:02:58 @ 143.0 bpm
  27 Oct 2022 08:53  High plains grifter: 4 detected hard-HR blocks; median 0:05:51 @ 160.9 bpm; median recovery 0:34:23 @ 140.1 bpm
  08 Dec 2022 14:01  Afternoon Ride: 3 detected hard-HR blocks; median 0:09:19 @ 167.6 bpm; median recovery 0:04:26 @ 139.3 bpm
```

To drill down further in the CSV file for the 26th August ride it automatically
classifies it as an : _endurance    supra-threshold intervals_ session lasting _1:31:26_
and says it  detected : _4 hard-HR blocks_ with a _median duration of 0:08:04 @ 166.0 bpm  and a  median recovery 0:03:03 @ 136.5_ bpm and it gives the blocks as _0:08:22|0:07:47|0:07:36|0:10:06._


