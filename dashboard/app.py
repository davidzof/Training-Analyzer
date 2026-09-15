import streamlit as st

from data import (
    load_training_json,
    build_weekly_dataframe,
    build_activity_dataframe,
    build_summary_metrics,
    find_activity,
)
from i18n import t
from charts import (
    weekly_load_chart,
    weekly_hours_chart,
    hr_duration_curve_chart,
    hr_duration_rolling_chart,
    intensity_load_chart,
    zone_distribution_chart,
    effort_timeline_chart,
)

st.set_page_config(page_title="Training Analyser", page_icon="📈", layout="wide")

LANG_OPTIONS = {"English": "en", "Français": "fr"}
with st.sidebar:
    language_name = st.selectbox("Language / Langue", list(LANG_OPTIONS), key="dashboard_language")
lang = LANG_OPTIONS[language_name]

st.title(t("app_title", lang))
st.caption(t("app_caption", lang))


def _as_float(value):
    """Return a finite float for numeric display fields, else None."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def _duration_label(seconds):
    if seconds is None:
        return "—"
    try:
        total = int(round(float(seconds)))
    except (TypeError, ValueError):
        return "—"
    hours, rem = divmod(total, 3600)
    mins, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{mins:02d}:{secs:02d}"
    return f"{mins}:{secs:02d}"


def _clock_seconds(value):
    """Convert HH:MM:SS to seconds since midnight for block nesting."""
    if not value or not isinstance(value, str):
        return None
    try:
        parts = [int(part) for part in value.split(":")]
        if len(parts) != 3:
            return None
        hours, minutes, seconds = parts
        return hours * 3600 + minutes * 60 + seconds
    except (TypeError, ValueError):
        return None


def _block_is_within(child, parent):
    child_start = _clock_seconds(child.get("start"))
    child_end = _clock_seconds(child.get("end"))
    parent_start = _clock_seconds(parent.get("start"))
    parent_end = _clock_seconds(parent.get("end"))
    if None in (child_start, child_end, parent_start, parent_end):
        return False
    return child_start >= parent_start and child_end <= parent_end


def _hard_block_line(index, block, lang="en"):
    bits = [_duration_label(block.get("duration_seconds"))]
    avg_hr = _as_float(block.get("average_hr_bpm"))
    max_hr = _as_float(block.get("max_hr_bpm"))
    block_cadence = _as_float(block.get("average_cadence_rpm"))
    if avg_hr is not None:
        bits.append(f"{avg_hr:.1f} bpm {t('average', lang)}")
    if max_hr is not None:
        bits.append(f"{max_hr:.0f} bpm {t('maximum', lang)}")
    if block_cadence is not None:
        bits.append(f"{block_cadence:.1f} rpm")
    return f"**{index}.** " + " · ".join(bits)


def _tempo_block_line(index, block, nested_count, lang="en"):
    bits = [_duration_label(block.get("duration_seconds"))]
    avg_hr = _as_float(block.get("average_hr_bpm"))
    max_hr = _as_float(block.get("max_hr_bpm"))
    above_lt1 = _as_float(block.get("above_lt1_fraction"))
    above_lt2 = _as_float(block.get("above_lt2_fraction"))
    if avg_hr is not None:
        bits.append(f"{avg_hr:.1f} bpm {t('average', lang)}")
    if max_hr is not None:
        bits.append(f"{max_hr:.0f} bpm {t('maximum', lang)}")
    if above_lt1 is not None:
        bits.append(f"{above_lt1 * 100:.1f}% {t('above', lang)} LT1")
    if above_lt2 is not None:
        bits.append(f"{above_lt2 * 100:.1f}% {t('above', lang)} LT2")
    plural = "s" if (lang == "en" and nested_count != 1) else ("s" if (lang == "fr" and nested_count != 1) else "")
    suffix = " · " + t("contains_hard", lang, count=nested_count, plural=plural)
    return f"**{t('tempo', lang)} {index}.** " + " · ".join(bits) + suffix


with st.sidebar:
    st.header(t("data", lang))
    uploaded = st.file_uploader(t("open_json", lang), type=["json"])
    st.caption(t("json_caption", lang))
    st.divider()
    st.header(t("filters", lang))

if uploaded is None:
    st.info(t("choose_json", lang))
    st.stop()

try:
    training = load_training_json(uploaded)
except Exception as exc:
    st.error(t("read_error", lang, error=exc))
    st.stop()

schema = training.get("schema_version")
project = training.get("project_version")
summary = training.get("summary", {})
period = summary.get("period", {})

with st.sidebar:
    st.write(f"{t('schema', lang)}: **{schema}**")
    if project is not None:
        st.write(f"{t('project_version', lang)}: **{project}**")

activity_df = build_activity_dataframe(training)
weekly_df = build_weekly_dataframe(training)

if activity_df.empty:
    st.warning(t("no_activities", lang))
    st.stop()

sport_options = sorted(activity_df["sport"].dropna().unique().tolist())
selected_sports = st.sidebar.multiselect(t("sports", lang), options=sport_options, default=sport_options)
filtered = activity_df[activity_df["sport"].isin(selected_sports)].copy()

if filtered.empty:
    st.warning(t("no_filter_activities", lang))
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
k1.metric(t("activities", lang), f"{metrics['activities']:,}")
k2.metric(t("moving_hours", lang), f"{metrics['moving_hours']:.1f}")
k3.metric(t("hr_load", lang), f"{metrics['hr_load']:.0f}")
k4.metric(t("distance", lang), f"{summary_distance_km:.0f} km" if summary_distance_km is not None else f"{metrics['distance_km']:.0f} km")
k5.metric(t("elevation", lang), f"{summary_elevation_gain_m:.0f} m" if summary_elevation_gain_m is not None else f"{metrics['elevation_gain_m']:.0f} m")

st.divider()
left, right = st.columns(2)
with left:
    st.subheader(t("weekly_hr_load", lang))
    weekly_load_chart(weekly_df, lang=lang)
with right:
    st.subheader(t("weekly_volume", lang))
    weekly_hours_chart(weekly_df, lang=lang)

st.divider()
st.subheader(t("hr_durability", lang))
st.caption(
    t("hr_durability_caption", lang)
)
curve_data = (summary.get("heart_rate", {}) or {}).get("duration_curve", {}) or {}
annual_curve = curve_data.get("annual", {}) or {}
rolling_curves = curve_data.get("rolling_8_week", []) or []
curve_period = st.selectbox(
    t("period", lang),
    ["Annual best", "Rolling 8-week history"],
    format_func=lambda x: t("annual_best", lang) if x == "Annual best" else t("rolling_history", lang),
    key="hr_curve_period",
)

all_curve_sports = set((annual_curve.get("by_sport", {}) or {}).keys())
for item in rolling_curves:
    all_curve_sports.update((item.get("by_sport", {}) or {}).keys())
curve_sport_options = ["Combined"] + sorted(all_curve_sports)
curve_sport = st.selectbox(t("sport", lang), curve_sport_options, key="hr_curve_sport", format_func=lambda x: t("combined", lang) if x == "Combined" else x)
curve_statistic = st.selectbox(
    t("statistic", lang),
    ["Best observed", "95th percentile"],
    format_func=lambda x: t("best_observed", lang) if x == "Best observed" else t("p95", lang),
    key="hr_curve_statistic",
    help=t("p95_help", lang),
)
use_p95 = curve_statistic == "95th percentile"
params = training.get("analysis_parameters", {}) or {}

if curve_period == "Annual best":
    if curve_sport == "Combined":
        curve_points = annual_curve.get("p95_all" if use_p95 else "all", []) or []
    else:
        curve_points = (annual_curve.get("p95_by_sport" if use_p95 else "by_sport", {}) or {}).get(curve_sport, []) or []
    hr_duration_curve_chart(
        curve_points,
        hrmax=params.get("hrmax_bpm"),
        lt1=params.get("lt1_bpm"),
        lt2=params.get("lt2_bpm"),
        statistic_label=t("p95", lang) if use_p95 else t("best_observed", lang),
        lang=lang,
    )
else:
    hr_duration_rolling_chart(
        rolling_curves,
        sport=curve_sport,
        use_p95=use_p95,
        hrmax=params.get("hrmax_bpm"),
        lt1=params.get("lt1_bpm"),
        lt2=params.get("lt2_bpm"),
        statistic_label=t("p95", lang) if use_p95 else t("best_observed", lang),
        lang=lang,
    )

st.divider()
st.subheader(t("intensity_vs_load", lang))
st.caption(
    t("intensity_caption", lang)
)
intensity_load_chart(filtered, lang=lang)

st.divider()
st.subheader(t("activity_explorer", lang))
st.caption(t("activity_explorer_caption", lang))

selector_df = filtered.sort_values("date", ascending=False).copy()
def _activity_selector_label(row):
    sport = str(row["sport"]).replace("_", " ").title()
    label = f"{row['date'].strftime('%d %b %Y')} — {sport} — {row['name']}"
    if row.get("location"):
        label += f" — {row['location']}"
    return label

selector_df["selector"] = selector_df.apply(_activity_selector_label, axis=1)
selector_options = selector_df["selector"].tolist()

# A scatter-plot click is queued by the chart callback before this widget is
# created. Translate its stable activity key into the selectbox label, then
# let the normal Activity Explorer workflow take over.
pending_activity_key = st.session_state.pop("pending_activity_key", None)
if pending_activity_key:
    clicked_rows = selector_df.loc[selector_df["activity_key"] == pending_activity_key]
    if not clicked_rows.empty:
        st.session_state["activity_selector"] = clicked_rows.iloc[0]["selector"]

# Filters can remove an activity that was previously selected. Reset cleanly
# rather than leaving Streamlit with a selectbox value that is no longer valid.
if st.session_state.get("activity_selector") not in selector_options:
    st.session_state["activity_selector"] = selector_options[0]

selection = st.selectbox(
    t("activity", lang),
    selector_options,
    index=0,
    key="activity_selector",
    label_visibility="collapsed",
)
selected_row = selector_df.loc[selector_df["selector"] == selection].iloc[0]
activity = find_activity(training, selected_row["activity_key"])

if activity:
    moving_time = activity.get("moving_time") or activity.get("moving_duration")
    cadence = _as_float(activity.get("average_cadence_rpm"))

    top = st.columns(8)
    top[0].metric(t("duration", lang), activity.get("duration") or "—")
    top[1].metric(t("moving", lang), moving_time or "—")
    top[2].metric(t("avg_hr", lang), f"{activity['average_hr']:.0f} bpm" if activity.get("average_hr") is not None else "—")
    top[3].metric(t("max_hr", lang), f"{activity['analysed_max_hr']:.0f} bpm" if activity.get("analysed_max_hr") is not None else "—")
    top[4].metric(t("hr_intensity", lang), f"{activity['hr_intensity']:.3f}" if activity.get("hr_intensity") is not None else "—")
    top[5].metric(t("hr_load", lang), f"{activity['hr_load']:.1f}" if activity.get("hr_load") is not None else "—")
    top[6].metric(t("distance", lang), f"{activity['distance_km']:.1f} km" if activity.get("distance_km") is not None else "—")
    top[7].metric(t("elevation", lang), f"{activity['elevation_gain_m']:.0f} m" if activity.get("elevation_gain_m") is not None else "—")

    context_bits = []
    if activity.get("start_location"):
        context_bits.append(activity["start_location"])
    if activity.get("activity_gear"):
        context_bits.append(activity["activity_gear"])
    if cadence is not None:
        context_bits.append(f"{cadence:.0f} rpm {t('avg_cadence', lang)}")
    if context_bits:
        st.caption(" · ".join(context_bits))

    classification = activity.get("classification") or t("unclassified", lang)
    confidence = activity.get("confidence")
    st.markdown(f"**{classification}**" + (f" · {t('confidence', lang)}: {confidence}" if confidence else ""))

    detail_left, detail_right = st.columns(2)
    with detail_left:
        st.markdown(f"#### {t('active_hr_zones', lang)}")
        zone_distribution_chart(activity, lang=lang)
    with detail_right:
        st.markdown(f"#### {t('sustained_efforts', lang)}")
        effort_timeline_chart(activity, lang=lang)

        hard_blocks = activity.get("hard_blocks", []) or []
        tempo_blocks = activity.get("tempo_blocks", []) or []

        if tempo_blocks:
            st.caption(t("tempo_nested", lang))
            assigned_hard = set()
            for tempo_index, tempo in enumerate(tempo_blocks, start=1):
                nested = [
                    (hard_index, hard)
                    for hard_index, hard in enumerate(hard_blocks, start=1)
                    if _block_is_within(hard, tempo)
                ]
                st.markdown(_tempo_block_line(tempo_index, tempo, len(nested), lang))
                for hard_index, hard in nested:
                    assigned_hard.add(hard_index - 1)
                    st.markdown(f"&nbsp;&nbsp;&nbsp;&nbsp;↳ {_hard_block_line(hard_index, hard, lang)}", unsafe_allow_html=True)

            unassigned = [
                (hard_index, hard)
                for hard_index, hard in enumerate(hard_blocks, start=1)
                if hard_index - 1 not in assigned_hard
            ]
            if unassigned:
                st.caption(t("other_hard_blocks", lang))
                for hard_index, hard in unassigned:
                    st.markdown(_hard_block_line(hard_index, hard, lang))
        elif hard_blocks:
            st.caption(t("hard_blocks", lang))
            for hard_index, hard in enumerate(hard_blocks, start=1):
                st.markdown(_hard_block_line(hard_index, hard, lang))

    # Interval cadence is still useful in the textual interval summary even
    # though the separate cadence chart was removed in v4.10.
    interval_avg_cadence = _as_float(activity.get("interval_work_avg_cadence_rpm"))

    evidence_left, evidence_right = st.columns(2)
    with evidence_left:
        st.markdown(f"#### {t('heart_rate_evidence', lang)}")
        hr_rows = [
            (t("max_analysed_hr", lang), activity.get("analysed_max_hr"), "bpm"),
            (t("best_30m_hr", lang), activity.get("best_30m_hr"), "bpm"),
            (t("best_60m_hr", lang), activity.get("best_60m_hr"), "bpm"),
            (t("best_90m_hr", lang), activity.get("best_90m_hr"), "bpm"),
            (t("best_2h_hr", lang), activity.get("best_2h_hr"), "bpm"),
            (t("best_4h_hr", lang), activity.get("best_4h_hr"), "bpm"),
        ]
        shown = False
        for label, value, unit in hr_rows:
            if value is not None:
                shown = True
                st.write(f"**{label}:** {value:.1f} {unit}")
        if not shown:
            st.caption(t("no_hr_evidence", lang))

    with evidence_right:
        st.markdown(f"#### {t('climbing_effort', lang)}")
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
                interval_text += f" · {interval_avg_cadence:.1f} rpm {t('avg_cadence', lang)}"
            st.write(f"**{t('intervals', lang)}:** {interval_text}")
        if activity.get("key_effort"):
            shown = True
            st.write(f"**{t('key_effort', lang)}:** {activity['key_effort']}")
        if activity.get("lt2_reason") and activity.get("lt2_reason") != "no suitable sustained hard effort":
            shown = True
            st.write(f"**{t('lt2_evidence', lang)}:** {activity.get('lt2_evidence', '—')} — {activity['lt2_reason']}")
        if not shown:
            st.caption(t("no_effort_evidence", lang))

    with st.expander(t("raw_details", lang)):
        st.json(activity)

st.divider()
st.subheader(t("recent_activities", lang))
recent = filtered.sort_values("date", ascending=False).head(20).copy()
recent = recent[["date", "name", "sport", "location", "duration", "average_hr", "hr_intensity", "hr_load", "classification"]].rename(
    columns={
        "date": t("date", lang),
        "name": t("activity", lang),
        "sport": t("sport", lang),
        "location": t("location", lang),
        "duration": t("duration", lang),
        "average_hr": t("avg_hr", lang),
        "hr_intensity": t("hr_intensity", lang),
        "hr_load": t("hr_load", lang),
        "classification": t("classification", lang),
    }
)
st.dataframe(
    recent,
    use_container_width=True,
    hide_index=True,
    column_config={
        t("date", lang): st.column_config.DatetimeColumn(format="DD MMM YYYY"),
        t("avg_hr", lang): st.column_config.NumberColumn(format="%.1f"),
        t("hr_intensity", lang): st.column_config.NumberColumn(format="%.3f"),
        t("hr_load", lang): st.column_config.NumberColumn(format="%.1f"),
    },
)

st.divider()
with st.expander(t("about_load", lang)):
    params = training.get("analysis_parameters", {})
    model = params.get("hr_load_model", {})
    st.markdown(
        f"""
**{t("thresholds_export", lang)}**

- LT1: `{params.get('lt1_bpm', '—')}` bpm
- LT2: `{params.get('lt2_bpm', '—')}` bpm
- HRmax: `{params.get('hrmax_bpm', '—')}` bpm
- {t("minimum_hr_anchor", lang)}: `{params.get('min_hr_bpm', '—')}` bpm

**{t("model_anchors", lang)}**

- {t("lt1_weight", lang)}: `{model.get('lt1_weight', '—')}`
- {t("lt2_weight", lang)}: `{model.get('lt2_weight', '—')}`
- {t("hrmax_weight", lang)}: `{model.get('hrmax_weight', '—')}`
- {t("below_lt1_exp", lang)}: `{model.get('below_lt1_exponent', '—')}`
- {t("normalisation", lang)}: `{model.get('normalization', '—')}`
"""
    )
