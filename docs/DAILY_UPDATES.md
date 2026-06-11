# Daily Updates Log

A running changelog of bugs fixed and improvements made each session.

---

## 2026-06-11

### Bugs Fixed

| # | File | Line(s) | Severity | Description |
|---|------|---------|----------|-------------|
| 1 | `Processing/feature_engineering.py` | 421–443 | HIGH | `n_new` was always 0 because it subtracted `len(df.columns)` from itself. Captured `n_input_cols` before transformations so the log now reports `+N new` columns correctly. |
| 2 | `machine_learning_files/fetch_events.py` | 187 | MEDIUM | `ev.get("classifications", [{}])[0]` raises `IndexError` when the API returns an empty list. Changed to safe two-step extraction. |
| 3 | `machine_learning_files/fetch_weather_openmeteo.py` | 169–174 | LOW | `int(c)` inside `.map()` raises `ValueError` when `weather_code` contains `NaN`. Extracted a `_decode_weather` helper with an explicit `pd.isna` guard. |
| 4 | `machine_learning_files/api.py` | 136–146 | MEDIUM | When cached forecast columns didn't match expected quantile names, code silently returned `p10/p50/p90 = 0.0`. Now logs a warning and falls through to live Chronos inference instead. |
| 5 | `machine_learning_files/zero_shot.py` | 199–202 | LOW | Fallback to `pred_df.columns[-1]` when no median column found could return an arbitrary column. Changed to raise a `ValueError` with the actual column list so failures are explicit. |
| 6 | `models/chronos2/predict.py` | 447–451 | MEDIUM | `future_row.iloc[0].get(...)` called `.get()` on a `pd.Series` (works but semantically wrong), and the `is_raining` block used `.iloc[0]` on an unguarded filtered frame. Refactored to cache the `future_rows` slice, guard with `.empty`, and access columns directly. |

### Improvements Identified (not yet implemented)

- **Auto-detect inference device** (`configs/model.yaml`): device is hardcoded to `cpu`; should fall back to MPS or CUDA when available.
- **Timezone consistency**: tz-aware/tz-naive datetimes are mixed across `merge_pipeline.py`, `api.py`, and `fetch_events.py`. Standardise on `America/Los_Angeles` tz-aware everywhere.
- **`hours_to_event` column mis-use** (`merge_pipeline.py:208`): field stores event *count* for the month, not hours until event. Should be renamed `game_count` to avoid confusion.
- **Config schema validation**: `configs/model.yaml` and `configs/sources.yaml` have no type-checking. A wrong value type (e.g. `train_end` as int) silently produces wrong behaviour. Consider `pydantic` validation on load.
- **Prophet seasonality check** (`models/baselines/prophet_baseline.py:111`): consecutive-month check assumes no gaps; missing months break the assumption.
- **No retry on cache miss in API** (`machine_learning_files/api.py`): if the newest cached file is corrupt/empty, older files are not tried. Should iterate in reverse-chronological order before falling back to live inference.

---

*This file is updated each session. Append new entries at the top under a fresh `## YYYY-MM-DD` heading.*
