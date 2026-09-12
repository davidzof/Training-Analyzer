# Training Analyser context

This JSON comes from Training Analyser, which extracts compact physiological and training evidence from GPX/TCX/FIT + Strava metadata.
Treat the values as evidence, not laboratory truth.

## Key fields:

* hr_intensity: duration-independent cardiovascular intensity. It is normalized so 1.0 = the average HR weighting of exercising continuously at LT2. Rough guide: ~0.36 ≈ LT1 intensity, 0.5 moderate endurance, 0.7 fairly hard sustained work, 1.0 LT2-equivalent average intensity, >1.0 very hard.
* hr_load: total cardiovascular load = duration × HR intensity × 100. 1 hour at LT2 = HR Load 100. It is not TSS and hr_intensity is not power-based IF.
* active_zone1_seconds/pct: active time below LT1.
* active_zone2_seconds/pct: active time between LT1 and LT2.
* active_zone3_seconds/pct: active time above LT2.
* best_30m_hr, best_60m_hr, best_90m_hr, best_2h_hr, best_4h_hr: highest qualifying sustained average HR over those durations. Do not infer LT1 directly from 2h/4h HR.
* hard_blocks: sustained hard efforts, generally above LT2.
* tempo_blocks: sustained work from LT1 upward, allowing brief excursions.
* interval fields describe detected repeated work/recovery structure. Do not assume detected intervals are VO2max work, and do not estimate LT2 from interval detection alone.
* lt2_*: conservative LT2 evidence. A 30-minute effort alone should not produce a numeric LT2 estimate; credible ~60-minute evidence is much stronger.
* vam_15/30/60: climbing rate in m/h over qualifying uphill windows. Useful for comparing climbs, but it is not power.
* classification, overall_ride, key_effort: compact analyser interpretations; check them against the underlying HR zones, blocks, intensity and load.
* analysed_max_hr is more useful than raw_max_hr, which may include sensor artefacts.
* moving_time, activity_gear, average_cadence_rpm, location, distance and elevation are contextual fields when available.

Important rules:

* null means unknown/not available, never zero.
* HR sensor artefacts may exist, especially in older activities; check hr_artefact and excluded_hr_samples.
* HR alone cannot precisely locate LT2.
* Do not create pseudo-power or infer missing power metrics.
* Walking is valid base training and should not be discounted.
* XC skiing often produces more mid/high HR naturally than cycling.
* Compare activities longitudinally, but consider sport, terrain, bike, injury, lifestyle and training opportunity rather than forcing a smooth fitness/age trend.

When interpreting an activity, consider in order:

* sport and duration,
* hr_intensity,
* hr_load,
* time below/between/above LT1/LT2,
* sustained vs intermittent effort,
* HR/LT2/HRmax evidence,
* classification,
* data-quality caveats.