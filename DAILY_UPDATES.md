# Daily Updates — Transit Demand Forecasting

---

## 2026-06-13

### Bug Fixes

**1. `Processing/feature_engineering.py` — Logic bug: `n_new` always 0 (line 442)**
- `n_new = n_features - len(df.columns)` subtracted a value from itself, always yielding 0.
- Fixed by capturing input column count (`n_cols_input`) before feature engineering begins, then computing `n_new = n_features - n_cols_input`.
- Log message now correctly reports `+N new` features added.

**2. `machine_learning_files/merge_pipeline.py` — Double timestamp parse in `_ts` (line 342)**
- `pd.Timestamp(s)` was called twice on the same input in the conditional expression.
- Fixed by parsing once into a local variable before branching on `tzinfo`.

**3. `machine_learning_files/api.py` — Internal exception details leaked to API clients (line 247)**
- `raise HTTPException(status_code=500, detail=str(e))` exposed raw Python exception messages to callers.
- Fixed by returning generic client-safe messages (`"Internal forecast error"`, `"Station not found or invalid parameters"`) while still logging the full exception server-side.

**4. `machine_learning_files/fetch_weather_openmeteo.py` — Incomplete empty-data guard (line 151)**
- Guard only checked `if not hourly` but not whether the `"time"` key was present, meaning a dict with only metadata keys would slip through.
- Fixed to also validate `hourly.get("time")` and include coordinates in the error message.

### Code Quality Issues Identified (not yet fixed)

- `merge_pipeline.py` line 109: `ridership / 22` — magic number for weekdays/month; should be a named constant.
- `models/baselines/benchmarks.py` lines 88, 70: hardcoded P10/P90 ratio multipliers and `nanos` division without null guard.
- `evaluation/metrics.py`: no bounds checking before `mape`/`wape` computation on near-zero arrays.
- `machine_learning_files/api.py`: global mutable `_pipeline` / `_feature_store` state; consider dependency injection.
- No pytest test suite exists; metric functions and validators have no automated coverage.

---
