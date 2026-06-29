# Daily Updates Log

---

## 2026-06-29

### Bug Fixes

**Critical — would cause runtime errors:**

1. **`models/chronos2/predict.py`** — Wrong Chronos class name in zero-shot fallback  
   `Chronos2Pipeline` does not exist in `chronos-forecasting` 1.x; the correct class is `ChronosPipeline` (consistent with `api.py` and `zero_shot.py`). This caused an `ImportError` whenever the fine-tuned model was absent and the code fell back to zero-shot inference.

2. **`models/baselines/scheduler.py`** — Three wrong module import paths (all `ModuleNotFoundError`)  
   - `from ingestion.fetch_weather_openmeteo import ...` → `from machine_learning_files.fetch_weather_openmeteo import ...`  
   - `from ingestion.fetch_events import fetch_all` → `from machine_learning_files.fetch_events import fetch_all`  
   - `from processing.validators import validate_feature_store, ValidationMode` → `from evaluation.validators import validate_feature_store, ValidationMode`  
   The `ingestion/` and `processing/` packages don't exist at these paths; `fetch_weather_openmeteo.py` and `fetch_events.py` live under `machine_learning_files/`, and `validators.py` lives under `evaluation/`. All three inline steps in the nightly scheduler were broken.

3. **`machine_learning_files/merge_pipeline.py`** — Timezone mismatch in date-range filter  
   `build_feature_store()` compared the tz-naive `base["timestamp"]` column against tz-aware `pd.Timestamp(start, tz="America/Los_Angeles")` values, raising `TypeError: Cannot compare tz-naive and tz-aware timestamps`. Fixed by stripping timezone from the filter boundaries before comparison, consistent with how the rest of the function handles timestamps.

**Non-critical — silent bugs or deprecations:**

4. **`Processing/feature_engineering.py`** — Dead code in `build_features()`  
   `n_new = n_features - len(df.columns)` always evaluates to 0 (subtracts a variable from itself) and was never logged or used. Removed the dead assignment.

5. **`machine_learning_files/api.py`** — Deprecated `@app.on_event("startup")`  
   Replaced with the `lifespan` context manager pattern (FastAPI ≥0.95 recommendation). The old form still works but emits deprecation warnings in FastAPI 0.110+.

6. **`machine_learning_files/api.py`** — `datetime.utcnow()` deprecated in Python 3.12  
   Both usages (in `/health` and `/forecast`) replaced with `datetime.now(timezone.utc)`.

7. **`machine_learning_files/zero_shot.py`** — Incorrect module path in docstring  
   Docstring said `models/chronos2/zero_shot.py`; actual path is `machine_learning_files/zero_shot.py`.

### Files Changed
- `models/chronos2/predict.py`
- `models/baselines/scheduler.py`
- `machine_learning_files/merge_pipeline.py`
- `Processing/feature_engineering.py`
- `machine_learning_files/api.py`
- `machine_learning_files/zero_shot.py`
- `DAILY_UPDATES.md` (created)
