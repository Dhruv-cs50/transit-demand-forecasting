# Daily Updates Log

---

## 2026-06-05

### Bugs Fixed

#### 1. Inverted sort guard in `Processing/feature_engineering.py` (line 140)
- **Bug:** `if df["timestamp"].is_monotonic_increasing: df = df.sort_values(...)` — the condition was backwards. The sort only ran when the data was *already* sorted, doing nothing; unsorted data was passed directly to rolling-window calculations, producing incorrect lag features.
- **Fix:** Changed to `if not df["timestamp"].is_monotonic_increasing`.

#### 2. Dead `n_new` variable in `Processing/feature_engineering.py` (lines 421, 442)
- **Bug:** `n_new = n_features - len(df.columns)` always evaluated to `0` because both sides referenced the same object after transformations.
- **Fix:** Captured `n_original = len(df.columns)` before the pipeline runs, then computed `n_new = n_features - n_original`. Updated the log message to emit `+{n_new} new` columns.

#### 3. Silent zero fallback for missing quantile columns in `machine_learning_files/api.py` (lines 141–143)
- **Bug:** The cached/fast path returned `0.0` when a quantile column was absent, while the slow (live-inference) path returned `float("nan")`. Zero is a valid ridership value, so clients could not distinguish "no forecast" from "forecast is zero".
- **Fix:** Changed the cached-path fallback to `float("nan")`, matching the slow path.

#### 4. Deprecated `@app.on_event("startup")` in `machine_learning_files/api.py` (line 214)
- **Bug:** `@app.on_event()` is deprecated since FastAPI 0.93 and will be removed in a future release.
- **Fix:** Replaced with an `@asynccontextmanager` lifespan function and passed it as `FastAPI(lifespan=lifespan)`.

---

### Improvements Noted (not yet implemented)

| Priority | File | Issue |
|----------|------|-------|
| High | `machine_learning_files/api.py` | CORS `allow_origins=["*"]` is open to any domain — restrict to known frontend origin once the production URL is stable. |
| Medium | `machine_learning_files/merge_pipeline.py` (lines 314–316) | Timezone normalization before date-range filtering is inconsistent; mixed tz-aware/naive timestamps can silently drop rows. |
| Medium | `machine_learning_files/api.py` / `machine_learning_files/merge_pipeline.py` | `load_model_config()` has no error handling — a missing `configs/model.yaml` produces a cryptic traceback. Add a `FileNotFoundError` guard with a human-readable hint. |
| Medium | `machine_learning_files/merge_pipeline.py` (lines ~178, 201, 210) | `float("nan")` used for missing event data may cause JSON serialization errors in the website export pipeline. Convert to `None` / `null` before serialising. |
| Medium | (all) | Zero test coverage across 21 Python files. At minimum, add unit tests for `merge_pipeline`, `validators`, and the API endpoints. |
| Low | `evaluation/validators.py` | Hardcoded anomaly-detection thresholds (`RIDERSHIP_MAX_PLAUSIBLE`, `RIDERSHIP_SPIKE_MULTIPLIER`, etc.) should be moved to `configs/model.yaml` for tunability. |
| Low | `machine_learning_files/api.py` | `load_model_config()` is called via `@lru_cache` but the cache is never invalidated. Fine for production; consider a reload endpoint for development iteration. |

---
