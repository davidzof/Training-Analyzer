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

def _selected_activity_key_from_chart_state(state):
    """Extract an activity key from Streamlit's Altair selection state."""
    if not state:
        return None

    try:
        selection = state.get("selection", {})
    except AttributeError:
        selection = getattr(state, "selection", {})

    try:
        picked = selection.get("activity_pick")
    except AttributeError:
        picked = getattr(selection, "activity_pick", None)

    if not picked:
        return None

    # A field-based Vega-Lite point selection normally arrives as
    # {"activity_key": ["..."]}. Keep a couple of fallbacks so minor
    # Streamlit/Vega-Lite representation changes do not break navigation.
    if isinstance(picked, dict):
        value = picked.get("activity_key")
        if isinstance(value, (list, tuple)):
            return value[0] if value else None
        if value:
            return value

    if isinstance(picked, (list, tuple)) and picked:
        first = picked[0]
        if isinstance(first, dict):
            return first.get("activity_key")
        if isinstance(first, str):
            return first

    return None


def _on_intensity_load_select():
    """Queue a clicked scatter activity for the Activity Explorer."""
    state = st.session_state.get("intensity_load_scatter")
    activity_key = _selected_activity_key_from_chart_state(state)
    if activity_key:
        st.session_state["pending_activity_key"] = activity_key


def intensity_load_chart(activity_df):
    chart_df = activity_df.dropna(subset=["hr_intensity", "hr_load"]).copy()
    if chart_df.empty:
        st.info("No HR Intensity / HR Load data available.")
        return

    activity_pick = alt.selection_point(
        name="activity_pick",
        fields=["activity_key"],
        on="click",
        clear="dblclick",
        toggle=False,
    )

    points = (
        alt.Chart(chart_df)
        .mark_circle(size=70)
        .encode(
            x=alt.X("hr_intensity:Q", title="HR Intensity", scale=alt.Scale(zero=True)),
            y=alt.Y("hr_load:Q", title="HR Load", scale=alt.Scale(zero=True)),
            color=alt.Color("sport:N", title="Sport"),
            opacity=alt.condition(activity_pick, alt.value(1.0), alt.value(0.72)),
            size=alt.condition(activity_pick, alt.value(125), alt.value(70)),
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
        .add_params(activity_pick)
    )

    intensity_ref = alt.Chart(pd.DataFrame({"hr_intensity": [1.0]})).mark_rule(strokeDash=[6, 5], opacity=0.65).encode(x="hr_intensity:Q")
    load_ref = alt.Chart(pd.DataFrame({"hr_load": [100.0]})).mark_rule(strokeDash=[6, 5], opacity=0.65).encode(y="hr_load:Q")

    chart = (points + intensity_ref + load_ref).interactive().properties(height=430)
    st.altair_chart(
        chart,
        key="intensity_load_scatter",
        use_container_width=True,
        on_select=_on_intensity_load_select,
        selection_mode="activity_pick",
    )


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


def hr_duration_curve_chart(points, hrmax=None, lt1=None, lt2=None, statistic_label="Best observed"):
    """Plot an observed HR-duration curve on a logarithmic time axis."""
    if not points:
        st.info("No HR-duration data available for this selection.")
        return

    rows = []
    for point in points:
        try:
            duration = float(point.get("duration_minutes"))
            bpm = float(point.get("bpm"))
        except (TypeError, ValueError, AttributeError):
            continue
        if duration <= 0:
            continue
        rows.append({
            "duration_minutes": duration,
            "bpm": bpm,
            "qualifying_activities": point.get("qualifying_activities"),
            "activity_date": point.get("activity_date"),
            "activity_name": point.get("activity_name") or point.get("filename") or "—",
        })

    if not rows:
        st.info("No HR-duration data available for this selection.")
        return

    df = pd.DataFrame(rows).sort_values("duration_minutes")
    base = alt.Chart(df).encode(
        x=alt.X(
            "duration_minutes:Q",
            title="Duration (minutes, log scale)",
            scale=alt.Scale(type="log", domain=[1, 240]),
            axis=alt.Axis(values=[1, 2, 5, 10, 20, 30, 60, 120, 240], format="g"),
        ),
        y=alt.Y("bpm:Q", title=f"{statistic_label} sustained average HR (bpm)", scale=alt.Scale(zero=False)),
    )
    tooltips = [
        alt.Tooltip("duration_minutes:Q", title="Duration (min)", format="g"),
        alt.Tooltip("bpm:Q", title=statistic_label, format=".1f"),
        alt.Tooltip("qualifying_activities:Q", title="Qualifying activities", format=".0f"),
    ]
    if statistic_label == "Best observed":
        tooltips.extend([
            alt.Tooltip("activity_date:N", title="Date"),
            alt.Tooltip("activity_name:N", title="Activity"),
        ])
    line = base.mark_line(point=True).encode(tooltip=tooltips)

    layers = [line]
    refs = []
    for label, value in (("HRmax", hrmax), ("LT2", lt2), ("LT1", lt1)):
        try:
            value = float(value)
        except (TypeError, ValueError):
            continue
        refs.append({"label": label, "bpm": value})
    if refs:
        ref_df = pd.DataFrame(refs)
        rules = alt.Chart(ref_df).mark_rule(strokeDash=[5, 4]).encode(
            y="bpm:Q",
            tooltip=[alt.Tooltip("label:N", title="Reference"), alt.Tooltip("bpm:Q", title="HR", format=".0f")],
        )
        layers.append(rules)

    st.altair_chart(alt.layer(*layers).properties(height=330), use_container_width=True)


def hr_duration_rolling_chart(rolling_curves, sport="Combined", use_p95=False, hrmax=None, lt1=None, lt2=None, statistic_label="Best observed"):
    """Plot all rolling 8-week HR-duration curves together.

    Older windows are shown as a pale-to-dark recency backdrop, while the
    previous and latest windows are deliberately emphasised so recent change is
    easy to compare at a glance.
    """
    rows = []
    valid_sets = []

    for item in rolling_curves or []:
        as_of = item.get("as_of")
        if sport == "Combined":
            points = item.get("p95_all" if use_p95 else "all", []) or []
        else:
            points = (item.get("p95_by_sport" if use_p95 else "by_sport", {}) or {}).get(sport, []) or []

        parsed = []
        for point in points:
            try:
                duration = float(point.get("duration_minutes"))
                bpm = float(point.get("bpm"))
            except (TypeError, ValueError, AttributeError):
                continue
            if duration <= 0:
                continue
            parsed.append({
                "duration_minutes": duration,
                "bpm": bpm,
                "qualifying_activities": point.get("qualifying_activities"),
                "activity_date": point.get("activity_date"),
                "activity_name": point.get("activity_name") or point.get("filename") or "—",
            })
        if parsed:
            valid_sets.append((as_of, parsed))

    if not valid_sets:
        st.info("No rolling HR-duration data available for this selection.")
        return

    n = len(valid_sets)
    palette = [
        "#dbe7f3", "#c7daec", "#b1cce4", "#98bcda", "#7eabd0",
        "#6499c5", "#4c87b9", "#3674ab", "#245f98", "#174a7e",
        "#0f3762", "#08284a",
    ]
    if n == 1:
        colors = [palette[-1]]
    else:
        colors = [palette[round(i * (len(palette) - 1) / (n - 1))] for i in range(n)]

    for idx, ((as_of, parsed), color) in enumerate(zip(valid_sets, colors)):
        label = f"8 weeks to {as_of}"
        if idx == n - 1:
            recency_class = "Latest"
        elif idx == n - 2:
            recency_class = "Previous"
        else:
            recency_class = "Older"

        for point in parsed:
            rows.append({
                **point,
                "period": label,
                "period_order": idx,
                "period_color": color,
                "recency_class": recency_class,
            })

    df = pd.DataFrame(rows).sort_values(["period_order", "duration_minutes"])

    common_x = alt.X(
        "duration_minutes:Q",
        title="Duration (minutes, log scale)",
        scale=alt.Scale(type="log", domain=[1, 240]),
        axis=alt.Axis(values=[1, 2, 5, 10, 20, 30, 60, 120, 240], format="g"),
    )
    common_y = alt.Y(
        "bpm:Q",
        title=f"{statistic_label} sustained average HR (bpm)",
        scale=alt.Scale(zero=False),
    )
    tooltip = [
        alt.Tooltip("period:N", title="Period"),
        alt.Tooltip("duration_minutes:Q", title="Duration (min)", format="g"),
        alt.Tooltip("bpm:Q", title=statistic_label, format=".1f"),
        alt.Tooltip("qualifying_activities:Q", title="Qualifying activities", format=".0f"),
    ]

    # Older curves retain the recency gradient but do not create a long legend.
    older_df = df[df["recency_class"] == "Older"].copy()
    layers = []
    if not older_df.empty:
        older_labels = older_df[["period_order", "period", "period_color"]].drop_duplicates().sort_values("period_order")
        old_domain = older_labels["period"].tolist()
        old_range = older_labels["period_color"].tolist()
        older = (
            alt.Chart(older_df)
            .mark_line(point=False, strokeWidth=1.25, opacity=0.62)
            .encode(
                x=common_x,
                y=common_y,
                detail="period:N",
                color=alt.Color(
                    "period:N",
                    scale=alt.Scale(domain=old_domain, range=old_range),
                    legend=None,
                ),
                tooltip=tooltip,
            )
        )
        layers.append(older)

    # Previous: same dark-blue family, but dashed and clearly thicker.
    previous_df = df[df["recency_class"] == "Previous"].copy()
    if not previous_df.empty:
        previous = (
            alt.Chart(previous_df)
            .mark_line(point=False, strokeWidth=2.3, strokeDash=[7, 4], opacity=0.95, color="#174a7e")
            .encode(x=common_x, y=common_y, detail="period:N", tooltip=tooltip)
        )
        layers.append(previous)

    # Latest: strongest visual anchor, solid and marked with points.
    latest_df = df[df["recency_class"] == "Latest"].copy()
    latest = (
        alt.Chart(latest_df)
        .mark_line(point=alt.OverlayMarkDef(size=55, filled=True), strokeWidth=3.4, opacity=1.0, color="#08284a")
        .encode(x=common_x, y=common_y, detail="period:N", tooltip=tooltip)
    )
    layers.append(latest)

    # Make every curve easy to inspect without making the historical lines
    # visually heavy.  A nearly invisible wide line acts as a generous pointer
    # target for hover/click interaction.  Clicking a curve highlights it;
    # double-clicking clears the selection.
    curve_select = alt.selection_point(
        fields=["period"],
        on="click",
        clear="dblclick",
        empty=False,
        name="selected_curve",
    )

    hit_target = (
        alt.Chart(df)
        .mark_line(strokeWidth=10, opacity=0.001, color="#ffffff")
        .encode(
            x=common_x,
            y=common_y,
            detail="period:N",
            tooltip=tooltip,
        )
        .add_params(curve_select)
    )
    layers.append(hit_target)

    # Bring the clicked curve to the foreground.  This overlay is deliberately
    # distinct from the recency styling so an older curve is just as easy to
    # inspect as the latest one.
    selected_curve = (
        alt.Chart(df)
        .transform_filter(curve_select)
        .mark_line(
            point=alt.OverlayMarkDef(size=48, filled=True),
            strokeWidth=4.2,
            opacity=1.0,
            color="#f2b84b",
        )
        .encode(
            x=common_x,
            y=common_y,
            detail="period:N",
            tooltip=tooltip,
        )
    )
    layers.append(selected_curve)

    refs = []
    for label, value in (("HRmax", hrmax), ("LT2", lt2), ("LT1", lt1)):
        try:
            value = float(value)
        except (TypeError, ValueError):
            continue
        refs.append({"label": label, "bpm": value})
    if refs:
        ref_df = pd.DataFrame(refs)
        rules = alt.Chart(ref_df).mark_rule(strokeDash=[5, 4], opacity=0.55).encode(
            y="bpm:Q",
            tooltip=[
                alt.Tooltip("label:N", title="Reference"),
                alt.Tooltip("bpm:Q", title="HR", format=".0f"),
            ],
        )
        layers.append(rules)

    st.altair_chart(alt.layer(*layers).properties(height=380), use_container_width=True)

    latest_period = latest_df["period"].iloc[0] if not latest_df.empty else "Latest"
    previous_period = previous_df["period"].iloc[0] if not previous_df.empty else None
    if previous_period:
        st.caption(
            f"Older periods are shown as lighter background curves. {previous_period} is dashed; "
            f"{latest_period} is the thick solid curve with points. Hover any curve for values; "
            "click a curve to highlight it and double-click to clear the selection."
        )
    else:
        st.caption(
            f"{latest_period} is the current rolling 8-week curve. Hover any curve for values; "
            "click a curve to highlight it and double-click to clear the selection."
        )
