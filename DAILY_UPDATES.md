# Daily Updates — Transit Demand Forecasting

---

## 2026-06-12

### Bug Fixes

**1. Critical: `feature_engineering.py` — `datetime.date` + `pd.Timedelta` TypeError**
- **File**: `Processing/feature_engineering.py:103`
- **Problem**: `lambda d: (d + pd.Timedelta(days=1)) in CA_HOLIDAYS` — `d` is a `datetime.date` object, and `pd.Timedelta` cannot be added to it directly; this raises `TypeError` at runtime.
- **Fix**: Wrapped `d` in `pd.Timestamp()` before addition and called `.date()` on the result:
  ```python
  lambda d: (pd.Timestamp(d) + pd.Timedelta(days=1)).date() in CA_HOLIDAYS
  ```

**2. High: `api.py` — `context_length_hours` missing from config, passes `None` to `prepare_context()`**
- **File**: `machine_learning_files/api.py:169`
- **Problem**: `cfg["data"].get("context_length_hours")` returns `None` because the key does not exist in `configs/model.yaml`. If `context_steps` is ever `None`, line 99 of `zero_shot.py` would crash with `TypeError: unsupported operand type(s) for -: 'Timestamp' and 'NoneType'`.
- **Fix**: Added a safe default of 720 hours (30 days): `.get("context_length_hours", 720)`

**3. Medium: `api.py` — Timezone mismatch between `as_of` paths**
- **File**: `machine_learning_files/api.py:158-162`
- **Problem**: When `as_of` was provided as a string it was localized to `America/Los_Angeles` (tz-aware), but when taken from `station_df["timestamp"].max()` it was tz-naive. This inconsistency could cause comparison failures or silent incorrect filtering in `prepare_context()`.
- **Fix**: Both paths now produce a tz-naive timestamp. The `as_of` string path uses `pd.Timestamp(as_of).tz_localize(None)`, and the max-timestamp path strips any tz info with an explicit check.

### Improvements Identified (not yet implemented)

- **Inconsistent timezone handling** across `merge_pipeline.py`, `validators.py`, and `feature_engineering.py` — a shared `normalize_timestamp()` utility would prevent future issues.
- **Silent NaN in quantile column detection** (`api.py:190-192`) — if quantile columns are missing from prediction output, the API silently returns `nan` instead of raising a diagnostic error.
- **Incomplete BART station mapping** in `scripts/export_website_data.py` — stations `AS, EP, ML, NC, OA, SH, WC, WP, WS` are not mapped and are silently skipped during website export.
- **No API key validation at startup** — `configs/sources.yaml` contains placeholder keys; missing keys should be caught early with a clear error message.
- **No automated test suite** — the codebase has no unit or integration tests; regressions are only caught by manual validation runs.
- **Python 3.11 lock** — AutoGluon/Chronos dependency conflicts block Python 3.12+; this is a long-term maintenance risk.

---
