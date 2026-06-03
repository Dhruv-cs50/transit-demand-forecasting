# Daily Updates — Transit Demand Forecasting

---

## 2026-06-03

### Bug Fixes

**`Processing/feature_engineering.py`**
- **Critical fix**: Reversed the monotonic-sort guard in `add_weather_features`. The condition was `if df["timestamp"].is_monotonic_increasing: sort(...)`, which sorted only when already sorted and left unsorted data untouched. Rolling precipitation windows (3hr, 6hr, 24hr) were therefore computed on arbitrarily ordered rows for any unsorted input. Corrected to `if not df["timestamp"].is_monotonic_increasing`.
- **Dead-code fix**: `n_new` in `build_features` was computed as `len(df.columns) - len(df.columns)`, always 0. Added `n_input_cols` capture at function entry and use it to report the actual number of columns added by the pipeline.

**`evaluation/validators.py`**
- **Index arithmetic fix** in `check_missing_windows`: the gap-start timestamp lookup used `grp.loc[idx - 1, ...]`, assuming a contiguous integer index that is not guaranteed after `groupby`. Replaced with positional lookup via `grp.index.get_loc(idx)` + `grp.iloc[pos - 1]`.

**`machine_learning_files/api.py`**
- **Inconsistent fallback fix** in `_run_forecast` fast path: missing quantile columns fell back to `0.0` while the slow path fell back to `float("nan")`. Aligned both to `float("nan")` and added a `log.warning` when any quantile column is absent from the cached forecast file.

**`transit_eda/notebooks/eda_complete.py`**
- Replaced three bare `except:` clauses with `except (ValueError, TypeError):` (matrix cell coercion) and `except (ValueError, IndexError):` (filename month parse). Bare excepts silently swallow `KeyboardInterrupt` and `SystemExit`, making the notebook hard to interrupt and masking real errors.

### Open Issues (not yet fixed)

| Priority | File | Issue |
|----------|------|-------|
| High | `merge_pipeline.py:300` | Silent NaN rows if `event_features` length differs from `base` after timezone issues — add length assertion before concat |
| High | `machine_learning_files/zero_shot.py:129-130` | No covariate column alignment check — missing weather for a station silently produces partial covariate sets |
| Medium | `merge_pipeline.py:289` | Left-join weather leaves large NaN blocks with no threshold warning |
| Medium | `feature_engineering.py:304-309` | `HUB_STATIONS` and `DIRIDON_LAT/LNG` hardcoded — should live in `configs/sources.yaml` |
| Medium | `configs/sources.yaml` | Placeholder API keys for 511 and Ticketmaster still present |
| Low | `machine_learning_files/fetch_bart_od.py` | No retry logic on HTTP download failures |

---
