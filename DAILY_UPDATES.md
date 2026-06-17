# Daily Updates — Transit Demand Forecasting

---

## 2026-06-17

### Bug Fixes

**`models/chronos2/predict.py`**
- Fixed wrong import: `Chronos2Pipeline` → `ChronosPipeline`. The zero-shot fallback path would raise `ImportError` at runtime when the fine-tuned model is unavailable.

**`models/baselines/prophet_baseline.py`**
- Fixed `tz_localize(None)` called on a tz-aware `Timestamp` (raises `TypeError` at runtime). Replaced with a guard + `tz_convert(None)`.

**`evaluation/metrics.py`**
- Fixed truthiness-check bug in `MetricsReport.to_dict()`: `if self.mase`, `if self.coverage`, `if self.int_width` all evaluate to `False` when the metric is exactly `0.0`, causing the output dict to silently return `None` instead of `0.0`. Changed to `if self.mase is not None` (and same for coverage, int_width).

**`Processing/feature_engineering.py`**
- Fixed `is_rain_onset` groupby: passing `[True] * len(df)` as the groupby key when `station_id` is absent would silently produce wrong results. Replaced with explicit branch using `df["is_raining"].shift(1)` for the no-station-id case.
- Fixed dead variable `n_new = n_features - len(df.columns)` (always 0). Captured `n_input_features` before transformations and computed `n_new` correctly.

**`scripts/export_website_data.py`**
- Fixed `ts.tz_localize(None)` on a tz-aware `Timestamp` in `export_ridership_actuals`. Replaced with `ts.tz_convert(None)` guarded by `ts.tzinfo is not None`.

### Improvements

**`machine_learning_files/api.py`**
- Replaced deprecated `@app.on_event("startup")` with the modern `lifespan` context manager (FastAPI 0.93+).
- Replaced deprecated `datetime.utcnow()` with `datetime.now(timezone.utc)` (Python 3.12+ deprecation).

**`models/chronos2/predict.py`**
- Replaced deprecated `datetime.utcnow()` with `datetime.now(timezone.utc)`.
