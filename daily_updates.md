# Daily Updates — Transit Demand Forecasting

---

## 2026-06-19

### Bug Fixes

**1. Timezone mismatch crash in `merge_pipeline.py` (line 313–316)**
- **File:** `machine_learning_files/merge_pipeline.py`
- **Severity:** High — would raise `TypeError: Cannot compare tz-naive and tz-aware timestamps` in pandas 2.0+ whenever `--start` or `--end` args are passed to the pipeline CLI.
- **Root cause:** `base["timestamp"]` is tz-naive (parsed from BART OD period strings via `pd.to_datetime`), but the date filter was constructing tz-aware `pd.Timestamp(..., tz="America/Los_Angeles")` comparison values.
- **Fix:** Removed `tz=` from the filter Timestamps so both sides of the comparison are tz-naive.

**2. Deprecated FastAPI lifespan hook in `api.py` (line 214)**
- **File:** `machine_learning_files/api.py`
- **Severity:** Medium — `@app.on_event("startup")` is deprecated since FastAPI 0.93 and removed in 0.115+. Would fail silently or raise a deprecation warning in newer versions.
- **Fix:** Replaced with the `@asynccontextmanager` lifespan pattern; passed as `lifespan=lifespan` to the `FastAPI()` constructor.

**3. Latent `KeyError: 'forecast_horizon_hours'` in `zero_shot.py`**
- **File:** `machine_learning_files/zero_shot.py`
- **Severity:** Medium — dead code path that would crash if `forecast_horizon_steps` is ever removed from `configs/model.yaml`. Config has `forecast_horizon_steps` but the fallback branch referenced the non-existent key `forecast_horizon_hours`.
- **Fix:** Fallback now reads `cfg["data"].get("forecast_horizon_steps", 6)` consistently.

**4. Latent `KeyError: 'forecast_horizon_hours'` / `'context_length_hours'` in `finetune.py`**
- **File:** `models/chronos2/finetune.py`
- **Severity:** Medium — same dead-code fallback issue. `cfg["data"]["forecast_horizon_hours"]` and `cfg["data"]["context_length_hours"]` don't exist in the config; both keys are `*_steps` variants.
- **Fix:** Dead-code branch now uses `cfg["data"].get("forecast_horizon_steps", 6)` and `cfg["data"].get("context_length_steps", 24)`.

**5. Cleanup: removed stale `context_length_hours` references in `zero_shot.py`**
- Two call sites passed `cfg["data"].get("context_length_hours")` (always `None`) as `context_hours` to `prepare_context()`. Since `context_steps` is always resolved and takes priority, this was harmless but confusing. Replaced with explicit `None` and added clarifying comment.

---

### Known Issues (not yet fixed)

| Issue | File | Severity | Notes |
|-------|------|----------|-------|
| No test suite | entire codebase | High | Zero pytest/unittest files; regressions go undetected |
| CORS wildcard in production | `api.py` | Medium | `allow_origins=["*"]` should be restricted to known domains |
| Silent weather NaN merge | `merge_pipeline.py` | Medium | Left-join with weather produces all-NaN rows without warning |
| Hard-coded station mapping | `export_website_data.py` | Medium | `BART_CODE_TO_WEBSITE_ID` dict must be manually updated if BART adds stations |
| NaN propagation in lag features | `feature_engineering.py` | Medium | First N rows per station have NaN lags; AutoGluon silently drops or interpolates |
| No cache-expiry on forecast parquet | `api.py` | Low | Pre-computed forecasts are served indefinitely until container redeploy |
| Unpinned dependencies | `requirements.txt` | Low | `>=` versions could introduce breaking changes; pin with `==` for production |

---
