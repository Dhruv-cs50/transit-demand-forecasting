# Daily Updates

A running log of automated daily checks, bug fixes, and improvements.

---

## 2026-06-21

### Bugs Fixed

#### 1. Timezone stripping logic — `machine_learning_files/merge_pipeline.py`
**Severity:** High

Four call sites used `tz_localize(None)` on timezone-aware Series, which raises `TypeError` at runtime (`tz_localize` attaches a timezone to naive data; `tz_convert` strips it from aware data).

Changed to `tz_convert(None)` at all four locations:
- Line 185: `ev_ts` (events timestamp)
- Line 191: `ts_series` (transit timestamps)
- Line 270: `wdf["timestamp"]` (weather data)
- Line 286: `base_ts` (base transit data)

#### 2. Feature count always reported as 0 — `Processing/feature_engineering.py`
**Severity:** Medium

In `build_features()`, `n_new` was computed as `len(df.columns) - len(df.columns)`, which is always 0. Added `n_original = len(df.columns)` before feature engineering runs and used it in the final log line, which now correctly reports how many columns were added.

#### 3. Bare `except:` clauses — `transit_eda/notebooks/eda_complete.py`
**Severity:** Low

Three bare `except:` blocks silently swallowed all exception types including `KeyboardInterrupt` and `SystemExit`. Replaced with `except (ValueError, TypeError):` at all three sites (two in matrix cell parsing, one in filename-to-month parsing).

### No regressions observed in other modules.
