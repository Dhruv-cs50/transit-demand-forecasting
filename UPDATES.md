# Daily Updates Log

---

## 2026-06-20

### Bug Fixes

**`Processing/feature_engineering.py`**
- Fixed `n_new` counter in `build_features()` — was always `0` because it subtracted `len(df.columns)` from itself. Now correctly captures `n_input_cols` before transformations begin so the log line reports actual new features added.
- Fixed `is_rain_onset` computation when `station_id` column is absent. Previously used `groupby([True] * len(df))` as a fallback key, which is error-prone and relies on undocumented pandas behavior. Now uses a plain `.shift(1)` on the column directly when no `station_id` is present.

**`machine_learning_files/api.py`**
- Replaced deprecated `@app.on_event("startup")` (removed in FastAPI 0.103+) with the recommended `lifespan` async context manager. Required adding `from contextlib import asynccontextmanager`.
- Replaced `datetime.utcnow()` (deprecated in Python 3.12) with `datetime.now(timezone.utc)` throughout. Added `timezone` to the `datetime` import.

**`models/chronos2/predict.py`**
- Replaced `datetime.utcnow()` with `datetime.now(timezone.utc)` to match Python 3.12+ best practices.

**`models/baselines/arima.py`**
- Fixed `fit_auto_arima()` using wrong seasonal period for monthly data. Was defaulting to `s=96` (designed for 15-min data) when `"h"` was not in the frequency string. Monthly data (`"MS"`) now correctly uses `s=12` (annual cycle). Hourly data uses `s=24`, 15-min data uses `s=96`.

**`machine_learning_files/merge_pipeline.py`**
- Fixed potential `TypeError` in the date range filter when `base["timestamp"]` is timezone-naive but the filter boundary was always created as timezone-aware (`tz="America/Los_Angeles"`). Now inspects the column's timezone at runtime and strips tz from the boundary when the column is tz-naive.

**`machine_learning_files/zero_shot.py`**
- Fixed incorrect module path in the docstring header (said `models/chronos2/zero_shot.py`; correct path is `machine_learning_files/zero_shot.py`).

### Improvements Made
- All `datetime.utcnow()` calls migrated to `datetime.now(timezone.utc)` — no silent incorrect UTC timestamps on systems with non-UTC local time.
- FastAPI lifespan approach is forward-compatible and avoids deprecation warnings in server logs.
- `build_features()` log output now shows a meaningful `+N new` count instead of `+0 new`.
