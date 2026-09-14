# Training Analyser Dashboard

A deliberately small Streamlit dashboard for Training Analyser JSON exports.

The dashboard is a **consumer of the exported JSON only**. It does not import or depend on analyser modules. The JSON schema remains the interface between analysis and presentation.

## v4

- headline activity, moving-time, distance, elevation and HR Load totals
- weekly HR Load and weekly moving hours
- HR Intensity vs HR Load scatter plot
  - fixed-size markers
  - reference lines at HR Intensity 1.0 and HR Load 100
  - hover details
- sport filtering
- Activity Explorer
  - activity metrics
  - active HR-zone distribution
  - continuous endurance/tempo/hard effort timeline (hard takes display priority over overlapping tempo)
  - sustained HR evidence
  - VAM, interval and LT2 evidence where available
  - expandable raw activity JSON
- recent activity table
- embedded HR Load model parameters

## Run

From the `dashboard` directory:

```bash
python -m pip install -r requirements.txt
streamlit run app.py
```

Then upload a Training Analyser JSON export in the sidebar.

## Design principle

The dashboard remains a presentation layer. New analysis should normally be added to Training Analyser and exported in the JSON rather than calculated silently in the dashboard.

- Location labels are displayed when supplied by analyser schema v3+


## v4.11

- Shows average cadence alongside hard-block duration and HR when present.
- Keeps cadence detail in the hard-block list and removes the separate interval-cadence chart.
- Cadence is omitted automatically when unavailable.


### v4.11
Fixed a NameError after removal of the interval cadence chart: the interval average cadence is now initialised independently and remains available in the textual interval summary.


### v4.12

- Top-level Distance and Elevation cards now prefer the analyser-exported `summary.volume.distance_km` and `summary.volume.elevation_gain_m` values, falling back to activity sums only if those summary fields are absent.


### v4.13

- Adds tempo-block detail beneath the sustained-effort timeline.
- Hard blocks are visually nested beneath the tempo block that contains them, making it explicit that the harder LT2-level efforts are part of the broader sustained tempo effort.
- Hard blocks that do not fall inside a tempo block remain visible separately.

## v4.14

- The **Intensity vs Load** scatter plot is now clickable. Clicking an activity point opens the matching activity in **Activity Explorer**.
- The clicked point is enlarged while selected; double-click clears the chart selection.
- Navigation uses the exported activity key only; no additional activity data are loaded or inferred.



## v4.15 — HR-duration curve

Adds a Heart-rate duration curve section for analyser schema 5 / project 31.8 exports.

- Annual best and rolling 8-week snapshots can be selected.
- Combined or individual-sport curves can be displayed.
- HRmax, LT2 and LT1 are overlaid as reference lines when present in the export.
- The duration axis is explicitly logarithmic so durations from 1 minute to 4 hours remain legible without pretending they are evenly spaced.
- Hovering a point shows the source activity and date.
- The dashboard still only reads analyser JSON and performs no physiological inference.


## v4.16 — HR-duration P95

- Adds a **Curve statistic** selector: **Best observed** or **95th percentile**.
- P95 reads the analyser's activity-level percentile curve and does not calculate physiology in the dashboard.
- Tooltips show the number of qualifying activities at each duration.
- Best-observed tooltips continue to show the source activity/date.
- Durations with fewer than 8 qualifying activities are intentionally absent from the P95 curve.
