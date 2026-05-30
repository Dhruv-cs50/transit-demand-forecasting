# Daily Updates

---

## 2026-05-30

### Bug Fixes

**`machine_learning_files/merge_pipeline.py`**
- **Line 185** — `compute_event_features()`: Changed `ev_ts.dt.tz_localize(None)` → `ev_ts.dt.tz_convert(None)`. Calling `tz_localize(None)` on an already timezone-aware Series raises a `TypeError`; `tz_convert(None)` is the correct call to strip timezone info.
- **Lines 313–316** — `build_feature_store()`: Fixed the `--start` / `--end` date range filter. The comparison was mixing a tz-naive `base["timestamp"]` column with a tz-aware `pd.Timestamp(..., tz="America/Los_Angeles")`, which raises `TypeError: Cannot compare tz-naive and tz-aware`. Both sides are now normalized to tz-naive before comparison.

**`Processing/feature_engineering.py`**
- **Line 442** — `build_features()`: Removed the dead assignment `n_new = n_features - len(df.columns)`. The expression always evaluates to 0 because `n_features` was set from `len(df.columns)` one line earlier. The variable was never used in the log message.

**`evaluation/validators.py`**
- **Line 174** — `check_missing_windows()`: Fixed a potential `KeyError` when retrieving the gap-start timestamp. The previous code used `grp.loc[idx - 1, "timestamp"]`, assuming label `idx - 1` exists in the group's index. After `sort_values()`, the index labels are arbitrary (original DataFrame row numbers), so `idx - 1` is often missing. Replaced with positional lookup: `grp.iloc[pos - 1]` where `pos = grp.index.get_loc(idx)`.

**`scripts/export_website_data.py`**
- **Lines 157–158** — `export_ridership_actuals()`: Changed `ts.tz_localize(None)` → `ts.tz_convert(None)` for tz-aware `pd.Timestamp` scalars. Also replaced the fragile `hasattr(ts, "tz")` check with the standard `ts.tzinfo is not None`.

**`machine_learning_files/api.py`**
- **Lines 214–221** — Replaced the deprecated `@app.on_event("startup")` decorator (removed in FastAPI 0.109+) with the recommended `@asynccontextmanager lifespan` pattern, passed to `FastAPI(lifespan=lifespan)`.

### Summary

| File | Issue | Fix |
|---|---|---|
| `merge_pipeline.py` | `tz_localize` on tz-aware Series crashes | → `tz_convert(None)` |
| `merge_pipeline.py` | tz-naive vs tz-aware date comparison crashes | Normalize both sides to tz-naive |
| `feature_engineering.py` | `n_new` always 0, dead code | Removed |
| `validators.py` | `loc[idx-1]` KeyError on arbitrary index | → positional `iloc` lookup |
| `export_website_data.py` | `tz_localize` on tz-aware Timestamp crashes | → `tz_convert(None)` + correct guard |
| `api.py` | Deprecated `@app.on_event("startup")` | → `lifespan` context manager |
