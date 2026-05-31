# Daily Updates Log

Ongoing record of bug fixes and improvements made to the transit demand forecasting codebase.

---

## 2026-05-31

### Bug Fixes

**1. `merge_pipeline.py` — Removed unused `ridership_daily_est` column (line 109)**
- The column divided monthly ridership by 22 (assumed weekdays) but was never referenced downstream.
- Removed to avoid misleading callers inspecting the feature store schema.

**2. `merge_pipeline.py` — Fixed timezone stripping in `compute_event_features` (lines 184–191)**
- `tz_localize(None)` raises `TypeError` on a tz-aware Series; correct call is `tz_convert(None)`.
- Applied the same fix to the `ts_series` path in the same function.
- **Impact**: Without this fix, any tz-aware event timestamp caused a runtime crash during feature store construction.

**3. `feature_engineering.py` — Fixed always-zero `n_new` in `build_features` logging (line 442)**
- `n_new = n_features - len(df.columns)` always evaluated to 0 (same expression both sides).
- Now tracks `n_input_cols` at entry and logs the actual number of engineered columns added.

**4. `feature_engineering.py` — Fixed `is_rain_onset` groupby fallback (lines 152–154)**
- The fallback path (`[True] * len(df)`) was unidiomatic and fragile.
- Replaced with a clean conditional that uses `shift(1)` directly when no `station_id` column is present.

**5. `validators.py` — Fixed positional index access in `check_missing_windows` (line 174)**
- `grp.loc[idx - 1, ...]` assumed the row at position `idx - 1` existed in the group's index slice, which fails when the DataFrame has non-contiguous index values after filtering/grouping.
- Replaced with `grp.index.get_loc(idx)` → `grp.iloc[pos - 1]` for safe positional access.
- **Impact**: Without this fix, gap detection could raise `KeyError` for any station with a non-zero-based index.

**6. `api.py` — Made model output directory configurable via `MODEL_OUTPUT_DIR` env var (line 127)**
- Hardcoded `"models/chronos2/outputs"` path broke containerised deployments where volumes are mounted at different paths.
- Now reads `os.getenv("MODEL_OUTPUT_DIR", "models/chronos2/outputs")` with the original path as default.

**7. `api.py` — Tightened quantile column regex in the forecast cache fast-path (lines 133–135)**
- Plain `"0.1" in str(c)` could false-positive on a column like `"precip_0.10mm"`.
- Replaced with word-boundary regex (`r'(^|[^0-9])0\.1([^0-9]|$)'`) for all three quantiles.

### Summary
- 7 bugs fixed across 4 files
- 2 crash-level bugs resolved (tz_localize TypeError, validators KeyError)
- 1 silent correctness bug fixed (logging always showed 0 new features)
- 1 deployment/portability improvement (configurable model output path)
- 1 robustness improvement (rain onset logic, quantile column matching)
