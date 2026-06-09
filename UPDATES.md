# Daily Updates Log

Daily bug fixes, improvements, and notes for the Bay Area Transit Demand Forecasting project.

---

## 2026-06-09

### Bug Fixes

#### 1. `Processing/feature_engineering.py` — Inverted sort condition in `add_weather_features`
**Bug:** Line 140 had `if df["timestamp"].is_monotonic_increasing: df = df.sort_values(...)` — the condition was inverted, so it sorted when data was already sorted and skipped sorting when it wasn't.
**Fix:** Changed to `if not df["timestamp"].is_monotonic_increasing`.

#### 2. `Processing/feature_engineering.py` — Invalid groupby key in `is_rain_onset`
**Bug:** When `station_id` column was absent, the code passed `[True] * len(df)` as the groupby key — not a valid pandas groupby argument, raising `TypeError` at runtime.
**Fix:** Replaced with an explicit branch: groupby `station_id` when present, otherwise call `.shift(1)` directly on the column.

#### 3. `Processing/feature_engineering.py` — `n_new` always 0 in `build_features`
**Bug:** `n_new = n_features - len(df.columns)` used the same DataFrame twice so the result was always 0. The variable was also not included in the log message.
**Fix:** Captured `n_original_cols = len(df.columns)` before the feature pipeline runs, and updated the log message to show `+{n_new}` new columns.

#### 4. `machine_learning_files/merge_pipeline.py` — Timezone mismatch in date range filter
**Bug:** `build_feature_store` strips timezone from the `timestamp` column during the weather merge (line 270), then the `--start` / `--end` filter created tz-aware `pd.Timestamp` objects. Comparing tz-naive and tz-aware timestamps raises `TypeError`.
**Fix:** The filter now normalises both sides to tz-naive before comparison.

#### 5. `machine_learning_files/api.py` — Deprecated `datetime.utcnow()`
**Bug:** `datetime.utcnow()` is deprecated in Python 3.12+ and will be removed in a future version.
**Fix:** Replaced both occurrences with `datetime.now(timezone.utc)`, importing `timezone` from the standard library.

#### 6. `machine_learning_files/api.py` — Wrong API title ("Traffic" vs "Transit")
**Bug:** `FastAPI(title="Bay Area Traffic Forecast API", ...)` — the word "Traffic" should be "Transit" to match the project description, docstring, and route root response.
**Fix:** Changed title to `"Bay Area Transit Forecast API"`.

#### 7. `evaluation/validators.py` — Unsafe `idx - 1` label lookup in `check_missing_windows`
**Bug:** `grp.loc[idx - 1, "timestamp"]` uses `idx - 1` as an index *label*, not a positional offset. For DataFrames with non-sequential indices (e.g. after concat/filter), `idx - 1` may point to the wrong row or not exist at all, silently returning "unknown" even when a valid predecessor exists.
**Fix:** Replaced with `grp.index.get_loc(idx)` to get the positional offset, then `grp.iloc[pos - 1]` for the correct preceding row.

---
