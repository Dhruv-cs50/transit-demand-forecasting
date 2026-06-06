# Daily Updates Log

---

## 2026-06-06

### Bugs Fixed

#### 1. `Processing/feature_engineering.py` — Feature count logging always reported 0 new columns (line 442)
- **Root cause:** `n_new` was computed as `len(df.columns) - len(df.columns)`, which is always 0.
- **Fix:** Capture `n_cols_before = len(df.columns)` at the top of `build_features()` before any transformations run, then compute `n_new = n_features - n_cols_before` at the end.
- **Impact:** Log messages now correctly report how many feature columns were added per pipeline run.

#### 2. `machine_learning_files/merge_pipeline.py` — `tz_localize(None)` called on already timezone-aware datetimes (lines 185, 191, 270, 286, 340)
- **Root cause:** Pandas raises `TypeError` (or `AmbiguousTimeError` during DST transitions) when `dt.tz_localize(None)` is called on a Series that already has timezone info. The correct method to strip timezone from an aware datetime is `dt.tz_convert(None)`.
- **Fix:** Replaced all five occurrences of `dt.tz_localize(None)` (guarded by `if ... .dt.tz is not None`) with `dt.tz_convert(None)`.
  - `compute_event_features()` — `ev_ts` and `ts_series`
  - `build_feature_store()` — `wdf["timestamp"]` and `base_ts`
  - `make_splits()` — `ts`
- **Impact:** Pipeline no longer raises runtime errors when weather, event, or transit data carries UTC/Pacific timezone info (which is the norm for all ingested sources).

#### 3. `machine_learning_files/api.py` — `horizon_hours` field/parameter mismatched to monthly model output
- **Root cause:** The Pydantic request/response models and `_run_forecast()` used `horizon_hours` (with `le=168`, implying hourly forecasts up to 7 days), but the underlying Chronos-2 and AutoGluon models produce **monthly** forecasts. Passing `horizon_hours=24` to `.head()` on monthly data would return 24 months of forecasts — a 2-year horizon named "24 hours".
- **Fix:**
  - Renamed `horizon_hours → horizon_months` in `ForecastRequest`, `ForecastResponse`, and `_run_forecast()`.
  - Updated field constraint to `ge=1, le=24` (max 2 years of monthly forecasts).
  - Kept deprecated `horizon_hours` field on `ForecastRequest` (nullable) for backwards-compatible clients, with the endpoint resolving it as a fallback.
  - Updated docstring curl example.
- **Impact:** API semantics now match model output frequency; clients requesting 12 months get 12 monthly forecasts, not 12 hours.

### Code Quality Notes (no code changes)
- Multiple `.iterrows()` loops in `scripts/export_website_data.py` and `evaluation/metrics.py` could be vectorized for better performance on large station datasets.
- Several bare `except:` blocks in `transit_eda/eda_complete.ipynb` should be narrowed to specific exception types.
- Timezone handling is now consistent across `merge_pipeline.py`; the rest of the codebase should continue to store timestamps as UTC-naive internally.
