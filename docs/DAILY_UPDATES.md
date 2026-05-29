# Daily Updates Log

---

## 2026-05-29

### Bug Fixes

#### Critical — Timezone Stripping (Data Corruption)
- **`scripts/export_website_data.py:158`** — `tz_localize(None)` → `tz_convert(None)`.
  `tz_localize(None)` strips timezone info without converting, silently shifting exported timestamps by hours. `tz_convert(None)` converts to UTC first, then removes tz info, preserving the correct point in time.
- **`machine_learning_files/merge_pipeline.py:185,191`** — Same `tz_localize` → `tz_convert` fix applied to event timestamps and the base timestamp series inside `compute_event_features`.
- **`machine_learning_files/merge_pipeline.py:286`** — Same fix for the weather merge timestamp strip.

#### High — Date Filter TypeError (Pipeline Crash)
- **`machine_learning_files/merge_pipeline.py:314-316`** — Date range filter used `pd.Timestamp(start, tz="America/Los_Angeles")` unconditionally. If `base["timestamp"]` is tz-naive (which it is after the pipeline strips tz), this comparison throws a `TypeError`. Fix: check the column's tz first and only attach `tz_localize` when needed.

#### High — IndexError on Missing Future Rows (API Crash)
- **`models/chronos2/predict.py:451`** — The rain forecast check re-sliced `station_df[station_df["timestamp"] > now]` without an `.empty` guard before `.iloc[0]`. If there are no future rows, this raises `IndexError`. Fix: save the slice to `future_weather` and guard with `if not future_weather.empty`.

#### Medium — Off-by-label Gap Start Lookup (Wrong Diagnostic Output)
- **`evaluation/validators.py:174`** — Gap start detection used `grp.loc[idx - 1, "timestamp"]`, where `idx` is a DataFrame label (not a sequential position). After `sort_values` the original integer labels are non-contiguous, so `idx - 1` is rarely the actual preceding row. Result: gap_start almost always shows `"unknown"`. Fix: use positional lookup via `grp.index.get_loc(idx)` and `grp.iloc[pos - 1]`.

#### Low — Dead Variable (`n_new` Always Zero)
- **`Processing/feature_engineering.py:442`** — `n_new = n_features - len(df.columns)` computed immediately after setting `n_features = len(df.columns)`, so `n_new` was always `0` and never used. Removed the dead line.

---
