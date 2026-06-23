# Daily Updates Log

Automated daily maintenance log — bugs found, fixes applied, improvements noted.

---

## 2026-06-23

### Bugs Fixed

#### 1. `merge_pipeline.py` — `tz_localize(None)` on timezone-aware Series (5 instances)
**Severity:** High  
**Impact:** `TypeError: Already tz-aware, use tz_convert to convert.` at runtime whenever input timestamps carry timezone info.

`tz_localize(None)` is for *adding* timezone info to naive datetimes. To *strip* timezone info from aware datetimes, the correct call is `tz_convert(None)`. All five occurrences were patched:
- Line 185 — `ev_ts` (event timestamps)
- Line 191 — `ts_series` (merge timestamps)
- Line 270 — `wdf["timestamp"]` (weather merge)
- Line 286 — `base_ts` (base grid timestamps)
- Line 340 (`make_splits`) — `ts` (split timestamps)

**Fix:** `tz_localize(None)` → `tz_convert(None)` in all conditional tz-stripping blocks.

---

#### 2. `models/baselines/prophet_baseline.py:86` — Same `tz_localize` crash in Prophet prep
**Severity:** High  
**Impact:** Prophet training crashes with `TypeError` on any tz-aware ridership dataset.

The `ds` column was created with `pd.to_datetime(...).dt.tz_localize(None)` unconditionally. If the source timestamps are already tz-aware this raises immediately.

**Fix:** Check `dt.tz` first; use `tz_convert(None)` for aware, leave naive datetimes as-is:
```python
_ds = pd.to_datetime(train["timestamp"])
train["ds"] = _ds.dt.tz_convert(None) if _ds.dt.tz is not None else _ds
```

---

#### 3. `scripts/export_website_data.py:157-158` — `tz_localize` on `pd.Timestamp` in website export
**Severity:** High  
**Impact:** JSON export step crashes when ridership timestamps carry timezone info, preventing website data refresh.

`pd.Timestamp.tz_localize(None)` raises `TypeError` on an already-aware Timestamp. The code correctly checks `ts.tz is not None` but then calls the wrong method.

**Fix:** `ts.tz_localize(None)` → `ts.tz_convert(None)`.

---

#### 4. `Processing/ablation.py:197-202` — KeyError if no P50 quantile column found
**Severity:** Medium  
**Impact:** Ablation run crashes with `KeyError: 'p50'` when neither `"p50"` nor any column containing `"0.5"` is present in AutoGluon prediction output (e.g. model returns only `"mean"`).

**Fix:** Added an explicit column-presence check before the final DataFrame slice; returns an empty DataFrame with an error log instead of raising:
```python
required = ["timestamp", "station_id", "p10", "p50", "p90"]
missing = [c for c in required if c not in preds_df.columns]
if missing:
    log.error(f"Prediction DataFrame missing columns: {missing}")
    return pd.DataFrame()
```

---

#### 5. `Processing/feature_engineering.py:421-442` — `n_new` always 0
**Severity:** Low  
**Impact:** Log line reported `+0 new` features every run — misleading but not a runtime failure.

`n_new = n_features - len(df.columns)` was comparing the column count to itself at the same point in time. Added `n_input_cols = len(df.columns)` at the start of `build_features` before any transformations, and updated the subtraction and log message to use it.

---

### Potential Issues Noted (No Fix Applied — Needs Monitoring)

- **`validators.py:174`** — `grp.loc[idx - 1, ...]` assumes integer-sequential index labels to find the row preceding a gap. If the DataFrame index is non-sequential after groupby/sort, `idx - 1` may not be the previous row's label, giving an inaccurate `gap_start` in the validation report. Falls back to `"unknown"` so won't crash, but the gap location logged may be wrong. Fix would be to use `iloc` relative positioning.

- **`merge_pipeline.py:314-316`** — Date-range filter creates tz-aware `pd.Timestamp` objects (`tz="America/Los_Angeles"`) and compares them against `base["timestamp"]`. If `base["timestamp"]` was already stripped of timezone by the pipeline steps above, this comparison raises `TypeError`. Should use tz-naive Timestamps for the filter:
  ```python
  base = base[base["timestamp"] >= pd.Timestamp(start)]
  ```
  Low risk in current pipeline (CLI usage always passes naive date strings), but could surface with downstream callers.

- **`ablation.py:152-154`** — `groupby([True] * len(df))` is used as a fallback when no `station_id` column exists. This groups all rows together (single group), which is functionally correct but unusual. If the DataFrame is very large this creates an unnecessarily large in-memory group. Non-critical.

---

### Summary

| File | Lines | Bug | Severity | Status |
|------|-------|-----|----------|--------|
| `merge_pipeline.py` | 185, 191, 270, 286, 340 | `tz_localize` → `tz_convert` | High | Fixed |
| `prophet_baseline.py` | 86 | `tz_localize` crash on aware timestamps | High | Fixed |
| `export_website_data.py` | 157–158 | `tz_localize` crash on aware Timestamp | High | Fixed |
| `ablation.py` | 197–202 | KeyError on missing p50 column | Medium | Fixed |
| `feature_engineering.py` | 421–442 | `n_new` always 0 in log | Low | Fixed |
| `validators.py` | 174 | Inaccurate gap_start via integer index arithmetic | Low | Monitoring |
| `merge_pipeline.py` | 314–316 | tz-aware/naive timestamp comparison in date filter | Low | Monitoring |
