# Daily Updates Log

Automated daily audit log. Each entry records bugs fixed, improvements made, and any open issues surfaced during the daily review.

---

## 2026-06-16

### Bugs Fixed

#### 1. `Processing/feature_engineering.py` — `n_new` always 0 in log message
- **Bug**: `n_new = n_features - len(df.columns)` subtracted the same value from itself, always producing 0. The log line `"→ N total feature columns"` never reported how many new features were added.
- **Fix**: Capture `n_input_cols = len(df.columns)` before any transformations, then compute `n_new = n_features - n_input_cols`.

#### 2. `evaluation/validators.py` — Wrong column name in `check_event_coverage`
- **Bug**: `EVENT_COLS` listed `"is_sharks_game_window"` (the name used after `feature_engineering.py`), but the raw feature store produced by `merge_pipeline.py` uses `"is_sharks_game"`. The check silently reported "No event columns found" even when event data was present.
- **Fix**: Changed `"is_sharks_game_window"` → `"is_sharks_game"` in `EVENT_COLS`.

#### 3. `evaluation/validators.py` — Index offset bug in `check_missing_windows`
- **Bug**: After `sort_values("timestamp")`, the grouped DataFrame retained its original non-contiguous integer index. The code used `idx - 1` (where `idx` is a label from `.items()`) to look up the previous row, which fails whenever the index is non-contiguous, producing `"unknown"` for nearly all gap-start timestamps.
- **Fix**: Added `.reset_index(drop=True)` after `sort_values` so that positional arithmetic `pos - 1` is always safe, with a guard `if pos > 0`.

#### 4. `evaluation/validators.py` — Monthly gap threshold too lenient
- **Bug**: The exception handler for calendar-based offsets (`"MS"`) set `max_gap = pd.Timedelta(days=62)`. A skipped month creates a gap of ~59–62 days, which the `diffs > max_gap` condition would miss.
- **Fix**: Changed to `pd.Timedelta(days=35)`, which catches any single missing month while tolerating the natural variation in month lengths.

#### 5. `evaluation/validators.py` — `tz_localize(None)` crashes on tz-aware timestamps
- **Bug**: `check_station_coverage` called `.dt.tz_localize(None)` unconditionally. If the timestamp column is already tz-aware, pandas raises `TypeError: Already tz-aware, use tz_convert`.
- **Fix**: Check `.dt.tz` first and use `.dt.tz_convert(None)` for tz-aware columns, otherwise leave as-is.

#### 6. `machine_learning_files/merge_pipeline.py` — Timezone mismatch crashes date-range filter
- **Bug**: `build_feature_store` compared a tz-naive `base["timestamp"]` column against `pd.Timestamp(start, tz="America/Los_Angeles")` (tz-aware), raising `TypeError: Cannot compare tz-naive and tz-aware timestamps` whenever `--start` or `--end` args were passed.
- **Fix**: Normalize both sides to tz-naive before comparing, handling the case where the timestamp column might itself be tz-aware.

#### 7. `evaluation/metrics.py` — Wrong MASE seasonality for monthly BART data
- **Bug**: `mase()` defaulted to `seasonality=96` (96 × 15 min = 24 hr), inherited from a sub-hourly data design. The project uses monthly BART OD data, so the correct seasonal period is 12 (12 months = 1 year). Using 96 produced a meaningless scale derived from comparing rows that are 96 months (~8 years) apart.
- **Fix**: Changed default to `seasonality=12` with updated docstring.

#### 8. `evaluation/metrics.py` — MASE never computed due to threshold tied to old seasonality
- **Bug**: `_compute` only called `mase()` when `len(y_train) > 96`. With only ~24 months of training data, this condition was never true and MASE was silently skipped.
- **Fix**: Changed threshold to `len(y_train) > 12` (matching the corrected seasonality).

#### 9. `machine_learning_files/api.py` — Deprecated `datetime.utcnow()` on Python 3.12
- **Bug**: `datetime.utcnow()` is deprecated since Python 3.12 (the project's runtime). Produces a `DeprecationWarning` on every `/health` and `/forecast` response.
- **Fix**: Replaced with `datetime.now(timezone.utc)` and added `timezone` to the import.

#### 10. `machine_learning_files/api.py` — "Traffic" typo in API title and root response
- **Bug**: The FastAPI title and root endpoint declared `"Bay Area Traffic Forecast API"` instead of `"Bay Area Transit Forecast API"`.
- **Fix**: Corrected both occurrences to `"Transit"`.

### Files Changed
- `Processing/feature_engineering.py`
- `evaluation/validators.py`
- `machine_learning_files/merge_pipeline.py`
- `evaluation/metrics.py`
- `machine_learning_files/api.py`

### Open Issues (not fixed — require design discussion)
- `machine_learning_files/api.py`: The `horizon_hours` parameter (1–168 hours) is passed directly as a row limit (`station_cache.head(horizon_hours)`) to a cached forecast that is monthly-granularity. Requesting 24 "hours" returns up to 24 monthly rows — misleading to API consumers. Consider renaming the parameter or adding granularity documentation.
- `machine_learning_files/fetch_bart_od.py`: `YEAR_MONTH_FORMAT` dict (lines 40–44) is defined but never used. URL patterns are hardcoded in `build_url_candidates()` instead.
- `machine_learning_files/zero_shot.py`: `median_col = f"mean"` uses an `f`-string prefix with no interpolation variables (harmless but misleading).
- `machine_learning_files/api.py`: `@app.on_event("startup")` is deprecated in recent FastAPI versions. Should be migrated to a lifespan context manager.

---
