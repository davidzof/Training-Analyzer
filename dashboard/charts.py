from datetime import datetime
import altair as alt
import pandas as pd
import streamlit as st


def weekly_load_chart(weekly_df):
    if weekly_df.empty or "hr_load" not in weekly_df.columns:
        st.info("No weekly HR Load data available.")
        return
    chart_df = weekly_df[["week_start", "hr_load"]].dropna().copy()
    chart = alt.Chart(chart_df).mark_bar().encode(
        x=alt.X("week_start:T", title=None, axis=alt.Axis(format="%b")),
        y=alt.Y("hr_load:Q", title="HR Load"),
        tooltip=[alt.Tooltip("week_start:T", title="Week", format="%d %b %Y"), alt.Tooltip("hr_load:Q", title="HR Load", format=".1f")],
    ).properties(height=320)
    st.altair_chart(chart, use_container_width=True)


def weekly_hours_chart(weekly_df):
    if weekly_df.empty or "moving_hours" not in weekly_df.columns:
        st.info("No weekly volume data available.")
        return

    chart_df = weekly_df[["week_start", "moving_hours"]].dropna().copy()

    # Render each week as a conventional vertical column.  Using an x/x2
    # temporal interval made the weekly rectangles appear as thin floating
    # dashes in some Altair/Streamlit combinations.
    chart = (
        alt.Chart(chart_df)
        .mark_bar(size=8)
        .encode(
            x=alt.X(
                "week_start:T",
                title=None,
                axis=alt.Axis(format="%b", labelOverlap="greedy"),
                scale=alt.Scale(nice=False),
            ),
            y=alt.Y(
                "moving_hours:Q",
                title="Moving hours",
                scale=alt.Scale(zero=True),
            ),
            tooltip=[
                alt.Tooltip("week_start:T", title="Week", format="%d %b %Y"),
                alt.Tooltip("moving_hours:Q", title="Hours", format=".1f"),
            ],
        )
        .properties(height=320)
    )

    st.altair_chart(chart, use_container_width=True)

def intensity_load_chart(activity_df):
    chart_df = activity_df.dropna(subset=["hr_intensity", "hr_load"]).copy()
    if chart_df.empty:
        st.info("No HR Intensity / HR Load data available.")
        return

    points = alt.Chart(chart_df).mark_circle(size=70, opacity=0.72).encode(
        x=alt.X("hr_intensity:Q", title="HR Intensity", scale=alt.Scale(zero=True)),
        y=alt.Y("hr_load:Q", title="HR Load", scale=alt.Scale(zero=True)),
        color=alt.Color("sport:N", title="Sport"),
        tooltip=[
            alt.Tooltip("date:T", title="Date", format="%d %b %Y"),
            alt.Tooltip("name:N", title="Activity"),
            alt.Tooltip("sport:N", title="Sport"),
            alt.Tooltip("duration:N", title="Duration"),
            alt.Tooltip("average_hr:Q", title="Avg HR", format=".1f"),
            alt.Tooltip("hr_intensity:Q", title="HR Intensity", format=".3f"),
            alt.Tooltip("hr_load:Q", title="HR Load", format=".1f"),
            alt.Tooltip("classification:N", title="Classification"),
        ],
    )

    intensity_ref = alt.Chart(pd.DataFrame({"hr_intensity": [1.0]})).mark_rule(strokeDash=[6, 5], opacity=0.65).encode(x="hr_intensity:Q")
    load_ref = alt.Chart(pd.DataFrame({"hr_load": [100.0]})).mark_rule(strokeDash=[6, 5], opacity=0.65).encode(y="hr_load:Q")

    chart = (points + intensity_ref + load_ref).interactive().properties(height=430)
    st.altair_chart(chart, use_container_width=True)


def zone_distribution_chart(activity):
    values = [
        ("Below LT1", activity.get("active_zone1_seconds"), "#9ad5a5"),
        ("LT1–LT2", activity.get("active_zone2_seconds"), "#4c78a8"),
        ("Above LT2", activity.get("active_zone3_seconds"), "#e45756"),
    ]

    total_seconds = sum((seconds or 0) for _, seconds, _ in values)
    if total_seconds <= 0:
        st.caption("No active HR-zone data.")
        return

    rows = []
    cursor_hours = 0.0

    for zone, seconds, colour in values:
        seconds = seconds or 0
        hours = seconds / 3600.0
        share = 100.0 * seconds / total_seconds

        rows.append(
            {
                "zone": zone,
                "start_hours": cursor_hours,
                "end_hours": cursor_hours + hours,
                "hours": hours,
                "share": share,
                "colour": colour,
                "activity": "Active HR time",
            }
        )
        cursor_hours += hours

    df = pd.DataFrame(rows)

    chart = (
        alt.Chart(df)
        .mark_bar()
        .encode(
            x=alt.X("start_hours:Q", title="Hours"),
            x2="end_hours:Q",
            y=alt.Y("activity:N", title=None, axis=None),
            color=alt.Color(
                "zone:N",
                title=None,
                scale=alt.Scale(
                    domain=["Below LT1", "LT1–LT2", "Above LT2"],
                    range=["#9ad5a5", "#4c78a8", "#e45756"],
                ),
                legend=alt.Legend(
                    orient="right",
                ),
            ),
            tooltip=[
                alt.Tooltip("zone:N", title="Zone"),
                alt.Tooltip("hours:Q", title="Hours", format=".2f"),
                alt.Tooltip("share:Q", title="Share", format=".1f"),
            ],
        )
        .properties(height=105)
    )

    st.altair_chart(chart, use_container_width=True)

    cols = st.columns(3)
    for col, row in zip(cols, rows):
        col.metric(row["zone"], f"{row['share']:.1f}%")

def _seconds_from_start(activity_start, clock_text):
    if not clock_text:
        return None
    try:
        clock = datetime.strptime(clock_text, "%H:%M:%S").time()
    except ValueError:
        return None

    candidate = datetime.combine(activity_start.date(), clock)
    delta = (candidate - activity_start).total_seconds()
    if delta < -12 * 3600:
        delta += 24 * 3600
    return max(0.0, delta)


def _duration_seconds(duration_text):
    if not duration_text:
        return None

    try:
        parts = [int(float(p)) for p in str(duration_text).split(":")]
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


def _activity_effort_segments(activity):
    """
    Build a mutually exclusive display timeline from the analyser's overlapping
    tempo/hard blocks.

    Display priority:
        Hard > Tempo > Endurance

    The source JSON is not changed. This is only a presentation transform.
    """
    date_text = activity.get("activity_date")
    if not date_text:
        return []

    try:
        start_dt = datetime.strptime(date_text, "%d %b %Y %H:%M")
    except ValueError:
        return []

    total_seconds = _duration_seconds(activity.get("duration"))
    if not total_seconds or total_seconds <= 0:
        return []

    tempo = []
    hard = []

    for kind, source in (
        ("Tempo", activity.get("tempo_blocks", []) or []),
        ("Hard", activity.get("hard_blocks", []) or []),
    ):
        target = hard if kind == "Hard" else tempo

        for block in source:
            start = _seconds_from_start(start_dt, block.get("start"))
            end = _seconds_from_start(start_dt, block.get("end"))

            if start is None or end is None:
                continue
            if end < start:
                end += 24 * 3600

            start = max(0.0, min(float(total_seconds), start))
            end = max(0.0, min(float(total_seconds), end))

            if end > start:
                target.append((start, end))

    boundaries = {0.0, float(total_seconds)}
    for intervals in (tempo, hard):
        for start, end in intervals:
            boundaries.add(start)
            boundaries.add(end)

    boundaries = sorted(boundaries)
    segments = []

    for left, right in zip(boundaries[:-1], boundaries[1:]):
        if right <= left:
            continue

        midpoint = (left + right) / 2.0

        if any(start <= midpoint < end for start, end in hard):
            effort = "Hard"
        elif any(start <= midpoint < end for start, end in tempo):
            effort = "Tempo"
        else:
            effort = "Endurance"

        if segments and segments[-1]["type"] == effort and abs(segments[-1]["end_sec"] - left) < 1e-6:
            segments[-1]["end_sec"] = right
        else:
            segments.append(
                {
                    "type": effort,
                    "start_sec": left,
                    "end_sec": right,
                }
            )

    for segment in segments:
        segment["start_min"] = segment["start_sec"] / 60.0
        segment["end_min"] = segment["end_sec"] / 60.0
        segment["duration_min"] = (segment["end_sec"] - segment["start_sec"]) / 60.0

    return segments


def effort_timeline_chart(activity):
    rows = _activity_effort_segments(activity)

    if not rows:
        st.caption("No activity timing information.")
        return

    df = pd.DataFrame(rows)
    lane_order = ["< LT1", "LT1–LT2", "> LT2"]
    df["lane"] = df["type"].map({"Endurance": "< LT1", "Tempo": "LT1–LT2", "Hard": "> LT2"})

    lane_df = pd.DataFrame({"lane": lane_order})
    background = alt.Chart(lane_df).mark_rule(opacity=0).encode(
        y=alt.Y("lane:N", title=None, sort=lane_order)
    )

    bars = alt.Chart(df).mark_bar(size=18).encode(
        x=alt.X("start_min:Q", title="Minutes from start", axis=alt.Axis(titlePadding=12)),
        x2="end_min:Q",
        y=alt.Y("lane:N", title=None, sort=lane_order, axis=alt.Axis(labelPadding=10)),
        color=alt.Color(
            "lane:N", title=None,
            scale=alt.Scale(domain=lane_order, range=["#9ad5a5", "#4c78a8", "#e45756"]),
            legend=None,
        ),
        tooltip=[
            alt.Tooltip("lane:N", title="Intensity"),
            alt.Tooltip("start_min:Q", title="Start (min)", format=".1f"),
            alt.Tooltip("duration_min:Q", title="Duration (min)", format=".1f"),
        ],
    )

    chart = (background + bars).properties(height=185)
    st.altair_chart(chart, use_container_width=True)
