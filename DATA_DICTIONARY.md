# Training Analyser Data Dictionary

## Overview

> The data should be interpreted as **evidence**, not as laboratory truth.


## Activity Identity and Metadata

### `filename`
Original GPX, TCX or FIT filename.

### `activity_date`
Date and time when the activity started.

### `activity_type`
Normalised sport type, for example `cycling`, `running`, `walking`, `hiking`, `skiing` or `roller skiing`.

### `strava_activity_id`
Strava activity ID where available from `activities.csv`.

### `activity_name`
Activity title from Strava metadata.

### `activity_gear`
Equipment recorded by Strava, such as a bicycle, running shoes or skis.

### `bike_id`
Strava bicycle identifier where applicable.

### `bike_weight`
Bike weight from Strava metadata where available.

### `athlete_weight`
Athlete weight recorded in Strava metadata.

## Location

### `start_lat` / `start_lon`
Approximate coordinates of the first valid moving GPS point.

### `start_city`
Reverse-geocoded town or locality.

### `start_region`
Region, department, county or state.

### `start_country`
Country.

### `start_location`
Human-readable location such as `Saint-Égrève, Isère, France`.

The location is intended as activity context rather than precise geolocation.

## Duration and Movement

### `duration`
Total elapsed activity duration. This may include stops.

### `moving_time`
Moving time from Strava metadata where available. This is distinct from elapsed duration.

For example:

```text
duration = 4:00:00
moving_time = 3:30:00
```
Note short stops for photographs or other are ignored.

## Cadence

### `average_cadence_rpm`
Average recorded cadence in revolutions per minute where available.

The value may come from Strava metadata or recorded cadence samples in GPX, TCX or FIT.

Missing cadence remains `null`; it is not inferred.

## Basic Heart-Rate Fields

### `average_hr`
Mean heart rate after the analyser's cleaning rules.

### `raw_max_hr`
Highest raw HR value found in the file. This may include sensor artefacts and should not automatically be interpreted as physiological HRmax.

### `analysed_max_hr`
Highest HR accepted after cleaning and artefact filtering. This is generally more useful than `raw_max_hr`.

### `excluded_hr_samples`
Number of HR samples rejected as invalid or artefactual.

### `hr_artefact`
Indicates that suspicious HR data were detected.

## HRmax Evidence

### `hrmax_10s`
Highest approximately 10-second sustained HR observation.

### `hrmax_30s`
Highest approximately 30-second sustained HR observation.

### `hrmax_60s`
Highest approximately 60-second sustained HR observation.

### `hrmax_candidate`
Candidate physiological HRmax suggested by the activity. This is evidence, not a laboratory measurement.

### `hrmax_confidence`
Confidence assigned to the HRmax candidate.

### `hrmax_reason`
Human-readable explanation of why the candidate was accepted or rejected.

## Sustained Heart-Rate Evidence

### `best_30m_hr`
Highest qualifying average HR over approximately 30 minutes.

### `best_60m_hr`
Highest qualifying average HR over approximately 60 minutes. This is particularly useful as evidence when considering LT2.

### `best_90m_hr`
Highest qualifying average HR over approximately 90 minutes.

### `best_2h_hr`
Highest qualifying average HR over a sustained two-hour period. This is endurance evidence and should **not** be interpreted directly as LT1.

### `best_4h_hr`
Highest qualifying average HR over a sustained four-hour period. This is also long-duration endurance evidence rather than an LT1 estimate.

### Long-duration quality fields

The analyser may also provide:

- `best_2h_moving_fraction`
- `best_2h_hr_p10`
- `best_2h_hr_p90`
- `best_4h_moving_fraction`
- `best_4h_hr_p10`
- `best_4h_hr_p90`

These help describe how steady or variable the effort was.

## Active Heart-Rate Zones

Training Analyser uses the supplied LT1 and LT2 thresholds to divide active HR time into three physiological domains.

### `active_zone1_seconds`
Active time below LT1.

### `active_zone2_seconds`
Active time between LT1 and LT2.

### `active_zone3_seconds`
Active time above LT2.

### `active_zone_total_seconds`
Total active HR time used in the zone calculation.

Equivalent percentage fields are:

- `active_zone1_pct`
- `active_zone2_pct`
- `active_zone3_pct`

For training interpretation, these `active_zone...` fields are usually more useful than the broader recorded-zone fields because they aim to exclude stationary periods.

## HR Intensity

### `hr_intensity`

HR Intensity is a custom, duration-independent measure of cardiovascular intensity.

It answers:

> **How hard was this activity cardiovascularly?**

The analyser uses a nonlinear HR weighting curve with these reference points:

```text
LT1   = weight 1.0
LT2   = weight 2.75
HRmax = weight 9.0
```

The average weighted HR is then normalised to LT2.

Therefore:

```text
HR Intensity = 1.0
```

means:

> The activity had the same average weighted cardiovascular intensity as exercising continuously at LT2.

It does **not necessarily mean** that average HR was exactly LT2. A session alternating between easier work and periods well above LT2 could also produce an HR Intensity near 1.0.

Approximate interpretation:

| HR Intensity | Approximate meaning |
|---:|---|
| ~0.36 | Approximately continuous LT1 intensity |
| 0.4–0.5 | Easy to moderate endurance |
| 0.5–0.7 | Moderate to demanding endurance/tempo |
| 0.7–1.0 | Hard sustained cardiovascular work |
| 1.0 | LT2-equivalent average intensity |
| >1.0 | Average cardiovascular intensity above the LT2 reference |
| 1.5+ | Very hard activity, usually with substantial high-HR work |

HR Intensity is independent of duration.

## HR Load

### `hr_load`

HR Load combines activity duration with HR Intensity.

It answers:

> **How much cardiovascular training load accumulated?**

The basic relationship is:

```text
HR Load = duration in hours × HR Intensity × 100
```

The reference point is:

```text
1 hour at LT2 = HR Load 100
```

Examples:

| Activity | HR Intensity | Duration | HR Load |
|---|---:|---:|---:|
| 1 h near LT1 | 0.36 | 1 h | ~36 |
| 1 h at LT2 | 1.00 | 1 h | 100 |
| 2 h at moderate intensity | 0.50 | 2 h | 100 |
| 3 h at 0.42 | 0.42 | 3 h | ~126 |
| 45 min at 1.40 | 1.40 | 0.75 h | ~105 |

HR Load and HR Intensity should normally be interpreted together.

HR Load is not TSS and HR Intensity is not power-based IF.

## Hard Effort Blocks

### `hard_block_count`
Number of sustained hard effort blocks detected.

### `hard_block_threshold_bpm`
HR threshold used for hard block detection, generally related to LT2.

### `hard_blocks`
List of sustained hard cardiovascular efforts, including properties such as start, end, duration, average HR and maximum HR.

These should not automatically be labelled VO2max intervals.

### `hard_block_gaps`
Information about gaps between hard blocks, useful when distinguishing structured intervals from terrain-driven variations.

## Tempo Blocks

### `tempo_block_count`
Number of sustained tempo/endurance blocks detected.

### `tempo_blocks`
Sustained periods beginning around LT1 or above. The detector allows short excursions below LT1, excursions above LT2 and brief interruptions.

Hard and tempo blocks may overlap in the raw analyser evidence.

## Interval Detection

Relevant fields include:

- `interval_count`
- `interval_work_total`
- `interval_work_median`
- `interval_work_avg_hr`
- `interval_work_max_hr`
- `interval_recovery_median`
- `interval_recovery_avg_hr`
- `interval_work_durations`
- `interval_work_avg_hrs`
- `interval_work_max_hrs`
- `interval_recovery_durations`
- `interval_recovery_avg_hrs`
- `interval_summary`

These describe the structure of a possible repeated work/recovery session.

Important interpretation rules:

- Interval detection does not prove that the session was deliberately structured.
- Repeated climbs can sometimes appear interval-like.
- HR-only intervals should not automatically be called VO2max intervals.
- Interval detection must not be used directly to estimate LT2.

Depending on the evidence, terms such as `threshold intervals`, `supra-threshold intervals` or `very hard intervals` may be more appropriate.

## Activity Classification

### `overall_ride`
Broad interpretation of the activity.

### `key_effort`
Most notable detected effort.

### `classification`
Compact description of the session, for example:

```text
easy endurance / recovery
endurance ride with sustained tempo effort
endurance ride with sustained hard effort
interval session
```

The classification is an interpretation of the underlying evidence, not a physiological measurement.

### `confidence`
Confidence in the activity classification.

## LT2 Evidence

### `lt2_low`
Lower bound of a possible LT2 range where sufficient evidence exists.

### `lt2_high`
Upper bound of the possible LT2 range.

### `lt2_evidence`
Type or strength of evidence supporting the estimate.

### `lt2_reason`
Human-readable explanation of the LT2 assessment.

### `lt2_clue`
Additional supporting clue where appropriate.

> A strong 30-minute effort alone should **not** be used to generate a numerical LT2 estimate. Credible sustained approximately 60-minute evidence is much stronger. HR alone cannot locate LT2 with laboratory precision.

## VAM and Climbing Evidence

VAM is vertical ascent rate in metres per hour.

### `vam_15`
Best qualifying 15-minute VAM.

### `vam_30`
Best qualifying 30-minute VAM.

### `vam_60`
Best qualifying 60-minute VAM.

### `vam_retention_pct`
Indicates how well climbing rate is maintained over longer durations.

### `vam_comparison`
Human-readable interpretation of the VAM evidence.

VAM can be useful when comparing similar climbs, but it is not a power measurement. It can be affected by gradient, bicycle, road surface, terrain, altitude, wind, body mass and pacing.

## Distance and Elevation

### `distance_km`
Activity distance in kilometres.

### `elevation_gain_m`
Total accumulated elevation gain in metres.

## Data Availability Flags

### `has_hr`
Whether usable heart-rate data exists.

### `has_gps`
Whether usable GPS data exists.

### `has_elevation`
Whether usable elevation data exists.

### `has_power`
Whether recorded power data exists.

Training Analyser does not create pseudo-power when power is missing.

## Status and Errors

### `status`
Activity processing status, normally `ok` or `error`.

### `error`
Description of the problem if the activity could not be analysed.

An activity with `status: "error"` should not be interpreted as having zero values.

## Missing Data

Throughout the JSON:

```json
null
```

means the value is unavailable, unknown or could not be established.

It does **not** mean zero.

For example:

```json
"average_cadence_rpm": null
```

means cadence was not available, not that cadence was 0 rpm.

## Recommended Interpretation Order

When analysing a single activity, a human or LLM should roughly consider the fields in this order:

1. **Sport** — `activity_type`
2. **Duration and context** — `duration`, `moving_time`, distance, elevation, equipment and location
3. **How hard was it?** — `hr_intensity`
4. **How much total cardiovascular load accumulated?** — `hr_load`
5. **Where was HR relative to LT1 and LT2?** — active zone percentages
6. **Was the work continuous or intermittent?** — tempo blocks, hard blocks and interval fields
7. **Was there useful physiological evidence?** — sustained HR, LT2 evidence and HRmax evidence
8. **What does the classification say?** — `classification`, `key_effort`, `overall_ride`
9. **Are there data-quality caveats?** — HR artefacts, excluded samples, missing data and processing errors

## Summary

Training Analyser is intended to turn large collections of raw endurance-training files into a smaller set of transparent evidence.

The most important distinction is:

```text
HR Intensity = how hard
HR Load      = how much
```

with:

```text
HR Intensity 1.0 = LT2-equivalent average cardiovascular intensity
HR Load 100      = approximately one hour at LT2
```

The analyser should be used to support longitudinal interpretation rather than to manufacture precise physiological values from insufficient evidence.
