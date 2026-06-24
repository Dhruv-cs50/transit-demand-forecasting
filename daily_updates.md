# Daily Updates — Transit Demand Forecasting

---

## 2026-06-24

### Bug Fixes

**1. `Processing/feature_engineering.py` — `n_new` always reported as 0**
- `n_new = n_features - len(df.columns)` was computing zero because both operands referred to the post-transformation column count. Added `n_input_cols = len(df.columns)` before transformations start and used it in the diff. The log message now correctly reports how many columns were added.

**2. `machine_learning_files/merge_pipeline.py` — tz-aware vs tz-naive timestamp comparison crash**
- The `--start` / `--end` date range filter compared the tz-naive `base["timestamp"]` column against `pd.Timestamp(..., tz="America/Los_Angeles")` (tz-aware). This raises `TypeError: Cannot compare tz-naive and tz-aware datetime-like objects` whenever CLI flags are used. Fixed by dropping the explicit timezone from the filter timestamp so both sides are tz-naive.

**3. `machine_learning_files/fetch_events.py` — `is_playoff` always `False`**
- The NHL API returns `gameType` as an integer (1=preseason, 2=regular, 3=playoff), but the code compared it to the string `"3"`. Changed to `pd.to_numeric(..., errors="coerce").eq(3)` to handle both integer and missing/empty values correctly.

**4. `machine_learning_files/zero_shot.py` — spurious f-string**
- `f"mean"` contained no interpolation and was unnecessarily wrapping a plain string literal. Changed to `"mean"`.

**5. `machine_learning_files/api.py` — deprecated `@app.on_event("startup")`**
- FastAPI deprecated the `on_event` decorator in favour of the `lifespan` context manager (introduced in v0.93). Replaced the startup handler with an `@asynccontextmanager` lifespan function passed to the `FastAPI()` constructor to suppress deprecation warnings and align with the current recommended pattern.

**6. `machine_learning_files/fetch_bart_od.py` — dead code removed**
- `YEAR_MONTH_FORMAT` was a dict defined at module level but never referenced anywhere in the file. URL construction happens entirely inside `build_url_candidates()`. Removed the dead dict to reduce confusion.

**7. `models/baselines/benchmarks.py` — zero-shot and fine-tuned benchmarks used the same `Predictor` singleton**
- `Predictor` is a singleton that calls `_load_finetuned()` first inside `_ensure_loaded()`. When fine-tuned weights exist, both the "Chronos-2 zero-shot" benchmark (#4) and the "AutoGluon fine-tuned" benchmark (#5) were calling the same model, producing identical results in the leaderboard.
- Fixed by having benchmark #4 import and call `machine_learning_files.zero_shot.forecast_all_stations` (the raw zero-shot module) directly, which bypasses the `Predictor` singleton and guarantees Chronos zero-shot inference. Benchmark #5 still uses `Predictor()` which correctly loads fine-tuned weights when available.

### Improvements Identified (not yet implemented)

- **`models/chronos2/predict.py:219`** — `_naive_forecast` adds `np.random.normal()` noise, making results non-deterministic across calls. Consider seeding or removing noise for reproducibility in evaluation.
- **`models/baselines/benchmarks.py` docstring** — file docstring at top says `evaluation/benchmarks.py` but the actual path is `models/baselines/benchmarks.py`.
- **`machine_learning_files/api.py`** — `horizon_hours` in `ForecastRequest` is described as "hours" but the underlying data is monthly. The `head(horizon_hours)` in the cached-forecast fast path is semantically mismatched (24 hours vs 6 monthly rows). Consider renaming to `horizon_steps` or adding a note about granularity mismatch.
- **No automated test suite** — the project has no pytest/unittest tests. Adding smoke tests for the core pipeline functions (feature engineering, merge pipeline, metrics) would catch future regressions earlier.

