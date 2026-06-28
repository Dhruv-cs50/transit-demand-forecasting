# Daily Updates Log

Automated bug-check and improvement log, maintained by the scheduled Claude Code routine.

---

## 2026-06-28

### Bugs Fixed (7)

**1. `merge_pipeline.py:185` — `tz_localize(None)` on tz-aware Series (runtime crash)**
- In `compute_event_features()`, a tz-aware `ev_ts` was passed to `.tz_localize(None)`, which raises `TypeError: Already tz-aware, use tz_convert to convert.`
- Fixed: replaced with `.tz_convert(None)`.

**2. `Processing/feature_engineering.py:140` — Inverted sort condition (logic error)**
- `add_weather_features()` contained `if df["timestamp"].is_monotonic_increasing: df = df.sort_values(...)` — this sorted only when already sorted (a no-op) and skipped sorting when out of order.
- Fixed: changed to `if not df["timestamp"].is_monotonic_increasing`.

**3. `Processing/feature_engineering.py:442` — Dead `n_new` variable (always 0)**
- In `build_features()`, `n_new = n_features - len(df.columns)` computed 0 every time because `n_features` had just been set to `len(df.columns)`. The variable was never logged or used.
- Fixed: removed the dead assignment.

**4. `scripts/export_website_data.py:158` — `tz_localize(None)` on tz-aware Timestamp (runtime crash)**
- In `export_ridership_actuals()`, a tz-aware Timestamp was passed to `.tz_localize(None)` which raises `TypeError`.
- Fixed: replaced with `.tz_convert(None)`.

**5. `models/chronos2/predict.py:122` — Wrong import name `Chronos2Pipeline` (NameError on import)**
- `_load_zeroshot()` imported `from chronos import Chronos2Pipeline`, but the Chronos package exports `ChronosPipeline`. The rest of the codebase (`zero_shot.py`, `api.py`) already used the correct name.
- Fixed: changed to `from chronos import ChronosPipeline` and updated the instantiation call.

**6. `evaluation/validators.py:372` — `tz_localize(None)` on tz-aware timestamp column (runtime crash)**
- `check_station_coverage()` called `.dt.tz_localize(None)` on the timestamp column, which crashes when the feature store uses tz-aware timestamps (the default schema is `datetime64[ns, America/Los_Angeles]`).
- Fixed: check `dt.tz` first and use `tz_convert(None)` when tz-aware.

**7. `evaluation/validators.py:173` — Incorrect gap_start lookup via `idx - 1` label (wrong values)**
- `check_missing_windows()` used `grp.loc[idx - 1, "timestamp"]` to find the row before a gap, assuming sequential integer index labels. After groupby + sort operations the index is not guaranteed sequential, so this silently returned incorrect or missing timestamps.
- Fixed: pre-compute `prev_ts = grp["timestamp"].shift(1)` before the loop and look up by `prev_ts.loc[idx]`.

### Improvements

**8. `machine_learning_files/api.py`, `models/chronos2/predict.py` — `datetime.utcnow()` deprecated in Python 3.12+**
- Replaced both usages of `datetime.utcnow().isoformat()` with `datetime.now(timezone.utc).isoformat()` and added `timezone` to the `from datetime import ...` line in each file.

### Summary

| Category | Count |
|---|---|
| Runtime crashes fixed | 4 (bugs 1, 4, 5, 6) |
| Logic errors fixed | 2 (bugs 2, 7) |
| Dead code removed | 1 (bug 3) |
| Deprecation fixes | 1 (improvement 8) |

No new features or API changes. All fixes are backward-compatible.
