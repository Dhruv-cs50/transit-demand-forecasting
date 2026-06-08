# Daily Updates

---

## 2026-06-08

### Bug Fixes

#### Critical: `tz_localize(None)` → `tz_convert(None)` — `machine_learning_files/merge_pipeline.py`
- **Problem:** Three locations in the pipeline called `.dt.tz_localize(None)` on timezone-aware Series (guarded by `if tz is not None`). On tz-aware data this raises `ValueError: Already tz-aware, use tz_convert to convert`.
- **Fix:** Replaced all three occurrences with `.dt.tz_convert(None)` which strips the timezone while preserving wall-clock times.
- **Affected functions:** `compute_event_features()`, `build_feature_store()` weather block, `make_splits()`.

#### Critical: `n_new` feature count always logged as 0 — `Processing/feature_engineering.py`
- **Problem:** `n_new = n_features - len(df.columns)` subtracts the column count from itself (both sides reference the enriched DataFrame), always yielding `0` and making the feature-count log line meaningless.
- **Fix:** Captured `n_orig_cols = len(df.columns)` before any feature engineering steps. Changed the calculation to `n_new = n_features - n_orig_cols` and updated the log message to include the delta (`+{n_new} new`).

#### Moderate: API parameter mismatch (`horizon_hours` on monthly data) — `machine_learning_files/api.py`
- **Problem:** `ForecastRequest` accepted `horizon_hours` (1–168) but the underlying data is monthly (`MS` frequency). `station_cache.head(horizon_hours)` treated an hour count as a month-row count — requesting `horizon_hours=24` silently returned 24 months (2 years) of forecasts.
- **Fix:** Renamed the field to `horizon_months` (range 1–24) in `ForecastRequest`, `ForecastResponse`, `_run_forecast()`, and all call sites.

### Notes
- No test suite exists in the repo; all fixes were verified by code inspection.
- Three additional lower-priority issues remain (bare `except Exception` handlers, DataFrame concat without index alignment, Chronos device default mismatch in docs) — tracked for future sessions.

