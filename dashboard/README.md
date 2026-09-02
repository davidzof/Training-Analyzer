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
