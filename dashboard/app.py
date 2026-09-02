import streamlit as st

from data import (
    load_training_json,
    build_weekly_dataframe,
    build_activity_dataframe,
    build_summary_metrics,
    find_activity,
)
from charts import (
    weekly_load_chart,
    weekly_hours_chart,
    intensity_load_chart,
    zone_distribution_chart,
    effort_timeline_chart,
)

st.set_page_config(page_title="Training Analyser", page_icon="📈", layout="wide")

st.title("Training Analyser")
st.caption("Long-term endurance training data, reduced to the metrics that matter.")


def _as_float(value):
    """Return a finite float for numeric display fields, else None."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None


with st.sidebar:
    st.header("Data")
    uploaded = st.file_uploader("Open analyser JSON", type=["json"])
    st.caption("The dashboard reads the exported JSON only. It does not import analyser code.")
    st.divider()
    st.header("Filters")

if uploaded is None:
    st.info("Choose a Training Analyser JSON export to begin.")
    st.stop()

try:
    training = load_training_json(uploaded)
except Exception as exc:
    st.error(f"Could not read this JSON file: {exc}")
    st.stop()

schema = training.get("schema_version")
project = training.get("project_version")
summary = training.get("summary", {})
period = summary.get("period", {})

with st.sidebar:
    st.write(f"Schema: **{schema}**")
    if project is not None:
        st.write(f"Project version: **{project}**")

activity_df = build_activity_dataframe(training)
weekly_df = build_weekly_dataframe(training)

if activity_df.empty:
    st.warning("No activities were found in this export.")
    st.stop()

sport_options = sorted(activity_df["sport"].dropna().unique().tolist())
selected_sports = st.sidebar.multiselect("Sports", options=sport_options, default=sport_options)
filtered = activity_df[activity_df["sport"].isin(selected_sports)].copy()

if filtered.empty:
    st.warning("No activities match the current filters.")
    st.stop()

metrics = build_summary_metrics(filtered)

# Distance and elevation are authoritative analyser summary values.
# Summing per-activity values can be distorted by malformed or legacy track metadata.
volume_summary = summary.get("volume", {}) or {}
summary_distance_km = _as_float(volume_summary.get("distance_km"))
summary_elevation_gain_m = _as_float(volume_summary.get("elevation_gain_m"))

if period.get("start") and period.get("end_exclusive"):
    st.caption(f"{period['start']} → {period['end_exclusive']}")

k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Activities", f"{metrics['activities']:,}")
k2.metric("Moving hours", f"{metrics['moving_hours']:.1f}")
k3.metric("HR Load", f"{metrics['hr_load']:.0f}")
k4.metric("Distance", f"{summary_distance_km:.0f} km" if summary_distance_km is not None else f"{metrics['distance_km']:.0f} km")
k5.metric("Elevation", f"{summary_elevation_gain_m:.0f} m" if summary_elevation_gain_m is not None else f"{metrics['elevation_gain_m']:.0f} m")

st.divider()
left, right = st.columns(2)
with left:
    st.subheader("Weekly HR Load")
    weekly_load_chart(weekly_df)
with right:
    st.subheader("Weekly training volume")
    weekly_hours_chart(weekly_df)

st.divider()
st.subheader("Intensity vs Load")
st.caption(
    "Rightwards = harder minute-for-minute. Upwards = more accumulated cardiovascular stress. "
    "Dashed reference lines mark HR Intensity 1.0 and HR Load 100."
)
intensity_load_chart(filtered)

st.divider()
st.subheader("Activity Explorer")
st.caption("Select an activity to inspect what the analyser extracted from it.")

selector_df = filtered.sort_values("date", ascending=False).copy()
def _activity_selector_label(row):
    sport = str(row["sport"]).replace("_", " ").title()
    label = f"{row['date'].strftime('%d %b %Y')} — {sport} — {row['name']}"
    if row.get("location"):
        label += f" — {row['location']}"
    return label

selector_df["selector"] = selector_df.apply(_activity_selector_label, axis=1)
selection = st.selectbox("Activity", selector_df["selector"].tolist(), index=0, label_visibility="collapsed")
selected_row = selector_df.loc[selector_df["selector"] == selection].iloc[0]
activity = find_activity(training, selected_row["activity_key"])

if activity:
    moving_time = activity.get("moving_time") or activity.get("moving_duration")
    cadence = _as_float(activity.get("average_cadence_rpm"))

    top = st.columns(8)
    top[0].metric("Duration", activity.get("duration") or "—")
    top[1].metric("Moving", moving_time or "—")
    top[2].metric("Avg HR", f"{activity['average_hr']:.0f} bpm" if activity.get("average_hr") is not None else "—")
    top[3].metric("Max HR", f"{activity['analysed_max_hr']:.0f} bpm" if activity.get("analysed_max_hr") is not None else "—")
    top[4].metric("HR Intensity", f"{activity['hr_intensity']:.3f}" if activity.get("hr_intensity") is not None else "—")
    top[5].metric("HR Load", f"{activity['hr_load']:.1f}" if activity.get("hr_load") is not None else "—")
    top[6].metric("Distance", f"{activity['distance_km']:.1f} km" if activity.get("distance_km") is not None else "—")
    top[7].metric("Elevation", f"{activity['elevation_gain_m']:.0f} m" if activity.get("elevation_gain_m") is not None else "—")

    context_bits = []
    if activity.get("start_location"):
        context_bits.append(activity["start_location"])
    if activity.get("activity_gear"):
        context_bits.append(activity["activity_gear"])
    if cadence is not None:
        context_bits.append(f"{cadence:.0f} rpm avg cadence")
    if context_bits:
        st.caption(" · ".join(context_bits))

    classification = activity.get("classification") or "Unclassified"
    confidence = activity.get("confidence")
    st.markdown(f"**{classification}**" + (f" · confidence: {confidence}" if confidence else ""))

    detail_left, detail_right = st.columns(2)
    with detail_left:
        st.markdown("#### Active HR zones")
        zone_distribution_chart(activity)
    with detail_right:
        st.markdown("#### Sustained efforts")
        effort_timeline_chart(activity)

        hard_blocks = activity.get("hard_blocks", []) or []
        if hard_blocks:
            hard_lines = []
            for index, block in enumerate(hard_blocks, start=1):
                duration_seconds = block.get("duration_seconds")
                if duration_seconds is not None:
                    mins, secs = divmod(int(round(duration_seconds)), 60)
                    duration_label = f"{mins}:{secs:02d}"
                else:
                    duration_label = "—"

                avg_hr = block.get("average_hr_bpm")
                max_hr = block.get("max_hr_bpm")
                block_cadence = _as_float(block.get("average_cadence_rpm"))

                bits = [duration_label]
                if avg_hr is not None:
                    bits.append(f"{avg_hr:.1f} bpm avg")
                if max_hr is not None:
                    bits.append(f"{max_hr:.0f} bpm max")
                if block_cadence is not None:
                    bits.append(f"{block_cadence:.1f} rpm")
                hard_lines.append(f"**{index}.** " + " · ".join(bits))

            st.caption("Hard blocks")
            for line in hard_lines:
                st.markdown(line)

    # Interval cadence is still useful in the textual interval summary even
    # though the separate cadence chart was removed in v4.10.
    interval_avg_cadence = _as_float(activity.get("interval_work_avg_cadence_rpm"))

    evidence_left, evidence_right = st.columns(2)
    with evidence_left:
        st.markdown("#### Heart-rate evidence")
        hr_rows = [
            ("Max analysed HR", activity.get("analysed_max_hr"), "bpm"),
            ("Best 30 min HR", activity.get("best_30m_hr"), "bpm"),
            ("Best 60 min HR", activity.get("best_60m_hr"), "bpm"),
            ("Best 90 min HR", activity.get("best_90m_hr"), "bpm"),
            ("Best 2 h HR", activity.get("best_2h_hr"), "bpm"),
            ("Best 4 h HR", activity.get("best_4h_hr"), "bpm"),
        ]
        shown = False
        for label, value, unit in hr_rows:
            if value is not None:
                shown = True
                st.write(f"**{label}:** {value:.1f} {unit}")
        if not shown:
            st.caption("No sustained HR evidence available.")

    with evidence_right:
        st.markdown("#### Climbing / effort evidence")
        shown = False
        for label, key in [("VAM 15 min", "vam_15"), ("VAM 30 min", "vam_30"), ("VAM 60 min", "vam_60")]:
            value = activity.get(key)
            if value is not None:
                shown = True
                st.write(f"**{label}:** {value:.0f} m/h")
        if activity.get("interval_summary"):
            shown = True
            interval_text = activity["interval_summary"]
            if interval_avg_cadence is not None:
                interval_text += f" · {interval_avg_cadence:.1f} rpm avg cadence"
            st.write(f"**Intervals:** {interval_text}")
        if activity.get("key_effort"):
            shown = True
            st.write(f"**Key effort:** {activity['key_effort']}")
        if activity.get("lt2_reason") and activity.get("lt2_reason") != "no suitable sustained hard effort":
            shown = True
            st.write(f"**LT2 evidence:** {activity.get('lt2_evidence', '—')} — {activity['lt2_reason']}")
        if not shown:
            st.caption("No additional effort evidence available.")

    with st.expander("Raw activity details"):
        st.json(activity)

st.divider()
st.subheader("Recent activities")
recent = filtered.sort_values("date", ascending=False).head(20).copy()
recent = recent[["date", "name", "sport", "location", "duration", "average_hr", "hr_intensity", "hr_load", "classification"]].rename(
    columns={
        "date": "Date",
        "name": "Activity",
        "sport": "Sport",
        "location": "Location",
        "duration": "Duration",
        "average_hr": "Avg HR",
        "hr_intensity": "HR Intensity",
        "hr_load": "HR Load",
        "classification": "Classification",
    }
)
st.dataframe(
    recent,
    use_container_width=True,
    hide_index=True,
    column_config={
        "Date": st.column_config.DatetimeColumn(format="DD MMM YYYY"),
        "Avg HR": st.column_config.NumberColumn(format="%.1f"),
        "HR Intensity": st.column_config.NumberColumn(format="%.3f"),
        "HR Load": st.column_config.NumberColumn(format="%.1f"),
    },
)

st.divider()
with st.expander("About HR Intensity and HR Load"):
    params = training.get("analysis_parameters", {})
    model = params.get("hr_load_model", {})
    st.markdown(
        f"""
**Thresholds in this export**

- LT1: `{params.get('lt1_bpm', '—')}` bpm
- LT2: `{params.get('lt2_bpm', '—')}` bpm
- HRmax: `{params.get('hrmax_bpm', '—')}` bpm
- Minimum HR anchor: `{params.get('min_hr_bpm', '—')}` bpm

**Model anchors**

- LT1 weight: `{model.get('lt1_weight', '—')}`
- LT2 weight: `{model.get('lt2_weight', '—')}`
- HRmax weight: `{model.get('hrmax_weight', '—')}`
- Below-LT1 exponent: `{model.get('below_lt1_exponent', '—')}`
- Normalisation: `{model.get('normalization', '—')}`
"""
    )
